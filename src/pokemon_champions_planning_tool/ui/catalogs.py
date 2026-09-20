"""Startup catalogue caches shared by views: Champions species, megas, items.

Loaded once per session in a single database session, then held on the context.
Records from these repositories are expunged by the repositories themselves, so they
are safe to keep after the session closes. Replace the instance (not its contents)
after a catalogue sync; stores re-read ``ctx.catalogs`` on their next load.
"""

from __future__ import annotations

from collections.abc import Callable
from contextlib import AbstractContextManager
from dataclasses import dataclass, field
from functools import cached_property

from sqlmodel import Session

from ..infrastructure.database.database import get_session
from ..infrastructure.database.models import ChampionsSpeciesRecord, ItemRecord, MegaEvolutionRecord
from ..infrastructure.database.repositories import ChampionsCatalogRepository, MegaEvolutionRepository
from ..domain.moves import MoveInfo, move_key, resolve_learnset_key
from ..services.items_catalog_service import load_items_catalog
from ..services.move_catalog_service import load_move_catalog
from ..services.species_catalog_service import load_species_catalog
from ..domain.species import SpeciesInfo, resolve_species_key

SessionFactory = Callable[[], AbstractContextManager[Session]]


from ..domain.pokemon_identity import format_api_name, format_display_name, qualified_name


@dataclass(frozen=True)
class SpeciesSuggestion:
    display_name: str
    species_name: str
    canonical_id: str = ""


@dataclass(frozen=True)
class Catalogs:
    champions: tuple[ChampionsSpeciesRecord, ...] = ()
    megas: tuple[MegaEvolutionRecord, ...] = ()
    items_by_id: dict[str, ItemRecord] = field(default_factory=dict)
    champions_items: tuple[ItemRecord, ...] = ()
    mega_stone_map: dict[str, list[ItemRecord]] = field(default_factory=dict)
    moves_by_id: dict[str, MoveInfo] = field(default_factory=dict)
    learnsets: dict[str, frozenset[str]] = field(default_factory=dict)   # Showdown species key -> move ids
    species_by_canonical: dict[str, SpeciesInfo] = field(default_factory=dict)   # base stats/abilities/weight for every species and form

    # -- species catalogue (damage calculator) --------------------------------------------

    @property
    def has_species(self) -> bool:
        return bool(self.species_by_canonical)

    def species_for(self, canonical_id: str | None) -> SpeciesInfo | None:
        """Catalogue entry for one of our ids (megas and forms are their own rows)."""
        key = resolve_species_key(canonical_id, self.species_by_canonical)
        return self.species_by_canonical.get(key) if key else None

    @cached_property
    def _search_pool(self) -> tuple[tuple[str, SpeciesInfo], ...]:
        """(lowercased calculator name, species) for every catalogue entry, built once."""
        return tuple(
            (s.name.lower(), s)
            for s in sorted(self.species_by_canonical.values(), key=lambda s: (len(s.name), s.name))
        )

    def search_species(self, query: str, limit: int = 8, *, legal_only: bool = True) -> list[SpeciesInfo]:
        """Prefix matches first, then contains, on the calculator names; megas included."""
        q = query.strip().lower()
        if len(q) < 2:
            return []
        # The pool is pre-sorted, so the two passes keep their (length, name) order without
        # re-sorting the whole catalogue on every keystroke.
        starts: list[SpeciesInfo] = []
        contains: list[SpeciesInfo] = []
        for lowered, s in self._search_pool:
            if not (s.is_legal or not legal_only):
                continue
            if lowered.startswith(q):
                starts.append(s)
                if len(starts) >= limit:
                    return starts[:limit]
            elif len(contains) < limit and q in lowered:
                contains.append(s)
        return (starts + contains)[:limit]

    # -- moves --------------------------------------------------------------------------------

    @property
    def has_moves(self) -> bool:
        return bool(self.moves_by_id) and bool(self.learnsets)

    def learnset_key(self, canonical_id: str | None) -> str | None:
        """Learnset for a species; Mega forms use their base species'."""
        return resolve_learnset_key(canonical_id, self.learnsets)

    def legal_move_ids(self, canonical_id: str | None) -> frozenset[str] | None:
        key = self.learnset_key(canonical_id)
        return self.learnsets.get(key) if key else None

    @cached_property
    def legal_moves_sorted(self) -> tuple[MoveInfo, ...]:
        """Every Champions-legal move, ordered by name — the picker's base list."""
        return tuple(sorted((m for m in self.moves_by_id.values() if m.is_legal), key=lambda m: m.name.lower()))

    def move_by_name(self, name: str | None) -> MoveInfo | None:
        return self.moves_by_id.get(move_key(name))

    def move_legality(self, canonical_id: str | None, name: str | None) -> bool | None:
        """True/False when the catalogue can judge, None when it has no learnset for the species."""
        if not name or not name.strip():
            return None
        legal = self.legal_move_ids(canonical_id)
        if legal is None:
            return None
        info = self.move_by_name(name)
        if info is not None and not info.is_legal:
            return False
        return move_key(name) in legal

    # -- derived lookups ----------------------------------------------------------------

    @cached_property
    def champions_names(self) -> list[str]:
        return [r.display_name for r in self.champions]

    @cached_property
    def champions_species_names(self) -> set[str]:
        return {r.species_name.lower() for r in self.champions if r.species_name}

    @cached_property
    def mega_species(self) -> frozenset[str]:
        return frozenset(m.species_name.lower() for m in self.megas if m.species_name)

    @cached_property
    def _megas_by_species(self) -> dict[str, list[MegaEvolutionRecord]]:
        index: dict[str, list[MegaEvolutionRecord]] = {}
        for m in self.megas:
            index.setdefault((m.species_name or "").lower(), []).append(m)
        return index

    def megas_for(self, species_name: str | None) -> list[MegaEvolutionRecord]:
        return list(self._megas_by_species.get((species_name or "").lower(), ()))

    @cached_property
    def _mega_forms_by_base(self) -> dict[str, list[SpeciesInfo]]:
        """Base species id -> its Mega entries in the species catalogue."""
        index: dict[str, list[SpeciesInfo]] = {}
        for s in self.species_by_canonical.values():
            if s.is_mega:
                index.setdefault(s.base_species_id, []).append(s)
        return index

    @cached_property
    def _mega_form_by_stone(self) -> dict[tuple[str, str], str]:
        """(base species id, lowercased stone name) -> the mega form that stone unlocks."""
        index: dict[tuple[str, str], str] = {}
        for base_id, forms in self._mega_forms_by_base.items():
            for s in forms:
                if s.required_item:
                    index.setdefault((base_id, s.required_item.strip().lower()), s.canonical_id)
        return index

    def form_choices_for(self, canonical_id: str | None) -> list[tuple[str, str]]:
        """List of (canonical_id, label) for a species and its mega forms.

        Returns empty list if the species has no mega evolutions.
        If it has mega evolutions, the first entry is always the base form ('Base').
        """
        species = self.species_for(canonical_id)
        if species is None:
            return []
        base_species = self.species_for(species.base_species_id) or species
        megas = self.megas_for(base_species.name)
        if not megas:
            mega_species_list = self._mega_forms_by_base.get(base_species.canonical_id, [])
            if not mega_species_list:
                return []
            out = [(base_species.canonical_id, "Base")]
            for s in mega_species_list:
                lbl = s.name.replace(base_species.name, "").replace("-", " ").strip()
                lbl = " ".join(lbl.split()) if lbl else "Mega"
                out.append((s.canonical_id, lbl))
            return out

        out = [(base_species.canonical_id, "Base")]
        for m in megas:
            lbl = m.display_name.replace(base_species.name, "").replace("-", " ").strip()
            lbl = " ".join(lbl.split()) if lbl else "Mega"
            out.append((m.canonical_id, lbl))
        return out

    def mega_for_item(self, species_canonical_id: str | None, item_name: str | None) -> str | None:
        """If item_name is a Mega Stone for this species (base or mega), return the mega form canonical id."""
        if not species_canonical_id or not item_name:
            return None
        species = self.species_for(species_canonical_id)
        if species is None:
            return None
        return self._mega_form_by_stone.get((species.base_species_id, item_name.strip().lower()))

    @cached_property
    def items_by_name(self) -> dict[str, ItemRecord]:
        return {r.display_name.lower(): r for r in self.items_by_id.values()}

    def item_for(self, reference: str | None) -> ItemRecord | None:
        """Look an item up by canonical id, then by display name (TeamMember.item stores names)."""
        if not reference:
            return None
        return self.items_by_id.get(reference) or self.items_by_name.get(reference.lower())

    @cached_property
    def _suggestion_index(self) -> tuple[tuple[SpeciesSuggestion, frozenset[str]], ...]:
        """Every suggestable species with its searchable name variants, built once.

        The list and the per-entry variants used to be rebuilt on every keystroke, and the
        "contains" pass then did an O(n²) ``not in`` over the prefix hits.
        """
        suggestions: list[SpeciesSuggestion] = []
        seen_ids: set[str] = set()

        for r in self.champions:
            cid = (r.species_name or "").lower()
            if cid and cid not in seen_ids:
                seen_ids.add(cid)
                suggestions.append(SpeciesSuggestion(display_name=r.display_name, species_name=cid, canonical_id=cid))

        # Legal non-mega, non-battle-only forms from the species catalogue.
        for s in self.species_by_canonical.values():
            if not s.is_legal or s.is_mega or s.battle_only:
                continue
            cid = s.canonical_id.lower()
            if cid in seen_ids:
                continue
            # Format female forms nicely, e.g. "Indeedee (Female)"
            disp = s.name
            if cid.endswith("-f"):
                base_disp = s.name[:-2] if s.name.endswith(("-F", "-f")) else s.name
                disp = f"{base_disp} (Female)"
            elif "-" in cid:
                disp = format_display_name(cid)

            seen_ids.add(cid)
            suggestions.append(SpeciesSuggestion(display_name=disp, species_name=cid, canonical_id=cid))

        index: list[tuple[SpeciesSuggestion, frozenset[str]]] = []
        for suggestion in suggestions:
            raw_names = [
                suggestion.display_name.lower(),
                suggestion.species_name.lower(),
                suggestion.canonical_id.lower(),
                qualified_name(suggestion.display_name, suggestion.canonical_id).lower(),
            ]
            variants = set(raw_names)
            for n in raw_names:
                cleaned = " ".join(n.replace("(", " ").replace(")", " ").replace("-", " ").split())
                variants.add(cleaned)
                variants.add(cleaned.replace(" ", "-"))
            index.append((suggestion, frozenset(variants)))
        return tuple(index)

    def suggest_species(self, query: str, limit: int = 8) -> list[SpeciesSuggestion]:
        q = query.strip().lower()
        if len(q) < 2:
            return []
        q_clean = q.replace("\u2640", " female").replace("\u2642", " male").replace("(", " ").replace(")", " ")
        q_clean = " ".join(q_clean.split())

        starts: list[SpeciesSuggestion] = []
        contains: list[SpeciesSuggestion] = []
        for suggestion, variants in self._suggestion_index:
            if any(v.startswith(q) or (q_clean and v.startswith(q_clean)) for v in variants):
                starts.append(suggestion)
                if len(starts) >= limit:
                    return starts[:limit]
            elif len(contains) < limit and any(q in v or (q_clean and q_clean in v) for v in variants):
                contains.append(suggestion)
        return (starts + contains)[:limit]

    # -- loading ------------------------------------------------------------------------

    @classmethod
    def load(cls, session_factory: SessionFactory = get_session) -> "Catalogs":
        state: dict = {}
        with session_factory() as session:
            session.expire_on_commit = False
            champions = tuple(ChampionsCatalogRepository(session).list_all())
            megas_list = MegaEvolutionRepository(session).list_all()
            load_items_catalog(session, state)
            moves_by_id, learnsets = load_move_catalog(session)
            species = load_species_catalog(session)
            needs_commit = False
            for m in megas_list:
                if not m.ability:
                    s = species.get(m.canonical_id) or (species.get(resolve_species_key(m.canonical_id, species)) if species else None)
                    if s is not None and s.abilities:
                        m.ability = s.abilities[0]
                        session.add(m)
                        needs_commit = True
            if needs_commit:
                try:
                    session.commit()
                except Exception:
                    session.rollback()
            megas = tuple(megas_list)
        return cls(
            champions=champions,
            megas=megas,
            items_by_id=dict(state.get("items_by_id") or {}),
            champions_items=tuple(state.get("champions_items") or ()),
            mega_stone_map={k: list(v) for k, v in (state.get("mega_stone_map") or {}).items()},
            moves_by_id=moves_by_id,
            learnsets=learnsets,
            species_by_canonical=species,
        )

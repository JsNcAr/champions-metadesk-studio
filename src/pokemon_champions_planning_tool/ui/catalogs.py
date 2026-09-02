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

from sqlmodel import Session

from ..infrastructure.database.database import get_session
from ..infrastructure.database.models import ChampionsSpeciesRecord, ItemRecord, MegaEvolutionRecord
from ..infrastructure.database.repositories import ChampionsCatalogRepository, MegaEvolutionRepository
from ..domain.moves import MoveInfo, move_key, resolve_learnset_key
from ..services.items_catalog_service import load_items_catalog
from ..services.move_catalog_service import load_move_catalog

SessionFactory = Callable[[], AbstractContextManager[Session]]


@dataclass(frozen=True)
class Catalogs:
    champions: tuple[ChampionsSpeciesRecord, ...] = ()
    megas: tuple[MegaEvolutionRecord, ...] = ()
    items_by_id: dict[str, ItemRecord] = field(default_factory=dict)
    champions_items: tuple[ItemRecord, ...] = ()
    mega_stone_map: dict[str, list[ItemRecord]] = field(default_factory=dict)
    moves_by_id: dict[str, MoveInfo] = field(default_factory=dict)
    learnsets: dict[str, frozenset[str]] = field(default_factory=dict)   # Showdown species key -> move ids

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

    @property
    def champions_names(self) -> list[str]:
        return [r.display_name for r in self.champions]

    @property
    def champions_species_names(self) -> set[str]:
        return {r.species_name.lower() for r in self.champions if r.species_name}

    @property
    def mega_species(self) -> frozenset[str]:
        return frozenset(m.species_name.lower() for m in self.megas if m.species_name)

    def megas_for(self, species_name: str | None) -> list[MegaEvolutionRecord]:
        key = (species_name or "").lower()
        return [m for m in self.megas if (m.species_name or "").lower() == key]

    @property
    def items_by_name(self) -> dict[str, ItemRecord]:
        return {r.display_name.lower(): r for r in self.items_by_id.values()}

    def item_for(self, reference: str | None) -> ItemRecord | None:
        """Look an item up by canonical id, then by display name (TeamMember.item stores names)."""
        if not reference:
            return None
        return self.items_by_id.get(reference) or self.items_by_name.get(reference.lower())

    def suggest_species(self, query: str, limit: int = 8) -> list[ChampionsSpeciesRecord]:
        q = query.strip().lower()
        if len(q) < 2:
            return []
        starts = [r for r in self.champions if r.display_name.lower().startswith(q) or (r.species_name or "").lower().startswith(q)]
        contains = [r for r in self.champions if r not in starts and (q in r.display_name.lower() or q in (r.species_name or "").lower())]
        return (starts + contains)[:limit]

    # -- loading ------------------------------------------------------------------------

    @classmethod
    def load(cls, session_factory: SessionFactory = get_session) -> "Catalogs":
        state: dict = {}
        with session_factory() as session:
            champions = tuple(ChampionsCatalogRepository(session).list_all())
            megas = tuple(MegaEvolutionRepository(session).list_all())
            load_items_catalog(session, state)
            moves_by_id, learnsets = load_move_catalog(session)
        return cls(
            champions=champions,
            megas=megas,
            items_by_id=dict(state.get("items_by_id") or {}),
            champions_items=tuple(state.get("champions_items") or ()),
            mega_stone_map={k: list(v) for k, v in (state.get("mega_stone_map") or {}).items()},
            moves_by_id=moves_by_id,
            learnsets=learnsets,
        )

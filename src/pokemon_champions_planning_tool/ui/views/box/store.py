"""Box store: the single read path for the roster plus every mutation. Flet-free.

Holds detached ``BoxEntry`` objects; every method that touches the database opens its
own session. Mutations notify subscribers with a change tuple so the view can update
only what moved:

    ("all",)              roster reloaded
    ("entry", id)         one entry's metadata changed
    ("selection", id)     selected entry changed (id may be None)
    ("multi",)            the multi-selection set changed
"""

from __future__ import annotations

from collections.abc import Callable
from contextlib import AbstractContextManager
from dataclasses import dataclass, field
from typing import Any
from pathlib import Path
from typing import Any, Literal
from uuid import UUID

from sqlmodel import Session

from ....domain.entities.box_entry import BoxEntry
from ....domain.entities.team import Team
from ....domain.entities.team_member import TeamMember
from ....domain.entities.pokemon_stats import PokemonStats
from ....domain.type_chart import bucket_profile, defensive_profile
from ....infrastructure.csv.csv_operations import export_box_entries_to_csv
from ....infrastructure.database.database import get_session
from ....infrastructure.database.models import MegaEvolutionRecord
from ....infrastructure.database.repositories import BoxRepository, MegaEvolutionRepository, TeamRepository
from ....services.box_transfer_service import (
    BoxImportReport,
    ParsedBoxItem,
    ParsedBoxResult,
    apply_box_import,
    export_box_to_csv_text,
    export_box_to_json,
    export_box_to_names,
    parse_box_import_text,
)
from ....services.mega_evolution_service import sync_mega_evolutions_for_species
from ....services.pokemon_import_service import add_pokemon_to_box, refresh_pokemon_record
from ...catalogs import Catalogs
from .filters import BoxFilters, apply_filters

SessionFactory = Callable[[], AbstractContextManager[Session]]
Change = tuple
Listener = Callable[[Change], None]


@dataclass(frozen=True)
class FormOption:
    """A selectable form in the detail panel: the base species or one of its megas."""

    form_id: str
    label: str
    sprite_url: str | None
    types: tuple[str, ...]
    stats: PokemonStats
    is_mega: bool
    ability: str | None = None

    @property
    def abilities(self) -> tuple[str, ...]:
        """Backwards compatibility property returning abilities tuple."""
        return (self.ability,) if self.ability else ()

    @classmethod
    def from_mega(cls, mega: MegaEvolutionRecord, ability: str | None = None, **kwargs: Any) -> "FormOption":
        resolved_ability = ability or mega.ability or None
        if not resolved_ability and "abilities" in kwargs:
            raw = kwargs["abilities"]
            resolved_ability = raw[0] if raw else None
        return cls(
            form_id=mega.canonical_id,
            label=mega.display_name,
            sprite_url=mega.sprite_url,
            types=tuple(mega.types or ()),
            stats=PokemonStats(
                hp=mega.hp, attack=mega.attack, defense=mega.defense,
                sp_atk=mega.special_attack, sp_def=mega.special_defense, speed=mega.speed,
            ),
            is_mega=True,
            ability=resolved_ability,
        )


@dataclass(frozen=True)
class BoxDetail:
    entry: BoxEntry
    forms: tuple[FormOption, ...]
    teams: tuple[tuple[str, int], ...]   # (team name, slot) holding this entry
    megas_checked: bool                  # False = never looked up; a sync may find some

    def form(self, form_id: str | None) -> FormOption:
        for option in self.forms:
            if option.form_id == form_id:
                return option
        return self.forms[0]

    def defensive_buckets(self, form_id: str | None = None) -> dict[float, list[str]]:
        return bucket_profile(defensive_profile(list(self.form(form_id).types)))


@dataclass(frozen=True)
class TeamOption:
    team_id: UUID
    name: str
    filled: int


@dataclass(frozen=True)
class AddToTeamResult:
    added: int
    already_on_team: int
    no_room: int


class BoxStore:
    def __init__(self, catalogs: Catalogs | None = None, session_factory: SessionFactory = get_session) -> None:
        self._sf = session_factory
        self.catalogs = catalogs or Catalogs()
        self.entries: list[BoxEntry] = []
        self.filters = BoxFilters()
        self.selected_id: UUID | None = None
        self.selected_form_id: str | None = None
        self.multi: set[UUID] = set()
        self._listeners: list[Listener] = []
        self._usage_cache: dict[tuple[str, str], dict[str, int]] = {}
        # Resolved (regulation, battle format) per requested regulation. Resolving it
        # needs two queries, and the grid asks for the usage map several times per render.
        self._usage_key_cache: dict[str, tuple[str, str]] = {}
        self._by_id: dict[UUID, BoxEntry] = {}

    # -- subscription -------------------------------------------------------------------

    def subscribe(self, listener: Listener) -> Callable[[], None]:
        self._listeners.append(listener)
        return lambda: self._listeners.remove(listener)

    def _notify(self, change: Change) -> None:
        for listener in list(self._listeners):
            listener(change)

    # -- reading ------------------------------------------------------------------------

    def load(self) -> list[BoxEntry]:
        with self._sf() as s:
            self.entries = BoxRepository(s).list_entries(include_planned=True)
        self._by_id = {e.box_entry_id: e for e in self.entries}
        if self.selected_id is not None and self.entry(self.selected_id) is None:
            self.selected_id = None
        self.multi &= self._by_id.keys()
        self._notify(("all",))
        return self.entries

    def entry(self, box_entry_id: UUID | None) -> BoxEntry | None:
        if box_entry_id is None:
            return None
        return self._by_id.get(box_entry_id)

    def latest_regulation(self) -> str:
        if self._sf is not None:
            try:
                with self._sf() as s:
                    from ....infrastructure.database.repositories import TournamentRepository
                    return TournamentRepository(s).get_latest_regulation()
            except Exception:
                pass
        return "Regulation M-C"

    def available_regulations(self) -> list[str]:
        if self._sf is not None:
            try:
                with self._sf() as s:
                    from ....infrastructure.database.repositories import TournamentRepository
                    return TournamentRepository(s).list_regulations_by_date()
            except Exception:
                pass
        return ["Regulation M-C", "Regulation M-B", "Regulation M-A"]

    def get_usage_map(self, regulation: str = "latest") -> dict[str, int]:
        """Cached {canonical_id: team_count} for the specified regulation."""
        if self._sf is None:
            return {}
        cache_key = self._usage_key_cache.get(regulation)
        if cache_key is not None:
            cached = self._usage_cache.get(cache_key)
            if cached is not None:
                return cached
        try:
            with self._sf() as s:
                from ....infrastructure.database.repositories import TournamentRepository
                repo = TournamentRepository(s)
                if cache_key is None:
                    bformat = repo.get_state("pref_battle_format") or "doubles"
                    reg = repo.get_latest_regulation() if regulation == "latest" else regulation
                    cache_key = (reg, bformat)
                    self._usage_key_cache[regulation] = cache_key
                if cache_key in self._usage_cache:
                    return self._usage_cache[cache_key]
                umap = repo.species_usage_by_regulation(regulation=cache_key[0], battle_format=cache_key[1])
                self._usage_cache[cache_key] = umap
                return umap
        except Exception:
            return {}

    def usage_map_cached(self, regulation: str = "latest") -> bool:
        """True when ``get_usage_map`` would answer without touching the database."""
        key = self._usage_key_cache.get(regulation)
        return key is not None and key in self._usage_cache

    def invalidate_usage_cache(self) -> None:
        self._usage_cache.clear()
        self._usage_key_cache.clear()

    def visible(self) -> list[BoxEntry]:
        umap = self.get_usage_map(self.filters.usage_regulation) if self.filters.sort == "usage" else None
        return apply_filters(self.entries, self.filters, self.catalogs.mega_species, usage_map=umap)

    def counts(self, visible_entries: list[BoxEntry] | None = None) -> tuple[int, int]:
        """(visible, total owned) for the header chip."""
        owned = sum(1 for e in self.entries if not e.is_planned)
        vis_count = len(visible_entries) if visible_entries is not None else len(self.visible())
        return vis_count, owned

    def all_tags(self) -> list[str]:
        seen: dict[str, str] = {}
        for e in self.entries:
            for t in e.tags:
                seen.setdefault(t.lower(), t)
        return sorted(seen.values(), key=str.lower)

    def is_mega_capable(self, entry: BoxEntry) -> bool:
        return (entry.pokemon.species_name or "").lower() in self.catalogs.mega_species

    def detail(self, box_entry_id: UUID) -> BoxDetail | None:
        entry = self.entry(box_entry_id)
        if entry is None:
            return None
        with self._sf() as s:
            mega_repo = MegaEvolutionRepository(s)
            megas = mega_repo.list_by_species(entry.pokemon.species_name or entry.pokemon.canonical_id)
            checked = mega_repo.is_species_checked(entry.pokemon.species_name or "")
            teams = TeamRepository(s).teams_containing(box_entry_id)
        base = FormOption(
            form_id="base",
            label=entry.pokemon.form_name or "Base",
            sprite_url=entry.pokemon.sprite_url,
            types=tuple(entry.pokemon.types),
            stats=entry.pokemon.stats,
            is_mega=False,
            ability=None,
        )
        mega_options = []
        for m in megas:
            m_ability = m.ability or None
            if not m_ability:
                cat_s = self.catalogs.species_for(m.canonical_id)
                if cat_s is not None and cat_s.abilities:
                    m_ability = cat_s.abilities[0]
            mega_options.append(FormOption.from_mega(m, ability=m_ability))
        return BoxDetail(
            entry=entry,
            forms=(base, *mega_options),
            teams=tuple(teams),
            megas_checked=checked or bool(megas),
        )

    # -- selection / filters -------------------------------------------------------------

    def select(self, box_entry_id: UUID | None) -> None:
        if box_entry_id == self.selected_id:
            return
        self.selected_id = box_entry_id
        self.selected_form_id = None
        self._notify(("selection", box_entry_id))

    def set_filters(self, filters: BoxFilters) -> None:
        self.filters = filters

    # -- multi-selection ------------------------------------------------------------------

    def toggle_multi(self, box_entry_id: UUID, selected: bool | None = None) -> None:
        if selected is None:
            selected = box_entry_id not in self.multi
        (self.multi.add if selected else self.multi.discard)(box_entry_id)
        self._notify(("multi",))

    def select_all_visible(self) -> None:
        self.multi = {e.box_entry_id for e in self.visible()}
        self._notify(("multi",))

    def clear_multi(self) -> None:
        if self.multi:
            self.multi = set()
            self._notify(("multi",))

    def multi_entries(self) -> list[BoxEntry]:
        return [e for e in self.entries if e.box_entry_id in self.multi]

    def teams_for(self, ids: list[UUID]) -> dict[UUID, list[tuple[str, int]]]:
        """Teams holding each of the given entries (for a bulk-delete confirmation)."""
        with self._sf() as s:
            repo = TeamRepository(s)
            return {i: repo.teams_containing(i) for i in ids}

    # -- mutations (each is one session) ----------------------------------------------------

    def set_favorite(self, box_entry_id: UUID, value: bool) -> None:
        entry = self.entry(box_entry_id)
        if entry is None:
            return
        with self._sf() as s:
            BoxRepository(s).update_metadata(str(box_entry_id), is_favorite=value)
        entry.is_favorite = value
        self._notify(("entry", box_entry_id))

    def save_notes(self, box_entry_id: UUID, notes: str) -> None:
        entry = self.entry(box_entry_id)
        if entry is None:
            return
        with self._sf() as s:
            BoxRepository(s).update_metadata(str(box_entry_id), notes=notes)
        entry.notes = notes
        self._notify(("entry", box_entry_id))

    def save_tags(self, box_entry_id: UUID, tags: list[str]) -> None:
        entry = self.entry(box_entry_id)
        if entry is None:
            return
        clean: list[str] = []
        for tag in tags:
            t = tag.strip()
            if t and t.lower() not in {c.lower() for c in clean}:
                clean.append(t)
        with self._sf() as s:
            BoxRepository(s).update_metadata(str(box_entry_id), tags=clean)
        entry.tags = clean
        self._notify(("entry", box_entry_id))

    def set_planned(self, box_entry_id: UUID, planned: bool) -> None:
        with self._sf() as s:
            BoxRepository(s).update_metadata(str(box_entry_id), is_planned=planned)
        self.load()

    def bulk_update(self, ids: list[UUID], **changes: Any) -> int:
        with self._sf() as s:
            n = BoxRepository(s).update_many(ids, **changes)
        self.load()
        return n

    def delete(self, ids: list[UUID]) -> list[BoxEntry]:
        """Delete entries (and their team memberships). Returns the removed entries so
        a caller can offer Undo."""
        removed = [e for e in self.entries if e.box_entry_id in set(ids)]
        if not removed:
            return []
        with self._sf() as s:
            BoxRepository(s).delete_many(ids)
        if self.selected_id in set(ids):
            self.selected_id = None
        self.load()
        return removed

    def restore(self, entries: list[BoxEntry]) -> None:
        """Undo a delete: re-create the entries with their metadata (team slots are not restored)."""
        with self._sf() as s:
            repo = BoxRepository(s)
            for entry in entries:
                if entry.is_planned:
                    repo.create_planned_entry(entry)
                else:
                    repo.upsert_box_entry(entry)
        self.load()

    # -- work for background threads (no notifications; call load() in on_done) ------------

    def add_by_name(self, name: str) -> BoxEntry:
        """Blocking: resolves the species (PokéAPI on a miss) and stores it."""
        return add_pokemon_to_box(name)

    def refresh_entry(self, entry_id: UUID) -> bool:
        """Blocking: re-fetch a placeholder Pokémon's data from PokéAPI and reload."""
        entry = self.entry(entry_id)
        if entry is None:
            return False
        fetched = refresh_pokemon_record(entry.pokemon.canonical_id, entry.pokemon.display_name)
        return fetched is not None

    def fetch_megas(self, species_name: str) -> list[MegaEvolutionRecord]:
        """Blocking: look up mega forms for a species the catalogue has not checked yet."""
        with self._sf() as s:
            return list(sync_mega_evolutions_for_species(s, species_name))

    def export_csv(self, entries: list[BoxEntry] | None = None) -> int:
        """Write owned entries to the CSV file; ``entries`` limits it to a visible or selected set."""
        source = self.entries if entries is None else entries
        owned = [e for e in source if not e.is_planned]
        export_box_entries_to_csv(owned)
        return len(owned)

    def export_box(self, format_type: str = "json", entries: list[BoxEntry] | None = None) -> str:
        """Serialize entries into JSON, plain text names, or CSV."""
        source = self.entries if entries is None else entries
        if format_type == "json":
            return export_box_to_json(source)
        elif format_type == "text":
            return export_box_to_names(source, include_metadata=True)
        elif format_type == "csv":
            return export_box_to_csv_text(source)
        raise ValueError(f"Unknown format: {format_type}")

    def import_box(
        self,
        items: list[ParsedBoxItem],
        strategy: Literal["merge", "replace"] = "merge",
        as_planned: bool | None = None,
    ) -> BoxImportReport:
        """Apply parsed items to the database and reload."""
        with self._sf() as s:
            report = apply_box_import(s, items, strategy=strategy, as_planned=as_planned)
        self.load()
        return report

    def save_export_file(self, content: str, filename: str) -> Path:
        """Save text content to the local filesystem."""
        path = Path(filename)
        path.write_text(content, encoding="utf-8")
        return path.resolve()

    # -- teams -----------------------------------------------------------------------------

    def list_teams(self) -> list[TeamOption]:
        with self._sf() as s:
            repo = TeamRepository(s)
            counts = repo.member_counts()
            return [TeamOption(r.team_id, r.name, counts.get(r.team_id, 0)) for r in repo.list_all()]

    def create_team(self, name: str) -> UUID:
        clean = name.strip()
        if not clean:
            raise ValueError("Team name cannot be empty")
        with self._sf() as s:
            repo = TeamRepository(s)
            if repo.get_by_name(clean) is not None:
                raise ValueError(f"A team named “{clean}” already exists")
            return repo.create(Team(name=clean)).team_id

    def add_to_team(self, team_id: UUID, ids: list[UUID]) -> AddToTeamResult:
        """Put entries into the team's empty slots, in order. Entries already on the team are
        skipped; entries beyond the free slots are counted, not placed."""
        with self._sf() as s:
            repo = TeamRepository(s)
            members = repo.get_members(team_id)
            on_team = {m.box_entry_id for m in members}
            free = [p for p in range(1, 7) if p not in {m.slot_position for m in members}]
            added = already = no_room = 0
            for entry_id in ids:
                if entry_id in on_team:
                    already += 1
                    continue
                if not free:
                    no_room += 1
                    continue
                repo.upsert_member(team_id, TeamMember(box_entry_id=entry_id, slot_position=free.pop(0)))
                on_team.add(entry_id)
                added += 1
        return AddToTeamResult(added=added, already_on_team=already, no_room=no_room)

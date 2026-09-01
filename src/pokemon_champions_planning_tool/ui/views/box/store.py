"""Box store: the single read path for the roster plus every mutation. Flet-free.

Holds detached ``BoxEntry`` objects; every method that touches the database opens its
own session. Mutations notify subscribers with a change tuple so the view can update
only what moved:

    ("all",)              roster reloaded
    ("entry", id)         one entry's metadata changed
    ("selection", id)     selected entry changed (id may be None)
"""

from __future__ import annotations

from collections.abc import Callable
from contextlib import AbstractContextManager
from dataclasses import dataclass, field
from typing import Any
from uuid import UUID

from sqlmodel import Session

from ....domain.entities.box_entry import BoxEntry
from ....domain.entities.pokemon_stats import PokemonStats
from ....domain.type_chart import bucket_profile, defensive_profile
from ....infrastructure.csv.csv_operations import export_box_entries_to_csv
from ....infrastructure.database.database import get_session
from ....infrastructure.database.models import MegaEvolutionRecord
from ....infrastructure.database.repositories import BoxRepository, MegaEvolutionRepository, TeamRepository
from ....services.mega_evolution_service import sync_mega_evolutions_for_species
from ....services.pokemon_import_service import add_pokemon_to_box
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

    @classmethod
    def from_mega(cls, mega: MegaEvolutionRecord) -> "FormOption":
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


class BoxStore:
    def __init__(self, catalogs: Catalogs | None = None, session_factory: SessionFactory = get_session) -> None:
        self._sf = session_factory
        self.catalogs = catalogs or Catalogs()
        self.entries: list[BoxEntry] = []
        self.filters = BoxFilters()
        self.selected_id: UUID | None = None
        self.selected_form_id: str | None = None
        self._listeners: list[Listener] = []

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
        if self.selected_id is not None and self.entry(self.selected_id) is None:
            self.selected_id = None
        self._notify(("all",))
        return self.entries

    def entry(self, box_entry_id: UUID | None) -> BoxEntry | None:
        if box_entry_id is None:
            return None
        return next((e for e in self.entries if e.box_entry_id == box_entry_id), None)

    def visible(self) -> list[BoxEntry]:
        return apply_filters(self.entries, self.filters, self.catalogs.mega_species)

    def counts(self) -> tuple[int, int]:
        """(visible, total owned) for the header chip."""
        owned = sum(1 for e in self.entries if not e.is_planned)
        return len(self.visible()), owned

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
        )
        return BoxDetail(
            entry=entry,
            forms=(base, *[FormOption.from_mega(m) for m in megas]),
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

    def fetch_megas(self, species_name: str) -> list[MegaEvolutionRecord]:
        """Blocking: look up mega forms for a species the catalogue has not checked yet."""
        with self._sf() as s:
            return list(sync_mega_evolutions_for_species(s, species_name))

    def export_csv(self) -> int:
        owned = [e for e in self.entries if not e.is_planned]
        export_box_entries_to_csv(owned)
        return len(owned)

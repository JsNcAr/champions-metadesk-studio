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
from ..services.items_catalog_service import load_items_catalog

SessionFactory = Callable[[], AbstractContextManager[Session]]


@dataclass(frozen=True)
class Catalogs:
    champions: tuple[ChampionsSpeciesRecord, ...] = ()
    megas: tuple[MegaEvolutionRecord, ...] = ()
    items_by_id: dict[str, ItemRecord] = field(default_factory=dict)
    champions_items: tuple[ItemRecord, ...] = ()
    mega_stone_map: dict[str, list[ItemRecord]] = field(default_factory=dict)

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
        return cls(
            champions=champions,
            megas=megas,
            items_by_id=dict(state.get("items_by_id") or {}),
            champions_items=tuple(state.get("champions_items") or ()),
            mega_stone_map={k: list(v) for k, v in (state.get("mega_stone_map") or {}).items()},
        )

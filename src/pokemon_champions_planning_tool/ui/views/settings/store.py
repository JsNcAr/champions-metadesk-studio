"""Settings store: catalogue status and the three sync operations.

Flet-free. Every method opens its own session, so the sync methods are safe to run
from a worker thread via ``run_in_background``.
"""

from __future__ import annotations

from collections.abc import Callable
from contextlib import AbstractContextManager
from dataclasses import dataclass
from datetime import datetime
from typing import Any

from sqlmodel import Session, func, select

from ....infrastructure.database.database import get_session
from ....infrastructure.database.models import (
    ItemCatalogMetaRecord,
    ItemRecord,
    MegaCheckedSpeciesRecord,
    MegaEvolutionRecord,
    MoveCatalogMetaRecord,
    PokemonRecord,
    TournamentRecord,
    TournamentTeamRecord,
)
from ....services.items_catalog_service import sync_items_catalog
from ....services.mega_evolution_service import sync_all_champions_megas_on_startup
from ....infrastructure.database.repositories import BoxRepository
from ....infrastructure.database.repositories import BoxRepository, TournamentRepository
from ....services.move_catalog_service import sync_move_catalog
from ....services.species_catalog_service import sync_species_catalog
from ....services.pokemon_import_service import refresh_stub_pokemon
from ....services.tournament_service import TournamentService

SessionFactory = Callable[[], AbstractContextManager[Session]]


@dataclass(frozen=True)
class SettingsStatus:
    mega_count: int
    megas_checked_at: datetime | None
    item_count: int
    items_synced_at: datetime | None
    tournament_count: int
    tournament_team_count: int
    tournaments_synced_at: datetime | None
    move_count: int = 0
    move_species_count: int = 0
    moves_synced_at: datetime | None = None
    placeholder_in_box: int = 0      # box entries whose Pokémon has no PokéAPI data
    placeholder_records: int = 0     # placeholder records in the table (any, referenced or not)


class SettingsStore:
    def __init__(self, session_factory: SessionFactory = get_session) -> None:
        self._sf = session_factory

    def status(self) -> SettingsStatus:
        with self._sf() as s:
            mega_count = s.exec(select(func.count()).select_from(MegaEvolutionRecord)).one()
            megas_checked_at = s.exec(select(func.max(MegaCheckedSpeciesRecord.checked_at))).one()
            item_count = s.exec(select(func.count()).select_from(ItemRecord)).one()
            meta = s.get(ItemCatalogMetaRecord, 1)
            items_synced_at = meta.last_synced_at if meta and item_count else None
            tournament_count = s.exec(select(func.count()).select_from(TournamentRecord)).one()
            team_count = s.exec(select(func.count()).select_from(TournamentTeamRecord)).one()
            move_meta = s.get(MoveCatalogMetaRecord, 1)
            placeholder_records = int(s.exec(select(func.count()).select_from(PokemonRecord).where(PokemonRecord.is_placeholder == True)).one() or 0)  # noqa: E712
            placeholder_in_box = sum(1 for e in BoxRepository(s).list_entries(include_planned=True) if e.pokemon.is_stub)
            tournaments_synced_at = s.exec(
                select(func.max(TournamentRecord.updated_at)).where(TournamentRecord.standings_synced == True)  # noqa: E712
            ).one()
        return SettingsStatus(
            mega_count=int(mega_count or 0),
            megas_checked_at=megas_checked_at,
            item_count=int(item_count or 0),
            items_synced_at=items_synced_at,
            tournament_count=int(tournament_count or 0),
            tournament_team_count=int(team_count or 0),
            tournaments_synced_at=tournaments_synced_at,
            move_count=int(move_meta.move_count) if move_meta else 0,
            move_species_count=int(move_meta.species_count) if move_meta else 0,
            moves_synced_at=move_meta.last_synced_at if move_meta and move_meta.move_count else None,
            placeholder_in_box=placeholder_in_box,
            placeholder_records=placeholder_records,
        )

    # -- sync operations (run on a worker thread) ---------------------------------------

    def sync_megas(self) -> dict[str, Any]:
        with self._sf() as s:
            return sync_all_champions_megas_on_startup(s)

    def sync_items(self) -> dict[str, Any]:
        with self._sf() as s:
            return sync_items_catalog(s, force=True)

    def sync_moves(self) -> dict[str, Any]:
        """Showdown data: moves + learnsets, then the species catalogue (stats, weights, abilities)."""
        with self._sf() as s:
            result = dict(sync_move_catalog(s, force=True))
            species = sync_species_catalog(s, force=True)
            result["species_catalog"] = species.get("species", 0)
            result["species_status"] = species.get("status")
            return result

    def repair_data(self) -> dict[str, Any]:
        """Re-fetch placeholder Pokémon referenced by the box."""
        with self._sf() as s:
            return refresh_stub_pokemon(s)

    def sync_tournaments(self, on_progress: Any = None) -> dict[str, Any]:
        # Not forced: a manual sync lists what is new, drains the standings backlog and
        # reads only official events not yet ingested. Forcing would re-fetch a year.
        with self._sf() as s:
            return TournamentService(s).sync(force=False, max_age_days=365, include_official=True, on_progress=on_progress)

    def get_battle_format_preference(self) -> str:
        """Stored tournament battle format preference: 'doubles', 'all', or 'singles'."""
        with self._sf() as s:
            repo = TournamentRepository(s)
            val = repo.get_state("pref_battle_format")
            return val if val in ("doubles", "all", "singles") else "doubles"

    def set_battle_format_preference(self, pref: str) -> None:
        """Update stored tournament battle format preference."""
        if pref not in ("doubles", "all", "singles"):
            pref = "doubles"
        with self._sf() as s:
            repo = TournamentRepository(s)
            repo.set_state("pref_battle_format", pref)

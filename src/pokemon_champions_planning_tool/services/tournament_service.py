"""Services for VGC Tournament Explorer search, indexing, and meta partner synergy analysis."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any
from uuid import UUID

from sqlmodel import Session, select

from ..domain.pokemon_identity import format_api_name
from ..infrastructure.database.models import (
    PokemonRecord,
    TournamentRecord,
    TournamentTeamMemberRecord,
    TournamentTeamRecord,
)
from ..infrastructure.database.repositories import TournamentRepository


@dataclass(frozen=True)
class PartnerRecommendation:
    """Calculated partner synergy recommendation for a given species."""

    species_name: str
    canonical_id: str
    display_name: str
    sprite_url: str | None
    co_occurrence_count: int
    total_target_teams: int
    synergy_percentage: float


class MetaSynergyService:
    """Calculates teammate co-occurrence metrics across tournament team rosters."""

    def __init__(self, session: Session):
        self.session = session

    def get_top_partners(
        self,
        species_identifier: str,
        limit: int = 6,
        regulation_filter: str | None = None,
        min_co_occurrence: int = 1,
        min_synergy_percent: float = 0.0,
    ) -> list[PartnerRecommendation]:
        """Find the most frequent tournament teammates for a target species."""
        clean_target = format_api_name(species_identifier)

        # 1. Locate all tournament_team_ids containing the target species
        stmt_target_teams = select(TournamentTeamMemberRecord.tournament_team_id).where(
            (TournamentTeamMemberRecord.canonical_id == clean_target)
            | (TournamentTeamMemberRecord.species_name.ilike(clean_target))
        )

        if regulation_filter and regulation_filter != "All":
            stmt_target_teams = (
                stmt_target_teams.join(
                    TournamentTeamRecord,
                    TournamentTeamMemberRecord.tournament_team_id
                    == TournamentTeamRecord.tournament_team_id,
                )
                .join(
                    TournamentRecord,
                    TournamentTeamRecord.tournament_id == TournamentRecord.tournament_id,
                )
                .where(TournamentRecord.format_regulation == regulation_filter)
            )

        target_team_ids = list(self.session.exec(stmt_target_teams).all())
        total_teams_count = len(target_team_ids)
        if total_teams_count == 0:
            return []

        # 2. Query all other team members in those specific teams
        stmt_partners = select(TournamentTeamMemberRecord).where(
            TournamentTeamMemberRecord.tournament_team_id.in_(target_team_ids)
        )
        partner_members = list(self.session.exec(stmt_partners).all())

        # 3. Aggregate co-occurrence counts (excluding the target species itself)
        co_counts: dict[str, int] = {}
        display_names: dict[str, str] = {}

        for pm in partner_members:
            c_id = pm.canonical_id
            if c_id == clean_target or pm.species_name.lower() == clean_target:
                continue
            co_counts[c_id] = co_counts.get(c_id, 0) + 1
            display_names[c_id] = pm.species_name

        # 4. Fetch sprites and assemble PartnerRecommendation objects
        recommendations: list[PartnerRecommendation] = []
        for c_id, count in co_counts.items():
            if count < min_co_occurrence:
                continue
            pct = (count / total_teams_count) * 100.0
            if pct < min_synergy_percent:
                continue

            pok_rec = self.session.get(PokemonRecord, c_id)
            sprite_url = pok_rec.sprite_url if pok_rec else None
            disp_name = pok_rec.display_name if pok_rec else display_names.get(c_id, c_id.title())

            recommendations.append(
                PartnerRecommendation(
                    species_name=display_names.get(c_id, disp_name),
                    canonical_id=c_id,
                    display_name=disp_name,
                    sprite_url=sprite_url,
                    co_occurrence_count=count,
                    total_target_teams=total_teams_count,
                    synergy_percentage=round(pct, 1),
                )
            )

        # Sort by co-occurrence count descending
        recommendations.sort(key=lambda r: r.co_occurrence_count, reverse=True)
        return recommendations[:limit]


class TournamentService:
    """High-level domain service orchestrating tournament search and meta analytics."""

    def __init__(self, session: Session, seed_file_path: Path | None = None):
        self.session = session
        self.repo = TournamentRepository(session)
        self.synergy_service = MetaSynergyService(session)

        if seed_file_path:
            self.ensure_seeded(seed_file_path)

    def ensure_seeded(self, seed_file_path: Path, force: bool = False) -> dict[str, Any]:
        """Ensure initial tournament dataset is loaded into SQLite."""
        return self.repo.seed_from_file(seed_file_path, force=force)

    def list_tournaments(self) -> list[TournamentRecord]:
        return self.repo.list_tournaments()

    def get_team(self, tournament_team_id: UUID) -> TournamentTeamRecord | None:
        return self.repo.get_team(tournament_team_id)

    def get_team_members(self, tournament_team_id: UUID) -> list[TournamentTeamMemberRecord]:
        return self.repo.get_team_members(tournament_team_id)

    def search_teams(
        self,
        query: str | None = None,
        regulation_filter: str | None = None,
        placement_filter: int | None = None,
        species_filter: str | None = None,
        game_platform_filter: str | None = None,
        max_age_days: int | None = None,
    ) -> list[TournamentTeamRecord]:
        return self.repo.search_teams(
            query=query,
            regulation_filter=regulation_filter,
            placement_filter=placement_filter,
            species_filter=species_filter,
            game_platform_filter=game_platform_filter,
            max_age_days=max_age_days,
        )

    def get_top_partners(
        self,
        species_identifier: str,
        limit: int = 6,
        regulation_filter: str | None = None,
    ) -> list[PartnerRecommendation]:
        return self.synergy_service.get_top_partners(
            species_identifier=species_identifier,
            limit=limit,
            regulation_filter=regulation_filter,
        )

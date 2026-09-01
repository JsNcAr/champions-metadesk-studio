"""Services for VGC Tournament Explorer search, indexing, and meta partner synergy analysis."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any
from uuid import UUID

from sqlmodel import Session, func, select

from ..domain.pokemon_identity import format_api_name, get_pokemon_sprite_url
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


# A species appearing in only a handful of tournament teams produces percentages
# that look authoritative but mean nothing ("50% Venusaur" off a 2-team sample).
_DEFAULT_MIN_SAMPLE_TEAMS = 5


class MetaSynergyService:
    """Calculates teammate co-occurrence metrics across tournament team rosters."""

    def __init__(self, session: Session):
        self.session = session

    def _target_team_ids_subquery(self, clean_target: str, regulation_filter: str | None):
        """Distinct tournament team IDs whose roster contains the target species."""
        stmt = select(TournamentTeamMemberRecord.tournament_team_id).where(
            (TournamentTeamMemberRecord.canonical_id == clean_target)
            | (func.lower(TournamentTeamMemberRecord.species_name) == clean_target)
        )

        if regulation_filter and regulation_filter != "All":
            stmt = (
                stmt.join(
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

        # DISTINCT matters: without it a roster listing the target twice would be
        # counted twice in the denominator.
        return stmt.distinct()

    def get_top_partners(
        self,
        species_identifier: str,
        limit: int = 6,
        regulation_filter: str | None = None,
        min_co_occurrence: int = 1,
        min_synergy_percent: float = 0.0,
        min_sample_teams: int = _DEFAULT_MIN_SAMPLE_TEAMS,
    ) -> list[PartnerRecommendation]:
        """Find the most frequent tournament teammates for a target species.

        Co-occurrence is aggregated in SQL rather than by loading every roster row
        into Python: a widely played species appears in thousands of teams, and this
        runs synchronously while the Team Builder renders.

        Args:
            limit: Maximum recommendations to return.
            regulation_filter: Restrict to one format regulation, or "All"/None.
            min_co_occurrence: Drop partners seen fewer times than this.
            min_synergy_percent: Drop partners below this share of target teams.
            min_sample_teams: Return nothing when the target itself appears in fewer
                teams than this, since percentages off a tiny sample are misleading.
        """
        clean_target = format_api_name(species_identifier)
        target_teams = self._target_team_ids_subquery(clean_target, regulation_filter)

        total_teams_count = self.session.exec(
            select(func.count()).select_from(target_teams.subquery())
        ).one()
        if not total_teams_count or total_teams_count < min_sample_teams:
            return []

        # Count teammates per canonical_id in one aggregate query.
        co_occurrence = func.count().label("co_occurrence")
        stmt = (
            select(
                TournamentTeamMemberRecord.canonical_id,
                func.min(TournamentTeamMemberRecord.species_name).label("species_name"),
                co_occurrence,
            )
            .where(
                TournamentTeamMemberRecord.tournament_team_id.in_(target_teams),
                TournamentTeamMemberRecord.canonical_id != clean_target,
                func.lower(TournamentTeamMemberRecord.species_name) != clean_target,
            )
            .group_by(TournamentTeamMemberRecord.canonical_id)
            .having(co_occurrence >= min_co_occurrence)
            .order_by(co_occurrence.desc())
            .limit(limit)
        )

        recommendations: list[PartnerRecommendation] = []
        for canonical_id, species_name, count in self.session.exec(stmt).all():
            pct = (count / total_teams_count) * 100.0
            if pct < min_synergy_percent:
                continue

            # Most tournament species have no local PokemonRecord (they are only ever
            # seen in imported rosters), so fall back to the same CDN resolver the
            # Tournament Explorer uses instead of rendering a blank pill.
            pokemon_record = self.session.get(PokemonRecord, canonical_id)
            display_name = (
                pokemon_record.display_name if pokemon_record else (species_name or canonical_id.title())
            )
            sprite_url = (
                pokemon_record.sprite_url
                if pokemon_record and pokemon_record.sprite_url
                else get_pokemon_sprite_url(canonical_id or species_name)
            )

            recommendations.append(
                PartnerRecommendation(
                    species_name=species_name or display_name,
                    canonical_id=canonical_id,
                    display_name=display_name,
                    sprite_url=sprite_url,
                    co_occurrence_count=count,
                    total_target_teams=total_teams_count,
                    synergy_percentage=round(pct, 1),
                )
            )

        return recommendations


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
        limit: int | None = None,
        offset: int = 0,
    ) -> list[TournamentTeamRecord]:
        return self.repo.search_teams(
            query=query,
            regulation_filter=regulation_filter,
            placement_filter=placement_filter,
            species_filter=species_filter,
            game_platform_filter=game_platform_filter,
            max_age_days=max_age_days,
            limit=limit,
            offset=offset,
        )

    def get_top_partners(
        self,
        species_identifier: str,
        limit: int = 6,
        regulation_filter: str | None = None,
        min_sample_teams: int = _DEFAULT_MIN_SAMPLE_TEAMS,
    ) -> list[PartnerRecommendation]:
        return self.synergy_service.get_top_partners(
            species_identifier=species_identifier,
            limit=limit,
            regulation_filter=regulation_filter,
            min_sample_teams=min_sample_teams,
        )

    def sync(
        self,
        force: bool = False,
        max_age_days: int = 365,
        include_official: bool = True,
    ) -> dict[str, Any]:
        """Syncs live tournament data from Limitless and Victory Road into local SQLite DB."""
        from .tournament_sync_service import sync_tournaments

        return sync_tournaments(
            self.session,
            force=force,
            max_age_days=max_age_days,
            include_official=include_official,
        )


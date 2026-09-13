"""Services for VGC Tournament Explorer search, indexing, and meta partner synergy analysis."""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import Any
from uuid import UUID

from sqlmodel import Session, func, select

from ..domain.pokemon_identity import base_canonical_id, format_api_name, get_pokemon_sprite_url, qualified_name
from datetime import datetime
from ..infrastructure.database.models import (
    PokemonRecord,
    TournamentRecord,
    TournamentTeamMemberRecord,
    TournamentTeamRecord,
)
from ..infrastructure.database.repositories import ChampionsCatalogRepository, TournamentRepository


@dataclass(frozen=True)
class TournamentBuild:
    """Consolidated tournament build per species."""

    canonical_id: str
    moves: list[str]
    nature: str | None = None
    item: str | None = None
    ability: str | None = None


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


@dataclass(frozen=True)
class MetaMemberRow:
    """One roster slot of a tournament team, ready to render."""

    slot: int
    species_name: str
    canonical_id: str
    sprite_url: str
    is_legal: bool
    in_box: bool | None = None   # None: no box was supplied

    @property
    def display_name(self) -> str:
        """Provider name plus the implicit default form: "Basculegion (Male)"."""
        return qualified_name(self.species_name, self.canonical_id)


@dataclass(frozen=True)
class MetaTeamRow:
    """A tournament team with its event context, detached from the session."""

    team_id: UUID
    tournament_id: str
    tournament_name: str
    event_date: datetime
    regulation: str
    game_platform: str
    organizer: str
    location: str
    total_players: int
    source_url: str | None
    event_tier: str
    player_name: str
    placement: int
    standing_label: str
    pokepast_url: str | None
    showdown_text: str
    members: tuple[MetaMemberRow, ...]
    legality_known: bool
    missing_count: int | None = None   # members not in the box; None when no box was supplied

    @property
    def illegal_species(self) -> list[str]:
        return [m.display_name for m in self.members if not m.is_legal]

    @property
    def is_legal(self) -> bool:
        return self.legality_known and not self.illegal_species

    @property
    def box_label(self) -> str | None:
        """"6/6 in box" for the chip; None when no box was supplied."""
        if self.missing_count is None:
            return None
        return f"{len(self.members) - self.missing_count}/{len(self.members)} in box"


@dataclass(frozen=True)
class MetaSummary:
    team_count: int
    event_count: int
    synced_at: datetime | None


def _legal_lookup(names: list[str]) -> set[str]:
    """Species names and their base species, lowercased, for O(1) legality checks."""
    lookup: set[str] = set()
    for name in names:
        if not name:
            continue
        key = name.lower().strip()
        lookup.add(key)
        lookup.add(key.split("-")[0])
    return lookup


def _is_legal(species_name: str, canonical_id: str, lookup: set[str]) -> bool:
    sname = (species_name or "").lower().strip()
    ckey = (canonical_id or "").lower().strip()
    return sname in lookup or ckey in lookup or ckey.split("-")[0] in lookup


# A species appearing in only a handful of tournament teams produces percentages
# that look authoritative but mean nothing ("50% Venusaur" off a 2-team sample).
_DEFAULT_MIN_SAMPLE_TEAMS = 5


class MetaSynergyService:
    """Calculates teammate co-occurrence metrics across tournament team rosters."""

    def __init__(self, session: Session):
        self.session = session

    def _target_team_ids_subquery(
        self,
        clean_target: str,
        regulation_filter: str | None,
        battle_format: str | None = "doubles",
    ):
        """Distinct tournament team IDs whose roster contains the target species."""
        # Indexed: the species id or one of its forms ("charizard-mega-y"). The old
        # lower(species_name) comparison forced a scan of every roster row.
        stmt = select(TournamentTeamMemberRecord.tournament_team_id).where(
            (TournamentTeamMemberRecord.canonical_id == clean_target)
            | (TournamentTeamMemberRecord.canonical_id.op("GLOB")(f"{clean_target}-*"))
        )

        has_reg = bool(regulation_filter and regulation_filter != "All")
        has_bf = bool(battle_format and battle_format != "all")

        if has_reg or has_bf:
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
            )
            if has_reg:
                stmt = stmt.where(TournamentRecord.format_regulation == regulation_filter)
            if has_bf:
                stmt = stmt.where(TournamentRecord.battle_format == battle_format)

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
        battle_format: str | None = "doubles",
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
            battle_format: Filter by battle format ("doubles" by default, "all", "singles").
        """
        clean_target = format_api_name(species_identifier)
        target_teams = self._target_team_ids_subquery(clean_target, regulation_filter, battle_format=battle_format)

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
                # …nor the target's own forms: a Mega Charizard is not Charizard's partner.
                ~TournamentTeamMemberRecord.canonical_id.op("GLOB")(f"{clean_target}-*"),
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
            display_name = qualified_name(
                pokemon_record.display_name if pokemon_record else (species_name or canonical_id.title()), canonical_id
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
        event_tiers: Sequence[str] | None = None,
        tournament_id_filter: str | None = None,
        owned_species: Sequence[str] | None = None,
        max_missing: int | None = None,
        battle_format_filter: str | None = "doubles",
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
            event_tiers=event_tiers,
            tournament_id_filter=tournament_id_filter,
            owned_species=owned_species,
            max_missing=max_missing,
            battle_format_filter=battle_format_filter,
        )

    def count_teams(self, **filters: Any) -> int:
        return self.repo.count_teams(**filters)

    def list_regulations(self) -> list[str]:
        return self.repo.list_regulations()

    def get_latest_regulation(self, game_platform: str | None = None) -> str:
        return self.repo.get_latest_regulation(game_platform)

    def list_regulations_by_date(self, game_platform: str | None = None) -> list[str]:
        return self.repo.list_regulations_by_date(game_platform)

    def species_usage_by_regulation(
        self, regulation: str | None = None, battle_format: str | None = "doubles"
    ) -> dict[str, int]:
        return self.repo.species_usage_by_regulation(regulation=regulation, battle_format=battle_format)

    def move_usage(self, canonical_id: str, *, battle_format: str | None = "doubles") -> dict[str, float]:
        """Share of stored rosters of this species (megas included) carrying each move,
        keyed by the move's Showdown id so it matches the catalogue regardless of spelling."""
        from ..domain.moves import move_key

        counts = self.repo.move_usage(canonical_id, battle_format=battle_format)
        if not counts:
            return {}
        # Every roster has four moves; teams ≈ total move slots / 4.
        teams = max(1.0, sum(n for _m, n in counts) / 4)
        usage: dict[str, float] = {}
        for name, n in counts:
            key = move_key(name)
            usage[key] = usage.get(key, 0.0) + n / teams
        return usage

    def common_moves_by_species(self, top: int = 4, *, battle_format: str | None = "doubles") -> dict[str, list[str]]:
        """The ``top`` most used roster moves per base species id (the "tournament set")."""
        usage = self.repo.move_usage_all(battle_format=battle_format)
        return {cid: [name for name, _n in moves[:top]] for cid, moves in usage.items()}

    def common_builds_by_species(self, top_moves: int = 4, *, battle_format: str | None = "doubles") -> dict[str, TournamentBuild]:
        """Tournament build per species: top moves, most common nature, item, and ability."""
        moves_usage = self.repo.move_usage_all(battle_format=battle_format)
        natures_usage = self.repo.nature_usage_all(battle_format=battle_format)
        items_usage = self.repo.item_usage_all(battle_format=battle_format)
        abilities_usage = self.repo.ability_usage_all(battle_format=battle_format)

        all_keys = set(moves_usage.keys()) | set(natures_usage.keys()) | set(items_usage.keys()) | set(abilities_usage.keys())
        builds: dict[str, TournamentBuild] = {}
        for cid in all_keys:
            top_m = [name for name, _n in moves_usage.get(cid, [])[:top_moves]]
            top_nat = natures_usage.get(cid, [(None, 0)])[0][0] if natures_usage.get(cid) else None
            top_itm = items_usage.get(cid, [(None, 0)])[0][0] if items_usage.get(cid) else None
            top_ab = abilities_usage.get(cid, [(None, 0)])[0][0] if abilities_usage.get(cid) else None
            builds[cid] = TournamentBuild(
                canonical_id=cid,
                moves=top_m,
                nature=top_nat,
                item=top_itm,
                ability=top_ab,
            )
        return builds

    def search_team_rows(
        self,
        query: str | None = None,
        regulation_filter: str | None = None,
        placement_filter: int | None = None,
        game_platform_filter: str | None = None,
        max_age_days: int | None = None,
        limit: int | None = None,
        offset: int = 0,
        event_tiers: Sequence[str] | None = None,
        tournament_id_filter: str | None = None,
        owned_species: Sequence[str] | None = None,
        max_missing: int | None = None,
        battle_format_filter: str | None = "doubles",
    ) -> list[MetaTeamRow]:
        """Search teams and return detached rows with event context, roster and legality.

        Three queries regardless of page size: teams, their tournaments, their members.
        Only the Champions catalogue defines legality; when it is empty every member is
        reported legal and ``legality_known`` is False, so the UI never labels a team
        illegal on the basis of missing data.
        """
        teams = self.repo.search_teams(
            query=query,
            regulation_filter=regulation_filter,
            placement_filter=placement_filter,
            game_platform_filter=game_platform_filter,
            max_age_days=max_age_days,
            limit=limit,
            offset=offset,
            event_tiers=event_tiers,
            tournament_id_filter=tournament_id_filter,
            owned_species=owned_species,
            max_missing=max_missing,
            battle_format_filter=battle_format_filter,
        )
        if not teams:
            return []

        names = ChampionsCatalogRepository(self.session).list_species_names()
        legality_known = bool(names)
        lookup = _legal_lookup(names)

        team_ids = [t.tournament_team_id for t in teams]
        tournament_ids = list({t.tournament_id for t in teams})
        tournaments = {
            t.tournament_id: t
            for t in self.session.exec(
                select(TournamentRecord).where(TournamentRecord.tournament_id.in_(tournament_ids))
            ).all()
        }
        members_by_team: dict[UUID, list[TournamentTeamMemberRecord]] = {}
        for m in self.session.exec(
            select(TournamentTeamMemberRecord).where(
                TournamentTeamMemberRecord.tournament_team_id.in_(team_ids)
            )
        ).all():
            members_by_team.setdefault(m.tournament_team_id, []).append(m)

        owned = {o for o in (owned_species or ()) if o} if owned_species is not None else None
        rows: list[MetaTeamRow] = []
        for team in teams:
            tournament = tournaments.get(team.tournament_id)
            members = sorted(members_by_team.get(team.tournament_team_id, []), key=lambda m: m.slot_position)
            in_box = [
                (
                    ((m.base_canonical_id.lower() if m.base_canonical_id else None) or base_canonical_id(m.canonical_id)) in owned
                    or (m.canonical_id.lower() if m.canonical_id else "") in owned
                )
                if owned is not None
                else None
                for m in members
            ]
            rows.append(
                MetaTeamRow(
                    team_id=team.tournament_team_id,
                    tournament_id=team.tournament_id,
                    tournament_name=tournament.name if tournament else team.tournament_id,
                    event_date=tournament.event_date if tournament else team.created_at,
                    regulation=tournament.format_regulation if tournament else "",
                    game_platform=tournament.game_platform if tournament else "",
                    organizer=tournament.organizer if tournament else "",
                    location=tournament.location if tournament else "",
                    total_players=tournament.total_players if tournament else 0,
                    source_url=tournament.source_url if tournament else None,
                    event_tier=tournament.event_tier if tournament else "community",
                    player_name=team.player_name,
                    placement=team.placement,
                    standing_label=team.standing_label,
                    pokepast_url=team.pokepast_url,
                    showdown_text=team.showdown_text,
                    members=tuple(
                        MetaMemberRow(
                            slot=m.slot_position,
                            species_name=m.species_name,
                            canonical_id=m.canonical_id,
                            sprite_url=get_pokemon_sprite_url(m.canonical_id or m.species_name),
                            is_legal=(not legality_known) or _is_legal(m.species_name, m.canonical_id, lookup),
                            in_box=in_box[index],
                        )
                        for index, m in enumerate(members)
                    ),
                    legality_known=legality_known,
                    missing_count=(sum(1 for flag in in_box if flag is False) if owned is not None else None),
                )
            )
        return rows

    def meta_summary(self) -> MetaSummary:
        team_count = self.session.exec(select(func.count()).select_from(TournamentTeamRecord)).one()
        event_count = self.session.exec(
            select(func.count(func.distinct(TournamentTeamRecord.tournament_id)))
        ).one()
        synced_at = self.session.exec(
            select(func.max(TournamentRecord.updated_at)).where(TournamentRecord.standings_synced == True)  # noqa: E712
        ).one()
        return MetaSummary(team_count=int(team_count or 0), event_count=int(event_count or 0), synced_at=synced_at)

    def get_top_partners(
        self,
        species_identifier: str,
        limit: int = 6,
        regulation_filter: str | None = None,
        min_sample_teams: int = _DEFAULT_MIN_SAMPLE_TEAMS,
        battle_format: str | None = "doubles",
    ) -> list[PartnerRecommendation]:
        return self.synergy_service.get_top_partners(
            species_identifier=species_identifier,
            limit=limit,
            regulation_filter=regulation_filter,
            min_sample_teams=min_sample_teams,
            battle_format=battle_format,
        )

    def sync(
        self,
        force: bool = False,
        max_age_days: int = 365,
        include_official: bool = True,
        on_progress: Any = None,
    ) -> dict[str, Any]:
        """Syncs live tournament data from Limitless and Victory Road into local SQLite DB."""
        from .tournament_sync_service import sync_tournaments

        return sync_tournaments(
            self.session,
            force=force,
            max_age_days=max_age_days,
            include_official=include_official,
            on_progress=on_progress,
        )


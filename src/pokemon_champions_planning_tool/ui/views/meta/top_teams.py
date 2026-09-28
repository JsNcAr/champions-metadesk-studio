"""Meta › Top teams: teams grouped by lineup, with usage share, best finish, top-cut rate,
trend and each slot's item spread. Flet-free.

Two teams are the same lineup when they field the same six Pokémon and the same Mega
Evolutions — a Choice Scarf Tyranitar team and a Life Orb Tyranitar team are one team; a
Mega Tyranitar team is another. Tournament rosters never store a Mega form directly (a
member's ``canonical_id`` is always the base species): a slot counts as its Mega only when
its held item is that species' stone, so the "member key" that decides sameness comes from
``Catalogs.mega_for_item``.
"""

from __future__ import annotations

from collections import Counter, defaultdict
from collections.abc import Sequence
from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import Any
from uuid import UUID

from ....domain.stat_calc import format_points
from ....services.tournament_service import TopTeamMemberRow

MIN_TEAMS_DEFAULT = 2
TOP_CUT_PLACEMENT = 8            # "Top 8", the app's own shorthand for a strong finish (store.py PLACEMENT_OPTIONS)
TREND_WINDOW_DAYS = 30
TREND_MIN_SAMPLE = 20            # teams needed in each trend window for the swing to mean anything


def member_key(canonical_id: str, item: str | None, catalogs: Any) -> str:
    """The species id one roster slot counts as: its Mega form when the held item is
    that species' stone, its own id otherwise (an id already a Mega form is kept)."""
    cid = (canonical_id or "").strip().lower()
    if not cid:
        return cid
    mega = catalogs.mega_for_item(cid, item) if item else None
    return (mega or cid).lower()


@dataclass(frozen=True)
class TopTeamMember:
    """One lineup slot, detached from any one team."""

    slot: int
    key: str                 # member_key: species or Mega form id
    item: str | None
    ability: str | None
    nature: str | None
    moves: tuple[str, ...]

    @property
    def canonical_id(self) -> str:
        """Alias for ``key``: lets a ``TopTeamEntry`` duck-type as a ``MetaTeamRow`` for
        Meta's ``_calc_vs``/``rivals_from_meta_row``, which read a roster member's id
        under this name."""
        return self.key

    @property
    def display_name(self) -> str:
        """A readable fallback for messages; the species catalogue's own name is used
        wherever one is available (this is only the "not in the catalogue" case)."""
        return self.key.replace("-", " ").title()


@dataclass(frozen=True)
class TopTeamEntry:
    """One team belonging to a lineup group: enough to reuse Meta's Import, Save as
    rival preset and Damage calc actions (``rivals_from_meta_row`` and friends only
    read ``showdown_text``, ``player_name``, ``tournament_name`` and each member's
    ``canonical_id``, which this duck-types) without a second database session."""

    team_id: UUID
    tournament_id: str
    tournament_name: str
    event_date: datetime
    player_name: str
    placement: int
    standing_label: str
    pokepast_url: str | None
    showdown_text: str
    members: tuple[TopTeamMember, ...]

    @property
    def is_top_cut(self) -> bool:
        return self.placement <= TOP_CUT_PLACEMENT


@dataclass(frozen=True)
class BestFinish:
    placement: int
    standing_label: str
    tournament_name: str
    event_date: datetime
    player_name: str


@dataclass(frozen=True)
class MemberSpread:
    """How one lineup slot's set varies across the group's teams."""

    key: str
    items: tuple[tuple[str, float], ...]      # (item name or "No item", share), most used first
    ability: str | None
    nature: str | None
    moves: tuple[tuple[str, float], ...]      # up to 4 moves, most used first, (name, share of teams running it)


@dataclass(frozen=True)
class TopTeam:
    key: tuple[str, ...]              # sorted member keys — the group's identity
    members: tuple[str, ...]          # member keys in display order (the best finish's slots)
    count: int
    share: float                      # count / TopTeamsResult.total_teams
    best: BestFinish
    top_cut: float                    # share of this group's teams that placed top TOP_CUT_PLACEMENT
    trend: float | None               # percentage-point change, last 30 days vs the 30 before; None: too few teams
    teams: tuple[TopTeamEntry, ...]   # best placement first
    spread: dict[str, MemberSpread]   # member_key -> its item/ability/nature spread


@dataclass(frozen=True)
class TopTeamsResult:
    total_teams: int             # complete (6-member) teams matching the filters
    incomplete_teams: int        # filtered-in teams with fewer than 6 members, excluded from grouping
    teams: tuple[TopTeam, ...]   # most used first, then best placement


def _entries_by_team(rows: Sequence[TopTeamMemberRow], catalogs: Any) -> dict[UUID, TopTeamEntry]:
    by_team: dict[UUID, list[TopTeamMemberRow]] = defaultdict(list)
    for row in rows:
        by_team[row.team_id].append(row)
    entries: dict[UUID, TopTeamEntry] = {}
    for team_id, members in by_team.items():
        ordered = sorted(members, key=lambda m: m.slot)
        first = ordered[0]
        entries[team_id] = TopTeamEntry(
            team_id=team_id, tournament_id=first.tournament_id, tournament_name=first.tournament_name,
            event_date=first.event_date, player_name=first.player_name, placement=first.placement,
            standing_label=first.standing_label, pokepast_url=first.pokepast_url, showdown_text=first.showdown_text,
            members=tuple(
                TopTeamMember(slot=m.slot, key=member_key(m.canonical_id, m.item, catalogs), item=m.item, ability=m.ability, nature=m.nature, moves=m.moves)
                for m in ordered
            ),
        )
    return entries


def _spread(teams: Sequence[TopTeamEntry]) -> dict[str, MemberSpread]:
    by_key: dict[str, list[TopTeamMember]] = defaultdict(list)
    for e in teams:
        for m in e.members:
            by_key[m.key].append(m)
    out: dict[str, MemberSpread] = {}
    for key, members in by_key.items():
        n = len(members)
        item_counts = Counter(m.item or "No item" for m in members)
        items = tuple(sorted(((name, count / n) for name, count in item_counts.items()), key=lambda t: -t[1]))
        ability = Counter(m.ability for m in members if m.ability).most_common(1)
        nature = Counter(m.nature for m in members if m.nature).most_common(1)
        move_counts: Counter = Counter()
        for m in members:
            move_counts.update(m.moves)
        moves = tuple((name, count / n) for name, count in move_counts.most_common(4))
        out[key] = MemberSpread(key=key, items=items, ability=ability[0][0] if ability else None, nature=nature[0][0] if nature else None, moves=moves)
    return out


def group_teams(rows: Sequence[TopTeamMemberRow], catalogs: Any, *, min_teams: int = MIN_TEAMS_DEFAULT) -> TopTeamsResult:
    """Group the roster rows for one set of Meta filters into lineups.

    ``rows`` is every roster slot of every matching team (``TournamentService.
    team_members_for_filters``'s result); order does not matter, they are regrouped by
    team id here. Only lineups brought by at least ``min_teams`` teams are kept, but every
    complete team counts toward ``total_teams`` and the trend windows.
    """
    entries = _entries_by_team(rows, catalogs)
    complete = [e for e in entries.values() if len(e.members) == 6]
    incomplete = len(entries) - len(complete)
    total = len(complete)
    if total == 0:
        return TopTeamsResult(total_teams=0, incomplete_teams=incomplete, teams=())

    newest = max(e.event_date for e in complete)
    window1_start = newest - timedelta(days=TREND_WINDOW_DAYS)
    window2_start = newest - timedelta(days=2 * TREND_WINDOW_DAYS)
    recent_total = sum(1 for e in complete if window1_start <= e.event_date <= newest)
    prior_total = sum(1 for e in complete if window2_start <= e.event_date < window1_start)
    trend_ready = recent_total >= TREND_MIN_SAMPLE and prior_total >= TREND_MIN_SAMPLE

    by_lineup: dict[tuple[str, ...], list[TopTeamEntry]] = defaultdict(list)
    for e in complete:
        by_lineup[tuple(sorted(m.key for m in e.members))].append(e)

    groups: list[TopTeam] = []
    for key, teams in by_lineup.items():
        if len(teams) < min_teams:
            continue
        teams = sorted(teams, key=lambda e: (e.placement, e.event_date))
        best_entry = teams[0]
        best = BestFinish(placement=best_entry.placement, standing_label=best_entry.standing_label,
                          tournament_name=best_entry.tournament_name, event_date=best_entry.event_date, player_name=best_entry.player_name)
        top_cut = sum(1 for e in teams if e.is_top_cut) / len(teams)
        trend = None
        if trend_ready:
            recent_group = sum(1 for e in teams if window1_start <= e.event_date <= newest)
            prior_group = sum(1 for e in teams if window2_start <= e.event_date < window1_start)
            trend = (recent_group / recent_total * 100) - (prior_group / prior_total * 100)
        groups.append(TopTeam(
            key=key, members=tuple(m.key for m in best_entry.members), count=len(teams), share=len(teams) / total,
            best=best, top_cut=top_cut, trend=trend, teams=tuple(teams), spread=_spread(teams),
        ))

    groups.sort(key=lambda g: (-g.count, g.best.placement))
    return TopTeamsResult(total_teams=total, incomplete_teams=incomplete, teams=tuple(groups))


def _points_by_key(teams: Sequence[TopTeamEntry]) -> dict[str, Counter]:
    """The most common stat-point spread per lineup slot, parsed from each team's own
    paste. A paste that fails to parse, or a slot with no points line, is skipped."""
    from ....services.showdown_service import parse_showdown_text

    counts: dict[str, Counter] = defaultdict(Counter)
    for e in teams:
        try:
            parsed_slots = parse_showdown_text(e.showdown_text).slots
        except Exception:  # noqa: BLE001 - a paste that does not parse just means no points for it
            continue
        for index, m in enumerate(e.members):
            if index >= len(parsed_slots):
                continue
            points = parsed_slots[index].points
            if points:
                counts[m.key][tuple(sorted(points.items()))] += 1
    return counts


def consensus_paste(team: TopTeam, catalogs: Any) -> str | None:
    """Showdown text for the group's most common set: each lineup slot with its most
    used item, ability, nature, top-4 moves and (when any of the group's pastes has one)
    its most common stat-point spread. None when no member is in the species catalogue.

    Parsing the group's pastes for points is the one part not already folded into
    ``spread``/``group_teams``: call this only when the text is actually needed (Import,
    Save as rival, Copy), on a worker, and cache the result by the group's key.
    """
    move_counts: dict[str, Counter] = defaultdict(Counter)
    for e in team.teams:
        for m in e.members:
            move_counts[m.key].update(m.moves)
    points_by_key = _points_by_key(team.teams)

    blocks: list[str] = []
    for key in team.members:
        species = catalogs.species_for(key)
        if species is None:
            continue
        spread = team.spread.get(key)
        item = spread.items[0][0] if spread and spread.items else None
        lines = [species.name if not item or item == "No item" else f"{species.name} @ {item}"]
        if spread and spread.ability:
            lines.append(f"Ability: {spread.ability}")
        best_points = points_by_key.get(key, Counter()).most_common(1)
        if best_points:
            spread_text = format_points(dict(best_points[0][0]))
            if spread_text:
                lines.append(f"EVs: {spread_text}")
        if spread and spread.nature:
            lines.append(f"{spread.nature.strip().title()} Nature")
        for name, _n in move_counts.get(key, Counter()).most_common(4):
            lines.append(f"- {name}")
        blocks.append("\n".join(lines))
    return "\n\n".join(blocks) if blocks else None


__all__ = [
    "MIN_TEAMS_DEFAULT", "TOP_CUT_PLACEMENT", "TREND_MIN_SAMPLE", "TREND_WINDOW_DAYS",
    "BestFinish", "MemberSpread", "TopTeam", "TopTeamEntry", "TopTeamMember", "TopTeamsResult",
    "consensus_paste", "group_teams", "member_key",
]

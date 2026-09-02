"""Tournament data sync service.

Orchestrates automated data ingestion from:
1. Play Limitless API (LimitlessProvider) — community VGC/Champions meta datasets
2. Victory Road Pro (VictoryRoadProvider, PokepastProvider, VRPasteProvider) — official premier events

Standardizes and normalizes all ingested data into SQLModel entities:
- TournamentRecord
- TournamentTeamRecord
- TournamentTeamMemberRecord
"""

from __future__ import annotations

import threading
import time
from collections.abc import Callable
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from sqlmodel import Session, select

from ..config import (
    LIMITLESS_MAX_AGE_DAYS,
    VICTORY_ROAD_CALENDAR_MAX_AGE_HOURS,
    VICTORY_ROAD_MAX_PLACEMENT,
    VICTORY_ROAD_PAGES_PER_RUN,
    VICTORY_ROAD_RESULTS_GRACE_DAYS,
    LIMITLESS_STANDINGS_PER_RUN,
    RECENT_EVENT_GRACE_DAYS,
    STARTUP_SYNC_MIN_INTERVAL_HOURS,
)
from ..domain.event_tier import classify_event_tier
from ..domain.pokemon_identity import base_canonical_id, format_api_name, normalize_format_regulation
from ..infrastructure.database.models import (
    TournamentRecord,
    TournamentTeamRecord,
    TournamentTeamMemberRecord,
)
from ..infrastructure.database.database import get_session
from ..infrastructure.database.repositories import TournamentRepository
from ..infrastructure.providers import (
    LimitlessProvider,
    PokepastProvider,
    VictoryRoadProvider,
    VRPasteProvider,
    LimitlessStanding,
    VRPasteResult,
)
from ..infrastructure.providers.victory_road_provider import OFFICIAL_EVENT_SLUGS

ProgressCallback = Callable[["SyncProgress"], None]


@dataclass(frozen=True)
class SyncProgress:
    """A snapshot of a running sync, for the UI.

    ``phase`` is one of listing / standings / official / pastes / done / error / busy.
    ``total`` is 0 when the step has no known length.
    """

    phase: str
    message: str
    done: int = 0
    total: int = 0
    teams_added: int = 0

    @property
    def fraction(self) -> float | None:
        if self.total <= 0:
            return None
        return max(0.0, min(1.0, self.done / self.total))

    @property
    def running(self) -> bool:
        return self.phase not in ("done", "error", "busy")


def _report(cb: ProgressCallback | None, phase: str, message: str, *, done: int = 0, total: int = 0, teams: int = 0) -> None:
    if cb is None:
        return
    try:
        cb(SyncProgress(phase=phase, message=message, done=done, total=total, teams_added=teams))
    except Exception:  # noqa: BLE001 - progress reporting must never break a sync
        pass


# Only one sync at a time per process: the launch sync and a "Sync now" pressed during
# it would otherwise both write the same tables and fight over the SQLite lock.
_SYNC_LOCK = threading.Lock()


def sync_in_progress() -> bool:
    return _SYNC_LOCK.locked()


# Standings requests issued per sync run. Limitless allows 50 requests per 5 minutes; the
# provider also stops on its own when the window's budget is nearly spent, so a run
# drains part of the backlog and the next run continues.
_MAX_STANDINGS_PER_RUN = LIMITLESS_STANDINGS_PER_RUN
# Pause between paste fetches for official events (Poképaste / VRPaste are separate
# hosts from Limitless, but they are still someone else's servers).
_PASTE_DELAY_S = 0.25
# Patchable in tests: event pages read per run.
_VR_PAGES_PER_RUN = VICTORY_ROAD_PAGES_PER_RUN
_VR_CALENDAR_STATE_KEY = "victory_road.calendar_checked_at"


def _assemble_showdown_from_limitless(standing: LimitlessStanding) -> str:
    """Assembles Showdown format string from Limitless standing members."""
    lines: list[str] = []
    for member in standing.members:
        header = member.display_name
        if member.item:
            header += f" @ {member.item}"
        lines.append(header)

        if member.ability:
            lines.append(f"Ability: {member.ability}")

        lines.append("Level: 50")

        if member.nature:
            lines.append(f"{member.nature} Nature")

        for move in member.moves:
            if move:
                lines.append(f"- {move}")

        lines.append("")  # Blank line separator between mons

    return "\n".join(lines).strip()


def _assemble_showdown_from_vrpaste(vr_result: VRPasteResult) -> str:
    """Assembles Showdown format string from VRPaste members."""
    lines: list[str] = []
    for member in vr_result.members:
        header = member.display_name
        if member.item:
            header += f" @ {member.item}"
        lines.append(header)

        if member.ability:
            lines.append(f"Ability: {member.ability}")

        lines.append("Level: 50")

        if member.nature:
            lines.append(f"{member.nature} Nature")

        for move in member.moves:
            if move:
                lines.append(f"- {move}")

        lines.append("")

    return "\n".join(lines).strip()


def _moves_by_slot(showdown_text: str) -> list[list[str]]:
    """Move names per Pokémon block, in paste order."""
    out: list[list[str]] = []
    current: list[str] | None = None
    for raw in showdown_text.splitlines():
        line = raw.strip()
        if not line:
            current = None
            continue
        if current is None:
            current = []
            out.append(current)
        if line.startswith("-"):
            move = line[1:].strip()
            if move:
                current.append(move)
    return out


def _parse_showdown_members(showdown_text: str) -> list[tuple[str, str]]:
    """Extract (canonical_id, display_name) pairs from Showdown-format paste text.

    Showdown format: first non-blank line of each block is either
      "Species Name" or "Species Name @ Item" or "Nickname (Species) @ Item"

    Lines we skip: move lines (start with -), field lines (contain ':'),
    'Level N', 'EVs:', 'IVs:', 'Nature', 'Shiny:'.
    """
    members: list[tuple[str, str]] = []
    seen_blanks = True  # start in "fresh block" mode

    skip_prefixes = ("-", "ability:", "level:", "evs:", "ivs:", "shiny:", "tera type:")
    skip_suffixes = ("nature",)

    for raw_line in showdown_text.splitlines():
        line = raw_line.strip()

        if not line:
            seen_blanks = True
            continue

        # Skip lines that are move/field entries
        lower = line.lower()
        if any(lower.startswith(p) for p in skip_prefixes):
            seen_blanks = False
            continue
        if any(lower.endswith(s) for s in skip_suffixes):
            seen_blanks = False
            continue

        # First substantive line of a new block is the species line
        if seen_blanks:
            seen_blanks = False
            # Strip item: "Charizard @ Charizardite Y" -> "Charizard"
            species_part = line.split("@")[0].strip()
            # Handle nickname: "Nickname (Species)" -> "Species"
            import re as _re
            bracket = _re.search(r"\(([^)]+)\)", species_part)
            if bracket:
                species_part = bracket.group(1).strip()
            if species_part:
                canonical = format_api_name(species_part)
                members.append((canonical, species_part))

    return members


def _sync_limitless(
    session: Session,
    repo: TournamentRepository,
    force: bool,
    max_age_days: int,
    limitless_provider: LimitlessProvider | None = None,
    on_progress: ProgressCallback | None = None,
) -> dict:
    """Ingests Limitless community tournaments and team decklists.

    Standings requests are capped per run to respect the API rate limit, so the
    tournaments left over form a backlog. Every tournament row is written with
    ``standings_synced=False`` and only flipped to True once its standings request
    actually succeeds, which is what lets later runs drain the backlog instead of
    skipping those tournaments forever as "already known".
    """
    provider = limitless_provider or LimitlessProvider()
    known_ids = {t_id.removeprefix("limitless-") for t_id in repo.list_tournament_ids(source_prefix="limitless-")}
    _report(on_progress, "listing", "Listing Limitless tournaments…")
    # The listing stops at the first page of already-known tournaments (unless forced,
    # when metadata such as player counts is refreshed all the way back).
    tournaments = provider.fetch_champions_tournaments(
        max_age_days=max_age_days, known_ids=None if force else known_ids
    )

    fetched_count = len(tournaments)
    teams_added = 0
    skipped_count = 0
    now = datetime.now(timezone.utc)
    grace = timedelta(days=RECENT_EVENT_GRACE_DAYS)
    window_start = now - timedelta(days=max_age_days)

    # Only tournaments inside the sync window are worth standings requests; a pending
    # event that has aged past the window is simply left alone.
    pending_ids = repo.list_tournament_ids_pending_standings(source_prefix="limitless-", since=window_start)

    # Persist metadata for every listed tournament and decide which still need
    # standings. Tournaments are returned newest-first, so the backlog drains from
    # the most recent events downwards.
    needs_standings: list[str] = []
    listed_dates: dict[str, datetime] = {}
    for t_dto in tournaments:
        t_id = f"limitless-{t_dto.id}"
        existing = repo.get_tournament(t_id)
        listed_dates[t_dto.id] = t_dto.date

        if existing and existing.standings_synced and not force:
            skipped_count += 1
            continue

        norm_format = normalize_format_regulation(t_dto.format_code)
        t_record = TournamentRecord(
            tournament_id=t_id,
            name=t_dto.name,
            event_date=t_dto.date,
            format_regulation=norm_format,
            game_platform="Pokémon Champions",
            organizer=t_dto.organizer,
            location="Limitless Online",
            total_players=t_dto.player_count,
            source_url=f"https://play.limitlesstcg.com/tournament/{t_dto.id}",
            event_tier=classify_event_tier(t_dto.name, t_dto.organizer),
        )
        repo.upsert_tournament(t_record)
        if existing is None or t_id in pending_ids or force:
            needs_standings.append(t_dto.id)

    # Tournaments listed by an earlier run whose standings are still pending are part
    # of the backlog even though the incremental listing no longer returns them.
    listed_now = set(needs_standings)
    for t_id in sorted(pending_ids):
        raw = t_id.removeprefix("limitless-")
        if raw not in listed_now:
            needs_standings.append(raw)
            listed_now.add(raw)

    # An event that has not started has no standings to fetch; requesting them only
    # spends the rate budget. It stays pending and is fetched once its date has passed.
    def _has_started(raw_id: str) -> bool:
        date = listed_dates.get(raw_id)
        if date is None:
            record = repo.get_tournament(f"limitless-{raw_id}")
            date = record.event_date if record else None
        if date is None:
            return True
        if date.tzinfo is None:
            date = date.replace(tzinfo=timezone.utc)
        return date <= now

    not_started = [raw for raw in needs_standings if not _has_started(raw)]
    needs_standings = [raw for raw in needs_standings if raw not in set(not_started)]

    planned = min(len(needs_standings), _MAX_STANDINGS_PER_RUN)
    _report(on_progress, "standings", f"{fetched_count:,} tournaments listed · {len(needs_standings):,} awaiting standings", done=0, total=planned)

    # Batch-fetch standings with rate-limiting. Tournaments not reached this run keep
    # standings_synced=False and are retried by the next run.
    standings_batch = provider.fetch_standings_batch(
        tournament_ids=needs_standings,
        max_placement=None,  # All placements
        max_requests=_MAX_STANDINGS_PER_RUN,
        on_progress=lambda i, n, _tid: _report(on_progress, "standings", f"Fetching standings {i} of {n}", done=i - 1, total=n),
    )

    backlog_remaining = len(needs_standings) - len(standings_batch) + len(not_started)
    retry_recent = 0

    for index, (raw_id, standings_list) in enumerate(standings_batch.items(), start=1):
        t_id = f"limitless-{raw_id}"
        # Replace rather than append, so a forced re-sync cannot duplicate rosters.
        repo.delete_teams_for_tournament(t_id)
        entries: list[tuple[TournamentTeamRecord, list[TournamentTeamMemberRecord]]] = []

        for s in standings_list:
            showdown_txt = _assemble_showdown_from_limitless(s)
            if not showdown_txt:
                continue

            team_record = TournamentTeamRecord(
                tournament_id=t_id,
                player_name=s.player_handle,
                placement=s.placement,
                standing_label=f"Place #{s.placement}",
                showdown_text=showdown_txt,
                source_dataset="limitless_api",
                sync_source="limitless",
            )

            # canonical_id from Limitless API is already the PokéAPI slug
            members: list[TournamentTeamMemberRecord] = []
            for idx, m in enumerate(s.members, start=1):
                # Use api canonical_id directly; fall back to format_api_name on display_name
                canon_id = m.canonical_id if m.canonical_id else format_api_name(m.display_name)
                members.append(
                    TournamentTeamMemberRecord(
                        slot_position=idx,
                        canonical_id=canon_id,
                        species_name=m.display_name,
                        base_canonical_id=base_canonical_id(canon_id),
                        moves=[mv for mv in m.moves if mv],
                    )
                )

            entries.append((team_record, members))

        teams_added += repo.save_teams(entries)
        _report(on_progress, "standings", f"Saved standings {index} of {len(standings_batch)}", done=index, total=len(standings_batch), teams=teams_added)

        # The request succeeded, so this tournament leaves the backlog even when the
        # event published no decklists at all — otherwise it would be retried forever.
        # The one exception is an event that ran in the last few days: decklists are
        # published when it finishes, so an empty answer that soon is "not yet".
        date = listed_dates.get(raw_id)
        if date is not None and date.tzinfo is None:
            date = date.replace(tzinfo=timezone.utc)
        if not standings_list and date is not None and now - date < grace:
            retry_recent += 1
            backlog_remaining += 1
            continue
        repo.mark_standings_synced(t_id, True)

    return {
        "fetched": fetched_count,
        "added": teams_added,
        "skipped": skipped_count,
        "standings_synced": len(standings_batch) - retry_recent,
        "backlog_remaining": backlog_remaining,
        "not_started": len(not_started),
        "requests": getattr(provider, "requests_made", None),
        "rate_remaining": getattr(provider, "rate_remaining", None),
    }



def _vr_meta_from_record(record: TournamentRecord) -> dict:
    slug = record.tournament_id.removeprefix("vr-")
    registry = next((m for m in OFFICIAL_EVENT_SLUGS if m["slug"] == slug), {})
    date = record.event_date
    return {
        "slug": slug,
        "name": record.name,
        "date": registry.get("date") or (date.strftime("%Y-%m-%d") if date else ""),
        "game": record.game_platform or registry.get("game", "Pokémon Champions"),
        "format": registry.get("format") or record.format_regulation or "Regulation M-A",
        "location": record.location or registry.get("location", ""),
    }


def _register_official_event(repo: TournamentRepository, meta: dict, *, event_date: datetime | None = None) -> bool:
    """Store a discovered or registry event as pending; never touches an existing row."""
    date = event_date
    if date is None and meta.get("date"):
        try:
            date = datetime.fromisoformat(f"{meta['date']}T00:00:00+00:00")
        except ValueError:
            date = None
    return repo.add_tournament_if_missing(
        TournamentRecord(
            tournament_id=f"vr-{meta['slug']}",
            name=meta["name"],
            event_date=date or datetime.now(timezone.utc),
            format_regulation=normalize_format_regulation(meta.get("format", "Regulation M-A")),
            game_platform=meta.get("game", "Pokémon Champions"),
            organizer="Play! Pokémon Premier Events",
            location=meta.get("location", ""),
            total_players=0,
            source_url=f"https://victoryroad.pro/{meta['slug']}/",
            standings_synced=False,
            event_tier=classify_event_tier(meta["name"], "Play! Pokémon Premier Events"),
        )
    )


def _calendar_is_stale(repo: TournamentRepository, now: datetime) -> bool:
    stamp = repo.get_state(_VR_CALENDAR_STATE_KEY)
    if not stamp:
        return True
    try:
        checked = datetime.fromisoformat(stamp)
    except ValueError:
        return True
    if checked.tzinfo is None:
        checked = checked.replace(tzinfo=timezone.utc)
    return now - checked > timedelta(hours=VICTORY_ROAD_CALENDAR_MAX_AGE_HOURS)


def _sync_victory_road(
    session: Session,
    repo: TournamentRepository,
    force: bool,
    vr_provider: VictoryRoadProvider | None = None,
    pokepast_provider: PokepastProvider | None = None,
    vrpaste_provider: VRPasteProvider | None = None,
    on_progress: ProgressCallback | None = None,
) -> dict:
    """Ingests official Play! Pokémon events from Victory Road.

    Discovery: the season calendar pages (this season and the next) list every event
    with its date, name, city and format; new ones are stored as pending. The static
    registry seeds the same way, so the app works before the first calendar read.
    Reading: at most VICTORY_ROAD_PAGES_PER_RUN finished, pending events are read per
    run, newest first, and the top VICTORY_ROAD_MAX_PLACEMENT sheets ingested. An event
    page without sheets is retried while the event ended within the grace window; a
    partly ingested event stays pending and only its missing sheets are fetched.
    """
    vr = vr_provider or VictoryRoadProvider()
    pokepast = pokepast_provider or PokepastProvider()
    vrpaste = vrpaste_provider or VRPasteProvider()
    now = datetime.now(timezone.utc)

    # -- discovery -------------------------------------------------------------------------
    discovered = 0
    calendar_checked = False
    if force or _calendar_is_stale(repo, now):
        _report(on_progress, "official", "Checking Victory Road's season calendar…")
        for season in (now.year, now.year + 1):
            try:
                events = vr.fetch_season_calendar(season)
            except Exception as exc:  # noqa: BLE001 - discovery is best-effort
                print(f"⚠️ Victory Road calendar {season} unavailable: {exc}")
                continue
            calendar_checked = True
            for ev in events or []:
                if _register_official_event(repo, ev.to_meta(), event_date=ev.date):
                    discovered += 1
        if calendar_checked:
            repo.set_state(_VR_CALENDAR_STATE_KEY, now.isoformat())
    for meta in OFFICIAL_EVENT_SLUGS:
        if _register_official_event(repo, meta):
            discovered += 1

    # -- queue -------------------------------------------------------------------------------
    queue = repo.list_official_events(ended_before=now, pending_only=not force)
    candidates = queue[:_VR_PAGES_PER_RUN]
    skipped_count = len(queue) - len(candidates)
    fetched_count = 0
    added_count = 0
    teams_added = 0
    paste_errors = 0
    no_results = 0
    grace = timedelta(days=VICTORY_ROAD_RESULTS_GRACE_DAYS)

    for index, record in enumerate(candidates, start=1):
        t_id = record.tournament_id
        _report(on_progress, "official", f"Reading {record.name} ({index} of {len(candidates)})…", done=index - 1, total=len(candidates), teams=teams_added)
        ev = vr.fetch_event(_vr_meta_from_record(record), masters_only=True)
        if ev is None:
            event_date = record.event_date if record.event_date.tzinfo else record.event_date.replace(tzinfo=timezone.utc)
            if now - event_date > grace:
                # Ended long ago and still no sheets: stop asking.
                repo.mark_standings_synced(t_id, True)
            no_results += 1
            continue
        fetched_count += 1

        norm_format = normalize_format_regulation(ev.format_regulation)
        t_record = TournamentRecord(
            tournament_id=t_id,
            name=record.name,
            event_date=record.event_date,
            format_regulation=norm_format if norm_format != "Unknown" else record.format_regulation,
            game_platform=ev.game_platform or record.game_platform,
            organizer="Play! Pokémon Premier Events",
            location=record.location or ev.location,
            total_players=ev.total_players,
            source_url=f"https://victoryroad.pro/{ev.slug}/",
            event_tier=classify_event_tier(record.name, "Play! Pokémon Premier Events"),
        )
        repo.upsert_tournament(t_record)
        if force:
            # Replace rather than append, so a forced re-sync cannot duplicate rosters.
            repo.delete_teams_for_tournament(t_id)
            already_stored: set[str] = set()
        else:
            # Resume: keep the teams a previous run managed to fetch.
            already_stored = repo.list_paste_urls_for_tournament(t_id)
        event_errors = 0
        entries: list[tuple[TournamentTeamRecord, list[TournamentTeamMemberRecord]]] = []
        wanted = [st for st in ev.standings if st.paste_id and st.placement <= VICTORY_ROAD_MAX_PLACEMENT and not (st.paste_url and st.paste_url in already_stored)]

        for st in wanted:
            _report(on_progress, "pastes", f"{record.name}: fetching team {len(entries) + event_errors + 1} of {len(wanted)}", done=len(entries) + event_errors, total=len(wanted), teams=teams_added)

            showdown_text = ""
            members_raw: list[tuple[str, str]] = []  # (canonical_id, species_name)

            if st.paste_provider == "pokepast":
                try:
                    pdata = _with_one_retry(lambda: pokepast.fetch_by_id(st.paste_id))
                    showdown_text = pdata.get("paste", "")
                    members_raw = _parse_showdown_members(showdown_text)
                except Exception as exc:
                    print(f"⚠️ Could not fetch Pokepast '{st.paste_id}' for {st.player_name}: {exc}")
                    paste_errors += 1
                    event_errors += 1
                    continue

            elif st.paste_provider == "vrpaste":
                try:
                    vr_data = _with_one_retry(lambda: vrpaste.fetch_by_id(st.paste_id))
                    showdown_text = _assemble_showdown_from_vrpaste(vr_data)
                    for m in vr_data.members:
                        members_raw.append((format_api_name(m.display_name), m.display_name))
                except Exception as exc:
                    print(f"⚠️ Could not fetch VRPaste '{st.paste_id}' for {st.player_name}: {exc}")
                    paste_errors += 1
                    event_errors += 1
                    continue
            if _PASTE_DELAY_S:
                time.sleep(_PASTE_DELAY_S)

            if not showdown_text:
                continue

            team_record = TournamentTeamRecord(
                tournament_id=t_id,
                player_name=st.player_name,
                placement=st.placement,
                standing_label=f"Place #{st.placement}" if st.placement > 0 else "Participant",
                pokepast_url=st.paste_url,
                showdown_text=showdown_text,
                source_dataset="victory_road_pro",
                sync_source="victory_road",
                division=st.division,
            )

            member_moves = _moves_by_slot(showdown_text)
            members: list[TournamentTeamMemberRecord] = [
                TournamentTeamMemberRecord(
                    slot_position=pos,
                    canonical_id=cid,
                    species_name=sname,
                    base_canonical_id=base_canonical_id(cid),
                    moves=member_moves[pos - 1] if pos - 1 < len(member_moves) else [],
                )
                for pos, (cid, sname) in enumerate(members_raw[:6], start=1)
            ]

            entries.append((team_record, members))

        teams_added += repo.save_teams(entries)
        added_count += 1
        # Only a complete event leaves the backlog; a partial one is re-read next run
        # and just the missing pastes are fetched.
        repo.mark_standings_synced(t_id, event_errors == 0)

    return {
        "fetched": fetched_count,
        "added": teams_added,
        "events_ingested": added_count,
        "skipped": skipped_count,
        "paste_errors": paste_errors,
        "discovered": discovered,
        "no_results": no_results,
        "queued": max(0, len(queue) - added_count - no_results),
    }


def _with_one_retry(call, pause_s: float = 1.0):
    """Run ``call``; on failure wait briefly and try once more (paste hosts hiccup)."""
    try:
        return call()
    except Exception:  # noqa: BLE001 - retried once, then surfaced by the caller
        time.sleep(pause_s)
        return call()


def sync_tournaments(
    session: Session,
    force: bool = False,
    max_age_days: int = LIMITLESS_MAX_AGE_DAYS,
    include_official: bool = True,
    limitless_provider: LimitlessProvider | None = None,
    vr_provider: VictoryRoadProvider | None = None,
    pokepast_provider: PokepastProvider | None = None,
    vrpaste_provider: VRPasteProvider | None = None,
    on_progress: ProgressCallback | None = None,
) -> dict:
    """Master sync function ingesting tournament data into local SQLite DB.

    Flow:
      1. Fetch Limitless community datasets.
      2. Fetch Victory Road official premier event datasets.
      3. Return execution metrics summary dict.

    Only one sync runs per process; a second call while one is running returns a zero
    result with status "busy". ``on_progress`` receives SyncProgress snapshots.
    """
    if not _SYNC_LOCK.acquire(blocking=False):
        _report(on_progress, "busy", "A sync is already running")
        return _skipped_result("busy")
    try:
        return _sync_tournaments_locked(
            session, force=force, max_age_days=max_age_days, include_official=include_official,
            limitless_provider=limitless_provider, vr_provider=vr_provider,
            pokepast_provider=pokepast_provider, vrpaste_provider=vrpaste_provider, on_progress=on_progress,
        )
    except BaseException as exc:
        _report(on_progress, "error", f"Sync failed: {exc}")
        raise
    finally:
        _SYNC_LOCK.release()


def _sync_tournaments_locked(
    session: Session,
    *,
    force: bool,
    max_age_days: int,
    include_official: bool,
    limitless_provider: LimitlessProvider | None,
    vr_provider: VictoryRoadProvider | None,
    pokepast_provider: PokepastProvider | None,
    vrpaste_provider: VRPasteProvider | None,
    on_progress: ProgressCallback | None,
) -> dict:
    repo = TournamentRepository(session)

    res_limitless = _sync_limitless(
        session=session,
        repo=repo,
        force=force,
        max_age_days=max_age_days,
        limitless_provider=limitless_provider,
        on_progress=on_progress,
    )

    res_official = {
        "fetched": 0,
        "added": 0,
        "events_ingested": 0,
        "skipped": 0,
        "paste_errors": 0,
    }
    if include_official:
        res_official = _sync_victory_road(
            session=session,
            repo=repo,
            force=force,
            vr_provider=vr_provider,
            pokepast_provider=pokepast_provider,
            vrpaste_provider=vrpaste_provider,
            on_progress=on_progress,
        )

    status = "synced"
    if res_limitless["fetched"] == 0 and res_official["fetched"] == 0 and res_limitless.get("standings_synced", 0) == 0:
        status = "offline"
    elif res_official.get("paste_errors", 0) > 0:
        status = "partial"

    result = {
        "limitless": res_limitless,
        "victory_road": res_official,
        "status": status,
    }
    _report(on_progress, "done", summarize_sync_result(result), teams=res_limitless["added"] + res_official["added"])
    return result


def summarize_sync_result(result: dict) -> str:
    """One line for a toast or caption: what a sync did and what is left."""
    lim = result.get("limitless") or {}
    vr = result.get("victory_road") or {}
    status = result.get("status")
    if status == "busy":
        return "A sync is already running"
    if status == "recent":
        return "Already synced recently"
    if status == "offline":
        return "Tournament sources unreachable"
    added = int(lim.get("added", 0) or 0) + int(vr.get("added", 0) or 0)
    events = int(lim.get("standings_synced", 0) or 0) + int(vr.get("events_ingested", 0) or 0)
    bits = [f"{added:,} new team{'s' if added != 1 else ''}", f"{events:,} event{'s' if events != 1 else ''}"]
    backlog = int(lim.get("backlog_remaining", 0) or 0) + int(vr.get("queued", 0) or 0)
    if backlog:
        bits.append(f"{backlog:,} still queued")
    if vr.get("discovered"):
        bits.append(f"{vr['discovered']} official event{'s' if vr['discovered'] != 1 else ''} discovered")
    if vr.get("paste_errors"):
        bits.append(f"{vr['paste_errors']} paste{'s' if vr['paste_errors'] != 1 else ''} failed")
    return "Synced · " + " · ".join(bits)


# ---------------------------------------------------------------------------
# Startup sync guard
# ---------------------------------------------------------------------------
# The GUI syncs on launch. In web mode main(page) runs once per browser tab, so the
# guard is process-wide: the first session syncs, later ones get None.
_STARTUP_SYNC_LOCK = threading.Lock()
_STARTUP_SYNC_DONE = False


def startup_sync_due(session: Session, min_interval_hours: float = STARTUP_SYNC_MIN_INTERVAL_HOURS) -> bool:
    """Whether the launch-time sync should run.

    It runs when nothing has ever synced, when the last successful sync is older than
    the interval, or when standings are still pending from an earlier run (the backlog
    drains a slice per run and the provider's rate budget keeps that safe).
    """
    repo = TournamentRepository(session)
    last = repo.last_standings_sync_at()
    if last is None:
        return True
    if last.tzinfo is None:
        last = last.replace(tzinfo=timezone.utc)
    if datetime.now(timezone.utc) - last >= timedelta(hours=min_interval_hours):
        return True
    window_start = datetime.now(timezone.utc) - timedelta(days=LIMITLESS_MAX_AGE_DAYS)
    return bool(repo.list_tournament_ids_pending_standings(since=window_start))


def _skipped_result(reason: str) -> dict:
    zero_l = {"fetched": 0, "added": 0, "skipped": 0, "standings_synced": 0, "backlog_remaining": 0}
    zero_v = {"fetched": 0, "added": 0, "events_ingested": 0, "skipped": 0, "paste_errors": 0}
    return {"limitless": zero_l, "victory_road": zero_v, "status": reason}


def sync_tournaments_once_per_process(
    *, min_interval_hours: float = STARTUP_SYNC_MIN_INTERVAL_HOURS, **kwargs
) -> dict | None:
    """Run ``sync_tournaments`` in a fresh session, at most once per process.

    Returns the sync result, ``None`` if a sync has already been started by this
    process, or a zero result with status "recent" when the last sync is fresh and
    no backlog is waiting. Safe to call from a worker thread.
    """
    global _STARTUP_SYNC_DONE
    with _STARTUP_SYNC_LOCK:
        if _STARTUP_SYNC_DONE:
            return None
        _STARTUP_SYNC_DONE = True
    with get_session() as session:
        if not startup_sync_due(session, min_interval_hours):
            return _skipped_result("recent")
        return sync_tournaments(session, **kwargs)


def reset_startup_sync_guard() -> None:
    """Test hook: allow ``sync_tournaments_once_per_process`` to run again."""
    global _STARTUP_SYNC_DONE
    with _STARTUP_SYNC_LOCK:
        _STARTUP_SYNC_DONE = False

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

from datetime import datetime, timezone
from sqlmodel import Session, select

from ..config import LIMITLESS_MAX_AGE_DAYS
from ..domain.pokemon_identity import format_api_name, normalize_format_regulation
from ..infrastructure.database.models import (
    TournamentRecord,
    TournamentTeamRecord,
    TournamentTeamMemberRecord,
)
from ..infrastructure.database.repositories import TournamentRepository
from ..infrastructure.providers import (
    LimitlessProvider,
    PokepastProvider,
    VictoryRoadProvider,
    VRPasteProvider,
    LimitlessStanding,
    VRPasteResult,
)


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
) -> dict:
    """Ingests Limitless community tournaments and team decklists."""
    provider = limitless_provider or LimitlessProvider()
    tournaments = provider.fetch_champions_tournaments(max_age_days=max_age_days)

    fetched_count = len(tournaments)
    added_count = 0
    skipped_count = 0

    # Split into new (need standings) vs existing (skip standings if not forced)
    new_tournament_ids: list[str] = []
    for t_dto in tournaments:
        t_id = f"limitless-{t_dto.id}"
        existing = repo.get_tournament(t_id)
        if existing and not force:
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
        )
        repo.upsert_tournament(t_record)
        new_tournament_ids.append(t_dto.id)

    # Batch-fetch standings with rate-limiting (max 20 requests per sync)
    id_map = {f"limitless-{t.id}": t for t in tournaments}
    raw_ids = [t.id for t in tournaments if f"limitless-{t.id}" in
               [f"limitless-{i}" for i in new_tournament_ids]]

    standings_batch = provider.fetch_standings_batch(
        tournament_ids=raw_ids,
        max_placement=None,  # All placements
        max_requests=20,
    )

    for raw_id, standings_list in standings_batch.items():
        t_id = f"limitless-{raw_id}"
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
                    )
                )

            repo.save_team(team_record, members)

        added_count += 1

    return {
        "fetched": fetched_count,
        "added": added_count,
        "skipped": skipped_count,
    }



def _sync_victory_road(
    session: Session,
    repo: TournamentRepository,
    force: bool,
    vr_provider: VictoryRoadProvider | None = None,
    pokepast_provider: PokepastProvider | None = None,
    vrpaste_provider: VRPasteProvider | None = None,
) -> dict:
    """Ingests official premier events from Victory Road Pro."""
    vr = vr_provider or VictoryRoadProvider()
    pokepast = pokepast_provider or PokepastProvider()
    vrpaste = vrpaste_provider or VRPasteProvider()

    events = vr.fetch_all_known_events()
    fetched_count = len(events)
    added_count = 0
    skipped_count = 0
    paste_errors = 0

    for ev in events:
        t_id = f"vr-{ev.slug}"
        existing_tourney = repo.get_tournament(t_id)

        if existing_tourney and not force:
            skipped_count += 1
            continue

        norm_format = normalize_format_regulation(ev.format_regulation)
        t_record = TournamentRecord(
            tournament_id=t_id,
            name=ev.name,
            event_date=ev.date,
            format_regulation=norm_format,
            game_platform=ev.game_platform,
            organizer="Play! Pokémon Premier Events",
            location=ev.location,
            total_players=ev.total_players,
            source_url=f"https://victoryroad.pro/{ev.slug}/",
        )
        repo.upsert_tournament(t_record)

        for st in ev.standings:
            if not st.paste_id:
                continue
            # Only ingest the top placements per event (configurable via force flag)
            max_per_event = 50 if force else 16
            if st.placement > max_per_event:
                continue

            showdown_text = ""
            members_raw: list[tuple[str, str]] = []  # (canonical_id, species_name)

            if st.paste_provider == "pokepast":
                try:
                    pdata = pokepast.fetch_by_id(st.paste_id)
                    showdown_text = pdata.get("paste", "")
                    members_raw = _parse_showdown_members(showdown_text)
                except Exception as exc:
                    print(f"⚠️ Could not fetch Pokepast '{st.paste_id}' for {st.player_name}: {exc}")
                    paste_errors += 1
                    continue

            elif st.paste_provider == "vrpaste":
                try:
                    vr_data = vrpaste.fetch_by_id(st.paste_id)
                    showdown_text = _assemble_showdown_from_vrpaste(vr_data)
                    for m in vr_data.members:
                        members_raw.append((format_api_name(m.display_name), m.display_name))
                except Exception as exc:
                    print(f"⚠️ Could not fetch VRPaste '{st.paste_id}' for {st.player_name}: {exc}")
                    paste_errors += 1
                    continue

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
            )

            members: list[TournamentTeamMemberRecord] = [
                TournamentTeamMemberRecord(
                    slot_position=pos,
                    canonical_id=cid,
                    species_name=sname,
                )
                for pos, (cid, sname) in enumerate(members_raw[:6], start=1)
            ]

            repo.save_team(team_record, members)

        added_count += 1

    return {
        "fetched": fetched_count,
        "added": added_count,
        "skipped": skipped_count,
        "paste_errors": paste_errors,
    }


def sync_tournaments(
    session: Session,
    force: bool = False,
    max_age_days: int = LIMITLESS_MAX_AGE_DAYS,
    include_official: bool = True,
    limitless_provider: LimitlessProvider | None = None,
    vr_provider: VictoryRoadProvider | None = None,
    pokepast_provider: PokepastProvider | None = None,
    vrpaste_provider: VRPasteProvider | None = None,
) -> dict:
    """Master sync function ingesting tournament data into local SQLite DB.

    Flow:
      1. Fetch Limitless community datasets.
      2. Fetch Victory Road official premier event datasets.
      3. Return execution metrics summary dict.
    """
    repo = TournamentRepository(session)

    res_limitless = _sync_limitless(
        session=session,
        repo=repo,
        force=force,
        max_age_days=max_age_days,
        limitless_provider=limitless_provider,
    )

    res_official = {"fetched": 0, "added": 0, "skipped": 0, "paste_errors": 0}
    if include_official:
        res_official = _sync_victory_road(
            session=session,
            repo=repo,
            force=force,
            vr_provider=vr_provider,
            pokepast_provider=pokepast_provider,
            vrpaste_provider=vrpaste_provider,
        )

    status = "synced"
    if res_limitless["fetched"] == 0 and res_official["fetched"] == 0:
        status = "offline"
    elif res_official.get("paste_errors", 0) > 0:
        status = "partial"

    return {
        "limitless": res_limitless,
        "victory_road": res_official,
        "status": status,
    }

"""HTTP client for the Play Limitless VGC public API.

API Endpoints:
- GET /api/tournaments?game=VGC — list tournaments (supports pagination)
- GET /api/tournaments/{id}/standings — list player standings with team decklists

Real API shape (verified 2026-08-31):
  Standings item = {
      "name": str,         # display name (may include country)
      "player": str,       # handle (lowercase)
      "placing": int,
      "record": {"wins": int, "losses": int, "ties": int},
      "decklist": [        # LIST of Pokémon objects (NOT a dict)
          {
              "id": str,       # canonical slug e.g. "charizard"
              "name": str,     # display name e.g. "Charizard"
              "item": str,
              "ability": str,
              "nature": str,
              "attacks": [str, str, str, str],   # NOTE: "attacks", not "moves"
              "tera": str | null,
          }
      ]
  }
"""

from __future__ import annotations

import time
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any

import requests

from ...config import (
    LIMITLESS_API_BASE_URL,
    LIMITLESS_CHAMPIONS_FORMATS,
    LIMITLESS_MAX_AGE_DAYS,
    LIMITLESS_PAGE_SIZE,
    TOURNAMENT_SYNC_TIMEOUT,
    TOURNAMENT_USER_AGENT,
)

# Max standings requests per sync run to avoid 429 rate-limiting.
# At ~1 req/s this caps a single sync at ~20 s of standings I/O.
_MAX_STANDINGS_PER_SYNC = 20
# Delay (seconds) between consecutive standings requests.
_STANDINGS_DELAY_S = 0.6


class LimitlessNetworkError(Exception):
    """Raised when Limitless API is unreachable or returns HTTP errors."""


class LimitlessParseError(Exception):
    """Raised when Limitless API payload structure is invalid or unparseable."""


@dataclass(frozen=True)
class LimitlessTeamMember:
    """A single Pokémon entry within a Limitless decklist."""

    canonical_id: str
    display_name: str
    item: str | None = None
    ability: str | None = None
    nature: str | None = None
    moves: tuple[str, ...] = field(default_factory=tuple)


@dataclass(frozen=True)
class LimitlessStanding:
    """A player's standing and decklist in a Limitless tournament."""

    player_handle: str
    placement: int
    wins: int = 0
    losses: int = 0
    ties: int = 0
    members: tuple[LimitlessTeamMember, ...] = field(default_factory=tuple)


@dataclass(frozen=True)
class LimitlessTournament:
    """Metadata for a Limitless VGC tournament."""

    id: str
    name: str
    date: datetime
    format_code: str
    player_count: int
    organizer: str = "Limitless Community"


def _safe_int(val: Any, default: int = 0) -> int:
    """Safely converts value to int, defaulting if None or invalid."""
    if val is None:
        return default
    try:
        return int(val)
    except (ValueError, TypeError):
        return default


class LimitlessProvider:
    """Thin requests-based client for play.limitlesstcg.com/api."""

    def __init__(
        self,
        base_url: str = LIMITLESS_API_BASE_URL,
        user_agent: str = TOURNAMENT_USER_AGENT,
        timeout: int = TOURNAMENT_SYNC_TIMEOUT,
    ):
        self.base_url = base_url.rstrip("/")
        self.user_agent = user_agent
        self.timeout = timeout

    def _get(self, endpoint: str, params: dict[str, Any] | None = None, retries: int = 3) -> Any:
        """Executes HTTP GET and returns parsed JSON response with HTTP 429 retry backoff."""
        url = f"{self.base_url}{endpoint}"
        headers = {
            "User-Agent": self.user_agent,
            "Accept": "application/json",
            "Accept-Language": "en-US,en;q=0.9",
        }

        for attempt in range(1, retries + 1):
            try:
                resp = requests.get(url, params=params, headers=headers, timeout=self.timeout)
                if resp.status_code == 429 and attempt < retries:
                    retry_after = resp.headers.get("Retry-After")
                    delay = float(retry_after) if (retry_after and retry_after.isdigit()) else (attempt * 2.0)
                    print(f"⚠️ Limitless API rate-limited (HTTP 429). Retrying attempt {attempt}/{retries} in {delay:.1f}s...")
                    time.sleep(delay)
                    continue
                resp.raise_for_status()
                return resp.json()
            except Exception as exc:
                if attempt < retries:
                    time.sleep(attempt * 1.5)
                    continue
                raise LimitlessNetworkError(f"HTTP GET failed for '{url}': {exc}") from exc

    def fetch_champions_tournaments(
        self,
        max_age_days: int = LIMITLESS_MAX_AGE_DAYS,
        target_formats: set[str] | None = None,
    ) -> list[LimitlessTournament]:
        """Fetches VGC tournaments filtered to Champions formats within max_age_days.

        Returns newest-first list of LimitlessTournament DTOs.
        """
        if target_formats is None:
            target_formats = LIMITLESS_CHAMPIONS_FORMATS

        cutoff_ts = datetime.now(timezone.utc).timestamp() - (max_age_days * 86400)
        tournaments: list[LimitlessTournament] = []
        page = 1
        keep_fetching = True

        while keep_fetching:
            try:
                data = self._get("/tournaments", {"game": "VGC", "limit": LIMITLESS_PAGE_SIZE, "page": page})
            except LimitlessNetworkError as exc:
                print(f"⚠️ Limitless tourneys page {page} fetch failed: {exc}")
                break

            if not isinstance(data, list) or not data:
                break  # Empty page = exhausted

            for item in data:
                try:
                    format_code = str(item.get("format", ""))
                    date_str = str(item.get("date", ""))

                    event_dt = datetime.now(timezone.utc)
                    if date_str:
                        try:
                            event_dt = datetime.fromisoformat(date_str.replace("Z", "+00:00"))
                        except ValueError:
                            pass

                    # Stop paging when we've passed the age cutoff
                    if event_dt.timestamp() < cutoff_ts:
                        keep_fetching = False
                        break

                    if format_code in target_formats or any(tf in format_code for tf in target_formats):
                        tournaments.append(
                            LimitlessTournament(
                                id=str(item.get("id", "")),
                                name=str(item.get("name", "Limitless Tournament")),
                                date=event_dt,
                                format_code=format_code,
                                player_count=_safe_int(item.get("players"), 0),
                                organizer=str(item.get("organizer", "Limitless Community")),
                            )
                        )
                except Exception as exc:
                    print(f"⚠️ Skipping malformed Limitless tourney item: {exc}")
                    continue

            page += 1
            if page > 10:  # safety page cap per sync run
                break

            # Throttle requests between pages to respect API limits
            time.sleep(0.5)

        return tournaments

    def fetch_standings(
        self,
        tournament_id: str,
        max_placement: int | None = None,
    ) -> list[LimitlessStanding]:
        """Fetches standings and decklists for a tournament ID.

        Args:
            tournament_id: Limitless tournament identifier.
            max_placement: If given, only return standings up to this placement
                           (e.g. 8 = Top 8 only). Saves filtering downstream.
        """
        try:
            data = self._get(f"/tournaments/{tournament_id}/standings")
        except LimitlessNetworkError as exc:
            print(f"⚠️ Failed to fetch standings for Limitless tourney '{tournament_id}': {exc}")
            return []

        if not isinstance(data, list):
            return []

        standings: list[LimitlessStanding] = []
        for item in data:
            try:
                # Real API uses "player" for the handle and "name" for display name
                player_name = str(item.get("name", item.get("player", "Unknown Player")))
                placement = _safe_int(item.get("placing"), 999)

                if max_placement is not None and placement > max_placement:
                    continue

                record = item.get("record", {})
                wins = _safe_int(record.get("wins"), 0) if isinstance(record, dict) else 0
                losses = _safe_int(record.get("losses"), 0) if isinstance(record, dict) else 0
                ties = _safe_int(record.get("ties"), 0) if isinstance(record, dict) else 0

                # Real API: decklist is a LIST (not a dict with "pokemon" key)
                decklist = item.get("decklist", [])
                if not isinstance(decklist, list) or not decklist:
                    continue

                members: list[LimitlessTeamMember] = []
                for p in decklist:
                    if not isinstance(p, dict):
                        continue
                    raw_id = str(p.get("id", ""))
                    display_name = str(p.get("name", raw_id))
                    item_name = p.get("item")
                    ability_name = p.get("ability")
                    nature_name = p.get("nature")
                    # Real API uses "attacks", NOT "moves"
                    moves = tuple(p.get("attacks", p.get("moves", [])))

                    if raw_id:
                        members.append(
                            LimitlessTeamMember(
                                canonical_id=raw_id.lower().strip(),
                                display_name=display_name,
                                item=str(item_name) if item_name else None,
                                ability=str(ability_name) if ability_name else None,
                                nature=str(nature_name) if nature_name else None,
                                moves=moves,
                            )
                        )

                if members:
                    standings.append(
                        LimitlessStanding(
                            player_handle=player_name,
                            placement=placement,
                            wins=wins,
                            losses=losses,
                            ties=ties,
                            members=tuple(members),
                        )
                    )
            except Exception as exc:
                print(f"⚠️ Skipping malformed Limitless standing: {exc}")
                continue

        return sorted(standings, key=lambda s: s.placement)

    def fetch_standings_batch(
        self,
        tournament_ids: list[str],
        max_placement: int | None = None,
        max_requests: int = _MAX_STANDINGS_PER_SYNC,
        delay_between: float = _STANDINGS_DELAY_S,
    ) -> dict[str, list[LimitlessStanding]]:
        """Fetches standings for a batch of tournament IDs with rate-limiting.

        Args:
            tournament_ids: Ordered list of Limitless tournament IDs to fetch.
            max_placement: Only return top N placements per tournament.
            max_requests: Hard cap on total HTTP requests to avoid 429 errors.
            delay_between: Seconds to sleep between each request.

        Returns:
            Dict mapping tournament_id -> list of standings (may be empty if failed).
        """
        results: dict[str, list[LimitlessStanding]] = {}
        fetched = 0

        for t_id in tournament_ids:
            if fetched >= max_requests:
                print(f"ℹ️ Limitless: standings batch cap ({max_requests}) reached, stopping early.")
                break

            standings = self.fetch_standings(t_id, max_placement=max_placement)
            results[t_id] = standings
            fetched += 1

            if fetched < len(tournament_ids) and fetched < max_requests:
                time.sleep(delay_between)

        return results

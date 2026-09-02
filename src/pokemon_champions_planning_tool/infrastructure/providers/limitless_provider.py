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

import re
import time
from collections.abc import Callable
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any

import requests

from ...config import (
    LIMITLESS_API_BASE_URL,
    LIMITLESS_CHAMPIONS_FORMATS,
    LIMITLESS_MAX_AGE_DAYS,
    LIMITLESS_PAGE_SIZE,
    LIMITLESS_RATE_RESERVE,
    LIMITLESS_STANDINGS_PER_RUN,
    TOURNAMENT_SYNC_TIMEOUT,
    TOURNAMENT_USER_AGENT,
)

# Standings requests per batch unless the rate budget runs out first.
_MAX_STANDINGS_PER_SYNC = LIMITLESS_STANDINGS_PER_RUN
# Delay (seconds) between consecutive standings requests.
_STANDINGS_DELAY_S = 0.6
# Listing pages per call (200 tournaments each). Only the first full sync goes deep;
# afterwards paging stops at the first page made entirely of known tournaments.
_MAX_LIST_PAGES = 12

_RATELIMIT_FIELD_RE = re.compile(r"\b([rt])=(\d+)")
_RETRYABLE_STATUS = {429, 500, 502, 503, 504}


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
        self.rate_reserve = LIMITLESS_RATE_RESERVE
        # From the ``ratelimit`` response header ("50-in-5min"; r=<remaining>; t=<reset s>).
        self.rate_remaining: int | None = None
        self.rate_reset_s: int | None = None
        self.requests_made = 0

    # -- rate budget -------------------------------------------------------------------

    def _note_rate_headers(self, headers: Any) -> None:
        value = headers.get("ratelimit") if headers is not None else None
        if not value:
            return
        fields = dict(_RATELIMIT_FIELD_RE.findall(str(value)))
        if "r" in fields:
            self.rate_remaining = int(fields["r"])
        if "t" in fields:
            self.rate_reset_s = int(fields["t"])

    @property
    def budget(self) -> int | None:
        """Requests this client may still make before touching the reserve; None if unknown."""
        if self.rate_remaining is None:
            return None
        return max(0, self.rate_remaining - self.rate_reserve)

    def _get(self, endpoint: str, params: dict[str, Any] | None = None, retries: int = 3) -> Any:
        """HTTP GET returning parsed JSON.

        Retries only what can succeed on a retry: HTTP 429 (honouring ``Retry-After`` or
        the window reset), 5xx, connection errors and timeouts. A 4xx such as 404 is
        raised at once — retrying it only burned three requests of the rate budget.
        """
        url = f"{self.base_url}{endpoint}"
        headers = {
            "User-Agent": self.user_agent,
            "Accept": "application/json",
            "Accept-Language": "en-US,en;q=0.9",
        }

        last_error: Exception | None = None
        for attempt in range(1, retries + 1):
            try:
                resp = requests.get(url, params=params, headers=headers, timeout=self.timeout)
            except (requests.exceptions.ConnectionError, requests.exceptions.Timeout) as exc:
                last_error = exc
                if attempt < retries:
                    time.sleep(attempt * 1.5)
                    continue
                break
            except Exception as exc:  # noqa: BLE001 - anything else is not retryable
                raise LimitlessNetworkError(f"HTTP GET failed for '{url}': {exc}") from exc

            self.requests_made += 1
            self._note_rate_headers(getattr(resp, "headers", None) or {})
            status = getattr(resp, "status_code", 200)
            if status in _RETRYABLE_STATUS and attempt < retries:
                retry_after = (resp.headers.get("Retry-After") or "") if resp.headers is not None else ""
                if status == 429:
                    delay = float(retry_after) if retry_after.isdigit() else float(self.rate_reset_s or attempt * 5)
                    delay = min(max(delay, 1.0), 90.0)
                    print(f"⚠️ Limitless API rate-limited (HTTP 429). Waiting {delay:.0f}s before retry {attempt}/{retries}…")
                else:
                    delay = attempt * 1.5
                time.sleep(delay)
                last_error = LimitlessNetworkError(f"HTTP {status}")
                continue
            try:
                resp.raise_for_status()
                return resp.json()
            except Exception as exc:  # noqa: BLE001 - surfaced as one error type
                raise LimitlessNetworkError(f"HTTP GET failed for '{url}': {exc}") from exc
        raise LimitlessNetworkError(f"HTTP GET failed for '{url}': {last_error}")

    def fetch_champions_tournaments(
        self,
        max_age_days: int = LIMITLESS_MAX_AGE_DAYS,
        target_formats: set[str] | None = None,
        known_ids: set[str] | None = None,
    ) -> list[LimitlessTournament]:
        """Fetches VGC tournaments filtered to Champions formats within max_age_days.

        The listing is newest-first, so paging stops at the first page that holds no
        tournament outside ``known_ids``: everything below it was listed by an earlier
        sync and any still-missing standings are tracked in the database backlog. In
        steady state that is one request instead of a dozen.

        Returns newest-first list of LimitlessTournament DTOs.
        """
        if target_formats is None:
            target_formats = LIMITLESS_CHAMPIONS_FORMATS
        known = known_ids or set()

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

            page_has_new = False
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
                        # Only Champions-format events count as "new": the feed also lists
                        # other VGC formats that are never stored, and they must not keep
                        # the paging going.
                        if str(item.get("id", "")) not in known:
                            page_has_new = True
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

            if known and not page_has_new:
                break  # every tournament on this page was listed by an earlier sync
            if len(data) < LIMITLESS_PAGE_SIZE:
                break  # short page = last page
            page += 1
            if page > _MAX_LIST_PAGES:
                break

            # Throttle requests between pages to respect API limits
            time.sleep(0.5)

        return tournaments

    def fetch_standings(
        self,
        tournament_id: str,
        max_placement: int | None = None,
        raise_on_error: bool = False,
    ) -> list[LimitlessStanding]:
        """Fetches standings and decklists for a tournament ID.

        Args:
            tournament_id: Limitless tournament identifier.
            max_placement: If given, only return standings up to this placement
                           (e.g. 8 = Top 8 only). Saves filtering downstream.
            raise_on_error: Propagate LimitlessNetworkError instead of returning an
                            empty list. Callers that persist a "standings fetched"
                            flag need to tell a failed request apart from an event
                            that genuinely published no decklists.
        """
        try:
            data = self._get(f"/tournaments/{tournament_id}/standings")
        except LimitlessNetworkError as exc:
            if raise_on_error:
                raise
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
        on_progress: Callable[[int, int, str], None] | None = None,
    ) -> dict[str, list[LimitlessStanding]]:
        """Fetches standings for a batch of tournament IDs with rate-limiting.

        Args:
            tournament_ids: Ordered list of Limitless tournament IDs to fetch.
            max_placement: Only return top N placements per tournament.
            max_requests: Hard cap on total HTTP requests to avoid 429 errors.
            delay_between: Seconds to sleep between each request.

        Returns:
            Dict mapping tournament_id -> list of standings, containing an entry only
            for tournaments whose request succeeded. A tournament whose request failed
            is omitted entirely so callers can retry it on a later run, rather than
            recording it as an event with no teams.
        """
        results: dict[str, list[LimitlessStanding]] = {}
        fetched = 0
        self.last_batch_stop: str | None = None

        for t_id in tournament_ids:
            if fetched >= max_requests:
                self.last_batch_stop = "cap"
                print(f"ℹ️ Limitless: standings batch cap ({max_requests}) reached, stopping early.")
                break
            if self.budget is not None and self.budget <= 0:
                self.last_batch_stop = "rate"
                print(f"ℹ️ Limitless: rate budget exhausted ({self.rate_remaining} left in window, reserve {self.rate_reserve}); resuming next run.")
                break

            fetched += 1
            if on_progress is not None:
                on_progress(fetched, min(len(tournament_ids), max_requests), t_id)
            try:
                results[t_id] = self.fetch_standings(
                    t_id, max_placement=max_placement, raise_on_error=True
                )
            except LimitlessNetworkError as exc:
                print(f"⚠️ Failed to fetch standings for Limitless tourney '{t_id}': {exc}")

            if fetched < len(tournament_ids) and fetched < max_requests:
                time.sleep(delay_between)

        return results

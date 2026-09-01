"""Scraper provider for Victory Road Pro (victoryroad.pro).

Parses official event standings tables to extract player placements and paste links
(Poképaste or VRPaste).

HTML structure verified 2026-08-31:
  Each row with a paste link has cells like:
    ['1', '10-2', '', 'Yuma Kinugawa ( スカーレット )', '2026 Worlds 500 CP $15,000', '', '']
  OR:
    ['', '2', '10-2', '', 'Juan Salerno ( Juanfi )', '2026 Worlds 480 CP $10,000', '', '']

  Strategy: find first numeric cell = placement, then find the cell containing a
  bracketed handle (e.g. "( Juanfi )"), and extract the handle.
"""

from __future__ import annotations

import re
import urllib.request
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any

from ...config import (
    TOURNAMENT_SYNC_TIMEOUT,
    TOURNAMENT_USER_AGENT,
    VICTORY_ROAD_BASE_URL,
)

# Known official premier events maintained as static registry
OFFICIAL_EVENT_SLUGS: list[dict[str, Any]] = [
    {
        "slug": "2026-naic",
        "name": "2026 North America International Championships",
        "date": "2026-07-04",
        "game": "Pokémon Champions",
        "format": "Regulation M-A",
        "location": "New Orleans, LA",
    },
    {
        "slug": "2026-laic",
        "name": "2026 Latin America International Championships",
        "date": "2025-11-23",
        "game": "Pokémon Champions",
        "format": "Regulation H",
        "location": "São Paulo, Brazil",
    },
    {
        "slug": "2026-euic",
        "name": "2026 Europe International Championships",
        "date": "2026-04-11",
        "game": "Scarlet & Violet",
        "format": "Regulation F",
        "location": "London, UK",
    },
    {
        "slug": "2025-worlds",
        "name": "2025 World Championships",
        "date": "2025-08-14",
        "game": "Scarlet & Violet",
        "format": "Regulation H",
        "location": "Anaheim, CA",
    },
    {
        "slug": "2025-naic",
        "name": "2025 North America International Championships",
        "date": "2025-06-20",
        "game": "Scarlet & Violet",
        "format": "Regulation G",
        "location": "New Orleans, LA",
    },
]


class VictoryRoadNetworkError(Exception):
    """Raised when Victory Road Pro is unreachable or returns HTTP errors."""


class VictoryRoadParseError(Exception):
    """Raised when Victory Road page content structure cannot be parsed."""


@dataclass(frozen=True)
class VRStandingRef:
    """Refers to a player's standing and paste link on Victory Road."""

    placement: int
    player_name: str
    swiss_record: str = ""
    paste_url: str = ""
    paste_provider: str = "pokepast"  # "pokepast" | "vrpaste"
    paste_id: str = ""


@dataclass(frozen=True)
class VREventResult:
    """Extracted tournament standings and metadata from Victory Road Pro."""

    slug: str
    name: str
    date: datetime
    game_platform: str
    format_regulation: str
    location: str
    total_players: int = 0
    standings: tuple[VRStandingRef, ...] = field(default_factory=tuple)


# Pre-compiled patterns
_POKEPAST_RE = re.compile(r"https://pokepast\.es/([a-f0-9]+)", re.IGNORECASE)
_VRPASTE_RE = re.compile(r"https://(?:www\.)?vrpastes\.com/([a-zA-Z0-9]+)", re.IGNORECASE)
_TD_RE = re.compile(r"<td[^>]*>(.*?)</td>", re.DOTALL)
_STRIP_TAGS_RE = re.compile(r"<[^>]+>")
_HANDLE_RE = re.compile(r"\(([^)]+)\)")
_NUMERIC_RE = re.compile(r"^\d+$")


def _strip_tags(html: str) -> str:
    """Remove HTML tags and collapse whitespace."""
    return " ".join(_STRIP_TAGS_RE.sub(" ", html).split())


class VictoryRoadProvider:
    """Scraper client for victoryroad.pro event pages."""

    def __init__(
        self,
        base_url: str = VICTORY_ROAD_BASE_URL,
        user_agent: str = TOURNAMENT_USER_AGENT,
        timeout: int = TOURNAMENT_SYNC_TIMEOUT,
    ):
        self.base_url = base_url.rstrip("/")
        self.user_agent = user_agent
        self.timeout = timeout

    def _fetch_html(self, url: str) -> str:
        """Fetches page HTML with timeout extension and fallback retries."""
        headers = {
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
            "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,image/webp,*/*;q=0.8",
            "Accept-Language": "en-US,en;q=0.9",
        }
        # Heavy WP/Elementor pages like 2026-naic can take up to 20-25s
        fetch_timeout = max(self.timeout, 25)
        retries = 2

        for attempt in range(1, retries + 1):
            req = urllib.request.Request(url, headers=headers)
            try:
                with urllib.request.urlopen(req, timeout=fetch_timeout) as resp:
                    return resp.read().decode("utf-8", errors="ignore")
            except Exception as exc:
                if attempt < retries:
                    print(f"⚠️ Victory Road fetch attempt {attempt} failed ({exc}). Retrying in 2.0s...")
                    import time
                    time.sleep(2.0)
                    continue
                raise VictoryRoadNetworkError(f"HTTP GET failed for '{url}': {exc}") from exc

    def _parse_standings_from_html(self, html: str) -> list[VRStandingRef]:
        """Parses player standings from Victory Road HTML.

        Strategy:
          1. Find every <td> cell block that is directly followed within 3000
             chars by a pokepaste or vrpaste link.
          2. Use cells backward from the link to extract placement (first numeric
             cell) and player name (cell with bracketed handle).
        """
        standings: list[VRStandingRef] = []

        # Iterate over all paste link occurrences in the document
        for paste_match in _POKEPAST_RE.finditer(html):
            paste_url = paste_match.group(0)
            paste_id = paste_match.group(1)
            provider = "pokepast"
            _process_paste_match(html, paste_match, paste_url, paste_id, provider, standings)

        for paste_match in _VRPASTE_RE.finditer(html):
            paste_url = paste_match.group(0)
            paste_id = paste_match.group(1)
            provider = "vrpaste"
            _process_paste_match(html, paste_match, paste_url, paste_id, provider, standings)

        # Sort by placement ascending, deduplicate by paste_id
        seen_ids: set[str] = set()
        unique: list[VRStandingRef] = []
        for s in sorted(standings, key=lambda x: x.placement):
            if s.paste_id not in seen_ids:
                seen_ids.add(s.paste_id)
                unique.append(s)
        return unique

    def fetch_event(self, event_meta: dict[str, Any]) -> VREventResult | None:
        """Scrapes standings table for a given event metadata dictionary."""
        slug = event_meta["slug"]
        url = f"{self.base_url}/{slug}/"

        try:
            html = self._fetch_html(url)
        except VictoryRoadNetworkError as exc:
            print(f"⚠️ Victory Road scraper: network error fetching '{slug}': {exc}")
            return None

        standings = self._parse_standings_from_html(html)

        if not standings:
            print(f"ℹ️ Victory Road scraper: zero paste entries found on '{slug}'.")
            return None

        event_date = datetime.now(timezone.utc)
        if "date" in event_meta:
            try:
                event_date = datetime.fromisoformat(f"{event_meta['date']}T00:00:00+00:00")
            except ValueError:
                pass

        return VREventResult(
            slug=slug,
            name=event_meta.get("name", slug),
            date=event_date,
            game_platform=event_meta.get("game", "Pokémon Champions"),
            format_regulation=event_meta.get("format", "Regulation M-A"),
            location=event_meta.get("location", "Global"),
            total_players=len(standings),
            standings=tuple(standings),
        )

    def fetch_all_known_events(self) -> list[VREventResult]:
        """Iterates known official event registry and fetches available event standings."""
        results: list[VREventResult] = []
        for meta in OFFICIAL_EVENT_SLUGS:
            res = self.fetch_event(meta)
            if res:
                results.append(res)
        return results


def _process_paste_match(
    html: str,
    paste_match: re.Match,
    paste_url: str,
    paste_id: str,
    provider: str,
    standings: list[VRStandingRef],
) -> None:
    """Extracts placement and player name from the HTML context around a paste link."""
    # Look backwards up to 3000 chars for cells
    start = max(0, paste_match.start() - 3000)
    ctx = html[start:paste_match.end()]

    # Extract all <td> cell texts in this window
    cells = [_strip_tags(c) for c in _TD_RE.findall(ctx)]
    if not cells:
        return

    # Take the last 8 cells before the paste link (most relevant)
    cells = cells[-8:]

    # Find placement: first cell that is purely numeric
    placement = 999
    player_name = "Unknown Player"
    swiss_rec = ""

    for i, cell in enumerate(cells):
        clean = cell.strip()
        if _NUMERIC_RE.match(clean) and placement == 999:
            placement = int(clean)
            # Swiss record is often the next cell (e.g. "10-2")
            if i + 1 < len(cells) and re.match(r"\d+-\d+", cells[i + 1].strip()):
                swiss_rec = cells[i + 1].strip()
        # Player name: find a cell containing a bracketed handle "( handle )"
        handle_m = _HANDLE_RE.search(clean)
        if handle_m and player_name == "Unknown Player":
            handle = handle_m.group(1).strip()
            # Skip empty or very short handles (probably not player handles)
            if len(handle) >= 2:
                player_name = handle

    if placement == 999 and player_name == "Unknown Player":
        return  # Can't extract useful data, skip

    standings.append(
        VRStandingRef(
            placement=placement,
            player_name=player_name,
            swiss_record=swiss_rec,
            paste_url=paste_url,
            paste_provider=provider,
            paste_id=paste_id,
        )
    )

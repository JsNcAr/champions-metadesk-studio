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

Division handling (verified 2026-09-01):
  Premier event pages publish several age divisions on one page, each with its own
  placements restarting at 1. The Masters tables come first, followed by a heading
  such as "Teams and results - Seniors & Juniors" and then "Seniors Top 32" /
  "Juniors Top 32". Without division awareness every event yields three "1st place"
  teams and Junior rosters carry the same weight as Masters in meta analytics.

  Each paste link is therefore labelled with the division of the nearest preceding
  <h1>-<h4> heading that names one. A page with no such heading is treated as a
  single-division (Masters) event, so regional/community pages keep every row.
"""

from __future__ import annotations

import re
import time
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any

import requests

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


DIVISION_MASTERS = "masters"
DIVISION_OTHER = "seniors_juniors"


_MONTHS = {m: i for i, m in enumerate(("jan", "feb", "mar", "apr", "may", "jun", "jul", "aug", "sep", "oct", "nov", "dec"), start=1)}
_CAL_ROW_RE = re.compile(r"<tr[^>]*>(.*?)</tr>", re.S)
_CAL_LINK_RE = re.compile(r'href="https?://(?:www\.)?victoryroad\.pro/(20\d{2}-[a-z0-9-]+)/"', re.I)
_CAL_DATE_RE = re.compile(r"(\d{1,2})\s+([A-Za-z]{3})[a-z]*\.?\s+(\d{4})")
_CAL_ACRONYM_RE = re.compile(r"^(.*?\([A-Z0-9]{2,6}\))\s*(.*)$")
_CAL_NOTE_RE = re.compile(r"\(\s+[^)]*\)")   # "( qualified players )" — notes, not acronyms
_CAL_SKIP_SLUG = ("season", "calendar", "structure", "invites")
_NAME_SUFFIXES = ("Regional", "SC", "Championships", "Championship", "Special")


@dataclass(frozen=True)
class VRCalendarEvent:
    """One row of a Victory Road season calendar."""

    slug: str
    name: str
    date: datetime          # last day of the event, UTC midnight
    game_platform: str
    format_regulation: str  # raw text, normalised by the sync
    location: str
    season: int

    def to_meta(self) -> dict[str, Any]:
        return {
            "slug": self.slug, "name": self.name, "date": self.date.strftime("%Y-%m-%d"),
            "game": self.game_platform, "format": self.format_regulation, "location": self.location,
        }


def _calendar_date(cell: str) -> datetime | None:
    """Last day mentioned in a calendar date cell ("12–14 Jun 2026", "25 Jan 2026")."""
    matches = _CAL_DATE_RE.findall(cell)
    if not matches:
        return None
    day, mon, year = matches[-1]
    month = _MONTHS.get(mon.lower()[:3])
    if month is None:
        return None
    try:
        return datetime(int(year), month, int(day), tzinfo=timezone.utc)
    except ValueError:
        return None


_EVENT_KIND_RE = re.compile(r"\b(Championships?|Regional|Special Championship|SC|League|Challenge|Qualifier|Cup|Open)\b")


def _split_event_cell(cell: str) -> tuple[str, str]:
    """Name and city from an Event cell.

    "North America International (NAIC) New Orleans, LA" -> (up to the acronym, the rest);
    "World Championships San Francisco, CA" -> (up to the event kind, the rest);
    "Houston Regional" -> ("Houston Regional", "Houston").
    """
    clean = " ".join(_CAL_NOTE_RE.sub(" ", cell).split())
    m = _CAL_ACRONYM_RE.match(clean)
    if m:
        return m.group(1).strip(), m.group(2).strip()
    kinds = list(_EVENT_KIND_RE.finditer(clean))
    if kinds:
        last = kinds[-1]
        name, rest = clean[: last.end()].strip(), clean[last.end():].strip()
        if rest:
            return name, rest
        words = name.split()
        if last.group(1) in ("Regional", "SC", "Special Championship") and len(words) >= 2:
            return name, " ".join(words[: -len(last.group(1).split())])
        return name, ""
    return clean, ""


def _format_from_cell(cell: str) -> tuple[str, str]:
    """(game platform, regulation text) from "Champions M-A , OTS+Nat" / "SV Reg. Set F OTS"."""
    game = "Scarlet & Violet" if ("SV" in cell and "Champions" not in cell) else "Pokémon Champions"
    m = re.search(r"\bM-([A-Z])\b", cell)
    if m:
        return game, f"Regulation M-{m.group(1)}"
    m = re.search(r"\bSet\s+([A-Z])\b", cell)
    if m:
        return game, f"Regulation {m.group(1)}"
    return game, "Unknown"


def parse_season_calendar(html: str, season: int) -> list[VRCalendarEvent]:
    """Events from a season calendar page: rows are Date · Event (name + city) · Winner · Format."""
    events: dict[str, VRCalendarEvent] = {}
    for row in _CAL_ROW_RE.findall(html):
        link = _CAL_LINK_RE.search(row)
        if not link:
            continue
        slug = link.group(1).lower()
        if any(k in slug for k in _CAL_SKIP_SLUG):
            continue
        cells = [_strip_tags(c) for c in _TD_RE.findall(row)]
        if len(cells) < 4:
            continue
        date = _calendar_date(cells[0])
        if date is None:
            continue
        name, location = _split_event_cell(cells[1])
        if not name:
            continue
        game, regulation = _format_from_cell(cells[3])
        events.setdefault(slug, VRCalendarEvent(
            slug=slug, name=f"{season} {name}", date=date, game_platform=game,
            format_regulation=regulation, location=location, season=season,
        ))
    return list(events.values())


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
    division: str = DIVISION_MASTERS  # DIVISION_MASTERS | DIVISION_OTHER


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
_HEADING_RE = re.compile(r"<h[1-4][^>]*>(.*?)</h[1-4]>", re.DOTALL | re.IGNORECASE)
_MASTERS_KW_RE = re.compile(r"master", re.IGNORECASE)
_OTHER_DIVISION_KW_RE = re.compile(r"senior|junior", re.IGNORECASE)


def _division_boundaries(html: str) -> list[tuple[int, str]]:
    """Return sorted (offset, division) markers for headings that name a division.

    A heading naming Seniors or Juniors wins over one naming Masters, so a combined
    "Seniors & Juniors" heading is treated as non-Masters. That bias is deliberate:
    mislabelling a section as non-Masters drops rows, while the reverse would let
    Junior teams into the meta statistics.
    """
    boundaries: list[tuple[int, str]] = []
    for match in _HEADING_RE.finditer(html):
        text = _strip_tags(match.group(1))
        if not text:
            continue
        if _OTHER_DIVISION_KW_RE.search(text):
            boundaries.append((match.start(), DIVISION_OTHER))
        elif _MASTERS_KW_RE.search(text):
            boundaries.append((match.start(), DIVISION_MASTERS))
    boundaries.sort()
    return boundaries


def _division_at(boundaries: list[tuple[int, str]], offset: int) -> str:
    """Division of the nearest heading preceding *offset*, defaulting to Masters.

    Defaulting to Masters keeps single-division pages (no division heading at all)
    fully intact, which is the common case outside premier events.
    """
    division = DIVISION_MASTERS
    for pos, label in boundaries:
        if pos > offset:
            break
        division = label
    return division


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
            try:
                resp = requests.get(url, headers=headers, timeout=fetch_timeout)
                resp.raise_for_status()
                return resp.content.decode("utf-8", errors="ignore")
            except Exception as exc:
                if attempt < retries:
                    print(f"⚠️ Victory Road fetch attempt {attempt} failed ({exc}). Retrying in 2.0s...")
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
          3. Label each link with the division of the nearest preceding heading.
        """
        standings: list[VRStandingRef] = []
        boundaries = _division_boundaries(html)

        # Iterate over all paste link occurrences in the document
        for paste_match in _POKEPAST_RE.finditer(html):
            paste_url = paste_match.group(0)
            paste_id = paste_match.group(1)
            provider = "pokepast"
            division = _division_at(boundaries, paste_match.start())
            _process_paste_match(html, paste_match, paste_url, paste_id, provider, division, standings)

        for paste_match in _VRPASTE_RE.finditer(html):
            paste_url = paste_match.group(0)
            paste_id = paste_match.group(1)
            provider = "vrpaste"
            division = _division_at(boundaries, paste_match.start())
            _process_paste_match(html, paste_match, paste_url, paste_id, provider, division, standings)

        # Sort by placement ascending, deduplicate by paste_id
        seen_ids: set[str] = set()
        unique: list[VRStandingRef] = []
        for s in sorted(standings, key=lambda x: x.placement):
            if s.paste_id not in seen_ids:
                seen_ids.add(s.paste_id)
                unique.append(s)
        return unique

    def fetch_event(
        self, event_meta: dict[str, Any], masters_only: bool = True
    ) -> VREventResult | None:
        """Scrapes standings table for a given event metadata dictionary.

        Args:
            event_meta: Registry entry describing the event (slug, name, date, ...).
            masters_only: Drop Senior and Junior division rows. Premier events publish
                all three divisions on one page with placements restarting at 1 per
                division, so keeping them would produce several "1st place" teams per
                event and let Junior rosters skew the meta statistics.
        """
        slug = event_meta["slug"]
        url = f"{self.base_url}/{slug}/"
        # None means either "the page has no team list" or "the page could not be read";
        # callers deciding whether to keep retrying need to know which.
        self.last_fetch_failed = False

        try:
            html = self._fetch_html(url)
        except VictoryRoadNetworkError as exc:
            print(f"⚠️ Victory Road scraper: network error fetching '{slug}': {exc}")
            self.last_fetch_failed = True
            return None

        standings = self._parse_standings_from_html(html)

        if masters_only:
            total = len(standings)
            standings = [s for s in standings if s.division == DIVISION_MASTERS]
            dropped = total - len(standings)
            if dropped:
                print(
                    f"ℹ️ Victory Road scraper: '{slug}' — kept {len(standings)} Masters "
                    f"entries, dropped {dropped} Senior/Junior entries."
                )

        if not standings:
            # No results table with team pastes yet (typical for a few days after an event).
            # The sync reports this with its retry plan, so nothing is printed here.
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

    def fetch_season_calendar(self, season: int) -> list[VRCalendarEvent]:
        """Events listed on /{season}-season-calendar/; [] when the page does not exist."""
        url = f"{self.base_url}/{season}-season-calendar/"
        try:
            html = self._fetch_html(url)
        except VictoryRoadNetworkError as exc:
            if "404" in str(exc):
                return []
            raise
        return parse_season_calendar(html, season)

    def fetch_all_known_events(
        self, masters_only: bool = True, skip_slugs: set[str] | frozenset[str] | None = None
    ) -> list[VREventResult]:
        """Iterates the official event registry and fetches each event's standings page.

        ``skip_slugs`` names events already ingested; their pages (heavy WordPress
        renders of 20 s or more) are not requested at all.
        """
        results: list[VREventResult] = []
        skip = skip_slugs or set()
        for meta in OFFICIAL_EVENT_SLUGS:
            if meta["slug"] in skip:
                continue
            res = self.fetch_event(meta, masters_only=masters_only)
            if res:
                results.append(res)
        return results


def _process_paste_match(
    html: str,
    paste_match: re.Match,
    paste_url: str,
    paste_id: str,
    provider: str,
    division: str,
    standings: list[VRStandingRef],
) -> None:
    """Extracts placement and player name from the HTML context around a paste link."""
    # Prefer the enclosing table row: a fixed-width backward window can spill into the
    # previous row and pick up its placement, which is wrong whenever rows are compact.
    window_start = max(0, paste_match.start() - 3000)
    row_start = html.rfind("<tr", window_start, paste_match.start())
    start = row_start if row_start != -1 else window_start
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
            division=division,
        )
    )

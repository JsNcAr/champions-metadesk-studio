"""HTTP client for the VRPastes public REST API (vrpaste-backend.vercel.app).

Used by Victory Road Pro for 2026+ major events (e.g. NAIC 2026, EUIC 2026).
- GET /api/paste/{id} — retrieves parsed team payload as JSON.
"""

from __future__ import annotations

import json
import urllib.request
from dataclasses import dataclass, field

from ...config import (
    TOURNAMENT_SYNC_TIMEOUT,
    TOURNAMENT_USER_AGENT,
    VRPASTE_BACKEND_URL,
)


class VRPasteNetworkError(Exception):
    """Raised when VRPaste API is unreachable or returns an HTTP error."""


@dataclass(frozen=True)
class VRPasteTeamMember:
    """A single Pokémon entry parsed from VRPastes."""

    species: str
    display_name: str
    item: str | None = None
    ability: str | None = None
    nature: str | None = None
    moves: tuple[str, ...] = field(default_factory=tuple)


@dataclass(frozen=True)
class VRPasteResult:
    """Parsed paste result from VRPastes."""

    paste_id: str
    title: str
    format_label: str
    members: tuple[VRPasteTeamMember, ...] = field(default_factory=tuple)


class VRPasteProvider:
    """Client for vrpaste-backend.vercel.app."""

    def __init__(
        self,
        base_url: str = VRPASTE_BACKEND_URL,
        user_agent: str = TOURNAMENT_USER_AGENT,
        timeout: int = TOURNAMENT_SYNC_TIMEOUT,
    ):
        self.base_url = base_url.rstrip("/")
        self.user_agent = user_agent
        self.timeout = timeout

    def fetch_by_id(self, paste_id: str) -> VRPasteResult:
        """GET /api/paste/{paste_id} and return parsed VRPasteResult DTO."""
        url = f"{self.base_url}/{paste_id}"
        req = urllib.request.Request(
            url,
            headers={
                "User-Agent": self.user_agent,
                "Accept": "application/json",
            },
        )
        try:
            with urllib.request.urlopen(req, timeout=self.timeout) as resp:
                raw = resp.read().decode("utf-8")
                data = json.loads(raw)
        except Exception as exc:
            raise VRPasteNetworkError(f"Failed to fetch VRPaste '{paste_id}': {exc}") from exc

        if not isinstance(data, dict):
            raise VRPasteNetworkError(f"Unexpected non-dict payload for VRPaste '{paste_id}'")

        title = str(data.get("title", f"VRPaste {paste_id}"))
        format_label = str(data.get("format", "VGC"))
        teams_data = data.get("teams", [])

        members: list[VRPasteTeamMember] = []
        if isinstance(teams_data, list):
            for mon in teams_data:
                if not isinstance(mon, dict):
                    continue
                species = str(mon.get("species", mon.get("name", "")))
                name = str(mon.get("name", species))
                item = mon.get("item")
                ability = mon.get("ability")
                nature = mon.get("nature")
                moves = tuple(mon.get("moves", []))

                if species:
                    members.append(
                        VRPasteTeamMember(
                            species=species,
                            display_name=name,
                            item=str(item) if item else None,
                            ability=str(ability) if ability else None,
                            nature=str(nature) if nature else None,
                            moves=moves,
                        )
                    )

        return VRPasteResult(
            paste_id=paste_id,
            title=title,
            format_label=format_label,
            members=tuple(members),
        )

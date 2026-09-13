"""HTTP client for the Pokepast.es public API.

Pokepast.es provides:
- POST /create  — publish a Showdown paste; returns a redirect to the new URL.
- GET  /{id}/json — retrieve a paste as a JSON object.

All HTTP operations are isolated here so the domain service layer remains
free of network concerns and easy to test with mocks.
"""

from __future__ import annotations

import re
from typing import Optional

import requests


_BASE_URL = "https://pokepast.es"
_TIMEOUT_SECONDS = 8
_USER_AGENT = "ChampionsMetaDeskStudio/1.0 (https://github.com)"
_PASTE_ID_RE = re.compile(r"pokepast\.es/([a-f0-9]+)", re.IGNORECASE)


class PokepastNetworkError(Exception):
    """Raised when Pokepast.es is unreachable or returns an unexpected response."""


class PokepastProvider:
    """Thin HTTP wrapper around the Pokepast.es public API.

    Methods raise :exc:`PokepastNetworkError` on any network or HTTP failure so
    callers can handle them uniformly without catching low-level HTTP errors.
    """

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def publish(
        self,
        *,
        title: str,
        author: str = "Pokémon Champions Planning Tool",
        notes: str = "",
        paste_text: str,
    ) -> str:
        """POST /create and return the generated Pokepast URL.

        Args:
            title: Human-readable team title shown on the paste page.
            author: Author name shown on the paste page.
            notes: Optional free-text notes shown below the team.
            paste_text: Raw Showdown-format team string.

        Returns:
            The full shareable URL, e.g. ``https://pokepast.es/abc123def456``.

        Raises:
            PokepastNetworkError: On any network failure or unexpected HTTP status.
        """
        payload = {
            "title": title,
            "author": author,
            "notes": notes,
            "paste": paste_text,
        }

        try:
            resp = requests.post(
                f"{_BASE_URL}/create",
                data=payload,
                headers={"User-Agent": _USER_AGENT},
                timeout=_TIMEOUT_SECONDS,
            )
            resp.raise_for_status()
            # The endpoint issues a 302 redirect; requests follows it and
            # the final URL is the generated paste page.
            final_url = resp.url
            if not final_url or "pokepast.es" not in final_url:
                raise PokepastNetworkError(
                    f"Unexpected redirect target: {final_url!r}"
                )
            return final_url
        except PokepastNetworkError:
            raise
        except Exception as exc:
            raise PokepastNetworkError(f"Failed to publish paste: {exc}") from exc

    def fetch_by_id(self, paste_id: str) -> dict:
        """GET /{paste_id}/json and return the parsed JSON payload.

        Args:
            paste_id: Alphanumeric paste identifier (e.g. ``abc123def456``).

        Returns:
            A dict with keys ``title``, ``author``, ``notes``, ``paste``.

        Raises:
            PokepastNetworkError: On any network failure or unexpected HTTP status.
        """
        url = f"{_BASE_URL}/{paste_id}/json"
        try:
            resp = requests.get(
                url,
                headers={"User-Agent": _USER_AGENT},
                timeout=_TIMEOUT_SECONDS,
            )
            resp.raise_for_status()
            return resp.json()
        except Exception as exc:
            raise PokepastNetworkError(
                f"Failed to fetch paste '{paste_id}': {exc}"
            ) from exc

    # ------------------------------------------------------------------
    # Utility helpers
    # ------------------------------------------------------------------

    @staticmethod
    def extract_id_from_url(url: str) -> Optional[str]:
        """Extract the paste ID from a Pokepast URL or return ``None``.

        Accepts full URLs (``https://pokepast.es/abc123``) as well as bare IDs.

        Examples::

            >>> PokepastProvider.extract_id_from_url("https://pokepast.es/abc123def456")
            'abc123def456'
            >>> PokepastProvider.extract_id_from_url("abc123def456")
            'abc123def456'
            >>> PokepastProvider.extract_id_from_url("not-a-paste-url")
            None
        """
        # Full URL match
        m = _PASTE_ID_RE.search(url)
        if m:
            return m.group(1)
        # Bare hex ID
        if re.fullmatch(r"[a-f0-9]{8,}", url.strip(), re.IGNORECASE):
            return url.strip()
        return None

    @staticmethod
    def is_pokepast_url(text: str) -> bool:
        """Return True if *text* looks like a Pokepast.es URL."""
        return "pokepast.es" in text.lower()

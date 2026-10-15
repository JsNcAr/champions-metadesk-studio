"""Is a newer release out? One request a day to GitHub's latest-release API.

The app only tells the user (a toast, a line in Settings › About) and links to the release
page; it never downloads or installs anything. The request carries the app's User-Agent and
nothing else. Flet-free.
"""

from __future__ import annotations

import json
import logging
import re
from dataclasses import asdict, dataclass

import requests

from .. import __version__
from ..config import HTTP_HEADERS
from .app_state import check_due

log = logging.getLogger(__name__)

REPOSITORY = "JsNcAr/champions-metadesk-studio"
# "latest" skips drafts and pre-releases, so a release candidate is never offered.
RELEASES_API = f"https://api.github.com/repos/{REPOSITORY}/releases/latest"
RELEASES_PAGE = f"https://github.com/{REPOSITORY}/releases/latest"
CHECK_EVERY_HOURS = 24
STATE_CHECKED_AT = "updates.checked_at"
STATE_LATEST = "updates.latest"        # JSON of the last Release seen
STATE_NOTIFIED = "updates.notified"    # the tag a toast was last shown for
PREF_ENABLED = "updates.check"         # preferences.json: the daily check is on unless False

_VERSION_RE = re.compile(r"^v?(\d+)\.(\d+)\.(\d+)(?:-([0-9A-Za-z.-]+))?(?:\+.*)?$")


@dataclass(frozen=True)
class Release:
    tag: str
    version: str
    url: str
    published_at: str = ""


def parse_version(text: str) -> tuple | None:
    """``"v0.8.0-rc.1"`` -> a tuple that sorts like semantic versions (a pre-release before
    its release), or None when it is not ``X.Y.Z[-pre]``."""
    match = _VERSION_RE.match((text or "").strip())
    if match is None:
        return None
    major, minor, patch, pre = match.groups()
    pre_key = tuple((0, int(p)) if p.isdigit() else (1, p) for p in pre.split(".")) if pre else ()
    return (int(major), int(minor), int(patch), 0 if pre else 1, pre_key)


def is_newer(latest: str, current: str = __version__) -> bool:
    new, old = parse_version(latest), parse_version(current)
    return new is not None and old is not None and new > old


def fetch_latest(timeout: float = 8) -> Release | None:
    """The newest published release, or None (offline, rate-limited, no release yet)."""
    try:
        resp = requests.get(RELEASES_API, headers={**HTTP_HEADERS, "Accept": "application/vnd.github+json"}, timeout=timeout)
    except requests.RequestException as exc:
        log.warning("Update check: GitHub could not be reached (%s)", exc)
        return None
    if resp.status_code != 200:
        log.warning("Update check: GitHub answered HTTP %s", resp.status_code)
        return None
    try:
        data = resp.json()
        tag = str(data["tag_name"])
    except (ValueError, KeyError, TypeError) as exc:
        log.warning("Update check: unexpected answer from GitHub (%s)", exc)
        return None
    return Release(tag=tag, version=tag.removeprefix("v"), url=str(data.get("html_url") or RELEASES_PAGE),
                   published_at=str(data.get("published_at") or ""))


def stored_latest(session) -> Release | None:
    """The release the last check saw (shown on days the check doesn't run)."""
    from ..infrastructure.database.repositories import TournamentRepository

    raw = TournamentRepository(session).get_state(STATE_LATEST)
    try:
        return Release(**json.loads(raw)) if raw else None
    except (TypeError, ValueError):
        return None


def last_checked(session) -> str | None:
    from ..infrastructure.database.repositories import TournamentRepository

    return TournamentRepository(session).get_state(STATE_CHECKED_AT) or None


def check_for_update(session, *, force: bool = False) -> Release | None:
    """Ask GitHub at most once a day (always when ``force``). Returns the latest release
    when it is newer than this app, else None."""
    from ..infrastructure.database.repositories import TournamentRepository

    if force:
        TournamentRepository(session).set_state(STATE_CHECKED_AT, "")
    if not check_due(session, STATE_CHECKED_AT, hours=CHECK_EVERY_HOURS):
        return None
    release = fetch_latest()
    if release is None:
        return None
    TournamentRepository(session).set_state(STATE_LATEST, json.dumps(asdict(release)))
    if is_newer(release.version):
        log.info("Version %s is available (this is %s)", release.version, __version__)
        return release
    return None


def claim_notification(session, release: Release) -> bool:
    """True the first time this release is offered: one toast per version, not per launch."""
    from ..infrastructure.database.repositories import TournamentRepository

    repo = TournamentRepository(session)
    if repo.get_state(STATE_NOTIFIED) == release.tag:
        return False
    repo.set_state(STATE_NOTIFIED, release.tag)
    return True


__all__ = [
    "PREF_ENABLED", "RELEASES_API", "RELEASES_PAGE", "Release", "check_for_update", "claim_notification", "fetch_latest",
    "is_newer", "last_checked", "parse_version", "stored_latest",
]

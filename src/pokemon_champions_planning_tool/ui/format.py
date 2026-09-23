"""Number and time formatting shared by views."""

from __future__ import annotations

import re
import sys
from datetime import datetime, timezone

# Shortcuts are written with Ctrl and Alt and read Cmd and Option on macOS (AppShell._on_key maps the keys).
# ponytail: the host OS, so a browser on another OS served from a Mac shows ⌘; use
# page.platform in both places if web mode across machines matters.
MAC = sys.platform == "darwin"


def shortcut(label: str) -> str:
    """A shortcut label for this OS: "Ctrl+Shift+S" reads "⇧⌘S" and "Alt+←" reads "⌥←" on macOS.

    Modifiers become symbols in Apple's order (⌥ ⇧ ⌘); Ctrl is the shortcut key, so ⌘.
    """
    if not MAC:
        return label
    return re.sub(
        r"\b(?:(?:Ctrl|Alt|Shift)\+)+",
        lambda m: "".join(sym for mod, sym in (("Alt+", "⌥"), ("Shift+", "⇧"), ("Ctrl+", "⌘")) if mod in m.group()),
        label,
    )


def thousands(n: int | None) -> str:
    return "—" if n is None else f"{n:,}"


def plural(n: int, singular: str, plural_form: str | None = None) -> str:
    word = singular if n == 1 else (plural_form or singular + "s")
    return f"{thousands(n)} {word}"


def _aware(dt: datetime) -> datetime:
    return dt if dt.tzinfo is not None else dt.replace(tzinfo=timezone.utc)


def absolute_time(dt: datetime | None) -> str:
    """'24 Aug 2026, 14:41' in local time."""
    if dt is None:
        return "never"
    local = _aware(dt).astimezone()
    return f"{local.day} {local.strftime('%b %Y, %H:%M')}"


def relative_time(dt: datetime | None, *, now: datetime | None = None) -> str:
    """'just now' · '5m ago' · '2h ago' · '3d ago' · else the absolute date."""
    if dt is None:
        return "never"
    now = _aware(now or datetime.now(timezone.utc))
    seconds = max(0.0, (now - _aware(dt)).total_seconds())
    if seconds < 60:
        return "just now"
    minutes = seconds / 60
    if minutes < 60:
        return f"{int(minutes)}m ago"
    hours = minutes / 60
    if hours < 24:
        return f"{int(hours)}h ago"
    days = hours / 24
    if days < 7:
        return f"{int(days)}d ago"
    local = _aware(dt).astimezone()
    return f"{local.day} {local.strftime('%b %Y')}"

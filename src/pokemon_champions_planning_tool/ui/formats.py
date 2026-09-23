"""The formats the app knows: the built-in ones and the custom ones saved in preferences.

Flet-free. The default format (``formats.default``) is what a team without its own
format follows; custom formats live in ``formats.custom`` as plain dicts. Listeners hear
``("formats",)`` after any change; the view layer relays it as ``FORMAT_CHANGED``.
"""

from __future__ import annotations

from collections.abc import Callable
from typing import Any
from uuid import uuid4

from ..domain.formats import BUILTIN_FORMATS, DEFAULT_FORMAT_ID, Format, builtin_format
from .preferences import Preferences

PREF_DEFAULT = "formats.default"
PREF_CUSTOM = "formats.custom"

Listener = Callable[[tuple], None]


class FormatRegistry:
    def __init__(self, prefs: Any = None) -> None:
        # Without a preferences file (tests, scripts) custom formats live in memory.
        self.prefs = prefs if prefs is not None else Preferences()
        self._listeners: list[Listener] = []

    def subscribe(self, listener: Listener) -> Callable[[], None]:
        self._listeners.append(listener)
        return lambda: self._listeners.remove(listener)

    def _notify(self) -> None:
        for listener in list(self._listeners):
            listener(("formats",))

    def _get(self, key: str, default: Any) -> Any:
        try:
            return self.prefs.get(key, default) if self.prefs is not None else default
        except Exception:  # noqa: BLE001 - a broken preference falls back to the defaults
            return default

    def _set(self, key: str, value: Any) -> None:
        if self.prefs is not None:
            self.prefs.set(key, value)

    # -- reading ----------------------------------------------------------------------------------

    def custom(self) -> list[Format]:
        out = []
        for data in self._get(PREF_CUSTOM, []) or []:
            try:
                out.append(Format.from_dict(data))
            except (KeyError, TypeError, ValueError):
                continue          # a malformed entry is skipped, not fatal
        return out

    def all(self) -> list[Format]:
        return [*BUILTIN_FORMATS, *self.custom()]

    def get(self, format_id: str | None) -> Format | None:
        if not format_id:
            return None
        return builtin_format(format_id) or next((f for f in self.custom() if f.format_id == format_id), None)

    def default(self) -> Format:
        return self.get(self._get(PREF_DEFAULT, DEFAULT_FORMAT_ID)) or BUILTIN_FORMATS[0]

    def for_team(self, format_id: str | None) -> Format:
        """The team's own format, or the default when it has none (or it was deleted)."""
        return self.get(format_id) or self.default()

    # -- writing ----------------------------------------------------------------------------------

    def set_default(self, format_id: str) -> None:
        if self.get(format_id) is not None and format_id != self.default().format_id:
            self._set(PREF_DEFAULT, format_id)
            self._notify()

    def new_id(self) -> str:
        return f"custom-{uuid4().hex[:8]}"

    def save_custom(self, fmt: Format) -> Format:
        """Add or replace a custom format (built-ins cannot be overwritten)."""
        if builtin_format(fmt.format_id) is not None:
            raise ValueError("Built-in formats cannot be changed; save a copy instead")
        others = [f for f in self.custom() if f.format_id != fmt.format_id]
        position = next((i for i, f in enumerate(self.custom()) if f.format_id == fmt.format_id), len(others))
        others.insert(position, fmt)
        self._set(PREF_CUSTOM, [f.to_dict() for f in others])
        self._notify()
        return fmt

    def delete_custom(self, format_id: str) -> None:
        kept = [f for f in self.custom() if f.format_id != format_id]
        if len(kept) == len(self.custom()):
            return
        self._set(PREF_CUSTOM, [f.to_dict() for f in kept])
        if self._get(PREF_DEFAULT, DEFAULT_FORMAT_ID) == format_id:
            self._set(PREF_DEFAULT, DEFAULT_FORMAT_ID)
        self._notify()


__all__ = ["FormatRegistry", "PREF_CUSTOM", "PREF_DEFAULT"]

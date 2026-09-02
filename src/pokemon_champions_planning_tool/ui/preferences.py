"""View preferences that survive a restart: layout choices, not data.

A flat JSON file next to the database (``preferences.json``). Keys are dotted
("box.view_mode"); values are JSON scalars. Without a path the store is in-memory, which
is what tests and the smoke script get by default. Reads never raise; a corrupt file
starts empty and is overwritten on the next write.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any


class Preferences:
    def __init__(self, path: Path | str | None = None) -> None:
        self.path = Path(path) if path else None
        self._data: dict[str, Any] = {}
        if self.path is not None and self.path.exists():
            try:
                loaded = json.loads(self.path.read_text(encoding="utf-8"))
                if isinstance(loaded, dict):
                    self._data = loaded
            except (OSError, ValueError):
                self._data = {}

    def get(self, key: str, default: Any = None) -> Any:
        return self._data.get(key, default)

    def set(self, key: str, value: Any) -> None:
        if self._data.get(key) == value:
            return
        self._data[key] = value
        self._flush()

    def _flush(self) -> None:
        if self.path is None:
            return
        try:
            self.path.write_text(json.dumps(self._data, indent=2, sort_keys=True), encoding="utf-8")
        except OSError as exc:
            print(f"⚠️ Could not save preferences to {self.path}: {exc}")


__all__ = ["Preferences"]

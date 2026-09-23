"""In-process event bus for cross-view invalidation.

Views never import each other. When one view changes data another view displays, it
emits an event; the other view's store subscribes and reloads from the database. The
bus is intentionally small — a dict of listeners — and is only ever called on the UI
loop (background work marshals through ``page.run_task`` first).
"""

from __future__ import annotations

from collections import defaultdict
from typing import Any, Callable

Listener = Callable[[Any], None]
Unsubscribe = Callable[[], None]

# Box entries were added, edited or deleted. Payload: None.
BOX_CHANGED = "box.changed"
# A box entry was deleted (team members referencing it are gone). Payload: box_entry_id.
BOX_ENTRY_DELETED = "box.entry_deleted"
# Teams or their members changed. Payload: active team id (UUID) or None.
TEAMS_CHANGED = "teams.changed"
# A catalogue was re-synced. Payload: "megas" | "items" | "tournaments".
CATALOGS_RELOADED = "catalogs.reloaded"
# Tournament data was synced. Payload: the sync result dict.
META_SYNCED = "meta.synced"
# Tournament battle format filter preference changed. Payload: "doubles" | "all" | "singles".
BATTLE_FORMAT_CHANGED = "tournaments.battle_format_changed"
# Ask the team builder to import Showdown text. Payload: (text, title).
IMPORT_REQUESTED = "import.requested"
# Ask the shell to show a view. Payload: view key.
NAVIGATE = "navigate"
# Ask the damage calculator to load Pokémon; payload: ui.views.calc.CalcRequest.
CALC_REQUESTED = "calc.requested"
# The default format or a custom format changed (Settings). Payload: None.
FORMAT_CHANGED = "formats.changed"
# Show Meta's teams matching a search (the view is shown first). Payload: query text.
META_SEARCH = "meta.search"
# Rival teams were saved or changed outside the calculator (Meta). Payload: team id or None.
RIVALS_CHANGED = "rivals.changed"
# Ask the calculator to show a rival team. Payload: rival team id.
RIVAL_OPEN = "rivals.open"
# The team builder's active team changed. Payload: team id (UUID) or None.
ACTIVE_TEAM = "team.active"


class EventBus:
    def __init__(self) -> None:
        self._listeners: dict[str, list[Listener]] = defaultdict(list)

    def on(self, event: str, listener: Listener) -> Unsubscribe:
        """Subscribe; returns a function that removes the subscription."""
        self._listeners[event].append(listener)

        def unsubscribe() -> None:
            try:
                self._listeners[event].remove(listener)
            except ValueError:
                pass

        return unsubscribe

    def emit(self, event: str, payload: Any = None) -> None:
        """Call every listener in subscription order. A failing listener does not stop
        the others; its exception is re-raised after all have run."""
        first_error: BaseException | None = None
        for listener in list(self._listeners.get(event, ())):
            try:
                listener(payload)
            except BaseException as exc:  # noqa: BLE001 - keep delivering
                first_error = first_error or exc
        if first_error is not None:
            raise first_error

    def listener_count(self, event: str) -> int:
        return len(self._listeners.get(event, ()))

# A tournament sync reported progress. Payload: services.tournament_sync_service.SyncProgress.
SYNC_PROGRESS = "sync.progress"

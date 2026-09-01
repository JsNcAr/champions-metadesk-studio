"""Bridges bus events to the legacy views during the migration.

New views publish events; the legacy views only know how to reload themselves from the
database. This adapter maps one to the other so views can be replaced one at a time.
It only ever calls legacy *reload* functions — it never copies state between the two
worlds. Deleted together with ``ui/legacy.py``.
"""

from __future__ import annotations

from collections.abc import Callable

from . import events
from .context import AppContext
from .legacy import LegacyViews


def bind_legacy(ctx: AppContext, views: LegacyViews) -> list[Callable[[], None]]:
    """Subscribe the legacy reload functions to the bus. Returns the unsubscribers."""
    bus = ctx.bus

    def on_catalogs_reloaded(kind: str) -> None:
        if kind == "megas":
            views.reload_catalogs()
        elif kind == "items":
            views.reload_items()

    def on_import_requested(payload: tuple[str, str]) -> None:
        text, title = payload
        views.import_showdown_text(text, title)

    return [
        bus.on(events.BOX_CHANGED, lambda _payload: views.refresh_box_state()),
        bus.on(events.BOX_ENTRY_DELETED, lambda _payload: views.refresh_box_state()),
        bus.on(events.ACTIVE_TEAM, views.set_active_team),
        bus.on(events.EXPORT_REQUESTED, lambda _payload: views.open_export_modal()),
        bus.on(events.CATALOGS_RELOADED, on_catalogs_reloaded),
        bus.on(events.IMPORT_REQUESTED, on_import_requested),
    ]

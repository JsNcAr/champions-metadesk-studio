"""Flet application entry point: theme, context, shell, views, startup sync."""

from __future__ import annotations

from types import SimpleNamespace

import flet as ft

from ..config import APP_NAME
from ..services.tournament_sync_service import sync_tournaments_once_per_process
from . import events
from .context import AppContext
from .legacy import build_legacy_views
from .legacy_adapter import bind_legacy
from .shell import AppShell
from .theme import apply_theme
from .views.settings import SettingsView

# Headless smoke tests switch this off so construction never touches the network.
STARTUP_SYNC_ENABLED = True


def _start_background_sync(ctx: AppContext) -> None:
    """Sync tournament data once per process without blocking the UI."""

    def work():
        return sync_tournaments_once_per_process(max_age_days=365, include_official=True)

    def done(result) -> None:
        if result is None:  # another session already ran it
            return
        print(f"✅ Startup tournament sync completed: {result}")
        ctx.bus.emit(events.META_SYNCED, result)

    def failed(exc: BaseException) -> None:
        print(f"⚠️ Startup tournament sync skipped/failed: {exc}")

    ctx.run_in_background(work, on_done=done, on_error=failed)


def main(page: ft.Page) -> None:
    page.title = APP_NAME
    apply_theme(page)
    page.padding = 0

    ctx = AppContext(page)
    shell = AppShell(ctx)

    # Legacy views, hosted by the new shell until each is migrated.
    views = build_legacy_views(
        page,
        SimpleNamespace(
            toast=ctx.legacy_toast,
            confirm=ctx.confirm,
            copy_to_clipboard=ctx.copy_to_clipboard,
        ),
    )
    bind_legacy(ctx, views)
    shell.register_view(
        "box",
        label="Box",
        icon=ft.Icons.INVENTORY_2_OUTLINED,
        selected_icon=ft.Icons.INVENTORY_2,
        control=views.box,
    )
    shell.register_view(
        "team",
        label="Teams",
        icon=ft.Icons.GROUPS_OUTLINED,
        selected_icon=ft.Icons.GROUPS,
        control=views.team,
    )
    shell.register_view(
        "meta",
        label="Meta",
        icon=ft.Icons.EMOJI_EVENTS_OUTLINED,
        selected_icon=ft.Icons.EMOJI_EVENTS,
        control=views.meta,
        on_activate=views.on_activate_meta,
    )
    settings_view = SettingsView(ctx)
    shell.register_view(
        "settings",
        label="Settings",
        icon=ft.Icons.SETTINGS_OUTLINED,
        selected_icon=ft.Icons.SETTINGS,
        control=settings_view,
        on_activate=settings_view.refresh,
        in_rail=False,
    )
    shell.register_settings(lambda: shell.navigate("settings"))

    shell.navigate("box")
    page.add(shell)

    if STARTUP_SYNC_ENABLED:
        _start_background_sync(ctx)

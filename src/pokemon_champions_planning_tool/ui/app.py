"""Flet application entry point: theme, context, shell, views, startup sync."""

from __future__ import annotations

from pathlib import Path

import flet as ft

from ..config import APP_NAME, DEFAULT_PREFERENCES_FILENAME
from ..infrastructure.database.database import get_session
from ..services.tournament_service import TournamentService
from ..services.tournament_sync_service import sync_tournaments_once_per_process
from . import events
from .catalogs import Catalogs
from .context import AppContext
from .preferences import Preferences
from .shell import AppShell
from .theme import apply_theme
from .views.box import BoxView
from .views.meta import MetaView
from .views.settings import SettingsView
from .views.team import TeamStore
from .views.team.view import TeamView

SEED_FILE_PATH = Path(__file__).parent.parent / "data" / "seed_tournaments.json"

# Headless smoke tests switch this off so construction never touches the network.
STARTUP_SYNC_ENABLED = True


def _seed_once() -> None:
    """Load the bundled tournament dataset the first time the app runs."""
    try:
        with get_session() as session:
            TournamentService(session, seed_file_path=SEED_FILE_PATH)
    except Exception as exc:  # noqa: BLE001 - seeding is best-effort
        print(f"⚠️ Tournament seed check skipped: {exc}")


def _start_background_sync(ctx: AppContext) -> None:
    """Sync tournament data once per process without blocking the UI."""

    def work(relay):
        return sync_tournaments_once_per_process(max_age_days=365, include_official=True, on_progress=relay)

    def done(result) -> None:
        if result is None:  # another session already ran it
            return
        print(f"✅ Startup tournament sync completed: {result}")
        ctx.bus.emit(events.META_SYNCED, result)

    def failed(exc: BaseException) -> None:
        print(f"⚠️ Startup tournament sync skipped/failed: {exc}")

    ctx.sync_tournaments(work, on_done=done, on_error=failed)


def main(page: ft.Page) -> None:
    page.title = APP_NAME
    apply_theme(page)
    page.padding = 0

    _seed_once()
    ctx = AppContext(page)
    ctx.prefs = Preferences(Path(DEFAULT_PREFERENCES_FILENAME))
    ctx.catalogs = Catalogs.load()
    # Subscribed before any view so a reloaded catalogue is in place when views react.
    ctx.bus.on(events.CATALOGS_RELOADED, lambda _kind: setattr(ctx, "catalogs", Catalogs.load()))
    shell = AppShell(ctx)

    box_view = BoxView(ctx)
    shell.register_view("box", label="Box", icon=ft.Icons.INVENTORY_2_OUTLINED, selected_icon=ft.Icons.INVENTORY_2,
                        control=box_view, on_activate=box_view.ensure_loaded)
    team_view = TeamView(ctx, TeamStore(ctx.catalogs))
    shell.register_view("team", label="Teams", icon=ft.Icons.GROUPS_OUTLINED, selected_icon=ft.Icons.GROUPS,
                        control=team_view, on_activate=team_view.ensure_loaded)
    meta_view = MetaView(ctx)
    shell.register_view("meta", label="Meta", icon=ft.Icons.EMOJI_EVENTS_OUTLINED, selected_icon=ft.Icons.EMOJI_EVENTS,
                        control=meta_view, on_activate=meta_view.ensure_loaded)
    settings_view = SettingsView(ctx)
    shell.register_view("settings", label="Settings", icon=ft.Icons.SETTINGS_OUTLINED, selected_icon=ft.Icons.SETTINGS,
                        control=settings_view, on_activate=settings_view.refresh, in_rail=False)
    shell.register_settings(lambda: shell.navigate("settings"))

    shell.navigate("box")
    page.add(shell)

    if STARTUP_SYNC_ENABLED:
        _start_background_sync(ctx)

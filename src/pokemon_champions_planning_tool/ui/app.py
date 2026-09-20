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
from .views.calc import CalcStore, CalcView
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


def _start_catalogue_refresh(ctx: AppContext, shell: AppShell) -> None:
    """Download catalogues after the window is up, not before it.

    Nothing blocks ``ft.run`` any more: a first launch opens on an empty database with a
    banner and fills in as the data arrives, and a later launch only refreshes what has
    gone stale. Before this, a fresh install showed no window at all until four downloads
    had finished.
    """

    from ..main import bootstrap_catalogues, catalogues_missing, refresh_catalogues

    with get_session() as session:
        first_run = catalogues_missing(session)
    if first_run:
        shell.set_status("Setting up — downloading the Pokédex, moves and items. The app fills in as it arrives.", "info")

    def work() -> set[str]:
        with get_session() as session:
            if first_run:
                bootstrap_catalogues(session)
            return refresh_catalogues(session)

    def done(changed: set[str]) -> None:
        if first_run:
            with get_session() as session:
                missing = catalogues_missing(session)
            if missing:
                shell.set_status("Some Pokédex data could not be downloaded. Retry from Settings once you are online.", "warning",
                                 action_label="Settings", on_action=lambda: shell.navigate("settings"))
            else:
                shell.clear_status()
        # One event per kind, so a view reloads for the catalogue it actually reads.
        for kind in sorted(changed):
            ctx.bus.emit(events.CATALOGS_RELOADED, kind)

    def failed(exc: BaseException) -> None:
        print(f"⚠️ Startup catalogue refresh skipped: {exc}")
        if first_run:
            shell.set_status(f"Could not download the Pokédex data: {exc}", "error",
                             action_label="Settings", on_action=lambda: shell.navigate("settings"))

    ctx.run_in_background(work, on_done=done, on_error=failed)


def _start_sprite_prefetch(ctx: AppContext) -> None:
    """Cache the roster's sprites for the next launch, quietly.

    Sprites are served from ``/sprites/`` only once they were on disk at startup, so this
    is what makes the second launch instant. It also matters for correctness on the web
    build, where Flet sets ``Cross-Origin-Embedder-Policy: require-corp`` and the Showdown
    CDN sends no CORP/CORS headers, so a cross-origin sprite cannot load at all.
    """

    def work() -> int:
        from ..infrastructure.database.repositories import BoxRepository
        from ..services.sprite_cache_service import sprite_cache

        with get_session() as session:
            species = [e.pokemon.canonical_id for e in BoxRepository(session).list_entries(include_planned=True)]
        return sprite_cache.prefetch(species)

    def failed(exc: BaseException) -> None:
        print(f"⚠️ Sprite prefetch skipped: {exc}")

    ctx.run_in_background(work, on_done=lambda _n: None, on_error=failed)


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
    team_store = TeamStore(ctx.catalogs)
    shell.register_view("team", label="Teams", icon=ft.Icons.GROUPS_OUTLINED, selected_icon=ft.Icons.GROUPS,
                        factory=lambda: TeamView(ctx, team_store),
                        on_activate=lambda: getattr(shell.get_view("team"), "ensure_loaded", lambda: None)())
    shell.register_view("meta", label="Meta", icon=ft.Icons.EMOJI_EVENTS_OUTLINED, selected_icon=ft.Icons.EMOJI_EVENTS,
                        factory=lambda: MetaView(ctx),
                        on_activate=lambda: getattr(shell.get_view("meta"), "ensure_loaded", lambda: None)())
    shell.register_view("calc", label="Calc", icon=ft.Icons.CALCULATE_OUTLINED, selected_icon=ft.Icons.CALCULATE,
                        factory=lambda: CalcView(ctx, CalcStore(ctx.catalogs, prefs=ctx.prefs, team_store=team_store)),
                        on_activate=lambda: getattr(shell.get_view("calc"), "ensure_loaded", lambda: None)())
    shell.register_view("settings", label="Settings", icon=ft.Icons.SETTINGS_OUTLINED, selected_icon=ft.Icons.SETTINGS,
                        factory=lambda: SettingsView(ctx),
                        on_activate=lambda: getattr(shell.get_view("settings"), "refresh", lambda: None)(), in_rail=False)
    shell.register_settings(lambda: shell.navigate("settings"))

    # The frame goes up first: mounting the shell paints the rail and the empty content
    # host straight away, so navigating (which builds and fills the Box) happens against a
    # window the user can already see rather than a blank one.
    page.add(shell)
    shell.navigate("box")

    async def _prewarm_views() -> None:
        """Build the other views while the app is idle, so switching to them is instant.

        Yields between each: built back to back they blocked the loop for a quarter of a
        second right when the Box is still drawing and the user may already be clicking.
        """
        import asyncio
        await asyncio.sleep(0.25)
        for k in ("team", "meta", "calc", "settings"):
            try:
                shell.get_view(k)
            except Exception:
                pass
            await asyncio.sleep(0)

    page.run_task(_prewarm_views)

    if STARTUP_SYNC_ENABLED:
        _start_catalogue_refresh(ctx, shell)
        _start_sprite_prefetch(ctx)
        _start_background_sync(ctx)

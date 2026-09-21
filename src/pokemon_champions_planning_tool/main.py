import sys
from pathlib import Path

from pokemon_champions_planning_tool.config import DEFAULT_ASSETS_DIR, DEFAULT_SPRITE_CACHE_DIR
from pokemon_champions_planning_tool.infrastructure.database.database import initialize_database, get_session
from pokemon_champions_planning_tool.services.champions_catalog_service import sync_champions_catalog_on_startup
from pokemon_champions_planning_tool.services.items_catalog_service import sync_items_catalog
from pokemon_champions_planning_tool.services.move_catalog_service import sync_move_catalog_on_startup
from pokemon_champions_planning_tool.services.species_catalog_service import sync_species_catalog_on_startup
from pokemon_champions_planning_tool.services.pokemon_import_service import refresh_stub_pokemon
from pokemon_champions_planning_tool.services.terminal_shell import TerminalShell


STARTUP_CHECK_HOURS = 24


def _startup_check_due(session, key: str, hours: int = STARTUP_CHECK_HOURS) -> bool:
    """True at most once per ``hours`` per key; records the check time when due."""
    from datetime import datetime, timedelta, timezone

    from pokemon_champions_planning_tool.infrastructure.database.repositories import TournamentRepository

    repo = TournamentRepository(session)
    stamp = repo.get_state(key)
    now = datetime.now(timezone.utc)
    if stamp:
        try:
            last = datetime.fromisoformat(stamp)
            if last.tzinfo is None:
                last = last.replace(tzinfo=timezone.utc)
            if now - last < timedelta(hours=hours):
                return False
        except ValueError:
            pass
    repo.set_state(key, now.isoformat())
    return True


def _empty_table(session, table: str) -> bool:
    """Is there anything at all in this table? Not a count — it stops at the first row."""
    from sqlalchemy import text

    return session.exec(text(f"SELECT 1 FROM {table} LIMIT 1")).first() is None


CATALOGUE_TABLES = ("champions_species", "item_records", "moves", "species_catalog")


def catalogues_missing(session) -> bool:
    """True on a first launch: at least one catalogue has never been downloaded."""
    return any(_empty_table(session, table) for table in CATALOGUE_TABLES)


def bootstrap_catalogues(session) -> None:
    """Fetch the catalogues that have never been downloaded (the very first launch).

    A catalogue that is merely stale is left to ``refresh_catalogues``. Both run on a
    worker once the window is up; the GUI opens on whatever is already stored, so a slow
    or unreachable PokéAPI/Showdown delays data rather than the window.
    """
    def _empty(table: str) -> bool:
        return _empty_table(session, table)

    if _empty("champions_species"):
        if _startup_check_due(session, "startup.champions_checked_at"):
            sync_champions_catalog_on_startup(session)
    if _empty("item_records"):
        if _startup_check_due(session, "startup.items_checked_at"):
            sync_items_catalog(session)
    if _empty("moves"):
        sync_move_catalog_on_startup(session)
    if _empty("species_catalog"):
        sync_species_catalog_on_startup(session)


def refresh_catalogues(session) -> set[str]:
    """The daily PokéAPI/Showdown refresh and the placeholder repair.

    Safe to run on a worker thread. Returns the catalogue kinds that actually changed
    (the ``CATALOGS_RELOADED`` vocabulary), so the caller can tell the views what to
    reload; an unchanged catalogue returns nothing and no view is disturbed.
    """
    changed: set[str] = set()
    # PokéAPI and Showdown are only asked once a day; Settings can force a refresh any
    # time. Without the gate an offline start waited on both timeouts.
    if _startup_check_due(session, "startup.champions_checked_at"):
        if sync_champions_catalog_on_startup(session).get("added"):
            changed.add("champions")
    if _startup_check_due(session, "startup.items_checked_at"):
        if sync_items_catalog(session).get("status") == "synced":
            changed.add("items")
    if sync_move_catalog_on_startup(session).get("status") == "synced":
        changed.add("moves")
    if sync_species_catalog_on_startup(session).get("status") == "synced":
        changed.add("species")
    try:
        refresh_stub_pokemon(session)
    except Exception as exc:  # noqa: BLE001 - repair is best-effort
        print(f"⚠️ Box data repair skipped: {exc}")
    return changed


def run():
    # Initialize DB schema once before anything else (DDL, migrations)
    initialize_database()

    if "--cli" in sys.argv:
        with get_session() as session:
            bootstrap_catalogues(session)
            refresh_catalogues(session)
        TerminalShell().run()
        return

    import flet as ft
    from pokemon_champions_planning_tool.ui.app import main as gui_main

    # Flet drops assets_dir when the directory is missing, and then serves nothing from
    # it — including the sprite cache. Create it before handing the path over.
    Path(DEFAULT_SPRITE_CACHE_DIR).mkdir(parents=True, exist_ok=True)

    view_mode = ft.AppView.WEB_BROWSER if "--web" in sys.argv else ft.AppView.FLET_APP
    ft.run(gui_main, view=view_mode, port=8550, assets_dir=DEFAULT_ASSETS_DIR)


if __name__ == "__main__":
    run()

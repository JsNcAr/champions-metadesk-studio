import sys
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


def run():
    # Initialize DB schema once before anything else (DDL, migrations)
    initialize_database()

    with get_session() as session:
        # PokéAPI and Showdown are only asked once a day at launch; Settings can force a
        # refresh any time. Without the gate an offline start waited on both timeouts.
        if _startup_check_due(session, "startup.champions_checked_at"):
            sync_champions_catalog_on_startup(session)
        if _startup_check_due(session, "startup.items_checked_at"):
            sync_items_catalog(session)
        sync_move_catalog_on_startup(session)
        sync_species_catalog_on_startup(session)
        try:
            refresh_stub_pokemon(session)
        except Exception as exc:  # noqa: BLE001 - repair is best-effort
            print(f"⚠️ Box data repair skipped: {exc}")

    if "--cli" in sys.argv:
        TerminalShell().run()
    else:
        import flet as ft
        from pokemon_champions_planning_tool.ui.app import main as gui_main

        view_mode = ft.AppView.WEB_BROWSER if "--web" in sys.argv else ft.AppView.FLET_APP
        ft.run(gui_main, view=view_mode, port=8550)


if __name__ == "__main__":
    run()

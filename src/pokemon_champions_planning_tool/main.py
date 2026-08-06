import sys
from .infrastructure.database.database import get_session
from .services.champions_catalog_service import sync_champions_catalog_on_startup
from .services.terminal_shell import TerminalShell


def run():
    with get_session() as session:
        sync_champions_catalog_on_startup(session)

    if "--cli" in sys.argv:
        TerminalShell().run()
    else:
        import flet as ft
        from .ui.app import main as gui_main

        view_mode = ft.AppView.WEB_BROWSER if "--web" in sys.argv else ft.AppView.FLET_APP
        ft.app(target=gui_main, view=view_mode, port=8550)


if __name__ == "__main__":
    run()


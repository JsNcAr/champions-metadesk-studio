import sys
from .services.terminal_shell import TerminalShell


def run():
    if "--cli" in sys.argv:
        TerminalShell().run()
    else:
        import flet as ft
        from .ui.app import main as gui_main
        
        # Default to native app view, but allow web browser option for remote/headless setups
        view_mode = ft.AppView.WEB_BROWSER if "--web" in sys.argv else ft.AppView.FLET_APP
        ft.app(target=gui_main, view=view_mode, port=8550)


if __name__ == "__main__":
    run()

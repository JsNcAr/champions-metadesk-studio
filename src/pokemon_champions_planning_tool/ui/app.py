"""Flet application entry point.

Builds the page, then mounts the views. During the UI overhaul the views come from
``ui/legacy.py``; this module hosts them behind a minimal switcher that will be replaced
by the new application shell.
"""

from __future__ import annotations

import flet as ft

from ..config import APP_NAME
from .legacy import LegacyViews, build_legacy_views
from .theme import Colors, apply_theme


class _TransitionalServices:
    """The services contract the legacy views expect, pending the real shell."""

    def __init__(self, page: ft.Page):
        self._page = page

    def toast(self, message: str, is_error: bool = False) -> None:
        snack = ft.SnackBar(
            content=ft.Text(message, color=Colors.WHITE),
            bgcolor=Colors.RED_ACCENT if is_error else Colors.GREEN_ACCENT_700,
            duration=3000,
        )
        self._page.overlay.append(snack)
        snack.open = True
        self._page.update()


def _mount(page: ft.Page, views: LegacyViews) -> None:
    """Temporary tab switcher: three buttons, a settings button, and a content host."""
    host = ft.Container(content=views.box, expand=True)
    tabs = [
        ("Box Roster", ft.Icons.INBOX, views.box, None),
        ("Team Builder", ft.Icons.PEOPLE, views.team, None),
        ("Tournaments & Meta", ft.Icons.EMOJI_EVENTS, views.meta, views.on_activate_meta),
    ]
    buttons: list[ft.TextButton] = []

    def select(index: int) -> None:
        for i, button in enumerate(buttons):
            button.style = ft.ButtonStyle(
                color=Colors.WHITE if i == index else Colors.GREY_400,
                bgcolor=Colors.AMBER_700 if i == index else Colors.CARD_BG,
            )
        _label, _icon, content, on_activate = tabs[index]
        host.content = content
        if on_activate:
            on_activate()
        page.update()

    for i, (label, icon, _content, _on_activate) in enumerate(tabs):
        buttons.append(ft.TextButton(label, icon=icon, on_click=lambda e, i=i: select(i)))

    header = ft.Container(
        content=ft.Row(
            alignment=ft.MainAxisAlignment.SPACE_BETWEEN,
            controls=[
                ft.Row(spacing=12, controls=[
                    ft.Icon(ft.Icons.CATCHING_POKEMON, color=Colors.AMBER_400, size=28),
                    ft.Text(APP_NAME, size=20, weight=ft.FontWeight.BOLD, color=Colors.AMBER_400),
                ]),
                ft.Row(spacing=8, controls=[
                    *buttons,
                    ft.IconButton(
                        icon=ft.Icons.SETTINGS,
                        icon_color=Colors.GREY_400,
                        tooltip="Data & Synchronization Settings",
                        on_click=lambda e: views.open_settings(),
                    ),
                ]),
            ],
        ),
        bgcolor=Colors.CARD_BG,
        padding=ft.Padding.symmetric(horizontal=20, vertical=12),
        border_radius=12,
        border=ft.Border.all(1, Colors.DIVIDER),
        margin=ft.Margin.only(bottom=14),
    )
    select(0)
    page.add(header, host)


def main(page: ft.Page) -> None:
    page.title = APP_NAME
    apply_theme(page)
    page.padding = ft.Padding.symmetric(horizontal=20, vertical=16)

    views = build_legacy_views(page, _TransitionalServices(page))
    _mount(page, views)

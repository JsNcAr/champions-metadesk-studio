"""A button-looking trigger for ``ft.PopupMenuButton``.

A real button (``OutlinedButton``, ``FilledTonalButton``…) used as a menu's ``content``
takes the tap itself: Flutter hands the gesture to the inner button, which has no handler,
so the menu never opens. The Teams "Export" and Box "Add to team" menus did nothing for that
reason. The trigger is therefore a plain Container painted like the button it replaces, with
a caret to say it opens a menu.
"""

from __future__ import annotations

from typing import Literal

import flet as ft

from ..theme import Palette, Space

Tone = Literal["outlined", "tonal"]


def menu_button(label: str, icon: str, *, tone: Tone = "outlined") -> ft.Container:
    """``PopupMenuButton(content=menu_button("Export", ft.Icons.UPLOAD), items=[…])``."""
    if tone == "tonal":
        fg, bg, border = Palette.ON_SECONDARY_CONTAINER, Palette.SECONDARY_CONTAINER, None
    else:
        fg, bg, border = Palette.PRIMARY, None, ft.Border.all(1, Palette.OUTLINE)
    return ft.Container(
        content=ft.Row(
            spacing=Space.SM,
            tight=True,
            vertical_alignment=ft.CrossAxisAlignment.CENTER,
            controls=[
                ft.Icon(icon, size=18, color=fg),
                ft.Text(label, theme_style=ft.TextThemeStyle.LABEL_LARGE, color=fg, weight=ft.FontWeight.W_600),
                ft.Icon(ft.Icons.ARROW_DROP_DOWN, size=18, color=fg),
            ],
        ),
        height=40,   # Material 3 button height, so it lines up with the buttons beside it
        padding=ft.Padding.only(left=Space.LG, right=Space.SM),
        border_radius=20,
        bgcolor=bg,
        border=border,
    )


__all__ = ["menu_button"]

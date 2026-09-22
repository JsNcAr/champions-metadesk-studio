"""A "?" button that explains a panel: a short tooltip on hover, the full text on click.

A tooltip alone does nothing on a click (or a touch screen), which read as a broken button.
"""

from __future__ import annotations

from collections.abc import Sequence

import flet as ft

from ..theme import IconSize, Palette, Space


def help_dialog(title: str, lines: Sequence[str], *, on_close) -> ft.AlertDialog:
    """Paragraphs; a line ending in ":" is a small heading."""
    controls: list[ft.Control] = []
    for line in lines:
        if not line:
            continue
        heading = line.endswith(":")
        controls.append(ft.Text(line, theme_style=ft.TextThemeStyle.TITLE_SMALL if heading else ft.TextThemeStyle.BODY_MEDIUM,
                                color=Palette.ON_SURFACE if heading else Palette.ON_SURFACE_VARIANT,
                                weight=ft.FontWeight.W_600 if heading else None))
    return ft.AlertDialog(
        modal=False, scrollable=True, title=ft.Text(title),
        content=ft.Container(width=520, content=ft.Column(spacing=Space.SM, tight=True, controls=controls)),
        actions=[ft.TextButton("Close", on_click=lambda _e: on_close())],
        actions_alignment=ft.MainAxisAlignment.END,
    )


def help_button(title: str, lines: Sequence[str], *, tooltip: str = "Help") -> ft.IconButton:
    def show(e: ft.ControlEvent) -> None:
        page = e.control.page
        page.show_dialog(help_dialog(title, lines, on_close=page.pop_dialog))

    return ft.IconButton(icon=ft.Icons.HELP_OUTLINE, icon_size=IconSize.SM, tooltip=tooltip, on_click=show)


__all__ = ["help_button", "help_dialog"]

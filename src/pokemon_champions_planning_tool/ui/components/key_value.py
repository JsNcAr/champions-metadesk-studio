"""Two-column key/value list for metadata (Settings, About)."""

from __future__ import annotations

from collections.abc import Sequence

import flet as ft

from ..theme import Palette, Space

_KEY_WIDTH = 140


class KeyValueList(ft.Column):
    def __init__(self, rows: Sequence[tuple[str, str | ft.Control]] = ()) -> None:
        super().__init__(spacing=Space.SM, tight=True)
        self.set_rows(rows)

    def set_rows(self, rows: Sequence[tuple[str, str | ft.Control]]) -> None:
        self.controls = [self._row(key, value) for key, value in rows]

    @staticmethod
    def _row(key: str, value: str | ft.Control) -> ft.Row:
        value_control = (
            ft.Text(value, theme_style=ft.TextThemeStyle.BODY_MEDIUM, color=Palette.ON_SURFACE, selectable=True, expand=True)
            if isinstance(value, str)
            else value
        )
        return ft.Row(
            vertical_alignment=ft.CrossAxisAlignment.START,
            controls=[
                ft.Container(
                    content=ft.Text(key, theme_style=ft.TextThemeStyle.BODY_SMALL, color=Palette.ON_SURFACE_VARIANT),
                    width=_KEY_WIDTH,
                ),
                value_control,
            ],
        )

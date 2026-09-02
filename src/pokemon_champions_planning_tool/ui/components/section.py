"""Section header (overline text, optional trailing action/status) and Panel (card surface)."""

from __future__ import annotations

from collections.abc import Sequence

import flet as ft

from ..theme import Palette, Radius, Space


class SectionHeader(ft.Row):
    """Uppercase overline label with room for a trailing action and a status caption."""

    def __init__(self, label: str, *, action: ft.Control | None = None, status: str | None = None, accent: str = Palette.SECONDARY) -> None:
        super().__init__(
            alignment=ft.MainAxisAlignment.SPACE_BETWEEN,
            vertical_alignment=ft.CrossAxisAlignment.CENTER,
        )
        self._bar = ft.Container(width=3, height=12, border_radius=Radius.PILL, bgcolor=accent)
        self._label = ft.Row(
            spacing=Space.SM,
            tight=True,
            vertical_alignment=ft.CrossAxisAlignment.CENTER,
            controls=[self._bar, ft.Text(label.upper(), theme_style=ft.TextThemeStyle.LABEL_SMALL, color=Palette.ON_SURFACE_VARIANT)],
        )
        self._status = ft.Text(
            status or "", theme_style=ft.TextThemeStyle.BODY_SMALL, color=Palette.ON_SURFACE_VARIANT,
            visible=bool(status),
        )
        trailing = ft.Row(spacing=Space.SM, controls=[self._status] + ([action] if action else []))
        self.controls = [self._label, trailing]

    def set_label(self, label: str) -> None:
        self._label.controls[1].value = label.upper()

    def set_status(self, status: str | None, *, color: str | None = None) -> None:
        self._status.value = status or ""
        self._status.visible = bool(status)
        self._status.color = color or Palette.ON_SURFACE_VARIANT


class Panel(ft.Container):
    """A card surface holding a column of controls with the standard padding."""

    def __init__(self, controls: Sequence[ft.Control], *, spacing: int = Space.MD, width: int | None = None) -> None:
        super().__init__()
        self.content = ft.Column(spacing=spacing, controls=list(controls), tight=True)
        self.bgcolor = Palette.SURFACE_2
        self.border_radius = Radius.MD
        self.border = ft.Border.all(1, Palette.OUTLINE_VARIANT)
        self.padding = Space.PANEL_PADDING
        self.width = width

    @property
    def column(self) -> ft.Column:
        return self.content

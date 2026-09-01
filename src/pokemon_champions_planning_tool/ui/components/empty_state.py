"""Empty state: icon, title, description, one primary action (and an optional secondary)."""

from __future__ import annotations

from collections.abc import Callable

import flet as ft

from ..theme import IconSize, Palette, Space


class EmptyState(ft.Container):
    def __init__(
        self,
        icon: str,
        title: str,
        description: str = "",
        *,
        action_label: str | None = None,
        on_action: Callable[[], None] | None = None,
        secondary_label: str | None = None,
        on_secondary: Callable[[], None] | None = None,
    ) -> None:
        super().__init__()
        self._title = ft.Text(title, theme_style=ft.TextThemeStyle.BODY_LARGE, color=Palette.ON_SURFACE, text_align=ft.TextAlign.CENTER)
        self._description = ft.Text(
            description,
            theme_style=ft.TextThemeStyle.BODY_MEDIUM,
            color=Palette.ON_SURFACE_VARIANT,
            text_align=ft.TextAlign.CENTER,
            visible=bool(description),
        )
        buttons: list[ft.Control] = []
        if action_label:
            buttons.append(ft.FilledTonalButton(action_label, on_click=lambda _e: on_action() if on_action else None))
        if secondary_label:
            buttons.append(ft.TextButton(secondary_label, on_click=lambda _e: on_secondary() if on_secondary else None))
        self.content = ft.Column(
            horizontal_alignment=ft.CrossAxisAlignment.CENTER,
            spacing=Space.SM,
            tight=True,
            controls=[
                ft.Icon(icon, size=IconSize.EMPTY_STATE, color=Palette.DISABLED),
                self._title,
                self._description,
                ft.Row(alignment=ft.MainAxisAlignment.CENTER, spacing=Space.SM, controls=buttons, visible=bool(buttons)),
            ],
        )
        self.width = 360
        self.alignment = ft.Alignment.CENTER
        self.padding = ft.Padding.symmetric(vertical=Space.XXXL)

    def set_text(self, title: str, description: str = "") -> None:
        self._title.value = title
        self._description.value = description
        self._description.visible = bool(description)

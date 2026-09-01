"""Inline banner: sits in flow under the control it explains. Never floats."""

from __future__ import annotations

from collections.abc import Callable
from typing import Literal

import flet as ft

from ..theme import IconSize, Palette, Radius, Space

Kind = Literal["info", "warning", "error", "success"]

_STYLES: dict[Kind, tuple[str, str, str]] = {
    "info": (Palette.INFO_CONTAINER, Palette.ON_INFO_CONTAINER, ft.Icons.INFO_OUTLINE),
    "warning": (Palette.WARNING_CONTAINER, Palette.ON_WARNING_CONTAINER, ft.Icons.WARNING_AMBER_OUTLINED),
    "error": (Palette.ERROR_CONTAINER, Palette.ON_ERROR_CONTAINER, ft.Icons.ERROR_OUTLINE),
    "success": (Palette.SUCCESS_CONTAINER, Palette.ON_SUCCESS_CONTAINER, ft.Icons.CHECK_CIRCLE_OUTLINE),
}


class InlineBanner(ft.Container):
    def __init__(
        self,
        message: str = "",
        kind: Kind = "info",
        *,
        action_label: str | None = None,
        on_action: Callable[[], None] | None = None,
        visible: bool = True,
    ) -> None:
        super().__init__()
        self._icon = ft.Icon(ft.Icons.INFO_OUTLINE, size=IconSize.SM)
        self._text = ft.Text("", theme_style=ft.TextThemeStyle.BODY_MEDIUM, max_lines=2, overflow=ft.TextOverflow.ELLIPSIS, expand=True)
        self._action = ft.TextButton("", visible=False, on_click=lambda _e: self._on_action() if self._on_action else None)
        self._on_action = on_action
        self.content = ft.Row(
            spacing=Space.SM,
            vertical_alignment=ft.CrossAxisAlignment.CENTER,
            controls=[self._icon, self._text, self._action],
        )
        self.border_radius = Radius.SM
        self.padding = ft.Padding.symmetric(horizontal=Space.MD, vertical=Space.SM)
        self.visible = visible
        self.set(message, kind, action_label=action_label, on_action=on_action)

    def set(
        self,
        message: str,
        kind: Kind = "info",
        *,
        action_label: str | None = None,
        on_action: Callable[[], None] | None = None,
    ) -> None:
        bg, fg, icon = _STYLES[kind]
        self.bgcolor = bg
        self._icon.name = icon
        self._icon.color = fg
        self._text.value = message
        self._text.color = fg
        self._on_action = on_action
        self._action.content = action_label or ""
        self._action.visible = bool(action_label)
        self._action.style = ft.ButtonStyle(color=fg)

    def show(self, message: str, kind: Kind = "info", **kwargs) -> None:
        self.set(message, kind, **kwargs)
        self.visible = True

    def hide(self) -> None:
        self.visible = False

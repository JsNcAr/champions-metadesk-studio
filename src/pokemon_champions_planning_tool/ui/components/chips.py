"""Small chips: status (tonal, with icon), placement badge, removable active-filter chip."""

from __future__ import annotations

from collections.abc import Callable
from typing import Literal

import flet as ft

from ..theme import IconSize, Palette, Radius, Space

Tone = Literal["success", "error", "warning", "info", "neutral", "primary", "tertiary", "silver"]

_TONES: dict[Tone, tuple[str | None, str, str | None]] = {
    # bg, fg, border
    "success": (Palette.SUCCESS_CONTAINER, Palette.ON_SUCCESS_CONTAINER, None),
    "error": (Palette.ERROR_CONTAINER, Palette.ON_ERROR_CONTAINER, None),
    "warning": (Palette.WARNING_CONTAINER, Palette.ON_WARNING_CONTAINER, None),
    "info": (Palette.SECONDARY_CONTAINER, Palette.ON_SECONDARY_CONTAINER, None),
    "neutral": (None, Palette.ON_SURFACE_VARIANT, Palette.OUTLINE),
    "primary": (Palette.PRIMARY, Palette.ON_PRIMARY, None),
    "tertiary": (Palette.TERTIARY_CONTAINER, Palette.ON_TERTIARY_CONTAINER, None),
    "silver": (Palette.SILVER, Palette.ON_SILVER, None),
}


class StatusChip(ft.Container):
    """Tonal chip with optional leading icon: `✓ Champions-legal`, `1 illegal species`…"""

    def __init__(self, label: str, tone: Tone = "neutral", *, icon: str | None = None, tooltip: str | None = None) -> None:
        super().__init__()
        self._icon = ft.Icon(icon or ft.Icons.CIRCLE, size=IconSize.SM, visible=icon is not None)
        self._label = ft.Text(label, theme_style=ft.TextThemeStyle.LABEL_MEDIUM)
        self.content = ft.Row(spacing=4, tight=True, vertical_alignment=ft.CrossAxisAlignment.CENTER, controls=[self._icon, self._label])
        self.border_radius = Radius.SM
        self.padding = ft.Padding.symmetric(horizontal=Space.SM, vertical=3)
        self.tooltip = tooltip
        self.set_tone(tone)

    def set(self, label: str, tone: Tone, *, icon: str | None = None, tooltip: str | None = None) -> None:
        self._label.value = label
        self._icon.visible = icon is not None
        if icon is not None:
            self._icon.name = icon
        self.tooltip = tooltip
        self.set_tone(tone)

    def set_tone(self, tone: Tone) -> None:
        bg, fg, border = _TONES[tone]
        self.bgcolor = bg
        self.border = ft.Border.all(1, border) if border else None
        self._label.color = fg
        self._icon.color = fg


class PlacementBadge(ft.Container):
    """40×24 badge with the standing label; tone by placement tier."""

    def __init__(self, placement: int = 0, label: str = "") -> None:
        super().__init__()
        self._label = ft.Text("", theme_style=ft.TextThemeStyle.LABEL_MEDIUM, weight=ft.FontWeight.W_600)
        self.content = self._label
        self.width = 48
        self.height = 24
        self.alignment = ft.Alignment.CENTER
        self.border_radius = Radius.SM
        self.set(placement, label)

    def set(self, placement: int, label: str = "") -> None:
        self._label.value = label or _ordinal(placement)
        if placement == 1:
            bg, fg, border = Palette.PRIMARY, Palette.ON_PRIMARY, None
        elif placement == 2:
            bg, fg, border = Palette.SILVER, Palette.ON_SILVER, None
        elif placement <= 4:
            bg, fg, border = Palette.TERTIARY_CONTAINER, Palette.ON_TERTIARY_CONTAINER, None
        else:
            bg, fg, border = None, Palette.ON_SURFACE_VARIANT, Palette.OUTLINE
        self.bgcolor = bg
        self._label.color = fg
        self.border = ft.Border.all(1, border) if border else None


def _ordinal(n: int) -> str:
    if n <= 0:
        return "—"
    suffix = "th" if 10 <= n % 100 <= 20 else {1: "st", 2: "nd", 3: "rd"}.get(n % 10, "th")
    return f"{n}{suffix}"


class ActiveFilterChip(ft.Container):
    """`Fire ×` — a removable chip echoing an active filter."""

    def __init__(self, label: str, on_remove: Callable[[], None]) -> None:
        super().__init__()
        self.content = ft.Row(
            spacing=4,
            tight=True,
            vertical_alignment=ft.CrossAxisAlignment.CENTER,
            controls=[
                ft.Text(label, theme_style=ft.TextThemeStyle.LABEL_MEDIUM, color=Palette.ON_PRIMARY_CONTAINER),
                ft.IconButton(
                    icon=ft.Icons.CLOSE,
                    icon_size=14,
                    icon_color=Palette.ON_PRIMARY_CONTAINER,
                    width=20,
                    height=20,
                    padding=0,
                    tooltip="Remove filter",
                    on_click=lambda _e: on_remove(),
                ),
            ],
        )
        self.bgcolor = Palette.PRIMARY_CONTAINER
        self.border_radius = Radius.PILL
        self.padding = ft.Padding.only(left=Space.MD, right=4, top=2, bottom=2)

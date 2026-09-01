"""Sprite avatar: circular Pokémon image with optional ring and badge.

Sizes 24 / 32 / 40 / 64 / 96. Rings: none, type colour, mega (primary + bolt badge),
planned (tertiary + note badge, dimmed sprite), selected (primary). The image falls back
to a Poké Ball icon when the CDN has no art (Champions-exclusive megas).
"""

from __future__ import annotations

from typing import Literal

import flet as ft

from ..theme import Palette, Radius, alpha, type_color

Ring = Literal["none", "type", "mega", "planned", "selected", "error"]


class Sprite(ft.Container):
    def __init__(
        self,
        src: str | None = None,
        *,
        size: int = 40,
        ring: Ring = "none",
        primary_type: str | None = None,
        tooltip: str | None = None,
        badge_number: int | None = None,
    ) -> None:
        super().__init__()
        self._size = size
        self._image = ft.Image(
            src=src or "",
            width=int(size * 0.85),
            height=int(size * 0.85),
            fit=ft.BoxFit.CONTAIN,
            error_content=ft.Icon(
                ft.Icons.CATCHING_POKEMON, size=int(size * 0.55), color=Palette.DISABLED
            ),
        )
        self._badge = ft.Container(
            width=max(14, size // 3),
            height=max(14, size // 3),
            border_radius=Radius.PILL,
            alignment=ft.Alignment.CENTER,
            visible=False,
            right=-2,
            bottom=-2,
        )
        self._number = ft.Container(
            content=ft.Text("", size=max(9, size // 4), weight=ft.FontWeight.W_600, color=Palette.ON_SURFACE),
            width=max(14, size // 3),
            height=max(14, size // 3),
            border_radius=Radius.PILL,
            bgcolor=Palette.SURFACE_4,
            alignment=ft.Alignment.CENTER,
            visible=False,
            left=-2,
            bottom=-2,
        )
        self.content = ft.Stack(
            controls=[
                ft.Container(content=self._image, alignment=ft.Alignment.CENTER, width=size, height=size),
                self._badge,
                self._number,
            ],
            width=size,
            height=size,
        )
        self.width = size
        self.height = size
        self.border_radius = Radius.PILL
        self.bgcolor = Palette.SURFACE_3
        self.alignment = ft.Alignment.CENTER
        self.tooltip = tooltip
        self.set_ring(ring, primary_type)
        self.set_badge_number(badge_number)

    def set_src(self, src: str | None) -> None:
        self._image.src = src or ""

    def set_tooltip(self, tooltip: str | None) -> None:
        self.tooltip = tooltip

    def set_badge_number(self, number: int | None) -> None:
        self._number.visible = number is not None
        self._number.content.value = "" if number is None else str(number)

    def set_ring(self, ring: Ring, primary_type: str | None = None) -> None:
        self._image.opacity = 1.0
        self._badge.visible = False
        colour: str | None = None
        width = 2
        if ring == "type":
            colour = type_color(primary_type)
        elif ring == "mega":
            colour = Palette.PRIMARY
            self._badge.visible = True
            self._badge.bgcolor = Palette.PRIMARY_CONTAINER
            self._badge.content = ft.Icon(ft.Icons.BOLT, size=max(10, self._size // 4), color=Palette.ON_PRIMARY_CONTAINER)
        elif ring == "planned":
            colour = Palette.TERTIARY
            self._image.opacity = 0.7
            self._badge.visible = True
            self._badge.bgcolor = Palette.TERTIARY_CONTAINER
            self._badge.content = ft.Icon(ft.Icons.EDIT_NOTE, size=max(10, self._size // 4), color=Palette.ON_TERTIARY_CONTAINER)
        elif ring == "selected":
            colour = Palette.PRIMARY
        elif ring == "error":
            colour = Palette.ERROR
        self.border = ft.Border.all(width, colour) if colour else None
        self.shadow = (
            ft.BoxShadow(blur_radius=6, spread_radius=1, color=alpha(Palette.PRIMARY, 0.35))
            if ring == "selected"
            else None
        )

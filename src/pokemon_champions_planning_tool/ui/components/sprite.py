"""Sprite avatar: circular Pokémon image with optional ring and badge.

Sizes 24 / 32 / 40 / 64 / 96. Rings: none, type colour, mega (primary + bolt badge),
planned (tertiary + note badge, dimmed sprite), selected (primary). The image falls back
to a Poké Ball icon when the CDN has no art (Champions-exclusive megas).
"""

from __future__ import annotations

from typing import Literal

import flet as ft

from ..theme import Palette, Radius, alpha, type_color

Ring = Literal["none", "type", "mega", "planned", "selected", "error", "missing"]


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
        # An empty ``src`` makes Flutter render "A valid src value must be specified" in red,
        # so the image is hidden and the fallback icon shown whenever there is no URL.
        self._image = ft.Image(
            src=src or "",
            width=int(size * 0.85),
            height=int(size * 0.85),
            fit=ft.BoxFit.CONTAIN,
            visible=bool(src),
            error_content=ft.Icon(
                ft.Icons.CATCHING_POKEMON, size=int(size * 0.55), color=Palette.DISABLED
            ),
        )
        self._fallback = ft.Icon(ft.Icons.CATCHING_POKEMON, size=int(size * 0.55), color=Palette.DISABLED, visible=not src)
        # The two overlays are built on demand and appended to the stack. Most sprites
        # never show either — only mega/planned rings get a badge and only the team
        # summary numbers its rings — and together they were a quarter of the cost of a
        # sprite, which a full box grid pays hundreds of times.
        self._badge: ft.Container | None = None
        self._number: ft.Container | None = None
        self._ring_state: tuple[Ring, str | None] | None = None
        # The circle (background, ring, shadow) is an inner control: a Container with a
        # pill radius clips its children to the circle, which cut the corner badge. The
        # badge is a sibling in an unclipped stack, so it may overhang the ring.
        self._circle = ft.Container(
            content=ft.Stack(
                controls=[
                    ft.Container(content=self._image, alignment=ft.Alignment.CENTER, width=size, height=size),
                    ft.Container(content=self._fallback, alignment=ft.Alignment.CENTER, width=size, height=size),
                ],
                width=size,
                height=size,
            ),
            width=size,
            height=size,
            border_radius=Radius.PILL,
            bgcolor=Palette.SURFACE_3,
            alignment=ft.Alignment.CENTER,
        )
        self.content = ft.Stack(
            controls=[self._circle],
            width=size,
            height=size,
            clip_behavior=ft.ClipBehavior.NONE,
        )
        self.width = size
        self.height = size
        self.clip_behavior = ft.ClipBehavior.NONE
        self.alignment = ft.Alignment.CENTER
        self.tooltip = tooltip
        self.set_ring(ring, primary_type)
        self.set_badge_number(badge_number)

    def _ensure_badge(self) -> ft.Container:
        """The ring's bottom-right badge; a rim in the surface colour separates it from
        the ring, and the stack must not clip it at the circle."""
        if self._badge is None:
            size = self._size
            self._badge = ft.Container(
                width=max(16, size // 3),
                height=max(16, size // 3),
                border_radius=Radius.PILL,
                alignment=ft.Alignment.CENTER,
                border=ft.Border.all(2, Palette.SURFACE_2),
                visible=False,
                right=-4,
                bottom=-4,
            )
            self.content.controls.append(self._badge)
        return self._badge

    def _ensure_number(self) -> ft.Container:
        if self._number is None:
            size = self._size
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
            self.content.controls.append(self._number)
        return self._number

    def set_src(self, src: str | None) -> None:
        self._image.src = src or ""
        self._image.visible = bool(src)
        self._fallback.visible = not src

    def set_tooltip(self, tooltip: str | None) -> None:
        self.tooltip = tooltip

    def set_badge_number(self, number: int | None) -> None:
        if number is None and self._number is None:
            return
        number_badge = self._ensure_number()
        number_badge.visible = number is not None
        number_badge.content.value = "" if number is None else str(number)

    def set_ring(self, ring: Ring, primary_type: str | None = None) -> None:
        # Rebuilding the border, shadow and badge icon costs more than the comparison, and
        # a grid re-render asks every card for the ring it already has.
        if self._ring_state == (ring, primary_type):
            return
        self._ring_state = (ring, primary_type)
        self._image.opacity = 1.0
        if self._badge is not None:
            self._badge.visible = False
        colour: str | None = None
        width = 2
        if ring == "type":
            colour = type_color(primary_type)
        elif ring == "mega":
            colour = Palette.PRIMARY
            badge = self._ensure_badge()
            badge.visible = True
            badge.bgcolor = Palette.PRIMARY
            badge.content = ft.Icon(ft.Icons.BOLT, size=max(10, self._size // 5), color=Palette.ON_PRIMARY)
        elif ring == "planned":
            colour = Palette.TERTIARY
            self._image.opacity = 0.7
            badge = self._ensure_badge()
            badge.visible = True
            badge.bgcolor = Palette.TERTIARY
            badge.content = ft.Icon(ft.Icons.EDIT_NOTE, size=max(10, self._size // 5), color=Palette.ON_TERTIARY)
        elif ring == "selected":
            colour = Palette.PRIMARY
        elif ring == "error":
            colour = Palette.ERROR
        elif ring == "missing":
            # Not in the box: dimmed with a plain outline ring.
            colour = Palette.OUTLINE
            self._image.opacity = 0.45
        self._circle.border = ft.Border.all(width, colour) if colour else None
        self._circle.shadow = (
            ft.BoxShadow(blur_radius=6, spread_radius=1, color=alpha(Palette.PRIMARY, 0.35))
            if ring == "selected"
            else None
        )

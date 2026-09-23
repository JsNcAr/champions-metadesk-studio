"""Item icon: the item's sprite, or its cell on Showdown's item sheet, or a generic icon.

Items PokéAPI has no art for store a sheet reference as their ``sprite_url``
(``domain.item_sprites``); the cell is cropped by placing the whole sheet, scaled, behind
a clipped box. Pixel art stays sharp (no filtering) at any size.
"""

from __future__ import annotations

import flet as ft

from ...domain.item_sprites import CELL, ITEM_SHEET_URL, SHEET_HEIGHT, SHEET_WIDTH, cell_offset, sheet_cell
from ...services.sprite_cache_service import resolve_sprite_src
from ..theme import Palette


def item_icon(sprite_url: str | None, *, size: int = 24, fallback: str = ft.Icons.DIAMOND_OUTLINED, tooltip: str | None = None) -> ft.Control:
    cell = sheet_cell(sprite_url)
    placeholder = ft.Icon(fallback, size=int(size * 0.75), color=Palette.ON_SURFACE_VARIANT)
    if cell is not None:
        scale = size / CELL
        x, y = cell_offset(cell)
        return ft.Container(
            width=size, height=size, clip_behavior=ft.ClipBehavior.HARD_EDGE, tooltip=tooltip,
            content=ft.Stack(width=size, height=size, controls=[
                ft.Image(src=resolve_sprite_src(ITEM_SHEET_URL) or ITEM_SHEET_URL, width=SHEET_WIDTH * scale, height=SHEET_HEIGHT * scale,
                         left=-x * scale, top=-y * scale, fit=ft.BoxFit.FILL, filter_quality=ft.FilterQuality.NONE, error_content=placeholder),
            ]),
        )
    if sprite_url:
        return ft.Container(width=size, height=size, alignment=ft.Alignment.CENTER, tooltip=tooltip, content=ft.Image(
            src=resolve_sprite_src(sprite_url) or sprite_url, width=size, height=size, fit=ft.BoxFit.CONTAIN,
            filter_quality=ft.FilterQuality.NONE, error_content=placeholder))
    return ft.Container(width=size, height=size, alignment=ft.Alignment.CENTER, tooltip=tooltip, content=placeholder)


__all__ = ["item_icon"]

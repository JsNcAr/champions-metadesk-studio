"""Input styling shared by the search and filter fields.

Flet 0.85 has no theme-level text-field decoration, so the fields that must stand out
on a dark toolbar take these keyword arguments: a filled surface-3 box with a visible
outline that turns amber on focus.
"""

from __future__ import annotations

from ..theme import Palette

SEARCH_FIELD_STYLE: dict = {
    "filled": True,
    "fill_color": Palette.SURFACE_3,
    "bgcolor": Palette.SURFACE_3,
    "focused_bgcolor": Palette.SURFACE_3,
    "hover_color": Palette.SURFACE_4,
    "border_color": Palette.OUTLINE,
    "focused_border_color": Palette.PRIMARY,
    "cursor_color": Palette.PRIMARY,
}

__all__ = ["SEARCH_FIELD_STYLE"]

"""Design system: tokens (colour, spacing, radius, type) and the Flet theme built from them.

Views and components use ``Palette``, ``Space``, ``Radius``, ``FontSize``, ``IconSize``,
``Layout``, ``Motion``, ``TYPE_COLORS``/``type_color``/``on_type_color``, ``STAT_COLORS``
and ``alpha`` — never literals (``tests/test_ui_theme_lint.py`` enforces it).
"""

from .build import FONT_FAMILY, INTER_FONT_URL, apply_theme, build_color_scheme, build_text_theme, build_theme
from .tokens import (
    OVERLAY_SHADOW,
    STAT_COLORS,
    STAT_LABELS,
    STAT_MAX,
    STAT_ORDER,
    STAT_TRACK,
    TYPE_COLORS,
    TYPE_ORDER,
    FontSize,
    IconSize,
    Layout,
    Motion,
    Palette,
    Radius,
    Space,
    alpha,
    on_type_color,
    type_color,
)

__all__ = [
    "FONT_FAMILY",
    "INTER_FONT_URL",
    "OVERLAY_SHADOW",
    "STAT_COLORS",
    "STAT_LABELS",
    "STAT_MAX",
    "STAT_ORDER",
    "STAT_TRACK",
    "TYPE_COLORS",
    "TYPE_ORDER",
    "FontSize",
    "IconSize",
    "Layout",
    "Motion",
    "Palette",
    "Radius",
    "Space",
    "alpha",
    "apply_theme",
    "build_color_scheme",
    "build_text_theme",
    "build_theme",
    "on_type_color",
    "type_color",
]

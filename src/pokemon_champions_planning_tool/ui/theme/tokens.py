"""Design tokens — the single source of truth for colour, spacing, radius and type.

Every colour, size and radius used by the UI comes from here. Views and components must
not contain literals; ``tests/test_ui_theme_lint.py`` enforces that for hex colours.

The palette is a dark slate system expressed as Material 3 roles, so that both the Flet
theme (see ``build.py``) and any component that needs a colour Material has no role for
(type, stat, warning, success) read from one place.
"""

from __future__ import annotations

import flet as ft


class Palette:
    """Semantic colour roles for the dark theme."""

    # Surfaces, from the page background up to overlays.
    BG = "#0F172A"
    SURFACE_1 = "#172033"       # side panels, table rows, grouped lists
    SURFACE_2 = "#1E293B"       # cards, tiles, inputs, toolbars
    SURFACE_3 = "#273447"       # hover, selected rows, chips, menus
    SURFACE_4 = "#2F3D52"       # dialogs, sheets, tooltips
    OUTLINE = "#3B4A63"         # borders that need definition
    OUTLINE_VARIANT = "#263244" # hairlines, dividers
    SCRIM = "#000000"

    # Text.
    ON_SURFACE = "#F1F5F9"
    ON_SURFACE_VARIANT = "#A3B0C2"
    DISABLED = "#64748B"        # disabled / placeholder only, never body text

    # Accent — interactive and selected elements only, never headers or metadata.
    PRIMARY = "#FBBF24"
    ON_PRIMARY = "#1C1400"
    PRIMARY_CONTAINER = "#3B2F0B"
    ON_PRIMARY_CONTAINER = "#FDE68A"

    SECONDARY = "#38BDF8"       # links, tags, info
    ON_SECONDARY = "#041C2A"
    SECONDARY_CONTAINER = "#0C3A52"
    ON_SECONDARY_CONTAINER = "#BAE6FD"

    TERTIARY = "#A78BFA"        # planned entries, tournament accents
    ON_TERTIARY = "#1B0F3A"
    TERTIARY_CONTAINER = "#2E1F5E"
    ON_TERTIARY_CONTAINER = "#DDD6FE"

    ERROR = "#F87171"
    ON_ERROR = "#2A0A0A"
    ERROR_CONTAINER = "#3F1216"
    ON_ERROR_CONTAINER = "#FECACA"

    # Orange on purpose: "selected" (amber) and "careful" must never share a hue.
    WARNING = "#FB923C"
    ON_WARNING = "#2A1204"
    WARNING_CONTAINER = "#3D1F0A"
    ON_WARNING_CONTAINER = "#FED7AA"

    SUCCESS = "#4ADE80"
    ON_SUCCESS = "#04200F"
    SUCCESS_CONTAINER = "#0B3A24"
    ON_SUCCESS_CONTAINER = "#BBF7D0"

    INFO = SECONDARY
    INFO_CONTAINER = SECONDARY_CONTAINER
    ON_INFO_CONTAINER = ON_SECONDARY_CONTAINER

    # Placement badge for 2nd place (silver); 1st uses PRIMARY, top 4 TERTIARY_CONTAINER.
    SILVER = "#CBD5E1"
    ON_SILVER = "#0B1220"


class Space:
    """4-pt spacing scale."""

    XS = 4
    SM = 8
    MD = 12
    LG = 16
    XL = 24
    XXL = 32
    XXXL = 48

    CARD_PADDING = MD
    PANEL_PADDING = LG
    PAGE_PADDING = XL
    GUTTER = XL
    GRID_GAP = MD


class Radius:
    SM = 6      # chips inside cards, badges, inputs
    MD = 10     # cards, buttons, tiles
    LG = 14     # dialogs, side sheets
    PILL = 999


class FontSize:
    """Type scale (Inter). Line heights live in ``build.py``'s TextTheme."""

    TITLE_LG = 22
    TITLE = 17
    BODY_LG = 15
    BODY = 13
    LABEL = 12
    CAPTION = 11
    OVERLINE = 11


class IconSize:
    SM = 16     # inside chips, captions, badges
    MD = 20     # buttons, list leading, toolbar icon buttons
    LG = 24     # rail, page headers
    EMPTY_STATE = 40


class Layout:
    RAIL_WIDTH = 80
    RAIL_WIDTH_COMPACT = 64
    PAGE_HEADER_HEIGHT = 56
    TOOLBAR_HEIGHT = 44
    SIDE_PANEL_WIDTH = 360
    SIDE_PANEL_WIDTH_COMPACT = 320
    MIN_HIT_TARGET = 32
    BREAKPOINT_COMPACT = 1280
    BREAKPOINT_NARROW = 1024


class Motion:
    FAST_MS = 150
    NORMAL_MS = 200
    SLOW_MS = 250
    CURVE = ft.AnimationCurve.EASE_OUT


# Overlay-only shadow. Resting surfaces use tone, not shadow.
OVERLAY_SHADOW = ft.BoxShadow(
    blur_radius=24, offset=ft.Offset(0, 8), color=ft.Colors.with_opacity(0.45, Palette.SCRIM)
)


# Pokémon types. Text colour is chosen per chip so every label passes 4.5:1.
_ON_TYPE_DARK = "#0B1220"
_ON_TYPE_LIGHT = "#FFFFFF"

TYPE_COLORS: dict[str, str] = {
    "normal": "#A8A77A",
    "fire": "#EE8130",
    "water": "#6390F0",
    "grass": "#7AC74C",
    "electric": "#F7D02C",
    "ice": "#96D9D6",
    "fighting": "#C22E28",
    "poison": "#A33EA1",
    "ground": "#E2BF65",
    "flying": "#A98FF3",
    "psychic": "#F95587",
    "bug": "#A6B91A",
    "rock": "#B6A136",
    "ghost": "#735797",
    "dragon": "#6F35FC",
    "dark": "#705746",
    "steel": "#B7B7CE",
    "fairy": "#D685AD",
    "unknown": "#64748B",
}

_LIGHT_TEXT_TYPES = frozenset({"fighting", "poison", "ghost", "dragon", "dark", "unknown"})

TYPE_ORDER: tuple[str, ...] = tuple(t for t in TYPE_COLORS if t != "unknown")


def type_color(type_name: str | None) -> str:
    """Chip background for a type, with one fallback for anything unrecognised."""
    return TYPE_COLORS.get((type_name or "unknown").lower(), TYPE_COLORS["unknown"])


def on_type_color(type_name: str | None) -> str:
    """Readable text colour for a type chip."""
    key = (type_name or "unknown").lower()
    if key not in TYPE_COLORS:
        key = "unknown"
    return _ON_TYPE_LIGHT if key in _LIGHT_TEXT_TYPES else _ON_TYPE_DARK


# Stats, keyed by PokemonStats field name. Bars normalise to /255 everywhere.
STAT_COLORS: dict[str, str] = {
    "hp": "#F87171",
    "attack": "#FB923C",
    "defense": "#FACC15",
    "special_attack": "#60A5FA",
    "special_defense": "#4ADE80",
    "speed": "#F472B6",
}
STAT_TRACK = "#334155"
STAT_MAX = 255

STAT_ORDER: tuple[str, ...] = ("hp", "attack", "defense", "special_attack", "special_defense", "speed")
STAT_LABELS: dict[str, str] = {
    "hp": "HP",
    "attack": "Atk",
    "defense": "Def",
    "special_attack": "SpA",
    "special_defense": "SpD",
    "speed": "Spe",
}


def alpha(color: str, opacity: float) -> str:
    """The only sanctioned way to derive a translucent colour."""
    return ft.Colors.with_opacity(opacity, color)

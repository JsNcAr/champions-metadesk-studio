"""Application colour palette.

The UI uses a fixed dark theme built on a Tailwind-style slate palette rather
than Flet's Material colour enum, because the design needs semantic surface
tokens (``CARD_BG``, ``PANEL_BG``, ``DIVIDER``, ...) that Material does not
provide.

Every value is an explicit colour string, so an attribute that does not exist
raises ``AttributeError`` at the call site instead of silently producing an
unrenderable colour name.
"""

from __future__ import annotations


class Colors:
    """Explicit colour tokens used across the Flet UI."""

    # Base
    WHITE = "white"
    BLACK = "black"

    # Surfaces
    BG_BASE = "#0f172a"         # page background
    CARD_BG = "#1e293b"         # default card surface
    CARD_SELECTED = "#1e3a5f"   # selected card highlight (blue tinted)
    PANEL_BG = "#111827"        # right panel / drawer
    TOOLBAR_BG = "#1e293b"      # filter toolbar bar
    HEADER_BG = "#0f172a"
    SURFACE_VARIANT = "#1e293b"
    DIVIDER = "#334155"

    # Neutrals
    GREY_300 = "#d1d5db"
    GREY_400 = "#9ca3af"
    GREY_500 = "#6b7280"
    GREY_600 = "#6b7280"
    GREY_800 = "#374151"
    BLUE_GREY_600 = "#475569"
    BLUE_GREY_900 = "#1e293b"
    BLUE_GREY_950 = "#111827"

    # Reds
    RED_200 = "#fecaca"
    RED_300 = "#fca5a5"
    RED_400 = "#f87171"
    RED_700 = "#b91c1c"
    RED_900 = "#7f1d1d"
    RED_ACCENT = "redaccent"

    # Ambers / yellows / oranges
    AMBER_100 = "#fef3c7"
    AMBER_300 = "#fcd34d"
    AMBER_400 = "#fbbf24"
    AMBER_500 = "#f59e0b"
    AMBER_600 = "#d97706"
    AMBER_700 = "#d97706"
    YELLOW = "#fbbf24"
    YELLOW_400 = "#facc15"
    ORANGE_400 = "#fb923c"

    # Greens
    GREEN_300 = "#86efac"
    GREEN_400 = "#4ade80"
    GREEN_700 = "#15803d"
    GREEN_ACCENT_700 = "#16a34a"

    # Blues / cyans
    BLUE_300 = "#93c5fd"
    BLUE_400 = "#60a5fa"
    BLUE_700 = "#1d4ed8"
    CYAN_400 = "#22d3ee"

    # Purples / pinks
    PURPLE_900 = "#581c87"
    PINK_400 = "#f472b6"

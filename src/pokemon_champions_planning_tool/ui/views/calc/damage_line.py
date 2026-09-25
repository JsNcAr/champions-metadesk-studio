"""One hit as a small gauge, for the side panel's cards: → Knock Off ▰▰▰▱ 58–68%.

The bar is the move card's in miniature (the lowest roll solid, up to the highest roll
lighter) with a tick at half the HP, so a 2HKO reads at a glance; the range beside it is
rounded to whole percents ("90%+" when the highest roll KOs, "OHKO" when every roll does).
→ is your hit on them, in teal; ← theirs on you, in orange. Within each colour, a stronger
hit is brighter, so the two lines tell apart at a glance and still show how hard each hits.
"""

from __future__ import annotations

import flet as ft

from ...theme import Palette, Radius, alpha
from .state import MoveResult

GAUGE_WIDTH = 40
GAUGE_HEIGHT = 6
DIRECTIONS = {"you": (ft.Icons.EAST, "Your best hit on them"), "them": (ft.Icons.WEST, "Their best hit on you")}
# Your hits and the ones you take in two colour families, away from the cards' class tints.
HUES = {"you": Palette.HIT_DEALT, "them": Palette.HIT_TAKEN}


def strength(max_pct: float) -> float:
    """How bright a hit is drawn: faint for chip damage, full for a KO."""
    return 1.0 if max_pct >= 100 else 0.85 if max_pct >= 50 else 0.7 if max_pct >= 25 else 0.5


def hit_colour(direction: str, max_pct: float) -> str:
    return alpha(HUES[direction], strength(max_pct))


def gauge(min_pct: float, max_pct: float, width: int = GAUGE_WIDTH, *, direction: str = "you") -> ft.Control:
    colour = hit_colour(direction, max_pct)

    def fill(pct: float, color: str) -> ft.Container:
        return ft.Container(left=0, top=0, width=round(width * min(1.0, pct / 100)), height=GAUGE_HEIGHT, bgcolor=color, border_radius=Radius.PILL)

    return ft.Stack(width=width, height=GAUGE_HEIGHT, controls=[
        ft.Container(left=0, top=0, width=width, height=GAUGE_HEIGHT, bgcolor=Palette.SURFACE_4, border_radius=Radius.PILL),
        fill(max_pct, alpha(HUES[direction], 0.35 * strength(max_pct))),
        fill(min_pct, colour),
        ft.Container(left=width // 2, top=0, width=1, height=GAUGE_HEIGHT, bgcolor=alpha(Palette.ON_SURFACE, 0.5)),   # half the HP
    ])


def pct_range(result: MoveResult) -> str:
    """"58–68%"; "90%+" when the highest roll KOs, "OHKO" when every roll does. The exact
    range is in the tooltip; three-digit ranges do not fit the card."""
    if result.min_pct >= 100:
        return "OHKO"
    if result.max_pct >= 100:
        return f"{result.min_pct:.0f}%+"
    return f"{result.min_pct:.0f}–{result.max_pct:.0f}%"


def damage_line(direction: str, result: MoveResult | None, fallback: str) -> ft.Control:
    """``direction``: "you" (your hit on them) or "them" (theirs on you)."""
    icon, what = DIRECTIONS[direction]
    arrow = ft.Icon(icon, size=12, color=HUES[direction])
    small = ft.TextThemeStyle.LABEL_SMALL
    if result is None:
        return ft.Row(spacing=6, vertical_alignment=ft.CrossAxisAlignment.CENTER, tooltip=what, controls=[
            arrow, ft.Text(fallback, theme_style=small, color=Palette.ON_SURFACE_VARIANT, italic=True, max_lines=1, overflow=ft.TextOverflow.ELLIPSIS, expand=True),
        ])
    hits = f" · {'OHKO' if result.ko_hits == 1 else f'{result.ko_hits}HKO'} on an average roll" if result.ko_hits else ""
    return ft.Row(spacing=6, vertical_alignment=ft.CrossAxisAlignment.CENTER,
                  tooltip=f"{what}: {result.name} {result.min_pct:g}–{result.max_pct:g}%{hits}", controls=[
        arrow,
        ft.Text(result.name, theme_style=small, color=Palette.ON_SURFACE, max_lines=1, overflow=ft.TextOverflow.ELLIPSIS, expand=True),
        gauge(result.min_pct, result.max_pct, direction=direction),
        ft.Text(pct_range(result), theme_style=small, weight=ft.FontWeight.W_700, color=hit_colour(direction, result.max_pct), width=50,
                text_align=ft.TextAlign.RIGHT, max_lines=1),
    ])


def speed_mark(speed: int, faster: bool, tie: bool = False) -> ft.Text:
    """"137▼" beside the name: ▲ you move first, ▼ they do."""
    tip = "Speed tie" if tie else ("You move first" if faster else "They move first")
    return ft.Text(f"{speed}{'▲' if faster else '▼'}", theme_style=ft.TextThemeStyle.LABEL_SMALL, weight=ft.FontWeight.W_700,
                   color=Palette.WARNING if tie else (Palette.SUCCESS if faster else Palette.ERROR), tooltip=f"Spe {speed} · {tip}")


__all__ = ["GAUGE_WIDTH", "HUES", "damage_line", "gauge", "hit_colour", "pct_range", "speed_mark", "strength"]

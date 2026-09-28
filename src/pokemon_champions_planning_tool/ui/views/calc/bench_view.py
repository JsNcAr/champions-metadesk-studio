"""How a move's benchmarks read, in an open move card and in the Build tab alike:
"Tyranitar: OHKO with Atk 20", "Rillaboom: survive 1 hit with HP 12 / Def 8", with Apply
where the answer needs more points than are spent now."""

from __future__ import annotations

from collections.abc import Callable

import flet as ft

from ...theme import Palette, Space
from .benchmarks import STAT_SHORT, Benchmarks, ko_needs_points, ko_text, survive_needs_points, survive_text

TOOLTIP = "Stat points for a guaranteed KO (lowest roll), or to survive the highest roll; everything else as set"

# (whose points: "mine" | "theirs", {stat: points}) — the panel applies it to the right side.
ApplyPoints = Callable[[str, dict[str, int]], None]


def heading(text: str = "BENCHMARKS") -> ft.Text:
    return ft.Text(text, theme_style=ft.TextThemeStyle.LABEL_SMALL, color=Palette.ON_SURFACE_VARIANT, tooltip=TOOLTIP)


def _note(text: str) -> ft.Text:
    return ft.Text(text, theme_style=ft.TextThemeStyle.BODY_SMALL, color=Palette.ON_SURFACE_VARIANT)


def loading(title: ft.Control) -> ft.Control:
    return ft.Row(spacing=Space.SM, vertical_alignment=ft.CrossAxisAlignment.CENTER,
                  controls=[title, ft.ProgressRing(width=12, height=12, stroke_width=2), _note("Working out the numbers…")])


def _row(text: str, apply: tuple[str, dict[str, int]] | None, tip: str, on_apply: ApplyPoints | None) -> ft.Control:
    controls: list[ft.Control] = [ft.Text(text, theme_style=ft.TextThemeStyle.BODY_SMALL, color=Palette.ON_SURFACE, expand=True)]
    if apply is not None and on_apply is not None:
        controls.append(ft.TextButton("Apply", tooltip=tip, style=ft.ButtonStyle(visual_density=ft.VisualDensity.COMPACT),
                                      on_click=lambda _e: on_apply(*apply)))
    return ft.Row(spacing=Space.SM, vertical_alignment=ft.CrossAxisAlignment.CENTER, controls=controls)


def rows(value: Benchmarks | None, *, mine: str, theirs: str, on_apply: ApplyPoints | None) -> list[ft.Control]:
    """One line per benchmark; ``mine`` names the attacker of the move, ``theirs`` its target."""
    if value is None:
        return [_note("Not available for this move")]
    out: list[ft.Control] = []
    for k in value.ko:
        apply = ("mine", {k.stat: k.points}) if ko_needs_points(k) else None
        out.append(_row(f"{mine}: {ko_text(k)}", apply, f"Set {STAT_SHORT[k.stat]} to {k.points} (now {k.current})", on_apply))
    for s in value.survive:
        apply = ("theirs", {"hp": s.hp, s.stat: s.defence}) if survive_needs_points(s) else None
        tip = f"Set their HP to {s.hp} and {STAT_SHORT[s.stat]} to {s.defence} (now {s.current_hp} / {s.current_defence})"
        out.append(_row(f"{theirs}: {survive_text(s)}", apply, tip, on_apply))
    return out


__all__ = ["ApplyPoints", "TOOLTIP", "heading", "loading", "rows"]

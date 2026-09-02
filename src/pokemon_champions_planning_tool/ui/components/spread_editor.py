"""Champions stat-point editor: nature, six point sliders, the 66-point budget, live stats.

Champions has no EVs or IVs — every Pokémon is level 50 with 31 IVs and spends 0–32 points
per stat, 66 in total. The editor clamps every change to the remaining budget (as Showdown
does) and shows the resulting battle stat next to each slider. Embedded by the team
builder's spread dialog and by the damage calculator's Pokémon panels.
"""

from __future__ import annotations

from collections.abc import Callable, Mapping

import flet as ft

from ...domain.entities.pokemon_stats import PokemonStats
from ...domain.stat_calc import (
    MAX_POINTS_PER_STAT,
    MAX_POINTS_TOTAL,
    NATURES,
    champions_stats,
    nature_label,
    nature_multiplier,
    points_total,
)
from ..theme import STAT_COLORS, STAT_LABELS, STAT_ORDER, Palette, Space

ChangeHandler = Callable[[str, dict[str, int]], None]

# The −Spe nature that keeps a spread's boosted stat: the Champions replacement for
# "0 Speed IVs" on Trick Room sets.
_MIN_SPEED_NATURE: dict[str, str] = {"attack": "brave", "defense": "relaxed", "special_attack": "quiet", "special_defense": "sassy"}


class SpreadEditor(ft.Column):
    def __init__(
        self,
        *,
        base_stats: PokemonStats,
        nature: str | None,
        points: Mapping[str, int] | None,
        on_change: ChangeHandler | None = None,
        compact: bool = False,
    ) -> None:
        super().__init__(spacing=Space.SM, tight=True)
        self._base = base_stats
        self._on_change = on_change
        self._compact = compact
        self._points: dict[str, int] = {k: int((points or {}).get(k, 0)) for k in STAT_ORDER}

        self._nature = ft.Dropdown(
            label="Nature", width=200 if compact else 230, dense=True, enable_filter=True,
            value=(nature or "hardy").lower(),
            options=[ft.DropdownOption(key=n, text=nature_label(n)) for n in NATURES],
            on_select=lambda _e: self._changed(),
        )
        self._sliders: dict[str, ft.Slider] = {}
        self._fields: dict[str, ft.TextField] = {}
        self._computed: dict[str, ft.Text] = {}
        self._arrows: dict[str, ft.Icon] = {}
        label_width = 36 if compact else 44
        rows: list[ft.Control] = []
        if not compact:
            rows.append(ft.Row(spacing=Space.SM, controls=[
                ft.Container(width=label_width),
                ft.Text("Stat points", theme_style=ft.TextThemeStyle.LABEL_SMALL, color=Palette.ON_SURFACE_VARIANT, expand=True),
                ft.Text("Pts", theme_style=ft.TextThemeStyle.LABEL_SMALL, color=Palette.ON_SURFACE_VARIANT, width=52, text_align=ft.TextAlign.CENTER),
                ft.Text("Stat", theme_style=ft.TextThemeStyle.LABEL_SMALL, color=Palette.ON_SURFACE_VARIANT, width=52, text_align=ft.TextAlign.RIGHT),
            ]))
        for stat in STAT_ORDER:
            slider = ft.Slider(min=0, max=MAX_POINTS_PER_STAT, divisions=MAX_POINTS_PER_STAT, value=self._points[stat], expand=True, active_color=STAT_COLORS[stat],
                               on_change=lambda e, stat=stat: self._slider_changed(stat, int(round(e.control.value))))
            field = ft.TextField(value=str(self._points[stat]), width=52, dense=True, text_align=ft.TextAlign.CENTER, keyboard_type=ft.KeyboardType.NUMBER,
                                 on_change=lambda e, stat=stat: self._typed(stat, e.control.value or ""))
            computed = ft.Text("", theme_style=ft.TextThemeStyle.LABEL_MEDIUM, weight=ft.FontWeight.W_600, color=Palette.ON_SURFACE, width=52, text_align=ft.TextAlign.RIGHT)
            arrow = ft.Icon(ft.Icons.ARROW_UPWARD, size=12, visible=False)
            self._sliders[stat], self._fields[stat], self._computed[stat], self._arrows[stat] = slider, field, computed, arrow
            rows.append(ft.Row(spacing=Space.SM, vertical_alignment=ft.CrossAxisAlignment.CENTER, controls=[
                ft.Row(spacing=2, tight=True, width=label_width, controls=[ft.Text(STAT_LABELS[stat], theme_style=ft.TextThemeStyle.LABEL_MEDIUM, color=STAT_COLORS[stat]), arrow]),
                slider, field, computed,
            ]))

        self._total = ft.Text("", theme_style=ft.TextThemeStyle.LABEL_MEDIUM, color=Palette.ON_SURFACE)
        self._total_bar = ft.ProgressBar(value=0, bar_height=6, color=Palette.PRIMARY, bgcolor=Palette.OUTLINE_VARIANT, expand=True)
        self.controls = [
            self._nature,
            *rows,
            ft.Row(spacing=Space.SM, vertical_alignment=ft.CrossAxisAlignment.CENTER, controls=[self._total_bar, self._total]),
        ]
        self._recompute()

    # -- values ----------------------------------------------------------------------------------

    @property
    def nature(self) -> str:
        return (self._nature.value or "hardy").lower()

    @property
    def points(self) -> dict[str, int]:
        """Invested stats only, in stat order."""
        return {k: v for k, v in self._points.items() if v > 0}

    @property
    def total(self) -> int:
        return points_total(self._points)

    @property
    def remaining(self) -> int:
        return MAX_POINTS_TOTAL - self.total

    @property
    def stats(self) -> PokemonStats:
        try:
            return champions_stats(self._base, self._points, self.nature)
        except ValueError:  # unknown nature stored by an older version — show neutral
            return champions_stats(self._base, self._points, None)

    def set_base_stats(self, stats: PokemonStats) -> None:
        self._base = stats
        self._recompute()

    def set_values(self, nature: str | None, points: Mapping[str, int] | None) -> None:
        """Replace nature and points without notifying (a load, not an edit)."""
        self._nature.value = (nature or "hardy").lower()
        for stat in STAT_ORDER:
            self._set_point(stat, int((points or {}).get(stat, 0)))
        self._recompute()

    def apply_points(self, points: Mapping[str, int]) -> None:
        """Apply a preset (an edit: listeners are notified)."""
        for stat in STAT_ORDER:
            self._set_point(stat, int(points.get(stat, 0)))
        self._changed()

    def set_min_speed(self) -> None:
        """0 Speed points and a −Spe nature that keeps the current boost (Trick Room)."""
        self._set_point("speed", 0)
        up, down = NATURES.get(self.nature, (None, None))
        if down != "speed":
            self._nature.value = _MIN_SPEED_NATURE.get(up or "", "brave")
        self._changed()

    # -- edits -----------------------------------------------------------------------------------

    def _clamp(self, stat: str, value: int) -> int:
        """0–32, and never past the 66-point budget shared with the other stats."""
        others = self.total - self._points[stat]
        return max(0, min(MAX_POINTS_PER_STAT, value, MAX_POINTS_TOTAL - others))

    def _set_point(self, stat: str, value: int) -> None:
        self._points[stat] = max(0, min(MAX_POINTS_PER_STAT, value))
        self._sliders[stat].value = self._points[stat]
        self._fields[stat].value = str(self._points[stat])

    def _slider_changed(self, stat: str, value: int) -> None:
        self._set_point(stat, self._clamp(stat, value))
        self._changed()

    def _typed(self, stat: str, text: str) -> None:
        try:
            value = int(text)
        except ValueError:
            return
        self._set_point(stat, self._clamp(stat, value))
        self._changed()

    def _changed(self) -> None:
        self._recompute()
        if self._on_change is not None:
            self._on_change(self.nature, self.points)

    def _recompute(self) -> None:
        total = self.total
        over = total > MAX_POINTS_TOTAL
        self._total.value = f"{total} / {MAX_POINTS_TOTAL} · {MAX_POINTS_TOTAL - total} left" if not over else f"{total} / {MAX_POINTS_TOTAL} · over by {total - MAX_POINTS_TOTAL}"
        self._total_bar.value = min(1.0, total / MAX_POINTS_TOTAL)
        self._total_bar.color = Palette.ERROR if over else Palette.PRIMARY
        self._total.color = Palette.ERROR if over else Palette.ON_SURFACE
        stats = self.stats
        for stat in STAT_ORDER:
            self._computed[stat].value = str(getattr(stats, stat))
            try:
                mult = nature_multiplier(self.nature, stat)
            except ValueError:
                mult = 1.0
            arrow = self._arrows[stat]
            arrow.visible = mult != 1.0
            arrow.icon = ft.Icons.ARROW_UPWARD if mult > 1.0 else ft.Icons.ARROW_DOWNWARD
            arrow.color = Palette.SUCCESS if mult > 1.0 else Palette.ERROR
        self._safe_update()

    def _safe_update(self) -> None:
        try:
            if self.page is not None:
                self.update()
        except RuntimeError:
            pass

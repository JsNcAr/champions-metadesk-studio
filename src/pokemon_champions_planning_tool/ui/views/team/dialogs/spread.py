"""Spread editor: nature, level, EV sliders, IVs, presets, live level-50 stats."""

from __future__ import annotations

from collections.abc import Callable

import flet as ft

from .....domain.entities.pokemon_stats import PokemonStats
from .....domain.stat_calc import MAX_EV_PER_STAT, MAX_EV_TOTAL, MAX_IV, NATURES, calc_all, nature_label, nature_multiplier
from ....components.banner import InlineBanner
from ....theme import STAT_COLORS, STAT_LABELS, STAT_ORDER, Palette, Space

# EV presets: (label, evs)
PRESETS: dict[str, dict[str, int]] = {
    "Physical sweeper": {"attack": 252, "speed": 252, "hp": 4},
    "Special sweeper": {"special_attack": 252, "speed": 252, "hp": 4},
    "Bulky": {"hp": 252, "defense": 128, "special_defense": 128},
    "Trick Room": {"hp": 252, "attack": 252, "special_defense": 4},
}
IV_PRESETS: dict[str, dict[str, int]] = {
    "0 Atk": {"attack": 0},
    "0 Spe": {"speed": 0},
    "31 all": {},
}

SaveHandler = Callable[[str, int, dict[str, int], dict[str, int]], list[str]]


class SpreadDialog(ft.AlertDialog):
    def __init__(
        self,
        *,
        title: str,
        base_stats: PokemonStats,
        nature: str | None,
        level: int,
        evs: dict[str, int],
        ivs: dict[str, int],
        on_save: SaveHandler,
        on_close: Callable[[], None],
    ) -> None:
        super().__init__(modal=True, scrollable=True)
        self._base = base_stats
        self._on_save = on_save
        self._on_close = on_close
        self._evs = {k: int(evs.get(k, 0)) for k in STAT_ORDER}
        self._ivs = {k: int(ivs.get(k, MAX_IV)) for k in STAT_ORDER}

        self._nature = ft.Dropdown(
            label="Nature", width=230, dense=True, enable_filter=True,
            value=(nature or "hardy").lower(),
            options=[ft.DropdownOption(key=n, text=nature_label(n)) for n in NATURES],
            on_select=lambda _e: self._recompute(),
        )
        self._level = ft.TextField(label="Level", value=str(level or 50), width=90, dense=True, keyboard_type=ft.KeyboardType.NUMBER,
                                   on_change=lambda _e: self._recompute())
        self._level_minus = ft.IconButton(icon=ft.Icons.REMOVE, icon_size=16, on_click=lambda _e: self._bump_level(-1))
        self._level_plus = ft.IconButton(icon=ft.Icons.ADD, icon_size=16, on_click=lambda _e: self._bump_level(+1))

        self._sliders: dict[str, ft.Slider] = {}
        self._ev_fields: dict[str, ft.TextField] = {}
        self._iv_fields: dict[str, ft.TextField] = {}
        self._computed: dict[str, ft.Text] = {}
        self._arrows: dict[str, ft.Icon] = {}
        rows: list[ft.Control] = [
            ft.Row(spacing=Space.SM, controls=[
                ft.Container(width=44), ft.Text("EVs", theme_style=ft.TextThemeStyle.LABEL_SMALL, color=Palette.ON_SURFACE_VARIANT, expand=True),
                ft.Text("EV", theme_style=ft.TextThemeStyle.LABEL_SMALL, color=Palette.ON_SURFACE_VARIANT, width=56, text_align=ft.TextAlign.CENTER),
                ft.Text("IV", theme_style=ft.TextThemeStyle.LABEL_SMALL, color=Palette.ON_SURFACE_VARIANT, width=48, text_align=ft.TextAlign.CENTER),
                ft.Text("Stat", theme_style=ft.TextThemeStyle.LABEL_SMALL, color=Palette.ON_SURFACE_VARIANT, width=52, text_align=ft.TextAlign.RIGHT),
            ])
        ]
        for stat in STAT_ORDER:
            slider = ft.Slider(min=0, max=MAX_EV_PER_STAT, divisions=63, value=self._evs[stat], expand=True, active_color=STAT_COLORS[stat],
                               on_change=lambda e, stat=stat: self._slider_changed(stat, int(e.control.value)))
            ev_field = ft.TextField(value=str(self._evs[stat]), width=56, dense=True, text_align=ft.TextAlign.CENTER, keyboard_type=ft.KeyboardType.NUMBER,
                                    on_change=lambda e, stat=stat: self._ev_typed(stat, e.control.value or ""))
            iv_field = ft.TextField(value=str(self._ivs[stat]), width=48, dense=True, text_align=ft.TextAlign.CENTER, keyboard_type=ft.KeyboardType.NUMBER,
                                    on_change=lambda e, stat=stat: self._iv_typed(stat, e.control.value or ""))
            computed = ft.Text("", theme_style=ft.TextThemeStyle.LABEL_MEDIUM, weight=ft.FontWeight.W_600, color=Palette.ON_SURFACE, width=52, text_align=ft.TextAlign.RIGHT)
            arrow = ft.Icon(ft.Icons.ARROW_UPWARD, size=12, visible=False)
            self._sliders[stat], self._ev_fields[stat], self._iv_fields[stat], self._computed[stat], self._arrows[stat] = slider, ev_field, iv_field, computed, arrow
            rows.append(ft.Row(spacing=Space.SM, vertical_alignment=ft.CrossAxisAlignment.CENTER, controls=[
                ft.Row(spacing=2, tight=True, width=44, controls=[ft.Text(STAT_LABELS[stat], theme_style=ft.TextThemeStyle.LABEL_MEDIUM, color=STAT_COLORS[stat]), arrow]),
                slider, ev_field, iv_field, computed,
            ]))

        self._total = ft.Text("", theme_style=ft.TextThemeStyle.LABEL_MEDIUM, color=Palette.ON_SURFACE)
        self._total_bar = ft.ProgressBar(value=0, bar_height=6, color=Palette.PRIMARY, bgcolor=Palette.OUTLINE_VARIANT, expand=True)
        self._banner = InlineBanner(visible=False)
        presets = ft.Row(spacing=Space.XS, wrap=True, controls=[
            *[ft.Chip(label=ft.Text(name), show_checkmark=False, on_click=lambda _e, evs=evs: self._apply_evs(evs)) for name, evs in PRESETS.items()],
            ft.Chip(label=ft.Text("Reset EVs"), show_checkmark=False, on_click=lambda _e: self._apply_evs({})),
        ])
        iv_presets = ft.Row(spacing=Space.XS, wrap=True, controls=[
            ft.Chip(label=ft.Text(name), show_checkmark=False, on_click=lambda _e, ivs=ivs: self._apply_ivs(ivs)) for name, ivs in IV_PRESETS.items()
        ])

        self.title = ft.Text(f"Spread · {title}")
        self.content = ft.Container(
            width=560,
            content=ft.Column(spacing=Space.MD, tight=True, controls=[
                ft.Row(spacing=Space.SM, vertical_alignment=ft.CrossAxisAlignment.CENTER, controls=[self._nature, ft.Container(expand=True), self._level_minus, self._level, self._level_plus]),
                *rows,
                ft.Row(spacing=Space.SM, vertical_alignment=ft.CrossAxisAlignment.CENTER, controls=[self._total_bar, self._total]),
                ft.Text("EV presets", theme_style=ft.TextThemeStyle.LABEL_SMALL, color=Palette.ON_SURFACE_VARIANT),
                presets,
                ft.Text("IV presets", theme_style=ft.TextThemeStyle.LABEL_SMALL, color=Palette.ON_SURFACE_VARIANT),
                iv_presets,
                self._banner,
            ]),
        )
        self.actions = [ft.TextButton("Cancel", on_click=lambda _e: self._on_close()), ft.FilledButton("Save spread", on_click=lambda _e: self._save())]
        self.actions_alignment = ft.MainAxisAlignment.END
        self._recompute()

    # -- values ----------------------------------------------------------------------------------

    @property
    def level(self) -> int:
        try:
            return max(1, min(100, int(self._level.value or 50)))
        except ValueError:
            return 50

    def _bump_level(self, delta: int) -> None:
        self._level.value = str(max(1, min(100, self.level + delta)))
        self._recompute()

    def _slider_changed(self, stat: str, value: int) -> None:
        self._evs[stat] = max(0, min(MAX_EV_PER_STAT, value // 4 * 4))
        self._ev_fields[stat].value = str(self._evs[stat])
        self._recompute()

    def _ev_typed(self, stat: str, text: str) -> None:
        try:
            value = max(0, min(MAX_EV_PER_STAT, int(text)))
        except ValueError:
            return
        self._evs[stat] = value
        self._sliders[stat].value = value
        self._recompute()

    def _iv_typed(self, stat: str, text: str) -> None:
        try:
            self._ivs[stat] = max(0, min(MAX_IV, int(text)))
        except ValueError:
            return
        self._recompute()

    def _apply_evs(self, evs: dict[str, int]) -> None:
        for stat in STAT_ORDER:
            self._evs[stat] = int(evs.get(stat, 0))
            self._sliders[stat].value = self._evs[stat]
            self._ev_fields[stat].value = str(self._evs[stat])
        self._recompute()

    def _apply_ivs(self, ivs: dict[str, int]) -> None:
        for stat in STAT_ORDER:
            self._ivs[stat] = int(ivs.get(stat, MAX_IV))
            self._iv_fields[stat].value = str(self._ivs[stat])
        self._recompute()

    def _recompute(self) -> None:
        total = sum(self._evs.values())
        self._total.value = f"EVs {total} / {MAX_EV_TOTAL}"
        self._total_bar.value = min(1.0, total / MAX_EV_TOTAL)
        over = total > MAX_EV_TOTAL
        self._total_bar.color = Palette.ERROR if over else Palette.PRIMARY
        self._total.color = Palette.ERROR if over else Palette.ON_SURFACE
        nature = self._nature.value or "hardy"
        try:
            stats = calc_all(self._base, self._evs, self._ivs, nature, self.level)
        except ValueError:
            stats = calc_all(self._base, self._evs, self._ivs, None, self.level)
        for stat in STAT_ORDER:
            self._computed[stat].value = str(getattr(stats, stat))
            try:
                mult = nature_multiplier(nature, stat)
            except ValueError:
                mult = 1.0
            arrow = self._arrows[stat]
            arrow.visible = mult != 1.0
            arrow.name = ft.Icons.ARROW_UPWARD if mult > 1.0 else ft.Icons.ARROW_DOWNWARD
            arrow.color = Palette.SUCCESS if mult > 1.0 else Palette.ERROR
        if over:
            self._banner.show(f"EV total {total} exceeds {MAX_EV_TOTAL}", "error")
        else:
            self._banner.hide()
        self._safe_update()

    def _save(self) -> None:
        problems = self._on_save(self._nature.value or "hardy", self.level, dict(self._evs), dict(self._ivs))
        if problems:
            self._banner.show("; ".join(problems), "error")
            self._safe_update()

    def _safe_update(self) -> None:
        try:
            if self.page is not None:
                self.update()
        except RuntimeError:
            pass

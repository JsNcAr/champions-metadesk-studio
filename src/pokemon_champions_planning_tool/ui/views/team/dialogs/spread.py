"""Spread dialog: Champions stat points (0–32 per stat, 66 total), nature and presets.

Level 50 and 31 IVs are fixed in Champions, so there is nothing else to edit. The editor
itself is the shared ``SpreadEditor`` component; this dialog adds presets and the save flow.
"""

from __future__ import annotations

from collections.abc import Callable

import flet as ft

from .....domain.entities.pokemon_stats import PokemonStats
from ....components.banner import InlineBanner
from ....components.spread_editor import SpreadEditor
from ....theme import Palette, Space

# Presets in stat points (a "252 / 252 / 4" EV spread is 32 / 32 / 2 — see points_from_evs).
PRESETS: dict[str, dict[str, int]] = {
    "Physical sweeper": {"attack": 32, "speed": 32, "hp": 2},
    "Special sweeper": {"special_attack": 32, "speed": 32, "hp": 2},
    "Bulky physical": {"hp": 32, "defense": 32, "special_defense": 2},
    "Bulky special": {"hp": 32, "special_defense": 32, "defense": 2},
    "Trick Room": {"hp": 32, "attack": 32, "special_defense": 2},
    "Balanced": {"hp": 32, "defense": 17, "special_defense": 17},
}

SaveHandler = Callable[[str, dict[str, int]], list[str]]


class SpreadDialog(ft.AlertDialog):
    def __init__(
        self,
        *,
        title: str,
        base_stats: PokemonStats,
        nature: str | None,
        points: dict[str, int],
        on_save: SaveHandler,
        on_close: Callable[[], None],
    ) -> None:
        super().__init__(modal=True, scrollable=True)
        self._on_save = on_save
        self._on_close = on_close
        self._editor = SpreadEditor(base_stats=base_stats, nature=nature, points=points, on_change=lambda _n, _p: self._banner.hide())
        # Shared controls, exposed for tests and for callers that tweak them directly.
        self._nature = self._editor._nature
        self._computed = self._editor._computed
        self._banner = InlineBanner(visible=False)

        presets = ft.Row(spacing=Space.XS, wrap=True, controls=[
            *[ft.Chip(label=ft.Text(name), show_checkmark=False, on_click=lambda _e, pts=pts, name=name: self._preset(name, pts)) for name, pts in PRESETS.items()],
            ft.Chip(label=ft.Text("Min speed"), show_checkmark=False, tooltip="0 Speed points and a −Spe nature", on_click=lambda _e: self._editor.set_min_speed()),
            ft.Chip(label=ft.Text("Reset"), show_checkmark=False, on_click=lambda _e: self._editor.apply_points({})),
        ])

        self.title = ft.Text(f"Spread · {title}")
        self.content = ft.Container(
            width=560,
            content=ft.Column(spacing=Space.MD, tight=True, controls=[
                ft.Text("Level 50 · 31 IVs (fixed in Champions)", theme_style=ft.TextThemeStyle.BODY_SMALL, color=Palette.ON_SURFACE_VARIANT),
                self._editor,
                ft.Text("Presets", theme_style=ft.TextThemeStyle.LABEL_SMALL, color=Palette.ON_SURFACE_VARIANT),
                presets,
                self._banner,
            ]),
        )
        self.actions = [ft.TextButton("Cancel", on_click=lambda _e: self._on_close()), ft.FilledButton("Save spread", on_click=lambda _e: self._save())]
        self.actions_alignment = ft.MainAxisAlignment.END

    # -- values ----------------------------------------------------------------------------------

    @property
    def points(self) -> dict[str, int]:
        return self._editor.points

    @property
    def nature(self) -> str:
        return self._editor.nature

    def _preset(self, name: str, points: dict[str, int]) -> None:
        self._editor.apply_points(points)
        if name == "Trick Room":
            self._editor.set_min_speed()

    def _apply_points(self, points: dict[str, int]) -> None:
        self._editor.apply_points(points)

    def _recompute(self) -> None:
        self._editor._recompute()

    def _save(self) -> None:
        problems = self._on_save(self.nature, self.points)
        if problems:
            self._banner.show("; ".join(problems), "error")
            self._safe_update()

    def _safe_update(self) -> None:
        try:
            if self.page is not None:
                self.update()
        except RuntimeError:
            pass

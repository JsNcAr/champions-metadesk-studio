"""Each side's best hit on the other, on one line in its column's header:
"Best: Knock Off 57.6–68.3% · guaranteed 2HKO". A click opens that move's card. Who moves
first is the Spe chip beside the name (▲ first, ▼ second), so no separate bar is needed."""

from __future__ import annotations

from collections.abc import Callable

import flet as ft

from ...tasks import safe_update
from ...theme import Palette, Radius, Space
from .move_card import damage_colour
from .state import MoveResult
from .store import CalcStore, best_of


class BestHit(ft.Container):
    def __init__(self, side: str, *, store: CalcStore, on_open: Callable[[str, int], None] | None = None) -> None:
        super().__init__()
        self.side = side
        self.other = "right" if side == "left" else "left"
        self.store = store
        self._on_open = on_open
        self.best: MoveResult | None = None
        self._move = ft.Text("", theme_style=ft.TextThemeStyle.LABEL_LARGE, weight=ft.FontWeight.W_600, color=Palette.ON_SURFACE, max_lines=1)
        self._pct = ft.Text("", theme_style=ft.TextThemeStyle.LABEL_LARGE, weight=ft.FontWeight.W_700, max_lines=1)
        self._ko = ft.Text("", theme_style=ft.TextThemeStyle.LABEL_MEDIUM, color=Palette.ON_SURFACE_VARIANT, max_lines=1,
                           overflow=ft.TextOverflow.ELLIPSIS, expand=True, expand_loose=True)
        self.content = ft.Row(spacing=Space.XS, tight=True, alignment=ft.MainAxisAlignment.END, vertical_alignment=ft.CrossAxisAlignment.CENTER, controls=[
            ft.Text("Best:", theme_style=ft.TextThemeStyle.LABEL_MEDIUM, color=Palette.ON_SURFACE_VARIANT), self._move, self._pct, self._ko,
        ])
        self.padding = ft.Padding.symmetric(horizontal=Space.XS)
        self.border_radius = Radius.SM
        self.ink = True
        self.on_click = lambda _e: self.open()
        self.visible = False

    def update_from(self) -> None:
        ready = self.store.species(self.side) is not None and self.store.species(self.other) is not None
        results = self.store.results.left_vs_right if self.side == "left" else self.store.results.right_vs_left
        best = best_of(results) if ready else None
        self.best = best
        self.visible = ready
        if best is None:
            self._move.value, self._pct.value, self._ko.value = "no damaging move yet", "", ""
            self._move.color = Palette.ON_SURFACE_VARIANT
            self.tooltip = None
        else:
            self._move.value = best.name
            self._move.color = Palette.ON_SURFACE
            self._pct.value = f"{best.min_pct:g}–{best.max_pct:g}%"
            self._pct.color = damage_colour(best.max_pct)
            self._ko.value = f"· {best.ko_text}" if best.ko_text else ""
            self._ko.color = Palette.ERROR if "OHKO" in best.ko_text else Palette.ON_SURFACE_VARIANT
            self.tooltip = f"{best.name} {best.min_pct:g}–{best.max_pct:g}% {best.ko_text}".strip() + "\nClick to open the move"
        safe_update(self)

    def open(self) -> None:
        if self.best is not None and self._on_open is not None:
            self._on_open(self.side, self.best.index)


__all__ = ["BestHit"]

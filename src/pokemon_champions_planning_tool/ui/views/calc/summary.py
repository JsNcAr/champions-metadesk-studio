"""The matchup at a glance, pinned under the page header: each side's best hit on the other
(damage range and KO text) and who moves first. The answer to "who wins this exchange" is
visible without scrolling to the move cards. Clicking a side's hit opens that move's card."""

from __future__ import annotations

from collections.abc import Callable

import flet as ft

from ...theme import Palette, Radius, Space
from ...tasks import safe_update
from .move_card import damage_colour
from .state import MoveResult
from .store import CalcStore, best_of


class _Direction(ft.Column):
    """`Garchomp → Incineroar` over `Earthquake  56.4–66.3%  guaranteed 2HKO`."""

    def __init__(self, *, align_end: bool) -> None:
        align = ft.CrossAxisAlignment.END if align_end else ft.CrossAxisAlignment.START
        super().__init__(spacing=2, tight=True, expand=True, horizontal_alignment=align)
        self._title = ft.Text("", theme_style=ft.TextThemeStyle.LABEL_SMALL, color=Palette.ON_SURFACE_VARIANT, max_lines=1, overflow=ft.TextOverflow.ELLIPSIS)
        self._move = ft.Text("", theme_style=ft.TextThemeStyle.BODY_MEDIUM, weight=ft.FontWeight.W_600, color=Palette.ON_SURFACE, max_lines=1, overflow=ft.TextOverflow.ELLIPSIS)
        self._pct = ft.Text("", theme_style=ft.TextThemeStyle.TITLE_MEDIUM, weight=ft.FontWeight.W_700)
        self._ko = ft.Text("", theme_style=ft.TextThemeStyle.BODY_SMALL, color=Palette.ON_SURFACE_VARIANT, max_lines=1, overflow=ft.TextOverflow.ELLIPSIS)
        line = [self._move, self._pct, self._ko]
        self.controls = [
            self._title,
            ft.Row(spacing=Space.SM, tight=True, wrap=True, vertical_alignment=ft.CrossAxisAlignment.CENTER,
                   alignment=ft.MainAxisAlignment.END if align_end else ft.MainAxisAlignment.START, controls=line),
        ]

    def show(self, title: str, best: MoveResult | None, empty: str) -> None:
        self._title.value = title
        if best is None:
            self._move.value = empty
            self._move.color = Palette.ON_SURFACE_VARIANT
            self._move.weight = ft.FontWeight.W_400
            self._pct.value = self._ko.value = ""
            return
        self._move.value = best.name
        self._move.color = Palette.ON_SURFACE
        self._move.weight = ft.FontWeight.W_600
        self._pct.value = f"{best.min_pct:g}–{best.max_pct:g}%"
        self._pct.color = damage_colour(best.max_pct)
        self._ko.value = best.ko_text
        self._ko.color = Palette.ERROR if "OHKO" in best.ko_text else Palette.ON_SURFACE_VARIANT


class MatchupBar(ft.Container):
    def __init__(self, *, store: CalcStore, on_open: Callable[[str, int], None] | None = None) -> None:
        super().__init__()
        self.store = store
        self._on_open = on_open
        self._left = _Direction(align_end=False)
        self._right = _Direction(align_end=True)
        self._best: dict[str, MoveResult | None] = {"left": None, "right": None}
        self._left_hit = ft.Container(content=self._left, expand=True, ink=True, border_radius=Radius.SM, padding=ft.Padding.symmetric(horizontal=Space.XS),
                                      on_click=lambda _e: self._open("left"))
        self._right_hit = ft.Container(content=self._right, expand=True, ink=True, border_radius=Radius.SM, padding=ft.Padding.symmetric(horizontal=Space.XS),
                                       on_click=lambda _e: self._open("right"))
        self._speed = ft.Text("", theme_style=ft.TextThemeStyle.LABEL_MEDIUM, color=Palette.ON_SURFACE_VARIANT, text_align=ft.TextAlign.CENTER)
        self._hint = ft.Text("Pick an attacker and a defender to see the matchup here.", theme_style=ft.TextThemeStyle.BODY_SMALL, color=Palette.ON_SURFACE_VARIANT)
        self._body = ft.Row(spacing=Space.LG, vertical_alignment=ft.CrossAxisAlignment.CENTER, controls=[
            self._left_hit,
            ft.Container(content=self._speed, padding=ft.Padding.symmetric(horizontal=Space.SM)),
            self._right_hit,
        ])
        self.content = ft.Stack(controls=[self._hint, self._body])
        self.bgcolor = Palette.SURFACE_2
        self.border_radius = Radius.MD
        self.border = ft.Border.all(1, Palette.OUTLINE_VARIANT)
        self.padding = ft.Padding.symmetric(horizontal=Space.MD, vertical=Space.SM)

    def update_from(self) -> None:
        left, right = self.store.species("left"), self.store.species("right")
        ready = left is not None and right is not None
        self._hint.visible = not ready
        self._body.visible = ready
        if ready:
            results = self.store.results
            self._best = {"left": best_of(results.left_vs_right), "right": best_of(results.right_vs_left)}
            self._left.show(f"{left.name} → {right.name}", self._best["left"], "No damaging move yet")
            self._right.show(f"{right.name} → {left.name}", self._best["right"], "No damaging move yet")
            for side, hit in (("left", self._left_hit), ("right", self._right_hit)):
                hit.tooltip = "Open this move's details and benchmarks" if self._best[side] is not None else None
            order = self.store.speed_order()
            a, b = results.left_speed, results.right_speed
            room = " (Trick Room)" if self.store.state.field.trick_room else ""
            if order == "tie":
                self._speed.value = f"Speed tie · {a}"
                self._speed.color = Palette.WARNING
            else:
                first = left.name if order == "left" else right.name
                self._speed.value = f"{first} moves first{room}\n{a} vs {b}"
                self._speed.color = Palette.SUCCESS if order == "left" else Palette.ERROR
        safe_update(self)

    def _open(self, side: str) -> None:
        best = self._best.get(side)
        if best is not None and self._on_open is not None:
            self._on_open(side, best.index)

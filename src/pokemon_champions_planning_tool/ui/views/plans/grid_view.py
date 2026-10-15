"""The plan's matchup grid: a field bar (format, weather, terrain, Trick Room, each side's
Tailwind and Stealth Rock) over your six (rows) against their six (columns), each cell
classed and coloured like Calc's Team vs team grid. Clicking a cell opens the pair in Calc
under the same field."""

from __future__ import annotations

from collections.abc import Callable, Sequence
from dataclasses import replace
from typing import Any

import flet as ft

from ...tasks import is_mounted
from ...theme import Accent, Palette, Radius, Space, alpha
from ..calc.classes import CLASS_BG, CLASS_BORDER, CLASS_HELP
from ..calc.dialogs.team_matrix import summarise
from ..calc.hit import hit_text, speed_line
from ..calc.state import DOUBLES_ONLY, SWEEP_CLASSES, TERRAINS, WEATHERS, FieldState, PokemonState, SideConditions, TeamRating
from .components import species_sprite

CELL_W = 96
CELL_H = 58
NAME_W = 136
ANSWERS_W = 64

GRID_TIP = (
    "Each cell is your Pokémon (row) against theirs (column), from your side, under the field above: "
    "→ your best hit, ← theirs, ▲ you move first, ▼ they do. Click a cell to open both in Calc with this field."
)


def cell_tooltip(rating: TeamRating, your_name: str, rival_name: str) -> str:
    label = dict(SWEEP_CLASSES).get(rating.klass, rating.klass)
    return "\n".join((
        f"{your_name} vs {rival_name}: {label} — {CLASS_HELP.get(rating.klass, '')}",
        f"You: {hit_text(rating.your_best, ko=True)}",
        f"Them: {hit_text(rating.their_best, ko=True)}",
        speed_line(rating),
        "Click to open both in Calc · right-click to pin it to the plan",
    ))


def _pct(result) -> str:
    return f"{result.min_pct:g}–{result.max_pct:g}%" if result is not None else "—"


def _speed_mark(rating: TeamRating) -> str:
    if rating.your_speed == rating.their_speed:
        return "="
    return "▲" if rating.faster else "▼"


def _label(text: str, *, width: int, bold: bool = False, color: str = Palette.ON_SURFACE_VARIANT, align=ft.TextAlign.CENTER, tooltip: str | None = None) -> ft.Text:
    return ft.Text(text, width=width, text_align=align, theme_style=ft.TextThemeStyle.LABEL_SMALL, color=color,
                   weight=ft.FontWeight.W_600 if bold else None, max_lines=1, overflow=ft.TextOverflow.ELLIPSIS, tooltip=tooltip)


class GridSection(ft.Column):
    def __init__(self, *, catalogs: Any, on_field: Callable[[FieldState], None], on_cell: Callable[[str, int], None],
                 on_pin: Callable[[str, int], None] | None = None) -> None:
        super().__init__(spacing=Space.SM, tight=True)
        self.catalogs = catalogs
        self._on_field = on_field
        self._on_cell = on_cell
        self._on_pin = on_pin
        self.field = FieldState()
        self._bar = ft.Row(spacing=Space.SM, wrap=True, run_spacing=Space.SM, vertical_alignment=ft.CrossAxisAlignment.CENTER)
        self._status = ft.Row(spacing=Space.SM, visible=False, controls=[
            ft.ProgressRing(width=14, height=14, stroke_width=2),
            ft.Text("Calculating every pairing…", theme_style=ft.TextThemeStyle.BODY_SMALL, color=Palette.ON_SURFACE_VARIANT),
        ])
        self._table = ft.Column(spacing=Space.XS, tight=True)
        self._legend = ft.Row(spacing=Space.SM, wrap=True, controls=[
            ft.Container(content=ft.Text(label, theme_style=ft.TextThemeStyle.LABEL_SMALL, color=Palette.ON_SURFACE), tooltip=CLASS_HELP[key],
                         bgcolor=CLASS_BG[key], border=CLASS_BORDER[key], border_radius=Radius.SM, padding=ft.Padding.symmetric(horizontal=Space.SM, vertical=2))
            for key, label in SWEEP_CLASSES
        ])
        self.controls = [self._bar, self._status, ft.Row(scroll=ft.ScrollMode.AUTO, controls=[self._table]), self._legend]

    # -- field bar ------------------------------------------------------------------------

    def set_field(self, field: FieldState) -> None:
        self.field = field
        self._bar.controls = [
            ft.SegmentedButton(
                selected=[field.game_type], allow_multiple_selection=False, allow_empty_selection=False, show_selected_icon=False,
                segments=[ft.Segment(value="doubles", label=ft.Text("Doubles")), ft.Segment(value="singles", label=ft.Text("Singles"))],
                on_change=lambda e: self._change(game_type=next(iter(e.control.selected or ["doubles"]))),
            ),
            self._menu("Weather", field.weather, WEATHERS, lambda v: self._change(weather=v)),
            self._menu("Terrain", field.terrain, TERRAINS, lambda v: self._change(terrain=v)),
            self._toggle("Trick Room", field.trick_room, lambda: self._change(trick_room=not self.field.trick_room),
                         tip="Reverses who moves first (the damage is the same)"),
            ft.Container(width=1, height=24, bgcolor=Palette.OUTLINE_VARIANT),
            *self._side_toggles("left", "Your", field.left),
            ft.Container(width=1, height=24, bgcolor=Palette.OUTLINE_VARIANT),
            *self._side_toggles("right", "Their", field.right),
        ]

    def _side_toggles(self, side: str, who: str, cond: SideConditions) -> list[ft.Control]:
        return [
            self._toggle(f"{who} Tailwind", cond.tailwind, lambda s=side: self._side(s, tailwind=not getattr(self.field, s).tailwind),
                         tip=f"Tailwind on {who.lower()} side: doubles their Speed"),
            self._toggle(f"Rocks on {who.lower()} side", cond.stealth_rock, lambda s=side: self._side(s, stealth_rock=not getattr(self.field, s).stealth_rock),
                         tip=f"Stealth Rock damage already taken by {who.lower()} Pokémon, counted in the KO chances"),
        ]

    def _toggle(self, label: str, on: bool, fn: Callable[[], None], *, tip: str | None = None) -> ft.Control:
        return ft.Container(
            content=ft.Text(label, theme_style=ft.TextThemeStyle.LABEL_LARGE, color=Palette.ON_SURFACE if on else Palette.ON_SURFACE_VARIANT,
                            weight=ft.FontWeight.W_700 if on else ft.FontWeight.W_500),
            height=32, padding=ft.Padding.symmetric(horizontal=Space.MD, vertical=6), border_radius=Radius.PILL,   # no alignment: it would fill the row
            bgcolor=alpha(Accent.PLANS, 0.18) if on else Palette.SURFACE_3, border=ft.Border.all(1, Accent.PLANS if on else Palette.OUTLINE_VARIANT),
            ink=True, on_click=lambda _e: fn(), tooltip=tip, data={"toggle": label, "on": on},
        )

    def _menu(self, label: str, value: str, options: Sequence[tuple[str, str]], fn: Callable[[str], None]) -> ft.Control:
        names = dict(options)
        set_ = value not in ("none", "", None)
        return ft.PopupMenuButton(
            tooltip=label,
            content=ft.Container(
                content=ft.Row(spacing=Space.XS, tight=True, vertical_alignment=ft.CrossAxisAlignment.CENTER, controls=[
                    ft.Text(names.get(value, label) if set_ else label, theme_style=ft.TextThemeStyle.LABEL_LARGE,
                            color=Palette.ON_SURFACE if set_ else Palette.ON_SURFACE_VARIANT, weight=ft.FontWeight.W_700 if set_ else ft.FontWeight.W_500),
                    ft.Icon(ft.Icons.ARROW_DROP_DOWN, size=16, color=Palette.ON_SURFACE_VARIANT),
                ]),
                height=32, padding=ft.Padding.only(left=Space.MD, right=Space.XS), border_radius=Radius.PILL,
                bgcolor=alpha(Accent.PLANS, 0.18) if set_ else Palette.SURFACE_3, border=ft.Border.all(1, Accent.PLANS if set_ else Palette.OUTLINE_VARIANT),
            ),
            items=[ft.PopupMenuItem(content=ft.Text(f"No {label.lower()}"), on_click=lambda _e: fn("none"))]
                  + [ft.PopupMenuItem(content=ft.Text(text), on_click=lambda _e, k=key: fn(k)) for key, text in options],
            data={"menu": label, "value": value},
        )

    def _change(self, **changes: Any) -> None:
        field = replace(self.field, **changes)
        if field.game_type == "singles":
            field = replace(field, left=replace(field.left, **{k: False for k in DOUBLES_ONLY}), right=replace(field.right, **{k: False for k in DOUBLES_ONLY}))
        self._on_field(field)

    def _side(self, side: str, **changes: Any) -> None:
        cond = replace(getattr(self.field, side), **changes)
        self._on_field(replace(self.field, **{side: cond}))

    # -- the table ------------------------------------------------------------------------

    def set_loading(self, loading: bool) -> None:
        self._status.visible = loading
        self._refresh()

    def set_error(self, exc: BaseException) -> None:
        self._status.visible = False
        self._table.controls = [ft.Text(f"Could not compute the grid: {exc}", color=Palette.ERROR)]
        self._refresh()

    def set_grid(self, grid: dict[tuple[str, int], TeamRating], mine: Sequence[tuple[str, PokemonState]], opponent: Sequence[PokemonState]) -> None:
        if not mine or not opponent:
            self._table.controls = [ft.Text("The grid needs Pokémon on both sides: fill your team, or add their team with Edit as paste…",
                                            theme_style=ft.TextThemeStyle.BODY_SMALL, color=Palette.ON_SURFACE_VARIANT)]
            self._refresh()
            return
        keys = [k for k, _ in mine]
        answers, per_rival = summarise(grid, keys, len(opponent))
        header: list[ft.Control] = [ft.Container(width=NAME_W)]
        for rival in opponent:
            header.append(ft.Container(width=CELL_W, alignment=ft.Alignment.CENTER, content=ft.Column(
                spacing=0, tight=True, horizontal_alignment=ft.CrossAxisAlignment.CENTER, controls=[
                    species_sprite(rival.species, self.catalogs, size=32),
                    _label(self._name(rival.species), width=CELL_W),
                ])))
        header.append(_label("Answers", width=ANSWERS_W, bold=True, tooltip="How many of theirs this Pokémon answers (Crushed or Mitigated)"))
        rows: list[ft.Control] = [ft.Row(spacing=Space.XS, controls=header)]
        for key, you in mine:
            cells: list[ft.Control] = [ft.Row(width=NAME_W, spacing=Space.XS, controls=[
                species_sprite(you.species, self.catalogs, size=28),
                _label(self._name(you.species), width=NAME_W - 34, color=Palette.ON_SURFACE, align=ft.TextAlign.LEFT),
            ])]
            for j, rival in enumerate(opponent):
                cells.append(self._cell(grid.get((key, j)), key, j, self._name(you.species), self._name(rival.species)))
            cells.append(_label(f"{answers.get(key, 0)} / {len(opponent)}", width=ANSWERS_W, bold=True, color=Palette.ON_SURFACE))
            rows.append(ft.Row(spacing=Space.XS, vertical_alignment=ft.CrossAxisAlignment.CENTER, controls=cells))
        footer: list[ft.Control] = [_label("Beaten by · threatens", width=NAME_W, align=ft.TextAlign.LEFT)]
        for j in range(len(opponent)):
            beaten, threats = per_rival.get(j, (0, 0))
            footer.append(ft.Container(width=CELL_W, alignment=ft.Alignment.CENTER, tooltip=f"{beaten} of yours beat it · it threatens {threats}",
                                       content=ft.Text(f"{beaten} · {threats}", theme_style=ft.TextThemeStyle.LABEL_SMALL, weight=ft.FontWeight.W_600,
                                                       color=Palette.ERROR if beaten == 0 else Palette.ON_SURFACE)))
        rows.append(ft.Row(spacing=Space.XS, controls=footer))
        self._table.controls = rows
        self._status.visible = False
        self._refresh()

    def _cell(self, rating: TeamRating | None, key: str, j: int, your_name: str, rival_name: str) -> ft.Control:
        if rating is None:
            return ft.Container(width=CELL_W, height=CELL_H, border_radius=Radius.SM, bgcolor=Palette.SURFACE_2, alignment=ft.Alignment.CENTER,
                                content=_label("—", width=CELL_W), tooltip="Not in the species catalogue")
        cell = ft.Container(
            width=CELL_W, height=CELL_H, border_radius=Radius.SM, bgcolor=CLASS_BG.get(rating.klass, Palette.SURFACE_2),
            border=CLASS_BORDER.get(rating.klass), alignment=ft.Alignment.CENTER, ink=True, tooltip=cell_tooltip(rating, your_name, rival_name),
            on_click=lambda _e: self._on_cell(key, j), data={"cell": (key, j), "klass": rating.klass},
            content=ft.Column(spacing=0, tight=True, horizontal_alignment=ft.CrossAxisAlignment.CENTER, controls=[
                _label(f"→ {_pct(rating.your_best)}", width=CELL_W, bold=True, color=Palette.ON_SURFACE),
                _label(f"← {_pct(rating.their_best)}", width=CELL_W),
                _label(f"{dict(SWEEP_CLASSES).get(rating.klass, rating.klass)} {_speed_mark(rating)}", width=CELL_W),
            ]),
        )
        if self._on_pin is None:
            return cell
        return ft.GestureDetector(content=cell, on_secondary_tap=lambda _e: self._on_pin(key, j), data={"pin_cell": (key, j)})

    def _name(self, canonical_id: str | None) -> str:
        if not canonical_id:
            return "?"
        species = self.catalogs.species_for(canonical_id)
        return species.name if species else canonical_id.replace("-", " ").title()

    def _refresh(self) -> None:
        if is_mounted(self):
            self.update()


__all__ = ["GRID_TIP", "GridSection", "cell_tooltip"]

"""Team vs team: your active team (rows) against a rival team (columns), every pairing
classified from your member's side. Clicking a cell loads both into the calculator."""

from __future__ import annotations

from collections.abc import Callable

import flet as ft

from .....domain.pokemon_identity import get_pokemon_sprite_url
from ....components import Sprite
from ....theme import Palette, Radius, Space
from ..classes import CLASS_BG, CLASS_BORDER, CLASS_HELP
from ..hit import hit_text, speed_line
from ..state import SWEEP_CLASSES, PokemonState, TeamRating

CELL_W = 76
CELL_H = 46
NAME_W = 132
GOOD = frozenset({"crushed", "mitigated"})


def cell_tooltip(rating: TeamRating, rival_name: str) -> str:
    label = dict(SWEEP_CLASSES).get(rating.klass, rating.klass)
    return "\n".join((
        f"{rating.name} vs {rival_name}: {label} — {CLASS_HELP.get(rating.klass, '')}",
        f"You: {hit_text(rating.your_best, ko=True)}",
        f"Them: {hit_text(rating.their_best, ko=True)}",
        speed_line(rating),
        "Click to load both",
    ))


def summarise(grid: dict[tuple[str, int], TeamRating], rows: list[str], columns: int) -> tuple[dict[str, int], dict[int, tuple[int, int]]]:
    """Per member: how many rivals it answers (Crushed or Mitigated). Per rival: how many of
    your members beat it, and how many it threatens."""
    answers = {key: sum(1 for c in range(columns) if (r := grid.get((key, c))) is not None and r.klass in GOOD) for key in rows}
    per_rival = {}
    for c in range(columns):
        cells = [grid[(key, c)] for key in rows if (key, c) in grid]
        per_rival[c] = (sum(1 for r in cells if r.klass in GOOD), sum(1 for r in cells if r.klass == "threat"))
    return answers, per_rival


def _label(text: str, *, width: int, bold: bool = False, color: str = Palette.ON_SURFACE_VARIANT, align=ft.TextAlign.CENTER) -> ft.Text:
    return ft.Text(text, width=width, text_align=align, theme_style=ft.TextThemeStyle.LABEL_SMALL, color=color,
                   weight=ft.FontWeight.W_600 if bold else None, max_lines=1, overflow=ft.TextOverflow.ELLIPSIS)


class TeamMatrixDialog(ft.AlertDialog):
    def __init__(self, *, team_name: str, rival_team_name: str, members: list[tuple[str, PokemonState]], rivals: list[PokemonState],
                 species_name: Callable[[str | None], str], on_pick: Callable[[str, int], None], on_close: Callable[[], None]) -> None:
        super().__init__(modal=False, scrollable=True)
        self._members = members
        self._rivals = rivals
        self._name = species_name
        self._on_pick = on_pick
        self.title = ft.Text(f"{team_name} vs {rival_team_name}")
        self._legend = ft.Row(spacing=Space.SM, wrap=True, controls=[
            ft.Container(content=ft.Text(label, theme_style=ft.TextThemeStyle.LABEL_SMALL, color=Palette.ON_SURFACE), tooltip=CLASS_HELP[key],
                         bgcolor=CLASS_BG[key], border=CLASS_BORDER[key], border_radius=Radius.SM, padding=ft.Padding.symmetric(horizontal=Space.SM, vertical=2))
            for key, label in SWEEP_CLASSES
        ])
        self._grid = ft.Column(spacing=Space.XS, tight=True, controls=[
            ft.Row(spacing=Space.SM, controls=[ft.ProgressRing(width=16, height=16, stroke_width=2),
                                               ft.Text("Computing every pairing…", theme_style=ft.TextThemeStyle.BODY_SMALL, color=Palette.ON_SURFACE_VARIANT)]),
        ])
        self.content = ft.Column(spacing=Space.MD, tight=True, controls=[
            ft.Text("Each cell is your member (row) against theirs (column), from your side, under the current field.",
                    theme_style=ft.TextThemeStyle.BODY_SMALL, color=Palette.ON_SURFACE_VARIANT),
            ft.Row(scroll=ft.ScrollMode.AUTO, controls=[self._grid]),
            self._legend,
        ])
        self.actions = [ft.TextButton("Close", on_click=lambda _e: on_close())]
        self.actions_alignment = ft.MainAxisAlignment.END

    def set_error(self, exc: BaseException) -> None:
        self._grid.controls = [ft.Text(f"Could not compute the grid: {exc}", color=Palette.ERROR)]
        self._safe_update(self)

    def set_grid(self, grid: dict[tuple[str, int], TeamRating]) -> None:
        keys = [key for key, _m in self._members]
        answers, per_rival = summarise(grid, keys, len(self._rivals))
        header: list[ft.Control] = [ft.Container(width=NAME_W)]
        for rival in self._rivals:
            header.append(ft.Container(width=CELL_W, alignment=ft.Alignment.CENTER, tooltip=self._name(rival.species), content=ft.Column(
                spacing=0, tight=True, horizontal_alignment=ft.CrossAxisAlignment.CENTER, controls=[
                    Sprite(get_pokemon_sprite_url(rival.species or ""), size=32),
                    _label(self._name(rival.species), width=CELL_W),
                ])))
        header.append(_label("Answers", width=64, bold=True))
        rows: list[ft.Control] = [ft.Row(spacing=Space.XS, controls=header)]
        for key, member in self._members:
            cells: list[ft.Control] = [ft.Row(width=NAME_W, spacing=Space.XS, controls=[
                Sprite(get_pokemon_sprite_url(member.species or ""), size=28),
                _label(self._name(member.species), width=NAME_W - 34, color=Palette.ON_SURFACE, align=ft.TextAlign.LEFT),
            ])]
            for index, rival in enumerate(self._rivals):
                cells.append(self._cell(grid.get((key, index)), key, index, self._name(rival.species)))
            cells.append(_label(f"{answers.get(key, 0)} / {len(self._rivals)}", width=64, bold=True, color=Palette.ON_SURFACE))
            rows.append(ft.Row(spacing=Space.XS, vertical_alignment=ft.CrossAxisAlignment.CENTER, controls=cells))
        footer: list[ft.Control] = [_label("Beaten by · threatens", width=NAME_W, align=ft.TextAlign.LEFT)]
        for index in range(len(self._rivals)):
            beaten, threats = per_rival.get(index, (0, 0))
            footer.append(ft.Container(width=CELL_W, alignment=ft.Alignment.CENTER,
                                       tooltip=f"{beaten} of your Pokémon beat it · it threatens {threats}",
                                       content=ft.Text(f"{beaten} · {threats}", theme_style=ft.TextThemeStyle.LABEL_SMALL, weight=ft.FontWeight.W_600,
                                                       color=Palette.ERROR if beaten == 0 else Palette.ON_SURFACE)))
        rows.append(ft.Row(spacing=Space.XS, controls=footer))
        self._grid.controls = rows
        self._safe_update(self)

    def _cell(self, rating: TeamRating | None, key: str, index: int, rival_name: str) -> ft.Control:
        if rating is None:
            return ft.Container(width=CELL_W, height=CELL_H, border_radius=Radius.SM, bgcolor=Palette.SURFACE_2,
                                content=_label("—", width=CELL_W), alignment=ft.Alignment.CENTER)
        best = rating.your_best
        return ft.Container(
            width=CELL_W, height=CELL_H, border_radius=Radius.SM, bgcolor=CLASS_BG.get(rating.klass, Palette.SURFACE_2),
            border=CLASS_BORDER.get(rating.klass), alignment=ft.Alignment.CENTER, ink=True, tooltip=cell_tooltip(rating, rival_name),
            on_click=lambda _e: self._on_pick(key, index),
            content=ft.Column(spacing=0, tight=True, horizontal_alignment=ft.CrossAxisAlignment.CENTER, controls=[
                _label(dict(SWEEP_CLASSES).get(rating.klass, rating.klass), width=CELL_W, bold=True, color=Palette.ON_SURFACE),
                _label(f"{best.max_pct:g}% {'▲' if rating.faster else '▼'}" if best else f"— {'▲' if rating.faster else '▼'}", width=CELL_W),
            ]),
        )

    @staticmethod
    def _safe_update(control: ft.Control) -> None:
        try:
            if control.page is not None:
                control.update()
        except RuntimeError:
            pass


__all__ = ["TeamMatrixDialog", "cell_tooltip", "summarise"]

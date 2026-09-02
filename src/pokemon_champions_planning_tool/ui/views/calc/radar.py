"""A small radar (hexagon) chart of a stat spread, drawn on a canvas."""

from __future__ import annotations

import math

import flet as ft
import flet.canvas as cv

from ....domain.entities.pokemon_stats import PokemonStats
from ...theme import STAT_COLORS, Palette, alpha

_AXES: tuple[tuple[str, str], ...] = (("hp", "HP"), ("attack", "Atk"), ("defense", "Def"), ("speed", "Spe"), ("special_defense", "SpD"), ("special_attack", "SpA"))
_MAX = 260  # a level-50 stat rarely exceeds this; the chart clamps above it


class RadarChart(ft.Container):
    def __init__(self, size: int = 150, colour: str = Palette.SECONDARY) -> None:
        super().__init__()
        self._size = size
        self._colour = colour
        self._canvas = cv.Canvas(width=size, height=size, shapes=[])
        self.content = self._canvas
        self.width = size
        self.height = size
        self.set_stats(None)

    def _point(self, index: int, radius: float) -> tuple[float, float]:
        angle = -math.pi / 2 + index * (2 * math.pi / len(_AXES))
        c = self._size / 2
        return c + radius * math.cos(angle), c + radius * math.sin(angle)

    def set_stats(self, stats: PokemonStats | None) -> None:
        c = self._size / 2
        outer = c - 22
        grid = ft.Paint(color=Palette.OUTLINE_VARIANT, style=ft.PaintingStyle.STROKE, stroke_width=1)
        shapes: list[cv.Shape] = []
        for ring in (1 / 3, 2 / 3, 1.0):
            pts = [self._point(i, outer * ring) for i in range(len(_AXES))]
            shapes.append(cv.Path([cv.Path.MoveTo(*pts[0]), *[cv.Path.LineTo(x, y) for x, y in pts[1:]], cv.Path.Close()], paint=grid))
        for i, (key, label) in enumerate(_AXES):
            x, y = self._point(i, outer)
            shapes.append(cv.Line(c, c, x, y, paint=grid))
            lx, ly = self._point(i, outer + 13)
            shapes.append(cv.Text(lx, ly, label, style=ft.TextStyle(size=10, weight=ft.FontWeight.W_600, color=STAT_COLORS[key]), alignment=ft.Alignment.CENTER))
        if stats is not None:
            pts = [self._point(i, outer * min(1.0, getattr(stats, key) / _MAX)) for i, (key, _l) in enumerate(_AXES)]
            fill = ft.Paint(color=alpha(self._colour, 0.35), style=ft.PaintingStyle.FILL)
            stroke = ft.Paint(color=self._colour, style=ft.PaintingStyle.STROKE, stroke_width=2)
            path = [cv.Path.MoveTo(*pts[0]), *[cv.Path.LineTo(x, y) for x, y in pts[1:]], cv.Path.Close()]
            shapes.append(cv.Path(list(path), paint=fill))
            shapes.append(cv.Path(list(path), paint=stroke))
            for (x, y), (key, _l) in zip(pts, _AXES):
                shapes.append(cv.Circle(x, y, 3, paint=ft.Paint(color=STAT_COLORS[key], style=ft.PaintingStyle.FILL)))
        self._canvas.shapes = shapes
        try:
            if self._canvas.page is not None:
                self._canvas.update()
        except RuntimeError:
            pass

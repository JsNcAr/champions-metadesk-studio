"""Field strip: one-click tiles for game type, weather, terrain and the field (Trick Room,
Gravity, rooms), each side's conditions (Tailwind, screens, Helping Hand, hazards…), and Clear.

Always expanded but dense: every group's label sits beside its tiles, tiles are only as wide
as their label, and the two sides' conditions share one row as two columns of small tiles.
"""

from __future__ import annotations

from collections.abc import Callable

import flet as ft

from ...theme import TERRAIN_COLORS, WEATHER_COLORS, Palette, Radius, Space, alpha
from .state import DOUBLES_ONLY, SIDE_CONDITION_LABELS, TERRAINS, WEATHERS
from .store import CalcStore

WEATHER_COLOURS = WEATHER_COLORS
TERRAIN_COLOURS = TERRAIN_COLORS

CLEAR_TOOLTIP = "Reset weather, terrain, rooms, speed control, side conditions, stat stages, statuses and activated abilities"


class Tile(ft.Container):
    def __init__(self, label: str, colour: str, on_click: Callable[[], None], *, tooltip: str | None = None, small: bool = True) -> None:
        super().__init__()
        self._colour = colour
        self._label = ft.Text(label, theme_style=ft.TextThemeStyle.LABEL_SMALL if small else ft.TextThemeStyle.LABEL_MEDIUM,
                              color=Palette.ON_SURFACE_VARIANT, text_align=ft.TextAlign.CENTER, max_lines=1)
        self.label = self._label
        self.content = self._label
        self.padding = ft.Padding.symmetric(horizontal=Space.SM, vertical=Space.XS) if small else ft.Padding.symmetric(horizontal=Space.SM + 2, vertical=Space.XS + 2)
        self.border_radius = Radius.SM
        self.ink = True
        self.tooltip = tooltip
        self.on_click = lambda _e: on_click()
        self.set_active(False)

    def set_active(self, active: bool) -> None:
        self.active = active
        self.bgcolor = alpha(self._colour, 0.35) if active else Palette.SURFACE_3
        self.border = ft.Border.all(1, self._colour if active else Palette.OUTLINE_VARIANT)
        self._label.color = Palette.ON_SURFACE if active else Palette.ON_SURFACE_VARIANT
        self._label.weight = ft.FontWeight.W_700 if active else ft.FontWeight.W_500


def _label(text: str, width: int | None = None) -> ft.Text:
    return ft.Text(text.upper(), theme_style=ft.TextThemeStyle.LABEL_SMALL, color=Palette.ON_SURFACE_VARIANT, width=width)


def _group(title: str, tiles: list[ft.Control]) -> ft.Row:
    """``TITLE [tile][tile]…`` kept together on one line; groups wrap as whole units."""
    return ft.Row(spacing=Space.XS, tight=True, vertical_alignment=ft.CrossAxisAlignment.CENTER, controls=[_label(title), *tiles])


class FieldStrip(ft.Container):
    def __init__(self, *, store: CalcStore, on_clear: Callable[[], None]) -> None:
        super().__init__()
        self.store = store
        self._syncing = False
        s = store
        self.tiles: dict[str, Tile] = {
            "singles": Tile("Singles", Palette.SECONDARY, lambda: s.set_field(game_type="singles")),
            "doubles": Tile("Doubles", Palette.SECONDARY, lambda: s.set_field(game_type="doubles")),
            "tailwind_left": Tile("Tailwind", Palette.SUCCESS, lambda: s.toggle_side("left", "tailwind"), tooltip="Doubles your side's Speed"),
            "trick_room": Tile("Trick Room", Palette.TERTIARY, lambda: s.toggle_field("trick_room"), tooltip="Reverses the speed order shown; the formula itself only cares about it for Payback and Analytic"),
            "tailwind_right": Tile("Tailwind", Palette.SUCCESS, lambda: s.toggle_side("right", "tailwind"), tooltip="Doubles their side's Speed"),
            "gravity": Tile("Gravity", Palette.TERTIARY, lambda: s.toggle_field("gravity")),
            "magic_room": Tile("Magic Room", Palette.TERTIARY, lambda: s.toggle_field("magic_room")),
            "wonder_room": Tile("Wonder Room", Palette.TERTIARY, lambda: s.toggle_field("wonder_room")),
        }
        for key, label in WEATHERS:
            self.tiles[f"weather:{key}"] = Tile(label, WEATHER_COLOURS[key], lambda key=key: s.toggle_field("weather", key))
        for key, label in TERRAINS:
            self.tiles[f"terrain:{key}"] = Tile(label.replace(" Terrain", ""), TERRAIN_COLOURS[key], lambda key=key: s.toggle_field("terrain", key), tooltip=label)

        self.side_chips: dict[tuple[str, str], Tile] = {}
        columns: list[ft.Control] = []
        for side, title in (("left", "Your side"), ("right", "Their side")):
            chips: list[ft.Control] = [self.tiles[f"tailwind_{side}"]]
            for key, label in SIDE_CONDITION_LABELS:
                chip = Tile(label, Palette.SECONDARY, lambda side=side, key=key: self._toggle_side(side, key))
                self.side_chips[(side, key)] = chip
                chips.append(chip)
            spikes = Tile("Spikes", Palette.SECONDARY, lambda side=side: self._cycle_spikes(side), tooltip="Click to add a layer (up to three)")
            self.side_chips[(side, "spikes")] = spikes
            chips.append(spikes)
            columns.append(ft.Column(spacing=Space.XS, tight=True, col={"xs": 12, "md": 6}, controls=[
                _label(title),
                ft.Row(spacing=Space.XS, run_spacing=Space.XS, wrap=True, controls=chips),
            ]))

        self._clear = ft.TextButton("Clear", icon=ft.Icons.CLEAR_ALL, tooltip=CLEAR_TOOLTIP, disabled=True, on_click=lambda _e: on_clear())
        self.content = ft.Column(spacing=Space.SM, tight=True, controls=[
            ft.Row(spacing=Space.SM, vertical_alignment=ft.CrossAxisAlignment.START, controls=[
                ft.Row(spacing=Space.LG, run_spacing=Space.SM, wrap=True, expand=True, controls=[
                    _group("Format", [self.tiles["singles"], self.tiles["doubles"]]),
                    _group("Weather", [self.tiles[f"weather:{k}"] for k, _l in WEATHERS]),
                    _group("Terrain", [self.tiles[f"terrain:{k}"] for k, _l in TERRAINS]),
                    _group("Field", [self.tiles["trick_room"], self.tiles["gravity"], self.tiles["magic_room"], self.tiles["wonder_room"]]),
                ]),
                self._clear,
            ]),
            ft.ResponsiveRow(spacing=Space.LG, run_spacing=Space.SM, controls=columns),
        ])
        self.bgcolor = Palette.SURFACE_2
        self.border_radius = Radius.MD
        self.border = ft.Border.all(1, Palette.OUTLINE_VARIANT)
        self.padding = Space.MD

    def _toggle_side(self, side: str, key: str) -> None:
        if not self._syncing:
            self.store.toggle_side(side, key)

    def _cycle_spikes(self, side: str) -> None:
        if self._syncing:
            return
        current = self.store.state.field.left if side == "left" else self.store.state.field.right
        self.store.set_side_conditions(side, spikes=(current.spikes + 1) % 4)

    def update_from(self) -> None:
        self._syncing = True
        try:
            f = self.store.state.field
            self.tiles["singles"].set_active(f.game_type == "singles")
            self.tiles["doubles"].set_active(f.game_type == "doubles")
            self.tiles["tailwind_left"].set_active(f.left.tailwind)
            self.tiles["tailwind_right"].set_active(f.right.tailwind)
            self.tiles["trick_room"].set_active(f.trick_room)
            self.tiles["gravity"].set_active(f.gravity)
            self.tiles["magic_room"].set_active(f.magic_room)
            self.tiles["wonder_room"].set_active(f.wonder_room)
            for key, _l in WEATHERS:
                self.tiles[f"weather:{key}"].set_active(f.weather == key)
            for key, _l in TERRAINS:
                self.tiles[f"terrain:{key}"].set_active(f.terrain == key)
            doubles = f.game_type == "doubles"
            for side in ("left", "right"):
                conditions = f.left if side == "left" else f.right
                for key, _l in SIDE_CONDITION_LABELS:
                    chip = self.side_chips[(side, key)]
                    chip.set_active(getattr(conditions, key))
                    chip.visible = doubles or key not in DOUBLES_ONLY
                spikes = self.side_chips[(side, "spikes")]
                spikes.set_active(conditions.spikes > 0)
                spikes.label.value = f"Spikes ×{conditions.spikes}" if conditions.spikes else "Spikes"
            self._clear.disabled = not self.store.has_conditions()
        finally:
            self._syncing = False
        try:
            if self.page is not None:
                self.update()
        except RuntimeError:
            pass

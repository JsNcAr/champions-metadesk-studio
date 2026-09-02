"""Field strip: one-click tiles for game type, speed control, weather, terrain and rooms, plus a
row of per-side effect chips (screens, Helping Hand, hazards, Leech Seed…)."""

from __future__ import annotations

from collections.abc import Callable

import flet as ft

from ...theme import TERRAIN_COLORS, WEATHER_COLORS, Palette, Radius, Space, alpha
from .state import SIDE_CONDITION_LABELS, TERRAINS, WEATHERS
from .store import CalcStore

WEATHER_COLOURS = WEATHER_COLORS
TERRAIN_COLOURS = TERRAIN_COLORS


class Tile(ft.Container):
    def __init__(self, label: str, colour: str, on_click: Callable[[], None], *, width: int | None = None, tooltip: str | None = None) -> None:
        super().__init__()
        self._colour = colour
        self._label = ft.Text(label, theme_style=ft.TextThemeStyle.LABEL_LARGE, color=Palette.ON_SURFACE_VARIANT, text_align=ft.TextAlign.CENTER, max_lines=1)
        self.content = self._label
        self.padding = ft.Padding.symmetric(horizontal=Space.MD, vertical=Space.SM)
        self.border_radius = Radius.SM
        self.width = width or 110
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


def _group(title: str, tiles: list[ft.Control]) -> ft.Column:
    return ft.Column(spacing=Space.XS, tight=True, controls=[
        ft.Text(title.upper(), theme_style=ft.TextThemeStyle.LABEL_SMALL, color=Palette.ON_SURFACE_VARIANT),
        ft.Row(spacing=Space.XS, tight=True, wrap=True, controls=tiles),
    ])


class FieldStrip(ft.Container):
    def __init__(self, *, store: CalcStore, on_swap: Callable[[], None]) -> None:
        super().__init__()
        self.store = store
        self._syncing = False
        s = store
        self.tiles: dict[str, Tile] = {
            "singles": Tile("Singles", Palette.SECONDARY, lambda: s.set_field(game_type="singles"), width=90),
            "doubles": Tile("Doubles", Palette.SECONDARY, lambda: s.set_field(game_type="doubles"), width=90),
            "tailwind_left": Tile("Your Tailwind", Palette.SUCCESS, lambda: s.toggle_side("left", "tailwind"), width=122, tooltip="Attacker's side"),
            "trick_room": Tile("Trick Room", Palette.TERTIARY, lambda: s.toggle_field("trick_room"), width=104, tooltip="Reverses the speed order shown; the formula itself only cares about it for Payback and Analytic"),
            "tailwind_right": Tile("Their Tailwind", Palette.SUCCESS, lambda: s.toggle_side("right", "tailwind"), width=122, tooltip="Defender's side"),
            "gravity": Tile("Gravity", Palette.TERTIARY, lambda: s.toggle_field("gravity"), width=90),
            "magic_room": Tile("Magic Room", Palette.TERTIARY, lambda: s.toggle_field("magic_room"), width=116),
            "wonder_room": Tile("Wonder Room", Palette.TERTIARY, lambda: s.toggle_field("wonder_room"), width=124),
        }
        for key, label in WEATHERS:
            self.tiles[f"weather:{key}"] = Tile(label, WEATHER_COLOURS[key], lambda key=key: s.toggle_field("weather", key), width=84)
        for key, label in TERRAINS:
            self.tiles[f"terrain:{key}"] = Tile(label.replace(" Terrain", ""), TERRAIN_COLOURS[key], lambda key=key: s.toggle_field("terrain", key), width=84)

        swap = ft.IconButton(icon=ft.Icons.SWAP_HORIZ, icon_size=18, tooltip="Swap attacker and defender (Ctrl+Shift+S)", on_click=lambda _e: on_swap())
        self.side_chips: dict[tuple[str, str], ft.Chip] = {}
        rows: list[ft.Control] = []
        for side, title in (("left", "Attacker side"), ("right", "Defender side")):
            chips: list[ft.Control] = [ft.Text(title, theme_style=ft.TextThemeStyle.LABEL_SMALL, color=Palette.ON_SURFACE_VARIANT, width=96)]
            if side == "left":
                chips.append(swap)
            for key, label in SIDE_CONDITION_LABELS:
                chip = ft.Chip(label=ft.Text(label), selected=False, show_checkmark=False, on_select=lambda _e, side=side, key=key: self._toggle_side(side, key))
                self.side_chips[(side, key)] = chip
                chips.append(chip)
            spikes = ft.Chip(label=ft.Text("Spikes"), selected=False, show_checkmark=False, tooltip="Click to add a layer (up to three)", on_select=lambda _e, side=side: self._cycle_spikes(side))
            self.side_chips[(side, "spikes")] = spikes
            chips.append(spikes)
            rows.append(ft.Row(spacing=Space.XS, wrap=True, vertical_alignment=ft.CrossAxisAlignment.CENTER, controls=chips))

        self.content = ft.Column(spacing=Space.SM, tight=True, controls=[
            ft.Row(spacing=Space.LG, wrap=True, vertical_alignment=ft.CrossAxisAlignment.START, controls=[
                _group("Battle", [self.tiles["singles"], self.tiles["doubles"]]),
                _group("Speed", [self.tiles["tailwind_left"], self.tiles["trick_room"], self.tiles["tailwind_right"]]),
                _group("Weather", [self.tiles[f"weather:{k}"] for k, _l in WEATHERS]),
                _group("Terrain", [self.tiles[f"terrain:{k}"] for k, _l in TERRAINS]),
                _group("Rooms", [self.tiles["gravity"], self.tiles["magic_room"], self.tiles["wonder_room"]]),
            ]),
            *rows,
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
            for side in ("left", "right"):
                conditions = f.left if side == "left" else f.right
                for key, _l in SIDE_CONDITION_LABELS:
                    self.side_chips[(side, key)].selected = getattr(conditions, key)
                spikes = self.side_chips[(side, "spikes")]
                spikes.selected = conditions.spikes > 0
                spikes.label = ft.Text(f"Spikes ×{conditions.spikes}" if conditions.spikes else "Spikes")
        finally:
            self._syncing = False
        try:
            if self.page is not None:
                self.update()
        except RuntimeError:
            pass

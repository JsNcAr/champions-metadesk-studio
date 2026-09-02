"""Field panel: game type, weather, terrain, rooms and per-side conditions."""

from __future__ import annotations

from collections.abc import Callable

import flet as ft

from ...components.section import SectionHeader
from ...theme import IconSize, Palette, Radius, Space
from .state import SIDE_CONDITION_LABELS, TERRAINS, WEATHERS
from .store import CalcStore


class FieldPanel(ft.Container):
    def __init__(self, *, store: CalcStore, accent: str, on_swap: Callable[[], None]) -> None:
        super().__init__()
        self.store = store
        self._syncing = False

        self._game_type = ft.SegmentedButton(
            selected=["doubles"], show_selected_icon=False,
            segments=[ft.Segment(value="doubles", label=ft.Text("Doubles")), ft.Segment(value="singles", label=ft.Text("Singles"))],
            on_change=lambda e: self._game_type_changed(e.control.selected),
        )
        self._weather = ft.Dropdown(label="Weather", dense=True, expand=True, value="none", options=[ft.DropdownOption(key=k, text=t) for k, t in WEATHERS],
                                    on_select=lambda e: self._field("weather", e.control.value or "none"))
        self._terrain = ft.Dropdown(label="Terrain", dense=True, expand=True, value="none", options=[ft.DropdownOption(key=k, text=t) for k, t in TERRAINS],
                                    on_select=lambda e: self._field("terrain", e.control.value or "none"))
        self._gravity = ft.Switch(label="Gravity", value=False, on_change=lambda e: self._field("gravity", bool(e.control.value)))
        self._magic_room = ft.Switch(label="Magic Room", value=False, on_change=lambda e: self._field("magic_room", bool(e.control.value)))
        self._wonder_room = ft.Switch(label="Wonder Room", value=False, on_change=lambda e: self._field("wonder_room", bool(e.control.value)))

        self._checks: dict[tuple[str, str], ft.Checkbox] = {}
        self._spikes: dict[str, ft.Dropdown] = {}
        columns: list[ft.Control] = []
        for side, title in (("left", "Attacker side"), ("right", "Defender side")):
            items: list[ft.Control] = [ft.Text(title, theme_style=ft.TextThemeStyle.LABEL_MEDIUM, color=Palette.ON_SURFACE)]
            for key, label in SIDE_CONDITION_LABELS:
                cb = ft.Checkbox(label=label, value=False, on_change=lambda e, side=side, key=key: self._side(side, key, bool(e.control.value)))
                self._checks[(side, key)] = cb
                items.append(cb)
            spikes = ft.Dropdown(label="Spikes", dense=True, width=110, value="0", options=[ft.DropdownOption(key=str(n), text=f"{n} layer{'s' if n != 1 else ''}" if n else "None") for n in range(4)],
                                 on_select=lambda e, side=side: self._side(side, "spikes", int(e.control.value or 0)))
            self._spikes[side] = spikes
            items.append(spikes)
            columns.append(ft.Column(spacing=0, tight=True, expand=True, controls=items))

        swap = ft.IconButton(icon=ft.Icons.SWAP_HORIZ, icon_size=IconSize.MD, tooltip="Swap attacker and defender (Ctrl+Shift+S)", on_click=lambda _e: on_swap())
        self.content = ft.Column(spacing=Space.SM, tight=True, controls=[
            SectionHeader("Field", accent=accent, action=swap),
            self._game_type,
            self._weather,
            self._terrain,
            ft.Column(spacing=0, tight=True, controls=[self._gravity, self._magic_room, self._wonder_room]),
            ft.Row(spacing=Space.SM, vertical_alignment=ft.CrossAxisAlignment.START, controls=columns),
        ])
        self.bgcolor = Palette.SURFACE_2
        self.border_radius = Radius.MD
        self.border = ft.Border.all(1, Palette.OUTLINE_VARIANT)
        self.padding = Space.MD

    def _game_type_changed(self, selected) -> None:
        if self._syncing:
            return
        value = next(iter(selected), "doubles") if selected else "doubles"
        self.store.set_field(game_type=value)

    def _field(self, key: str, value) -> None:
        if self._syncing:
            return
        self.store.set_field(**{key: value})

    def _side(self, side: str, key: str, value) -> None:
        if self._syncing:
            return
        self.store.set_side_conditions(side, **{key: value})

    def update_from(self) -> None:
        self._syncing = True
        try:
            f = self.store.state.field
            self._game_type.selected = [f.game_type]
            self._weather.value = f.weather
            self._terrain.value = f.terrain
            self._gravity.value = f.gravity
            self._magic_room.value = f.magic_room
            self._wonder_room.value = f.wonder_room
            for side in ("left", "right"):
                conditions = f.left if side == "left" else f.right
                for key, _label in SIDE_CONDITION_LABELS:
                    self._checks[(side, key)].value = getattr(conditions, key)
                self._spikes[side].value = str(conditions.spikes)
        finally:
            self._syncing = False
        try:
            if self.page is not None:
                self.update()
        except RuntimeError:
            pass

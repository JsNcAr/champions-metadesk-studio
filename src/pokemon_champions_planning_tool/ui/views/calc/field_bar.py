"""The field in one line, and each side's conditions under its own Pokémon.

``FieldBar``: Singles / Doubles, then Weather, Terrain and Field (Trick Room, Gravity, the
rooms) as small menus whose label is what is set, and Clear. ``SideConditionsRow``: the
conditions on one side (Tailwind, screens, Helping Hand, hazards…) as removable chips, and
"+" for the rest. Only what is active takes room.
"""

from __future__ import annotations

from collections.abc import Callable

import flet as ft

from ...theme import TERRAIN_COLORS, WEATHER_COLORS, Palette, Radius, Space, alpha
from ...tasks import safe_update
from .state import DOUBLES_ONLY, SIDE_CONDITION_LABELS, TERRAINS, WEATHERS
from .store import ABILITY_FIELD_EFFECTS, CalcStore

CLEAR_TOOLTIP = "Reset weather, terrain, rooms, speed control, side conditions, stat stages, statuses and activated abilities"
WEATHER_ICONS = {"Sun": ft.Icons.WB_SUNNY_OUTLINED, "Rain": ft.Icons.WATER_DROP_OUTLINED, "Sand": ft.Icons.GRAIN, "Snow": ft.Icons.AC_UNIT}
ROOMS: tuple[tuple[str, str, str], ...] = (
    ("trick_room", "Trick Room", "Reverses the speed order shown; the formula itself only cares about it for Payback and Analytic"),
    ("gravity", "Gravity", "Grounds everything: Ground moves hit Flying types and Levitate"),
    ("magic_room", "Magic Room", "Held items have no effect"),
    ("wonder_room", "Wonder Room", "Defense and Special Defense swap"),
)
SIDE_TIPS = {
    "tailwind": "Doubles this side's Speed",
    "reflect": "Halves physical damage to this side (×0.67 in Doubles)",
    "light_screen": "Halves special damage to this side (×0.67 in Doubles)",
    "aurora_veil": "Reflect and Light Screen together",
    "helping_hand": "An ally boosts this side's next move ×1.5",
    "friend_guard": "An ally with Friend Guard: ×0.75 damage taken",
    "protect": "This side is protected this turn",
    "stealth_rock": "Stealth Rock on this side: damage on switching in",
    "leech_seed": "This side is seeded",
    "charge": "Charged: the next Electric move is doubled",
    "power_trick": "Attack and Defense swapped",
}


def pill(label: str, icon: str | None, colour: str | None, *, placeholder: bool) -> ft.Container:
    """A menu trigger: muted with the group's name when nothing is set, tinted when set."""
    fg = Palette.ON_SURFACE if not placeholder else Palette.ON_SURFACE_VARIANT
    controls: list[ft.Control] = []
    if icon:
        controls.append(ft.Icon(icon, size=16, color=colour if (colour and not placeholder) else fg))
    controls += [ft.Text(label, theme_style=ft.TextThemeStyle.LABEL_LARGE, color=fg, weight=ft.FontWeight.W_500 if placeholder else ft.FontWeight.W_700,
                         max_lines=1), ft.Icon(ft.Icons.ARROW_DROP_DOWN, size=16, color=Palette.ON_SURFACE_VARIANT)]
    return ft.Container(
        content=ft.Row(spacing=Space.XS, tight=True, vertical_alignment=ft.CrossAxisAlignment.CENTER, controls=controls),
        height=32, padding=ft.Padding.only(left=Space.SM, right=Space.XS), border_radius=Radius.PILL,
        bgcolor=alpha(colour, 0.22) if (colour and not placeholder) else Palette.SURFACE_3,
        border=ft.Border.all(1, colour if (colour and not placeholder) else Palette.OUTLINE_VARIANT),
    )


def _item(label: str, on_click: Callable[[], None], *, checked: bool = False, icon: str | None = None) -> ft.PopupMenuItem:
    return ft.PopupMenuItem(content=ft.Text(label, weight=ft.FontWeight.W_700 if checked else None), icon=ft.Icons.CHECK if checked else icon,
                            on_click=lambda _e: on_click())


class FieldBar(ft.Container):
    def __init__(self, *, store: CalcStore, on_clear: Callable[[], None]) -> None:
        super().__init__()
        self.store = store
        self._format = ft.SegmentedButton(
            segments=[ft.Segment(value="singles", label=ft.Text("Singles")), ft.Segment(value="doubles", label=ft.Text("Doubles"))],
            selected=["doubles"], show_selected_icon=False, allow_empty_selection=False,
            style=ft.ButtonStyle(visual_density=ft.VisualDensity.COMPACT),
            on_change=lambda e: self.pick("game_type", (e.control.selected or ["doubles"])[0]),
        )
        self.weather = ft.PopupMenuButton(tooltip="Weather", items=[])
        self.terrain = ft.PopupMenuButton(tooltip="Terrain", items=[])
        self.rooms = ft.PopupMenuButton(tooltip="Trick Room, Gravity, Magic Room, Wonder Room", items=[])
        self._clear = ft.TextButton("Clear", icon=ft.Icons.CLEAR_ALL, tooltip=CLEAR_TOOLTIP, disabled=True, on_click=lambda _e: on_clear())
        self._drawn: tuple | None = None
        self.content = ft.Row(spacing=Space.SM, vertical_alignment=ft.CrossAxisAlignment.CENTER, controls=[
            ft.Row(spacing=Space.SM, run_spacing=Space.XS, wrap=True, expand=True, vertical_alignment=ft.CrossAxisAlignment.CENTER, controls=[
                ft.Text("FIELD", theme_style=ft.TextThemeStyle.LABEL_SMALL, color=Palette.ON_SURFACE_VARIANT),
                self._format, self.weather, self.terrain, self.rooms,
            ]),
            self._clear,
        ])
        self.bgcolor = Palette.SURFACE_2
        self.border_radius = Radius.MD
        self.border = ft.Border.all(1, Palette.OUTLINE_VARIANT)
        self.padding = ft.Padding.symmetric(horizontal=Space.MD, vertical=Space.XS)
        self.update_from()

    # -- edits ---------------------------------------------------------------------------------

    def pick(self, key: str, value) -> None:
        """Set a field value: ``("weather", "Sun")``, ``("weather", "none")``, ``("trick_room", None)`` toggles."""
        if key == "game_type":
            if value != self.store.state.field.game_type:
                self.store.set_field(game_type=value)
        elif key in ("weather", "terrain"):
            self.store.set_field(**{key: value})
        else:
            self.store.toggle_field(key)

    # -- rendering -----------------------------------------------------------------------------

    def _set_by(self, key: str, value: str) -> str | None:
        """"Tyranitar's Sand Stream" when an ability on the field sets this weather or terrain."""
        for side in ("left", "right"):
            p = self.store.state.side(side)
            if p.ability and ABILITY_FIELD_EFFECTS.get(p.ability, {}).get(key) == value:
                species = self.store.species(side)
                return f"{species.name if species else 'A Pokémon'}'s {p.ability}"
        return None

    def update_from(self) -> None:
        # Every edit (a slider tick included) sends "state"; redraw only what this bar reads:
        # the field, the abilities that name a weather or terrain, and whether Clear applies.
        state = self.store.state
        f = state.field
        drawn = (f, state.left.ability, state.left.species, state.right.ability, state.right.species, self.store.has_conditions())
        if drawn == self._drawn:
            return
        self._drawn = drawn
        self._format.selected = [f.game_type]
        weather = f.weather if f.weather != "none" else None
        terrain = f.terrain if f.terrain != "none" else None
        self.weather.content = pill(weather or "Weather", WEATHER_ICONS.get(weather or "", ft.Icons.CLOUD_OUTLINED), WEATHER_COLORS.get(weather or ""), placeholder=weather is None)
        self.weather.items = [_item(label, lambda k=key: self.pick("weather", k), checked=f.weather == key, icon=WEATHER_ICONS[key]) for key, label in WEATHERS]
        self.weather.items += [ft.PopupMenuItem(), _item("No weather", lambda: self.pick("weather", "none"), checked=weather is None)]
        by = self._set_by("weather", weather) if weather else None
        self.weather.tooltip = f"Weather · set by {by}" if by else "Weather"
        terrain_label = dict(TERRAINS).get(terrain or "", "")
        self.terrain.content = pill(terrain_label.replace(" Terrain", "") if terrain else "Terrain", ft.Icons.LANDSCAPE_OUTLINED, TERRAIN_COLORS.get(terrain or ""), placeholder=terrain is None)
        self.terrain.items = [_item(label, lambda k=key: self.pick("terrain", k), checked=f.terrain == key) for key, label in TERRAINS]
        self.terrain.items += [ft.PopupMenuItem(), _item("No terrain", lambda: self.pick("terrain", "none"), checked=terrain is None)]
        by = self._set_by("terrain", terrain) if terrain else None
        self.terrain.tooltip = f"Terrain · set by {by}" if by else "Terrain"
        on = [label for key, label, _t in ROOMS if getattr(f, key)]
        self.rooms.content = pill(" · ".join(on) if on else "Rooms", ft.Icons.MEETING_ROOM_OUTLINED, Palette.TERTIARY if on else None, placeholder=not on)
        self.rooms.items = [ft.PopupMenuItem(content=ft.Text(label, weight=ft.FontWeight.W_700 if getattr(f, key) else None, tooltip=tip),
                                             icon=ft.Icons.CHECK_BOX if getattr(f, key) else ft.Icons.CHECK_BOX_OUTLINE_BLANK,
                                             on_click=lambda _e, k=key: self.pick(k, None))
                            for key, label, tip in ROOMS]
        self._clear.disabled = not self.store.has_conditions()
        safe_update(self)


# Set nearly every turn in Doubles, so they are one click away instead of in the "+" menu.
QUICK: tuple[tuple[str, str, str], ...] = (("tailwind", "Tailwind", ft.Icons.AIR), ("helping_hand", "Helping Hand", ft.Icons.BACK_HAND_OUTLINED))


class SideConditionsRow(ft.Row):
    """One side's conditions: Tailwind and Helping Hand as one-click toggles, the other active
    ones as chips (✕ removes), and "+" for the rest."""

    def __init__(self, side: str, *, store: CalcStore) -> None:
        super().__init__(spacing=Space.XS, run_spacing=Space.XS, wrap=True, vertical_alignment=ft.CrossAxisAlignment.CENTER)
        self.side = side
        self.store = store
        self._title = ft.Text("YOUR SIDE" if side == "left" else "THEIR SIDE", theme_style=ft.TextThemeStyle.LABEL_SMALL, color=Palette.ON_SURFACE_VARIANT)
        self.add = ft.PopupMenuButton(
            content=ft.Container(
                content=ft.Row(spacing=2, tight=True, controls=[ft.Icon(ft.Icons.ADD, size=14, color=Palette.PRIMARY),
                                                                ft.Text("Condition", theme_style=ft.TextThemeStyle.LABEL_MEDIUM, color=Palette.PRIMARY)]),
                height=28, padding=ft.Padding.symmetric(horizontal=Space.SM), border_radius=Radius.PILL, border=ft.Border.all(1, Palette.OUTLINE_VARIANT),
            ),
            tooltip="Screens, Protect, hazards, Leech Seed, Charge…", items=[],
        )
        self.chips: dict[str, ft.Chip] = {}      # the other active conditions
        self.quick: dict[str, ft.Chip] = {}      # the always-there toggles
        for key, label, icon in QUICK:
            self.quick[key] = ft.Chip(
                label=ft.Text(label, theme_style=ft.TextThemeStyle.LABEL_MEDIUM), leading=ft.Icon(icon, size=14), show_checkmark=False,
                selected_color=alpha(Palette.SUCCESS if key == "tailwind" else Palette.SECONDARY, 0.3), visual_density=ft.VisualDensity.COMPACT,
                tooltip=SIDE_TIPS[key], on_select=lambda _e, key=key: self.toggle(key),
            )
        self._drawn: tuple | None = None
        self.update_from()

    def _conditions(self):
        f = self.store.state.field
        return f.left if self.side == "left" else f.right

    def _labels(self) -> list[tuple[str, str]]:
        doubles = self.store.state.field.game_type == "doubles"
        return [("tailwind", "Tailwind"), *((k, label) for k, label in SIDE_CONDITION_LABELS if doubles or k not in DOUBLES_ONLY)]

    def toggle(self, key: str) -> None:
        self.store.toggle_side(self.side, key)

    def add_spikes(self) -> None:
        self.store.set_side_conditions(self.side, spikes=min(3, self._conditions().spikes + 1))

    def update_from(self) -> bool:
        c = self._conditions()
        labels = self._labels()
        active = tuple(k for k, _l in labels if getattr(c, k))
        key = (active, c.spikes, tuple(k for k, _l in labels))
        if key == self._drawn:
            return False
        self._drawn = key
        self.chips = {}
        quick: list[ft.Control] = []
        for k, _label, _icon in QUICK:
            chip = self.quick[k]
            on = bool(getattr(c, k))
            chip.selected = on
            chip.label.color = Palette.ON_SURFACE if on else Palette.ON_SURFACE_VARIANT
            chip.label.weight = ft.FontWeight.W_700 if on else ft.FontWeight.W_500
            chip.leading.color = (Palette.SUCCESS if k == "tailwind" else Palette.SECONDARY) if on else Palette.ON_SURFACE_VARIANT
            if any(k == key for key, _l in labels):     # Helping Hand only in Doubles
                quick.append(chip)
        chips: list[ft.Control] = []
        for k, label in labels:
            if k in self.quick:
                continue
            if getattr(c, k):
                chip = ft.Chip(label=ft.Text(label, theme_style=ft.TextThemeStyle.LABEL_MEDIUM, color=Palette.ON_SURFACE, weight=ft.FontWeight.W_600),
                               bgcolor=alpha(Palette.SUCCESS if k == "tailwind" else Palette.SECONDARY, 0.25), tooltip=SIDE_TIPS.get(k),
                               visual_density=ft.VisualDensity.COMPACT, delete_icon_tooltip="Remove", on_delete=lambda _e, k=k: self.toggle(k))
                self.chips[k] = chip
                chips.append(chip)
        if c.spikes:
            chip = ft.Chip(label=ft.Text(f"Spikes ×{c.spikes}", theme_style=ft.TextThemeStyle.LABEL_MEDIUM, color=Palette.ON_SURFACE, weight=ft.FontWeight.W_600),
                           bgcolor=alpha(Palette.SECONDARY, 0.25), visual_density=ft.VisualDensity.COMPACT, tooltip="Click to add a layer (up to three)",
                           on_click=lambda _e: self.add_spikes(), delete_icon_tooltip="Remove", on_delete=lambda _e: self.store.set_side_conditions(self.side, spikes=0))
            self.chips["spikes"] = chip
            chips.append(chip)
        items = [ft.PopupMenuItem(content=ft.Text(label, tooltip=SIDE_TIPS.get(k)), on_click=lambda _e, k=k: self.toggle(k))
                 for k, label in labels if not getattr(c, k) and k not in self.quick]
        if c.spikes < 3:
            items.append(ft.PopupMenuItem(content=ft.Text("Spikes (add a layer)" if c.spikes else "Spikes"), on_click=lambda _e: self.add_spikes()))
        self.add.items = items
        self.add.visible = bool(items)
        self.controls = [self._title, *quick, *chips, self.add]
        return True


__all__ = ["FieldBar", "QUICK", "ROOMS", "SideConditionsRow", "pill"]

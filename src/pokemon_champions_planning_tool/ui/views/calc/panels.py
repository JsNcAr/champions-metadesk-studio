"""Attacker / defender panels: species, spread, boosts, ability, item, HP, status, moves."""

from __future__ import annotations

from collections.abc import Callable

import flet as ft

from ....domain.pokemon_identity import get_pokemon_sprite_url
from ....domain.stat_calc import format_points
from ...components import Sprite, StatusChip
from ...components.inputs import SEARCH_FIELD_STYLE
from ...components.pokemon import TypeChip
from ...components.section import SectionHeader
from ...components.spread_editor import SpreadEditor
from ...theme import STAT_COLORS, STAT_LABELS, IconSize, Palette, Radius, Space
from ..team.slot_card import MoveButton
from .state import BOOST_STATS, STATUSES
from .store import CalcStore

_MOVE_ROWS = 4


class _Move:
    """Shape ``MoveButton.update_from`` expects (name + catalogue info + legality)."""

    def __init__(self, name: str | None, info, legal: bool | None) -> None:
        self.name = name
        self.info = info
        self.legal = legal


class PokemonPanel(ft.Container):
    def __init__(
        self,
        side: str,
        *,
        title: str,
        accent: str,
        store: CalcStore,
        on_pick_move: Callable[[str, int], None],
        on_pick_item: Callable[[str], None],
    ) -> None:
        super().__init__()
        self.side = side
        self.store = store
        self._on_pick_move = on_pick_move
        self._on_pick_item = on_pick_item
        self._syncing = False

        self.search = ft.TextField(hint_text="Species…", prefix_icon=ft.Icons.SEARCH, dense=True, expand=True, **SEARCH_FIELD_STYLE,
                                   on_change=lambda e: self._suggest(e.control.value or ""), on_submit=lambda e: self._submit(e.control.value or ""))
        self._suggestions = ft.Row(spacing=Space.XS, wrap=True, visible=False)
        self.sprite = Sprite(size=56)
        self._name = ft.Text("Pick a species", theme_style=ft.TextThemeStyle.TITLE_MEDIUM, color=Palette.ON_SURFACE, max_lines=1, overflow=ft.TextOverflow.ELLIPSIS)
        self._types = ft.Row(spacing=Space.XS, tight=True)
        self._caption = ft.Text("", theme_style=ft.TextThemeStyle.BODY_SMALL, color=Palette.ON_SURFACE_VARIANT, max_lines=2, overflow=ft.TextOverflow.ELLIPSIS)
        self._legality = StatusChip("Not in Champions", "warning", icon=ft.Icons.WARNING_AMBER_ROUNDED)
        self._legality.visible = False

        self.editor = SpreadEditor(base_stats=_ZERO, nature="hardy", points={}, on_change=self._spread_changed, compact=True)

        self._boosts: dict[str, ft.Dropdown] = {}
        boost_controls: list[ft.Control] = []
        for stat in BOOST_STATS:
            dd = ft.Dropdown(width=84, dense=True, text_size=13, value="0", options=[ft.DropdownOption(key=str(v), text=f"{v:+d}" if v else "0") for v in range(6, -7, -1)],
                             on_select=lambda e, stat=stat: self._boost_changed(stat, e.control.value))
            self._boosts[stat] = dd
            boost_controls.append(ft.Column(spacing=2, tight=True, horizontal_alignment=ft.CrossAxisAlignment.CENTER,
                                            controls=[ft.Text(STAT_LABELS[stat], theme_style=ft.TextThemeStyle.LABEL_SMALL, color=STAT_COLORS[stat]), dd]))

        self._ability = ft.Dropdown(label="Ability", dense=True, expand=True, enable_filter=True, options=[], on_select=lambda e: self._ability_changed(e.control.value))
        self._ability_on = ft.Switch(label="Active", value=False, tooltip="Ability already triggered: Intimidate applied, Flash Fire lit, Electromorphosis charged, Unburden…",
                                     on_change=lambda e: self.store.set_pokemon(self.side, ability_on=bool(e.control.value)))

        self._item_name = ft.Text("Held item…", theme_style=ft.TextThemeStyle.BODY_MEDIUM, color=Palette.ON_SURFACE_VARIANT, expand=True, max_lines=1, overflow=ft.TextOverflow.ELLIPSIS)
        self._item_clear = ft.IconButton(icon=ft.Icons.CLOSE, icon_size=16, width=28, height=28, padding=0, tooltip="Remove item", visible=False,
                                         on_click=lambda _e: self.store.set_pokemon(self.side, item=None))
        self._item_field = ft.Container(
            content=ft.Row(spacing=Space.SM, vertical_alignment=ft.CrossAxisAlignment.CENTER, controls=[
                ft.Icon(ft.Icons.DIAMOND_OUTLINED, size=IconSize.SM, color=Palette.ON_SURFACE_VARIANT), self._item_name, self._item_clear,
                ft.Icon(ft.Icons.CHEVRON_RIGHT, size=IconSize.SM, color=Palette.ON_SURFACE_VARIANT),
            ]),
            height=36, padding=ft.Padding.symmetric(horizontal=Space.MD), border_radius=Radius.SM, bgcolor=Palette.SURFACE_3, border=ft.Border.all(1, Palette.OUTLINE),
            ink=True, on_click=lambda _e: self._on_pick_item(self.side), tooltip="Choose held item",
        )

        self._hp_slider = ft.Slider(min=0, max=100, divisions=100, value=100, expand=True, active_color=STAT_COLORS["hp"],
                                    on_change_end=lambda e: self.store.set_hp_pct(self.side, float(e.control.value)))
        self._hp_abs = ft.TextField(value="", width=64, dense=True, text_align=ft.TextAlign.CENTER, keyboard_type=ft.KeyboardType.NUMBER, on_submit=lambda e: self._hp_typed(e.control.value or ""))
        self._hp_label = ft.Text("", theme_style=ft.TextThemeStyle.LABEL_MEDIUM, color=Palette.ON_SURFACE, width=90, text_align=ft.TextAlign.RIGHT)

        self._status = ft.Dropdown(label="Status", dense=True, width=170, value="none", options=[ft.DropdownOption(key=k, text=t) for k, t in STATUSES],
                                   on_select=lambda e: self.store.set_pokemon(self.side, status=e.control.value or "none"))
        self._allies = ft.Dropdown(label="Allies fainted", dense=True, width=140, value="0", tooltip="Supreme Overlord", options=[ft.DropdownOption(key=str(n), text=str(n)) for n in range(6)],
                                   on_select=lambda e: self.store.set_pokemon(self.side, allies_fainted=int(e.control.value or 0)))

        self._moves: list[MoveButton] = []
        self._crits: list[ft.IconButton] = []
        move_rows: list[ft.Control] = []
        for index in range(_MOVE_ROWS):
            button = MoveButton(index=index, on_click=lambda index=index: self._on_pick_move(self.side, index))
            crit = ft.IconButton(icon=ft.Icons.FLASH_ON_OUTLINED, selected_icon=ft.Icons.FLASH_ON, icon_size=IconSize.SM, selected=False, tooltip="Critical hit",
                                 icon_color=Palette.ON_SURFACE_VARIANT, selected_icon_color=Palette.PRIMARY, on_click=lambda _e, index=index: self.store.toggle_crit(self.side, index))
            self._moves.append(button)
            self._crits.append(crit)
            move_rows.append(ft.Row(spacing=Space.XS, vertical_alignment=ft.CrossAxisAlignment.CENTER, controls=[button, crit]))

        self.content = ft.Column(spacing=Space.SM, tight=True, controls=[
            SectionHeader(title, accent=accent),
            self.search,
            self._suggestions,
            ft.Row(spacing=Space.MD, vertical_alignment=ft.CrossAxisAlignment.CENTER, controls=[
                self.sprite,
                ft.Column(spacing=2, tight=True, expand=True, controls=[self._name, self._types, self._caption, self._legality]),
            ]),
            self.editor,
            ft.Text("Stat stages", theme_style=ft.TextThemeStyle.LABEL_SMALL, color=Palette.ON_SURFACE_VARIANT),
            ft.Row(spacing=Space.XS, alignment=ft.MainAxisAlignment.SPACE_BETWEEN, controls=boost_controls),
            ft.Row(spacing=Space.SM, vertical_alignment=ft.CrossAxisAlignment.CENTER, controls=[self._ability, self._ability_on]),
            self._item_field,
            ft.Row(spacing=Space.SM, vertical_alignment=ft.CrossAxisAlignment.CENTER, controls=[
                ft.Text("HP", theme_style=ft.TextThemeStyle.LABEL_MEDIUM, color=STAT_COLORS["hp"], width=24), self._hp_slider, self._hp_abs, self._hp_label,
            ]),
            ft.Row(spacing=Space.SM, controls=[self._status, self._allies]),
            ft.Text("Moves", theme_style=ft.TextThemeStyle.LABEL_SMALL, color=Palette.ON_SURFACE_VARIANT),
            *move_rows,
        ])
        self.bgcolor = Palette.SURFACE_2
        self.border_radius = Radius.MD
        self.border = ft.Border.all(1, Palette.OUTLINE_VARIANT)
        self.padding = Space.MD
        self.expand = True

    # -- species search ------------------------------------------------------------------------

    def _suggest(self, query: str) -> None:
        matches = self.store.search_species(query)
        self._suggestions.controls = [
            ft.Chip(
                label=ft.Text(s.name),
                leading=ft.Image(src=get_pokemon_sprite_url(s.canonical_id), width=22, height=22, fit=ft.BoxFit.CONTAIN,
                                 error_content=ft.Icon(ft.Icons.CATCHING_POKEMON, size=16, color=Palette.ON_SURFACE_VARIANT)),
                show_checkmark=False, border_side=ft.BorderSide(1, Palette.PRIMARY) if i == 0 else None, tooltip="Enter picks this one" if i == 0 else None,
                on_click=lambda _e, cid=s.canonical_id: self._pick(cid),
            )
            for i, s in enumerate(matches)
        ]
        self._suggestions.visible = bool(matches)
        self._safe_update(self._suggestions)

    def _submit(self, query: str) -> None:
        matches = self.store.search_species(query)
        if matches:
            self._pick(matches[0].canonical_id)

    def _pick(self, canonical_id: str) -> None:
        self.search.value = ""
        self._suggestions.controls = []
        self._suggestions.visible = False
        self.store.load_species(self.side, canonical_id)

    # -- edits ---------------------------------------------------------------------------------

    def _spread_changed(self, nature: str, points: dict[str, int]) -> None:
        if self._syncing:
            return
        self.store.set_pokemon(self.side, nature=nature, points=dict(points))

    def _boost_changed(self, stat: str, value: str | None) -> None:
        if self._syncing:
            return
        try:
            self.store.set_boost(self.side, stat, int(value or 0))
        except ValueError:
            pass

    def _ability_changed(self, value: str | None) -> None:
        if self._syncing:
            return
        self.store.set_pokemon(self.side, ability=(value or "").strip() or None)

    def _hp_typed(self, text: str) -> None:
        try:
            self.store.set_hp_abs(self.side, int(text))
        except ValueError:
            pass

    # -- rendering -----------------------------------------------------------------------------

    def update_from(self) -> None:
        self._syncing = True
        try:
            state = self.store.state.side(self.side)
            species = self.store.species(self.side)
            stats = self.store.stats(self.side)
            if species is None:
                self._name.value = "Pick a species"
                self._types.controls = []
                self._caption.value = "Type a name above — every Champions species and Mega is available." if state.species is None else f"Unknown species: {state.species}"
                self._legality.visible = False
                self.sprite.set_src(None)
                self.sprite.set_tooltip(None)
                self.editor.visible = False
            else:
                self._name.value = species.name
                self._types.controls = [TypeChip(t, size="sm") for t in species.types_lower]
                bits = [state.source] if state.source else []
                bits.append(f"{species.weightkg:g} kg")
                if state.assumptions:
                    bits.append("; ".join(state.assumptions))
                self._caption.value = " · ".join(bits)
                self._legality.visible = not species.is_legal
                self.sprite.set_src(get_pokemon_sprite_url(species.canonical_id))
                self.sprite.set_tooltip(species.name)
                self.sprite.set_ring("mega" if species.is_mega else "type", species.types_lower[0] if species.types_lower else None)
                self.editor.visible = True
                self.editor.set_base_stats(species.stats)
                self.editor.set_values(state.nature, state.points)
            for stat, dd in self._boosts.items():
                dd.value = str(state.boosts.get(stat, 0))
            options = self.store.ability_options(self.side)
            self._ability.options = [ft.DropdownOption(key=a, text=a) for a in options]
            self._ability.value = state.ability if state.ability in options else (options[0] if options else None)
            self._ability_on.value = state.ability_on
            self._item_name.value = state.item or "Held item…"
            self._item_name.color = Palette.ON_SURFACE if state.item else Palette.ON_SURFACE_VARIANT
            self._item_clear.visible = bool(state.item)
            max_hp = self.store.max_hp(self.side)
            cur_hp = self.store.cur_hp(self.side)
            self._hp_slider.value = state.hp_pct
            self._hp_abs.value = str(cur_hp) if max_hp else ""
            self._hp_label.value = f"/ {max_hp} ({state.hp_pct:.0f}%)" if max_hp else ""
            self._status.value = state.status
            self._allies.value = str(state.allies_fainted)
            for index, button in enumerate(self._moves):
                name = state.moves[index]
                info = self.store.catalogs.move_by_name(name) if name else None
                legal = self.store.catalogs.move_legality(species.canonical_id, name) if species and name else None
                button.update_from(_Move(name, info, legal) if name else None, species=species.name if species else "")
                self._crits[index].selected = bool(state.crit[index])
        finally:
            self._syncing = False
        self._safe_update(self)

    def focus_search(self) -> bool:
        try:
            if self.search.page is not None:
                self.search.focus()
                return True
        except RuntimeError:
            pass
        return False

    @staticmethod
    def _safe_update(control: ft.Control) -> None:
        try:
            if control.page is not None:
                control.update()
        except RuntimeError:
            pass

    @property
    def spread_summary(self) -> str:
        state = self.store.state.side(self.side)
        return f"{state.nature.capitalize()} · {format_points(state.points) or 'no points'}"


from ....domain.entities.pokemon_stats import PokemonStats  # noqa: E402

_ZERO = PokemonStats(hp=1, attack=1, defense=1, sp_atk=1, sp_def=1, speed=1)

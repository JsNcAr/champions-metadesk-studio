"""Attacker / defender panels: identity with ability and speed, item, HP, then the four move
cards that carry the results, and below them the collapsible spread (radar + editor) and
"Stages & status" sections. Results come first; the tuning is one click away."""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import replace

import flet as ft

from ....domain.entities.pokemon_stats import PokemonStats
from ....domain.pokemon_identity import get_pokemon_sprite_url
from ....services.sprite_cache_service import resolve_sprite_src
from ...components import Sprite, StatusChip
from ...components.inputs import SEARCH_FIELD_STYLE
from ...components.pokemon import TypeChip
from ...components.section import SectionHeader
from ...components.spread_editor import SpreadEditor
from ...tasks import Debouncer, is_mounted
from ...theme import STAT_COLORS, STAT_LABELS, IconSize, Palette, Radius, Space
from .chips import set_toggle, toggle_chip
from .move_card import MoveCard
from .radar import RadarChart
from .state import BOOST_STATS, STATUSES, TOGGLE_ABILITIES
from .store import CalcStore, move_effect

_ZERO = PokemonStats(hp=1, attack=1, defense=1, sp_atk=1, sp_def=1, speed=1)


class StageControl(ft.Column):
    """`Atk  [−] +2 [+]` for one stat stage."""

    def __init__(self, stat: str, on_bump: Callable[[str, int], None]) -> None:
        super().__init__(spacing=0, tight=True, horizontal_alignment=ft.CrossAxisAlignment.CENTER)
        self.value = ft.Text("0", theme_style=ft.TextThemeStyle.LABEL_LARGE, color=Palette.ON_SURFACE, width=26, text_align=ft.TextAlign.CENTER)
        self.controls = [
            ft.Text(STAT_LABELS[stat], theme_style=ft.TextThemeStyle.LABEL_SMALL, color=STAT_COLORS[stat]),
            ft.Row(spacing=0, tight=True, vertical_alignment=ft.CrossAxisAlignment.CENTER, controls=[
                ft.IconButton(icon=ft.Icons.REMOVE, icon_size=14, width=24, height=24, padding=0, tooltip=f"Lower {STAT_LABELS[stat]}", on_click=lambda _e: on_bump(stat, -1)),
                self.value,
                ft.IconButton(icon=ft.Icons.ADD, icon_size=14, width=24, height=24, padding=0, tooltip=f"Raise {STAT_LABELS[stat]}", on_click=lambda _e: on_bump(stat, +1)),
            ]),
        ]

    def set(self, stage: int) -> None:
        self.value.value = f"{stage:+d}" if stage else "0"
        self.value.color = Palette.SUCCESS if stage > 0 else Palette.ERROR if stage < 0 else Palette.ON_SURFACE


def _modifiers_summary(state) -> str:
    """"+2 Atk · −1 Spe · Burned", so a collapsed section never hides an active modifier."""
    bits = [f"{value:+d} {STAT_LABELS[stat]}".replace("-", "−") for stat, value in state.boosts.items() if value]
    if state.status != "none":
        bits.append(dict(STATUSES).get(state.status, state.status))
    return " · ".join(bits)


class PokemonPanel(ft.Container):
    def __init__(self, side: str, *, title: str, accent: str, store: CalcStore, on_pick_move: Callable[[str, int], None], on_pick_item: Callable[[str], None],
                 on_copy: Callable[[str], None]) -> None:
        super().__init__()
        self.side = side
        self.store = store
        self._on_pick_move = on_pick_move
        self._on_pick_item = on_pick_item
        self._syncing = False
        self._head: tuple | None = None          # what the non-card part was last drawn from
        self._spread_later: Debouncer | None = None

        self.search = ft.TextField(hint_text="Species…", prefix_icon=ft.Icons.SEARCH, dense=True, **SEARCH_FIELD_STYLE,
                                   on_change=lambda e: self._suggest(e.control.value or ""), on_submit=lambda e: self._submit(e.control.value or ""))
        self._suggestions = ft.Row(spacing=Space.XS, wrap=True, visible=False)
        self._no_match = ft.Text("", theme_style=ft.TextThemeStyle.BODY_SMALL, color=Palette.ON_SURFACE_VARIANT, visible=False)
        self.sprite = Sprite(size=64)
        self._name = ft.Text("Pick a species", theme_style=ft.TextThemeStyle.TITLE_MEDIUM, color=Palette.ON_SURFACE, max_lines=1, overflow=ft.TextOverflow.ELLIPSIS)
        self._types = ft.Row(spacing=Space.XS, tight=True)
        self._mega = StatusChip("Mega", "warning")
        self._mega.visible = False
        self._form = ft.SegmentedButton(
            selected=["base"],
            allow_multiple_selection=False,
            allow_empty_selection=False,
            show_selected_icon=False,
            segments=[ft.Segment(value="base", label=ft.Text("Base"))],
            visible=False,
            on_change=lambda e: self._on_form_changed(next(iter(e.control.selected or []))),
        )
        self._speed = StatusChip("Spe", "neutral")
        self._speed.visible = False
        self._ability = ft.Dropdown(dense=True, expand=True, text_size=13, enable_filter=True, options=[], on_select=lambda e: self._ability_changed(e.control.value))
        self._ability_on = ft.Chip(label=ft.Text("Activate"), selected=False, show_checkmark=True, visible=False,
                                   tooltip="Ability already triggered: Intimidate applied, Flash Fire lit, Electromorphosis charged, Unburden active…",
                                   on_select=lambda e: self._ability_on_changed(bool(e.control.selected)))
        self._caption = ft.Text("", theme_style=ft.TextThemeStyle.BODY_SMALL, color=Palette.ON_SURFACE_VARIANT, max_lines=2, overflow=ft.TextOverflow.ELLIPSIS)
        self._legality = StatusChip("Not in Champions", "warning", icon=ft.Icons.WARNING_AMBER_ROUNDED)
        self._legality.visible = False

        self._item_name = ft.Text("Held item…", theme_style=ft.TextThemeStyle.BODY_MEDIUM, color=Palette.ON_SURFACE_VARIANT, expand=True, max_lines=1, overflow=ft.TextOverflow.ELLIPSIS)
        self._item_clear = ft.IconButton(icon=ft.Icons.CLOSE, icon_size=16, width=28, height=28, padding=0, tooltip="Remove item", visible=False,
                                         on_click=lambda _e: self.store.set_item(self.side, None))
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
        self._hp_abs = ft.TextField(value="", width=64, dense=True, text_align=ft.TextAlign.CENTER, keyboard_type=ft.KeyboardType.NUMBER,
                                    on_submit=lambda e: self._hp_typed(e.control.value or ""), on_blur=lambda e: self._hp_typed(e.control.value or ""))
        self._hp_label = ft.Text("", theme_style=ft.TextThemeStyle.LABEL_MEDIUM, color=Palette.ON_SURFACE, width=96, text_align=ft.TextAlign.RIGHT)

        self.radar = RadarChart(size=140, colour=accent)
        self.editor = SpreadEditor(base_stats=_ZERO, nature="hardy", points={}, on_change=self._spread_changed, compact=True)
        self._spread_body = ft.Column(spacing=Space.SM, tight=True, horizontal_alignment=ft.CrossAxisAlignment.STRETCH,
                                      controls=[ft.Row(alignment=ft.MainAxisAlignment.CENTER, controls=[self.radar]), self.editor])
        self._spread_open = store.section_open("spread", True)
        self._spread_body.visible = self._spread_open
        self._spread_toggle = ft.IconButton(icon=ft.Icons.EXPAND_LESS if self._spread_open else ft.Icons.EXPAND_MORE, icon_size=IconSize.SM,
                                            tooltip="Collapse" if self._spread_open else "Expand", on_click=lambda _e: self._toggle_spread())

        self._stages: dict[str, StageControl] = {stat: StageControl(stat, self._bump) for stat in BOOST_STATS}
        self._status_chips: dict[str, ft.Chip] = {}
        status_controls: list[ft.Control] = []
        for key, label in STATUSES:
            chip = toggle_chip(label, lambda key=key: self._status_changed(key), selected=key == "none")
            self._status_chips[key] = chip
            status_controls.append(chip)
        self._allies = ft.Dropdown(label="Allies fainted", dense=True, width=150, text_size=13, value="0", tooltip="Supreme Overlord",
                                   options=[ft.DropdownOption(key=str(n), text=str(n)) for n in range(6)], on_select=lambda e: self.store.set_pokemon(self.side, allies_fainted=int(e.control.value or 0)))
        self._mods_body = ft.Column(spacing=Space.SM, tight=True, controls=[
            ft.Row(spacing=Space.SM, wrap=True, alignment=ft.MainAxisAlignment.SPACE_BETWEEN, controls=list(self._stages.values())),
            ft.Row(spacing=Space.XS, run_spacing=Space.XS, wrap=True, vertical_alignment=ft.CrossAxisAlignment.CENTER, controls=[*status_controls, self._allies]),
        ])

        self._mods_open = store.section_open("mods", False)
        self._mods_toggle = ft.IconButton(icon=ft.Icons.EXPAND_LESS if self._mods_open else ft.Icons.EXPAND_MORE, icon_size=IconSize.SM,
                                          tooltip="Collapse" if self._mods_open else "Expand", on_click=lambda _e: self._toggle_mods())
        self._mods_header = SectionHeader("Stages & status", accent=Palette.OUTLINE, action=self._mods_toggle)
        self._fill = ft.TextButton("Fill with top moves", icon=ft.Icons.AUTO_FIX_HIGH, visible=False,
                                   tooltip="Most used in tournaments, or the hardest hitters when there is no usage data",
                                   on_click=lambda _e: self.store.fill_top_moves(self.side))

        self.cards: list[MoveCard] = [
            MoveCard(i, on_pick=lambda i: self._on_pick_move(self.side, i), on_crit=lambda i: self.store.toggle_crit(self.side, i),
                     on_activate=lambda i: self.store.toggle_move_effect(self.side, i), on_copy=on_copy)
            for i in range(4)
        ]

        self.content = ft.Column(spacing=Space.SM, tight=True, horizontal_alignment=ft.CrossAxisAlignment.STRETCH, controls=[
            SectionHeader(title, accent=accent),
            self.search,
            self._suggestions,
            self._no_match,
            ft.Row(spacing=Space.MD, vertical_alignment=ft.CrossAxisAlignment.CENTER, controls=[
                self.sprite,
                ft.Column(spacing=3, tight=True, expand=True, controls=[
                    ft.Row(spacing=Space.SM, tight=True, controls=[self._name, self._mega]),
                    ft.Row(spacing=Space.SM, wrap=True, vertical_alignment=ft.CrossAxisAlignment.CENTER, controls=[self._form]),
                    ft.Row(spacing=Space.XS, tight=True, controls=[self._types, self._speed]),
                    ft.Row(spacing=Space.SM, vertical_alignment=ft.CrossAxisAlignment.CENTER, controls=[self._ability, self._ability_on]),
                    self._caption, self._legality,
                ]),
            ]),
            self._item_field,
            ft.Row(spacing=Space.SM, vertical_alignment=ft.CrossAxisAlignment.CENTER, controls=[
                ft.Text("HP", theme_style=ft.TextThemeStyle.LABEL_MEDIUM, color=STAT_COLORS["hp"], width=24), self._hp_slider, self._hp_abs, self._hp_label,
            ]),
            SectionHeader("Moves", accent=Palette.OUTLINE, action=self._fill),
            *self.cards,
            SectionHeader("Spread", accent=Palette.OUTLINE, action=self._spread_toggle),
            self._spread_body,
            self._mods_header,
            self._mods_body,
        ])
        self.bgcolor = Palette.SURFACE_2
        self.border_radius = Radius.MD
        self.border = ft.Border.all(1, Palette.OUTLINE_VARIANT)
        self.padding = Space.MD
        self.col = {"xs": 12, "lg": 6}   # side by side from the large breakpoint, stacked below it

    # -- species search ------------------------------------------------------------------------

    def _suggest(self, query: str) -> None:
        matches = self.store.search_species(query)
        self._show_no_match(query if query.strip() and not matches else None)
        self._suggestions.controls = [
            ft.Chip(
                label=ft.Text(s.name, color=Palette.ON_SURFACE),
                leading=ft.Image(src=resolve_sprite_src(get_pokemon_sprite_url(s.canonical_id)), width=22, height=22, fit=ft.BoxFit.CONTAIN,
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
        elif query.strip():
            self._show_no_match(query)   # keep the text so it can be corrected

    def _show_no_match(self, query: str | None) -> None:
        visible = query is not None
        if visible == self._no_match.visible and (not visible or self._no_match.value.endswith(f"‘{query.strip()}’")):
            return
        self._no_match.visible = visible
        self._no_match.value = f"No Pokémon matches ‘{query.strip()}’" if visible else ""
        self._safe_update(self._no_match)

    def _pick(self, canonical_id: str) -> None:
        self.search.value = ""
        self._show_no_match(None)
        self._suggestions.controls = []
        self._suggestions.visible = False
        self.store.load_species(self.side, canonical_id, preset=self.side == "right" and self.store.sweep_presets)

    # -- edits ---------------------------------------------------------------------------------

    def _on_form_changed(self, form_id: str) -> None:
        if not self._syncing and form_id:
            self.store.switch_form(self.side, form_id)

    def _spread_changed(self, nature: str, points: dict[str, int]) -> None:
        """Show the edit at once; recompute once the slider or typing pauses.

        Each slider tick used to recompute both directions, save the preferences, redraw
        both panels and restart the opponents sweep.
        """
        if self._syncing:
            return
        if not is_mounted(self):
            self.store.set_pokemon(self.side, nature=nature, points=dict(points))
            return
        self._safe_update(self.editor)
        if self._spread_later is None:
            self._spread_later = Debouncer(self.page, 150, lambda v: self.store.set_pokemon(self.side, nature=v[0], points=v[1]))
        self._spread_later((nature, dict(points)))

    def _bump(self, stat: str, delta: int) -> None:
        self.store.bump_boost(self.side, stat, delta)

    def _ability_changed(self, value: str | None) -> None:
        if not self._syncing:
            self.store.set_pokemon(self.side, ability=(value or "").strip() or None)

    def _ability_on_changed(self, value: bool) -> None:
        if not self._syncing:
            self.store.set_pokemon(self.side, ability_on=value)

    def _status_changed(self, key: str) -> None:
        if not self._syncing:
            self.store.set_pokemon(self.side, status=key)

    def _hp_typed(self, text: str) -> None:
        try:
            hp = int(text)
        except ValueError:
            max_hp = self.store.max_hp(self.side)
            self._hp_abs.value = str(self.store.cur_hp(self.side)) if max_hp else ""   # not a number: put it back
            self._safe_update(self._hp_abs)
            return
        if hp != self.store.cur_hp(self.side):
            self.store.set_hp_abs(self.side, hp)

    def _toggle_spread(self) -> None:
        self._spread_open = not self._spread_open
        self._spread_body.visible = self._spread_open
        self._spread_toggle.icon = ft.Icons.EXPAND_LESS if self._spread_open else ft.Icons.EXPAND_MORE
        self._spread_toggle.tooltip = "Collapse" if self._spread_open else "Expand"
        self.store.set_section_open("spread", self._spread_open)
        self._safe_update(self)

    def _toggle_mods(self) -> None:
        self._mods_open = not self._mods_open
        self._mods_body.visible = self._mods_open
        self._mods_toggle.icon = ft.Icons.EXPAND_LESS if self._mods_open else ft.Icons.EXPAND_MORE
        self._mods_toggle.tooltip = "Collapse" if self._mods_open else "Expand"
        self.store.set_section_open("mods", self._mods_open)
        self._safe_update(self)

    # -- rendering -----------------------------------------------------------------------------

    def update_from(self) -> None:
        state = self.store.state.side(self.side)
        # Everything outside the move cards depends on this. When only moves, crits, applied
        # effects or the results changed, just the affected cards are redrawn.
        head = (replace(state, moves=[], crit=[], active=[]), any(state.moves), self.store.speed_order(), self.store.speed(self.side), id(self.store.catalogs))
        if head == self._head:
            self._update_cards(state, redraw=True)
            return
        self._head = head
        self._syncing = True
        try:
            species = self.store.species(self.side)
            stats = self.store.stats(self.side)
            other = "right" if self.side == "left" else "left"
            if species is None:
                self._name.value = "Pick a species"
                self._types.controls = []
                self._mega.visible = self._form.visible = self._speed.visible = self._legality.visible = self._ability_on.visible = False
                self._caption.value = "Type a name above, or pick one from your team or the box." if state.species is None else f"Unknown species: {state.species}"
                self.sprite.set_src(None)
                self.sprite.set_tooltip(None)
                self.editor.visible = False
                self.radar.set_stats(None)
            else:
                self._name.value = species.name
                self._types.controls = [TypeChip(t, size="sm") for t in species.types_lower]
                self._mega.visible = species.is_mega
                form_choices = self.store.catalogs.form_choices_for(species.canonical_id)
                if form_choices and self.store.mega_enabled:
                    self._form.visible = True
                    self._form.segments = [ft.Segment(value=cid, label=ft.Text(lbl)) for cid, lbl in form_choices]
                    self._form.selected = [species.canonical_id]
                else:
                    self._form.visible = False
                    self._form.segments = [ft.Segment(value="base", label=ft.Text("Base"))]
                    self._form.selected = ["base"]
                order = self.store.speed_order()
                faster = order == self.side
                self._speed.visible = True
                self._speed.set(f"Spe {self.store.speed(self.side)}{' ▲' if faster else (' ▼' if order == other else '')}", "success" if faster else ("error" if order == other else "neutral"),
                                tooltip="Moves first" if faster else ("Moves second" if order == other else "Speed tie"))
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
                self.radar.set_stats(stats)
                self._ability_on.selected = state.ability_on
                self._ability_on.label = ft.Text("Active" if state.ability_on else "Activate")
            options = self.store.ability_options(self.side)
            self._ability.options = [ft.DropdownOption(key=a, text=a) for a in options]
            self._ability.value = state.ability if state.ability in options else (options[0] if options else None)
            # Only abilities the engine can switch on get the chip, and only Supreme Overlord
            # reads fainted allies (a value already set stays visible so it can be cleared).
            ability = self._ability.value if species is not None else None
            self._ability_on.visible = ability in TOGGLE_ABILITIES or (species is not None and state.ability_on)
            self._item_name.value = state.item or "Held item…"
            self._item_name.color = Palette.ON_SURFACE if state.item else Palette.ON_SURFACE_VARIANT
            self._item_clear.visible = bool(state.item)
            max_hp = self.store.max_hp(self.side)
            self._hp_slider.value = state.hp_pct
            self._hp_abs.value = str(self.store.cur_hp(self.side)) if max_hp else ""
            self._hp_label.value = f"/ {max_hp} ({state.hp_pct:.0f}%)" if max_hp else ""
            for stat, control in self._stages.items():
                control.set(state.boosts.get(stat, 0))
            self._mods_body.visible = self._mods_open
            self._mods_header.set_status(_modifiers_summary(state), color=Palette.WARNING if (state.boosts or state.status != "none") else None)
            self._fill.visible = species is not None and not any(state.moves)
            for key, chip in self._status_chips.items():
                set_toggle(chip, state.status == key)
            self._allies.value = str(state.allies_fainted)
            self._allies.visible = ability == "Supreme Overlord" or state.allies_fainted > 0
            self._update_cards(state, redraw=False)
        finally:
            self._syncing = False
        self._safe_update(self)

    def _update_cards(self, state, *, redraw: bool) -> None:
        results = self.store.results.left_vs_right if self.side == "left" else self.store.results.right_vs_left
        by_index = {r.index: r for r in results}
        for index, card in enumerate(self.cards):
            name = state.moves[index]
            info = self.store.catalogs.move_by_name(name) if name else None
            changed = card.update_from(name, info, by_index.get(index), active=bool(state.active[index]), effect=move_effect(name), crit=bool(state.crit[index]))
            if redraw and changed:
                self._safe_update(card)

    def collapse_cards(self) -> bool:
        changed = False
        for card in self.cards:
            if card.expanded:
                card.toggle()
                changed = True
        return changed

    def focus_search(self) -> bool:
        try:
            if self.search.page is not None:
                # ``focus`` is a coroutine in Flet 0.85: called bare it never ran.
                self.search.page.run_task(self.search.focus)
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

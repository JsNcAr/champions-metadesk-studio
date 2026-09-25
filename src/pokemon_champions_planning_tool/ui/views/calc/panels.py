"""Attacker / defender columns: a fixed header (sprite, name, form, types, speed, ability,
item, HP), then three tabs — Moves (the four cards that carry the results), Build (nature
and stat points with a small radar, and the benchmarks of the best move) and Stages (stat
stages, status) — and this side's field conditions at the bottom. The results are always
in the first tab; the tuning is one click away and never pushes them off screen."""

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
from ...components.spread_editor import SpreadEditor
from ...format import shortcut
from ...tasks import Debouncer, is_mounted, safe_update
from ...theme import STAT_COLORS, STAT_LABELS, IconSize, Palette, Radius, Space
from . import bench_view
from .chips import set_toggle, toggle_chip
from .field_bar import SideConditionsRow
from .move_card import MoveCard
from .radar import RadarChart
from .state import BOOST_STATS, STATUSES, TOGGLE_ABILITIES
from .store import CalcStore, best_of, move_effect
from .summary import BestHit

_ZERO = PokemonStats(hp=1, attack=1, defense=1, sp_atk=1, sp_def=1, speed=1)
TABS: tuple[tuple[str, str], ...] = (("moves", "Moves"), ("build", "Build"), ("stages", "Stages"))

# Asks the view for a move's benchmarks: (side, move index, answer callback). The answer comes
# at once when cached, else later from a worker.
BenchRequest = Callable[[str, int, Callable[[object], None]], None]


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


def modifiers_summary(state) -> str:
    """"+2 Atk · −1 Spe · Burned": what the Stages tab holds, for its tooltip."""
    bits = [f"{value:+d} {STAT_LABELS[stat]}".replace("-", "−") for stat, value in state.boosts.items() if value]
    if state.status != "none":
        bits.append(dict(STATUSES).get(state.status, state.status))
    return " · ".join(bits)


def modifiers_count(state) -> int:
    return sum(1 for v in state.boosts.values() if v) + (state.status != "none")


class TabBar(ft.Row):
    """Three text tabs with an underline on the selected one."""

    def __init__(self, on_select: Callable[[str], None]) -> None:
        super().__init__(spacing=0)
        self._on_select = on_select
        self.labels: dict[str, ft.Text] = {}
        self.tabs: dict[str, ft.Container] = {}
        for key, label in TABS:
            text = ft.Text(label, theme_style=ft.TextThemeStyle.LABEL_LARGE)
            tab = ft.Container(content=text, padding=ft.Padding.symmetric(horizontal=Space.MD, vertical=6), ink=True,
                               on_click=lambda _e, key=key: on_select(key))
            self.labels[key] = text
            self.tabs[key] = tab
        self.controls = list(self.tabs.values())
        self.selected = "moves"

    def select(self, key: str) -> None:
        self.selected = key
        for k, tab in self.tabs.items():
            on = k == key
            self.labels[k].color = Palette.PRIMARY if on else Palette.ON_SURFACE_VARIANT
            self.labels[k].weight = ft.FontWeight.W_700 if on else ft.FontWeight.W_500
            tab.border = ft.Border(bottom=ft.BorderSide(2, Palette.PRIMARY if on else ft.Colors.TRANSPARENT))

    def set_label(self, key: str, label: str, tooltip: str | None = None) -> None:
        self.labels[key].value = label
        self.tabs[key].tooltip = tooltip


class PokemonPanel(ft.Container):
    def __init__(self, side: str, *, title: str, accent: str, store: CalcStore, on_pick_move: Callable[[str, int], None], on_pick_item: Callable[[str], None],
                 on_copy: Callable[[str], None], on_bench: BenchRequest | None = None, on_apply_points: Callable[[str, dict[str, int]], None] | None = None,
                 on_tab: Callable[[str, str], None] | None = None, tab: str = "moves") -> None:
        super().__init__()
        self.side = side
        self.other = "right" if side == "left" else "left"
        self.store = store
        self._on_pick_move = on_pick_move
        self._on_pick_item = on_pick_item
        self._on_bench = on_bench
        self._on_apply_points = on_apply_points
        self._on_tab = on_tab
        self._syncing = False
        self._head: tuple | None = None          # what the non-card part was last drawn from
        self._spread_later: Debouncer | None = None
        self._search_open = False   # the user opened the search over a loaded Pokémon
        self._build_bench_key: tuple | None = None

        # -- header ---------------------------------------------------------------------------
        self.search = ft.TextField(hint_text="Search a Pokémon…", prefix_icon=ft.Icons.SEARCH, dense=True, **SEARCH_FIELD_STYLE,
                                   on_change=lambda e: self._suggest(e.control.value or ""), on_submit=lambda e: self._submit(e.control.value or ""))
        self._search_close = ft.IconButton(icon=ft.Icons.CLOSE, icon_size=16, tooltip="Cancel", on_click=lambda _e: self.close_search())
        self._search_row = ft.Row(spacing=Space.XS, vertical_alignment=ft.CrossAxisAlignment.CENTER, controls=[ft.Container(content=self.search, expand=True), self._search_close])
        self._suggestions = ft.Row(spacing=Space.XS, run_spacing=Space.XS, wrap=True, visible=False)
        self._no_match = ft.Text("", theme_style=ft.TextThemeStyle.BODY_SMALL, color=Palette.ON_SURFACE_VARIANT, visible=False)
        self.sprite = Sprite(size=56)
        self._name = ft.Text("Pick a species", theme_style=ft.TextThemeStyle.TITLE_MEDIUM, weight=ft.FontWeight.W_700, color=Palette.ON_SURFACE,
                             max_lines=1, overflow=ft.TextOverflow.ELLIPSIS)
        self._name_button = ft.Container(content=ft.Row(spacing=Space.XS, tight=True, vertical_alignment=ft.CrossAxisAlignment.CENTER, controls=[
            self._name, ft.Icon(ft.Icons.EDIT_OUTLINED, size=14, color=Palette.ON_SURFACE_VARIANT)]),
            ink=True, border_radius=Radius.SM, tooltip=shortcut("Change Pokémon (Ctrl+F on the attacker)"), on_click=lambda _e: self.open_search())
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
            style=ft.ButtonStyle(visual_density=ft.VisualDensity.COMPACT),
            on_change=lambda e: self._on_form_changed(next(iter(e.control.selected or []))),
        )
        self._speed = StatusChip("Spe", "neutral")
        self._speed.visible = False
        self._ability = ft.Dropdown(label="Ability", dense=True, expand=True, text_size=13, enable_filter=True, options=[], on_select=lambda e: self._ability_changed(e.control.value))
        self._ability_on = ft.Chip(label=ft.Text("Activate"), selected=False, show_checkmark=True, visible=False,
                                   tooltip="Ability already triggered: Intimidate applied, Flash Fire lit, Electromorphosis charged, Unburden active…",
                                   on_select=lambda e: self._ability_on_changed(bool(e.control.selected)))
        self._caption = ft.Text("", theme_style=ft.TextThemeStyle.BODY_SMALL, color=Palette.ON_SURFACE_VARIANT, max_lines=1, overflow=ft.TextOverflow.ELLIPSIS)
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
            height=40, expand=True, padding=ft.Padding.symmetric(horizontal=Space.MD), border_radius=Radius.SM, bgcolor=Palette.SURFACE_3, border=ft.Border.all(1, Palette.OUTLINE),
            ink=True, on_click=lambda _e: self._on_pick_item(self.side), tooltip="Choose held item",
        )
        self._hp_slider = ft.Slider(min=0, max=100, divisions=100, value=100, expand=True, active_color=STAT_COLORS["hp"],
                                    on_change_end=lambda e: self.store.set_hp_pct(self.side, float(e.control.value)))
        self._hp_abs = ft.TextField(value="", width=60, dense=True, text_align=ft.TextAlign.CENTER, keyboard_type=ft.KeyboardType.NUMBER,
                                    on_submit=lambda e: self._hp_typed(e.control.value or ""), on_blur=lambda e: self._hp_typed(e.control.value or ""))
        self._hp_label = ft.Text("", theme_style=ft.TextThemeStyle.LABEL_MEDIUM, color=Palette.ON_SURFACE, width=88, text_align=ft.TextAlign.RIGHT)

        self._identity = ft.Row(spacing=Space.MD, vertical_alignment=ft.CrossAxisAlignment.CENTER, controls=[
            self.sprite,
            ft.Column(spacing=2, tight=True, expand=True, controls=[
                ft.Row(spacing=Space.SM, vertical_alignment=ft.CrossAxisAlignment.CENTER, controls=[self._name_button, self._mega]),
                ft.Row(spacing=Space.XS, wrap=True, vertical_alignment=ft.CrossAxisAlignment.CENTER, controls=[self._types, self._speed, self._legality]),
            ]),
            self._form,
        ])
        self._set_row = ft.Row(spacing=Space.SM, vertical_alignment=ft.CrossAxisAlignment.CENTER, controls=[self._ability, self._ability_on, self._item_field])
        self._hp_row = ft.Row(spacing=Space.SM, vertical_alignment=ft.CrossAxisAlignment.CENTER, controls=[
            ft.Text("HP", theme_style=ft.TextThemeStyle.LABEL_MEDIUM, color=STAT_COLORS["hp"], width=24), self._hp_slider, self._hp_abs, self._hp_label,
        ])

        # -- tabs -----------------------------------------------------------------------------
        self.tab_bar = TabBar(self.select_tab)

        self._fill = ft.TextButton("Fill with top moves", icon=ft.Icons.AUTO_FIX_HIGH, visible=False,
                                   tooltip="Most used in tournaments, or the hardest hitters when there is no usage data",
                                   on_click=lambda _e: self.store.fill_top_moves(self.side))
        self.cards: list[MoveCard] = [
            MoveCard(i, on_pick=lambda i: self._on_pick_move(self.side, i), on_crit=lambda i: self.store.toggle_crit(self.side, i),
                     on_activate=lambda i: self.store.toggle_move_effect(self.side, i), on_copy=on_copy,
                     on_targets=lambda i: self.store.toggle_single_target(self.side, i),
                     on_expand=self._card_expanded if on_bench is not None else None, on_apply=self._apply_bench)
            for i in range(4)
        ]
        self._moves_body = ft.Column(spacing=Space.SM, tight=True, horizontal_alignment=ft.CrossAxisAlignment.STRETCH, controls=[*self.cards, self._fill])

        self.radar = RadarChart(size=110, colour=accent)
        self.editor = SpreadEditor(base_stats=_ZERO, nature="hardy", points={}, on_change=self._spread_changed, compact=True)
        self._build_bench = ft.Column(spacing=2, tight=True, controls=[])
        self._build_body = ft.Column(spacing=Space.SM, tight=True, horizontal_alignment=ft.CrossAxisAlignment.STRETCH, controls=[
            ft.Row(spacing=Space.SM, vertical_alignment=ft.CrossAxisAlignment.START, controls=[ft.Container(content=self.editor, expand=True), self.radar]),
            self._build_bench,
        ])

        self._stages: dict[str, StageControl] = {stat: StageControl(stat, self._bump) for stat in BOOST_STATS}
        self._status_chips: dict[str, ft.Chip] = {}
        status_controls: list[ft.Control] = []
        for key, label in STATUSES:
            chip = toggle_chip(label, lambda key=key: self._status_changed(key), selected=key == "none")
            self._status_chips[key] = chip
            status_controls.append(chip)
        self._allies = ft.Dropdown(label="Allies fainted", dense=True, width=150, text_size=13, value="0", tooltip="Supreme Overlord",
                                   options=[ft.DropdownOption(key=str(n), text=str(n)) for n in range(6)], on_select=lambda e: self.store.set_pokemon(self.side, allies_fainted=int(e.control.value or 0)))
        self._stages_body = ft.Column(spacing=Space.MD, tight=True, controls=[
            ft.Row(spacing=Space.SM, wrap=True, alignment=ft.MainAxisAlignment.SPACE_BETWEEN, controls=list(self._stages.values())),
            ft.Row(spacing=Space.XS, run_spacing=Space.XS, wrap=True, vertical_alignment=ft.CrossAxisAlignment.CENTER, controls=[*status_controls, self._allies]),
        ])
        self._bodies = {"moves": self._moves_body, "build": self._build_body, "stages": self._stages_body}
        self.conditions = SideConditionsRow(side, store=store)
        # This side's best hit on the other, in the header line; a click opens its card.
        self.best_hit = BestHit(side, store=store, on_open=lambda _side, index: self.expand_move(index))

        self._loaded = ft.Column(spacing=Space.SM, tight=True, horizontal_alignment=ft.CrossAxisAlignment.STRETCH, controls=[
            self._set_row, self._caption, self._hp_row,
            ft.Container(content=self.tab_bar, border=ft.Border(bottom=ft.BorderSide(1, Palette.OUTLINE_VARIANT))),
            *self._bodies.values(),
        ])
        self.content = ft.Column(spacing=Space.SM, tight=True, horizontal_alignment=ft.CrossAxisAlignment.STRETCH, controls=[
            ft.Row(spacing=Space.SM, vertical_alignment=ft.CrossAxisAlignment.CENTER, controls=[
                # The section overline (as SectionHeader draws it), kept tight so the best hit gets the rest.
                ft.Row(spacing=Space.SM, tight=True, vertical_alignment=ft.CrossAxisAlignment.CENTER, controls=[
                    ft.Container(width=3, height=12, border_radius=Radius.PILL, bgcolor=accent),
                    ft.Text(title.upper(), theme_style=ft.TextThemeStyle.LABEL_SMALL, color=Palette.ON_SURFACE_VARIANT),
                ]),
                ft.Container(content=self.best_hit, expand=True, alignment=ft.Alignment.CENTER_RIGHT),
            ]),
            self._identity,
            self._search_row, self._suggestions, self._no_match,
            self._loaded,
            ft.Container(content=self.conditions, padding=ft.Padding.only(top=Space.XS), border=ft.Border(top=ft.BorderSide(1, Palette.OUTLINE_VARIANT))),
        ])
        self.bgcolor = Palette.SURFACE_2
        self.border_radius = Radius.MD
        self.border = ft.Border.all(1, Palette.OUTLINE_VARIANT)
        self.padding = Space.MD
        self.col = {"xs": 12, "md": 6}
        self.select_tab(tab if tab in self._bodies else "moves", notify=False)
        self._show_search(False)

    # -- tabs ------------------------------------------------------------------------------------

    def select_tab(self, key: str, *, notify: bool = True) -> None:
        if key not in self._bodies:
            return
        self.tab_bar.select(key)
        for k, body in self._bodies.items():
            body.visible = k == key
        if key == "build":
            self._refresh_build_bench()
        if notify and self._on_tab is not None:
            self._on_tab(self.side, key)
        safe_update(self)

    @property
    def tab(self) -> str:
        return self.tab_bar.selected

    # -- species search ------------------------------------------------------------------------

    def _show_search(self, opened: bool) -> None:
        """The search row shows when opened over a Pokémon (with ✕) or when nothing is loaded."""
        empty = self.store.species(self.side) is None
        self._search_open = opened and not empty
        self._search_row.visible = opened or empty
        self._search_close.visible = self._search_open
        self._identity.visible = self._loaded.visible = not empty
        if not self._search_row.visible:
            self.search.value = ""
            self._suggestions.controls = []
            self._suggestions.visible = False
            self._show_no_match(None)

    def open_search(self) -> None:
        self._show_search(True)
        safe_update(self)
        self.focus_search()

    def close_search(self) -> None:
        self._show_search(False)
        safe_update(self)

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
        safe_update(self._suggestions)

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
        safe_update(self._no_match)

    def _pick(self, canonical_id: str) -> None:
        self._search_open = False
        self.search.value = ""
        self._suggestions.controls = []
        self._suggestions.visible = False
        self._show_no_match(None)
        self.store.load_species(self.side, canonical_id, preset=self.side == "right" and self.store.sweep_presets)
        self._show_search(False)
        safe_update(self)

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
        safe_update(self.editor)
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
            safe_update(self._hp_abs)
            return
        if hp != self.store.cur_hp(self.side):
            self.store.set_hp_abs(self.side, hp)

    # -- benchmarks ----------------------------------------------------------------------------

    def _apply_bench(self, target: str, points: dict[str, int]) -> None:
        if self._on_apply_points is not None:
            self._on_apply_points(self.side if target == "mine" else self.other, points)

    def _card_expanded(self, index: int) -> None:
        self._request_card(self.cards[index])

    def _names(self) -> tuple[str, str]:
        me, other = self.store.species(self.side), self.store.species(self.other)
        return (me.name if me else "You", other.name if other else "They")

    def _request_card(self, card: MoveCard) -> None:
        if self._on_bench is None:
            return
        key = self.store.benchmark_key(self.side, card.index)
        if card.bench_key == key:
            return
        card.bench_key = key
        names = self._names()
        card.set_benchmarks(None, loading=True, names=names)

        def answer(value, card=card, key=key) -> None:
            if card.bench_key == key:
                card.set_benchmarks(value, names=names)
        self._on_bench(self.side, card.index, answer)

    def _refresh_build_bench(self) -> None:
        """The Build tab: the benchmarks of this side's best move against the other side."""
        if self._on_bench is None or self.tab != "build":
            return
        results = self.store.results.left_vs_right if self.side == "left" else self.store.results.right_vs_left
        best = best_of(results)
        if best is None or self.store.species(self.other) is None:
            self._build_bench_key = None
            self._build_bench.controls = []
            return
        key = (self.store.benchmark_key(self.side, best.index), best.name)
        if key == self._build_bench_key:
            return
        self._build_bench_key = key
        mine, theirs = self._names()
        title = bench_view.heading(f"BENCHMARKS · {best.name} vs {theirs}")
        self._build_bench.controls = [bench_view.loading(title)]

        def answer(value, key=key) -> None:
            if key == self._build_bench_key:
                self._build_bench.controls = [title, *bench_view.rows(value, mine=mine, theirs=theirs, on_apply=self._apply_bench)]
                safe_update(self._build_bench)
        self._on_bench(self.side, best.index, answer)

    # -- rendering -----------------------------------------------------------------------------

    def update_from(self) -> None:
        state = self.store.state.side(self.side)
        self.best_hit.update_from()
        if self.conditions.update_from():
            safe_update(self.conditions)
        # Everything outside the move cards depends on this. When only moves, crits, applied
        # effects or the results changed, just the affected cards are redrawn.
        head = (replace(state, moves=[], crit=[], active=[], single=[]), any(state.moves), self.store.speed_order(), self.store.speed(self.side), id(self.store.catalogs),
                self.store.mega_enabled)
        if head == self._head:
            self._update_cards(state, redraw=True)
            self._refresh_build_bench()
            return
        self._head = head
        self._syncing = True
        try:
            species = self.store.species(self.side)
            stats = self.store.stats(self.side)
            if species is None:
                self._name.value = "Pick a species"
                self._types.controls = []
                self._mega.visible = self._form.visible = self._speed.visible = self._legality.visible = self._ability_on.visible = False
                self._caption.value = "" if state.species is None else f"Unknown species: {state.species}"
                self.search.hint_text = "Search a Pokémon, or pick one from your team or the side panel…" if state.species is None else f"Unknown species: {state.species}"
                self.sprite.set_src(None)
                self.sprite.set_tooltip(None)
                self.editor.visible = False
                self.radar.set_stats(None)
            else:
                self.search.hint_text = "Search a Pokémon…"
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
                self._speed.set(f"Spe {self.store.speed(self.side)}{' ▲' if faster else (' ▼' if order == self.other else '')}",
                                "success" if faster else ("error" if order == self.other else "neutral"),
                                tooltip="Moves first" if faster else ("Moves second" if order == self.other else "Speed tie"))
                bits = [state.source] if state.source else []
                bits.append(f"{species.weightkg:g} kg")
                if state.assumptions:
                    bits.append("; ".join(state.assumptions))
                self._caption.value = " · ".join(bits)
                self._caption.tooltip = self._caption.value
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
            count = modifiers_count(state)
            self.tab_bar.set_label("stages", f"Stages · {count}" if count else "Stages", modifiers_summary(state) or "Stat stages and status")
            spent = sum(state.points.values())
            self.tab_bar.set_label("build", f"Build · {state.nature.title()}" if species is not None else "Build", f"{spent} of 66 stat points")
            self._fill.visible = species is not None and not any(state.moves)
            for key, chip in self._status_chips.items():
                set_toggle(chip, state.status == key)
            self._allies.value = str(state.allies_fainted)
            self._allies.visible = ability == "Supreme Overlord" or state.allies_fainted > 0
            self._show_search(self._search_open)
            self._update_cards(state, redraw=False)
            self._refresh_build_bench()
        finally:
            self._syncing = False
        safe_update(self)

    def _update_cards(self, state, *, redraw: bool) -> None:
        results = self.store.results.left_vs_right if self.side == "left" else self.store.results.right_vs_left
        by_index = {r.index: r for r in results}
        for index, card in enumerate(self.cards):
            name = state.moves[index]
            info = self.store.catalogs.move_by_name(name) if name else None
            changed = card.update_from(name, info, by_index.get(index), active=bool(state.active[index]), effect=move_effect(name), crit=bool(state.crit[index]))
            if card.expanded:
                self._request_card(card)   # asks again only when the state changed
            if redraw and changed:
                safe_update(card)

    def expand_move(self, index: int) -> None:
        """Show a move's details (the versus bar's best hit was clicked)."""
        self.select_tab("moves")
        card = self.cards[index]
        if not card.expanded and card.result is not None and card.result.ok:
            card.toggle()

    def collapse_cards(self) -> bool:
        changed = False
        for card in self.cards:
            if card.expanded:
                card.toggle()
                changed = True
        if self._search_open:
            self.close_search()
            changed = True
        return changed

    def focus_search(self) -> bool:
        if not self._search_row.visible:
            self._show_search(True)
            safe_update(self)
        try:
            if self.search.page is not None:
                # ``focus`` is a coroutine in Flet 0.85: called bare it never ran.
                self.search.page.run_task(self.search.focus)
                return True
        except RuntimeError:
            pass
        return False


__all__ = ["PokemonPanel", "StageControl", "TABS", "TabBar", "modifiers_count", "modifiers_summary"]

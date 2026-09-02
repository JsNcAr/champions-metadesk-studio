"""Calc view: attacker | field | defender panels over a results list; both directions at once."""

from __future__ import annotations

import flet as ft

from ... import events
from ...components import PageHeader
from ...context import AppContext
from ...theme import Accent, Layout, Space
from ..team.dialogs.item_picker import ItemPickerDialog
from ..team.dialogs.move_picker import MovePickerDialog
from .field_panel import FieldPanel
from .panels import PokemonPanel
from .results import ResultsList
from .state import CalcRequest
from .store import CalcStore


class CalcView(ft.Column):
    def __init__(self, ctx: AppContext, store: CalcStore | None = None) -> None:
        super().__init__(spacing=Space.MD, expand=True, scroll=ft.ScrollMode.AUTO)
        self.ctx = ctx
        self.store = store or CalcStore(ctx.catalogs, prefs=ctx.prefs)
        self._narrow = False

        self.attacker = PokemonPanel("left", title="Attacker", accent=Accent.CALC, store=self.store, on_pick_move=self._open_move_picker, on_pick_item=self._open_item_picker)
        self.defender = PokemonPanel("right", title="Defender", accent=Accent.CALC, store=self.store, on_pick_move=self._open_move_picker, on_pick_item=self._open_item_picker)
        self.field = FieldPanel(store=self.store, accent=Accent.CALC, on_swap=self.store.swap_sides)
        self.field.width = Layout.SIDE_PANEL_WIDTH
        self.results = ResultsList(on_copy=self._copy, accent=Accent.CALC)

        self._panels = ft.Row(spacing=Space.LG, vertical_alignment=ft.CrossAxisAlignment.START, controls=[self.attacker, self.field, self.defender])
        self._stack = ft.Column(spacing=Space.LG, tight=True, controls=[])
        self._host = ft.Container(content=self._panels)
        self.header = PageHeader(
            "Calc", icon=ft.Icons.CALCULATE, accent=Accent.CALC, caption="Champions damage · both directions",
            actions=[
                ft.IconButton(icon=ft.Icons.SWAP_HORIZ, tooltip="Swap attacker and defender (Ctrl+Shift+S)", on_click=lambda _e: self.store.swap_sides()),
                ft.TextButton("Reset", icon=ft.Icons.RESTART_ALT, on_click=lambda _e: self.store.reset()),
            ],
        )
        # Results first so the numbers are visible without scrolling; the panels below tune them.
        self.controls = [self.header, self.results, self._host]

        self.store.subscribe(self._on_store)
        ctx.bus.on(events.CALC_REQUESTED, self._on_request)

    # -- lifecycle -----------------------------------------------------------------------------

    def ensure_loaded(self) -> None:
        if not self.store.loaded:
            self.store.load()

    def _on_store(self, event: tuple) -> None:
        if event[0] == "state":
            self.attacker.update_from()
            self.defender.update_from()
            self.field.update_from()
        elif event[0] == "results":
            self.results.update_from(self.store.results)
            self._sync_species_banner()

    def _sync_species_banner(self) -> None:
        if not self.store.catalogs.has_species:
            self.header.set_caption("Species data not synced yet — Settings › Moves, learnsets & species")

    def _on_request(self, req: CalcRequest) -> None:
        self.ensure_loaded()
        self.store.apply_request(req)
        self.ctx.bus.emit(events.NAVIGATE, "calc")
        names = []
        if req.attacker is not None:
            species = self.store.species("left")
            names.append(f"{species.name if species else 'attacker'} as attacker")
        if req.defender is not None:
            species = self.store.species("right")
            names.append(f"{species.name if species else 'defender'} as defender")
        if names:
            self.ctx.toast("Loaded " + " and ".join(names), "success")

    # -- layout ------------------------------------------------------------------------------------

    def handle_resize(self, width: float, height: float) -> None:
        narrow = width < Layout.BREAKPOINT_NARROW
        compact = width < Layout.BREAKPOINT_COMPACT
        if narrow != self._narrow:
            self._narrow = narrow
            self._panels.controls = []
            self._stack.controls = []
            if narrow:
                self._stack.controls = [self.attacker, self.defender, self.field]
                self._host.content = self._stack
                self.field.width = None
            else:
                self._panels.controls = [self.attacker, self.field, self.defender]
                self._host.content = self._panels
        if not narrow:
            self.field.width = Layout.SIDE_PANEL_WIDTH_COMPACT if compact else Layout.SIDE_PANEL_WIDTH
        try:
            if self.page is not None:
                self._host.update()
        except RuntimeError:
            pass

    def handle_key(self, e) -> bool:
        key = (e.key or "").lower()
        if e.ctrl and e.shift and key == "s":
            self.store.swap_sides()
            return True
        if e.ctrl and key == "f":
            return self.attacker.focus_search()
        if key == "escape":
            return self.results.collapse_all()
        return False

    # -- dialogs -------------------------------------------------------------------------------

    def _open_move_picker(self, side: str, index: int) -> None:
        species = self.store.species(side)
        if species is None:
            self.ctx.toast("Pick a species first", "info")
            return
        page = self.ctx.page
        current = self.store.state.side(side).moves[index]

        def pick(name: str | None) -> None:
            page.pop_dialog()
            self.store.set_move(side, index, name)

        page.show_dialog(MovePickerDialog(
            species_label=species.name, options=self.store.move_options(side), current=current,
            show_all=bool(self.ctx.prefs.get("team.show_all_moves", False)), on_pick=pick, on_close=page.pop_dialog,
        ))

    def _open_item_picker(self, side: str) -> None:
        species = self.store.species(side)
        if species is None:
            self.ctx.toast("Pick a species first", "info")
            return
        page = self.ctx.page
        state = self.store.state.side(side)
        current = self.store.catalogs.item_for(state.item) if state.item else None

        def pick(item_id: str | None) -> None:
            page.pop_dialog()
            record = self.store.catalogs.item_for(item_id) if item_id else None
            self.store.set_pokemon(side, item=record.display_name if record else None)

        page.show_dialog(ItemPickerDialog(
            catalogs=self.store.catalogs, species_name=species.name.split("-")[0].lower(), current_item_id=current.canonical_id if current else None,
            on_pick=pick, on_close=page.pop_dialog,
        ))

    def _copy(self, text: str) -> None:
        self.ctx.copy_to_clipboard(text)
        self.ctx.toast("Copied", "success")

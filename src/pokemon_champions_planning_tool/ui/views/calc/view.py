"""Calc view: the matchup summary under the header, then team/box rail | field strip over the
two Pokémon panels | opponent sweep. On wide windows each of the three columns scrolls on its
own, so the rail and the opponents stay in view; narrow windows stack them in one scroll."""

from __future__ import annotations

import flet as ft

from ... import events
from ...components import PageHeader
from ...context import AppContext
from ...tasks import Debouncer, is_mounted
from ...theme import Accent, Layout, Space
from ..team.dialogs.item_picker import ItemPickerDialog
from ..team.dialogs.move_picker import MovePickerDialog
from .field_strip import FieldStrip
from .panels import PokemonPanel
from .rail import CalcRail
from .state import CalcRequest, SweepEntry
from .store import CalcStore
from .summary import MatchupBar
from .sweep import SweepPanel

SAVE_DELAY_MS = 500    # a burst of edits (a slider drag) writes preferences.json once
SWEEP_DELAY_MS = 300   # the opponents sweep starts once the edits pause
RAIL_WIDTH = 224
SWEEP_WIDTH = 300
CAPTION = "Champions damage · both directions"


class CalcView(ft.Column):
    def __init__(self, ctx: AppContext, store: CalcStore | None = None) -> None:
        super().__init__(spacing=Space.MD, expand=True)
        self.ctx = ctx
        self.store = store or CalcStore(ctx.catalogs, prefs=ctx.prefs)
        self._narrow = False
        self._sweep_running = False
        self._presets_warming = False
        self._rail_key: tuple | None = None
        self._sweep_later: Debouncer | None = None

        self.attacker = PokemonPanel("left", title="Attacker", accent=Accent.CALC, store=self.store, on_pick_move=self._open_move_picker, on_pick_item=self._open_item_picker, on_copy=self._copy)
        self.defender = PokemonPanel("right", title="Defender", accent=Accent.CALC, store=self.store, on_pick_move=self._open_move_picker, on_pick_item=self._open_item_picker, on_copy=self._copy)
        self.field = FieldStrip(store=self.store, on_clear=self._clear_conditions)
        self.rail = CalcRail(store=self.store, accent=Accent.CALC)
        self.rail.width = RAIL_WIDTH
        self.sweep = SweepPanel(store=self.store, accent=Accent.CALC, on_pick=self._pick_opponent)
        self.sweep.width = SWEEP_WIDTH
        self.summary = MatchupBar(store=self.store)

        self._pokemon_row = ft.ResponsiveRow(spacing=Space.MD, run_spacing=Space.MD, vertical_alignment=ft.CrossAxisAlignment.START, controls=[self.attacker, self.defender])
        self._centre = ft.Column(spacing=Space.MD, expand=True, scroll=ft.ScrollMode.AUTO, controls=[self.field, self._pokemon_row])
        self._wide = ft.Row(spacing=Space.MD, vertical_alignment=ft.CrossAxisAlignment.START, controls=[self.rail, self._centre, self.sweep])
        self._stack = ft.Column(spacing=Space.MD, scroll=ft.ScrollMode.AUTO, controls=[])
        self._host = ft.Container(content=self._wide, expand=True)
        self.rail.set_scrolling(True)
        self.sweep.set_scrolling(True)
        self.header = PageHeader(
            "Calc", icon=ft.Icons.CALCULATE, accent=Accent.CALC, caption=CAPTION,
            actions=[
                ft.IconButton(icon=ft.Icons.SWAP_HORIZ, tooltip="Swap attacker and defender (Ctrl+Shift+S)", on_click=lambda _e: self.store.swap_sides()),
                ft.TextButton("Reset", icon=ft.Icons.RESTART_ALT, tooltip="Clear both Pokémon and the field", on_click=lambda _e: self._reset()),
            ],
        )
        self.controls = [self.header, self.summary, self._host]

        self.store.subscribe(self._on_store)
        ctx.bus.on(events.CALC_REQUESTED, self._on_request)
        ctx.bus.on(events.CATALOGS_RELOADED, self._on_catalogs_reloaded)
        ctx.bus.on(events.BOX_CHANGED, lambda _p: self.rail.invalidate_box())
        ctx.bus.on(events.TEAMS_CHANGED, lambda _p: self.rail.refresh_team())
        ctx.bus.on(events.BATTLE_FORMAT_CHANGED, lambda _p: (self.store.invalidate_presets(), self._warm_presets(), self._maybe_sweep()))
        ctx.bus.on(events.META_SYNCED, lambda _p: (self.store.invalidate_presets(), self._warm_presets(), self._maybe_sweep()))

    # -- lifecycle -----------------------------------------------------------------------------

    def did_mount(self) -> None:
        # Only on a live page: the delays need its loop (and tests want edits applied at once).
        page = self.ctx.page
        save_later = Debouncer(page, SAVE_DELAY_MS, lambda _v: self.store.save_state(), quiet_event=False)
        self.store.defer_save = lambda: save_later(None)
        # The delayed save must not be lost when the app closes inside that window.
        self.ctx.on_shutdown(self.store.save_state)
        self._sweep_later = Debouncer(page, SWEEP_DELAY_MS, lambda _v: self._start_sweep(), quiet_event=False)

    def will_unmount(self) -> None:
        self.store.save_state()
        self.store.defer_save = None
        self._sweep_later = None

    def ensure_loaded(self) -> None:
        if not self.store.loaded:
            self.store.load()
        self.rail.refresh()
        self._warm_presets()
        self._maybe_sweep()

    def _warm_presets(self) -> None:
        """Read the tournament builds on a worker while the view is merely open.

        Building them aggregates every roster row four times over, and the paths that
        need them (picking an opponent, choosing a defender) run on the UI loop — so
        without this the first click after a sync froze the calculator.
        """
        if self.store.presets_ready or self._presets_warming:
            return
        self._presets_warming = True

        def finish(_result=None) -> None:
            self._presets_warming = False

        try:
            self.ctx.run_in_background(self.store.preset_builds, on_done=finish, on_error=finish)
        except Exception:  # noqa: BLE001 - no page loop (tests): leave it to the caller
            self._presets_warming = False

    def _on_store(self, event: tuple) -> None:
        if event[0] == "state":
            self.field.update_from()
        elif event[0] == "results":
            self.summary.update_from()
            self.attacker.update_from()
            self.defender.update_from()
            # The rail only marks which team member is loaded; TEAMS_CHANGED covers the rest.
            left = self.store.state.left
            if (left.species, left.source) != self._rail_key:
                self._rail_key = (left.species, left.source)
                self.rail.refresh_team()
            self._sync_species_banner()
            self._maybe_sweep()
        elif event[0] == "sweep":
            self.sweep.render()
            self._maybe_sweep()

    def _sync_species_banner(self) -> None:
        # Cleared as well as set: the catalogue can arrive while this view is open.
        self.header.set_caption(
            CAPTION if self.store.catalogs.has_species
            else "Species data not synced yet — Settings › Moves, learnsets & species"
        )

    def _clear_conditions(self) -> None:
        previous = self.store.clear_conditions()
        self.ctx.toast("Conditions cleared", "info", action="Undo", on_action=lambda: self.store.restore(previous))

    def _reset(self) -> None:
        previous = self.store.reset()
        self.ctx.toast("Calculator reset", "info", action="Undo", on_action=lambda: self.store.restore(previous))

    def _on_catalogs_reloaded(self, kind: str) -> None:
        if kind not in ("items", "megas", "moves", "species", "champions"):
            return
        self.store.refresh_catalogs(self.ctx.catalogs or self.store.catalogs)
        self.rail.refresh()
        self.sweep.render()
        self._sync_species_banner()
        if is_mounted(self):
            self.update()

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

    # -- opponent sweep ------------------------------------------------------------------------

    def _maybe_sweep(self) -> None:
        """Recompute the sweep in the background when the attacker or the field changed,
        once edits pause for ``SWEEP_DELAY_MS`` on a live page."""
        if self._sweep_running or not self.store.sweep_stale():
            return
        if self._sweep_later is not None:
            self._sweep_later(None)
        else:
            self._start_sweep()

    def _start_sweep(self) -> None:
        if self._sweep_running or not self.store.sweep_stale():
            return
        if self.store.species("left") is None or not any(self.store.state.left.moves):
            self.store.publish_sweep(())
            return
        self._sweep_running = True
        self.sweep.set_busy(True)
        key = self.store.sweep_key()

        def prog(entries: tuple[SweepEntry, ...]) -> None:
            if self._sweep_running and self.store.sweep_key() == key:
                self.store.publish_progressive_sweep(entries)

        def done(entries: tuple[SweepEntry, ...]) -> None:
            self._sweep_running = False
            self.sweep.set_busy(False)
            if self.store.sweep_key() == key:
                self.store.publish_sweep(entries)
            else:
                self._maybe_sweep()

        def failed(exc: BaseException) -> None:
            self._sweep_running = False
            self.sweep.set_busy(False)
            self.sweep.render()
            print(f"⚠️ Opponent sweep failed: {exc}")

        try:
            self.ctx.run_in_background(
                lambda: self.store.compute_sweep(on_progressive=lambda e: self.ctx.post(prog, e)),
                on_done=done,
                on_error=failed,
            )
        except Exception:  # noqa: BLE001 - no page loop (tests): compute inline
            done(self.store.compute_sweep())

    def _pick_opponent(self, entry: SweepEntry) -> None:
        preset = self.store.sweep_presets
        if preset and not self.store.presets_ready:
            # Clicked before the warm-up finished: say so in the rail rather than freeze.
            self.sweep.set_busy(True)

            def done(_builds=None) -> None:
                self._presets_warming = False
                self.sweep.set_busy(False)
                self.store.load_species("right", entry.canonical_id, preset=True, source="Opponents")

            self._presets_warming = True
            try:
                self.ctx.run_in_background(self.store.preset_builds, on_done=done, on_error=lambda _e: done())
                return
            except Exception:  # noqa: BLE001 - no page loop (tests): fall through
                self._presets_warming = False
                self.sweep.set_busy(False)
        self.store.load_species("right", entry.canonical_id, preset=preset, source="Opponents")

    # -- layout ------------------------------------------------------------------------------------

    def handle_resize(self, width: float, height: float) -> None:
        narrow = width < Layout.BREAKPOINT_NARROW
        compact = width < Layout.BREAKPOINT_COMPACT
        if narrow != self._narrow:
            self._narrow = narrow
            self._wide.controls = []
            self._stack.controls = []
            self._centre.controls = []
            # Inside the stack's single scroll the side columns must not scroll themselves.
            self.rail.set_scrolling(not narrow)
            self.sweep.set_scrolling(not narrow)
            if narrow:
                self._stack.controls = [self.field, self._pokemon_row, self.rail, self.sweep]
                self._host.content = self._stack
                self.rail.width = None
                self.sweep.width = None
            else:
                self._centre.controls = [self.field, self._pokemon_row]
                self._wide.controls = [self.rail, self._centre, self.sweep]
                self._host.content = self._wide
        if not narrow:
            self.rail.width = 190 if compact else RAIL_WIDTH
            self.sweep.width = 270 if compact else SWEEP_WIDTH
        # Between the side columns a compact window leaves each panel under 300px, which
        # squeezes the HP slider and the ability to nothing: stack them there instead (the
        # summary bar keeps the head-to-head in view).
        panel_col = {"xs": 12} if compact and not narrow else {"xs": 12, "lg": 6}
        self.attacker.col = self.defender.col = panel_col
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
            return self.attacker.collapse_cards() | self.defender.collapse_cards()
        return False

    # -- dialogs -------------------------------------------------------------------------------

    def _open_move_picker(self, side: str, index: int) -> None:
        species = self.store.species(side)
        if species is None:
            self.ctx.toast("Pick a species first", "info")
            return
        page = self.ctx.page
        current = self.store.state.side(side).moves[index]
        target = self.store.species("right" if side == "left" else "left")

        def pick(name: str | None) -> None:
            page.pop_dialog()
            self.store.set_move(side, index, name)

        def set_sort(value: str) -> None:
            self.ctx.prefs.set("calc.move_sort", value)

        dialog = MovePickerDialog(
            species_label=species.name, options=self.store.move_options(side), current=current,
            show_all=bool(self.ctx.prefs.get("team.show_all_moves", False)), on_pick=pick, on_close=page.pop_dialog,
            damage_for=(lambda info: self.store.damage_preview(side, info.name)) if target is not None else None,
            target_label=target.name if target is not None else None,
            sort=str(self.ctx.prefs.get("calc.move_sort", "damage")),
        )
        dialog.on_sort = set_sort
        page.show_dialog(dialog)

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
            self.store.set_item(side, record.display_name if record else None)

        page.show_dialog(ItemPickerDialog(
            catalogs=self.store.catalogs, species_name=species.name.split("-")[0].lower(), current_item_id=current.canonical_id if current else None,
            on_pick=pick, on_close=page.pop_dialog,
        ))

    def _copy(self, text: str) -> None:
        self.ctx.copy_to_clipboard(text)
        self.ctx.toast("Copied", "success")

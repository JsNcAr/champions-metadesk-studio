"""Calc view: the matchup summary under the header, then team/box rail | field strip over the
two Pokémon panels | opponent sweep. On wide windows each of the three columns scrolls on its
own, so the rail and the opponents stay in view; narrow windows stack them in one scroll."""

from __future__ import annotations

from dataclasses import replace

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
from .rival_store import RivalStore, rivals_from_team
from .rivals_panel import RivalsPanel, mode_switch
from .state import CalcRequest, RivalMember, SweepEntry, revealed_fields, rival_set
from .store import CalcStore
from .summary import MatchupBar
from .sweep import SweepPanel

SAVE_DELAY_MS = 500    # a burst of edits (a slider drag) writes preferences.json once
SWEEP_DELAY_MS = 300   # the opponents sweep starts once the edits pause
RAIL_WIDTH = 224
SWEEP_WIDTH = 300
PREF_RIGHT_MODE = "calc.right_mode"   # "all" (every opponent) | "rival" (a rival team)
CAPTION = "Champions damage · both directions"


class CalcView(ft.Column):
    def __init__(self, ctx: AppContext, store: CalcStore | None = None, rivals: RivalStore | None = None) -> None:
        super().__init__(spacing=Space.MD, expand=True)
        self.ctx = ctx
        self.store = store or CalcStore(ctx.catalogs, prefs=ctx.prefs, formats=ctx.formats)
        self.rivals = rivals or RivalStore(self.store.session_factory)
        self._narrow = False
        self._sweep_running = False
        self._presets_warming = False
        self._rail_key: tuple | None = None
        self._sweep_later: Debouncer | None = None
        self._rate_later: Debouncer | None = None
        self._rated_key: str | None = None
        self._rating_running = False
        self._rivals_later: Debouncer | None = None
        self._write_later: Debouncer | None = None
        self._rivals_key: str | None = None
        self._rivals_running = False
        self._right_mode = "rival" if self._pref(PREF_RIGHT_MODE, "all") == "rival" else "all"

        self.attacker = PokemonPanel("left", title="Attacker", accent=Accent.CALC, store=self.store, on_pick_move=self._open_move_picker, on_pick_item=self._open_item_picker, on_copy=self._copy)
        self.defender = PokemonPanel("right", title="Defender", accent=Accent.CALC, store=self.store, on_pick_move=self._open_move_picker, on_pick_item=self._open_item_picker, on_copy=self._copy)
        self.field = FieldStrip(store=self.store, on_clear=self._clear_conditions)
        self.rail = CalcRail(store=self.store, accent=Accent.CALC)
        self.rail.width = RAIL_WIDTH
        self.sweep = SweepPanel(store=self.store, accent=Accent.CALC, on_pick=self._pick_opponent)
        self.sweep.width = SWEEP_WIDTH
        self.rivals_panel = RivalsPanel(rivals=self.rivals, species_name=self._species_name, accent=Accent.CALC,
                                        on_pick=self._pick_rival, on_action=self._rival_action)
        self.rivals_panel.width = SWEEP_WIDTH
        # One switch per panel (a control has one parent); both follow ``_right_mode``.
        self._switches = [mode_switch(self._right_mode, self.set_right_mode), mode_switch(self._right_mode, self.set_right_mode)]
        self.sweep.content.controls.insert(0, self._switches[0])
        self.rivals_panel.set_switch(self._switches[1])
        self.summary = MatchupBar(store=self.store)

        self._pokemon_row = ft.ResponsiveRow(spacing=Space.MD, run_spacing=Space.MD, vertical_alignment=ft.CrossAxisAlignment.START, controls=[self.attacker, self.defender])
        self._centre = ft.Column(spacing=Space.MD, expand=True, scroll=ft.ScrollMode.AUTO, controls=[self.field, self._pokemon_row])
        self._wide = ft.Row(spacing=Space.MD, vertical_alignment=ft.CrossAxisAlignment.START, controls=[self.rail, self._centre, self._right()])
        self._stack = ft.Column(spacing=Space.MD, scroll=ft.ScrollMode.AUTO, controls=[])
        self._host = ft.Container(content=self._wide, expand=True)
        self.rail.set_scrolling(True)
        self.sweep.set_scrolling(True)
        self.rivals_panel.set_scrolling(True)
        self.header = PageHeader(
            "Calc", icon=ft.Icons.CALCULATE, accent=Accent.CALC, caption=CAPTION,
            actions=[
                ft.IconButton(icon=ft.Icons.SWAP_HORIZ, tooltip="Swap attacker and defender (Ctrl+Shift+S)", on_click=lambda _e: self.store.swap_sides()),
                ft.TextButton("Reset", icon=ft.Icons.RESTART_ALT, tooltip="Clear both Pokémon and the field", on_click=lambda _e: self._reset()),
            ],
        )
        self.controls = [self.header, self.summary, self._host]

        self.store.subscribe(self._on_store)
        self.rivals.subscribe(lambda _e: self._on_rivals())
        ctx.bus.on(events.RIVALS_CHANGED, lambda _p: self.rivals.load() if self.rivals.loaded else None)
        ctx.bus.on(events.RIVAL_OPEN, self._open_rival)
        ctx.bus.on(events.FORMAT_CHANGED, lambda _p: (self.attacker.update_from(), self.defender.update_from()))
        ctx.bus.on(events.CALC_REQUESTED, self._on_request)
        ctx.bus.on(events.CATALOGS_RELOADED, self._on_catalogs_reloaded)
        ctx.bus.on(events.BOX_CHANGED, lambda _p: self.rail.invalidate_box())
        ctx.bus.on(events.TEAMS_CHANGED, lambda _p: self._on_teams_changed())
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
        self._rate_later = Debouncer(page, SWEEP_DELAY_MS, lambda _v: self._start_rating(), quiet_event=False)
        self._rivals_later = Debouncer(page, SWEEP_DELAY_MS, lambda _v: self._start_rating_rivals(), quiet_event=False)
        self._write_later = Debouncer(page, SAVE_DELAY_MS, lambda _v: self._write_back(), quiet_event=False)

    def will_unmount(self) -> None:
        self.store.save_state()
        self.store.defer_save = None
        self._sweep_later = None
        self._rate_later = None
        self._rivals_later = None
        if self._write_later is not None:
            self._write_back()      # a battle edit inside the save delay is not lost
        self._write_later = None

    def ensure_loaded(self) -> None:
        if not self.store.loaded:
            self.store.load()
        if not self.rivals.loaded:
            try:
                self.rivals.load()
            except Exception as exc:  # noqa: BLE001 - rival teams must not keep the calculator from opening
                print(f"⚠️ Rival teams could not be read: {exc}")
        self.rail.refresh()
        self._warm_presets()
        self._maybe_sweep()
        self._maybe_rate_team()
        self._maybe_rate_rivals()

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
            self._maybe_rate_team()
            self._on_defender_changed()
            self._maybe_rate_rivals()
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

    def _pref(self, key: str, default):
        try:
            return self.ctx.prefs.get(key, default)
        except Exception:  # noqa: BLE001 - no preferences (tests)
            return default

    def _species_name(self, canonical_id: str | None) -> str:
        species = self.store.catalogs.species_for(canonical_id) if canonical_id else None
        return species.name if species else (canonical_id or "?")

    # -- right column: all opponents | rival team ------------------------------------------------

    def _right(self) -> ft.Control:
        return self.rivals_panel if self._right_mode == "rival" else self.sweep

    def set_right_mode(self, mode: str) -> None:
        mode = "rival" if mode == "rival" else "all"
        for switch in self._switches:
            switch.selected = [mode]
        if mode == self._right_mode:
            return
        old, self._right_mode = self._right(), mode
        new = self._right()
        try:
            self.ctx.prefs.set(PREF_RIGHT_MODE, mode)
        except Exception:  # noqa: BLE001
            pass
        new.width = old.width
        for column in (self._wide, self._stack):
            column.controls = [new if c is old else c for c in column.controls]
        if mode == "rival":
            self.rivals_panel.render()
            self._maybe_rate_rivals()
        else:
            self.sweep.render()
            self._maybe_sweep()
        try:
            if self._host.page is not None:
                self._host.update()
        except RuntimeError:
            pass

    def _open_rival(self, rival_team_id) -> None:
        """Meta's "Open in Calc" after saving a rival team."""
        self.ensure_loaded()
        self.rivals.load()
        self.rivals.set_active(str(rival_team_id) if rival_team_id else None)
        self.set_right_mode("rival")
        self.ctx.bus.emit(events.NAVIGATE, "calc")

    def _on_rivals(self) -> None:
        self._sync_link()
        self.rivals_panel.render()
        self._maybe_rate_rivals()

    def _pick_rival(self, slot: int) -> None:
        team = self.rivals.active
        if team is None or not 0 <= slot < len(team.members):
            return
        self._write_back()      # a pending battle edit belongs to the member loaded before
        label = "Battle" if team.is_battle else team.name
        pokemon = replace(team.members[slot].pokemon, source=f"Rival · {label} · slot {slot + 1}")
        self.store.load_rival(team.rival_team_id, slot, pokemon)

    def _linked_member(self) -> tuple[str, int, RivalMember] | None:
        link = self.store.rival_link
        team = self.rivals.get(link[0]) if link else None
        if link is None or team is None or not 0 <= link[1] < len(team.members):
            return None
        return link[0], link[1], team.members[link[1]]

    def _sync_link(self) -> None:
        linked = self._linked_member()
        active = self.rivals.active
        self.rivals_panel.set_linked(linked[1] if linked and active and linked[0] == active.rival_team_id else None)
        pending = None
        if linked is not None:
            team = self.rivals.get(linked[0])
            if team is not None and not team.is_battle and revealed_fields(linked[2].pokemon, rival_set(self.store.state.right)):
                pending = self._species_name(linked[2].pokemon.species)
        self.rivals_panel.set_pending(pending)

    def _on_defender_changed(self) -> None:
        """A battle member edited in the Defender panel is written back once edits pause; a
        saved team's member only offers "Save Defender to …"."""
        linked = self._linked_member()
        self._sync_link()
        if linked is None:
            return
        team = self.rivals.get(linked[0])
        if team is None or not team.is_battle:
            return
        if self._write_later is not None:
            self._write_later(None)
        else:
            self._write_back()

    def _write_back(self) -> None:
        linked = self._linked_member()
        if linked is None:
            return
        team = self.rivals.get(linked[0])
        if team is not None and team.is_battle:
            self.rivals.sync_member(linked[0], linked[1], self.store.state.right)

    def _rival_action(self, key: str) -> None:
        team = self.rivals.active
        if key == "battle":
            self.open_battle_dialog("preview")
        elif key == "load":
            self.open_battle_dialog("presets" if self.rivals.presets else "teams")
        elif key == "paste":
            self.open_battle_dialog("paste")
        elif key == "matrix":
            self._open_matrix()
        elif key == "update_member":
            linked = self._linked_member()
            if linked is not None:
                self.rivals.sync_member(linked[0], linked[1], self.store.state.right)
                self.ctx.toast(f"{self._species_name(linked[2].pokemon.species)} updated in the rival team", "success")
        elif team is None:
            return
        elif key == "use_preset":
            self._use_preset(team.rival_team_id)
        elif key == "end_battle":
            members = list(team.members)
            self.rivals.end_battle()
            self.ctx.toast("Battle ended", "info", action="Undo", on_action=lambda: self.rivals.start_battle(members, source=team.source))
        elif key == "duplicate":
            copy = self.rivals.duplicate(team.rival_team_id)
            if copy is not None:
                self.ctx.toast(f"Duplicated as “{copy.name}”", "success")
        elif key == "delete":
            members = list(team.members)
            self.rivals.delete(team.rival_team_id)
            self.ctx.toast(f"Deleted “{team.name}”", "info", action="Undo", on_action=lambda: self.rivals.create(team.name, members, source=team.source))
        elif key in ("rename", "save_battle"):
            self.ctx.page.run_task(self._name_team, key, team.rival_team_id)

    async def _name_team(self, key: str, rival_team_id: str) -> None:
        team = self.rivals.get(rival_team_id)
        if team is None:
            return
        if key == "rename":
            name = await self.ctx.prompt_text("Rename preset", "Preset name", value=team.name, submit_label="Rename")
            if name:
                self.rivals.rename(rival_team_id, name)
            return
        name = await self.ctx.prompt_text("Save battle as preset", "Preset name", value="", submit_label="Save")
        if name:
            saved = self.rivals.save_battle_as(name)
            if saved is not None:
                self.ctx.toast(f"Saved preset “{saved.name}”; the battle goes on", "success")

    def open_battle_dialog(self, mode: str = "preview") -> None:
        from .dialogs.battle_preview import BattleDialog

        page = self.ctx.page

        def start(members: list[RivalMember], source: str, name: str | None) -> None:
            page.pop_dialog()
            if name is None:
                self.rivals.start_battle(members, source=source)
                self.ctx.toast(f"Battle started: {len(members)} Pokémon", "success")
            else:
                self.rivals.create(name, members, source=source)
                self.ctx.toast(f"Saved preset “{name}”", "success")
            self.set_right_mode("rival")

        def use(preset_id: str) -> None:
            page.pop_dialog()
            self._use_preset(preset_id)

        self.ensure_loaded()
        team_store = self.store.team_store
        my_teams: list[tuple] = []
        if team_store is not None:
            try:
                if not getattr(team_store, "teams", None):
                    team_store.load()
                my_teams = [(t.team_id, t.name, t.filled) for t in team_store.teams]
            except Exception as exc:  # noqa: BLE001 - the other sources still work
                print(f"⚠️ Teams could not be listed: {exc}")
        catalogs = self.store.catalogs
        page.show_dialog(BattleDialog(
            calc_store=self.store, run_in_background=self.ctx.run_in_background, on_start=start, on_close=page.pop_dialog, mode=mode,
            presets=self.rivals.presets, on_use_preset=use, my_teams=my_teams,
            load_team=(lambda team_id: rivals_from_team(team_store, catalogs, team_id)) if team_store is not None else None,
        ))

    def _use_preset(self, preset_id: str) -> None:
        preset = self.rivals.get(preset_id)
        battle = self.rivals.use_preset(preset_id)
        if preset is not None and battle is not None:
            self.set_right_mode("rival")
            self.ctx.toast(f"Battling “{preset.name}”: the preset stays as saved", "success")

    def _open_matrix(self) -> None:
        from .dialogs.team_matrix import TeamMatrixDialog

        team = self.rivals.active
        if team is None or not team.members:
            return
        members = self.store.team_members()
        if not members:
            self.ctx.toast("Your active team is empty: pick or build one in Teams", "info")
            return
        page = self.ctx.page
        rivals = [m.pokemon for m in team.members]
        team_name = getattr(self.store.team_store, "active_team_name", None) or "Your team"

        def pick(slot_key: str, index: int) -> None:
            page.pop_dialog()
            member = next((p for k, p in members if k == slot_key), None)
            if member is not None:
                self.store.load_pokemon("left", member)
            self._pick_rival(index)

        dialog = TeamMatrixDialog(team_name=team_name, rival_team_name="Current battle" if team.is_battle else team.name,
                                  members=members, rivals=rivals, species_name=self._species_name, on_pick=pick, on_close=page.pop_dialog)
        page.show_dialog(dialog)
        try:
            self.ctx.run_in_background(lambda: self.store.team_matrix(rivals), on_done=dialog.set_grid, on_error=dialog.set_error)
        except Exception:  # noqa: BLE001 - no page loop (tests): compute inline
            dialog.set_grid(self.store.team_matrix(rivals))

    # -- rival cards against the attacker -------------------------------------------------------

    def _rivals_rating_key(self) -> str:
        team = self.rivals.active
        return "|".join((self.store.sweep_key(), str(team.rival_team_id if team else None), str(self.rivals.version)))

    def _maybe_rate_rivals(self) -> None:
        """Rate the rival team against the Attacker once edits pause; only while it is shown."""
        if self._right_mode != "rival" or self._rivals_running:
            return
        key = self._rivals_rating_key()
        if key == self._rivals_key:
            return
        team = self.rivals.active
        if team is None or not team.members or self.store.species("left") is None:
            self._rivals_key = key
            self.rivals_panel.set_ratings((), "")
            return
        if self._rivals_later is not None:
            self._rivals_later(None)
        else:
            self._start_rating_rivals()

    def _start_rating_rivals(self) -> None:
        key = self._rivals_rating_key()
        team = self.rivals.active
        if key == self._rivals_key or self._rivals_running or team is None:
            return
        self._rivals_running = True
        self.rivals_panel.set_busy(True)
        members = [m.pokemon for m in team.members]

        def done(ratings) -> None:
            self._rivals_running = False
            self.rivals_panel.set_busy(False)
            if self._rivals_rating_key() != key:
                self._maybe_rate_rivals()
                return
            self._rivals_key = key
            attacker = self.store.species("left")
            self.rivals_panel.set_ratings(ratings, attacker.name if attacker else "")

        def failed(exc: BaseException) -> None:
            self._rivals_running = False
            self.rivals_panel.set_busy(False)
            print(f"⚠️ Rival rating failed: {exc}")

        try:
            self.ctx.run_in_background(lambda: self.store.rate_rivals(members), on_done=done, on_error=failed)
        except Exception:  # noqa: BLE001 - no page loop (tests): compute inline
            done(self.store.rate_rivals(members))

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

    # -- team ratings ----------------------------------------------------------------------------

    def _on_teams_changed(self) -> None:
        self.store.invalidate_team_ratings()
        self.rail.refresh_team()
        self._maybe_rate_team()

    def _maybe_rate_team(self) -> None:
        """Colour the team rail against the Defender once edits pause, off the UI loop."""
        key = self.store.team_rating_key()
        if key == self._rated_key or self._rating_running:
            return
        if self.store.species("right") is None or not self.store.team_slots():
            self._rated_key = key
            self.rail.apply_ratings({}, "")   # nothing to rate: clear at once, no computing
            return
        if self._rate_later is not None:
            self._rate_later(None)
        else:
            self._start_rating()

    def _start_rating(self) -> None:
        key = self.store.team_rating_key()
        if key == self._rated_key or self._rating_running:
            return
        self._rating_running = True

        def done(ratings) -> None:
            self._rating_running = False
            if self.store.team_rating_key() != key:
                self._maybe_rate_team()   # the rival, field or team moved on meanwhile
                return
            self._rated_key = key
            rival = self.store.species("right")
            self.rail.apply_ratings(ratings, rival.name if rival else "")

        def failed(exc: BaseException) -> None:
            self._rating_running = False
            print(f"⚠️ Team rating failed: {exc}")

        try:
            self.ctx.run_in_background(self.store.rate_team, on_done=done, on_error=failed)
        except Exception:  # noqa: BLE001 - no page loop (tests): compute inline
            done(self.store.rate_team())

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
            self.rivals_panel.set_scrolling(not narrow)
            if narrow:
                self._stack.controls = [self.field, self._pokemon_row, self.rail, self._right()]
                self._host.content = self._stack
                self.rail.width = None
                self.sweep.width = self.rivals_panel.width = None
            else:
                self._centre.controls = [self.field, self._pokemon_row]
                self._wide.controls = [self.rail, self._centre, self._right()]
                self._host.content = self._wide
        if not narrow:
            self.rail.width = 190 if compact else RAIL_WIDTH
            self.sweep.width = self.rivals_panel.width = 270 if compact else SWEEP_WIDTH
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
        if e.ctrl and key == "b":
            self.open_battle_dialog("preview")
            return True
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

        dialog = ItemPickerDialog(
            catalogs=self.store.catalogs, species_name=species.name.split("-")[0].lower(), current_item_id=current.canonical_id if current else None,
            on_pick=pick, on_close=page.pop_dialog, mega=self.store.mega_enabled,
            sort=str(self.ctx.prefs.get("team.item_sort", "popular")), on_sort=lambda v: self.ctx.prefs.set("team.item_sort", v),
        )
        page.show_dialog(dialog)
        # Tournament usage ranks the list; it can take a query the first time, so it arrives later.
        self.ctx.run_in_background(lambda: self.store.item_usage(side), on_done=dialog.set_usage, on_error=lambda _e: None)

    def _copy(self, text: str) -> None:
        self.ctx.copy_to_clipboard(text)
        self.ctx.toast("Copied", "success")

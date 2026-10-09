"""Plans view, serialised headlessly: the team picker and plan list, the editor (difficulty,
Lead/Back, game plan, threat notes), and adding a plan from a paste or a rival preset."""

import sys
from types import SimpleNamespace
import unittest
from dataclasses import replace
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

import flet as ft  # noqa: E402
from _ui_stubs import StubPage, check_layout, serialise  # noqa: E402
from test_plans_store import _draft, _rival  # noqa: E402
from test_ui_calc import CHARIZARD, INCINEROAR, KINGAMBIT, MEGA_Y, MOVES  # noqa: E402
from test_ui_team_store import _TeamStoreCase  # noqa: E402

from pokemon_champions_planning_tool.ui import events  # noqa: E402
from pokemon_champions_planning_tool.ui.context import AppContext  # noqa: E402
from pokemon_champions_planning_tool.ui.help import SHORTCUTS, TIPS  # noqa: E402
from pokemon_champions_planning_tool.ui.views.calc.rival_store import RivalStore  # noqa: E402
from pokemon_champions_planning_tool.ui.views.calc.state import CalcState, FieldState, PokemonState, SideConditions  # noqa: E402
from pokemon_champions_planning_tool.ui.views.plans import MemberRef, PinLink, PinRequest, PlanStore  # noqa: E402
from pokemon_champions_planning_tool.ui.views.plans.dialogs import AddPlanDialog, LeadPairDialog, PasteDialog, PinDialog, PresetPickerDialog  # noqa: E402
from pokemon_champions_planning_tool.ui.components import StatusChip  # noqa: E402
from pokemon_champions_planning_tool.ui.views.plans.view import PREF_TEAM, PlansView  # noqa: E402


class _ViewCase(_TeamStoreCase):
    make_team = True

    def setUp(self):
        super().setUp()
        self.catalogs = replace(self.catalogs, species_by_canonical={s.canonical_id: s for s in (KINGAMBIT, INCINEROAR, CHARIZARD, MEGA_Y)}, moves_by_id=MOVES)
        if self.make_team:
            self.store.create_team("Sun")
            self.store.assign(1, self.charizard)
            self.store.assign(2, self.lucario)
            self.team_id = str(self.store.active_team_id)
        self.plans = PlanStore(self.catalogs, self.db.session, team_store=self.store)
        self.page = StubPage()
        self.ctx = AppContext(self.page)
        self.ctx.catalogs = self.catalogs
        self.ctx.run_in_background = lambda work, on_done=None, on_error=None, **kw: on_done(work()) if on_done else work()
        self.copied = []
        self.ctx.copy_to_clipboard = self.copied.append
        self.view = PlansView(self.ctx, self.plans, self.store, rival_store_factory=lambda: RivalStore(self.db.session))

    def _toast_text(self):
        return self.page.dialogs[-1].content.controls[1].value


class TestEmptyStates(_ViewCase):
    make_team = False

    def test_without_a_team_it_points_to_teams(self):
        self.view.ensure_loaded()
        self.assertFalse(self.view._body.visible)
        self.assertTrue(self.view._empty.visible)
        self.assertIn("No teams yet", serialise_text(self.view._empty))
        self.assertTrue(self.view._copy_all.disabled)
        serialise(self.view)


class TestListAndEditor(_ViewCase):
    def test_a_team_without_plans_invites_one(self):
        self.view.ensure_loaded()
        self.assertEqual(self.view.team_id, self.team_id)
        self.assertEqual(self.view._list.controls, [])
        self.assertIn("No plans for this team yet", serialise_text(self.view._editor_host))
        self.assertTrue(self.view._copy_all.disabled)

    def test_it_lands_on_the_active_team_and_its_first_plan(self):
        a = self.plans.create_from_draft(self.team_id, _draft("Big Six"))
        self.plans.create_from_draft(self.team_id, _draft("Raptor (Sand)"))
        self.view.ensure_loaded()
        self.assertEqual(self.view._team_picker.value, self.team_id)
        self.assertEqual([r.plan.name for r in self.view._list.controls], ["Big Six", "Raptor (Sand)"])
        self.assertEqual(self.view.plan_id, a.plan_id)
        self.assertEqual(self.view.editor._title.value, "Big Six")
        self.assertEqual(len(self.view.editor._opponent.controls), 2)
        self.assertGreater(serialise(self.view), 100)
        check_layout(self.view)

    def test_selecting_a_plan_shows_it_and_is_remembered(self):
        self.plans.create_from_draft(self.team_id, _draft("A"))
        b = self.plans.create_from_draft(self.team_id, _draft("B"))
        self.view.ensure_loaded()
        self.view.select_plan(b.plan_id)
        self.assertEqual(self.view.editor._title.value, "B")
        again = PlansView(self.ctx, self.plans, self.store)
        again.ensure_loaded()
        self.assertEqual(again.plan_id, b.plan_id)

    def test_difficulty_and_picks_are_saved(self):
        plan = self.plans.create_from_draft(self.team_id, _draft())
        self.view.ensure_loaded()
        ed = self.view.editor
        ed._set_difficulty("4")
        self.assertEqual(self.plans.get(plan.plan_id).difficulty_label, "Hard")
        self.assertEqual(self.view.plans[0].difficulty, 4, "the list row follows")
        zard, luca = str(self.charizard), str(self.lucario)
        ed._toggle_pick("lead", zard, "charizard")
        ed._toggle_pick("lead", luca, "lucario")
        self.assertEqual([r.box_entry_id for r in self.plans.get(plan.plan_id).lead], [zard, luca])
        ed._toggle_pick("back", zard, "charizard")
        saved = self.plans.get(plan.plan_id)
        self.assertEqual(([r.box_entry_id for r in saved.lead], [r.box_entry_id for r in saved.back]), ([luca], [zard]))
        ed._toggle_pick("lead", luca, "lucario")
        self.assertEqual(self.plans.get(plan.plan_id).lead, ())
        picked = [c.data for c in ed._back.controls if c.data["picked"]]
        self.assertEqual([d["box_entry_id"] for d in picked], [zard])

    def test_game_plan_and_threat_notes_are_saved(self):
        plan = self.plans.create_from_draft(self.team_id, _draft())
        self.view.ensure_loaded()
        self.view.editor._save_game_plan("Tailwind T1\n  Fake Out the Kingambit")
        self.view.editor._save_note(0, "Low Kick OHKOs it")
        saved = self.plans.get(plan.plan_id)
        self.assertEqual(saved.game_plan, "Tailwind T1\n  Fake Out the Kingambit")
        self.assertEqual(saved.note_for(0), "Low Kick OHKOs it")

    def test_text_still_in_focus_is_saved_when_another_plan_is_opened(self):
        a = self.plans.create_from_draft(self.team_id, _draft("A"))
        b = self.plans.create_from_draft(self.team_id, _draft("B"))
        self.view.ensure_loaded()
        self.view.select_plan(a.plan_id)
        ed = self.view.editor
        ed._game_plan.value = "typed, never blurred"
        ed._note_fields[1].value = "Fake Out first"
        self.view.select_plan(b.plan_id)
        saved = self.plans.get(a.plan_id)
        self.assertEqual((saved.game_plan, saved.note_for(1)), ("typed, never blurred", "Fake Out first"))
        self.assertEqual(ed._game_plan.value, "", "plan B shows its own (empty) game plan")
        self.assertEqual(self.plans.get(b.plan_id).game_plan, "")

    def test_switching_team_shows_its_own_plans(self):
        self.plans.create_from_draft(self.team_id, _draft("Sun's plan"))
        self.store.create_team("Rain")
        rain = str(self.store.active_team_id)
        self.plans.create_from_draft(rain, _draft("Rain's plan"))
        self.view.ensure_loaded()
        self.assertEqual({o.text for o in self.view._team_picker.options}, {"Sun", "Rain"})
        self.view.select_team(rain)
        self.assertEqual([r.plan.name for r in self.view._list.controls], ["Rain's plan"])
        self.assertEqual(self.ctx.prefs.get(PREF_TEAM), rain)

    def test_a_team_edit_redraws_the_picks_next_time_plans_opens(self):
        plan = self.plans.create_from_draft(self.team_id, _draft())
        self.plans.update(plan.plan_id, back=[MemberRef(str(self.lucario), "lucario")])
        self.view.ensure_loaded()
        self.store.load(self.store.active_team_id)
        self.store.clear_slot(2)
        self.assertTrue(self.view._stale)
        self.view.ensure_loaded()
        labels = [c.content.controls[1].value for c in self.view.editor._back.controls]
        self.assertIn("Lucario (not in team)", labels)

    def test_copy_as_markdown(self):
        plan = self.plans.create_from_draft(self.team_id, _draft("Big Six"))
        self.plans.update(plan.plan_id, difficulty=2, game_plan="Tailwind T1")
        self.view.ensure_loaded()
        self.view.copy_plan(self.view.plans[0])
        self.assertTrue(self.copied[-1].startswith("## Big Six\n"))
        self.view.copy_all()
        self.assertTrue(self.copied[-1].startswith("# Sun — matchup plans"))

    def test_rename_duplicate_move_and_delete(self):
        async def yes(*_a, **_k):
            return True

        async def named(*_a, **_k):
            return "Big Six (Chople)"

        self.ctx.confirm, self.ctx.prompt_text = yes, named
        a = self.plans.create_from_draft(self.team_id, _draft("Big Six"))
        self.plans.create_from_draft(self.team_id, _draft("Raptor"))
        self.view.ensure_loaded()
        self.view._rename(self.view.plans[0])
        self.assertEqual(self.plans.get(a.plan_id).name, "Big Six (Chople)")
        self.view._duplicate(self.view.plans[0])
        self.assertEqual([p.name for p in self.view.plans], ["Big Six (Chople)", "Raptor", "Big Six (Chople) (copy)"])
        self.assertEqual(self.view.editor._title.value, "Big Six (Chople) (copy)", "the copy is opened")
        self.view._move(self.view.plans[2], -1)
        self.assertEqual([p.name for p in self.view.plans], ["Big Six (Chople)", "Big Six (Chople) (copy)", "Raptor"])
        self.view._delete(self.view.plans[0])
        self.assertEqual([p.name for p in self.view.plans], ["Big Six (Chople) (copy)", "Raptor"])

    def test_open_an_opposing_set_in_calc(self):
        self.plans.create_from_draft(self.team_id, _draft())
        self.view.ensure_loaded()
        got = []
        self.ctx.bus.on(events.CALC_REQUESTED, got.append)
        self.view.editor.actions.open_in_calc(self.view.plans[0].opponent[0].pokemon)
        self.assertEqual(got[0].defender.species, "kingambit")

    def test_narrow_window(self):
        self.plans.create_from_draft(self.team_id, _draft())
        self.view.ensure_loaded()
        self.view.handle_resize(1100, 800)
        self.assertEqual(self.view._list_panel.width, 240)
        check_layout(self.view)
        serialise(self.view)


class TestMatchupGrid(_ViewCase):
    def setUp(self):
        super().setUp()
        self.plan = self.plans.create_from_draft(self.team_id, _draft())
        self.view.ensure_loaded()
        self.grid = self.view.editor.grid

    def _cells(self):
        out = []

        def walk(c):
            if isinstance(getattr(c, "data", None), dict) and "cell" in c.data:
                out.append(c)
            for attr in ("content", "controls"):
                child = getattr(c, attr, None)
                for x in (child if isinstance(child, list) else [child] if child is not None else []):
                    walk(x)
        walk(self.grid._table)
        return out

    def test_the_grid_rates_your_team_against_theirs(self):
        cells = self._cells()
        # Charizard (in the species catalogue) against Kingambit and Incineroar; Lucario is not.
        self.assertEqual(sorted(c.data["cell"] for c in cells), [(str(self.charizard), 0), (str(self.charizard), 1)])
        self.assertFalse(self.grid._status.visible)
        serialise(self.view)
        check_layout(self.view)

    def test_a_cell_opens_both_in_calc_with_the_plans_field(self):
        self.view._set_field(self.plan.plan_id, FieldState(weather="Sun", left=SideConditions(tailwind=True)))
        got = []
        self.ctx.bus.on(events.CALC_REQUESTED, got.append)
        cell = self._cells()[0]
        cell.on_click(None)
        req = got[0]
        self.assertEqual((req.attacker.species, req.defender.species), ("charizard", "kingambit"))
        self.assertEqual(req.field.weather, "Sun")
        self.assertTrue(req.field.left.tailwind)

    def test_a_field_toggle_is_saved_and_recomputes(self):
        computed = []
        real = self.view.refresh_grid
        self.view.refresh_grid = lambda plan: (computed.append(plan.field), real(plan))
        self.grid._side("right", stealth_rock=True)
        self.assertTrue(self.plans.get(self.plan.plan_id).field.right.stealth_rock)
        self.assertTrue(computed and computed[-1].right.stealth_rock)
        toggle = next(c for c in self.grid._bar.controls if isinstance(getattr(c, "data", None), dict) and c.data.get("toggle") == "Rocks on their side")
        self.assertTrue(toggle.data["on"])
        self.grid._change(game_type="singles", left=SideConditions(helping_hand=True))
        saved = self.plans.get(self.plan.plan_id).field
        self.assertEqual(saved.game_type, "singles")
        self.assertFalse(saved.left.helping_hand, "Doubles-only conditions are dropped in Singles")

    def test_the_grid_follows_the_team(self):
        before = len(self._cells())
        self.store.load(self.store.active_team_id)
        self.store.clear_slot(1)   # Charizard leaves: no row in the catalogue is left
        self.view.ensure_loaded()
        self.assertEqual(len(self._cells()), 0)
        self.assertGreater(before, 0)


class TestPinnedCalcs(_ViewCase):
    def setUp(self):
        super().setUp()
        self.plan = self.plans.create_from_draft(self.team_id, _draft())
        self.view.ensure_loaded()

    def _pin_rows(self):
        return [c for c in self.view.editor._pins.controls if isinstance(getattr(c, "data", None), dict) and "pin" in c.data]

    def _pin_cell(self, box_id, j):
        def walk(c):
            if isinstance(c, ft.GestureDetector) and c.data == {"pin_cell": (box_id, j)}:
                return c
            for attr in ("content", "controls"):
                child = getattr(c, attr, None)
                for x in (child if isinstance(child, list) else [child] if child is not None else []):
                    found = walk(x)
                    if found is not None:
                        return found
            return None
        return walk(self.view.editor.grid._table)

    def test_right_click_on_a_grid_cell_pins_it(self):
        self.assertIn("No pinned calcs yet", serialise_text(self.view.editor._pins))
        self._pin_cell(str(self.charizard), 0).on_secondary_tap(None)
        pins = self.plans.pins(self.plan.plan_id)
        self.assertEqual([(p.label, p.link.box_entry_id, p.link.opp_index) for p in pins], [("Charizard vs Kingambit", str(self.charizard), 0)])
        rows = self._pin_rows()
        self.assertEqual(len(rows), 1)
        text = serialise_text(rows[0])
        self.assertIn("Follows your Charizard", text)
        self.assertIn("Follows their Kingambit", text)
        serialise(self.view)

    def test_open_rename_note_unpin_and_undo(self):
        async def named(*_a, **_k):
            return "Kowtow into Zard"

        self.ctx.prompt_text = named
        self._pin_cell(str(self.charizard), 0).on_secondary_tap(None)
        pin = self.plans.pins(self.plan.plan_id)[0]
        got = []
        self.ctx.bus.on(events.CALC_REQUESTED, got.append)
        self.view.editor.actions.open_pin(self.view.store.pin_views(self.view.plans[0])[0])
        self.assertEqual((got[0].attacker.species, got[0].defender.species), ("charizard", "kingambit"))
        self.view._rename_pin(pin)
        self.view._pin_note(pin, "after Intimidate")
        saved = self.plans.pins(self.plan.plan_id)[0]
        self.assertEqual((saved.label, saved.note), ("Kowtow into Zard", "after Intimidate"))
        toasts = []
        self.ctx.toast = lambda message, kind="info", **kw: toasts.append((message, kw))
        self.view._delete_pin(saved)
        self.assertEqual(self.plans.pins(self.plan.plan_id), [])
        self.assertEqual((toasts[-1][0], toasts[-1][1]["action"]), ("Unpinned", "Undo"))
        toasts[-1][1]["on_action"]()
        restored = self.plans.pins(self.plan.plan_id)
        self.assertEqual([(p.label, p.note, p.link) for p in restored], [("Kowtow into Zard", "after Intimidate", saved.link)])

    def test_a_pin_follows_a_spread_change_in_teams(self):
        state = CalcState(left=PokemonState(species="charizard"), right=PokemonState(species="kingambit", nature="adamant", points={"attack": 32},
                                                                                  moves=["Kowtow Cleave", None, None, None]))
        self.plans.add_pin(self.plan.plan_id, state, label="Kowtow into Zard", mine="left", focus=("right", 0), link=PinLink(str(self.charizard), None))
        self.view.refresh_pins(self.view.plans[0])
        before = serialise_text(self._pin_rows()[0])
        self.store.load(self.store.active_team_id)
        self.store.save_spread(1, nature="bold", points={"hp": 32, "defense": 32})   # Charizard bulks up in Teams
        self.view.ensure_loaded()                                                    # Plans is shown again
        after = serialise_text(self._pin_rows()[0])
        self.assertIn("Kowtow Cleave", after)
        self.assertNotEqual(before, after, "the linked side took the new spread")
        self.assertIn("32 HP / 32+ Def Charizard", after)

    def test_pins_are_in_the_markdown(self):
        self._pin_cell(str(self.charizard), 0).on_secondary_tap(None)
        self.view.copy_plan(self.view.plans[0])
        self.assertIn("### Key calcs", self.copied[-1])
        self.assertIn("*Charizard vs Kingambit:*", self.copied[-1])

    def test_a_calc_from_calc_is_pinned_with_its_links(self):
        state = CalcState(left=PokemonState(species="charizard-mega-y", moves=["Heat Wave", None, None, None]),
                          right=PokemonState(species="kingambit", moves=["Kowtow Cleave", None, None, None]),
                          field=FieldState(weather="Sun"))
        self.ctx.bus.emit(events.PLAN_PIN_REQUESTED, PinRequest(state=state, focus=("left", 0), label="Heat Wave into Gambit"))
        dialog = self.page.dialogs[-1]
        self.assertIsInstance(dialog, PinDialog)
        self.assertEqual((dialog._team.value, dialog._plan.value), (self.team_id, self.plan.plan_id))
        self.assertTrue(dialog._follow_mine.value and dialog._follow_theirs.value, "Mega Charizard Y matches the team's Charizard")
        self.assertIn("Charizard", dialog._follow_mine.label)
        dialog._fire()
        pin = self.plans.pins(self.plan.plan_id)[0]
        self.assertEqual((pin.label, pin.mine, pin.focus), ("Heat Wave into Gambit", "left", ("left", 0)))
        self.assertEqual(pin.link, PinLink(str(self.charizard), 0))
        self.assertEqual(pin.state.field.weather, "Sun")
        self.assertTrue(self._toast_text().startswith("Pinned to"))

    def test_your_side_as_the_defender(self):
        state = CalcState(left=PokemonState(species="kingambit"), right=PokemonState(species="charizard"))
        self.view.request_pin(PinRequest(state=state))
        dialog = self.page.dialogs[-1]
        dialog._mine.selected = ["right"]
        dialog._links(refresh=False)
        dialog._fire()
        pin = self.plans.pins(self.plan.plan_id)[0]
        self.assertEqual((pin.mine, pin.link), ("right", PinLink(str(self.charizard), 0)))
        self.assertEqual(pin.label, "Kingambit vs Charizard")

    def test_pinning_needs_a_plan_and_both_pokemon(self):
        self.view.request_pin(PinRequest(state=CalcState(left=PokemonState(species="kingambit"))))
        self.assertIn("both sides", self._toast_text())
        self.plans.delete(self.plan.plan_id)
        self.view.request_pin(PinRequest(state=CalcState(left=PokemonState(species="kingambit"), right=PokemonState(species="charizard"))))
        self.assertIn("Make a plan first", self._toast_text())


def _find(control, pred):
    """Every control under ``control`` (content/controls/items) matching ``pred``."""
    out = []

    def walk(c):
        if c is None:
            return
        if pred(c):
            out.append(c)
        for attr in ("content", "controls", "items"):
            child = getattr(c, attr, None)
            for x in (child if isinstance(child, list) else [child] if isinstance(child, ft.Control) else []):
                walk(x)
    walk(control)
    return out


def _data(key):
    return lambda c: isinstance(getattr(c, "data", None), dict) and key in c.data


class TestBattleFlow(_ViewCase):
    def setUp(self):
        super().setUp()
        self.store.set_move(1, 0, "Heat Wave")
        self.store.assign(3, self.ghost)
        self.plans.invalidate()
        self.plan = self.plans.create_from_draft(self.team_id, _draft())
        self.plans.update(self.plan.plan_id, lead=[MemberRef(str(self.charizard), "charizard"), MemberRef(str(self.lucario), "lucario")],
                          back=[MemberRef(str(self.ghost), "gengar")])
        self.view.ensure_loaded()
        self.flow = self.view.editor.flow

    def _add(self):
        self.flow.actions.add(False)
        dialog = self.page.dialogs[-1]
        self.assertIsInstance(dialog, LeadPairDialog)
        dialog.toggle(0)
        dialog.toggle(1)
        dialog._ok.on_click(None)
        return self.plans.scenarios(self.plan.plan_id)[-1]

    def _card(self, sc):
        return self.flow.cards[sc.scenario_id]

    def _pick(self, card, key, label):
        menu = _find(card, lambda c: isinstance(c, ft.PopupMenuButton) and getattr(c, "data", None) == {"action": key})[0]
        item = next(i for i in menu.items if isinstance(getattr(i, "content", None), ft.Text) and i.content.value == label)
        item.on_click(None)

    def test_a_scenario_for_their_lead(self):
        sc = self._add()
        self.assertEqual([o.index for o in sc.their_lead], [0, 1])
        card = self._card(sc)
        self.assertTrue(card.opened, "a new scenario opens")
        self.assertIn("If they lead Kingambit + Incineroar", serialise_text(card))
        self.assertIn("Lead Charizard + Lucario · Back Gengar", serialise_text(card))
        self.flow.actions.add(False)
        dialog = self.page.dialogs[-1]
        dialog.toggle(1)
        dialog.toggle(0)
        dialog._ok.on_click(None)
        self.assertIn("already a scenario for that lead", self._toast_text())
        serialise(self.view)
        check_layout(self.view)

    def test_any_other_lead_only_once(self):
        self.flow.actions.add(True)
        self.assertTrue(self.plans.scenarios(self.plan.plan_id)[0].is_fallback)
        self.assertTrue(self.flow._fallback.disabled)
        self.flow.actions.add(True)
        self.assertIn("already a fallback", self._toast_text())

    def test_picking_a_move_saves_it_and_shows_its_damage(self):
        sc = self._add()
        self._pick(self._card(sc), (None, 0, 0), "Heat Wave")
        saved = self.plans.scenarios(self.plan.plan_id)[0]
        action = saved.turns[0].actions[0]
        self.assertEqual((action.kind, action.move, action.target), ("move", "Heat Wave", "foes"))
        hit = _find(self._card(saved), _data("hit"))
        self.assertEqual(len(hit), 1, "the damage line is there")
        self.assertIn("Kingambit", serialise_text(hit[0]))
        self.assertIn("%", serialise_text(hit[0]))

    def test_a_switch_puts_the_back_pokemon_in_next_turn(self):
        sc = self._add()
        self._pick(self._card(sc), (None, 0, 1), "Switch → Gengar")
        from pokemon_champions_planning_tool.ui.views.plans.flow import add_turn

        self._card(sc)._save(add_turn(self._card(sc).sc))
        card = self._card(sc)
        second = _find(card, lambda c: getattr(c, "data", None) == {"picker": (None, 1, 1)})[0]
        self.assertIn("Gengar", serialise_text(second))

    def test_no_mega_toggle_without_a_stone(self):
        sc = self._add()
        self.assertEqual(_find(self._card(sc), _data("mega")), [])

    def test_an_if_block_after_a_turn(self):
        sc = self._add()
        self._card(sc)._add_if(0)
        saved = self.plans.scenarios(self.plan.plan_id)[0]
        self.assertEqual((saved.branches[0].kind, saved.branches[0].ko.box_entry_id), ("ko", str(self.charizard)))
        block = _find(self._card(saved), _data("branch"))[0]
        dropdowns = _find(block, lambda c: isinstance(c, ft.Dropdown))
        self.assertEqual(len(dropdowns), 2, "who is KO'd, and who comes in")
        rep = dropdowns[1]
        rep.value = str(self.ghost)
        rep.on_select(SimpleNamespace(control=rep))
        self.assertEqual(self.plans.scenarios(self.plan.plan_id)[0].branches[0].replacement.box_entry_id, str(self.ghost))
        self.assertIn("If Charizard is KO'd after T1: bring Gengar", self.plans.plan_markdown(self.plan.plan_id))

    def test_a_changed_opponent_is_flagged(self):
        sc = self._add()
        from pokemon_champions_planning_tool.ui.views.calc.rival_store import rivals_from_paste
        members, _ = rivals_from_paste("Charizard\n- Heat Wave\n\nIncineroar\n- Fake Out", self.catalogs, source="Paste")
        self.plans.replace_opponent(self.plan.plan_id, members)
        self.view._reload_plans(keep=self.plan.plan_id)
        chips = [c for c in _find(self._card(sc), lambda c: isinstance(c, StatusChip)) if "to check" in c._label.value]
        self.assertEqual(len(chips), 1)
        self.assertIn("Their slot 1 changed", chips[0].tooltip)

    def test_open_and_pin_a_damage_line(self):
        sc = self._add()
        self._pick(self._card(sc), (None, 0, 0), "Heat Wave")
        saved = self.plans.scenarios(self.plan.plan_id)[0]
        got = []
        self.ctx.bus.on(events.CALC_REQUESTED, got.append)
        _find(self._card(saved), _data("hit"))[0].on_click(None)
        self.assertEqual((got[0].attacker.species, got[0].defender.species), ("charizard", "kingambit"))
        self.assertEqual(got[0].field, self.plans.get(self.plan.plan_id).field)
        self.view._pin_hit(saved, (None, 0, 0), 1)
        pin = self.plans.pins(self.plan.plan_id)[0]
        self.assertEqual((pin.label, pin.focus, pin.link), ("Charizard Heat Wave → Incineroar", ("left", 0), PinLink(str(self.charizard), 1)))

    def test_delete_and_undo(self):
        sc = self._add()
        toasts = []
        self.ctx.toast = lambda message, kind="info", **kw: toasts.append((message, kw))
        self.flow.actions.delete(sc)
        self.assertEqual(self.plans.scenarios(self.plan.plan_id), [])
        toasts[-1][1]["on_action"]()
        self.assertEqual(len(self.plans.scenarios(self.plan.plan_id)), 1)
        self.assertEqual(len(self.flow.cards), 1)

    def test_narrow_window(self):
        sc = self._add()
        self._card(sc)._add_if(0)
        self.view.handle_resize(900, 800)
        check_layout(self.view)
        serialise(self.view)


class TestAddingPlans(_ViewCase):
    PASTE = "Kingambit @ Black Glasses\nAbility: Supreme Overlord\n- Kowtow Cleave\n- Sucker Punch\n\nCharizard @ Charizardite Y\nAbility: Blaze\n- Heat Wave"

    def test_a_paste_becomes_a_plan_with_mega_forms_resolved(self):
        self.view.ensure_loaded()
        self.view.open_paste()
        dialog = self.page.dialogs[-1]
        self.assertIsInstance(dialog, PasteDialog)
        dialog._text.value = self.PASTE
        dialog._fire()
        self.assertNotIn(dialog, self.page.dialogs, "closed once saved")
        plan = self.view.plans[0]
        self.assertEqual(plan.name, "Kingambit + Charizard-Mega-Y", "named after the first three when left blank")
        self.assertEqual([m.pokemon.species for m in plan.opponent], ["kingambit", "charizard-mega-y"])
        self.assertEqual(plan.source, "Paste")
        self.assertEqual(self.view.plan_id, plan.plan_id)

    def test_an_empty_or_unreadable_paste_says_so(self):
        self.view.ensure_loaded()
        self.view.open_paste()
        dialog = self.page.dialogs[-1]
        dialog._fire()
        self.assertTrue(dialog._error.visible)
        dialog._text.value = "Missingno\n- Glitch"
        dialog._fire()
        self.assertIn("No Pokémon", dialog._error.value)
        self.assertEqual(self.view.plans, [])

    def test_edit_as_paste_replaces_their_sets_and_notes_follow_their_pokemon(self):
        plan = self.plans.create_from_draft(self.team_id, _draft())
        self.plans.set_threat_note(plan.plan_id, 0, "first slot note")
        self.plans.set_threat_note(plan.plan_id, 1, "second slot note")
        self.view.ensure_loaded()
        self.view.open_edit_paste(self.view.plans[0])
        dialog = self.page.dialogs[-1]
        self.assertIn("Kingambit @ Black Glasses", dialog._text.value)
        self.assertIn("- Kowtow Cleave", dialog._text.value)
        dialog._text.value = "Incineroar @ Sitrus Berry\nAbility: Intimidate\n- Fake Out"
        dialog._fire()
        saved = self.plans.get(plan.plan_id)
        self.assertEqual([m.pokemon.species for m in saved.opponent], ["incineroar"])
        self.assertEqual(saved.threat_notes, {0: "second slot note"}, "Incineroar's note follows it to the first slot; Kingambit's goes")

    def test_a_rival_preset_becomes_a_plan(self):
        RivalStore(self.db.session).create("Rain (Wolfe)", [_rival("kingambit", "Black Glasses")], source="Meta · Wolfe")
        self.view.ensure_loaded()
        self.view.open_presets()
        dialog = self.page.dialogs[-1]
        self.assertIsInstance(dialog, PresetPickerDialog)
        dialog.content.content.controls[0].on_click(None)
        plan = self.view.plans[0]
        self.assertEqual((plan.name, plan.source), ("Rain (Wolfe)", "Rival preset · Meta · Wolfe"))
        self.assertNotIn(dialog, self.page.dialogs)

    def test_the_rival_picker_without_presets(self):
        self.view.ensure_loaded()
        self.view.open_presets()
        self.assertIn("No rival presets yet", serialise_text(self.page.dialogs[-1]))

    def test_from_meta_goes_to_meta(self):
        navigated = []
        self.ctx.bus.on(events.NAVIGATE, navigated.append)
        self.view.ensure_loaded()
        self.view._add_from_meta()
        self.assertEqual(navigated, ["meta"])


class TestAddFromElsewhere(_ViewCase):
    """Meta and Calc send a draft through the bus; Plans asks which team and saves it."""

    def test_a_draft_from_meta_asks_for_a_team_and_is_saved(self):
        self.store.create_team("Rain")
        rain = str(self.store.active_team_id)
        draft = _draft("Raichu + Staraptor")
        draft = replace(draft, members=(_rival("charizard", "Charizardite Y", "Blaze"),) + draft.members)
        self.ctx.bus.emit(events.PLAN_ADD_REQUESTED, draft)
        dialog = self.page.dialogs[-1]
        self.assertIsInstance(dialog, AddPlanDialog)
        self.assertEqual(dialog._team.value, rain, "the active team by default")
        self.assertEqual(dialog._name.value, "Raichu + Staraptor")
        self.assertIn("Charizard-Mega-Y", serialise_text(dialog) + str([c.tooltip for c in dialog.content.content.controls[1].controls]))
        dialog._team.value = self.team_id
        dialog._name.value = "Sun vs Big Six"
        dialog._fire()
        plans = self.plans.list_plans(self.team_id)
        self.assertEqual([p.name for p in plans], ["Sun vs Big Six"])
        self.assertEqual(plans[0].opponent[0].pokemon.species, "charizard-mega-y")
        self.assertEqual(self._toast_text(), "Added “Sun vs Big Six” to Sun's plans")

    def test_open_from_the_toast_shows_the_plan(self):
        navigated = []
        self.ctx.bus.on(events.NAVIGATE, navigated.append)
        plan = self.plans.create_from_draft(self.team_id, _draft("A"))
        b = self.plans.create_from_draft(self.team_id, _draft("B"))
        self.ctx.bus.emit(events.PLAN_OPEN, (self.team_id, b.plan_id))
        self.assertEqual(navigated, ["plans"])
        self.view.ensure_loaded()   # what showing the view does
        self.assertEqual((self.view.team_id, self.view.plan_id), (self.team_id, b.plan_id))
        self.ctx.bus.emit(events.PLAN_OPEN, (self.team_id, plan.plan_id))
        self.assertEqual(self.view.plan_id, plan.plan_id, "already loaded: switches straight away")

    def test_a_plan_added_elsewhere_shows_up_in_the_list(self):
        self.view.ensure_loaded()
        self.plans.create_from_draft(self.team_id, _draft("From Calc"))
        self.ctx.bus.emit(events.PLANS_CHANGED, self.team_id)
        self.assertEqual([p.name for p in self.view.plans], ["From Calc"])

    def test_without_a_team_it_says_so(self):
        with self.db.session() as s:
            from pokemon_champions_planning_tool.infrastructure.database.repositories import TeamRepository
            TeamRepository(s).delete(self.store.active_team_id)
        self.ctx.bus.emit(events.PLAN_ADD_REQUESTED, _draft())
        self.assertNotIsInstance(self.page.dialogs[-1], AddPlanDialog)
        self.assertIn("Build a team first", self._toast_text())


class TestHelp(unittest.TestCase):
    def test_plans_has_a_shortcut_and_tips(self):
        self.assertIn(("Ctrl+1 / 2 / 3 / 4 / 5", "Box · Teams · Meta · Calc · Plans"), SHORTCUTS)
        self.assertIn("Plans", TIPS)


def serialise_text(control) -> str:
    """Every Text value under a control, joined (for "does it say X" checks)."""
    import flet as ft

    out: list[str] = []

    def walk(c):
        if isinstance(c, ft.Text) and c.value:
            out.append(str(c.value))
        for attr in ("content", "controls", "title", "actions"):
            child = getattr(c, attr, None)
            if isinstance(child, list):
                for x in child:
                    walk(x)
            elif isinstance(child, ft.Control):
                walk(child)
    walk(control)
    return " ".join(out)


if __name__ == "__main__":
    unittest.main()

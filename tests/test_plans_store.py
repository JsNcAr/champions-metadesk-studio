"""Plans: matchup plans and pinned calcs on a temporary database, Mega normalisation, and
the Markdown export."""

import sys
import unittest
from pathlib import Path
from uuid import UUID

sys.path.insert(0, str(Path(__file__).resolve().parent))

from test_ui_calc import CHARIZARD, KINGAMBIT, MEGA_Y  # noqa: E402
from test_ui_team_store import _TeamStoreCase  # noqa: E402

from pokemon_champions_planning_tool.infrastructure.database.models import MatchupPlanRecord, PlanCalcRecord  # noqa: E402
from pokemon_champions_planning_tool.infrastructure.database.repositories import MatchupPlanRepository  # noqa: E402
from pokemon_champions_planning_tool.ui.catalogs import Catalogs  # noqa: E402
from pokemon_champions_planning_tool.ui.views.calc.state import CalcState, FieldState, PokemonState, RivalMember, SideConditions  # noqa: E402
from pokemon_champions_planning_tool.ui.views.plans import MemberRef, PinLink, PlanDraft, PlanStore  # noqa: E402
from pokemon_champions_planning_tool.ui.views.plans.report import PinLine, PlanText, plan_markdown, team_markdown  # noqa: E402
from pokemon_champions_planning_tool.ui.views.plans.store import plan_from_record  # noqa: E402
from sqlmodel import select  # noqa: E402


def _rival(species, item=None, ability=None, moves=("Protect",)):
    return RivalMember(PokemonState(species=species, item=item, ability=ability, moves=list(moves) + [None] * (4 - len(moves))), frozenset({"item"}))


def _draft(name="Big Six", n=2):
    members = (_rival("kingambit", "Black Glasses", "Supreme Overlord", ("Kowtow Cleave", "Sucker Punch")), _rival("incineroar", "Sitrus Berry", "Intimidate"))
    return PlanDraft(name=name, members=members[:n], source="Meta · Top teams")


class _PlansCase(_TeamStoreCase):
    def setUp(self):
        super().setUp()
        self.store.create_team("Sun")
        self.store.assign(1, self.charizard)
        self.store.assign(2, self.lucario)
        self.team_id = str(self.store.active_team_id)
        self.plans = PlanStore(self.catalogs, self.db.session, team_store=self.store)

    def _ref(self, box_id, species=""):
        return MemberRef(str(box_id), species)

    def _count(self, model):
        with self.db.session() as s:
            return len(s.exec(select(model)).all())


class TestPlanStore(_PlansCase):
    def test_a_plan_is_created_from_a_draft_and_listed_in_order(self):
        first = self.plans.create_from_draft(self.team_id, _draft("Big Six"))
        second = self.plans.create_from_draft(self.team_id, _draft("Raptor (Sand)"))
        self.assertEqual([p.name for p in self.plans.list_plans(self.team_id)], ["Big Six", "Raptor (Sand)"])
        self.assertEqual((first.sort_order, second.sort_order), (0, 1))
        self.assertEqual(first.difficulty, 0)
        self.assertEqual(first.source, "Meta · Top teams")
        self.assertEqual(first.field.game_type, "doubles", "from the team's format (Champions)")
        self.assertEqual([m.pokemon.species for m in first.opponent], ["kingambit", "incineroar"])
        self.assertEqual(first.opponent[0].assumed, frozenset({"item"}))

    def test_fields_are_saved_and_read_back(self):
        plan = self.plans.create_from_draft(self.team_id, _draft())
        field = FieldState(weather="Sand", left=SideConditions(tailwind=True), right=SideConditions(stealth_rock=True))
        self.plans.update(plan.plan_id, difficulty=3, game_plan="Tailwind T1\n  Stealth Rock", field=field, name=" Big Six (Chople) ")
        self.plans.set_threat_note(plan.plan_id, 0, "Low Kick OHKOs it")
        again = self.plans.get(plan.plan_id)
        self.assertEqual(again.difficulty_label, "Medium")
        self.assertEqual(again.name, "Big Six (Chople)")
        self.assertEqual(again.game_plan, "Tailwind T1\n  Stealth Rock")
        self.assertTrue(again.field.left.tailwind and again.field.right.stealth_rock)
        self.assertEqual(again.field.weather, "Sand")
        self.assertEqual(again.note_for(0), "Low Kick OHKOs it")
        self.plans.set_threat_note(plan.plan_id, 0, "  ")
        self.assertEqual(self.plans.get(plan.plan_id).threat_notes, {}, "a blank note is removed")
        self.assertEqual(self.plans.update(plan.plan_id, difficulty=9).difficulty, 5, "clamped to Very hard")
        with self.assertRaises(ValueError):
            self.plans.update(plan.plan_id, name="  ")
        with self.assertRaises(ValueError):
            self.plans.update(plan.plan_id, team_id="x")

    def test_lead_and_back_hold_two_each_and_never_the_same_pokemon(self):
        plan = self.plans.create_from_draft(self.team_id, _draft())
        zard, luca = self._ref(self.charizard, "charizard"), self._ref(self.lucario, "lucario")
        plan = self.plans.update(plan.plan_id, lead=[zard, luca, self._ref("x")], back=[])
        self.assertEqual([r.box_entry_id for r in plan.lead], [str(self.charizard), str(self.lucario)])
        plan = self.plans.update(plan.plan_id, back=[luca])
        self.assertEqual([r.box_entry_id for r in plan.lead], [str(self.charizard)], "moved from lead to back")
        self.assertEqual([r.box_entry_id for r in plan.back], [str(self.lucario)])

    def test_picks_follow_the_box_entry_when_the_team_is_reordered(self):
        plan = self.plans.create_from_draft(self.team_id, _draft())
        self.plans.update(plan.plan_id, lead=[self._ref(self.charizard, "charizard")])
        self.store.swap(1, 2)
        self.plans.invalidate(self.team_id)
        ref = self.plans.get(plan.plan_id).lead[0]
        self.assertEqual(self.plans.ref_label(ref, self.team_id), ("Charizard", True))
        self.assertEqual([box for box, _ in self.plans.my_members(self.team_id)], [str(self.lucario), str(self.charizard)])

    def test_a_pick_that_left_the_team_keeps_its_name(self):
        plan = self.plans.create_from_draft(self.team_id, _draft())
        self.plans.update(plan.plan_id, back=[self._ref(self.lucario, "lucario")])
        self.store.clear_slot(2)
        self.plans.invalidate(self.team_id)
        self.assertEqual(self.plans.ref_label(self.plans.get(plan.plan_id).back[0], self.team_id), ("Lucario", False))

    def test_duplicate_move_and_delete_a_plan(self):
        a = self.plans.create_from_draft(self.team_id, _draft("A"))
        b = self.plans.create_from_draft(self.team_id, _draft("B"))
        self.plans.add_pin(a.plan_id, CalcState(), label="pin")
        copy = self.plans.duplicate(a.plan_id, "A (copy)")
        self.assertEqual([p.name for p in self.plans.list_plans(self.team_id)], ["A", "B", "A (copy)"])
        self.assertEqual(len(self.plans.pins(copy.plan_id)), 1, "pins come along")
        self.plans.move(copy.plan_id, -1)
        self.assertEqual([p.name for p in self.plans.list_plans(self.team_id)], ["A", "A (copy)", "B"])
        self.plans.move(a.plan_id, -1)   # already first
        self.assertEqual(self.plans.list_plans(self.team_id)[0].name, "A")
        self.assertTrue(self.plans.delete(a.plan_id))
        self.assertEqual([p.name for p in self.plans.list_plans(self.team_id)], ["A (copy)", "B"])
        self.assertEqual(self._count(PlanCalcRecord), 1, "only the copy's pin is left")
        self.assertFalse(self.plans.delete(a.plan_id))
        self.assertIsNotNone(self.plans.get(b.plan_id))


class TestPinnedCalcs(_PlansCase):
    def test_a_pin_round_trips(self):
        plan = self.plans.create_from_draft(self.team_id, _draft())
        state = CalcState(left=PokemonState(species="charizard", boosts={"special_attack": 1}, hp_pct=50.0), right=PokemonState(species="kingambit"),
                          field=FieldState(left=SideConditions(helping_hand=True)))
        pin = self.plans.add_pin(plan.plan_id, state, label=" Heat Wave into Gambit ", mine="left", focus=("left", 2),
                                 link=PinLink(str(self.charizard), 0), note="after Intimidate")
        self.assertEqual(pin.label, "Heat Wave into Gambit")
        again = self.plans.pins(plan.plan_id)[0]
        self.assertEqual(again.state, state)
        self.assertEqual((again.mine, again.theirs, again.focus), ("left", "right", ("left", 2)))
        self.assertEqual(again.link, PinLink(str(self.charizard), 0))
        updated = self.plans.update_pin(pin.calc_id, label="HW", note="", link=None)
        self.assertEqual((updated.label, updated.note, updated.link), ("HW", "", PinLink()))
        second = self.plans.add_pin(plan.plan_id, CalcState())
        self.assertEqual([p.calc_id for p in self.plans.pins(plan.plan_id)], [pin.calc_id, second.calc_id])
        self.assertTrue(self.plans.delete_pin(pin.calc_id))
        self.assertEqual(len(self.plans.pins(plan.plan_id)), 1)

    def test_a_pin_from_calc_survives_a_plan_save_from_the_editor(self):
        plan = self.plans.create_from_draft(self.team_id, _draft())   # the editor's copy
        self.plans.add_pin(plan.plan_id, CalcState(), label="from Calc")
        self.plans.update(plan.plan_id, game_plan="written meanwhile")
        self.assertEqual([p.label for p in self.plans.pins(plan.plan_id)], ["from Calc"])


class TestBattleFlowStore(_PlansCase):
    def _opp(self, i, species):
        from pokemon_champions_planning_tool.ui.views.plans.flow import OppRef
        return OppRef(i, species)

    def test_scenarios_are_added_saved_reordered_and_deleted(self):
        from pokemon_champions_planning_tool.ui.views.plans.flow import Action, set_action

        plan = self.plans.create_from_draft(self.team_id, _draft())
        a = self.plans.add_scenario(plan.plan_id, (self._opp(0, "kingambit"), self._opp(1, "incineroar")))
        fallback = self.plans.add_scenario(plan.plan_id)
        self.assertEqual(len(a.turns), 1, "starts with an empty T1")
        self.assertTrue(fallback.is_fallback)
        with self.assertRaises(ValueError):
            self.plans.add_scenario(plan.plan_id, (self._opp(1, "incineroar"), self._opp(0, "kingambit")))
        with self.assertRaises(ValueError):
            self.plans.add_scenario(plan.plan_id)
        edited = set_action(a, None, 0, 0, Action("move", "Heat Wave", "foes"))
        self.plans.save_scenario(edited)
        self.assertEqual(self.plans.scenarios(plan.plan_id)[0].turns[0].actions[0].move, "Heat Wave")
        self.plans.move_scenario(fallback.scenario_id, -1)
        self.assertEqual([s.is_fallback for s in self.plans.scenarios(plan.plan_id)], [True, False])
        self.assertTrue(self.plans.delete_scenario(a.scenario_id))
        restored = self.plans.restore_scenario(edited)
        self.assertEqual(restored.turns[0].actions[0].move, "Heat Wave", "undo brings it back")
        self.assertEqual(len(self.plans.scenarios(plan.plan_id)), 2)

    def test_undo_of_a_delete_is_refused_when_that_lead_has_a_new_scenario(self):
        plan = self.plans.create_from_draft(self.team_id, _draft())
        lead = (self._opp(0, "kingambit"), self._opp(1, "incineroar"))
        first = self.plans.add_scenario(plan.plan_id, lead)
        self.plans.delete_scenario(first.scenario_id)
        self.plans.add_scenario(plan.plan_id, lead)
        with self.assertRaises(ValueError):
            self.plans.restore_scenario(first)
        self.assertEqual(len(self.plans.scenarios(plan.plan_id)), 1)

    def test_edit_as_paste_moves_pins_and_the_flow_with_their_pokemon(self):
        from pokemon_champions_planning_tool.ui.views.plans.flow import Action, set_action
        plan = self.plans.create_from_draft(self.team_id, _draft())
        sc = self.plans.add_scenario(plan.plan_id, (self._opp(0, "kingambit"), self._opp(1, "incineroar")))
        self.plans.save_scenario(set_action(sc, None, 0, 0, Action("move", "Heat Wave", "foe", self._opp(1, "incineroar"))))
        pin = self.plans.add_pin(plan.plan_id, CalcState(), link=PinLink(None, 1))
        self.plans.set_threat_note(plan.plan_id, 1, "Fake Out")
        swapped = self.plans.replace_opponent(plan.plan_id, [_rival("incineroar", "Sitrus Berry", "Intimidate"), _rival("garchomp")])
        self.assertEqual(swapped.threat_notes, {0: "Fake Out"})
        self.assertEqual(self.plans.pins(plan.plan_id)[0].link, PinLink(None, 0))
        again = self.plans.scenarios(plan.plan_id)[0]
        self.assertEqual([(o.index, o.species) for o in again.their_lead], [(0, "kingambit"), (0, "incineroar")],
                         "Kingambit left: kept at its slot, and flagged")
        from pokemon_champions_planning_tool.ui.views.plans.flow import validate
        self.assertTrue(any("slot 1 changed" in i.text for i in validate(swapped, again, {})))
        self.assertEqual(again.turns[0].actions[0].foe.index, 0)
        self.assertEqual(pin.calc_id, self.plans.pins(plan.plan_id)[0].calc_id)

    def test_scenarios_go_with_their_plan_and_team(self):
        plan = self.plans.create_from_draft(self.team_id, _draft())
        self.plans.add_scenario(plan.plan_id, (self._opp(0, "kingambit"), self._opp(1, "incineroar")))
        copy = self.plans.duplicate(plan.plan_id)
        self.assertEqual(len(self.plans.scenarios(copy.plan_id)), 1)
        new_team = str(self.store.duplicate_team("Sun (copy)"))
        self.assertEqual(len(self.plans.scenarios(self.plans.list_plans(new_team)[0].plan_id)), 1)
        self.plans.delete(copy.plan_id)
        from pokemon_champions_planning_tool.infrastructure.database.models import PlanScenarioRecord
        self.assertEqual(self._count(PlanScenarioRecord), 3, "the original plan, plus the duplicated team's two plans")
        self.store.load(UUID(new_team))
        self.store.delete_team()
        self.assertEqual(self._count(PlanScenarioRecord), 1)

    def test_the_flow_is_in_the_markdown(self):
        from pokemon_champions_planning_tool.ui.views.plans.flow import Action, set_action

        plan = self.plans.create_from_draft(self.team_id, _draft())
        self.plans.update(plan.plan_id, lead=[self._ref(self.charizard, "charizard"), self._ref(self.lucario, "lucario")])
        sc = self.plans.add_scenario(plan.plan_id, (self._opp(0, "kingambit"), self._opp(1, "incineroar")))
        self.plans.save_scenario(set_action(sc, None, 0, 0, Action("move", "Heat Wave", "foes")))
        md = self.plans.plan_markdown(plan.plan_id)
        self.assertIn("### Battle flow\n\n#### If they lead Kingambit + Incineroar", md)
        self.assertIn("Lead: Charizard + Lucario", md)
        self.assertIn("- T1: Charizard: Heat Wave → both foes", md)


class TestTeamDeleteAndDuplicate(_PlansCase):
    def test_deleting_a_team_deletes_its_plans_and_pins(self):
        plan = self.plans.create_from_draft(self.team_id, _draft())
        self.plans.add_pin(plan.plan_id, CalcState())
        self.store.create_team("Other")
        other = self.plans.create_from_draft(str(self.store.active_team_id), _draft("Kept"))
        self.store.load(UUID(self.team_id))
        self.store.delete_team()
        self.assertEqual(self._count(MatchupPlanRecord), 1)
        self.assertEqual(self._count(PlanCalcRecord), 0)
        self.assertIsNotNone(self.plans.get(other.plan_id))

    def test_duplicating_a_team_copies_its_plans_with_their_picks(self):
        plan = self.plans.create_from_draft(self.team_id, _draft())
        self.plans.update(plan.plan_id, lead=[self._ref(self.charizard, "charizard")], difficulty=4)
        self.plans.add_pin(plan.plan_id, CalcState(), label="k")
        new_id = str(self.store.duplicate_team("Sun (copy)"))
        copies = self.plans.list_plans(new_id)
        self.assertEqual([(p.name, p.difficulty) for p in copies], [("Big Six", 4)])
        self.assertEqual(self.plans.ref_label(copies[0].lead[0], new_id), ("Charizard", True), "same box entries in the copy")
        self.assertEqual([p.label for p in self.plans.pins(copies[0].plan_id)], ["k"])
        self.assertEqual(len(self.plans.list_plans(self.team_id)), 1, "the original keeps its own")


class TestOldOrPartialData(_PlansCase):
    def test_a_partial_record_still_loads(self):
        with self.db.session() as s:
            record = MatchupPlanRepository(s).upsert(MatchupPlanRecord(
                team_id=UUID(self.team_id), name="Old", difficulty=99,
                lead=[{"species": "charizard"}, {"box_entry_id": str(self.charizard)}],
                field={"game_type": "singles", "left": {"tailwind": 1, "warp": True}},
                opponent=[{"pokemon": {"species": "kingambit", "moves": ["Low Kick"]}, "assumed": ["item", "bogus"]}, {}],
                threat_notes={"1": "ok", "x": "bad", "0": ""},
            ))
            plan = plan_from_record(record)
        self.assertEqual(plan.difficulty, 5)
        self.assertEqual([r.box_entry_id for r in plan.lead], [str(self.charizard)], "a pick without a box entry is dropped")
        self.assertEqual(plan.field.game_type, "singles")
        self.assertTrue(plan.field.left.tailwind)
        self.assertEqual(plan.opponent[0].pokemon.moves, ["Low Kick", None, None, None])
        self.assertEqual(plan.opponent[0].assumed, frozenset({"item"}))
        self.assertIsNone(plan.opponent[1].pokemon.species)
        self.assertEqual(plan.threat_notes, {1: "ok"})


class TestMegaNormalisation(unittest.TestCase):
    def setUp(self):
        self.catalogs = Catalogs(species_by_canonical={s.canonical_id: s for s in (CHARIZARD, MEGA_Y, KINGAMBIT)})
        self.plans = PlanStore(self.catalogs, session_factory=None)

    def test_a_held_stone_becomes_the_mega_form(self):
        out = self.plans.normalise_megas([_rival("charizard", "Charizardite Y", "Blaze"), _rival("kingambit", "Black Glasses", "Supreme Overlord")])
        self.assertEqual((out[0].pokemon.species, out[0].pokemon.ability, out[0].pokemon.item), ("charizard-mega-y", "Drought", "Charizardite Y"))
        self.assertEqual(out[0].assumed, frozenset({"item"}), "what was assumed stays assumed")
        self.assertEqual(out[1].pokemon.species, "kingambit")

    def test_without_mega_evolution_the_base_form_is_kept(self):
        out = self.plans.normalise_megas([_rival("charizard", "Charizardite Y", "Blaze")], enabled=False)
        self.assertEqual(out[0].pokemon.species, "charizard")

    def test_without_mega_evolution_a_mega_form_goes_back_to_its_base(self):
        out = self.plans.normalise_megas([_rival("charizard-mega-y", "Charizardite Y", "Drought")], enabled=False)
        self.assertEqual((out[0].pokemon.species, out[0].pokemon.ability), ("charizard", "Blaze"))


class TestMarkdown(unittest.TestCase):
    def _plan(self, **kw):
        from pokemon_champions_planning_tool.ui.views.plans import Plan
        return Plan(plan_id="p", team_id="t", name=kw.pop("name", "Raptor (Sand)"), **kw)

    def test_a_plan_reads_like_a_team_report_entry(self):
        text = PlanText(
            plan=self._plan(difficulty=3, game_plan="• If they lead Tyranitar + Excadrill, Tailwind + Wave Crash T1\n\n  - Excadrill is at Sash after\n- Raichu cleans up"),
            lead=("Basculegion", "Whimsicott"), back=("Kingambit", "Raichu"),
            opponent=("Tyranitar @ Choice Band", "Excadrill"), threats=(("Excadrill", "High Horsepower never OHKOes Kingambit\n(8 HP / 3 Def)"),),
            pins=(PinLine("HHP into Gambit", "252+ Atk Excadrill High Horsepower vs. 8 HP / 3 Def Kingambit: 70–83%", "Sand up"),),
        )
        self.assertEqual(plan_markdown(text), (
            "## Raptor (Sand)\n"
            "\n"
            "**Difficulty:** Medium  \n"
            "**Lead:** Basculegion + Whimsicott  \n"
            "**Back:** Kingambit + Raichu\n"
            "\n"
            "**Their team:** Tyranitar @ Choice Band · Excadrill\n"
            "\n"
            "### Game plan\n"
            "\n"
            "- If they lead Tyranitar + Excadrill, Tailwind + Wave Crash T1\n"
            "  - Excadrill is at Sash after\n"
            "- Raichu cleans up\n"
            "\n"
            "### Threats\n"
            "\n"
            "- **Excadrill:** High Horsepower never OHKOes Kingambit (8 HP / 3 Def)\n"
            "\n"
            "### Key calcs\n"
            "\n"
            "- *HHP into Gambit:* 252+ Atk Excadrill High Horsepower vs. 8 HP / 3 Def Kingambit: 70–83% — Sand up\n"
        ))

    def test_an_empty_plan_is_just_its_heading(self):
        self.assertEqual(plan_markdown(PlanText(self._plan(name="Perish Rain"))), "## Perish Rain\n")

    def test_a_team_document(self):
        self.assertIn("_No plans yet._", team_markdown("Sun", []))
        doc = team_markdown("Sun", [PlanText(self._plan(name="A")), PlanText(self._plan(name="B", difficulty=1))])
        self.assertTrue(doc.startswith("# Sun — matchup plans\n\n## A\n"))
        self.assertIn("## B\n\n**Difficulty:** Very easy\n", doc)


class TestStoreMarkdown(_PlansCase):
    def test_names_are_resolved_from_the_team_and_the_catalogue(self):
        plan = self.plans.create_from_draft(self.team_id, _draft())
        self.plans.update(plan.plan_id, lead=[self._ref(self.charizard, "charizard")], back=[self._ref(self.lucario, "lucario")], difficulty=2,
                          game_plan="Fake Out + Heat Wave")
        self.plans.set_threat_note(plan.plan_id, 1, "Intimidate cycling")
        md = self.plans.plan_markdown(plan.plan_id)
        self.assertIn("**Lead:** Charizard  \n**Back:** Lucario", md)
        self.assertIn("**Their team:** Kingambit @ Black Glasses · Incineroar @ Sitrus Berry", md)
        self.assertIn("- **Incineroar:** Intimidate cycling", md)
        team_doc = self.plans.team_markdown(self.team_id, "Sun")
        self.assertTrue(team_doc.startswith("# Sun — matchup plans"))
        self.assertIn("## Big Six", team_doc)


if __name__ == "__main__":
    unittest.main()

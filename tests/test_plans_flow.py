"""Battle flow, pure: who is on your field turn by turn (switches, an "If…" KO and its
replacement, one Mega per battle), what no longer fits, the editing helpers and the words."""

import unittest

from pokemon_champions_planning_tool.ui.views.calc.state import PokemonState, RivalMember
from pokemon_champions_planning_tool.ui.views.plans.flow import (
    Action,
    Names,
    OppRef,
    Scenario,
    Turn,
    action_label,
    add_branch,
    add_turn,
    board_at,
    brought,
    default_target,
    NO_ACTION,
    foes_at,
    remap_opponents,
    remove_turn,
    scenario_markdown,
    set_action,
    set_branch,
    set_turn,
    validate,
)
from pokemon_champions_planning_tool.ui.views.plans.model import MemberRef, Plan

GARD, KLEAVOR, GAMBIT, GROSS, EXTRA = (MemberRef(b, s) for b, s in (
    ("g", "gardevoir"), ("k", "kleavor"), ("a", "kingambit"), ("m", "metagross"), ("x", "incineroar")))
THEIRS = ("whimsicott", "kleavor", "kingambit", "basculegion", "floette", "garchomp")
PLAN = Plan(plan_id="p", team_id="t", name="Big Six", lead=(GARD, KLEAVOR), back=(GAMBIT, GROSS),
            opponent=tuple(RivalMember(PokemonState(species=s)) for s in THEIRS))
MOVES = {"g": ["Hyper Voice", "Protect", "Moonblast", None], "k": ["Stone Axe", "Close Combat", "Protect", None],
         "a": ["Sucker Punch", "Kowtow Cleave", "Protect", None], "m": ["Meteor Mash", None, None, None], "x": ["Fake Out", None, None, None]}
MINE = {box: PokemonState(moves=moves) for box, moves in MOVES.items()}
NAMES = Names(member=lambda r: r.species.title(), opp=lambda o: THEIRS[o.index].title())


def opp(i):
    return OppRef(i, THEIRS[i])


def move(name, target="foe", foe=None, mega=False):
    return Action("move", name, target, foe, mega)


def switch(ref):
    return Action("switch", switch_to=ref)


def scenario(*turns, **kw):
    return Scenario(scenario_id="s", plan_id="p", their_lead=(opp(0), opp(1)), turns=tuple(turns), **kw)


class TestBoard(unittest.TestCase):
    def test_the_lead_and_back_come_from_the_plan_unless_overridden(self):
        self.assertEqual(brought(PLAN, scenario()), ((GARD, KLEAVOR), (GAMBIT, GROSS)))
        own = scenario(lead=(GAMBIT, KLEAVOR))
        self.assertEqual(brought(PLAN, own), ((GAMBIT, KLEAVOR), (GARD, GROSS)), "the rest of the plan's four")
        self.assertEqual(brought(PLAN, scenario(lead=(GAMBIT, KLEAVOR), back=(GARD, EXTRA)))[1], (GARD, EXTRA))

    def test_a_switch_changes_who_is_on_the_field_next_turn(self):
        sc = scenario(Turn((move("Hyper Voice", "foes", mega=True), switch(GAMBIT))), Turn())
        first, second = board_at(PLAN, sc, 0), board_at(PLAN, sc, 1)
        self.assertEqual((first.left, first.right), (GARD, KLEAVOR))
        self.assertEqual((second.left, second.right), (GARD, GAMBIT))
        self.assertEqual(set(r.box_entry_id for r in second.bench), {"k", "m"})
        self.assertEqual(second.mega_by, "g")

    def test_an_if_ko_brings_the_replacement_into_that_slot(self):
        sc = scenario(Turn((move("Hyper Voice", "foes", mega=True), move("Stone Axe", foe=opp(0)))))
        sc = add_branch(sc, 1, ko=GARD)
        sc = set_branch(sc, 0, replacement=GAMBIT)
        board = board_at(PLAN, sc, 0, branch=0)
        self.assertEqual((board.left, board.right), (GAMBIT, KLEAVOR))
        self.assertEqual(board.fainted, ("g",))
        self.assertEqual(board.mega_by, "g", "the Mega was used before the KO")
        self.assertEqual(sc.turn_number(0, 0), 2, "a branch after T1 starts at T2")

    def test_their_field_carries_over_until_noted_again(self):
        sc = scenario(Turn(), Turn(their_field=(opp(0), opp(3))), Turn())
        self.assertEqual(foes_at(sc, 0), (opp(0), opp(1)))
        self.assertEqual(foes_at(sc, 2), (opp(0), opp(3)))


class TestValidate(unittest.TestCase):
    def texts(self, sc, **kw):
        return [i.text for i in validate(PLAN, sc, MINE, name=lambda r: r.species.title(), **kw)]

    def test_a_clean_scenario_has_no_issues(self):
        sc = scenario(Turn((move("Hyper Voice", "foes", mega=True), move("Stone Axe", foe=opp(0)))),
                      Turn((move("Protect", ""), switch(GAMBIT))))
        self.assertEqual(self.texts(sc), [])

    def test_impossible_actions_are_flagged(self):
        sc = scenario(
            Turn((move("Flamethrower", foe=opp(0)), switch(GAMBIT))),
            Turn((switch(GAMBIT), move("Sucker Punch", foe=opp(1), mega=True))),
        )
        texts = self.texts(sc, can_mega=lambda box: box == "g")
        self.assertIn("Gardevoir doesn't know Flamethrower", texts)
        self.assertIn("Can't switch to Kingambit: not in the back", texts)
        self.assertIn("Kingambit can't Mega Evolve (no Mega Stone)", texts)

    def test_one_mega_per_battle(self):
        sc = scenario(Turn((move("Hyper Voice", "foes", mega=True), Action())), Turn((move("Protect", "", mega=True), Action())))
        self.assertIn("Gardevoir has already Mega Evolved", self.texts(sc))
        sc2 = scenario(Turn((move("Hyper Voice", "foes", mega=True), Action())), Turn((Action(), move("Stone Axe", foe=opp(0), mega=True))))
        self.assertIn("Only one Mega Evolution per battle", self.texts(sc2))

    def test_stale_team_members_and_their_slots(self):
        gone = {k: v for k, v in MINE.items() if k != "a"}
        sc = scenario(Turn((move("Stone Axe", foe=OppRef(2, "tyranitar")), Action())))
        texts = [i.text for i in validate(PLAN, sc, gone, name=lambda r: r.species.title())]
        self.assertIn("Kingambit is no longer in the team", texts)
        self.assertIn("Their slot 3 changed (was Tyranitar)", texts)
        self.assertIn("Gardevoir doesn't know Stone Axe", texts)

    def test_an_if_whose_pokemon_is_not_on_the_field(self):
        sc = add_branch(scenario(Turn()), 1, ko=GAMBIT)
        self.assertIn("Kingambit isn't on the field after T1", self.texts(sc))


class TestEditing(unittest.TestCase):
    def test_turns_are_added_and_removed_and_ifs_follow(self):
        sc = scenario(Turn(), Turn(), Turn())
        sc = add_branch(sc, 3, ko=GARD)
        sc = remove_turn(sc, None, 2)
        self.assertEqual(len(sc.turns), 2)
        self.assertEqual(sc.branches[0].after_turn, 2, "moved to the last turn left")
        sc = add_turn(sc, 0)
        self.assertEqual(len(sc.branches[0].turns), 2)

    def test_picking_mega_on_one_slot_clears_it_on_the_other(self):
        sc = scenario(Turn((move("Hyper Voice", "foes", mega=True), Action())))
        sc = set_action(sc, None, 0, 1, move("Stone Axe", foe=opp(0), mega=True))
        left, right = sc.turns[0].actions
        self.assertFalse(left.mega)
        self.assertTrue(right.mega)

    def test_notes_and_their_field(self):
        sc = set_turn(scenario(Turn()), None, 0, note="watch Sucker Punch", their_field=(opp(4), opp(5)))
        self.assertEqual((sc.turns[0].note, sc.turns[0].their_field), ("watch Sucker Punch", (opp(4), opp(5))))

    def test_default_targets(self):
        self.assertEqual([default_target(t) for t in ("normal", "allAdjacentFoes", "allAdjacent", "adjacentAlly", "self", "allySide", None)],
                         ["foe", "foes", "foes", "ally", "", "", "foe"])


class TestRoundTrip(unittest.TestCase):
    def test_a_scenario_survives_json_and_old_data_loads(self):
        sc = add_branch(scenario(Turn((move("Hyper Voice", "foes", mega=True), switch(GAMBIT)), note="n")), 1, kind="other", text="they Tailwind")
        sc = Scenario.from_body(sc.body(), scenario_id="s", plan_id="p")
        self.assertEqual(sc.turns[0].actions[1].switch_to, GAMBIT)
        self.assertEqual(sc.branches[0].text, "they Tailwind")
        odd = Scenario.from_body({"their_lead": [{"index": "x"}, {"index": 2}], "rating": "great", "turns": [{"actions": [{"kind": "fly"}]}],
                                  "branches": [{"after_turn": "?"}]})
        self.assertEqual(odd.their_lead, (OppRef(2, ""),))
        self.assertEqual(odd.rating, "")
        self.assertTrue(odd.turns[0].actions[0].empty and odd.turns[0].actions[1].empty)
        self.assertEqual(odd.branches[0].after_turn, 1)
        self.assertEqual(Scenario.from_body(None), Scenario())


class TestWords(unittest.TestCase):
    def test_action_labels(self):
        self.assertEqual(action_label(move("Hyper Voice", "foes", mega=True), NAMES), "Mega Evolve, Hyper Voice → both foes")
        self.assertEqual(action_label(move("Stone Axe", foe=opp(0)), NAMES), "Stone Axe → Whimsicott")
        self.assertEqual(action_label(switch(GAMBIT), NAMES), "Switch → Kingambit")
        self.assertEqual(action_label(Action(), NAMES), "—")

    def test_a_scenario_reads_like_a_report(self):
        sc = scenario(Turn((move("Hyper Voice", "foes", mega=True), move("Stone Axe", foe=opp(0)))),
                      Turn((move("Protect", ""), switch(GAMBIT)), note="Tailwind is up"), rating="favourable")
        sc = set_branch(add_branch(sc, 1, ko=GARD), 0, replacement=GROSS)
        lines = scenario_markdown(PLAN, sc, NAMES, hits={(None, 0, 1): "92–109% · 50% chance to OHKO"})
        self.assertEqual(lines, [
            "### If they lead Whimsicott + Kleavor (Favourable)",
            "",
            "Lead: Gardevoir + Kleavor · Back: Kingambit + Metagross",
            "",
            "- T1: Gardevoir: Mega Evolve, Hyper Voice → both foes · Kleavor: Stone Axe → Whimsicott (92–109% · 50% chance to OHKO)",
            "- If Gardevoir is KO'd after T1: bring Metagross",
            "  - T2: —",
            "- T2: Gardevoir: Protect · Kleavor: Switch → Kingambit — Tailwind is up",
        ])
        fallback = scenario_markdown(PLAN, Scenario(), NAMES)
        self.assertEqual(fallback[0], "### Any other lead")


if __name__ == "__main__":
    unittest.main()


class TestReviewFixes(unittest.TestCase):
    def test_removing_an_earlier_turn_keeps_the_if_after_the_same_turn(self):
        sc = scenario(Turn(), Turn(), Turn(), Turn())
        sc = add_branch(sc, 3, ko=GARD)
        self.assertEqual(remove_turn(sc, None, 0).branches[0].after_turn, 2, "after the old T3, now T2")
        self.assertEqual(remove_turn(sc, None, 2).branches[0].after_turn, 2, "its own turn gone: after the turn before")
        self.assertEqual(remove_turn(sc, None, 3).branches[0].after_turn, 3, "a later turn gone: unchanged")

    def test_odd_json_shapes_load_as_empty(self):
        for body in ({"turns": 5}, {"their_lead": True}, {"turns": [{"actions": 3}]}, {"lead": ["x"]},
                     {"turns": [{"actions": [{"kind": "switch", "switch_to": "abc"}]}]},
                     {"branches": [{"after_turn": float("inf")}]}, {"their_lead": [{"index": float("inf")}]}):
            Scenario.from_body(body)   # never raises

    def test_a_mega_without_its_stone_does_not_use_up_the_mega(self):
        sc = scenario(Turn(actions=(move("Hyper Voice", "foes", mega=False), move("Stone Axe", foe=opp(0), mega=True))),
                      Turn(actions=(move("Hyper Voice", "foes", mega=True), NO_ACTION)))
        stone = {"g"}.__contains__
        texts = [i.text for i in validate(PLAN, sc, MINE, can_mega=stone)]
        self.assertIn("kleavor can't Mega Evolve (no Mega Stone)", texts)
        self.assertNotIn("Only one Mega Evolution per battle", texts)
        self.assertEqual(board_at(PLAN, sc, 2, can_mega=stone).mega_by, "g")

    def test_two_switches_to_the_same_member_are_flagged_and_only_one_happens(self):
        sc = scenario(Turn(actions=(switch(GAMBIT), switch(GAMBIT))), Turn())
        self.assertTrue(any("already coming in" in i.text for i in validate(PLAN, sc, MINE)))
        board = board_at(PLAN, sc, 1)
        self.assertEqual((board.left, board.right), (GAMBIT, KLEAVOR))

    def test_the_member_switched_out_cannot_come_back_in_the_same_turn(self):
        sc = scenario(Turn(actions=(switch(GAMBIT), switch(GARD))), Turn())
        board = board_at(PLAN, sc, 1)
        self.assertEqual((board.left, board.right), (GAMBIT, KLEAVOR))
        self.assertTrue(any("not in the back" in i.text for i in validate(PLAN, sc, MINE)))

    def test_a_mega_on_a_switch_and_a_ko_branch_without_its_member_are_flagged(self):
        sc = scenario(Turn(actions=(Action("switch", switch_to=GAMBIT, mega=True), NO_ACTION)))
        sc = add_branch(sc, 1)
        sc = set_branch(sc, 0, ko=None)
        texts = [i.text for i in validate(PLAN, sc, MINE)]
        self.assertIn("Mega Evolution needs an attack, not a switch", texts)
        self.assertIn("Pick which of yours is KO'd", texts)

    def test_remap_follows_their_pokemon_to_new_slots(self):
        sc = scenario(Turn(actions=(move("Stone Axe", foe=opp(2)), NO_ACTION), their_field=(opp(2), opp(1))))
        moved = {0: 1, 1: 0, 2: 2}
        new_opp = tuple(PLAN.opponent[i] for i in (1, 0, 2, 3, 4, 5))
        out = remap_opponents(sc, moved, new_opp)
        self.assertEqual([o.index for o in out.their_lead], [1, 0])
        self.assertEqual([o.index for o in out.turns[0].their_field], [2, 0])
        self.assertEqual(out.turns[0].actions[0].foe.index, 2)

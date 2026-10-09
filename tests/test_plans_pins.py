"""Pinned calcs: linked sides take the current sets and keep the situation as pinned, the
line a pin shows (its focused move, or the best hit each way), and links that no longer
resolve."""

import sys
import unittest
from dataclasses import replace
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from test_plans_grid import gambit, roar, zard  # noqa: E402
from test_ui_calc import catalogs  # noqa: E402

from pokemon_champions_planning_tool.ui.views.calc.state import CalcState, FieldState, SideConditions  # noqa: E402
from pokemon_champions_planning_tool.ui.views.plans.model import PinLink, PinnedCalc  # noqa: E402
from pokemon_champions_planning_tool.ui.views.plans.pins import lines_for, resolve, view_pin  # noqa: E402
from pokemon_champions_planning_tool.ui.views.calc.store import run  # noqa: E402


def pin(state, **kw):
    return PinnedCalc(calc_id="c", plan_id="p", state=state, **kw)


class TestResolve(unittest.TestCase):
    def setUp(self):
        self.situation = gambit(boosts={"attack": 1}, hp_pct=50.0, status="brn")
        self.situation.crit[0] = True
        self.state = CalcState(left=self.situation, right=roar(), field=FieldState(right=SideConditions(stealth_rock=True)))

    def test_a_linked_side_takes_the_current_set_and_keeps_the_situation(self):
        current = replace(gambit(), item="Black Glasses", nature="jolly", moves=["Iron Head", "Kowtow Cleave", None, None])
        state, yours, theirs, broken = resolve(pin(self.state, link=PinLink("a", None)), {"a": current}, [])
        left = state.left
        self.assertEqual((left.item, left.nature, left.moves[:2]), ("Black Glasses", "jolly", ["Iron Head", "Kowtow Cleave"]))
        self.assertEqual((left.boosts, left.hp_pct, left.status, left.crit[0]), ({"attack": 1}, 50.0, "brn", True), "the situation stays")
        self.assertTrue(state.field.right.stealth_rock)
        self.assertEqual((yours, theirs, broken), (True, False, ()))
        self.assertEqual(state.right, self.state.right, "an unlinked side stays as pinned")

    def test_their_side_follows_the_plans_opponent(self):
        new_roar = replace(roar(), item="Sitrus Berry")
        state, _yours, theirs, _broken = resolve(pin(self.state, link=PinLink(None, 1)), {}, [zard(), new_roar])
        self.assertTrue(theirs)
        self.assertEqual(state.right.item, "Sitrus Berry")

    def test_your_side_can_be_the_defender(self):
        state = CalcState(left=roar(), right=self.situation)
        current = replace(gambit(), item="Chople Berry")
        out, yours, _theirs, _broken = resolve(pin(state, mine="right", link=PinLink("a", 0)), {"a": current}, [replace(roar(), item="Choice Band")])
        self.assertTrue(yours)
        self.assertEqual((out.right.item, out.left.item), ("Chople Berry", "Choice Band"))

    def test_a_link_that_no_longer_resolves_keeps_the_pinned_set(self):
        state, yours, theirs, broken = resolve(pin(self.state, link=PinLink("gone", 5)), {}, [zard()])
        self.assertEqual(state, self.state)
        self.assertEqual((yours, theirs, broken), (False, False, ("team member", "opponent")))


class TestLines(unittest.TestCase):
    def setUp(self):
        self.catalogs = catalogs()
        self.state = CalcState(left=gambit(), right=roar())

    def test_a_focused_pin_shows_that_move_with_its_ko_text(self):
        results = run(self.state, self.catalogs)
        lines = lines_for(results, pin(self.state, focus=("left", 1)))
        self.assertEqual(len(lines), 1)
        self.assertIn("Iron Head", lines[0])
        self.assertIn("Incineroar", lines[0])
        self.assertRegex(lines[0], r"HKO|KO")

    def test_without_focus_it_is_the_best_hit_each_way(self):
        lines = lines_for(run(self.state, self.catalogs), pin(self.state))
        self.assertEqual(len(lines), 2)
        self.assertIn("Kingambit", lines[0].split(" vs")[0])
        self.assertIn("Flare Blitz", lines[1])
        mine_right = lines_for(run(self.state, self.catalogs), pin(self.state, mine="right"))
        self.assertEqual(mine_right, (lines[1], lines[0]), "your hit first")

    def test_a_reordered_linked_set_keeps_the_focused_move(self):
        p = pin(self.state, focus=("left", 1), link=PinLink("a", None))      # pinned on Iron Head (slot 2)
        reordered = replace(gambit(), moves=["Iron Head", "Kowtow Cleave", None, None])
        view = view_pin(p, {"a": reordered}, [], self.catalogs)
        self.assertIn("Iron Head", view.lines[0])
        self.assertEqual((view.your_name, view.their_name), ("Kingambit", "Incineroar"))
        self.assertTrue(view.linked_yours)


if __name__ == "__main__":
    unittest.main()

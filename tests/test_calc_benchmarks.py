"""Calc: spread moves on one or two targets in Doubles, and the bulk / power benchmarks."""

import shutil
import sys
import tempfile
import unittest
from dataclasses import replace
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from _ui_stubs import StubPage, serialise  # noqa: E402
from test_ui_calc import catalogs  # noqa: E402

from pokemon_champions_planning_tool.domain.stat_calc import champions_stats  # noqa: E402
from pokemon_champions_planning_tool.ui.context import AppContext  # noqa: E402
from pokemon_champions_planning_tool.ui.preferences import Preferences  # noqa: E402
from pokemon_champions_planning_tool.ui.views.calc import CalcState, CalcStore, CalcView, PokemonState  # noqa: E402
from pokemon_champions_planning_tool.ui.views.calc.benchmarks import benchmarks, ko_text, survive_text  # noqa: E402
from pokemon_champions_planning_tool.ui.views.calc.state import FieldState, SideConditions  # noqa: E402
from pokemon_champions_planning_tool.ui.views.calc.store import engine_field, run_side  # noqa: E402


class _Base(unittest.TestCase):
    def setUp(self):
        self.dir = tempfile.mkdtemp()
        self.addCleanup(shutil.rmtree, self.dir)
        self.catalogs = catalogs()
        self.store = CalcStore(self.catalogs, session_factory=None, prefs=Preferences(Path(self.dir) / "prefs.json"))
        self.store.load()


class TestSpreadTargets(_Base):
    def load(self, game_type="doubles"):
        self.store.set_field(game_type=game_type)
        self.store.load_pokemon("left", PokemonState(species="charizard-mega-y", ability="Drought", nature="modest", points={"special_attack": 32},
                                                     moves=["Heat Wave", None, None, None]))
        self.store.load_pokemon("right", PokemonState(species="kingambit", ability="Defiant", moves=["Iron Head", None, None, None]))
        self.store.set_field(weather="none")

    def test_doubles_spread_is_two_targets_and_one_target_is_full_damage(self):
        self.load()
        two = self.store.results.left_vs_right[0]
        self.assertEqual(two.targets, 2)
        self.store.toggle_single_target("left", 0)
        one = self.store.results.left_vs_right[0]
        self.assertEqual(one.targets, 1)
        self.assertGreater(one.max_dmg, two.max_dmg)
        self.assertAlmostEqual(two.max_dmg / one.max_dmg, 0.75, delta=0.02)
        self.assertIsNone(self.store.results.right_vs_left[0].targets, "Iron Head is single-target")

    def test_singles_and_the_sweep_ignore_the_flag(self):
        self.load("singles")
        self.assertIsNone(self.store.results.left_vs_right[0].targets)
        self.store.set_field(game_type="doubles")
        key = self.store.sweep_key()
        self.store.toggle_single_target("left", 0)
        self.assertEqual(self.store.sweep_key(), key, "the opponents list always assumes both foes")
        state = self.store.state
        fast = run_side(state.left, state.right, engine_field(state.field, attacker_is_left=True), self.catalogs, fast=True)
        self.assertEqual(fast[0].targets, 2)

    def test_state_round_trips_and_a_new_move_resets_it(self):
        self.load()
        self.store.toggle_single_target("left", 0)
        restored = CalcState.from_dict(self.store.state.to_dict())
        self.assertEqual(restored.left.single, [True, False, False, False])
        self.assertEqual(CalcState.from_dict({"left": {"species": "kingambit"}}).left.single, [False] * 4, "old saved states load")
        self.store.set_move("left", 0, "Heat Wave")
        self.assertFalse(self.store.state.left.single[0])


class TestBenchmarks(_Base):
    def state(self, **field) -> CalcState:
        attacker = PokemonState(species="kingambit", ability="Defiant", nature="adamant", points={"attack": 10}, moves=["Kowtow Cleave", "Iron Head", "Protect", None])
        defender = PokemonState(species="charizard-mega-y", ability="Drought", nature="modest", points={"speed": 20}, moves=["Heat Wave", None, None, None])
        return CalcState(left=attacker, right=defender, field=FieldState(**field))

    def damage(self, state: CalcState, index: int = 0):
        return run_side(state.left, state.right, engine_field(state.field, attacker_is_left=True), self.catalogs, fast=True)[index]

    def hp(self, p: PokemonState) -> int:
        return champions_stats(self.catalogs.species_for(p.species).stats, p.points, p.nature).hp

    def test_ko_points_are_the_fewest_that_work(self):
        state = self.state()
        state = replace(state, right=replace(state.right, points={"hp": 20, "defense": 12}))
        result = benchmarks(state, "left", 0, self.catalogs)
        self.assertEqual(result.move, "Kowtow Cleave")
        self.assertEqual([b.hits for b in result.ko], [1, 2])
        target = self.hp(state.right)
        checked = 0
        for b in result.ko:
            self.assertEqual((b.stat, b.current), ("attack", 10))
            if not b.points:
                continue
            with_it = replace(state, left=replace(state.left, points={"attack": b.points}))
            self.assertGreaterEqual(self.damage(with_it).min_dmg * b.hits, target)
            fewer = replace(state, left=replace(state.left, points={"attack": b.points - 1}))
            self.assertLess(self.damage(fewer).min_dmg * b.hits, target)
            checked += 1
        self.assertTrue(checked)

    def test_survival_spread_survives_and_one_point_less_does_not(self):
        state = self.state()
        result = benchmarks(state, "left", 0, self.catalogs)
        checked = 0
        for b in result.survive:
            self.assertEqual((b.stat, b.current_hp), ("defense", 0))
            if b.hp is None or (b.hp == 0 and b.defence == 0):
                continue
            self.assertLessEqual(b.hp + b.defence + 20, 66, "the Speed points still count")
            points = {k: v for k, v in {**state.right.points, "hp": b.hp, "defense": b.defence}.items() if v}
            survives = replace(state, right=replace(state.right, points=points))
            self.assertLess(self.damage(survives).max_dmg * b.hits, self.hp(survives.right))
            if b.defence:
                less = replace(survives, right=replace(survives.right, points={**points, "defense": b.defence - 1}))
                self.assertGreaterEqual(self.damage(less).max_dmg * b.hits, self.hp(less.right))
            checked += 1
        self.assertTrue(checked, "at least one survival benchmark needs points")

    def test_screens_and_texts(self):
        plain = benchmarks(self.state(), "left", 0, self.catalogs)
        screened = benchmarks(self.state(right=SideConditions(reflect=True)), "left", 0, self.catalogs)
        self.assertTrue(all((s.points or 99) >= (p.points or 99) for s, p in zip(screened.ko, plain.ko)), "Reflect never lowers what a KO takes")
        self.assertIsNone(benchmarks(self.state(), "left", 2, self.catalogs), "status moves have none")
        self.assertIsNone(benchmarks(self.state(), "left", 3, self.catalogs), "empty slot")
        self.assertTrue(ko_text(plain.ko[0]).startswith(("OHKO", "can't OHKO")))
        self.assertTrue(survive_text(plain.survive[0]).startswith(("survive", "can't")))


class TestInTheView(_Base):
    def setUp(self):
        super().setUp()
        self.page = StubPage()
        self.ctx = AppContext(self.page)
        self.ctx.prefs = self.store._prefs
        self.ctx.catalogs = self.catalogs
        self.view = CalcView(self.ctx, self.store)
        self.view.ensure_loaded()
        self.store.load_pokemon("left", PokemonState(species="charizard-mega-y", ability="Drought", nature="modest", moves=["Heat Wave", None, None, None]))
        self.store.load_pokemon("right", PokemonState(species="kingambit", ability="Defiant", nature="adamant", points={"hp": 4}, moves=["Kowtow Cleave", None, None, None]))

    def test_the_spread_chip_switches_targets(self):
        card = self.view.attacker.cards[0]
        self.assertTrue(card._targets.visible)
        self.assertEqual(card._targets_label.value, "×0.75")
        self.assertIn("both foes", card._targets.tooltip)
        card._targets.on_click(None)
        self.assertTrue(self.store.state.left.single[0])
        self.assertEqual(card._targets_label.value, "×1")
        self.assertIn("single target", card._targets.tooltip)
        self.assertFalse(self.view.defender.cards[0]._targets.visible, "single-target moves have no chip")
        self.view.field.pick("game_type", "singles")
        self.assertFalse(card._targets.visible, "Singles has no spread")
        serialise(self.view)

    def test_an_expanded_card_shows_benchmarks_and_apply_can_be_undone(self):
        card = self.view.defender.cards[0]
        card.toggle()
        self.assertEqual(card._bench_state, "ready")
        self.assertIsNotNone(card.benchmarks)
        texts = [c.controls[0].value for c in card._details.controls[-2].controls[1:]]
        self.assertEqual(len(texts), 4, "OHKO, 2HKO, survives 1 hit, survives 2 hits")
        self.assertTrue(texts[0].startswith("Kingambit: "), "the attacker's lines name it")
        self.assertTrue(texts[2].startswith("Charizard-Mega-Y: "), "the target's lines name it")
        serialise(self.view)
        before = self.store.state
        self.view._apply_points("left", {"hp": 20, "special_defense": 12})
        self.assertEqual(self.store.state.left.points, {"hp": 20, "special_defense": 12})
        self.assertEqual(self.store.state.right, before.right)
        self.assertNotEqual(card.bench_key, None)
        self.assertEqual(card.bench_key, self.store.benchmark_key("right", 0), "the open card asked again for the new spread")
        snack = self.page.dialogs[-1]
        self.assertEqual(snack.action, "Undo")
        snack.on_action(None)
        self.assertEqual(self.store.state, before)


class TestDamageLine(unittest.TestCase):
    def test_ranges_fit_the_card(self):
        from pokemon_champions_planning_tool.ui.views.calc.damage_line import damage_line, pct_range
        from pokemon_champions_planning_tool.ui.views.calc.state import MoveResult

        def hit(lo, hi, ko_hits=None):
            return MoveResult(0, "Iron Head", "Steel", "Physical", 1, 2, lo, hi, (), "", "", ko_hits=ko_hits)

        self.assertEqual(pct_range(hit(57.6, 68.3)), "58–68%")
        self.assertEqual(pct_range(hit(90.2, 107.4)), "90%+", "a KO on the high rolls")
        self.assertEqual(pct_range(hit(116.0, 139.5)), "OHKO", "every roll KOs")
        line = damage_line("you", hit(57.6, 68.3, ko_hits=2), "no damage")
        self.assertIn("57.6–68.3%", line.tooltip, "the exact range is one hover away")
        self.assertIn("2HKO", line.tooltip)
        self.assertIn("moves unknown", damage_line("them", None, "moves unknown").controls[1].value)

    def test_dealt_and_taken_read_apart(self):
        from pokemon_champions_planning_tool.ui.theme import Palette
        from pokemon_champions_planning_tool.ui.views.calc.damage_line import HUES, damage_line, hit_colour, strength
        from pokemon_champions_planning_tool.ui.views.calc.state import MoveResult

        self.assertEqual((HUES["you"], HUES["them"]), (Palette.HIT_DEALT, Palette.HIT_TAKEN))
        self.assertNotEqual(hit_colour("you", 60), hit_colour("them", 60), "same damage, different colour by direction")
        self.assertLess(strength(10), strength(40))
        self.assertLess(strength(40), strength(80))
        self.assertLess(strength(80), strength(120), "a KO is the brightest")
        hit = MoveResult(0, "Iron Head", "Steel", "Physical", 1, 2, 56.0, 67.0, (), "", "")
        mine, theirs = damage_line("you", hit, ""), damage_line("them", hit, "")
        self.assertEqual((mine.controls[0].color, theirs.controls[0].color), (Palette.HIT_DEALT, Palette.HIT_TAKEN), "the arrows carry the colour too")


class TestTeamStripSizes(unittest.TestCase):
    def test_all_six_fit_down_to_the_smallest_tier(self):
        from pokemon_champions_planning_tool.ui.views.calc.team_strip import TIERS, fit_tier, rival_width, team_width

        self.assertEqual(fit_tier(2000), TIERS[0], "room to spare: the full picker and sprites")
        for width in range(360, 700, 10):
            picker, sprite = fit_tier(width)
            if (picker, sprite) != TIERS[-1]:
                self.assertLessEqual(max(team_width(picker, sprite), rival_width(picker, sprite)), width)
        sizes = [fit_tier(w) for w in (700, 500, 450, 420)]
        self.assertEqual(sizes, sorted(sizes, reverse=True), "narrower never means bigger")


if __name__ == "__main__":
    unittest.main()

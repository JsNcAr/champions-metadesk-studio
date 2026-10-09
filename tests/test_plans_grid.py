"""A plan's matchup grid: every pairing in fast mode, KO text on the best hits, the cache, and
the field (Tailwind, Trick Room) reaching the result; Calc opening a pairing with the field."""

import sys
import unittest
from dataclasses import replace
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parent))

from test_ui_calc import catalogs  # noqa: E402

from pokemon_champions_planning_tool.ui.views.calc import CalcRequest, CalcStore  # noqa: E402
from pokemon_champions_planning_tool.ui.views.calc.state import FieldState, PokemonState, SideConditions  # noqa: E402
from pokemon_champions_planning_tool.ui.views.calc.store import matchup  # noqa: E402
from pokemon_champions_planning_tool.ui.views.plans import grid as grid_mod  # noqa: E402
from pokemon_champions_planning_tool.ui.views.plans.grid import compute_grid, with_ko_text  # noqa: E402

PTS = {"hp": 32, "attack": 32, "speed": 2}


def gambit(**kw):
    return PokemonState(species="kingambit", nature="adamant", points=dict(PTS), ability="Supreme Overlord",
                        moves=["Kowtow Cleave", "Iron Head", None, None], **kw)


def roar(**kw):
    return PokemonState(species="incineroar", nature="adamant", points=dict(PTS), ability="Blaze", moves=["Flare Blitz", None, None, None], **kw)


def zard(**kw):
    return PokemonState(species="charizard-mega-y", nature="modest", points={"special_attack": 32, "speed": 32}, ability="Drought",
                        item="Charizardite Y", moves=["Heat Wave", None, None, None], **kw)


class TestGrid(unittest.TestCase):
    def setUp(self):
        self.catalogs = catalogs()
        self.mine = [("a", gambit()), ("b", roar())]
        self.opp = [zard(), gambit(), PokemonState(species="missingno")]

    def test_every_pairing_is_rated_like_calc_does(self):
        field = FieldState()
        grid = compute_grid(self.mine, self.opp, field, self.catalogs)
        self.assertEqual(sorted(grid), [("a", 0), ("a", 1), ("b", 0), ("b", 1)], "the unknown species is left out")
        yours, theirs, _ys, _rs, faster, klass = matchup(gambit(), self.catalogs.species_for("kingambit"), zard(),
                                                          self.catalogs.species_for("charizard-mega-y"), field, self.catalogs)
        cell = grid[("a", 0)]
        self.assertEqual((cell.klass, cell.faster), (klass, faster))
        self.assertEqual((cell.your_best.name, cell.your_best.max_pct), (yours.name, yours.max_pct))
        self.assertEqual(cell.their_best.name, theirs.name)
        self.assertEqual(cell.slot_key, "a")
        self.assertEqual(cell.name, "Charizard-Mega-Y")

    def test_ko_text_is_added_to_the_best_hits_only(self):
        field = FieldState()
        fast = compute_grid(self.mine, self.opp, field, self.catalogs)
        self.assertEqual(fast[("a", 1)].your_best.ko_text, "", "fast mode writes no KO text")
        full = with_ko_text(fast, self.mine, self.opp, field, self.catalogs)
        best = full[("a", 1)].your_best
        self.assertEqual(best.name, fast[("a", 1)].your_best.name)
        self.assertTrue(best.ko_text, "full mode on the best move")
        self.assertIn("Kingambit", best.description)
        self.assertEqual((best.min_pct, best.max_pct), (fast[("a", 1)].your_best.min_pct, fast[("a", 1)].your_best.max_pct))

    def test_unchanged_pairings_come_from_the_cache(self):
        cache: dict = {}
        field = FieldState()
        calls = []
        real = grid_mod.matchup

        def counting(*a, **k):
            calls.append(1)
            return real(*a, **k)

        with patch.object(grid_mod, "matchup", counting):
            compute_grid(self.mine, self.opp, field, self.catalogs, cache=cache)
            first = len(calls)
            compute_grid(self.mine, self.opp, field, self.catalogs, cache=cache)
            self.assertEqual(len(calls), first, "nothing recalculated")
            changed = [("a", replace(gambit(), nature="jolly")), ("b", roar())]
            compute_grid(changed, self.opp, field, self.catalogs, cache=cache)
            self.assertEqual(len(calls), first + 2, "only the changed row")
            compute_grid(self.mine, self.opp, replace(field, weather="Sun"), self.catalogs, cache=cache)
            self.assertEqual(len(calls), first + 2 + 4, "a field change reruns every pairing")

    def test_tailwind_and_trick_room_change_who_moves_first(self):
        mine, opp = [("a", gambit())], [zard()]
        base = compute_grid(mine, opp, FieldState(), self.catalogs)[("a", 0)]
        self.assertFalse(base.faster, "Mega Charizard Y outspeeds a 2-Speed Kingambit")
        tailwind = compute_grid(mine, opp, FieldState(left=SideConditions(tailwind=True)), self.catalogs)[("a", 0)]
        self.assertEqual(tailwind.your_speed, base.your_speed * 2)
        trick_room = compute_grid(mine, opp, FieldState(trick_room=True), self.catalogs)[("a", 0)]
        self.assertTrue(trick_room.faster, "the slower Pokémon moves first under Trick Room")


class TestCalcOpensWithTheField(unittest.TestCase):
    def test_a_request_with_a_field_sets_it(self):
        store = CalcStore(catalogs(), session_factory=None)
        field = FieldState(weather="Sand", trick_room=True, left=SideConditions(tailwind=True), right=SideConditions(stealth_rock=True))
        store.apply_request(CalcRequest(attacker=gambit(), defender=roar(), field=field))
        self.assertEqual(store.state.field.weather, "Sand")
        self.assertTrue(store.state.field.trick_room and store.state.field.left.tailwind and store.state.field.right.stealth_rock)
        self.assertEqual((store.state.left.species, store.state.right.species), ("kingambit", "incineroar"))
        field.left.tailwind = False
        self.assertTrue(store.state.field.left.tailwind, "Calc keeps its own copy")

    def test_a_request_without_a_field_keeps_calcs(self):
        store = CalcStore(catalogs(), session_factory=None)
        store.set_field(weather="Rain")
        store.apply_request(CalcRequest(defender=roar()))
        self.assertEqual(store.state.field.weather, "Rain")


if __name__ == "__main__":
    unittest.main()

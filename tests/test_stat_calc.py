"""Stat formula against well-known level-50 values, natures, and spread validation."""

import unittest

from pokemon_champions_planning_tool.domain.entities.pokemon_stats import PokemonStats
from pokemon_champions_planning_tool.domain.stat_calc import (
    NATURES,
    NEUTRAL_NATURES,
    calc_all,
    calc_hp,
    calc_stat,
    nature_label,
    nature_multiplier,
    validate_spread,
)

GARCHOMP = PokemonStats(hp=108, attack=130, defense=95, sp_atk=80, sp_def=85, speed=102)


class TestFormula(unittest.TestCase):
    def test_garchomp_level_50_reference_values(self):
        # 252 Atk / 252 Spe, Jolly, 31 IVs — the most common competitive spread.
        stats = calc_all(GARCHOMP, evs={"attack": 252, "speed": 252, "hp": 4}, nature="Jolly")
        self.assertEqual(stats.attack, 182)
        self.assertEqual(stats.speed, 169)
        self.assertEqual(stats.hp, 184)
        self.assertEqual(stats.special_attack, 90, "hindered stat: floor((85+5)·0.9)=90")
        adamant = calc_all(GARCHOMP, evs={"attack": 252}, nature="Adamant")
        self.assertEqual(adamant.attack, 200)

    def test_hp_with_full_investment(self):
        self.assertEqual(calc_hp(108, ev=252), 215)
        self.assertEqual(calc_hp(1, ev=252), 1, "Shedinja")

    def test_sparse_spread_defaults(self):
        stats = calc_all(GARCHOMP)
        self.assertEqual(stats.attack, calc_stat(130))
        self.assertEqual(stats.hp, calc_hp(108))
        zero_iv = calc_all(GARCHOMP, ivs={"speed": 0})
        self.assertEqual(zero_iv.speed, calc_stat(102, iv=0))

    def test_level_scales(self):
        self.assertEqual(calc_stat(130, ev=252, level=100), 359)
        self.assertEqual(calc_hp(108, ev=252, level=100), 420)


class TestNatures(unittest.TestCase):
    def test_table_shape(self):
        self.assertEqual(len(NATURES), 25)
        self.assertEqual(len(NEUTRAL_NATURES), 5)
        for name, (up, down) in NATURES.items():
            self.assertEqual(up is None, down is None, name)
            self.assertNotEqual(up, "hp", "no nature touches HP")

    def test_multipliers(self):
        self.assertEqual(nature_multiplier("timid", "speed"), 1.1)
        self.assertEqual(nature_multiplier("Timid", "attack"), 0.9)
        self.assertEqual(nature_multiplier("timid", "defense"), 1.0)
        self.assertEqual(nature_multiplier("serious", "speed"), 1.0)
        self.assertEqual(nature_multiplier(None, "speed"), 1.0)
        with self.assertRaises(ValueError):
            nature_multiplier("timmid", "speed")

    def test_labels(self):
        self.assertEqual(nature_label("timid"), "Timid (+Spe −Atk)")
        self.assertEqual(nature_label("hardy"), "Hardy (neutral)")


class TestValidateSpread(unittest.TestCase):
    def test_legal_spreads_pass(self):
        self.assertEqual(validate_spread({"attack": 252, "speed": 252, "hp": 4}, {}), [])
        self.assertEqual(validate_spread({}, {}), [])
        self.assertEqual(validate_spread(None, None), [])

    def test_problems_are_reported(self):
        problems = validate_spread({"attack": 256, "speed": 252, "hp": 4}, {"speed": 32})
        self.assertTrue(any("attack EVs" in p for p in problems))
        self.assertTrue(any("exceeds 510" in p for p in problems))
        self.assertTrue(any("speed IVs" in p for p in problems))
        self.assertTrue(validate_spread({"attack": 252, "speed": 252, "hp": 8}, {}))
        self.assertTrue(validate_spread({"atk": 10}, {}))
        self.assertTrue(validate_spread({}, {}, level=0))


if __name__ == "__main__":
    unittest.main()

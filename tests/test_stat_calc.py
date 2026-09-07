"""Stat formula against well-known level-50 values, natures, and spread validation."""

import unittest

from pokemon_champions_planning_tool.domain.entities.pokemon_stats import PokemonStats
from pokemon_champions_planning_tool.domain.stat_calc import (
    NATURES,
    NEUTRAL_NATURES,
    calc_all,
    calc_hp,
    calc_stat,
    champions_stat,
    champions_stats,
    format_points,
    nature_label,
    nature_multiplier,
    points_from_evs,
    points_left,
    validate_points,
    default_points_for_nature,
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


class TestChampionsPoints(unittest.TestCase):
    def test_garchomp_reference_values(self):
        # The classic 252 Atk / 252 Spe / 4 HP Jolly spread is 32 / 32 / 1 in points.
        stats = champions_stats(GARCHOMP, {"attack": 32, "speed": 32, "hp": 1}, "Jolly")
        self.assertEqual((stats.hp, stats.attack, stats.speed, stats.special_attack), (184, 182, 169, 90))
        self.assertEqual(champions_stats(GARCHOMP, {"attack": 32}, "Adamant").attack, 200)
        self.assertEqual(champions_stat(1, 32, hp=True), 1, "Shedinja")
        self.assertEqual(champions_stat(108, 0, hp=True), 183)
        self.assertEqual(champions_stat(130, 0), 150)

    def test_calculator_reference_sets(self):
        # Values produced by the Smogon calculator's Champions module.
        mega_y = PokemonStats(hp=78, attack=104, defense=78, sp_atk=159, sp_def=115, speed=100)
        s = champions_stats(mega_y, {"hp": 2, "special_attack": 32, "speed": 32}, "Timid")
        self.assertEqual((s.hp, s.attack, s.defense, s.special_attack, s.special_defense, s.speed), (155, 111, 98, 211, 135, 167))
        g = champions_stats(GARCHOMP, {"hp": 32, "attack": 32, "speed": 2}, "Jolly")
        self.assertEqual((g.hp, g.attack, g.defense, g.special_attack, g.special_defense, g.speed), (215, 182, 115, 90, 105, 136))

    def test_points_from_evs_preserves_every_legacy_stat(self):
        self.assertEqual(points_from_evs({"attack": 252, "speed": 252, "hp": 4}), {"attack": 32, "speed": 32, "hp": 1})
        self.assertEqual(points_from_evs({"hp": 0, "atk": 10}), {})
        self.assertEqual(points_from_evs({"attack": 999}), {"attack": 32})
        for base in (1, 45, 80, 108, 130, 255):
            for ev in range(0, 253, 4):
                p = points_from_evs({"hp": ev})["hp"] if ev else 0
                self.assertEqual(champions_stat(base, p, hp=True), calc_hp(base, ev=ev), (base, ev))
                for mult in (1.0, 1.1, 0.9):
                    self.assertEqual(champions_stat(base, p, mult), calc_stat(base, ev=ev, nature_mult=mult), (base, ev, mult))

    def test_validation_and_budget(self):
        self.assertEqual(validate_points({"attack": 32, "speed": 32, "hp": 2}), [])
        self.assertEqual(validate_points(None), [])
        self.assertTrue(any("Atk points" in p for p in validate_points({"attack": 33})))
        self.assertTrue(any("exceeds 66" in p for p in validate_points({"attack": 32, "speed": 32, "hp": 3})))
        self.assertTrue(validate_points({"atk": 1}))
        self.assertEqual(points_left({"attack": 32, "speed": 32}), 2)
        self.assertEqual(points_left({}), 66)

    def test_format(self):
        self.assertEqual(format_points({"speed": 32, "attack": 32, "hp": 2}), "2 HP / 32 Atk / 32 Spe")
        self.assertEqual(format_points({"hp": 0}), "")
        self.assertEqual(format_points(None), "")


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
class TestDefaultPointsForNature(unittest.TestCase):
    def test_speed_boosting_natures(self):
        timid = default_points_for_nature("timid")
        self.assertEqual(timid, {"special_attack": 32, "speed": 32, "hp": 2})
        self.assertEqual(validate_points(timid), [])

        jolly = default_points_for_nature("jolly")
        self.assertEqual(jolly, {"attack": 32, "speed": 32, "hp": 2})
        self.assertEqual(validate_points(jolly), [])

    def test_offensive_boosting_natures(self):
        fast = PokemonStats(hp=80, attack=100, defense=80, sp_atk=100, sp_def=80, speed=100)
        adamant_fast = default_points_for_nature("adamant", fast)
        self.assertEqual(adamant_fast, {"attack": 32, "speed": 32, "hp": 2})

        slow = PokemonStats(hp=100, attack=120, defense=100, sp_atk=50, sp_def=80, speed=50)
        adamant_slow = default_points_for_nature("adamant", slow)
        self.assertEqual(adamant_slow, {"hp": 32, "attack": 32, "special_defense": 2})

    def test_trick_room_and_defensive(self):
        quiet = default_points_for_nature("quiet")
        self.assertEqual(quiet, {"hp": 32, "special_attack": 32, "special_defense": 2})
        self.assertEqual(validate_points(quiet), [])

        brave = default_points_for_nature("brave")
        self.assertEqual(brave, {"hp": 32, "attack": 32, "special_defense": 2})

        impish = default_points_for_nature("impish")
        self.assertEqual(impish, {"hp": 32, "defense": 32, "special_defense": 2})

        calm = default_points_for_nature("calm")
        self.assertEqual(calm, {"hp": 32, "special_defense": 32, "defense": 2})

    def test_neutral_and_fallback(self):
        hardy = default_points_for_nature("hardy")
        self.assertEqual(hardy, {"hp": 32, "defense": 17, "special_defense": 17})
        self.assertEqual(validate_points(hardy), [])

        none = default_points_for_nature(None)
        self.assertEqual(none, {"hp": 32, "defense": 17, "special_defense": 17})


if __name__ == "__main__":
    unittest.main()

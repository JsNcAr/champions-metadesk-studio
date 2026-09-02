"""Type chart correctness: known matchups, dual-type stacking, immunities, summaries."""

import unittest

from pokemon_champions_planning_tool.domain.type_chart import (
    BUCKETS,
    TYPES,
    bucket_profile,
    defensive_multiplier,
    defensive_profile,
    effectiveness,
    team_defensive_matrix,
    team_weakness_summary,
)


class TestSingleMatchups(unittest.TestCase):
    def test_known_matchups(self):
        cases = [
            ("ground", "electric", 2.0),
            ("electric", "ground", 0.0),
            ("ghost", "normal", 0.0),
            ("normal", "ghost", 0.0),
            ("fire", "water", 0.5),
            ("water", "fire", 2.0),
            ("poison", "steel", 0.0),
            ("dragon", "fairy", 0.0),
            ("fairy", "dragon", 2.0),
            ("psychic", "dark", 0.0),
            ("ghost", "steel", 1.0),   # Gen VI: Steel no longer resists Ghost
            ("dark", "steel", 1.0),    # ...or Dark
            ("fire", "fire", 0.5),
            ("ice", "dragon", 2.0),
        ]
        for atk, dfn, expected in cases:
            self.assertEqual(effectiveness(atk, dfn), expected, f"{atk} → {dfn}")

    def test_every_type_has_a_complete_row_and_column(self):
        self.assertEqual(len(TYPES), 18)
        for atk in TYPES:
            profile = {dfn: effectiveness(atk, dfn) for dfn in TYPES}
            self.assertEqual(len(profile), 18)
            self.assertTrue(set(profile.values()) <= {0.0, 0.5, 1.0, 2.0}, atk)

    def test_unknown_types_are_neutral_and_case_insensitive(self):
        self.assertEqual(effectiveness("stellar", "fire"), 1.0)
        self.assertEqual(effectiveness("Fire", " GRASS "), 2.0)


class TestDualTypes(unittest.TestCase):
    def test_stacking(self):
        self.assertEqual(defensive_multiplier("water", ["rock", "ground"]), 4.0)
        self.assertEqual(defensive_multiplier("ice", ["dragon", "flying"]), 4.0)
        self.assertEqual(defensive_multiplier("fire", ["water", "dragon"]), 0.25)
        self.assertEqual(defensive_multiplier("ground", ["electric", "flying"]), 0.0, "immunity wins")
        self.assertEqual(defensive_multiplier("fighting", ["normal", "ghost"]), 0.0)
        self.assertEqual(defensive_multiplier("grass", ["water", "fire"]), 1.0, "2× and ½× cancel")

    def test_duplicate_and_blank_types_are_ignored(self):
        self.assertEqual(defensive_multiplier("water", ["fire", "fire"]), 2.0)
        self.assertEqual(defensive_multiplier("water", ["fire", "", None]), 2.0)  # type: ignore[list-item]
        self.assertEqual(defensive_multiplier("water", []), 1.0)


class TestProfiles(unittest.TestCase):
    def test_charizard_profile_buckets(self):
        buckets = bucket_profile(defensive_profile(["fire", "flying"]))
        self.assertEqual(buckets[4.0], ["rock"])
        self.assertEqual(buckets[2.0], ["water", "electric"])
        self.assertEqual(buckets[0.0], ["ground"])
        self.assertEqual(buckets[0.25], ["grass", "bug"], "both Fire and Flying resist these")
        self.assertEqual(set(buckets[0.5]), {"fire", "fighting", "steel", "fairy"}, "Steel vs Flying is neutral")
        self.assertEqual(list(buckets), list(BUCKETS), "bucket keys keep display order")

    def test_team_weakness_summary_counts(self):
        team = [["fire", "flying"], ["grass"], ["ground"], [], ["electric", "flying"]]
        summary = team_weakness_summary(team)
        self.assertEqual(summary["rock"], (2, 1, 0), "Charizard 4× and Zapdos 2× weak; Ground resists; Grass neutral")
        self.assertEqual(summary["ground"], (0, 1, 2), "Charizard and Zapdos immune, Grass resists")
        self.assertEqual(summary["ice"], (3, 0, 0))

    def test_team_defensive_matrix_keeps_member_order(self):
        matrix = team_defensive_matrix([["fire"], [], ["water"]])
        self.assertEqual(matrix["water"], [2.0, 1.0, 0.5])
        self.assertEqual(len(matrix), 18)




class TestOffensiveCoverage(unittest.TestCase):
    def test_best_multiplier_matrix_and_uncovered(self):
        from pokemon_champions_planning_tool.domain.type_chart import (
            best_offensive_multiplier,
            team_offensive_matrix,
            team_offensive_summary,
            uncovered_types,
        )

        self.assertEqual(best_offensive_multiplier(["fire", "flying"], "grass"), 2.0)
        self.assertEqual(best_offensive_multiplier(["fire"], "water"), 0.5)
        self.assertEqual(best_offensive_multiplier(["normal"], "ghost"), 0.0)
        self.assertIsNone(best_offensive_multiplier([], "grass"))
        matrix = team_offensive_matrix([["fire", "flying"], ["ground"], []])
        self.assertEqual(matrix["grass"], [2.0, 0.5, None])
        self.assertEqual(matrix["electric"], [1.0, 2.0, None])
        self.assertEqual(team_offensive_summary(matrix)["grass"], (1, 0, 1))
        uncovered = uncovered_types(matrix)
        self.assertIn("water", uncovered)
        self.assertNotIn("grass", uncovered)
        self.assertNotIn("steel", uncovered, "fire and ground both hit steel")


if __name__ == "__main__":
    unittest.main()

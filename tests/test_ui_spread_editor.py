"""SpreadEditor: Champions stat points — clamping to 32 and to the 66 budget, min speed, layout."""

import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from _ui_stubs import serialise  # noqa: E402

from pokemon_champions_planning_tool.domain.entities.pokemon_stats import PokemonStats
from pokemon_champions_planning_tool.ui.components.spread_editor import SpreadEditor

CHARIZARD = PokemonStats(hp=78, attack=84, defense=78, sp_atk=109, sp_def=85, speed=100)


class TestSpreadEditor(unittest.TestCase):
    def setUp(self):
        self.changes: list[tuple[str, dict]] = []
        self.editor = SpreadEditor(base_stats=CHARIZARD, nature="timid", points={"special_attack": 32}, on_change=lambda n, p: self.changes.append((n, p)))

    def test_typed_and_slid_values_are_clamped_to_stat_and_budget(self):
        self.editor._typed("speed", "40")
        self.assertEqual(self.editor.points["speed"], 32, "32 per stat")
        self.editor._slider_changed("hp", 10)
        self.assertEqual(self.editor.points["hp"], 2, "only 2 of the 66 points were left")
        self.assertEqual(self.editor.remaining, 0)
        self.editor._typed("attack", "abc")
        self.assertNotIn("attack", self.editor.points)
        self.assertEqual(self.changes[-1], ("timid", {"hp": 2, "special_attack": 32, "speed": 32}))
        self.assertEqual(self.editor.stats.speed, 167)
        self.assertEqual(self.editor._computed["special_attack"].value, "161", "109+32+20, Timid does not touch SpA")
        self.assertIn("0 left", self.editor._total.value)

    def test_min_speed_keeps_the_boosted_stat(self):
        self.editor._nature.value = "modest"
        self.editor._typed("speed", "20")
        self.editor.set_min_speed()
        self.assertEqual((self.editor.nature, self.editor.points.get("speed")), ("quiet", None))
        self.editor._nature.value = "hardy"
        self.editor.set_min_speed()
        self.assertEqual(self.editor.nature, "brave")
        self.editor._nature.value = "sassy"
        self.editor.set_min_speed()
        self.assertEqual(self.editor.nature, "sassy", "already a −Spe nature")

    def test_set_values_loads_without_notifying_and_serialises(self):
        self.editor.set_values("Adamant", {"attack": 32, "hp": 32, "speed": 2})
        self.assertEqual(self.changes, [])
        self.assertEqual(self.editor._computed["attack"].value, "149")
        self.assertGreater(serialise(self.editor), 20)
        compact = SpreadEditor(base_stats=CHARIZARD, nature=None, points=None, compact=True)
        self.assertGreater(serialise(compact), 10)
        self.assertEqual(compact.remaining, 66)


if __name__ == "__main__":
    unittest.main()

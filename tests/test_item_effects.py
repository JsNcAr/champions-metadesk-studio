"""Unit tests for item effect calculation and guardrail validation in item_effect_service.py."""

import unittest

from pokemon_champions_planning_tool.domain.entities.item import Item
from pokemon_champions_planning_tool.domain.entities.pokemon_stats import PokemonStats
from pokemon_champions_planning_tool.services.item_effect_service import (
    ValidationResult,
    compute_effective_stats,
    validate_item_assignment,
)


class TestItemEffectService(unittest.TestCase):
    """Tests for pure stat modifier computation and guardrail validation rules."""

    def setUp(self):
        self.base_stats = PokemonStats(
            hp=100,
            attack=100,
            defense=100,
            sp_atk=100,
            sp_def=100,
            speed=100,
        )

        self.choice_scarf = Item(
            canonical_id="choice-scarf",
            display_name="Choice Scarf",
            category="choice",
            is_champions_legal=True,
            stat_modifiers={"speed": 1.5},
        )

        self.iron_ball = Item(
            canonical_id="iron-ball",
            display_name="Iron Ball",
            category="bad-held-items",
            is_champions_legal=True,
            stat_modifiers={"speed": 0.5},
        )

        self.choice_band = Item(
            canonical_id="choice-band",
            display_name="Choice Band",
            category="choice",
            is_champions_legal=False,  # Not in Champions
            stat_modifiers={"attack": 1.5},
        )

        self.charizardite_x = Item(
            canonical_id="charizardite-x",
            display_name="Charizardite X",
            category="mega-stones",
            is_champions_legal=True,
            target_species="charizard",
            target_form="mega-x",
        )

        self.blastoisite = Item(
            canonical_id="blastoisite",
            display_name="Blastoisite",
            category="mega-stones",
            is_champions_legal=True,
            target_species="blastoise",
            target_form="mega",
        )

    def test_compute_effective_stats_choice_scarf(self):
        modified = compute_effective_stats(self.base_stats, self.choice_scarf)
        self.assertEqual(modified.speed, 150)
        self.assertEqual(modified.attack, 100)
        self.assertEqual(modified.hp, 100)

    def test_compute_effective_stats_iron_ball(self):
        modified = compute_effective_stats(self.base_stats, self.iron_ball)
        self.assertEqual(modified.speed, 50)

    def test_compute_effective_stats_no_item(self):
        modified = compute_effective_stats(self.base_stats, None)
        self.assertEqual(modified, self.base_stats)

    def test_validate_legal_item(self):
        res = validate_item_assignment(self.choice_scarf, species_name="Charizard")
        self.assertTrue(res.is_valid)
        self.assertIsNone(res.warning)
        self.assertIsNone(res.error)

    def test_validate_non_champions_item_yields_warning(self):
        res = validate_item_assignment(self.choice_band, species_name="Charizard")
        self.assertTrue(res.is_valid)  # Valid assignment, but has warning
        self.assertIsNotNone(res.warning)
        self.assertIn("not available in Pokémon Champions format", res.warning)

    def test_validate_mega_stone_correct_species(self):
        res = validate_item_assignment(self.charizardite_x, species_name="Charizard")
        self.assertTrue(res.is_valid)
        self.assertIsNone(res.error)
        self.assertEqual(res.unlocked_form, "mega-x")

    def test_validate_mega_stone_wrong_species_yields_error(self):
        res = validate_item_assignment(self.charizardite_x, species_name="Pikachu")
        self.assertFalse(res.is_valid)
        self.assertIsNotNone(res.error)
        self.assertIn("can only be held by Charizard", res.error)
        self.assertIsNone(res.unlocked_form)

    def test_validate_multi_mega_team_warning(self):
        # Charizard holds Charizardite X, Blastoise holds Blastoisite
        res = validate_item_assignment(
            self.blastoisite,
            species_name="Blastoise",
            team_items=[self.charizardite_x, self.blastoisite],
        )
        self.assertTrue(res.is_valid)
        self.assertEqual(res.unlocked_form, "mega")
        self.assertIsNotNone(res.warning)
        self.assertIn("Only one Pokémon per team can Mega Evolve", res.warning)


if __name__ == "__main__":
    unittest.main()


class TestAssaultVestModifier(unittest.TestCase):
    def test_assault_vest_is_in_the_modifier_map(self):
        from pokemon_champions_planning_tool.infrastructure.providers import _STAT_MODIFIER_MAP

        self.assertEqual(_STAT_MODIFIER_MAP["assaultvest"], {"special_defense": 1.5})

    def test_assault_vest_boosts_special_defense_only(self):
        base = PokemonStats(hp=100, attack=100, defense=100, sp_atk=100, sp_def=100, speed=100)
        vest = Item(canonical_id="assault-vest", display_name="Assault Vest", category="held", stat_modifiers={"special_defense": 1.5})
        boosted = compute_effective_stats(base, vest)
        self.assertEqual(boosted.special_defense, 150)
        self.assertEqual((boosted.hp, boosted.attack, boosted.defense, boosted.special_attack, boosted.speed), (100, 100, 100, 100, 100))

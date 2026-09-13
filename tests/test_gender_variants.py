import unittest
from unittest.mock import MagicMock, patch

from pokemon_champions_planning_tool.domain.pokemon_identity import (
    expand_canonical_aliases,
    format_api_name,
    qualified_name,
    SHOWDOWN_TO_POKEAPI_SLUG,
)
from pokemon_champions_planning_tool.domain.species import SpeciesInfo
from pokemon_champions_planning_tool.infrastructure.database.models import (
    ChampionsSpeciesRecord,
)
from pokemon_champions_planning_tool.infrastructure.pokeapi.pokeapi_retrieval import (
    get_official_stats,
)
from pokemon_champions_planning_tool.ui.catalogs import Catalogs


class TestGenderVariantsIdentity(unittest.TestCase):
    def test_format_api_name_gender_forms(self):
        # Indeedee variants
        self.assertEqual(format_api_name("Indeedee-F"), "indeedee-f")
        self.assertEqual(format_api_name("Indeedee (Female)"), "indeedee-f")
        self.assertEqual(format_api_name("Indeedee Female"), "indeedee-f")
        self.assertEqual(format_api_name("Indeedee ♀"), "indeedee-f")
        self.assertEqual(format_api_name("Indeedee-f"), "indeedee-f")
        self.assertEqual(format_api_name("Indeedee f"), "indeedee-f")
        self.assertEqual(format_api_name("Indeedee"), "indeedee")
        self.assertEqual(format_api_name("Indeedee (Male)"), "indeedee")
        self.assertEqual(format_api_name("Indeedee Male"), "indeedee")
        self.assertEqual(format_api_name("Indeedee ♂"), "indeedee")
        self.assertEqual(format_api_name("Indeedee-M"), "indeedee")

        # Basculegion variants
        self.assertEqual(format_api_name("Basculegion-F"), "basculegion-f")
        self.assertEqual(format_api_name("Basculegion (Female)"), "basculegion-f")
        self.assertEqual(format_api_name("Basculegion Female"), "basculegion-f")
        self.assertEqual(format_api_name("Basculegion ♀"), "basculegion-f")
        self.assertEqual(format_api_name("Basculegion"), "basculegion")
        self.assertEqual(format_api_name("Basculegion (Male)"), "basculegion")
        self.assertEqual(format_api_name("Basculegion Male"), "basculegion")
        self.assertEqual(format_api_name("Basculegion ♂"), "basculegion")
        self.assertEqual(format_api_name("Basculegion-M"), "basculegion")

        # Meowstic variants
        self.assertEqual(format_api_name("Meowstic-F"), "meowstic-f")
        self.assertEqual(format_api_name("Meowstic (Female)"), "meowstic-f")
        self.assertEqual(format_api_name("Meowstic Female"), "meowstic-f")
        self.assertEqual(format_api_name("Meowstic ♀"), "meowstic-f")
        self.assertEqual(format_api_name("Meowstic"), "meowstic")
        self.assertEqual(format_api_name("Meowstic (Male)"), "meowstic")

        # Oinkologne variants
        self.assertEqual(format_api_name("Oinkologne-F"), "oinkologne-f")
        self.assertEqual(format_api_name("Oinkologne (Female)"), "oinkologne-f")
        self.assertEqual(format_api_name("Oinkologne Female"), "oinkologne-f")
        self.assertEqual(format_api_name("Oinkologne"), "oinkologne")
        self.assertEqual(format_api_name("Oinkologne (Male)"), "oinkologne")

    def test_expand_canonical_aliases(self):
        self.assertIn("indeedee-f", expand_canonical_aliases(["indeedee-female"]))
        self.assertIn("indeedee-female", expand_canonical_aliases(["indeedee-f"]))
        self.assertIn("basculegion-f", expand_canonical_aliases(["basculegion-female"]))
        self.assertIn("basculegion-female", expand_canonical_aliases(["basculegion-f"]))
        self.assertIn("indeedee", expand_canonical_aliases(["indeedee-male"]))
        self.assertIn("basculegion", expand_canonical_aliases(["basculegion-male"]))

    def test_qualified_name(self):
        self.assertEqual(qualified_name("Indeedee", "indeedee"), "Indeedee (Male)")
        self.assertEqual(qualified_name("Basculegion", "basculegion"), "Basculegion (Male)")
        self.assertEqual(qualified_name("Indeedee-F", "indeedee-f"), "Indeedee-F")
        self.assertEqual(qualified_name("Basculegion ♀", "basculegion-f"), "Basculegion ♀")


class TestCatalogsSuggestions(unittest.TestCase):
    def test_suggest_species_includes_forms(self):
        champions = (
            ChampionsSpeciesRecord(entry_number=1, species_name="indeedee", display_name="Indeedee"),
            ChampionsSpeciesRecord(entry_number=2, species_name="basculegion", display_name="Basculegion"),
        )
        species_by_canonical = {
            "indeedee": SpeciesInfo(
                canonical_id="indeedee", showdown_id="indeedee", name="Indeedee", dex_number=876,
                base_species_id="indeedee", forme=None, types=("Psychic", "Normal"),
                base_stats={"hp": 60, "atk": 65, "def": 55, "spa": 105, "spd": 95, "spe": 95},
                abilities=("Psychic Surge",), weightkg=28.0, gender="M", required_item=None,
                battle_only=None, is_mega=False, is_legal=True,
            ),
            "indeedee-f": SpeciesInfo(
                canonical_id="indeedee-f", showdown_id="indeedeef", name="Indeedee-F", dex_number=876,
                base_species_id="indeedee", forme="F", types=("Psychic", "Normal"),
                base_stats={"hp": 70, "atk": 55, "def": 55, "spa": 95, "spd": 105, "spe": 85},
                abilities=("Psychic Surge",), weightkg=28.0, gender="F", required_item=None,
                battle_only=None, is_mega=False, is_legal=True,
            ),
            "basculegion": SpeciesInfo(
                canonical_id="basculegion", showdown_id="basculegion", name="Basculegion", dex_number=902,
                base_species_id="basculegion", forme=None, types=("Water", "Ghost"),
                base_stats={"hp": 120, "atk": 112, "def": 65, "spa": 80, "spd": 75, "spe": 78},
                abilities=("Adaptability",), weightkg=110.0, gender="M", required_item=None,
                battle_only=None, is_mega=False, is_legal=True,
            ),
            "basculegion-f": SpeciesInfo(
                canonical_id="basculegion-f", showdown_id="basculegionf", name="Basculegion-F", dex_number=902,
                base_species_id="basculegion", forme="F", types=("Water", "Ghost"),
                base_stats={"hp": 120, "atk": 92, "def": 65, "spa": 100, "spd": 75, "spe": 78},
                abilities=("Adaptability",), weightkg=110.0, gender="F", required_item=None,
                battle_only=None, is_mega=False, is_legal=True,
            ),
        }

        cats = Catalogs(champions=champions, species_by_canonical=species_by_canonical)

        # Both variants returned when searching "indeedee"
        indeedee_results = cats.suggest_species("indeedee")
        self.assertEqual(len(indeedee_results), 2)
        self.assertEqual(
            [(r.display_name, r.canonical_id) for r in indeedee_results],
            [("Indeedee", "indeedee"), ("Indeedee (Female)", "indeedee-f")],
        )

        # Specific query returns the female form
        indeedee_f_results = cats.suggest_species("indeedee-f")
        self.assertEqual(len(indeedee_f_results), 1)
        self.assertEqual(indeedee_f_results[0].canonical_id, "indeedee-f")

        indeedee_female_results = cats.suggest_species("indeedee female")
        self.assertEqual(len(indeedee_female_results), 1)
        self.assertEqual(indeedee_female_results[0].canonical_id, "indeedee-f")

        # Both variants returned when searching "basculegion"
        basculegion_results = cats.suggest_species("basculegion")
        self.assertEqual(len(basculegion_results), 2)
        self.assertEqual(
            [(r.display_name, r.canonical_id) for r in basculegion_results],
            [("Basculegion", "basculegion"), ("Basculegion (Female)", "basculegion-f")],
        )


class TestPokeApiRetrievalGenderForms(unittest.TestCase):
    def test_showdown_slug_to_pokeapi(self):
        self.assertEqual(SHOWDOWN_TO_POKEAPI_SLUG["indeedee-f"], "indeedee-female")
        self.assertEqual(SHOWDOWN_TO_POKEAPI_SLUG["basculegion-f"], "basculegion-female")
        self.assertEqual(SHOWDOWN_TO_POKEAPI_SLUG["meowstic-f"], "meowstic-female")
        self.assertEqual(SHOWDOWN_TO_POKEAPI_SLUG["oinkologne-f"], "oinkologne-female")

    @patch("pokemon_champions_planning_tool.infrastructure.pokeapi.pokeapi_retrieval._get_json")
    def test_get_official_stats_fetches_female_variety(self, mock_get_json):
        mock_get_json.return_value = {
            "name": "indeedee-female",
            "species": {"name": "indeedee"},
            "id": 876,
            "stats": [
                {"stat": {"name": "hp"}, "base_stat": 70},
                {"stat": {"name": "attack"}, "base_stat": 55},
                {"stat": {"name": "defense"}, "base_stat": 55},
                {"stat": {"name": "special-attack"}, "base_stat": 95},
                {"stat": {"name": "special-defense"}, "base_stat": 105},
                {"stat": {"name": "speed"}, "base_stat": 85},
            ],
            "abilities": [
                {"ability": {"name": "psychic-surge", "url": "https://pokeapi.co/api/v2/ability/180/"}, "slot": 3, "is_hidden": True},
            ],
            "types": [
                {"type": {"name": "psychic"}},
                {"type": {"name": "normal"}},
            ],
            "sprites": {"front_default": "https://sprites/876-f.png"},
        }

        # Querying with Showdown name "Indeedee-F"
        p = get_official_stats("Indeedee-F")
        self.assertIsNotNone(p)
        self.assertEqual(p.canonical_id, "indeedee-f")
        self.assertEqual(p.form_name, "Female")
        self.assertEqual(p.stats.hp, 70)
        self.assertEqual(p.stats.attack, 55)
        self.assertEqual(p.stats.special_defense, 105)

        # Verify it called the correct variety endpoint
        mock_get_json.assert_called_with("https://pokeapi.co/api/v2/pokemon/indeedee-female")


if __name__ == "__main__":
    unittest.main()


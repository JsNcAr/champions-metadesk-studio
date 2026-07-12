import unittest

from pokemon_champions_planning_tool.domain.pokemon_identity import (
    format_api_name,
    format_display_name,
)


class TestPokemonIdentity(unittest.TestCase):
    def test_format_display_name(self):
        self.assertEqual(format_display_name("pikachu"), "Pikachu")
        self.assertEqual(format_display_name("charizard-mega-x"), "Mega Charizard X")
        self.assertEqual(format_display_name("mewtwo-mega-y"), "Mega Mewtwo Y")
        self.assertEqual(format_display_name("lucario-mega"), "Mega Lucario")
        self.assertEqual(format_display_name("raichu-alola"), "Alolan Raichu")
        self.assertEqual(format_display_name("meowth-galar"), "Galarian Meowth")
        self.assertEqual(format_display_name("growlithe-hisui"), "Hisuian Growlithe")
        self.assertEqual(format_display_name("wooper-paldea"), "Paldean Wooper")
        self.assertEqual(format_display_name(""), "")
        self.assertEqual(format_display_name(None), "")

    def test_format_api_name(self):
        self.assertEqual(format_api_name("Pikachu"), "pikachu")
        self.assertEqual(format_api_name("Mega Charizard X"), "charizard-mega-x")
        self.assertEqual(format_api_name("Mega Mewtwo Y"), "mewtwo-mega-y")
        self.assertEqual(format_api_name("Mega Lucario"), "lucario-mega")
        self.assertEqual(format_api_name("Alolan Raichu"), "raichu-alola")
        self.assertEqual(format_api_name("Galarian Meowth"), "meowth-galar")
        self.assertEqual(format_api_name("Hisuian Growlithe"), "growlithe-hisui")
        self.assertEqual(format_api_name("Paldean Wooper"), "wooper-paldea")
        self.assertEqual(format_api_name("   "), "")
        self.assertEqual(format_api_name(""), "")

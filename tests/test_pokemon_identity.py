import unittest

from pokemon_champions_planning_tool.domain.pokemon_identity import (
    format_api_name,
    format_display_name,
    get_pokemon_sprite_url,
    get_showdown_sprite_slug,
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


class TestShowdownSpriteSlug(unittest.TestCase):
    """Showdown names sprites '<species>-<form>' with each part stripped of
    non-alphanumerics. PokeAPI uses hyphens for both, so the split has to be right."""

    def test_forms_keep_the_separator(self):
        """Regression: these all collapsed to one word and 404'd on the CDN."""
        for canonical, expected in [
            ("lycanroc-dusk", "lycanroc-dusk"),
            ("rotom-wash", "rotom-wash"),
            ("rotom-heat", "rotom-heat"),
            ("giratina-origin", "giratina-origin"),
            ("maushold-four", "maushold-four"),
            ("sinistcha-masterpiece", "sinistcha-masterpiece"),
            ("tatsugiri-droopy", "tatsugiri-droopy"),
            ("basculegion-f", "basculegion-f"),
            ("indeedee-f", "indeedee-f"),
            ("meowstic-f", "meowstic-f"),
        ]:
            self.assertEqual(get_showdown_sprite_slug(canonical), expected, canonical)

    def test_hyphenated_species_lose_the_hyphen(self):
        """A hyphen inside a species name is not a form separator."""
        for canonical, expected in [
            ("chien-pao", "chienpao"),
            ("wo-chien", "wochien"),
            ("ting-lu", "tinglu"),
            ("ho-oh", "hooh"),
            ("porygon-z", "porygonz"),
            ("mr-mime", "mrmime"),
            ("tapu-koko", "tapukoko"),
            ("roaring-moon", "roaringmoon"),
            ("iron-hands", "ironhands"),
            ("great-tusk", "greattusk"),
            ("type-null", "typenull"),
        ]:
            self.assertEqual(get_showdown_sprite_slug(canonical), expected, canonical)

    def test_species_form_ambiguity_is_resolved(self):
        """'nidoran-f' is a species; 'indeedee-f' is a female form."""
        self.assertEqual(get_showdown_sprite_slug("nidoran-f"), "nidoranf")
        self.assertEqual(get_showdown_sprite_slug("indeedee-f"), "indeedee-f")

    def test_multi_word_forms_are_collapsed(self):
        """Only the species/form separator survives; hyphens inside a form do not."""
        self.assertEqual(get_showdown_sprite_slug("urshifu-rapid-strike"), "urshifu-rapidstrike")
        self.assertEqual(get_showdown_sprite_slug("charizard-mega-x"), "charizard-megax")
        self.assertEqual(get_showdown_sprite_slug("charizard-mega-y"), "charizard-megay")
        self.assertEqual(get_showdown_sprite_slug("lucario-mega"), "lucario-mega")
        self.assertEqual(get_showdown_sprite_slug("necrozma-dusk-mane"), "necrozma-duskmane")
        self.assertEqual(get_showdown_sprite_slug("tauros-paldea-aqua"), "tauros-paldeaaqua")

    def test_overrides(self):
        """Slugs Showdown does not derive from the PokeAPI identifier."""
        self.assertEqual(get_showdown_sprite_slug("tauros-paldea"), "tauros-paldeacombat")
        self.assertEqual(get_showdown_sprite_slug("urshifu-single-strike"), "urshifu")

    def test_plain_species_unchanged(self):
        self.assertEqual(get_showdown_sprite_slug("incineroar"), "incineroar")
        self.assertEqual(get_showdown_sprite_slug("Incineroar"), "incineroar")

    def test_url_and_empty_input(self):
        self.assertEqual(
            get_pokemon_sprite_url("lycanroc-dusk"),
            "https://play.pokemonshowdown.com/sprites/gen5/lycanroc-dusk.png",
        )
        self.assertIn("poke-ball", get_pokemon_sprite_url(""))


class TestDefaultFormLabels(unittest.TestCase):
    def test_bare_species_with_an_implicit_default_form_are_labelled(self):
        from pokemon_champions_planning_tool.domain.pokemon_identity import default_form_label, qualified_name

        self.assertEqual(default_form_label("basculegion"), "Male")
        self.assertEqual(default_form_label("Aegislash"), "Shield")
        self.assertIsNone(default_form_label("kingambit"))
        self.assertIsNone(default_form_label("basculegion-f"))  # the name already says which form
        self.assertIsNone(default_form_label(None))
        self.assertEqual(qualified_name("Basculegion", "basculegion"), "Basculegion (Male)")
        self.assertEqual(qualified_name("Kingambit", "kingambit"), "Kingambit")
        self.assertEqual(qualified_name("Lycanroc Midday", "lycanroc"), "Lycanroc Midday")  # never doubled

    def test_pokemon_entity_exposes_the_label(self):
        from pokemon_champions_planning_tool.domain.entities.pokemon import Pokemon
        from pokemon_champions_planning_tool.domain.entities.pokemon_stats import PokemonStats

        stats = PokemonStats(hp=1, attack=1, defense=1, sp_atk=1, sp_def=1, speed=1)
        p = Pokemon(canonical_id="basculegion", display_name="Basculegion", form_name="Male", stats=stats)
        self.assertEqual(p.form_label, "Male")
        self.assertEqual(p.qualified_name, "Basculegion (Male)")
        base = Pokemon(canonical_id="kingambit", display_name="Kingambit", form_name="Base", stats=stats)
        self.assertIsNone(base.form_label)
        self.assertEqual(base.qualified_name, "Kingambit")
        mega = Pokemon(canonical_id="charizard-mega-x", display_name="Mega Charizard X", form_name="Mega", stats=stats)
        self.assertEqual(mega.qualified_name, "Mega Charizard X")

    def test_meta_member_row_shows_the_label(self):
        from pokemon_champions_planning_tool.services.tournament_service import MetaMemberRow

        row = MetaMemberRow(slot=1, species_name="Basculegion", canonical_id="basculegion", sprite_url="", is_legal=True)
        self.assertEqual(row.display_name, "Basculegion (Male)")
        female = MetaMemberRow(slot=2, species_name="Basculegion ♀", canonical_id="basculegion-f", sprite_url="", is_legal=True)
        self.assertEqual(female.display_name, "Basculegion ♀")

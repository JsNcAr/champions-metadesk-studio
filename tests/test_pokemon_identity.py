import unittest

from pokemon_champions_planning_tool.domain.pokemon_identity import (
    classify_battle_format,
    format_api_name,
    format_display_name,
    get_pokemon_sprite_url,
    get_showdown_sprite_slug,
    normalize_format_regulation,
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


class TestNormalizeFormatRegulation(unittest.TestCase):
    def test_title_overrides_stale_format_code(self):
        # M-C in title overrides M-B format code
        self.assertEqual(
            normalize_format_regulation("M-B", "[Shiny Salamence to 1st] The Grim Challenge #8 M-C"),
            "Regulation M-C",
        )
        self.assertEqual(
            normalize_format_regulation("M-B", "Cusca Champions Weekly M-C ⚡ #12 (PCVGC)"),
            "Regulation M-C",
        )
        self.assertEqual(
            normalize_format_regulation("M-B", "CHAMPIONS REG. M-C |👑CROWN FIGHT Bo3 TOUR #85👑"),
            "Regulation M-C",
        )
        self.assertEqual(
            normalize_format_regulation("M-B", "r/VGC Regulation M-C Kickoff Cup"),
            "Regulation M-C",
        )
        # M-B in title overrides M-A format code
        self.assertEqual(
            normalize_format_regulation("M-A", "Friday Fight Night #60 Reg M-B Bo3"),
            "Regulation M-B",
        )
        self.assertEqual(
            normalize_format_regulation("M-A", "Extreme Speed #8 REG M-B"),
            "Regulation M-B",
        )

    def test_unhyphenated_and_custom_variations(self):
        self.assertEqual(
            normalize_format_regulation("CUSTOM", "Circuito VGC #7 REG MC | Z2 Gaming"),
            "Regulation M-C",
        )
        self.assertEqual(
            normalize_format_regulation("CUSTOM", "BPL MC KICKOFF TOURNAMENT"),
            "Regulation M-C",
        )
        self.assertEqual(
            normalize_format_regulation("CUSTOM", "🍋Sitrus-Series🍋|Champions-MC|$50 to First|#75"),
            "Regulation M-C",
        )
        self.assertEqual(
            normalize_format_regulation("CUSTOM", "Torneo KURAMI, REG M-C"),
            "Regulation M-C",
        )
        self.assertEqual(
            normalize_format_regulation("CUSTOM", "˗ˋˏ❤︎ˎˊ˗ Pomelo Late Night Tour (M-C)"),
            "Regulation M-C",
        )

    def test_fallback_to_raw_format_code(self):
        self.assertEqual(normalize_format_regulation("M-C"), "Regulation M-C")
        self.assertEqual(normalize_format_regulation("M-B"), "Regulation M-B")
        self.assertEqual(normalize_format_regulation("M-A"), "Regulation M-A")
        self.assertEqual(
            normalize_format_regulation("M-B", "PWC - Battle in the Colosseum #26"),
            "Regulation M-B",
        )
        self.assertEqual(
            normalize_format_regulation("SV Reg. Set F OTS", "Charlotte Regional"),
            "Regulation F",
        )
        self.assertEqual(normalize_format_regulation("", ""), "Champions Season 1")


class TestClassifyBattleFormat(unittest.TestCase):
    def test_singles_detected_from_name(self):
        self.assertEqual(
            classify_battle_format("ChampionMads SINGLES Battle Arena #8 - $50 USD"),
            "singles",
        )
        self.assertEqual(
            classify_battle_format("Rising Stars - S2 (Single Battle)"),
            "singles",
        )
        self.assertEqual(
            classify_battle_format("GVGCL 3v3 Mini Series Tour 1/3"),
            "singles",
        )
        self.assertEqual(
            classify_battle_format("Boldore's Gate 10 - Champions SINGLES! - $5 Pool"),
            "singles",
        )
        self.assertEqual(
            classify_battle_format("⛩️Chadweezy95 Singles Champions Tournament Ep 1!⛩️"),
            "singles",
        )
        self.assertEqual(
            classify_battle_format("Champions 1v1 Fast Cup"),
            "singles",
        )
        self.assertEqual(
            classify_battle_format("Champions 6v6 Showdown"),
            "singles",
        )
        self.assertEqual(
            classify_battle_format("BSS Champions Season 1"),
            "singles",
        )

    def test_single_elimination_bracket_is_not_singles(self):
        self.assertEqual(
            classify_battle_format("Single Elimination Doubles Tournament"),
            "doubles",
        )
        self.assertEqual(
            classify_battle_format("VGC 2026 - Single Elim"),
            "doubles",
        )
        self.assertEqual(
            classify_battle_format("Champions Single-Elimination Weekly"),
            "doubles",
        )

    def test_doubles_defaults_and_explicit(self):
        self.assertEqual(
            classify_battle_format("2027 Baltimore Regional"),
            "doubles",
        )
        self.assertEqual(
            classify_battle_format("Alpensee x Smogon VGC Tour (Reg M-B) #70"),
            "doubles",
        )
        self.assertEqual(
            classify_battle_format("PWC - Battle in the Colosseum #26"),
            "doubles",
        )
        self.assertEqual(
            classify_battle_format("Trinity Championship 10 (Double Format)"),
            "doubles",
        )
        self.assertEqual(
            classify_battle_format(None, None),
            "doubles",
        )
        self.assertEqual(
            classify_battle_format("Custom Tour", "SINGLES"),
            "singles",
        )




class TestMegaZNames(unittest.TestCase):
    """Champions adds Z Megas (Garchomp, Absol). They used to show as "Garchomp-Mega-Z"."""

    def test_z_megas_read_like_the_other_megas(self):
        from pokemon_champions_planning_tool.domain.pokemon_identity import format_display_name

        self.assertEqual(format_display_name("garchomp-mega-z"), "Mega Garchomp Z")
        self.assertEqual(format_display_name("absol-mega-z"), "Mega Absol Z")
        self.assertEqual(format_display_name("garchomp-mega"), "Mega Garchomp")

    def test_a_record_cached_with_the_old_name_still_shows_the_new_one(self):
        from pokemon_champions_planning_tool.infrastructure.database.models import MegaEvolutionRecord
        from pokemon_champions_planning_tool.ui.views.box.store import FormOption

        cached = MegaEvolutionRecord(canonical_id="garchomp-mega-z", species_name="garchomp", display_name="Garchomp-Mega-Z",
                                     types=["dragon"], hp=108, attack=130, defense=95, special_attack=80, special_defense=85, speed=102)
        self.assertEqual(FormOption.from_mega(cached).label, "Mega Garchomp Z")

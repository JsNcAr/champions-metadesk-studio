"""Unit tests for ShowdownService and PokepastProvider."""

from __future__ import annotations

import unittest
from unittest.mock import MagicMock, patch

from pokemon_champions_planning_tool.services.showdown_service import (
    ParsedSlot,
    ParsedTeamResult,
    ImportReadinessReport,
    ShowdownExportResult,
    _parse_header,
    _parse_spread_line,
    _normalize_showdown_key,
    export_team_to_showdown_text,
    parse_showdown_text,
    resolve_import_readiness,
    import_from_pokepast_url,
    publish_to_pokepast,
)
from pokemon_champions_planning_tool.infrastructure.providers.pokepast_provider import (
    PokepastProvider,
    PokepastNetworkError,
)


# ---------------------------------------------------------------------------
# Header Parser Tests
# ---------------------------------------------------------------------------


class TestParseHeader(unittest.TestCase):
    """_parse_header covers the right-to-left step-based algorithm."""

    def test_simple_species_only(self):
        species, nick, gender, item = _parse_header("Pikachu")
        self.assertEqual(species, "Pikachu")
        self.assertIsNone(nick)
        self.assertIsNone(gender)
        self.assertIsNone(item)

    def test_species_with_item(self):
        species, nick, gender, item = _parse_header("Iron Hands @ Booster Energy")
        self.assertEqual(species, "Iron Hands")
        self.assertIsNone(nick)
        self.assertIsNone(gender)
        self.assertEqual(item, "Booster Energy")

    def test_species_with_hyphen(self):
        species, nick, gender, item = _parse_header("Ho-Oh @ Sacred Ash")
        self.assertEqual(species, "Ho-Oh")
        self.assertEqual(item, "Sacred Ash")

    def test_type_null(self):
        species, nick, gender, item = _parse_header("Type: Null")
        self.assertEqual(species, "Type: Null")
        self.assertIsNone(item)

    def test_nickname_species_gender_item(self):
        species, nick, gender, item = _parse_header(
            "Sparky (Pikachu-Starter) (F) @ Light Ball"
        )
        self.assertEqual(species, "Pikachu-Starter")
        self.assertEqual(nick, "Sparky")
        self.assertEqual(gender, "F")
        self.assertEqual(item, "Light Ball")

    def test_species_gender_only(self):
        species, nick, gender, item = _parse_header("Gardevoir (F) @ Choice Specs")
        self.assertEqual(species, "Gardevoir")
        self.assertIsNone(nick)
        self.assertEqual(gender, "F")
        self.assertEqual(item, "Choice Specs")

    def test_composite_form_no_nickname(self):
        species, nick, gender, item = _parse_header(
            "Urshifu-Rapid-Strike @ Choice Band"
        )
        self.assertEqual(species, "Urshifu-Rapid-Strike")
        self.assertIsNone(nick)
        self.assertEqual(item, "Choice Band")


# ---------------------------------------------------------------------------
# Spread Parser Tests
# ---------------------------------------------------------------------------


class TestParseSpreadLine(unittest.TestCase):
    def test_full_ev_spread(self):
        result = _parse_spread_line("252 HP / 4 Def / 252 Spe")
        self.assertEqual(result["hp"], 252)
        self.assertEqual(result["defense"], 4)
        self.assertEqual(result["speed"], 252)

    def test_special_attack_abbreviation(self):
        result = _parse_spread_line("252 SpA / 252 Spe")
        self.assertEqual(result["special_attack"], 252)

    def test_zero_iv(self):
        result = _parse_spread_line("0 Atk")
        self.assertEqual(result["attack"], 0)

    def test_unknown_key_ignored(self):
        result = _parse_spread_line("252 xyz")
        self.assertNotIn("xyz", result)


# ---------------------------------------------------------------------------
# Full Paste Parser Tests
# ---------------------------------------------------------------------------


SIMPLE_PASTE = """\
Pikachu @ Light Ball
Ability: Static
Level: 50
EVs: 252 Atk / 4 SpD / 252 Spe
Jolly Nature
- Volt Tackle
- Quick Attack
- Iron Tail
- Protect
"""

MULTI_POKEMON_PASTE = """\
Iron Hands @ Assault Vest
Ability: Quark Drive
EVs: 252 HP / 4 Atk / 252 Def
Brave Nature
IVs: 0 Spe
- Fake Out
- Drain Punch
- Wild Charge
- Heavy Slam

Flutter Mane @ Choice Specs
Ability: Protosynthesis
EVs: 252 SpA / 4 SpD / 252 Spe
Timid Nature
- Moonblast
- Shadow Ball
- Dazzling Gleam
- Protect
"""

EDGE_CASE_PASTE = """\
Ho-Oh @ Sacred Ash
Ability: Regenerator
- Sacred Fire
- Brave Bird
- Earthquake
- Recover

Type: Null @ Eviolite
Ability: Battle Armor
- Return
- Iron Head
- Sleep Talk
- Protect
"""

NICKNAME_PASTE = """\
Sparky (Pikachu-Starter) (F) @ Light Ball
Ability: Lightning Rod
- Thunderbolt
- Fake Out
- Volt Switch
- Protect
"""


class TestParseShowdownText(unittest.TestCase):
    def test_single_pokemon(self):
        result = parse_showdown_text(SIMPLE_PASTE)
        self.assertTrue(result.is_valid)
        self.assertEqual(len(result.slots), 1)
        slot = result.slots[0]
        self.assertEqual(slot.species_name, "Pikachu")
        self.assertEqual(slot.item_name, "Light Ball")
        self.assertEqual(slot.ability_name, "Static")
        self.assertEqual(slot.level, 50)
        self.assertEqual(slot.nature, "Jolly")
        self.assertEqual(slot.evs["attack"], 252)
        self.assertEqual(slot.evs["speed"], 252)
        self.assertIn("Volt Tackle", slot.moves)
        self.assertIn("Protect", slot.moves)

    def test_multi_pokemon(self):
        result = parse_showdown_text(MULTI_POKEMON_PASTE)
        self.assertEqual(len(result.slots), 2)
        iron_hands = result.slots[0]
        flutter = result.slots[1]
        self.assertEqual(iron_hands.species_name, "Iron Hands")
        self.assertEqual(iron_hands.ivs.get("speed"), 0)
        self.assertEqual(flutter.species_name, "Flutter Mane")
        self.assertEqual(flutter.item_name, "Choice Specs")

    def test_edge_cases_ho_oh_and_type_null(self):
        result = parse_showdown_text(EDGE_CASE_PASTE)
        self.assertEqual(len(result.slots), 2)
        names = [s.species_name for s in result.slots]
        self.assertIn("Ho-Oh", names)
        self.assertIn("Type: Null", names)

    def test_nickname_slot(self):
        result = parse_showdown_text(NICKNAME_PASTE)
        self.assertEqual(len(result.slots), 1)
        slot = result.slots[0]
        self.assertEqual(slot.nickname, "Sparky")
        self.assertEqual(slot.species_name, "Pikachu-Starter")
        self.assertEqual(slot.gender, "F")

    def test_empty_paste(self):
        result = parse_showdown_text("")
        self.assertFalse(result.is_valid)
        self.assertEqual(len(result.slots), 0)

    def test_max_4_moves(self):
        paste = "Pikachu\n- A\n- B\n- C\n- D\n- E\n"
        result = parse_showdown_text(paste)
        self.assertEqual(len(result.slots[0].moves), 4)

    def test_showdown_form_key_normalised(self):
        result = parse_showdown_text("Iron Hands @ Assault Vest\n")
        self.assertEqual(result.slots[0].showdown_form_key, "iron-hands")


# ---------------------------------------------------------------------------
# Round-trip export → parse
# ---------------------------------------------------------------------------


class TestRoundTrip(unittest.TestCase):
    """Export a team then re-parse it and assert identity."""

    def _make_mock_member(self, display_name, item, ability, moves, nature, evs, ivs):
        member = MagicMock()
        member.slot_position = 1
        member.item = item
        member.ability = ability
        member.nature = nature
        member.evs = evs
        member.ivs = ivs
        member.level = 50
        member.moveset = [MagicMock(name=m) for m in moves]
        for i, m_name in enumerate(moves):
            member.moveset[i].name = m_name

        box_entry = MagicMock()
        box_entry.pokemon.display_name = display_name
        box_entry.pokemon.canonical_id = display_name.lower().replace(" ", "-")
        box_entry.shiny = False

        member.box_entry_id = "test-uuid"
        return member, box_entry

    def test_export_then_parse(self):
        member, box_entry = self._make_mock_member(
            display_name="Incineroar",
            item="Assault Vest",
            ability="Intimidate",
            moves=["Fake Out", "Knock Off", "Flare Blitz", "U-turn"],
            nature="Adamant",
            evs={"hp": 252, "attack": 4, "defense": 252},
            ivs={},
        )
        text = export_team_to_showdown_text([member], {"test-uuid": box_entry})
        result = parse_showdown_text(text)
        self.assertTrue(result.is_valid)
        slot = result.slots[0]
        self.assertEqual(slot.species_name, "Incineroar")
        self.assertEqual(slot.item_name, "Assault Vest")
        self.assertEqual(slot.ability_name, "Intimidate")
        self.assertEqual(slot.nature, "Adamant")
        self.assertIn("Fake Out", slot.moves)


# ---------------------------------------------------------------------------
# Import Readiness Tests
# ---------------------------------------------------------------------------


class TestResolveImportReadiness(unittest.TestCase):
    def _make_slot(self, species, key=None):
        return ParsedSlot(
            raw_header=species,
            species_name=species,
            showdown_form_key=key or species.lower().replace(" ", "-"),
        )

    def _make_box_repo(self, owned_names_and_ids: list[tuple[str, str]]):
        repo = MagicMock()
        entries = []
        for display, cid in owned_names_and_ids:
            e = MagicMock()
            e.pokemon.canonical_id = cid
            e.pokemon.display_name = display
            entries.append(e)
        repo.list_entries.return_value = entries
        return repo

    def test_all_in_box(self):
        slot = self._make_slot("Incineroar", "incineroar")
        result_mock = MagicMock()
        result_mock.slots = (slot,)
        repo = self._make_box_repo([("Incineroar", "incineroar")])
        report = resolve_import_readiness(result_mock, repo)
        self.assertEqual(len(report.in_box), 1)
        self.assertEqual(len(report.missing), 0)

    def test_illegal_species_detection(self):
        legal_slot = self._make_slot("Pikachu", "pikachu")
        illegal_slot = self._make_slot("Miraidon", "miraidon")
        result_mock = MagicMock()
        result_mock.slots = (legal_slot, illegal_slot)
        repo = self._make_box_repo([("Pikachu", "pikachu")])

        catalog = {"Pikachu", "Charizard", "Lucario"}
        report = resolve_import_readiness(result_mock, repo, legal_species_catalog=catalog)

        self.assertEqual(len(report.in_box), 1)
        self.assertEqual(len(report.illegal_species), 1)
        self.assertEqual(report.illegal_species[0].species_name, "Miraidon")
        self.assertTrue(any("Miraidon" in w for w in report.warnings))


# ---------------------------------------------------------------------------
# PokepastProvider Tests
# ---------------------------------------------------------------------------



class TestPokepastProviderExtractId(unittest.TestCase):
    def test_full_url(self):
        result = PokepastProvider.extract_id_from_url(
            "https://pokepast.es/87b754b592a5a6fd"
        )
        self.assertEqual(result, "87b754b592a5a6fd")

    def test_bare_id(self):
        result = PokepastProvider.extract_id_from_url("87b754b592a5a6fd")
        self.assertEqual(result, "87b754b592a5a6fd")

    def test_non_paste_url_returns_none(self):
        result = PokepastProvider.extract_id_from_url("https://example.com/teams/123")
        self.assertIsNone(result)

    def test_is_pokepast_url(self):
        self.assertTrue(PokepastProvider.is_pokepast_url("https://pokepast.es/abc"))
        self.assertFalse(PokepastProvider.is_pokepast_url("Pikachu @ Light Ball"))


class TestPokepastProviderNetwork(unittest.TestCase):
    def test_publish_network_error_raises(self):
        provider = PokepastProvider()
        with patch(
            "pokemon_champions_planning_tool.infrastructure.providers"
            ".pokepast_provider.requests.post",
            side_effect=Exception("timeout"),
        ):
            with self.assertRaises(PokepastNetworkError):
                provider.publish(
                    title="Test",
                    paste_text="Pikachu\n",
                )

    def test_fetch_network_error_raises(self):
        provider = PokepastProvider()
        with patch(
            "pokemon_champions_planning_tool.infrastructure.providers"
            ".pokepast_provider.requests.get",
            side_effect=Exception("connection refused"),
        ):
            with self.assertRaises(PokepastNetworkError):
                provider.fetch_by_id("abc123")


if __name__ == "__main__":
    unittest.main()

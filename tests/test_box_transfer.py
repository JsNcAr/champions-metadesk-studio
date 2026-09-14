"""Tests for the box transfer service: serialization, parsing, and database import."""

import json
import unittest

from sqlmodel import Session, SQLModel, create_engine

from pokemon_champions_planning_tool.domain.entities.box_entry import BoxEntry
from pokemon_champions_planning_tool.domain.entities.pokemon import Pokemon
from pokemon_champions_planning_tool.domain.entities.pokemon_ability import PokemonAbility
from pokemon_champions_planning_tool.domain.entities.pokemon_stats import PokemonStats
from pokemon_champions_planning_tool.services.box_transfer_service import (
    apply_box_import,
    export_box_to_csv_text,
    export_box_to_json,
    export_box_to_names,
    parse_box_import_text,
)


def _mon(canonical_id: str, name: str) -> Pokemon:
    return Pokemon(
        canonical_id=canonical_id,
        display_name=name,
        species_name=canonical_id,
        form_name="Base",
        types=["fire"],
        stats=PokemonStats(hp=70, attack=70, defense=70, sp_atk=70, sp_def=70, speed=70),
        abilities=[PokemonAbility(name="blaze")],
    )


class TestBoxTransferSerialization(unittest.TestCase):
    def setUp(self):
        self.mon1 = _mon("charizard", "Charizard")
        self.mon2 = _mon("incineroar", "Incineroar")
        self.entry1 = BoxEntry(
            pokemon=self.mon1,
            notes="Tailwind lead",
            tags=["VGC", "Core"],
            is_favorite=True,
            is_planned=False,
        )
        self.entry2 = BoxEntry(
            pokemon=self.mon2,
            notes="",
            tags=["Intimidate"],
            is_favorite=False,
            is_planned=True,
        )
        self.entries = [self.entry1, self.entry2]

    def test_json_export_and_import_roundtrip(self):
        json_str = export_box_to_json(self.entries)
        data = json.loads(json_str)
        self.assertEqual(data["app"], "Champions MetaDesk Studio")
        self.assertEqual(data["total"], 2)
        self.assertEqual(len(data["box"]), 2)

        parsed = parse_box_import_text(json_str)
        self.assertEqual(parsed.format_detected, "json")
        self.assertEqual(len(parsed.items), 2)
        self.assertEqual(parsed.items[0].species, "Charizard")
        self.assertEqual(parsed.items[0].tags, ["VGC", "Core"])
        self.assertEqual(parsed.items[0].notes, "Tailwind lead")
        self.assertTrue(parsed.items[0].is_favorite)
        self.assertFalse(parsed.items[0].is_planned)

        self.assertEqual(parsed.items[1].species, "Incineroar")
        self.assertTrue(parsed.items[1].is_planned)

    def test_plain_text_export_and_parse(self):
        names_only = export_box_to_names(self.entries, include_metadata=False)
        self.assertEqual(names_only, "Charizard\nIncineroar")

        parsed = parse_box_import_text(names_only)
        self.assertEqual(parsed.format_detected, "plain_text")
        self.assertEqual(len(parsed.items), 2)
        self.assertEqual(parsed.items[0].species, "Charizard")
        self.assertEqual(parsed.items[1].species, "Incineroar")

    def test_plain_text_with_inline_tags_and_favorites(self):
        raw_text = """
        # My Tournament Roster
        Charizard #Fire #Special ★
        Incineroar #Intimidate
        Rillaboom (Galar) #GrassySurge [planned]
        // This is a comment
        """
        parsed = parse_box_import_text(raw_text)
        self.assertEqual(parsed.format_detected, "plain_text")
        self.assertEqual(len(parsed.items), 3)

        self.assertEqual(parsed.items[0].species, "Charizard")
        self.assertEqual(parsed.items[0].tags, ["Fire", "Special"])
        self.assertTrue(parsed.items[0].is_favorite)

        self.assertEqual(parsed.items[1].species, "Incineroar")
        self.assertEqual(parsed.items[1].tags, ["Intimidate"])

        self.assertEqual(parsed.items[2].species, "Rillaboom")
        self.assertEqual(parsed.items[2].form, "Galar")
        self.assertEqual(parsed.items[2].tags, ["GrassySurge"])
        self.assertTrue(parsed.items[2].is_planned)

    def test_csv_export_and_parse(self):
        csv_str = export_box_to_csv_text(self.entries)
        self.assertIn("Pokémon,Form,Tags,Notes,Favorite,Planned", csv_str)
        self.assertIn("Charizard,Base,VGC;Core,Tailwind lead,True,False", csv_str)

        parsed = parse_box_import_text(csv_str)
        self.assertEqual(parsed.format_detected, "csv")
        self.assertEqual(len(parsed.items), 2)
        self.assertEqual(parsed.items[0].species, "Charizard")
        self.assertEqual(parsed.items[0].tags, ["VGC", "Core"])
        self.assertEqual(parsed.items[0].notes, "Tailwind lead")
        self.assertTrue(parsed.items[0].is_favorite)


class TestBoxTransferDatabaseApplication(unittest.TestCase):
    def setUp(self):
        self.engine = create_engine("sqlite:///:memory:")
        SQLModel.metadata.create_all(self.engine)

    def test_apply_import_merge_and_replace(self):
        with Session(self.engine) as session:
            # 1. Initial import of 2 items
            items1 = parse_box_import_text("Charizard #Fire\nIncineroar #Dark").items
            rep1 = apply_box_import(session, items1, strategy="merge")
            self.assertEqual(rep1.added, 2)
            self.assertEqual(rep1.total, 2)

            # 2. Merge import with 1 overlapping (with new tag) and 1 new
            items2 = parse_box_import_text("Charizard #VGC ★\nRillaboom #Grass").items
            rep2 = apply_box_import(session, items2, strategy="merge")
            self.assertEqual(rep2.added, 1)  # Rillaboom added
            self.assertEqual(rep2.updated, 1)  # Charizard updated with VGC tag & star

            # 3. Replace import with only 1 item
            items3 = parse_box_import_text("Garchomp #Dragon").items
            rep3 = apply_box_import(session, items3, strategy="replace")
            self.assertEqual(rep3.added, 1)

            from pokemon_champions_planning_tool.infrastructure.database.repositories import BoxRepository

            repo = BoxRepository(session)
            entries = repo.list_entries(include_planned=True)
            self.assertEqual(len(entries), 1)
            self.assertEqual(entries[0].pokemon.canonical_id, "garchomp")


if __name__ == "__main__":
    unittest.main()


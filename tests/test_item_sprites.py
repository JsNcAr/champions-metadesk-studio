"""Item icons: Showdown sheet cells for items PokéAPI has no art for, and the item sync
keeping what PokéAPI gave it."""

import unittest
from unittest.mock import patch

import flet as ft
from sqlmodel import Session, SQLModel, create_engine

from pokemon_champions_planning_tool.domain.item_sprites import ITEM_SHEET_URL, cell_offset, sheet_cell, sheet_url
from pokemon_champions_planning_tool.infrastructure.database.models import ItemRecord
from pokemon_champions_planning_tool.infrastructure.database.repositories import ItemRepository
from pokemon_champions_planning_tool.infrastructure.providers import _build_item_record
from pokemon_champions_planning_tool.infrastructure.showdown import parse_item_spritenums
from pokemon_champions_planning_tool.services import items_catalog_service
from pokemon_champions_planning_tool.ui.components.item_icon import item_icon

from _ui_stubs import serialise

BASE = """export const Items: import('../sim/dex-items').ItemDataTable = {
\tlifeorb: {
\t\tname: "Life Orb",
\t\tspritenum: 249,
\t\tfling: { basePower: 30 },
\t},
\texcadrite: {
\t\tname: "Excadrite",
\t\tspritenum: 999,
\t\tmegaStone: { "Excadrill": "Excadrill-Mega" },
\t},
};
"""
CHAMPIONS = """export const Items: import('../../../sim/dex-items').ModdedItemDataTable = {
\texcadrite: {
\t\tinherit: true,
\t\tspritenum: 553,
\t\tisNonstandard: null,
\t},
};
"""


class TestSheetReferences(unittest.TestCase):
    def test_urls_and_cells(self):
        self.assertEqual(sheet_cell(sheet_url(553)), 553)
        self.assertIsNone(sheet_cell("https://raw.githubusercontent.com/PokeAPI/sprites/master/sprites/items/life-orb.png"))
        self.assertIsNone(sheet_cell(None))
        self.assertEqual(cell_offset(553), (9 * 24, 34 * 24))

    def test_spritenums_with_the_champions_override(self):
        self.assertEqual(parse_item_spritenums(BASE, CHAMPIONS), {"lifeorb": 249, "excadrite": 553})

    def test_the_sheet_fills_in_for_missing_art(self):
        record = _build_item_record("excadrite", True, {}, {"names": [{"language": {"name": "en"}, "name": "Excadrite"}], "sprites": {"default": None}}, 553)
        self.assertEqual(record.sprite_url, f"{ITEM_SHEET_URL}#553")
        art = _build_item_record("lifeorb", True, {}, {"sprites": {"default": "https://x/life-orb.png"}}, 249)
        self.assertEqual(art.sprite_url, "https://x/life-orb.png", "PokéAPI art wins when it exists")


class TestItemIcon(unittest.TestCase):
    def test_sheet_cell_is_cropped(self):
        icon = item_icon(sheet_url(553), size=48)
        self.assertEqual(icon.clip_behavior, ft.ClipBehavior.HARD_EDGE)
        image = icon.content.controls[0]
        self.assertEqual((image.left, image.top, image.width), (-432, -1632, 768), "scaled ×2")
        serialise(icon)

    def test_plain_sprite_and_fallback(self):
        self.assertIsInstance(item_icon("https://x/life-orb.png").content, ft.Image)
        self.assertIsInstance(item_icon(None).content, ft.Icon)


class TestSyncKeepsStoredItemData(unittest.TestCase):
    def test_an_unforced_sync_keeps_pokeapi_fields(self):
        engine = create_engine("sqlite:///:memory:")
        SQLModel.metadata.create_all(engine)
        self.addCleanup(engine.dispose)
        with Session(engine) as s:
            ItemRepository(s).upsert(ItemRecord(canonical_id="life-orb", display_name="Life Orb", category="held-items", is_champions_legal=True,
                                                sprite_url="https://x/life-orb.png", short_effect="Boosts damage."))

        class Provider:
            def clear_cache(self):
                pass

            def fetch_item_records(self, existing_pokeapi_slugs, skip_pokeapi=False):
                assert "life-orb" in existing_pokeapi_slugs
                return [_build_item_record("lifeorb", True, {}, None, 249)]      # no PokéAPI data this time

            def get_champions_legal_count(self):
                return 1

            def item_spritenums(self):
                return {"lifeorb": 249}

        with Session(engine) as s, patch.object(items_catalog_service, "HybridItemProvider", Provider), \
                patch.object(items_catalog_service, "check_items_catalog_staleness", lambda _s: True):
            items_catalog_service.sync_items_catalog(s)
            record = ItemRepository(s).get("life-orb")
        self.assertEqual((record.sprite_url, record.short_effect, record.category), ("https://x/life-orb.png", "Boosts damage.", "held-items"))


if __name__ == "__main__":
    unittest.main()

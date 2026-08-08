"""Unit tests for the Showdown client, ShowdownItemAdapter, and ItemRepository."""

import shutil
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from sqlmodel import Session, SQLModel, create_engine

from pokemon_champions_planning_tool.infrastructure.database.models import ItemRecord
from pokemon_champions_planning_tool.infrastructure.database.repositories import ItemRepository
from pokemon_champions_planning_tool.infrastructure.showdown import (
    _extract_item_blocks,
    get_champions_legal_slugs,
    get_mega_stone_mappings,
    clear_showdown_cache,
)
from pokemon_champions_planning_tool.infrastructure.showdown.showdown_adapter import ShowdownItemAdapter
from pokemon_champions_planning_tool.domain.interfaces import ItemCatalogProvider


# ---------------------------------------------------------------------------
# Minimal TypeScript fixtures that mirror real Showdown file structure
# ---------------------------------------------------------------------------

_FAKE_BASE_ITEMS_TS = """
export const Items: import('../../../sim/dex-items').ModdedItemDataTable = {
    choicescarf: {
        name: "Choice Scarf",
        num: 287,
        gen: 4,
    },
    choiceband: {
        name: "Choice Band",
        num: 220,
        gen: 3,
        isNonstandard: "Past",
    },
    charizarditex: {
        name: "Charizardite X",
        megaStone: { "Charizard": "Charizard-Mega-X" },
        itemUser: ["Charizard"],
        num: 660,
        gen: 6,
        isNonstandard: "Past",
    },
    blastoisinite: {
        name: "Blastoisite",
        megaStone: { "Blastoise": "Blastoise-Mega" },
        itemUser: ["Blastoise"],
        num: 659,
        gen: 6,
        isNonstandard: "Past",
    },
    ironball: {
        name: "Iron Ball",
        num: 278,
        gen: 4,
    },
};
"""

_FAKE_CHAMPIONS_ITEMS_TS = """
export const Items: import('../../../sim/dex-items').ModdedItemDataTable = {
    choiceband: {
        inherit: true,
        isNonstandard: "Past",
    },
    charizarditex: {
        inherit: true,
        isNonstandard: null,
    },
    blastoisinite: {
        inherit: true,
        isNonstandard: null,
    },
};
"""


class TestShowdownClientParsing(unittest.TestCase):
    """Tests for the TypeScript block parser and legality resolution logic."""

    def setUp(self):
        # Always start with a clean cache so mock patches apply cleanly
        clear_showdown_cache()

    def tearDown(self):
        clear_showdown_cache()

    def test_extract_item_blocks_finds_all_items(self):
        blocks = _extract_item_blocks(_FAKE_BASE_ITEMS_TS)
        self.assertIn("choicescarf", blocks)
        self.assertIn("choiceband", blocks)
        self.assertIn("charizarditex", blocks)
        self.assertIn("ironball", blocks)

    def test_extract_item_blocks_handles_nested_megastone(self):
        blocks = _extract_item_blocks(_FAKE_BASE_ITEMS_TS)
        self.assertIn("megaStone", blocks["charizarditex"])

    @patch("pokemon_champions_planning_tool.infrastructure.showdown._fetch_base_items_ts")
    @patch("pokemon_champions_planning_tool.infrastructure.showdown._fetch_champions_items_ts")
    def test_legality_resolution(self, mock_champs, mock_base):
        mock_base.return_value = _FAKE_BASE_ITEMS_TS
        mock_champs.return_value = _FAKE_CHAMPIONS_ITEMS_TS

        legal = get_champions_legal_slugs()

        # Items with no isNonstandard in base AND not banned in champions = legal
        self.assertIn("choicescarf", legal)
        self.assertIn("ironball", legal)
        # Mega Stones overridden to null = legal
        self.assertIn("charizarditex", legal)
        self.assertIn("blastoisinite", legal)
        # Items explicitly marked Past in champions mod = illegal
        self.assertNotIn("choiceband", legal)

    @patch("pokemon_champions_planning_tool.infrastructure.showdown._fetch_base_items_ts")
    @patch("pokemon_champions_planning_tool.infrastructure.showdown._fetch_champions_items_ts")
    def test_mega_stone_mappings(self, mock_champs, mock_base):
        mock_base.return_value = _FAKE_BASE_ITEMS_TS
        mock_champs.return_value = _FAKE_CHAMPIONS_ITEMS_TS

        megas = get_mega_stone_mappings()

        self.assertIn("charizarditex", megas)
        self.assertEqual(megas["charizarditex"]["species"], "charizard")
        self.assertEqual(megas["charizarditex"]["form"], "mega-x")
        self.assertEqual(megas["charizarditex"]["mega_stone_name"], "Charizard-Mega-X")

        self.assertIn("blastoisinite", megas)
        self.assertEqual(megas["blastoisinite"]["species"], "blastoise")
        self.assertEqual(megas["blastoisinite"]["form"], "mega")

        # Non-Mega item must not appear
        self.assertNotIn("choicescarf", megas)

    @patch("pokemon_champions_planning_tool.infrastructure.showdown._fetch_base_items_ts")
    @patch("pokemon_champions_planning_tool.infrastructure.showdown._fetch_champions_items_ts")
    def test_offline_returns_empty(self, mock_champs, mock_base):
        mock_base.return_value = ""
        mock_champs.return_value = ""
        self.assertEqual(get_champions_legal_slugs(), set())
        self.assertEqual(get_mega_stone_mappings(), {})


class TestShowdownAdapterProtocol(unittest.TestCase):
    """Verifies ShowdownItemAdapter satisfies the ItemCatalogProvider protocol."""

    def test_satisfies_protocol(self):
        adapter = ShowdownItemAdapter()
        self.assertIsInstance(adapter, ItemCatalogProvider)


class TestItemRepository(unittest.TestCase):
    """Integration tests for ItemRepository against an in-memory SQLite DB."""

    def setUp(self):
        self.test_dir = tempfile.mkdtemp()
        db_file = Path(self.test_dir) / "test_items.db"
        db_url = f"sqlite:///{db_file.resolve()}"
        self.engine = create_engine(db_url, connect_args={"check_same_thread": False})
        from pokemon_champions_planning_tool.infrastructure.database import models  # noqa: F401
        SQLModel.metadata.create_all(self.engine)
        self.session = Session(self.engine)

    def tearDown(self):
        self.session.close()
        shutil.rmtree(self.test_dir)

    def _make_item(self, canonical_id="choice-scarf", legal=True) -> ItemRecord:
        return ItemRecord(
            canonical_id=canonical_id,
            display_name="Choice Scarf",
            category="choice",
            is_champions_legal=legal,
            short_effect="Boosts Speed by 50%.",
            stat_modifiers={"speed": 1.5},
        )

    def test_upsert_and_get(self):
        repo = ItemRepository(self.session)
        record = self._make_item()
        saved = repo.upsert(record)
        self.assertEqual(saved.canonical_id, "choice-scarf")
        self.assertEqual(saved.stat_modifiers, {"speed": 1.5})

        fetched = repo.get("choice-scarf")
        self.assertIsNotNone(fetched)
        self.assertEqual(fetched.display_name, "Choice Scarf")

    def test_upsert_is_idempotent(self):
        repo = ItemRepository(self.session)
        repo.upsert(self._make_item())
        repo.upsert(self._make_item())  # second upsert should not duplicate
        self.assertEqual(repo.count(), 1)

    def test_list_champions_legal(self):
        repo = ItemRepository(self.session)
        repo.upsert(self._make_item("choice-scarf", legal=True))
        repo.upsert(self._make_item("choice-band", legal=False))
        legal = repo.list_champions_legal()
        self.assertEqual(len(legal), 1)
        self.assertEqual(legal[0].canonical_id, "choice-scarf")

    def test_list_mega_stones(self):
        repo = ItemRepository(self.session)
        repo.upsert(self._make_item("choice-scarf"))
        mega = ItemRecord(
            canonical_id="charizardite-x",
            display_name="Charizardite X",
            category="mega-stones",
            is_champions_legal=True,
            short_effect="Allows Charizard to Mega Evolve.",
            target_species="charizard",
            target_form="mega-x",
            stat_modifiers={},
        )
        repo.upsert(mega)
        stones = repo.list_mega_stones()
        self.assertEqual(len(stones), 1)
        self.assertEqual(stones[0].canonical_id, "charizardite-x")

    def test_meta_staleness_sentinel(self):
        repo = ItemRepository(self.session)
        self.assertIsNone(repo.get_meta())

        repo.update_meta(159)
        meta = repo.get_meta()
        self.assertIsNotNone(meta)
        self.assertEqual(meta.total_holdable_items, 159)

        # Update should overwrite, not create a second row
        repo.update_meta(162)
        self.assertEqual(repo.get_meta().total_holdable_items, 162)


if __name__ == "__main__":
    unittest.main()

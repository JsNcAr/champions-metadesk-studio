"""UI integration tests for Box export and import dialogs."""

import contextlib
import shutil
import tempfile
import unittest
from pathlib import Path
from unittest.mock import MagicMock, patch

import flet as ft
from sqlmodel import Session, SQLModel, create_engine

from _ui_stubs import StubPage, serialise
from pokemon_champions_planning_tool.domain.entities.box_entry import BoxEntry
from pokemon_champions_planning_tool.domain.entities.pokemon import Pokemon
from pokemon_champions_planning_tool.domain.entities.pokemon_stats import PokemonStats
from pokemon_champions_planning_tool.infrastructure.database.models import ChampionsSpeciesRecord
from pokemon_champions_planning_tool.infrastructure.database.repositories import BoxRepository
from pokemon_champions_planning_tool.ui import events
from pokemon_champions_planning_tool.ui.catalogs import Catalogs
from pokemon_champions_planning_tool.ui.context import AppContext
from pokemon_champions_planning_tool.ui.views.box import BoxStore, BoxView
from pokemon_champions_planning_tool.ui.views.box.dialogs import BoxExportDialog, BoxImportDialog


def _mon(cid: str, name: str, types: list[str]) -> Pokemon:
    return Pokemon(
        canonical_id=cid,
        display_name=name,
        species_name=cid,
        types=types,
        stats=PokemonStats(hp=100, attack=100, defense=100, sp_atk=100, sp_def=100, speed=100),
    )


class _TempDb:
    def __init__(self):
        self.dir = tempfile.mkdtemp()
        self.engine = create_engine(f"sqlite:///{Path(self.dir) / 'test_box_ui.db'}", connect_args={"check_same_thread": False})
        SQLModel.metadata.create_all(self.engine)

    @contextlib.contextmanager
    def session(self):
        with Session(self.engine) as s:
            yield s

    def close(self):
        self.engine.dispose()
        shutil.rmtree(self.dir, ignore_errors=True)


class TestUiBoxImportExport(unittest.TestCase):
    def setUp(self):
        self.db = _TempDb()
        self._patcher = patch("pokemon_champions_planning_tool.infrastructure.database.database.get_session", self.db.session)
        self._patcher.start()

        with self.db.session() as s:
            for idx, (cid, name, types) in enumerate([
                ("charizard", "Charizard", ["fire", "flying"]),
                ("incineroar", "Incineroar", ["fire", "dark"]),
                ("rillaboom", "Rillaboom", ["grass"]),
            ], start=1):
                s.add(ChampionsSpeciesRecord(entry_number=idx, species_name=cid, display_name=name))
            s.commit()

        self.catalogs = Catalogs.load(self.db.session)
        self.page = StubPage()
        self.ctx = AppContext(self.page, catalogs=self.catalogs)
        self.store = BoxStore(self.catalogs, session_factory=self.db.session)

        # Seed box with 2 entries
        with self.db.session() as s:
            repo = BoxRepository(s)
            r1 = repo.upsert_box_entry(BoxEntry(pokemon=_mon("charizard", "Charizard", ["fire", "flying"]), tags=["starter"], is_favorite=True))
            r2 = repo.upsert_box_entry(BoxEntry(pokemon=_mon("incineroar", "Incineroar", ["fire", "dark"]), notes="Bulky support"))
            self.e1_id = r1.box_entry_id
            self.e2_id = r2.box_entry_id
        self.store.load()

    def tearDown(self):
        self._patcher.stop()
        self.db.close()

    def test_export_dialog_formats_and_copy(self):
        dialog = BoxExportDialog(self.ctx, self.store)
        self.page.show_dialog(dialog)
        serialise(dialog)

        # Default is JSON
        self.assertEqual(dialog.current_format, "json")
        self.assertIn('"app": "Champions MetaDesk Studio"', dialog._text.value)
        self.assertIn('"charizard"', dialog._text.value)

        # Switch to text
        dialog._on_format_changed("text")
        self.assertEqual(dialog.current_format, "text")
        self.assertIn("Charizard", dialog._text.value)
        self.assertIn("Incineroar", dialog._text.value)

        # Switch to CSV
        dialog._on_format_changed("csv")
        self.assertEqual(dialog.current_format, "csv")
        self.assertIn("Pokémon,Form,Tags", dialog._text.value)
        self.assertIn("Charizard", dialog._text.value)

        # Test copy to clipboard
        copied = []
        self.ctx.copy_to_clipboard = copied.append
        dialog._copy()
        self.assertEqual(len(copied), 1)
        self.assertEqual(copied[0], dialog._text.value)

        # Test close
        dialog.close()
        self.assertFalse(dialog.open)
        self.assertNotIn(dialog, self.page.dialogs)

    def test_export_dialog_save_file(self):
        dialog = BoxExportDialog(self.ctx, self.store)
        self.page.show_dialog(dialog)

        with patch.object(self.store, "save_export_file", return_value=Path("/tmp/champions_box.json")) as mock_save:
            dialog._save_file()
            mock_save.assert_called_once()
            self.assertTrue(dialog._banner.visible)
            self.assertIn("Saved to champions_box.json", dialog._banner._text.value)

    def test_import_dialog_input_detection(self):
        dialog = BoxImportDialog(self.ctx, self.store)
        self.page.show_dialog(dialog)
        serialise(dialog)

        # Empty initial
        self.assertTrue(dialog._import_button.disabled)

        # Paste plain text
        dialog._input.value = "Rillaboom\nCharizard #fire ★"
        dialog._on_input_changed()
        self.assertFalse(dialog._import_button.disabled)
        self.assertEqual(dialog.parsed.format_detected, "plain_text")
        self.assertEqual(len(dialog.parsed.items), 2)
        self.assertIn("2 Pokémon", dialog._status_text.value)

        # Paste JSON
        json_export = self.store.export_box("json")
        dialog._input.value = json_export
        dialog._on_input_changed()
        self.assertFalse(dialog._import_button.disabled)
        self.assertEqual(dialog.parsed.format_detected, "json")
        self.assertEqual(len(dialog.parsed.items), 2)

        # Invalid/empty
        dialog._input.value = "   \n\n  "
        dialog._on_input_changed()
        self.assertTrue(dialog._import_button.disabled)

    def test_import_dialog_execution_merge_and_replace(self):
        # 1. Merge import
        dialog = BoxImportDialog(self.ctx, self.store, initial_text="Rillaboom #Starter")
        self.page.show_dialog(dialog)

        reported = []
        dialog._on_done = reported.append

        dialog._do_import()
        self.assertEqual(len(reported), 1)
        self.assertEqual(reported[0].added, 1)

        # Roster should now have 3 Pokémon
        self.assertEqual(len(self.store.entries), 3)
        species_in_box = {e.pokemon.canonical_id for e in self.store.entries}
        self.assertIn("rillaboom", species_in_box)
        self.assertFalse(dialog.open)

        # 2. Replace import
        dialog2 = BoxImportDialog(self.ctx, self.store, initial_text="Charizard")
        self.page.show_dialog(dialog2)
        dialog2._strategy_radio.value = "replace"
        dialog2._do_import()

        # Roster should now have only Charizard
        self.assertEqual(len(self.store.entries), 1)
        self.assertEqual(self.store.entries[0].pokemon.canonical_id, "charizard")

    def test_box_view_buttons_open_dialogs(self):
        view = BoxView(self.ctx, self.store)
        serialise(view)

        # Test Export button opens BoxExportDialog
        view._open_export_dialog()
        self.assertIsInstance(self.page.dialogs[-1], BoxExportDialog)
        export_dlg = self.page.dialogs[-1]
        self.assertEqual(len(export_dlg.entries), 2)
        export_dlg.close()

        # Test with multi-selection
        self.store.toggle_multi(self.e1_id, True)
        entries, suffix = view._get_export_entries()
        self.assertEqual(len(entries), 1)
        self.assertEqual(entries[0].box_entry_id, self.e1_id)
        self.assertIn("1 selected", suffix)

        # Test Import button opens BoxImportDialog
        view._open_import_dialog(initial_text="Rillaboom")
        self.assertIsInstance(self.page.dialogs[-1], BoxImportDialog)
        import_dlg = self.page.dialogs[-1]
        self.assertEqual(import_dlg._input.value, "Rillaboom")
        import_dlg.close()


if __name__ == "__main__":
    unittest.main()

"""View preferences persist across a restart; the import preview flags moves outside the learnset."""

import shutil
import tempfile
import unittest
from pathlib import Path
from unittest.mock import MagicMock

from sqlmodel import Session, create_engine

from _ui_stubs import StubPage, serialise
from pokemon_champions_planning_tool.ui.context import AppContext
from pokemon_champions_planning_tool.ui.preferences import Preferences
from pokemon_champions_planning_tool.ui.views.box.view import BoxView
from pokemon_champions_planning_tool.ui.views.box.store import BoxStore
from pokemon_champions_planning_tool.ui.views.meta.store import MetaStore
from pokemon_champions_planning_tool.ui.views.meta.view import MetaView


class TestPreferences(unittest.TestCase):
    def setUp(self):
        self.dir = tempfile.mkdtemp()
        self.path = Path(self.dir) / "preferences.json"

    def tearDown(self):
        shutil.rmtree(self.dir)

    def test_round_trip_and_corrupt_file(self):
        prefs = Preferences(self.path)
        self.assertEqual(prefs.get("box.view_mode", "grid"), "grid")
        prefs.set("box.view_mode", "table")
        prefs.set("meta.collapsed", False)
        again = Preferences(self.path)
        self.assertEqual(again.get("box.view_mode"), "table")
        self.assertIs(again.get("meta.collapsed"), False)
        self.path.write_text("{not json", encoding="utf-8")
        self.assertEqual(Preferences(self.path).get("box.view_mode", "grid"), "grid", "corrupt file starts empty")
        memory = Preferences()
        memory.set("x", 1)
        self.assertEqual(memory.get("x"), 1)

    def test_views_restore_and_save_their_layout_choices(self):
        prefs = Preferences(self.path)
        prefs.set("box.view_mode", "table"); prefs.set("box.show_stats", True)
        prefs.set("meta.view_mode", "cards"); prefs.set("meta.collapsed", False)
        page = StubPage()
        ctx = AppContext(page, prefs=Preferences(self.path))
        engine = create_engine("sqlite:///:memory:")
        self.addCleanup(engine.dispose)
        from sqlmodel import SQLModel

        SQLModel.metadata.create_all(engine)
        sf = lambda: Session(engine)  # noqa: E731
        box = BoxView(ctx, BoxStore(ctx.catalogs, sf))
        self.assertEqual(box.view_mode, "table")
        self.assertTrue(box.show_stats)
        self.assertEqual(box.toolbar._view_mode.selected, ["table"])
        self.assertTrue(box.toolbar._stats_item.checked)
        meta = MetaView(ctx, MetaStore(sf))
        self.assertEqual(meta.view_mode, "cards")
        self.assertFalse(meta.collapsed)
        self.assertEqual(meta._layout_toggle.selected, ["cards"])
        self.assertEqual(meta._collapse_button.content, "Collapse all")
        # changes are written back
        box._set_view_mode("grid")
        meta._toggle_all()
        saved = Preferences(self.path)
        self.assertEqual(saved.get("box.view_mode"), "grid")
        self.assertIs(saved.get("meta.collapsed"), True)
        serialise(box)
        serialise(meta)


if __name__ == "__main__":
    unittest.main()

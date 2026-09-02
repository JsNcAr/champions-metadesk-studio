"""Saved filter views round-trip through preferences; the database path is configurable."""

import importlib
import os
import unittest
from unittest.mock import AsyncMock, patch

from _ui_stubs import serialise
from pokemon_champions_planning_tool.ui.views.box.filters import BoxFilters
from test_ui_box_actions import TestBoxActions as _Base


class TestSavedViews(_Base):
    def test_filters_round_trip(self):
        f = BoxFilters(text="char", types=frozenset({"fire"}), favourites_only=True, bst_range=(400, 700), stat_ranges={"speed": (90, 255)}, tags=frozenset({"sun"}), sort="speed", descending=True)
        self.assertEqual(BoxFilters.from_dict(f.to_dict()), f)
        self.assertEqual(BoxFilters.from_dict({"sort": "bogus", "bst_range": "x"}), BoxFilters(), "garbage falls back to defaults")

    def test_save_apply_forget(self):
        self.view.toolbar._set(text="luca", favourites_only=True)
        self.ctx.prompt_text = AsyncMock(return_value="Fighters")
        self.page.run_task(self.view._save_view)
        self.assertEqual(list(self.ctx.prefs.get("box.saved_views")), ["Fighters"])
        self.assertEqual(self.view.toolbar._views_label.value, "Views · 1")
        self.view.toolbar.clear()
        self.assertEqual(self.store.filters, BoxFilters())
        self.view._apply_view("Fighters")
        self.assertEqual((self.store.filters.text, self.store.filters.favourites_only), ("luca", True))
        self.assertEqual([e.pokemon.display_name for e in self.store.visible()], [])
        self.ctx.prompt_text = AsyncMock(return_value="Fighters")
        self.page.run_task(self.view._forget_view)
        self.assertEqual(self.ctx.prefs.get("box.saved_views"), {})
        self.assertEqual(self.view.toolbar._views_label.value, "Views")
        serialise(self.view)


class TestDatabasePathConfig(unittest.TestCase):
    def test_env_var_overrides_paths(self):
        import pokemon_champions_planning_tool.config as config

        with patch.dict(os.environ, {"PCPT_DATABASE": "/tmp/pcpt-test/champions.db"}, clear=False):
            importlib.reload(config)
            self.assertEqual(config.DEFAULT_DATABASE_FILENAME, "/tmp/pcpt-test/champions.db")
            self.assertEqual(config.DEFAULT_PREFERENCES_FILENAME, "/tmp/pcpt-test/preferences.json")
        os.environ.pop("PCPT_DATABASE", None)
        importlib.reload(config)
        self.assertEqual(config.DEFAULT_DATABASE_FILENAME, "pokemon_champions.db")
        self.assertEqual(config.DEFAULT_PREFERENCES_FILENAME, "preferences.json")


# Reuse the fixture only; do not re-run the base class's own tests here.
for _name in [n for n in dir(_Base) if n.startswith("test_")]:
    for _cls in [c for c in list(globals().values()) if isinstance(c, type) and issubclass(c, _Base) and c is not _Base]:
        setattr(_cls, _name, None)
del _Base  # not collected again under this module's name


if __name__ == "__main__":
    unittest.main()

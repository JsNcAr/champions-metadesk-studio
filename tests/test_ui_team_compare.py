"""Compare teams dialog and TeamStore.summary_for."""

import unittest
from unittest.mock import MagicMock

from _ui_stubs import StubPage, serialise
from pokemon_champions_planning_tool.ui.context import AppContext
from pokemon_champions_planning_tool.ui.views.team.dialogs.compare import CompareDialog
from test_move_catalog import TestLegalityInTeamBuilder as _Base


class TestCompare(_Base):
    def test_summary_for_other_team_and_dialog(self):
        self.store.set_move(1, 0, "Heat Wave")
        first = self.store.active_team_id
        self.store.create_team("Rain")
        self.store.assign(1, self.charizard)
        self.assertEqual(self.store.active_team_name, "Rain")
        name, slots, summary = self.store.summary_for(first)
        self.assertEqual(name, "Sun")
        self.assertEqual(summary.filled, 1)
        self.assertEqual(slots[0].damaging_types, ["fire"])
        self.assertEqual(self.store.active_team_name, "Rain", "comparison never switches the active team")
        dialog = CompareDialog(self.store, on_close=lambda: None)
        self.assertEqual(dialog._left._name.value, "Rain")
        self.assertEqual(dialog._right._name.value, "Sun")
        self.assertIn("Uncovered", dialog._right._coverage.value)
        self.assertEqual(dialog._left._coverage.value, "Coverage: no damaging moves assigned")
        serialise(dialog)

    def test_view_menu_opens_compare(self):
        from pokemon_champions_planning_tool.ui.views.team.view import TeamView

        page = StubPage()
        view = TeamView(AppContext(page, catalogs=self.catalogs), self.store)
        view.ensure_loaded()
        view._open_compare()
        self.assertIsInstance(page.dialogs[-1], CompareDialog)
        self.assertEqual(page.dialogs[-1]._picker.options, [], "only one team: nothing to compare with")


# Reuse the fixture only; do not re-run the base class's own tests here.
for _name in [n for n in dir(_Base) if n.startswith("test_")]:
    for _cls in [c for c in list(globals().values()) if isinstance(c, type) and issubclass(c, _Base) and c is not _Base]:
        setattr(_cls, _name, None)


if __name__ == "__main__":
    unittest.main()

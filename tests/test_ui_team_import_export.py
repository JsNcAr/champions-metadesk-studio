"""Import dialog steps, export dialog, and the store's import/export methods."""

import contextlib
import shutil
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from sqlmodel import Session, SQLModel, create_engine

from _ui_stubs import StubPage, serialise
from pokemon_champions_planning_tool.domain.entities.box_entry import BoxEntry
from pokemon_champions_planning_tool.domain.entities.pokemon import Pokemon
from pokemon_champions_planning_tool.domain.entities.pokemon_stats import PokemonStats
from pokemon_champions_planning_tool.infrastructure.database.models import ChampionsSpeciesRecord
from pokemon_champions_planning_tool.infrastructure.database.repositories import BoxRepository
from pokemon_champions_planning_tool.services.showdown_service import ShowdownExportResult
from pokemon_champions_planning_tool.ui import events
from pokemon_champions_planning_tool.ui.catalogs import Catalogs
from pokemon_champions_planning_tool.ui.context import AppContext
from pokemon_champions_planning_tool.ui.views.team import TeamStore
from pokemon_champions_planning_tool.ui.views.team.dialogs.export_dialog import ExportDialog
from pokemon_champions_planning_tool.ui.views.team.dialogs.import_dialog import ImportDialog
from pokemon_champions_planning_tool.ui.views.team.view import TeamView

PASTE = """Incineroar @ Safety Goggles
Ability: Intimidate
Tera Type: Grass
- Fake Out
- Knock Off

Rillaboom @ Assault Vest
Ability: Grassy Surge
- Grassy Glide
- Fake Out
"""


class _TempDb:
    def __init__(self):
        self.dir = tempfile.mkdtemp()
        self.engine = create_engine(f"sqlite:///{Path(self.dir) / 'imp.db'}", connect_args={"check_same_thread": False})
        SQLModel.metadata.create_all(self.engine)

    @contextlib.contextmanager
    def session(self):
        with Session(self.engine) as s:
            yield s

    def close(self):
        self.engine.dispose()
        shutil.rmtree(self.dir)


def _mon(cid, name, types):
    return Pokemon(canonical_id=cid, display_name=name, species_name=cid, types=types, stats=PokemonStats(hp=80, attack=80, defense=80, sp_atk=80, sp_def=80, speed=80))


class TestImportExport(unittest.TestCase):
    def setUp(self):
        self.db = _TempDb()
        with self.db.session() as s:
            BoxRepository(s).upsert_box_entry(BoxEntry(pokemon=_mon("incineroar", "Incineroar", ["fire", "dark"])))
            for i, name in enumerate(["incineroar", "rillaboom"], start=1):
                s.add(ChampionsSpeciesRecord(entry_number=i, species_name=name, display_name=name.title()))
            s.commit()
        self.page = StubPage()
        self.ctx = AppContext(self.page, catalogs=Catalogs.load(self.db.session))
        self.ctx.run_in_background = lambda work, on_done=None, on_error=None, **kw: on_done(work()) if on_done else work()
        self.store = TeamStore(self.ctx.catalogs, self.db.session)
        self.store.load()

    def tearDown(self):
        self.db.close()

    def test_store_readiness_and_import(self):
        parsed = self.store.parse(PASTE)
        r = self.store.readiness(parsed)
        self.assertEqual([s.species_name for s in r.in_box], ["Incineroar"])
        self.assertEqual([s.species_name for s in r.missing] + [s.species_name for s in r.unresolvable], ["Rillaboom"])
        result = self.store.import_parsed(parsed, use_planned=True, team_name="Rain")
        self.assertEqual(result.reused, ("Incineroar",))
        self.assertEqual(result.created_planned, ("Rillaboom",))
        self.assertEqual(self.store.active_team_name, "Rain")
        self.assertTrue(self.store.slot(2).is_planned)
        self.assertEqual(self.store.slot(1).member.tera_type, "grass")

    def test_dialog_walks_paste_preview_readiness_done(self):
        dialog = ImportDialog(self.ctx, self.store, initial_text="", initial_title="")
        self.assertEqual(dialog.step, 0)
        self.assertTrue(dialog._next.disabled)
        dialog._input.value = PASTE
        dialog._input_changed()
        self.assertFalse(dialog._next.disabled)
        dialog._advance()
        self.assertEqual(dialog.step, 1)
        self.assertEqual(len(dialog._preview.controls), 2)
        serialise(dialog)
        dialog._team_name.value = "Rain"
        dialog._advance()
        self.assertEqual(dialog.step, 2, "one species missing -> readiness step")
        self.assertIn("1 missing", dialog._readiness_summary.value)
        emitted = []
        self.ctx.bus.on(events.TEAMS_CHANGED, emitted.append)
        dialog._choose(True)
        dialog._advance()
        self.assertEqual(dialog.step, 3)
        self.assertIsNotNone(dialog.result_team_id)
        self.assertEqual(emitted, [dialog.result_team_id])
        self.assertTrue(self.store.slot(2).is_planned)
        self.assertTrue(dialog._cancel.visible, "Close button must be visible on the done step")
        self.assertEqual(dialog._cancel.content, "Close")
        self.assertEqual(dialog._next.content, "Open team")
        self.assertFalse(dialog.modal, "Modal should be non-blocking on the done step")
        serialise(dialog)
        dialog.close()
        self.assertFalse(dialog.open)

    def test_all_in_box_skips_readiness_and_illegal_blocks(self):
        with self.db.session() as s:
            BoxRepository(s).upsert_box_entry(BoxEntry(pokemon=_mon("rillaboom", "Rillaboom", ["grass"])))
        dialog = ImportDialog(self.ctx, self.store, initial_text=PASTE, initial_title="Sun")
        self.assertEqual(dialog.step, 1, "prefilled text starts at the preview")
        dialog._advance()
        self.assertEqual(dialog.step, 3, "nothing missing -> imported directly")
        blocked = ImportDialog(self.ctx, self.store, initial_text="Pikachu\n- Thunderbolt\n", initial_title="")
        blocked._advance()
        self.assertEqual(blocked.step, 2)
        self.assertTrue(blocked._next.disabled)
        self.assertTrue(blocked._readiness_banner.visible)

    def test_dialog_advance_on_done_step_invokes_on_done_and_closes(self):
        called = []
        dialog = ImportDialog(self.ctx, self.store, initial_text=PASTE, initial_title="Sun", on_done=called.append)
        dialog._advance()
        self.assertEqual(dialog.step, 2)
        dialog._choose(True)
        dialog._advance()
        self.assertEqual(dialog.step, 3)
        self.page.show_dialog(dialog)
        self.ctx.toast("Imported Sun", "success")
        dialog._advance()
        self.assertEqual(called, [dialog.result_team_id])
        self.assertFalse(dialog.open)
        self.assertNotIn(dialog, self.page.dialogs)

    def test_dialog_cancel_clicked_on_done_step_closes_dialog_and_toasts(self):
        dialog = ImportDialog(self.ctx, self.store, initial_text=PASTE, initial_title="Sun")
        dialog._advance()
        dialog._choose(True)
        dialog._advance()
        self.assertEqual(dialog.step, 3)
        self.page.show_dialog(dialog)
        self.assertEqual(dialog._cancel.content, "Close")
        dialog._cancel_clicked()
        self.assertFalse(dialog.open)
        self.assertNotIn(dialog, self.page.dialogs)

    def test_view_opens_import_on_bus_and_export_dialog(self):
        view = TeamView(self.ctx, self.store)
        self.ctx.bus.emit(events.IMPORT_REQUESTED, (PASTE, "Player — Event"))
        self.assertIsInstance(self.page.dialogs[-1], ImportDialog)
        self.assertEqual(self.page.dialogs[-1]._team_name.value, "Player — Event")
        self.store.create_team("Sun")
        view._open_export()
        dialog = self.page.dialogs[-1]
        self.assertIsInstance(dialog, ExportDialog)
        serialise(dialog)
        with patch.object(self.store, "publish", return_value=ShowdownExportResult(team_id="x", team_name="Sun", showdown_text="", pokepast_url="https://pokepast.es/abc")):
            dialog._do_publish()
        self.assertTrue(dialog._link.visible)
        self.assertEqual(dialog.url, "https://pokepast.es/abc")


if __name__ == "__main__":
    unittest.main()

"""Settings store against a temporary database, and the view serialised headlessly."""

import contextlib
import shutil
import tempfile
import unittest
from datetime import datetime, timezone
from pathlib import Path
from unittest.mock import patch

import flet as ft
from sqlmodel import Session, SQLModel, create_engine

from _ui_stubs import StubPage, serialise
from pokemon_champions_planning_tool.infrastructure.database.models import (
    ItemCatalogMetaRecord,
    ItemRecord,
    MegaEvolutionRecord,
    TournamentRecord,
    TournamentTeamRecord,
)
from pokemon_champions_planning_tool.ui import events
from pokemon_champions_planning_tool.ui.context import AppContext
from pokemon_champions_planning_tool.ui.format import relative_time
from pokemon_champions_planning_tool.ui.views.settings import SettingsStore, SettingsView


class _TempDb:
    def __init__(self):
        self.dir = tempfile.mkdtemp()
        self.engine = create_engine(f"sqlite:///{Path(self.dir) / 'settings.db'}", connect_args={"check_same_thread": False})
        SQLModel.metadata.create_all(self.engine)

    @contextlib.contextmanager
    def session(self):
        with Session(self.engine) as s:
            yield s

    def close(self):
        self.engine.dispose()
        shutil.rmtree(self.dir)


class TestSettingsStore(unittest.TestCase):
    def setUp(self):
        self.db = _TempDb()
        self.store = SettingsStore(self.db.session)

    def tearDown(self):
        self.db.close()

    def test_empty_database_reports_zero_and_never(self):
        status = self.store.status()
        self.assertEqual((status.mega_count, status.item_count, status.tournament_count, status.tournament_team_count), (0, 0, 0, 0))
        self.assertIsNone(status.items_synced_at)
        self.assertIsNone(status.tournaments_synced_at)

    def test_counts_and_last_synced(self):
        synced = datetime(2026, 8, 24, 14, 41, tzinfo=timezone.utc)
        with self.db.session() as s:
            s.add(MegaEvolutionRecord(canonical_id="lucario-mega", species_name="lucario", display_name="Mega Lucario",
                                      types=["fighting", "steel"], hp=70, attack=145, defense=88, special_attack=140, special_defense=70, speed=112))
            s.add(ItemRecord(canonical_id="choice-band", display_name="Choice Band", category="held", is_champions_legal=True, stat_modifiers={"attack": 1.5}))
            s.add(ItemCatalogMetaRecord(id=1, total_holdable_items=1, last_synced_at=synced))
            s.add(TournamentRecord(tournament_id="t1", name="Cup", format_regulation="Regulation M-A", standings_synced=True, updated_at=synced))
            s.add(TournamentRecord(tournament_id="t2", name="Pending", format_regulation="Regulation M-A", standings_synced=False))
            s.commit()
            s.add(TournamentTeamRecord(tournament_id="t1", player_name="p", placement=1, showdown_text="x"))
            s.commit()
        status = self.store.status()
        self.assertEqual((status.mega_count, status.item_count, status.tournament_count, status.tournament_team_count), (1, 1, 2, 1))
        self.assertEqual(status.items_synced_at.replace(tzinfo=None), synced.replace(tzinfo=None))
        self.assertEqual(status.tournaments_synced_at.replace(tzinfo=None), synced.replace(tzinfo=None), "only synced tournaments count")

    def test_sync_methods_delegate_to_services_in_their_own_session(self):
        calls = []
        with patch("pokemon_champions_planning_tool.ui.views.settings.store.sync_all_champions_megas_on_startup", side_effect=lambda s: calls.append(("megas", s)) or {"added": 2, "total_local": 5}), \
             patch("pokemon_champions_planning_tool.ui.views.settings.store.sync_items_catalog", side_effect=lambda s, force: calls.append(("items", force)) or {"added": 1, "updated": 0, "total": 3}), \
             patch("pokemon_champions_planning_tool.ui.views.settings.store.TournamentService") as svc:
            svc.return_value.sync.return_value = {"status": "synced", "limitless": {"added": 4}, "victory_road": {"added": 0}}
            self.assertEqual(self.store.sync_megas()["total_local"], 5)
            self.assertEqual(self.store.sync_items()["total"], 3)
            self.assertEqual(self.store.sync_tournaments()["status"], "synced")
        self.assertEqual(calls[0][0], "megas")
        self.assertEqual(calls[1], ("items", True), "manual item sync forces a refresh")
        svc.return_value.sync.assert_called_once_with(force=True, max_age_days=365, include_official=True)


class TestRelativeTime(unittest.TestCase):
    def test_buckets(self):
        now = datetime(2026, 9, 1, 12, 0, tzinfo=timezone.utc)
        mk = lambda **kw: relative_time(now - __import__("datetime").timedelta(**kw), now=now)
        self.assertEqual(relative_time(None), "never")
        self.assertEqual(mk(seconds=5), "just now")
        self.assertEqual(mk(minutes=5), "5m ago")
        self.assertEqual(mk(hours=2), "2h ago")
        self.assertEqual(mk(days=3), "3d ago")
        self.assertTrue(mk(days=40).endswith("2026"))


class TestSettingsView(unittest.TestCase):
    def setUp(self):
        self.db = _TempDb()
        self.page = StubPage()
        self.ctx = AppContext(self.page)
        self.view = SettingsView(self.ctx, SettingsStore(self.db.session))

    def tearDown(self):
        self.db.close()

    def test_builds_and_serialises(self):
        self.view.refresh()
        self.assertGreater(serialise(self.view), 30)
        self.assertEqual(self.view.row_megas._status.value, "Never synced")

    def test_sync_success_updates_row_toasts_and_emits(self):
        emitted = []
        self.ctx.bus.on(events.CATALOGS_RELOADED, emitted.append)
        with patch.object(self.view.store, "sync_items", return_value={"added": 3, "updated": 1, "total": 148}):
            self.view._sync("items")
        self.assertEqual(emitted, ["items"])
        self.assertEqual(self.view.row_items._result.value, "+3 added · 1 updated")
        self.assertFalse(self.view.row_items.button.disabled)
        self.assertFalse(self.view.row_items.spinner.visible)
        self.assertEqual(len(self.page.dialogs), 1, "one success toast")
        self.assertIsInstance(self.page.dialogs[0], ft.SnackBar)

    def test_sync_failure_marks_row_and_does_not_emit(self):
        emitted = []
        self.ctx.bus.on(events.CATALOGS_RELOADED, emitted.append)
        with patch.object(self.view.store, "sync_megas", side_effect=RuntimeError("offline")):
            self.view._sync("megas")
        self.assertEqual(emitted, [])
        self.assertEqual(self.view.row_megas._result.value, "Sync failed")
        self.assertFalse(self.view.row_megas.button.disabled)

    def test_meta_synced_event_refreshes_counts(self):
        with self.db.session() as s:
            s.add(TournamentRecord(tournament_id="t1", name="Cup", format_regulation="Regulation M-A", standings_synced=True))
            s.commit()
        self.ctx.bus.emit(events.META_SYNCED, {})
        self.assertIn("1 event", self.view.row_tournaments._status.value)


if __name__ == "__main__":
    unittest.main()

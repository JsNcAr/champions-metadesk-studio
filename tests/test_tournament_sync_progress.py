"""Sync progress reporting, single-flight lock, batched writes, WAL pragmas, UI indicators."""

import sqlite3
import tempfile
import threading
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path
from unittest.mock import MagicMock, patch

from sqlmodel import Session, SQLModel, create_engine, select

from _ui_stubs import StubPage, serialise
from pokemon_champions_planning_tool.infrastructure.database import database
from pokemon_champions_planning_tool.infrastructure.database.models import TournamentRecord, TournamentTeamMemberRecord, TournamentTeamRecord
from pokemon_champions_planning_tool.infrastructure.database.repositories import TournamentRepository
from pokemon_champions_planning_tool.infrastructure.providers import LimitlessStanding, LimitlessTeamMember, LimitlessTournament
from pokemon_champions_planning_tool.services import tournament_sync_service as sync_mod
from pokemon_champions_planning_tool.services.tournament_sync_service import SyncProgress, summarize_sync_result, sync_tournaments
from pokemon_champions_planning_tool.ui import events
from pokemon_champions_planning_tool.ui.context import AppContext


def _standing():
    return LimitlessStanding(player_handle="p", placement=1, members=(LimitlessTeamMember(canonical_id="incineroar", display_name="Incineroar", moves=("Fake Out",)),))


def _limitless(tournaments, served):
    provider = MagicMock()
    provider.fetch_champions_tournaments.return_value = tournaments

    def _batch(tournament_ids, max_placement=None, max_requests=20, on_progress=None, **kwargs):
        out = {}
        for i, t in enumerate(tournament_ids[:max_requests], start=1):
            if on_progress:
                on_progress(i, min(len(tournament_ids), max_requests), t)
            out[t] = [_standing()] if t in served else []
        return out

    provider.fetch_standings_batch.side_effect = _batch
    return provider


class _DbCase(unittest.TestCase):
    def setUp(self):
        self.engine = create_engine("sqlite:///:memory:")
        SQLModel.metadata.create_all(self.engine)
        self.addCleanup(self.engine.dispose)
        self.session = Session(self.engine)
        patch.object(sync_mod.time, "sleep").start()
        self.addCleanup(patch.stopall)

    def tearDown(self):
        self.session.close()


class TestProgressAndLock(_DbCase):
    def test_progress_phases_in_order_with_totals(self):
        old = datetime.now(timezone.utc) - timedelta(days=10)
        tournaments = [LimitlessTournament(id=f"t{i}", name=f"Cup {i}", date=old, format_code="M-B", player_count=8) for i in range(3)]
        seen: list[SyncProgress] = []
        res = sync_tournaments(self.session, limitless_provider=_limitless(tournaments, served={"t0", "t1", "t2"}), include_official=False, on_progress=seen.append)
        phases = [p.phase for p in seen]
        self.assertEqual(phases[0], "listing")
        self.assertIn("standings", phases)
        self.assertEqual(phases[-1], "done")
        fetching = [p for p in seen if p.message.startswith("Fetching standings")]
        self.assertEqual([(p.done, p.total) for p in fetching], [(0, 3), (1, 3), (2, 3)])
        self.assertEqual(seen[-1].teams_added, 3)
        self.assertEqual(seen[-1].fraction, None)
        self.assertFalse(seen[-1].running)
        self.assertEqual(summarize_sync_result(res), "Synced · 3 new teams · 3 events")

    def test_second_sync_while_one_runs_returns_busy(self):
        started, release = threading.Event(), threading.Event()
        provider = MagicMock()

        def _slow_listing(**kwargs):
            started.set()
            release.wait(5)
            return []

        provider.fetch_champions_tournaments.side_effect = _slow_listing
        provider.fetch_standings_batch.return_value = {}
        # The worker only needs to hold the lock while the listing blocks; a mock
        # session keeps it off this thread's in-memory database.
        worker = threading.Thread(target=lambda: sync_tournaments(MagicMock(), limitless_provider=provider, include_official=False))
        worker.start()
        started.wait(5)
        seen = []
        res = sync_tournaments(self.session, limitless_provider=MagicMock(), include_official=False, on_progress=seen.append)
        self.assertEqual(res["status"], "busy")
        self.assertEqual([p.phase for p in seen], ["busy"])
        self.assertTrue(sync_mod.sync_in_progress())
        release.set()
        worker.join(5)
        self.assertFalse(sync_mod.sync_in_progress())


class TestBatchedWritesAndWindow(_DbCase):
    def test_save_teams_is_one_transaction(self):
        repo = TournamentRepository(self.session)
        self.session.add(TournamentRecord(tournament_id="x", name="X", event_date=datetime.now(timezone.utc), format_regulation="Regulation M-B", game_platform="Pokémon Champions"))
        self.session.commit()
        entries = []
        for i in range(5):
            team = TournamentTeamRecord(tournament_id="x", player_name=f"p{i}", placement=i + 1, showdown_text="Incineroar\n")
            entries.append((team, [TournamentTeamMemberRecord(slot_position=1, canonical_id="incineroar", species_name="Incineroar")]))
        with patch.object(self.session, "commit", wraps=self.session.commit) as commit:
            self.assertEqual(repo.save_teams(entries), 5)
            self.assertEqual(commit.call_count, 1)
        members = self.session.exec(select(TournamentTeamMemberRecord)).all()
        self.assertEqual(len(members), 5)
        self.assertEqual({m.tournament_team_id for m in members}, {t.tournament_team_id for t, _ in entries})

    def test_pending_backlog_ignores_events_outside_the_window(self):
        now = datetime.now(timezone.utc)
        for tid, days in (("limitless-old", 400), ("limitless-new", 5)):
            self.session.add(TournamentRecord(tournament_id=tid, name=tid, event_date=now - timedelta(days=days), format_regulation="Regulation M-B", game_platform="Pokémon Champions", standings_synced=False))
        self.session.commit()
        repo = TournamentRepository(self.session)
        self.assertEqual(repo.list_tournament_ids_pending_standings(since=now - timedelta(days=365)), {"limitless-new"})
        provider = _limitless([], served={"new", "old"})
        sync_tournaments(self.session, limitless_provider=provider, include_official=False)
        requested = [c.kwargs.get("tournament_ids") or c.args[0] for c in provider.fetch_standings_batch.call_args_list]
        self.assertEqual(requested, [["new"]], "the year-old event is not fetched")


class TestSqlitePragmas(unittest.TestCase):
    def test_engine_uses_wal_and_busy_timeout(self):
        tmp = tempfile.mkdtemp()
        path = str(Path(tmp) / "pragmas.db")
        database.reset_engines()
        try:
            database.initialize_database(path)
            conn = sqlite3.connect(path)
            self.assertEqual(conn.execute("PRAGMA journal_mode").fetchone()[0].lower(), "wal")
            conn.close()
        finally:
            database.reset_engines()


class TestIndicators(unittest.TestCase):
    def test_meta_and_settings_follow_progress_events(self):
        from pokemon_champions_planning_tool.ui.views.meta.view import MetaView
        from pokemon_champions_planning_tool.ui.views.meta.store import MetaStore
        from pokemon_champions_planning_tool.ui.views.settings.view import SettingsView

        page = StubPage()
        ctx = AppContext(page)
        engine = create_engine("sqlite:///:memory:")
        self.addCleanup(engine.dispose)
        meta = MetaView(ctx, MetaStore(lambda: Session(engine)))
        settings = SettingsView(ctx)
        ctx.bus.emit(events.SYNC_PROGRESS, SyncProgress("standings", "Fetching standings 3 of 40", done=2, total=40, teams_added=120))
        self.assertTrue(meta.sync_indicator.visible)
        self.assertEqual(meta.sync_indicator._text.value, "Fetching standings 3 of 40 · 120 teams")
        self.assertAlmostEqual(meta.sync_indicator._bar.value, 0.05)
        self.assertTrue(meta._sync_button.disabled)
        self.assertTrue(settings.row_tournaments._bar.visible)
        self.assertTrue(settings.row_tournaments.button.disabled)
        ctx.bus.emit(events.SYNC_PROGRESS, SyncProgress("done", "Synced · 1,970 new teams · 40 events"))
        self.assertFalse(meta._sync_button.disabled)
        self.assertFalse(meta.sync_indicator._ring.visible)
        self.assertFalse(settings.row_tournaments._bar.visible)
        serialise(meta)
        serialise(settings)

    def test_context_relays_progress_from_the_worker(self):
        page = StubPage()
        ctx = AppContext(page)
        seen = []
        ctx.bus.on(events.SYNC_PROGRESS, seen.append)
        done = []
        ctx.sync_tournaments(lambda relay: (relay(SyncProgress("listing", "Listing…")), {"status": "synced"})[1], on_done=done.append)
        self.assertEqual([p.phase for p in seen], ["listing"])
        self.assertEqual(done, [{"status": "synced"}])


if __name__ == "__main__":
    unittest.main()

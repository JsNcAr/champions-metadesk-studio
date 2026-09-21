"""Request budget and reliability of the tournament sync: retries, incremental listing,
rate budget, unfinished events, Victory Road resume, and the launch-time throttle."""

import unittest
from datetime import datetime, timedelta, timezone
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

import requests
from sqlmodel import Session, SQLModel, create_engine, select

from pokemon_champions_planning_tool.infrastructure.database.models import TournamentRecord, TournamentTeamMemberRecord, TournamentTeamRecord
from pokemon_champions_planning_tool.infrastructure.providers import (
    LimitlessStanding,
    LimitlessTeamMember,
    LimitlessTournament,
    VREventResult,
    VRStandingRef,
)
from pokemon_champions_planning_tool.infrastructure.providers.limitless_provider import LimitlessNetworkError, LimitlessProvider
from pokemon_champions_planning_tool.services import tournament_sync_service as sync_mod
from pokemon_champions_planning_tool.services.tournament_sync_service import startup_sync_due, sync_tournaments

MOD = "pokemon_champions_planning_tool.infrastructure.providers.limitless_provider"


def _response(status=200, payload=None, headers=None):
    resp = SimpleNamespace(status_code=status, headers=headers or {}, _payload=payload)

    def raise_for_status():
        if status >= 400:
            raise requests.exceptions.HTTPError(f"HTTP {status}")

    resp.raise_for_status = raise_for_status
    resp.json = lambda: resp._payload
    return resp


class TestProviderRetries(unittest.TestCase):
    def setUp(self):
        self.provider = LimitlessProvider()
        self.sleep = patch(f"{MOD}.time.sleep").start()
        self.addCleanup(patch.stopall)

    def test_404_is_not_retried(self):
        get = patch(f"{MOD}.requests.get", return_value=_response(404)).start()
        with self.assertRaises(LimitlessNetworkError):
            self.provider._get("/tournaments/x/standings")
        self.assertEqual(get.call_count, 1)

    def test_5xx_then_success_is_retried_once(self):
        get = patch(f"{MOD}.requests.get", side_effect=[_response(503), _response(200, [1])]).start()
        self.assertEqual(self.provider._get("/tournaments"), [1])
        self.assertEqual(get.call_count, 2)

    def test_429_waits_for_the_window_reset(self):
        get = patch(f"{MOD}.requests.get", side_effect=[
            _response(429, headers={"ratelimit": '"50-in-5min"; r=0; t=17'}),
            _response(200, [], headers={"ratelimit": '"50-in-5min"; r=49; t=300'}),
        ]).start()
        self.provider._get("/tournaments")
        self.assertEqual(get.call_count, 2)
        self.assertEqual(self.sleep.call_args[0][0], 17.0)
        self.assertEqual(self.provider.rate_remaining, 49)
        self.assertEqual(self.provider.budget, 49 - self.provider.rate_reserve)


class TestIncrementalListing(unittest.TestCase):
    def setUp(self):
        patch(f"{MOD}.time.sleep").start()
        self.addCleanup(patch.stopall)
        self.now = datetime.now(timezone.utc)

    def _item(self, i):
        return {"id": f"t{i}", "name": f"Cup {i}", "date": (self.now - timedelta(days=i)).isoformat(), "format": "M-B", "players": 20}

    def test_stops_at_the_first_page_of_known_tournaments(self):
        pages = {1: [self._item(i) for i in range(200)], 2: [self._item(i) for i in range(200, 400)], 3: []}
        get = patch(f"{MOD}.requests.get", side_effect=lambda url, params=None, **kw: _response(200, pages[params["page"]])).start()
        provider = LimitlessProvider()
        # Everything on page 1 known -> one request.
        got = provider.fetch_champions_tournaments(known_ids={f"t{i}" for i in range(200)})
        self.assertEqual(get.call_count, 1)
        self.assertEqual(len(got), 200)
        # One unknown on page 1 -> page 2 is read, which is all known -> stop at 2.
        get.reset_mock()
        provider.fetch_champions_tournaments(known_ids={f"t{i}" for i in range(1, 400)})
        self.assertEqual(get.call_count, 2)
        # Nothing known (first sync) -> pages until the short/empty one.
        get.reset_mock()
        provider.fetch_champions_tournaments(known_ids=set(), max_age_days=1000)
        self.assertEqual(get.call_count, 3)

    def test_standings_batch_stops_when_the_budget_is_spent(self):
        provider = LimitlessProvider()
        provider.rate_remaining = provider.rate_reserve + 2
        calls = []

        def fake_standings(t_id, max_placement=None, raise_on_error=False):
            calls.append(t_id)
            provider.rate_remaining -= 1
            return []

        provider.fetch_standings = fake_standings
        provider.fetch_standings_batch(["a", "b", "c", "d"], max_requests=10, delay_between=0)
        self.assertEqual(calls, ["a", "b"])
        self.assertEqual(provider.last_batch_stop, "rate")


class _DbCase(unittest.TestCase):
    def setUp(self):
        self.engine = create_engine("sqlite:///:memory:")
        SQLModel.metadata.create_all(self.engine)
        self.addCleanup(self.engine.dispose)
        self.session = Session(self.engine)
        patch.object(sync_mod, "_PASTE_DELAY_S", 0).start()
        patch.object(sync_mod.time, "sleep").start()
        self.addCleanup(patch.stopall)

    def tearDown(self):
        self.session.close()

    def _standing(self):
        return LimitlessStanding(player_handle="p", placement=1, members=(LimitlessTeamMember(canonical_id="incineroar", display_name="Incineroar", moves=("Fake Out",)),))

    def _limitless(self, tournaments, served):
        provider = MagicMock()
        provider.fetch_champions_tournaments.return_value = tournaments
        provider.requested = []

        def _batch(tournament_ids, max_placement=None, max_requests=20, **kwargs):
            provider.requested.extend(tournament_ids[:max_requests])
            return {t: [self._standing()] if t in served else [] for t in tournament_ids[:max_requests]}

        provider.fetch_standings_batch.side_effect = _batch
        return provider

    def _records(self):
        return {t.tournament_id: t for t in self.session.exec(select(TournamentRecord)).all()}


class TestUnfinishedEvents(_DbCase):
    def test_future_events_are_not_requested_and_recent_empty_ones_are_retried(self):
        now = datetime.now(timezone.utc)
        tournaments = [
            LimitlessTournament(id="future", name="Tomorrow Cup", date=now + timedelta(days=1), format_code="M-B", player_count=0),
            LimitlessTournament(id="today", name="Today Cup", date=now - timedelta(hours=2), format_code="M-B", player_count=30),
            LimitlessTournament(id="old", name="Old Cup", date=now - timedelta(days=30), format_code="M-B", player_count=30),
        ]
        provider = self._limitless(tournaments, served=set())  # nobody has decklists yet
        res = sync_tournaments(self.session, limitless_provider=provider, include_official=False)
        self.assertEqual(provider.requested, ["today", "old"], "the future event costs no request")
        recs = self._records()
        self.assertFalse(recs["limitless-future"].standings_synced)
        self.assertFalse(recs["limitless-today"].standings_synced, "empty standings on a fresh event are retried")
        self.assertTrue(recs["limitless-old"].standings_synced, "an old event with no decklists leaves the backlog")
        self.assertEqual(res["limitless"]["not_started"], 1)
        self.assertEqual(res["limitless"]["backlog_remaining"], 2)

    def test_pending_backlog_is_requested_even_when_no_longer_listed(self):
        now = datetime.now(timezone.utc)
        first = [LimitlessTournament(id="deep", name="Deep Cup", date=now - timedelta(days=40), format_code="M-B", player_count=30)]
        provider = self._limitless(first, served=set())
        with patch.object(sync_mod, "_MAX_STANDINGS_PER_RUN", 0):
            sync_tournaments(self.session, limitless_provider=provider, include_official=False)
        self.assertFalse(self._records()["limitless-deep"].standings_synced)
        # Next run: the incremental listing returns nothing new, the backlog is still fetched.
        provider = self._limitless([], served={"deep"})
        sync_tournaments(self.session, limitless_provider=provider, include_official=False)
        self.assertEqual(provider.requested, ["deep"])
        self.assertTrue(self._records()["limitless-deep"].standings_synced)
        members = self.session.exec(select(TournamentTeamMemberRecord)).all()
        self.assertTrue(members and all(m.base_canonical_id == "incineroar" for m in members), "ingest stores the base species id")
        self.assertEqual(provider.fetch_champions_tournaments.call_args.kwargs["known_ids"], {"deep"})


class TestVictoryRoadResume(_DbCase):
    def setUp(self):
        super().setUp()
        patch.object(sync_mod, "_VR_PAGES_PER_RUN", 1).start()

    def _event(self):
        return VREventResult(
            slug="2026-naic", name="2026 North America International Championships", date=datetime(2026, 7, 4, tzinfo=timezone.utc),
            game_platform="Pokémon Champions", format_regulation="Regulation M-A", location="New Orleans, LA", total_players=2,
            standings=(
                VRStandingRef(placement=1, player_name="one", paste_url="https://pokepast.es/aaa", paste_provider="pokepast", paste_id="aaa"),
                VRStandingRef(placement=2, player_name="two", paste_url="https://pokepast.es/bbb", paste_provider="pokepast", paste_id="bbb"),
            ),
        )

    def _vr(self, event):
        vr = MagicMock()
        vr.fetch_season_calendar.return_value = []
        vr.fetch_event.side_effect = lambda meta, masters_only=True: event if meta["slug"] == "2026-naic" else None
        return vr

    def test_failed_paste_keeps_the_event_pending_and_only_the_missing_paste_is_refetched(self):
        vr = self._vr(self._event())
        pokepast = MagicMock()
        pokepast.fetch_by_id.side_effect = lambda pid: {"paste": "Incineroar\n- Fake Out\n"} if pid == "aaa" else (_ for _ in ()).throw(RuntimeError("boom"))
        limitless = self._limitless([], served=set())
        res = sync_tournaments(self.session, limitless_provider=limitless, vr_provider=vr, pokepast_provider=pokepast, vrpaste_provider=MagicMock())
        self.assertEqual(res["victory_road"]["paste_errors"], 1)
        self.assertEqual(res["status"], "partial")
        self.assertEqual(vr.fetch_event.call_args.args[0]["slug"], "2026-naic", "newest finished registry event is read first")
        self.assertFalse(self._records()["vr-2026-naic"].standings_synced)
        self.assertEqual(len(self.session.exec(select(TournamentTeamRecord)).all()), 1)
        self.assertEqual(pokepast.fetch_by_id.call_args_list.count(unittest.mock.call("bbb")), 2, "one retry")

        # Second run: the page is re-read (still pending), only 'bbb' is fetched, no duplicate of 'aaa'.
        vr = self._vr(self._event())
        pokepast = MagicMock(); pokepast.fetch_by_id.return_value = {"paste": "Rillaboom\n- Grassy Glide\n"}
        sync_tournaments(self.session, limitless_provider=self._limitless([], served=set()), vr_provider=vr, pokepast_provider=pokepast, vrpaste_provider=MagicMock())
        self.assertEqual([c.args[0] for c in pokepast.fetch_by_id.call_args_list], ["bbb"])
        self.assertTrue(self._records()["vr-2026-naic"].standings_synced)
        self.assertEqual(len(self.session.exec(select(TournamentTeamRecord)).all()), 2)

        # Third run: the complete event is not requested again; the queue moves on.
        vr = self._vr(self._event())
        sync_tournaments(self.session, limitless_provider=self._limitless([], served=set()), vr_provider=vr, pokepast_provider=MagicMock(), vrpaste_provider=MagicMock())
        self.assertNotEqual(vr.fetch_event.call_args.args[0]["slug"], "2026-naic")


class TestStartupThrottle(_DbCase):
    def test_due_only_when_stale_or_backlogged(self):
        self.assertTrue(startup_sync_due(self.session), "never synced")
        now = datetime.now(timezone.utc)
        self.session.add(TournamentRecord(tournament_id="limitless-a", name="A", event_date=now, format_regulation="Regulation M-B",
                                          game_platform="Pokémon Champions", standings_synced=True, updated_at=now - timedelta(hours=1)))
        self.session.commit()
        self.assertFalse(startup_sync_due(self.session, min_interval_hours=6), "fresh and no backlog")
        self.assertTrue(startup_sync_due(self.session, min_interval_hours=0.5), "older than the interval")
        self.session.add(TournamentRecord(tournament_id="limitless-b", name="B", event_date=now, format_regulation="Regulation M-B",
                                          game_platform="Pokémon Champions", standings_synced=False))
        self.session.commit()
        self.assertTrue(startup_sync_due(self.session, min_interval_hours=6), "a backlog makes it due")


if __name__ == "__main__":
    unittest.main()

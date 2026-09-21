"""Victory Road season-calendar discovery: parsing, seeding, queue, grace and placement cap."""

import unittest
from datetime import datetime, timedelta, timezone
from unittest.mock import MagicMock, patch

from sqlmodel import Session, SQLModel, create_engine, select

from pokemon_champions_planning_tool.infrastructure.database.models import TournamentRecord, TournamentTeamRecord
from pokemon_champions_planning_tool.infrastructure.database.repositories import TournamentRepository
from pokemon_champions_planning_tool.infrastructure.providers import VREventResult, VRStandingRef
from pokemon_champions_planning_tool.infrastructure.providers.victory_road_provider import VRCalendarEvent, parse_season_calendar
from pokemon_champions_planning_tool.services import tournament_sync_service as sync_mod
from pokemon_champions_planning_tool.services.tournament_sync_service import sync_tournaments

ROW = "<tr><td>{date}</td><td><a href=\"https://victoryroad.pro/{slug}/\">{event}</a></td><td>{winner}</td><td>{fmt}</td></tr>"
CALENDAR = "<table><tr><th>Date</th><th>Event</th><th>Winner</th><th>Format</th></tr>" + "".join([
    ROW.format(date="28–30 Aug 2026", slug="2026-worlds", event="World Championships ( qualified players ) San Francisco, CA", winner="T. Y.", fmt="Champions M-B , OTS+Nat"),
    ROW.format(date="12–14 Jun 2026", slug="2026-naic", event="North America International (NAIC) New Orleans, LA", winner="F. P.", fmt="Champions M-A , OTS+Nat"),
    ROW.format(date="21–22 Mar 2026", slug="2026-houston", event="Houston Regional", winner="D. M.", fmt="SV Reg. Set F OTS"),
    ROW.format(date="25 Jan 2026", slug="2026-auckland", event="Auckland SC", winner="Y. R.", fmt="SV Reg. Set F OTS"),
    ROW.format(date="25–26 Apr 2026", slug="2026-philippines", event="Philippines Master Ball League Pasay", winner="N. A.", fmt="SV Reg. Set I OTS"),
    ROW.format(date="TBA", slug="2026-mystery", event="Mystery Regional", winner="", fmt="Champions"),
    ROW.format(date="1 Jan 2026", slug="2026-season-structure", event="Season structure", winner="", fmt=""),
]) + "</table>"


class TestCalendarParsing(unittest.TestCase):
    def test_rows_become_events(self):
        events = {e.slug: e for e in parse_season_calendar(CALENDAR, 2026)}
        self.assertEqual(set(events), {"2026-worlds", "2026-naic", "2026-houston", "2026-auckland", "2026-philippines"}, "no date / non-event rows dropped")
        w = events["2026-worlds"]
        self.assertEqual((w.name, w.location, w.date.date().isoformat(), w.game_platform, w.format_regulation), ("2026 World Championships", "San Francisco, CA", "2026-08-30", "Pokémon Champions", "Regulation M-B"))
        n = events["2026-naic"]
        self.assertEqual((n.name, n.location, n.format_regulation), ("2026 North America International (NAIC)", "New Orleans, LA", "Regulation M-A"))
        h = events["2026-houston"]
        self.assertEqual((h.name, h.location, h.game_platform, h.format_regulation, h.date.date().isoformat()), ("2026 Houston Regional", "Houston", "Scarlet & Violet", "Regulation F", "2026-03-22"))
        self.assertEqual((events["2026-auckland"].name, events["2026-auckland"].location), ("2026 Auckland SC", "Auckland"))
        self.assertEqual((events["2026-philippines"].name, events["2026-philippines"].location), ("2026 Philippines Master Ball League", "Pasay"))
        self.assertEqual(w.to_meta()["date"], "2026-08-30")


def _standing(n):
    return VRStandingRef(placement=n, player_name=f"p{n}", paste_url=f"https://pokepast.es/{n:03x}", paste_provider="pokepast", paste_id=f"{n:03x}")


class TestDiscoverySync(unittest.TestCase):
    def setUp(self):
        self.engine = create_engine("sqlite:///:memory:")
        SQLModel.metadata.create_all(self.engine)
        self.session = Session(self.engine)
        self.addCleanup(self.engine.dispose)
        self.addCleanup(self.session.close)
        patch.object(sync_mod, "_PASTE_DELAY_S", 0).start()
        patch.object(sync_mod.time, "sleep").start()
        patch.object(sync_mod, "_VR_PAGES_PER_RUN", 2).start()
        patch.object(sync_mod, "OFFICIAL_EVENT_SLUGS", []).start()   # calendar only
        self.addCleanup(patch.stopall)
        self.now = datetime.now(timezone.utc)

    def tearDown(self):
        self.session.close()

    def _calendar(self):
        d = lambda days: self.now - timedelta(days=days)  # noqa: E731
        return [
            VRCalendarEvent("2026-old", "2026 Old Regional", d(60), "Pokémon Champions", "Regulation M-B", "Old", 2026),
            VRCalendarEvent("2026-recent", "2026 Recent Regional", d(3), "Pokémon Champions", "Regulation M-B", "Recent", 2026),
            VRCalendarEvent("2026-mid", "2026 Mid Regional", d(20), "Pokémon Champions", "Regulation M-B", "Mid", 2026),
            VRCalendarEvent("2027-future", "2027 Future Regional", self.now + timedelta(days=30), "Pokémon Champions", "Regulation M-B", "Future", 2027),
        ]

    def _limitless(self):
        p = MagicMock(); p.fetch_champions_tournaments.return_value = []; p.fetch_standings_batch.return_value = {}
        return p

    def _records(self):
        return {t.tournament_id: t for t in self.session.exec(select(TournamentRecord)).all()}

    def test_calendar_seeds_pending_events_and_the_queue_reads_newest_finished_first(self):
        vr = MagicMock()
        vr.fetch_season_calendar.side_effect = lambda season: self._calendar() if season == self.now.year else []
        # recent: no sheets yet; mid: sheets; old: nothing ever published
        def event(meta, masters_only=True):
            if meta["slug"] == "2026-mid":
                return VREventResult(slug="2026-mid", name=meta["name"], date=self.now, game_platform="Pokémon Champions", format_regulation="Regulation M-B", location="Mid", total_players=100, standings=tuple(_standing(i) for i in range(1, 101)))
            return None
        vr.fetch_event.side_effect = event
        pokepast = MagicMock(); pokepast.fetch_by_id.return_value = {"paste": "Incineroar\n- Fake Out\n"}
        with patch.object(sync_mod, "VICTORY_ROAD_MAX_PLACEMENT", 5):
            res = sync_tournaments(self.session, limitless_provider=self._limitless(), vr_provider=vr, pokepast_provider=pokepast, vrpaste_provider=MagicMock())
        recs = self._records()
        self.assertEqual(res["victory_road"]["discovered"], 4)
        self.assertEqual(set(recs), {"vr-2026-old", "vr-2026-recent", "vr-2026-mid", "vr-2027-future"})
        self.assertEqual(recs["vr-2026-recent"].event_tier, "regional")
        # two pages per run, newest finished first: recent (no sheets, within grace -> stays pending) and mid
        self.assertEqual([c.args[0]["slug"] for c in vr.fetch_event.call_args_list], ["2026-recent", "2026-mid"])
        self.assertFalse(recs["vr-2026-recent"].standings_synced, "results not posted yet: retried later")
        self.assertTrue(recs["vr-2026-mid"].standings_synced)
        self.assertFalse(recs["vr-2027-future"].standings_synced, "future event never requested")
        self.assertEqual(len(self.session.exec(select(TournamentTeamRecord)).all()), 5, "placement cap")
        self.assertEqual(recs["vr-2026-mid"].total_players, 100)
        self.assertEqual(res["victory_road"]["queued"], 1, "old still queued")
        self.assertIn("4 official events discovered", sync_mod.summarize_sync_result(res))
        self.assertIsNotNone(TournamentRepository(self.session).get_state("victory_road.calendar_checked_at"))

        # Second run within 24 h: calendar not re-read; old gets its turn, no sheets and past the give-up age -> closed.
        vr2 = MagicMock(); vr2.fetch_season_calendar.return_value = []; vr2.fetch_event.return_value = None
        sync_tournaments(self.session, limitless_provider=self._limitless(), vr_provider=vr2, pokepast_provider=pokepast, vrpaste_provider=MagicMock())
        self.assertEqual(vr2.fetch_season_calendar.call_count, 0)
        self.assertEqual(sorted(c.args[0]["slug"] for c in vr2.fetch_event.call_args_list), ["2026-old", "2026-recent"])
        self.assertTrue(self._records()["vr-2026-old"].standings_synced, "ended 60 days ago with no sheets: stop asking")
        self.assertFalse(self._records()["vr-2026-recent"].standings_synced)

        # A forced sync re-reads the calendar even when fresh.
        vr3 = MagicMock(); vr3.fetch_season_calendar.return_value = []; vr3.fetch_event.return_value = None
        sync_tournaments(self.session, force=True, limitless_provider=self._limitless(), vr_provider=vr3, pokepast_provider=pokepast, vrpaste_provider=MagicMock())
        self.assertEqual(vr3.fetch_season_calendar.call_count, 2)

    def test_queue_puts_champions_events_before_other_games(self):
        d = lambda days: self.now - timedelta(days=days)  # noqa: E731
        for slug, game, days in (("sv-new", "Scarlet & Violet", 1), ("ch-old", "Pokémon Champions", 30), ("ch-new", "Pokémon Champions", 5)):
            self.session.add(TournamentRecord(tournament_id=f"vr-{slug}", name=slug, event_date=d(days), format_regulation="Regulation M-B", game_platform=game, standings_synced=False))
        self.session.commit()
        queue = TournamentRepository(self.session).list_official_events(ended_before=self.now)
        self.assertEqual([q.tournament_id for q in queue], ["vr-ch-new", "vr-ch-old", "vr-sv-new"])

    def test_existing_rows_are_never_overwritten_by_discovery(self):
        self.session.add(TournamentRecord(tournament_id="vr-2026-mid", name="Custom name", event_date=self.now - timedelta(days=20), format_regulation="Regulation M-B", game_platform="Pokémon Champions", standings_synced=True))
        self.session.commit()
        vr = MagicMock(); vr.fetch_season_calendar.side_effect = lambda season: self._calendar() if season == self.now.year else []; vr.fetch_event.return_value = None
        res = sync_tournaments(self.session, limitless_provider=self._limitless(), vr_provider=vr, pokepast_provider=MagicMock(), vrpaste_provider=MagicMock())
        self.assertEqual(res["victory_road"]["discovered"], 3)
        self.assertEqual(self._records()["vr-2026-mid"].name, "Custom name")



class TestTeamListRetryPolicy(unittest.TestCase):
    """An official event whose page has no team list yet: retried eagerly, then slowly,
    then given up — instead of being closed for good 14 days after the event."""

    def setUp(self):
        self.engine = create_engine("sqlite:///:memory:")
        SQLModel.metadata.create_all(self.engine)
        self.session = Session(self.engine)
        self.addCleanup(self.engine.dispose)
        self.addCleanup(self.session.close)
        patch.object(sync_mod, "_PASTE_DELAY_S", 0).start()
        patch.object(sync_mod.time, "sleep").start()
        patch.object(sync_mod, "_VR_PAGES_PER_RUN", 2).start()
        patch.object(sync_mod, "OFFICIAL_EVENT_SLUGS", []).start()
        self.addCleanup(patch.stopall)
        self.now = datetime.now(timezone.utc)
        self.repo = TournamentRepository(self.session)
        self.repo.set_state("victory_road.calendar_checked_at", self.now.isoformat())   # no calendar reads

    def tearDown(self):
        self.session.close()

    def _event(self, slug, days_ago):
        self.session.add(TournamentRecord(tournament_id=f"vr-{slug}", name=f"{slug} Regional", event_date=self.now - timedelta(days=days_ago),
                                          format_regulation="Regulation M-C", game_platform="Pokémon Champions", standings_synced=False))
        self.session.commit()

    def _checked(self, slug, days_ago):
        self.repo.set_state(f"victory_road.no_sheets_checked_at.vr-{slug}", (self.now - timedelta(days=days_ago)).isoformat())

    def _sync(self, vr=None):
        vr = vr or MagicMock(fetch_season_calendar=MagicMock(return_value=[]), fetch_event=MagicMock(return_value=None))
        limitless = MagicMock(); limitless.fetch_champions_tournaments.return_value = []; limitless.fetch_standings_batch.return_value = {}
        with patch("builtins.print") as printed:
            res = sync_tournaments(self.session, limitless_provider=limitless, vr_provider=vr, pokepast_provider=MagicMock(), vrpaste_provider=MagicMock())
        lines = [" ".join(map(str, c.args)) for c in printed.call_args_list]
        return res, vr, lines

    def _read(self, vr):
        return [c.args[0]["slug"] for c in vr.fetch_event.call_args_list]

    def _synced(self, slug):
        self.session.expire_all()
        return self.session.get(TournamentRecord, f"vr-{slug}").standings_synced

    def test_a_recent_event_is_read_every_sync_and_says_so(self):
        self._event("baltimore", 1)
        res, vr, lines = self._sync()
        self.assertEqual(self._read(vr), ["baltimore"])
        self.assertFalse(self._synced("baltimore"))
        msg = next(line for line in lines if "baltimore" in line)
        self.assertIn("no team list published yet", msg)
        self.assertIn("checking on every sync until", msg)
        self.assertIn("Victory Road", msg)
        self.assertEqual(res["status"], "synced", "the page answered: not an outage")
        self.assertIn("1 official event awaiting team lists", sync_mod.summarize_sync_result(res))
        _res, vr2, _ = self._sync()
        self.assertEqual(self._read(vr2), ["baltimore"], "still within the eager window: read again")

    def test_after_the_grace_window_it_is_kept_not_closed(self):
        """The old rule closed an event for good 14 days in; a slow Victory Road update
        then made it disappear permanently."""
        self._event("slow", 20)
        _res, vr, lines = self._sync()
        self.assertEqual(self._read(vr), ["slow"])
        self.assertFalse(self._synced("slow"))
        self.assertIn("checking every 3 days until", next(line for line in lines if "slow" in line))

    def test_a_slow_retry_that_is_not_due_does_not_use_the_page_budget(self):
        self._event("recent-a", 1)
        self._event("recent-b", 2)
        self._event("slow", 20)
        self._event("due", 30)
        self._checked("slow", 1)           # read yesterday: not due
        self._checked("due", 4)            # read 4 days ago: due
        patch.object(sync_mod, "_VR_PAGES_PER_RUN", 3).start()
        res, vr, _ = self._sync()
        self.assertEqual(self._read(vr), ["recent-a", "recent-b", "due"], "the waiting event is skipped, not the due one")
        self.assertEqual(res["victory_road"]["waiting"], 1)

    def test_past_the_give_up_age_it_is_read_once_more_then_closed(self):
        self._event("abandoned", 50)
        self._checked("abandoned", 1)      # recently checked, but past the give-up age it is due regardless
        _res, vr, lines = self._sync()
        self.assertEqual(self._read(vr), ["abandoned"])
        self.assertTrue(self._synced("abandoned"))
        self.assertIn("no longer checking", next(line for line in lines if "abandoned" in line))
        self.assertEqual(self.repo.get_state("victory_road.no_sheets_checked_at.vr-abandoned"), "", "bookkeeping cleared")

    def test_a_network_error_never_closes_an_event_or_delays_its_retry(self):
        self._event("offline", 50)
        vr = MagicMock(fetch_season_calendar=MagicMock(return_value=[]))
        def failing(meta, masters_only=True):
            vr.last_fetch_failed = True
            return None
        vr.fetch_event.side_effect = failing
        _res, _vr, lines = self._sync(vr)
        self.assertFalse(self._synced("offline"), "an unreadable page is not evidence there is no team list")
        self.assertIn("couldn't read the page", next(line for line in lines if "offline" in line))
        self.assertIsNone(self.repo.get_state("victory_road.no_sheets_checked_at.vr-offline"), "no slow-retry clock started")

    def test_a_forced_sync_reads_waiting_events_too(self):
        self._event("slow", 20)
        self._checked("slow", 1)
        vr = MagicMock(fetch_season_calendar=MagicMock(return_value=[]), fetch_event=MagicMock(return_value=None))
        limitless = MagicMock(); limitless.fetch_champions_tournaments.return_value = []; limitless.fetch_standings_batch.return_value = {}
        with patch("builtins.print"):
            sync_tournaments(self.session, force=True, limitless_provider=limitless, vr_provider=vr, pokepast_provider=MagicMock(), vrpaste_provider=MagicMock())
        self.assertIn("slow", self._read(vr))


if __name__ == "__main__":
    unittest.main()

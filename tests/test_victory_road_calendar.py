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

        # Second run within 24 h: calendar not re-read; old gets its turn, no sheets and past grace -> closed.
        vr2 = MagicMock(); vr2.fetch_season_calendar.return_value = []; vr2.fetch_event.return_value = None
        sync_tournaments(self.session, limitless_provider=self._limitless(), vr_provider=vr2, pokepast_provider=pokepast, vrpaste_provider=MagicMock())
        self.assertEqual(vr2.fetch_season_calendar.call_count, 0)
        self.assertEqual(sorted(c.args[0]["slug"] for c in vr2.fetch_event.call_args_list), ["2026-old", "2026-recent"])
        self.assertTrue(self._records()["vr-2026-old"].standings_synced, "ended long ago with no sheets: stop asking")
        self.assertFalse(self._records()["vr-2026-recent"].standings_synced)

        # A forced sync re-reads the calendar even when fresh.
        vr3 = MagicMock(); vr3.fetch_season_calendar.return_value = []; vr3.fetch_event.return_value = None
        sync_tournaments(self.session, force=True, limitless_provider=self._limitless(), vr_provider=vr3, pokepast_provider=pokepast, vrpaste_provider=MagicMock())
        self.assertEqual(vr3.fetch_season_calendar.call_count, 2)

    def test_existing_rows_are_never_overwritten_by_discovery(self):
        self.session.add(TournamentRecord(tournament_id="vr-2026-mid", name="Custom name", event_date=self.now - timedelta(days=20), format_regulation="Regulation M-B", game_platform="Pokémon Champions", standings_synced=True))
        self.session.commit()
        vr = MagicMock(); vr.fetch_season_calendar.side_effect = lambda season: self._calendar() if season == self.now.year else []; vr.fetch_event.return_value = None
        res = sync_tournaments(self.session, limitless_provider=self._limitless(), vr_provider=vr, pokepast_provider=MagicMock(), vrpaste_provider=MagicMock())
        self.assertEqual(res["victory_road"]["discovered"], 3)
        self.assertEqual(self._records()["vr-2026-mid"].name, "Custom name")


if __name__ == "__main__":
    unittest.main()

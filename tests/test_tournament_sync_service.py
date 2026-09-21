"""Unit tests for tournament_sync_service and format/alias normalization."""

import unittest
from datetime import datetime, timezone
import unittest.mock
from unittest.mock import MagicMock

from sqlmodel import Session, SQLModel, create_engine

from pokemon_champions_planning_tool.domain.pokemon_identity import (
    format_api_name,
    normalize_format_regulation,
)
from pokemon_champions_planning_tool.infrastructure.providers import (
    LimitlessStanding,
    LimitlessTeamMember,
    LimitlessTournament,
    VREventResult,
    VRStandingRef,
)
from pokemon_champions_planning_tool.services.tournament_service import TournamentService
from pokemon_champions_planning_tool.services.tournament_sync_service import sync_tournaments


class TestTournamentSyncService(unittest.TestCase):

    def setUp(self):
        """Set up an in-memory SQLite database session."""
        self.engine = create_engine("sqlite:///:memory:")
        SQLModel.metadata.create_all(self.engine)
        self.addCleanup(self.engine.dispose)
        self.session = Session(self.engine)

    def tearDown(self):
        self.session.close()

    def test_format_regulation_normalization(self):
        """Verify raw format strings map to clean standard labels."""
        self.assertEqual(normalize_format_regulation("M-A"), "Regulation M-A")
        self.assertEqual(normalize_format_regulation("VGC Regulation Set M-B"), "Regulation M-B")
        self.assertEqual(normalize_format_regulation("gen9vgc2025regh"), "Regulation H")
        self.assertEqual(normalize_format_regulation("VGC Regulation Set F"), "Regulation F")

    def test_species_alias_normalization(self):
        """Verify competitive display names resolve to PokéAPI canonical IDs."""
        self.assertEqual(format_api_name("Rapid Strike Urshifu"), "urshifu-rapid-strike")
        self.assertEqual(format_api_name("Hearthflame Mask Ogerpon"), "ogerpon-hearthflame")
        self.assertEqual(format_api_name("Bloodmoon Ursaluna"), "ursaluna-bloodmoon")
        self.assertEqual(format_api_name("Eternal Flower Floette"), "floette-eternal")
        self.assertEqual(format_api_name("Hisuian Arcanine"), "arcanine-hisui")
        self.assertEqual(format_api_name("Mega Charizard Y"), "charizard-mega-y")

    def test_sync_tournaments_end_to_end(self):
        """Test full tournament sync pipeline with mocked providers."""
        mock_limitless = MagicMock()
        mock_limitless.fetch_champions_tournaments.return_value = [
            LimitlessTournament(
                id="tourney1",
                name="Champions Invitational #1",
                date=datetime.now(timezone.utc),
                format_code="M-A",
                player_count=64,
            )
        ]
        # New API: fetch_standings_batch returns dict[str, list[LimitlessStanding]]
        mock_limitless.fetch_standings_batch.return_value = {
            "tourney1": [
                LimitlessStanding(
                    player_handle="PlayerOne",
                    placement=1,
                    members=(
                        LimitlessTeamMember(
                            canonical_id="charizard-mega-y",
                            display_name="Mega Charizard Y",
                            item="Charizardite Y",
                            ability="Drought",
                            nature="Timid",
                            moves=("Heat Wave", "Solar Beam", "Protect", "Overheat"),
                        ),
                    ),
                )
            ]
        }

        mock_vr = MagicMock()
        mock_vr.fetch_season_calendar.return_value = []
        mock_vr.fetch_event.return_value = (
            VREventResult(
                slug="2026-laic",
                name="2026 Latin America International Championships",
                date=datetime.now(timezone.utc),
                game_platform="Pokémon Champions",
                format_regulation="Regulation M-A",
                location="São Paulo",
                total_players=512,
                standings=(
                    VRStandingRef(
                        placement=1,
                        player_name="WinnerPlayer",
                        paste_id="vrpaste1",
                        paste_provider="vrpaste",
                    ),
                ),
            )
        )

        mock_vrpaste = MagicMock()
        mock_vrpaste.fetch_by_id.return_value = MagicMock(
            members=[
                MagicMock(
                    display_name="Urshifu-Rapid-Strike",
                    item="Choice Scarf",
                    ability="Unseen Fist",
                    nature="Jolly",
                    moves=["Surging Strikes", "Close Combat"],
                )
            ]
        )

        with unittest.mock.patch("pokemon_champions_planning_tool.services.tournament_sync_service._VR_PAGES_PER_RUN", 1):
          res = sync_tournaments(
            session=self.session,
            force=True,
            limitless_provider=mock_limitless,
            vr_provider=mock_vr,
            vrpaste_provider=mock_vrpaste,
        )

        self.assertEqual(res["status"], "synced")
        self.assertEqual(res["limitless"]["added"], 1)
        self.assertEqual(res["victory_road"]["added"], 1)

        svc = TournamentService(self.session)
        tourneys = svc.list_tournaments()
        # one Limitless event plus the registry's official events (seeded as pending)
        self.assertGreaterEqual(len(tourneys), 2)
        # the newest finished official event in the queue was read and marked complete
        self.assertTrue(any(t.tournament_id.startswith("vr-") and t.standings_synced for t in tourneys))

        teams = svc.search_teams()
        self.assertGreaterEqual(len(teams), 2)


if __name__ == "__main__":
    unittest.main()


class TestLimitlessStandingsBacklog(unittest.TestCase):
    """The standings cap must produce a draining backlog, not permanent orphans."""

    def setUp(self):
        self.engine = create_engine("sqlite:///:memory:")
        SQLModel.metadata.create_all(self.engine)
        self.addCleanup(self.engine.dispose)
        self.session = Session(self.engine)

    def tearDown(self):
        self.session.close()

    @staticmethod
    def _tournament(idx: int) -> LimitlessTournament:
        return LimitlessTournament(
            id=f"t{idx}",
            name=f"Champions Cup #{idx}",
            date=datetime(2026, 8, 1, tzinfo=timezone.utc),
            format_code="M-A",
            player_count=64,
        )

    @staticmethod
    def _standing(player: str) -> LimitlessStanding:
        return LimitlessStanding(
            player_handle=player,
            placement=1,
            members=(
                LimitlessTeamMember(
                    canonical_id="incineroar",
                    display_name="Incineroar",
                    item="Safety Goggles",
                    ability="Intimidate",
                    moves=("Fake Out", "Knock Off", "Parting Shot", "Will-O-Wisp"),
                ),
            ),
        )

    def _provider(self, tournaments, served):
        """Provider whose standings batch honours a per-run request cap."""
        provider = MagicMock()
        provider.fetch_champions_tournaments.return_value = tournaments

        def _batch(tournament_ids, max_placement=None, max_requests=20, **kwargs):
            return {
                t_id: [self._standing(f"player-{t_id}")]
                for t_id in tournament_ids[:max_requests]
                if t_id in served
            }

        provider.fetch_standings_batch.side_effect = _batch
        return provider

    def _counts(self):
        from pokemon_champions_planning_tool.infrastructure.database.models import (
            TournamentRecord,
            TournamentTeamRecord,
        )
        from sqlmodel import select

        tournaments = list(self.session.exec(select(TournamentRecord)).all())
        teams = list(self.session.exec(select(TournamentTeamRecord)).all())
        synced = [t for t in tournaments if t.standings_synced]
        return len(tournaments), len(synced), len(teams)

    def test_backlog_drains_across_runs(self):
        """Tournaments past the per-run cap are retried, not skipped forever."""
        tournaments = [self._tournament(i) for i in range(5)]
        served = {f"t{i}" for i in range(5)}

        # Run 1: cap of 2 leaves 3 tournaments awaiting standings.
        provider = self._provider(tournaments, served)
        with unittest.mock.patch(
            "pokemon_champions_planning_tool.services.tournament_sync_service._MAX_STANDINGS_PER_RUN",
            2,
        ):
            res = sync_tournaments(
                self.session, limitless_provider=provider, include_official=False
            )
        self.assertEqual(res["limitless"]["standings_synced"], 2)
        self.assertEqual(res["limitless"]["backlog_remaining"], 3)
        self.assertEqual(self._counts(), (5, 2, 2))

        # Run 2: the remaining backlog is picked up rather than skipped as "existing".
        provider = self._provider(tournaments, served)
        with unittest.mock.patch(
            "pokemon_champions_planning_tool.services.tournament_sync_service._MAX_STANDINGS_PER_RUN",
            2,
        ):
            res = sync_tournaments(
                self.session, limitless_provider=provider, include_official=False
            )
        self.assertEqual(res["limitless"]["skipped"], 2, "already-synced ones are skipped")
        self.assertEqual(res["limitless"]["standings_synced"], 2)
        self.assertEqual(self._counts(), (5, 4, 4))

        # Run 3 drains the last one.
        provider = self._provider(tournaments, served)
        with unittest.mock.patch(
            "pokemon_champions_planning_tool.services.tournament_sync_service._MAX_STANDINGS_PER_RUN",
            2,
        ):
            sync_tournaments(self.session, limitless_provider=provider, include_official=False)
        self.assertEqual(self._counts(), (5, 5, 5))

    def test_failed_standings_request_is_retried(self):
        """A tournament whose standings request failed stays in the backlog."""
        tournaments = [self._tournament(0)]

        # Provider returns no entry for t0 (request failed) -> must remain unsynced.
        provider = self._provider(tournaments, served=set())
        sync_tournaments(self.session, limitless_provider=provider, include_official=False)
        self.assertEqual(self._counts(), (1, 0, 0))

        # Once the request succeeds the tournament leaves the backlog.
        provider = self._provider(tournaments, served={"t0"})
        sync_tournaments(self.session, limitless_provider=provider, include_official=False)
        self.assertEqual(self._counts(), (1, 1, 1))

    def test_resync_replaces_teams_instead_of_duplicating(self):
        """Re-ingesting a tournament must not append duplicate rosters."""
        tournaments = [self._tournament(0)]
        for _ in range(3):
            provider = self._provider(tournaments, served={"t0"})
            sync_tournaments(
                self.session, force=True, limitless_provider=provider, include_official=False
            )
        self.assertEqual(self._counts(), (1, 1, 1), "3 forced syncs must leave 1 team")

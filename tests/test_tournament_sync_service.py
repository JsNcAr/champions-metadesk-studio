"""Unit tests for tournament_sync_service and format/alias normalization."""

import unittest
from datetime import datetime, timezone
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
        mock_vr.fetch_all_known_events.return_value = [
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
        ]

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
        self.assertEqual(len(tourneys), 2)

        teams = svc.search_teams()
        self.assertGreaterEqual(len(teams), 2)


if __name__ == "__main__":
    unittest.main()

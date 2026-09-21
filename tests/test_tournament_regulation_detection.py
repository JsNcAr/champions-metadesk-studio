import unittest
from datetime import datetime, timezone
from unittest.mock import MagicMock
from sqlmodel import Session, SQLModel, create_engine, select

from pokemon_champions_planning_tool.domain.pokemon_identity import (
    REGULATION_MC_SPECIES,
    normalize_format_regulation,
)
from pokemon_champions_planning_tool.infrastructure.database.models import (
    TournamentRecord,
    TournamentTeamMemberRecord,
    TournamentTeamRecord,
)
from pokemon_champions_planning_tool.infrastructure.database.database import _remediate_tournament_regulations
from pokemon_champions_planning_tool.infrastructure.providers.limitless_provider import (
    LimitlessProvider,
    LimitlessTournament,
)


class TestTournamentRegulationDetection(unittest.TestCase):
    def setUp(self):
        self.engine = create_engine("sqlite:///:memory:")
        SQLModel.metadata.create_all(self.engine)
        self.addCleanup(self.engine.dispose)

    def test_remediate_tournament_regulations_title_and_roster(self):
        with Session(self.engine) as session:
            # 1. Tournament with M-C in title but marked Regulation M-B
            t1 = TournamentRecord(
                tournament_id="t1",
                name="[Shiny Salamence to 1st] The Grim Challenge #8 M-C",
                event_date=datetime(2026, 9, 12, tzinfo=timezone.utc),
                format_regulation="Regulation M-B",
                game_platform="Pokémon Champions",
            )
            # 2. Tournament with M-B in title but marked Regulation M-A
            t2 = TournamentRecord(
                tournament_id="t2",
                name="Friday Fight Night #60 Reg M-B Bo3",
                event_date=datetime(2026, 8, 20, tzinfo=timezone.utc),
                format_regulation="Regulation M-A",
                game_platform="Pokémon Champions",
            )
            # 3. Tournament with generic title but holding teams with M-C species (e.g. Golisopod)
            t3 = TournamentRecord(
                tournament_id="t3",
                name="PWC - Battle in the Colosseum #26",
                event_date=datetime(2026, 9, 12, tzinfo=timezone.utc),
                format_regulation="Regulation M-B",
                game_platform="Pokémon Champions",
            )
            # 4. Legitimate M-B tournament with M-B title
            t4 = TournamentRecord(
                tournament_id="t4",
                name="IV Clash - Reg. M-B",
                event_date=datetime(2026, 9, 12, tzinfo=timezone.utc),
                format_regulation="Regulation M-B",
                game_platform="Pokémon Champions",
            )
            session.add_all([t1, t2, t3, t4])

            # Add teams for t3 with an M-C exclusive species (golisopod)
            team3 = TournamentTeamRecord(
                tournament_id="t3",
                player_name="player1",
                placement=1,
                standing_label="1st",
                showdown_text="Golisopod\nAbility: Emergency Exit\n- First Impression",
            )
            session.add(team3)
            session.commit()
            session.refresh(team3)

            m1 = TournamentTeamMemberRecord(
                tournament_team_id=team3.tournament_team_id,
                slot_position=1,
                canonical_id="golisopod",
                base_canonical_id="golisopod",
                species_name="Golisopod",
            )
            session.add(m1)
            session.commit()

        # Run remediation
        with self.engine.connect() as conn:
            _remediate_tournament_regulations(conn)

        # Verify results
        with Session(self.engine) as session:
            t1_updated = session.get(TournamentRecord, "t1")
            self.assertEqual(t1_updated.format_regulation, "Regulation M-C")

            t2_updated = session.get(TournamentRecord, "t2")
            self.assertEqual(t2_updated.format_regulation, "Regulation M-B")

            t3_updated = session.get(TournamentRecord, "t3")
            self.assertEqual(t3_updated.format_regulation, "Regulation M-C")

            t4_updated = session.get(TournamentRecord, "t4")
            self.assertEqual(t4_updated.format_regulation, "Regulation M-B")

    def test_limitless_provider_accepts_custom_format_if_champions_title(self):
        provider = LimitlessProvider()
        # Mock _get returning a mix of tournaments
        raw_items = [
            {
                "id": "tour1",
                "name": "Pomelo Late Night Tour (M-C)",
                "format": "CUSTOM",
                "date": "2026-09-12T10:00:00Z",
                "players": 32,
                "organizer": "Pomelo",
            },
            {
                "id": "tour2",
                "name": "Random SV Tour",
                "format": "CUSTOM",
                "date": "2026-09-12T10:00:00Z",
                "players": 16,
                "organizer": "Random",
            },
            {
                "id": "tour3",
                "name": "Standard M-B Tour",
                "format": "M-B",
                "date": "2026-09-12T10:00:00Z",
                "players": 64,
                "organizer": "VGC",
            },
        ]
        provider._get = MagicMock(return_value=raw_items)

        tournaments = provider.fetch_champions_tournaments(max_age_days=30)
        ids = [t.id for t in tournaments]
        self.assertIn("tour1", ids)  # Accepted because of (M-C) in name
        self.assertNotIn("tour2", ids)  # Rejected because format=CUSTOM and name has no Champions reg
        self.assertIn("tour3", ids)  # Accepted because format=M-B


if __name__ == "__main__":
    unittest.main()

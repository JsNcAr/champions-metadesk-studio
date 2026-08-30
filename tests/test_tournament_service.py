import unittest
from datetime import datetime, timezone
from sqlmodel import Session, SQLModel, create_engine
from pokemon_champions_planning_tool.infrastructure.database.models import (
    TournamentRecord,
    TournamentTeamRecord,
    TournamentTeamMemberRecord,
)
from pokemon_champions_planning_tool.services.tournament_service import (
    TournamentService,
    MetaSynergyService,
)


class TestTournamentService(unittest.TestCase):
    def setUp(self):
        self.engine = create_engine("sqlite:///:memory:")
        SQLModel.metadata.create_all(self.engine)
        self.session = Session(self.engine)
        self.svc = TournamentService(self.session)

    def tearDown(self):
        self.session.close()

    def test_synergy_service_partner_recommendations(self):
        # Create test tournament and 2 teams sharing Charizard
        t_rec = TournamentRecord(
            tournament_id="synergy-test-1",
            name="Synergy Invitational",
            event_date=datetime.now(timezone.utc),
            format_regulation="Champions Season 1",
        )
        self.svc.repo.upsert_tournament(t_rec)

        # Team 1: Charizard + Pikachu + Lucario
        team1 = TournamentTeamRecord(
            tournament_id="synergy-test-1",
            player_name="Player 1",
            placement=1,
            showdown_text="Charizard\nPikachu\nLucario\n",
        )
        m1_1 = TournamentTeamMemberRecord(slot_position=1, canonical_id="charizard", species_name="Charizard")
        m1_2 = TournamentTeamMemberRecord(slot_position=2, canonical_id="pikachu", species_name="Pikachu")
        m1_3 = TournamentTeamMemberRecord(slot_position=3, canonical_id="lucario", species_name="Lucario")
        self.svc.repo.save_team(team1, [m1_1, m1_2, m1_3])

        # Team 2: Charizard + Pikachu + Gengar
        team2 = TournamentTeamRecord(
            tournament_id="synergy-test-1",
            player_name="Player 2",
            placement=2,
            showdown_text="Charizard\nPikachu\nGengar\n",
        )
        m2_1 = TournamentTeamMemberRecord(slot_position=1, canonical_id="charizard", species_name="Charizard")
        m2_2 = TournamentTeamMemberRecord(slot_position=2, canonical_id="pikachu", species_name="Pikachu")
        m2_3 = TournamentTeamMemberRecord(slot_position=3, canonical_id="gengar", species_name="Gengar")
        self.svc.repo.save_team(team2, [m2_1, m2_2, m2_3])

        # Query top partners for Charizard
        partners = self.svc.get_top_partners("charizard", limit=5)
        self.assertTrue(len(partners) >= 1)
        top_partner = partners[0]
        self.assertEqual(top_partner.canonical_id, "pikachu")
        self.assertEqual(top_partner.co_occurrence_count, 2)
        self.assertEqual(top_partner.synergy_percentage, 100.0)


if __name__ == "__main__":
    unittest.main()

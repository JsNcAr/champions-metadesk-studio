import unittest
from datetime import datetime, timezone, timedelta
from pathlib import Path
from tempfile import NamedTemporaryFile

from sqlmodel import Session, SQLModel, create_engine
from pokemon_champions_planning_tool.infrastructure.database.models import (
    TournamentRecord,
    TournamentTeamRecord,
    TournamentTeamMemberRecord,
)
from pokemon_champions_planning_tool.infrastructure.database.repositories import TournamentRepository


class TestTournamentRepository(unittest.TestCase):
    def setUp(self):
        self.engine = create_engine("sqlite:///:memory:")
        SQLModel.metadata.create_all(self.engine)
        self.addCleanup(self.engine.dispose)
        self.session = Session(self.engine)
        self.repo = TournamentRepository(self.session)

    def tearDown(self):
        self.session.close()

    def test_upsert_and_get_tournament(self):
        t_rec = TournamentRecord(
            tournament_id="test-tourney-1",
            name="Test Championship 2026",
            event_date=datetime.now(timezone.utc),
            format_regulation="Champions Season 1",
            game_platform="Pokémon Champions",
            organizer="Play! Pokémon",
            location="Tokyo",
            total_players=64,
        )
        saved = self.repo.upsert_tournament(t_rec)
        self.assertEqual(saved.tournament_id, "test-tourney-1")

        fetched = self.repo.get_tournament("test-tourney-1")
        self.assertIsNotNone(fetched)
        self.assertEqual(fetched.name, "Test Championship 2026")
        self.assertEqual(fetched.game_platform, "Pokémon Champions")

    def test_save_and_search_teams(self):
        t_rec = TournamentRecord(
            tournament_id="test-tourney-2",
            name="Regional 2026",
            event_date=datetime.now(timezone.utc),
            format_regulation="Regulation H",
            game_platform="Scarlet & Violet",
        )
        self.repo.upsert_tournament(t_rec)

        team = TournamentTeamRecord(
            tournament_id="test-tourney-2",
            player_name="Ash Ketchum",
            placement=1,
            standing_label="1st Place",
            showdown_text="Pikachu @ Light Ball\n- Volt Tackle\n",
        )
        m1 = TournamentTeamMemberRecord(slot_position=1, canonical_id="pikachu", species_name="Pikachu")
        self.repo.save_team(team, [m1])

        results = self.repo.search_teams(query="Pikachu")
        self.assertEqual(len(results), 1)
        self.assertEqual(results[0].player_name, "Ash Ketchum")

        members = self.repo.get_team_members(team.tournament_team_id)
        self.assertEqual(len(members), 1)
        self.assertEqual(members[0].species_name, "Pikachu")

    def test_search_team_game_platform_and_recency(self):
        # 1. Old Scarlet & Violet tournament (2 years ago)
        old_date = datetime.now(timezone.utc) - timedelta(days=730)
        t_old = TournamentRecord(
            tournament_id="sv-worlds-2024",
            name="2024 VGC World Championship",
            event_date=old_date,
            format_regulation="Regulation G",
            game_platform="Scarlet & Violet",
        )
        self.repo.upsert_tournament(t_old)
        team_old = TournamentTeamRecord(
            tournament_id="sv-worlds-2024",
            player_name="Luca C.",
            placement=1,
            showdown_text="Miraidon @ Choice Specs\n",
        )
        m_old = TournamentTeamMemberRecord(slot_position=1, canonical_id="miraidon", species_name="Miraidon")
        self.repo.save_team(team_old, [m_old])

        # 2. Recent Champions tournament (10 days ago)
        recent_date = datetime.now(timezone.utc) - timedelta(days=10)
        t_recent = TournamentRecord(
            tournament_id="champions-2026",
            name="Champions Launch 2026",
            event_date=recent_date,
            format_regulation="Champions Season 1",
            game_platform="Pokémon Champions",
        )
        self.repo.upsert_tournament(t_recent)
        team_recent = TournamentTeamRecord(
            tournament_id="champions-2026",
            player_name="Red",
            placement=1,
            showdown_text="Charizard @ Solar Glasses\n",
        )
        m_recent = TournamentTeamMemberRecord(slot_position=1, canonical_id="charizard", species_name="Charizard")
        self.repo.save_team(team_recent, [m_recent])

        # Filter by platform = Pokémon Champions
        champ_teams = self.repo.search_teams(game_platform_filter="Pokémon Champions")
        self.assertEqual(len(champ_teams), 1)
        self.assertEqual(champ_teams[0].player_name, "Red")

        # Filter by recency = last 365 days
        recent_teams = self.repo.search_teams(max_age_days=365)
        self.assertEqual(len(recent_teams), 1)
        self.assertEqual(recent_teams[0].player_name, "Red")

        # All time should return both
        all_teams = self.repo.search_teams(max_age_days=None)
        self.assertEqual(len(all_teams), 2)

    def test_preset_builds_cache(self):
        self.assertIsNone(self.repo.get_cached_preset_builds("doubles"))
        sample = {"incineroar": {"canonical_id": "incineroar", "moves": ["Flare Blitz"]}}
        self.repo.set_cached_preset_builds("doubles", sample)
        cached = self.repo.get_cached_preset_builds("doubles")
        self.assertEqual(cached, sample)

        # Invalidate cache
        self.repo.invalidate_preset_builds_cache()
        self.assertIsNone(self.repo.get_cached_preset_builds("doubles"))

    def test_search_teams_with_exclusions(self):
        t_rec = TournamentRecord(
            tournament_id="tourney-exclusion",
            name="Special Event 2026",
            event_date=datetime.now(timezone.utc),
            format_regulation="Regulation H",
            game_platform="Scarlet & Violet",
        )
        self.repo.upsert_tournament(t_rec)

        # Team 1: Pelipper + Archaludon
        team1 = TournamentTeamRecord(
            tournament_id="tourney-exclusion",
            player_name="Player Rain",
            placement=1,
            showdown_text="",
        )
        m1 = [
            TournamentTeamMemberRecord(slot_position=1, canonical_id="pelipper", base_canonical_id="pelipper", species_name="Pelipper"),
            TournamentTeamMemberRecord(slot_position=2, canonical_id="archaludon", base_canonical_id="archaludon", species_name="Archaludon"),
        ]
        self.repo.save_team(team1, m1)

        # Team 2: Pelipper + Urshifu (No Archaludon)
        team2 = TournamentTeamRecord(
            tournament_id="tourney-exclusion",
            player_name="Player Water",
            placement=2,
            showdown_text="",
        )
        m2 = [
            TournamentTeamMemberRecord(slot_position=1, canonical_id="pelipper", base_canonical_id="pelipper", species_name="Pelipper"),
            TournamentTeamMemberRecord(slot_position=2, canonical_id="urshifu-rapid-strike", base_canonical_id="urshifu", species_name="Urshifu-Rapid-Strike"),
        ]
        self.repo.save_team(team2, m2)

        # Team 3: Dondozo + Tatsugiri
        team3 = TournamentTeamRecord(
            tournament_id="tourney-exclusion",
            player_name="Player Sushi",
            placement=3,
            showdown_text="",
        )
        m3 = [
            TournamentTeamMemberRecord(slot_position=1, canonical_id="dondozo", base_canonical_id="dondozo", species_name="Dondozo"),
            TournamentTeamMemberRecord(slot_position=2, canonical_id="tatsugiri", base_canonical_id="tatsugiri", species_name="Tatsugiri"),
        ]
        self.repo.save_team(team3, m3)

        # Query 1: All Pelipper teams -> Team 1 and Team 2
        pelipper_all = self.repo.search_teams(query="pelipper")
        self.assertEqual(len(pelipper_all), 2)

        # Query 2: Pelipper without Archaludon -> only Team 2
        pelipper_no_arch = self.repo.search_teams(query="pelipper -archaludon")
        self.assertEqual(len(pelipper_no_arch), 1)
        self.assertEqual(pelipper_no_arch[0].player_name, "Player Water")

        # Query 3: Pure exclusion: teams without Archaludon and without Tatsugiri -> only Team 2
        no_arch_no_tat = self.repo.search_teams(query="-archaludon -tatsugiri")
        self.assertEqual(len(no_arch_no_tat), 1)
        self.assertEqual(no_arch_no_tat[0].player_name, "Player Water")

        # Query 4: Multiple inclusions: Pelipper and Archaludon -> only Team 1
        rain_both = self.repo.search_teams(query="pelipper archaludon")
        self.assertEqual(len(rain_both), 1)
        self.assertEqual(rain_both[0].player_name, "Player Rain")


if __name__ == "__main__":
    unittest.main()


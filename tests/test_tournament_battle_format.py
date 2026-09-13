import unittest
from datetime import datetime, timezone
from sqlmodel import Session, SQLModel, create_engine
from pokemon_champions_planning_tool.domain.pokemon_identity import classify_battle_format
from pokemon_champions_planning_tool.infrastructure.database.models import (
    TournamentRecord,
    TournamentTeamRecord,
    TournamentTeamMemberRecord,
)
from pokemon_champions_planning_tool.infrastructure.database.repositories import (
    TournamentRepository,
)
from pokemon_champions_planning_tool.infrastructure.database.database import (
    _remediate_tournament_battle_formats,
)
from pokemon_champions_planning_tool.ui.views.settings.store import SettingsStore
from pokemon_champions_planning_tool.ui.views.meta.store import MetaStore


class TestTournamentBattleFormat(unittest.TestCase):
    def setUp(self):
        self.engine = create_engine("sqlite:///:memory:")
        SQLModel.metadata.create_all(self.engine)
        self.session = Session(self.engine)
        self.repo = TournamentRepository(self.session)

    def tearDown(self):
        self.session.close()

    def test_classify_battle_format(self):
        # Singles indicators
        self.assertEqual(classify_battle_format("ChampionMads SINGLES Battle Arena #1"), "singles")
        self.assertEqual(classify_battle_format("Rising Stars - S2 (Single Battle)"), "singles")
        self.assertEqual(classify_battle_format("GVGCL 3v3 Mini Series"), "singles")
        self.assertEqual(classify_battle_format("BSS Series 1 Open"), "singles")
        self.assertEqual(classify_battle_format("Custom 1v1 Tourney"), "singles")
        self.assertEqual(classify_battle_format("6v6 OU Invitational"), "singles")

        # Bracket formats like 'Single Elimination' or 'Single-Elimination' should NOT be classified as singles
        self.assertEqual(classify_battle_format("Champions Cup - Single Elimination"), "doubles")
        self.assertEqual(classify_battle_format("Frankfurt Regional - Single Elim"), "doubles")
        self.assertEqual(classify_battle_format("Champions Single-Elimination Weekly"), "doubles")

        # Standard doubles tournaments
        self.assertEqual(classify_battle_format("Orlando Regional Championships"), "doubles")
        self.assertEqual(classify_battle_format("VGC 2026 World Championships"), "doubles")

    def test_search_and_count_teams_with_format_filter(self):
        # 1. Doubles tournament
        t_doubles = TournamentRecord(
            tournament_id="tourney-doubles-1",
            name="VGC World Championship 2026",
            event_date=datetime.now(timezone.utc),
            format_regulation="Regulation M-C",
            game_platform="Pokémon Champions",
            battle_format="doubles",
        )
        self.repo.upsert_tournament(t_doubles)

        team_doubles = TournamentTeamRecord(
            tournament_id="tourney-doubles-1",
            player_name="Player 1",
            placement=1,
            showdown_text="Incineroar @ Sitrus Berry\n",
        )
        m_doubles = TournamentTeamMemberRecord(
            slot_position=1,
            canonical_id="incineroar",
            base_canonical_id="incineroar",
            species_name="Incineroar",
        )
        self.repo.save_team(team_doubles, [m_doubles])

        # 2. Singles tournament
        t_singles = TournamentRecord(
            tournament_id="tourney-singles-1",
            name="Singles Arena Cup",
            event_date=datetime.now(timezone.utc),
            format_regulation="Regulation M-C",
            game_platform="Pokémon Champions",
            battle_format="singles",
        )
        self.repo.upsert_tournament(t_singles)

        team_singles = TournamentTeamRecord(
            tournament_id="tourney-singles-1",
            player_name="Player 2",
            placement=1,
            showdown_text="Incineroar @ Choice Band\n",
        )
        m_singles = TournamentTeamMemberRecord(
            slot_position=1,
            canonical_id="incineroar",
            base_canonical_id="incineroar",
            species_name="Incineroar",
        )
        self.repo.save_team(team_singles, [m_singles])

        # Default filter ("doubles")
        doubles_teams = self.repo.search_teams(battle_format_filter="doubles")
        self.assertEqual(len(doubles_teams), 1)
        self.assertEqual(doubles_teams[0].player_name, "Player 1")
        self.assertEqual(self.repo.count_teams(battle_format_filter="doubles"), 1)

        # Singles filter ("singles")
        singles_teams = self.repo.search_teams(battle_format_filter="singles")
        self.assertEqual(len(singles_teams), 1)
        self.assertEqual(singles_teams[0].player_name, "Player 2")
        self.assertEqual(self.repo.count_teams(battle_format_filter="singles"), 1)

        # All formats (None)
        all_teams = self.repo.search_teams(battle_format_filter=None)
        self.assertEqual(len(all_teams), 2)
        self.assertEqual(self.repo.count_teams(battle_format_filter=None), 2)

    def test_usage_queries_filter_by_battle_format(self):
        t_doubles = TournamentRecord(
            tournament_id="tourney-d",
            name="Doubles Tourney",
            event_date=datetime.now(timezone.utc),
            format_regulation="Regulation M-C",
            battle_format="doubles",
        )
        t_singles = TournamentRecord(
            tournament_id="tourney-s",
            name="Singles Tourney",
            event_date=datetime.now(timezone.utc),
            format_regulation="Regulation M-C",
            battle_format="singles",
        )
        self.repo.upsert_tournament(t_doubles)
        self.repo.upsert_tournament(t_singles)

        # Create team in doubles
        team_d = TournamentTeamRecord(
            tournament_id="tourney-d",
            player_name="D Player",
            placement=1,
            showdown_text="Incineroar @ Sitrus Berry\n- Fake Out\n",
        )
        m_d = TournamentTeamMemberRecord(
            slot_position=1,
            canonical_id="incineroar",
            base_canonical_id="incineroar",
            species_name="Incineroar",
            moves=["Fake Out"],
            nature="Careful",
            item="Sitrus Berry",
            ability="Intimidate",
        )
        self.repo.save_team(team_d, [m_d])

        # Create team in singles
        team_s = TournamentTeamRecord(
            tournament_id="tourney-s",
            player_name="S Player",
            placement=1,
            showdown_text="Incineroar @ Choice Band\n- Swords Dance\n",
        )
        m_s = TournamentTeamMemberRecord(
            slot_position=1,
            canonical_id="incineroar",
            base_canonical_id="incineroar",
            species_name="Incineroar",
            moves=["Swords Dance"],
            nature="Jolly",
            item="Choice Band",
            ability="Blaze",
        )
        self.repo.save_team(team_s, [m_s])

        # Individual species move_usage
        d_moves = self.repo.move_usage("incineroar", battle_format="doubles")
        self.assertEqual(d_moves, [("Fake Out", 1)])
        s_moves = self.repo.move_usage("incineroar", battle_format="singles")
        self.assertEqual(s_moves, [("Swords Dance", 1)])
        all_moves = self.repo.move_usage("incineroar", battle_format=None)
        self.assertEqual(len(all_moves), 2)

        # Bulk move_usage_all
        all_d_moves = self.repo.move_usage_all(battle_format="doubles")
        self.assertEqual(all_d_moves.get("incineroar"), [("Fake Out", 1)])
        all_s_moves = self.repo.move_usage_all(battle_format="singles")
        self.assertEqual(all_s_moves.get("incineroar"), [("Swords Dance", 1)])

        # Natures
        d_natures = self.repo.nature_usage_all(battle_format="doubles")
        self.assertEqual(d_natures.get("incineroar"), [("careful", 1)])
        s_natures = self.repo.nature_usage_all(battle_format="singles")
        self.assertEqual(s_natures.get("incineroar"), [("jolly", 1)])

        # Items
        d_items = self.repo.item_usage_all(battle_format="doubles")
        self.assertEqual(d_items.get("incineroar"), [("Sitrus Berry", 1)])
        s_items = self.repo.item_usage_all(battle_format="singles")
        self.assertEqual(s_items.get("incineroar"), [("Choice Band", 1)])

        # Abilities
        d_abilities = self.repo.ability_usage_all(battle_format="doubles")
        self.assertEqual(d_abilities.get("incineroar"), [("Intimidate", 1)])
        s_abilities = self.repo.ability_usage_all(battle_format="singles")
        self.assertEqual(s_abilities.get("incineroar"), [("Blaze", 1)])

    def test_remediate_tournament_battle_formats(self):
        t1 = TournamentRecord(
            tournament_id="t-singles-old",
            name="Rising Stars - S2 (Single Battle)",
            event_date=datetime.now(timezone.utc),
            format_regulation="Champions Season 1",
            battle_format="doubles",
        )
        t2 = TournamentRecord(
            tournament_id="t-doubles-old",
            name="Liverpool Regional Championships",
            event_date=datetime.now(timezone.utc),
            format_regulation="Champions Season 1",
            battle_format="doubles",
        )
        self.repo.upsert_tournament(t1)
        self.repo.upsert_tournament(t2)

        with self.engine.connect() as conn:
            _remediate_tournament_battle_formats(conn)

        # Re-fetch via session
        self.session.expire_all()
        fetched_t1 = self.repo.get_tournament("t-singles-old")
        fetched_t2 = self.repo.get_tournament("t-doubles-old")
        self.assertIsNotNone(fetched_t1)
        self.assertEqual(fetched_t1.battle_format, "singles")
        self.assertIsNotNone(fetched_t2)
        self.assertEqual(fetched_t2.battle_format, "doubles")

    def test_settings_store_preference(self):
        store = SettingsStore(session_factory=lambda: self.session)
        # Default should be doubles
        self.assertEqual(store.get_battle_format_preference(), "doubles")

        # Change to all
        store.set_battle_format_preference("all")
        self.assertEqual(store.get_battle_format_preference(), "all")

        # Change to singles
        store.set_battle_format_preference("singles")
        self.assertEqual(store.get_battle_format_preference(), "singles")

    def test_meta_store_filter_initialization(self):
        store = SettingsStore(session_factory=lambda: self.session)
        # When preference is 'singles'
        store.set_battle_format_preference("singles")

        meta_store = MetaStore(session_factory=lambda: self.session)
        self.assertEqual(meta_store.filters.battle_format, "singles")

        # When preference is 'all'
        store.set_battle_format_preference("all")
        meta_store = MetaStore(session_factory=lambda: self.session)
        self.assertEqual(meta_store.filters.battle_format, "all")


if __name__ == "__main__":
    unittest.main()

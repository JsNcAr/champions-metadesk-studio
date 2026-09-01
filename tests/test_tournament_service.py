import unittest
from datetime import datetime, timezone
from sqlmodel import Session, SQLModel, create_engine
from pokemon_champions_planning_tool.infrastructure.database.models import (
    TournamentRecord,
    TournamentTeamRecord,
    TournamentTeamMemberRecord,
)
from pokemon_champions_planning_tool.infrastructure.database.repositories import (
    TournamentRepository,
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

        # Query top partners for Charizard. This fixture is deliberately tiny and
        # exercises the counting logic, so it opts below the default sample floor.
        partners = self.svc.get_top_partners("charizard", limit=5, min_sample_teams=1)
        self.assertTrue(len(partners) >= 1)
        top_partner = partners[0]
        self.assertEqual(top_partner.canonical_id, "pikachu")
        self.assertEqual(top_partner.co_occurrence_count, 2)
        self.assertEqual(top_partner.synergy_percentage, 100.0)



class TestMetaSynergyService(unittest.TestCase):
    """Partner recommendations must be accurate, sprite-resolved and honest about
    the sample they are computed from."""

    def setUp(self):
        self.engine = create_engine("sqlite:///:memory:")
        SQLModel.metadata.create_all(self.engine)
        self.session = Session(self.engine)
        self.repo = TournamentRepository(self.session)
        self.repo.upsert_tournament(
            TournamentRecord(
                tournament_id="t-main",
                name="Champions Cup",
                event_date=datetime(2026, 8, 1, tzinfo=timezone.utc),
                format_regulation="Regulation M-A",
                game_platform="Pokémon Champions",
            )
        )
        self.repo.upsert_tournament(
            TournamentRecord(
                tournament_id="t-other",
                name="Other Format Cup",
                event_date=datetime(2026, 8, 2, tzinfo=timezone.utc),
                format_regulation="Regulation H",
                game_platform="Pokémon Champions",
            )
        )

    def tearDown(self):
        self.session.close()
        self.engine.dispose()

    def _add_team(self, species, tournament_id="t-main", placement=1):
        team = TournamentTeamRecord(
            tournament_id=tournament_id,
            player_name=f"player-{placement}-{species[0]}",
            placement=placement,
            showdown_text="x",
        )
        members = [
            TournamentTeamMemberRecord(slot_position=i, canonical_id=name, species_name=name.title())
            for i, name in enumerate(species, start=1)
        ]
        self.repo.save_team(team, members)

    def test_counts_and_percentages(self):
        """Co-occurrence counts and shares are computed over target teams."""
        for _ in range(4):
            self._add_team(["incineroar", "rillaboom"])
        self._add_team(["incineroar", "amoonguss"])

        svc = MetaSynergyService(self.session)
        partners = {p.canonical_id: p for p in svc.get_top_partners("incineroar")}

        self.assertEqual(partners["rillaboom"].co_occurrence_count, 4)
        self.assertEqual(partners["rillaboom"].total_target_teams, 5)
        self.assertEqual(partners["rillaboom"].synergy_percentage, 80.0)
        self.assertEqual(partners["amoonguss"].co_occurrence_count, 1)
        self.assertNotIn("incineroar", partners, "target must not recommend itself")

    def test_small_samples_are_withheld(self):
        """A 2-team sample must not produce confident-looking percentages."""
        for _ in range(2):
            self._add_team(["pikachu", "venusaur"])

        svc = MetaSynergyService(self.session)
        self.assertEqual(svc.get_top_partners("pikachu"), [], "below the sample floor")
        self.assertTrue(
            svc.get_top_partners("pikachu", min_sample_teams=1),
            "an explicit lower floor still opts in",
        )

    def test_every_partner_resolves_a_sprite(self):
        """Species with no local PokemonRecord still render, via the CDN fallback."""
        for _ in range(5):
            self._add_team(["incineroar", "urshifu-rapid-strike"])

        partners = MetaSynergyService(self.session).get_top_partners("incineroar")
        self.assertTrue(partners)
        for p in partners:
            self.assertTrue(p.sprite_url, f"{p.canonical_id} rendered without a sprite")

    def test_regulation_filter_restricts_the_sample(self):
        """Filtering by regulation changes both numerator and denominator."""
        for _ in range(5):
            self._add_team(["incineroar", "rillaboom"], tournament_id="t-main")
        for _ in range(5):
            self._add_team(["incineroar", "amoonguss"], tournament_id="t-other")

        svc = MetaSynergyService(self.session)
        all_formats = {p.canonical_id for p in svc.get_top_partners("incineroar")}
        self.assertEqual(all_formats, {"rillaboom", "amoonguss"})

        reg_a = svc.get_top_partners("incineroar", regulation_filter="Regulation M-A")
        self.assertEqual({p.canonical_id for p in reg_a}, {"rillaboom"})
        self.assertEqual(reg_a[0].total_target_teams, 5, "denominator is filtered too")

    def test_unknown_species_returns_nothing(self):
        for _ in range(5):
            self._add_team(["incineroar", "rillaboom"])
        self.assertEqual(MetaSynergyService(self.session).get_top_partners("missingno"), [])


class TestTournamentSearchOrdering(unittest.TestCase):
    """Search results must favour recent events, and the filters must compose."""

    def setUp(self):
        self.engine = create_engine("sqlite:///:memory:")
        SQLModel.metadata.create_all(self.engine)
        self.session = Session(self.engine)
        self.repo = TournamentRepository(self.session)

        for idx, (t_id, day) in enumerate([("t-old", 1), ("t-new", 20)]):
            self.repo.upsert_tournament(
                TournamentRecord(
                    tournament_id=t_id,
                    name=f"{t_id} Championship",
                    event_date=datetime(2026, 8, day, tzinfo=timezone.utc),
                    format_regulation="Regulation M-A",
                    game_platform="Pokémon Champions",
                )
            )
            for placement in (1, 2, 3):
                team = TournamentTeamRecord(
                    tournament_id=t_id,
                    player_name=f"{t_id}-p{placement}",
                    placement=placement,
                    showdown_text="x",
                )
                self.repo.save_team(
                    team,
                    [
                        TournamentTeamMemberRecord(
                            slot_position=1, canonical_id="incineroar", species_name="Incineroar"
                        )
                    ],
                )

    def tearDown(self):
        self.session.close()
        self.engine.dispose()

    def test_recent_events_come_first(self):
        """A capped result set must not be monopolised by the oldest event's winners."""
        results = self.repo.search_teams(limit=3)
        self.assertEqual(
            [t.tournament_id for t in results],
            ["t-new"] * 3,
            "newest event first",
        )
        self.assertEqual([t.placement for t in results], [1, 2, 3], "best placement within it")

    def test_species_filter_is_independent_of_query(self):
        """species_filter narrows the query rather than being silently ignored."""
        both = self.repo.search_teams(query="t-new-p1", species_filter="incineroar")
        self.assertEqual(len(both), 1)

        # Previously this branch was skipped whenever species_filter == query.
        same = self.repo.search_teams(query="incineroar", species_filter="incineroar")
        self.assertEqual(len(same), 6)

        self.assertEqual(self.repo.search_teams(species_filter="pikachu"), [])

    def test_query_matches_event_name(self):
        self.assertEqual(len(self.repo.search_teams(query="t-old Championship")), 3)


if __name__ == "__main__":
    unittest.main()

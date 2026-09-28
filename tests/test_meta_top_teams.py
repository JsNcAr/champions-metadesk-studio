"""Meta › Top teams: grouping tournament teams by lineup, the most common set, and the
repository query they are both built on."""

import sys
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path

from sqlmodel import Session, SQLModel, create_engine

sys.path.insert(0, str(Path(__file__).resolve().parent))

from pokemon_champions_planning_tool.domain.species import SpeciesInfo  # noqa: E402
from pokemon_champions_planning_tool.infrastructure.database.models import ItemRecord, MegaEvolutionRecord  # noqa: E402
from pokemon_champions_planning_tool.infrastructure.database.models import (  # noqa: E402
    TournamentRecord,
    TournamentTeamMemberRecord,
    TournamentTeamRecord,
)
from pokemon_champions_planning_tool.services.showdown_service import parse_showdown_text  # noqa: E402
from pokemon_champions_planning_tool.services.tournament_service import TournamentService  # noqa: E402
from pokemon_champions_planning_tool.ui.catalogs import Catalogs  # noqa: E402
from pokemon_champions_planning_tool.ui.views.meta.top_teams import (  # noqa: E402
    TREND_MIN_SAMPLE,
    consensus_paste,
    group_teams,
    member_key,
)

D0 = datetime(2026, 9, 1, tzinfo=timezone.utc)   # "today" for the fixtures below


def species(canonical_id, name, base_species_id=None, is_mega=False, required_item=None):
    return SpeciesInfo(
        canonical_id=canonical_id, showdown_id=name.lower().replace("-", ""), name=name, dex_number=1,
        base_species_id=base_species_id or canonical_id, forme=None, types=("Normal",), base_stats={"hp": 80, "atk": 80, "def": 80, "spa": 80, "spd": 80, "spe": 80},
        abilities=("Levitate",), weightkg=50.0, gender=None, required_item=required_item, battle_only=None, is_mega=is_mega, is_legal=True,
    )


TYRANITAR = species("tyranitar", "Tyranitar")
INCINEROAR = species("incineroar", "Incineroar")
GARCHOMP = species("garchomp", "Garchomp")
RILLABOOM = species("rillaboom", "Rillaboom")
FLUTTER_MANE = species("flutter-mane", "Flutter Mane")
GRIMMSNARL = species("grimmsnarl", "Grimmsnarl")
CHARIZARD = species("charizard", "Charizard")
MEGA_X = species("charizard-mega-x", "Charizard-Mega-X", base_species_id="charizard", is_mega=True, required_item="Charizardite X")
MEGA_Y = species("charizard-mega-y", "Charizard-Mega-Y", base_species_id="charizard", is_mega=True, required_item="Charizardite Y")

CATALOGS = Catalogs(
    species_by_canonical={s.canonical_id: s for s in (TYRANITAR, INCINEROAR, GARCHOMP, RILLABOOM, FLUTTER_MANE, GRIMMSNARL, CHARIZARD, MEGA_X, MEGA_Y)},
    items_by_id={
        "charizardite-x": ItemRecord(canonical_id="charizardite-x", display_name="Charizardite X", category="mega-stone", is_champions_legal=True, target_species="charizard", target_form="mega-x"),
        "charizardite-y": ItemRecord(canonical_id="charizardite-y", display_name="Charizardite Y", category="mega-stone", is_champions_legal=True, target_species="charizard", target_form="mega-y"),
    },
    megas=(
        MegaEvolutionRecord(canonical_id="charizard-mega-x", species_name="Charizard", display_name="Mega Charizard X", form_name="Mega X", types=["Fire", "Dragon"], hp=78, attack=130, defense=111, special_attack=130, special_defense=85, speed=100, ability="Tough Claws"),
        MegaEvolutionRecord(canonical_id="charizard-mega-y", species_name="Charizard", display_name="Mega Charizard Y", form_name="Mega Y", types=["Fire", "Flying"], hp=78, attack=104, defense=78, special_attack=159, special_defense=115, speed=100, ability="Drought"),
    ),
)

# A six-species core shared by every fixture team below, so "the same lineup" tests only
# vary Tyranitar's item (or swap it for a Mega Charizard).
CORE = ("incineroar", "garchomp", "rillaboom", "flutter-mane", "grimmsnarl")


def _team_text(header: str, moves=("Move A", "Move B", "Move C", "Move D"), points=None, nature=None) -> str:
    lines = [header]
    if points:
        lines.append(f"EVs: {points}")
    if nature:
        lines.append(f"{nature} Nature")
    lines += [f"- {m}" for m in moves]
    return "\n".join(lines)


class _RepoBase(unittest.TestCase):
    def setUp(self):
        self.engine = create_engine("sqlite:///:memory:")
        SQLModel.metadata.create_all(self.engine)
        self.addCleanup(self.engine.dispose)
        self.session = Session(self.engine)
        self.svc = TournamentService(self.session)
        self._tournaments = set()

    def tearDown(self):
        self.session.close()

    def _tournament(self, tid: str, *, date: datetime = D0, regulation: str = "Regulation M-C", battle_format: str = "doubles") -> None:
        if tid in self._tournaments:
            return
        self._tournaments.add(tid)
        self.svc.repo.upsert_tournament(TournamentRecord(tournament_id=tid, name=f"Cup {tid}", event_date=date, format_regulation=regulation, battle_format=battle_format))

    def add_team(self, *, tid="t1", date=D0, regulation="Regulation M-C", battle_format="doubles",
                 player="P", placement=1, tyranitar_item="Choice Scarf", mega=None, extra_species=CORE,
                 nature=None, points=None, move_overrides=None) -> str:
        """A six-member team: Tyranitar (or a Mega Charizard form) plus ``extra_species``."""
        self._tournament(tid, date=date, regulation=regulation, battle_format=battle_format)
        lead_cid = mega or "tyranitar"
        lead_item = None if mega else tyranitar_item
        if mega == "charizard-mega-x":
            lead_item = "Charizardite X"
        elif mega == "charizard-mega-y":
            lead_item = "Charizardite Y"
        header = "Charizard" if mega else f"Tyranitar{f' @ {tyranitar_item}' if tyranitar_item else ''}"
        if mega:
            header = f"Charizard @ {lead_item}"
        lead_moves = list(move_overrides or ("Move A", "Move B", "Move C", "Move D"))
        text = _team_text(header, moves=lead_moves, points=points, nature=nature)
        team = TournamentTeamRecord(tournament_id=tid, player_name=player, placement=placement, standing_label=f"Place #{placement}", showdown_text=text)
        members = [TournamentTeamMemberRecord(slot_position=1, canonical_id=lead_cid, species_name="Tyranitar" if not mega else "Charizard", item=lead_item, nature=nature, moves=lead_moves)]
        members += [TournamentTeamMemberRecord(slot_position=i, canonical_id=cid, species_name=cid.title()) for i, cid in enumerate(extra_species, start=2)]
        self.svc.repo.save_team(team, members)
        return str(team.tournament_team_id)

    def rows(self, **filters):
        return self.svc.team_members_for_filters(**filters)


class TestGrouping(_RepoBase):
    def test_different_items_group_together(self):
        self.add_team(tyranitar_item="Choice Scarf")
        self.add_team(tyranitar_item="Life Orb", player="P2")
        result = group_teams(self.rows(), CATALOGS)
        self.assertEqual(len(result.teams), 1)
        self.assertEqual(result.teams[0].count, 2)
        self.assertEqual(result.total_teams, 2)

    def test_a_mega_is_a_different_team(self):
        self.add_team(tyranitar_item="Choice Scarf")
        self.add_team(mega="charizard-mega-y", player="P2")
        result = group_teams(self.rows(), CATALOGS, min_teams=1)
        self.assertEqual(len(result.teams), 2)
        keys = {g.key for g in result.teams}
        self.assertIn(("charizard-mega-y", *sorted(CORE)), keys)

    def test_x_and_y_stones_differ(self):
        self.add_team(mega="charizard-mega-x")
        self.add_team(mega="charizard-mega-y", player="P2")
        result = group_teams(self.rows(), CATALOGS, min_teams=1)
        self.assertEqual(len(result.teams), 2)
        self.assertNotEqual(result.teams[0].key, result.teams[1].key)

    def test_slot_order_does_not_matter(self):
        self.add_team(tyranitar_item="Choice Scarf", extra_species=CORE)
        self.add_team(tyranitar_item="Choice Scarf", extra_species=tuple(reversed(CORE)), player="P2")
        result = group_teams(self.rows(), CATALOGS)
        self.assertEqual(len(result.teams), 1)
        self.assertEqual(result.teams[0].count, 2)

    def test_incomplete_teams_are_excluded_and_counted(self):
        self.add_team()
        self.add_team(player="P2")
        # A five-member team: drop one slot by hand.
        team = TournamentTeamRecord(tournament_id="t1", player_name="P3", placement=3, showdown_text="x")
        self.svc.repo.save_team(team, [TournamentTeamMemberRecord(slot_position=1, canonical_id="tyranitar", species_name="Tyranitar", item="Choice Scarf")])
        result = group_teams(self.rows(), CATALOGS)
        self.assertEqual(result.total_teams, 2, "the incomplete team does not count")
        self.assertEqual(result.incomplete_teams, 1)

    def test_a_one_off_is_hidden_but_counts_in_the_total(self):
        self.add_team(tyranitar_item="Choice Scarf")
        self.add_team(tyranitar_item="Life Orb", player="P2")
        self.add_team(mega="charizard-mega-y", player="P3")   # only one team: below the default minimum
        result = group_teams(self.rows(), CATALOGS)
        self.assertEqual(len(result.teams), 1, "the lone Mega team is hidden")
        self.assertEqual(result.total_teams, 3, "but still counted")
        self.assertAlmostEqual(result.teams[0].share, 2 / 3)

    def test_shares_add_up_to_the_visible_teams(self):
        self.add_team(tyranitar_item="Choice Scarf")
        self.add_team(tyranitar_item="Choice Scarf", player="P2")
        self.add_team(mega="charizard-mega-y", player="P3")
        self.add_team(mega="charizard-mega-y", player="P4")
        result = group_teams(self.rows(), CATALOGS)
        self.assertEqual(len(result.teams), 2)
        self.assertAlmostEqual(sum(g.share for g in result.teams), 1.0)

    def test_best_finish_and_top_cut(self):
        self.add_team(tyranitar_item="Choice Scarf", placement=1, player="Winner")
        self.add_team(tyranitar_item="Choice Scarf", placement=16, player="Loser")
        result = group_teams(self.rows(), CATALOGS)
        team = result.teams[0]
        self.assertEqual((team.best.placement, team.best.player_name), (1, "Winner"))
        self.assertAlmostEqual(team.top_cut, 0.5, msg="only the 1st-place finish is top 8")

    def test_trend_is_none_below_the_sample_floor(self):
        # A tournament's event_date is shared by every team recorded under it, so a
        # different date needs a different tournament id.
        self.add_team(tyranitar_item="Choice Scarf", date=D0, tid="t-recent")
        self.add_team(tyranitar_item="Choice Scarf", date=D0 - timedelta(days=45), player="P2", tid="t-prior")
        result = group_teams(self.rows(), CATALOGS)
        self.assertIsNone(result.teams[0].trend)

    def test_trend_reflects_a_swing_between_windows(self):
        # Every other team (a filler lineup) keeps both 30-day windows above the sample
        # floor; only Tyranitar's own share moves between them.
        for i in range(TREND_MIN_SAMPLE):
            self.add_team(mega="charizard-mega-x", date=D0, player=f"filler-recent-{i}", tid=f"t-recent-{i}")
            self.add_team(mega="charizard-mega-x", date=D0 - timedelta(days=45), player=f"filler-prior-{i}", tid=f"t-prior-{i}")
        for i in range(6):
            self.add_team(tyranitar_item="Choice Scarf", date=D0, player=f"recent-{i}", tid=f"t-tt-recent-{i}")
        self.add_team(tyranitar_item="Choice Scarf", date=D0 - timedelta(days=45), player="prior-0", tid="t-tt-prior")
        result = group_teams(self.rows(), CATALOGS, min_teams=1)
        tyranitar = next(g for g in result.teams if "tyranitar" in g.key)
        self.assertIsNotNone(tyranitar.trend)
        self.assertGreater(tyranitar.trend, 0, "Tyranitar picked up share in the recent window")


class TestConsensusSet(_RepoBase):
    def test_most_used_item_ability_nature_and_moves_are_picked(self):
        self.add_team(tyranitar_item="Choice Scarf", move_overrides=("Rock Slide", "Knock Off", "Ice Punch", "Low Kick"))
        self.add_team(tyranitar_item="Choice Scarf", player="P2", move_overrides=("Rock Slide", "Knock Off", "Ice Punch", "Stone Edge"))
        self.add_team(tyranitar_item="Life Orb", player="P3", move_overrides=("Rock Slide", "Knock Off", "Superpower", "Low Kick"))
        result = group_teams(self.rows(), CATALOGS)
        text = consensus_paste(result.teams[0], CATALOGS)
        self.assertIn("Tyranitar @ Choice Scarf", text, "held by 2 of 3 teams")
        self.assertIn("- Rock Slide", text)
        self.assertIn("- Knock Off", text)
        self.assertNotIn("Stone Edge", text, "only the top 4 moves by frequency")

    def test_a_mega_keeps_its_stone(self):
        self.add_team(mega="charizard-mega-y")
        self.add_team(mega="charizard-mega-y", player="P2")
        result = group_teams(self.rows(), CATALOGS)
        text = consensus_paste(result.teams[0], CATALOGS)
        self.assertIn("Charizard-Mega-Y @ Charizardite Y", text)

    def test_points_come_from_the_pastes_or_are_left_out(self):
        self.add_team(tyranitar_item="Choice Scarf", points="4 HP / 32 Atk", nature="Adamant")
        self.add_team(tyranitar_item="Choice Scarf", points="4 HP / 32 Atk", nature="Adamant", player="P2")
        with_points = group_teams(self.rows(), CATALOGS)
        text = consensus_paste(with_points.teams[0], CATALOGS)
        self.assertIn("EVs: 4 HP / 32 Atk", text)
        self.assertIn("Adamant Nature", text)

        self.engine.dispose()
        self.setUp()
        self.add_team(tyranitar_item="Choice Scarf")
        self.add_team(tyranitar_item="Choice Scarf", player="P2")
        no_points = group_teams(self.rows(), CATALOGS)
        text = consensus_paste(no_points.teams[0], CATALOGS)
        self.assertNotIn("EVs:", text, "no paste had a points line")

    def test_the_text_parses_back_to_the_same_six(self):
        self.add_team(tyranitar_item="Choice Scarf")
        self.add_team(tyranitar_item="Choice Scarf", player="P2")
        result = group_teams(self.rows(), CATALOGS)
        text = consensus_paste(result.teams[0], CATALOGS)
        parsed = parse_showdown_text(text)
        self.assertEqual(len(parsed.slots), 6)
        self.assertEqual({s.species_name.lower() for s in parsed.slots}, {"tyranitar", "incineroar", "garchomp", "rillaboom", "flutter mane", "grimmsnarl"})


class TestMemberKey(unittest.TestCase):
    def test_no_item_keeps_the_base_species(self):
        self.assertEqual(member_key("charizard", None, CATALOGS), "charizard")

    def test_a_foreign_item_does_not_trigger_a_mega(self):
        self.assertEqual(member_key("charizard", "Choice Scarf", CATALOGS), "charizard")

    def test_already_a_mega_id_is_kept(self):
        self.assertEqual(member_key("charizard-mega-y", None, CATALOGS), "charizard-mega-y")


class TestRepositoryFilters(_RepoBase):
    def test_team_ids_match_count_teams(self):
        self.add_team(regulation="Regulation M-C", battle_format="doubles")
        self.add_team(regulation="Regulation M-C", battle_format="doubles", player="P2")
        self.add_team(regulation="Regulation M-B", battle_format="doubles", player="P3", tid="t2")
        self.add_team(regulation="Regulation M-C", battle_format="singles", player="P4", tid="t3")

        for kwargs in (
            {},
            {"regulation_filter": "Regulation M-C"},
            {"battle_format_filter": "singles"},
            {"battle_format_filter": "all"},
            {"placement_filter": 1},
        ):
            with self.subTest(**kwargs):
                team_ids = {row.team_id for row in self.svc.team_members_for_filters(**kwargs)}
                self.assertEqual(len(team_ids), self.svc.count_teams(**kwargs))

    def test_every_matched_team_has_six_member_rows(self):
        self.add_team()
        rows = self.rows()
        self.assertEqual(len(rows), 6)
        self.assertEqual({r.slot for r in rows}, {1, 2, 3, 4, 5, 6})


if __name__ == "__main__":
    unittest.main()

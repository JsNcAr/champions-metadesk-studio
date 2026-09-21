"""Indexed search paths, the partner cache and the daily startup gate."""

import unittest
from datetime import datetime, timedelta, timezone

from sqlmodel import Session, SQLModel, create_engine

from pokemon_champions_planning_tool.infrastructure.database.models import (
    ChampionsSpeciesRecord,
    TournamentRecord,
    TournamentTeamMemberRecord,
    TournamentTeamRecord,
)
from pokemon_champions_planning_tool.domain.pokemon_identity import base_canonical_id
from pokemon_champions_planning_tool.infrastructure.database.repositories import TournamentRepository
from pokemon_champions_planning_tool.main import _startup_check_due
from pokemon_champions_planning_tool.services.tournament_service import TournamentService


class _Db(unittest.TestCase):
    def setUp(self):
        self.engine = create_engine("sqlite:///:memory:")
        SQLModel.metadata.create_all(self.engine)
        self.addCleanup(self.engine.dispose)
        self.session = Session(self.engine)
        now = datetime.now(timezone.utc)
        self.session.add(ChampionsSpeciesRecord(entry_number=1, species_name="charizard", display_name="Charizard"))
        self.session.add(TournamentRecord(tournament_id="t", name="T", event_date=now, format_regulation="Regulation M-B", game_platform="Pokémon Champions"))
        self.session.commit()
        for i, roster in enumerate((["charizard-mega-y", "incineroar"], ["charizard", "rillaboom"], ["flutter-mane", "rillaboom"], ["rillaboom", "incineroar"])):
            team = TournamentTeamRecord(tournament_id="t", player_name=f"p{i}", placement=i + 1, showdown_text="x")
            self.session.add(team); self.session.commit()
            for slot, cid in enumerate(roster, start=1):
                self.session.add(TournamentTeamMemberRecord(tournament_team_id=team.tournament_team_id, slot_position=slot, canonical_id=cid, species_name=cid.replace("-", " ").title()))
        self.session.commit()
        self.repo = TournamentRepository(self.session)

    def tearDown(self):
        self.session.close()


class TestIndexedSearch(_Db):
    def test_catalogue_species_search_includes_forms_and_unknown_names_still_scan(self):
        by_player = lambda rows: sorted(t.player_name for t in rows)  # noqa: E731
        self.assertEqual(by_player(self.repo.search_teams(query="Chariz")), ["p0", "p1"], "base and mega form via the indexed clause")
        self.assertEqual(self.repo._species_ids_matching("chariz", "chariz"), ["charizard"])
        self.assertEqual(self.repo._species_ids_matching("flutter", "flutter-mane"), [], "not in the Champions catalogue")
        self.assertEqual(by_player(self.repo.search_teams(query="flutter")), ["p2"], "fallback substring scan")
        self.assertEqual(self.repo.count_teams(query="rillaboom"), 3)

    def test_partner_target_uses_forms(self):
        svc = TournamentService(self.session)
        partners = svc.get_top_partners("charizard", limit=3, min_sample_teams=1)
        self.assertEqual(sorted(p.canonical_id for p in partners), ["incineroar", "rillaboom"])
        self.assertEqual(partners[0].co_occurrence_count, 1)
        self.assertEqual(partners[0].total_target_teams, 2, "mega roster counts as a Charizard team")


class TestPartnerCacheAndStartupGate(_Db):
    def test_partner_cache_serves_repeat_requests_until_invalidated(self):
        from pokemon_champions_planning_tool.ui.catalogs import Catalogs
        from pokemon_champions_planning_tool.ui.views.team.store import TeamStore

        store = TeamStore(Catalogs(), lambda: Session(self.engine))
        store._partner_cache[("charizard", 3)] = ["cached"]
        slot = store.slot(1)
        from pokemon_champions_planning_tool.domain.entities.box_entry import BoxEntry
        from pokemon_champions_planning_tool.domain.entities.pokemon import Pokemon
        from pokemon_champions_planning_tool.domain.entities.pokemon_stats import PokemonStats
        from pokemon_champions_planning_tool.domain.entities.team_member import TeamMember

        entry = BoxEntry(pokemon=Pokemon(canonical_id="charizard-mega-y", display_name="Mega Charizard Y", species_name="charizard", types=["fire", "flying"], stats=PokemonStats(hp=1, attack=1, defense=1, sp_atk=1, sp_def=1, speed=1)))
        slot.entry, slot.member = entry, TeamMember(box_entry_id=entry.box_entry_id, slot_position=1)
        self.assertEqual(store.partners(1, limit=3), ["cached"], "mega form shares the base species' cache entry")
        batch = store.partners_for_positions([1, 2], limit=3)
        self.assertEqual(batch[1], ["cached"])
        self.assertEqual(batch[2], [])
        store.invalidate_partners()
        self.assertEqual(store._partner_cache, {})

    def test_catalogues_missing_drives_the_first_run_banner(self):
        """The GUI opens on whatever is stored; this is how it knows to say "setting up"."""
        from pokemon_champions_planning_tool.infrastructure.database.models import (
            ItemRecord,
            MoveRecord,
            SpeciesRecord,
        )
        from pokemon_champions_planning_tool.main import catalogues_missing

        # _Db seeds champions_species only, so three catalogues are still empty.
        self.assertTrue(catalogues_missing(self.session))
        self.session.add(ItemRecord(canonical_id="leftovers", display_name="Leftovers"))
        self.session.add(MoveRecord(move_id="tackle", name="Tackle"))
        self.session.commit()
        self.assertTrue(catalogues_missing(self.session), "species catalogue still empty")
        self.session.add(SpeciesRecord(showdown_id="charizard", canonical_id="charizard", name="Charizard"))
        self.session.commit()
        self.assertFalse(catalogues_missing(self.session), "every catalogue has data now")

    def test_startup_gate_runs_once_per_day(self):
        self.assertTrue(_startup_check_due(self.session, "startup.test", hours=24))
        self.assertFalse(_startup_check_due(self.session, "startup.test", hours=24), "checked just now")
        self.repo.set_state("startup.test", (datetime.now(timezone.utc) - timedelta(hours=30)).isoformat())
        self.assertTrue(_startup_check_due(self.session, "startup.test", hours=24))


class TestRewrittenAggregates(unittest.TestCase):
    """The indexed forms of the box filter and per-species move usage.

    Both were rewritten for speed; these pin the results they must keep producing.
    """

    def setUp(self):
        self.engine = create_engine("sqlite:///:memory:")
        SQLModel.metadata.create_all(self.engine)
        self.addCleanup(self.engine.dispose)
        self.session = Session(self.engine)
        now = datetime.now(timezone.utc)
        self.session.add(TournamentRecord(tournament_id="d", name="Doubles Cup", event_date=now, format_regulation="Regulation M-C", battle_format="doubles"))
        self.session.add(TournamentRecord(tournament_id="s", name="Singles Cup", event_date=now, format_regulation="Regulation M-C", battle_format="singles"))
        self.session.commit()
        # (tournament, placement, roster of (canonical_id, moves))
        rosters = [
            ("d", 1, [("charizard", ["Heat Wave", "Protect"]), ("incineroar", ["Fake Out"])]),
            ("d", 2, [("charizard-mega-y", ["Heat Wave", "Solar Beam"]), ("rillaboom", ["Grassy Glide"])]),
            ("d", 3, [("charizard-mega-x", ["Flare Blitz"]), ("rotom-wash", ["Hydro Pump"])]),
            ("s", 1, [("charizard", ["Blast Burn"]), ("incineroar", ["Fake Out"])]),
        ]
        for tid, placement, roster in rosters:
            team = TournamentTeamRecord(tournament_id=tid, player_name=f"{tid}{placement}", placement=placement, showdown_text="x", member_count=len(roster))
            self.session.add(team)
            self.session.commit()
            for slot, (cid, moves) in enumerate(roster, start=1):
                self.session.add(TournamentTeamMemberRecord(
                    tournament_team_id=team.tournament_team_id, slot_position=slot, canonical_id=cid,
                    species_name=cid.replace("-", " ").title(), moves=list(moves),
                    base_canonical_id=base_canonical_id(cid),
                ))
        self.session.commit()
        self.repo = TournamentRepository(self.session)

    def tearDown(self):
        self.session.close()

    def test_move_usage_folds_mega_forms_and_honours_the_battle_format(self):
        doubles = dict(self.repo.move_usage("charizard"))
        self.assertEqual(doubles["Heat Wave"], 2, "base and Mega-Y rosters both count")
        self.assertEqual(doubles["Flare Blitz"], 1, "Mega-X counts too")
        self.assertNotIn("Blast Burn", doubles, "the singles roster is excluded")
        self.assertIn("Blast Burn", dict(self.repo.move_usage("charizard", battle_format="all")))
        self.assertNotIn("Solar Beam", dict(self.repo.move_usage("charizard", include_megas=False)))
        self.assertNotIn("Hydro Pump", doubles, "a different species whose id shares no prefix")

    def test_move_usage_does_not_swallow_other_forms_of_the_same_species(self):
        """The mega range must not reach past "<base>-mega…" into neighbouring ids."""
        self.assertEqual(dict(self.repo.move_usage("rotom")), {}, "rotom-wash is its own species")
        self.assertEqual(dict(self.repo.move_usage("rotom-wash"))["Hydro Pump"], 1)

    def test_box_filter_counts_and_orders_by_members_missing_from_the_box(self):
        owned = ["charizard", "incineroar"]
        self.assertEqual(self.repo.count_teams(owned_species=owned, max_missing=0, max_age_days=None), 1, "only the all-owned roster")
        self.assertEqual(self.repo.count_teams(owned_species=owned, max_missing=1, max_age_days=None), 3, "every doubles roster misses at most one")
        self.assertEqual(self.repo.count_teams(owned_species=[], max_missing=0, max_age_days=None), 0, "an empty box matches nothing")
        self.assertEqual(
            self.repo.count_teams(owned_species=owned, max_missing=1, max_age_days=None, battle_format_filter="all"), 4,
            "the singles roster joins in when the format filter is off",
        )
        rows = self.repo.search_teams(owned_species=owned, max_missing=1, max_age_days=None)
        self.assertEqual([r.player_name for r in rows][0], "d1", "the fully owned roster sorts first")


if __name__ == "__main__":
    unittest.main()

"""Indexed search paths, the partner cache and the daily startup gate."""

import unittest
from datetime import datetime, timedelta, timezone
from unittest.mock import patch

from sqlmodel import Session, SQLModel, create_engine, select

from pokemon_champions_planning_tool.infrastructure.database.models import (
    ChampionsSpeciesRecord,
    TournamentRecord,
    TournamentTeamMemberRecord,
    TournamentTeamRecord,
)
from pokemon_champions_planning_tool.infrastructure.database.repositories import TournamentRepository
from pokemon_champions_planning_tool.main import _startup_check_due
from pokemon_champions_planning_tool.services.tournament_service import TournamentService


class _Db(unittest.TestCase):
    def setUp(self):
        self.engine = create_engine("sqlite:///:memory:")
        SQLModel.metadata.create_all(self.engine)
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

    def test_startup_gate_runs_once_per_day(self):
        self.assertTrue(_startup_check_due(self.session, "startup.test", hours=24))
        self.assertFalse(_startup_check_due(self.session, "startup.test", hours=24), "checked just now")
        self.repo.set_state("startup.test", (datetime.now(timezone.utc) - timedelta(hours=30)).isoformat())
        self.assertTrue(_startup_check_due(self.session, "startup.test", hours=24))


if __name__ == "__main__":
    unittest.main()

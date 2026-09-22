"""Rival teams: the table and repository, the builders, and RivalStore."""

from __future__ import annotations

import unittest
from types import SimpleNamespace

from sqlmodel import Session, SQLModel, create_engine

from pokemon_champions_planning_tool.infrastructure.database.models import RivalTeamRecord
from pokemon_champions_planning_tool.infrastructure.database.repositories import RivalTeamRepository
from pokemon_champions_planning_tool.services.tournament_service import TournamentBuild
from pokemon_champions_planning_tool.ui.views.calc import CalcStore
from pokemon_champions_planning_tool.ui.views.calc.rival_store import (
    BATTLE_NAME,
    RivalStore,
    rival_from_species,
    rivals_from_meta_row,
    rivals_from_paste,
)
from pokemon_champions_planning_tool.ui.views.calc.state import RIVAL_FIELDS, PokemonState, RivalMember
from test_ui_calc import catalogs

PASTE = """Kingambit @ Life Orb
Ability: Defiant
EVs: 32 HP / 32 Atk / 2 Spe
Adamant Nature
- Kowtow Cleave
- Iron Head

Incineroar
Ability: Intimidate
- Flare Blitz

Missingno
- Tackle
"""


class _Db:
    def setUp(self):
        self.engine = create_engine("sqlite:///:memory:")
        SQLModel.metadata.create_all(self.engine)
        self.addCleanup(self.engine.dispose)
        self.sf = lambda: Session(self.engine)


class TestRepository(_Db, unittest.TestCase):
    def test_round_trip_and_a_single_battle_team(self):
        member = RivalMember(PokemonState(species="kingambit", moves=["Iron Head", None, None, None]), frozenset({"item"}))
        with self.sf() as s:
            repo = RivalTeamRepository(s)
            saved = repo.upsert(RivalTeamRecord(name="Wolfe", members=[member.to_dict()]))
            repo.upsert(RivalTeamRecord(name=BATTLE_NAME, kind="battle"))
            second = repo.upsert(RivalTeamRecord(name=BATTLE_NAME, kind="battle"))
            self.assertEqual(repo.battle().rival_team_id, second.rival_team_id, "a new battle replaces the old one")
            self.assertEqual([r.name for r in repo.list_saved()], ["Wolfe"])
            self.assertEqual(RivalMember.from_dict(repo.get(saved.rival_team_id).members[0]), member)
            self.assertTrue(repo.delete(saved.rival_team_id))
            self.assertEqual(repo.list_saved(), [])

    def test_create_all_adds_the_table_to_an_existing_database(self):
        from sqlalchemy import inspect

        engine = create_engine("sqlite:///:memory:")
        self.addCleanup(engine.dispose)
        others = [t for name, t in SQLModel.metadata.tables.items() if name != "rival_teams"]
        SQLModel.metadata.create_all(engine, tables=others)
        self.assertNotIn("rival_teams", inspect(engine).get_table_names())
        SQLModel.metadata.create_all(engine)
        self.assertIn("rival_teams", inspect(engine).get_table_names())


class TestBuilders(unittest.TestCase):
    def setUp(self):
        self.catalogs = catalogs()
        self.calc = CalcStore(self.catalogs, session_factory=None)
        self.calc.preset_builds = lambda: {"kingambit": TournamentBuild("kingambit", ["Kowtow Cleave", "Iron Head"], "adamant", "Black Glasses", "Defiant")}

    def test_team_preview_fills_the_tournament_set_all_assumed(self):
        member = rival_from_species(self.calc, "kingambit")
        self.assertEqual((member.pokemon.item, member.pokemon.moves[:2]), ("Black Glasses", ["Kowtow Cleave", "Iron Head"]))
        self.assertEqual(member.assumed, frozenset(RIVAL_FIELDS))
        plain = rival_from_species(self.calc, "incineroar")
        self.assertEqual(plain.assumed, frozenset(RIVAL_FIELDS), "no tournament data: a plain set, still a guess")
        self.assertIsNone(plain.pokemon.item)

    def test_a_paste_gives_known_sets(self):
        members, skipped = rivals_from_paste(PASTE, self.catalogs, source="Paste")
        self.assertEqual([m.pokemon.species for m in members], ["kingambit", "incineroar"])
        self.assertEqual(skipped, ["Missingno"])
        self.assertEqual(members[0].assumed, frozenset(), "everything came from the paste")
        self.assertEqual(members[0].pokemon.item, "Life Orb")
        self.assertEqual(members[1].assumed, frozenset({"points", "nature"}), "no spread or nature in the paste")

    def test_a_meta_row_matches_damage_calc_vs(self):
        row = SimpleNamespace(player_name="Wolfe", tournament_name="Worlds", showdown_text=PASTE,
                              members=[SimpleNamespace(canonical_id="kingambit"), SimpleNamespace(canonical_id="incineroar")])
        members = rivals_from_meta_row(row, self.catalogs)
        self.assertEqual(members[0].pokemon.source, "Wolfe · Worlds")
        self.assertEqual(members[0].pokemon.moves[:2], ["Kowtow Cleave", "Iron Head"])


class TestRivalStore(_Db, unittest.TestCase):
    def setUp(self):
        super().setUp()
        self.store = RivalStore(self.sf)
        self.store.load()
        self.members = [RivalMember(PokemonState(species="kingambit"), frozenset(RIVAL_FIELDS)),
                        RivalMember(PokemonState(species="incineroar"), frozenset({"points"}))]

    def test_battle_lifecycle(self):
        battle = self.store.start_battle(self.members)
        self.assertEqual((battle.name, self.store.active_id), (BATTLE_NAME, battle.rival_team_id))
        again = self.store.start_battle(self.members[:1])
        self.assertEqual(again.rival_team_id, battle.rival_team_id, "one battle team, reused")
        self.assertEqual(len(self.store.battle.members), 1)
        kept = self.store.save_battle_as("Kingambit mirror")
        self.store.end_battle()
        self.assertIsNone(self.store.battle)
        self.assertEqual([t.name for t in self.store.teams], ["Kingambit mirror"])
        reloaded = RivalStore(self.sf)
        reloaded.load()
        self.assertEqual(reloaded.get(kept.rival_team_id).members, kept.members)

    def test_saved_team_editing(self):
        team = self.store.create("Wolfe", self.members, source="Meta")
        self.store.rename(team.rival_team_id, "Wolfe — Worlds")
        copy = self.store.duplicate(team.rival_team_id)
        self.assertEqual(self.store.get(copy.rival_team_id).name, "Wolfe — Worlds (copy)")
        self.store.delete(team.rival_team_id)
        self.assertIsNone(self.store.get(team.rival_team_id))
        self.assertEqual(self.store.active_id, copy.rival_team_id)

    def test_revealed_fields_stop_being_assumed(self):
        battle = self.store.start_battle(self.members)
        version = self.store.version
        seen = PokemonState(species="kingambit", item="Black Glasses")
        self.store.update_member(battle.rival_team_id, 0, seen, revealed=["item"])
        member = self.store.battle.members[0]
        self.assertEqual(member.pokemon.item, "Black Glasses")
        self.assertEqual(member.assumed, frozenset(RIVAL_FIELDS) - {"item"})
        self.assertGreater(self.store.version, version)
        version = self.store.version
        self.store.update_member(battle.rival_team_id, 0, seen, revealed=["item"])
        self.assertEqual(self.store.version, version, "nothing changed: no write, no notification")


if __name__ == "__main__":
    unittest.main()

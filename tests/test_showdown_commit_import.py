"""commit_team_import: planned vs owned entries, reuse, slot cap, tera, validation."""

import shutil
import tempfile
import unittest
from pathlib import Path

from sqlmodel import Session, SQLModel, create_engine

from pokemon_champions_planning_tool.domain.entities.box_entry import BoxEntry
from pokemon_champions_planning_tool.domain.entities.pokemon import Pokemon
from pokemon_champions_planning_tool.domain.entities.pokemon_stats import PokemonStats
from pokemon_champions_planning_tool.infrastructure.database.repositories import BoxRepository, TeamRepository
from pokemon_champions_planning_tool.services.showdown_service import commit_team_import, parse_showdown_text

PASTE = """Incineroar @ Safety Goggles
Ability: Intimidate
Tera Type: Grass
EVs: 252 HP / 4 Atk / 252 SpD
Careful Nature
- Fake Out
- Knock Off
- Parting Shot
- Will-O-Wisp

Rillaboom @ Assault Vest
Ability: Grassy Surge
Level: 50
EVs: 252 HP / 252 Atk / 4 SpD
Adamant Nature
- Grassy Glide
- Wood Hammer
- Fake Out
- U-turn
"""


class TestCommitTeamImport(unittest.TestCase):
    def setUp(self):
        self.dir = tempfile.mkdtemp()
        self.engine = create_engine(f"sqlite:///{Path(self.dir) / 'import.db'}", connect_args={"check_same_thread": False})
        from pokemon_champions_planning_tool.infrastructure.database import models  # noqa: F401

        SQLModel.metadata.create_all(self.engine)
        self.session = Session(self.engine)
        self.parsed = parse_showdown_text(PASTE)
        self.assertTrue(self.parsed.is_valid)

    def tearDown(self):
        self.session.close()
        self.engine.dispose()
        shutil.rmtree(self.dir)

    def test_planned_import_creates_ghost_entries_and_members(self):
        result = commit_team_import(self.session, self.parsed, use_planned=True, team_name="Rain")
        self.assertEqual(result.team_name, "Rain")
        self.assertEqual(result.created_planned, ("Incineroar", "Rillaboom"))
        self.assertEqual(result.created_owned, ())
        box = BoxRepository(self.session)
        self.assertEqual(box.list_entries(include_planned=False), [], "ghosts stay out of the roster")
        ghosts = box.list_entries(include_planned=True)
        self.assertEqual(sorted(e.pokemon.display_name for e in ghosts), ["Incineroar", "Rillaboom"])
        self.assertTrue(all(e.is_planned and "imported" in e.tags and "Rain" in e.tags for e in ghosts))
        members = TeamRepository(self.session).get_members(result.team_id)
        self.assertEqual([m.slot_position for m in members], [1, 2])
        inc = members[0]
        self.assertEqual(inc.item, "Safety Goggles")
        self.assertEqual(inc.ability, "Intimidate")
        self.assertEqual(inc.tera_type, "grass", "tera type is carried and normalised")
        self.assertEqual(inc.nature, "Careful")
        self.assertEqual(inc.points.get("hp"), 32, "legacy EV lines land as stat points")
        self.assertEqual([m.name for m in inc.moveset], ["Fake Out", "Knock Off", "Parting Shot", "Will-O-Wisp"])
        self.assertIsNone(members[1].tera_type)

    def test_owned_import_adds_real_entries(self):
        result = commit_team_import(self.session, self.parsed, use_planned=False)
        self.assertEqual(result.team_name, "Imported Team", "untitled pastes get the default name")
        self.assertEqual(result.created_owned, ("Incineroar", "Rillaboom"))
        roster = BoxRepository(self.session).list_entries(include_planned=False)
        self.assertEqual(len(roster), 2)

    def test_reuses_existing_entries_by_name_or_canonical_id(self):
        box = BoxRepository(self.session)
        stats = PokemonStats(hp=95, attack=115, defense=90, sp_atk=80, sp_def=90, speed=60)
        existing = box.upsert_box_entry(BoxEntry(pokemon=Pokemon(canonical_id="incineroar", display_name="Incineroar", stats=stats)))
        result = commit_team_import(self.session, self.parsed, use_planned=False, team_name="Custom")
        self.assertEqual(result.team_name, "Custom")
        self.assertEqual(result.reused, ("Incineroar",))
        self.assertEqual(result.created_owned, ("Rillaboom",))
        members = TeamRepository(self.session).get_members(result.team_id)
        self.assertEqual(members[0].box_entry_id, existing.box_entry_id)

    def test_seven_slots_cap_to_six(self):
        block = "Pikachu\n- Thunderbolt\n\n"
        parsed = parse_showdown_text("".join(f"Mon{i}\n- Tackle\n\n" for i in range(7)))
        self.assertGreaterEqual(len(parsed.slots), 7)
        result = commit_team_import(self.session, parsed, use_planned=True)
        self.assertEqual(len(TeamRepository(self.session).get_members(result.team_id)), 6)

    def test_invalid_and_illegal_pastes_raise(self):
        with self.assertRaises(ValueError):
            commit_team_import(self.session, parse_showdown_text(""), use_planned=True)
        with self.assertRaises(ValueError) as ctx:
            commit_team_import(self.session, self.parsed, use_planned=True, legal_species=["incineroar"])
        self.assertIn("Rillaboom", str(ctx.exception))
        self.assertEqual(TeamRepository(self.session).list_all(), [], "nothing written before the legality check")


if __name__ == "__main__":
    unittest.main()

import tempfile
import shutil
from pathlib import Path
import unittest

from sqlmodel import SQLModel, Session, create_engine
from pokemon_champions_planning_tool.domain.entities.pokemon import Pokemon
from pokemon_champions_planning_tool.domain.entities.pokemon_stats import PokemonStats
from pokemon_champions_planning_tool.domain.entities.pokemon_ability import PokemonAbility
from pokemon_champions_planning_tool.domain.entities.box_entry import BoxEntry
from pokemon_champions_planning_tool.domain.entities.team import Team
from pokemon_champions_planning_tool.domain.entities.team_member import TeamMember
from pokemon_champions_planning_tool.infrastructure.database.repositories import (
    BoxRepository,
    TeamRepository,
    PokemonRepository,
)


class TestRepositories(unittest.TestCase):
    def setUp(self):
        self.test_dir = tempfile.mkdtemp()
        db_file = Path(self.test_dir) / "test_pokemon_champions.db"
        db_url = f"sqlite:///{db_file.resolve()}"
        self.engine = create_engine(db_url, connect_args={"check_same_thread": False})
        
        # Import models to register SQLModel tables
        from pokemon_champions_planning_tool.infrastructure.database import models  # noqa: F401
        
        SQLModel.metadata.create_all(self.engine)
        self.session = Session(self.engine)

    def tearDown(self):
        self.session.close()
        shutil.rmtree(self.test_dir)

    def test_pokemon_repository_upsert_and_get(self):
        repo = PokemonRepository(self.session)
        stats = PokemonStats(hp=35, attack=55, defense=40, sp_atk=50, sp_def=50, speed=90)
        pokemon = Pokemon(
            canonical_id="pikachu",
            display_name="Pikachu",
            species_name="pikachu",
            form_name="Base",
            dex_number=25,
            types=["electric"],
            sprite_url="http://example.com/sprite.png",
            stats=stats,
            abilities=[PokemonAbility(name="static", slot=1, is_hidden=False)],
            moves=[],
            available_forms=[],
        )

        record = repo.upsert(pokemon)
        self.assertEqual(record.canonical_id, "pikachu")
        self.assertEqual(record.display_name, "Pikachu")
        self.assertEqual(record.hp, 35)

        # Retrieve it
        fetched = repo.get("pikachu")
        self.assertIsNotNone(fetched)
        self.assertEqual(fetched.display_name, "Pikachu")
        self.assertEqual(fetched.to_domain().stats.speed, 90)

    def test_box_repository_crud(self):
        box_repo = BoxRepository(self.session)
        stats = PokemonStats(hp=35, attack=55, defense=40, sp_atk=50, sp_def=50, speed=90)
        pokemon = Pokemon(
            canonical_id="pikachu",
            display_name="Pikachu",
            species_name="pikachu",
            stats=stats,
        )
        
        entry = BoxEntry(pokemon=pokemon, notes="My favorite mouse", is_favorite=True)
        record = box_repo.upsert_box_entry(entry)
        
        self.assertEqual(record.pokemon_canonical_id, "pikachu")
        self.assertEqual(record.notes, "My favorite mouse")
        self.assertTrue(record.is_favorite)

        # Retrieve
        loaded = box_repo.load_entry("Pikachu")
        self.assertIsNotNone(loaded)
        self.assertEqual(loaded.pokemon.display_name, "Pikachu")
        self.assertEqual(loaded.notes, "My favorite mouse")

        # List entries
        entries = box_repo.list_entries()
        self.assertEqual(len(entries), 1)
        self.assertEqual(entries[0].pokemon.canonical_id, "pikachu")

        # Update metadata
        updated = box_repo.update_metadata("pikachu", notes="Sparky", is_favorite=False, tags=["electric", "fast"])
        self.assertIsNotNone(updated)
        self.assertEqual(updated.notes, "Sparky")
        self.assertFalse(updated.is_favorite)
        self.assertEqual(updated.tags, ["electric", "fast"])

        # Delete
        deleted = box_repo.delete_by_canonical_id("pikachu")
        self.assertTrue(deleted)
        self.assertIsNone(box_repo.load_entry("pikachu"))

    def test_team_repository_crud(self):
        team_repo = TeamRepository(self.session)
        box_repo = BoxRepository(self.session)

        # Insert a box entry to reference
        stats = PokemonStats(hp=35, attack=55, defense=40, sp_atk=50, sp_def=50, speed=90)
        pokemon = Pokemon(
            canonical_id="pikachu",
            display_name="Pikachu",
            species_name="pikachu",
            stats=stats,
        )
        box_entry = BoxEntry(pokemon=pokemon)
        box_record = box_repo.upsert_box_entry(box_entry)

        # Create team
        team = Team(name="Electric Storm", description="Main team")
        team_record = team_repo.create(team)
        self.assertEqual(team_record.name, "Electric Storm")
        
        # Resolve team
        resolved = team_repo.resolve("Electric Storm")
        self.assertIsNotNone(resolved)
        self.assertEqual(resolved.team_id, team_record.team_id)

        # Add member
        member = TeamMember(
            box_entry_id=box_record.box_entry_id,
            slot_position=1,
            item="Light Ball",
            ability="Static",
            notes="Lead sweeper",
        )
        team_repo.upsert_member(team_record.team_id, member)

        # Load team and verify
        loaded_team = team_repo.load_team(team_record.team_id)
        self.assertIsNotNone(loaded_team)
        self.assertEqual(len(loaded_team.members), 1)
        self.assertEqual(loaded_team.members[0].item, "Light Ball")
        self.assertEqual(loaded_team.members[0].slot_position, 1)

        # Rename team
        team_repo.rename(team_record.team_id, "Lightning Strike")
        self.assertEqual(team_repo.get(team_record.team_id).name, "Lightning Strike")

        # Delete member
        self.assertTrue(team_repo.delete_member(team_record.team_id, 1))
        self.assertEqual(len(team_repo.list_members(team_record.team_id)), 0)

        # Delete team
        self.assertTrue(team_repo.delete(team_record.team_id))
        self.assertIsNone(team_repo.get(team_record.team_id))

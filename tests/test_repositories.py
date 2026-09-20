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

        # Retrieve by UUID string
        loaded_by_uuid = box_repo.load_entry(str(record.box_entry_id))
        self.assertIsNotNone(loaded_by_uuid)
        self.assertEqual(loaded_by_uuid.pokemon.display_name, "Pikachu")

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

        # Add member with Mega form selection and competitive spread
        member = TeamMember(
            box_entry_id=box_record.box_entry_id,
            slot_position=1,
            selected_form="charizard-mega-x",
            item="Charizardite X",
            ability="Tough Claws",
            notes="Lead sweeper",
            points={"hp": 32, "attack": 32, "speed": 1},
            nature="Jolly",
        )
        team_repo.upsert_member(team_record.team_id, member)

        # Test get_members helper method
        members = team_repo.get_members(team_record.team_id)
        self.assertEqual(len(members), 1)
        self.assertEqual(members[0].selected_form, "charizard-mega-x")
        self.assertEqual(members[0].nature, "Jolly")
        self.assertEqual(members[0].points, {"hp": 32, "attack": 32, "speed": 1})

        # Test update (upsert) existing member spread fields
        member_update = TeamMember(
            box_entry_id=box_record.box_entry_id,
            slot_position=1,
            selected_form="charizard-mega-x",
            item="Charizardite X",
            ability="Tough Claws",
            notes="Updated sweeper",
            points={"hp": 1, "attack": 32, "speed": 32},
            nature="Adamant",
        )
        team_repo.upsert_member(team_record.team_id, member_update)
        updated_members = team_repo.get_members(team_record.team_id)
        self.assertEqual(len(updated_members), 1)
        self.assertEqual(updated_members[0].nature, "Adamant")
        self.assertEqual(updated_members[0].level, 50, "level is fixed in Champions")
        self.assertEqual(updated_members[0].points, {"hp": 1, "attack": 32, "speed": 32})
        member_points = TeamMember(box_entry_id=box_record.box_entry_id, slot_position=1, selected_form="charizard-mega-x", item="Charizardite X", ability="Tough Claws",
                                   points={"hp": 32, "defense": 32, "special_defense": 2}, nature="Impish")
        team_repo.upsert_member(team_record.team_id, member_points)
        self.assertEqual(team_repo.get_members(team_record.team_id)[0].points, {"hp": 32, "defense": 32, "special_defense": 2})

        # Load team and verify
        loaded_team = team_repo.load_team(team_record.team_id)
        self.assertIsNotNone(loaded_team)
        self.assertEqual(len(loaded_team.members), 1)
        self.assertEqual(loaded_team.members[0].selected_form, "charizard-mega-x")
        self.assertEqual(loaded_team.members[0].item, "Charizardite X")
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


class TestTeamMemberCounts(unittest.TestCase):
    """One grouped query behind the team pickers, which redraw on every card click."""

    def setUp(self):
        self.engine = create_engine("sqlite:///:memory:")
        SQLModel.metadata.create_all(self.engine)
        self.session = Session(self.engine)
        box_repo = BoxRepository(self.session)
        self.repo = TeamRepository(self.session)
        stats = PokemonStats(hp=35, attack=55, defense=40, sp_atk=50, sp_def=50, speed=90)
        self.entries = [
            box_repo.upsert_box_entry(BoxEntry(pokemon=Pokemon(canonical_id=cid, display_name=cid.title(), species_name=cid, stats=stats)))
            for cid in ("pikachu", "raichu", "pichu")
        ]

    def tearDown(self):
        self.session.close()

    def test_counts_every_team_including_the_empty_ones(self):
        full = self.repo.create(Team(name="Full"))
        one = self.repo.create(Team(name="One"))
        empty = self.repo.create(Team(name="Empty"))
        for slot, entry in enumerate(self.entries, start=1):
            self.repo.upsert_member(full.team_id, TeamMember(box_entry_id=entry.box_entry_id, slot_position=slot))
        self.repo.upsert_member(one.team_id, TeamMember(box_entry_id=self.entries[0].box_entry_id, slot_position=1))

        counts = self.repo.member_counts()
        self.assertEqual(counts.get(full.team_id), 3)
        self.assertEqual(counts.get(one.team_id), 1)
        self.assertNotIn(empty.team_id, counts, "an empty team has no rows to group")
        self.assertEqual(counts.get(empty.team_id, 0), 0, "callers read it with a default")

    def test_agrees_with_counting_each_team_separately(self):
        teams = [self.repo.create(Team(name=f"T{i}")) for i in range(3)]
        for i, team in enumerate(teams):
            for slot, entry in enumerate(self.entries[: i + 1], start=1):
                self.repo.upsert_member(team.team_id, TeamMember(box_entry_id=entry.box_entry_id, slot_position=slot))
        counts = self.repo.member_counts()
        for team in teams:
            self.assertEqual(counts.get(team.team_id, 0), len(self.repo.list_members(team.team_id)))


class TestTeamSlotSwapAndTera(unittest.TestCase):
    """swap_slots must respect uq_team_slot, and tera_type must round-trip."""

    def setUp(self):
        self.test_dir = tempfile.mkdtemp()
        db_url = f"sqlite:///{(Path(self.test_dir) / 'swap.db').resolve()}"
        self.engine = create_engine(db_url, connect_args={"check_same_thread": False})
        from pokemon_champions_planning_tool.infrastructure.database import models  # noqa: F401

        SQLModel.metadata.create_all(self.engine)
        self.session = Session(self.engine)
        self.box = BoxRepository(self.session)
        self.teams = TeamRepository(self.session)
        self.team = self.teams.create(Team(name="Swap Team"))
        self.entries = {}
        for name in ("incineroar", "rillaboom", "amoonguss"):
            stats = PokemonStats(hp=95, attack=115, defense=90, sp_atk=80, sp_def=90, speed=60)
            entry = BoxEntry(pokemon=Pokemon(canonical_id=name, display_name=name.title(), stats=stats))
            self.entries[name] = self.box.upsert_box_entry(entry)

    def tearDown(self):
        self.session.close()
        self.engine.dispose()
        shutil.rmtree(self.test_dir)

    def _assign(self, slot: int, name: str, **kwargs):
        return self.teams.upsert_member(
            self.team.team_id,
            TeamMember(box_entry_id=self.entries[name].box_entry_id, slot_position=slot, **kwargs),
        )

    def _slots(self):
        return {m.slot_position: m.box_entry_id for m in self.teams.list_members(self.team.team_id)}

    def test_swap_two_filled_slots(self):
        self._assign(1, "incineroar")
        self._assign(2, "rillaboom")
        self.assertTrue(self.teams.swap_slots(self.team.team_id, 1, 2))
        slots = self._slots()
        self.assertEqual(slots[1], self.entries["rillaboom"].box_entry_id)
        self.assertEqual(slots[2], self.entries["incineroar"].box_entry_id)
        self.assertEqual(set(slots), {1, 2}, "no parking slot left behind")

    def test_swap_with_empty_slot_moves(self):
        self._assign(1, "incineroar")
        self.assertTrue(self.teams.swap_slots(self.team.team_id, 1, 6))
        self.assertEqual(self._slots(), {6: self.entries["incineroar"].box_entry_id})
        self.assertTrue(self.teams.move_member(self.team.team_id, 3, 6), "swap from empty into filled pulls it back")
        self.assertEqual(self._slots(), {3: self.entries["incineroar"].box_entry_id})

    def test_swap_noops(self):
        self._assign(1, "incineroar")
        self.assertFalse(self.teams.swap_slots(self.team.team_id, 1, 1))
        self.assertFalse(self.teams.swap_slots(self.team.team_id, 4, 5))
        self.assertEqual(self._slots(), {1: self.entries["incineroar"].box_entry_id})

    def test_tera_type_round_trips_through_upsert(self):
        self._assign(1, "incineroar", tera_type="grass")
        self.assertEqual(self.teams.get_members(self.team.team_id)[0].tera_type, "grass")
        # Updating an existing slot must carry the field too (the explicit copy block).
        self._assign(1, "incineroar", tera_type="fire")
        self.assertEqual(self.teams.get_members(self.team.team_id)[0].tera_type, "fire")
        self._assign(1, "incineroar")
        self.assertIsNone(self.teams.get_members(self.team.team_id)[0].tera_type)

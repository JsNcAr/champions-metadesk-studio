import tempfile
import shutil
from pathlib import Path
import unittest
from unittest.mock import patch

from sqlmodel import SQLModel, Session, create_engine
from pokemon_champions_planning_tool.infrastructure.database.models import MegaEvolutionRecord
from pokemon_champions_planning_tool.infrastructure.database.repositories import MegaEvolutionRepository
from pokemon_champions_planning_tool.services.mega_evolution_service import sync_mega_evolutions_for_species


class TestMegaEvolutionBackend(unittest.TestCase):
    def setUp(self):
        self.test_dir = tempfile.mkdtemp()
        db_file = Path(self.test_dir) / "test_megas.db"
        db_url = f"sqlite:///{db_file.resolve()}"
        self.engine = create_engine(db_url, connect_args={"check_same_thread": False})

        from pokemon_champions_planning_tool.infrastructure.database import models  # noqa: F401
        SQLModel.metadata.create_all(self.engine)
        self.addCleanup(self.engine.dispose)
        self.session = Session(self.engine)

    def tearDown(self):
        self.session.close()
        shutil.rmtree(self.test_dir)

    def test_repository_crud(self):
        repo = MegaEvolutionRepository(self.session)
        rec = MegaEvolutionRecord(
            canonical_id="charizard-mega-x",
            species_name="charizard",
            display_name="Mega Charizard X",
            form_name="Mega X",
            types=["fire", "dragon"],
            sprite_url="https://raw.githubusercontent.com/PokeAPI/sprites/master/sprites/pokemon/10034.png",
            hp=78,
            attack=130,
            defense=111,
            special_attack=130,
            special_defense=85,
            speed=100,
        )

        saved = repo.upsert(rec)
        self.assertEqual(saved.canonical_id, "charizard-mega-x")
        self.assertEqual(saved.types, ["fire", "dragon"])

        by_species = repo.list_by_species("charizard")
        self.assertEqual(len(by_species), 1)
        self.assertEqual(by_species[0].display_name, "Mega Charizard X")

    @patch("pokemon_champions_planning_tool.services.mega_evolution_service.get_mega_varieties_for_species")
    @patch("pokemon_champions_planning_tool.services.mega_evolution_service.get_official_mega_details")
    def test_service_species_sync(self, mock_get_details, mock_get_varieties):
        mock_get_varieties.return_value = ["lucario-mega", "lucario-mega-z"]
        mock_get_details.side_effect = [
            MegaEvolutionRecord(
                canonical_id="lucario-mega",
                species_name="lucario",
                display_name="Mega Lucario",
                form_name="Mega",
                types=["fighting", "steel"],
                hp=70, attack=145, defense=88, special_attack=140, special_defense=70, speed=112
            ),
            MegaEvolutionRecord(
                canonical_id="lucario-mega-z",
                species_name="lucario",
                display_name="Mega Lucario Z",
                form_name="Mega Z",
                types=["fighting", "steel"],
                hp=70, attack=150, defense=90, special_attack=145, special_defense=75, speed=115
            )
        ]

        megas = sync_mega_evolutions_for_species(self.session, "lucario")
        self.assertEqual(len(megas), 2)
        self.assertEqual(megas[0].canonical_id, "lucario-mega")
        self.assertEqual(megas[1].canonical_id, "lucario-mega-z")

        # Second run uses cached database entries without re-calling mock_get_varieties
        mock_get_varieties.reset_mock()
        cached_megas = sync_mega_evolutions_for_species(self.session, "lucario")
        self.assertEqual(len(cached_megas), 2)
        mock_get_varieties.assert_not_called()

    @patch("pokemon_champions_planning_tool.services.mega_evolution_service.get_mega_varieties_for_species")
    def test_non_mega_species_sentinel_caching(self, mock_get_varieties):
        mock_get_varieties.return_value = []  # Pikachu has no Megas

        megas = sync_mega_evolutions_for_species(self.session, "pikachu")
        self.assertEqual(megas, [])
        mock_get_varieties.assert_called_once_with("pikachu")

        # Second call for Pikachu must NOT query PokéAPI again!
        mock_get_varieties.reset_mock()
        megas2 = sync_mega_evolutions_for_species(self.session, "pikachu")
        self.assertEqual(megas2, [])
        mock_get_varieties.assert_not_called()


if __name__ == "__main__":
    unittest.main()

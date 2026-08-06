import tempfile
import shutil
from pathlib import Path
import unittest
from unittest.mock import patch

from sqlmodel import SQLModel, Session, create_engine
from pokemon_champions_planning_tool.infrastructure.database.models import ChampionsSpeciesRecord
from pokemon_champions_planning_tool.infrastructure.database.repositories import ChampionsCatalogRepository
from pokemon_champions_planning_tool.services.champions_catalog_service import sync_champions_catalog_on_startup


class TestChampionsCatalog(unittest.TestCase):
    def setUp(self):
        self.test_dir = tempfile.mkdtemp()
        db_file = Path(self.test_dir) / "test_catalog.db"
        db_url = f"sqlite:///{db_file.resolve()}"
        self.engine = create_engine(db_url, connect_args={"check_same_thread": False})
        
        from pokemon_champions_planning_tool.infrastructure.database import models  # noqa: F401
        SQLModel.metadata.create_all(self.engine)
        self.session = Session(self.engine)

    def tearDown(self):
        self.session.close()
        shutil.rmtree(self.test_dir)

    def test_repository_sync_and_list(self):
        repo = ChampionsCatalogRepository(self.session)
        mock_entries = [
            {"entry_number": 1, "species_name": "bulbasaur", "display_name": "Bulbasaur"},
            {"entry_number": 2, "species_name": "ivysaur", "display_name": "Ivysaur"},
        ]
        
        res1 = repo.sync_species_entries(mock_entries)
        self.assertEqual(res1["added"], 2)
        self.assertEqual(res1["total_remote"], 2)

        # Retrieve
        species_names = repo.list_species_names()
        self.assertEqual(species_names, ["bulbasaur", "ivysaur"])

        # Second sync with no new entries
        res2 = repo.sync_species_entries(mock_entries)
        self.assertEqual(res2["added"], 0)
        self.assertEqual(res2["existing"], 2)

    @patch("pokemon_champions_planning_tool.services.champions_catalog_service.get_champions_pokedex_species")
    def test_service_startup_sync_delta(self, mock_get_species):
        mock_get_species.return_value = [
            {"entry_number": 1, "species_name": "venusaur", "display_name": "Venusaur"},
            {"entry_number": 2, "species_name": "charizard", "display_name": "Charizard"},
        ]

        # First run: inserts 2
        res1 = sync_champions_catalog_on_startup(self.session)
        self.assertEqual(res1["added"], 2)

        # Second run with same data: inserts 0 (no redundant DB writes)
        res2 = sync_champions_catalog_on_startup(self.session)
        self.assertEqual(res2["added"], 0)

        # Run with 1 new addition: inserts only the new 1
        mock_get_species.return_value.append(
            {"entry_number": 3, "species_name": "blastoise", "display_name": "Blastoise"}
        )
        res3 = sync_champions_catalog_on_startup(self.session)
        self.assertEqual(res3["added"], 1)
        self.assertEqual(res3["total_remote"], 3)

    def test_catalog_search_matching(self):
        repo = ChampionsCatalogRepository(self.session)
        repo.sync_species_entries([
            {"entry_number": 1, "species_name": "pikachu", "display_name": "Pikachu"},
            {"entry_number": 2, "species_name": "pidgeot", "display_name": "Pidgeot"},
            {"entry_number": 3, "species_name": "charizard", "display_name": "Charizard"},
        ])
        
        all_recs = repo.list_all()
        query = "pi"
        matches = [r.display_name for r in all_recs if query in r.species_name.lower()]
        self.assertEqual(matches, ["Pikachu", "Pidgeot"])


if __name__ == "__main__":
    unittest.main()


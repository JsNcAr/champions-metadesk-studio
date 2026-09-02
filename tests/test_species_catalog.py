"""Species catalogue: Showdown pokedex parsing, Champions legality, id resolution, sync, Catalogs."""

import shutil
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import MagicMock

from sqlmodel import Session, SQLModel, create_engine

sys.path.insert(0, str(Path(__file__).resolve().parent))
from pokemon_champions_planning_tool.domain.species import CANONICAL_ALIASES, canonical_id_from_showdown, resolve_species_key, showdown_id  # noqa: E402
from pokemon_champions_planning_tool.infrastructure.database.repositories import SpeciesRepository  # noqa: E402
from pokemon_champions_planning_tool.infrastructure.providers.showdown_species_provider import build_species_catalog, parse_formats_data_ts  # noqa: E402
from pokemon_champions_planning_tool.services.species_catalog_service import load_species_catalog, species_catalog_is_stale, sync_species_catalog  # noqa: E402
from pokemon_champions_planning_tool.ui.catalogs import Catalogs  # noqa: E402

FORMATS_TS = """export const FormatsData = {
\tbulbasaur: {
\t\tisNonstandard: "Past",
\t\ttier: "Illegal",
\t},
\tcharizard: {
\t\ttier: "RU",
\t},
\tcharizardmegay: {
\t\ttier: "UUBL",
\t},
\tcharizardgmax: {
\t\tisNonstandard: "Past",
\t\ttier: "Illegal",
\t},
\taegislashblade: {
\t},
\tbasculegion: {
\t\ttier: "OU",
\t},
\tbasculegionf: {
\t\ttier: "OU",
\t},
\tmrrime: {
\t\ttier: "PU",
\t},
\tfloettemega: {
\t\ttier: "Uber",
\t},
\turshifu: {
\t\tisNonstandard: "Past",
\t\ttier: "Illegal",
\t},
};
"""

POKEDEX = {
    "bulbasaur": {"num": 1, "name": "Bulbasaur", "types": ["Grass", "Poison"], "baseStats": {"hp": 45, "atk": 49, "def": 49, "spa": 65, "spd": 65, "spe": 45}, "abilities": {"0": "Overgrow", "H": "Chlorophyll"}, "weightkg": 6.9},
    "charizard": {"num": 6, "name": "Charizard", "types": ["Fire", "Flying"], "baseStats": {"hp": 78, "atk": 84, "def": 78, "spa": 109, "spd": 85, "spe": 100}, "abilities": {"0": "Blaze", "H": "Solar Power"}, "weightkg": 90.5, "otherFormes": ["Charizard-Mega-X", "Charizard-Mega-Y"]},
    "charizardmegay": {"num": 6, "name": "Charizard-Mega-Y", "baseSpecies": "Charizard", "forme": "Mega-Y", "types": ["Fire", "Flying"], "baseStats": {"hp": 78, "atk": 104, "def": 78, "spa": 159, "spd": 115, "spe": 100}, "abilities": {"0": "Drought"}, "weightkg": 100.5, "requiredItem": "Charizardite Y"},
    "charizardgmax": {"num": 6, "name": "Charizard-Gmax", "baseSpecies": "Charizard", "forme": "Gmax", "types": ["Fire", "Flying"], "baseStats": {"hp": 78, "atk": 84, "def": 78, "spa": 109, "spd": 85, "spe": 100}, "abilities": {"0": "Blaze"}, "weightkg": 0},
    "basculegion": {"num": 902, "name": "Basculegion", "types": ["Water", "Ghost"], "baseStats": {"hp": 120, "atk": 112, "def": 65, "spa": 80, "spd": 75, "spe": 78}, "abilities": {"0": "Swift Swim", "1": "Adaptability", "H": "Mold Breaker"}, "weightkg": 110, "gender": "M"},
    "basculegionf": {"num": 902, "name": "Basculegion-F", "baseSpecies": "Basculegion", "forme": "F", "types": ["Water", "Ghost"], "baseStats": {"hp": 120, "atk": 92, "def": 65, "spa": 100, "spd": 75, "spe": 78}, "abilities": {"0": "Swift Swim", "1": "Adaptability", "H": "Mold Breaker"}, "weightkg": 110, "gender": "F"},
    "mrrime": {"num": 866, "name": "Mr. Rime", "types": ["Ice", "Psychic"], "baseStats": {"hp": 80, "atk": 85, "def": 75, "spa": 110, "spd": 100, "spe": 70}, "abilities": {"0": "Tangled Feet"}, "weightkg": 58.2},
    "floettemega": {"num": 670, "name": "Floette-Mega", "baseSpecies": "Floette", "forme": "Mega", "types": ["Fairy"], "baseStats": {"hp": 74, "atk": 85, "def": 87, "spa": 155, "spd": 148, "spe": 102}, "abilities": {"0": "Fairy Aura"}, "weightkg": 100.8, "gender": "F", "battleOnly": "Floette-Eternal", "requiredItem": "Floettite"},
    "urshifu": {"num": 892, "name": "Urshifu", "types": ["Fighting", "Dark"], "baseStats": {"hp": 100, "atk": 130, "def": 100, "spa": 63, "spd": 60, "spe": 97}, "abilities": {"0": "Unseen Fist"}, "weightkg": 105},
    "missingno": {"num": 0, "name": "MissingNo.", "types": ["Bird", "Normal"], "baseStats": {"hp": 33, "atk": 136, "def": 0, "spa": 6, "spd": 6, "spe": 29}, "abilities": {"0": ""}, "weightkg": 1590.8},
    "syclant": {"num": -1, "name": "Syclant", "types": ["Ice", "Bug"], "baseStats": {"hp": 70, "atk": 116, "def": 70, "spa": 114, "spd": 64, "spe": 121}, "abilities": {"0": "Compound Eyes"}, "weightkg": 52, "isNonstandard": "CAP"},
}


def _payload():
    return build_species_catalog(POKEDEX, parse_formats_data_ts(FORMATS_TS))


class TestParsing(unittest.TestCase):
    def test_legal_ids_from_formats_data(self):
        legal = parse_formats_data_ts(FORMATS_TS)
        self.assertEqual(legal, frozenset({"charizard", "charizardmegay", "aegislashblade", "basculegion", "basculegionf", "mrrime", "floettemega"}))

    def test_catalog_rows(self):
        by = {s.canonical_id: s for s in _payload().species}
        self.assertNotIn("syclant", by, "CAP dropped")
        self.assertNotIn("missingno", by, "num <= 0 dropped")
        mega = by["charizard-mega-y"]
        self.assertEqual((mega.name, mega.showdown_id, mega.base_species_id, mega.forme, mega.is_mega, mega.is_legal, mega.required_item, mega.weightkg), ("Charizard-Mega-Y", "charizardmegay", "charizard", "Mega-Y", True, True, "Charizardite Y", 100.5))
        self.assertEqual(mega.abilities, ("Drought",))
        self.assertEqual(by["basculegion"].abilities, ("Swift Swim", "Adaptability", "Mold Breaker"))
        self.assertEqual((by["basculegion"].gender, by["basculegion-f"].gender, by["basculegion-f"].base_stats["atk"]), ("M", "F", 92))
        self.assertFalse(by["urshifu"].is_legal)
        self.assertFalse(by["charizard-gmax"].is_legal)
        self.assertEqual(by["mr-rime"].name, "Mr. Rime")
        floette = by["floette-mega"]
        self.assertEqual((floette.battle_only, floette.gender, floette.is_mega), ("Floette-Eternal", "F", True))
        self.assertEqual(by["charizard"].base_stats["spa"], 109)


class TestIdRules(unittest.TestCase):
    def test_canonical_from_showdown_names(self):
        self.assertEqual(canonical_id_from_showdown("Charizard-Mega-Y"), "charizard-mega-y")
        self.assertEqual(canonical_id_from_showdown("Mr. Rime"), "mr-rime")
        self.assertEqual(canonical_id_from_showdown("Basculegion-F"), "basculegion-f")
        self.assertEqual(canonical_id_from_showdown("Tauros-Paldea-Combat"), "tauros-paldea-combat")
        self.assertEqual(canonical_id_from_showdown("Type: Null"), "type-null")
        self.assertEqual(canonical_id_from_showdown("Farfetch’d"), "farfetchd")
        self.assertEqual(showdown_id("Charizard-Mega-Y"), "charizardmegay")

    def test_resolve_species_key(self):
        keys = {"charizard", "charizard-mega-y", "rotom-wash", "basculegion", "basculegion-f", "urshifu", "urshifu-rapid-strike", "maushold", "maushold-four", "tauros-paldea-combat", "aegislash", "meowstic-f"}
        self.assertEqual(resolve_species_key("charizard-mega-y", keys), "charizard-mega-y", "megas are their own rows")
        self.assertEqual(resolve_species_key("Rotom-Wash", keys), "rotom-wash")
        self.assertEqual(resolve_species_key("basculegion", keys), "basculegion", "the default form never falls through to the F row")
        self.assertEqual(resolve_species_key("basculegion-female", keys), "basculegion-f")
        self.assertEqual(resolve_species_key("basculegion-male", keys), "basculegion")
        self.assertEqual(resolve_species_key("urshifu-single-strike", keys), "urshifu")
        self.assertEqual(resolve_species_key("maushold-family-of-four", keys), "maushold-four")
        self.assertEqual(resolve_species_key("tauros-paldea-combat-breed", keys), "tauros-paldea-combat")
        self.assertEqual(resolve_species_key("aegislash-shield", keys), "aegislash")
        self.assertEqual(resolve_species_key("meowstic-female", keys), "meowstic-f")
        self.assertEqual(resolve_species_key("rotomwash", keys), "rotom-wash", "alnum keys resolve")
        self.assertEqual(resolve_species_key("charizard-mega-z", keys), "charizard", "unknown suffixes drop back")
        self.assertIsNone(resolve_species_key("floette-eternal", keys))
        self.assertIsNone(resolve_species_key(None, keys))
        self.assertTrue(all("-" in k for k in CANONICAL_ALIASES))


class TestSyncAndCatalogs(unittest.TestCase):
    def setUp(self):
        self.dir = tempfile.mkdtemp()
        self.engine = create_engine(f"sqlite:///{Path(self.dir) / 'species.db'}", connect_args={"check_same_thread": False})
        from pokemon_champions_planning_tool.infrastructure.database import models  # noqa: F401

        SQLModel.metadata.create_all(self.engine)

    def tearDown(self):
        self.engine.dispose()
        shutil.rmtree(self.dir)

    def _session(self):
        return Session(self.engine)

    def test_sync_cache_and_load(self):
        provider = MagicMock()
        provider.fetch_species_catalog.return_value = _payload()
        with self._session() as s:
            self.assertTrue(species_catalog_is_stale(s))
            res = sync_species_catalog(s, provider=provider)
            self.assertEqual((res["status"], res["species"], res["legal"]), ("synced", 9, 6))
            self.assertEqual(sync_species_catalog(s, provider=provider)["status"], "cached")
            self.assertEqual(provider.fetch_species_catalog.call_count, 1)
            loaded = load_species_catalog(s)
            self.assertEqual(loaded["charizard-mega-y"].weightkg, 100.5)
            self.assertEqual(SpeciesRepository(s).get("basculegionf").name, "Basculegion-F")
            meta = SpeciesRepository(s).get_meta()
            meta.schema_version = 0
            s.add(meta); s.commit()
            self.assertTrue(species_catalog_is_stale(s), "an older stored shape forces a re-sync")
        catalogs = Catalogs.load(self._session)
        self.assertTrue(catalogs.has_species)
        self.assertEqual(catalogs.species_for("charizard-mega-y").abilities, ("Drought",))
        self.assertEqual(catalogs.species_for("basculegion-female").name, "Basculegion-F")
        self.assertEqual(catalogs.species_for("basculegion").name, "Basculegion")
        self.assertIsNone(catalogs.species_for("garchomp"))
        self.assertEqual([s.name for s in catalogs.search_species("char")], ["Charizard", "Charizard-Mega-Y"], "legal only by default")
        self.assertEqual([s.name for s in catalogs.search_species("urs", legal_only=False)], ["Urshifu"])
        self.assertEqual([s.name for s in catalogs.search_species("rime")], ["Mr. Rime"])
        self.assertEqual(catalogs.search_species("c"), [])

    def test_offline_keeps_local_data(self):
        from pokemon_champions_planning_tool.infrastructure.providers.showdown_species_provider import ShowdownSpeciesNetworkError

        provider = MagicMock()
        provider.fetch_species_catalog.side_effect = ShowdownSpeciesNetworkError("down")
        with self._session() as s:
            self.assertEqual(sync_species_catalog(s, provider=provider)["status"], "offline")
            self.assertFalse(Catalogs.load(lambda: Session(self.engine)).has_species)


if __name__ == "__main__":
    unittest.main()

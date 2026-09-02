"""Guards that keep placeholder Pokémon from ever passing as real data again."""

import re
import shutil
import sqlite3
import tempfile
import unittest
from pathlib import Path
from unittest.mock import MagicMock, patch

import requests
from sqlmodel import Session, SQLModel, create_engine

from _ui_stubs import StubPage, serialise
from pokemon_champions_planning_tool.domain.entities.box_entry import BoxEntry
from pokemon_champions_planning_tool.domain.entities.pokemon import Pokemon
from pokemon_champions_planning_tool.domain.entities.pokemon_stats import PokemonStats
from pokemon_champions_planning_tool.infrastructure.database import database
from pokemon_champions_planning_tool.infrastructure.database.repositories import BoxRepository, PlaceholderPokemonError, PokemonRepository
from pokemon_champions_planning_tool.infrastructure.pokeapi import pokeapi_retrieval
from pokemon_champions_planning_tool.services import pokemon_import_service as imp

SRC = Path(__file__).resolve().parents[1] / "src" / "pokemon_champions_planning_tool"
# Zero stat blocks that are not Pokémon: the team summary's empty totals.
ZERO_STATS_ALLOWLIST = {"domain/entities/pokemon.py", "ui/views/team/summary.py"}


def _real(cid="kingambit"):
    return Pokemon(canonical_id=cid, display_name=cid.title(), species_name=cid, types=["dark", "steel"], stats=PokemonStats(hp=100, attack=135, defense=120, sp_atk=60, sp_def=85, speed=50))


class TestPlaceholderLint(unittest.TestCase):
    def test_only_the_placeholder_constructor_builds_zero_stat_pokemon(self):
        offenders = []
        for path in SRC.rglob("*.py"):
            rel = path.relative_to(SRC).as_posix()
            if rel in ZERO_STATS_ALLOWLIST:
                continue
            for lineno, line in enumerate(path.read_text(encoding="utf-8").splitlines(), 1):
                if re.search(r"PokemonStats\(\s*hp\s*=\s*0\b", line):
                    offenders.append(f"{rel}:{lineno}")
        self.assertEqual(offenders, [], "build placeholders with Pokemon.placeholder(), never by hand")

    def test_placeholder_is_explicit_and_round_trips(self):
        p = Pokemon.placeholder("kingambit", "Kingambit")
        self.assertTrue(p.is_placeholder and p.is_stub)
        self.assertFalse(_real().is_stub)
        engine = create_engine("sqlite:///:memory:")
        SQLModel.metadata.create_all(engine)
        with Session(engine) as s:
            PokemonRepository(s).upsert(p)
            self.assertTrue(PokemonRepository(s).get("kingambit").to_domain().is_placeholder)


class TestWriteGuards(unittest.TestCase):
    def setUp(self):
        self.engine = create_engine("sqlite:///:memory:")
        SQLModel.metadata.create_all(self.engine)
        self.session = Session(self.engine)

    def tearDown(self):
        self.session.close()

    def test_placeholder_never_overwrites_real_data(self):
        repo = PokemonRepository(self.session)
        repo.upsert(_real())
        repo.upsert(Pokemon.placeholder("kingambit", "Kingambit"))
        self.assertEqual(repo.get("kingambit").to_domain().types, ["dark", "steel"], "real record kept")
        repo.upsert(Pokemon.placeholder("garchomp", "Garchomp"))
        repo.upsert(_real("garchomp"))
        self.assertFalse(repo.get("garchomp").to_domain().is_stub, "real data replaces a placeholder")

    def test_box_refuses_placeholders_unless_intentional(self):
        repo = BoxRepository(self.session)
        with self.assertRaises(PlaceholderPokemonError):
            repo.upsert_box_entry(BoxEntry(pokemon=Pokemon.placeholder("kingambit", "Kingambit")))
        with self.assertRaises(PlaceholderPokemonError):
            repo.create_planned_entry(BoxEntry(pokemon=Pokemon.placeholder("kingambit", "Kingambit"), is_planned=True))
        repo.upsert_box_entry(BoxEntry(pokemon=Pokemon.placeholder("kingambit", "Kingambit")), allow_placeholder=True)
        self.assertEqual(len(repo.list_entries(include_planned=True)), 1)


class TestMigrationFlagsOldPlaceholders(unittest.TestCase):
    def test_existing_zero_records_are_flagged(self):
        d = tempfile.mkdtemp()
        path = str(Path(d) / "old.db")
        try:
            engine = create_engine(f"sqlite:///{path}")
            SQLModel.metadata.create_all(engine)
            engine.dispose()
            conn = sqlite3.connect(path)
            conn.execute("ALTER TABLE pokemon_records DROP COLUMN is_placeholder")
            conn.execute("INSERT INTO pokemon_records (canonical_id, display_name, form_name, types, hp, attack, defense, special_attack, special_defense, speed, abilities, moves, available_forms, created_at, updated_at)"
                         " VALUES ('kingambit', 'Kingambit', 'base', '[]', 0, 0, 0, 0, 0, 0, '[]', '[]', '[]', '2026-01-01', '2026-01-01'),"
                         " ('garchomp', 'Garchomp', 'Base', '[\"dragon\"]', 108, 130, 95, 80, 85, 102, '[]', '[]', '[]', '2026-01-01', '2026-01-01')")
            conn.commit(); conn.close()
            database.get_engine.cache_clear(); database._DB_INITIALIZED.discard(path)
            database.initialize_database(path)
            conn = sqlite3.connect(path)
            self.assertEqual(dict(conn.execute("SELECT canonical_id, is_placeholder FROM pokemon_records").fetchall()), {"kingambit": 1, "garchomp": 0})
            conn.close()
        finally:
            database.get_engine.cache_clear(); database._DB_INITIALIZED.discard(path)
            shutil.rmtree(d)


class TestUnavailableIsNotNotFound(unittest.TestCase):
    def _resp(self, status):
        resp = MagicMock(status_code=status)
        resp.raise_for_status.side_effect = requests.exceptions.HTTPError(f"{status}")
        return resp

    def test_404_is_none_and_503_raises(self):
        with patch.object(pokeapi_retrieval.requests, "get", return_value=self._resp(404)):
            self.assertIsNone(pokeapi_retrieval.get_official_stats("Nope"))
        with patch.object(pokeapi_retrieval.requests, "get", return_value=self._resp(503)):
            with self.assertRaises(pokeapi_retrieval.PokeApiUnavailable):
                pokeapi_retrieval.get_official_stats("Kingambit")
        with patch.object(pokeapi_retrieval.requests, "get", side_effect=requests.exceptions.ConnectionError("down")):
            with self.assertRaises(pokeapi_retrieval.PokeApiUnavailable):
                pokeapi_retrieval.get_official_stats("Kingambit")

    def test_add_by_name_reports_unavailability_instead_of_not_found(self):
        engine = create_engine("sqlite:///:memory:")
        SQLModel.metadata.create_all(engine)
        import contextlib

        @contextlib.contextmanager
        def sf():
            with Session(engine) as s:
                yield s

        with patch.object(imp, "get_session", sf), patch.object(imp, "get_official_stats", side_effect=pokeapi_retrieval.PokeApiUnavailable("PokéAPI is unreachable: down")):
            with self.assertRaises(pokeapi_retrieval.PokeApiUnavailable) as ctx:
                imp.add_pokemon_to_box("Kingambit")
            self.assertIn("unreachable", str(ctx.exception))


class TestVisibility(unittest.TestCase):
    def test_box_header_says_how_many_are_hidden(self):
        from pokemon_champions_planning_tool.ui.catalogs import Catalogs
        from pokemon_champions_planning_tool.ui.context import AppContext
        from pokemon_champions_planning_tool.ui.views.box.store import BoxStore
        from pokemon_champions_planning_tool.ui.views.box.view import BoxView

        engine = create_engine("sqlite:///:memory:")
        SQLModel.metadata.create_all(engine)
        with Session(engine) as s:
            BoxRepository(s).upsert_box_entry(BoxEntry(pokemon=_real("kingambit")))
            BoxRepository(s).upsert_box_entry(BoxEntry(pokemon=_real("garchomp")))
            s.commit()
        sf = lambda: Session(engine)  # noqa: E731
        ctx = AppContext(StubPage())
        view = BoxView(ctx, BoxStore(Catalogs(), sf))
        view.ensure_loaded()
        self.assertFalse(view._hidden_button.visible)
        view.toolbar._set(text="garch")
        self.assertTrue(view._hidden_button.visible)
        self.assertEqual(view._hidden_button.content, "1 hidden by filters")
        serialise(view)
        view.toolbar.clear()
        self.assertFalse(view._hidden_button.visible)

    def test_settings_health_row_counts_placeholders(self):
        from pokemon_champions_planning_tool.ui.context import AppContext
        from pokemon_champions_planning_tool.ui.views.settings.store import SettingsStore
        from pokemon_champions_planning_tool.ui.views.settings.view import SettingsView

        engine = create_engine("sqlite:///:memory:")
        SQLModel.metadata.create_all(engine)
        with Session(engine) as s:
            BoxRepository(s).upsert_box_entry(BoxEntry(pokemon=Pokemon.placeholder("kingambit", "Kingambit")), allow_placeholder=True)
            s.commit()
        sf = lambda: Session(engine)  # noqa: E731
        view = SettingsView(AppContext(StubPage()), SettingsStore(sf))
        status = view.store.status()
        self.assertEqual((status.placeholder_in_box, status.placeholder_records), (1, 1))
        view.apply_status(status)
        self.assertIn("1 Pokémon in the box without PokéAPI data", view.row_health._status.value)
        self.assertFalse(view.row_health.button.disabled)
        serialise(view)


if __name__ == "__main__":
    unittest.main()

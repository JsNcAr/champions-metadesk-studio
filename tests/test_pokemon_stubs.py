"""Placeholder Pokémon records: never reused, repaired, and visible in the Box."""

import contextlib
import shutil
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from sqlmodel import Session, SQLModel, create_engine

from _ui_stubs import StubPage, serialise
from pokemon_champions_planning_tool.domain.entities.box_entry import BoxEntry
from pokemon_champions_planning_tool.domain.entities.pokemon import Pokemon
from pokemon_champions_planning_tool.domain.entities.pokemon_stats import PokemonStats
from pokemon_champions_planning_tool.infrastructure.database.models import ChampionsSpeciesRecord
from pokemon_champions_planning_tool.infrastructure.database.repositories import BoxRepository, PokemonRepository
from pokemon_champions_planning_tool.services import pokemon_import_service as imp
from pokemon_champions_planning_tool.services import showdown_service
from pokemon_champions_planning_tool.ui.catalogs import Catalogs
from pokemon_champions_planning_tool.ui.context import AppContext
from pokemon_champions_planning_tool.ui.views.box.filters import BoxFilters, apply_filters
from pokemon_champions_planning_tool.ui.views.box.store import BoxStore
from pokemon_champions_planning_tool.ui.views.box.view import BoxView

ZERO = PokemonStats(hp=0, attack=0, defense=0, sp_atk=0, sp_def=0, speed=0)
REAL = PokemonStats(hp=100, attack=135, defense=120, sp_atk=60, sp_def=85, speed=50)


def _stub(cid="kingambit"):
    return Pokemon(canonical_id=cid, display_name=cid.title(), species_name=cid, form_name="base", types=[], stats=ZERO)


def _real(cid="kingambit"):
    return Pokemon(canonical_id=cid, display_name=cid.title(), species_name=cid, form_name="base", types=["dark", "steel"], stats=REAL, dex_number=983)


class _Db:
    def __init__(self):
        self.dir = tempfile.mkdtemp()
        self.engine = create_engine(f"sqlite:///{Path(self.dir) / 'stub.db'}", connect_args={"check_same_thread": False})
        SQLModel.metadata.create_all(self.engine)

    @contextlib.contextmanager
    def session(self):
        with Session(self.engine) as s:
            yield s

    def close(self):
        self.engine.dispose()
        shutil.rmtree(self.dir)


class TestStubs(unittest.TestCase):
    def setUp(self):
        self.db = _Db()
        patch.object(imp, "get_session", self.db.session).start()
        self.addCleanup(patch.stopall)

    def tearDown(self):
        self.db.close()

    def test_is_stub(self):
        self.assertTrue(_stub().is_stub)
        self.assertFalse(_real().is_stub)

    def test_add_by_name_refetches_a_placeholder_record(self):
        with self.db.session() as s:
            PokemonRepository(s).upsert(_stub())
        with patch.object(imp, "get_official_stats", return_value=_real()) as fetch:
            entry = imp.add_pokemon_to_box("Kingambit")
        fetch.assert_called_once()
        self.assertEqual(entry.pokemon.types, ["dark", "steel"])
        self.assertEqual(entry.pokemon.total, 550)
        # a real record is reused without a fetch
        with patch.object(imp, "get_official_stats", return_value=None) as fetch:
            imp.add_pokemon_to_box("Kingambit")
        fetch.assert_not_called()

    def test_add_by_name_keeps_the_placeholder_when_offline(self):
        with self.db.session() as s:
            PokemonRepository(s).upsert(_stub())
        with patch.object(imp, "get_official_stats", return_value=None):
            entry = imp.add_pokemon_to_box("Kingambit")
        self.assertTrue(entry.pokemon.is_stub, "offline: stored, marked incomplete, repaired later")

    def test_repair_pass_refetches_stubs_referenced_by_the_box(self):
        with self.db.session() as s:
            repo = BoxRepository(s)
            repo.upsert_box_entry(BoxEntry(pokemon=_stub("kingambit")), allow_placeholder=True)
            repo.upsert_box_entry(BoxEntry(pokemon=_real("garchomp")))
            s.commit()
        with patch.object(imp, "get_official_stats", side_effect=lambda name: _real() if "kingambit" in name.lower() else None) as fetch, self.db.session() as s:
            res = imp.refresh_stub_pokemon(s)
        self.assertEqual(res, {"stubs": 1, "repaired": 1})
        self.assertEqual(fetch.call_count, 1, "only the placeholder touches the network")
        with self.db.session() as s:
            entries = {e.pokemon.canonical_id: e for e in BoxRepository(s).list_entries(include_planned=True)}
        self.assertFalse(entries["kingambit"].pokemon.is_stub)
        with self.db.session() as s:
            self.assertEqual(imp.refresh_stub_pokemon(s), {"stubs": 0, "repaired": 0})

    def test_import_fetches_real_data_for_missing_species(self):
        paste = "Kingambit @ Leftovers\nAbility: Defiant\n- Kowtow Cleave\n"
        with self.db.session() as s:
            s.add(ChampionsSpeciesRecord(entry_number=1, species_name="kingambit", display_name="Kingambit")); s.commit()
            parsed = showdown_service.parse_showdown_text(paste)
            with patch.object(showdown_service, "_fetch_official", return_value=_real()):
                showdown_service.commit_team_import(s, parsed, use_planned=False, team_name="Dark")
            entries = BoxRepository(s).list_entries(include_planned=True)
        self.assertEqual([(e.pokemon.canonical_id, e.pokemon.is_stub) for e in entries], [("kingambit", False)])
        # offline: a placeholder is stored and marked as such
        with self.db.session() as s:
            BoxRepository(s).delete_by_canonical_id("kingambit"); s.commit()
            parsed = showdown_service.parse_showdown_text(paste.replace("Kingambit", "Garchomp"))
            with patch.object(showdown_service, "_fetch_official", return_value=None):
                showdown_service.commit_team_import(s, parsed, use_planned=True, team_name="Sand")
            entries = BoxRepository(s).list_entries(include_planned=True)
        self.assertTrue(entries[0].pokemon.is_stub)

    def test_box_shows_placeholders_with_a_mark_and_refresh(self):
        with self.db.session() as s:
            repo = BoxRepository(s)
            stub_id = repo.upsert_box_entry(BoxEntry(pokemon=_stub()), allow_placeholder=True).box_entry_id
            repo.upsert_box_entry(BoxEntry(pokemon=_real("garchomp")))
            s.commit()
        with self.db.session() as s:
            entries = BoxRepository(s).list_entries(include_planned=True)
        self.assertEqual({e.pokemon.canonical_id for e in apply_filters(entries, BoxFilters())}, {"kingambit", "garchomp"}, "a placeholder is not hidden by the BST range")
        self.assertEqual({e.pokemon.canonical_id for e in apply_filters(entries, BoxFilters(tags=frozenset({"x"})))}, set())
        page = StubPage()
        ctx = AppContext(page, catalogs=Catalogs.load(self.db.session))
        ctx.run_in_background = lambda work, on_done=None, on_error=None, **kw: on_done(work()) if on_done else work()
        view = BoxView(ctx, BoxStore(ctx.catalogs, self.db.session))
        view.ensure_loaded()
        card = view._cards[stub_id]
        self.assertTrue(card._planned.visible)
        self.assertEqual(card._planned._label.value, "Incomplete data")
        view.store.select(stub_id)
        self.assertTrue(view.detail._refresh_button.visible)
        self.assertTrue(view.detail._refresh_banner.visible)
        serialise(view)
        with patch.object(imp, "get_official_stats", return_value=_real()):
            view._refresh_entry(stub_id)
        self.assertFalse(view.store.entry(stub_id).pokemon.is_stub)
        self.assertFalse(view.detail._refresh_button.visible)
        self.assertFalse(view._cards[stub_id]._planned.visible)


if __name__ == "__main__":
    unittest.main()

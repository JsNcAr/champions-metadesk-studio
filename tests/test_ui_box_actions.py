"""Box: bulk / detail add-to-team, optional table columns, filtered CSV export."""

import contextlib
import shutil
import tempfile
import unittest
from pathlib import Path
from unittest.mock import AsyncMock, patch

from sqlmodel import Session, SQLModel, create_engine

import flet as ft

from _ui_stubs import StubPage, serialise
from pokemon_champions_planning_tool.domain.entities.box_entry import BoxEntry
from pokemon_champions_planning_tool.domain.entities.pokemon import Pokemon
from pokemon_champions_planning_tool.domain.entities.pokemon_ability import PokemonAbility
from pokemon_champions_planning_tool.domain.entities.pokemon_stats import PokemonStats
from pokemon_champions_planning_tool.domain.entities.team import Team
from pokemon_champions_planning_tool.infrastructure.database.repositories import BoxRepository, TeamRepository
from pokemon_champions_planning_tool.ui import events
from pokemon_champions_planning_tool.ui.catalogs import Catalogs
from pokemon_champions_planning_tool.ui.context import AppContext
from pokemon_champions_planning_tool.ui.views.box import BoxStore
from pokemon_champions_planning_tool.ui.views.box.view import BoxView


class _Db:
    def __init__(self):
        self.dir = tempfile.mkdtemp()
        self.engine = create_engine(f"sqlite:///{Path(self.dir) / 'box.db'}", connect_args={"check_same_thread": False})
        SQLModel.metadata.create_all(self.engine)

    @contextlib.contextmanager
    def session(self):
        with Session(self.engine) as s:
            yield s

    def close(self):
        self.engine.dispose()
        shutil.rmtree(self.dir)


def _mon(cid, name, types, dex):
    return Pokemon(canonical_id=cid, display_name=name, species_name=cid, types=types, dex_number=dex,
                   abilities=[PokemonAbility(name="intimidate", is_hidden=False)],
                   stats=PokemonStats(hp=80, attack=80, defense=80, sp_atk=80, sp_def=80, speed=80))


class TestBoxActions(unittest.TestCase):
    def setUp(self):
        self.db = _Db()
        with self.db.session() as s:
            repo = BoxRepository(s)
            self.ids = [repo.upsert_box_entry(BoxEntry(pokemon=_mon(c, c.title(), t, d), notes=f"note {c}")).box_entry_id
                        for c, t, d in (("charizard", ["fire", "flying"], 6), ("lucario", ["fighting", "steel"], 448), ("gardevoir", ["psychic", "fairy"], 282))]
            self.team_id = TeamRepository(s).create(Team(name="Sun")).team_id
            s.commit()
        self.page = StubPage()
        self.ctx = AppContext(self.page, catalogs=Catalogs.load(self.db.session))
        self.store = BoxStore(self.ctx.catalogs, self.db.session)
        self.view = BoxView(self.ctx, self.store)
        self.view.ensure_loaded()

    def tearDown(self):
        self.db.close()

    def test_add_to_team_fills_free_slots_and_reports_leftovers(self):
        res = self.store.add_to_team(self.team_id, self.ids[:2])
        self.assertEqual((res.added, res.already_on_team, res.no_room), (2, 0, 0))
        res = self.store.add_to_team(self.team_id, self.ids)
        self.assertEqual((res.added, res.already_on_team, res.no_room), (1, 2, 0))
        with self.db.session() as s:
            members = TeamRepository(s).get_members(self.team_id)
            self.assertEqual(sorted(m.slot_position for m in members), [1, 2, 3])
        # a full team leaves the rest out
        with self.db.session() as s:
            repo = BoxRepository(s)
            extra = [repo.upsert_box_entry(BoxEntry(pokemon=_mon(f"mon{i}", f"Mon{i}", ["normal"], 100 + i))).box_entry_id for i in range(4)]
        res = self.store.add_to_team(self.team_id, extra)
        self.assertEqual((res.added, res.no_room), (3, 1))
        self.assertEqual([t.filled for t in self.store.list_teams()], [6])

    def test_bulk_bar_and_detail_menus_offer_teams_and_new_team(self):
        self.store.toggle_multi(self.ids[0], True)
        self.store.toggle_multi(self.ids[1], True)
        labels = [i.content.value for i in self.view._bulk_team_menu.items]
        self.assertEqual(labels, ["Sun · 0/6", "New team…"])
        emitted = []
        self.ctx.bus.on(events.TEAMS_CHANGED, emitted.append)
        self.page.run_task(self.view._add_flow, [self.ids[0], self.ids[1]], self.team_id)
        self.assertEqual(emitted, [self.team_id])
        self.assertEqual(self.store.multi, set())
        self.store.select(self.ids[2])
        self.assertEqual([i.content.value for i in self.view.detail._add_to_team.items], ["Sun · 2/6", "New team…"])
        # "New team…" prompts for a name, then creates and fills it
        self.ctx.prompt_text = AsyncMock(return_value="Rain")
        self.page.run_task(self.view._add_flow, [self.ids[2]], None)
        self.assertEqual({t.name: t.filled for t in self.store.list_teams()}, {"Sun": 2, "Rain": 1})
        serialise(self.view)

    def test_table_columns_are_optional_and_remembered(self):
        self.view._set_view_mode("table")
        base = len(self.view.table.table.columns)
        self.view._set_columns(["dex", "abilities", "notes"])
        self.assertEqual(len(self.view.table.table.columns), base + 3)
        self.assertEqual(self.ctx.prefs.get("box.columns"), ["abilities", "dex", "notes"], "kept in catalogue order")
        row = self.view.table.table.rows[0]
        self.assertEqual(len(row.cells), base + 3)
        self.assertEqual(row.cells[-2].content.value, "#006")
        self.assertTrue(self.view.toolbar._column_items["dex"].checked)
        serialise(self.view)

    def test_export_uses_visible_or_selected_entries(self):
        with patch("pokemon_champions_planning_tool.ui.views.box.store.export_box_entries_to_csv") as export:
            self.view._export()
            self.assertEqual(len(export.call_args.args[0]), 3)
            self.view.toolbar._set(text="luca")
            self.view._export()
            self.assertEqual([e.pokemon.display_name for e in export.call_args.args[0]], ["Lucario"])
            self.view.toolbar.clear()
            self.store.toggle_multi(self.ids[2], True)
            self.view._export()
            self.assertEqual([e.pokemon.display_name for e in export.call_args.args[0]], ["Gardevoir"])



    def test_enter_on_a_partial_name_adds_the_first_suggestion(self):
        from pokemon_champions_planning_tool.infrastructure.database.models import ChampionsSpeciesRecord
        from pokemon_champions_planning_tool.ui.catalogs import Catalogs

        with self.db.session() as s:
            for i, (sid, name) in enumerate((("kingambit", "Kingambit"), ("kingdra", "Kingdra"), ("charizard", "Charizard")), start=1):
                s.add(ChampionsSpeciesRecord(entry_number=i, species_name=sid, display_name=name))
            s.commit()
        self.ctx.catalogs = Catalogs.load(self.db.session)
        self.assertEqual(self.view._resolve_name("kinga"), "Kingambit", "first suggestion for a partial name")
        self.assertEqual(self.view._resolve_name("kingdra"), "Kingdra", "an exact match is kept even if it is not the first suggestion")
        self.assertEqual(self.view._resolve_name("KINGDRA"), "Kingdra")
        self.assertEqual(self.view._resolve_name("mew"), "mew", "no suggestion: passed through for PokéAPI")
        self.assertEqual(self.view._resolve_name("  "), "")
        self.view._suggest("king")
        chips = self.view._suggestions.controls
        self.assertEqual([c.label.value for c in chips], ["Kingambit", "Kingdra"])
        self.assertTrue(all(isinstance(c.leading, ft.Image) and "kingambit" in c.leading.src or "kingdra" in c.leading.src for c in chips), "sprites from the species id")
        self.assertIsNotNone(chips[0].border_side, "first chip is outlined: Enter adds it")
        self.assertIsNone(chips[1].border_side)
        serialise(self.view)


if __name__ == "__main__":
    unittest.main()

"""Box view: constructed against a temp DB and a stub page, serialised through Flet."""

import contextlib
import shutil
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

import flet as ft
from sqlmodel import Session, SQLModel, create_engine

from _ui_stubs import StubPage, serialise
from pokemon_champions_planning_tool.domain.entities.box_entry import BoxEntry
from pokemon_champions_planning_tool.domain.entities.pokemon import Pokemon
from pokemon_champions_planning_tool.domain.entities.pokemon_ability import PokemonAbility
from pokemon_champions_planning_tool.domain.entities.pokemon_stats import PokemonStats
from pokemon_champions_planning_tool.domain.entities.team import Team
from pokemon_champions_planning_tool.domain.entities.team_member import TeamMember
from pokemon_champions_planning_tool.infrastructure.database.models import ChampionsSpeciesRecord, MegaCheckedSpeciesRecord
from pokemon_champions_planning_tool.infrastructure.database.repositories import BoxRepository, TeamRepository
from pokemon_champions_planning_tool.ui import events
from pokemon_champions_planning_tool.ui.catalogs import Catalogs
from pokemon_champions_planning_tool.ui.context import AppContext
from pokemon_champions_planning_tool.ui.views.box import BoxStore
from pokemon_champions_planning_tool.ui.views.box.view import BoxView


def _mon(cid, name, types, **stats) -> Pokemon:
    base = dict(hp=80, attack=80, defense=80, sp_atk=80, sp_def=80, speed=80)
    base.update(stats)
    return Pokemon(canonical_id=cid, display_name=name, species_name=cid, types=list(types), dex_number=6,
                   stats=PokemonStats(**base), abilities=[PokemonAbility(name="blaze"), PokemonAbility(name="solar-power", is_hidden=True)])


class _TempDb:
    def __init__(self):
        self.dir = tempfile.mkdtemp()
        self.engine = create_engine(f"sqlite:///{Path(self.dir) / 'boxview.db'}", connect_args={"check_same_thread": False})
        SQLModel.metadata.create_all(self.engine)

    @contextlib.contextmanager
    def session(self):
        with Session(self.engine) as s:
            yield s

    def close(self):
        self.engine.dispose()
        shutil.rmtree(self.dir)


class _BoxViewCase(unittest.TestCase):
    def setUp(self):
        self.db = _TempDb()
        with self.db.session() as s:
            repo = BoxRepository(s)
            self.charizard = repo.upsert_box_entry(BoxEntry(pokemon=_mon("charizard", "Charizard", ["fire", "flying"], speed=100), tags=["lead"])).box_entry_id
            self.rillaboom = repo.upsert_box_entry(BoxEntry(pokemon=_mon("rillaboom", "Rillaboom", ["grass"], attack=125))).box_entry_id
            s.add(ChampionsSpeciesRecord(entry_number=1, species_name="charizard", display_name="Charizard"))
            for name in ("charizard", "rillaboom"):
                s.add(MegaCheckedSpeciesRecord(species_name=name))  # no network lookups in tests
            s.commit()
            team = TeamRepository(s).create(Team(name="Sun"))
            TeamRepository(s).upsert_member(team.team_id, TeamMember(box_entry_id=self.charizard, slot_position=1))
        self.page = StubPage()
        self.ctx = AppContext(self.page, catalogs=Catalogs.load(self.db.session))
        self.view = BoxView(self.ctx, BoxStore(self.ctx.catalogs, self.db.session))

    def tearDown(self):
        self.db.close()


class TestBoxView(_BoxViewCase):
    def test_loads_cards_and_serialises(self):
        self.view.ensure_loaded()
        self.assertEqual(len(self.view.grid.controls), 2)
        self.assertEqual(self.view.header._count.content.value, "2")
        self.assertGreater(serialise(self.view), 60)
        self.assertFalse(self.view.detail.visible)

    def test_select_opens_detail_with_forms_defensive_and_teams(self):
        self.view.ensure_loaded()
        self.view._select(self.charizard)
        self.assertTrue(self.view.detail.visible)
        self.assertEqual(self.view.detail._title.value, "Charizard")
        self.assertIn("Sun (slot 1)", self.view.detail._teams.value)
        labels = [r.controls[0].value for r in self.view.detail._defensive.controls if isinstance(r, ft.Row)]
        self.assertEqual(labels[:2], ["4×", "2×"])
        self.assertEqual(len(self.view.detail._abilities.controls), 2)
        serialise(self.view)
        self.view.handle_key(type("K", (), {"key": "Escape", "ctrl": False})())
        self.assertFalse(self.view.detail.visible)

    def test_filter_and_table_mode(self):
        self.view.ensure_loaded()
        self.view.toolbar._set(text="rilla")
        self.assertEqual(len(self.view.grid.controls), 1)
        self.assertEqual(self.view.header._count.content.value, "1 of 2")
        self.view.toolbar.clear()
        self.view._set_view_mode("table")
        self.assertTrue(self.view.table.visible)
        self.assertEqual(len(self.view.table.table.rows), 2)
        serialise(self.view)
        self.view._on_table_sort("attack", ascending=False)
        self.assertEqual(self.view.table.table.rows[0].cells[1].content.controls[1].controls[0].value, "Rillaboom")

    def test_favourite_from_card_updates_store_and_emits(self):
        self.view.ensure_loaded()
        emitted = []
        self.ctx.bus.on(events.BOX_CHANGED, emitted.append)
        card = self.view._cards[self.rillaboom]
        card._toggle_favorite()
        self.assertTrue(self.view.store.entry(self.rillaboom).is_favorite)
        self.assertEqual(card._star.icon, ft.Icons.STAR)
        self.assertEqual(len(emitted), 1)

    def test_add_flow_selects_new_entry_and_toasts(self):
        self.view.ensure_loaded()
        new_entry = BoxEntry(pokemon=_mon("amoonguss", "Amoonguss", ["grass", "poison"]))
        with self.db.session() as s:
            saved_id = BoxRepository(s).upsert_box_entry(new_entry).box_entry_id
        new_entry.box_entry_id = saved_id
        with patch.object(self.view.store, "add_by_name", return_value=new_entry):
            self.view._add("Amoonguss")
        self.assertEqual(self.view.store.selected_id, saved_id)
        self.assertEqual(len(self.view.grid.controls), 3)
        self.assertTrue(any(isinstance(d, ft.SnackBar) for d in self.page.dialogs))
        self.assertFalse(self.view._add_field.disabled)

    def test_add_failure_shows_inline_banner(self):
        self.view.ensure_loaded()
        with patch.object(self.view.store, "add_by_name", side_effect=LookupError("'Pikachuu' could not be found")):
            self.view._add("Pikachuu")
        self.assertTrue(self.view._add_banner.visible)
        self.assertIn("could not be found", self.view._add_banner._text.value)

    def test_delete_without_teams_is_immediate_with_undo(self):
        self.view.ensure_loaded()
        deleted = []
        self.ctx.bus.on(events.BOX_ENTRY_DELETED, deleted.append)
        self.view._delete(self.rillaboom)  # StubPage runs the coroutine to completion
        self.assertEqual(deleted, [self.rillaboom])
        self.assertEqual(len(self.view.grid.controls), 1)
        snack = next(d for d in self.page.dialogs if isinstance(d, ft.SnackBar))
        self.assertEqual(snack.action, "Undo")
        self.view._undo_delete([e for e in [] ] or self.view.store.entries[:0])  # no-op guard
        snack.on_action(None)
        self.assertEqual(len(self.view.grid.controls), 2, "undo restored the entry")


if __name__ == "__main__":
    unittest.main()


class TestBoxBulkAndRanges(_BoxViewCase):
    """Multi-selection bar and the range filters (C12)."""

    def test_check_from_card_shows_bulk_bar_and_select_all(self):
        self.view.ensure_loaded()
        self.view._check(self.charizard, True)
        self.assertTrue(self.view.bulk_bar.visible)
        self.assertEqual(self.view._bulk_count.value, "1 selected")
        self.assertTrue(self.view._cards[self.charizard]._check.value)
        self.view.handle_key(type("K", (), {"key": "a", "ctrl": True, "shift": True})())
        self.assertEqual(self.view._bulk_count.value, "2 selected")
        serialise(self.view)
        self.view.handle_key(type("K", (), {"key": "Escape", "ctrl": False, "shift": False})())
        self.assertFalse(self.view.bulk_bar.visible, "Esc clears the selection first")

    def test_bulk_favourite_and_delete_with_confirmation(self):
        self.view.ensure_loaded()
        self.view.store.select_all_visible()
        self.view._bulk_favorite(True)
        self.assertTrue(all(e.is_favorite for e in self.view.store.entries))
        from unittest.mock import AsyncMock

        self.ctx.confirm = AsyncMock(return_value=True)
        self.view.store.select_all_visible()
        self.ctx.page.run_task(self.view._bulk_delete)
        self.ctx.confirm.assert_awaited_once()
        self.assertIn("Sun", self.ctx.confirm.await_args.args[1], "affected teams are named")
        self.assertEqual(self.view.store.entries, [])
        self.assertFalse(self.view.bulk_bar.visible)

    def test_bulk_delete_cancelled_keeps_entries(self):
        self.view.ensure_loaded()
        from unittest.mock import AsyncMock

        self.ctx.confirm = AsyncMock(return_value=False)
        self.view.store.select_all_visible()
        self.ctx.page.run_task(self.view._bulk_delete)
        self.assertEqual(len(self.view.store.entries), 2)

    def test_range_filters_apply_and_echo_as_chips(self):
        self.view.ensure_loaded()
        self.view.toolbar._set(bst_range=(510, 600))
        self.assertEqual(len(self.view.grid.controls), 1, "only Rillaboom (BST 525) is in range; Charizard is 500")
        self.assertIn("BST 510–600", [c.content.controls[0].value for c in self.view.toolbar.active_row.controls if hasattr(c, "content") and hasattr(c.content, "controls")])
        self.view.toolbar._set_stat_range("speed", 90, 255)
        self.assertEqual(len(self.view.grid.controls), 0)
        self.view.toolbar.clear()
        self.assertEqual(len(self.view.grid.controls), 2)
        self.view.toolbar._toggle_drawer("stats", True)
        self.assertTrue(self.view.toolbar.drawer.visible)
        serialise(self.view)


class TestBoxLoadingFeedback(_BoxViewCase):
    """The roster never blocks the window without saying so."""

    def test_skeleton_shows_until_the_first_render(self):
        self.assertTrue(self.view._loading.visible, "a fresh view shows the skeleton, not an empty panel")
        self.assertFalse(self.view.grid.visible)
        self.view.ensure_loaded()
        self.assertFalse(self.view._loading.visible)
        self.assertTrue(self.view.grid.visible)

    def test_usage_sort_fetches_off_the_render_and_ends_sorted(self):
        from dataclasses import replace

        self.view.ensure_loaded()
        self.assertFalse(self.view.store.usage_map_cached("latest"), "not read until something asks for it")
        self.view._on_filters(replace(self.view.store.filters, sort="usage"))
        # The stub page runs the worker inline, so by now the fetch has been and gone.
        self.assertTrue(self.view.store.usage_map_cached("latest"))
        self.assertFalse(self.view._usage_loading)
        self.assertFalse(self.view._loading.visible, "the skeleton gives way once the counts are in")
        self.assertTrue(self.view.grid.visible)
        self.assertEqual(len(self.view.grid.controls), 2)

    def test_usage_sort_shows_the_skeleton_while_the_counts_are_outstanding(self):
        from dataclasses import replace

        self.view.ensure_loaded()
        # Pin the view in the state it holds while the worker is still running.
        self.view._usage_loading = True
        self.view.store.set_filters(replace(self.view.store.filters, sort="usage"))
        self.view._render()
        self.assertTrue(self.view._loading.visible)
        self.assertFalse(self.view.grid.visible)
        self.assertFalse(self.view._empty.visible)
        self.assertFalse(self.view._no_match.visible)

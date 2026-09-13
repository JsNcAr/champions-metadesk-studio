"""Team view: six cards, header, summary, dialogs — against a temp DB and stub page."""

import contextlib
import shutil
import tempfile
import unittest
from pathlib import Path
from unittest.mock import AsyncMock, patch

import flet as ft
from sqlmodel import Session, SQLModel, create_engine

from _ui_stubs import StubPage, serialise
from pokemon_champions_planning_tool.domain.entities.box_entry import BoxEntry
from pokemon_champions_planning_tool.domain.entities.pokemon import Pokemon
from pokemon_champions_planning_tool.domain.entities.pokemon_ability import PokemonAbility
from pokemon_champions_planning_tool.domain.entities.pokemon_stats import PokemonStats
from pokemon_champions_planning_tool.infrastructure.database.models import ItemRecord, MegaEvolutionRecord
from pokemon_champions_planning_tool.infrastructure.database.repositories import BoxRepository
from pokemon_champions_planning_tool.ui import events
from pokemon_champions_planning_tool.ui.catalogs import Catalogs
from pokemon_champions_planning_tool.ui.context import AppContext
from pokemon_champions_planning_tool.ui.views.team import TeamStore
from pokemon_champions_planning_tool.ui.views.team.dialogs.item_picker import ItemPickerDialog
from pokemon_champions_planning_tool.ui.views.team.dialogs.spread import SpreadDialog
from pokemon_champions_planning_tool.ui.views.team.view import TeamView


def _mon(cid, name, types, abilities=("blaze",), **stats) -> Pokemon:
    base = dict(hp=80, attack=80, defense=80, sp_atk=80, sp_def=80, speed=80)
    base.update(stats)
    return Pokemon(canonical_id=cid, display_name=name, species_name=cid, types=list(types), stats=PokemonStats(**base),
                   abilities=[PokemonAbility(name=a) for a in abilities])


class _TempDb:
    def __init__(self):
        self.dir = tempfile.mkdtemp()
        self.engine = create_engine(f"sqlite:///{Path(self.dir) / 'teamview.db'}", connect_args={"check_same_thread": False})
        SQLModel.metadata.create_all(self.engine)

    @contextlib.contextmanager
    def session(self):
        with Session(self.engine) as s:
            yield s

    def close(self):
        self.engine.dispose()
        shutil.rmtree(self.dir)


class _TeamViewCase(unittest.TestCase):
    def setUp(self):
        self.db = _TempDb()
        with self.db.session() as s:
            repo = BoxRepository(s)
            self.charizard = repo.upsert_box_entry(BoxEntry(pokemon=_mon("charizard", "Charizard", ["fire", "flying"], ("blaze", "solar-power"), attack=84))).box_entry_id
            self.lucario = repo.upsert_box_entry(BoxEntry(pokemon=_mon("lucario", "Lucario", ["fighting", "steel"], attack=110))).box_entry_id
            s.add(MegaEvolutionRecord(canonical_id="charizard-mega-x", species_name="charizard", display_name="Mega Charizard X", types=["fire", "dragon"],
                                      hp=78, attack=130, defense=111, special_attack=130, special_defense=85, speed=100))
            s.add(ItemRecord(canonical_id="charizardite-x", display_name="Charizardite X", category="mega-stone", is_champions_legal=True, target_species="charizard", target_form="mega-x", stat_modifiers={}))
            s.add(ItemRecord(canonical_id="choice-band", display_name="Choice Band", category="choice", is_champions_legal=True, stat_modifiers={"attack": 1.5}, short_effect="Boosts Attack but locks the move"))
            s.commit()
        self.page = StubPage()
        self.ctx = AppContext(self.page, catalogs=Catalogs.load(self.db.session))
        self.ctx.run_in_background = lambda work, on_done=None, on_error=None, **kw: on_done(work()) if on_done else work()  # synchronous partners
        self.store = TeamStore(self.ctx.catalogs, self.db.session)
        self.view = TeamView(self.ctx, self.store)

    def tearDown(self):
        self.db.close()


class TestTeamView(_TeamViewCase):
    def test_empty_state_then_create_team(self):
        self.view.ensure_loaded()
        self.assertTrue(self.view._empty.visible)
        self.assertFalse(self.view.grid.visible)
        serialise(self.view)
        self.ctx.prompt_text = AsyncMock(return_value="Sun")
        self.page.run_task(self.view._new_team)
        self.assertEqual(self.store.active_team_name, "Sun")
        self.assertTrue(self.view.grid.visible)
        self.assertEqual(len(self.view._team_select.options), 1)
        self.assertIn("0/6", self.view._team_select.options[0].text)

    def test_assign_renders_card_and_summary_and_emits_active_team(self):
        actives = []
        self.ctx.bus.on(events.ACTIVE_TEAM, actives.append)
        self.view.ensure_loaded()
        self.store.create_team("Sun")
        self.store.assign(1, self.charizard)
        card = self.view.cards[0]
        self.assertEqual(card._name.value, "Charizard")
        self.assertEqual(card._ability.value, "Blaze")
        self.assertTrue(card._form.visible, "mega forms available")
        self.assertIn("6/6", [c._label.value for c in self.view._health.controls] + ["1/6"]) if False else None
        self.assertTrue(any("1/6" in c._label.value for c in self.view._health.controls))
        self.assertEqual(actives[-1], self.store.active_team_id)
        self.assertGreater(serialise(self.view), 200)

    def test_item_flow_updates_card_guardrail_and_deltas(self):
        self.view.ensure_loaded()
        self.store.create_team("Sun")
        self.store.assign(1, self.charizard)
        self.view._open_item_picker(1)
        dialog = self.page.dialogs[-1]
        self.assertIsInstance(dialog, ItemPickerDialog)
        serialise(dialog)
        dialog._on_pick("choice-band")
        card = self.view.cards[0]
        self.assertEqual(card._item_name.value, "Choice Band")
        self.assertTrue(card._deltas.visible)
        self.assertIn("+50%", card._deltas.controls[0]._label.value)
        self.view._open_item_picker(1)
        self.page.dialogs[-1]._on_pick("charizardite-x")
        self.assertEqual(self.store.slot(1).member.selected_form, "charizard-mega-x")
        self.assertEqual(card._form_caption.value, "Mega Charizard X")
        self.assertTrue(card._guardrail.visible)

    def test_move_picker_flow_sets_and_clears_specific_slots(self):
        self.view.ensure_loaded()
        self.store.create_team("Sun")
        self.store.assign(1, self.charizard)
        card = self.view.cards[0]
        # Open move picker for Move 3 (index 2) when moves 1 and 2 are empty
        self.view._open_move_picker(1, 2)
        dialog = self.page.dialogs[-1]
        self.assertFalse(dialog._current)
        dialog._on_pick("Flamethrower")
        # Ensure slot 3 got Flamethrower, and slot 1/2 remain empty
        self.assertEqual(card._moves[2]._name.value, "Flamethrower")
        self.assertEqual(card._moves[0]._name.value, "Move 1…")
        self.assertEqual(card._moves[1]._name.value, "Move 2…")
        self.assertEqual(self.store.slot(1).moves[2].name, "Flamethrower")
        self.assertIsNone(self.store.slot(1).moves[0])
        # Open Move 3 picker again: current should now be Flamethrower
        self.view._open_move_picker(1, 2)
        dialog2 = self.page.dialogs[-1]
        self.assertEqual(dialog2._current, "Flamethrower")
        # Clear move
        dialog2._on_pick(None)
        self.assertEqual(card._moves[2]._name.value, "Move 3…")
        self.assertIsNone(self.store.slot(1).moves[2])

    def test_item_clear_removes_item_without_opening_dialog(self):
        self.view.ensure_loaded()
        self.store.create_team("Sun")
        self.store.assign(1, self.charizard)
        self.store.set_item(1, "choice-band")
        card = self.view.cards[0]
        self.assertEqual(card._item_name.value, "Choice Band")
        self.assertTrue(card._item_clear.visible)
        dialog_count = len(self.page.dialogs)
        # Click item clear button directly
        card._item_clear.on_click(None)
        self.assertIsNone(self.store.slot(1).item)
        self.assertEqual(card._item_name.value, "Held item…")
        self.assertFalse(card._item_clear.visible)
        # Verify no ItemPickerDialog was opened
        new_dialogs = self.page.dialogs[dialog_count:]
        self.assertFalse(any(isinstance(d, ItemPickerDialog) for d in new_dialogs))

    def test_spread_dialog_saves_and_rejects(self):
        self.view.ensure_loaded()
        self.store.create_team("Sun")
        self.store.assign(1, self.charizard)
        self.view._open_spread(1)
        dialog = self.page.dialogs[-1]
        self.assertIsInstance(dialog, SpreadDialog)
        serialise(dialog)
        dialog._apply_points({"attack": 32, "speed": 32, "hp": 2})
        dialog._nature.value = "adamant"
        dialog._recompute()
        self.assertEqual(dialog._computed["attack"].value, "149", "84 base, 32 points, Adamant: floor((84+32+20)·1.1)")
        dialog._save()
        self.assertEqual(self.store.slot(1).member.points, {"attack": 32, "speed": 32, "hp": 2})
        self.assertIn("32 Atk", self.view.cards[0]._spread.value)
        self.view._open_spread(1)
        dialog = self.page.dialogs[-1]
        dialog._editor._points["hp"] = 3  # past the 66 budget, bypassing the editor's clamp
        dialog._save()
        self.assertTrue(dialog._banner.visible)

    def test_clear_with_undo_swap_and_keyboard_focus(self):
        self.view.ensure_loaded()
        self.store.create_team("Sun")
        self.store.assign(1, self.charizard)
        self.store.assign(2, self.lucario)
        self.view._clear_slot(1)
        self.assertFalse(self.store.slot(1).filled)
        snack = next(d for d in self.page.dialogs if isinstance(d, ft.SnackBar))
        snack.on_action(None)
        self.assertTrue(self.store.slot(1).filled, "undo restored the slot")
        self.view._swap(1, 3)
        self.assertEqual(self.store.slot(3).entry.pokemon.display_name, "Charizard")
        self.assertEqual(self.view.focused, 3)
        self.view.handle_key(type("K", (), {"key": "Arrow Right", "ctrl": False, "alt": True, "shift": False})())
        self.assertEqual(self.view.focused, 4)
        self.view.handle_key(type("K", (), {"key": "Escape", "ctrl": False, "alt": False, "shift": False})())
        self.assertIsNone(self.view.focused)

    def test_assign_dialog_pick_and_export_requests(self):
        self.view.ensure_loaded()
        self.store.create_team("Sun")
        self.view._open_assign(2)
        dialog = self.page.dialogs[-1]
        serialise(dialog)
        dialog._on_pick(self.lucario)
        self.assertEqual(self.store.slot(2).entry.pokemon.display_name, "Lucario")
        from pokemon_champions_planning_tool.ui.views.team.dialogs.export_dialog import ExportDialog
        from pokemon_champions_planning_tool.ui.views.team.dialogs.import_dialog import ImportDialog

        self.view._import()
        self.assertIsInstance(self.page.dialogs[-1], ImportDialog)
        self.view._open_export()
        self.assertIsInstance(self.page.dialogs[-1], ExportDialog)
        with patch.object(self.ctx, "copy_to_clipboard") as copy:
            self.view._copy_export()
        self.assertIn("Lucario", copy.call_args.args[0])

    def test_teams_changed_from_legacy_import_reloads(self):
        self.view.ensure_loaded()
        self.store.create_team("Sun")
        other = self.store.create_team("Rain")
        self.ctx.bus.emit(events.TEAMS_CHANGED, other)
        self.assertEqual(self.store.active_team_id, other)
        self.assertEqual(len(self.view._team_select.options), 2)



class TestSlotDragAndDrop(_TeamViewCase):
    def test_drop_on_another_card_swaps_and_highlights(self):
        self.view.ensure_loaded()
        self.store.create_team("Sun")
        self.store.assign(1, self.charizard)
        src = self.view.cards[0]
        target = self.view.cards[3]
        event = type("E", (), {"src": src._drag_handle})()
        target._on_will_accept(event)
        self.assertTrue(target._drop_hover)
        target._on_accept(event)
        self.assertFalse(target._drop_hover)
        self.assertEqual(self.store.slot(4).entry.pokemon.display_name, "Charizard")
        self.assertFalse(self.store.slot(1).filled)
        serialise(self.view)

    def test_drop_on_itself_is_ignored(self):
        self.view.ensure_loaded()
        self.store.create_team("Sun")
        self.store.assign(2, self.lucario)
        card = self.view.cards[1]
        card._on_accept(type("E", (), {"src": card._drag_handle})())
        self.assertEqual(self.store.slot(2).entry.pokemon.display_name, "Lucario")


if __name__ == "__main__":
    unittest.main()

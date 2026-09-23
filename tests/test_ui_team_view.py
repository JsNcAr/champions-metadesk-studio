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
from pokemon_champions_planning_tool.ui.theme import Palette
from pokemon_champions_planning_tool.ui.views.team import TeamStore
from pokemon_champions_planning_tool.ui.views.team.dialogs.item_picker import ItemPickerDialog
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
        self.assertEqual(self.view.mode, "library", "no teams: the library is the empty state")
        self.assertTrue(self.view.library._empty.visible)
        serialise(self.view)
        self.ctx.prompt_text = AsyncMock(return_value="Sun")
        self.page.run_task(self.view._new_team)
        self.assertEqual(self.store.active_team_name, "Sun")
        self.assertEqual(self.view.mode, "editor", "a new team opens in the editor")
        self.assertIn(self.view._body, self.view.controls)
        self.assertEqual((self.view._switch_name.value, self.view._switch_count.value), ("Sun", "0/6"))

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
        self.assertEqual(self.view.compacts[0]._name.value, "Charizard")
        self.assertIn("note", self.view._health_label.value, "one summary chip for the team's checks")
        self.assertIn("1/6", self.view._health.tooltip)
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

    def test_inline_spread_saves_and_rejects(self):
        self.view.ensure_loaded()
        self.store.create_team("Sun")
        self.store.assign(1, self.charizard)
        editor = self.view.cards[0]._spread_editor
        editor._nature.value = "adamant"
        editor.apply_points({"attack": 32, "speed": 32, "hp": 2})    # no page loop: saved at once
        self.assertEqual(editor._computed["attack"].value, "149", "84 base, 32 points, Adamant: floor((84+32+20)·1.1)")
        self.assertEqual(self.store.slot(1).member.points, {"attack": 32, "speed": 32, "hp": 2})
        self.assertEqual(self.store.slot(1).member.nature, "adamant")
        self.assertIn("32 Atk", self.view.compacts[0]._spread.value)
        self.view._spread_changed(1, "adamant", {"attack": 32, "speed": 32, "hp": 3})   # past the 66 budget
        self.assertTrue(self.view.cards[0]._spread_banner.visible)
        self.assertEqual(self.store.slot(1).member.points, {"attack": 32, "speed": 32, "hp": 2}, "an illegal spread is not saved")

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
        self.assertEqual(self.view._switch_name.value, "Rain")
        self.view.open_library()
        self.assertEqual([r.name for r in self.view.library.rows], ["Rain", "Sun"], "most recently edited first")



class TestSlotDragAndDrop(_TeamViewCase):
    def test_drop_on_another_card_swaps_and_highlights(self):
        self.view.ensure_loaded()
        self.store.create_team("Sun")
        self.store.assign(1, self.charizard)
        src = self.view.compacts[0]
        target = self.view.compacts[3]
        event = type("E", (), {"src": src.drag_handle})()
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
        card = self.view.compacts[1]
        card._on_accept(type("E", (), {"src": card.drag_handle})())
        self.assertEqual(self.store.slot(2).entry.pokemon.display_name, "Lucario")


def _key(key, *, ctrl=False, alt=False, shift=False):
    return type("K", (), {"key": key, "ctrl": ctrl, "alt": alt, "shift": shift})()


class TestTeamGrid(_TeamViewCase):
    def setUp(self):
        super().setUp()
        from _ui_stubs import check_layout

        self.check_layout = check_layout
        self.view.ensure_loaded()
        self.store.create_team("Sun")
        self.store.assign(1, self.charizard)
        self.store.assign(2, self.lucario)

    def test_the_editor_opens_in_a_pane_and_cards_stay_in_place(self):
        cells = list(self.view.grid.controls)
        self.assertEqual([c.content for c in cells], self.view.compacts, "all compact at first")
        self.assertFalse(self.view._pane.visible)
        self.view.compacts[0].on_click(None)
        self.assertEqual(self.view.selected, 1)
        self.assertIs(self.view._pane.content, self.view.cards[0], "the editor sits in the pane")
        self.assertEqual(list(self.view.grid.controls), cells, "no card moved or was replaced")
        self.assertEqual([c.content for c in cells], self.view.compacts)
        self.assertTrue(all(c._condensed for c in self.view.compacts), "the cards condense while editing")
        self.assertTrue(self.view.compacts[1]._moves.visible, "moves stay visible while editing")
        self.assertFalse(self.view.compacts[1]._spread_row.visible, "only the spread row hides")
        self.assertTrue(self.view.compacts[0]._editing.visible)
        self.assertEqual(self.view.cards[0]._slot_label.value, "1 / 2")
        self.check_layout(self.view)
        serialise(self.view)
        self.view.compacts[1].on_click(None)
        self.assertIs(self.view._pane.content, self.view.cards[1], "another card switches the pane")
        self.assertFalse(self.view.compacts[0]._editing.visible)
        self.view._set_selected(4)
        self.assertEqual(self.view.selected, 2, "an empty slot does not open")
        self.view.compacts[1].on_click(None)
        self.assertIsNone(self.view.selected, "clicking the open card closes the pane")
        self.assertFalse(self.view._pane.visible)
        self.assertFalse(any(c._condensed for c in self.view.compacts))
        self.view.compacts[3].on_click(None)
        from pokemon_champions_planning_tool.ui.views.team.dialogs.assign import AssignDialog

        self.assertIsInstance(self.page.dialogs[-1], AssignDialog, "clicking an empty card assigns")

    def test_stepping_through_the_filled_slots(self):
        self.view._set_selected(1)
        self.view.cards[0]._next.on_click(None)
        self.assertEqual(self.view.selected, 2)
        self.view.cards[1]._next.on_click(None)
        self.assertEqual(self.view.selected, 1, "wraps around, skipping empty slots")
        self.view.handle_key(_key("Arrow Left", alt=True))
        self.assertEqual(self.view.selected, 2, "Alt+← moves the selection while the pane is open")

    def test_editor_edits_show_on_the_compact_card(self):
        self.view._set_selected(1)
        self.view._open_item_picker(1)
        self.page.dialogs[-1]._on_pick("choice-band")
        self.assertEqual(self.view.compacts[0]._item.value, "Choice Band")
        self.assertTrue(self.view.cards[0]._item_effect.visible, "the item's effect under it")
        self.store.set_move(1, 0, "Flamethrower")
        self.view._clear_move(1, 0)
        self.assertIsNone(self.store.slot(1).moves[0])
        self.assertEqual(self.store.slot(1).battle_stats.speed, int(self.view.compacts[0]._speed.value.split()[-1]))

    def test_a_problem_shows_as_a_short_line_on_the_card(self):
        card = self.view.compacts[1]
        self.assertFalse(card._problem.visible)
        self.store.set_item(2, "charizardite-x")            # a Charizard stone on Lucario
        self.assertTrue(card._problem.visible)
        self.assertIn("can only be held by Charizard", card._problem.value)
        self.view._set_selected(1)
        self.assertTrue(card._problem.visible, "still shown while the editor is open")

    def test_defense_block_and_weakness_line(self):
        card = self.view.cards[0]          # Charizard: Fire/Flying
        labels = [row.controls[0].content.value for row in card._defense.controls]
        self.assertEqual(labels, ["4×", "2×", "½", "¼", "Immune"])
        quad = [chip for chip in card._defense.controls[0].controls[1].controls]
        self.assertEqual(len(quad), 1, "Rock hits Fire/Flying 4×")
        weak = "".join(span.text for span in self.view.compacts[0]._weak.spans)
        self.assertTrue(weak.startswith("Weak: Rock 4×"), weak)
        self.assertIn("Immune: Ground", self.view.compacts[0]._weak.tooltip)

    def test_keyboard_select_move_and_escape_order(self):
        self.view._focus(1)
        self.view.handle_key(_key("Enter"))
        self.assertEqual(self.view.selected, 1)
        self.view.handle_key(_key("Arrow Right", alt=True, shift=True))
        self.assertEqual(self.store.slot(2).entry.pokemon.display_name, "Charizard", "Alt+Shift+→ moves the card")
        self.assertEqual(self.view.selected, 2, "the editor follows the card")
        self.assertTrue(self.view.summary.visible)
        self.view.handle_key(_key("Escape"))
        self.assertIsNone(self.view.selected, "first Escape closes the editor")
        self.view.handle_key(_key("Escape"))
        self.assertIsNone(self.view.focused, "then clears the focus")
        self.view.handle_key(_key("Escape"))
        self.assertFalse(self.view.summary.visible, "then closes the panel")

    def test_tournament_set_menu_applies_and_undoes(self):
        from pokemon_champions_planning_tool.services.tournament_service import TournamentBuild

        build = TournamentBuild("charizard", ["Heat Wave", "Protect"], "timid", "Choice Band", "Solar Power")
        self.store._builds = {"charizard": build}
        self.view._set_selected(1)
        card = self.view.cards[0]
        self.assertTrue(card._build_menu.visible)
        self.assertIn("Choice Band · Solar Power · Timid · Heat Wave, Protect", card._build_line.value)
        card._build_menu.items[2].on_click(None)                    # Apply the full set
        member = self.store.slot(1).member
        self.assertEqual(([m.name for m in member.moveset if m.name], member.item, member.ability, member.nature),
                         (["Heat Wave", "Protect"], "choice-band", "Solar Power", "Timid"))
        snack = next(d for d in reversed(self.page.dialogs) if isinstance(d, ft.SnackBar))
        snack.on_action(None)
        self.assertIsNone(self.store.slot(1).member.item, "Undo restores the slot")
        self.store._builds = {}
        self.view._set_selected(2)
        self.assertFalse(self.view.cards[1]._build_menu.visible, "no tournament data: no menu")

    def test_move_rows_show_category_power_accuracy_and_stab(self):
        from types import SimpleNamespace

        from pokemon_champions_planning_tool.domain.moves import MoveInfo
        from pokemon_champions_planning_tool.ui.views.team.slot_card import MoveButton

        heat_wave = MoveInfo("heatwave", "Heat Wave", "fire", "special", 95, 90, 10, 0, "allAdjacentFoes", "May burn the foes.", True)
        button = MoveButton(index=0, on_click=lambda: None)
        button.update_from(SimpleNamespace(name="Heat Wave", info=heat_wave, legal=True), species="Charizard", types=("fire", "flying"))
        self.assertTrue(button._category.visible)
        self.assertEqual(button._category.tooltip, "Fire · Special")
        self.assertTrue(button._stab.visible, "a Fire move on Charizard")
        self.assertEqual(button._meta.value, "95 · 90%")
        self.assertIn("Hits both foes", button.tooltip)
        self.assertIn("May burn the foes.", button.tooltip)
        button.update_from(SimpleNamespace(name="Heat Wave", info=heat_wave, legal=True), species="Lucario", types=("fighting", "steel"))
        self.assertFalse(button._stab.visible)

    def test_compact_menu_moves_cards(self):
        items = {getattr(i.content, "value", None): i for i in self.view.compacts[1]._menu.items}
        self.assertNotIn(None, [k for k in items if k and k.startswith("Swap")], "no Swap-with-N list any more")
        items["Move left"].on_click(None)
        self.assertEqual(self.store.slot(1).entry.pokemon.display_name, "Lucario")
        self.assertEqual(self.store.slot(2).entry.pokemon.display_name, "Charizard")
        self.assertEqual(self.store.slot(2).member.slot_position, 2, "swapped in memory with the right positions")
        self.store.load()
        self.assertEqual(self.store.slot(1).entry.pokemon.display_name, "Lucario", "and saved")

    def test_analysis_tabs_render_when_shown(self):
        panel = self.view.summary
        self.assertIn("stats", panel._stale, "Stats is built when first shown")
        panel.show_tab("stats")
        rows = panel.battle_rows()
        self.assertEqual([r[0].position for r in rows], [1, 2])
        self.assertEqual(rows[0][1], self.store.slot(1).battle_stats)
        panel.sort_by("speed")
        speeds = [r[1].speed for r in panel.battle_rows()]
        self.assertEqual(speeds, sorted(speeds, reverse=True))
        panel.sort_by("speed")
        self.assertEqual([r[0].position for r in panel.battle_rows()], [1, 2], "clicking again restores slot order")
        for tab in ("coverage", "roles", "overview"):
            panel.show_tab(tab)
            self.check_layout(panel)
            serialise(panel)
        self.assertTrue(panel._role_rows.controls)
        self.view._health.on_click(None)
        self.assertEqual(panel.tab, "overview", "the health chip opens the checks")

    def test_partner_chip_opens_meta(self):
        seen = []
        self.ctx.bus.on(events.NAVIGATE, lambda v: seen.append(("nav", v)))
        self.ctx.bus.on(events.META_SEARCH, lambda q: seen.append(("search", q)))
        self.view._open_partner("Incineroar")
        self.assertEqual(seen, [("nav", "meta"), ("search", "Incineroar")])

    def test_team_menu_has_every_team_action(self):
        labels = [getattr(i.content, "value", None) for i in self.view._more.items]
        for label in ("New team", "Rename team…", "Duplicate team…", "Compare teams…", "Delete team…"):
            self.assertIn(label, labels)


class TestTeamLibrary(_TeamViewCase):
    def setUp(self):
        super().setUp()
        self.view.ensure_loaded()
        self.sun = self.store.create_team("Sun")
        self.store.assign(1, self.charizard)
        self.store.assign(2, self.lucario)
        self.rain = self.store.create_team("Rain")
        self.store.assign(1, self.lucario)
        self.view._open_team(self.sun)

    def test_tiles_show_every_team_with_its_sprites(self):
        from _ui_stubs import check_layout

        self.view.handle_key(type("K", (), {"key": "l", "ctrl": True, "alt": False, "shift": False})())
        self.assertEqual(self.view.mode, "library")
        lib = self.view.library
        rows = {r.name: r for r in lib.rows}
        self.assertEqual([m.name for m in rows["Sun"].members], ["Charizard", "Lucario"])
        self.assertTrue(all(m.sprite_url for m in rows["Sun"].members))
        tiles = lib._grid.controls
        self.assertEqual(len(tiles), 2)
        active = next(t for t in tiles if t.row.name == "Sun")
        self.assertEqual(active.border.top.color, Palette.PRIMARY, "the open team is marked")
        check_layout(self.view)
        serialise(self.view)
        lib._search.value = "charizard"
        lib.render()
        self.assertEqual([t.row.name for t in lib._grid.controls], ["Sun"], "search matches Pokémon too")
        lib._search.value = ""
        lib.set_sort("complete")
        self.assertEqual([r.name for r in lib.shown()], ["Sun", "Rain"])
        lib.set_sort("name")
        self.assertEqual([r.name for r in lib.shown()], ["Rain", "Sun"])

    def test_opening_and_leaving_the_library(self):
        self.view.open_library()
        tile = next(t for t in self.view.library._grid.controls if t.row.name == "Rain")
        tile.on_click(None)
        self.assertEqual((self.view.mode, self.store.active_team_name), ("editor", "Rain"))
        self.view.open_library()
        self.view.handle_key(type("K", (), {"key": "Escape", "ctrl": False, "alt": False, "shift": False})())
        self.assertEqual(self.view.mode, "editor", "Escape goes back to the team")

    def test_tile_actions(self):
        from pokemon_champions_planning_tool.ui.views.team.dialogs.compare import CompareDialog

        self.view.open_library()
        self.view._compare_with(self.rain)
        dialog = self.page.dialogs[-1]
        self.assertIsInstance(dialog, CompareDialog)
        self.assertEqual(dialog._picker.value, str(self.rain))
        self.assertEqual(dialog._right._name.value, "Rain")
        copied = []
        self.ctx.copy_to_clipboard = copied.append
        self.view._copy_team(self.rain)
        self.assertIn("Lucario", copied[-1])
        self.assertNotIn("Charizard", copied[-1], "the tile's team, not the open one")
        self.assertEqual(self.store.active_team_name, "Sun", "copying does not switch teams")
        self.ctx.prompt_text = AsyncMock(return_value="Drizzle")
        self.view._act_on(self.rain, self.view._rename_team)
        self.assertIn("Drizzle", [r.name for r in self.view.library.rows])
        self.assertEqual(self.view.mode, "library", "renaming stays in the library")


if __name__ == "__main__":
    unittest.main()

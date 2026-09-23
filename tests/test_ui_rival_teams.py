"""Rival teams in the calculator: ratings against the attacker, the Team vs team grid, the
right column's "Rival team" mode, the team-preview dialog, battle write-back and Meta's
"Save as rival team"."""

import sys
import unittest
from pathlib import Path
from types import SimpleNamespace

sys.path.insert(0, str(Path(__file__).resolve().parent))
from _ui_stubs import StubPage, check_layout, serialise  # noqa: E402
from test_ui_calc import _Base, _FakeTeamStore, _team_slot, _walk  # noqa: E402

import flet as ft  # noqa: E402

from sqlmodel import Session, SQLModel, create_engine  # noqa: E402

from pokemon_champions_planning_tool.ui import events  # noqa: E402
from pokemon_champions_planning_tool.ui.context import AppContext  # noqa: E402
from pokemon_champions_planning_tool.ui.help import SHORTCUTS, TIPS  # noqa: E402
from pokemon_champions_planning_tool.ui.preferences import Preferences  # noqa: E402
from pokemon_champions_planning_tool.ui.views.calc import CalcStore, CalcView, PokemonState  # noqa: E402
from pokemon_champions_planning_tool.ui.views.calc.classes import CLASS_BG  # noqa: E402
from pokemon_champions_planning_tool.ui.views.calc.dialogs.battle_preview import BattleDialog  # noqa: E402
from pokemon_champions_planning_tool.ui.views.calc.dialogs.team_matrix import TeamMatrixDialog, summarise  # noqa: E402
from pokemon_champions_planning_tool.ui.views.calc.state import RIVAL_FIELDS, RivalMember, classify  # noqa: E402
from pokemon_champions_planning_tool.ui.views.calc.view import PREF_RIGHT_MODE  # noqa: E402
from pokemon_champions_planning_tool.ui.views.meta.row import TeamRow  # noqa: E402
from pokemon_champions_planning_tool.ui.views.meta.view import MetaView  # noqa: E402

PASTE = """Kingambit @ Life Orb
Ability: Defiant
EVs: 32 HP / 32 Atk / 2 Spe
Adamant Nature
- Kowtow Cleave
- Iron Head

Incineroar
Ability: Intimidate
- Flare Blitz
"""


def _rivals(*species_moves):
    return [PokemonState(species=cid, moves=list(moves) + [None] * (4 - len(moves)), ability=ability)
            for cid, moves, ability in species_moves]


def _slots():
    return [
        _team_slot(1, "incineroar", "Incineroar", ("fire", "dark"), (95, 115, 90, 80, 90, 60), ["Flare Blitz"], ability="Intimidate"),
        _team_slot(2, "charizard", "Mega Charizard Y", ("fire", "flying"), (78, 104, 78, 159, 115, 100), ["Heat Wave"],
                   ability="Drought", nature="Modest", points={"special_attack": 32, "speed": 32}, mega="charizard-mega-y", item="Charizardite Y"),
    ]


class TestRivalComputation(_Base):
    def setUp(self):
        super().setUp()
        self.store.team_store = _FakeTeamStore(_slots())
        self.store.load_species("left", "kingambit")
        self.store.set_move("left", 0, "Kowtow Cleave")
        self.rivals = _rivals(("incineroar", ["Flare Blitz"], "Intimidate"), ("kingambit", ["Iron Head"], "Defiant"), ("missingno", [], None))

    def _count_calls(self):
        calls = []
        real = self.store._calc
        self.store._calc = lambda *a, **k: (calls.append(1), real(*a, **k))[1]
        return calls

    def test_rivals_are_rated_against_the_attacker(self):
        ratings = self.store.rate_rivals(self.rivals)
        self.assertEqual(len(ratings), 3)
        self.assertIsNone(ratings[2], "unknown species: no rating")
        blaze = ratings[0]
        self.assertEqual(blaze.your_best.name, "Kowtow Cleave")
        self.assertEqual(blaze.their_best.name, "Flare Blitz")
        for r in ratings[:2]:
            self.assertEqual(r.klass, classify(r.your_best, r.their_best, r.faster))
        self.store.load_pokemon("left", PokemonState())
        self.assertEqual(self.store.rate_rivals(self.rivals), (None, None, None), "no attacker: nothing to rate")

    def test_the_grid_is_cached_per_pair(self):
        grid = self.store.team_matrix(self.rivals[:2])
        self.assertEqual(sorted(grid), [("team-1:1", 0), ("team-1:1", 1), ("team-1:2", 0), ("team-1:2", 1)])
        self.assertEqual(grid[("team-1:2", 1)].klass, "crushed", "Mega Charizard Y's sun Heat Wave, faster, OHKOs Kingambit")
        for r in grid.values():
            self.assertEqual(r.klass, classify(r.your_best, r.their_best, r.faster))
        calls = self._count_calls()
        self.store.team_matrix(self.rivals[:2])
        self.assertEqual(calls, [], "nothing changed: every cell from the cache")
        edited = [self.rivals[0], PokemonState(species="kingambit", moves=["Iron Head", "Kowtow Cleave", None, None], ability="Defiant")]
        self.store.team_matrix(edited)
        self.assertEqual(len(calls), 2 * 3, "one column recomputed: per member one move out, two back")
        self.assertEqual(self.store.team_matrix(edited)[("team-1:1", 0)], grid[("team-1:1", 0)])

    def test_the_field_changes_every_cell(self):
        before = self.store.team_matrix(self.rivals[1:2])[("team-1:1", 0)]    # Incineroar vs Kingambit: no speed tie
        self.store.toggle_field("trick_room")
        after = self.store.team_matrix(self.rivals[1:2])[("team-1:1", 0)]
        self.assertEqual(after.faster, not before.faster)

    def test_the_rival_link_follows_the_defender(self):
        self.store.load_rival("team-a", 1, PokemonState(species="incineroar"))
        self.assertEqual(self.store.rival_link, ("team-a", 1))
        self.store.set_item("right", "Life Orb")
        self.assertEqual(self.store.rival_link, ("team-a", 1), "editing the member keeps the link")
        self.store.load_species("left", "incineroar")
        self.assertEqual(self.store.rival_link, ("team-a", 1), "a new attacker keeps it too")
        self.store.load_species("right", "kingambit")
        self.assertIsNone(self.store.rival_link, "a Defender from elsewhere drops it")
        self.store.load_rival("team-a", 0, PokemonState(species="incineroar"))
        self.store.swap_sides()
        self.assertIsNone(self.store.rival_link)

    def test_summaries(self):
        grid = self.store.team_matrix(self.rivals[:2])
        answers, per_rival = summarise(grid, ["team-1:1", "team-1:2"], 2)
        good = {"crushed", "mitigated"}
        self.assertEqual(answers["team-1:2"], sum(1 for c in range(2) if grid[("team-1:2", c)].klass in good))
        self.assertEqual(per_rival[1][1], sum(1 for k in ("team-1:1", "team-1:2") if grid[(k, 1)].klass == "threat"))


class _TeamsWithHistory(_FakeTeamStore):
    """The fake team store, plus a second team readable by id (as TeamStore.summary_for)."""

    def __init__(self, slots):
        super().__init__(slots)
        self.teams = [SimpleNamespace(team_id="team-1", name="Sand", filled=len(slots)), SimpleNamespace(team_id="team-2", name="Empty", filled=0)]

    def summary_for(self, team_id):
        return ("Sand", self.slots, None) if team_id == "team-1" else ("Empty", [], None)


class _ViewBase(_Base):
    def setUp(self):
        super().setUp()
        self.store.team_store = _TeamsWithHistory(_slots())
        self.page = StubPage()
        self.ctx = AppContext(self.page)
        self.ctx.prefs = self.prefs
        self.ctx.catalogs = self.catalogs
        self.toasts = []
        self.ctx.toast = lambda message, kind="info", **kw: self.toasts.append((message, kw))
        self.navigated = []
        self.ctx.bus.on(events.NAVIGATE, self.navigated.append)
        self.view = CalcView(self.ctx, self.store)
        self.view.ensure_loaded()
        self.store.load_species("left", "kingambit")
        self.store.set_move("left", 0, "Kowtow Cleave")

    def _battle(self, *queries):
        self.view.open_battle_dialog("preview")
        dialog = self.page.dialogs[-1]
        self.assertIsInstance(dialog, BattleDialog)
        for index, query in enumerate(queries):
            slot = dialog.slots[index]
            slot.field.value = query
            dialog._typed(slot, query)
            dialog._submit(slot, query)
        return dialog


class TestRivalPanel(_ViewBase):
    def test_the_side_panel_switches_and_remembers(self):
        side = self.view.side_panel
        self.assertEqual(side.tab, "opponents")
        self.assertIs(side._body.content, self.view.sweep)
        side.select("rivals")
        self.assertIs(side._body.content, self.view.rivals_panel)
        self.assertEqual(self.prefs.get("calc.side_tab", None), "rivals")
        self.assertTrue(self.view.rivals_panel._empty.visible, "no rival team yet")
        self.assertTrue(self.view.rival_strip._empty.visible, "the strip offers team preview")
        side.select("box")
        self.assertIs(side._body.content, self.view.box)
        side.select("rivals")
        check_layout(self.view)
        serialise(self.view)
        again = CalcView(self.ctx, CalcStore(self.catalogs, session_factory=None, prefs=Preferences(self.prefs.path)))
        self.assertEqual(again.side_panel.tab, "rivals")

    def test_the_old_right_column_choice_carries_over(self):
        self.prefs.set(PREF_RIGHT_MODE, "rival")
        again = CalcView(self.ctx, CalcStore(self.catalogs, session_factory=None, prefs=Preferences(self.prefs.path)))
        self.assertEqual(again.side_panel.tab, "rivals")

    def test_team_preview_by_keyboard_starts_a_battle(self):
        dialog = self._battle("king", "incin")
        self.assertEqual([s.name for s in dialog.slots[:2]], ["Kingambit", "Incineroar"])
        self.assertTrue(dialog.slots[0].caption.value, "the assumed set is shown")
        self.assertEqual(dialog.slots[0].member.assumed, frozenset(RIVAL_FIELDS))
        check_layout(dialog)
        serialise(dialog)
        dialog._submit(dialog.slots[2], "")                    # Enter on an empty slot: start
        self.assertEqual(self.page.dialogs, [])
        battle = self.view.rivals.battle
        self.assertEqual([m.pokemon.species for m in battle.members], ["kingambit", "incineroar"])
        strip = self.view.rival_strip
        self.assertEqual(len(strip.avatars), 2, "the strip above the Defender shows the battle")
        self.assertIsNotNone(strip.avatars[1].rating, "rated against the attacker")
        self.assertIn("Tournament set", strip.avatars[1].tile.tooltip)
        cards = self.view.rivals_panel._list.controls
        self.assertEqual(len(cards), 2)
        self.assertIsNotNone(self.view.rivals_panel._ratings[1], "rated against the attacker")
        self.assertIn("Tournament set", cards[1].tooltip)
        check_layout(self.view)
        serialise(self.view)

    def test_revealed_items_stick_for_the_battle(self):
        self._battle("king", "incin")
        self.page.dialogs[-1]._start_battle()
        self.view.rivals_panel._list.controls[1].on_click(None)
        self.assertEqual(self.store.state.right.species, "incineroar")
        self.assertEqual(self.store.rival_link, (self.view.rivals.battle.rival_team_id, 1))
        self.assertIn("Rival · Battle · slot 2", self.store.state.right.source)
        self.assertEqual(self.view.rivals_panel._linked, 1)
        self.store.set_item("right", "Life Orb")
        self.store.set_boost("right", "attack", -1)
        member = self.view.rivals.battle.members[1]
        self.assertEqual(member.pokemon.item, "Life Orb", "written back")
        self.assertNotIn("item", member.assumed)
        self.assertEqual(member.pokemon.boosts, {}, "stat stages belong to the turn")
        self.view.rivals_panel._list.controls[0].on_click(None)
        self.view.rivals_panel._list.controls[1].on_click(None)
        self.assertEqual(self.store.state.right.item, "Life Orb", "still there when it comes back")
        self.assertFalse(self.view.rival_strip._update_member.visible, "a battle saves by itself")
        self.assertEqual(self.view.rival_strip._linked, 1)
        self.view.rival_strip.avatars[0].on_secondary()          # right-click: as the attacker
        self.assertEqual(self.store.state.left.species, "kingambit")
        self.view.rival_strip.avatars[1].on_primary()
        self.assertEqual(self.store.state.right.species, "incineroar")

    def test_a_saved_plan_changes_only_on_request(self):
        members = [RivalMember(PokemonState(species="incineroar", moves=["Flare Blitz", None, None, None], ability="Intimidate"), frozenset({"item"}))]
        team = self.view.rivals.create("Wolfe", members)
        self.view.set_right_mode("rival")
        self.view.rivals_panel._list.controls[0].on_click(None)
        self.store.set_item("right", "Life Orb")
        self.assertIsNone(self.view.rivals.get(team.rival_team_id).members[0].pokemon.item, "browsing a plan never overwrites it")
        self.assertTrue(self.view.rival_strip._update_member.visible)
        self.assertIn("Incineroar", self.view.rival_strip._update_member.content)
        self.view._rival_action("update_member")
        saved = self.view.rivals.get(team.rival_team_id).members[0]
        self.assertEqual((saved.pokemon.item, saved.assumed), ("Life Orb", frozenset()))
        self.assertFalse(self.view.rival_strip._update_member.visible)

    def test_team_actions(self):
        async def named(*_a, **_k):
            return "Kept"

        self.ctx.prompt_text = named
        self._battle("king")
        self.page.dialogs[-1]._start_battle()
        self.view._rival_action("save_battle")
        self.assertEqual([t.name for t in self.view.rivals.teams], ["Current battle", "Kept"])
        self.view._rival_action("end_battle")
        self.assertIsNone(self.view.rivals.battle)
        self.assertEqual(self.toasts[-1][1]["action"], "Undo")
        self.toasts[-1][1]["on_action"]()
        self.assertIsNotNone(self.view.rivals.battle, "Undo brings the battle back")
        kept = next(t for t in self.view.rivals.teams if t.name == "Kept")
        self.view.rivals.set_active(kept.rival_team_id)
        self.view._rival_action("duplicate")
        self.assertIn("Kept (copy)", [t.name for t in self.view.rivals.teams])
        self.view._rival_action("delete")
        self.assertNotIn("Kept (copy)", [t.name for t in self.view.rivals.teams])
        self.view.rivals.set_active(kept.rival_team_id)
        labels = [getattr(i.content, "value", None) for i in self.view.rival_strip._menu.items]
        self.assertIn("Rename preset…", labels)
        self.assertIn("Use in battle", labels)

    def test_paste_tab(self):
        self.view.open_battle_dialog("paste")
        dialog = self.page.dialogs[-1]
        dialog._paste.value = PASTE
        dialog._read_paste()
        self.assertEqual([m.pokemon.species for m in dialog.members()], ["kingambit", "incineroar"])
        self.assertTrue(dialog._save.disabled, "saving needs a name")
        dialog._name.value = "Ladder Kingambit"
        dialog._sync_actions()
        dialog._save_team()
        team = self.view.rivals.active
        self.assertEqual((team.name, team.is_battle, team.source), ("Ladder Kingambit", False, "Paste"))
        self.assertEqual(team.members[0].pokemon.item, "Life Orb")

    def test_ctrl_b_opens_team_preview(self):
        self.assertTrue(self.view.handle_key(SimpleNamespace(key="B", ctrl=True, shift=False, alt=False, meta=False)))
        self.assertIsInstance(self.page.dialogs[-1], BattleDialog)
        self.assertIn(("Ctrl+B", "Start a battle: enter the rival's team preview (Calc)"), SHORTCUTS)
        self.assertTrue(any("Rival team" in tip for tip in TIPS["Calc"]))

    def test_team_vs_team_grid(self):
        self._battle("king", "incin")
        self.page.dialogs[-1]._start_battle()
        self.view._rival_action("matrix")
        dialog = self.page.dialogs[-1]
        self.assertIsInstance(dialog, TeamMatrixDialog)
        rows = dialog._grid.controls
        self.assertEqual(len(rows), 1 + 2 + 1, "header, two members, the summary row")
        cell = rows[2].controls[1]                              # Mega Charizard Y vs Kingambit
        self.assertEqual(cell.bgcolor, CLASS_BG["crushed"])
        self.assertIn("Charizard", cell.tooltip)
        check_layout(dialog)
        serialise(dialog)
        cell.on_click(None)
        self.assertEqual(self.page.dialogs, [])
        self.assertEqual((self.store.state.left.species, self.store.state.right.species), ("charizard-mega-y", "kingambit"))
        self.assertEqual(self.store.rival_link[1], 0)


class TestPresetsAndMyTeams(_ViewBase):
    def test_help_buttons_open_a_dialog(self):
        from pokemon_champions_planning_tool.ui.components.help_button import help_button

        self.view.set_right_mode("rival")
        for panel in (self.view.rivals_panel, self.view.sweep):
            button = next(c for c in _walk(panel) if isinstance(c, ft.IconButton) and c.icon == ft.Icons.HELP_OUTLINE)
            self.assertIsNotNone(button.on_click, "a click, not only a hover tooltip")
            button.on_click(SimpleNamespace(control=SimpleNamespace(page=self.page)))
            dialog = self.page.dialogs[-1]
            self.assertIsInstance(dialog, ft.AlertDialog)
            check_layout(dialog)
            serialise(dialog)
            dialog.actions[0].on_click(None)
            self.assertEqual(self.page.dialogs, [])
        self.assertTrue(callable(help_button("t", ["a:"]).on_click))

    def test_save_team_preview_as_a_preset(self):
        dialog = self._battle("king", "incin")
        self.assertTrue(dialog._save.disabled, "a preset needs a name")
        dialog._name.value = "Ladder Kingambit"
        dialog._sync_actions()
        dialog._save_team()
        preset = self.view.rivals.active
        self.assertEqual((preset.name, preset.is_battle, len(preset.members)), ("Ladder Kingambit", False, 2))
        self.assertIsNone(self.view.rivals.battle, "saving does not start a battle")

    def test_a_preset_goes_into_the_current_battle_and_stays_as_saved(self):
        members = [RivalMember(PokemonState(species="incineroar", moves=["Flare Blitz", None, None, None], ability="Intimidate"), frozenset({"item"}))]
        preset = self.view.rivals.create("Wolfe", members)
        self.view.set_right_mode("rival")
        self.assertTrue(self.view.rival_strip._use.visible, "a preset on screen offers Use in battle")
        self.view._rival_action("use_preset")
        battle = self.view.rivals.battle
        self.assertEqual(self.view.rivals.active_id, battle.rival_team_id)
        self.assertEqual(battle.members, preset.members)
        self.assertEqual(battle.source, "Preset · Wolfe")
        self.assertFalse(self.view.rival_strip._use.visible)
        self.view.rivals_panel._list.controls[0].on_click(None)
        self.store.set_item("right", "Life Orb")
        self.assertEqual(self.view.rivals.battle.members[0].pokemon.item, "Life Orb", "the battle keeps the reveal")
        self.assertIsNone(self.view.rivals.get(preset.rival_team_id).members[0].pokemon.item, "the preset does not")

    def test_the_load_dialog_lists_presets_and_starts_from_one(self):
        preset = self.view.rivals.create("Wolfe", [RivalMember(PokemonState(species="kingambit"))])
        self.view._rival_action("load")
        dialog = self.page.dialogs[-1]
        self.assertEqual(dialog._mode, "presets", "with presets saved, Load team opens on them")
        self.assertTrue(dialog._start.disabled)
        self.assertFalse(dialog._save_row.visible, "a preset is already saved")
        dialog.pick_preset(preset)
        self.assertEqual(dialog._start.content, "Use in battle")
        check_layout(dialog)
        serialise(dialog)
        dialog._start_battle()
        self.assertEqual(self.page.dialogs, [])
        self.assertEqual(self.view.rivals.battle.source, "Preset · Wolfe")

    def test_load_one_of_my_teams(self):
        self.view.open_battle_dialog("teams")
        dialog = self.page.dialogs[-1]
        self.assertEqual([c.title for c in dialog._team_choices.values()], ["Sand", "Empty"])
        dialog.pick_team("team-1")
        self.assertEqual([m.pokemon.species for m in dialog.members()], ["incineroar", "charizard-mega-y"])
        self.assertTrue(all(not m.assumed for m in dialog.members()), "your own sets are known")
        self.assertEqual(dialog._name.value, "Sand", "named after the team")
        check_layout(dialog)
        serialise(dialog)
        dialog._save_team()
        preset = self.view.rivals.active
        self.assertEqual((preset.name, preset.source), ("Sand", "My team · Sand"))
        self.view.open_battle_dialog("teams")
        dialog = self.page.dialogs[-1]
        dialog.pick_team("team-2")
        self.assertEqual(dialog.members(), [])
        self.assertTrue(dialog._banner.visible)
        dialog.pick_team("team-1")
        dialog._start_battle()
        self.assertEqual(self.view.rivals.battle.members[1].pokemon.item, "Charizardite Y")


class TestMetaSavesRivalTeams(_Base):
    def test_save_as_rival_team_and_open_in_calc(self):
        engine = create_engine("sqlite:///:memory:")
        self.addCleanup(engine.dispose)
        SQLModel.metadata.create_all(engine)
        sf = lambda: Session(engine)  # noqa: E731
        page = StubPage()
        ctx = AppContext(page)
        ctx.prefs = self.prefs
        ctx.catalogs = self.catalogs
        toasts = []
        ctx.toast = lambda message, kind="info", **kw: toasts.append((message, kw))
        calc = CalcView(ctx, CalcStore(self.catalogs, session_factory=sf, prefs=self.prefs))
        calc.ensure_loaded()
        row = SimpleNamespace(player_name="Wolfe", tournament_name="Worlds", showdown_text=PASTE,
                              members=[SimpleNamespace(canonical_id="kingambit", display_name="Kingambit"),
                                       SimpleNamespace(canonical_id="incineroar", display_name="Incineroar")])
        MetaView._save_rival(SimpleNamespace(ctx=ctx, store=SimpleNamespace(session_factory=sf)), row)
        self.assertEqual([t.name for t in calc.rivals.teams], ["Wolfe — Worlds"], "the calculator reloaded")
        message, kw = toasts[-1]
        self.assertEqual(kw["action"], "Open in Calc")
        kw["on_action"]()
        self.assertEqual(calc.rivals.active.name, "Wolfe — Worlds")
        self.assertEqual(calc.side_panel.tab, "rivals")

    def test_the_row_menu_offers_it(self):
        from datetime import datetime
        from uuid import uuid4

        from pokemon_champions_planning_tool.services.tournament_service import MetaMemberRow, MetaTeamRow

        members = tuple(MetaMemberRow(slot=i + 1, species_name=n, canonical_id=n.lower(), sprite_url="", is_legal=True) for i, n in enumerate(("Kingambit", "Incineroar")))
        row = MetaTeamRow(team_id=uuid4(), tournament_id="e", tournament_name="Event", event_date=datetime(2026, 1, 1), regulation="Reg M-B", game_platform="Pokémon Champions",
                          organizer="Play! Pokémon", location="Online", total_players=8, source_url=None, event_tier="regional", player_name="Ash", placement=1, standing_label="Place #1",
                          pokepast_url=None, showdown_text=PASTE, members=members, legality_known=True)
        saved = []
        team_row = TeamRow(row, on_import=lambda _r: None, on_calc=lambda _r, _i: None, on_rival=saved.append)
        menu = next(c for c in _walk(team_row) if isinstance(c, ft.PopupMenuButton))
        self.assertEqual(menu.items[-1].content.value, "Save as rival preset")
        menu.items[-1].on_click(None)
        self.assertEqual(saved, [row])
        serialise(team_row)


if __name__ == "__main__":
    unittest.main()

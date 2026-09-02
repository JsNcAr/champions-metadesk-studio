"""Damage calculator UI: store state/mutations/cache/persistence, view rendering, entry points."""

import shutil
import sys
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace

import flet as ft

sys.path.insert(0, str(Path(__file__).resolve().parent))
from _ui_stubs import StubPage, serialise  # noqa: E402

from pokemon_champions_planning_tool.domain.moves import MoveInfo, MoveMechanics  # noqa: E402
from pokemon_champions_planning_tool.domain.species import SpeciesInfo  # noqa: E402
from pokemon_champions_planning_tool.ui import events  # noqa: E402
from pokemon_champions_planning_tool.ui.catalogs import Catalogs  # noqa: E402
from pokemon_champions_planning_tool.ui.context import AppContext  # noqa: E402
from pokemon_champions_planning_tool.ui.help import TIPS  # noqa: E402
from pokemon_champions_planning_tool.ui.preferences import Preferences  # noqa: E402
from pokemon_champions_planning_tool.ui.theme import Accent  # noqa: E402
from pokemon_champions_planning_tool.ui.views.calc import CalcRequest, CalcState, CalcStore, CalcView, PokemonState, pokemon_from_parsed, pokemon_from_slot  # noqa: E402
from pokemon_champions_planning_tool.ui.views.calc.store import PREF_STATE  # noqa: E402
from pokemon_champions_planning_tool.ui.views.meta.row import TeamRow  # noqa: E402
from pokemon_champions_planning_tool.ui.views.team.slot_card import SlotCallbacks  # noqa: E402


def species(canonical_id, name, types, stats, abilities, weight, is_mega=False):
    return SpeciesInfo(canonical_id=canonical_id, showdown_id=name.lower().replace("-", ""), name=name, dex_number=1, base_species_id=name.lower(), forme=None,
                       types=types, base_stats=stats, abilities=abilities, weightkg=weight, gender="M", required_item=None, battle_only=None, is_mega=is_mega, is_legal=True)


KINGAMBIT = species("kingambit", "Kingambit", ("Dark", "Steel"), {"hp": 100, "atk": 135, "def": 120, "spa": 60, "spd": 85, "spe": 50}, ("Defiant", "Supreme Overlord", "Pressure"), 120)
INCINEROAR = species("incineroar", "Incineroar", ("Fire", "Dark"), {"hp": 95, "atk": 115, "def": 90, "spa": 80, "spd": 90, "spe": 60}, ("Blaze", "Intimidate"), 83)
MEGA_Y = species("charizard-mega-y", "Charizard-Mega-Y", ("Fire", "Flying"), {"hp": 78, "atk": 104, "def": 78, "spa": 159, "spd": 115, "spe": 100}, ("Drought",), 100.5, True)
MOVES = {
    "kowtowcleave": MoveInfo("kowtowcleave", "Kowtow Cleave", "dark", "physical", 85, 100, 10, 0, "normal", "", True, MoveMechanics(contact=True, slicing=True)),
    "ironhead": MoveInfo("ironhead", "Iron Head", "steel", "physical", 80, 100, 15, 0, "normal", "", True, MoveMechanics(contact=True, secondaries=True)),
    "flareblitz": MoveInfo("flareblitz", "Flare Blitz", "fire", "physical", 120, 100, 15, 0, "normal", "", True, MoveMechanics(contact=True, recoil=(33, 100), secondaries=True)),
    "heatwave": MoveInfo("heatwave", "Heat Wave", "fire", "special", 95, 90, 10, 0, "allAdjacentFoes", "", True, MoveMechanics(wind=True, secondaries=True)),
    "protect": MoveInfo("protect", "Protect", "normal", "status", None, None, 10, 4, "self", "", True),
}


def catalogs() -> Catalogs:
    return Catalogs(
        moves_by_id=MOVES,
        learnsets={"kingambit": frozenset({"kowtowcleave", "ironhead", "protect"}), "incineroar": frozenset({"flareblitz", "protect"}), "charizard": frozenset({"heatwave", "protect"})},
        species_by_canonical={s.canonical_id: s for s in (KINGAMBIT, INCINEROAR, MEGA_Y)},
    )


class _Base(unittest.TestCase):
    def setUp(self):
        self.dir = tempfile.mkdtemp()
        self.prefs = Preferences(Path(self.dir) / "prefs.json")
        self.catalogs = catalogs()
        self.store = CalcStore(self.catalogs, session_factory=None, prefs=self.prefs)
        self.store.load()

    def tearDown(self):
        shutil.rmtree(self.dir)


class TestCalcStore(_Base):
    def test_state_round_trip_tolerates_unknown_keys(self):
        state = CalcState.from_dict({"left": {"species": "kingambit", "points": {"attack": 32}, "moves": ["Iron Head"], "bogus": 1}, "field": {"weather": "Sun", "left": {"reflect": True, "nope": 2}}, "extra": {}})
        self.assertEqual(state.left.moves, ["Iron Head", None, None, None])
        self.assertEqual(state.field.left.reflect, True)
        self.assertEqual(CalcState.from_dict(state.to_dict()), state)
        self.assertEqual(state.key(), CalcState.from_dict(state.to_dict()).key())

    def test_load_species_defaults_and_results_both_ways(self):
        self.store.load_species("left", "kingambit")
        self.store.load_species("right", "incineroar")
        self.assertEqual(self.store.state.left.ability, "Defiant")
        self.assertTrue(self.store.results.empty, "no moves yet")
        self.store.set_move("left", 0, "Kowtow Cleave")
        self.store.set_move("left", 1, "Protect")
        self.store.set_move("left", 2, "Nope")
        self.store.set_move("right", 0, "Flare Blitz")
        results = self.store.results
        self.assertEqual([r.name for r in results.left_vs_right], ["Kowtow Cleave", "Protect", "Nope"])
        self.assertTrue(results.left_vs_right[0].ok)
        self.assertEqual(results.left_vs_right[1].error, "Status move")
        self.assertEqual(results.left_vs_right[2].error, "Not in the move catalogue")
        self.assertEqual(len(results.left_vs_right[0].rolls), 16)
        self.assertIn("Kingambit Kowtow Cleave vs.", results.left_vs_right[0].description)
        self.assertEqual((results.left_name, results.right_name), ("Kingambit", "Incineroar"))
        blitz = results.right_vs_left[0]
        self.assertTrue(blitz.ok)
        self.assertIn("recoil", blitz.recoil or "")

    def test_mutations_persist_and_are_cached(self):
        calls = []
        real = self.store._calc

        def counting(*args, **kwargs):
            calls.append(1)
            return real(*args, **kwargs)

        self.store._calc = counting
        self.store.load_species("left", "kingambit")
        self.store.load_species("right", "incineroar")
        self.store.set_move("left", 0, "Iron Head")
        n = len(calls)
        self.store.set_points("left", {"attack": 32, "speed": 40, "hp": 2})
        self.assertEqual(self.store.state.left.points, {"attack": 32, "speed": 32, "hp": 2})
        self.assertGreater(len(calls), n)
        n = len(calls)
        self.store.set_points("left", {"attack": 32, "speed": 40, "hp": 2})
        self.assertEqual(len(calls), n, "identical state is served from the cache")
        self.store.set_boost("left", "attack", 9)
        self.assertEqual(self.store.state.left.boosts, {"attack": 6})
        self.store.set_boost("left", "attack", 0)
        self.assertEqual(self.store.state.left.boosts, {})
        self.store.set_hp_abs("right", 50)
        self.assertEqual(self.store.cur_hp("right"), 50)
        self.assertAlmostEqual(self.store.state.right.hp_pct, 100 * 50 / self.store.max_hp("right"))
        self.store.toggle_crit("left", 0)
        self.assertTrue(self.store.state.left.crit[0])
        self.store.set_side_conditions("right", reflect=True, spikes=2)
        self.store.set_field(weather="Sand", game_type="singles")
        self.assertEqual((self.store.state.field.right.reflect, self.store.state.field.right.spikes, self.store.state.field.weather), (True, 2, "Sand"))
        self.store.swap_sides()
        self.assertEqual((self.store.state.left.species, self.store.state.field.left.reflect), ("incineroar", True))
        restored = CalcStore(self.catalogs, session_factory=None, prefs=Preferences(Path(self.dir) / "prefs.json"))
        restored.load()
        self.assertEqual(restored.state, self.store.state, "the last calculation is remembered")
        self.assertIsNotNone(self.prefs.get(PREF_STATE))
        self.store.reset()
        self.assertEqual(self.store.state, CalcState())

    def test_builders_from_slot_and_paste(self):
        from pokemon_champions_planning_tool.domain.entities.pokemon_stats import PokemonStats

        stats = PokemonStats(hp=78, attack=84, defense=78, sp_atk=109, sp_def=85, speed=100)
        entry = SimpleNamespace(pokemon=SimpleNamespace(canonical_id="charizard", display_name="Charizard", abilities=[SimpleNamespace(name="blaze")]))
        member = SimpleNamespace(selected_form="charizard-mega-y", item="Charizardite Y", ability=None, points={"special_attack": 32, "speed": 32, "hp": 2}, nature="Timid",
                                 moveset=[SimpleNamespace(name="Heat Wave"), SimpleNamespace(name="Protect")])
        form = SimpleNamespace(form_id="charizard-mega-y", label="Mega Charizard Y", types=("fire", "flying"), stats=stats, is_mega=True)
        slot = SimpleNamespace(entry=entry, member=member, form=form, item=SimpleNamespace(display_name="Charizardite Y"))
        p = pokemon_from_slot(slot, self.catalogs, source="Sun · slot 1")
        self.assertEqual((p.species, p.ability, p.item, p.nature, p.points), ("charizard-mega-y", "Drought", "Charizardite Y", "timid", {"special_attack": 32, "speed": 32, "hp": 2}))
        self.assertEqual(p.moves, ["Heat Wave", "Protect", None, None])
        self.assertEqual(p.source, "Sun · slot 1")
        parsed = SimpleNamespace(ability_name="Intimidate", item_name="Sitrus Berry", points={"hp": 252, "attack": 4, "defense": 252}, nature="Impish", moves=("Flare Blitz",))
        q = pokemon_from_parsed(parsed, "incineroar", self.catalogs, source="Paste")
        self.assertEqual((q.species, q.ability, q.item, q.nature, q.points), ("incineroar", "Intimidate", "Sitrus Berry", "impish", {"hp": 252, "attack": 4, "defense": 252}))
        self.assertIsNone(pokemon_from_parsed(None, "garchomp", self.catalogs))
        self.store.apply_request(CalcRequest(attacker=p, defender=q))
        self.assertEqual((self.store.state.left.species, self.store.state.right.species), ("charizard-mega-y", "incineroar"))
        self.assertTrue(self.store.results.left_vs_right[0].ok)


class TestCalcView(_Base):
    def setUp(self):
        super().setUp()
        self.page = StubPage()
        self.ctx = AppContext(self.page)
        self.ctx.prefs = self.prefs
        self.ctx.catalogs = self.catalogs
        self.navigated = []
        self.ctx.bus.on(events.NAVIGATE, self.navigated.append)
        self.view = CalcView(self.ctx, self.store)
        self.view.ensure_loaded()

    def _load_pair(self):
        self.store.load_species("left", "kingambit")
        self.store.load_species("right", "incineroar")
        self.store.set_move("left", 0, "Kowtow Cleave")
        self.store.set_move("left", 1, "Iron Head")
        self.store.set_move("left", 2, "Swords Dance")
        self.store.set_move("right", 0, "Flare Blitz")

    def test_empty_and_full_render(self):
        self.assertGreater(serialise(self.view), 100)
        self.assertEqual(self.view.attacker.cards[0]._name.value, "Move 1…")
        self._load_pair()
        cards = self.view.attacker.cards
        self.assertEqual(cards[0]._name.value, "Kowtow Cleave")
        self.assertIn("%", cards[0]._pct.value)
        self.assertTrue(cards[0]._bar.visible)
        self.assertTrue(cards[0]._eff.visible, "Dark vs Fire/Dark is resisted: 0.5×")
        self.assertEqual(cards[0]._eff._label.value, "0.5×")
        self.assertTrue(cards[2]._activate.visible, "Swords Dance has a known effect")
        self.assertEqual(self.view.attacker._name.value, "Kingambit")
        self.assertEqual(self.view.attacker._ability.value, "Defiant")
        self.assertIn("/ 175", self.view.attacker._hp_label.value)
        self.assertTrue(self.view.attacker._speed.visible)
        serialise(self.view)
        cards[0].toggle()
        self.assertTrue(cards[0].expanded)
        self.assertGreater(len(cards[0]._details.controls), 2)
        serialise(self.view)
        self.assertTrue(self.view.handle_key(SimpleNamespace(key="Escape", ctrl=False, shift=False, alt=False, meta=False)))
        self.assertFalse(cards[0].expanded)

    def test_status_move_activation_applies_boosts_and_field(self):
        self._load_pair()
        before = self.store.results.left_vs_right[0].max_pct
        self.assertTrue(self.store.toggle_move_effect("left", 2))
        self.assertEqual(self.store.state.left.boosts, {"attack": 2})
        self.assertTrue(self.store.state.left.active[2])
        self.assertGreater(self.store.results.left_vs_right[0].max_pct, before)
        self.store.toggle_move_effect("left", 2)
        self.assertEqual(self.store.state.left.boosts, {})
        self.store.set_move("right", 1, "Will-O-Wisp")
        self.store.toggle_move_effect("right", 1)
        self.assertEqual(self.store.state.left.status, "brn")
        self.store.set_move("right", 2, "Tailwind")
        self.store.toggle_move_effect("right", 2)
        self.assertTrue(self.store.state.field.right.tailwind)
        self.store.set_move("right", 2, "Protect")
        self.assertFalse(self.store.state.field.right.tailwind, "replacing an active move reverts its effect")
        self.assertTrue(self.store.toggle_move_effect("right", 2), "Protect is a known side condition")
        self.assertTrue(self.store.state.field.right.protect)
        self.store.set_move("right", 3, "Roar")
        self.assertFalse(self.store.toggle_move_effect("right", 3), "unknown status moves have no toggle")
        self.assertFalse(self.store.toggle_move_effect("left", 0), "damaging moves have no effect toggle")

    def test_field_strip_and_speed_order(self):
        self._load_pair()
        self.view.field.tiles["weather:Sun"].on_click(None)
        self.assertEqual(self.store.state.field.weather, "Sun")
        self.assertTrue(self.view.field.tiles["weather:Sun"].active)
        self.view.field.tiles["weather:Sun"].on_click(None)
        self.assertEqual(self.store.state.field.weather, "none")
        self.view.field.tiles["singles"].on_click(None)
        self.assertEqual(self.store.state.field.game_type, "singles")
        self.view.field._toggle_side("right", "reflect")
        self.view.field._cycle_spikes("right")
        self.view.field._cycle_spikes("right")
        self.assertEqual((self.store.state.field.right.reflect, self.store.state.field.right.spikes), (True, 2))
        self.assertEqual(self.view.field.side_chips[("right", "spikes")].label.value, "Spikes ×2")
        self.assertEqual(self.store.speed_order(), "right", "Incineroar (80) outspeeds Kingambit (50)")
        self.view.field.tiles["trick_room"].on_click(None)
        self.assertEqual(self.store.speed_order(), "left")
        self.view.field.tiles["tailwind_left"].on_click(None)
        self.assertGreater(self.store.speed("left"), 102)
        serialise(self.view)

    def test_panel_search_and_edits_go_through_the_store(self):
        self.view.attacker._suggest("king")
        self.assertEqual([c.label.value for c in self.view.attacker._suggestions.controls], ["Kingambit"])
        self.view.attacker._submit("king")
        self.assertEqual(self.store.state.left.species, "kingambit")
        self.view.attacker.editor._typed("attack", "32")
        self.assertEqual(self.store.state.left.points, {"attack": 32})
        self.view.attacker._bump("attack", 1)
        self.view.attacker._bump("attack", 1)
        self.assertEqual(self.store.state.left.boosts, {"attack": 2})
        self.assertEqual(self.view.attacker._stages["attack"].value.value, "+2")
        self.view.attacker._status_changed("brn")
        self.assertEqual(self.store.state.left.status, "brn")
        self.view.attacker._hp_typed("90")
        self.assertEqual(self.store.cur_hp("left"), 90)
        self.view.attacker._toggle_spread()
        self.assertFalse(self.view.attacker._spread_body.visible)
        serialise(self.view)

    def test_rail_and_sweep(self):
        self._load_pair()
        entries = self.store.compute_sweep()
        self.assertEqual({e.canonical_id for e in entries}, {"kingambit", "incineroar", "charizard-mega-y"})
        by = {e.canonical_id: e for e in entries}
        self.assertFalse(by["incineroar"].preset, "no roster data: their moves unknown")
        self.assertIn(by["incineroar"].klass, {"wall", "neutral", "mitigated"})
        self.assertIsNotNone(by["charizard-mega-y"].your_best)
        self.store.publish_sweep(entries)
        self.assertFalse(self.store.sweep_stale())
        self.assertEqual(len(self.view.sweep._list.controls), 3)
        self.view.sweep._set_query("char")
        self.assertEqual(len(self.view.sweep._list.controls), 1)
        self.view.sweep._set_query("")
        self.view.sweep._set_class("wall")
        self.assertTrue(all(c.content.controls[2]._label.value == "Wall" for c in self.view.sweep._list.controls if hasattr(c, "content") and isinstance(c.content, ft.Row)))
        self.view.sweep._set_class(None)
        card = self.view.sweep._list.controls[0]
        card.on_click(None)
        self.assertEqual(self.store.state.right.species, card.content.controls[0].tooltip or self.store.state.right.species)
        self.assertTrue(self.store.state.right.source.startswith("Opponents"))
        self.assertEqual(self.view.rail._team.controls[0].value, "No team yet — build one in Teams.")
        serialise(self.view)

    def test_resize_and_request(self):
        self.view.handle_resize(1000, 700)
        self.assertIs(self.view._host.content, self.view._stack)
        self.assertIsNone(self.view.rail.width)
        serialise(self.view)
        self.view.handle_resize(1440, 900)
        self.assertIs(self.view._host.content, self.view._wide)
        self.assertEqual(self.view.sweep.width, 300)
        serialise(self.view)
        self._load_pair()
        self.assertTrue(self.view.handle_key(SimpleNamespace(key="S", ctrl=True, shift=True, alt=False, meta=False)))
        self.assertEqual(self.store.state.left.species, "incineroar")
        self.ctx.bus.emit(events.CALC_REQUESTED, CalcRequest(attacker=PokemonState(species="charizard-mega-y", ability="Drought", moves=["Heat Wave", None, None, None])))
        self.assertEqual(self.store.state.left.species, "charizard-mega-y")
        self.assertEqual(self.navigated, ["calc"])
        self.assertEqual(self.view.attacker.cards[0]._name.value, "Heat Wave")

    def test_classify_rules(self):
        from pokemon_champions_planning_tool.ui.views.calc.state import classify

        def mr(pct):
            return MoveResultStub(pct) if pct is not None else None

        self.assertEqual(classify(mr(120), mr(30), True), "crushed")
        self.assertEqual(classify(mr(120), mr(110), False), "threat", "they OHKO first")
        self.assertEqual(classify(mr(120), mr(110), True), "crushed", "you OHKO first")
        self.assertEqual(classify(mr(40), mr(60), True), "threat", "their 2HKO beats your 3HKO")
        self.assertEqual(classify(mr(20), mr(20), True), "wall")
        self.assertEqual(classify(None, mr(60), True), "threat")
        self.assertEqual(classify(mr(60), mr(40), False), "mitigated")
        self.assertEqual(classify(mr(60), mr(60), False), "neutral")
        self.assertEqual(classify(mr(60), None, False), "mitigated")

    def test_move_picker_shows_damage_against_the_other_pokemon_and_sorts_by_it(self):
        from pokemon_champions_planning_tool.ui.views.team.dialogs.move_picker import MovePickerDialog

        self._load_pair()
        preview = self.store.damage_preview("left", "Iron Head")
        self.assertIsNotNone(preview)
        self.assertGreater(preview.max_pct, 0)
        self.assertIsNone(self.store.damage_preview("left", None))
        self.store.set_field(weather="Rain")
        self.assertLess(self.store.damage_preview("right", "Flare Blitz").max_pct, self.store.damage_preview("right", "Flare Blitz").max_pct + 1)
        self.view._open_move_picker("left", 0)
        dialog = self.page.dialogs[-1]
        self.assertIsInstance(dialog, MovePickerDialog)
        self.assertIn("damage vs Incineroar", dialog._caption.value)
        self.assertTrue(dialog._sort_control.visible)
        self.assertEqual(dialog._sort, "damage", "the calculator defaults to damage order")
        names = [r.content.controls[2].value for r in dialog._list.controls if isinstance(r, ft.Container) and isinstance(r.content, ft.Row) and len(r.content.controls) > 2]
        self.assertEqual(names[:2], ["Kowtow Cleave", "Iron Head"], "Kowtow Cleave (85 BP, STAB) outdamages Iron Head; Protect last")
        chips = [c for r in dialog._list.controls if isinstance(r, ft.Container) and isinstance(r.content, ft.Row) for c in r.content.controls if isinstance(c, ft.Text) and c.width == 92]
        self.assertTrue(any("%" in c.value for c in chips))
        self.assertTrue(any(c.value == "—" for c in chips), "Protect shows no damage")
        dialog._set_sort("usage")
        self.assertEqual(self.ctx.prefs.get("calc.move_sort"), "usage")
        self.assertIn("ranked by tournament usage", dialog._caption.value)
        serialise(dialog)
        self.page.pop_dialog()
        self.store.reset()
        self.store.load_species("left", "kingambit")
        self.view._open_move_picker("left", 0)
        self.assertFalse(self.page.dialogs[-1]._sort_control.visible, "no target: no damage column")

    def test_help_and_accent(self):
        self.assertIn("Calc", TIPS)
        self.assertTrue(hasattr(Accent, "CALC"))


class MoveResultStub:
    def __init__(self, pct):
        self.ok = True
        self.min_pct = pct
        self.max_pct = pct


def _walk(control):
    yield control
    for attr in ("controls", "content", "actions"):
        child = getattr(control, attr, None)
        if child is None:
            continue
        for c in (child if isinstance(child, list) else [child]):
            if isinstance(c, ft.Control):
                yield from _walk(c)


class TestEntryPoints(unittest.TestCase):
    def test_slot_callbacks_default_and_meta_row_menu(self):
        cb = SlotCallbacks(on_assign=lambda p: None, on_clear=lambda p: None, on_form=lambda p, f: None, on_ability=lambda p, a: None, on_tera=lambda p, t: None,
                           on_item=lambda p: None, on_remove_item=lambda p: None, on_move=lambda p, i, n: None, on_notes=lambda p, n: None, on_spread=lambda p: None,
                           on_swap=lambda a, b: None, on_focus=lambda p: None)
        self.assertIsNone(cb.on_calc(1))
        from pokemon_champions_planning_tool.services.tournament_service import MetaMemberRow, MetaTeamRow

        members = tuple(MetaMemberRow(slot=i + 1, species_name=n, canonical_id=n.lower(), sprite_url="", is_legal=True) for i, n in enumerate(("Kingambit", "Incineroar")))
        from datetime import datetime
        from uuid import uuid4

        row = MetaTeamRow(team_id=uuid4(), tournament_id="e", tournament_name="Event", event_date=datetime(2026, 1, 1), regulation="Reg M-B", game_platform="Pokémon Champions",
                          organizer="Play! Pokémon", location="Online", total_players=8, source_url=None, event_tier="regional", player_name="Ash", placement=1, standing_label="Place #1",
                          pokepast_url=None, showdown_text="Kingambit @ Life Orb\nAbility: Supreme Overlord\n- Kowtow Cleave\n\nIncineroar\n- Flare Blitz\n", members=members, legality_known=True)
        picked = []
        team_row = TeamRow(row, on_import=lambda r: None, on_calc=lambda r, i: picked.append((r.player_name, i)))
        menu = next(c for c in _walk(team_row) if isinstance(c, ft.PopupMenuButton))
        self.assertEqual([i.content.value for i in menu.items], ["Kingambit", "Incineroar"])
        menu.items[1].on_click(None)
        self.assertEqual(picked, [("Ash", 1)])
        serialise(team_row)
        self.assertFalse(any(isinstance(c, ft.PopupMenuButton) for c in _walk(TeamRow(row, on_import=lambda r: None))))


if __name__ == "__main__":
    unittest.main()

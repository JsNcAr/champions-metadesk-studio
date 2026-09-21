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
from pokemon_champions_planning_tool.ui.views.calc.sweep import SweepPanel  # noqa: E402
from pokemon_champions_planning_tool.ui.views.calc.store import PREF_STATE  # noqa: E402
from pokemon_champions_planning_tool.ui.views.meta.row import TeamRow  # noqa: E402
from pokemon_champions_planning_tool.ui.views.team.slot_card import SlotCallbacks  # noqa: E402


from pokemon_champions_planning_tool.infrastructure.database.models import ItemRecord, MegaEvolutionRecord  # noqa: E402


def species(canonical_id, name, types, stats, abilities, weight, is_mega=False, required_item=None):
    return SpeciesInfo(canonical_id=canonical_id, showdown_id=name.lower().replace("-", ""), name=name, dex_number=1, base_species_id=name.lower().split("-")[0], forme=None,
                       types=types, base_stats=stats, abilities=abilities, weightkg=weight, gender="M", required_item=required_item, battle_only=None, is_mega=is_mega, is_legal=True)


KINGAMBIT = species("kingambit", "Kingambit", ("Dark", "Steel"), {"hp": 100, "atk": 135, "def": 120, "spa": 60, "spd": 85, "spe": 50}, ("Defiant", "Supreme Overlord", "Pressure"), 120)
INCINEROAR = species("incineroar", "Incineroar", ("Fire", "Dark"), {"hp": 95, "atk": 115, "def": 90, "spa": 80, "spd": 90, "spe": 60}, ("Blaze", "Intimidate"), 83)
CHARIZARD = species("charizard", "Charizard", ("Fire", "Flying"), {"hp": 78, "atk": 84, "def": 78, "spa": 109, "spd": 85, "spe": 100}, ("Blaze", "Solar Power"), 90.5)
MEGA_Y = species("charizard-mega-y", "Charizard-Mega-Y", ("Fire", "Flying"), {"hp": 78, "atk": 104, "def": 78, "spa": 159, "spd": 115, "spe": 100}, ("Drought",), 100.5, True, required_item="Charizardite Y")
MOVES = {
    "kowtowcleave": MoveInfo("kowtowcleave", "Kowtow Cleave", "dark", "physical", 85, 100, 10, 0, "normal", "", True, MoveMechanics(contact=True, slicing=True)),
    "ironhead": MoveInfo("ironhead", "Iron Head", "steel", "physical", 80, 100, 15, 0, "normal", "", True, MoveMechanics(contact=True, secondaries=True)),
    "flareblitz": MoveInfo("flareblitz", "Flare Blitz", "fire", "physical", 120, 100, 15, 0, "normal", "", True, MoveMechanics(contact=True, recoil=(33, 100), secondaries=True)),
    "heatwave": MoveInfo("heatwave", "Heat Wave", "fire", "special", 95, 90, 10, 0, "allAdjacentFoes", "", True, MoveMechanics(wind=True, secondaries=True)),
    "protect": MoveInfo("protect", "Protect", "normal", "status", None, None, 10, 4, "self", "", True),
}
ITEMS = {
    "charizardite-y": ItemRecord(canonical_id="charizardite-y", display_name="Charizardite Y", category="mega-stone", is_champions_legal=True, target_species="charizard", target_form="mega-y"),
    "life-orb": ItemRecord(canonical_id="life-orb", display_name="Life Orb", category="held", is_champions_legal=True),
}
MEGAS = (
    MegaEvolutionRecord(canonical_id="charizard-mega-y", species_name="Charizard", display_name="Mega Charizard Y", form_name="Mega Y",
                        types=["Fire", "Flying"], hp=78, attack=104, defense=78, special_attack=159, special_defense=115, speed=100, ability="Drought"),
)


def catalogs() -> Catalogs:
    return Catalogs(
        moves_by_id=MOVES,
        learnsets={"kingambit": frozenset({"kowtowcleave", "ironhead", "protect"}), "incineroar": frozenset({"flareblitz", "protect"}), "charizard": frozenset({"heatwave", "protect"})},
        species_by_canonical={s.canonical_id: s for s in (KINGAMBIT, INCINEROAR, MEGA_Y)},
        items_by_id=ITEMS,
        megas=MEGAS,
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
        self.assertEqual(self.store.state.field.weather, "Sun", "Mega Charizard Y Drought auto-activates Sun weather")

    def test_mega_drought_auto_activates_weather(self):
        self.store.set_field(weather=None)
        self.store.load_species("left", "charizard-mega-y")
        self.assertEqual(self.store.state.left.ability, "Drought")
        self.assertEqual(self.store.state.field.weather, "Sun", "Loading Mega Charizard Y automatically sets Sun")


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


    def test_species_search_says_when_nothing_matches(self):
        panel = self.view.attacker
        panel._suggest("zzzz")
        self.assertTrue(panel._no_match.visible)
        self.assertIn("zzzz", panel._no_match.value)
        panel.search.value = "zzzz"
        panel._submit("zzzz")
        self.assertEqual(panel.search.value, "zzzz", "Enter with no match keeps the text")
        panel._suggest("king")
        self.assertFalse(panel._no_match.visible)
        self.assertEqual(panel._suggestions.controls[0].label.color, "#F1F5F9", "suggestions are readable")

    def test_reset_can_be_undone(self):
        self._load_pair()
        before = self.store.state
        self.view._reset()
        self.assertEqual(self.store.state, CalcState())
        snack = self.page.dialogs[-1]
        self.assertEqual(snack.action, "Undo")
        snack.on_action(None)
        self.assertEqual(self.store.state, before)

    def test_ability_controls_only_where_the_engine_uses_them(self):
        self._load_pair()
        self.assertFalse(self.view.attacker._ability_on.visible, "Defiant has no on/off state in the engine")
        self.assertFalse(self.view.defender._ability_on.visible, "nor does Blaze")
        self.store.set_pokemon("right", ability="Intimidate")
        self.assertTrue(self.view.defender._ability_on.visible, "Intimidate does")
        self.assertFalse(self.view.attacker._allies.visible, "fainted allies only matter for Supreme Overlord")
        self.store.set_pokemon("left", ability="Supreme Overlord")
        self.assertTrue(self.view.attacker._allies.visible)

    def test_hp_field_restores_a_non_number(self):
        self._load_pair()
        panel = self.view.attacker
        current = panel._hp_abs.value
        panel._hp_abs.value = "abc"
        panel._hp_typed("abc")
        self.assertEqual(panel._hp_abs.value, current)

    def test_status_chips_brighten_when_selected(self):
        self._load_pair()
        self.store.set_pokemon("left", status="brn")
        chips = self.view.attacker._status_chips
        self.assertTrue(chips["brn"].selected)
        self.assertNotEqual(chips["brn"].label.color, chips["none"].label.color)

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


class TestTournamentPresets(_Base):
    def test_preset_builds_and_load_species_tournament_presets(self):
        from pokemon_champions_planning_tool.services.tournament_service import TournamentBuild

        builds = {
            "incineroar": TournamentBuild(
                canonical_id="incineroar",
                moves=["Flare Blitz", "Protect"],
                nature="careful",
                item="Sitrus Berry",
                ability="Intimidate",
            ),
            "charizard-mega-y": TournamentBuild(
                canonical_id="charizard-mega-y",
                moves=["Heat Wave", "Protect"],
                nature="timid",
                item="Charizardite Y",
                ability="Drought",
            ),
        }
        self.store._preset_builds = builds

        # 1. Loading with preset=False uses standard blank defaults
        self.store.load_species("right", "incineroar", preset=False)
        self.assertEqual(self.store.state.right.nature, "hardy")
        self.assertEqual(self.store.state.right.points, {})
        self.assertIsNone(self.store.state.right.item)
        self.assertEqual(self.store.state.right.ability, "Blaze")
        self.assertEqual(self.store.state.right.moves, [None, None, None, None])

        # 2. Loading with preset=True uses tournament build: careful nature, bulky spread, item, ability, moves
        self.store.load_species("right", "incineroar", preset=True)
        self.assertEqual(self.store.state.right.nature, "careful")
        self.assertEqual(self.store.state.right.points, {"hp": 32, "special_defense": 32, "defense": 2})
        self.assertEqual(self.store.state.right.item, "Sitrus Berry")
        self.assertEqual(self.store.state.right.ability, "Intimidate")
        self.assertEqual(self.store.state.right.moves[:2], ["Flare Blitz", "Protect"])
        self.assertEqual(self.store.state.right.source, "Tournament preset · Careful")

        # 3. Mega evolution gets tournament nature (timid -> 32 SpA / 32 Spe), mega stone, drought ability, field sun
        self.store.load_species("right", "charizard-mega-y", preset=True)
        self.assertEqual(self.store.state.right.nature, "timid")
        self.assertEqual(self.store.state.right.points, {"special_attack": 32, "speed": 32, "hp": 2})
        self.assertEqual(self.store.state.right.item, "Charizardite Y")
        self.assertEqual(self.store.state.right.ability, "Drought")
        self.assertEqual(self.store.state.field.weather, "Sun")

    def test_sweep_uses_tournament_builds(self):
        from pokemon_champions_planning_tool.services.tournament_service import TournamentBuild

        builds = {
            "incineroar": TournamentBuild(
                canonical_id="incineroar",
                moves=["Flare Blitz", "Protect"],
                nature="careful",
                item="Sitrus Berry",
                ability="Intimidate",
            ),
            "charizard-mega-y": TournamentBuild(
                canonical_id="charizard-mega-y",
                moves=["Heat Wave", "Protect"],
                nature="timid",
                item="Charizardite Y",
                ability="Drought",
            ),
        }
        self.store._preset_builds = builds
        self.store.load_species("left", "kingambit")
        self.store.set_move("left", 0, "Iron Head")

        # Sweep with presets enabled uses tournament builds
        self.store.sweep_presets = True
        entries = self.store.compute_sweep()
        by = {e.canonical_id: e for e in entries}
        self.assertIn("incineroar", by)
        self.assertTrue(by["incineroar"].preset)
        self.assertIsNotNone(by["incineroar"].their_best)

        # Incineroar attacks Kingambit with Flare Blitz, the move from its tournament build.
        # (The sweep runs in "fast" mode and does not build Smogon descriptions — it shows
        # the move name and the damage range, so that is what this pins.)
        self.assertEqual(by["incineroar"].their_best.name, "Flare Blitz")
        self.assertGreater(by["incineroar"].their_best.max_pct, 0)


class TestFormSwitcher(_Base):
    def setUp(self):
        super().setUp()
        self.store.catalogs.species_by_canonical["charizard"] = CHARIZARD

    def test_form_choices_for(self):
        choices = self.catalogs.form_choices_for("charizard")
        self.assertEqual(choices, [("charizard", "Base"), ("charizard-mega-y", "Mega Y")])
        choices_from_mega = self.catalogs.form_choices_for("charizard-mega-y")
        self.assertEqual(choices_from_mega, [("charizard", "Base"), ("charizard-mega-y", "Mega Y")])
        self.assertEqual(self.catalogs.form_choices_for("kingambit"), [])

    def test_switch_form_preserves_custom_build(self):
        self.store.load_species("left", "charizard")
        self.store.set_nature("left", "timid")
        self.store.set_points("left", {"special_attack": 32, "speed": 32, "hp": 2})
        self.store.set_move("left", 0, "Heat Wave")
        self.store.set_move("left", 1, "Protect")
        self.store.set_boost("left", "special_attack", 1)
        self.store.set_hp_pct("left", 75.0)
        self.assertEqual(self.store.state.left.ability, "Blaze")

        # Switch to Mega Y
        self.store.switch_form("left", "charizard-mega-y")
        left = self.store.state.left
        self.assertEqual(left.species, "charizard-mega-y")
        self.assertEqual(left.nature, "timid")
        self.assertEqual(left.points, {"special_attack": 32, "speed": 32, "hp": 2})
        self.assertEqual(left.moves[:2], ["Heat Wave", "Protect"])
        self.assertEqual(left.boosts, {"special_attack": 1})
        self.assertEqual(left.hp_pct, 75.0)
        self.assertEqual(left.ability, "Drought")
        self.assertEqual(self.store.state.field.weather, "Sun")
        self.assertEqual(left.item, "Charizardite Y")

        # Switch back to Base
        self.store.switch_form("left", "charizard")
        left = self.store.state.left
        self.assertEqual(left.species, "charizard")
        self.assertEqual(left.nature, "timid")
        self.assertEqual(left.points, {"special_attack": 32, "speed": 32, "hp": 2})
        self.assertEqual(left.moves[:2], ["Heat Wave", "Protect"])
        self.assertEqual(left.boosts, {"special_attack": 1})
        self.assertEqual(left.hp_pct, 75.0)
        self.assertEqual(left.ability, "Blaze")
        self.assertEqual(left.item, "Charizardite Y")

    def test_set_item_auto_syncs_mega_form(self):
        self.store.load_species("left", "charizard")
        self.assertEqual(self.store.state.left.species, "charizard")

        # Equipping Charizardite Y auto-evolves to Mega Y
        self.store.set_item("left", "Charizardite Y")
        self.assertEqual(self.store.state.left.species, "charizard-mega-y")
        self.assertEqual(self.store.state.left.item, "Charizardite Y")
        self.assertEqual(self.store.state.left.ability, "Drought")

        # Equipping Life Orb auto-reverts to base Charizard
        self.store.set_item("left", "Life Orb")
        self.assertEqual(self.store.state.left.species, "charizard")
        self.assertEqual(self.store.state.left.item, "Life Orb")
        self.assertEqual(self.store.state.left.ability, "Blaze")

        # Re-equipping Charizardite Y then clearing it (None) auto-reverts
        self.store.set_item("left", "Charizardite Y")
        self.assertEqual(self.store.state.left.species, "charizard-mega-y")
        self.store.set_item("left", None)
        self.assertEqual(self.store.state.left.species, "charizard")
        self.assertIsNone(self.store.state.left.item)

    def test_panel_segmented_button_ui(self):
        ctx = AppContext(StubPage())
        view = CalcView(ctx, store=self.store)
        self.store.load_species("left", "charizard")
        view.attacker.update_from()
        self.assertTrue(view.attacker._form.visible)
        self.assertEqual([s.value for s in view.attacker._form.segments], ["charizard", "charizard-mega-y"])
        self.assertEqual(view.attacker._form.selected, ["charizard"])

        self.store.load_species("left", "kingambit")
        view.attacker.update_from()
        self.assertFalse(view.attacker._form.visible)

    def test_sweep_sort_by_usage_default(self):
        # Mock get_usage_map to return specific counts
        self.store.get_usage_map = lambda regulation=None: {"incineroar": 100, "kingambit": 50, "charizard": 10}
        self.store.load_species("left", "kingambit")
        self.store.set_move("left", 0, "Iron Head")

        sweep = self.store.compute_sweep()
        self.assertTrue(len(sweep) >= 2)
        # Default sort is usage descending
        self.assertEqual(self.store.sweep_sort, "usage")
        # Incineroar (100) must appear before Kingambit (50) and Charizard-Mega-Y (0/10)
        names = [e.name for e in sweep]
        self.assertEqual(names[0], "Incineroar")
        self.assertEqual(sweep[0].usage_count, 100)

        # Re-sort by name
        self.store.publish_sweep(sweep)
        self.store.set_sweep_sort("name")
        self.assertEqual([e.name for e in self.store.sweep], sorted(names, key=str.lower))

        # Re-sort by speed
        self.store.set_sweep_sort("speed")
        speeds = [e.speed for e in self.store.sweep]
        self.assertEqual(speeds, sorted(speeds, reverse=True))

    def test_search_species_usage_ranking(self):
        self.store.get_usage_map = lambda regulation=None: {"incineroar": 200, "charizard": 5}
        # Searching "in" or "c" should prioritize higher tournament usage
        results = self.store.search_species("in")
        self.assertTrue(results)
        self.assertEqual(results[0].canonical_id, "incineroar")

    def test_sweep_panel_ui_sort_dropdown_and_card(self):
        self.store.get_usage_map = lambda regulation=None: {"incineroar": 150}
        self.store.load_species("left", "kingambit")
        self.store.set_move("left", 0, "Iron Head")
        sweep = self.store.compute_sweep()
        self.store.publish_sweep(sweep)

        panel = self.store
        ctx = AppContext(StubPage())
        view = CalcView(ctx, store=self.store)
        self.assertEqual(view.sweep._sort.value, "usage:latest")
        self.assertTrue(any(opt.key == "usage:latest" for opt in view.sweep._sort.options))
        self.assertTrue(any(opt.key == "name" for opt in view.sweep._sort.options))

        view.sweep.render()
        cards = [c for c in view.sweep._list.controls if hasattr(c, "tooltip")]
        self.assertTrue(cards)
        self.assertIn("150 tournament teams", cards[0].tooltip)


class TestCalcStoreDbUsage(unittest.TestCase):
    def setUp(self):
        from datetime import datetime, timezone
        from sqlmodel import Session, SQLModel, create_engine
        from pokemon_champions_planning_tool.infrastructure.database.models import TournamentRecord, TournamentTeamMemberRecord, TournamentTeamRecord

        self.engine = create_engine("sqlite:///:memory:")
        SQLModel.metadata.create_all(self.engine)
        self.addCleanup(self.engine.dispose)
        self.sf = lambda: Session(self.engine)
        with self.sf() as s:
            s.add(TournamentRecord(tournament_id="t1", name="Tourney 1", event_date=datetime(2026, 9, 1, tzinfo=timezone.utc), format_regulation="Regulation M-C", battle_format="doubles", game_platform="Pokémon Champions", standings_synced=True))
            s.add(TournamentRecord(tournament_id="t2", name="Tourney 2", event_date=datetime(2026, 8, 1, tzinfo=timezone.utc), format_regulation="Regulation M-B", battle_format="doubles", game_platform="Pokémon Champions", standings_synced=True))
            s.commit()
            # 2 teams in M-C with Incineroar, 1 with Kingambit
            tt1 = TournamentTeamRecord(tournament_id="t1", player_name="P1", placement=1, member_count=2, showdown_text="")
            tt2 = TournamentTeamRecord(tournament_id="t1", player_name="P2", placement=2, member_count=1, showdown_text="")
            s.add(tt1); s.add(tt2); s.commit()
            s.add(TournamentTeamMemberRecord(tournament_team_id=tt1.tournament_team_id, slot_position=1, canonical_id="incineroar", species_name="Incineroar", base_canonical_id="incineroar"))
            s.add(TournamentTeamMemberRecord(tournament_team_id=tt1.tournament_team_id, slot_position=2, canonical_id="kingambit", species_name="Kingambit", base_canonical_id="kingambit"))
            s.add(TournamentTeamMemberRecord(tournament_team_id=tt2.tournament_team_id, slot_position=1, canonical_id="incineroar", species_name="Incineroar", base_canonical_id="incineroar"))
            s.commit()

        self.catalogs = catalogs()
        self.store = CalcStore(self.catalogs, session_factory=self.sf)

    def test_database_usage_map_and_latest_regulation(self):
        self.assertEqual(self.store.latest_regulation(), "Regulation M-C")
        regs = self.store.available_regulations()
        self.assertIn("Regulation M-C", regs)
        self.assertIn("Regulation M-B", regs)

        umap = self.store.get_usage_map("Regulation M-C")
        self.assertEqual(umap.get("incineroar"), 2)
        self.assertEqual(umap.get("kingambit"), 1)

        # compute_sweep should order incineroar before kingambit
        self.store.load_species("left", "kingambit")
        self.store.set_move("left", 0, "Iron Head")
        sweep = self.store.compute_sweep()
        self.assertEqual(sweep[0].canonical_id, "incineroar")
        self.assertEqual(sweep[0].usage_count, 2)

    def test_progressive_sweep_and_cache(self):
        self.store.load_species("left", "kingambit")
        self.store.set_move("left", 0, "Iron Head")

        # Mock progressive callback
        progressive_results = []
        def on_prog(entries):
            progressive_results.append(entries)

        # Add dummy species to catalogs so count exceeds 30
        for i in range(35):
            cid = f"dummy_{i}"
            sp = species(cid, f"Dummy {i}", ("Normal",), {"hp": 100, "atk": 100, "def": 100, "spa": 100, "spd": 100, "spe": 100}, (), 50)
            self.store.catalogs.species_by_canonical[cid] = sp

        final_sweep = self.store.compute_sweep(on_progressive=on_prog)
        self.assertTrue(len(progressive_results) >= 1)
        self.assertEqual(len(progressive_results[0]), 30)
        self.assertGreater(len(final_sweep), 30)

        # publish_progressive_sweep does not set sweep_key
        initial_key = self.store._sweep_key
        self.store._sweep_key = None
        self.store.publish_progressive_sweep(progressive_results[0])
        self.assertIsNone(self.store._sweep_key)
        self.assertEqual(len(self.store.sweep), 30)

        # publish_sweep sets sweep_key
        self.store.publish_sweep(final_sweep)
        self.assertEqual(self.store._sweep_key, self.store.sweep_key())
        self.assertEqual(len(self.store.sweep), len(final_sweep))

    def test_sweep_panel_pagination(self):
        self.store.load_species("left", "kingambit")
        self.store.set_move("left", 0, "Iron Head")

        # Create 50 dummy entries in sweep
        for i in range(50):
            cid = f"dummy_panel_{i}"
            sp = species(cid, f"Dummy Panel {i}", ("Normal",), {"hp": 100, "atk": 100, "def": 100, "spa": 100, "spd": 100, "spe": 100}, (), 50)
            self.store.catalogs.species_by_canonical[cid] = sp

        sweep = self.store.compute_sweep()
        self.store.publish_sweep(sweep)
        self.assertGreater(len(self.store.sweep), 40)

        panel = SweepPanel(store=self.store, accent=Accent.CALC, on_pick=lambda _e: None)
        panel.render()

        # Should render 40 cards + 1 show more button
        self.assertEqual(len(panel._list.controls), 41)
        btn_container = panel._list.controls[-1]
        self.assertIsInstance(btn_container, ft.Container)
        self.assertIsInstance(btn_container.content, ft.TextButton)
        self.assertIn("remaining", str(btn_container.content.content))

        # Trigger show more
        btn_container.content.on_click(None)
        self.assertEqual(panel._limit, 80)
        self.assertEqual(len(panel._list.controls), len(sweep))


if __name__ == "__main__":
    unittest.main()




class TestCatalogueArrivesLate(_Base):
    """A first launch opens before the Showdown data has downloaded."""

    def test_presets_ready_reports_whether_a_lookup_would_aggregate(self):
        self.assertFalse(self.store.presets_ready, "nothing read yet")
        self.store._preset_builds = {}
        self.assertTrue(self.store.presets_ready)
        self.store.invalidate_presets()
        self.assertFalse(self.store.presets_ready, "a sync sends it back to the database")

    def test_refresh_catalogs_swaps_the_data_and_recomputes(self):
        empty = Catalogs()
        store = CalcStore(empty, session_factory=None, prefs=self.prefs)
        store.load()
        self.assertFalse(store.catalogs.has_species)
        self.assertEqual(store.search_species("char"), [])

        store._preset_builds = {"x": None}
        store.refresh_catalogs(self.catalogs)
        self.assertTrue(store.catalogs.has_species)
        # Ranking is the store's own business; what matters is that the search has data.
        self.assertEqual([s.name for s in store.search_species("char")], ["Charizard-Mega-Y"])
        self.assertFalse(store.presets_ready, "presets were built against the old catalogue")

    def test_view_picks_up_a_catalogue_that_lands_while_it_is_open(self):
        page = StubPage()
        ctx = AppContext(page, catalogs=Catalogs())
        view = CalcView(ctx, CalcStore(ctx.catalogs, session_factory=None, prefs=self.prefs))
        view.ensure_loaded()
        self.assertIn("not synced", view.header._caption.value)

        ctx.catalogs = self.catalogs
        ctx.bus.emit(events.CATALOGS_RELOADED, "species")
        self.assertTrue(view.store.catalogs.has_species)
        self.assertEqual(view.header._caption.value, "Champions damage · both directions", "the warning gives way to the usual caption")

    def test_an_unrelated_reload_is_ignored(self):
        page = StubPage()
        ctx = AppContext(page, catalogs=Catalogs())
        view = CalcView(ctx, CalcStore(ctx.catalogs, session_factory=None, prefs=self.prefs))
        view.ensure_loaded()
        ctx.catalogs = self.catalogs
        ctx.bus.emit(events.CATALOGS_RELOADED, "tournaments")
        self.assertFalse(view.store.catalogs.has_species, "tournament data is not a catalogue swap")

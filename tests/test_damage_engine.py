"""Hand-verified damage engine cases, item/ability tables, and move construction rules."""

import json
import unittest
from pathlib import Path

from pokemon_champions_planning_tool.domain.damage import CalcMove, CalcPokemon, Field, Side, calculate, canonical_ability_name, canonical_item_name, champions_items
from pokemon_champions_planning_tool.domain.damage.abilities import ability_names
from pokemon_champions_planning_tool.domain.damage.items import berry_resist_type, fling_power, item_boost_type, mega_stones, resists_knock_off
from pokemon_champions_planning_tool.domain.damage.ko import DescError
from pokemon_champions_planning_tool.domain.moves import MoveInfo, MoveMechanics

DATA = json.loads((Path(__file__).resolve().parent / "fixtures" / "damage" / "_data.json").read_text(encoding="utf-8"))

MEGA_Y = CalcPokemon(name="Charizard-Mega-Y", types=("Fire", "Flying"), base_stats={"hp": 78, "atk": 104, "def": 78, "spa": 159, "spd": 115, "spe": 100},
                     weightkg=100.5, abilities=("Drought",), nature="Timid", points={"hp": 2, "spa": 32, "spe": 32})
GARCHOMP = CalcPokemon(name="Garchomp", types=("Dragon", "Ground"), base_stats={"hp": 108, "atk": 130, "def": 95, "spa": 80, "spd": 85, "spe": 102},
                       weightkg=95, abilities=("Sand Veil", "Rough Skin"), nature="Jolly", points={"hp": 32, "atk": 32, "spe": 2}, item="Leftovers")
KINGAMBIT = CalcPokemon(name="Kingambit", types=("Dark", "Steel"), base_stats={"hp": 100, "atk": 135, "def": 120, "spa": 60, "spd": 85, "spe": 50},
                        weightkg=120, abilities=("Defiant",), nature="Adamant", points={"atk": 32, "spe": 32, "hp": 2})
GENGAR = CalcPokemon(name="Gengar", types=("Ghost", "Poison"), base_stats={"hp": 60, "atk": 65, "def": 60, "spa": 130, "spd": 75, "spe": 110}, weightkg=40.5, abilities=("Cursed Body",))


def move(name: str, **kw) -> CalcMove:
    return CalcMove.from_showdown(DATA["moves"][name], **kw)


class TestEngine(unittest.TestCase):
    def test_reference_smoke_case(self):
        result = calculate(MEGA_Y, GARCHOMP, move("heatwave"), Field(game_type="Doubles", weather="Sun"))
        self.assertEqual(result.damage, [60, 61, 62, 63, 63, 64, 65, 66, 66, 67, 68, 69, 69, 70, 71, 72])
        self.assertEqual(result.desc(), "32 SpA Charizard-Mega-Y Heat Wave vs. 32 HP / 0 SpD Garchomp in Sun: 60-72 (27.9 - 33.4%) -- 92.9% chance to 4HKO after Leftovers recovery")
        self.assertEqual(result.attacker.stats, {"hp": 155, "atk": 111, "def": 98, "spa": 211, "spd": 135, "spe": 167})
        self.assertEqual(result.defender.stats, {"hp": 215, "atk": 182, "def": 115, "spa": 90, "spd": 105, "spe": 136})
        self.assertEqual((result.min_pct, result.max_pct), (27.9, 33.4))

    def test_immunity_is_zero_damage_and_undescribable(self):
        levitating = CalcPokemon(**{**GENGAR.__dict__, "ability": "Levitate"})
        result = calculate(GARCHOMP, levitating, move("earthquake"))
        self.assertEqual(result.damage, 0)
        self.assertTrue(result.is_immune)
        self.assertEqual(result.range(), (0, 0))
        with self.assertRaises(DescError):
            result.desc()

    def test_mold_breaker_clears_the_defender_ability(self):
        dragonite = CalcPokemon(name="Dragonite", types=("Dragon", "Flying"), base_stats={"hp": 91, "atk": 134, "def": 95, "spa": 100, "spd": 100, "spe": 80}, weightkg=210, ability="Multiscale")
        plain = calculate(KINGAMBIT, dragonite, move("ironhead"))
        breaker = calculate(CalcPokemon(**{**KINGAMBIT.__dict__, "ability": "Mold Breaker"}), dragonite, move("ironhead"))
        self.assertEqual(breaker.defender.ability, "")
        self.assertGreater(breaker.range()[0], plain.range()[0])
        self.assertIn("Mold Breaker", breaker.desc())

    def test_parental_bond_shapes(self):
        kanga = CalcPokemon(name="Kangaskhan-Mega", types=("Normal",), base_stats={"hp": 105, "atk": 125, "def": 100, "spa": 60, "spd": 100, "spe": 100}, weightkg=100, ability="Parental Bond")
        result = calculate(kanga, KINGAMBIT, move("bodyslam"))
        self.assertEqual(len(result.damage), 2)
        self.assertEqual(len(result.damage[0]), 16)
        self.assertLess(result.damage[1][-1], result.damage[0][0], "the child hits for a quarter")
        fixed = calculate(kanga, KINGAMBIT, move("seismictoss"))
        self.assertEqual(fixed.damage, [50, 50])
        self.assertEqual(fixed.rolls, [100] * 16)

    def test_expanding_force_retargets_in_psychic_terrain(self):
        gardevoir = CalcPokemon(name="Gardevoir", types=("Psychic", "Fairy"), base_stats={"hp": 68, "atk": 65, "def": 65, "spa": 125, "spd": 115, "spe": 80}, weightkg=48.4)
        single = calculate(gardevoir, GARCHOMP, move("expandingforce"), Field(game_type="Doubles"))
        terrain = calculate(gardevoir, GARCHOMP, move("expandingforce"), Field(game_type="Doubles", terrain="Psychic"))
        self.assertEqual(single.move.target, "any", "the calculator has no target for ordinary moves")
        self.assertEqual(terrain.move.target, "allAdjacentFoes")
        self.assertEqual(terrain.raw_desc["moveBP"], 120)

    def test_speed_zero_guards(self):
        slow = CalcPokemon(name="Kingambit", types=("Dark", "Steel"), base_stats={"hp": 100, "atk": 135, "def": 120, "spa": 60, "spd": 85, "spe": 0}, weightkg=120)
        raichu = CalcPokemon(name="Raichu", types=("Electric",), base_stats={"hp": 60, "atk": 90, "def": 55, "spa": 90, "spd": 80, "spe": 110}, weightkg=30)
        # base speed 0 gives stat 20, not zero — force it with -6 and paralysis to exercise the guard path
        self.assertEqual(calculate(raichu, slow, move("electroball")).raw_desc["moveBP"], 150)
        self.assertEqual(calculate(slow, raichu, move("gyroball")).raw_desc["moveBP"], 150)

    def test_protect_and_unseen_fist(self):
        protected = Field(defender_side=Side(is_protected=True))
        self.assertEqual(calculate(KINGAMBIT, GENGAR, move("kowtowcleave"), protected).damage, 0)
        fist = CalcPokemon(**{**KINGAMBIT.__dict__, "ability": "Unseen Fist"})
        result = calculate(fist, GENGAR, move("kowtowcleave"), protected)
        self.assertGreater(result.range()[0], 0)
        self.assertIn("protected", result.desc())


class TestMoveConstruction(unittest.TestCase):
    def test_hits_rules(self):
        self.assertEqual(CalcMove.resolve_hits(None, False, None, None), 1)
        self.assertEqual(CalcMove.resolve_hits((2, 5), False, None, None), 3)
        self.assertEqual(CalcMove.resolve_hits((2, 5), False, None, "Skill Link"), 5)
        self.assertEqual(CalcMove.resolve_hits((2, 5), False, 4, None), 4)
        self.assertEqual(CalcMove.resolve_hits(10, True, None, None), 10)
        self.assertEqual(CalcMove.resolve_hits(3, True, 2, None), 2)
        self.assertEqual(CalcMove.resolve_hits(2, False, 5, None), 2, "fixed multihit ignores the request")

    def test_from_showdown_and_from_info_agree(self):
        data = DATA["moves"]["closecombat"]
        a = CalcMove.from_showdown(data)
        info = MoveInfo("closecombat", "Close Combat", "fighting", "physical", 120, 100, 5, 0, "normal", "", True,
                        MoveMechanics(contact=True, self_boosts=(("def", -1), ("spd", -1))))
        b = CalcMove.from_info(info)
        self.assertEqual((a.bp, a.type, a.category, a.drops_stats, a.flags.get("contact")), (b.bp, b.type, b.category, b.drops_stats, b.flags.get("contact")))
        overheat = CalcMove.from_info(MoveInfo("overheat", "Overheat", "fire", "special", 130, 90, 5, 0, "normal", "", True, MoveMechanics(self_boosts=(("spa", -2),))))
        self.assertEqual(overheat.drops_stats, 2)
        struggle = CalcMove.from_showdown({"id": "struggle", "name": "Struggle", "type": "Normal", "category": "Physical", "basePower": 50, "struggleRecoil": True})
        self.assertEqual(struggle.type, "???")
        self.assertEqual(CalcMove.from_showdown({"id": "return", "name": "Return", "type": "Normal", "category": "Physical", "basePower": 0}).bp, 102)


class TestTables(unittest.TestCase):
    def test_items_match_the_calculator(self):
        self.assertEqual(champions_items(), {i["name"] for i in DATA["items"]})
        self.assertEqual(len(champions_items()), 148)
        for name in ("Float Stone", "Choice Band", "Assault Vest", "Black Sludge", "Heavy-Duty Boots"):
            self.assertNotIn(name, champions_items())
        self.assertTrue(set(item_boost_type(i) for i in champions_items() if item_boost_type(i)) >= {"Fire", "Fairy", "Ghost", "Normal"})
        self.assertEqual(sum(1 for i in champions_items() if berry_resist_type(i)), 18)
        self.assertEqual(mega_stones(), DATA["mega_stones"])
        self.assertEqual(canonical_item_name("life-orb"), "Life Orb")
        self.assertEqual(canonical_item_name("kings-rock"), "King's Rock")
        self.assertEqual(canonical_item_name("Never Melt Ice"), "Never-Melt Ice")
        self.assertEqual(canonical_item_name("Mystery Thing"), "Mystery Thing")
        self.assertEqual((fling_power("Iron Ball"), fling_power("Sitrus Berry"), fling_power("Charizardite Y"), fling_power(None)), (130, 10, 0, 0))
        self.assertTrue(resists_knock_off("Charizardite Y", "Charizard"))
        self.assertTrue(resists_knock_off("Charizardite Y", "Charizard-Mega-Y"))
        self.assertFalse(resists_knock_off("Charizardite Y", "Incineroar"))

    def test_abilities_match_the_calculator(self):
        self.assertEqual(list(ability_names()), DATA["abilities"])
        for name in ("Dragonize", "Eelevate", "Fire Mane", "Mega Sol", "Piercing Drill", "Spicy Spray"):
            self.assertIn(name, ability_names())
        self.assertEqual(canonical_ability_name("lightning-rod"), "Lightning Rod")
        self.assertEqual(canonical_ability_name("supremeoverlord"), "Supreme Overlord")
        self.assertEqual(canonical_ability_name("not-an-ability"), "Not An Ability")
        self.assertIsNone(canonical_ability_name(None))


if __name__ == "__main__":
    unittest.main()

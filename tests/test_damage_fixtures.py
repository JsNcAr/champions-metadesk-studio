"""Golden-fixture replay: every scenario generated from the Smogon calculator's Champions
module must match the Python port roll for roll, in its description and in its KO text."""

from __future__ import annotations

import json
import time
import unittest
from pathlib import Path

from pokemon_champions_planning_tool.domain.damage import PORTED_CALC_COMMIT, CalcMove, CalcPokemon, Field, Side, calculate
from pokemon_champions_planning_tool.domain.damage.ko import DescError

FIXTURES = Path(__file__).resolve().parent / "fixtures" / "damage"


def load_cases() -> list[dict]:
    cases: list[dict] = []
    for path in sorted(FIXTURES.glob("*.json")):
        if path.name.startswith("_"):
            continue
        data = json.loads(path.read_text(encoding="utf-8"))
        assert data["meta"]["calc_commit"] == PORTED_CALC_COMMIT, f"{path.name} was generated from another calculator commit"
        cases.extend(data["cases"])
    return cases


def _side(spec: dict) -> Side:
    return Side(spikes=spec["spikes"], is_sr=spec["isSR"], is_reflect=spec["isReflect"], is_light_screen=spec["isLightScreen"], is_protected=spec["isProtected"],
                is_seeded=spec["isSeeded"], is_nightmared=spec["isNightmared"], is_salt_cured=spec["isSaltCured"], is_charge=spec["isCharge"],
                is_tailwind=spec["isTailwind"], is_helping_hand=spec["isHelpingHand"], is_power_trick=spec["isPowerTrick"], is_friend_guard=spec["isFriendGuard"],
                is_aurora_veil=spec["isAuroraVeil"], is_switching=spec["isSwitching"])


def build(case: dict) -> tuple[CalcPokemon, CalcPokemon, CalcMove, Field]:
    def mon(spec: dict, data: dict) -> CalcPokemon:
        abilities = data.get("abilities") or {}
        return CalcPokemon(
            name=data["name"], types=tuple(data["types"]), base_stats=data["baseStats"], weightkg=data["weightkg"],
            ability=spec["ability"], abilities=tuple(abilities[k] for k in ("0", "1", "H") if k in abilities), ability_on=spec["abilityOn"],
            item=spec["item"], nature=spec["nature"], points=spec["points"], boosts=spec["boosts"], cur_hp=spec["curHP"], status=spec["status"],
            toxic_counter=spec["toxicCounter"], allies_fainted=spec["alliesFainted"], gender=spec["gender"] or data.get("gender"),
        )

    attacker = mon(case["attacker"], case["data"]["attacker"])
    defender = mon(case["defender"], case["data"]["defender"])
    m = case["move"]
    attacker_ability = attacker.ability or (attacker.abilities[0] if attacker.abilities else None)
    move = CalcMove.from_showdown(case["data"]["move"], is_crit=m["isCrit"], hits=m["hits"], times_used=m["timesUsed"],
                                  times_used_with_metronome=m["timesUsedWithMetronome"], attacker_ability=attacker_ability)
    f = case["field"]
    field = Field(game_type=f["gameType"], weather=f["weather"], terrain=f["terrain"], is_gravity=f["isGravity"], is_magic_room=f["isMagicRoom"],
                  is_wonder_room=f["isWonderRoom"], is_fairy_aura=f["isFairyAura"], is_dark_aura=f["isDarkAura"],
                  attacker_side=_side(f["attackerSide"]), defender_side=_side(f["defenderSide"]))
    return attacker, defender, move, field


def _strip(d: dict) -> dict:
    return {k: v for k, v in d.items() if v is not None}


class TestDamageFixtures(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.cases = load_cases()

    def test_fixture_count(self):
        self.assertGreater(len(self.cases), 900)

    def test_replay(self):
        for case in self.cases:
            with self.subTest(id=case["id"]):
                attacker, defender, move, field = build(case)
                result = calculate(attacker, defender, move, field)
                exp = case["expected"]
                self.assertEqual(result.damage, exp["damage"], "damage")
                self.assertEqual(result.attacker.raw_stats, exp["attackerRaw"], "attacker raw stats")
                self.assertEqual(result.defender.raw_stats, exp["defenderRaw"], "defender raw stats")
                self.assertEqual(result.attacker.stats, exp["attackerStats"], "attacker stats")
                self.assertEqual(result.defender.stats, exp["defenderStats"], "defender stats")
                self.assertEqual(result.attacker.boosts, exp["attackerBoosts"], "attacker boosts")
                self.assertEqual(result.defender.boosts, exp["defenderBoosts"], "defender boosts")
                self.assertEqual(result.attacker.ability or None, exp["attackerAbility"] or None, "attacker ability")
                self.assertEqual(result.defender.ability or None, exp["defenderAbility"] or None, "defender ability")
                self.assertEqual(result.move.type, exp["moveType"], "move type")
                self.assertEqual(result.move.bp, exp["moveBp"], "move bp")
                self.assertEqual(result.move.category, exp["moveCategory"], "move category")
                self.assertEqual(result.move.target, exp["moveTarget"], "move target")
                self.assertEqual(result.move.hits, exp["moveHits"], "move hits")
                self.assertEqual(_strip(result.raw_desc), _strip(exp["rawDesc"]), "raw description")
                for name, getter in (("desc", result.desc), ("moveDesc", result.move_desc)):
                    expected = exp[name]
                    if isinstance(expected, dict) and "__error__" in expected:
                        with self.assertRaises(DescError, msg=name):
                            getter()
                    else:
                        self.assertEqual(getter(), expected, name)
                expected_ko = exp["kochance"]
                if isinstance(expected_ko, dict) and "__error__" in expected_ko:
                    with self.assertRaises(DescError, msg="kochance"):
                        result.ko_chance()
                else:
                    got = result.ko_chance()
                    self.assertEqual(got.text, expected_ko["text"], "ko text")
                    self.assertEqual(got.n, expected_ko["n"], "ko n")
                    if "chance" in expected_ko:
                        self.assertAlmostEqual(got.chance, expected_ko["chance"], places=9, msg="ko chance")
                    else:
                        self.assertIsNone(got.chance, "ko chance")
                recoil, recoil_text = result.recoil()
                self.assertEqual(recoil_text, exp["recoil"]["text"], "recoil text")
                self.assertEqual(recoil, exp["recoil"]["recoil"], "recoil")
                recovery, recovery_text = result.recovery()
                self.assertEqual(recovery_text, exp["recovery"]["text"], "recovery text")
                self.assertEqual(recovery, exp["recovery"]["recovery"], "recovery")

    def test_replay_is_fast(self):
        start = time.perf_counter()
        for case in self.cases:
            attacker, defender, move, field = build(case)
            result = calculate(attacker, defender, move, field)
            try:
                result.desc()
            except DescError:
                pass
        elapsed = time.perf_counter() - start
        self.assertLess(elapsed, 4.0, f"{len(self.cases)} cases took {elapsed:.2f}s")


if __name__ == "__main__":
    unittest.main()

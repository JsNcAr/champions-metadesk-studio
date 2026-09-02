"""KO chance, hazards and end-of-turn residuals — port of the relevant parts of ``desc.ts``."""

from __future__ import annotations

import math
from dataclasses import dataclass

from ..type_chart import effectiveness as chart_effectiveness
from .jsmath import js_round
from .state import FieldState, Mon, MoveState, SideState
from .util import is_grounded

TRAPPING = ("Bind", "Clamp", "Fire Spin", "Infestation", "Magma Storm", "Sand Tomb", "Thunder Cage", "Whirlpool", "Wrap", "G-Max Sandblast", "G-Max Centiferno")


class DescError(ValueError):
    """The reference raises for damage it cannot describe (all-zero rolls, NaN)."""


@dataclass(frozen=True)
class KOChance:
    chance: float | None
    n: int
    text: str

    def to_json(self) -> dict:
        out: dict = {"n": self.n, "text": self.text}
        if self.chance is not None:
            out["chance"] = self.chance
        return out


def combine(damage) -> tuple[list[int], bool]:
    """Flatten a damage matrix into one sorted distribution (approximate past three hits)."""
    if isinstance(damage, int):
        return [damage], False
    if len(damage) >= 16 and isinstance(damage[0], int):
        return list(damage), False
    if isinstance(damage[0], int) and isinstance(damage[1], int):
        return [damage[0] + damage[1]], False

    def reduce(dist: list[int], scale: int) -> list[int]:
        new_length = len(dist) // scale
        reduced = [0] * new_length
        reduced[0] = dist[0]
        reduced[new_length - 1] = dist[-1]
        for i in range(1, new_length - 1):
            reduced[i] = dist[js_round(i * scale + scale / 2)]
        return reduced

    def combine_two(d1: list[int], d2: list[int]) -> list[int]:
        return sorted(a + b for a in d1 for b in d2)

    combined = [0]
    num_rolls = len(damage[0])
    num_accuracy = 3 if num_rolls == 16 and len(damage) == 3 else 2
    approximate = False
    for i, dist in enumerate(damage):
        combined = combine_two(combined, list(dist))
        if i >= num_accuracy:
            combined = reduce(combined, len(dist))
            approximate = True
    return combined, approximate


def get_hazards(defender: Mon, side: SideState) -> tuple[int, list[str]]:
    damage = 0
    texts: list[str] = []
    if defender.has_item("Heavy-Duty Boots"):
        return damage, texts
    if side.is_sr and not defender.has_ability("Magic Guard", "Mountaineer"):
        eff = chart_effectiveness("rock", defender.types[0].lower()) * (chart_effectiveness("rock", defender.types[1].lower()) if len(defender.types) > 1 else 1)
        damage += max(math.floor((eff * defender.max_hp()) / 8), 1)
        texts.append("Stealth Rock")
    if not defender.has_type("Flying") and not defender.has_ability("Magic Guard", "Levitate", "Eelevate") and not defender.has_item("Air Balloon"):
        if side.spikes == 1:
            damage += math.floor(defender.max_hp() / 8)
            texts.append("1 layer of Spikes")
        elif side.spikes == 2:
            damage += math.floor(defender.max_hp() / 6)
            texts.append("2 layers of Spikes")
        elif side.spikes == 3:
            damage += math.floor(defender.max_hp() / 4)
            texts.append("3 layers of Spikes")
    return damage, texts


def get_end_of_turn(attacker: Mon, defender: Mon, move: MoveState, field: FieldState) -> tuple[int, list[str]]:
    damage = 0
    texts: list[str] = []
    lose_item = move.named("Knock Off") and not defender.has_ability("Sticky Hold")
    heal_block = move.named("Psychic Noise") and not (attacker.has_ability("Sheer Force") or defender.has_item("Covert Cloak") or defender.has_ability("Shield Dust", "Aroma Veil"))
    max_hp = defender.max_hp()

    if field.has_weather("Sun", "Harsh Sunshine"):
        if defender.has_ability("Dry Skin", "Solar Power"):
            damage -= math.floor(max_hp / 8)
            texts.append(f"{defender.ability} damage")
    elif field.has_weather("Rain", "Heavy Rain") and not heal_block:
        if defender.has_ability("Dry Skin"):
            damage += math.floor(max_hp / 8)
            texts.append("Dry Skin recovery")
        elif defender.has_ability("Rain Dish"):
            damage += math.floor(max_hp / 16)
            texts.append("Rain Dish recovery")
    elif field.has_weather("Sand"):
        if (not defender.has_type("Rock", "Ground", "Steel") and not defender.has_ability("Magic Guard", "Overcoat", "Sand Force", "Sand Rush", "Sand Veil")
                and not defender.has_item("Safety Goggles")):
            damage -= math.floor(max_hp / 16)
            texts.append("sandstorm damage")
    elif field.has_weather("Hail", "Snow"):
        if defender.has_ability("Ice Body") and not heal_block:
            damage += math.floor(max_hp / 16)
            texts.append("Ice Body recovery")
        elif (not defender.has_type("Ice") and not defender.has_ability("Magic Guard", "Overcoat", "Snow Cloak") and not defender.has_item("Safety Goggles")
              and field.has_weather("Hail")):
            damage -= math.floor(max_hp / 16)
            texts.append("hail damage")

    if defender.has_item("Leftovers") and not lose_item and not heal_block:
        damage += math.floor(max_hp / 16)
        texts.append("Leftovers recovery")
    elif defender.has_item("Black Sludge") and not lose_item:
        if defender.has_type("Poison"):
            if not heal_block:
                damage += math.floor(max_hp / 16)
                texts.append("Black Sludge recovery")
        elif not defender.has_ability("Magic Guard", "Klutz"):
            damage -= math.floor(max_hp / 8)
            texts.append("Black Sludge damage")
    elif defender.has_item("Sticky Barb") and not lose_item and not defender.has_ability("Magic Guard", "Klutz"):
        damage -= math.floor(max_hp / 8)
        texts.append("Sticky Barb damage")

    if field.defender_side.is_seeded and not defender.has_ability("Magic Guard"):
        damage -= math.floor(max_hp / 8)
        texts.append("Leech Seed damage")

    if field.defender_side.is_nightmared and not defender.has_ability("Magic Guard"):
        damage -= math.floor(max_hp / 4)
        texts.append("Nightmare damage")

    if field.attacker_side.is_seeded and not attacker.has_ability("Magic Guard"):
        recovery = math.floor(attacker.max_hp() / 8)
        if defender.has_item("Big Root"):
            recovery = math.trunc(recovery * 5324 / 4096)
        if attacker.has_ability("Liquid Ooze"):
            damage -= recovery
            texts.append("Liquid Ooze damage")
        elif not heal_block:
            damage += recovery
            texts.append("Leech Seed recovery")

    if field.has_terrain("Grassy") and is_grounded(defender, field) and not heal_block:
        damage += math.floor(max_hp / 16)
        texts.append("Grassy Terrain recovery")

    if defender.has_status("psn"):
        if defender.has_ability("Poison Heal"):
            if not heal_block:
                damage += math.floor(max_hp / 8)
                texts.append("Poison Heal")
        elif not defender.has_ability("Magic Guard"):
            damage -= math.floor(max_hp / 8)
            texts.append("poison damage")
    elif defender.has_status("tox"):
        if defender.has_ability("Poison Heal"):
            if not heal_block:
                damage += math.floor(max_hp / 8)
                texts.append("Poison Heal")
        elif not defender.has_ability("Magic Guard"):
            texts.append("toxic damage")
    elif defender.has_status("brn"):
        if defender.has_ability("Heatproof"):
            damage -= math.floor(max_hp / 32)
            texts.append("reduced burn damage")
        elif not defender.has_ability("Magic Guard"):
            damage -= math.floor(max_hp / 16)
            texts.append("burn damage")
    elif (defender.has_status("slp") or defender.has_ability("Comatose")) and attacker.has_ability("Bad Dreams") and not defender.has_ability("Magic Guard"):
        damage -= math.floor(max_hp / 8)
        texts.append("Bad Dreams")

    if not defender.has_ability("Magic Guard") and move.name in TRAPPING:
        # gen 0 takes the pre-gen-6 divisors in the reference (gen.num > 5 is false)
        damage -= math.floor(max_hp / (8 if attacker.has_item("Binding Band") else 16))
        texts.append("trapping damage")
    if field.defender_side.is_salt_cured and not defender.has_ability("Magic Guard"):
        damage -= math.floor(max_hp / (8 if defender.has_type("Water", "Steel") else 16))
        texts.append("Salt Cure")
    if not defender.has_type("Fire") and not defender.has_ability("Magic Guard") and move.named("Fire Pledge (Grass Pledge Boosted)", "Grass Pledge (Fire Pledge Boosted)"):
        damage -= math.floor(max_hp / 8)
        texts.append("Sea of Fire damage")

    return damage, texts


def compute_ko_chance(damage: list[int], hp: int, eot: int, hits: int, times_used: int, max_hp: int, toxic_counter: int, _memo: dict | None = None) -> float:
    if _memo is None:
        _memo = {}
    key = (hp, eot, hits, toxic_counter)
    if key in _memo:
        return _memo[key]
    toxic_damage = 0
    if toxic_counter > 0:
        toxic_damage = math.floor((toxic_counter * max_hp) / 16)
        toxic_counter += 1
    n = len(damage)
    if hits == 1:
        if eot - toxic_damage > 0:
            eot = 0
            toxic_damage = 0
        for i in range(n):
            if damage[n - 1] - eot + toxic_damage < hp:
                _memo[key] = 0.0
                return 0.0
            if damage[i] - eot + toxic_damage >= hp:
                _memo[key] = (n - i) / n
                return (n - i) / n
    total = 0.0
    last = 0.0
    for i in range(n):
        if i == 0 or damage[i] != damage[i - 1]:
            c = compute_ko_chance(damage, hp - damage[i] + eot - toxic_damage, eot, hits - 1, times_used, max_hp, toxic_counter, _memo)
        else:
            c = last
        if c == 1:
            total += n - i
            break
        total += c
        last = c
    _memo[key] = total / n
    return total / n


def predict_total(damage: int, eot: int, hits: int, times_used: int, toxic_counter: int, max_hp: int) -> int:
    toxic_damage = 0
    last_turn_eot = eot
    if toxic_counter > 0:
        for i in range(hits - 1):
            toxic_damage += math.floor(((toxic_counter + i) * max_hp) / 16)
        last_turn_eot -= math.floor(((toxic_counter + (hits - 1)) * max_hp) / 16)
    if hits > 1 and times_used == 1:
        total = damage * hits - eot * (hits - 1) + toxic_damage
    else:
        total = damage - eot * (hits - 1) + toxic_damage
    if last_turn_eot < 0:
        total -= last_turn_eot
    return total


def serialize_text(arr: list[str]) -> str:
    if not arr:
        return ""
    if len(arr) == 1:
        return arr[0]
    if len(arr) == 2:
        return f"{arr[0]} and {arr[1]}"
    return "".join(f"{a}, " for a in arr[:-1]) + "and " + arr[-1]


def _round_chance(chance: float) -> float:
    return max(min(js_round(chance * 1000), 999), 1) / 10


def _fmt(x: float) -> str:
    return str(int(x)) if float(x).is_integer() else repr(float(x))


def get_ko_chance(attacker: Mon, defender: Mon, move: MoveState, field: FieldState, damage_obj) -> KOChance:
    damage, approximate = combine(damage_obj)
    if damage[-1] == 0:
        raise DescError("damage[damage.length - 1] === 0.")

    if damage[0] >= defender.max_hp() and move.times_used == 1 and move.times_used_with_metronome == 1:
        return KOChance(1, 1, "guaranteed OHKO")

    hazards_damage, hazards_texts = get_hazards(defender, field.defender_side)
    eot_damage, eot_texts = get_end_of_turn(attacker, defender, move, field)
    toxic_counter = defender.toxic_counter if defender.has_status("tox") and not defender.has_ability("Magic Guard", "Poison Heal") else 0

    qualifier = "approx. " if approximate else ""
    hazards_text = f" after {serialize_text(hazards_texts)}" if hazards_texts else ""
    after_text = f" after {serialize_text(hazards_texts + eot_texts)}" if hazards_texts or eot_texts else ""
    after_text_no_hazards = f" after {serialize_text(eot_texts)}" if eot_texts else ""

    def ko(chance_without: float | None, chance_with: float | None, n: int, multiple_turns: bool = False) -> KOChance:
        turn_text = "OHKO" if n == 1 else (f"KO in {n} turns" if multiple_turns else f"{n}HKO")
        text = qualifier
        chance: float | None = None
        if chance_without is None or chance_with is None:
            text += f"possible {turn_text}"
        elif chance_without + chance_with == 0:
            chance = 0
            text += "not a KO"
        elif chance_without == 1:
            chance = chance_without
            text = f"guaranteed OHKO{hazards_text}"
        elif chance_without > 0:
            chance = chance_with
            if chance_with == 1:
                text += f"{_fmt(_round_chance(chance_without))}% chance to {turn_text}{hazards_text} (guaranteed {turn_text}{after_text_no_hazards})"
            elif chance_with > chance_without:
                text += (f"{_fmt(_round_chance(chance_without))}% chance to {turn_text}{hazards_text} "
                         f"({qualifier}{_fmt(_round_chance(chance_with))}% chance to {turn_text}{after_text_no_hazards})")
            elif chance_without > 0:
                text += f"{_fmt(_round_chance(chance_without))}% chance to {turn_text}{hazards_text}"
        elif chance_without == 0:
            chance = chance_with
            if chance_with == 1:
                text = f"guaranteed {turn_text}{after_text}"
            elif chance_with > 0:
                text += f"{_fmt(_round_chance(chance_with))}% chance to {turn_text}{after_text}"
        return KOChance(chance, n, text)

    cur = defender.cur_hp() - hazards_damage
    max_hp = defender.max_hp()
    if move.times_used == 1 and move.times_used_with_metronome == 1:
        chance = compute_ko_chance(damage, cur, 0, 1, 1, max_hp, 0)
        chance_eot = compute_ko_chance(damage, cur, eot_damage, 1, 1, max_hp, toxic_counter)
        if chance + chance_eot > 0:
            return ko(chance, chance_eot, 1)
        for i in range(2, 5):
            c = compute_ko_chance(damage, cur, eot_damage, i, 1, max_hp, toxic_counter)
            if c > 0:
                return ko(0, c, i)
        for i in range(5, 10):
            if predict_total(damage[0], eot_damage, i, 1, toxic_counter, max_hp) >= cur:
                return ko(0, 1, i)
            if predict_total(damage[-1], eot_damage, i, 1, toxic_counter, max_hp) >= cur:
                return ko(None, None, i)
    else:
        c = compute_ko_chance(damage, max_hp - hazards_damage, eot_damage, move.hits or 1, move.times_used or 1, max_hp, toxic_counter)
        if c > 0:
            return ko(0, c, move.times_used, c == 1)
        if predict_total(damage[0], eot_damage, 1, move.times_used, toxic_counter, max_hp) >= cur:
            return ko(0, 1, move.times_used, True)
        if predict_total(damage[-1], eot_damage, 1, move.times_used, toxic_counter, max_hp) >= cur:
            return ko(None, None, move.times_used, True)
        return ko(0, 0, move.times_used)

    return KOChance(0, 0, "")

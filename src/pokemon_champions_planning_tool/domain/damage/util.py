"""Port of the reference calculator's ``mechanics/util.ts`` for Pokémon Champions (gen 0).

Every function mirrors its TypeScript namesake, including the reference's quirks (they are
encoded in the golden fixtures): the odd 131172 speed bound, Power-Up Punch's boost table
lookup, and the defender-boost slip in ``check_multihit_boost``.
"""

from __future__ import annotations

import math

from ..type_chart import effectiveness as chart_effectiveness
from .items import EV_ITEMS
from .jsmath import chain_mods, of16, of32, poke_round
from .state import DISPLAY_STAT, FieldState, Mon, MoveState, SideState, nature_plus_minus

_BOOST_TABLE = [(2, 8), (2, 7), (2, 6), (2, 5), (2, 4), (2, 3), (2, 2), (3, 2), (4, 2), (5, 2), (6, 2), (7, 2), (8, 2)]


def is_grounded(pokemon: Mon, field: FieldState) -> bool:
    return bool(field.is_gravity or pokemon.has_item("Iron Ball") or (
        not pokemon.has_type("Flying") and not pokemon.has_ability("Levitate", "Eelevate") and not pokemon.has_item("Air Balloon")))


def get_modified_stat(stat: int, mod: int) -> int:
    num, den = _BOOST_TABLE[6 + mod]
    stat = of16(stat * num)
    return math.floor(stat / den)


def get_final_speed(pokemon: Mon, field: FieldState, side: SideState) -> int:
    weather = field.weather or ""
    terrain = field.terrain
    speed = get_modified_stat(pokemon.raw_stats["spe"], pokemon.boosts["spe"])
    mods: list[int] = []
    if side.is_tailwind:
        mods.append(8192)
    if ((pokemon.has_ability("Unburden") and pokemon.ability_on)
            or (pokemon.has_ability("Chlorophyll") and "Sun" in weather)
            or (pokemon.has_ability("Sand Rush") and weather == "Sand")
            or (pokemon.has_ability("Swift Swim") and "Rain" in weather)
            or (pokemon.has_ability("Slush Rush") and weather in ("Hail", "Snow"))
            or (pokemon.has_ability("Surge Surfer") and terrain == "Electric")):
        mods.append(8192)
    elif pokemon.has_ability("Quick Feet") and pokemon.status:
        mods.append(6144)
    elif pokemon.has_ability("Slow Start") and pokemon.ability_on:
        mods.append(2048)
    if not (pokemon.has_ability("Unburden") and pokemon.ability_on):
        if pokemon.has_item("Choice Scarf"):
            mods.append(6144)
        elif pokemon.has_item("Iron Ball", *EV_ITEMS):
            mods.append(2048)
        elif pokemon.has_item("Quick Powder") and pokemon.named("Ditto"):
            mods.append(8192)
    speed = of32(poke_round((speed * chain_mods(mods, 410, 131172)) / 4096))
    if pokemon.has_status("par") and not pokemon.has_ability("Quick Feet"):
        speed = math.floor(of32(speed * 50) / 100)
    speed = min(10000, speed)
    return max(0, int(speed))


def compute_final_stats(attacker: Mon, defender: Mon, field: FieldState, *stats: str) -> None:
    for pokemon, side in ((attacker, field.attacker_side), (defender, field.defender_side)):
        for stat in stats:
            if stat == "spe":
                pokemon.stats["spe"] = get_final_speed(pokemon, field, side)
            else:
                pokemon.stats[stat] = get_modified_stat(pokemon.raw_stats[stat], pokemon.boosts[stat])


def get_move_effectiveness(move: MoveState, type_: str, is_ghost_revealed: bool = False, is_gravity: bool = False, is_ring_target: bool = False) -> float:
    if is_ghost_revealed and type_ == "Ghost" and move.has_type("Normal", "Fighting"):
        return 1.0
    if is_gravity and type_ == "Flying" and move.has_type("Ground"):
        return 1.0
    if move.named("Freeze-Dry") and type_ == "Water":
        return 2.0
    if move.named("Nihil Light") and type_ == "Fairy":
        return 1.0
    eff = chart_effectiveness(move.type.lower(), type_.lower()) if move.type != "???" else 1.0
    if eff == 0 and is_ring_target:
        eff = 1.0
    if move.named("Flying Press"):
        eff *= chart_effectiveness("flying", type_.lower())
    return eff


def check_air_lock(pokemon: Mon, field: FieldState) -> None:
    if pokemon.has_ability("Air Lock", "Cloud Nine"):
        field.weather = None


def check_forecast(pokemon: Mon, weather: str | None) -> None:
    if pokemon.has_ability("Forecast") and pokemon.named("Castform"):
        if weather in ("Sun", "Harsh Sunshine"):
            pokemon.types = ["Fire"]
        elif weather in ("Rain", "Heavy Rain"):
            pokemon.types = ["Water"]
        elif weather in ("Hail", "Snow"):
            pokemon.types = ["Ice"]
        else:
            pokemon.types = ["Normal"]


def check_item(pokemon: Mon, magic_room: bool) -> None:
    if (pokemon.has_ability("Klutz") and pokemon.item not in EV_ITEMS) or magic_room:
        pokemon.disabled_item = pokemon.item
        pokemon.item = ""


def check_raw_stat_changes(pokemon: Mon, power_trick: bool, wonder_room: bool) -> None:
    rs = pokemon.raw_stats
    if power_trick:
        rs["atk"], rs["def"] = rs["def"], rs["atk"]
    if wonder_room:
        rs["def"], rs["spd"] = rs["spd"], rs["def"]


def check_intimidate(source: Mon, target: Mon) -> None:
    blocked = (target.has_ability("Clear Body", "White Smoke", "Hyper Cutter", "Full Metal Body")
               or target.has_ability("Inner Focus", "Own Tempo", "Oblivious", "Scrappy")
               or target.has_item("Clear Amulet"))
    if source.has_ability("Intimidate") and source.ability_on and not blocked:
        if target.has_ability("Contrary", "Defiant", "Guard Dog"):
            target.boosts["atk"] = min(6, target.boosts["atk"] + 1)
        elif target.has_ability("Simple"):
            target.boosts["atk"] = max(-6, target.boosts["atk"] - 2)
        else:
            target.boosts["atk"] = max(-6, target.boosts["atk"] - 1)
        if target.has_ability("Competitive"):
            target.boosts["spa"] = min(6, target.boosts["spa"] + 2)


def check_infiltrator(pokemon: Mon, affected_side: SideState) -> None:
    if pokemon.has_ability("Infiltrator"):
        affected_side.is_reflect = False
        affected_side.is_light_screen = False
        affected_side.is_aurora_veil = False


def check_multihit_boost(attacker: Mon, defender: Mon, move: MoveState, field: FieldState, desc: dict,
                         attacker_used_item: bool = False, defender_used_item: bool = False) -> tuple[bool, bool]:
    if move.named("Gyro Ball", "Electro Ball") and defender.has_ability("Gooey", "Tangling Hair"):
        if attacker.has_item("White Herb") and not attacker_used_item:
            desc["attackerItem"] = attacker.item
            attacker_used_item = True
        else:
            attacker.boosts["spe"] = max(attacker.boosts["spe"] - 1, -6)
            attacker.stats["spe"] = get_final_speed(attacker, field, field.attacker_side)
            desc["defenderAbility"] = defender.ability
    elif move.named("Power-Up Punch"):
        attacker.boosts["atk"] = min(attacker.boosts["atk"] + 1, 6)
        attacker.stats["atk"] = get_modified_stat(attacker.raw_stats["atk"], attacker.boosts["atk"])

    atk_simple = 2 if attacker.has_ability("Simple") else 1
    def_simple = 2 if defender.has_ability("Simple") else 1

    if ((not defender_used_item) and (defender.has_item("Luminous Moss") and move.has_type("Water"))
            or (defender.has_item("Maranga Berry") and move.category == "Special")
            or (defender.has_item("Kee Berry") and move.category == "Physical")):
        def_stat = "def" if defender.has_item("Kee Berry") else "spd"
        if attacker.has_ability("Unaware"):
            desc["attackerAbility"] = attacker.ability
        else:
            if defender.has_ability("Contrary"):
                desc["defenderAbility"] = defender.ability
                if defender.has_item("White Herb") and not defender_used_item:
                    desc["defenderItem"] = defender.item
                    defender_used_item = True
                else:
                    defender.boosts[def_stat] = max(-6, defender.boosts[def_stat] - def_simple)
            else:
                defender.boosts[def_stat] = min(6, defender.boosts[def_stat] + def_simple)
            if def_simple == 2:
                desc["defenderAbility"] = defender.ability
            defender.stats[def_stat] = get_modified_stat(defender.raw_stats[def_stat], defender.boosts[def_stat])
            desc["defenderItem"] = defender.item
            defender_used_item = True

    if defender.has_ability("Seed Sower"):
        field.terrain = "Grassy"
    if defender.has_ability("Sand Spit"):
        field.weather = "Sand"

    if defender.has_ability("Stamina"):
        if attacker.has_ability("Unaware"):
            desc["attackerAbility"] = attacker.ability
        else:
            defender.boosts["def"] = min(defender.boosts["def"] + 1, 6)
            defender.stats["def"] = get_modified_stat(defender.raw_stats["def"], defender.boosts["def"])
            desc["defenderAbility"] = defender.ability
    elif defender.has_ability("Water Compaction") and move.has_type("Water"):
        if attacker.has_ability("Unaware"):
            desc["attackerAbility"] = attacker.ability
        else:
            defender.boosts["def"] = min(defender.boosts["def"] + 2, 6)
            defender.stats["def"] = get_modified_stat(defender.raw_stats["def"], defender.boosts["def"])
            desc["defenderAbility"] = defender.ability
    elif defender.has_ability("Weak Armor"):
        if attacker.has_ability("Unaware"):
            desc["attackerAbility"] = attacker.ability
        else:
            if defender.has_item("White Herb") and not defender_used_item and defender.boosts["def"] == 0:
                desc["defenderItem"] = defender.item
                defender_used_item = True
            else:
                defender.boosts["def"] = max(defender.boosts["def"] - 1, -6)
                defender.stats["def"] = get_modified_stat(defender.raw_stats["def"], defender.boosts["def"])
            desc["defenderAbility"] = defender.ability
        defender.boosts["spe"] = min(defender.boosts["spe"] + 2, 6)
        defender.stats["spe"] = get_final_speed(defender, field, field.defender_side)

    if move.drops_stats:
        if attacker.has_ability("Unaware"):
            desc["attackerAbility"] = attacker.ability
        else:
            stat = "spa" if move.category == "Special" else "atk"
            boosts = attacker.boosts[stat]
            if attacker.has_ability("Contrary"):
                boosts = min(6, boosts + move.drops_stats)
                desc["attackerAbility"] = attacker.ability
            else:
                boosts = max(-6, boosts - move.drops_stats * atk_simple)
            if atk_simple == 2:
                desc["attackerAbility"] = attacker.ability
            if attacker.has_item("White Herb") and attacker.boosts[stat] < 0 and not attacker_used_item:
                boosts += move.drops_stats * atk_simple
                desc["attackerItem"] = attacker.item
                attacker_used_item = True
            attacker.boosts[stat] = boosts
            # Reference quirk: the stat is recomputed with the *defender's* boost.
            attacker.stats[stat] = get_modified_stat(attacker.raw_stats[stat], defender.boosts[stat])

    if defender.has_ability("Mummy", "Wandering Spirit", "Lingering Aroma") and move.flags.get("contact"):
        old = attacker.ability
        attacker.ability = defender.ability
        if desc.get("attackerAbility"):
            desc["defenderAbility"] = defender.ability
        if defender.has_ability("Wandering Spirit"):
            defender.ability = old

    return attacker_used_item, defender_used_item


def get_base_damage(level: int, base_power: int, attack: int, defense: int) -> int:
    return math.floor(of32(math.floor(of32(of32(math.floor((2 * level) / 5 + 2) * base_power) * attack) / defense) / 50 + 2))


def get_final_damage(base_amount: int, i: int, effectiveness: float, is_burned: bool, stab_mod: int, final_mod: int, protect: bool = False) -> int:
    amount: float = math.floor(of32(base_amount * (85 + i)) / 100)
    if stab_mod != 4096:
        amount = of32(amount * stab_mod) / 4096
    amount = math.floor(of32(poke_round(amount) * effectiveness))
    if is_burned:
        amount = math.floor(amount / 2)
    if protect:
        amount = poke_round(of32(amount * 1024) / 4096)
    return int(of16(poke_round(max(1, of32(amount * final_mod) / 4096))))


def get_shell_side_arm_category(source: Mon, target: Mon, wonder_room: bool) -> str:
    physical = source.stats["atk"] / target.stats["def"]
    special = source.stats["spa"] / target.stats["spd"]
    if wonder_room:
        physical = source.stats["atk"] / target.stats["spd"]
        special = source.stats["spa"] / target.stats["def"]
    return "Physical" if physical > special else "Special"


def get_weight(pokemon: Mon, desc: dict, role: str) -> float:
    weight_hg = pokemon.weightkg * 10
    factor = 2 if pokemon.has_ability("Heavy Metal") else 0.5 if pokemon.has_ability("Light Metal") else 1
    if factor != 1:
        weight_hg = max(math.trunc(weight_hg * factor), 1)
        desc[f"{role}Ability"] = pokemon.ability
    if pokemon.has_item("Float Stone"):
        weight_hg = max(math.trunc(weight_hg * 0.5), 1)
        desc[f"{role}Item"] = pokemon.item
    return weight_hg / 10


def get_stab_mod(pokemon: Mon, move: MoveState, desc: dict) -> int:
    stab = 4096
    if pokemon.has_original_type(move.type):
        stab += 2048
    elif pokemon.has_ability("Protean", "Libero"):
        stab += 2048
        desc["attackerAbility"] = pokemon.ability
    if pokemon.has_ability("Adaptability") and pokemon.has_type(move.type):
        stab += 2048
        desc["attackerAbility"] = pokemon.ability
    return stab


def count_boosts(boosts: dict[str, int]) -> int:
    return sum(v for k, v in boosts.items() if k in ("atk", "def", "spa", "spd", "spe") and v > 0)


def get_stat_description_text(pokemon: Mon, stat: str, power_trick: bool = False, wonder_room: bool = False) -> str:
    initial = stat
    if wonder_room:
        stat = {"def": "spd", "spd": "def"}.get(stat, stat)
    if power_trick:
        stat = {"atk": "def", "def": "atk"}.get(stat, stat)
    plus, minus = nature_plus_minus(pokemon.nature)
    sign = "" if stat == "hp" or plus == minus else "+" if plus == stat else "-" if minus == stat else ""
    text = f"{pokemon.points[stat]}{sign} {DISPLAY_STAT[initial]}"
    if stat != initial:
        text += f" ({DISPLAY_STAT[stat]})"
    return text


def handle_fixed_damage_moves(attacker: Mon, move: MoveState) -> int:
    if move.named("Seismic Toss", "Night Shade"):
        return attacker.level
    if move.named("Dragon Rage"):
        return 40
    if move.named("Sonic Boom"):
        return 20
    return 0

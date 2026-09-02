"""Port of ``mechanics/champions.ts`` — the Pokémon Champions damage formula.

Function for function, branch for branch, in the reference's order. ``desc`` is the raw
description dict (the reference's ``RawDesc``, camelCase keys) that ``desc.py`` renders.
"""

from __future__ import annotations

import math

from .abilities import MOLD_BREAKER_IGNORED
from .items import berry_resist_type, fling_power, item_boost_type, resists_knock_off
from .jsmath import chain_mods, of16, of32, poke_round
from .state import CalcMove, CalcPokemon, Field, FieldState, Mon, MoveState
from .util import (
    check_air_lock,
    check_forecast,
    check_infiltrator,
    check_intimidate,
    check_item,
    check_multihit_boost,
    check_raw_stat_changes,
    compute_final_stats,
    count_boosts,
    get_base_damage,
    get_final_damage,
    get_modified_stat,
    get_move_effectiveness,
    get_shell_side_arm_category,
    get_stab_mod,
    get_stat_description_text,
    get_weight,
    handle_fixed_damage_moves,
    is_grounded,
)

Damage = int | list[int] | list[list[int]]


class RawResult:
    """What ``calculateChampions`` returns: damage plus the mutated working state."""

    __slots__ = ("attacker", "defender", "move", "field", "damage", "desc")

    def __init__(self, attacker: Mon, defender: Mon, move: MoveState, field: FieldState, damage: Damage, desc: dict) -> None:
        self.attacker, self.defender, self.move, self.field, self.damage, self.desc = attacker, defender, move, field, damage, desc


def calculate_raw(attacker: CalcPokemon, defender: CalcPokemon, move: CalcMove, field: Field | None = None) -> RawResult:
    """``calculate()`` in ``calc.ts``: clone the inputs, then run the Champions mechanics."""
    return calculate_champions(Mon.from_input(attacker), Mon.from_input(defender), MoveState.from_input(move), FieldState.from_input(field or Field()))


def calculate_champions(attacker: Mon, defender: Mon, move: MoveState, field: FieldState) -> RawResult:
    check_air_lock(attacker, field)
    check_air_lock(defender, field)
    check_forecast(attacker, field.weather)
    check_forecast(defender, field.weather)
    check_item(attacker, field.is_magic_room)
    check_item(defender, field.is_magic_room)
    check_raw_stat_changes(attacker, field.attacker_side.is_power_trick, field.is_wonder_room)
    check_raw_stat_changes(defender, field.defender_side.is_power_trick, field.is_wonder_room)

    compute_final_stats(attacker, defender, field, "def", "spd", "spe")

    check_intimidate(attacker, defender)
    check_intimidate(defender, attacker)

    if move.named("Meteor Beam", "Electro Shot"):
        attacker.boosts["spa"] += -1 if attacker.has_ability("Contrary") else 1
        attacker.boosts["spa"] = min(6, max(-6, attacker.boosts["spa"]))

    compute_final_stats(attacker, defender, field, "atk", "spa")

    check_infiltrator(attacker, field.defender_side)
    check_infiltrator(defender, field.attacker_side)

    desc: dict = {"attackerName": attacker.name, "moveName": move.name, "defenderName": defender.name, "isWonderRoom": field.is_wonder_room}
    result = RawResult(attacker, defender, move, field, 0, desc)

    if move.category == "Status":
        return result

    if move.named("Shell Side Arm") and get_shell_side_arm_category(attacker, defender, field.is_wonder_room) == "Physical":
        move.category = "Physical"
        move.flags["contact"] = 1

    breaks_protect = move.breaks_protect or (attacker.has_ability("Unseen Fist", "Piercing Drill") and move.flags.get("contact"))

    if field.defender_side.is_protected and not breaks_protect:
        desc["isProtected"] = True
        return result

    if move.name == "Pain Split":
        average = math.floor((attacker.cur_hp() + defender.cur_hp()) / 2)
        result.damage = max(0, defender.cur_hp() - average)
        return result

    defender_ability_ignored = defender.has_ability(*MOLD_BREAKER_IGNORED)
    attacker_ignores_ability = attacker.has_ability("Mold Breaker")
    if defender_ability_ignored and attacker_ignores_ability:
        desc["attackerAbility"] = attacker.ability
        defender.ability = ""

    is_critical = (not defender.has_ability("Shell Armor", "Battle Armor")
                   and (move.is_crit or (attacker.has_ability("Merciless") and defender.has_status("psn", "tox")))
                   and move.times_used == 1)

    type_ = move.type
    if move.original_name == "Weather Ball":
        is_mega_sol = attacker.has_ability("Mega Sol")
        type_ = ("Fire" if field.has_weather("Sun", "Harsh Sunshine") or is_mega_sol
                 else "Water" if field.has_weather("Rain", "Heavy Rain")
                 else "Rock" if field.has_weather("Sand")
                 else "Ice" if field.has_weather("Hail", "Snow")
                 else "Normal")
        if is_mega_sol:
            desc["attackerAbility"] = attacker.ability
        else:
            desc["weather"] = field.weather
        desc["moveType"] = type_
    elif move.original_name == "Terrain Pulse" and is_grounded(attacker, field):
        type_ = ("Electric" if field.has_terrain("Electric") else "Grass" if field.has_terrain("Grassy")
                 else "Fairy" if field.has_terrain("Misty") else "Psychic" if field.has_terrain("Psychic") else "Normal")
        desc["terrain"] = field.terrain
        if not (move.named("Nature Power") and attacker.has_ability("Prankster")) and (
                "Dark" in defender.types or (field.has_terrain("Psychic") and is_grounded(defender, field))):
            desc["moveType"] = type_
    elif move.named("Aura Wheel"):
        if attacker.named("Morpeko"):
            type_ = "Electric"
        elif attacker.named("Morpeko-Hangry"):
            type_ = "Dark"
    elif move.named("Raging Bull"):
        if attacker.named("Tauros-Paldea-Combat"):
            type_ = "Fighting"
        elif attacker.named("Tauros-Paldea-Blaze"):
            type_ = "Fire"
        elif attacker.named("Tauros-Paldea-Aqua"):
            type_ = "Water"
        field.defender_side.is_reflect = False
        field.defender_side.is_light_screen = False
        field.defender_side.is_aurora_veil = False
    elif move.named("Brick Break", "Psychic Fangs"):
        field.defender_side.is_reflect = False
        field.defender_side.is_light_screen = False
        field.defender_side.is_aurora_veil = False

    if attacker.has_ability("Electromorphosis") and attacker.ability_on:
        field.attacker_side.is_charge = True

    has_ate_type_change = False
    no_type_change = move.named("Weather Ball", "Terrain Pulse", "Struggle")
    if not no_type_change:
        normal = type_ == "Normal"
        is_aerilate = attacker.has_ability("Aerilate") and normal
        is_dragonize = is_pixilate = is_refrigerate = is_liquid_voice = False
        if is_aerilate:
            type_ = "Flying"
        elif (is_dragonize := attacker.has_ability("Dragonize") and normal):
            type_ = "Dragon"
        elif (is_liquid_voice := attacker.has_ability("Liquid Voice") and bool(move.flags.get("sound"))):
            type_ = "Water"
        elif (is_pixilate := attacker.has_ability("Pixilate") and normal):
            type_ = "Fairy"
        elif (is_refrigerate := attacker.has_ability("Refrigerate") and normal):
            type_ = "Ice"
        if is_aerilate or is_dragonize or is_pixilate or is_refrigerate:
            desc["attackerAbility"] = attacker.ability
            has_ate_type_change = True
        elif is_liquid_voice:
            desc["attackerAbility"] = attacker.ability

    move.type = type_

    is_ghost_revealed = attacker.has_ability("Scrappy")
    type1 = get_move_effectiveness(move, defender.types[0], is_ghost_revealed, field.is_gravity, False)
    type2 = get_move_effectiveness(move, defender.types[1], is_ghost_revealed, field.is_gravity, False) if len(defender.types) > 1 else 1.0
    type_effectiveness = type1 * type2

    if type_effectiveness == 0 and move.has_type("Ground") and defender.has_item("Iron Ball") and not defender.has_ability("Klutz"):
        type_effectiveness = 1.0

    if type_effectiveness == 0:
        return result

    if (move.named("Steel Roller") and not field.terrain) or (move.named("Poltergeist") and not defender.item):
        return result

    if ((move.has_type("Grass") and defender.has_ability("Sap Sipper"))
            or (move.has_type("Fire") and defender.has_ability("Flash Fire"))
            or (move.has_type("Water") and defender.has_ability("Dry Skin", "Water Absorb"))
            or (move.has_type("Electric") and defender.has_ability("Lightning Rod", "Motor Drive", "Volt Absorb"))
            or (move.has_type("Ground") and not field.is_gravity and defender.has_ability("Levitate", "Eelevate"))
            or (move.flags.get("bullet") and defender.has_ability("Bulletproof"))
            or (move.flags.get("sound") and not move.named("Clangorous Soul") and defender.has_ability("Soundproof"))
            or (move.priority > 0 and defender.has_ability("Queenly Majesty", "Armor Tail"))
            or (move.has_type("Ground") and defender.has_ability("Earth Eater"))):
        desc["defenderAbility"] = defender.ability
        return result

    if move.priority > 0 and field.has_terrain("Psychic") and is_grounded(defender, field):
        desc["terrain"] = field.terrain
        return result

    desc["HPEVs"] = get_stat_description_text(defender, "hp")

    fixed = handle_fixed_damage_moves(attacker, move)
    if fixed:
        if attacker.has_ability("Parental Bond"):
            result.damage = [fixed, fixed]
            desc["attackerAbility"] = attacker.ability
        else:
            result.damage = fixed
        return result

    if move.named("Final Gambit"):
        result.damage = attacker.cur_hp()
        return result

    if move.hits > 1:
        desc["hits"] = move.hits

    base_power = calculate_base_power(attacker, defender, move, field, has_ate_type_change, desc)
    if base_power == 0:
        return result

    attack = calculate_attack(attacker, defender, move, field, desc, is_critical)
    defense = calculate_defense(attacker, defender, move, field, desc, is_critical)

    base_damage = calculate_base_damage(attacker, defender, base_power, attack, defense, move, field, desc, is_critical)

    if attacker.has_ability("Gale Wings") and move.has_type("Flying") and attacker.cur_hp() == attacker.max_hp():
        move.priority = 1
        desc["attackerAbility"] = attacker.ability

    stab_mod = get_stab_mod(attacker, move, desc)

    apply_burn = attacker.has_status("brn") and move.category == "Physical" and not attacker.has_ability("Guts") and not move.named("Facade")
    desc["isBurned"] = apply_burn
    final_mods = calculate_final_mods(attacker, defender, move, field, desc, is_critical, type_effectiveness)

    protect = False
    if field.defender_side.is_protected and (attacker.has_ability("Unseen Fist", "Piercing Drill") and move.flags.get("contact")):
        protect = True
        desc["isProtected"] = True

    final_mod = chain_mods(final_mods, 41, 131072)

    is_spread = field.game_type != "Singles" and move.target in ("allAdjacent", "allAdjacentFoes")

    child_damage: list[int] | None = None
    if attacker.has_ability("Parental Bond") and move.hits == 1 and not is_spread:
        child = attacker.clone()
        child.ability = "Parental Bond (Child)"
        check_multihit_boost(child, defender, move, field, desc)
        child_damage = calculate_champions(child, defender, move, field).damage  # type: ignore[assignment]
        desc["attackerAbility"] = attacker.ability

    damage = [get_final_damage(base_damage, i, type_effectiveness, apply_burn, stab_mod, final_mod, protect) for i in range(16)]
    result.damage = [damage, child_damage] if child_damage is not None else damage

    if move.times_used > 1 or move.hits > 1:
        orig_def_boost = desc.get("defenseBoost")
        orig_atk_boost = desc.get("attackBoost")
        if move.times_used > 1:
            desc["moveTurns"] = f"over {move.times_used} turns"
            num_attacks = move.times_used
        else:
            num_attacks = move.hits
        used_items = (False, False)
        matrix = [damage]
        for times in range(1, num_attacks):
            used_items = check_multihit_boost(attacker, defender, move, field, desc, used_items[0], used_items[1])
            new_attack = calculate_attack(attacker, defender, move, field, desc, is_critical)
            new_defense = calculate_defense(attacker, defender, move, field, desc, is_critical)
            has_ate_type_change = has_ate_type_change and attacker.has_ability("Aerilate", "Dragonize", "Pixilate", "Refrigerate")
            if move.times_used > 1:
                stab_mod = get_stab_mod(attacker, move, desc)
            new_bp = calculate_base_power(attacker, defender, move, field, has_ate_type_change, desc, times + 1)
            new_base_damage = calculate_base_damage(attacker, defender, new_bp, new_attack, new_defense, move, field, desc, is_critical)
            new_final_mods = calculate_final_mods(attacker, defender, move, field, desc, is_critical, type_effectiveness, times)
            new_final_mod = chain_mods(new_final_mods, 41, 131072)
            matrix.append([get_final_damage(new_base_damage, i, type_effectiveness, apply_burn, stab_mod, new_final_mod, protect) for i in range(16)])
        result.damage = matrix
        _set_or_delete(desc, "defenseBoost", orig_def_boost)
        _set_or_delete(desc, "attackBoost", orig_atk_boost)

    return result


def _set_or_delete(desc: dict, key: str, value) -> None:
    """``desc.x = undefined`` in JS leaves the key absent when serialised."""
    if value is None:
        desc.pop(key, None)
    else:
        desc[key] = value


def calculate_base_power(attacker: Mon, defender: Mon, move: MoveState, field: FieldState, has_ate_type_change: bool, desc: dict, hit: int = 1) -> int:
    turn_order = "first" if attacker.stats["spe"] > defender.stats["spe"] else "last"
    name = move.name
    if name == "Payback":
        bp = move.bp * (2 if turn_order == "last" else 1)
        desc["moveBP"] = bp
    elif name == "Electro Ball":
        if defender.stats["spe"] == 0:
            bp = 40
        else:
            r = math.floor(attacker.stats["spe"] / defender.stats["spe"])
            bp = 150 if r >= 4 else 120 if r >= 3 else 80 if r >= 2 else 60 if r >= 1 else 40
        desc["moveBP"] = bp
    elif name == "Gyro Ball":
        bp = 1 if attacker.stats["spe"] == 0 else min(150, math.floor((25 * defender.stats["spe"]) / attacker.stats["spe"]) + 1)
        desc["moveBP"] = bp
    elif name == "Punishment":
        bp = min(200, 60 + 20 * count_boosts(defender.boosts))
        desc["moveBP"] = bp
    elif name in ("Low Kick", "Grass Knot"):
        w = get_weight(defender, desc, "defender")
        bp = 120 if w >= 200 else 100 if w >= 100 else 80 if w >= 50 else 60 if w >= 25 else 40 if w >= 10 else 20
        desc["moveBP"] = bp
    elif name in ("Hex", "Infernal Parade"):
        bp = move.bp * (2 if defender.status else 1)
        desc["moveBP"] = bp
    elif name == "Barb Barrage":
        bp = move.bp * (2 if defender.has_status("psn", "tox") else 1)
        desc["moveBP"] = bp
    elif name in ("Heavy Slam", "Heat Crash"):
        wa = get_weight(attacker, desc, "attacker")
        wd = get_weight(defender, desc, "defender")
        wr = math.inf if wd == 0 else wa / wd
        bp = 120 if wr >= 5 else 100 if wr >= 4 else 80 if wr >= 3 else 60 if wr >= 2 else 40
        desc["moveBP"] = bp
    elif name in ("Stored Power", "Power Trip"):
        bp = 20 + 20 * count_boosts(attacker.boosts)
        desc["moveBP"] = bp
    elif name == "Acrobatics":
        bp = move.bp * (2 if not attacker.item else 1)
        desc["moveBP"] = bp
    elif name == "Assurance":
        bp = move.bp * (2 if defender.has_ability("Parental Bond (Child)") else 1)
    elif name == "Smelling Salts":
        bp = move.bp * (2 if defender.has_status("par") else 1)
        desc["moveBP"] = bp
    elif name == "Weather Ball":
        bp = move.bp * (2 if field.weather or attacker.has_ability("Mega Sol") else 1)
        desc["moveBP"] = bp
    elif name == "Terrain Pulse":
        bp = move.bp * (2 if is_grounded(attacker, field) and field.terrain else 1)
        desc["moveBP"] = bp
    elif name == "Rising Voltage":
        bp = move.bp * (2 if is_grounded(defender, field) and field.has_terrain("Electric") else 1)
        desc["moveBP"] = bp
    elif name == "Fling":
        bp = fling_power(attacker.item)
        desc["moveBP"] = bp
        desc["attackerItem"] = attacker.item
    elif name in ("Eruption", "Water Spout"):
        bp = max(1, math.floor((150 * attacker.cur_hp()) / attacker.max_hp()))
        desc["moveBP"] = bp
    elif name in ("Flail", "Reversal"):
        p = math.floor((48 * attacker.cur_hp()) / attacker.max_hp())
        bp = 200 if p <= 1 else 150 if p <= 4 else 100 if p <= 9 else 80 if p <= 16 else 40 if p <= 32 else 20
        desc["moveBP"] = bp
    elif name == "Triple Axel":
        bp = hit * 20
        desc["moveBP"] = 60 if move.hits == 2 else 120 if move.hits == 3 else 20
    elif name == "Hard Press":
        bp = 100 * math.floor((defender.cur_hp() * 4096) / defender.max_hp())
        bp = math.floor(math.floor((100 * bp + 2048 - 1) / 4096) / 100) or 1
        desc["moveBP"] = bp
    else:
        bp = move.bp
    if bp == 0:
        return 0
    bp_mods = calculate_bp_mods(attacker, defender, move, field, desc, bp, has_ate_type_change, turn_order, hit)
    return int(of16(max(1, poke_round((bp * chain_mods(bp_mods, 41, 2097152)) / 4096))))


def calculate_bp_mods(attacker: Mon, defender: Mon, move: MoveState, field: FieldState, desc: dict, base_power: int,
                      has_ate_type_change: bool, turn_order: str, hit: int) -> list[int]:
    mods: list[int] = []

    defender_item = defender.item if defender.item else defender.disabled_item
    resisted_knock_off = not defender_item
    if not resisted_knock_off and defender_item:
        resisted_knock_off = resists_knock_off(defender_item, defender.name)
    if not resisted_knock_off and hit > 1 and not defender.has_ability("Sticky Hold"):
        resisted_knock_off = True

    if ((move.named("Facade") and attacker.has_status("brn", "par", "psn", "tox"))
            or (move.named("Venoshock") and defender.has_status("psn", "tox"))
            or (move.named("Lash Out") and count_boosts(attacker.boosts) < 0)):
        mods.append(8192)
        desc["moveBP"] = base_power * 2
    elif move.named("Expanding Force") and is_grounded(attacker, field) and field.has_terrain("Psychic"):
        move.target = "allAdjacentFoes"
        mods.append(6144)
        desc["moveBP"] = base_power * 1.5
    elif ((move.named("Knock Off") and not resisted_knock_off)
          or (move.named("Misty Explosion") and is_grounded(attacker, field) and field.has_terrain("Misty"))
          or (move.named("Grav Apple") and field.is_gravity)):
        mods.append(6144)
        desc["moveBP"] = base_power * 1.5
    elif move.named("Solar Beam", "Solar Blade") and field.has_weather("Rain", "Sand", "Hail", "Snow") and not attacker.has_ability("Mega Sol"):
        mods.append(2048)
        desc["moveBP"] = base_power / 2
        desc["weather"] = field.weather

    if field.attacker_side.is_helping_hand:
        mods.append(6144)
        desc["isHelpingHand"] = True

    if is_grounded(attacker, field):
        if ((field.has_terrain("Electric") and move.has_type("Electric"))
                or (field.has_terrain("Grassy") and move.has_type("Grass"))
                or (field.has_terrain("Psychic") and move.has_type("Psychic"))):
            mods.append(5325)
            desc["terrain"] = field.terrain
    if is_grounded(defender, field):
        if (field.has_terrain("Misty") and move.has_type("Dragon")) or (field.has_terrain("Grassy") and move.named("Bulldoze", "Earthquake")):
            mods.append(2048)
            desc["terrain"] = field.terrain

    if ((attacker.has_ability("Technician") and base_power <= 60)
            or (attacker.has_ability("Mega Launcher") and move.flags.get("pulse"))
            or (attacker.has_ability("Strong Jaw") and move.flags.get("bite"))
            or (attacker.has_ability("Sharpness") and move.flags.get("slicing"))):
        mods.append(6144)
        desc["attackerAbility"] = attacker.ability

    if field.attacker_side.is_charge and move.has_type("Electric"):
        mods.append(8192)
        desc["isCharge"] = True

    aura = f"{move.type} Aura"
    is_attacker_aura = attacker.has_ability(aura)
    is_defender_aura = defender.has_ability(aura)
    if is_attacker_aura or is_defender_aura or (field.is_fairy_aura and move.type == "Fairy") or (field.is_dark_aura and move.type == "Dark"):
        mods.append(5448)
        if is_attacker_aura:
            desc["attackerAbility"] = attacker.ability
        if is_defender_aura:
            desc["defenderAbility"] = defender.ability

    if ((attacker.has_ability("Sheer Force") and (move.secondaries or move.named("Electro Shot")))
            or (attacker.has_ability("Sand Force") and field.has_weather("Sand") and move.has_type("Rock", "Ground", "Steel"))
            or (attacker.has_ability("Analytic") and (turn_order != "first" or field.defender_side.is_switching == "out" or attacker.ability_on))
            or (attacker.has_ability("Tough Claws") and move.flags.get("contact"))):
        mods.append(5325)
        desc["attackerAbility"] = attacker.ability

    if attacker.has_ability("Rivalry") and "N" not in (attacker.gender, defender.gender):
        if attacker.gender == defender.gender:
            mods.append(5120)
            desc["rivalry"] = "buffed"
        else:
            mods.append(3072)
            desc["rivalry"] = "nerfed"
        desc["attackerAbility"] = attacker.ability

    if has_ate_type_change:
        mods.append(4915)

    if (attacker.has_ability("Reckless") and (move.recoil or move.has_crash_damage)) or (attacker.has_ability("Iron Fist") and move.flags.get("punch")):
        mods.append(4915)
        desc["attackerAbility"] = attacker.ability

    if defender.has_ability("Dry Skin") and move.has_type("Fire"):
        mods.append(5120)
        desc["defenderAbility"] = defender.ability

    if attacker.has_ability("Supreme Overlord") and attacker.allies_fainted:
        mods.append([4096, 4506, 4915, 5325, 5734, 6144][min(5, attacker.allies_fainted)])
        desc["attackerAbility"] = attacker.ability
        desc["alliesFainted"] = attacker.allies_fainted

    if attacker.item and move.has_type(item_boost_type(attacker.item)):
        mods.append(4915)
        desc["attackerItem"] = attacker.item
    elif (attacker.has_item("Muscle Band") and move.category == "Physical") or (attacker.has_item("Wise Glasses") and move.category == "Special"):
        mods.append(4505)
        desc["attackerItem"] = attacker.item

    return mods


def calculate_attack(attacker: Mon, defender: Mon, move: MoveState, field: FieldState, desc: dict, is_critical: bool = False) -> int:
    source = defender if move.named("Foul Play") else attacker
    attack_stat = ("spd" if field.is_wonder_room else "def") if move.named("Body Press") else ("spa" if move.category == "Special" else "atk")
    if move.named("Foul Play"):
        desc["attackEVs"] = get_stat_description_text(source, attack_stat, field.defender_side.is_power_trick)
    else:
        desc["attackEVs"] = get_stat_description_text(source, attack_stat, field.attacker_side.is_power_trick, field.is_wonder_room)
    if field.attacker_side.is_power_trick:
        if (move.category == "Physical" and not move.named("Foul Play")) or move.named("Body Press"):
            desc["isPowerTrickAttacker"] = True
    boosts = source.boosts[attack_stat]
    if boosts == 0 or (is_critical and boosts < 0):
        attack = source.raw_stats[attack_stat]
    elif defender.has_ability("Unaware"):
        attack = source.raw_stats[attack_stat]
        desc["defenderAbility"] = defender.ability
    else:
        attack = get_modified_stat(source.raw_stats[attack_stat], boosts)
        desc["attackBoost"] = boosts

    if attacker.has_ability("Hustle") and move.category == "Physical":
        attack = poke_round((attack * 3) / 2)
        desc["attackerAbility"] = attacker.ability

    at_mods = calculate_at_mods(attacker, defender, move, field, desc)
    return int(of16(max(1, poke_round((attack * chain_mods(at_mods, 410, 131072)) / 4096))))


def calculate_at_mods(attacker: Mon, defender: Mon, move: MoveState, field: FieldState, desc: dict) -> list[int]:
    mods: list[int] = []
    if attacker.has_ability("Solar Power") and field.has_weather("Sun") and move.category == "Special":
        mods.append(6144)
        desc["attackerAbility"] = attacker.ability
        desc["weather"] = field.weather
    elif ((attacker.has_ability("Guts") and attacker.status and move.category == "Physical")
          or (attacker.cur_hp() <= attacker.max_hp() / 3 and (
              (attacker.has_ability("Overgrow") and move.has_type("Grass")) or (attacker.has_ability("Blaze") and move.has_type("Fire"))
              or (attacker.has_ability("Torrent") and move.has_type("Water")) or (attacker.has_ability("Swarm") and move.has_type("Bug"))))
          or (move.category == "Special" and attacker.ability_on and attacker.has_ability("Plus", "Minus"))):
        mods.append(6144)
        desc["attackerAbility"] = attacker.ability
    elif attacker.has_ability("Flash Fire") and attacker.ability_on and move.has_type("Fire"):
        mods.append(6144)
        desc["attackerAbility"] = "Flash Fire"
    elif attacker.has_ability("Fire Mane") and move.has_type("Fire"):
        mods.append(6144)
        desc["attackerAbility"] = attacker.ability
    elif (attacker.has_ability("Water Bubble") and move.has_type("Water")) or (attacker.has_ability("Huge Power", "Pure Power") and move.category == "Physical"):
        mods.append(8192)
        desc["attackerAbility"] = attacker.ability

    if ((defender.has_ability("Thick Fat") and move.has_type("Fire", "Ice"))
            or (defender.has_ability("Water Bubble") and move.has_type("Fire"))
            or (defender.has_ability("Purifying Salt") and move.has_type("Ghost"))):
        mods.append(2048)
        desc["defenderAbility"] = defender.ability

    if defender.has_ability("Heatproof") and move.has_type("Fire"):
        mods.append(2048)
        desc["defenderAbility"] = defender.ability

    if attacker.has_item("Light Ball") and "Pikachu" in attacker.name:
        mods.append(8192)
        desc["attackerItem"] = attacker.item

    return mods


def calculate_defense(attacker: Mon, defender: Mon, move: MoveState, field: FieldState, desc: dict, is_critical: bool = False) -> int:
    hits_physical = move.override_defensive_stat == "def" or move.category == "Physical"
    defense_stat = "def" if hits_physical else "spd"
    desc["defenseEVs"] = get_stat_description_text(defender, defense_stat, field.defender_side.is_power_trick, field.is_wonder_room)
    if field.defender_side.is_power_trick and (field.is_wonder_room != hits_physical):
        desc["isPowerTrickDefender"] = True

    boosts = defender.boosts[defense_stat]
    if boosts == 0 or (is_critical and boosts > 0) or move.ignore_defensive:
        defense = defender.raw_stats[defense_stat]
    elif attacker.has_ability("Unaware"):
        defense = defender.raw_stats[defense_stat]
        desc["attackerAbility"] = attacker.ability
    else:
        defense = get_modified_stat(defender.raw_stats[defense_stat], boosts)
        desc["defenseBoost"] = boosts

    if not attacker.has_ability("Mega Sol"):
        if field.has_weather("Sand") and defender.has_type("Rock") and not hits_physical:
            defense = poke_round((defense * 3) / 2)
            desc["weather"] = field.weather
        if field.has_weather("Snow") and defender.has_type("Ice") and hits_physical:
            defense = poke_round((defense * 3) / 2)
            desc["weather"] = field.weather

    df_mods = calculate_df_mods(attacker, defender, move, field, desc, is_critical, hits_physical)
    return int(of16(max(1, poke_round((defense * chain_mods(df_mods, 410, 131072)) / 4096))))


def calculate_df_mods(attacker: Mon, defender: Mon, move: MoveState, field: FieldState, desc: dict, is_critical: bool, hits_physical: bool) -> list[int]:
    mods: list[int] = []
    if defender.has_ability("Marvel Scale") and defender.status and hits_physical:
        mods.append(6144)
        desc["defenderAbility"] = defender.ability
    elif defender.has_ability("Fur Coat") and hits_physical:
        mods.append(8192)
        desc["defenderAbility"] = defender.ability
    return mods


def calculate_base_damage(attacker: Mon, defender: Mon, base_power: int, attack: int, defense: int, move: MoveState, field: FieldState,
                          desc: dict, is_critical: bool = False) -> int:
    base = get_base_damage(attacker.level, base_power, attack, defense)
    is_spread = field.game_type != "Singles" and move.target in ("allAdjacent", "allAdjacentFoes")
    if is_spread:
        base = poke_round(of32(base * 3072) / 4096)
    if attacker.has_ability("Parental Bond (Child)"):
        base = poke_round(of32(base * 1024) / 4096)

    is_mega_sol = attacker.has_ability("Mega Sol")
    if ((field.has_weather("Sun") or is_mega_sol) and move.has_type("Fire")) or (field.has_weather("Rain") and not is_mega_sol and move.has_type("Water")):
        base = poke_round(of32(base * 6144) / 4096)
        if is_mega_sol:
            desc["attackerAbility"] = attacker.ability
        else:
            desc["weather"] = field.weather
    elif ((field.has_weather("Sun") or is_mega_sol) and move.has_type("Water")) or (field.has_weather("Rain") and move.has_type("Fire")):
        base = poke_round(of32(base * 2048) / 4096)
        if is_mega_sol:
            desc["attackerAbility"] = attacker.ability
        else:
            desc["weather"] = field.weather

    if is_critical:
        base = math.floor(of32(base * 1.5))
        desc["isCritical"] = is_critical
    return int(base)


def calculate_final_mods(attacker: Mon, defender: Mon, move: MoveState, field: FieldState, desc: dict, is_critical: bool,
                         type_effectiveness: float, hit_count: int = 0) -> list[int]:
    mods: list[int] = []
    side = field.defender_side
    doubles = field.game_type != "Singles"

    if side.is_reflect and move.category == "Physical" and not is_critical and not side.is_aurora_veil:
        mods.append(2732 if doubles else 2048)
        desc["isReflect"] = True
    elif side.is_light_screen and move.category == "Special" and not is_critical and not side.is_aurora_veil:
        mods.append(2732 if doubles else 2048)
        desc["isLightScreen"] = True
    if side.is_aurora_veil and not is_critical:
        mods.append(2732 if doubles else 2048)
        desc["isAuroraVeil"] = True

    if attacker.has_ability("Sniper") and is_critical:
        mods.append(6144)
        desc["attackerAbility"] = attacker.ability

    if (defender.has_ability("Multiscale") and defender.cur_hp() == defender.max_hp() and hit_count == 0
            and (not side.is_sr and (not side.spikes or defender.has_type("Flying")))
            and not attacker.has_ability("Parental Bond (Child)")):
        mods.append(2048)
        desc["defenderAbility"] = defender.ability

    if defender.has_ability("Fluffy") and move.flags.get("contact") and not attacker.has_ability("Long Reach"):
        mods.append(2048)
        desc["defenderAbility"] = defender.ability

    if defender.has_ability("Solid Rock", "Filter") and type_effectiveness > 1:
        mods.append(3072)
        desc["defenderAbility"] = defender.ability

    if side.is_friend_guard:
        mods.append(3072)
        desc["isFriendGuard"] = True

    if defender.has_ability("Fluffy") and move.has_type("Fire"):
        mods.append(8192)
        desc["defenderAbility"] = defender.ability

    if attacker.has_item("Expert Belt") and type_effectiveness > 1:
        mods.append(4915)
        desc["attackerItem"] = attacker.item
    elif attacker.has_item("Life Orb"):
        mods.append(5324)
        desc["attackerItem"] = attacker.item
    elif attacker.has_item("Metronome") and move.times_used_with_metronome >= 1:
        n = math.floor(move.times_used_with_metronome)
        mods.append(4096 + n * 819 if n <= 4 else 8192)
        desc["attackerItem"] = attacker.item

    if (move.has_type(berry_resist_type(defender.item)) and (type_effectiveness > 1 or move.has_type("Normal"))
            and hit_count == 0 and not attacker.has_ability("Unnerve")):
        mods.append(1024 if defender.has_ability("Ripen") else 2048)
        desc["defenderItem"] = defender.item

    return mods

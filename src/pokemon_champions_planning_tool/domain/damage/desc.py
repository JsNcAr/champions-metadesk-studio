"""Result text — port of ``desc.ts``: the "32+ Atk Life Orb Kingambit Kowtow Cleave vs. 32 HP /
32+ Def Incineroar: 120-142 (60.1 - 71.2%) -- guaranteed 2HKO" line, recovery and recoil."""

from __future__ import annotations

import math

from .jsmath import js_round
from .ko import DescError, get_ko_chance
from .result_util import damage_range, multi_damage_range
from .state import FieldState, Mon, MoveState


def to_display(notation: str, a: float, b: float, f: float = 1) -> float | int:
    if notation == "%":
        return math.floor((a * (1000 / f)) / b) / 10
    return math.floor((a * (48 / f)) / b)


def fmt(x: float | int) -> str:
    """JavaScript number → string: integers without a decimal point."""
    if isinstance(x, int):
        return str(x)
    return str(int(x)) if float(x).is_integer() else repr(float(x))


def get_description_levels(attacker: Mon, defender: Mon) -> tuple[str, str]:
    if attacker.level != defender.level:
        return ("" if attacker.level == 100 else f"Lvl {attacker.level}", "" if defender.level == 100 else f"Lvl {defender.level}")
    level = "" if attacker.level in (100, 50, 5) else f"Lvl {attacker.level}"
    return level, level


def _append_if_set(text: str, value) -> str:
    return f"{text}{value} " if value else text


def build_description(d: dict, attacker: Mon, defender: Mon) -> str:
    attacker_level, defender_level = get_description_levels(attacker, defender)
    out = ""
    if d.get("attackBoost"):
        if d["attackBoost"] > 0:
            out += "+"
        out += f"{d['attackBoost']} "
    out = _append_if_set(out, attacker_level)
    out = _append_if_set(out, d.get("attackEVs"))
    out = _append_if_set(out, d.get("attackerItem"))
    out = _append_if_set(out, d.get("attackerAbility"))
    out = _append_if_set(out, d.get("rivalry"))
    if d.get("isBurned"):
        out += "burned "
    if d.get("alliesFainted"):
        n = d["alliesFainted"]
        out += f"{min(5, n)} {'ally' if n == 1 else 'allies'} fainted "
    out += f"{d['attackerName']} "
    if d.get("isHelpingHand"):
        out += "Helping Hand "
    if d.get("isPowerTrickAttacker"):
        out += "with Power Trick "
    if d.get("isSwitching"):
        out += "switching boosted "
    if d.get("isCharge"):
        out += "Charge boosted "
    out += f"{d['moveName']} "
    if d.get("moveBP") and d.get("moveType"):
        out += f"({fmt(d['moveBP'])} BP {d['moveType']}) "
    elif d.get("moveBP"):
        out += f"({fmt(d['moveBP'])} BP) "
    elif d.get("moveType"):
        out += f"({d['moveType']}) "
    if d.get("hits"):
        out += f"({d['hits']} hits) "
    out = _append_if_set(out, d.get("moveTurns"))
    out += "vs. "
    if d.get("defenseBoost"):
        if d["defenseBoost"] > 0:
            out += "+"
        out += f"{d['defenseBoost']} "
    out = _append_if_set(out, defender_level)
    out = _append_if_set(out, d.get("HPEVs"))
    if d.get("defenseEVs"):
        out += f"/ {d['defenseEVs']} "
    out = _append_if_set(out, d.get("defenderItem"))
    out = _append_if_set(out, d.get("defenderAbility"))
    if d.get("isProtected"):
        out += "protected "
    out += d["defenderName"]
    if d.get("weather") and d.get("terrain"):
        out += f" in {d['weather']} and {d['terrain']} Terrain"
    elif d.get("weather"):
        out += f" in {d['weather']}"
    elif d.get("terrain"):
        out += f" in {d['terrain']} Terrain"
    if d.get("isReflect"):
        out += " through Reflect"
    elif d.get("isLightScreen"):
        out += " through Light Screen"
    if d.get("isPowerTrickDefender"):
        out += " with Power Trick"
    if d.get("isFriendGuard"):
        out += " with an ally's Friend Guard"
    if d.get("isAuroraVeil"):
        out += " with an ally's Aurora Veil"
    if d.get("isCritical"):
        out += " on a critical hit"
    if d.get("isWonderRoom"):
        out += " in Wonder Room"
    return out


def display(attacker: Mon, defender: Mon, move: MoveState, field: FieldState, damage, raw_desc: dict, notation: str = "%") -> str:
    lo, hi = damage_range(damage)
    min_display = to_display(notation, lo, defender.max_hp())
    max_display = to_display(notation, hi, defender.max_hp())
    desc = build_description(raw_desc, attacker, defender)
    damage_text = f"{lo}-{hi} ({fmt(min_display)} - {fmt(max_display)}{notation})"
    if move.category == "Status" and not move.named("Nature Power"):
        return f"{desc}: {damage_text}"
    ko_text = get_ko_chance(attacker, defender, move, field, damage).text
    return f"{desc}: {damage_text} -- {ko_text}" if ko_text else f"{desc}: {damage_text}"


def display_move(attacker: Mon, defender: Mon, move: MoveState, damage, notation: str = "%") -> str:
    lo, hi = damage_range(damage)
    min_display = to_display(notation, lo, defender.max_hp())
    max_display = to_display(notation, hi, defender.max_hp())
    recovery_text = get_recovery(attacker, defender, move, damage, notation)[1]
    recoil_text = get_recoil(attacker, defender, move, damage, notation)[1]
    text = f"{fmt(min_display)} - {fmt(max_display)}{notation}"
    if recovery_text:
        text += f" ({recovery_text})"
    if recoil_text:
        text += f" ({recoil_text})"
    return text


def _as_lists(pair) -> tuple[list, list]:
    """``multiDamageRange`` returns numbers for single-hit damage; iterating them in JS yields
    nothing, so they become empty lists here."""
    lo, hi = pair
    return (list(lo) if isinstance(lo, list) else []), (list(hi) if isinstance(hi, list) else [])


def get_recovery(attacker: Mon, defender: Mon, move: MoveState, damage, notation: str = "%") -> tuple[list, str]:
    lo, hi = damage_range(damage)
    if move.times_used and move.times_used > 1:
        min_d, max_d = _as_lists(multi_damage_range(damage))
    else:
        min_d, max_d = [lo], [hi]
    recovery: list = [0, 0]
    text = ""
    if attacker.has_item("Shell Bell"):
        for i in range(len(min_d)):
            recovery[0] += max(js_round(min_d[i] / 8), 1) if min_d[i] > 0 else 0
            recovery[1] += max(js_round(max_d[i] / 8), 1) if max_d[i] > 0 else 0
        max_healing = js_round(defender.cur_hp() / 8)
        recovery[0] = min(recovery[0], max_healing)
        recovery[1] = min(recovery[1], max_healing)
    if move.named("Pain Split"):
        average = math.floor((attacker.cur_hp() + defender.cur_hp()) / 2)
        recovery[0] = recovery[1] = average - attacker.cur_hp()
    if move.drain:
        if attacker.has_ability("Parental Bond") or move.hits > 1:
            min_d, max_d = _as_lists(multi_damage_range(damage))
        percent = move.drain[0] / move.drain[1]
        big_root = attacker.has_item("Big Root")
        max_drain = js_round(defender.cur_hp() * percent)
        if big_root:
            max_drain = math.trunc(max_drain * 5324 / 4096)
        for i in range(len(min_d)):
            for j, value in enumerate((min_d[i], max_d[i])):
                drained = max(js_round(value * percent), 1)
                if big_root:
                    drained = math.trunc(drained * 5324 / 4096)
                recovery[j] += min(drained, max_drain)
    if recovery[1] == 0:
        return recovery, text
    min_hr = to_display(notation, recovery[0], attacker.max_hp())
    max_hr = to_display(notation, recovery[1], attacker.max_hp())
    change = "recovered" if recovery[0] > 0 else "lost"
    text = f"{fmt(min_hr)} - {fmt(max_hr)}{notation} {change}"
    return recovery, text


def get_recoil(attacker: Mon, defender: Mon, move: MoveState, damage, notation: str = "%") -> tuple[list | float | int, str]:
    lo, hi = damage_range(damage)
    recoil: list | float | int = [0, 0]
    text = ""
    overflow = lo > defender.cur_hp() or hi > defender.cur_hp()
    if move.recoil:
        mod = (move.recoil[0] / move.recoil[1]) * 100
        if overflow:
            min_r = to_display(notation, defender.cur_hp() * mod, attacker.max_hp(), 100)
            max_r = to_display(notation, defender.cur_hp() * mod, attacker.max_hp(), 100)
        else:
            min_r = to_display(notation, min(lo, defender.cur_hp()) * mod, attacker.max_hp(), 100)
            max_r = to_display(notation, min(hi, defender.cur_hp()) * mod, attacker.max_hp(), 100)
        if not attacker.has_ability("Rock Head"):
            recoil = [min_r, max_r]
            text = f"{fmt(min_r)} - {fmt(max_r)}{notation} recoil damage"
    elif move.has_crash_damage:
        recoil = 24 if notation == "%" else 50
        text = "50% crash damage"
    elif move.struggle_recoil:
        recoil = 12 if notation == "%" else 25
        text = "25% struggle damage"
    elif move.mind_blown_recoil:
        recoil = 24 if notation == "%" else 50
        text = "50% recoil damage"
    return recoil, text


__all__ = ["DescError", "build_description", "display", "display_move", "fmt", "get_recoil", "get_recovery", "to_display"]

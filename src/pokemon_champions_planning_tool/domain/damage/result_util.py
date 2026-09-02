"""Damage-shape helpers (``result.ts``): fixed, 16 rolls, Parental Bond pair, or a matrix."""

from __future__ import annotations


def multi_damage_range(damage) -> tuple:
    if isinstance(damage, int):
        return damage, damage
    if not isinstance(damage[0], int):
        lows = [d[0] for d in damage]
        highs = [d[-1] for d in damage]
        return lows, highs
    if len(damage) < 16:
        return list(damage), list(damage)
    return damage[0], damage[-1]


def damage_range(damage) -> tuple[int, int]:
    lo, hi = multi_damage_range(damage)
    if isinstance(lo, int):
        return lo, hi
    return sum(lo), sum(hi)

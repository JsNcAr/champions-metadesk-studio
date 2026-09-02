"""Integer and rounding helpers that reproduce the reference calculator's JavaScript maths.

The Smogon calculator runs on JS doubles with explicit 16- and 32-bit overflow emulation and
Game Freak's "round half down". Python ints are unbounded, so every overflow site in the port
calls ``of16``/``of32`` exactly where the TypeScript does, and every ``Math.round`` becomes
``js_round`` (JS rounds .5 up, Python's ``round`` is banker's rounding).
"""

from __future__ import annotations

import math


def poke_round(value: float) -> int:
    """Game Freak rounds *down* on exactly .5 (``pokeRound`` in the reference)."""
    frac = value % 1
    return math.ceil(value) if frac > 0.5 else math.floor(value)


def js_round(value: float) -> int:
    """JavaScript ``Math.round``: halves round towards +∞."""
    return math.floor(value + 0.5)


def js_trunc(value: float) -> int:
    """JavaScript ``Math.trunc``."""
    return math.trunc(value)


def of16(n: int | float) -> int | float:
    """16-bit overflow: ``n > 65535 ? n % 65536 : n``."""
    return n % 65536 if n > 65535 else n


def of32(n: int | float) -> int | float:
    """32-bit overflow: ``n > 4294967295 ? n % 4294967296 : n``."""
    return n % 4294967296 if n > 4294967295 else n


def js_shr12(n: int) -> int:
    """``n >> 12`` on a JS int32 (the operand is first truncated to 32 bits, sign included)."""
    n = int(n) & 0xFFFFFFFF
    if n >= 0x80000000:
        n -= 0x100000000
    return n >> 12


def chain_mods(mods: list[int], lower_bound: int, upper_bound: int) -> int:
    """Chain 4096-based modifiers the way the games do (``chainMods`` in the reference)."""
    m = 4096
    for mod in mods:
        if mod != 4096:
            m = js_shr12(m * mod + 2048)
    return max(min(m, upper_bound), lower_bound)

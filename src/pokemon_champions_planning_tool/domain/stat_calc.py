"""Battle stat calculation: natures, the level-50 formula, and spread validation.

Pure functions. Stat keys are the ``PokemonStats`` field names: ``hp``, ``attack``,
``defense``, ``special_attack``, ``special_defense``, ``speed``. EV/IV dicts may be
sparse — a missing EV is 0 and a missing IV is 31, matching the persistence layer.
"""

from __future__ import annotations

from collections.abc import Mapping

from .entities.pokemon_stats import PokemonStats

STAT_KEYS: tuple[str, ...] = ("hp", "attack", "defense", "special_attack", "special_defense", "speed")

MAX_EV_PER_STAT = 252
MAX_EV_TOTAL = 510
MAX_IV = 31
DEFAULT_LEVEL = 50

# nature -> (boosted stat, hindered stat); neutral natures map to (None, None).
NATURES: dict[str, tuple[str | None, str | None]] = {
    "hardy": (None, None),
    "lonely": ("attack", "defense"),
    "brave": ("attack", "speed"),
    "adamant": ("attack", "special_attack"),
    "naughty": ("attack", "special_defense"),
    "bold": ("defense", "attack"),
    "docile": (None, None),
    "relaxed": ("defense", "speed"),
    "impish": ("defense", "special_attack"),
    "lax": ("defense", "special_defense"),
    "timid": ("speed", "attack"),
    "hasty": ("speed", "defense"),
    "serious": (None, None),
    "jolly": ("speed", "special_attack"),
    "naive": ("speed", "special_defense"),
    "modest": ("special_attack", "attack"),
    "mild": ("special_attack", "defense"),
    "quiet": ("special_attack", "speed"),
    "bashful": (None, None),
    "rash": ("special_attack", "special_defense"),
    "calm": ("special_defense", "attack"),
    "gentle": ("special_defense", "defense"),
    "sassy": ("special_defense", "speed"),
    "careful": ("special_defense", "special_attack"),
    "quirky": (None, None),
}

NEUTRAL_NATURES: frozenset[str] = frozenset(n for n, (up, down) in NATURES.items() if up is None)


def nature_multiplier(nature: str | None, stat: str) -> float:
    """1.1 for the boosted stat, 0.9 for the hindered one, else 1.0.

    Raises ``ValueError`` for an unknown nature so typos never silently become neutral.
    """
    if not nature:
        return 1.0
    key = nature.strip().lower()
    if key not in NATURES:
        raise ValueError(f"unknown nature: {nature!r}")
    up, down = NATURES[key]
    if stat == up:
        return 1.1
    if stat == down:
        return 0.9
    return 1.0


def nature_label(nature: str) -> str:
    """'Timid (+Spe −Atk)' for menus; neutral natures get '(neutral)'."""
    key = nature.strip().lower()
    up, down = NATURES.get(key, (None, None))
    abbrev = {"hp": "HP", "attack": "Atk", "defense": "Def", "special_attack": "SpA", "special_defense": "SpD", "speed": "Spe"}
    suffix = "(neutral)" if up is None else f"(+{abbrev[up]} −{abbrev[down]})"
    return f"{key.capitalize()} {suffix}"


def calc_hp(base: int, iv: int = MAX_IV, ev: int = 0, level: int = DEFAULT_LEVEL) -> int:
    """HP = floor((2·B + IV + floor(EV/4)) · L / 100) + L + 10. Shedinja is always 1."""
    if base == 1:
        return 1
    return (2 * base + iv + ev // 4) * level // 100 + level + 10


def calc_stat(base: int, iv: int = MAX_IV, ev: int = 0, level: int = DEFAULT_LEVEL, nature_mult: float = 1.0) -> int:
    """Non-HP stat = floor((floor((2·B + IV + floor(EV/4)) · L / 100) + 5) · nature)."""
    inner = (2 * base + iv + ev // 4) * level // 100 + 5
    return int(inner * nature_mult)


def calc_all(
    base: PokemonStats,
    evs: Mapping[str, int] | None = None,
    ivs: Mapping[str, int] | None = None,
    nature: str | None = None,
    level: int = DEFAULT_LEVEL,
) -> PokemonStats:
    """Actual stats at ``level`` for the given spread."""
    evs = evs or {}
    ivs = ivs or {}
    values: dict[str, int] = {}
    for key in STAT_KEYS:
        b = getattr(base, key)
        iv = int(ivs.get(key, MAX_IV))
        ev = int(evs.get(key, 0))
        if key == "hp":
            values[key] = calc_hp(b, iv, ev, level)
        else:
            values[key] = calc_stat(b, iv, ev, level, nature_multiplier(nature, key))
    return PokemonStats(**values)


def ev_total(evs: Mapping[str, int] | None) -> int:
    return sum(int(v) for v in (evs or {}).values())


def validate_spread(evs: Mapping[str, int] | None, ivs: Mapping[str, int] | None, level: int = DEFAULT_LEVEL) -> list[str]:
    """Human-readable problems with a spread; empty when it is legal."""
    problems: list[str] = []
    evs = evs or {}
    ivs = ivs or {}
    for key, value in evs.items():
        if key not in STAT_KEYS:
            problems.append(f"Unknown stat '{key}' in EVs")
        elif not 0 <= int(value) <= MAX_EV_PER_STAT:
            problems.append(f"{key} EVs must be 0–{MAX_EV_PER_STAT} (got {value})")
    total = ev_total(evs)
    if total > MAX_EV_TOTAL:
        problems.append(f"EV total {total} exceeds {MAX_EV_TOTAL}")
    for key, value in ivs.items():
        if key not in STAT_KEYS:
            problems.append(f"Unknown stat '{key}' in IVs")
        elif not 0 <= int(value) <= MAX_IV:
            problems.append(f"{key} IVs must be 0–{MAX_IV} (got {value})")
    if not 1 <= int(level) <= 100:
        problems.append(f"Level must be 1–100 (got {level})")
    return problems

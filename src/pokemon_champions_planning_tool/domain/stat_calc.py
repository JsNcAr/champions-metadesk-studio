"""Battle stat calculation for Pokémon Champions: natures, stat points, spread validation.

Champions has no EVs or IVs. Every Pokémon is level 50 with 31 IVs, and the player spends
**stat points** instead: 0–32 per stat, 66 per Pokémon. The formula (Showdown's
``mods/champions`` and the Smogon calculator) is::

    HP    = base + points + 75            (base 1 → 1, Shedinja)
    other = floor(nature × (base + points + 20))

Pure functions. Stat keys are the ``PokemonStats`` field names: ``hp``, ``attack``,
``defense``, ``special_attack``, ``special_defense``, ``speed``. Point dicts may be sparse —
a missing stat has 0 points, matching the persistence layer.

The mainline level formula (``calc_stat``/``calc_hp``/``calc_all``) is kept as the reference
that ``points_from_evs`` is proven against: at level 50 with 31 IVs a mainline stat equals
``base + 15 + (EV + 4) // 8``, so legacy EV spreads convert to points without changing any stat.
"""

from __future__ import annotations

from collections.abc import Mapping

from .entities.pokemon_stats import PokemonStats

STAT_KEYS: tuple[str, ...] = ("hp", "attack", "defense", "special_attack", "special_defense", "speed")
STAT_ABBREV: dict[str, str] = {"hp": "HP", "attack": "Atk", "defense": "Def", "special_attack": "SpA", "special_defense": "SpD", "speed": "Spe"}

# Pokémon Champions rules
MAX_POINTS_PER_STAT = 32
MAX_POINTS_TOTAL = 66
CHAMPIONS_LEVEL = 50   # fixed; IVs are 31 and cannot be changed

# Mainline reference formula only (legacy EV spreads are converted with ``points_from_evs``).
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
    suffix = "(neutral)" if up is None else f"(+{STAT_ABBREV[up]} −{STAT_ABBREV[down]})"
    return f"{key.capitalize()} {suffix}"


# --- Pokémon Champions: stat points ---------------------------------------------------------


def champions_stat(base: int, points: int = 0, nature_mult: float = 1.0, *, hp: bool = False) -> int:
    """One stat under Champions rules (level 50, 31 IVs, ``points`` invested).

    Integer maths throughout: the nature multiplier is applied as ×11/10, ×9/10 or ×1 and
    floored, exactly like the game (and the Smogon calculator's ``calcStatChampions``).
    """
    if hp:
        return 1 if base == 1 else base + int(points) + 75
    inner = base + int(points) + 20
    if nature_mult > 1.0:
        return inner * 11 // 10
    if nature_mult < 1.0:
        return inner * 9 // 10
    return inner


def champions_stats(base: PokemonStats, points: Mapping[str, int] | None = None, nature: str | None = None) -> PokemonStats:
    """Actual battle stats for a Champions spread."""
    points = points or {}
    values: dict[str, int] = {}
    for key in STAT_KEYS:
        b = getattr(base, key)
        p = int(points.get(key, 0))
        if key == "hp":
            values[key] = champions_stat(b, p, hp=True)
        else:
            values[key] = champions_stat(b, p, nature_multiplier(nature, key))
    return PokemonStats(**values)


def points_total(points: Mapping[str, int] | None) -> int:
    return sum(int(v) for v in (points or {}).values())


def points_left(points: Mapping[str, int] | None) -> int:
    """Unspent points; negative when the spread is over budget."""
    return MAX_POINTS_TOTAL - points_total(points)


def validate_points(points: Mapping[str, int] | None) -> list[str]:
    """Human-readable problems with a stat-point spread; empty when it is legal."""
    problems: list[str] = []
    for key, value in (points or {}).items():
        if key not in STAT_KEYS:
            problems.append(f"Unknown stat '{key}' in stat points")
        elif not 0 <= int(value) <= MAX_POINTS_PER_STAT:
            problems.append(f"{STAT_ABBREV[key]} points must be 0–{MAX_POINTS_PER_STAT} (got {value})")
    total = points_total(points)
    if total > MAX_POINTS_TOTAL:
        problems.append(f"Stat points total {total} exceeds {MAX_POINTS_TOTAL}")
    return problems


def points_from_evs(evs: Mapping[str, int] | None) -> dict[str, int]:
    """Convert a mainline EV spread to Champions stat points without changing any stat.

    ``(EV + 4) // 8`` — the level-50 stat is ``base + 15 + (EV + 4) // 8`` with 31 IVs, and this
    is also Showdown's HOME-transfer mapping (4 EVs for the first point, 8 for each further one).
    Values are clamped to 32; zero-point stats are dropped.
    """
    points: dict[str, int] = {}
    for key, value in (evs or {}).items():
        if key not in STAT_KEYS:
            continue
        p = min(MAX_POINTS_PER_STAT, (max(0, int(value)) + 4) // 8)
        if p > 0:
            points[key] = p
    return points


def format_points(points: Mapping[str, int] | None) -> str:
    """'32 Atk / 32 Spe / 2 HP' in stat order, non-zero only; '' when nothing is invested."""
    order = ("hp", "attack", "defense", "special_attack", "special_defense", "speed")
    parts = [f"{int(v)} {STAT_ABBREV[k]}" for k in order for v in [(points or {}).get(k, 0)] if int(v) > 0]
    return " / ".join(parts)


# --- Mainline reference formula (level-based, EV/IV) ------------------------------------------


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

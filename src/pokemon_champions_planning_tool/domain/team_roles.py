"""Team roles: what a team brings (speed control, Fake Out, Intimidate, redirection…).

Pure. Each member is described by its moves, ability and item; the checklist says, per role,
which members provide it. A missing role is information, not an error: a team without
redirection may simply not want it. Doubles-only roles are skipped for singles formats.
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass
from typing import Any, Literal

from .moves import move_key

Status = Literal["ok", "missing", "info"]


@dataclass(frozen=True)
class RoleMember:
    slot: int
    name: str
    moves: tuple[Any, ...] = ()        # MoveInfo (preferred: target and priority) or plain move names
    ability: str | None = None
    item: str | None = None


@dataclass(frozen=True)
class RoleCheck:
    key: str
    label: str
    status: Status
    providers: tuple[str, ...]          # member names, in slot order
    note: str


def _keys(*names: str) -> frozenset[str]:
    return frozenset(move_key(n) for n in names)


SPEED_CONTROL = _keys("Tailwind", "Trick Room", "Icy Wind", "Electroweb", "Thunder Wave", "Scary Face", "Bulldoze", "Rock Tomb",
                      "String Shot", "Glare", "Nuzzle", "Bitter Malice", "Low Sweep", "Cotton Spore")
FAKE_OUT = _keys("Fake Out")
REDIRECTION = _keys("Follow Me", "Rage Powder", "Spotlight", "Ally Switch")
PIVOT = _keys("U-turn", "Volt Switch", "Flip Turn", "Parting Shot", "Teleport", "Baton Pass", "Chilly Reception", "Shed Tail")
SETUP = _keys("Swords Dance", "Nasty Plot", "Dragon Dance", "Calm Mind", "Bulk Up", "Quiver Dance", "Shell Smash", "Belly Drum",
              "Coil", "Iron Defense", "Agility", "Shift Gear", "Victory Dance", "Tidy Up", "Growth", "Work Up", "Curse")
PROTECT = _keys("Protect", "Detect", "Spiky Shield", "King's Shield", "Baneful Bunker", "Silk Trap", "Burning Bulwark", "Obstruct")
SUPPORT = _keys("Helping Hand", "Wide Guard", "Quick Guard", "Reflect", "Light Screen", "Aurora Veil", "Coaching", "Life Dew",
                "Pollen Puff", "Heal Pulse", "Decorate", "Instruct", "Taunt", "Encore", "Will-O-Wisp", "Spore", "Sleep Powder")
WEATHER_MOVES = _keys("Sunny Day", "Rain Dance", "Sandstorm", "Snowscape", "Hail")
TERRAIN_MOVES = _keys("Electric Terrain", "Grassy Terrain", "Psychic Terrain", "Misty Terrain")
WEATHER_ABILITIES = frozenset({"drought", "drizzle", "sand stream", "snow warning", "orichalcum pulse", "desolate land", "primordial sea", "mega sol"})
TERRAIN_ABILITIES = frozenset({"electric surge", "grassy surge", "psychic surge", "misty surge", "hadron engine", "seed sower"})
INTIMIDATE = frozenset({"intimidate"})
SPREAD_TARGETS = frozenset({"allAdjacentFoes", "allAdjacent"})
DOUBLES_ONLY = frozenset({"fake_out", "redirection", "spread", "support"})
RECOMMENDED_PROTECT = 4                 # doubles teams usually carry Protect on four or more


def _move_name(move: Any) -> str:
    return getattr(move, "name", None) or (move if isinstance(move, str) else "")


def _has(member: RoleMember, keys: frozenset[str]) -> bool:
    return any(move_key(_move_name(m)) in keys for m in member.moves if m)


def team_roles(members: Sequence[RoleMember], *, doubles: bool = True) -> list[RoleCheck]:
    def who(predicate) -> tuple[str, ...]:
        return tuple(m.name for m in sorted(members, key=lambda m: m.slot) if predicate(m))

    def ability(member: RoleMember) -> str:
        return (member.ability or "").replace("-", " ").strip().lower()

    def spread(member: RoleMember) -> bool:
        return any(getattr(m, "target", None) in SPREAD_TARGETS and (getattr(m, "category", "") or "").lower() != "status"
                   for m in member.moves if m)

    def priority(member: RoleMember) -> bool:
        return any((getattr(m, "priority", 0) or 0) > 0 and (getattr(m, "category", "") or "").lower() != "status"
                   and move_key(_move_name(m)) not in FAKE_OUT for m in member.moves if m)

    checks: list[RoleCheck] = []

    def add(key: str, label: str, providers: tuple[str, ...], missing_note: str, ok_note: str = "") -> None:
        if not doubles and key in DOUBLES_ONLY:
            return
        status: Status = "ok" if providers else "missing"
        checks.append(RoleCheck(key, label, status, providers, ok_note if providers else missing_note))

    add("speed_control", "Speed control", who(lambda m: _has(m, SPEED_CONTROL)),
        "Nothing changes speed order: no Tailwind, Trick Room, Icy Wind, Electroweb or paralysis.")
    add("fake_out", "Fake Out", who(lambda m: _has(m, FAKE_OUT)), "No Fake Out to buy a free turn.")
    add("intimidate", "Intimidate", who(lambda m: ability(m) in INTIMIDATE), "No Intimidate to weaken physical attackers.")
    add("redirection", "Redirection", who(lambda m: _has(m, REDIRECTION)), "No Follow Me or Rage Powder to protect a partner.")
    add("weather", "Weather", who(lambda m: ability(m) in WEATHER_ABILITIES or _has(m, WEATHER_MOVES)), "No weather setter.")
    add("terrain", "Terrain", who(lambda m: ability(m) in TERRAIN_ABILITIES or _has(m, TERRAIN_MOVES)), "No terrain setter.")
    add("priority", "Priority", who(priority), "No priority attacks to finish weakened threats.")
    add("spread", "Spread damage", who(spread), "No moves that hit both foes.")
    add("pivot", "Pivoting", who(lambda m: _has(m, PIVOT)), "No U-turn, Parting Shot or Volt Switch to switch safely.")
    add("setup", "Setup", who(lambda m: _has(m, SETUP)), "No boosting moves.")
    add("support", "Support", who(lambda m: _has(m, SUPPORT)), "No Helping Hand, Wide Guard, screens or status support.")

    protectors = who(lambda m: _has(m, PROTECT))
    if members:
        target = RECOMMENDED_PROTECT if doubles else 0
        note = f"{len(protectors)} of {len(members)} carry Protect or a variant"
        if doubles and len(protectors) < target:
            note += f"; doubles teams usually run it on {target} or more"
        checks.append(RoleCheck("protect", "Protect", "ok" if len(protectors) >= target else "info", protectors, note))
    return checks


__all__ = ["RECOMMENDED_PROTECT", "RoleCheck", "RoleMember", "team_roles"]

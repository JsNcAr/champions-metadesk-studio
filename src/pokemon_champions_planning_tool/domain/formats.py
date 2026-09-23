"""Battle formats and the generation mechanics they allow.

A format is the rule set a team is built for: singles or doubles, which regulations it
covers, and which generation mechanics exist in it. Champions' Regulations M-A to M-C
have Mega Evolution and nothing else, so the team builder shows no Terastallization,
Z-Move or Dynamax controls for them. Custom formats (see ``ui/formats.py``) switch
mechanics on for other rule sets.

Adding a mechanic later: give it ``implemented=True`` below and register a control for
it in the team builder's mechanic-controls table; formats and settings pick it up.
"""

from __future__ import annotations

from dataclasses import dataclass, field, replace
from enum import StrEnum
from typing import Any


class Mechanic(StrEnum):
    MEGA = "mega"
    TERA = "tera"
    Z_MOVE = "z_move"
    DYNAMAX = "dynamax"


@dataclass(frozen=True)
class MechanicInfo:
    label: str
    description: str
    implemented: bool      # the app has controls for it; the others are listed as "not supported yet"


MECHANICS: dict[Mechanic, MechanicInfo] = {
    Mechanic.MEGA: MechanicInfo("Mega Evolution", "A Pokémon holding its Mega Stone evolves in battle.", True),
    Mechanic.TERA: MechanicInfo("Terastallization", "Each Pokémon has a Tera Type it can change into once per battle.", True),
    Mechanic.Z_MOVE: MechanicInfo("Z-Moves", "A Pokémon holding a Z-Crystal can use one Z-Move per battle.", False),
    Mechanic.DYNAMAX: MechanicInfo("Dynamax", "One Pokémon per battle grows for three turns and uses Max Moves.", False),
}

GAME_TYPES: tuple[tuple[str, str], ...] = (("doubles", "Doubles"), ("singles", "Singles"))


@dataclass(frozen=True)
class Format:
    format_id: str
    name: str
    game_type: str = "doubles"                              # "doubles" | "singles"
    mechanics: frozenset[Mechanic] = frozenset()
    regulations: tuple[str, ...] = ()                        # normalised labels, e.g. "Regulation M-C"
    one_mega_per_team: bool = True
    item_clause: bool = True                                 # no two Pokémon hold the same item
    builtin: bool = False
    description: str = field(default="", compare=False)

    def has(self, mechanic: Mechanic) -> bool:
        return mechanic in self.mechanics

    @property
    def mechanics_label(self) -> str:
        """"Mega" / "Mega · Tera" / "No mechanics", in the registry's order."""
        names = [MECHANICS[m].label.split()[0] for m in MECHANICS if m in self.mechanics]
        return " · ".join(names) if names else "No mechanics"

    def to_dict(self) -> dict[str, Any]:
        return {
            "format_id": self.format_id, "name": self.name, "game_type": self.game_type,
            "mechanics": [m.value for m in MECHANICS if m in self.mechanics], "regulations": list(self.regulations),
            "one_mega_per_team": self.one_mega_per_team, "item_clause": self.item_clause, "description": self.description,
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "Format":
        known = {m.value for m in Mechanic}
        return cls(
            format_id=str(data["format_id"]), name=str(data.get("name") or "Custom format"),
            game_type="singles" if data.get("game_type") == "singles" else "doubles",
            mechanics=frozenset(Mechanic(m) for m in data.get("mechanics") or () if m in known),
            regulations=tuple(str(r) for r in data.get("regulations") or ()),
            one_mega_per_team=bool(data.get("one_mega_per_team", True)), item_clause=bool(data.get("item_clause", True)),
            description=str(data.get("description") or ""),
        )


CHAMPIONS_REGULATIONS = ("Regulation M-A", "Regulation M-B", "Regulation M-C")

BUILTIN_FORMATS: tuple[Format, ...] = (
    Format("champions-reg-m", "Champions · Regulations M-A to M-C", "doubles", frozenset({Mechanic.MEGA}), CHAMPIONS_REGULATIONS,
           builtin=True, description="Official Pokémon Champions doubles: level 50, stat points, Mega Evolution, one Mega per team."),
    Format("champions-reg-m-singles", "Champions · Regulations M-A to M-C (Singles)", "singles", frozenset({Mechanic.MEGA}), CHAMPIONS_REGULATIONS,
           builtin=True, description="The same rules, played one against one."),
)
DEFAULT_FORMAT_ID = BUILTIN_FORMATS[0].format_id


def builtin_format(format_id: str | None) -> Format | None:
    return next((f for f in BUILTIN_FORMATS if f.format_id == format_id), None)


def format_for_regulation(label: str | None, formats: tuple[Format, ...] | list[Format] = BUILTIN_FORMATS) -> Format | None:
    """The first format that covers a tournament regulation label (doubles first)."""
    if not label:
        return None
    return next((f for f in formats if label in f.regulations), None)


def custom_copy(base: Format, format_id: str, name: str) -> Format:
    """A custom format starting from ``base``'s rules."""
    return replace(base, format_id=format_id, name=name, builtin=False, description="")


__all__ = [
    "BUILTIN_FORMATS", "CHAMPIONS_REGULATIONS", "DEFAULT_FORMAT_ID", "Format", "GAME_TYPES", "MECHANICS", "Mechanic", "MechanicInfo",
    "builtin_format", "custom_copy", "format_for_regulation",
]

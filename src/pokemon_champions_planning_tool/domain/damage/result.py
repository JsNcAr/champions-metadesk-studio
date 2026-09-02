"""``DamageResult``: damage rolls plus the text the reference calculator produces."""

from __future__ import annotations

from dataclasses import dataclass

from .desc import display, display_move, get_recoil, get_recovery, to_display
from .ko import KOChance, get_ko_chance
from .result_util import damage_range, multi_damage_range
from .state import FieldState, Mon, MoveState


@dataclass
class DamageResult:
    """Post-calculation state: ``attacker``/``defender``/``move``/``field`` are the working
    copies the mechanics mutated (the description and KO chance read them)."""

    attacker: Mon
    defender: Mon
    move: MoveState
    field: FieldState
    damage: int | list[int] | list[list[int]]
    raw_desc: dict

    def range(self) -> tuple[int, int]:
        return damage_range(self.damage)

    def multi_range(self) -> tuple:
        return multi_damage_range(self.damage)

    def desc(self, notation: str = "%") -> str:
        return display(self.attacker, self.defender, self.move, self.field, self.damage, self.raw_desc, notation)

    def move_desc(self, notation: str = "%") -> str:
        return display_move(self.attacker, self.defender, self.move, self.damage, notation)

    def ko_chance(self) -> KOChance:
        return get_ko_chance(self.attacker, self.defender, self.move, self.field, self.damage)

    def recoil(self, notation: str = "%") -> tuple:
        return get_recoil(self.attacker, self.defender, self.move, self.damage, notation)

    def recovery(self, notation: str = "%") -> tuple:
        return get_recovery(self.attacker, self.defender, self.move, self.damage, notation)

    @property
    def min_pct(self) -> float:
        return float(to_display("%", self.range()[0], self.defender.max_hp()))

    @property
    def max_pct(self) -> float:
        return float(to_display("%", self.range()[1], self.defender.max_hp()))

    @property
    def rolls(self) -> list[int]:
        """The 16 rolls of a single hit (summed per roll index for multi-hit results)."""
        d = self.damage
        if isinstance(d, int):
            return [d] * 16
        if d and isinstance(d[0], list):
            return [sum(hit[i] for hit in d) for i in range(len(d[0]))]
        if len(d) == 2 and isinstance(d[0], int) and isinstance(d[1], int):
            return [d[0] + d[1]] * 16
        return list(d)

    @property
    def move_type(self) -> str:
        return self.move.type

    @property
    def move_bp(self) -> int | float:
        return self.raw_desc.get("moveBP") or self.move.bp

    @property
    def is_immune(self) -> bool:
        return self.range()[1] == 0 and self.move.category != "Status"

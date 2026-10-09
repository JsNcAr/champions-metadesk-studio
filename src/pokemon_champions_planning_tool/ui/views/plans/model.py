"""Plans: your matchup plans against opposing teams, as plain data. Flet- and DB-free.

A plan is what a team report's matchup entry holds: the opposing six, how hard it is, the
two you lead with and the two in the back, a written game plan, a note per threat and the
calcs it rests on. The app runs the calcs; the plan is the player's to write.
"""

from __future__ import annotations

from dataclasses import dataclass
from dataclasses import field as dc_field
from datetime import datetime

from ..calc.state import CalcState, FieldState, RivalMember

# Index 0 is "not rated"; 1..5 read like a team report's difficulty line.
DIFFICULTIES: tuple[str, ...] = ("Not rated", "Very easy", "Easy", "Medium", "Hard", "Very hard")
MAX_PICKS = 2   # Lead and Back: two each, as in Doubles; in Singles the first lead starts


def difficulty_label(value: int) -> str:
    return DIFFICULTIES[value] if 0 <= value < len(DIFFICULTIES) else DIFFICULTIES[0]


@dataclass(frozen=True)
class MemberRef:
    """A team member named by box entry (slot positions move when the team is reordered).

    ``species`` is the canonical id it had when picked: the label to fall back on once
    that Pokémon has left the team.
    """

    box_entry_id: str
    species: str = ""

    def to_dict(self) -> dict:
        return {"box_entry_id": self.box_entry_id, "species": self.species}

    @classmethod
    def from_dict(cls, data: dict | None) -> "MemberRef | None":
        d = dict(data or {})
        box_id = str(d.get("box_entry_id") or "")
        return cls(box_id, str(d.get("species") or "")) if box_id else None


@dataclass(frozen=True)
class Plan:
    plan_id: str
    team_id: str
    name: str
    source: str = ""
    difficulty: int = 0
    lead: tuple[MemberRef, ...] = ()
    back: tuple[MemberRef, ...] = ()
    game_plan: str = ""
    field: FieldState = dc_field(default_factory=FieldState)
    opponent: tuple[RivalMember, ...] = ()
    threat_notes: dict[int, str] = dc_field(default_factory=dict)   # opponent index -> note
    sort_order: int = 0
    updated_at: datetime | None = None

    @property
    def difficulty_label(self) -> str:
        return difficulty_label(self.difficulty)

    def note_for(self, index: int) -> str:
        return self.threat_notes.get(index, "")


@dataclass(frozen=True)
class PinLink:
    """Which team member and which opponent a pinned calc's two sides stand for."""

    box_entry_id: str | None = None
    opp_index: int | None = None

    def to_dict(self) -> dict:
        return {"box_entry_id": self.box_entry_id, "opp_index": self.opp_index}

    @classmethod
    def from_dict(cls, data: dict | None) -> "PinLink":
        d = dict(data or {})
        opp = d.get("opp_index")
        return cls(str(d["box_entry_id"]) if d.get("box_entry_id") else None, int(opp) if opp is not None else None)


@dataclass(frozen=True)
class PinnedCalc:
    calc_id: str
    plan_id: str
    state: CalcState
    label: str = ""
    note: str = ""
    mine: str = "left"                        # the side holding your Pokémon
    focus: tuple[str, int] | None = None      # (side, move index) the pin is about
    link: PinLink = dc_field(default_factory=PinLink)
    position: int = 0

    @property
    def theirs(self) -> str:
        return "right" if self.mine == "left" else "left"


@dataclass(frozen=True)
class PlanDraft:
    """A new plan's opponent before it is saved: from a Top teams lineup, a Meta team, a
    rival preset or a paste."""

    name: str
    members: tuple[RivalMember, ...]
    source: str = ""


__all__ = [
    "DIFFICULTIES", "MAX_PICKS", "MemberRef", "PinLink", "PinnedCalc", "Plan", "PlanDraft", "difficulty_label",
]

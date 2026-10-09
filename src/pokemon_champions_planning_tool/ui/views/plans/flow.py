"""Battle flow: what you do if they lead a given pair, turn by turn, and if things go wrong.

A small, fixed shape rather than a decision tree, so it stays readable:

- a **scenario** per opposing lead pair, plus one "Any other lead" fallback, rated
  Favourable / Even / Unfavourable, with your own lead and back (the plan's by default);
- its **turns**: for each of your two Pokémon on the field, a move (with a target) or a
  switch, and Mega Evolution; plus a note;
- "If…" **branches** after a turn, one level only: "If Gardevoir is KO'd after T1 → bring
  Kingambit", or free text, each with its own turns.

Only your side is planned: their moves are not simulated. Who is on your field at each turn
is never stored, it is replayed from the switches and KOs (``board_at``), so editing an
early turn can never leave a later one inconsistent; ``validate`` reports what no longer
fits instead. Pure: no Flet, no database.
"""

from __future__ import annotations

from collections.abc import Callable, Sequence
from dataclasses import dataclass, replace
from typing import Any

from .model import MAX_PICKS, MemberRef, Plan

RATINGS: tuple[tuple[str, str], ...] = (("favourable", "Favourable"), ("even", "Even"), ("unfavourable", "Unfavourable"))
RATING_LABELS = dict(RATINGS)
MAX_TURNS = 8
MAX_BRANCHES = 3
MAX_BRANCH_TURNS = 6

# Move targets (Showdown's) -> how an action aims: one foe, both foes, your ally, or nothing to pick.
_FOE_TARGETS = frozenset({"normal", "adjacentFoe", "any", "randomNormal", "scripted"})
_SPREAD_TARGETS = frozenset({"allAdjacentFoes", "allAdjacent"})
_ALLY_TARGETS = frozenset({"adjacentAlly", "adjacentAllyOrSelf"})

Where = int | None   # None: the scenario's main line; an int: that branch


# -- the shape ---------------------------------------------------------------------------------


@dataclass(frozen=True)
class OppRef:
    """One of their six, by index in ``plan.opponent``; ``species`` is what was there when
    it was picked, so a slot replaced with Edit as paste can be noticed."""

    index: int
    species: str = ""

    def to_dict(self) -> dict:
        return {"index": self.index, "species": self.species}

    @classmethod
    def from_dict(cls, data: Any) -> "OppRef | None":
        if not isinstance(data, dict):
            return None
        try:
            return cls(int(data["index"]), str(data.get("species") or ""))
        except (KeyError, TypeError, ValueError):
            return None


@dataclass(frozen=True)
class Action:
    """What one of your Pokémon does on a turn."""

    kind: str = ""                     # "move" | "switch" | ""
    move: str = ""
    target: str = ""                   # "foe" | "foes" | "ally" | "" (no target to pick)
    foe: OppRef | None = None
    mega: bool = False
    switch_to: MemberRef | None = None

    @property
    def empty(self) -> bool:
        return not self.kind and not self.mega

    def to_dict(self) -> dict:
        d: dict[str, Any] = {"kind": self.kind}
        if self.move:
            d["move"] = self.move
        if self.target:
            d["target"] = self.target
        if self.foe is not None:
            d["foe"] = self.foe.to_dict()
        if self.mega:
            d["mega"] = True
        if self.switch_to is not None:
            d["switch_to"] = self.switch_to.to_dict()
        return d

    @classmethod
    def from_dict(cls, data: Any) -> "Action":
        if not isinstance(data, dict):
            return cls()
        kind = str(data.get("kind") or "")
        return cls(
            kind=kind if kind in ("move", "switch") else "", move=str(data.get("move") or ""), target=str(data.get("target") or ""),
            foe=OppRef.from_dict(data.get("foe")), mega=bool(data.get("mega")), switch_to=MemberRef.from_dict(data.get("switch_to")),
        )


NO_ACTION = Action()


@dataclass(frozen=True)
class Turn:
    actions: tuple[Action, Action] = (NO_ACTION, NO_ACTION)   # your left Pokémon, your right one
    their_field: tuple[OppRef, ...] = ()                       # their two this turn; empty: as the turn before
    note: str = ""

    def to_dict(self) -> dict:
        return {"actions": [a.to_dict() for a in self.actions], "their_field": [o.to_dict() for o in self.their_field], "note": self.note}

    @classmethod
    def from_dict(cls, data: Any) -> "Turn":
        d = data if isinstance(data, dict) else {}
        actions = [Action.from_dict(a) for a in (d.get("actions") or [])][:2]
        actions += [NO_ACTION] * (2 - len(actions))
        field = tuple(o for o in (OppRef.from_dict(x) for x in (d.get("their_field") or [])) if o is not None)[:2]
        return cls(actions=(actions[0], actions[1]), their_field=field, note=str(d.get("note") or ""))


@dataclass(frozen=True)
class Branch:
    """"If…" after a turn of the main line: a KO of one of yours (who comes in), or free text."""

    after_turn: int = 1                # 1-based: after T1
    kind: str = "ko"                   # "ko" | "other"
    ko: MemberRef | None = None
    replacement: MemberRef | None = None
    text: str = ""
    turns: tuple[Turn, ...] = ()

    def to_dict(self) -> dict:
        return {"after_turn": self.after_turn, "kind": self.kind, "ko": self.ko.to_dict() if self.ko else None,
                "replacement": self.replacement.to_dict() if self.replacement else None, "text": self.text,
                "turns": [t.to_dict() for t in self.turns]}

    @classmethod
    def from_dict(cls, data: Any) -> "Branch":
        d = data if isinstance(data, dict) else {}
        try:
            after = max(1, int(d.get("after_turn") or 1))
        except (TypeError, ValueError):
            after = 1
        return cls(after_turn=after, kind="other" if d.get("kind") == "other" else "ko", ko=MemberRef.from_dict(d.get("ko")),
                   replacement=MemberRef.from_dict(d.get("replacement")), text=str(d.get("text") or ""),
                   turns=tuple(Turn.from_dict(t) for t in (d.get("turns") or []))[:MAX_BRANCH_TURNS])


@dataclass(frozen=True)
class Scenario:
    scenario_id: str = ""
    plan_id: str = ""
    position: int = 0
    their_lead: tuple[OppRef, ...] = ()   # empty: "Any other lead"
    rating: str = ""
    lead: tuple[MemberRef, ...] = ()      # empty: the plan's Lead
    back: tuple[MemberRef, ...] = ()      # empty: the plan's Back (or the rest of its four)
    note: str = ""
    turns: tuple[Turn, ...] = ()
    branches: tuple[Branch, ...] = ()

    @property
    def is_fallback(self) -> bool:
        return not self.their_lead

    def body(self) -> dict:
        return {"their_lead": [o.to_dict() for o in self.their_lead], "rating": self.rating,
                "lead": [r.to_dict() for r in self.lead], "back": [r.to_dict() for r in self.back], "note": self.note,
                "turns": [t.to_dict() for t in self.turns], "branches": [b.to_dict() for b in self.branches]}

    @classmethod
    def from_body(cls, body: Any, *, scenario_id: str = "", plan_id: str = "", position: int = 0) -> "Scenario":
        d = body if isinstance(body, dict) else {}

        def refs(key: str) -> tuple[MemberRef, ...]:
            return tuple(r for r in (MemberRef.from_dict(x) for x in (d.get(key) or [])) if r is not None)[:MAX_PICKS]

        rating = str(d.get("rating") or "")
        return cls(
            scenario_id=scenario_id, plan_id=plan_id, position=position,
            their_lead=tuple(o for o in (OppRef.from_dict(x) for x in (d.get("their_lead") or [])) if o is not None)[:2],
            rating=rating if rating in RATING_LABELS else "", lead=refs("lead"), back=refs("back"), note=str(d.get("note") or ""),
            turns=tuple(Turn.from_dict(t) for t in (d.get("turns") or []))[:MAX_TURNS],
            branches=tuple(Branch.from_dict(b) for b in (d.get("branches") or []))[:MAX_BRANCHES],
        )

    def turns_of(self, where: Where) -> tuple[Turn, ...]:
        return self.turns if where is None else self.branches[where].turns

    def turn_number(self, where: Where, i: int) -> int:
        """T1, T2… in the main line; a branch after T1 starts at T2."""
        return i + 1 if where is None else self.branches[where].after_turn + i + 1


# -- who is on the field ---------------------------------------------------------------------------


@dataclass(frozen=True)
class Board:
    """Your side at the start of a turn."""

    left: MemberRef | None
    right: MemberRef | None
    bench: tuple[MemberRef, ...]
    mega_by: str | None = None          # the box entry that Mega Evolved, if any
    fainted: tuple[str, ...] = ()

    def slot(self, i: int) -> MemberRef | None:
        return self.left if i == 0 else self.right


def _same(a: MemberRef | None, b: MemberRef | None) -> bool:
    return a is not None and b is not None and a.box_entry_id == b.box_entry_id


def brought(plan: Plan, sc: Scenario) -> tuple[tuple[MemberRef, ...], tuple[MemberRef, ...]]:
    """(lead, back) this scenario brings: its own, else the plan's. A back left empty is the
    rest of the plan's four."""
    lead = sc.lead or plan.lead
    if sc.back:
        back = sc.back
    else:
        pool = plan.back if not sc.lead else plan.lead + plan.back
        back = tuple(r for r in pool if not any(_same(r, x) for x in lead))[:MAX_PICKS]
    return lead, tuple(r for r in back if not any(_same(r, x) for x in lead))


def _apply(board: Board, turn: Turn) -> Board:
    left, right, bench, mega_by = board.left, board.right, list(board.bench), board.mega_by
    slots = [left, right]
    for i, action in enumerate(turn.actions):
        who = slots[i]
        if who is None:
            continue
        if action.mega and mega_by is None:
            mega_by = who.box_entry_id
        if action.kind == "switch" and action.switch_to is not None:
            incoming = next((b for b in bench if _same(b, action.switch_to)), None)
            if incoming is not None:
                bench.remove(incoming)
                bench.append(who)
                slots[i] = incoming
    return Board(slots[0], slots[1], tuple(bench), mega_by, board.fainted)


def board_at(plan: Plan, sc: Scenario, turn_index: int, branch: Where = None) -> Board:
    """Your field at the start of a turn (0-based in its line), switches and KOs replayed."""
    lead, back = brought(plan, sc)
    board = Board(lead[0] if lead else None, lead[1] if len(lead) > 1 else None, back)
    if branch is None:
        for turn in sc.turns[:turn_index]:
            board = _apply(board, turn)
        return board
    br = sc.branches[branch]
    for turn in sc.turns[:br.after_turn]:
        board = _apply(board, turn)
    if br.kind == "ko" and br.ko is not None:
        bench = [b for b in board.bench if not _same(b, br.replacement)]
        incoming = br.replacement if any(_same(b, br.replacement) for b in board.bench) else None
        slots = [board.left, board.right]
        for i, who in enumerate(slots):
            if _same(who, br.ko):
                slots[i] = incoming
        board = Board(slots[0], slots[1], tuple(bench), board.mega_by, board.fainted + (br.ko.box_entry_id,))
    for turn in br.turns[:turn_index]:
        board = _apply(board, turn)
    return board


def foes_at(sc: Scenario, turn_index: int, branch: Where = None) -> tuple[OppRef, ...]:
    """Their field at a turn: the latest "Their field" noted up to it, else their lead."""
    line = list(sc.turns[:turn_index + 1]) if branch is None else list(sc.turns[:sc.branches[branch].after_turn]) + list(sc.branches[branch].turns[:turn_index + 1])
    field = sc.their_lead
    for turn in line:
        if turn.their_field:
            field = turn.their_field
    return field


# -- checking ------------------------------------------------------------------------------------------


@dataclass(frozen=True)
class Issue:
    text: str
    where: Where = None
    turn: int | None = None      # 0-based in its line
    slot: int | None = None


def validate(plan: Plan, sc: Scenario, mine: dict[str, Any], *, can_mega: Callable[[str], bool] = lambda _box: True,
             name: Callable[[MemberRef], str] = lambda r: r.species) -> list[Issue]:
    """What no longer fits: Pokémon gone from the team, impossible switches or Megas, moves
    not in a moveset, their slots changed by Edit as paste. Never raises.

    ``mine`` maps box entry id -> the team member's calc state (``.moves``)."""
    issues: list[Issue] = []
    lead, back = brought(plan, sc)
    for ref in lead + back:
        if ref.box_entry_id not in mine:
            issues.append(Issue(f"{name(ref)} is no longer in the team"))

    def check_opp(ref: OppRef | None, **where: Any) -> None:
        if ref is None:
            return
        if not 0 <= ref.index < len(plan.opponent):
            issues.append(Issue(f"Their slot {ref.index + 1} no longer exists", **where))
        elif ref.species and plan.opponent[ref.index].pokemon.species != ref.species:
            issues.append(Issue(f"Their slot {ref.index + 1} changed (was {ref.species.replace('-', ' ').title()})", **where))

    for ref in sc.their_lead:
        check_opp(ref)
    lines: list[Where] = [None, *range(len(sc.branches))]
    for where in lines:
        if where is not None:
            br = sc.branches[where]
            if br.after_turn > len(sc.turns):
                issues.append(Issue(f"This “If…” comes after T{br.after_turn}, which no longer exists", where))
            if br.kind == "ko" and br.ko is not None:
                before = board_at(plan, sc, br.after_turn) if br.after_turn <= len(sc.turns) else None
                if before is not None and not (_same(before.left, br.ko) or _same(before.right, br.ko)):
                    issues.append(Issue(f"{name(br.ko)} isn't on the field after T{br.after_turn}", where))
                if br.replacement is not None and before is not None and not any(_same(b, br.replacement) for b in before.bench):
                    issues.append(Issue(f"{name(br.replacement)} isn't in the back to come in", where))
        for i, turn in enumerate(sc.turns_of(where)):
            board = board_at(plan, sc, i, where)
            for ref in turn.their_field:
                check_opp(ref, where=where, turn=i)
            for slot, action in enumerate(turn.actions):
                who = board.slot(slot)
                at = {"where": where, "turn": i, "slot": slot}
                if action.empty:
                    continue
                if who is None:
                    issues.append(Issue("Nobody is on this side of the field", **at))
                    continue
                if action.kind == "move":
                    known = getattr(mine.get(who.box_entry_id), "moves", None)
                    if known is not None and action.move not in [m for m in known if m]:
                        issues.append(Issue(f"{name(who)} doesn't know {action.move}", **at))
                    check_opp(action.foe, **at)
                if action.kind == "switch" and not any(_same(b, action.switch_to) for b in board.bench):
                    issues.append(Issue(f"Can't switch to {name(action.switch_to) if action.switch_to else '?'}: not in the back", **at))
                if action.mega:
                    if board.mega_by is not None and board.mega_by != who.box_entry_id:
                        issues.append(Issue("Only one Mega Evolution per battle", **at))
                    elif board.mega_by == who.box_entry_id:
                        issues.append(Issue(f"{name(who)} has already Mega Evolved", **at))
                    elif not can_mega(who.box_entry_id):
                        issues.append(Issue(f"{name(who)} can't Mega Evolve (no Mega Stone)", **at))
    return issues


# -- editing (each returns a new scenario) ---------------------------------------------------------------


def _with_turns(sc: Scenario, where: Where, turns: Sequence[Turn]) -> Scenario:
    if where is None:
        return replace(sc, turns=tuple(turns))
    branches = list(sc.branches)
    branches[where] = replace(branches[where], turns=tuple(turns))
    return replace(sc, branches=tuple(branches))


def add_turn(sc: Scenario, where: Where = None) -> Scenario:
    turns = list(sc.turns_of(where))
    if len(turns) >= (MAX_TURNS if where is None else MAX_BRANCH_TURNS):
        return sc
    return _with_turns(sc, where, [*turns, Turn()])


def remove_turn(sc: Scenario, where: Where, i: int) -> Scenario:
    turns = list(sc.turns_of(where))
    if not 0 <= i < len(turns):
        return sc
    del turns[i]
    out = _with_turns(sc, where, turns)
    if where is None:
        # An "If…" after a turn that is gone moves to the last turn left.
        out = replace(out, branches=tuple(replace(b, after_turn=max(1, min(b.after_turn, len(turns)))) for b in out.branches))
    return out


def set_action(sc: Scenario, where: Where, i: int, slot: int, action: Action) -> Scenario:
    turns = list(sc.turns_of(where))
    if not 0 <= i < len(turns):
        return sc
    actions = list(turns[i].actions)
    actions[slot] = action
    if action.mega:   # one Mega per battle: picking it here clears it on the other slot of the same turn
        other = 1 - slot
        actions[other] = replace(actions[other], mega=False)
    turns[i] = replace(turns[i], actions=(actions[0], actions[1]))
    return _with_turns(sc, where, turns)


def set_turn(sc: Scenario, where: Where, i: int, **changes: Any) -> Scenario:
    """Change a turn's note or their field."""
    turns = list(sc.turns_of(where))
    if not 0 <= i < len(turns):
        return sc
    turns[i] = replace(turns[i], **changes)
    return _with_turns(sc, where, turns)


def add_branch(sc: Scenario, after_turn: int, *, kind: str = "ko", ko: MemberRef | None = None, text: str = "") -> Scenario:
    if len(sc.branches) >= MAX_BRANCHES:
        return sc
    return replace(sc, branches=(*sc.branches, Branch(after_turn=max(1, after_turn), kind=kind, ko=ko, text=text, turns=(Turn(),))))


def set_branch(sc: Scenario, b: int, **changes: Any) -> Scenario:
    branches = list(sc.branches)
    branches[b] = replace(branches[b], **changes)
    return replace(sc, branches=tuple(branches))


def remove_branch(sc: Scenario, b: int) -> Scenario:
    return replace(sc, branches=tuple(x for i, x in enumerate(sc.branches) if i != b))


def default_target(move_target: str | None) -> str:
    """How a move aims from its Showdown target: one foe, both foes, your ally, or nothing."""
    if move_target in _SPREAD_TARGETS:
        return "foes"
    if move_target in _ALLY_TARGETS:
        return "ally"
    if move_target in _FOE_TARGETS or move_target is None:
        return "foe"
    return ""


# -- words --------------------------------------------------------------------------------------------


@dataclass(frozen=True)
class Names:
    """How to call your Pokémon and theirs (the store resolves them from the catalogue)."""

    member: Callable[[MemberRef], str]
    opp: Callable[[OppRef], str]


def action_label(action: Action, names: Names) -> str:
    if action.kind == "switch":
        return f"Switch → {names.member(action.switch_to) if action.switch_to else '?'}"
    parts = ["Mega Evolve"] if action.mega else []
    if action.kind == "move" and action.move:
        aim = {"foes": " → both foes", "ally": " → ally"}.get(action.target, "")
        if action.target == "foe" and action.foe is not None:
            aim = f" → {names.opp(action.foe)}"
        parts.append(f"{action.move}{aim}")
    return ", ".join(parts) or "—"


def scenario_title(sc: Scenario, names: Names) -> str:
    if sc.is_fallback:
        return "Any other lead"
    return "If they lead " + " + ".join(names.opp(o) for o in sc.their_lead)


def scenario_markdown(plan: Plan, sc: Scenario, names: Names, *, level: int = 3,
                      hits: dict[tuple[Where, int, int], str] | None = None) -> list[str]:
    """A scenario as report lines: a heading, the lead, a bullet per turn, a sub-list per "If…"."""
    hits = hits or {}
    rating = f" ({RATING_LABELS[sc.rating]})" if sc.rating else ""
    lead, back = brought(plan, sc)
    out = [f"{'#' * level} {scenario_title(sc, names)}{rating}", ""]
    who = " + ".join(names.member(r) for r in lead) or "—"
    out.append(f"Lead: {who}" + (f" · Back: {' + '.join(names.member(r) for r in back)}" if back else ""))
    if sc.note.strip():
        out += ["", sc.note.strip()]
    out.append("")

    def turn_line(where: Where, i: int, turn: Turn, indent: str) -> str:
        board = board_at(plan, sc, i, where)
        parts = []
        for slot, action in enumerate(turn.actions):
            mon = board.slot(slot)
            if mon is None or action.empty:
                continue
            hit = hits.get((where, i, slot))
            parts.append(f"{names.member(mon)}: {action_label(action, names)}" + (f" ({hit})" if hit else ""))
        note = f" — {turn.note.strip()}" if turn.note.strip() else ""
        return f"{indent}- T{sc.turn_number(where, i)}: {' · '.join(parts) or '—'}{note}"

    for i, turn in enumerate(sc.turns):
        out.append(turn_line(None, i, turn, ""))
        for b, br in enumerate(sc.branches):
            if br.after_turn != i + 1:
                continue
            if br.kind == "ko" and br.ko is not None:
                head = f"If {names.member(br.ko)} is KO'd after T{br.after_turn}" + (f": bring {names.member(br.replacement)}" if br.replacement else "")
            else:
                head = f"If {br.text.strip() or '…'} (after T{br.after_turn})"
            out.append(f"- {head}")
            out += [turn_line(b, j, t, "  ") for j, t in enumerate(br.turns)]
    for b, br in enumerate(sc.branches):   # anchored past the last turn (validate flags it): still exported
        if br.after_turn > len(sc.turns):
            out.append(f"- If {names.member(br.ko) if br.ko else br.text or '…'} (after T{br.after_turn})")
    return out


__all__ = [
    "MAX_BRANCHES", "MAX_BRANCH_TURNS", "MAX_TURNS", "NO_ACTION", "RATINGS", "RATING_LABELS",
    "Action", "Board", "Branch", "Issue", "Names", "OppRef", "Scenario", "Turn",
    "action_label", "add_branch", "add_turn", "board_at", "brought", "default_target", "foes_at", "remove_branch",
    "remove_turn", "scenario_markdown", "scenario_title", "set_action", "set_branch", "set_turn", "validate",
]

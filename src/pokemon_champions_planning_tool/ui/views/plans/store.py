"""Plans store: matchup plans and their pinned calcs. Flet-free, one session per call.

Plans belong to one of your teams; their opponent is a copy taken when the plan is made.
Your side is read live from the team (``my_members``), so a plan follows the team as it
changes, and Lead/Back name box entries so reordering the team does not move them.
"""

from __future__ import annotations

from collections.abc import Callable, Iterable, Sequence
from contextlib import AbstractContextManager
from dataclasses import asdict, replace
from typing import Any
from uuid import UUID

from sqlmodel import Session

from ....domain.formats import Mechanic
from ....infrastructure.database.database import get_session
from ....infrastructure.database.models import MatchupPlanRecord, PlanCalcRecord, PlanScenarioRecord
from ....infrastructure.database.repositories import MatchupPlanRepository, TeamRepository
from ..calc.state import CalcState, FieldState, PokemonState, RivalMember, pokemon_from_slot
from .model import DIFFICULTIES, MAX_PICKS, MemberRef, PinLink, PinnedCalc, Plan, PlanDraft
from .flow import Names, OppRef, Scenario, Turn, remap_opponents, scenario_markdown
from .flow_calc import action_hits, hit_text
from .pins import PinView, view_pin
from .report import PinLine, PlanText, plan_markdown, team_markdown

SessionFactory = Callable[[], AbstractContextManager[Session]]

_EDITABLE = frozenset({"name", "source", "difficulty", "lead", "back", "game_plan", "field", "opponent", "threat_notes"})


# -- record <-> plain data ----------------------------------------------------------------------


def plan_from_record(record: MatchupPlanRecord) -> Plan:
    notes: dict[int, str] = {}
    for key, text in (record.threat_notes or {}).items():
        try:
            if text:
                notes[int(key)] = str(text)
        except (TypeError, ValueError):
            continue
    return Plan(
        plan_id=str(record.plan_id), team_id=str(record.team_id), name=record.name, source=record.source or "",
        difficulty=max(0, min(len(DIFFICULTIES) - 1, int(record.difficulty or 0))),
        lead=_refs(record.lead), back=_refs(record.back), game_plan=record.game_plan or "",
        field=FieldState.from_dict(record.field), opponent=tuple(RivalMember.from_dict(m) for m in (record.opponent or [])),
        threat_notes=notes, sort_order=record.sort_order, updated_at=record.updated_at,
    )


def _refs(items: Iterable[dict] | None) -> tuple[MemberRef, ...]:
    refs = (MemberRef.from_dict(x) for x in (items or []))
    return tuple(r for r in refs if r is not None)[:MAX_PICKS]


def pin_from_record(record: PlanCalcRecord) -> PinnedCalc:
    focus = None
    if record.focus and record.focus.get("side") in ("left", "right"):
        try:
            focus = (str(record.focus["side"]), int(record.focus.get("index", 0)))
        except (TypeError, ValueError):
            focus = None
    return PinnedCalc(
        calc_id=str(record.calc_id), plan_id=str(record.plan_id), state=CalcState.from_dict(record.state),
        label=record.label or "", note=record.note or "", mine="right" if record.mine == "right" else "left",
        focus=focus, link=PinLink.from_dict(record.link), position=record.position,
    )


def _apply_changes(record: MatchupPlanRecord, changes: dict[str, Any]) -> None:
    unknown = set(changes) - _EDITABLE
    if unknown:
        raise ValueError(f"Not a plan field: {', '.join(sorted(unknown))}")
    if "name" in changes:
        clean = str(changes["name"] or "").strip()
        if not clean:
            raise ValueError("A plan needs a name")
        record.name = clean
    if "source" in changes:
        record.source = str(changes["source"] or "")
    if "difficulty" in changes:
        record.difficulty = max(0, min(len(DIFFICULTIES) - 1, int(changes["difficulty"] or 0)))
    lead = _clean_refs(changes["lead"]) if "lead" in changes else _refs(record.lead)
    back = _clean_refs(changes["back"]) if "back" in changes else _refs(record.back)
    if "lead" in changes or "back" in changes:
        # A Pokémon leads or stays back, never both: the newest pick wins.
        if "lead" in changes:
            taken = {r.box_entry_id for r in lead}
            back = tuple(r for r in back if r.box_entry_id not in taken)
        else:
            taken = {r.box_entry_id for r in back}
            lead = tuple(r for r in lead if r.box_entry_id not in taken)
        record.lead = [r.to_dict() for r in lead]
        record.back = [r.to_dict() for r in back]
    if "game_plan" in changes:
        record.game_plan = str(changes["game_plan"] or "")
    if "field" in changes:
        fs = changes["field"]
        record.field = asdict(fs) if isinstance(fs, FieldState) else asdict(FieldState.from_dict(fs))
    if "opponent" in changes:
        record.opponent = [m.to_dict() for m in changes["opponent"]]
    if "threat_notes" in changes:
        record.threat_notes = {str(int(k)): str(v) for k, v in dict(changes["threat_notes"]).items() if str(v or "").strip()}


def _clean_refs(refs: Sequence[MemberRef]) -> tuple[MemberRef, ...]:
    seen: set[str] = set()
    out: list[MemberRef] = []
    for ref in refs:
        if ref.box_entry_id and ref.box_entry_id not in seen:
            seen.add(ref.box_entry_id)
            out.append(ref)
    return tuple(out[:MAX_PICKS])


# -- store --------------------------------------------------------------------------------------


class PlanStore:
    def __init__(self, catalogs: Any, session_factory: SessionFactory = get_session, *, team_store: Any = None) -> None:
        self.catalogs = catalogs
        self._sf = session_factory
        self.team_store = team_store
        self._members_cache: dict[str, list[tuple[str, PokemonState]]] = {}
        self.calc_cache: dict = {}   # battle-flow damage, shared by the view's worker and the export

    # -- your side ------------------------------------------------------------------------

    def my_members(self, team_id: str) -> list[tuple[str, PokemonState]]:
        """(box entry id, calc state) for each filled slot of a team, in slot order. Cached
        until ``invalidate`` (a team edit, a box change or a catalogue reload)."""
        if team_id in self._members_cache:
            return self._members_cache[team_id]
        out: list[tuple[str, PokemonState]] = []
        if self.team_store is not None:
            name, slots, _summary = self.team_store.summary_for(UUID(team_id))
            for slot in slots:
                if not getattr(slot, "filled", False):
                    continue
                state = pokemon_from_slot(slot, self.catalogs, source=f"{name} · slot {slot.position}")
                if state is not None:
                    out.append((str(slot.entry.box_entry_id), state))
        self._members_cache[team_id] = out
        return out

    def invalidate(self, team_id: str | None = None) -> None:
        if team_id is None:
            self._members_cache.clear()
            self.calc_cache.clear()
        else:
            self._members_cache.pop(str(team_id), None)

    def species_name(self, canonical_id: str | None) -> str:
        if not canonical_id:
            return ""
        species = self.catalogs.species_for(canonical_id)
        return species.name if species else canonical_id.replace("-", " ").title()

    def ref_label(self, ref: MemberRef, team_id: str) -> tuple[str, bool]:
        """(name, still in the team): a pick whose Pokémon left the team keeps its name."""
        for box_id, state in self.my_members(team_id):
            if box_id == ref.box_entry_id:
                return self.species_name(state.species), True
        return self.species_name(ref.species), False

    def _team_format(self, team_id: str) -> Any:
        if self.team_store is None:
            return None
        with self._sf() as s:
            record = TeamRepository(s).get(UUID(team_id))
            format_id = record.format_id if record else None
        return self.team_store.formats.for_team(format_id)

    # -- creating -------------------------------------------------------------------------

    def _base(self, canonical_id: str | None) -> str | None:
        species = self.catalogs.species_for(canonical_id) if canonical_id else None
        if species is None:
            return canonical_id
        return species.base_species_id if species.is_mega else species.canonical_id

    def normalise_megas(self, members: Iterable[RivalMember], *, enabled: bool = True) -> tuple[RivalMember, ...]:
        """A member holding its Mega Stone becomes the Mega form, as the calculator does when
        an item is set: tournament rosters and pastes keep the base species. With Megas off
        (the team's format has none) a Mega form goes back to its base species."""
        out: list[RivalMember] = []
        for member in members:
            p = member.pokemon
            mega = self.catalogs.mega_for_item(p.species, p.item) if enabled else self._base(p.species)
            if mega and mega != p.species:
                species = self.catalogs.species_for(mega)
                ability = species.abilities[0] if species is not None and species.abilities else p.ability
                member = replace(member, pokemon=replace(p, species=mega, ability=ability))
            out.append(member)
        return tuple(out)

    def create_from_draft(self, team_id: str, draft: PlanDraft) -> Plan:
        name = (draft.name or "").strip() or "New plan"
        fmt = self._team_format(team_id)
        mega_enabled = fmt.has(Mechanic.MEGA) if fmt is not None else True
        game_type = fmt.game_type if fmt is not None else "doubles"
        members = self.normalise_megas(draft.members[:6], enabled=mega_enabled)
        with self._sf() as s:
            repo = MatchupPlanRepository(s)
            record = MatchupPlanRecord(
                team_id=UUID(team_id), name=name, source=draft.source or "",
                field=asdict(FieldState(game_type=game_type)), opponent=[m.to_dict() for m in members],
                sort_order=repo.next_sort_order(UUID(team_id)),
            )
            return plan_from_record(repo.upsert(record))

    def replace_opponent(self, plan_id: str, members: Sequence[RivalMember]) -> Plan:
        """New sets for the opposing six ("Edit as paste…"). Notes, pinned calcs and the
        battle flow follow each Pokémon still in the team, wherever it is now; a Pokémon that
        left keeps its slot (its note goes to what replaced it, its flow is flagged)."""
        plan = self.get(plan_id)
        if plan is None:
            raise KeyError(plan_id)
        fmt = self._team_format(plan.team_id)
        members = self.normalise_megas(list(members)[:6], enabled=fmt.has(Mechanic.MEGA) if fmt is not None else True)
        moved = self._follow(plan.opponent, members)
        notes: dict[int, str] = {}
        for i, note in sorted(plan.threat_notes.items(), key=lambda kv: kv[0] not in moved):   # followed notes first
            j = moved.get(i, i)
            if j < len(members) and j not in notes:
                notes[j] = note
        if any(i != j for i, j in moved.items()):
            for pin in self.pins(plan_id):
                j = moved.get(pin.link.opp_index) if pin.link.opp_index is not None else None
                if j is not None and j != pin.link.opp_index:
                    self.update_pin(pin.calc_id, link=replace(pin.link, opp_index=j))
            for sc in self.scenarios(plan_id):
                again = remap_opponents(sc, moved, members)
                if again != sc:
                    self.save_scenario(again)
        return self.update(plan_id, opponent=members, threat_notes=notes)

    def _follow(self, old: Sequence[RivalMember], new: Sequence[RivalMember]) -> dict[int, int]:
        """Old slot -> new slot of each Pokémon still there (by species, Mega or not)."""
        free = {j: self._base(m.pokemon.species) for j, m in enumerate(new)}
        out: dict[int, int] = {}
        for i, m in enumerate(old):
            base = self._base(m.pokemon.species)
            j = i if free.get(i) == base else next((k for k, b in free.items() if b == base), None)
            if j is not None:
                out[i] = j
                del free[j]
        return out

    # -- reading and editing plans --------------------------------------------------------

    def list_plans(self, team_id: str) -> list[Plan]:
        with self._sf() as s:
            return [plan_from_record(r) for r in MatchupPlanRepository(s).list_for_team(UUID(team_id))]

    def get(self, plan_id: str) -> Plan | None:
        with self._sf() as s:
            record = MatchupPlanRepository(s).get(UUID(plan_id))
            return plan_from_record(record) if record else None

    def update(self, plan_id: str, **changes: Any) -> Plan:
        """Save some of a plan's fields (name, difficulty, lead, back, game_plan, field,
        opponent, threat_notes, source); the others stay as they are in the database."""
        with self._sf() as s:
            repo = MatchupPlanRepository(s)
            record = repo.get(UUID(plan_id))
            if record is None:
                raise KeyError(plan_id)
            _apply_changes(record, changes)
            return plan_from_record(repo.upsert(record))

    def set_threat_note(self, plan_id: str, index: int, text: str) -> Plan:
        plan = self.get(plan_id)
        if plan is None:
            raise KeyError(plan_id)
        notes = dict(plan.threat_notes)
        if text.strip():
            notes[index] = text
        else:
            notes.pop(index, None)
        return self.update(plan_id, threat_notes=notes)

    def duplicate(self, plan_id: str, name: str | None = None) -> Plan:
        with self._sf() as s:
            record = MatchupPlanRepository(s).copy_plan(UUID(plan_id), name=name)
            if record is None:
                raise KeyError(plan_id)
            return plan_from_record(record)

    def delete(self, plan_id: str) -> bool:
        with self._sf() as s:
            return MatchupPlanRepository(s).delete(UUID(plan_id))

    def move(self, plan_id: str, delta: int) -> None:
        """Move a plan up (-1) or down (+1) in its team's list."""
        plan = self.get(plan_id)
        if plan is None:
            return
        ids = [p.plan_id for p in self.list_plans(plan.team_id)]
        i = ids.index(plan_id)
        j = max(0, min(len(ids) - 1, i + delta))
        if i == j:
            return
        ids.insert(j, ids.pop(i))
        with self._sf() as s:
            MatchupPlanRepository(s).reorder(UUID(plan.team_id), [UUID(x) for x in ids])

    # -- pinned calcs ---------------------------------------------------------------------

    def pins(self, plan_id: str) -> list[PinnedCalc]:
        with self._sf() as s:
            return [pin_from_record(r) for r in MatchupPlanRepository(s).calcs(UUID(plan_id))]

    def add_pin(
        self, plan_id: str, state: CalcState, *, label: str = "", mine: str = "left",
        focus: tuple[str, int] | None = None, link: PinLink | None = None, note: str = "",
    ) -> PinnedCalc:
        record = PlanCalcRecord(
            plan_id=UUID(plan_id), label=label.strip(), note=note, mine="right" if mine == "right" else "left",
            state=state.to_dict(), focus={"side": focus[0], "index": int(focus[1])} if focus else None,
            link=(link or PinLink()).to_dict(),
        )
        with self._sf() as s:
            return pin_from_record(MatchupPlanRepository(s).add_calc(record))

    def update_pin(self, calc_id: str, **changes: Any) -> PinnedCalc:
        with self._sf() as s:
            repo = MatchupPlanRepository(s)
            record = repo.get_calc(UUID(calc_id))
            if record is None:
                raise KeyError(calc_id)
            if "label" in changes:
                record.label = str(changes["label"] or "").strip()
            if "note" in changes:
                record.note = str(changes["note"] or "")
            if "state" in changes:
                record.state = changes["state"].to_dict()
            if "link" in changes:
                record.link = (changes["link"] or PinLink()).to_dict()
            return pin_from_record(repo.update_calc(record))

    def delete_pin(self, calc_id: str) -> bool:
        with self._sf() as s:
            return MatchupPlanRepository(s).delete_calc(UUID(calc_id))

    # -- battle flow ----------------------------------------------------------------------

    def scenarios(self, plan_id: str) -> list[Scenario]:
        with self._sf() as s:
            return [Scenario.from_body(r.body, scenario_id=str(r.scenario_id), plan_id=str(r.plan_id), position=r.position)
                    for r in MatchupPlanRepository(s).scenarios(UUID(plan_id))]

    def add_scenario(self, plan_id: str, their_lead: Sequence[OppRef] = ()) -> Scenario:
        """A new scenario with one empty turn. One per opposing lead pair, one fallback (no pair)."""
        lead = tuple(their_lead)[:2]
        if lead and len(lead) != 2:
            raise ValueError("Pick two of their Pokémon")
        wanted = frozenset(o.index for o in lead)
        for existing in self.scenarios(plan_id):
            if frozenset(o.index for o in existing.their_lead) == wanted:
                raise ValueError("There is already a fallback for any other lead" if not lead else "There is already a scenario for that lead")
        sc = Scenario(their_lead=lead, turns=(Turn(),))
        with self._sf() as s:
            r = MatchupPlanRepository(s).add_scenario(PlanScenarioRecord(plan_id=UUID(plan_id), body=sc.body()))
            return Scenario.from_body(r.body, scenario_id=str(r.scenario_id), plan_id=plan_id, position=r.position)

    def save_scenario(self, sc: Scenario) -> Scenario:
        with self._sf() as s:
            repo = MatchupPlanRepository(s)
            record = repo.get_scenario(UUID(sc.scenario_id))
            if record is None:
                raise KeyError(sc.scenario_id)
            record.body = sc.body()
            r = repo.update_scenario(record)
            return Scenario.from_body(r.body, scenario_id=str(r.scenario_id), plan_id=str(r.plan_id), position=r.position)

    def delete_scenario(self, scenario_id: str) -> bool:
        with self._sf() as s:
            return MatchupPlanRepository(s).delete_scenario(UUID(scenario_id))

    def restore_scenario(self, sc: Scenario) -> Scenario:
        """Undo a delete: the same scenario back, at the end of the list (unless one for the
        same lead was added since)."""
        wanted = frozenset(o.index for o in sc.their_lead)
        if any(frozenset(o.index for o in e.their_lead) == wanted for e in self.scenarios(sc.plan_id)):
            raise ValueError("There is already a fallback for any other lead" if not wanted else "There is already a scenario for that lead")
        with self._sf() as s:
            r = MatchupPlanRepository(s).add_scenario(PlanScenarioRecord(plan_id=UUID(sc.plan_id), body=sc.body()))
            return Scenario.from_body(r.body, scenario_id=str(r.scenario_id), plan_id=sc.plan_id, position=r.position)

    def move_scenario(self, scenario_id: str, delta: int) -> None:
        with self._sf() as s:
            repo = MatchupPlanRepository(s)
            record = repo.get_scenario(UUID(scenario_id))
            if record is None:
                return
            ids = [r.scenario_id for r in repo.scenarios(record.plan_id)]
            i = ids.index(record.scenario_id)
            j = max(0, min(len(ids) - 1, i + delta))
            if i != j:
                ids.insert(j, ids.pop(i))
                repo.reorder_scenarios(record.plan_id, ids)

    def names(self, plan: Plan) -> Names:
        """How the flow names your Pokémon (from the team, or the species it had) and theirs."""
        def opp(ref: OppRef) -> str:
            if 0 <= ref.index < len(plan.opponent):
                return self.species_name(plan.opponent[ref.index].pokemon.species)
            return self.species_name(ref.species) or f"their #{ref.index + 1}"
        return Names(member=lambda ref: self.ref_label(ref, plan.team_id)[0], opp=opp)

    def flow_hits(self, plan: Plan, sc: Scenario) -> dict:
        """Every picked attack of a scenario against its target(s), under the plan's field."""
        return action_hits(plan, sc, dict(self.my_members(plan.team_id)), self.catalogs, cache=self.calc_cache)

    def flow_lines(self, plan: Plan) -> list[str]:
        """The battle flow as Markdown lines, each attack with its damage."""
        names = self.names(plan)

        def foe(index: int) -> str:
            return self.species_name(plan.opponent[index].pokemon.species) if 0 <= index < len(plan.opponent) else "?"

        out: list[str] = []
        for sc in self.scenarios(plan.plan_id):
            hits = {key: hit_text(h, foe) for key, h in self.flow_hits(plan, sc).items()}
            out += scenario_markdown(plan, sc, names, level=4, hits=hits) + [""]
        return out[:-1] if out else out

    # -- export ---------------------------------------------------------------------------

    def member_line(self, pokemon: PokemonState) -> str:
        name = self.species_name(pokemon.species)
        return f"{name} @ {pokemon.item}" if pokemon.item else name

    def plan_text(self, plan: Plan, pins: Sequence[PinLine] = ()) -> PlanText:
        """A plan with every name resolved, ready for ``report.plan_markdown``."""
        threats = tuple(
            (self.species_name(plan.opponent[i].pokemon.species), note)
            for i, note in sorted(plan.threat_notes.items())
            if 0 <= i < len(plan.opponent) and note.strip()
        )
        return PlanText(
            plan=plan,
            lead=tuple(self.ref_label(r, plan.team_id)[0] for r in plan.lead),
            back=tuple(self.ref_label(r, plan.team_id)[0] for r in plan.back),
            opponent=tuple(self.member_line(m.pokemon) for m in plan.opponent),
            threats=threats, pins=tuple(pins), flow=tuple(self.flow_lines(plan)),
        )

    def pin_views(self, plan: Plan) -> list[PinView]:
        """Every pin of a plan recomputed now: linked sides take the current sets."""
        mine = dict(self.my_members(plan.team_id))
        opponent = [m.pokemon for m in plan.opponent]
        return [view_pin(pin, mine, opponent, self.catalogs) for pin in self.pins(plan.plan_id)]

    def pin_lines(self, plan: Plan) -> list[PinLine]:
        return [PinLine(v.pin.label or f"{v.your_name} vs {v.their_name}", "\n".join(v.lines), v.pin.note) for v in self.pin_views(plan)]

    def plan_markdown(self, plan_id: str, pins: Sequence[PinLine] | None = None) -> str:
        """One plan as Markdown; its pinned calcs are recomputed unless ``pins`` is given."""
        plan = self.get(plan_id)
        if plan is None:
            return ""
        return plan_markdown(self.plan_text(plan, self.pin_lines(plan) if pins is None else pins))

    def team_markdown(self, team_id: str, team_name: str) -> str:
        texts = [self.plan_text(p, self.pin_lines(p)) for p in self.list_plans(team_id)]
        return team_markdown(team_name, texts)


__all__ = ["PlanStore", "pin_from_record", "plan_from_record"]

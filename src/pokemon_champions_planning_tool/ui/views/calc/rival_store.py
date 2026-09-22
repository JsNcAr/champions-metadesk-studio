"""Rival teams for the calculator: saved plans against known teams, and the temporary
"Current battle" team entered at team preview. Flet-free; one database session per call.

Members are calculator states (``PokemonState``) with the fields still guessed from
tournament data marked ``assumed``; loading one into the Defender panel is one click, and
what the battle reveals (an item, a move) is written back so it sticks.
"""

from __future__ import annotations

from collections.abc import Callable, Sequence
from contextlib import AbstractContextManager
from datetime import datetime, timezone
from typing import Any
from uuid import UUID

from sqlmodel import Session

from ....infrastructure.database.database import get_session
from ....infrastructure.database.models import RivalTeamRecord
from ....infrastructure.database.repositories import RivalTeamRepository
from .state import RIVAL_FIELDS, PokemonState, RivalMember, RivalTeam, pokemon_from_parsed

SessionFactory = Callable[[], AbstractContextManager[Session]]
Listener = Callable[[tuple], None]

MAX_MEMBERS = 6
BATTLE_NAME = "Current battle"


# -- builders ---------------------------------------------------------------------------------


def rival_from_species(calc_store: Any, canonical_id: str, *, source: str = "Team preview") -> RivalMember:
    """A species seen at team preview: its most-used tournament set, every field assumed."""
    pokemon, _found = calc_store.preset_pokemon(canonical_id, source=source)
    return RivalMember(pokemon, frozenset(RIVAL_FIELDS))


def rival_from_parsed(parsed_slot: Any, canonical_id: str, catalogs: Any, *, source: str) -> RivalMember | None:
    """A member of a pasted team: the paste is known; a missing spread or nature is assumed."""
    pokemon = pokemon_from_parsed(parsed_slot, canonical_id, catalogs, source=source)
    if pokemon is None:
        return None
    assumed = set()
    if parsed_slot is None or not getattr(parsed_slot, "points", None):
        assumed.add("points")
    if parsed_slot is None or not getattr(parsed_slot, "nature", None):
        assumed.add("nature")
    if parsed_slot is None:
        assumed.update(("moves", "item", "ability"))
    return RivalMember(pokemon, frozenset(assumed))


def rivals_from_paste(text: str, catalogs: Any, *, source: str) -> tuple[list[RivalMember], list[str]]:
    """Members from a Showdown paste, and the species that could not be used."""
    from ....domain.pokemon_identity import format_api_name
    from ....services.showdown_service import parse_showdown_text

    parsed = parse_showdown_text(text or "")
    members: list[RivalMember] = []
    skipped: list[str] = []
    for slot in parsed.slots[:MAX_MEMBERS]:
        species = (catalogs.species_for(slot.showdown_form_key) if getattr(slot, "showdown_form_key", None) else None) \
            or catalogs.species_for(format_api_name(slot.species_name))
        member = rival_from_parsed(slot, species.canonical_id, catalogs, source=source) if species is not None else None
        if member is None:
            skipped.append(slot.species_name)
        else:
            members.append(member)
    return members, skipped


def rivals_from_meta_row(row: Any, catalogs: Any) -> list[RivalMember]:
    """A tournament team from Meta, with its paste's sets when it has one (as "Damage calc vs…")."""
    from ....services.showdown_service import parse_showdown_text

    slots: list[Any] = []
    if getattr(row, "showdown_text", None):
        try:
            slots = list(parse_showdown_text(row.showdown_text).slots)
        except Exception:  # noqa: BLE001 - a paste that does not parse just means defaults
            slots = []
    source = f"{row.player_name} · {row.tournament_name}"
    members = []
    for index, roster_member in enumerate(row.members[:MAX_MEMBERS]):
        member = rival_from_parsed(slots[index] if index < len(slots) else None, roster_member.canonical_id, catalogs, source=source)
        if member is not None:
            members.append(member)
    return members


# -- store ------------------------------------------------------------------------------------


def _to_team(record: RivalTeamRecord) -> RivalTeam:
    return RivalTeam(str(record.rival_team_id), record.name, record.kind, record.source,
                     tuple(RivalMember.from_dict(m) for m in (record.members or [])[:MAX_MEMBERS]))


def _utc_now() -> datetime:
    return datetime.now(timezone.utc)


class RivalStore:
    """The rival teams list, which one is active, and every change to them."""

    def __init__(self, session_factory: SessionFactory | None = get_session) -> None:
        self._sf = session_factory
        self.teams: list[RivalTeam] = []      # "Current battle" first, then saved by last use
        self.active_id: str | None = None
        self.version = 0                      # bumps on every change; part of the rating keys
        self._listeners: list[Listener] = []
        self.loaded = False

    def subscribe(self, listener: Listener) -> Callable[[], None]:
        self._listeners.append(listener)
        return lambda: self._listeners.remove(listener)

    def _notify(self) -> None:
        self.version += 1
        for listener in list(self._listeners):
            listener(("rivals",))

    # -- reading --------------------------------------------------------------------------------

    def load(self) -> None:
        if self._sf is None:
            self.loaded = True
            return
        with self._sf() as s:
            repo = RivalTeamRepository(s)
            battle = repo.battle()
            saved = repo.list_saved()
        self.teams = ([_to_team(battle)] if battle is not None else []) + [_to_team(r) for r in saved]
        if self.active_id is None or self.get(self.active_id) is None:
            self.active_id = self.teams[0].rival_team_id if self.teams else None
        self.loaded = True
        self._notify()

    def get(self, rival_team_id: str | None) -> RivalTeam | None:
        return next((t for t in self.teams if t.rival_team_id == rival_team_id), None)

    @property
    def active(self) -> RivalTeam | None:
        return self.get(self.active_id)

    @property
    def battle(self) -> RivalTeam | None:
        return next((t for t in self.teams if t.is_battle), None)

    def set_active(self, rival_team_id: str | None) -> None:
        if rival_team_id != self.active_id and (rival_team_id is None or self.get(rival_team_id) is not None):
            self.active_id = rival_team_id
            self._touch(rival_team_id)
            self._notify()

    # -- writing --------------------------------------------------------------------------------

    def create(self, name: str, members: Sequence[RivalMember], *, source: str = "", activate: bool = True) -> RivalTeam:
        team = self._save(RivalTeamRecord(name=name.strip() or "Rival team", kind="saved", source=source,
                                          members=[m.to_dict() for m in list(members)[:MAX_MEMBERS]]))
        if activate:
            self.active_id = team.rival_team_id
        self._notify()
        return team

    def start_battle(self, members: Sequence[RivalMember], *, source: str = "Team preview") -> RivalTeam:
        """Replace "Current battle" with these members and make it the active team."""
        existing = self.battle
        record = RivalTeamRecord(name=BATTLE_NAME, kind="battle", source=source, members=[m.to_dict() for m in list(members)[:MAX_MEMBERS]])
        if existing is not None:
            record.rival_team_id = UUID(existing.rival_team_id)
        team = self._save(record)
        self.active_id = team.rival_team_id
        self._notify()
        return team

    def end_battle(self) -> None:
        battle = self.battle
        if battle is not None:
            self.delete(battle.rival_team_id)

    def save_battle_as(self, name: str) -> RivalTeam | None:
        """Keep the battle's team (with what it revealed) as a saved rival team."""
        battle = self.battle
        if battle is None:
            return None
        return self.create(name, battle.members, source=battle.source)

    def rename(self, rival_team_id: str, name: str) -> None:
        self._update(rival_team_id, name=name.strip() or "Rival team")

    def duplicate(self, rival_team_id: str) -> RivalTeam | None:
        team = self.get(rival_team_id)
        if team is None:
            return None
        return self.create(f"{team.name} (copy)", team.members, source=team.source)

    def delete(self, rival_team_id: str) -> None:
        if self._sf is not None:
            with self._sf() as s:
                RivalTeamRepository(s).delete(UUID(rival_team_id))
        self.teams = [t for t in self.teams if t.rival_team_id != rival_team_id]
        if self.active_id == rival_team_id:
            self.active_id = self.teams[0].rival_team_id if self.teams else None
        self._notify()

    def update_member(self, rival_team_id: str, slot: int, pokemon: PokemonState, *, revealed: Sequence[str] = ()) -> None:
        """Store a member as edited; the fields in ``revealed`` are no longer assumed."""
        team = self.get(rival_team_id)
        if team is None or not 0 <= slot < len(team.members):
            return
        old = team.members[slot]
        member = RivalMember(pokemon, old.assumed - set(revealed))
        if member == old:
            return
        self._replace(team.with_member(slot, member))

    # -- internals ------------------------------------------------------------------------------

    def _update(self, rival_team_id: str, **changes: Any) -> None:
        from dataclasses import replace

        team = self.get(rival_team_id)
        if team is not None:
            self._replace(replace(team, **changes))

    def _replace(self, team: RivalTeam) -> None:
        record = RivalTeamRecord(rival_team_id=UUID(team.rival_team_id), name=team.name, kind=team.kind, source=team.source,
                                 members=[m.to_dict() for m in team.members])
        self._save(record)
        self._notify()

    def _save(self, record: RivalTeamRecord) -> RivalTeam:
        if self._sf is not None:
            with self._sf() as s:
                existing = RivalTeamRepository(s).get(record.rival_team_id)
                if existing is not None:
                    record.created_at = existing.created_at
                record = RivalTeamRepository(s).upsert(record)
                team = _to_team(record)
        else:
            team = _to_team(record)
        others = [t for t in self.teams if t.rival_team_id != team.rival_team_id and not (team.is_battle and t.is_battle)]
        if team.is_battle:
            self.teams = [team, *others]
        else:
            existing_index = next((i for i, t in enumerate(self.teams) if t.rival_team_id == team.rival_team_id), None)
            if existing_index is not None:
                self.teams = [team if t.rival_team_id == team.rival_team_id else t for t in self.teams]
            else:
                battle = [t for t in others if t.is_battle]
                self.teams = battle + [team] + [t for t in others if not t.is_battle]
        return team

    def _touch(self, rival_team_id: str | None) -> None:
        """Remember when a team was last used, so the list opens on the recent ones."""
        if rival_team_id is None or self._sf is None:
            return
        with self._sf() as s:
            record = RivalTeamRepository(s).get(UUID(rival_team_id))
            if record is not None:
                record.last_used_at = _utc_now()
                s.add(record)
                s.commit()


__all__ = ["BATTLE_NAME", "MAX_MEMBERS", "RivalStore", "rival_from_parsed", "rival_from_species", "rivals_from_meta_row", "rivals_from_paste"]

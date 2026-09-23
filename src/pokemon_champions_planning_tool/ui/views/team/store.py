"""Team store: teams, the active team's six slots, and every mutation. Flet-free.

``load()`` is the single read path: one session loads the team list, the active
team's members and their box entries, then slot models are built in memory with
guardrails, effective stats and mega forms from the catalogue. Mutations persist in
their own session, rebuild only the affected slot, and notify:

    ("teams",)          team list or active team changed
    ("all",)            every slot rebuilt
    ("slot", n)         one slot changed
    ("summary",)        totals / health / coverage changed
"""

from __future__ import annotations

from collections.abc import Callable, Sequence
from contextlib import AbstractContextManager
from dataclasses import dataclass, replace
from typing import Any
from uuid import UUID

from sqlmodel import Session

from ....domain.formats import Format, Mechanic
from ....domain.entities.box_entry import BoxEntry
from ....domain.entities.pokemon_move import PokemonMove
from ....domain.entities.team import Team
from ....domain.entities.team_member import TeamMember
from ....domain.stat_calc import validate_points
from ....infrastructure.database.database import get_session
from ....infrastructure.database.models import ItemRecord
from ....infrastructure.database.repositories import BoxRepository, MegaEvolutionRepository, TeamRepository
from ....infrastructure.providers.pokepast_provider import PokepastProvider
from ....services.showdown_service import (
    ImportedTeam,
    ImportReadinessReport,
    ParsedTeamResult,
    ShowdownExportResult,
    commit_team_import,
    export_team_to_showdown_text,
    import_from_pokepast_url,
    parse_showdown_text,
    publish_to_pokepast,
    resolve_import_readiness,
)
from ....domain.moves import base_canonical_id
from ....services.tournament_service import PartnerRecommendation, TournamentService
from ...catalogs import Catalogs
from ...move_options import (  # noqa: F401 - MoveOptions re-exported for the picker
    MoveOptions,
    invalidate_move_usage,
    move_options_for,
)
from ...formats import FormatRegistry
from .summary import EMPTY_SUMMARY, SlotModel, SlotMove, TeamSummary, summarize, validate_slot

SessionFactory = Callable[[], AbstractContextManager[Session]]
Change = tuple
Listener = Callable[[Change], None]


@dataclass(frozen=True)
class TeamRow:
    team_id: UUID
    name: str
    filled: int
    format_id: str | None = None      # None: follows the default format


class TeamStore:
    def __init__(self, catalogs: Catalogs | None = None, session_factory: SessionFactory = get_session, *, formats: FormatRegistry | None = None) -> None:
        self._sf = session_factory
        self.catalogs = catalogs or Catalogs()
        self.formats = formats or FormatRegistry()
        self.teams: list[TeamRow] = []
        self.active_team_id: UUID | None = None
        self.active_team_name: str = ""
        self.slots: list[SlotModel] = [SlotModel(p) for p in range(1, 7)]
        self.summary: TeamSummary = EMPTY_SUMMARY
        # Partner recommendations per species; the query costs ~200 ms and every slot edit
        # re-renders the card, so answers are kept until tournament data changes.
        self._partner_cache: dict[tuple[str, int], list[PartnerRecommendation]] = {}
        self._listeners: list[Listener] = []

    # -- subscription ---------------------------------------------------------------------

    def subscribe(self, listener: Listener) -> Callable[[], None]:
        self._listeners.append(listener)
        return lambda: self._listeners.remove(listener)

    def _notify(self, change: Change) -> None:
        for listener in list(self._listeners):
            listener(change)

    # -- reading ----------------------------------------------------------------------------

    def summary_for(self, team_id: UUID) -> tuple[str, list[SlotModel], TeamSummary]:
        """(name, slots, summary) of any team without touching the active one — for comparison."""
        with self._sf() as s:
            team_repo = TeamRepository(s)
            record = team_repo.get(team_id)
            name = record.name if record else ""
            fmt = self.formats.for_team(record.format_id if record else None)
            members = team_repo.get_members(team_id)
            entries = BoxRepository(s).list_entries_by_ids(m.box_entry_id for m in members)
            mega_repo = MegaEvolutionRepository(s)
            megas_by_species: dict[str, list] = {}
            for m in members:
                entry = entries.get(m.box_entry_id)
                if entry is not None:
                    species = entry.pokemon.species_name or entry.pokemon.canonical_id
                    if species not in megas_by_species:
                        raw_megas = mega_repo.list_by_species(species)
                        for rm in raw_megas:
                            if not rm.ability:
                                cat_s = self.catalogs.species_for(rm.canonical_id)
                                if cat_s is not None and cat_s.abilities:
                                    rm.ability = cat_s.abilities[0]
                        megas_by_species[species] = raw_megas
        slots = [SlotModel(p) for p in range(1, 7)]
        for m in members:
            entry = entries.get(m.box_entry_id)
            if entry is None or not 1 <= m.slot_position <= 6:
                continue
            slot = slots[m.slot_position - 1]
            slot.member, slot.entry = m, entry
            slot.megas = megas_by_species.get(entry.pokemon.species_name or entry.pokemon.canonical_id, [])
            slot.item = self.catalogs.item_for(m.item)
            slot.moves = self._resolve_moves(slot)
        for slot in slots:
            slot.validation = validate_slot(slot, slots, fmt)
        return name, slots, summarize(slots, fmt)

    def load(self, team_id: UUID | None = None) -> None:
        """Reload the team list and the active team (defaults to the first team)."""
        with self._sf() as s:
            team_repo = TeamRepository(s)
            box_repo = BoxRepository(s)
            mega_repo = MegaEvolutionRepository(s)
            records = team_repo.list_all()
            counts = team_repo.member_counts()
            self.teams = [TeamRow(r.team_id, r.name, counts.get(r.team_id, 0), r.format_id) for r in records]

            wanted = team_id or self.active_team_id
            if wanted is None or not any(t.team_id == wanted for t in self.teams):
                wanted = self.teams[0].team_id if self.teams else None
            self.active_team_id = wanted
            self.active_team_name = next((t.name for t in self.teams if t.team_id == wanted), "")

            members = team_repo.get_members(wanted) if wanted else []
            entries = box_repo.list_entries_by_ids(m.box_entry_id for m in members)
            megas_by_species: dict[str, list] = {}
            for m in members:
                entry = entries.get(m.box_entry_id)
                if entry is not None:
                    species = entry.pokemon.species_name or entry.pokemon.canonical_id
                    if species not in megas_by_species:
                        raw_megas = mega_repo.list_by_species(species)
                        for rm in raw_megas:
                            if not rm.ability:
                                cat_s = self.catalogs.species_for(rm.canonical_id)
                                if cat_s is not None and cat_s.abilities:
                                    rm.ability = cat_s.abilities[0]
                        megas_by_species[species] = raw_megas

        self.slots = [SlotModel(p) for p in range(1, 7)]
        for m in members:
            if not 1 <= m.slot_position <= 6:
                continue
            entry = entries.get(m.box_entry_id)
            if entry is None:
                continue
            slot = self.slots[m.slot_position - 1]
            slot.member = m
            slot.entry = entry
            slot.megas = megas_by_species.get(entry.pokemon.species_name or entry.pokemon.canonical_id, [])
            slot.item = self.catalogs.item_for(m.item)
            slot.moves = self._resolve_moves(slot)
        self._validate()
        self._notify(("teams",))
        self._notify(("all",))

    # -- format ---------------------------------------------------------------------------------

    @property
    def active_team_format_id(self) -> str | None:
        """The active team's own format id (None: it follows the default)."""
        return next((t.format_id for t in self.teams if t.team_id == self.active_team_id), None)

    @property
    def active_format(self) -> Format:
        """The rules the active team is built for: its own format or the default one."""
        return self.formats.for_team(self.active_team_format_id)

    def set_format(self, format_id: str | None) -> None:
        """Build the active team for another format (None: follow the default)."""
        if self.active_team_id is None:
            return
        with self._sf() as s:
            TeamRepository(s).set_format(self.active_team_id, format_id)
        self.load(self.active_team_id)

    def refresh_format(self) -> None:
        """The default or a custom format changed: re-check the team under its rules."""
        self._validate()
        self._notify(("all",))

    def _validate(self) -> None:
        fmt = self.active_format
        for slot in self.slots:
            slot.validation = validate_slot(slot, self.slots, fmt)
        self.summary = summarize(self.slots, fmt)

    def slot(self, position: int) -> SlotModel:
        return self.slots[position - 1]

    def box_choices(self, *, include_planned: bool = True) -> list[BoxEntry]:
        with self._sf() as s:
            entries = BoxRepository(s).list_entries(include_planned=include_planned)
        return entries

    def assigned_entry_ids(self) -> set[UUID]:
        return {s.member.box_entry_id for s in self.slots if s.member is not None}

    # -- team-level mutations -------------------------------------------------------------

    def select_team(self, team_id: UUID | None) -> None:
        if team_id == self.active_team_id:
            return
        self.load(team_id)

    def create_team(self, name: str) -> UUID:
        clean = name.strip()
        if not clean:
            raise ValueError("Team name cannot be empty")
        with self._sf() as s:
            repo = TeamRepository(s)
            if repo.get_by_name(clean) is not None:
                raise ValueError(f"A team named “{clean}” already exists")
            team = repo.create(Team(name=clean))
            team_id = team.team_id
        self.load(team_id)
        return team_id

    def rename_team(self, name: str) -> None:
        if self.active_team_id is None:
            return
        clean = name.strip()
        if not clean:
            raise ValueError("Team name cannot be empty")
        with self._sf() as s:
            repo = TeamRepository(s)
            existing = repo.get_by_name(clean)
            if existing is not None and existing.team_id != self.active_team_id:
                raise ValueError(f"A team named “{clean}” already exists")
            repo.rename(self.active_team_id, clean)
        self.load(self.active_team_id)

    def delete_team(self) -> str | None:
        if self.active_team_id is None:
            return None
        name = self.active_team_name
        with self._sf() as s:
            repo = TeamRepository(s)
            for m in repo.list_members(self.active_team_id):
                repo.delete_member(self.active_team_id, m.slot_position)
            repo.delete(self.active_team_id)
        self.active_team_id = None
        self.load()
        return name

    def duplicate_team(self, name: str) -> UUID:
        """Copy the active team's six slots (spreads, items, moves included) to a new team."""
        if self.active_team_id is None:
            raise ValueError("No team selected")
        copies = [
            TeamMember(
                box_entry_id=m.box_entry_id, slot_position=m.slot_position, selected_form=m.selected_form,
                item=m.item, moveset=list(m.moveset), ability=m.ability, notes=m.notes,
                points=dict(m.points), nature=m.nature, tera_type=m.tera_type,
            )
            for m in (s.member for s in self.slots if s.member is not None)
        ]
        format_id = self.active_team_format_id
        new_id = self.create_team(name)
        with self._sf() as s:
            repo = TeamRepository(s)
            if format_id is not None:
                repo.set_format(new_id, format_id)
            for member in copies:
                repo.upsert_member(new_id, member)
        self.load(new_id)
        return new_id

    # -- slot mutations --------------------------------------------------------------------------

    def _persist(self, member: TeamMember) -> None:
        with self._sf() as s:
            TeamRepository(s).upsert_member(self.active_team_id, member)

    def _rebuild_slot(self, position: int) -> None:
        """Recompute a slot's derived data after its member changed; summary follows."""
        slot = self.slot(position)
        slot.item = self.catalogs.item_for(slot.member.item) if slot.member else None
        slot.moves = self._resolve_moves(slot)
        self._validate()
        self._notify(("slot", position))
        self._notify(("summary",))

    def assign(self, position: int, box_entry_id: UUID) -> None:
        if self.active_team_id is None:
            raise ValueError("No team selected")
        with self._sf() as s:
            entry = BoxRepository(s).load_entry(str(box_entry_id))
            if entry is None:
                raise ValueError("That Pokémon is no longer in your box")
            species = entry.pokemon.species_name or entry.pokemon.canonical_id
            megas = MegaEvolutionRepository(s).list_by_species(species)
        abilities = [a.name.replace("-", " ").title() for a in entry.pokemon.abilities]
        member = TeamMember(box_entry_id=box_entry_id, slot_position=position, ability=abilities[0] if abilities else None)
        self._persist(member)
        slot = self.slot(position)
        slot.member, slot.entry, slot.megas = member, entry, megas
        self._rebuild_slot(position)

    def clear_slot(self, position: int) -> TeamMember | None:
        """Empty a slot; returns the removed member so the caller can offer Undo."""
        slot = self.slot(position)
        if slot.member is None or self.active_team_id is None:
            return None
        removed = slot.member
        with self._sf() as s:
            TeamRepository(s).delete_member(self.active_team_id, position)
        slot.member, slot.entry, slot.megas = None, None, []
        self._rebuild_slot(position)
        return removed

    def restore_slot(self, member: TeamMember) -> None:
        with self._sf() as s:
            entry = BoxRepository(s).load_entry(str(member.box_entry_id))
            megas = MegaEvolutionRepository(s).list_by_species(entry.pokemon.species_name or entry.pokemon.canonical_id) if entry else []
        if entry is None:
            return
        self._persist(member)
        slot = self.slot(member.slot_position)
        slot.member, slot.entry, slot.megas = member, entry, megas
        self._rebuild_slot(member.slot_position)

    def swap(self, a: int, b: int) -> bool:
        if self.active_team_id is None:
            return False
        with self._sf() as s:
            changed = TeamRepository(s).swap_slots(self.active_team_id, a, b)
        if changed:
            self.load(self.active_team_id)
        return changed

    def _update(self, position: int, **changes: Any) -> None:
        slot = self.slot(position)
        if slot.member is None:
            return
        slot.member = replace(slot.member, **changes)
        self._persist(slot.member)
        self._rebuild_slot(position)

    def set_form(self, position: int, form_id: str) -> None:
        slot = self.slot(position)
        target = form_id or "base"
        updates: dict[str, Any] = {"selected_form": target}
        if slot.entry is not None:
            choices = slot.form_choices()
            chosen = next((c for c in choices if c.form_id == target), None)
            if chosen is not None:
                if chosen.is_mega and chosen.ability:
                    updates["ability"] = chosen.ability
                elif not chosen.is_mega:
                    current = slot.member.ability if slot.member else None
                    base_abilities = [a.name.replace("-", " ").title() for a in slot.entry.pokemon.abilities]
                    if current and current not in base_abilities and base_abilities:
                        updates["ability"] = base_abilities[0]
        self._update(position, **updates)

    def set_ability(self, position: int, ability: str | None) -> None:
        self._update(position, ability=(ability or "").strip() or None)

    def set_tera(self, position: int, tera_type: str | None) -> None:
        self._update(position, tera_type=(tera_type or "").strip().lower() or None)

    def set_notes(self, position: int, notes: str) -> None:
        self._update(position, notes=notes.strip())

    def _resolve_moves(self, slot: SlotModel) -> tuple[SlotMove | None, ...]:
        if slot.member is None or slot.entry is None:
            return ()
        cid = slot.entry.pokemon.canonical_id
        raw = list(slot.member.moveset)[:4]
        while len(raw) < 4:
            raw.append(PokemonMove(name=""))
        resolved: list[SlotMove | None] = []
        for m in raw:
            if m and m.name and m.name.strip():
                name = m.name.strip()
                resolved.append(
                    SlotMove(name=name, info=self.catalogs.move_by_name(name), legal=self.catalogs.move_legality(cid, name))
                )
            else:
                resolved.append(None)
        return tuple(resolved)

    def move_options(self, position: int) -> MoveOptions:
        """Legal moves for the slot's species (base form for megas), every other move, and
        how often stored tournament rosters of that species carry each move."""
        slot = self.slot(position)
        if slot.entry is None:
            return MoveOptions((), (), {}, False)
        return move_options_for(self.catalogs, slot.entry.pokemon.canonical_id, self._sf)

    def set_move(self, position: int, index: int, name: str) -> None:
        slot = self.slot(position)
        if slot.member is None:
            return
        moves: list[PokemonMove] = [
            PokemonMove(name=m.name.strip()) if (m and m.name and m.name.strip()) else PokemonMove(name="")
            for m in slot.member.moveset[:4]
        ]
        while len(moves) < 4:
            moves.append(PokemonMove(name=""))
        moves[index] = PokemonMove(name=name.strip())
        self._update(position, moveset=moves)

    def set_item(self, position: int, item_id: str | None) -> ItemRecord | None:
        """Hold an item. A Mega Stone for this species switches to its mega form; removing
        it (or holding anything else) drops a mega form back to base."""
        slot = self.slot(position)
        if slot.member is None:
            return None
        item = self.catalogs.item_for(item_id) if item_id else None
        form = slot.member.selected_form or "base"
        is_currently_mega = slot.form is not None and slot.form.is_mega
        if item is not None and item.target_species and self.active_format.has(Mechanic.MEGA):
            if item.target_species.lower() == slot.species_name.lower():
                form = self._mega_form_for(slot, item) or form
        elif is_currently_mega:
            form = "base"
        updates: dict[str, Any] = {"item": item.canonical_id if item else None, "selected_form": form}
        if slot.entry is not None:
            choices = slot.form_choices()
            chosen = next((c for c in choices if c.form_id == form), None)
            if chosen is not None:
                if chosen.is_mega and chosen.ability:
                    updates["ability"] = chosen.ability
                elif not chosen.is_mega and is_currently_mega:
                    current = slot.member.ability
                    base_abilities = [a.name.replace("-", " ").title() for a in slot.entry.pokemon.abilities]
                    if current and current not in base_abilities and base_abilities:
                        updates["ability"] = base_abilities[0]
        self._update(position, **updates)
        return item

    @staticmethod
    def _mega_form_for(slot: SlotModel, stone: ItemRecord) -> str | None:
        """Map a stone to the species' mega canonical id.

        Stones record target_form as "mega" / "mega-x" / "mega-y" while slots store the
        mega's canonical id ("charizard-mega-x"); the legacy UI compared the two directly
        and never matched. Champions-only Z stones ("absolitez") carry target_form "mega"
        but unlock the "-mega-z" form.
        """
        wanted = (stone.target_form or "mega").lower()
        if wanted == "mega" and stone.canonical_id.lower().endswith("z") and any(m.canonical_id.lower().endswith("-mega-z") for m in slot.megas):
            wanted = "mega-z"
        for mega in slot.megas:
            cid = mega.canonical_id.lower()
            if cid.endswith(f"-{wanted}"):
                return mega.canonical_id
        return slot.megas[0].canonical_id if slot.megas else None

    def save_spread(self, position: int, *, nature: str | None, points: dict[str, int]) -> list[str]:
        """Validate and store a Champions stat-point spread. Returns problems (empty = saved)."""
        clean = {k: int(v) for k, v in points.items() if int(v) > 0}
        problems = validate_points(clean)
        if problems:
            return problems
        self._update(position, nature=(nature or "Hardy"), points=clean)
        return []

    # -- export / analytics -----------------------------------------------------------------------------

    def export_text(self, *, points_label: str = "EVs") -> str:
        """The active team as a Showdown paste. Keep ``EVs`` for text that leaves the app."""
        members = [s.member for s in self.slots if s.member is not None]
        entries = {s.member.box_entry_id: s.entry for s in self.slots if s.member is not None and s.entry is not None}
        return export_team_to_showdown_text(members, entries, points_label=points_label, tera=self.active_format.has(Mechanic.TERA))

    def partners(self, position: int, limit: int = 3) -> list[PartnerRecommendation]:
        """Blocking (run in the background): tournament teammates for the slot's species."""
        slot = self.slot(position)
        if slot.entry is None:
            return []
        key = (base_canonical_id(slot.entry.pokemon.canonical_id), limit)
        cached = self._partner_cache.get(key)
        if cached is not None:
            return cached
        with self._sf() as s:
            partners = TournamentService(s).get_top_partners(slot.entry.pokemon.canonical_id, limit=limit)
        self._partner_cache[key] = partners
        return partners

    def partners_for_positions(
        self, positions: Sequence[int], limit: int = 3
    ) -> dict[int, list[PartnerRecommendation]]:
        """Batch-load tournament teammates for multiple slot positions in a single DB session."""
        results: dict[int, list[PartnerRecommendation]] = {}
        to_fetch: list[tuple[int, str, tuple[str, int]]] = []

        for p in positions:
            slot = self.slot(p)
            if slot.entry is None:
                results[p] = []
                continue
            key = (base_canonical_id(slot.entry.pokemon.canonical_id), limit)
            cached = self._partner_cache.get(key)
            if cached is not None:
                results[p] = cached
            else:
                to_fetch.append((p, slot.entry.pokemon.canonical_id, key))

        if not to_fetch:
            return results

        with self._sf() as s:
            svc = TournamentService(s)
            for p, cid, key in to_fetch:
                cached = self._partner_cache.get(key)
                if cached is not None:
                    results[p] = cached
                else:
                    partners = svc.get_top_partners(cid, limit=limit)
                    self._partner_cache[key] = partners
                    results[p] = partners

        return results

    def invalidate_partners(self) -> None:
        """New tournament data landed: recompute recommendations on the next request."""
        self._partner_cache.clear()
        invalidate_move_usage()

    # -- import / export ------------------------------------------------------------------------------

    @staticmethod
    def parse(text: str) -> ParsedTeamResult:
        return parse_showdown_text(text)

    @staticmethod
    def is_paste_url(text: str) -> bool:
        return PokepastProvider.is_pokepast_url(text.strip())

    @staticmethod
    def fetch_paste(url_or_id: str) -> ParsedTeamResult:
        """Blocking (run in the background): fetch and parse a Poképaste."""
        return import_from_pokepast_url(url_or_id.strip(), PokepastProvider())

    def readiness(self, parsed: ParsedTeamResult) -> ImportReadinessReport:
        """Cross-reference parsed slots with the box and the Champions catalogue."""
        legal = self.catalogs.champions_species_names or None
        with self._sf() as s:
            return resolve_import_readiness(parsed, BoxRepository(s), legal_species_catalog=legal)

    def import_parsed(self, parsed: ParsedTeamResult, *, use_planned: bool, team_name: str | None = None) -> ImportedTeam:
        """Create a team from a parsed paste (see showdown_service.commit_team_import)."""
        with self._sf() as s:
            result = commit_team_import(s, parsed, use_planned=use_planned, team_name=team_name, legal_species=self.catalogs.champions_species_names or None)
        self.load(result.team_id)
        return result

    def publish(self, *, author: str = "Pokémon Champions Planning Tool", notes: str = "") -> ShowdownExportResult:
        """Blocking (run in the background): publish the active team to Poképast.es."""
        if self.active_team_id is None:
            raise ValueError("No team selected")
        members = [s.member for s in self.slots if s.member is not None]
        entries = {s.member.box_entry_id: s.entry for s in self.slots if s.member is not None and s.entry is not None}
        return publish_to_pokepast(members, entries, team_name=self.active_team_name, team_id=str(self.active_team_id),
                                   pokepast_provider=PokepastProvider(), author=author, notes=notes, tera=self.active_format.has(Mechanic.TERA))

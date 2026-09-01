"""Team-level derived data — pure functions over already-loaded slot models.

Replaces the legacy update_team_totals / update_team_banner / update_team_validation
trio, which each re-opened a session and re-loaded every member's box entry. Nothing
here touches the database.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Literal

from ....domain.entities.box_entry import BoxEntry
from ....domain.entities.pokemon_stats import PokemonStats
from ....domain.entities.team_member import TeamMember
from ....domain.stat_calc import calc_all
from ....domain.type_chart import team_defensive_matrix, team_weakness_summary
from ....infrastructure.database.models import ItemRecord, MegaEvolutionRecord
from ....services.item_effect_service import ValidationResult, compute_effective_stats, validate_item_assignment

STAT_KEYS = ("hp", "attack", "defense", "special_attack", "special_defense", "speed")

HealthStatus = Literal["ok", "warn", "error", "info"]


@dataclass(frozen=True)
class FormChoice:
    form_id: str          # "base" or a mega canonical_id
    label: str
    sprite_url: str | None
    types: tuple[str, ...]
    stats: PokemonStats
    is_mega: bool


@dataclass
class SlotModel:
    """Everything a slot card needs, resolved once per load."""

    position: int
    member: TeamMember | None = None
    entry: BoxEntry | None = None
    megas: list[MegaEvolutionRecord] = field(default_factory=list)
    item: ItemRecord | None = None
    validation: ValidationResult | None = None

    # -- derived -------------------------------------------------------------------------

    @property
    def filled(self) -> bool:
        return self.member is not None and self.entry is not None

    @property
    def is_planned(self) -> bool:
        return bool(self.entry and self.entry.is_planned)

    @property
    def species_name(self) -> str:
        if self.entry is None:
            return ""
        return self.entry.pokemon.species_name or self.entry.pokemon.canonical_id

    def form_choices(self) -> list[FormChoice]:
        if self.entry is None:
            return []
        p = self.entry.pokemon
        base = FormChoice("base", p.form_name or "Base", p.sprite_url, tuple(p.types), p.stats, False)
        return [base] + [
            FormChoice(
                m.canonical_id,
                m.display_name,
                m.sprite_url or p.sprite_url,
                tuple(m.types or ()),
                PokemonStats(hp=m.hp, attack=m.attack, defense=m.defense, sp_atk=m.special_attack, sp_def=m.special_defense, speed=m.speed),
                True,
            )
            for m in self.megas
        ]

    @property
    def form(self) -> FormChoice | None:
        choices = self.form_choices()
        if not choices:
            return None
        wanted = (self.member.selected_form if self.member else None) or "base"
        return next((c for c in choices if c.form_id == wanted), choices[0])

    @property
    def base_stats(self) -> PokemonStats | None:
        form = self.form
        return form.stats if form else None

    @property
    def effective_stats(self) -> PokemonStats | None:
        """Form stats with the held item's multipliers applied (what the badges show)."""
        base = self.base_stats
        if base is None:
            return None
        return compute_effective_stats(base, self.item) if self.item else base

    @property
    def battle_stats(self) -> PokemonStats | None:
        """Actual level-50 stats from the spread, before items."""
        base = self.base_stats
        if base is None or self.member is None:
            return None
        try:
            return calc_all(base, self.member.evs, self.member.ivs, self.member.nature, self.member.level or 50)
        except ValueError:  # unknown nature stored by an older version — show neutral
            return calc_all(base, self.member.evs, self.member.ivs, None, self.member.level or 50)

    @property
    def ability_options(self) -> list[str]:
        if self.entry is None:
            return []
        return [a.name.replace("-", " ").title() for a in self.entry.pokemon.abilities]

    @property
    def spread_summary(self) -> str:
        if self.member is None:
            return ""
        parts = [self.member.nature or "Hardy", f"Lv{self.member.level or 50}"]
        evs = [(k, v) for k, v in (self.member.evs or {}).items() if v]
        if evs:
            short = {"hp": "HP", "attack": "Atk", "defense": "Def", "special_attack": "SpA", "special_defense": "SpD", "speed": "Spe"}
            parts.append(" / ".join(f"{v} {short.get(k, k)}" for k, v in evs))
        return " · ".join(parts)


@dataclass(frozen=True)
class HealthCheck:
    status: HealthStatus
    label: str
    detail: str


@dataclass(frozen=True)
class TeamSummary:
    filled: int
    planned: int
    totals: PokemonStats
    averages: PokemonStats
    mega_stones: int
    duplicate_items: tuple[str, ...]
    checks: tuple[HealthCheck, ...]
    weakness: dict[str, tuple[int, int, int]]   # attacking type -> (weak, resist, immune)
    matrix: dict[str, list[float]]              # attacking type -> per-slot multiplier


EMPTY_STATS = PokemonStats(hp=0, attack=0, defense=0, sp_atk=0, sp_def=0, speed=0)
EMPTY_SUMMARY = TeamSummary(0, 0, EMPTY_STATS, EMPTY_STATS, 0, (), (), {}, {})


def team_items(slots: list[SlotModel], *, except_position: int | None = None) -> list[ItemRecord]:
    return [s.item for s in slots if s.item is not None and s.position != except_position]


def validate_slot(slot: SlotModel, slots: list[SlotModel]) -> ValidationResult | None:
    """Guardrails for one slot against the rest of the team (the cross-slot check the
    legacy UI hard-disabled with `if False`)."""
    if slot.entry is None or slot.item is None:
        return None
    return validate_item_assignment(slot.item, species_name=slot.species_name, team_items=team_items(slots, except_position=slot.position))


def summarize(slots: list[SlotModel]) -> TeamSummary:
    filled = [s for s in slots if s.filled]
    if not filled:
        return EMPTY_SUMMARY

    totals = {k: 0 for k in STAT_KEYS}
    for s in filled:
        stats = s.effective_stats or s.base_stats
        for k in STAT_KEYS:
            totals[k] += getattr(stats, k)
    n = len(filled)
    total_stats = PokemonStats(**totals)
    avg_stats = PokemonStats(**{k: round(v / n) for k, v in totals.items()})

    item_ids = [s.item.canonical_id for s in filled if s.item is not None]
    duplicates = tuple(sorted({i for i in item_ids if item_ids.count(i) > 1}))
    mega_stones = sum(1 for s in filled if s.item is not None and s.item.target_species)
    planned = sum(1 for s in filled if s.is_planned)

    checks: list[HealthCheck] = []
    if len(filled) < 6:
        checks.append(HealthCheck("info", f"{len(filled)}/6", f"{6 - len(filled)} empty slot{'s' if 6 - len(filled) != 1 else ''}"))
    else:
        checks.append(HealthCheck("ok", "6/6", "Full team"))
    if duplicates:
        names = ", ".join(next(s.item.display_name for s in filled if s.item and s.item.canonical_id == d) for d in duplicates)
        checks.append(HealthCheck("error", "Duplicate items", f"Held twice: {names}. Item Clause allows one of each."))
    else:
        checks.append(HealthCheck("ok", "Items unique", "No duplicate held items"))
    if mega_stones > 1:
        checks.append(HealthCheck("warn", f"{mega_stones} Mega Stones", "Only one Pokémon per team may Mega Evolve"))
    elif mega_stones == 1:
        checks.append(HealthCheck("ok", "1 Mega Stone", "One Mega Evolution available"))
    if planned:
        checks.append(HealthCheck("info", f"{planned} planned", f"{planned} template{'s' if planned != 1 else ''} not yet in your box"))

    types_per_slot = [list(s.form.types) if s.form else [] for s in slots]
    return TeamSummary(
        filled=len(filled),
        planned=planned,
        totals=total_stats,
        averages=avg_stats,
        mega_stones=mega_stones,
        duplicate_items=duplicates,
        checks=tuple(checks),
        weakness=team_weakness_summary(types_per_slot),
        matrix=team_defensive_matrix(types_per_slot),
    )

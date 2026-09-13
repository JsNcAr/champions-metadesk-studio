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
from ....domain.moves import MoveInfo
from ....domain.entities.team_member import TeamMember
from ....domain.stat_calc import MAX_POINTS_TOTAL, champions_stats, format_points, points_total, validate_points
from ....domain.type_chart import TYPES, best_offensive_multiplier, team_defensive_matrix, team_offensive_matrix, team_offensive_summary, team_weakness_summary, uncovered_types
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
    ability: str | None = None

    @property
    def abilities(self) -> tuple[str, ...]:
        """Backwards-compatible tuple of abilities."""
        return (self.ability,) if self.ability else ()


@dataclass(frozen=True)
class SlotMove:
    """One move on a slot, with what the catalogue knows about it."""

    name: str
    info: MoveInfo | None = None
    legal: bool | None = None   # None: the catalogue has no learnset for this species


@dataclass
class SlotModel:
    """Everything a slot card needs, resolved once per load."""

    position: int
    member: TeamMember | None = None
    entry: BoxEntry | None = None
    megas: list[MegaEvolutionRecord] = field(default_factory=list)
    item: ItemRecord | None = None
    validation: ValidationResult | None = None
    moves: tuple[SlotMove | None, ...] = ()

    # -- derived -------------------------------------------------------------------------

    @property
    def filled(self) -> bool:
        return self.member is not None and self.entry is not None

    @property
    def damaging_types(self) -> list[str]:
        """Types of this slot's damaging moves. Status moves and moves the catalogue does not
        know are excluded; variable-power moves (Grass Knot, Low Kick…) count even though
        Showdown lists their base power as 0."""
        out: list[str] = []
        for m in self.moves:
            if m is None:
                continue
            info = m.info
            if info is None or not info.type or (info.category or "").lower() == "status":
                continue
            if info.type.lower() not in out:
                out.append(info.type.lower())
        return out

    @property
    def super_effective_against(self) -> list[str]:
        """Defending types this slot hits for 2× or more with its damaging moves."""
        types = self.damaging_types
        if not types:
            return []
        return [d for d in TYPES if (best_offensive_multiplier(types, d) or 0) > 1.0]

    @property
    def illegal_moves(self) -> list[str]:
        return [m.name for m in self.moves if m is not None and m.legal is False]

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
        base_abilities = tuple(a.name.replace("-", " ").title() for a in p.abilities)
        base = FormChoice("base", p.form_name or "Base", p.sprite_url, tuple(p.types), p.stats, False, None)
        return [base] + [
            FormChoice(
                m.canonical_id,
                m.display_name,
                m.sprite_url or p.sprite_url,
                tuple(m.types or ()),
                PokemonStats(hp=m.hp, attack=m.attack, defense=m.defense, sp_atk=m.special_attack, sp_def=m.special_defense, speed=m.speed),
                True,
                m.ability or None,
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
        """Actual battle stats from the stat-point spread (level 50), before items."""
        base = self.base_stats
        if base is None or self.member is None:
            return None
        try:
            return champions_stats(base, self.member.points, self.member.nature)
        except ValueError:  # unknown nature stored by an older version — show neutral
            return champions_stats(base, self.member.points, None)

    @property
    def points_used(self) -> int:
        return points_total(self.member.points) if self.member is not None else 0

    @property
    def points_left(self) -> int:
        return MAX_POINTS_TOTAL - self.points_used

    @property
    def ability_options(self) -> list[str]:
        if self.entry is None:
            return []
        form = self.form
        if form is not None and form.is_mega and form.ability:
            return [form.ability]
        return [a.name.replace("-", " ").title() for a in self.entry.pokemon.abilities]

    @property
    def active_ability(self) -> str | None:
        """The battle ability of the currently selected form."""
        form = self.form
        if form is not None and form.is_mega and form.ability:
            return form.ability
        return self.member.ability if self.member else None

    @property
    def spread_summary(self) -> str:
        if self.member is None:
            return ""
        return " · ".join([self.member.nature or "Hardy", format_points(self.member.points) or "no points"])


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
    offense: dict[str, list[float | None]] = field(default_factory=dict)   # defending type -> best multiplier per slot
    offense_counts: dict[str, tuple[int, int, int]] = field(default_factory=dict)  # defending type -> (super, neutral, poor)
    uncovered: tuple[str, ...] = ()             # defending types nobody hits super-effectively
    has_moves: bool = False


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
    illegal = [(s.species_name, p) for s in filled if s.member is not None for p in validate_points(s.member.points)]
    unspread = [s for s in filled if s.points_used == 0]
    partial = [s for s in filled if 0 < s.points_used < MAX_POINTS_TOTAL]
    if illegal:
        checks.append(HealthCheck("error", "Illegal spread", "; ".join(f"{sp.title()}: {p}" for sp, p in illegal[:4])))
    if unspread:
        checks.append(HealthCheck("info", f"{len(unspread)} unspread", "No stat points yet: " + ", ".join(s.species_name.title() for s in unspread)))
    if partial:
        checks.append(HealthCheck("warn", f"{sum(s.points_left for s in partial)} points unused", " · ".join(f"{s.species_name.title()} {s.points_left} left" for s in partial)))
    if not illegal and not unspread and not partial:
        checks.append(HealthCheck("ok", "Spreads complete", f"Every slot uses all {MAX_POINTS_TOTAL} points"))
    flagged = [(s.species_name, m) for s in filled for m in s.illegal_moves]
    if flagged:
        detail = "; ".join(f"{sp.title()}: {m}" for sp, m in flagged[:6])
        checks.append(HealthCheck("warn", f"{len(flagged)} move{'s' if len(flagged) != 1 else ''} flagged", f"Not in the Champions learnset — {detail}"))
    if planned:
        checks.append(HealthCheck("info", f"{planned} planned", f"{planned} template{'s' if planned != 1 else ''} not yet in your box"))

    types_per_slot = [list(s.form.types) if s.form else [] for s in slots]
    move_types = [s.damaging_types if s.filled else [] for s in slots]
    has_moves = any(move_types)
    offense = team_offensive_matrix(move_types)
    uncovered = tuple(uncovered_types(offense)) if has_moves else ()
    if has_moves and uncovered:
        checks.append(HealthCheck("info", f"{len(uncovered)} type{'s' if len(uncovered) != 1 else ''} uncovered", "No slot hits these super-effectively: " + ", ".join(t.capitalize() for t in uncovered)))
    elif has_moves:
        checks.append(HealthCheck("ok", "Full coverage", "Every type is hit super-effectively by someone"))
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
        offense=offense,
        offense_counts=team_offensive_summary(offense),
        uncovered=uncovered,
        has_moves=has_moves,
    )

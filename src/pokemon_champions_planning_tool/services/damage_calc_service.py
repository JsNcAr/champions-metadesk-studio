"""Damage calculator service: turn app objects (team slots, roster members, species) into
engine inputs and run matchups. Flet-free; depends on the domain and a small catalogue
protocol that ``ui.catalogs.Catalogs`` satisfies.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from typing import Any, Protocol

from ..domain.damage import APP_TO_CALC_STAT, CalcMove, CalcPokemon, DamageResult, Field, canonical_ability_name, canonical_item_name, calculate
from ..domain.entities.pokemon_stats import PokemonStats
from ..domain.moves import MoveInfo
from ..domain.species import SpeciesInfo, canonical_id_from_showdown, showdown_id


class DamageCatalogs(Protocol):
    def species_for(self, canonical_id: str | None) -> SpeciesInfo | None: ...
    def move_by_name(self, name: str | None) -> MoveInfo | None: ...
    def item_for(self, reference: str | None) -> Any: ...


STATUS_KEYS = ("", "brn", "psn", "tox", "par", "slp", "frz")


def default_field(doubles: bool = True) -> Field:
    """Tournament play is doubles: spread moves hit for three quarters."""
    return Field(game_type="Doubles" if doubles else "Singles")


def calc_stat_table(values: Mapping[str, int] | None) -> dict[str, int]:
    """Accept app stat keys (``special_attack``) or calc keys (``spa``); drop zeros."""
    out: dict[str, int] = {}
    for key, value in (values or {}).items():
        calc_key = APP_TO_CALC_STAT.get(key, key)
        if calc_key in ("hp", "atk", "def", "spa", "spd", "spe") and int(value):
            out[calc_key] = int(value)
    return out


def species_from_form(*, canonical_id: str, name: str, types: Sequence[str], stats: PokemonStats, abilities: Sequence[str] = (), is_mega: bool = False) -> SpeciesInfo:
    """A catalogue-shaped species built from what the team builder already knows (no weight)."""
    return SpeciesInfo(
        canonical_id=canonical_id, showdown_id=showdown_id(name), name=name, dex_number=0, base_species_id=showdown_id(name), forme=None,
        types=tuple(t.capitalize() for t in types),
        base_stats={"hp": stats.hp, "atk": stats.attack, "def": stats.defense, "spa": stats.special_attack, "spd": stats.special_defense, "spe": stats.speed},
        abilities=tuple(abilities), weightkg=0.0, gender=None, required_item=None, battle_only=None, is_mega=is_mega, is_legal=True,
    )


def pokemon_from_species(
    species: SpeciesInfo,
    *,
    ability: str | None = None,
    ability_on: bool = False,
    item: str | None = None,
    nature: str | None = None,
    points: Mapping[str, int] | None = None,
    boosts: Mapping[str, int] | None = None,
    cur_hp: int | None = None,
    status: str = "",
    toxic_counter: int = 0,
    allies_fainted: int = 0,
) -> CalcPokemon:
    """Engine input for a catalogue species with the given set; unknown parts take defaults
    (first ability, no item, neutral nature, no points, full HP)."""
    return CalcPokemon(
        name=species.name, types=species.types, base_stats=dict(species.base_stats), weightkg=species.weightkg,
        ability=canonical_ability_name(ability) if ability else None, abilities=species.abilities, ability_on=ability_on,
        item=canonical_item_name(item) if item else None, nature=nature or None, points=calc_stat_table(points),
        boosts={k: max(-6, min(6, v)) for k, v in calc_stat_table(boosts).items()}, cur_hp=cur_hp,
        status=status if status in STATUS_KEYS else "", toxic_counter=int(toxic_counter or 0), allies_fainted=int(allies_fainted or 0),
        gender=species.gender if species.gender in ("M", "F", "N") else None,
    )


def build_calc_move(name: str | None, catalogs: DamageCatalogs, *, attacker_ability: str | None = None, is_crit: bool = False, hits: int | None = None,
                    times_used: int = 1, times_used_with_metronome: int = 1) -> CalcMove | None:
    """Engine move from the catalogue; None when the name is unknown there."""
    info = catalogs.move_by_name(name) if name else None
    if info is None:
        return None
    return CalcMove.from_info(info, is_crit=is_crit, hits=hits, times_used=times_used, times_used_with_metronome=times_used_with_metronome, attacker_ability=attacker_ability)


@dataclass(frozen=True)
class BuiltPokemon:
    """An engine input plus what had to be assumed to build it."""

    pokemon: CalcPokemon
    species: SpeciesInfo
    assumptions: tuple[str, ...] = ()
    moves: tuple[str, ...] = ()


def _item_name(reference: str | None, catalogs: DamageCatalogs) -> str | None:
    if not reference:
        return None
    record = catalogs.item_for(reference)
    display = getattr(record, "display_name", None) if record is not None else None
    return canonical_item_name(display or reference)


def build_from_slot(slot: Any, catalogs: DamageCatalogs) -> BuiltPokemon | None:
    """A team slot (``SlotModel``) as an attacker/defender: selected form, item, ability, moves
    and the stat-point spread. Falls back to the form's own stats when the species catalogue
    lacks the entry (weight then unknown)."""
    entry = getattr(slot, "entry", None)
    member = getattr(slot, "member", None)
    form = getattr(slot, "form", None)
    if entry is None or member is None or form is None:
        return None
    assumptions: list[str] = []
    canonical_id = member.selected_form if form.is_mega and member.selected_form else entry.pokemon.canonical_id
    species = catalogs.species_for(canonical_id)
    if species is None:
        fallback_ability = getattr(form, "ability", None)
        fallback_abilities = (fallback_ability,) if fallback_ability else tuple(getattr(form, "abilities", ())) or tuple(a.name.replace("-", " ").title() for a in entry.pokemon.abilities)
        species = species_from_form(canonical_id=canonical_id, name=form.label if form.is_mega else entry.pokemon.display_name, types=form.types, stats=form.stats,
                                    abilities=fallback_abilities, is_mega=form.is_mega)
        assumptions.append("species not in the Showdown catalogue: weight unknown (0 kg)")
    if form.is_mega:
        form_ability = getattr(form, "ability", None)
        mega_ability = canonical_ability_name(form_ability or (species.abilities[0] if species.abilities else None))
        member_ability = canonical_ability_name(member.ability) if member.ability else None
        if member_ability and member_ability == mega_ability:
            ability = member_ability
        elif mega_ability:
            ability = mega_ability
        else:
            ability = member_ability
    else:
        ability = canonical_ability_name(member.ability) if member.ability else None
        if ability is None and species.abilities:
            ability = species.abilities[0]
            assumptions.append(f"no ability set: {ability}")
    points = dict(getattr(member, "points", None) or {})
    if not points:
        assumptions.append("no stat points set")
    nature = member.nature
    if not nature:
        assumptions.append("no nature set: neutral")
    item = getattr(slot, "item", None)
    item_name = _item_name(item.display_name if item is not None else member.item, catalogs)
    moves = tuple(m.name for m in (member.moveset or []) if getattr(m, "name", None))
    pokemon = pokemon_from_species(species, ability=ability, item=item_name, nature=nature, points=points)
    return BuiltPokemon(pokemon=pokemon, species=species, assumptions=tuple(assumptions), moves=moves)


def build_from_roster_member(member: Any, parsed_slot: Any, catalogs: DamageCatalogs) -> BuiltPokemon | None:
    """A tournament roster member (``MetaMemberRow``) with, when the paste has them, its item,
    ability, nature, stat points and moves (``ParsedSlot``)."""
    canonical_id = getattr(member, "canonical_id", None) or canonical_id_from_showdown(getattr(member, "species_name", "") or "")
    species = catalogs.species_for(canonical_id)
    if species is None:
        return None
    assumptions: list[str] = []
    if species.is_mega:
        mega_ability = canonical_ability_name(species.abilities[0] if species.abilities else None)
        parsed_ability = canonical_ability_name(getattr(parsed_slot, "ability_name", None)) if parsed_slot is not None and getattr(parsed_slot, "ability_name", None) else None
        if parsed_ability and parsed_ability == mega_ability:
            ability = parsed_ability
        elif mega_ability:
            ability = mega_ability
        else:
            ability = parsed_ability
    else:
        ability = canonical_ability_name(getattr(parsed_slot, "ability_name", None)) if parsed_slot is not None and getattr(parsed_slot, "ability_name", None) else None
        if ability is None and species.abilities:
            ability = species.abilities[0]
            assumptions.append(f"ability not in the paste: {ability}")
    item = _item_name(getattr(parsed_slot, "item_name", None), catalogs) if parsed_slot is not None else None
    if item is None:
        assumptions.append("no item in the paste")
    points = dict(getattr(parsed_slot, "points", None) or {}) if parsed_slot is not None else {}
    if not points:
        assumptions.append("no spread in the paste: 0 points")
    nature = getattr(parsed_slot, "nature", None) if parsed_slot is not None else None
    if not nature:
        assumptions.append("no nature in the paste: neutral")
    moves = tuple(getattr(parsed_slot, "moves", ()) or ()) if parsed_slot is not None else ()
    pokemon = pokemon_from_species(species, ability=ability, item=item, nature=nature, points=points)
    return BuiltPokemon(pokemon=pokemon, species=species, assumptions=tuple(assumptions), moves=moves)


@dataclass(frozen=True)
class MatchupResult:
    move_name: str
    move: CalcMove
    result: DamageResult


def matchup(attacker: BuiltPokemon, moves: Sequence[str], defender: BuiltPokemon, field: Field, catalogs: DamageCatalogs) -> list[MatchupResult]:
    """Damaging moves of ``attacker`` against ``defender``, in the order given; unknown and
    status moves are skipped."""
    out: list[MatchupResult] = []
    for name in moves:
        move = build_calc_move(name, catalogs, attacker_ability=attacker.pokemon.ability or (attacker.species.abilities[0] if attacker.species.abilities else None))
        if move is None or move.category == "Status":
            continue
        out.append(MatchupResult(move_name=name, move=move, result=calculate(attacker.pokemon, defender.pokemon, move, field)))
    return out


def slot_vs_slot(a: Any, b: Any, field: Field, catalogs: DamageCatalogs) -> tuple[list[MatchupResult], list[MatchupResult]]:
    """Both directions between two team slots."""
    left = build_from_slot(a, catalogs)
    right = build_from_slot(b, catalogs)
    if left is None or right is None:
        return [], []
    return matchup(left, left.moves, right, field, catalogs), matchup(right, right.moves, left, field, catalogs)


__all__ = [
    "BuiltPokemon", "DamageCatalogs", "MatchupResult", "STATUS_KEYS", "build_calc_move", "build_from_roster_member", "build_from_slot",
    "calc_stat_table", "default_field", "matchup", "pokemon_from_species", "slot_vs_slot", "species_from_form",
]

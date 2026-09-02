"""Species catalogue types and the id rules between our slugs and Showdown's names.

The catalogue (base stats, types, abilities, weight, forms) comes from Showdown's
``pokedex.json``. Its species are named the calculator's way ("Charizard-Mega-Y",
"Rotom-Wash", "Basculegion-F") and keyed by a lowercase alphanumeric id
("charizardmegay"). Our canonical ids are hyphenated slugs; rosters imported from pastes
already use the Showdown-derived form ("rotom-wash", "basculegion-f"), while PokéAPI-derived
ids spell some default forms differently ("basculegion-male", "urshifu-single-strike"), so
``resolve_species_key`` maps both spellings onto the catalogue.
"""

from __future__ import annotations

import re
from collections.abc import Iterable
from dataclasses import dataclass

from .entities.pokemon_stats import PokemonStats

_NON_ALNUM = re.compile(r"[^a-z0-9]")
_SLUG_DROP = re.compile(r"[.'’:%]")

# PokéAPI-style ids whose Showdown counterpart is spelled differently.
CANONICAL_ALIASES: dict[str, str] = {
    "basculegion-male": "basculegion", "basculegion-female": "basculegion-f",
    "meowstic-male": "meowstic", "meowstic-female": "meowstic-f",
    "indeedee-male": "indeedee", "indeedee-female": "indeedee-f",
    "oinkologne-male": "oinkologne", "oinkologne-female": "oinkologne-f",
    "urshifu-single-strike": "urshifu", "aegislash-shield": "aegislash", "mimikyu-disguised": "mimikyu",
    "morpeko-full-belly": "morpeko", "toxtricity-amped": "toxtricity", "toxtricity-low-key": "toxtricity-low-key",
    "palafin-zero": "palafin", "gourgeist-average": "gourgeist", "pumpkaboo-average": "pumpkaboo",
    "maushold-family-of-three": "maushold", "maushold-family-of-four": "maushold-four",
    "lycanroc-midday": "lycanroc", "tatsugiri-curly": "tatsugiri", "ogerpon-teal-mask": "ogerpon",
    "tauros-paldea-combat-breed": "tauros-paldea-combat", "tauros-paldea-blaze-breed": "tauros-paldea-blaze", "tauros-paldea-aqua-breed": "tauros-paldea-aqua",
    "tauros-paldea": "tauros-paldea-combat", "dudunsparce-two-segment": "dudunsparce", "squawkabilly-green-plumage": "squawkabilly",
    "wormadam-plant": "wormadam", "keldeo-ordinary": "keldeo", "meloetta-aria": "meloetta", "shaymin-land": "shaymin",
    "giratina-altered": "giratina", "deoxys-normal": "deoxys", "darmanitan-standard": "darmanitan", "basculin-red-striped": "basculin",
    "wishiwashi-solo": "wishiwashi", "eiscue-ice": "eiscue", "minior-red-meteor": "minior", "oricorio-baile": "oricorio",
    "zygarde-50": "zygarde", "terapagos-normal": "terapagos", "mr-mime": "mr-mime", "mime-jr": "mime-jr",
}


@dataclass(frozen=True)
class SpeciesInfo:
    """One species or form from the catalogue."""

    canonical_id: str
    showdown_id: str
    name: str                      # calculator/Showdown name, e.g. "Charizard-Mega-Y"
    dex_number: int
    base_species_id: str           # showdown id of the base species (itself for a base form)
    forme: str | None
    types: tuple[str, ...]         # capitalised, as Showdown writes them
    base_stats: dict[str, int]     # calc keys: hp atk def spa spd spe
    abilities: tuple[str, ...]     # slots 0, 1, H — the first is the default
    weightkg: float
    gender: str | None             # "M" | "F" | "N" | None (either)
    required_item: str | None      # mega stone
    battle_only: str | None
    is_mega: bool
    is_legal: bool                 # Champions legality

    @property
    def stats(self) -> PokemonStats:
        b = self.base_stats
        return PokemonStats(hp=b["hp"], attack=b["atk"], defense=b["def"], sp_atk=b["spa"], sp_def=b["spd"], speed=b["spe"])

    @property
    def types_lower(self) -> tuple[str, ...]:
        return tuple(t.lower() for t in self.types)

    @property
    def display_name(self) -> str:
        return self.name


def showdown_id(name: str | None) -> str:
    return _NON_ALNUM.sub("", (name or "").lower())


def canonical_id_from_showdown(name: str) -> str:
    """"Charizard-Mega-Y" → "charizard-mega-y", "Mr. Rime" → "mr-rime", "Basculegion-F" → "basculegion-f"."""
    slug = _SLUG_DROP.sub("", (name or "").strip().lower())
    slug = re.sub(r"[\s_]+", "-", slug)
    slug = re.sub(r"-{2,}", "-", slug)
    return slug.strip("-")


def resolve_species_key(canonical_id: str | None, available: Iterable[str]) -> str | None:
    """Find the catalogue key (our canonical id) for ``canonical_id``.

    Exact match first, then the PokéAPI alias table, then the same id with its trailing
    segments dropped ("garchomp-mega" stays; "rotom-wash-x" → "rotom-wash" → "rotom").
    Megas are their own rows, so the mega suffix is never stripped on purpose.
    """
    if not canonical_id:
        return None
    keys = available if isinstance(available, (set, frozenset, dict)) else set(available)
    cid = canonical_id.strip().lower()
    if cid in keys:
        return cid
    alias = CANONICAL_ALIASES.get(cid)
    if alias and alias in keys:
        return alias
    stripped = _NON_ALNUM.sub("", cid)
    by_alnum = {_NON_ALNUM.sub("", k): k for k in keys}
    if stripped in by_alnum:
        return by_alnum[stripped]
    parts = cid.split("-")
    while len(parts) > 1:
        parts.pop()
        candidate = "-".join(parts)
        if candidate in keys:
            return candidate
    return None


__all__ = ["CANONICAL_ALIASES", "SpeciesInfo", "canonical_id_from_showdown", "resolve_species_key", "showdown_id"]

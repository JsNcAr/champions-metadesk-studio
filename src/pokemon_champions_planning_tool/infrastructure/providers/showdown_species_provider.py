"""Species data from Pokémon Showdown: base stats, types, abilities, weight, forms.

Two files: ``pokedex.json`` from the play.pokemonshowdown.com data bundle (every species and
form) and ``data/mods/champions/formats-data.ts`` from the Showdown repository, whose entries
mark which of them exist in Pokémon Champions (legal = no ``isNonstandard`` and not
``tier: "Illegal"``).
"""

from __future__ import annotations

import json
import re
from dataclasses import dataclass, field
from typing import Any

import requests

from ...config import SHOWDOWN_CHAMPIONS_FORMATS_DATA_URL, SHOWDOWN_POKEDEX_JSON_URL, TOURNAMENT_SYNC_TIMEOUT, TOURNAMENT_USER_AGENT
from ...domain.species import canonical_id_from_showdown, showdown_id

_FORMATS_BLOCK_RE = re.compile(r"\n\t(\w+): \{(.*?)\n\t\}", re.S)


class ShowdownSpeciesNetworkError(Exception):
    """Raised when either source cannot be fetched."""


@dataclass(frozen=True)
class SpeciesDTO:
    showdown_id: str
    canonical_id: str
    name: str
    dex_number: int
    base_species_id: str
    forme: str | None
    types: tuple[str, ...]
    base_stats: dict[str, int]
    abilities: tuple[str, ...]
    hidden_ability: str | None
    weightkg: float
    gender: str | None
    required_item: str | None
    battle_only: str | None
    is_mega: bool
    is_legal: bool


@dataclass(frozen=True)
class SpeciesCatalogPayload:
    species: tuple[SpeciesDTO, ...]
    legal_ids: frozenset[str] = field(default_factory=frozenset)


def parse_formats_data_ts(text: str) -> frozenset[str]:
    """Showdown ids of the species Champions allows."""
    legal: set[str] = set()
    for m in _FORMATS_BLOCK_RE.finditer(text):
        key, body = m.group(1), m.group(2)
        if "isNonstandard" in body or 'tier: "Illegal"' in body:
            continue
        legal.add(key)
    return frozenset(legal)


def build_species_catalog(pokedex: dict[str, Any], legal_ids: frozenset[str]) -> SpeciesCatalogPayload:
    species: list[SpeciesDTO] = []
    for key, raw in pokedex.items():
        if not isinstance(raw, dict) or not raw.get("name") or not raw.get("baseStats"):
            continue
        if raw.get("isNonstandard") in ("CAP", "Custom") or int(raw.get("num", 0) or 0) <= 0:
            continue
        abilities_raw = raw.get("abilities") or {}
        abilities = tuple(str(abilities_raw[k]) for k in ("0", "1", "H", "S") if abilities_raw.get(k))
        base_stats = {k: int(raw["baseStats"].get(k, 0)) for k in ("hp", "atk", "def", "spa", "spd", "spe")}
        base_species = raw.get("baseSpecies") or raw["name"]
        forme = raw.get("forme") or None
        battle_only = raw.get("battleOnly")
        if isinstance(battle_only, list):
            battle_only = battle_only[0] if battle_only else None
        species.append(SpeciesDTO(
            showdown_id=key,
            canonical_id=canonical_id_from_showdown(str(raw["name"])),
            name=str(raw["name"]),
            dex_number=int(raw.get("num", 0) or 0),
            base_species_id=showdown_id(base_species),
            forme=str(forme) if forme else None,
            types=tuple(str(t) for t in raw.get("types") or ()),
            base_stats=base_stats,
            abilities=abilities,
            hidden_ability=str(abilities_raw["H"]) if abilities_raw.get("H") else None,
            weightkg=float(raw.get("weightkg") or 0.0),
            gender=str(raw["gender"]) if raw.get("gender") else None,
            required_item=str(raw["requiredItem"]) if raw.get("requiredItem") else None,
            battle_only=str(battle_only) if battle_only else None,
            is_mega=bool(forme and str(forme).startswith("Mega")),
            is_legal=key in legal_ids,
        ))
    return SpeciesCatalogPayload(species=tuple(species), legal_ids=legal_ids)


class ShowdownSpeciesProvider:
    def __init__(self, timeout: int = TOURNAMENT_SYNC_TIMEOUT, user_agent: str = TOURNAMENT_USER_AGENT) -> None:
        self.timeout = timeout
        self.user_agent = user_agent

    def _get_text(self, url: str) -> str:
        try:
            resp = requests.get(url, headers={"User-Agent": self.user_agent}, timeout=max(self.timeout, 30))
            resp.raise_for_status()
            return resp.text
        except Exception as exc:  # noqa: BLE001 - one error type for callers
            raise ShowdownSpeciesNetworkError(f"Failed to fetch {url}: {exc}") from exc

    def fetch_species_catalog(self) -> SpeciesCatalogPayload:
        pokedex = json.loads(self._get_text(SHOWDOWN_POKEDEX_JSON_URL))
        legal = parse_formats_data_ts(self._get_text(SHOWDOWN_CHAMPIONS_FORMATS_DATA_URL))
        if not legal:
            raise ShowdownSpeciesNetworkError("Champions formats data parsed to nothing")
        payload = build_species_catalog(pokedex, legal)
        if len(payload.species) < 500:
            raise ShowdownSpeciesNetworkError("Showdown pokedex parsed to too few species")
        return payload


__all__ = ["ShowdownSpeciesNetworkError", "ShowdownSpeciesProvider", "SpeciesCatalogPayload", "SpeciesDTO", "build_species_catalog", "parse_formats_data_ts"]

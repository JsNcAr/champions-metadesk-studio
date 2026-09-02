"""Move data and Champions learnsets from Pokémon Showdown.

Three files, three requests, all static:
- ``moves.json`` from the play.pokemonshowdown.com data bundle: every move with type,
  category, base power, accuracy, PP, priority, target and description.
- ``data/mods/champions/learnsets.ts`` from the Showdown repository: for each species
  Champions can use, the moves it can learn there.
- ``data/mods/champions/moves.ts``: moves Champions removed (``isNonstandard: "Past"``),
  restored (``isNonstandard: null``) or rebalanced (base power, PP, accuracy, flags,
  secondary effects, self stat drops).

Legality: a move is legal in Champions when the mod does not remove it and it is either
current in the base data or explicitly restored by the mod.

The TypeScript files are plain object literals; a couple of regular expressions read
them without a JavaScript parser.
"""

from __future__ import annotations

import json
import re
from dataclasses import dataclass, field
from typing import Any

import requests

from ...config import (
    SHOWDOWN_CHAMPIONS_LEARNSETS_URL,
    SHOWDOWN_CHAMPIONS_MOVES_URL,
    SHOWDOWN_MOVES_JSON_URL,
    TOURNAMENT_SYNC_TIMEOUT,
    TOURNAMENT_USER_AGENT,
)

_SPECIES_BLOCK_RE = re.compile(r"\n\t(\w+): \{\n\t\tlearnset: \{(.*?)\n\t\}", re.S)
_LEARNSET_MOVE_RE = re.compile(r"\n\t\t\t(\w+): \[")
_MOVE_BLOCK_RE = re.compile(r"\n\t(\w+): \{(.*?)\n\t\},", re.S)
_NUMBER_FIELD_RE = re.compile(r"\b(basePower|accuracy|pp|priority): (-?\d+|true)")
_STRING_FIELD_RE = re.compile(r"\b(type|category|target): \"([^\"]+)\"")
_FLAGS_RE = re.compile(r"\bflags: \{([^}]*)\}")
_FLAG_RE = re.compile(r"(\w+): 1")
_SELF_BOOSTS_RE = re.compile(r"\bself: \{\s*boosts: \{([^}]*)\}")
_BOOST_RE = re.compile(r"(\w+): (-?\d+)")
_SECONDARY_UNDEFINED_RE = re.compile(r"\n\t\tsecondary: undefined")
_SECONDARY_OBJECT_RE = re.compile(r"\n\t\tsecondary: \{")
_RELEGALIZED_RE = re.compile(r"\n\t\tisNonstandard: null")
_MECHANICS_FLAGS = ("contact", "sound", "punch", "bite", "bullet", "pulse", "slicing", "wind")


class ShowdownMovesNetworkError(Exception):
    """Raised when any of the three sources cannot be fetched."""


@dataclass(frozen=True)
class MoveDTO:
    move_id: str
    name: str
    type: str | None
    category: str | None
    power: int | None
    accuracy: int | None
    pp: int | None
    priority: int
    target: str | None
    short_desc: str | None
    is_legal: bool
    mechanics: dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class MoveCatalogPayload:
    moves: tuple[MoveDTO, ...]
    learnsets: dict[str, tuple[str, ...]] = field(default_factory=dict)  # species key -> move ids
    removed: frozenset[str] = frozenset()
    changed: int = 0


def parse_learnsets_ts(text: str) -> dict[str, tuple[str, ...]]:
    return {m.group(1): tuple(_LEARNSET_MOVE_RE.findall(m.group(2))) for m in _SPECIES_BLOCK_RE.finditer(text)}


def parse_move_overrides_ts(text: str) -> tuple[frozenset[str], dict[str, dict[str, Any]]]:
    """(removed move ids, {move id: field overrides}) from the Champions moves mod."""
    removed: set[str] = set()
    overrides: dict[str, dict[str, Any]] = {}
    for m in _MOVE_BLOCK_RE.finditer(text):
        move_id, body = m.group(1), m.group(2)
        if 'isNonstandard: "Past"' in body:
            removed.add(move_id)
            continue
        fields: dict[str, Any] = {}
        for key, value in _NUMBER_FIELD_RE.findall(body):
            fields[key] = True if value == "true" else int(value)
        for key, value in _STRING_FIELD_RE.findall(body):
            fields[key] = value
        flags = _FLAGS_RE.search(body)
        if flags:
            fields["flags"] = {name: 1 for name in _FLAG_RE.findall(flags.group(1))}
        if _SECONDARY_UNDEFINED_RE.search(body):
            fields["secondaries"] = False
        elif _SECONDARY_OBJECT_RE.search(body):
            fields["secondaries"] = True
        self_boosts = _SELF_BOOSTS_RE.search(body)
        if self_boosts:
            fields["self_boosts"] = {k: int(v) for k, v in _BOOST_RE.findall(self_boosts.group(1))}
        if _RELEGALIZED_RE.search(body):
            fields["isNonstandard"] = None
        if fields:
            overrides[move_id] = fields
    return frozenset(removed), overrides


def _pair(value: Any) -> list[int] | None:
    return [int(value[0]), int(value[1])] if isinstance(value, (list, tuple)) and len(value) == 2 else None


def mechanics_from_showdown(raw: dict[str, Any], over: dict[str, Any]) -> dict[str, Any]:
    """The ``MoveMechanics`` JSON for a Showdown move, with the Champions override applied."""
    flags = over.get("flags", raw.get("flags") or {})
    self_boosts = over.get("self_boosts")
    if self_boosts is None:
        self_block = raw.get("self")
        self_boosts = (self_block.get("boosts") or {}) if isinstance(self_block, dict) else {}
    secondaries = over["secondaries"] if "secondaries" in over else bool(raw.get("secondary") or raw.get("secondaries"))
    multihit = raw.get("multihit")
    out: dict[str, Any] = {}
    for name in _MECHANICS_FLAGS:
        if flags.get(name):
            out[name] = True
    if secondaries:
        out["secondaries"] = True
    if _pair(raw.get("recoil")):
        out["recoil"] = _pair(raw.get("recoil"))
    if _pair(raw.get("drain")):
        out["drain"] = _pair(raw.get("drain"))
    if isinstance(multihit, int) and not isinstance(multihit, bool):
        out["multihit"] = multihit
    elif _pair(multihit):
        out["multihit"] = _pair(multihit)
    if raw.get("multiaccuracy"):
        out["multiaccuracy"] = True
    if raw.get("willCrit"):
        out["will_crit"] = True
    if raw.get("critRatio"):
        out["crit_ratio"] = int(raw["critRatio"])
    if raw.get("ignoreDefensive"):
        out["ignore_defensive"] = True
    for src, dst in (("overrideOffensiveStat", "override_offensive_stat"), ("overrideDefensiveStat", "override_defensive_stat"), ("overrideOffensivePokemon", "override_offensive_pokemon")):
        if raw.get(src):
            out[dst] = str(raw[src])
    for src, dst in (("breaksProtect", "breaks_protect"), ("hasCrashDamage", "has_crash_damage"), ("struggleRecoil", "struggle_recoil"), ("mindBlownRecoil", "mind_blown_recoil"), ("ohko", "ohko")):
        if raw.get(src):
            out[dst] = True
    if self_boosts:
        out["self_boosts"] = [[str(k), int(v)] for k, v in self_boosts.items()]
    return out


def build_catalog(moves_json: dict[str, Any], learnsets: dict[str, tuple[str, ...]], removed: frozenset[str], overrides: dict[str, dict[str, Any]]) -> MoveCatalogPayload:
    moves: list[MoveDTO] = []
    for move_id, raw in moves_json.items():
        if not isinstance(raw, dict) or not raw.get("name"):
            continue
        if raw.get("isNonstandard") in ("CAP", "Custom"):
            continue
        over = overrides.get(move_id, {})
        accuracy = over.get("accuracy", raw.get("accuracy"))
        moves.append(
            MoveDTO(
                move_id=move_id,
                name=str(raw["name"]),
                type=str(over.get("type", raw.get("type")) or "") or None,
                category=str(over.get("category", raw.get("category")) or "") or None,
                power=int(over.get("basePower", raw.get("basePower") or 0)) or None,
                accuracy=None if accuracy is True else (int(accuracy) if accuracy is not None else None),
                pp=int(over.get("pp", raw.get("pp") or 0)) or None,
                priority=int(over.get("priority", raw.get("priority") or 0)),
                target=str(raw.get("target") or "") or None,
                short_desc=str(raw.get("shortDesc") or raw.get("desc") or "") or None,
                is_legal=move_id not in removed and (raw.get("isNonstandard") is None or ("isNonstandard" in over and over["isNonstandard"] is None)),
                mechanics=mechanics_from_showdown(raw, over),
            )
        )
    return MoveCatalogPayload(moves=tuple(moves), learnsets=learnsets, removed=removed, changed=len(overrides))


class ShowdownMovesProvider:
    def __init__(self, timeout: int = TOURNAMENT_SYNC_TIMEOUT, user_agent: str = TOURNAMENT_USER_AGENT) -> None:
        self.timeout = timeout
        self.user_agent = user_agent

    def _get_text(self, url: str) -> str:
        try:
            resp = requests.get(url, headers={"User-Agent": self.user_agent}, timeout=max(self.timeout, 30))
            resp.raise_for_status()
            return resp.text
        except Exception as exc:  # noqa: BLE001 - one error type for callers
            raise ShowdownMovesNetworkError(f"Failed to fetch {url}: {exc}") from exc

    def fetch_move_catalog(self) -> MoveCatalogPayload:
        moves_json = json.loads(self._get_text(SHOWDOWN_MOVES_JSON_URL))
        learnsets = parse_learnsets_ts(self._get_text(SHOWDOWN_CHAMPIONS_LEARNSETS_URL))
        removed, overrides = parse_move_overrides_ts(self._get_text(SHOWDOWN_CHAMPIONS_MOVES_URL))
        if not learnsets:
            raise ShowdownMovesNetworkError("Champions learnsets file parsed to nothing")
        return build_catalog(moves_json, learnsets, removed, overrides)


__all__ = ["MoveCatalogPayload", "MoveDTO", "ShowdownMovesNetworkError", "ShowdownMovesProvider", "build_catalog", "mechanics_from_showdown", "parse_learnsets_ts", "parse_move_overrides_ts"]

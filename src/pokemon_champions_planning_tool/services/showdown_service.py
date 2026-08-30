"""Showdown format serialization, parsing, and Pokepast integration.

Public surface
--------------
* :func:`export_team_to_showdown_text` — Team → Showdown text string.
* :func:`parse_showdown_text` — Showdown text → :class:`ParsedTeamResult`.
* :func:`resolve_import_readiness` — Cross-reference parsed slots vs. the box.
* :func:`commit_import` — Transactional write of a parsed team to the DB.
* :func:`import_from_pokepast_url` — Fetch + parse a Pokepast paste.
* :func:`publish_to_pokepast` — Serialize + publish a team to Pokepast.es.

Data Transfer Objects (immutable frozen dataclasses)
----------------------------------------------------
* :class:`ParsedSlot`
* :class:`ParsedTeamResult`
* :class:`ImportReadinessReport`
* :class:`ShowdownExportResult`
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Optional
from uuid import UUID

if TYPE_CHECKING:
    from ..infrastructure.database.repositories import BoxRepository
    from ..infrastructure.providers.pokepast_provider import PokepastProvider

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

_STAT_KEYS = ("hp", "attack", "defense", "special_attack", "special_defense", "speed")

_SHOWDOWN_STAT_ALIASES: dict[str, str] = {
    "hp": "hp",
    "atk": "attack",
    "def": "defense",
    "spa": "special_attack",
    "spd": "special_defense",
    "spe": "speed",
    "attack": "attack",
    "defense": "defense",
    "special_attack": "special_attack",
    "special_defense": "special_defense",
    "speed": "speed",
}

_SHOWDOWN_STAT_LABELS: dict[str, str] = {
    "hp": "HP",
    "attack": "Atk",
    "defense": "Def",
    "special_attack": "SpA",
    "special_defense": "SpD",
    "speed": "Spe",
}

# ---------------------------------------------------------------------------
# DTOs
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class ParsedSlot:
    """A single Pokémon slot parsed from Showdown format text."""

    raw_header: str
    species_name: str           # e.g. "Iron Hands"
    showdown_form_key: str      # e.g. "iron-hands" (normalised Showdown key)
    nickname: Optional[str] = None
    resolved_canonical_id: Optional[str] = None  # Set after catalog resolution
    item_name: Optional[str] = None
    ability_name: Optional[str] = None
    level: int = 50
    gender: Optional[str] = None   # "M", "F", or None
    shiny: bool = False
    tera_type: Optional[str] = None
    moves: tuple[str, ...] = field(default_factory=tuple)
    evs: dict[str, int] = field(default_factory=dict)
    ivs: dict[str, int] = field(default_factory=dict)
    nature: Optional[str] = None


@dataclass(frozen=True)
class ParsedTeamResult:
    """Result returned by the Showdown parser."""

    title: Optional[str]
    author: Optional[str]
    notes: Optional[str]
    slots: tuple[ParsedSlot, ...]
    warnings: tuple[str, ...]
    is_valid: bool   # True if at least one slot was parsed without fatal error


@dataclass(frozen=True)
class ImportReadinessReport:
    """Cross-reference result between parsed slots and the user's box."""

    in_box: tuple[ParsedSlot, ...]        # Has a matching BoxEntry already
    missing: tuple[ParsedSlot, ...]       # Not in box, but found in catalog
    unresolvable: tuple[ParsedSlot, ...]  # Not found anywhere
    illegal_species: tuple[ParsedSlot, ...] = field(default_factory=tuple) # Species not legal in Champions
    warnings: tuple[str, ...] = field(default_factory=tuple)


@dataclass(frozen=True)
class ShowdownExportResult:
    """Result returned when exporting a team."""

    team_id: str
    team_name: str
    showdown_text: str
    pokepast_url: Optional[str] = None


# ---------------------------------------------------------------------------
# Export
# ---------------------------------------------------------------------------


def export_team_to_showdown_text(
    team_members: list,
    box_entries_by_id: dict[UUID, object],
) -> str:
    """Serialize a list of TeamMember domain objects to Showdown paste format.

    Args:
        team_members: List of :class:`~domain.entities.team_member.TeamMember`.
        box_entries_by_id: Mapping of box_entry_id → :class:`~domain.entities.box_entry.BoxEntry`.

    Returns:
        Multi-block Showdown text string.  Blocks are separated by ``\\n\\n``.
    """
    blocks: list[str] = []

    for member in sorted(team_members, key=lambda m: m.slot_position):
        box_entry = box_entries_by_id.get(member.box_entry_id)
        if box_entry is None:
            continue
        pokemon = box_entry.pokemon

        # --- Header line ---
        display = pokemon.display_name
        item_part = f" @ {member.item}" if member.item else ""
        header = f"{display}{item_part}"

        lines = [header]

        # --- Ability ---
        if member.ability:
            lines.append(f"Ability: {member.ability}")

        # --- Level (omit if 50, the VGC default) ---
        if member.level != 50:
            lines.append(f"Level: {member.level}")

        # --- Shiny (omit false) ---
        if getattr(box_entry, "shiny", False):
            lines.append("Shiny: Yes")

        # --- EVs ---
        if member.evs:
            ev_parts = [
                f"{v} {_SHOWDOWN_STAT_LABELS[k]}"
                for k, v in member.evs.items()
                if v and k in _SHOWDOWN_STAT_LABELS
            ]
            if ev_parts:
                lines.append(f"EVs: {' / '.join(ev_parts)}")

        # --- Nature ---
        if member.nature:
            lines.append(f"{member.nature} Nature")

        # --- IVs (only non-31 values) ---
        if member.ivs:
            iv_parts = [
                f"{v} {_SHOWDOWN_STAT_LABELS[k]}"
                for k, v in member.ivs.items()
                if v != 31 and k in _SHOWDOWN_STAT_LABELS
            ]
            if iv_parts:
                lines.append(f"IVs: {' / '.join(iv_parts)}")

        # --- Moves ---
        for move in member.moveset[:4]:
            move_name = getattr(move, "name", str(move))
            if move_name:
                lines.append(f"- {move_name}")

        blocks.append("\n".join(lines))

    return "\n\n".join(blocks)


# ---------------------------------------------------------------------------
# Parser (Right-to-Left Step-Based Header Parsing)
# ---------------------------------------------------------------------------

_EV_IV_PART_RE = re.compile(r"(\d+)\s+([A-Za-z/]+)")
_GENDER_RE = re.compile(r"\s+\(([MF])\)\s*$", re.IGNORECASE)


def _parse_spread_line(line: str) -> dict[str, int]:
    """Parse ``252 HP / 4 Def / 252 Spe`` into ``{hp: 252, defense: 4, speed: 252}``."""
    result: dict[str, int] = {}
    for m in _EV_IV_PART_RE.finditer(line):
        value = int(m.group(1))
        raw_key = m.group(2).strip().lower().rstrip("/").strip()
        canonical = _SHOWDOWN_STAT_ALIASES.get(raw_key)
        if canonical:
            result[canonical] = value
    return result


def _parse_header(raw_line: str) -> tuple[str, Optional[str], Optional[str], Optional[str]]:
    """Right-to-Left step-based header parser.

    Handles all formats including:
    - ``Nickname (Species-Form) (M) @ Item Name``
    - ``Species-Form (F) @ Item Name``
    - ``Iron Hands @ Booster Energy``
    - ``Type: Null``
    - ``Ho-Oh``

    Returns:
        (species_raw, nickname, gender, item)
    """
    line = raw_line.strip()

    # Step 1: Split on last " @ " to extract item
    item: Optional[str] = None
    if " @ " in line:
        at_idx = line.rfind(" @ ")
        item = line[at_idx + 3:].strip() or None
        line = line[:at_idx].strip()

    # Step 2: Extract gender suffix "(M)" or "(F)"
    gender: Optional[str] = None
    m = _GENDER_RE.search(line)
    if m:
        gender = m.group(1).upper()
        line = line[:m.start()].strip()

    # Step 3: Check for "(Species)" pattern at end → indicates a nickname precedes it
    nickname: Optional[str] = None
    species_raw: str = line

    if line.endswith(")"):
        # Find the matching opening paren
        open_idx = line.rfind("(")
        if open_idx > 0:
            candidate_species = line[open_idx + 1:-1].strip()
            candidate_nickname = line[:open_idx].strip()
            # Only treat as nickname+species if the "nickname" is non-empty
            if candidate_nickname:
                nickname = candidate_nickname
                species_raw = candidate_species

    return species_raw, nickname, gender, item


def _normalize_showdown_key(raw: str) -> str:
    """Convert a species/form string to the normalised Showdown key format."""
    return raw.strip().lower().replace(" ", "-").replace("'", "")


def parse_showdown_text(paste_text: str) -> ParsedTeamResult:
    """Parse raw Showdown-format text into a :class:`ParsedTeamResult`.

    The parser is line-based and uses a deterministic state machine:
    - A **header line** starts a new slot (not beginning with ``-``, not a
      key-value property, and not blank).
    - **Property lines** (``Ability:``, ``Level:``, ``EVs:``, ``IVs:``,
      ``Tera Type:``, ``Shiny:``, ``<Nature> Nature``) populate the current slot.
    - **Move lines** start with ``- ``.
    - **Blank lines** commit the current slot and start a new one.

    Non-fatal issues are collected in :attr:`ParsedTeamResult.warnings` rather
    than raising exceptions.
    """
    slots: list[ParsedSlot] = []
    warnings: list[str] = []

    # State for the current slot being built
    _header: Optional[str] = None
    _species_raw: Optional[str] = None
    _nickname: Optional[str] = None
    _gender: Optional[str] = None
    _item: Optional[str] = None
    _ability: Optional[str] = None
    _level: int = 50
    _shiny: bool = False
    _tera: Optional[str] = None
    _nature: Optional[str] = None
    _evs: dict[str, int] = {}
    _ivs: dict[str, int] = {}
    _moves: list[str] = []

    _PROPERTY_PREFIXES = (
        "ability:", "level:", "evs:", "ivs:", "tera type:", "shiny:",
        "nature:",  # sometimes written as explicit "nature: jolly"
    )
    _NATURE_NAMES = {
        "hardy", "lonely", "brave", "adamant", "naughty", "bold", "docile",
        "relaxed", "impish", "lax", "timid", "hasty", "serious", "jolly",
        "naive", "modest", "mild", "quiet", "bashful", "rash", "calm",
        "gentle", "sassy", "careful", "quirky",
    }

    def _is_property_line(line: str) -> bool:
        l = line.lower()
        return any(l.startswith(p) for p in _PROPERTY_PREFIXES)

    def _is_nature_line(line: str) -> bool:
        parts = line.strip().lower().split()
        return len(parts) == 2 and parts[0] in _NATURE_NAMES and parts[1] == "nature"

    def _is_move_line(line: str) -> bool:
        return line.startswith("- ")

    def _commit_slot():
        nonlocal _header, _species_raw, _nickname, _gender, _item
        nonlocal _ability, _level, _shiny, _tera, _nature, _evs, _ivs, _moves
        if _species_raw is None:
            return
        key = _normalize_showdown_key(_species_raw)
        slots.append(ParsedSlot(
            raw_header=_header or "",
            species_name=_species_raw.strip(),
            showdown_form_key=key,
            nickname=_nickname,
            item_name=_item,
            ability_name=_ability,
            level=_level,
            gender=_gender,
            shiny=_shiny,
            tera_type=_tera,
            moves=tuple(_moves[:4]),
            evs=dict(_evs),
            ivs=dict(_ivs),
            nature=_nature,
        ))
        # Reset state
        _header = _species_raw = _nickname = _gender = _item = None
        _ability = _tera = _nature = None
        _level = 50
        _shiny = False
        _evs = {}
        _ivs = {}
        _moves = []

    lines = paste_text.splitlines()
    for raw_line in lines:
        line = raw_line.rstrip()

        # Blank line → commit current slot
        if not line.strip():
            _commit_slot()
            continue

        # Move line
        if _is_move_line(line) and _species_raw is not None:
            move_name = line[2:].strip()
            if move_name:
                _moves.append(move_name)
            continue

        # Property lines
        ll = line.lower().strip()
        if ll.startswith("ability:"):
            _ability = line.split(":", 1)[1].strip() or None
            continue
        if ll.startswith("level:"):
            try:
                _level = int(line.split(":", 1)[1].strip())
            except ValueError:
                warnings.append(f"Could not parse level from: {line!r}")
            continue
        if ll.startswith("evs:"):
            _evs = _parse_spread_line(line.split(":", 1)[1])
            continue
        if ll.startswith("ivs:"):
            _ivs = _parse_spread_line(line.split(":", 1)[1])
            continue
        if ll.startswith("tera type:"):
            _tera = line.split(":", 1)[1].strip() or None
            continue
        if ll.startswith("shiny:"):
            _shiny = line.split(":", 1)[1].strip().lower() == "yes"
            continue
        if _is_nature_line(line):
            _nature = line.strip().split()[0].capitalize()
            continue

        # If it is not a known property/move, treat it as a header for a new slot
        if _species_raw is not None:
            # A new slot starts before a blank line — commit the previous one
            _commit_slot()

        _header = line
        _species_raw, _nickname, _gender, _item = _parse_header(line)
        if not _species_raw:
            warnings.append(f"Could not parse species from header: {line!r}")
            _species_raw = None

    # Commit any trailing slot not followed by a blank line
    _commit_slot()

    return ParsedTeamResult(
        title=None,
        author=None,
        notes=None,
        slots=tuple(slots),
        warnings=tuple(warnings),
        is_valid=len(slots) > 0,
    )


# ---------------------------------------------------------------------------
# Import Readiness
# ---------------------------------------------------------------------------


def resolve_import_readiness(
    parsed_result: ParsedTeamResult,
    box_repo: "BoxRepository",
    legal_species_catalog: set[str] | list[str] | None = None,
) -> ImportReadinessReport:
    """Cross-reference parsed slots against the user's box and format legality.

    Returns an :class:`ImportReadinessReport` categorising each slot as
    *in_box* (already owned), *missing* (not owned, but slot is parseable),
    *unresolvable* (species could not be identified at all), or *illegal_species*
    (not legal in Pokémon Champions format).
    """
    in_box: list[ParsedSlot] = []
    missing: list[ParsedSlot] = []
    unresolvable: list[ParsedSlot] = []
    illegal_species: list[ParsedSlot] = []
    warnings: list[str] = []

    # Build a lookup of canonical IDs already in the box
    real_entries = box_repo.list_entries(include_planned=False)
    owned_canonical_ids: set[str] = {e.pokemon.canonical_id for e in real_entries}

    catalog_set = set(legal_species_catalog) if legal_species_catalog else None

    for slot in parsed_result.slots:
        if not slot.species_name:
            unresolvable.append(slot)
            warnings.append(f"Slot {slot.raw_header!r}: species could not be identified.")
            continue

        # Check format legality if catalog is provided
        if catalog_set:
            s_name = slot.species_name.lower().strip()
            s_key = slot.showdown_form_key.lower().strip()
            is_legal = any(
                s_name == c.lower() or s_key == c.lower() or
                s_key.startswith(c.lower().split("-")[0]) or
                c.lower().startswith(s_key.split("-")[0])
                for c in catalog_set
            )
            if not is_legal:
                illegal_species.append(slot)
                warnings.append(f"⚠️ {slot.species_name} is NOT legal in Pokémon Champions format.")
                continue

        # Try to find a matching canonical ID by checking if any owned entry's
        # canonical_id or display_name matches the Showdown form key.
        matched = any(
            cid == slot.showdown_form_key or
            cid.startswith(slot.showdown_form_key.split("-")[0])
            for cid in owned_canonical_ids
        )
        # Also try exact display-name match
        if not matched:
            matched = any(
                e.pokemon.display_name.lower() == slot.species_name.lower()
                for e in real_entries
            )

        if matched:
            in_box.append(slot)
        else:
            missing.append(slot)

    return ImportReadinessReport(
        in_box=tuple(in_box),
        missing=tuple(missing),
        unresolvable=tuple(unresolvable),
        illegal_species=tuple(illegal_species),
        warnings=tuple(warnings),
    )



# ---------------------------------------------------------------------------
# Pokepast integration helpers
# ---------------------------------------------------------------------------


def import_from_pokepast_url(
    url_or_id: str,
    pokepast_provider: "PokepastProvider",
) -> ParsedTeamResult:
    """Fetch a Pokepast paste and parse it into a :class:`ParsedTeamResult`.

    Args:
        url_or_id: Full Pokepast URL or bare paste ID.
        pokepast_provider: Injected :class:`PokepastProvider` instance.

    Returns:
        Parsed team result with ``title``, ``author``, and ``notes`` populated
        from the Pokepast metadata.
    """
    from ..infrastructure.providers.pokepast_provider import PokepastProvider as _PP
    paste_id = _PP.extract_id_from_url(url_or_id) or url_or_id
    data = pokepast_provider.fetch_by_id(paste_id)
    result = parse_showdown_text(data.get("paste", ""))
    # Re-wrap with metadata from Pokepast
    return ParsedTeamResult(
        title=data.get("title") or result.title,
        author=data.get("author") or result.author,
        notes=data.get("notes") or result.notes,
        slots=result.slots,
        warnings=result.warnings,
        is_valid=result.is_valid,
    )


def publish_to_pokepast(
    team_members: list,
    box_entries_by_id: dict,
    team_name: str,
    team_id: str,
    pokepast_provider: "PokepastProvider",
    author: str = "Pokémon Champions Planning Tool",
    notes: str = "",
) -> ShowdownExportResult:
    """Serialize a team and publish it to Pokepast.es.

    Returns:
        :class:`ShowdownExportResult` with the generated ``pokepast_url``.
    """
    text = export_team_to_showdown_text(team_members, box_entries_by_id)
    url = pokepast_provider.publish(
        title=team_name,
        author=author,
        notes=notes,
        paste_text=text,
    )
    return ShowdownExportResult(
        team_id=team_id,
        team_name=team_name,
        showdown_text=text,
        pokepast_url=url,
    )

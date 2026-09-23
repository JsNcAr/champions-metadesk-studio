"""Showdown format serialization, parsing, and Pokepast integration.

Public surface
--------------
* :func:`export_team_to_showdown_text` — Team → Showdown text string.
* :func:`parse_showdown_text` — Showdown text → :class:`ParsedTeamResult`.
* :func:`resolve_import_readiness` — Cross-reference parsed slots vs. the box.
* :func:`commit_team_import` — Write a parsed team (and any missing box entries) to the DB.
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
from typing import TYPE_CHECKING, Iterable, Optional
from uuid import UUID

from ..domain.entities.pokemon_move import PokemonMove
from ..domain.stat_calc import MAX_POINTS_PER_STAT, MAX_POINTS_TOTAL, STAT_KEYS, format_points, points_from_evs, validate_points

if TYPE_CHECKING:
    from ..domain.entities.pokemon import Pokemon
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
    # Champions stat points. A paste's "EVs:" line carries points in Champions format; a
    # mainline 252-style spread is converted (and flagged) so its stats stay the same.
    points: dict[str, int] = field(default_factory=dict)
    points_converted: bool = False
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
    *,
    points_label: str = "EVs",
    tera: bool = True,
) -> str:
    """Serialize a list of TeamMember domain objects to Showdown paste format.

    Args:
        team_members: List of :class:`~domain.entities.team_member.TeamMember`.
        box_entries_by_id: Mapping of box_entry_id → :class:`~domain.entities.box_entry.BoxEntry`.
        points_label: Label of the stat-points line. Showdown's Champions format (and
            Poképaste) read stat points from the ``EVs:`` line, so text meant to be pasted
            elsewhere keeps the default. "Stat points" is for display; this app's importer
            reads either.
        tera: Write the ``Tera Type:`` line. False when the team's format has no
            Terastallization; the saved value is kept, only the text leaves it out.

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

        # --- Tera Type ---
        tera_type = getattr(member, "tera_type", None)
        if tera and tera_type:
            lines.append(f"Tera Type: {str(tera_type).strip().capitalize()}")

        # --- Shiny (omit false) ---
        if getattr(box_entry, "shiny", False):
            lines.append("Shiny: Yes")

        # --- Stat points (Showdown's Champions format reuses the EVs line for points) ---
        points = getattr(member, "points", None) or {}
        if points:
            spread = format_points(points)
            if spread:
                lines.append(f"{points_label}: {spread}")

        # --- Nature ---
        if member.nature:
            lines.append(f"{member.nature} Nature")

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


def _points_from_paste(values: dict[str, int]) -> tuple[dict[str, int], bool]:
    """Stat points from an "EVs:" line: verbatim when it already fits Champions' limits,
    otherwise converted from mainline EVs. Returns (points, converted)."""
    if not values:
        return {}, False
    # 33–35 in one stat is a typo in a points line, not an EV spread; anything larger is EVs.
    if any(v > MAX_POINTS_PER_STAT + 3 for v in values.values()) or sum(values.values()) > MAX_POINTS_TOTAL:
        return points_from_evs(values), True
    return {k: int(v) for k, v in values.items() if int(v) > 0}, False


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
        "ability:", "level:", "evs:", "stat points:", "sp:", "ivs:", "tera type:", "shiny:",
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
        species_label = _species_raw.strip()
        points, converted = _points_from_paste(_evs)
        if converted:
            warnings.append(f"{species_label}: EV spread converted to stat points ({format_points(points) or 'none'})")
        for problem in validate_points(points):
            warnings.append(f"{species_label}: {problem} — clamped")
        points = {k: min(MAX_POINTS_PER_STAT, v) for k, v in points.items() if k in STAT_KEYS and v > 0}
        if any(v != 31 for v in _ivs.values()):
            warnings.append(f"{species_label}: IVs ignored — Champions fixes IVs at 31")
        if _level != 50:
            warnings.append(f"{species_label}: level {_level} ignored — Champions is level 50")
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
            points=points,
            points_converted=converted,
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
        if ll.startswith(("evs:", "stat points:", "sp:")):   # the last two: this app's own display label
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
    *,
    tera: bool = True,
) -> ShowdownExportResult:
    """Serialize a team and publish it to Pokepast.es.

    Returns:
        :class:`ShowdownExportResult` with the generated ``pokepast_url``.
    """
    text = export_team_to_showdown_text(team_members, box_entries_by_id, tera=tera)
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


# ---------------------------------------------------------------------------
# Import commit
# ---------------------------------------------------------------------------

@dataclass(frozen=True)
class ImportedTeam:
    """Outcome of :func:`commit_team_import`."""

    team_id: UUID
    team_name: str
    created_owned: tuple[str, ...]     # display names added to the box as owned entries
    created_planned: tuple[str, ...]   # display names added as planned (ghost) entries
    reused: tuple[str, ...]            # display names that were already in the box


def _fetch_official(species_name: str, form_key: str | None) -> Pokemon | None:
    """PokéAPI lookup for an imported species; tries the display name, then the form key."""
    from ..infrastructure.pokeapi.pokeapi_retrieval import get_official_stats

    try:
        return get_official_stats(species_name) or (get_official_stats(form_key) if form_key else None)
    except Exception:  # noqa: BLE001 - offline or throttled: the caller stores a placeholder
        return None


def commit_team_import(
    session,
    parsed: ParsedTeamResult,
    *,
    use_planned: bool,
    team_name: Optional[str] = None,
    legal_species: Optional[Iterable[str]] = None,
) -> ImportedTeam:
    """Create a team from a parsed Showdown paste, adding missing Pokémon to the box.

    Existing box entries are matched by display name or canonical id. Missing species
    come from the local Pokémon catalogue when known, otherwise a zero-stat stub is
    created so the slot can still be filled; with ``use_planned`` they become planned
    (ghost) entries that do not appear in the roster. Slots beyond six are ignored.

    Raises ``ValueError`` when the paste is invalid or, if ``legal_species`` is given,
    when a species is outside it.
    """
    from ..domain.entities.box_entry import BoxEntry
    from ..domain.entities.pokemon import Pokemon
    from ..domain.entities.team import Team
    from ..domain.entities.team_member import TeamMember
    from ..infrastructure.database.repositories import BoxRepository, PokemonRepository, TeamRepository

    if parsed is None or not parsed.is_valid or not parsed.slots:
        raise ValueError("Nothing to import: the paste did not parse into any Pokémon")

    if legal_species is not None:
        legal = {name.lower().strip() for name in legal_species}
        if legal:
            illegal = [
                s.species_name for s in parsed.slots[:6]
                if s.species_name.lower() not in legal
                and (s.showdown_form_key or "").split("-")[0] not in legal
                and s.showdown_form_key not in legal
            ]
            if illegal:
                raise ValueError(f"Not in the Champions Pokédex: {', '.join(illegal)}")

    box_repo = BoxRepository(session)
    team_repo = TeamRepository(session)
    pokemon_repo = PokemonRepository(session)

    name = (team_name or parsed.title or "Imported Team").strip() or "Imported Team"
    team = team_repo.create(Team(name=name))

    entries = box_repo.list_entries(include_planned=True)
    by_name = {e.pokemon.display_name.lower(): e for e in entries}
    by_cid = {e.pokemon.canonical_id: e for e in entries}

    created_owned: list[str] = []
    created_planned: list[str] = []
    reused: list[str] = []

    for index, slot in enumerate(parsed.slots[:6], start=1):
        existing = by_name.get(slot.species_name.lower()) or by_cid.get(slot.showdown_form_key)
        if existing is not None:
            box_entry_id = existing.box_entry_id
            reused.append(slot.species_name)
        else:
            record = pokemon_repo.get(slot.showdown_form_key) or pokemon_repo.get(slot.species_name.lower())
            pokemon = record.to_domain() if record is not None else None
            if pokemon is None or pokemon.is_stub:
                # Real data from PokéAPI when reachable; a placeholder (no types, zero
                # stats) only offline, and it is repaired at the next launch.
                fetched = _fetch_official(slot.species_name, slot.showdown_form_key)
                if fetched is not None:
                    pokemon_repo.upsert(fetched)
                    pokemon = fetched
            if pokemon is None:
                pokemon = Pokemon.placeholder(slot.showdown_form_key, slot.species_name)
            entry = BoxEntry(pokemon=pokemon, tags=["imported", name], is_planned=use_planned)
            allow = pokemon.is_stub  # only the offline fallback stores a placeholder, knowingly
            saved = box_repo.create_planned_entry(entry, allow_placeholder=allow) if use_planned else box_repo.upsert_box_entry(entry, allow_placeholder=allow)
            box_entry_id = saved.box_entry_id
            (created_planned if use_planned else created_owned).append(slot.species_name)
            # Later slots may reference the same species.
            by_name[slot.species_name.lower()] = entry
            by_cid[slot.showdown_form_key] = entry
            entry.box_entry_id = box_entry_id

        member = TeamMember(
            box_entry_id=box_entry_id,
            slot_position=index,
            selected_form=slot.showdown_form_key or "base",
            item=slot.item_name,
            ability=slot.ability_name,
            moveset=[PokemonMove(name=m) for m in slot.moves if m],
            nature=slot.nature,
            points=dict(slot.points),
            tera_type=(slot.tera_type or "").strip().lower() or None,
        )
        team_repo.upsert_member(team.team_id, member)

    return ImportedTeam(
        team_id=team.team_id,
        team_name=name,
        created_owned=tuple(created_owned),
        created_planned=tuple(created_planned),
        reused=tuple(reused),
    )

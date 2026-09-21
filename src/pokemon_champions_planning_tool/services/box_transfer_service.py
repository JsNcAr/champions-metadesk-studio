"""Box transfer service: serialization, parsing, and database import for Box rosters.

Supports:
1. JSON: 100% lossless full backup and transfer between app instances (species, forms,
   tags, notes, favorite star, planned status).
2. Plain Text: Simple line-by-line species list for fast bulk imports and Discord sharing.
   Supports inline tags (#tag) and favorite symbols (★ / *).
3. CSV: Spreadsheet-compatible table for spreadsheet analysis.
"""

from __future__ import annotations

import csv
import io
import json
import re
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Literal

from sqlmodel import Session

from ..domain.entities.box_entry import BoxEntry
from ..domain.entities.pokemon import Pokemon
from ..domain.pokemon_identity import format_api_name
from ..infrastructure.database.repositories import BoxRepository, PokemonRepository
from ..infrastructure.pokeapi.pokeapi_retrieval import PokeApiUnavailable, get_official_stats

APP_IDENTIFIER = "Champions MetaDesk Studio"
FORMAT_VERSION = 1


@dataclass
class ParsedBoxItem:
    """An individual item parsed from an import payload."""

    species: str
    canonical_id: str | None = None
    form: str | None = None
    tags: list[str] = field(default_factory=list)
    notes: str = ""
    is_favorite: bool = False
    is_planned: bool = False


@dataclass
class ParsedBoxResult:
    """The result of parsing an import text payload."""

    items: list[ParsedBoxItem] = field(default_factory=list)
    format_detected: str = "empty"  # "json" | "csv" | "plain_text" | "empty"
    errors: list[str] = field(default_factory=list)


@dataclass
class BoxImportReport:
    """Summary of applying an import payload to the database."""

    total: int = 0
    added: int = 0
    updated: int = 0
    skipped: int = 0
    errors: list[str] = field(default_factory=list)


# --------------------------------------------------------------------------------------
# Export Functions
# --------------------------------------------------------------------------------------


def export_box_to_json(entries: list[BoxEntry]) -> str:
    """Serialize BoxEntry objects into formatted JSON with full fidelity."""
    data = {
        "app": APP_IDENTIFIER,
        "version": FORMAT_VERSION,
        "exported_at": datetime.now(timezone.utc).isoformat(),
        "total": len(entries),
        "box": [
            {
                "species": entry.pokemon.display_name,
                "canonical_id": entry.pokemon.canonical_id,
                "form": entry.pokemon.form_name or "Base",
                "notes": entry.notes or "",
                "tags": list(entry.tags or []),
                "is_favorite": bool(entry.is_favorite),
                "is_planned": bool(entry.is_planned),
            }
            for entry in entries
        ],
    }
    return json.dumps(data, indent=2, ensure_ascii=False)


def export_box_to_names(entries: list[BoxEntry], include_metadata: bool = False) -> str:
    """Export box entries as a plain text list.

    If ``include_metadata`` is True, appends inline tags and favorite marker.
    """
    lines: list[str] = []
    for entry in entries:
        name = entry.pokemon.display_name
        if include_metadata:
            parts = [name]
            if entry.tags:
                parts.extend(f"#{t}" for t in entry.tags)
            if entry.is_favorite:
                parts.append("★")
            if entry.is_planned:
                parts.append("[planned]")
            lines.append(" ".join(parts))
        else:
            lines.append(name)
    return "\n".join(lines)


def export_box_to_csv_text(entries: list[BoxEntry]) -> str:
    """Export box entries to a CSV formatted string with metadata and stats."""
    output = io.StringIO()
    headers = [
        "Pokémon",
        "Form",
        "Tags",
        "Notes",
        "Favorite",
        "Planned",
        "HP",
        "Attack",
        "Defense",
        "Sp. Atk",
        "Sp. Def",
        "Speed",
        "Total",
    ]
    writer = csv.DictWriter(output, fieldnames=headers)
    writer.writeheader()
    for entry in entries:
        p = entry.pokemon
        writer.writerow(
            {
                "Pokémon": p.display_name,
                "Form": p.form_name or "Base",
                "Tags": ";".join(entry.tags) if entry.tags else "",
                "Notes": entry.notes or "",
                "Favorite": "True" if entry.is_favorite else "False",
                "Planned": "True" if entry.is_planned else "False",
                "HP": p.stats.hp,
                "Attack": p.stats.attack,
                "Defense": p.stats.defense,
                "Sp. Atk": p.stats.special_attack,
                "Sp. Def": p.stats.special_defense,
                "Speed": p.stats.speed,
                "Total": p.total,
            }
        )
    return output.getvalue()


# --------------------------------------------------------------------------------------
# Parsing / Ingestion
# --------------------------------------------------------------------------------------


_TAG_RE = re.compile(r"#([A-Za-z0-9_\-]+)")
_FAVORITE_RE = re.compile(r"[★\*]")
_PLANNED_RE = re.compile(r"\[(planned|ghost|template)\]", re.IGNORECASE)


def parse_box_import_text(text: str) -> ParsedBoxResult:
    """Inspect and parse an import payload, auto-detecting JSON, CSV, or Plain Text."""
    raw = (text or "").strip()
    if not raw:
        return ParsedBoxResult(items=[], format_detected="empty")

    # 1. Try JSON
    if raw.startswith("{") or raw.startswith("["):
        try:
            parsed = json.loads(raw)
            return _parse_json(parsed)
        except json.JSONDecodeError:
            pass

    # 2. Try CSV (contains commas or standard header)
    first_line = raw.splitlines()[0] if raw.splitlines() else ""
    if (
        "pokémon" in first_line.lower()
        or "species" in first_line.lower()
        or ("," in first_line and len(first_line.split(",")) >= 2)
    ):
        try:
            csv_res = _parse_csv(raw)
            if csv_res.items:
                return csv_res
        except Exception:
            pass

    # 3. Fallback: Plain Text (one per line)
    return _parse_plain_text(raw)


def _parse_json(data: dict | list) -> ParsedBoxResult:
    """Parse JSON format box payload."""
    items: list[ParsedBoxItem] = []
    errors: list[str] = []

    box_list = data.get("box", []) if isinstance(data, dict) else data
    if not isinstance(box_list, list):
        return ParsedBoxResult(items=[], format_detected="json", errors=["Invalid JSON: 'box' must be a list"])

    for idx, obj in enumerate(box_list):
        if not isinstance(obj, dict):
            errors.append(f"Item #{idx + 1} is not a valid JSON object")
            continue
        species = obj.get("species") or obj.get("name") or obj.get("display_name")
        if not species or not str(species).strip():
            errors.append(f"Item #{idx + 1} missing species name")
            continue
        tags_raw = obj.get("tags") or []
        tags = [str(t).strip() for t in tags_raw if str(t).strip()] if isinstance(tags_raw, list) else []
        items.append(
            ParsedBoxItem(
                species=str(species).strip(),
                canonical_id=obj.get("canonical_id"),
                form=obj.get("form") or "Base",
                tags=tags,
                notes=str(obj.get("notes") or "").strip(),
                is_favorite=bool(obj.get("is_favorite", False)),
                is_planned=bool(obj.get("is_planned", False)),
            )
        )

    return ParsedBoxResult(items=items, format_detected="json", errors=errors)


def _parse_csv(csv_text: str) -> ParsedBoxResult:
    """Parse CSV text with header inspection."""
    items: list[ParsedBoxItem] = []
    errors: list[str] = []

    reader = csv.DictReader(io.StringIO(csv_text))
    fieldnames = [f.strip().lower() for f in (reader.fieldnames or [])]
    if not fieldnames:
        return ParsedBoxResult(items=[], format_detected="csv", errors=["Empty CSV header"])

    # Locate column names
    species_col = next((f for f in reader.fieldnames if f.strip().lower() in ("pokémon", "pokemon", "species", "name")), None)
    if not species_col:
        return ParsedBoxResult(items=[], format_detected="csv", errors=["CSV missing Pokémon/Species column"])

    form_col = next((f for f in reader.fieldnames if f.strip().lower() == "form"), None)
    tags_col = next((f for f in reader.fieldnames if f.strip().lower() == "tags"), None)
    notes_col = next((f for f in reader.fieldnames if f.strip().lower() == "notes"), None)
    fav_col = next((f for f in reader.fieldnames if f.strip().lower() in ("favorite", "favourite")), None)
    plan_col = next((f for f in reader.fieldnames if f.strip().lower() == "planned"), None)

    for idx, row in enumerate(reader):
        species = (row.get(species_col) or "").strip()
        if not species:
            continue
        tags = []
        if tags_col and row.get(tags_col):
            tags = [t.strip() for t in re.split(r"[,;]", row[tags_col]) if t.strip()]
        is_fav = False
        if fav_col and row.get(fav_col):
            is_fav = row[fav_col].strip().lower() in ("true", "1", "yes", "★")
        is_planned = False
        if plan_col and row.get(plan_col):
            is_planned = row[plan_col].strip().lower() in ("true", "1", "yes")

        items.append(
            ParsedBoxItem(
                species=species,
                form=(row.get(form_col) or "Base").strip() if form_col else "Base",
                tags=tags,
                notes=(row.get(notes_col) or "").strip() if notes_col else "",
                is_favorite=is_fav,
                is_planned=is_planned,
            )
        )

    return ParsedBoxResult(items=items, format_detected="csv", errors=errors)


def _parse_plain_text(text: str) -> ParsedBoxResult:
    """Parse plain text lines with inline tags and markers."""
    items: list[ParsedBoxItem] = []
    errors: list[str] = []

    for line_idx, line in enumerate(text.splitlines(), 1):
        clean = line.strip()
        if not clean or clean.startswith("//"):
            continue
        # Allow lines starting with a comment hash if nothing else
        if clean.startswith("#") and not _TAG_RE.match(clean):
            continue

        # Extract tags
        tags = _TAG_RE.findall(clean)
        # Extract favorite
        is_fav = bool(_FAVORITE_RE.search(clean))
        # Extract planned
        is_planned = bool(_PLANNED_RE.search(clean))

        # Strip tags and markers from the name
        cleaned_name = _TAG_RE.sub("", clean)
        cleaned_name = _FAVORITE_RE.sub("", cleaned_name)
        cleaned_name = _PLANNED_RE.sub("", cleaned_name).strip()

        # Check for form parenthetical, e.g. "Charizard (Mega X)" or "Rotom (Wash)"
        form = "Base"
        form_match = re.search(r"\(([^)]+)\)", cleaned_name)
        if form_match:
            form = form_match.group(1).strip()
            cleaned_name = re.sub(r"\([^)]+\)", "", cleaned_name).strip()

        if not cleaned_name:
            continue

        items.append(
            ParsedBoxItem(
                species=cleaned_name,
                form=form,
                tags=tags,
                notes="",
                is_favorite=is_fav,
                is_planned=is_planned,
            )
        )

    return ParsedBoxResult(items=items, format_detected="plain_text", errors=errors)


# --------------------------------------------------------------------------------------
# Application to Database
# --------------------------------------------------------------------------------------


def apply_box_import(
    session: Session,
    items: list[ParsedBoxItem],
    *,
    strategy: Literal["merge", "replace"] = "merge",
    as_planned: bool | None = None,
) -> BoxImportReport:
    """Ingest a parsed box roster into the database.

    :param session: Active SQLModel session.
    :param items: List of ParsedBoxItem objects to import.
    :param strategy: "merge" preserves existing box entries; "replace" clears the box first.
    :param as_planned: If set to True or False, overrides the item's planned state.
                       If None, preserves each item's is_planned value.
    """
    box_repo = BoxRepository(session)
    pokemon_repo = PokemonRepository(session)

    report = BoxImportReport(total=len(items))

    if strategy == "replace":
        # Fetch existing box entries to delete them
        existing_entries = box_repo.list_entries(include_planned=True)
        if existing_entries:
            box_repo.delete_many([e.box_entry_id for e in existing_entries])

    # Preload existing entries for merge comparison
    current_entries = {
        (e.pokemon.canonical_id, e.is_planned): e for e in box_repo.list_entries(include_planned=True)
    }

    for item in items:
        # Determine planned status
        target_planned = as_planned if as_planned is not None else item.is_planned

        # Resolve Pokemon entity
        canonical_id = item.canonical_id or format_api_name(item.species) or item.species.lower()
        official_data = None
        existing_mon = pokemon_repo.get(canonical_id)
        if existing_mon is not None and not existing_mon.to_domain().is_stub:
            official_data = existing_mon.to_domain()
        else:
            try:
                official_data = get_official_stats(item.species) or get_official_stats(canonical_id)
            except (PokeApiUnavailable, Exception):
                pass

        if official_data:
            pokemon_repo.upsert(official_data)
        else:
            # Fall back to a placeholder if completely unknown/offline
            official_data = Pokemon.placeholder(
                canonical_id=canonical_id,
                display_name=item.species.title(),
                species_name=canonical_id,
            )

        key = (official_data.canonical_id, target_planned)
        existing_entry = current_entries.get(key)

        if existing_entry is not None:
            # Merge metadata if needed
            changed = False
            new_tags = list(existing_entry.tags)
            for t in item.tags:
                if t.lower() not in {existing_t.lower() for existing_t in new_tags}:
                    new_tags.append(t)
                    changed = True
            new_notes = existing_entry.notes
            if item.notes and item.notes not in existing_entry.notes:
                new_notes = f"{existing_entry.notes}\n{item.notes}".strip() if existing_entry.notes else item.notes
                changed = True
            new_fav = existing_entry.is_favorite or item.is_favorite
            if new_fav != existing_entry.is_favorite:
                changed = True

            if changed:
                box_repo.update_many(
                    [existing_entry.box_entry_id],
                    add_tags=item.tags,
                    is_favorite=new_fav,
                    notes=new_notes,
                )
                report.updated += 1
            else:
                report.skipped += 1
        else:
            # Create new entry
            new_entry = BoxEntry(
                pokemon=official_data,
                notes=item.notes,
                tags=item.tags,
                is_favorite=item.is_favorite,
                is_planned=target_planned,
            )
            if target_planned:
                box_repo.create_planned_entry(new_entry, allow_placeholder=official_data.is_stub)
            else:
                box_repo.upsert_box_entry(new_entry, allow_placeholder=official_data.is_stub)
            current_entries[key] = new_entry
            report.added += 1

    return report

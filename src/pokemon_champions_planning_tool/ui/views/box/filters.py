"""Box filtering and sorting — pure functions over BoxEntry domain objects.

Filters are AND-composed; the type filter is "any of" within itself. Text matches the
display name, tags or types (the pre-overhaul behaviour). Stat ranges are inclusive.
"""

from __future__ import annotations

from dataclasses import dataclass, field, replace
from typing import Literal

from ....domain.entities.box_entry import BoxEntry

SortKey = Literal["name", "bst", "hp", "attack", "defense", "special_attack", "special_defense", "speed", "added", "usage"]

SORT_LABELS: dict[SortKey, str] = {
    "name": "Name",
    "bst": "BST",
    "hp": "HP",
    "attack": "Attack",
    "defense": "Defense",
    "special_attack": "Sp. Atk",
    "special_defense": "Sp. Def",
    "speed": "Speed",
    "added": "Added",
    "usage": "Tournament Usage",
}

BST_MIN, BST_MAX = 150, 800
STAT_MIN, STAT_MAX = 0, 255


@dataclass(frozen=True)
class BoxFilters:
    text: str = ""
    types: frozenset[str] = frozenset()
    favourites_only: bool = False
    mega_capable_only: bool = False
    show_planned: bool = False
    bst_range: tuple[int, int] = (BST_MIN, BST_MAX)
    stat_ranges: dict[str, tuple[int, int]] = field(default_factory=dict)
    tags: frozenset[str] = frozenset()
    sort: SortKey = "name"
    descending: bool = False
    usage_regulation: str = "latest"

    def is_active(self) -> bool:
        return bool(self.active_labels())

    def to_dict(self) -> dict:
        """JSON-friendly form for saved views."""
        return {
            "text": self.text, "types": sorted(self.types), "favourites_only": self.favourites_only,
            "mega_capable_only": self.mega_capable_only, "show_planned": self.show_planned,
            "bst_range": list(self.bst_range), "stat_ranges": {k: list(v) for k, v in self.stat_ranges.items()},
            "tags": sorted(self.tags), "sort": self.sort, "descending": self.descending,
            "usage_regulation": self.usage_regulation,
        }

    @classmethod
    def from_dict(cls, data: dict) -> "BoxFilters":
        base = cls()
        if not isinstance(data, dict):
            return base
        try:
            bst = data.get("bst_range") or list(base.bst_range)
            return cls(
                text=str(data.get("text", "")),
                types=frozenset(str(t) for t in data.get("types", [])),
                favourites_only=bool(data.get("favourites_only", False)),
                mega_capable_only=bool(data.get("mega_capable_only", False)),
                show_planned=bool(data.get("show_planned", False)),
                bst_range=(int(bst[0]), int(bst[1])),
                stat_ranges={str(k): (int(v[0]), int(v[1])) for k, v in (data.get("stat_ranges") or {}).items()},
                tags=frozenset(str(t) for t in data.get("tags", [])),
                sort=data.get("sort", "name") if data.get("sort", "name") in SORT_LABELS else "name",
                descending=bool(data.get("descending", False)),
                usage_regulation=str(data.get("usage_regulation", "latest")),
            )
        except (TypeError, ValueError, IndexError):
            return base

    def active_labels(self) -> list[tuple[str, str]]:
        """(field, label) for each non-default filter, for the removable chip row."""
        out: list[tuple[str, str]] = []
        if self.text.strip():
            out.append(("text", f"“{self.text.strip()}”"))
        for t in sorted(self.types):
            out.append((f"type:{t}", t.capitalize()))
        if self.favourites_only:
            out.append(("favourites_only", "Favourites"))
        if self.mega_capable_only:
            out.append(("mega_capable_only", "Mega-capable"))
        if self.bst_range != (BST_MIN, BST_MAX):
            out.append(("bst_range", f"BST {self.bst_range[0]}–{self.bst_range[1]}"))
        for stat, (lo, hi) in sorted(self.stat_ranges.items()):
            if (lo, hi) != (STAT_MIN, STAT_MAX):
                out.append((f"stat:{stat}", f"{_short(stat)} {lo}–{hi}"))
        for tag in sorted(self.tags):
            out.append((f"tag:{tag}", f"#{tag}"))
        return out

    def without(self, field_key: str) -> "BoxFilters":
        if field_key.startswith("type:"):
            return replace(self, types=self.types - {field_key[5:]})
        if field_key.startswith("stat:"):
            ranges = dict(self.stat_ranges)
            ranges.pop(field_key[5:], None)
            return replace(self, stat_ranges=ranges)
        if field_key.startswith("tag:"):
            return replace(self, tags=self.tags - {field_key[4:]})
        defaults = BoxFilters()
        return replace(self, **{field_key: getattr(defaults, field_key)})

    def cleared(self) -> "BoxFilters":
        """Reset everything except sort and the planned toggle (view preferences)."""
        return BoxFilters(sort=self.sort, descending=self.descending, show_planned=self.show_planned, usage_regulation=self.usage_regulation)


def _short(stat: str) -> str:
    return {"hp": "HP", "attack": "Atk", "defense": "Def", "special_attack": "SpA", "special_defense": "SpD", "speed": "Spe"}.get(stat, stat)


def matches(entry: BoxEntry, f: BoxFilters, mega_species: frozenset[str] | set[str]) -> bool:
    pokemon = entry.pokemon
    if entry.is_planned and not f.show_planned:
        return False
    if f.text.strip():
        q = f.text.strip().lower()
        if not (
            q in pokemon.display_name.lower()
            or any(q in t.lower() for t in entry.tags)
            or any(q in t.lower() for t in pokemon.types)
        ):
            return False
    if f.types:
        if not f.types & {t.lower() for t in pokemon.types}:
            return False
    if f.favourites_only and not entry.is_favorite:
        return False
    if f.mega_capable_only and (pokemon.species_name or "").lower() not in mega_species:
        return False
    if pokemon.is_stub:
        # No data to judge: keep the entry visible (with its "incomplete data" mark)
        # rather than silently hiding it behind the stat ranges.
        return not f.tags or bool(f.tags & {t.lower() for t in entry.tags})
    lo, hi = f.bst_range
    if not lo <= pokemon.total <= hi:
        return False
    for stat, (s_lo, s_hi) in f.stat_ranges.items():
        value = getattr(pokemon.stats, stat, None)
        if value is None or not s_lo <= value <= s_hi:
            return False
    if f.tags:
        entry_tags = {t.lower() for t in entry.tags}
        if not f.tags & entry_tags:
            return False
    return True


def apply_filters(
    entries: list[BoxEntry],
    f: BoxFilters,
    mega_species: frozenset[str] | set[str] = frozenset(),
    usage_map: dict[str, int] | None = None,
) -> list[BoxEntry]:
    return sort_entries(
        [e for e in entries if matches(e, f, mega_species)],
        f.sort,
        f.descending,
        usage_map=usage_map,
    )


def sort_entries(
    entries: list[BoxEntry],
    key: SortKey,
    descending: bool = False,
    usage_map: dict[str, int] | None = None,
) -> list[BoxEntry]:
    if key == "name":
        keyfn = lambda e: e.pokemon.display_name.lower()  # noqa: E731
    elif key == "bst":
        keyfn = lambda e: e.pokemon.total  # noqa: E731
    elif key == "added":
        keyfn = lambda e: e.created_at  # noqa: E731
    elif key == "usage":
        from ....domain.pokemon_identity import base_canonical_id

        umap = usage_map or {}

        def get_usage(e: BoxEntry) -> int:
            cid = e.pokemon.canonical_id.lower()
            base_cid = (e.pokemon.species_name or "").lower() or base_canonical_id(cid)
            return umap.get(cid) or umap.get(base_cid, 0)

        # Stable tie-break: alphabetical display name A-Z
        entries = sorted(entries, key=lambda e: e.pokemon.display_name.lower())
        return sorted(entries, key=get_usage, reverse=descending)
    else:
        keyfn = lambda e: getattr(e.pokemon.stats, key, 0)  # noqa: E731
    return sorted(entries, key=keyfn, reverse=descending)

"""Meta explorer store: filters, paged rows, summary. Flet-free.

Rows are detached ``MetaTeamRow`` values from the tournament service; nothing here holds
a session beyond a single method call. The store remembers which filter key it loaded so
re-entering the view with unchanged filters costs nothing.
"""

from __future__ import annotations

from collections.abc import Callable
from contextlib import AbstractContextManager
from dataclasses import dataclass, replace

from sqlmodel import Session

from ....domain.event_tier import OFFICIAL_TIERS, TIER_LABELS, tiers_for_filter
from ....domain.pokemon_identity import expand_canonical_aliases
from ....domain.search import parse_search_query, remove_query_token
from ....infrastructure.database.database import get_session
from ....infrastructure.database.repositories import BoxRepository
from ....services.tournament_service import MetaSummary, MetaTeamRow, TournamentService

SessionFactory = Callable[[], AbstractContextManager[Session]]

PAGE_SIZE = 20

PLACEMENT_OPTIONS: tuple[tuple[str, str], ...] = (
    ("1", "Winner (1st)"),
    ("4", "Top 4"),
    ("8", "Top 8"),
    ("16", "Top 16"),
    ("32", "Top 32"),
    ("64", "Top 64"),
    ("128", "Top 128"),
    ("all", "All placements"),
)
RECENCY_OPTIONS: tuple[tuple[str, str], ...] = (("90", "3 months"), ("365", "12 months"), ("all", "All time"))
BOX_OPTIONS: tuple[tuple[str, str], ...] = (("any", "Any team"), ("0", "All in my box"), ("1", "≤ 1 missing"), ("2", "≤ 2 missing"), ("3", "≤ 3 missing"))
SOURCE_OPTIONS: tuple[tuple[str, str], ...] = (("All", "All"), ("official", "Official"), ("community", "Community"))
TIER_OPTIONS: tuple[tuple[str, str], ...] = (("All", "All official events"),) + tuple((t, TIER_LABELS[t]) for t in OFFICIAL_TIERS)
GAME_OPTIONS: tuple[tuple[str, str], ...] = (
    ("All", "All games"),
    ("Pokémon Champions", "Pokémon Champions"),
    ("Scarlet & Violet", "Scarlet & Violet"),
)


FORMAT_OPTIONS: tuple[tuple[str, str], ...] = (
    ("doubles", "Doubles only"),
    ("all", "All formats"),
    ("singles", "Singles only"),
)


@dataclass(frozen=True)
class MetaFilters:
    query: str = ""
    placement: str = "8"     # "1" | "4" | "8" | "all"
    regulation: str = "All"
    recency: str = "365"     # days, or "all"
    game: str = "All"
    source: str = "All"      # "All" | "official" | "community"
    tier: str = "All"        # "All" or one of OFFICIAL_TIERS; only meaningful with source "official"
    box: str = "any"         # "any" or the most members allowed to be missing from the box
    battle_format: str = "doubles"  # "doubles" | "all" | "singles"

    @property
    def max_missing(self) -> int | None:
        return None if self.box == "any" else int(self.box)

    @property
    def event_tiers(self) -> tuple[str, ...] | None:
        return tiers_for_filter(self.source, self.tier)

    @property
    def placement_limit(self) -> int | None:
        return None if self.placement == "all" else int(self.placement)

    @property
    def max_age_days(self) -> int | None:
        return None if self.recency == "all" else int(self.recency)

    def to_query_kwargs(self) -> dict:
        return {
            "query": self.query.strip() or None,
            "regulation_filter": self.regulation,
            "placement_filter": self.placement_limit,
            "game_platform_filter": self.game,
            "max_age_days": self.max_age_days,
            "event_tiers": self.event_tiers,
            "max_missing": self.max_missing,
            "battle_format_filter": self.battle_format,
        }

    def active(self) -> list[tuple[str, str]]:
        """(field, label) for every filter that differs from the default."""
        default = MetaFilters()
        out: list[tuple[str, str]] = []
        if self.query.strip():
            parsed = parse_search_query(self.query)
            if len(parsed.tokens) <= 1 and not parsed.excludes:
                out.append(("query", f"“{self.query.strip()}”"))
            else:
                for t in parsed.tokens:
                    val_title = t.value.title()
                    if t.is_neg:
                        out.append((f"query_token:{t.raw_token}", f"- {val_title}"))
                    else:
                        label = f"+ {val_title}" if parsed.excludes else f"“{t.value}”"
                        out.append((f"query_token:{t.raw_token}", label))
        if self.placement != default.placement:
            out.append(("placement", dict(PLACEMENT_OPTIONS).get(self.placement, self.placement)))
        if self.regulation != default.regulation:
            out.append(("regulation", self.regulation))
        if self.recency != default.recency:
            out.append(("recency", dict(RECENCY_OPTIONS)[self.recency]))
        if self.game != default.game:
            out.append(("game", self.game))
        if self.box != default.box:
            out.append(("box", f"Box · {dict(BOX_OPTIONS)[self.box]}"))
        if self.battle_format != default.battle_format:
            out.append(("battle_format", f"Format · {dict(FORMAT_OPTIONS).get(self.battle_format, self.battle_format)}"))
        if self.tier != default.tier:
            out.append(("tier", f"Official · {TIER_LABELS.get(self.tier, self.tier)}"))
        elif self.source != default.source:
            out.append(("source", dict(SOURCE_OPTIONS)[self.source]))
        return out

    def without(self, field: str) -> "MetaFilters":
        if field.startswith("query_token:"):
            token = field.split(":", 1)[1]
            new_query = remove_query_token(self.query, token)
            return replace(self, query=new_query)
        defaults = MetaFilters()
        changes = {field: getattr(defaults, field)}
        if field == "source":
            changes["tier"] = defaults.tier   # a tier only exists inside "official"
        return replace(self, **changes)


class MetaStore:
    def __init__(self, session_factory: SessionFactory = get_session) -> None:
        self._sf = session_factory
        self.filters = MetaFilters()
        pref = self.load_preference()
        self.filters = MetaFilters(battle_format=pref)
        self.rows: list[MetaTeamRow] = []
        self.total: int = 0
        self.exhausted: bool = False
        self._loaded_key: MetaFilters | None = None
        self._stale: bool = True
        # Base species ids of owned (not planned) box entries; every query carries them so
        # rows are marked, and the Box filter counts against them.
        self.box_species: frozenset[str] = frozenset()
        self._box_loaded = False

    def load_preference(self) -> str:
        """Load stored battle format preference."""
        try:
            with self._sf() as s:
                from ....infrastructure.database.repositories import TournamentRepository
                val = TournamentRepository(s).get_state("pref_battle_format")
                return val if val in ("doubles", "all", "singles") else "doubles"
        except Exception:
            return "doubles"

    def reload_preference(self) -> None:
        pref = self.load_preference()
        if self.filters.battle_format != pref:
            self.filters = replace(self.filters, battle_format=pref)
            self._stale = True

    # -- state --------------------------------------------------------------------------

    @property
    def loaded(self) -> int:
        return len(self.rows)

    @property
    def needs_load(self) -> bool:
        return self._stale or self._loaded_key != self.filters

    def set_filters(self, filters: MetaFilters) -> None:
        self.filters = filters

    def refresh_box(self) -> frozenset[str]:
        """Re-read the owned box species (call after BOX_CHANGED); marks a reload as needed."""
        with self._sf() as s:
            entries = BoxRepository(s).list_entries(include_planned=False)
        raw_ids = [e.pokemon.canonical_id for e in entries if not e.is_planned]
        species = frozenset(expand_canonical_aliases(raw_ids))
        if species != self.box_species:
            self._stale = True
        self.box_species = species
        self._box_loaded = True
        return species

    def _query_kwargs(self) -> dict:
        if not self._box_loaded:
            self.refresh_box()
        # An empty box marks nothing (every row would read "0/6"); the Box filter itself
        # still needs the list to reject everything, hence [] rather than None there.
        owned = sorted(self.box_species)
        return {**self.filters.to_query_kwargs(), "owned_species": owned if (owned or self.filters.max_missing is not None) else None}

    def invalidate(self) -> None:
        """New data landed; the next load re-queries even with unchanged filters."""
        self._stale = True

    # -- loading (each call is one session) ---------------------------------------------

    def load_first_page(self) -> list[MetaTeamRow]:
        with self._sf() as s:
            svc = TournamentService(s)
            kwargs = self._query_kwargs()
            self.total = svc.count_teams(**kwargs)
            self.rows = svc.search_team_rows(**kwargs, limit=PAGE_SIZE, offset=0)
        self.exhausted = len(self.rows) >= self.total
        self._loaded_key = self.filters
        self._stale = False
        return self.rows

    def load_more(self) -> list[MetaTeamRow]:
        if self.exhausted:
            return []
        with self._sf() as s:
            batch = TournamentService(s).search_team_rows(
                **self._query_kwargs(), limit=PAGE_SIZE, offset=self.loaded
            )
        self.rows.extend(batch)
        self.exhausted = not batch or len(self.rows) >= self.total
        return batch

    def teams_for_event(self, tournament_id: str) -> list[MetaTeamRow]:
        """Every Masters team recorded for one event, best placement first, ignoring the
        list filters — the event dialog shows the whole standings."""
        with self._sf() as s:
            return TournamentService(s).search_team_rows(tournament_id_filter=tournament_id, owned_species=sorted(self.box_species) or None)

    def summary(self) -> MetaSummary:
        with self._sf() as s:
            return TournamentService(s).meta_summary()

    def regulation_options(self) -> list[str]:
        with self._sf() as s:
            return TournamentService(s).list_regulations()

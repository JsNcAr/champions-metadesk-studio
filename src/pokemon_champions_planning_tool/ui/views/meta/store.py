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

from ....infrastructure.database.database import get_session
from ....services.tournament_service import MetaSummary, MetaTeamRow, TournamentService

SessionFactory = Callable[[], AbstractContextManager[Session]]

PAGE_SIZE = 20

PLACEMENT_OPTIONS: tuple[tuple[str, str], ...] = (("1", "Winner"), ("4", "Top 4"), ("8", "Top 8"), ("all", "All"))
RECENCY_OPTIONS: tuple[tuple[str, str], ...] = (("90", "3 months"), ("365", "12 months"), ("all", "All time"))
GAME_OPTIONS: tuple[tuple[str, str], ...] = (
    ("All", "All games"),
    ("Pokémon Champions", "Pokémon Champions"),
    ("Scarlet & Violet", "Scarlet & Violet"),
)


@dataclass(frozen=True)
class MetaFilters:
    query: str = ""
    placement: str = "8"     # "1" | "4" | "8" | "all"
    regulation: str = "All"
    recency: str = "365"     # days, or "all"
    game: str = "All"

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
        }

    def active(self) -> list[tuple[str, str]]:
        """(field, label) for every filter that differs from the default."""
        default = MetaFilters()
        out: list[tuple[str, str]] = []
        if self.query.strip():
            out.append(("query", f"“{self.query.strip()}”"))
        if self.placement != default.placement:
            out.append(("placement", dict(PLACEMENT_OPTIONS)[self.placement]))
        if self.regulation != default.regulation:
            out.append(("regulation", self.regulation))
        if self.recency != default.recency:
            out.append(("recency", dict(RECENCY_OPTIONS)[self.recency]))
        if self.game != default.game:
            out.append(("game", self.game))
        return out

    def without(self, field: str) -> "MetaFilters":
        return replace(self, **{field: getattr(MetaFilters(), field)})


class MetaStore:
    def __init__(self, session_factory: SessionFactory = get_session) -> None:
        self._sf = session_factory
        self.filters = MetaFilters()
        self.rows: list[MetaTeamRow] = []
        self.total: int = 0
        self.exhausted: bool = False
        self._loaded_key: MetaFilters | None = None
        self._stale: bool = True

    # -- state --------------------------------------------------------------------------

    @property
    def loaded(self) -> int:
        return len(self.rows)

    @property
    def needs_load(self) -> bool:
        return self._stale or self._loaded_key != self.filters

    def set_filters(self, filters: MetaFilters) -> None:
        self.filters = filters

    def invalidate(self) -> None:
        """New data landed; the next load re-queries even with unchanged filters."""
        self._stale = True

    # -- loading (each call is one session) ---------------------------------------------

    def load_first_page(self) -> list[MetaTeamRow]:
        with self._sf() as s:
            svc = TournamentService(s)
            kwargs = self.filters.to_query_kwargs()
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
                **self.filters.to_query_kwargs(), limit=PAGE_SIZE, offset=self.loaded
            )
        self.rows.extend(batch)
        self.exhausted = not batch or len(self.rows) >= self.total
        return batch

    def summary(self) -> MetaSummary:
        with self._sf() as s:
            return TournamentService(s).meta_summary()

    def regulation_options(self) -> list[str]:
        with self._sf() as s:
            return TournamentService(s).list_regulations()

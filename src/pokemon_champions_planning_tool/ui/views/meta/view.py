"""Meta explorer: tournament teams as rows grouped by event, with filters and paging."""

from __future__ import annotations

from typing import Any

import flet as ft

from ....services.tournament_service import MetaTeamRow
from ... import events
from ...components import ActiveFilterChip, EmptyState, PageHeader, skeleton_rows
from ...components.banner import InlineBanner
from ...context import AppContext
from ...format import plural, relative_time
from ...tasks import Debouncer, is_mounted
from ...theme import Accent, IconSize, Layout, Palette, Space
from ..settings.store import SettingsStore
from .row import EventHeader, TeamRow
from .store import GAME_OPTIONS, PAGE_SIZE, PLACEMENT_OPTIONS, RECENCY_OPTIONS, MetaFilters, MetaStore

_SEARCH_DEBOUNCE_MS = 400


class MetaView(ft.Column):
    def __init__(self, ctx: AppContext, store: MetaStore | None = None) -> None:
        super().__init__(spacing=Space.MD, expand=True)
        self.ctx = ctx
        self.store = store or MetaStore()
        self._sync_store = SettingsStore()
        self._loading = False
        self._groups: dict[str, EventHeader] = {}
        self._group_counts: dict[str, int] = {}

        # -- header -------------------------------------------------------------------
        self._sync_button = ft.IconButton(
            icon=ft.Icons.SYNC, icon_size=IconSize.MD, tooltip="Sync tournaments now", on_click=lambda _e: self._sync_now()
        )
        self._sync_spinner = ft.ProgressRing(width=16, height=16, stroke_width=2, visible=False)
        self.header = PageHeader("Meta", icon=ft.Icons.EMOJI_EVENTS, accent=Accent.META, actions=[self._sync_spinner, self._sync_button])

        # -- filter bar ---------------------------------------------------------------
        self._search = ft.TextField(
            hint_text="Species, player or event…",
            prefix_icon=ft.Icons.SEARCH,
            width=320,
            dense=True,
            height=Layout.TOOLBAR_HEIGHT - 8,
            on_change=lambda e: self._debounced_search(e.control.value or ""),
            on_submit=lambda e: self._apply(query=e.control.value or ""),
        )
        self._debounced_search = Debouncer(ctx.page, _SEARCH_DEBOUNCE_MS, lambda q: self._apply(query=q))
        self._placement = ft.SegmentedButton(
            selected=[self.store.filters.placement],
            allow_multiple_selection=False,
            allow_empty_selection=False,
            show_selected_icon=False,
            segments=[ft.Segment(value=v, label=ft.Text(label)) for v, label in PLACEMENT_OPTIONS],
            on_change=lambda e: self._apply(placement=next(iter(e.control.selected or ["8"]))),
        )
        self._regulation = ft.Dropdown(
            value="All",
            options=[ft.DropdownOption(key="All", text="All regulations")],
            width=190,
            enable_filter=True,
            on_select=lambda e: self._apply(regulation=e.control.value or "All"),
        )
        self._recency = ft.Dropdown(
            value=self.store.filters.recency,
            options=[ft.DropdownOption(key=v, text=label) for v, label in RECENCY_OPTIONS],
            width=170,
            on_select=lambda e: self._apply(recency=e.control.value or "365"),
        )
        self._game = ft.Dropdown(
            value="All",
            options=[ft.DropdownOption(key=v, text=label) for v, label in GAME_OPTIONS],
            width=180,
            on_select=lambda e: self._apply(game=e.control.value or "All"),
        )
        self._search_button = ft.OutlinedButton("Search", icon=ft.Icons.SEARCH, on_click=lambda _e: self._apply(query=self._search.value or "", force=True))
        self.filter_bar = ft.Row(
            spacing=Space.SM,
            wrap=True,
            vertical_alignment=ft.CrossAxisAlignment.CENTER,
            controls=[self._search, self._placement, self._regulation, self._recency, self._game, self._search_button],
        )
        self._active_chips = ft.Row(spacing=Space.SM, wrap=True, visible=False)
        self._order_caption = ft.Text("", theme_style=ft.TextThemeStyle.BODY_SMALL, color=Palette.ON_SURFACE_VARIANT)

        # -- results ------------------------------------------------------------------
        self.banner = InlineBanner(visible=False)
        self._progress = ft.ProgressBar(visible=False, bar_height=2, color=Palette.PRIMARY, bgcolor=Palette.OUTLINE_VARIANT)
        self._list = ft.ListView(expand=True, spacing=0, padding=ft.Padding.only(bottom=Space.XL))
        self._more_ring = ft.ProgressRing(width=16, height=16, stroke_width=2, visible=False)
        self._more_button = ft.FilledTonalButton("Show more", icon=ft.Icons.EXPAND_MORE, visible=False, on_click=lambda _e: self._load_more())
        self._more_row = ft.Row(alignment=ft.MainAxisAlignment.CENTER, spacing=Space.SM, controls=[self._more_ring, self._more_button])

        self.controls = [
            self.header,
            self.filter_bar,
            self._active_chips,
            self.banner,
            self._progress,
            ft.Row(alignment=ft.MainAxisAlignment.SPACE_BETWEEN, controls=[self._order_caption]),
            self._list,
            self._more_row,
        ]

        ctx.bus.on(events.META_SYNCED, self._on_meta_synced)
        ctx.bus.on(events.CATALOGS_RELOADED, self._on_catalogs_reloaded)

    # -- lifecycle ----------------------------------------------------------------------

    def ensure_loaded(self) -> None:
        """Load on first visit or after invalidation; otherwise reuse the built rows."""
        if self.store.needs_load:
            self._reload()

    def _refresh_header(self) -> None:
        summary = self.store.summary()
        self.header.set_count(summary.team_count)
        self.header.set_caption(f"{plural(summary.event_count, 'event')} · synced {relative_time(summary.synced_at)}")
        regs = self.store.regulation_options()
        self._regulation.options = [ft.DropdownOption(key="All", text="All regulations")] + [
            ft.DropdownOption(key=r, text=r) for r in regs
        ]
        if self.store.filters.regulation not in {"All", *regs}:
            self._regulation.value = "All"

    # -- filters ------------------------------------------------------------------------

    def _apply(self, *, force: bool = False, **changes: Any) -> None:
        from dataclasses import replace

        new_filters = replace(self.store.filters, **changes)
        if new_filters == self.store.filters and not force:
            return
        self.store.set_filters(new_filters)
        if force:
            self.store.invalidate()
        self._reload()

    def _remove_filter(self, field: str) -> None:
        self.store.set_filters(self.store.filters.without(field))
        self._sync_filter_controls()
        self._reload()

    def _clear_filters(self) -> None:
        self.store.set_filters(MetaFilters())
        self._sync_filter_controls()
        self._reload()

    def _sync_filter_controls(self) -> None:
        f = self.store.filters
        self._search.value = f.query
        self._placement.selected = [f.placement]
        self._regulation.value = f.regulation
        self._recency.value = f.recency
        self._game.value = f.game

    def _render_active_chips(self) -> None:
        active = self.store.filters.active()
        chips: list[ft.Control] = [ActiveFilterChip(label, on_remove=lambda field=field: self._remove_filter(field)) for field, label in active]
        if chips:
            chips.append(ft.TextButton("Clear all", on_click=lambda _e: self._clear_filters()))
        self._active_chips.controls = chips
        self._active_chips.visible = bool(chips)

    # -- loading ------------------------------------------------------------------------

    def _reload(self) -> None:
        self._loading = True
        self.banner.hide()
        self._list.controls = [skeleton_rows(8)]
        self._more_button.visible = False
        self._render_active_chips()
        self._update_self()

        def work():
            rows = self.store.load_first_page()
            return rows

        def done(_rows) -> None:
            self._loading = False
            self._refresh_header()
            self._render_rows(reset=True)
            self._update_self()

        def failed(exc: BaseException) -> None:
            self._loading = False
            self._list.controls = [EmptyState(ft.Icons.ERROR_OUTLINE, "Couldn't load tournament data", str(exc), action_label="Retry", on_action=self._reload)]
            self._update_self()

        self.ctx.run_in_background(work, on_done=done, on_error=failed, spinner=self._progress)

    def _load_more(self) -> None:
        if self._loading or self.store.exhausted:
            return
        self._loading = True
        before = self.store.loaded

        def done(_batch) -> None:
            self._loading = False
            self._render_rows(reset=False, start=before)
            self._update_self()

        def failed(exc: BaseException) -> None:
            self._loading = False
            self.ctx.toast(f"Couldn't load more: {exc}", "error")
            self._update_self()

        self.ctx.run_in_background(self.store.load_more, on_done=done, on_error=failed, busy=[self._more_button], spinner=self._more_ring)

    def _render_rows(self, *, reset: bool, start: int = 0) -> None:
        rows = self.store.rows
        if reset:
            self._list.controls = []
            self._groups: dict[str, EventHeader] = {}
            self._group_counts: dict[str, int] = {}
            start = 0
        if not rows:
            self._list.controls = [self._empty_state()]
            self._more_button.visible = False
            self._order_caption.value = ""
            return
        for row in rows[start:]:
            header = self._groups.get(row.tournament_id)
            if header is None:
                header = EventHeader(row, shown=0)
                self._groups[row.tournament_id] = header
                self._group_counts[row.tournament_id] = 0
                self._list.controls.append(header)
            self._group_counts[row.tournament_id] += 1
            header.set_shown(self._group_counts[row.tournament_id])
            self._list.controls.append(TeamRow(row, on_import=self._import))
        self._more_button.visible = not self.store.exhausted
        self._more_button.content = f"Show more · {self.store.loaded:,} of {self.store.total:,}"
        self._order_caption.value = f"Newest events first · {self.store.loaded:,} of {plural(self.store.total, 'team')}"

    def _empty_state(self) -> ft.Control:
        if self.store.total == 0 and not self.store.filters.active():
            return EmptyState(
                ft.Icons.EMOJI_EVENTS_OUTLINED,
                "No tournament data yet",
                "Tournament teams sync in the background on startup from Limitless and Victory Road. This can take a few minutes.",
                action_label="Sync now",
                on_action=self._sync_now,
                secondary_label="Open Settings",
                on_secondary=lambda: self.ctx.bus.emit(events.NAVIGATE, "settings"),
            )
        return EmptyState(
            ft.Icons.SEARCH_OFF,
            "No teams match",
            "Try a broader placement tier, a longer time window, or clear the search.",
            action_label="Clear filters",
            on_action=self._clear_filters,
        )

    # -- import handoff --------------------------------------------------------------------

    def _import(self, row: MetaTeamRow) -> None:
        title = f"{row.player_name} — {row.tournament_name}"
        self.ctx.bus.emit(events.IMPORT_REQUESTED, (row.showdown_text, title))

    # -- sync -----------------------------------------------------------------------------

    def _sync_now(self) -> None:
        def done(result: dict) -> None:
            self.ctx.toast("Tournament data synced", "success")
            self.ctx.bus.emit(events.META_SYNCED, result)
            self.ctx.bus.emit(events.CATALOGS_RELOADED, "tournaments")

        self.ctx.run_in_background(
            self._sync_store.sync_tournaments,
            on_done=done,
            on_error=lambda exc: self.ctx.toast(f"Tournament sync failed: {exc}", "error"),
            busy=[self._sync_button],
            spinner=self._sync_spinner,
        )

    def _on_meta_synced(self, result: Any) -> None:
        """Background sync finished. Never reshuffle rows under the user: offer a refresh."""
        self.store.invalidate()
        added = 0
        if isinstance(result, dict):
            for key in ("limitless", "victory_road"):
                added += int((result.get(key) or {}).get("added", 0) or 0)
        if self.store.loaded and added:
            self.banner.show(f"{plural(added, 'new team')} synced", "info", action_label="Refresh", on_action=self._reload)
            self._update_self()
        elif is_mounted(self) and not self.store.loaded:
            self._reload()

    def _on_catalogs_reloaded(self, kind: str) -> None:
        if kind == "tournaments" and is_mounted(self):
            self._reload()

    # -- helpers --------------------------------------------------------------------------

    def _update_self(self) -> None:
        if is_mounted(self):
            self.update()

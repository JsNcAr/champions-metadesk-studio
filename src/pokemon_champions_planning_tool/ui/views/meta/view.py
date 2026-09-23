"""Meta explorer: tournament teams as rows grouped by event, with filters and paging."""

from __future__ import annotations

from typing import Any

import flet as ft

from ....services.tournament_service import MetaTeamRow
from ... import events
from ...components import ActiveFilterChip, EmptyState, PageHeader, SyncIndicator, skeleton_rows
from ...components.banner import InlineBanner
from ...components.inputs import SEARCH_FIELD_STYLE
from ...context import AppContext
from ...format import plural, relative_time
from ...tasks import Debouncer, grid_tile_aspect, is_mounted
from ...theme import Accent, DEFAULT_WINDOW_WIDTH, IconSize, Layout, Palette, Space
from ..settings.store import SettingsStore
from .row import EVENT_CARD_HEIGHT, EVENT_CARD_MAX_EXTENT, EventCard, EventDialog, EventGroup, EventHeader, TeamRow
from .store import BOX_OPTIONS, FORMAT_OPTIONS, TIER_OPTIONS, GAME_OPTIONS, PLACEMENT_OPTIONS, RECENCY_OPTIONS, MetaFilters, MetaStore

_SEARCH_DEBOUNCE_MS = 400
# With groups collapsed (or as cards) a 20-team page shows only two or three events, so
# pages keep loading until this many events are on screen or the results run out.
MIN_VISIBLE_GROUPS = 6
_MAX_FILL_PAGES = 4


class MetaView(ft.Column):
    def __init__(self, ctx: AppContext, store: MetaStore | None = None) -> None:
        super().__init__(spacing=Space.MD, expand=True)
        self.ctx = ctx
        self.store = store or MetaStore()
        self._sync_store = SettingsStore()
        self._loading = False
        self._groups: dict[str, EventGroup] = {}
        self._cards: dict[str, EventCard] = {}
        self.view_mode = "cards" if ctx.prefs.get("meta.view_mode") == "cards" else "rows"
        self.collapsed = bool(ctx.prefs.get("meta.collapsed", True))   # rows mode: only the winner of each event until expanded
        self._fill_pages = 0
        self._page_width = float(getattr(ctx.page, "width", None) or DEFAULT_WINDOW_WIDTH)

        # -- header -------------------------------------------------------------------
        self._sync_button = ft.IconButton(
            icon=ft.Icons.SYNC, icon_size=IconSize.MD, tooltip="Sync tournaments now", on_click=lambda _e: self._sync_now()
        )
        self._sync_spinner = ft.ProgressRing(width=16, height=16, stroke_width=2, visible=False)
        self.sync_indicator = SyncIndicator()
        self.header = PageHeader("Meta", icon=ft.Icons.EMOJI_EVENTS, accent=Accent.META, actions=[self.sync_indicator, self._sync_spinner, self._sync_button])

        # -- filter bar ---------------------------------------------------------------
        self._search = ft.TextField(**SEARCH_FIELD_STYLE, 
            hint_text="Species, player, event (-species to exclude)…",
            tooltip="Search species, players, or events. Prefix with - or ! to exclude (e.g. pelipper -archaludon)",
            prefix_icon=ft.Icons.SEARCH,
            width=320,
            dense=True,
            height=Layout.TOOLBAR_HEIGHT - 8,
            on_change=lambda e: self._debounced_search(e.control.value or ""),
            on_submit=lambda e: self._apply(query=e.control.value or ""),
        )
        self._debounced_search = Debouncer(ctx.page, _SEARCH_DEBOUNCE_MS, lambda q: self._apply(query=q))
        self._placement = ft.Dropdown(
            value=self.store.filters.placement,
            options=[ft.DropdownOption(key=v, text=label) for v, label in PLACEMENT_OPTIONS],
            width=165,
            leading_icon=ft.Icons.LEADERBOARD_OUTLINED,
            tooltip="Filter teams by tournament finish",
            on_select=lambda e: self._apply(placement=e.control.value or "8"),
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
        self._source = ft.SegmentedButton(
            selected=[self.store.filters.source],
            allow_multiple_selection=False,
            allow_empty_selection=False,
            show_selected_icon=False,
            segments=[
                ft.Segment(value="All", label=ft.Text("All"), tooltip="Official and community events"),
                ft.Segment(value="official", icon=ft.Icon(ft.Icons.VERIFIED, size=IconSize.SM), label=ft.Text("Official"), tooltip="Play! Pokémon events: Worlds, Internationals, Regionals, Special Events"),
                ft.Segment(value="community", icon=ft.Icon(ft.Icons.GROUPS, size=IconSize.SM), label=ft.Text("Community"), tooltip="Community-run and online events (Limitless, Victory Road community)"),
            ],
            on_change=lambda e: self._apply_source(next(iter(e.control.selected or ["All"]))),
        )
        self._tier = ft.Dropdown(
            value=self.store.filters.tier,
            options=[ft.DropdownOption(key=v, text=label) for v, label in TIER_OPTIONS],
            width=200,
            visible=self.store.filters.source == "official",
            on_select=lambda e: self._apply(tier=e.control.value or "All"),
        )
        self._box = ft.Dropdown(
            value=self.store.filters.box,
            options=[ft.DropdownOption(key=v, text=label) for v, label in BOX_OPTIONS],
            width=195,
            leading_icon=ft.Icons.INVENTORY_2_OUTLINED,
            tooltip="Teams you can build from your box (owned entries; Megas count as their base species)",
            on_select=lambda e: self._apply(box=e.control.value or "any"),
        )
        self._battle_format = ft.Dropdown(
            value=self.store.filters.battle_format,
            options=[ft.DropdownOption(key=v, text=label) for v, label in FORMAT_OPTIONS],
            width=180,
            visible=self.store.filters.battle_format != "doubles",
            on_select=lambda e: self._apply(battle_format=e.control.value or "doubles"),
        )
        self._search_button = ft.OutlinedButton("Search", icon=ft.Icons.SEARCH, on_click=lambda _e: self._apply(query=self._search.value or "", force=True))
        self.filter_bar = ft.Row(
            spacing=Space.SM,
            wrap=True,
            vertical_alignment=ft.CrossAxisAlignment.CENTER,
            controls=[self._search, self._placement, self._source, self._tier, self._box, self._regulation, self._recency, self._game, self._battle_format, self._search_button],
        )
        self._active_chips = ft.Row(spacing=Space.SM, wrap=True, visible=False)
        self._order_caption = ft.Text("", theme_style=ft.TextThemeStyle.BODY_SMALL, color=Palette.ON_SURFACE_VARIANT)
        self._collapse_button = ft.TextButton("Expand all" if self.collapsed else "Collapse all", icon=ft.Icons.UNFOLD_MORE if self.collapsed else ft.Icons.UNFOLD_LESS, on_click=lambda _e: self._toggle_all())
        self._layout_toggle = ft.SegmentedButton(
            selected=[self.view_mode],
            allow_multiple_selection=False,
            allow_empty_selection=False,
            show_selected_icon=False,
            segments=[
                ft.Segment(value="rows", icon=ft.Icon(ft.Icons.VIEW_LIST), tooltip="Events as rows"),
                ft.Segment(value="cards", icon=ft.Icon(ft.Icons.GRID_VIEW), tooltip="Events as cards"),
            ],
            on_change=lambda e: self._set_view_mode(next(iter(e.control.selected or ["rows"]))),
        )

        # -- results ------------------------------------------------------------------
        self.banner = InlineBanner(visible=False)
        self._progress = ft.ProgressBar(visible=False, bar_height=2, color=Palette.PRIMARY, bgcolor=Palette.OUTLINE_VARIANT)
        self._list = ft.ListView(expand=True, spacing=0, padding=ft.Padding.only(bottom=Space.XL))
        self._grid = ft.GridView(expand=True, max_extent=EVENT_CARD_MAX_EXTENT, child_aspect_ratio=1.3, spacing=Space.GRID_GAP, run_spacing=Space.GRID_GAP, visible=False)
        self._more_ring = ft.ProgressRing(width=16, height=16, stroke_width=2, visible=False)
        self._more_button = ft.FilledTonalButton("Show more", icon=ft.Icons.EXPAND_MORE, visible=False, on_click=lambda _e: self._load_more())
        self._more_row = ft.Row(alignment=ft.MainAxisAlignment.CENTER, spacing=Space.SM, controls=[self._more_ring, self._more_button])

        self.controls = [
            self.header,
            self.filter_bar,
            self._active_chips,
            self.banner,
            self._progress,
            ft.Row(
                alignment=ft.MainAxisAlignment.SPACE_BETWEEN,
                vertical_alignment=ft.CrossAxisAlignment.CENTER,
                controls=[self._order_caption, ft.Row(spacing=Space.SM, tight=True, controls=[self._collapse_button, self._layout_toggle])],
            ),
            self._list,
            self._grid,
            self._more_row,
        ]
        self._relayout()

        ctx.bus.on(events.META_SYNCED, self._on_meta_synced)
        ctx.bus.on(events.META_SEARCH, self._on_search_requested)
        ctx.bus.on(events.CATALOGS_RELOADED, self._on_catalogs_reloaded)
        ctx.bus.on(events.SYNC_PROGRESS, self._on_sync_progress)
        ctx.bus.on(events.BOX_CHANGED, self._on_box_changed)
        ctx.bus.on(events.BATTLE_FORMAT_CHANGED, self._on_battle_format_changed)

    def handle_key(self, e) -> bool:
        if e.ctrl and (e.key or "").lower() == "f" and is_mounted(self._search):
            self.ctx.page.run_task(self._search.focus)
            return True
        return False

    # -- lifecycle ----------------------------------------------------------------------

    def ensure_loaded(self) -> None:
        """Load on first visit or after invalidation; otherwise reuse the built rows."""
        if not self.store.loaded or self.store.needs_load:
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
        self._tier.visible = new_filters.source == "official"
        self._tier.value = new_filters.tier
        self._placement.value = new_filters.placement
        self._box.value = new_filters.box
        self._battle_format.value = new_filters.battle_format
        self._battle_format.visible = new_filters.battle_format != "doubles"
        if force:
            self.store.invalidate()
        self._reload()

    def _on_search_requested(self, query) -> None:
        """Another view asked for the teams with a species (Teams' partner chips)."""
        text = str(query or "").strip()
        if text:
            self._search.value = text
            self._apply(query=text, force=True)

    def _apply_source(self, source: str) -> None:
        """Leaving "official" drops the tier with it; the tier dropdown only shows there."""
        self._apply(source=source, tier=self.store.filters.tier if source == "official" else "All")

    def _remove_filter(self, field: str) -> None:
        self.store.set_filters(self.store.filters.without(field))
        self._sync_filter_controls()
        self._reload()

    def _clear_filters(self) -> None:
        self.store.set_filters(MetaFilters())
        pref = self.store.load_preference()
        self.store.set_filters(MetaFilters(battle_format=pref))
        self._sync_filter_controls()
        self._reload()

    def _sync_filter_controls(self) -> None:
        f = self.store.filters
        self._search.value = f.query
        self._placement.value = f.placement
        self._regulation.value = f.regulation
        self._recency.value = f.recency
        self._game.value = f.game
        self._source.selected = [f.source]
        self._tier.value = f.tier
        self._tier.visible = f.source == "official"
        self._box.value = f.box
        self._battle_format.value = f.battle_format
        self._battle_format.visible = f.battle_format != "doubles"

    def _on_battle_format_changed(self, _val: Any = None) -> None:
        self.store.reload_preference()
        self._sync_filter_controls()
        self._reload()

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
        self._fill_pages = 0
        self.banner.hide()
        self._list.controls = [skeleton_rows(8)]
        self._list.visible = True
        self._grid.visible = False
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
            self._maybe_fill()

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
            self._maybe_fill()

        def failed(exc: BaseException) -> None:
            self._loading = False
            self.ctx.toast(f"Couldn't load more: {exc}", "error")
            self._update_self()

        self.ctx.run_in_background(self.store.load_more, on_done=done, on_error=failed, busy=[self._more_button], spinner=self._more_ring)

    def _render_rows(self, *, reset: bool, start: int = 0) -> None:
        rows = self.store.rows
        if reset:
            self._list.controls = []
            self._grid.controls = []
            self._groups = {}
            self._cards = {}
            start = 0
        if not rows:
            self._list.controls = [self._empty_state()]
            self._grid.controls = []
            self._list.visible = True
            self._grid.visible = False
            self._more_button.visible = False
            self._order_caption.value = ""
            return
        for row in rows[start:]:
            group = self._groups.get(row.tournament_id)
            if group is None:
                header = EventHeader(row, shown=0, on_toggle=lambda tid=row.tournament_id: self._toggle_group(tid))
                group = EventGroup(header)
                group.collapsed = self.collapsed
                self._groups[row.tournament_id] = group
                self._list.controls.append(group)
                card = EventCard(row, shown=0, on_open=self._open_event, on_import=self._import)
                self._cards[row.tournament_id] = card
                self._grid.controls.append(card)
            group.add_row(TeamRow(row, on_import=self._import, on_calc=self._calc_vs, on_rival=self._save_rival))
            self._cards[row.tournament_id].set_shown(len(group.rows))
        self._list.visible = self.view_mode == "rows"
        self._grid.visible = self.view_mode == "cards"
        self._collapse_button.visible = self.view_mode == "rows"
        self._more_button.visible = not self.store.exhausted
        self._more_button.content = f"Show more · {self.store.loaded:,} of {self.store.total:,}"
        self._render_caption_only()

    # -- grouping, layout and the event dialog ------------------------------------------------

    def _maybe_fill(self) -> None:
        """Collapsed rows and cards show one line per event; keep paging until enough events are visible."""
        if self.view_mode == "rows" and not self.collapsed:
            return
        if self.store.exhausted or self._loading or self._fill_pages >= _MAX_FILL_PAGES:
            return
        if len(self._groups) >= MIN_VISIBLE_GROUPS:
            return
        self._fill_pages += 1
        self._load_more()

    def _toggle_group(self, tournament_id: str) -> None:
        group = self._groups.get(tournament_id)
        if group is None:
            return
        group.set_collapsed(not group.collapsed)
        if is_mounted(group):
            group.update()

    def _toggle_all(self) -> None:
        self.collapsed = not self.collapsed
        self.ctx.prefs.set("meta.collapsed", self.collapsed)
        self._collapse_button.content = "Expand all" if self.collapsed else "Collapse all"
        self._collapse_button.icon = ft.Icons.UNFOLD_MORE if self.collapsed else ft.Icons.UNFOLD_LESS
        for group in self._groups.values():
            group.set_collapsed(self.collapsed)
        if self.store.rows:
            self._render_caption_only()
        self._update_self()
        self._maybe_fill()

    def _render_caption_only(self) -> None:
        unit = "event" if self.view_mode == "cards" or self.collapsed else "team"
        shown = len(self._groups) if unit == "event" else self.store.loaded
        order = "Closest to your box first" if self.store.filters.max_missing is not None else "Newest events first"
        self._order_caption.value = f"{order} · {shown:,} {unit}{'s' if shown != 1 else ''} shown · {plural(self.store.total, 'team')} match"

    def _set_view_mode(self, mode: str) -> None:
        self.view_mode = "cards" if mode == "cards" else "rows"
        self.ctx.prefs.set("meta.view_mode", self.view_mode)
        self._layout_toggle.selected = [self.view_mode]
        has_rows = bool(self.store.rows)
        self._list.visible = self.view_mode == "rows" or not has_rows
        self._grid.visible = self.view_mode == "cards" and has_rows
        self._collapse_button.visible = self.view_mode == "rows"
        if has_rows:
            self._render_caption_only()
        self._update_self()
        self._maybe_fill()

    def handle_resize(self, width: float, height: float) -> None:
        self._page_width = width
        self._relayout()

    def _relayout(self) -> None:
        available = self._page_width - Layout.RAIL_WIDTH - 1 - 2 * Space.PAGE_PADDING
        self._grid.child_aspect_ratio = grid_tile_aspect(available, max_extent=EVENT_CARD_MAX_EXTENT, spacing=Space.GRID_GAP, tile_height=EVENT_CARD_HEIGHT)

    def _open_event(self, tournament_id: str) -> None:
        group = self._groups.get(tournament_id)
        if group is None or not group.rows:
            return
        page = self.ctx.page

        def import_and_close(row: MetaTeamRow) -> None:
            page.pop_dialog()
            self._import(row)

        dialog = EventDialog(group.first_row, on_import=import_and_close, on_close=page.pop_dialog, on_calc=self._calc_vs, on_rival=self._save_rival)
        page.show_dialog(dialog)
        self.ctx.run_in_background(lambda: self.store.teams_for_event(tournament_id), on_done=dialog.set_rows, on_error=dialog.set_error)

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
        if self.store.filters.box != "any" and not self.store.box_species:
            return EmptyState(
                ft.Icons.INVENTORY_2_OUTLINED,
                "Your box is empty",
                "Add the Pokémon you own to find tournament teams you can build.",
                action_label="Go to Box",
                on_action=lambda: self.ctx.bus.emit(events.NAVIGATE, "box"),
                secondary_label="Show all teams",
                on_secondary=lambda: self._apply(box="any"),
            )
        if self.store.filters.box != "any":
            limit = dict(BOX_OPTIONS)[self.store.filters.box]
            return EmptyState(
                ft.Icons.INVENTORY_2_OUTLINED,
                "No team is that close to your box",
                f"No roster matches “{limit}” with the other filters. Allow more missing Pokémon or widen the other filters.",
                action_label="Allow more missing" if self.store.filters.box != "3" else "Clear filters",
                on_action=(lambda: self._apply(box="3")) if self.store.filters.box != "3" else self._clear_filters,
                secondary_label="Show all teams",
                on_secondary=lambda: self._apply(box="any"),
            )
        return EmptyState(
            ft.Icons.SEARCH_OFF,
            "No teams match",
            "Try a broader placement tier, a longer time window, or clear the search.",
            action_label="Clear filters",
            on_action=self._clear_filters,
        )

    # -- import handoff --------------------------------------------------------------------

    def _calc_vs(self, row: MetaTeamRow, index: int) -> None:
        """Send one roster member to the damage calculator as the defender (with the paste's set)."""
        from ....services.showdown_service import parse_showdown_text
        from ..calc.state import CalcRequest, pokemon_from_parsed

        if index >= len(row.members):
            return
        member = row.members[index]
        parsed = None
        if row.showdown_text:
            try:
                slots = parse_showdown_text(row.showdown_text).slots
                parsed = slots[index] if index < len(slots) else None
            except Exception:  # noqa: BLE001 - a paste that does not parse just means defaults
                parsed = None
        pokemon = pokemon_from_parsed(parsed, member.canonical_id, self.ctx.catalogs, source=f"{row.player_name} · {row.tournament_name}")
        if pokemon is None:
            self.ctx.toast(f"{member.display_name} is not in the species catalogue", "warning")
            return
        self.ctx.bus.emit(events.CALC_REQUESTED, CalcRequest(defender=pokemon))

    def _save_rival(self, row: MetaTeamRow) -> None:
        """Keep a tournament team as a rival preset to plan against in the calculator."""
        from ..calc.rival_store import RivalStore, rivals_from_meta_row

        members = rivals_from_meta_row(row, self.ctx.catalogs)
        if not members:
            self.ctx.toast("None of this team's Pokémon are in the species catalogue", "warning")
            return
        team = RivalStore(self.store.session_factory).create(f"{row.player_name} — {row.tournament_name}", members, source=f"Meta · {row.player_name} · {row.tournament_name}")
        self.ctx.bus.emit(events.RIVALS_CHANGED, team.rival_team_id)
        self.ctx.toast(f"Saved {row.player_name}'s team as a rival preset", "success", action="Open in Calc",
                       on_action=lambda: self.ctx.bus.emit(events.RIVAL_OPEN, team.rival_team_id))

    def _import(self, row: MetaTeamRow) -> None:
        title = f"{row.player_name} — {row.tournament_name}"
        self.ctx.bus.emit(events.IMPORT_REQUESTED, (row.showdown_text, title))

    # -- sync -----------------------------------------------------------------------------

    def _sync_now(self) -> None:
        from ....services.tournament_sync_service import summarize_sync_result, sync_in_progress

        if sync_in_progress():
            self.ctx.toast("A sync is already running", "info")
            return

        def done(result: dict) -> None:
            self.ctx.toast(summarize_sync_result(result), "success" if result.get("status") in ("synced", "partial") else "info")
            if result.get("status") in ("synced", "partial"):
                self.ctx.bus.emit(events.META_SYNCED, result)
                self.ctx.bus.emit(events.CATALOGS_RELOADED, "tournaments")

        self.ctx.sync_tournaments(
            self._sync_store.sync_tournaments,
            on_done=done,
            on_error=lambda exc: self.ctx.toast(f"Tournament sync failed: {exc}", "error"),
            busy=[self._sync_button],
            spinner=self._sync_spinner,
        )

    def _on_sync_progress(self, progress) -> None:
        self.sync_indicator.update_from(progress)
        self._sync_button.disabled = progress.running
        if is_mounted(self._sync_button):
            self._sync_button.update()
        if not progress.running:
            self._hide_indicator_later()

    def _hide_indicator_later(self, delay_s: float = 8.0) -> None:
        import asyncio

        indicator = self.sync_indicator
        shown_phase = indicator.phase

        async def _hide() -> None:
            await asyncio.sleep(delay_s)
            if indicator.phase == shown_phase:
                indicator.hide()

        self.ctx.page.run_task(_hide)

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

    def _on_box_changed(self, _payload) -> None:
        """The box changed: marks and the Box filter must be recomputed on the next load."""
        before = self.store.box_species
        if self.store.refresh_box() != before or not self.store.loaded:
            self.store.invalidate()
            if is_mounted(self) and self.store.loaded:
                self._reload()

    def _on_catalogs_reloaded(self, kind: str) -> None:
        if kind == "tournaments" and is_mounted(self):
            self._reload()

    # -- helpers --------------------------------------------------------------------------

    def _update_self(self) -> None:
        if is_mounted(self):
            self.update()

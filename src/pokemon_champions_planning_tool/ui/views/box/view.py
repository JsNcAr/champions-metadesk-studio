"""Box roster view: header with add-by-name, toolbar, card grid or table, detail panel."""

from __future__ import annotations

from uuid import UUID

import flet as ft

from ....domain.entities.box_entry import BoxEntry
from ... import events
from ...components import EmptyState, PageHeader
from ...components.banner import InlineBanner
from ...components.inputs import SEARCH_FIELD_STYLE
from ...context import AppContext
from ...tasks import grid_tile_aspect, is_mounted
from ...theme import Accent, DEFAULT_WINDOW_WIDTH, Layout, Motion, OVERLAY_SHADOW, Palette, Radius, Space
from .card import CARD_HEIGHT, CARD_HEIGHT_WITH_STATS, CARD_MAX_EXTENT, PokemonCard
from .detail_panel import DetailPanel
from .filters import BoxFilters, SortKey
from .store import BoxStore
from .table import EXTRA_COLUMNS, BoxTable
from .toolbar import BoxToolbar

_MAX_SUGGESTIONS = 6


class BoxView(ft.Row):
    def __init__(self, ctx: AppContext, store: BoxStore | None = None) -> None:
        super().__init__(spacing=0, expand=True, vertical_alignment=ft.CrossAxisAlignment.STRETCH)
        self.ctx = ctx
        self.store = store or BoxStore(ctx.catalogs)
        self.view_mode = "table" if ctx.prefs.get("box.view_mode") == "table" else "grid"
        self.show_stats = bool(ctx.prefs.get("box.show_stats", False))
        self._cards: dict[UUID, PokemonCard] = {}

        # -- header: add by name -------------------------------------------------------------
        self._add_field = ft.TextField(**SEARCH_FIELD_STYLE, 
            hint_text="Add to box…",
            prefix_icon=ft.Icons.ADD_CIRCLE_OUTLINE,
            width=320,
            dense=True,
            height=Layout.TOOLBAR_HEIGHT - 8,
            on_change=lambda e: self._suggest(e.control.value or ""),
            on_submit=lambda e: self._add(e.control.value or ""),
        )
        self._add_spinner = ft.ProgressRing(width=16, height=16, stroke_width=2, visible=False)
        self._suggestions = ft.Row(spacing=Space.XS, wrap=True, visible=False)
        self._add_banner = InlineBanner(visible=False)
        self._export_button = ft.OutlinedButton("Export CSV", icon=ft.Icons.DOWNLOAD, tooltip="Export the visible entries (or the selected ones) to CSV", on_click=lambda _e: self._export())
        self.header = PageHeader("Box", icon=ft.Icons.INVENTORY_2, accent=Accent.BOX, count=0, actions=[self._add_spinner, self._add_field, self._export_button])

        # -- toolbar ---------------------------------------------------------------------------
        self.toolbar = BoxToolbar(ctx.page, on_filters=self._on_filters, on_view_mode=self._set_view_mode, on_show_stats=self._set_show_stats, on_columns=self._set_columns)
        self.toolbar.set_view_state(self.view_mode, self.show_stats)
        self.columns: list[str] = [c for c in (ctx.prefs.get("box.columns") or []) if isinstance(c, str)]
        self.toolbar.set_columns(self.columns)

        # -- content ---------------------------------------------------------------------------
        self._page_width = float(getattr(ctx.page, "width", None) or DEFAULT_WINDOW_WIDTH)
        self.grid = ft.GridView(expand=True, max_extent=CARD_MAX_EXTENT, child_aspect_ratio=1.0, spacing=Space.GRID_GAP, run_spacing=Space.GRID_GAP)
        self.table = BoxTable(on_sort=self._on_table_sort, on_select=self._select, on_check=self._check)
        self.table.set_columns(self.columns)
        self.table.visible = False
        self._empty = EmptyState(ft.Icons.INVENTORY_2_OUTLINED, "Your box is empty", "Add a Pokémon by name to start planning.", action_label="Add a Pokémon", on_action=self._focus_add)
        self._empty.visible = False
        self._no_match = EmptyState(ft.Icons.SEARCH_OFF, "No Pokémon match", "Try fewer filters or a different search.", action_label="Clear filters", on_action=self.toolbar.clear)
        self._no_match.visible = False
        # -- bulk selection bar (floats over the content) -------------------------------------
        self._bulk_count = ft.Text("", theme_style=ft.TextThemeStyle.BODY_LARGE, color=Palette.ON_SURFACE)
        self._bulk_team_menu = ft.PopupMenuButton(
            content=ft.Container(
                content=ft.Row(spacing=Space.XS, tight=True, vertical_alignment=ft.CrossAxisAlignment.CENTER, controls=[
                    ft.Icon(ft.Icons.GROUP_ADD, size=18, color=Palette.PRIMARY),
                    ft.Text("Add to team", theme_style=ft.TextThemeStyle.LABEL_LARGE, color=Palette.PRIMARY),
                    ft.Icon(ft.Icons.ARROW_DROP_DOWN, size=18, color=Palette.PRIMARY),
                ]),
                padding=ft.Padding.symmetric(horizontal=Space.SM, vertical=6),
            ),
            items=[],
            tooltip="Fill a team's empty slots with the selection",
        )
        self.bulk_bar = ft.Container(
            content=ft.Row(
                spacing=Space.SM,
                vertical_alignment=ft.CrossAxisAlignment.CENTER,
                tight=True,
                controls=[
                    self._bulk_count,
                    ft.VerticalDivider(width=Space.LG, thickness=1, color=Palette.OUTLINE_VARIANT),
                    ft.TextButton("Favourite", icon=ft.Icons.STAR, on_click=lambda _e: self._bulk_favorite(True)),
                    ft.TextButton("Unfavourite", icon=ft.Icons.STAR_BORDER, on_click=lambda _e: self._bulk_favorite(False)),
                    ft.TextButton("Tag", icon=ft.Icons.TAG, on_click=lambda _e: self.ctx.page.run_task(self._bulk_tag)),
                    self._bulk_team_menu,
                    ft.TextButton("Delete", icon=ft.Icons.DELETE_OUTLINE, style=ft.ButtonStyle(color=Palette.ERROR), on_click=lambda _e: self.ctx.page.run_task(self._bulk_delete)),
                    ft.VerticalDivider(width=Space.LG, thickness=1, color=Palette.OUTLINE_VARIANT),
                    ft.TextButton("Clear", on_click=lambda _e: self.store.clear_multi()),
                ],
            ),
            bgcolor=Palette.SURFACE_4,
            border_radius=Radius.LG,
            padding=ft.Padding.symmetric(horizontal=Space.LG, vertical=Space.SM),
            shadow=OVERLAY_SHADOW,
            visible=False,
            bottom=Space.LG,
            animate_opacity=Motion.NORMAL_MS,
        )
        self._content = ft.Container(
            expand=True,
            content=ft.Stack(
                expand=True,
                alignment=ft.Alignment.BOTTOM_CENTER,
                controls=[
                    ft.Column(expand=True, spacing=0, controls=[self.grid, self.table, ft.Row(alignment=ft.MainAxisAlignment.CENTER, controls=[self._empty, self._no_match])]),
                    self.bulk_bar,
                ],
            ),
        )

        # -- detail panel ----------------------------------------------------------------------
        self.detail = DetailPanel(
            on_close=lambda: self._select(None),
            on_form=self._set_form,
            on_favorite=self._set_favorite,
            on_notes=self._save_notes,
            on_tags=self._save_tags,
            on_toggle_planned=self._toggle_planned,
            on_delete=self._delete,
            on_add_to_team=self._add_to_team,
        )

        left = ft.Column(
            expand=True,
            spacing=Space.MD,
            controls=[self.header, self._suggestions, self._add_banner, self.toolbar, self._content],
        )
        self.controls = [ft.Container(content=left, expand=True, padding=ft.Padding.only(right=Space.LG)), self.detail]

        self._relayout()
        self.store.subscribe(self._on_store_change)
        ctx.bus.on(events.CATALOGS_RELOADED, self._on_catalogs_reloaded)

    # -- lifecycle -------------------------------------------------------------------------------

    def ensure_loaded(self) -> None:
        if not self.store.entries:
            self.store.load()

    def handle_key(self, e) -> bool:
        """Shell hook for keys the shell itself does not consume."""
        if e.key == "Escape" and self.store.multi:
            self.store.clear_multi()
            return True
        if e.key == "Escape" and self.store.selected_id is not None:
            self._select(None)
            return True
        if e.ctrl and e.shift and e.key.lower() == "a":
            self.store.select_all_visible()
            return True
        if e.key == "Delete" and self.store.multi:
            self.ctx.page.run_task(self._bulk_delete)
            return True
        if e.ctrl and e.key.lower() == "f":
            self._focus(self.toolbar.search)
            return True
        if e.ctrl and e.key.lower() == "k":
            self._focus_add()
            return True
        return False

    # -- store -> view -----------------------------------------------------------------------------

    def _on_store_change(self, change: tuple) -> None:
        kind = change[0]
        if kind == "all":
            self._render()
        elif kind == "entry":
            self._render_entry(change[1])
        elif kind == "selection":
            self._render_selection(change[1])
        elif kind == "multi":
            self._render_multi()
        self._update_self()

    def _render(self) -> None:
        self.store.catalogs = self.ctx.catalogs or self.store.catalogs
        visible = self.store.visible()
        shown, owned = self.store.counts()
        self.header.set_count(owned if shown == owned else f"{shown} of {owned}")
        self.toolbar.set_available_tags(self.store.all_tags())

        empty = not self.store.entries
        no_match = bool(self.store.entries) and not visible
        self._empty.visible = empty
        self._no_match.visible = no_match

        if self.view_mode == "table":
            self.grid.visible = False
            self.table.visible = not (empty or no_match)
            self.table.update_from(visible, sort=self.store.filters.sort, descending=self.store.filters.descending, selected_id=self.store.selected_id, checked=self.store.multi)
        else:
            self.table.visible = False
            self.grid.visible = not (empty or no_match)
            controls: list[ft.Control] = []
            for entry in visible:
                card = self._cards.get(entry.box_entry_id)
                if card is None:
                    card = PokemonCard(on_select=self._select, on_favorite=self._set_favorite, on_tag=self._filter_by_tag, on_check=self._check)
                    self._cards[entry.box_entry_id] = card
                card.update_from(entry, selected=entry.box_entry_id == self.store.selected_id, show_stats=self.show_stats, mega_capable=self.store.is_mega_capable(entry))
                card.set_checked(entry.box_entry_id in self.store.multi, selection_mode=bool(self.store.multi))
                controls.append(card)
            self.grid.controls = controls
            for stale in set(self._cards) - {e.box_entry_id for e in self.store.entries}:
                self._cards.pop(stale, None)
        self._render_multi()
        self._render_detail()

    def _render_multi(self) -> None:
        n = len(self.store.multi)
        self.bulk_bar.visible = n > 0
        self._bulk_count.value = f"{n} selected"
        if n > 0:
            self._bulk_team_menu.items = self._team_menu_items(lambda team_id: self._bulk_add_to_team(team_id))
        for eid, card in self._cards.items():
            card.set_checked(eid in self.store.multi, selection_mode=n > 0)
        if self.view_mode == "table":
            self.table.update_from(self.store.visible(), sort=self.store.filters.sort, descending=self.store.filters.descending, selected_id=self.store.selected_id, checked=self.store.multi)

    def _render_entry(self, entry_id: UUID) -> None:
        entry = self.store.entry(entry_id)
        card = self._cards.get(entry_id)
        if entry is not None and card is not None:
            card.update_from(entry, selected=entry_id == self.store.selected_id, show_stats=self.show_stats, mega_capable=self.store.is_mega_capable(entry))
        if self.view_mode == "table":
            self.table.update_from(self.store.visible(), sort=self.store.filters.sort, descending=self.store.filters.descending, selected_id=self.store.selected_id)
        if entry_id == self.store.selected_id:
            self._render_detail()

    def _render_selection(self, entry_id: UUID | None) -> None:
        for eid, card in self._cards.items():
            card.set_selected(eid == entry_id)
        if self.view_mode == "table":
            self.table.update_from(self.store.visible(), sort=self.store.filters.sort, descending=self.store.filters.descending, selected_id=entry_id)
        self._render_detail()

    def _render_detail(self) -> None:
        selected = self.store.selected_id
        if selected is None:
            self.detail.clear()
            return
        detail = self.store.detail(selected)
        if detail is None:
            self.detail.clear()
            return
        self.detail.update_from(detail, self.store.selected_form_id)
        self.detail.set_team_options(self._team_options())
        if not detail.megas_checked:
            species = detail.entry.pokemon.species_name or detail.entry.pokemon.canonical_id
            self.ctx.run_in_background(lambda: self.store.fetch_megas(species), on_done=lambda _m: self._refresh_detail_if(selected), on_error=lambda _exc: None)

    def _refresh_detail_if(self, entry_id: UUID) -> None:
        if self.store.selected_id == entry_id:
            self._render_detail()
            self._update_self()

    # -- toolbar -> store ------------------------------------------------------------------------------

    def _on_filters(self, filters: BoxFilters) -> None:
        self.store.set_filters(filters)
        self._render()
        self._update_self()

    def _on_table_sort(self, key: SortKey, ascending: bool) -> None:
        self.toolbar._set(sort=key, descending=not ascending)

    def _filter_by_tag(self, tag: str) -> None:
        self.toolbar._set(tags=frozenset({tag.lower()}))

    def _set_columns(self, columns: list[str]) -> None:
        self.columns = [k for k in EXTRA_COLUMNS if k in set(columns)]
        self.ctx.prefs.set("box.columns", self.columns)
        self.toolbar.set_columns(self.columns)
        self.table.set_columns(self.columns)
        if self.view_mode == "table":
            self._render()
        self._update_self()

    def _set_view_mode(self, mode: str) -> None:
        self.view_mode = mode
        self.ctx.prefs.set("box.view_mode", mode)
        self._render()
        self._update_self()

    def _set_show_stats(self, show: bool) -> None:
        self.show_stats = show
        self.ctx.prefs.set("box.show_stats", show)
        self._render()
        self._update_self()

    # -- selection / detail actions -------------------------------------------------------------

    def _select(self, entry_id: UUID | None) -> None:
        self.store.select(entry_id)

    def _set_form(self, form_id: str) -> None:
        self.store.selected_form_id = form_id
        self._render_detail()
        self._update_self()

    def _set_favorite(self, entry_id: UUID, value: bool) -> None:
        self.store.set_favorite(entry_id, value)
        self.ctx.bus.emit(events.BOX_CHANGED, None)

    def _save_notes(self, entry_id: UUID, notes: str) -> None:
        self.store.save_notes(entry_id, notes)

    def _save_tags(self, entry_id: UUID, tags: list[str]) -> None:
        self.store.save_tags(entry_id, tags)
        self.toolbar.set_available_tags(self.store.all_tags())
        self._update_self()

    def _toggle_planned(self, entry_id: UUID, planned: bool) -> None:
        self.store.set_planned(entry_id, planned)
        self.ctx.bus.emit(events.BOX_CHANGED, None)
        self.ctx.toast("Marked as planned" if planned else "Marked as owned", "success")

    def _delete(self, entry_id: UUID) -> None:
        self.ctx.page.run_task(self._delete_flow, entry_id)

    async def _delete_flow(self, entry_id: UUID) -> None:
        detail = self.store.detail(entry_id)
        if detail is None:
            return
        name = detail.entry.pokemon.display_name
        if detail.teams:
            where = ", ".join(f"{team} (slot {slot})" for team, slot in detail.teams)
            ok = await self.ctx.confirm(f"Remove {name} from your box?", f"It will also be removed from: {where}.", confirm_label="Remove")
            if not ok:
                return
        removed = self.store.delete([entry_id])
        self.ctx.bus.emit(events.BOX_ENTRY_DELETED, entry_id)
        self.ctx.bus.emit(events.BOX_CHANGED, None)
        if removed and not detail.teams:
            self.ctx.toast(f"Removed {name}", "info", action="Undo", on_action=lambda: self._undo_delete(removed))
        else:
            self.ctx.toast(f"Removed {name}", "info")
        self._update_self()

    def _undo_delete(self, removed: list[BoxEntry]) -> None:
        self.store.restore(removed)
        self.ctx.bus.emit(events.BOX_CHANGED, None)
        self._update_self()

    # -- bulk actions ------------------------------------------------------------------------------------

    def _check(self, entry_id: UUID, checked: bool) -> None:
        self.store.toggle_multi(entry_id, checked)

    def _bulk_favorite(self, value: bool) -> None:
        ids = list(self.store.multi)
        if not ids:
            return
        self.store.bulk_update(ids, is_favorite=value)
        self.ctx.bus.emit(events.BOX_CHANGED, None)
        self.ctx.toast(f"{len(ids)} {'favourited' if value else 'unfavourited'}", "success")
        self._update_self()

    async def _bulk_tag(self) -> None:
        ids = list(self.store.multi)
        if not ids:
            return
        tag = await self.ctx.prompt_text(f"Tag {len(ids)} Pokémon", "Tag", submit_label="Add tag",
                                         validate=lambda t: None if t.strip() else "Enter a tag")
        if not tag:
            return
        self.store.bulk_update(ids, add_tags=[tag])
        self.toolbar.set_available_tags(self.store.all_tags())
        self.ctx.toast(f"Tagged {len(ids)} with #{tag.strip()}", "success")
        self._update_self()

    async def _bulk_delete(self) -> None:
        ids = list(self.store.multi)
        if not ids:
            return
        teams = self.store.teams_for(ids)
        affected = sorted({team for slots in teams.values() for team, _slot in slots})
        body = f"{len(ids)} Pokémon will be removed from your box."
        if affected:
            body += f" They will also leave these teams: {', '.join(affected)}."
        if not await self.ctx.confirm(f"Remove {len(ids)} Pokémon?", body, confirm_label="Remove"):
            return
        removed = self.store.delete(ids)
        self.store.clear_multi()
        for entry in removed:
            self.ctx.bus.emit(events.BOX_ENTRY_DELETED, entry.box_entry_id)
        self.ctx.bus.emit(events.BOX_CHANGED, None)
        if affected:
            self.ctx.toast(f"Removed {len(removed)} Pokémon", "info")
        else:
            self.ctx.toast(f"Removed {len(removed)} Pokémon", "info", action="Undo", on_action=lambda: self._undo_delete(removed))
        self._update_self()

    # -- add by name -----------------------------------------------------------------------------------

    def _suggest(self, text: str) -> None:
        catalogs = self.ctx.catalogs or self.store.catalogs
        matches = catalogs.suggest_species(text, limit=_MAX_SUGGESTIONS)
        self._suggestions.controls = [
            ft.Chip(label=ft.Text(r.display_name), leading=ft.Icon(ft.Icons.CATCHING_POKEMON, size=16), show_checkmark=False,
                    on_click=lambda _e, name=r.display_name: self._add(name))
            for r in matches
        ]
        self._suggestions.visible = bool(matches)
        self._safe_update(self._suggestions)

    def _add(self, name: str) -> None:
        name = name.strip()
        if not name:
            return
        self._suggestions.visible = False
        self._suggestions.controls = []
        self._add_banner.hide()
        before = {e.box_entry_id for e in self.store.entries}

        def done(entry: BoxEntry) -> None:
            self._add_field.value = ""
            self.store.load()
            if entry.box_entry_id in before:
                self._add_banner.show(f"{entry.pokemon.display_name} is already in your box", "info")
            else:
                self.ctx.toast(f"Added {entry.pokemon.display_name}", "success")
            self.store.select(entry.box_entry_id)
            self._update_self()

        def failed(exc: BaseException) -> None:
            self._add_banner.show(str(exc), "error")
            self._update_self()

        self.ctx.run_in_background(lambda: self.store.add_by_name(name), on_done=done, on_error=failed, busy=[self._add_field], spinner=self._add_spinner)

    def _export(self) -> None:
        """Export the selection if there is one, otherwise the visible (filtered) entries."""
        visible = self.store.visible()
        if self.store.multi:
            chosen = [e for e in visible if e.box_entry_id in self.store.multi] or [e for e in self.store.entries if e.box_entry_id in self.store.multi]
            scope = "selected"
        else:
            chosen = visible
            scope = "visible" if self.store.filters.active_labels() else "all"
        count = self.store.export_csv(chosen)
        total = len([e for e in self.store.entries if not e.is_planned])
        suffix = "" if scope == "all" or count == total else f" ({scope}, of {total})"
        self.ctx.toast(f"Exported {count} entries to pokemon_team_stats.csv{suffix}", "success")

    # -- add to team --------------------------------------------------------------------------------------

    def _team_options(self) -> list[tuple[UUID | None, str]]:
        options: list[tuple[UUID | None, str]] = [(t.team_id, f"{t.name} · {t.filled}/6") for t in self.store.list_teams()]
        options.append((None, "New team…"))
        return options

    def _team_menu_items(self, on_pick) -> list[ft.PopupMenuItem]:
        return [
            ft.PopupMenuItem(content=ft.Text(label), icon=ft.Icons.ADD if team_id is None else None, on_click=lambda _e, team_id=team_id: on_pick(team_id))
            for team_id, label in self._team_options()
        ]

    def _add_to_team(self, entry_id: UUID, team_id: UUID | None) -> None:
        self.ctx.page.run_task(self._add_flow, [entry_id], team_id)

    def _bulk_add_to_team(self, team_id: UUID | None) -> None:
        ids = [e.box_entry_id for e in self.store.visible() if e.box_entry_id in self.store.multi]
        self.ctx.page.run_task(self._add_flow, ids, team_id)

    async def _add_flow(self, ids: list[UUID], team_id: UUID | None) -> None:
        if not ids:
            return
        if team_id is None:
            name = await self.ctx.prompt_text("New team", "Team name", submit_label="Create", validate=lambda t: None if t.strip() else "Enter a name")
            if not name:
                return
            try:
                team_id = self.store.create_team(name)
            except ValueError as exc:
                self.ctx.toast(str(exc), "error")
                return
        result = self.store.add_to_team(team_id, ids)
        team_name = next((t.name for t in self.store.list_teams() if t.team_id == team_id), "team")
        bits = [f"Added {result.added} to {team_name}"]
        if result.already_on_team:
            bits.append(f"{result.already_on_team} already there")
        if result.no_room:
            bits.append(f"{result.no_room} left out (no free slot)")
        self.ctx.toast(" · ".join(bits), "success" if result.added else "warning", action="View", on_action=lambda: self.ctx.bus.emit(events.NAVIGATE, "team"))
        self.ctx.bus.emit(events.TEAMS_CHANGED, team_id)
        if self.store.multi:
            self.store.clear_multi()
        self._update_self()

    # -- events ---------------------------------------------------------------------------------------------

    def _on_catalogs_reloaded(self, kind: str) -> None:
        if kind == "megas":
            self.store.catalogs = self.ctx.catalogs or self.store.catalogs
            self._render()
            self._update_self()

    # -- helpers ----------------------------------------------------------------------------------------------

    def _focus_add(self) -> None:
        self._focus(self._add_field)

    def _focus(self, field: ft.TextField) -> None:
        if is_mounted(field):
            self.ctx.page.run_task(field.focus)

    # -- layout ----------------------------------------------------------------------------------------------

    def handle_resize(self, width: float, height: float) -> None:
        self._page_width = width
        self._relayout()

    def _relayout(self) -> None:
        """Keep card height constant: the grid derives tile height from tile width."""
        available = (
            self._page_width - Layout.RAIL_WIDTH - 1 - 2 * Space.PAGE_PADDING - Space.LG
            - (Layout.SIDE_PANEL_WIDTH if self.detail.visible else 0)
        )
        self.grid.child_aspect_ratio = grid_tile_aspect(
            available, max_extent=CARD_MAX_EXTENT, spacing=Space.GRID_GAP,
            tile_height=CARD_HEIGHT_WITH_STATS if self.show_stats else CARD_HEIGHT,
        )

    def _update_self(self) -> None:
        self._relayout()
        if is_mounted(self):
            self.update()

    @staticmethod
    def _safe_update(control: ft.Control) -> None:
        if is_mounted(control):
            control.update()


__all__ = ["BoxView", "Palette", "Radius"]

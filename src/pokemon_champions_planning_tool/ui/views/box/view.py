"""Box roster view: header with add-by-name, toolbar, card grid or table, detail panel."""

from __future__ import annotations

from uuid import UUID

import flet as ft

from ....domain.entities.box_entry import BoxEntry
from ... import events
from ...components import EmptyState, PageHeader
from ...components.banner import InlineBanner
from ...context import AppContext
from ...tasks import is_mounted
from ...theme import Layout, Palette, Radius, Space
from .card import CARD_MAX_EXTENT, PokemonCard
from .detail_panel import DetailPanel
from .filters import BoxFilters, SortKey
from .store import BoxStore
from .table import BoxTable
from .toolbar import BoxToolbar

_MAX_SUGGESTIONS = 6


class BoxView(ft.Row):
    def __init__(self, ctx: AppContext, store: BoxStore | None = None) -> None:
        super().__init__(spacing=0, expand=True, vertical_alignment=ft.CrossAxisAlignment.STRETCH)
        self.ctx = ctx
        self.store = store or BoxStore(ctx.catalogs)
        self.view_mode = "grid"
        self.show_stats = False
        self._cards: dict[UUID, PokemonCard] = {}

        # -- header: add by name -------------------------------------------------------------
        self._add_field = ft.TextField(
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
        self._export_button = ft.OutlinedButton("Export CSV", icon=ft.Icons.DOWNLOAD, on_click=lambda _e: self._export())
        self.header = PageHeader("Box", count=0, actions=[self._add_spinner, self._add_field, self._export_button])

        # -- toolbar ---------------------------------------------------------------------------
        self.toolbar = BoxToolbar(ctx.page, on_filters=self._on_filters, on_view_mode=self._set_view_mode, on_show_stats=self._set_show_stats)

        # -- content ---------------------------------------------------------------------------
        self.grid = ft.GridView(expand=True, max_extent=CARD_MAX_EXTENT, child_aspect_ratio=0.82, spacing=Space.GRID_GAP, run_spacing=Space.GRID_GAP)
        self.table = BoxTable(on_sort=self._on_table_sort, on_select=self._select)
        self.table.visible = False
        self._empty = EmptyState(ft.Icons.INVENTORY_2_OUTLINED, "Your box is empty", "Add a Pokémon by name to start planning.", action_label="Add a Pokémon", on_action=self._focus_add)
        self._empty.visible = False
        self._no_match = EmptyState(ft.Icons.SEARCH_OFF, "No Pokémon match", "Try fewer filters or a different search.", action_label="Clear filters", on_action=self.toolbar.clear)
        self._no_match.visible = False
        self._content = ft.Container(
            expand=True,
            content=ft.Column(expand=True, spacing=0, controls=[self.grid, self.table, ft.Row(alignment=ft.MainAxisAlignment.CENTER, controls=[self._empty, self._no_match])]),
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
        )

        left = ft.Column(
            expand=True,
            spacing=Space.MD,
            controls=[self.header, self._suggestions, self._add_banner, self.toolbar, self._content],
        )
        self.controls = [ft.Container(content=left, expand=True, padding=ft.Padding.only(right=Space.LG)), self.detail]

        self.store.subscribe(self._on_store_change)
        ctx.bus.on(events.CATALOGS_RELOADED, self._on_catalogs_reloaded)

    # -- lifecycle -------------------------------------------------------------------------------

    def ensure_loaded(self) -> None:
        if not self.store.entries:
            self.store.load()

    def handle_key(self, e) -> bool:
        """Shell hook for keys the shell itself does not consume."""
        if e.key == "Escape" and self.store.selected_id is not None:
            self._select(None)
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
            self.table.update_from(visible, sort=self.store.filters.sort, descending=self.store.filters.descending, selected_id=self.store.selected_id)
        else:
            self.table.visible = False
            self.grid.visible = not (empty or no_match)
            controls: list[ft.Control] = []
            for entry in visible:
                card = self._cards.get(entry.box_entry_id)
                if card is None:
                    card = PokemonCard(on_select=self._select, on_favorite=self._set_favorite, on_tag=self._filter_by_tag)
                    self._cards[entry.box_entry_id] = card
                card.update_from(entry, selected=entry.box_entry_id == self.store.selected_id, show_stats=self.show_stats, mega_capable=self.store.is_mega_capable(entry))
                controls.append(card)
            self.grid.controls = controls
            for stale in set(self._cards) - {e.box_entry_id for e in self.store.entries}:
                self._cards.pop(stale, None)
        self._render_detail()

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

    def _set_view_mode(self, mode: str) -> None:
        self.view_mode = mode
        self._render()
        self._update_self()

    def _set_show_stats(self, show: bool) -> None:
        self.show_stats = show
        self.grid.child_aspect_ratio = 0.62 if show else 0.82
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
        count = self.store.export_csv()
        self.ctx.toast(f"Exported {count} entries to pokemon_team_stats.csv", "success")

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

    def _update_self(self) -> None:
        if is_mounted(self):
            self.update()

    @staticmethod
    def _safe_update(control: ft.Control) -> None:
        if is_mounted(control):
            control.update()


__all__ = ["BoxView", "Palette", "Radius"]

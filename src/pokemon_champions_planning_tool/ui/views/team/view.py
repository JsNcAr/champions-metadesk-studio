"""Team builder view: header, six slot cards, summary panel, and the slot dialogs."""

from __future__ import annotations

from uuid import UUID

import flet as ft

from ....domain.entities.team_member import TeamMember
from ... import events
from ...components import EmptyState, PageHeader, SplitPane, StatusChip
from ...components.menu_button import menu_button
from ...context import AppContext
from ...tasks import grid_tile_aspect, grid_tile_width, is_mounted
from ...theme import Accent, DEFAULT_WINDOW_WIDTH, Layout, Palette, Space
from .dialogs.assign import AssignDialog
from .dialogs.export_dialog import ExportDialog
from .dialogs.import_dialog import ImportDialog
from .dialogs.item_picker import ItemPickerDialog
from .dialogs.compare import CompareDialog
from .dialogs.move_picker import MovePickerDialog
from .dialogs.spread import SpreadDialog
from .slot_card import SLOT_CARD_HEIGHT, SLOT_CARD_HEIGHT_NARROW, SLOT_CARD_MAX_EXTENT, SLOT_CARD_WRAP_WIDTH, SlotCallbacks, SlotCard
from .store import TeamStore
from .summary_panel import SummaryPanel

_STATUS_TONE = {"ok": "success", "warn": "warning", "error": "error", "info": "info"}
_STATUS_ICON = {"ok": ft.Icons.CHECK, "warn": ft.Icons.WARNING_AMBER_OUTLINED, "error": ft.Icons.ERROR_OUTLINE, "info": ft.Icons.INFO_OUTLINE}


class TeamView(ft.Column):
    def __init__(self, ctx: AppContext, store: TeamStore | None = None) -> None:
        super().__init__(spacing=Space.MD, expand=True)
        self.ctx = ctx
        self.store = store or TeamStore(ctx.catalogs)
        self.focused: int | None = None
        self._loaded = False

        # -- header ------------------------------------------------------------------------
        self._team_select = ft.Dropdown(
            options=[], width=260, dense=True, enable_filter=True, hint_text="Select a team",
            on_select=lambda e: self._select_team(e.control.value),
        )
        self._rename = ft.IconButton(icon=ft.Icons.EDIT_OUTLINED, icon_size=18, tooltip="Rename team", on_click=lambda _e: self.ctx.page.run_task(self._rename_team))
        self._health = ft.Row(spacing=Space.XS, tight=True, wrap=True)
        self._import_button = ft.FilledTonalButton("Import", icon=ft.Icons.DOWNLOAD, tooltip="Import a Showdown paste (Ctrl+I)", on_click=lambda _e: self._import())
        self._export_menu = ft.PopupMenuButton(
            content=menu_button("Export", ft.Icons.UPLOAD),
            tooltip="Export (Ctrl+E)",
            items=[
                ft.PopupMenuItem(content=ft.Text("Copy Showdown text"), icon=ft.Icons.CONTENT_COPY, on_click=lambda _e: self._copy_export()),
                ft.PopupMenuItem(content=ft.Text("Show export / publish…"), icon=ft.Icons.OPEN_IN_NEW, on_click=lambda _e: self._open_export()),
            ],
        )
        self._summary_toggle = ft.IconButton(icon=ft.Icons.VIEW_SIDEBAR_OUTLINED, icon_size=20, tooltip="Toggle summary panel", selected=True, on_click=lambda _e: self._toggle_summary())
        # Move legality: the picker hides moves outside the Champions learnset unless this is on.
        self.show_all_moves = bool(ctx.prefs.get("team.show_all_moves", False))
        self._show_all_moves_item = ft.PopupMenuItem(
            content=ft.Text("Show all moves (ignore legality)"), checked=self.show_all_moves,
            on_click=lambda _e: self._set_show_all_moves(not self.show_all_moves),
        )
        self._more = ft.PopupMenuButton(
            icon=ft.Icons.MORE_VERT,
            tooltip="Team actions",
            items=[
                ft.PopupMenuItem(content=ft.Text("New team"), icon=ft.Icons.ADD, on_click=lambda _e: self.ctx.page.run_task(self._new_team)),
                ft.PopupMenuItem(content=ft.Text("Duplicate team"), icon=ft.Icons.CONTENT_COPY, on_click=lambda _e: self.ctx.page.run_task(self._duplicate_team)),
                ft.PopupMenuItem(content=ft.Text("Delete team"), icon=ft.Icons.DELETE_OUTLINE, on_click=lambda _e: self.ctx.page.run_task(self._delete_team)),
                ft.PopupMenuItem(content=ft.Text("Compare teams…"), icon=ft.Icons.COMPARE_ARROWS, on_click=lambda _e: self._open_compare()),
                ft.PopupMenuItem(),
                self._show_all_moves_item,
            ],
        )
        self.header = PageHeader("Teams", icon=ft.Icons.GROUPS, accent=Accent.TEAMS, actions=[self._import_button, self._export_menu, self._summary_toggle, self._more])
        self._team_row = ft.Row(spacing=Space.SM, vertical_alignment=ft.CrossAxisAlignment.CENTER, wrap=True,
                                controls=[self._team_select, self._rename, self._health])

        # -- body -------------------------------------------------------------------------------
        callbacks = SlotCallbacks(
            on_assign=self._open_assign,
            on_clear=self._clear_slot,
            on_form=self.store.set_form,
            on_ability=self.store.set_ability,
            on_tera=self.store.set_tera,
            on_item=self._open_item_picker,
            on_remove_item=self._remove_item,
            on_move=self.store.set_move,
            on_move_pick=self._open_move_picker,
            on_notes=self.store.set_notes,
            on_spread=self._open_spread,
            on_swap=self._swap,
            on_focus=self._focus,
            on_calc=self._open_calc,
        )
        self.cards = [SlotCard(p, callbacks) for p in range(1, 7)]
        self._page_width = float(getattr(ctx.page, "width", None) or DEFAULT_WINDOW_WIDTH)
        self.grid = ft.GridView(expand=True, max_extent=SLOT_CARD_MAX_EXTENT, child_aspect_ratio=1.15, spacing=Space.GRID_GAP, run_spacing=Space.GRID_GAP, controls=list(self.cards))
        self.summary = SummaryPanel(on_close=self._toggle_summary, on_focus_slot=self._focus)
        self.summary.visible = bool(ctx.prefs.get("team.summary_visible", True))
        self._summary_toggle.selected = self.summary.visible
        self._empty = EmptyState(ft.Icons.GROUPS_OUTLINED, "No teams yet", "Create a team, or import one from a Showdown paste or the Meta explorer.",
                                 action_label="Create team", on_action=lambda: self.ctx.page.run_task(self._new_team),
                                 secondary_label="Import", on_secondary=self._import)
        self._empty.visible = False
        self._body = SplitPane(ft.Column(expand=True, controls=[self.grid, ft.Row(alignment=ft.MainAxisAlignment.CENTER, controls=[self._empty])]), self.summary, gap=Space.LG)
        self._narrow = False
        self.controls = [self.header, self._team_row, self._body]
        self._relayout()

        self.store.subscribe(self._on_store_change)
        ctx.bus.on(events.BOX_CHANGED, lambda _p: self._reload_if_loaded())
        ctx.bus.on(events.BOX_ENTRY_DELETED, lambda _p: self._reload_if_loaded())
        ctx.bus.on(events.TEAMS_CHANGED, self._on_teams_changed)
        ctx.bus.on(events.CATALOGS_RELOADED, self._on_catalogs_reloaded)
        ctx.bus.on(events.META_SYNCED, lambda _r: self.store.invalidate_partners())
        ctx.bus.on(events.IMPORT_REQUESTED, self._on_import_requested)

    # -- lifecycle --------------------------------------------------------------------------------

    def ensure_loaded(self) -> None:
        if not self._loaded:
            self._loaded = True
            self.store.load()

    def handle_key(self, e) -> bool:
        key = (e.key or "")
        if e.ctrl and key.lower() == "n":
            self.ctx.page.run_task(self._new_team)
            return True
        if e.ctrl and key.lower() == "i":
            self._import()
            return True
        if e.ctrl and key.lower() == "e":
            self._copy_export()
            return True
        if e.alt and key in ("Arrow Left", "Arrow Right", "ArrowLeft", "ArrowRight"):
            step = -1 if "Left" in key else 1
            current = self.focused or 1
            self._focus(((current - 1 + step) % 6) + 1)
            return True
        if key == "Escape" and self.focused is not None:
            self._focus(None)
            return True
        return False

    # -- store -> view ------------------------------------------------------------------------------

    def _on_store_change(self, change: tuple) -> None:
        kind = change[0]
        if kind == "teams":
            self._render_teams()
        elif kind == "all":
            for card, slot in zip(self.cards, self.store.slots):
                card.update_from(slot, focused=slot.position == self.focused)
            self._render_summary()
            self._load_partners()
        elif kind == "slot":
            position = change[1]
            self.cards[position - 1].update_from(self.store.slot(position), focused=position == self.focused)
            self._load_partners(position)
        elif kind == "summary":
            self._render_summary()
        self._update_self()

    def _render_teams(self) -> None:
        self._team_select.options = [ft.DropdownOption(key=str(t.team_id), text=f"{t.name}  ·  {t.filled}/6") for t in self.store.teams]
        self._team_select.value = str(self.store.active_team_id) if self.store.active_team_id else None
        has_team = self.store.active_team_id is not None
        self._empty.visible = not has_team
        self.grid.visible = has_team
        self._rename.visible = has_team
        self.header.set_caption(self.store.active_team_name if has_team else None)
        self.ctx.bus.emit(events.ACTIVE_TEAM, self.store.active_team_id)

    def _render_summary(self) -> None:
        summary = self.store.summary
        self._health.controls = [
            StatusChip(c.label, _STATUS_TONE[c.status], icon=_STATUS_ICON[c.status], tooltip=c.detail) for c in summary.checks
        ]
        self.summary.update_from(self.store.slots, summary, focused=self.focused)

    def _load_partners(self, position: int | None = None) -> None:
        if position is not None:
            if not self.store.slot(position).filled:
                self.cards[position - 1].set_partners([])
                return
            self.ctx.run_in_background(
                lambda p=position: self.store.partners(p),
                on_done=lambda partners, p=position: self.cards[p - 1].set_partners(partners),
                on_error=lambda _exc: None,
            )
            return

        for s in self.store.slots:
            if not s.filled:
                self.cards[s.position - 1].set_partners([])

        filled = [s.position for s in self.store.slots if s.filled]
        if not filled:
            return

        def _apply_batch(results: dict[int, list]):
            for p, partners in results.items():
                if 1 <= p <= len(self.cards):
                    self.cards[p - 1].set_partners(partners)

        self.ctx.run_in_background(
            lambda: self.store.partners_for_positions(filled),
            on_done=_apply_batch,
            on_error=lambda _exc: None,
        )

    # -- team actions ------------------------------------------------------------------------------------

    def _select_team(self, value: str | None) -> None:
        if value:
            self.store.select_team(UUID(value))

    async def _new_team(self) -> None:
        name = await self.ctx.prompt_text("New team", "Team name", submit_label="Create", validate=self._validate_name)
        if name:
            self.store.create_team(name)
            self.ctx.toast(f"Created {name}", "success")
            self._update_self()

    async def _rename_team(self) -> None:
        if self.store.active_team_id is None:
            return
        name = await self.ctx.prompt_text("Rename team", "Team name", value=self.store.active_team_name, submit_label="Rename", validate=self._validate_name)
        if name and name != self.store.active_team_name:
            self.store.rename_team(name)
            self._update_self()

    async def _duplicate_team(self) -> None:
        if self.store.active_team_id is None:
            return
        name = await self.ctx.prompt_text("Duplicate team", "New team name", value=f"{self.store.active_team_name} copy", submit_label="Duplicate", validate=self._validate_name)
        if name:
            self.store.duplicate_team(name)
            self.ctx.toast(f"Duplicated as {name}", "success")
            self._update_self()

    async def _delete_team(self) -> None:
        if self.store.active_team_id is None:
            return
        name = self.store.active_team_name
        if await self.ctx.confirm(f"Delete team “{name}”?", "Its six slots and their spreads are deleted. Box entries are kept.", confirm_label="Delete team"):
            self.store.delete_team()
            self.ctx.toast(f"Deleted {name}", "info")
            self._update_self()

    def _validate_name(self, text: str) -> str | None:
        if not text.strip():
            return "Enter a name"
        if any(t.name.lower() == text.strip().lower() and t.team_id != self.store.active_team_id for t in self.store.teams):
            return "A team with this name already exists"
        return None

    def _on_teams_changed(self, team_id) -> None:
        """Another component (the legacy import dialog) changed teams."""
        self._loaded = True
        self.store.load(team_id if isinstance(team_id, UUID) else None)

    def _reload_if_loaded(self) -> None:
        if self._loaded:
            self.store.load(self.store.active_team_id)

    def _on_catalogs_reloaded(self, kind: str) -> None:
        if kind == "tournaments":
            self.store.invalidate_partners()
            if self._loaded:
                self._load_partners()
            return
        # "species" and "champions" feed the same slot cards: base stats and forms come
        # from the species catalogue, legality from the Champions Pokédex.
        if kind in ("items", "megas", "moves", "species", "champions"):
            self.store.catalogs = self.ctx.catalogs or self.store.catalogs
            self._reload_if_loaded()

    # -- slot actions -----------------------------------------------------------------------------------------

    def _focus(self, position: int | None) -> None:
        self.focused = position
        for card in self.cards:
            card.set_focused(card.position == position)
        self.summary.update_from(self.store.slots, self.store.summary, focused=position)
        self._update_self()

    def _open_assign(self, position: int) -> None:
        if self.store.active_team_id is None:
            self.ctx.toast("Create a team first", "info")
            return
        entries = self.store.box_choices(include_planned=True)

        def pick(box_entry_id: UUID) -> None:
            self.ctx.page.pop_dialog()
            self.store.assign(position, box_entry_id)
            self.ctx.toast(f"Assigned to slot {position}", "success")

        self.ctx.page.show_dialog(AssignDialog(slot=position, entries=entries, assigned=self.store.assigned_entry_ids(), on_pick=pick, on_close=self.ctx.page.pop_dialog))

    def _clear_slot(self, position: int) -> None:
        removed = self.store.clear_slot(position)
        if removed is not None:
            self.ctx.toast(f"Cleared slot {position}", "info", action="Undo", on_action=lambda: self._restore(removed))

    def _restore(self, member: TeamMember) -> None:
        self.store.restore_slot(member)
        self._update_self()

    def _swap(self, a: int, b: int) -> None:
        if self.store.swap(a, b):
            self._focus(b)

    def _open_compare(self) -> None:
        if self.store.active_team_id is None:
            self.ctx.toast("Create a team first", "info")
            return
        page = self.ctx.page
        page.show_dialog(CompareDialog(self.store, on_close=page.pop_dialog))

    def _set_show_all_moves(self, value: bool) -> None:
        self.show_all_moves = value
        self.ctx.prefs.set("team.show_all_moves", value)
        self._show_all_moves_item.checked = value
        if is_mounted(self._show_all_moves_item):
            self._show_all_moves_item.update()

    def _open_move_picker(self, position: int, index: int) -> None:
        slot = self.store.slot(position)
        if slot.entry is None:
            return
        options = self.store.move_options(position)
        current = slot.moves[index].name if (index < len(slot.moves) and slot.moves[index] is not None) else None
        page = self.ctx.page

        def pick(name: str | None) -> None:
            page.pop_dialog()
            self.store.set_move(position, index, name or "")
            mon = slot.entry.pokemon.display_name if slot.entry else "Pokémon"
            if name:
                self.ctx.toast(f"{mon} learned {name}", "success")
            else:
                self.ctx.toast(f"Cleared move {index + 1} on {mon}", "info")

        dialog = MovePickerDialog(
            species_label=slot.entry.pokemon.display_name,
            options=options,
            current=current,
            show_all=self.show_all_moves,
            on_pick=pick,
            on_close=page.pop_dialog,
            on_show_all=self._set_show_all_moves,
        )
        page.show_dialog(dialog)

    def _open_calc(self, position: int) -> None:
        """Send this slot to the damage calculator as the attacker."""
        from ..calc.state import CalcRequest, pokemon_from_slot

        slot = self.store.slot(position)
        if not slot.filled:
            return
        pokemon = pokemon_from_slot(slot, self.store.catalogs, source=f"{self.store.active_team_name or 'Team'} · slot {position}")
        if pokemon is None:
            self.ctx.toast("This slot cannot be calculated", "warning")
            return
        self.ctx.bus.emit(events.CALC_REQUESTED, CalcRequest(attacker=pokemon))

    def _remove_item(self, position: int) -> None:
        slot = self.store.slot(position)
        if not slot.filled:
            return
        name = slot.entry.pokemon.display_name if slot.entry else "Pokémon"
        self.store.set_item(position, None)
        self.ctx.toast(f"Removed item from {name}", "info")

    def _open_item_picker(self, position: int) -> None:
        slot = self.store.slot(position)
        if not slot.filled:
            return

        def pick(item_id: str | None) -> None:
            self.ctx.page.pop_dialog()
            item = self.store.set_item(position, item_id)
            self.ctx.toast(f"{slot.entry.pokemon.display_name} holds {item.display_name}" if item else "Item removed", "success")

        self.ctx.page.show_dialog(ItemPickerDialog(
            catalogs=self.store.catalogs, species_name=slot.species_name,
            current_item_id=slot.item.canonical_id if slot.item else None,
            on_pick=pick, on_close=self.ctx.page.pop_dialog,
        ))

    def _open_spread(self, position: int) -> None:
        slot = self.store.slot(position)
        if not slot.filled or slot.base_stats is None:
            return

        def save(nature: str, points: dict[str, int]) -> list[str]:
            problems = self.store.save_spread(position, nature=nature, points=points)
            if not problems:
                self.ctx.page.pop_dialog()
                self.ctx.toast("Spread saved", "success")
            return problems

        self.ctx.page.show_dialog(SpreadDialog(
            title=slot.entry.pokemon.display_name, base_stats=slot.base_stats,
            nature=slot.member.nature, points=dict(slot.member.points),
            on_save=save, on_close=self.ctx.page.pop_dialog,
        ))

    # -- import / export ----------------------------------------------------------------------------------------

    def _import(self) -> None:
        self.open_import("", "")

    def _on_import_requested(self, payload) -> None:
        text, title = payload if isinstance(payload, tuple) else ("", "")
        self.ensure_loaded()
        self.open_import(text or "", title or "")

    def open_import(self, text: str, title: str) -> None:
        def done(team_id: UUID) -> None:
            self.ctx.bus.emit(events.NAVIGATE, "team")
            self._focus(None)
            self._update_self()

        self.ctx.page.show_dialog(ImportDialog(self.ctx, self.store, initial_text=text, initial_title=title, on_done=done))

    def _copy_export(self) -> None:
        if self.store.active_team_id is None:
            return
        self.ctx.copy_to_clipboard(self.store.export_text())
        self.ctx.toast("Showdown text copied", "success")

    def _open_export(self) -> None:
        if self.store.active_team_id is None:
            self.ctx.toast("No team to export", "info")
            return
        self.ctx.page.show_dialog(ExportDialog(self.ctx, self.store))

    # -- helpers ---------------------------------------------------------------------------------------------------

    def _toggle_summary(self) -> None:
        self.summary.visible = not self.summary.visible
        self._summary_toggle.selected = self.summary.visible
        self.ctx.prefs.set("team.summary_visible", self.summary.visible)
        self._relayout()
        self._update_self()

    def handle_resize(self, width: float, height: float) -> None:
        self._page_width = width
        self._narrow = width < Layout.BREAKPOINT_NARROW
        self.summary.width = Layout.SIDE_PANEL_WIDTH_COMPACT if width < Layout.BREAKPOINT_COMPACT else Layout.SIDE_PANEL_WIDTH
        self._body.set_narrow(self._narrow)
        self._relayout()

    def _relayout(self) -> None:
        """Slot cards keep a fixed height whatever the window or summary panel does."""
        compact = self._page_width < Layout.BREAKPOINT_COMPACT
        rail = Layout.RAIL_WIDTH_COMPACT if compact else Layout.RAIL_WIDTH
        padding = Space.LG if compact else Space.PAGE_PADDING
        panel = 0 if (self._narrow or not self.summary.visible) else (self.summary.width or Layout.SIDE_PANEL_WIDTH) + Space.LG
        available = self._page_width - rail - 1 - 2 * padding - panel
        tile_width = grid_tile_width(available, max_extent=SLOT_CARD_MAX_EXTENT, spacing=Space.GRID_GAP)
        height = SLOT_CARD_HEIGHT_NARROW if tile_width < SLOT_CARD_WRAP_WIDTH else SLOT_CARD_HEIGHT
        self.grid.child_aspect_ratio = grid_tile_aspect(available, max_extent=SLOT_CARD_MAX_EXTENT, spacing=Space.GRID_GAP, tile_height=height)

    def _update_self(self) -> None:
        self._relayout()
        if is_mounted(self):
            self.update()


__all__ = ["TeamView", "Layout", "Palette"]

"""Team builder view: the team bar, six compact slot cards (one expands in place into the
editor), the analysis panel, and the slot dialogs."""

from __future__ import annotations

from uuid import UUID

import flet as ft

from ....domain.entities.team_member import TeamMember
from ....domain.formats import Mechanic
from ....domain.team_roles import team_roles
from ... import events
from ...components import PageHeader, Sprite, SplitPane
from ...components.menu_button import menu_button
from ...context import AppContext
from ...format import shortcut
from ...tasks import Debouncer, is_mounted
from ...theme import Accent, Layout, Palette, Radius, Space
from .compact_card import CompactCallbacks, CompactSlot
from .dialogs.assign import AssignDialog
from .dialogs.compare import CompareDialog
from .dialogs.export_dialog import ExportDialog
from .dialogs.import_dialog import ImportDialog
from .dialogs.item_picker import ItemPickerDialog
from .dialogs.move_picker import MovePickerDialog
from .library import LibraryCallbacks, TeamLibrary
from .slot_card import SlotCallbacks, SlotCard
from .status import health_summary
from .store import TeamStore
from .summary_panel import SummaryPanel

COMPACT_COL = {"xs": 12, "md": 6, "xl": 4}     # three across wide, two beside the panel, one narrow
SPREAD_SAVE_MS = 400
_TONE_COLOURS = {
    "success": (Palette.SUCCESS_CONTAINER, Palette.ON_SUCCESS_CONTAINER), "warning": (Palette.WARNING_CONTAINER, Palette.ON_WARNING_CONTAINER),
    "error": (Palette.ERROR_CONTAINER, Palette.ON_ERROR_CONTAINER), "info": (Palette.INFO_CONTAINER, Palette.ON_INFO_CONTAINER),
}
_ARROWS = ("Arrow Left", "Arrow Right", "ArrowLeft", "ArrowRight")


class TeamView(ft.Column):
    def __init__(self, ctx: AppContext, store: TeamStore | None = None) -> None:
        super().__init__(spacing=Space.MD, expand=True)
        self.ctx = ctx
        self.store = store or TeamStore(ctx.catalogs, formats=ctx.formats)
        self.focused: int | None = None
        self.selected: int | None = None     # the slot shown in the editor pane under the grid
        self._loaded = False
        self._spread_later: dict[int, Debouncer] = {}
        self._pending_spread: dict[int, tuple[str, dict[str, int]]] = {}

        # -- header ------------------------------------------------------------------------
        # The team switcher: the active team's six sprites and name; opens the library.
        self._switch_sprites = ft.Row(spacing=2, tight=True)
        self._switch_name = ft.Text("", theme_style=ft.TextThemeStyle.TITLE_SMALL, color=Palette.ON_SURFACE, max_lines=1, overflow=ft.TextOverflow.ELLIPSIS)
        self._switch_count = ft.Text("", theme_style=ft.TextThemeStyle.LABEL_LARGE, color=Palette.ON_SURFACE_VARIANT)
        self._switcher = ft.Container(
            content=ft.Row(spacing=Space.SM, tight=True, vertical_alignment=ft.CrossAxisAlignment.CENTER, controls=[
                self._switch_sprites, self._switch_name, self._switch_count, ft.Icon(ft.Icons.UNFOLD_MORE, size=18, color=Palette.ON_SURFACE_VARIANT),
            ]),
            padding=ft.Padding.symmetric(horizontal=Space.SM, vertical=Space.XS), border_radius=Radius.MD, bgcolor=Palette.SURFACE_2,
            border=ft.Border.all(1, Palette.OUTLINE_VARIANT), ink=True, tooltip=shortcut("All teams (Ctrl+L)"), on_click=lambda _e: self.open_library(),
        )
        # The format the team is built for: its mechanics decide which controls the cards show.
        self._format_label = ft.Text("", theme_style=ft.TextThemeStyle.LABEL_LARGE, color=Palette.ON_TERTIARY_CONTAINER, max_lines=1)
        self._format_menu = ft.PopupMenuButton(
            tooltip="The format this team is built for",
            content=ft.Container(
                content=ft.Row(spacing=Space.XS, tight=True, vertical_alignment=ft.CrossAxisAlignment.CENTER, controls=[
                    ft.Icon(ft.Icons.RULE, size=16, color=Palette.ON_TERTIARY_CONTAINER), self._format_label,
                    ft.Icon(ft.Icons.ARROW_DROP_DOWN, size=18, color=Palette.ON_TERTIARY_CONTAINER),
                ]),
                bgcolor=Palette.TERTIARY_CONTAINER, border_radius=Radius.PILL, padding=ft.Padding.only(left=Space.SM, right=Space.XS, top=4, bottom=4),
            ),
            items=[],
        )
        # One chip for the whole team's health; the list is in the panel's Overview tab.
        self._health_icon = ft.Icon(ft.Icons.CHECK, size=16)
        self._health_label = ft.Text("", theme_style=ft.TextThemeStyle.LABEL_LARGE)
        self._health = ft.Container(
            content=ft.Row(spacing=Space.XS, tight=True, vertical_alignment=ft.CrossAxisAlignment.CENTER, controls=[self._health_icon, self._health_label]),
            border_radius=Radius.PILL, padding=ft.Padding.symmetric(horizontal=Space.SM, vertical=4), ink=True,
            on_click=lambda _e: self._show_analysis("overview"),
        )
        self._import_button = ft.FilledTonalButton("Import", icon=ft.Icons.DOWNLOAD, tooltip=shortcut("Import a Showdown paste (Ctrl+I)"), on_click=lambda _e: self._import())
        self._export_menu = ft.PopupMenuButton(
            content=menu_button("Export", ft.Icons.UPLOAD),
            tooltip=shortcut("Export (Ctrl+E)"),
            items=[
                ft.PopupMenuItem(content=ft.Text("Copy Showdown text"), icon=ft.Icons.CONTENT_COPY, on_click=lambda _e: self._copy_export()),
                ft.PopupMenuItem(content=ft.Text("Show export / publish…"), icon=ft.Icons.OPEN_IN_NEW, on_click=lambda _e: self._open_export()),
            ],
        )
        self._summary_toggle = ft.IconButton(icon=ft.Icons.VIEW_SIDEBAR_OUTLINED, icon_size=20, tooltip="Team analysis", selected=True, on_click=lambda _e: self._toggle_summary())
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
                ft.PopupMenuItem(content=ft.Text("All teams…"), icon=ft.Icons.GRID_VIEW, on_click=lambda _e: self.open_library()),
                ft.PopupMenuItem(content=ft.Text("New team"), icon=ft.Icons.ADD, on_click=lambda _e: self.ctx.page.run_task(self._new_team)),
                ft.PopupMenuItem(content=ft.Text("Rename team…"), icon=ft.Icons.EDIT_OUTLINED, on_click=lambda _e: self.ctx.page.run_task(self._rename_team)),
                ft.PopupMenuItem(content=ft.Text("Duplicate team…"), icon=ft.Icons.CONTENT_COPY, on_click=lambda _e: self.ctx.page.run_task(self._duplicate_team)),
                ft.PopupMenuItem(content=ft.Text("Compare teams…"), icon=ft.Icons.COMPARE_ARROWS, on_click=lambda _e: self._open_compare()),
                ft.PopupMenuItem(content=ft.Text("Delete team…"), icon=ft.Icons.DELETE_OUTLINE, on_click=lambda _e: self.ctx.page.run_task(self._delete_team)),
                ft.PopupMenuItem(),
                self._show_all_moves_item,
            ],
        )
        self.header = PageHeader("Teams", icon=ft.Icons.GROUPS, accent=Accent.TEAMS, actions=[self._import_button, self._export_menu, self._summary_toggle, self._more])
        self._team_row = ft.Row(spacing=Space.SM, vertical_alignment=ft.CrossAxisAlignment.CENTER,
                                controls=[self._switcher, self._format_menu, self._health])

        # -- body -------------------------------------------------------------------------------
        callbacks = SlotCallbacks(
            on_assign=self._open_assign,
            on_clear=self._clear_slot,
            on_form=self.store.set_form,
            on_ability=self.store.set_ability,
            on_tera=self.store.set_tera,
            on_item=self._open_item_picker,
            on_remove_item=self._remove_item,
            on_move_pick=self._open_move_picker,
            on_clear_move=self._clear_move,
            on_notes=self.store.set_notes,
            on_spread_change=self._spread_changed,
            on_swap=self._swap,
            on_focus=self._focus,
            on_collapse=lambda _p: self._set_selected(None),
            on_step=self._step,
            on_apply_build=self._apply_build,
            on_partner=self._open_partner,
            on_calc=self._open_calc,
        )
        compact_callbacks = CompactCallbacks(on_expand=self._toggle_selected, on_assign=self._open_assign, on_swap=self._swap,
                                             on_clear=self._clear_slot, on_calc=self._open_calc)
        # ``cards`` are the editors (the selected one sits in the pane); ``compacts`` stay in the grid.
        self.cards = [SlotCard(p, callbacks) for p in range(1, 7)]
        self.compacts = [CompactSlot(p, compact_callbacks) for p in range(1, 7)]
        self._cells = [ft.Container(col=COMPACT_COL, content=c) for c in self.compacts]
        self.grid = ft.ResponsiveRow(spacing=Space.GRID_GAP, run_spacing=Space.GRID_GAP, vertical_alignment=ft.CrossAxisAlignment.START, controls=list(self._cells))
        self.summary = SummaryPanel(on_close=self._toggle_summary, on_focus_slot=lambda p: self._set_selected(p))
        self.summary.visible = bool(ctx.prefs.get("team.summary_visible", True))
        self._summary_toggle.selected = self.summary.visible
        # The editor pane under the grid: the cards never move, the pane shows the selected slot.
        self._pane = ft.Container(visible=False)
        self._main = ft.Column(expand=True, scroll=ft.ScrollMode.AUTO, spacing=Space.MD, controls=[self.grid, self._pane])
        self._body = SplitPane(self._main, self.summary, gap=Space.LG)
        self._narrow = False
        # The library of every team; with no teams it is the view's empty state.
        self.mode = "editor"
        self._library_loading = False
        self._library_auto = False
        self.library = TeamLibrary(LibraryCallbacks(
            on_open=self._open_team, on_new=lambda: self.ctx.page.run_task(self._new_team), on_import=self._import,
            on_rename=lambda tid: self._act_on(tid, self._rename_team), on_duplicate=lambda tid: self._act_on(tid, self._duplicate_team),
            on_compare=self._compare_with, on_copy=self._copy_team, on_delete=lambda tid: self._act_on(tid, self._delete_team),
            on_back=self.close_library, format_label=self._format_short,
        ))
        self.controls = [self.header, self._team_row, self._body]

        self.store.subscribe(self._on_store_change)
        ctx.bus.on(events.BOX_CHANGED, lambda _p: self._reload_if_loaded())
        ctx.bus.on(events.BOX_ENTRY_DELETED, lambda _p: self._reload_if_loaded())
        ctx.bus.on(events.TEAMS_CHANGED, self._on_teams_changed)
        ctx.bus.on(events.CATALOGS_RELOADED, self._on_catalogs_reloaded)
        ctx.bus.on(events.META_SYNCED, lambda _r: self.store.invalidate_partners())
        ctx.bus.on(events.IMPORT_REQUESTED, self._on_import_requested)
        ctx.bus.on(events.FORMAT_CHANGED, lambda _p: self.store.refresh_format() if self._loaded else None)

    # -- lifecycle --------------------------------------------------------------------------------

    def did_mount(self) -> None:
        page = self.ctx.page
        self._spread_later = {p: Debouncer(page, SPREAD_SAVE_MS, lambda _v, p=p: self._save_spread(p), quiet_event=False) for p in range(1, 7)}
        self.ctx.on_shutdown(self._flush_spreads)

    def will_unmount(self) -> None:
        self._flush_spreads()
        self._spread_later = {}

    def _flush_spreads(self) -> None:
        for position in list(self._pending_spread):
            self._save_spread(position)

    def ensure_loaded(self) -> None:
        if not self._loaded:
            self._loaded = True
            self.store.load()

    def handle_key(self, e) -> bool:
        key = (e.key or "")
        if e.ctrl and key.lower() == "l":
            if self.mode == "library":
                self.close_library()
            else:
                self.open_library()
            return True
        if e.ctrl and key.lower() == "n":
            self.ctx.page.run_task(self._new_team)
            return True
        if e.ctrl and key.lower() == "i":
            self._import()
            return True
        if e.ctrl and key.lower() == "e":
            self._copy_export()
            return True
        if e.alt and key in _ARROWS:
            step = -1 if "Left" in key else 1
            current = self.selected or self.focused or 1
            if e.shift:
                self._swap(current, current + step)          # move the card itself
            elif self.selected is not None:
                self._step(self.selected, step)              # the pane follows the selection
            else:
                self._focus(((current - 1 + step) % 6) + 1)
            return True
        if key == "Enter" and not (e.ctrl or e.alt or e.shift) and self.focused is not None and self.selected != self.focused:
            self._set_selected(self.focused)
            return True
        if key == "Escape" and self.mode == "library" and self.store.active_team_id is not None:
            self.close_library()
            return True
        if key == "Escape":
            if self.selected is not None:
                self._set_selected(None)
                return True
            if self.focused is not None:
                self._focus(None)
                return True
            if self.summary.visible:
                self._toggle_summary()
                return True
        return False

    # -- store -> view ------------------------------------------------------------------------------

    def _on_store_change(self, change: tuple) -> None:
        kind = change[0]
        fmt = self.store.active_format
        if kind == "teams":
            self._render_teams()
        elif kind == "all":
            for position in range(1, 7):
                self._render_slot(position, fmt)
            self._render_format()
            self._render_switcher()
            self._render_summary()
            self._load_partners()
        elif kind == "slot":
            position = change[1]
            self._render_slot(position, fmt)
            self._render_switcher()
            self._load_partners(position)
            self._update_cell(position)
            if is_mounted(self._switcher):
                self._switcher.update()
            return
        elif kind == "summary":
            self._render_summary()
        self._update_self()

    def _render_slot(self, position: int, fmt) -> None:
        slot = self.store.slot(position)
        self.compacts[position - 1].update_from(slot, focused=position == self.focused)
        self.cards[position - 1].update_from(slot, focused=position == self.focused, fmt=fmt)
        if self.selected == position and not slot.filled:
            self._set_selected(None)
        elif self.selected is not None:
            self._update_slot_info()

    def _update_cell(self, position: int) -> None:
        """A one-slot edit sends that slot's card (and its editor, when open) and the health chip."""
        cell = self._cells[position - 1]
        pane = [self._pane] if self.selected == position else []
        for control in (cell, *pane, self._health, self.summary):
            if is_mounted(control):
                control.update()

    def _render_teams(self) -> None:
        has_team = self.store.active_team_id is not None
        self._switch_name.value = self.store.active_team_name
        self._render_format()
        self.ctx.bus.emit(events.ACTIVE_TEAM, self.store.active_team_id)
        if not has_team:
            self.open_library(auto=True)    # no team to edit: the library is the empty state
        elif self.mode == "library" and self._library_auto:
            self.close_library()            # the first team arrived (created, imported, added from the Box)
        elif self.mode == "library":
            self._refresh_library()
        else:
            self.header.set_caption(self.store.active_team_name)

    def _render_switcher(self) -> None:
        slots = self.store.slots
        self._switch_sprites.controls = [
            Sprite(s.form.sprite_url, size=24) if s.filled and s.form is not None else
            ft.Container(width=24, height=24, border_radius=Radius.PILL, border=ft.Border.all(1, Palette.OUTLINE_VARIANT))
            for s in slots
        ]
        self._switch_count.value = f"{sum(1 for s in slots if s.filled)}/6"

    def _render_format(self) -> None:
        own = self.store.active_team_format_id
        fmt = self.store.active_format
        default = self.store.formats.default()
        self._format_label.value = f"{fmt.name} · {fmt.mechanics_label}"
        self._format_menu.tooltip = ("This team follows the default format (Settings)" if own is None else "This team's own format") + f"\n{fmt.description}".rstrip()
        items = [ft.PopupMenuItem(content=ft.Text(f"Default format ({default.name})"), checked=own is None,
                                  on_click=lambda _e: self._set_format(None)), ft.PopupMenuItem()]
        items += [ft.PopupMenuItem(content=ft.Text(f"{f.name} · {f.mechanics_label}"), checked=own == f.format_id,
                                   on_click=lambda _e, fid=f.format_id: self._set_format(fid)) for f in self.store.formats.all()]
        items += [ft.PopupMenuItem(), ft.PopupMenuItem(content=ft.Text("Manage formats in Settings…"), icon=ft.Icons.SETTINGS_OUTLINED,
                                                        on_click=lambda _e: self.ctx.bus.emit(events.NAVIGATE, "settings"))]
        self._format_menu.items = items

    def _set_format(self, format_id: str | None) -> None:
        if format_id != self.store.active_team_format_id:
            self.store.set_format(format_id)
            self.ctx.toast(f"Built for {self.store.active_format.name}", "success")

    def _render_summary(self) -> None:
        summary = self.store.summary
        label, tone = health_summary(summary.checks)
        bg, fg = _TONE_COLOURS[tone]
        self._health.bgcolor = bg
        self._health_label.value = label
        self._health_label.color = self._health_icon.color = fg
        self._health_icon.icon = {"success": ft.Icons.CHECK, "warning": ft.Icons.WARNING_AMBER_OUTLINED, "error": ft.Icons.ERROR_OUTLINE, "info": ft.Icons.INFO_OUTLINE}[tone]
        self._health.tooltip = "\n".join(f"{c.label}: {c.detail}" for c in summary.checks if c.status != "ok") or "Every check passes"
        fmt = self.store.active_format
        roles = team_roles(self.store.role_members(), doubles=fmt.game_type == "doubles")
        self.summary.update_from(self.store.slots, summary, focused=self.focused, roles=roles)

    def _load_partners(self, position: int | None = None) -> None:
        if position is not None:
            if not self.store.slot(position).filled:
                self.cards[position - 1].set_partners([])
                return
            self.ctx.run_in_background(
                lambda p=position: self.store.partners(p, limit=5),
                on_done=lambda partners, p=position: self.cards[p - 1].set_partners(partners),
                on_error=lambda exc: print(f"⚠️ Partners failed: {exc}"),
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
            on_error=lambda exc: print(f"⚠️ Partners failed: {exc}"),
        )

    # -- expanding and focus ----------------------------------------------------------------------

    def _toggle_selected(self, position: int) -> None:
        """A card click: open its editor, or close it when it is already open."""
        self._set_selected(None if position == self.selected else position)

    def _set_selected(self, position: int | None) -> None:
        """Show a slot's editor in the pane under the grid. The cards keep their places:
        they only condense while the pane is open, and the selected one is marked."""
        if position is not None and not self.store.slot(position).filled:
            return          # nothing to edit: an empty slot is assigned, not selected
        if position == self.selected:
            return
        self.selected = position
        self._pane.content = self.cards[position - 1] if position is not None else None
        self._pane.visible = position is not None
        for compact in self.compacts:
            compact.set_condensed(position is not None)
            compact.set_selected(compact.position == position)
        if position is not None:
            self.focused = position
            self._update_slot_info()
            self._load_build(position)
        if is_mounted(self._main):
            self._main.update()

    def _filled_positions(self) -> list[int]:
        return [s.position for s in self.store.slots if s.filled]

    def _update_slot_info(self) -> None:
        filled = self._filled_positions()
        if self.selected in filled:
            self.cards[self.selected - 1].set_slot_info(filled.index(self.selected) + 1, len(filled))

    def _step(self, position: int, delta: int) -> None:
        """‹ ›: the previous or next filled slot, wrapping around."""
        filled = self._filled_positions()
        if position not in filled or len(filled) < 2:
            return
        self._set_selected(filled[(filled.index(position) + delta) % len(filled)])

    def _load_build(self, position: int) -> None:
        """The species' most used tournament set, for the pane's "Tournament set" menu."""
        card = self.cards[position - 1]
        card.set_build(None)

        def done(build) -> None:
            if self.selected == position:
                card.set_build(build)

        self.ctx.run_in_background(lambda: self.store.tournament_build(position), on_done=done, on_error=lambda _e: None)

    def _apply_build(self, position: int, moves_only: bool) -> None:
        build = self.store.tournament_build(position)       # cached by the menu's load
        if build is None:
            return
        previous = self.store.apply_build(position, build, moves_only=moves_only)
        if previous is not None:
            what = "moves" if moves_only else "set"
            self.ctx.toast(f"Applied the tournament {what}", "success", action="Undo", on_action=lambda: self._restore(previous))

    def _focus(self, position: int | None) -> None:
        self.focused = position
        for compact in self.compacts:
            compact.set_focused(compact.position == position)
        self.summary.update_from(self.store.slots, self.store.summary, focused=position)
        self._update_self()

    # -- library -------------------------------------------------------------------------------------

    def open_library(self, *, auto: bool = False) -> None:
        """Show every team. ``auto``: opened because there is no team, so the editor comes
        back by itself once one exists."""
        self._library_auto = auto
        if self.mode != "library":
            self.mode = "library"
            self._set_selected(None)
            self.controls = [self.header, self.library]
            self.header.set_caption("All teams")
            for control in (self._import_button, self._export_menu, self._summary_toggle):
                control.visible = False
        self._refresh_library()
        self._update_self()

    def close_library(self) -> None:
        if self.mode == "editor" or self.store.active_team_id is None:
            return
        self.mode = "editor"
        self.controls = [self.header, self._team_row, self._body]
        self.header.set_caption(self.store.active_team_name)
        for control in (self._import_button, self._export_menu, self._summary_toggle):
            control.visible = True
        self._update_self()

    def _refresh_library(self) -> None:
        """Read the library rows off the UI loop; a second request while one runs is dropped
        (the running one reads the latest data when it starts)."""
        if self._library_loading:
            return
        self._library_loading = True
        self.library.set_loading(True)

        def done(rows) -> None:
            self._library_loading = False
            self.library.set_rows(rows, self.store.active_team_id)

        def failed(exc: BaseException) -> None:
            self._library_loading = False
            self.library.set_rows([], self.store.active_team_id)
            self.ctx.toast(f"Could not read the teams: {exc}", "error")

        self.ctx.run_in_background(self.store.library_rows, on_done=done, on_error=failed)

    def _open_team(self, team_id: UUID) -> None:
        self.store.select_team(team_id)
        self.close_library()

    def _act_on(self, team_id: UUID, action) -> None:
        """Run a team-menu action (rename, duplicate, delete) on a team picked in the library."""
        self.store.select_team(team_id)
        self.ctx.page.run_task(action)

    def _compare_with(self, team_id: UUID) -> None:
        page = self.ctx.page
        page.show_dialog(CompareDialog(self.store, on_close=page.pop_dialog, other_id=team_id))

    def _copy_team(self, team_id: UUID) -> None:
        self.ctx.copy_to_clipboard(self.store.export_text_for(team_id))
        self.ctx.toast("Showdown text copied", "success")

    def _format_short(self, format_id: str | None) -> str:
        fmt = self.store.formats.for_team(format_id)
        return fmt.name.replace("Regulations ", "Reg ")

    def _show_analysis(self, tab: str) -> None:
        if not self.summary.visible:
            self._toggle_summary()
        self.summary.show_tab(tab)

    # -- team actions ------------------------------------------------------------------------------------

    async def _new_team(self) -> None:
        name = await self.ctx.prompt_text("New team", "Team name", submit_label="Create", validate=self._validate_name)
        if name:
            self.store.create_team(name)
            self.close_library()                 # a new team opens in the editor
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
        if not 1 <= b <= 6 or a == b:
            return
        was_selected = self.selected == a
        if self.store.swap(a, b):
            if was_selected:
                self.selected = None
                self._set_selected(b)
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

    def _clear_move(self, position: int, index: int) -> None:
        slot = self.store.slot(position)
        if slot.entry is None:
            return
        self.store.set_move(position, index, "")
        self.ctx.toast(f"Cleared move {index + 1} on {slot.entry.pokemon.display_name}", "info")

    def _spread_changed(self, position: int, nature: str, points: dict[str, int]) -> None:
        """Inline spread edits are saved once the slider pauses (every commit re-validates
        the team, which a drag would otherwise do dozens of times)."""
        self._pending_spread[position] = (nature, points)
        later = self._spread_later.get(position)
        if later is not None:
            later(None)
        else:
            self._save_spread(position)

    def _save_spread(self, position: int) -> None:
        pending = self._pending_spread.pop(position, None)
        if pending is None:
            return
        problems = self.store.save_spread(position, nature=pending[0], points=pending[1])
        self.cards[position - 1].show_spread_problems(problems)

    def _open_partner(self, name: str) -> None:
        """Show the tournament teams with this partner in Meta."""
        self.ctx.bus.emit(events.NAVIGATE, "meta")      # builds the Meta view if needed, so it hears the search
        self.ctx.bus.emit(events.META_SEARCH, name)

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

        dialog = ItemPickerDialog(
            catalogs=self.store.catalogs, species_name=slot.species_name,
            current_item_id=slot.item.canonical_id if slot.item else None,
            on_pick=pick, on_close=self.ctx.page.pop_dialog, mega=self.store.active_format.has(Mechanic.MEGA),
            sort=str(self.ctx.prefs.get("team.item_sort", "popular")), on_sort=lambda v: self.ctx.prefs.set("team.item_sort", v),
        )
        self.ctx.page.show_dialog(dialog)
        # Tournament usage ranks the list; it can take a query the first time, so it arrives later.
        self.ctx.run_in_background(lambda: self.store.item_usage(position), on_done=dialog.set_usage, on_error=lambda _e: None)

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
            self.close_library()
            self._set_selected(None)
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
        self._update_self()

    def handle_resize(self, width: float, height: float) -> None:
        self._narrow = width < Layout.BREAKPOINT_NARROW
        self.summary.width = Layout.SIDE_PANEL_WIDTH_COMPACT if width < Layout.BREAKPOINT_COMPACT else Layout.SIDE_PANEL_WIDTH
        self._body.set_narrow(self._narrow)

    def _update_self(self) -> None:
        if is_mounted(self):
            self.update()


__all__ = ["COMPACT_COL", "TeamView"]

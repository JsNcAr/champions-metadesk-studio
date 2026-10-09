"""Plans view: your matchup plans against common meta teams, one list per team.

Pick a team, then a plan: the editor holds what a team report's matchup entry holds
(difficulty, Lead/Back, game plan, a note per threat). The opposing six come from a paste,
a Poképaste link, a Calc rival preset or Meta. The app runs no strategy of its own: the
plan is yours to write, and Copy as Markdown turns it into a report-style entry.
"""

from __future__ import annotations

from typing import Any

import flet as ft

from ... import events

from ...components import EmptyState, PageHeader
from ...context import AppContext
from ...tasks import is_mounted
from ...theme import DEFAULT_WINDOW_WIDTH, Accent, IconSize, Layout, Palette, Radius, Space
from ..calc.state import CalcRequest, PokemonState, RivalTeam
from .components import PlanRow
from .dialogs import PasteDialog, PresetPickerDialog
from .editor import EditorActions, PlanEditor
from .model import Plan, PlanDraft
from .report import pokemon_to_showdown
from .store import PlanStore

PREF_TEAM = "plans.team"
PREF_PLAN = "plans.plan"
LIST_WIDTH = 300
LIST_WIDTH_NARROW = 240
NARROW_BELOW = Layout.BREAKPOINT_COMPACT   # the width below which the rail goes compact too


class PlansView(ft.Column):
    def __init__(self, ctx: AppContext, store: PlanStore, team_store: Any, *, rival_store_factory: Any = None) -> None:
        super().__init__(spacing=0, expand=True)
        self.ctx = ctx
        self.store = store
        self.team_store = team_store
        self._rival_store_factory = rival_store_factory
        self.team_id: str | None = None
        self.plan_id: str | None = None
        self.plans: list[Plan] = []
        self._teams: list[tuple[str, str]] = []
        self._loaded = False
        self._stale = False
        self._dialog: ft.AlertDialog | None = None

        self._team_picker = ft.Dropdown(width=240, leading_icon=ft.Icons.GROUPS_OUTLINED, tooltip="The team these plans are for",
                                        on_select=lambda e: self.select_team(e.control.value))
        self._add = ft.PopupMenuButton(
            tooltip="Add a plan against another team",
            content=ft.Container(
                content=ft.Row(spacing=Space.XS, tight=True, controls=[ft.Icon(ft.Icons.ADD, size=IconSize.SM, color=Palette.ON_PRIMARY),
                                                                         ft.Text("Add plan", theme_style=ft.TextThemeStyle.LABEL_LARGE, color=Palette.ON_PRIMARY)]),
                bgcolor=Accent.PLANS, border_radius=Radius.PILL, padding=ft.Padding.symmetric(horizontal=Space.MD, vertical=Space.SM),
            ),
            items=[
                ft.PopupMenuItem(content=ft.Text("From Meta…"), icon=ft.Icons.EMOJI_EVENTS_OUTLINED, on_click=lambda _e: self._add_from_meta()),
                ft.PopupMenuItem(content=ft.Text("Paste or Poképaste link…"), icon=ft.Icons.CONTENT_PASTE, on_click=lambda _e: self.open_paste()),
                ft.PopupMenuItem(content=ft.Text("Rival preset…"), icon=ft.Icons.SPORTS_MMA_OUTLINED, on_click=lambda _e: self.open_presets()),
            ],
        )
        self._copy_all = ft.IconButton(icon=ft.Icons.CONTENT_COPY, tooltip="Copy every plan of this team as Markdown", on_click=lambda _e: self.copy_all())
        self.header = PageHeader("Plans", icon=ft.Icons.ASSIGNMENT_OUTLINED, accent=Accent.PLANS,
                                 actions=[self._team_picker, self._copy_all, self._add])

        self._list_caption = ft.Text("", theme_style=ft.TextThemeStyle.LABEL_SMALL, color=Palette.ON_SURFACE_VARIANT)
        self._list = ft.ListView(expand=True, spacing=2)
        self._list_panel = ft.Container(
            width=LIST_WIDTH,
            content=ft.Column(spacing=Space.SM, expand=True, controls=[self._list_caption, self._list]),
            padding=ft.Padding.only(right=Space.SM),
            border=ft.Border.only(right=ft.BorderSide(1, Palette.OUTLINE_VARIANT)),
        )
        self.editor = PlanEditor(catalogs=store.catalogs, actions=EditorActions(
            update=self._update_plan, set_note=self._set_note, open_in_calc=self._open_in_calc, edit_paste=self.open_edit_paste,
            copy=self.copy_plan, rename=self._rename, duplicate=self._duplicate, delete=self._delete,
        ))
        self._editor_host = ft.Container(expand=True, content=self.editor, padding=ft.Padding.only(left=Space.LG))
        self._body = ft.Row(expand=True, spacing=0, vertical_alignment=ft.CrossAxisAlignment.STRETCH, controls=[self._list_panel, self._editor_host])
        self._empty = ft.Container(expand=True, visible=False)
        self.controls = [self.header, self._body, self._empty]
        self.handle_resize(float(getattr(ctx.page, "width", None) or DEFAULT_WINDOW_WIDTH), 0)

        team_store.subscribe(self._on_team_store_change)
        ctx.bus.on(events.TEAMS_CHANGED, lambda _p: self._mark_stale(teams=True))
        ctx.bus.on(events.BOX_ENTRY_DELETED, lambda _p: self._mark_stale())
        ctx.bus.on(events.CATALOGS_RELOADED, self._on_catalogs_reloaded)
        ctx.bus.on(events.FORMAT_CHANGED, lambda _p: self._mark_stale())

    # -- lifecycle ------------------------------------------------------------------------

    def ensure_loaded(self) -> None:
        if not self._loaded:
            self._loaded = True
            self._load_teams()
            wanted = self.ctx.prefs.get(PREF_TEAM)
            active = str(self.team_store.active_team_id) if self.team_store.active_team_id else None
            ids = [t for t, _ in self._teams]
            self.select_team(wanted if wanted in ids else (active if active in ids else (ids[0] if ids else None)), remember=False)
            return
        if self._stale:
            self._stale = False
            self._load_teams()
            ids = [t for t, _ in self._teams]
            if self.team_id not in ids:
                self.select_team(ids[0] if ids else None)
            else:
                self.store.invalidate(self.team_id)
                self._reload_plans(keep=self.plan_id)

    def handle_resize(self, width: float, _height: float) -> None:
        self._list_panel.width = LIST_WIDTH_NARROW if width < NARROW_BELOW else LIST_WIDTH

    # -- teams ----------------------------------------------------------------------------

    def _load_teams(self) -> None:
        rows = self.team_store.library_rows()
        self._teams = [(str(r.team_id), r.name) for r in rows]
        self._team_picker.options = [ft.DropdownOption(key=t, text=name) for t, name in self._teams]

    def team_name(self) -> str:
        return next((name for t, name in self._teams if t == self.team_id), "")

    def select_team(self, team_id: str | None, *, remember: bool = True) -> None:
        self.team_id = team_id or None
        self._team_picker.value = self.team_id
        if remember and self.team_id:
            self.ctx.prefs.set(PREF_TEAM, self.team_id)
        wanted = self.ctx.prefs.get(PREF_PLAN)
        self._reload_plans(keep=wanted)

    def _reload_plans(self, *, keep: str | None = None) -> None:
        self.plans = self.store.list_plans(self.team_id) if self.team_id else []
        ids = [p.plan_id for p in self.plans]
        self.plan_id = keep if keep in ids else (ids[0] if ids else None)
        self._render()

    # -- rendering ------------------------------------------------------------------------

    def _render(self) -> None:
        if not self._teams:
            self._show_empty(EmptyState(ft.Icons.GROUPS_OUTLINED, "No teams yet",
                                        "Plans are made for one of your teams. Build one in Teams, then plan its matchups here.",
                                        action_label="Go to Teams", on_action=lambda: self.ctx.bus.emit(events.NAVIGATE, "team")))
            return
        self._body.visible, self._empty.visible = True, False
        self._list_caption.value = f"{len(self.plans)} plan{'s' if len(self.plans) != 1 else ''} · {self.team_name()}"
        self._list.controls = [self._row(p) for p in self.plans]
        self._copy_all.disabled = not self.plans
        if self.plan_id is None:
            self._editor_host.content = EmptyState(
                ft.Icons.ASSIGNMENT_OUTLINED, "No plans for this team yet",
                "Add a plan against a common team: from Meta › Top teams, a paste or Poképaste link, or one of your rival presets. "
                "Then note how hard it is, what you lead with and keep in the back, and how you handle each threat.",
                action_label="Paste a team…", on_action=self.open_paste,
            )
        else:
            plan = next(p for p in self.plans if p.plan_id == self.plan_id)
            self._editor_host.content = self.editor
            self.editor.show(plan, self.store.my_members(self.team_id))
        self._update()

    def _row(self, plan: Plan) -> PlanRow:
        idx = self.plans.index(plan)
        return PlanRow(plan, self.store.catalogs, selected=plan.plan_id == self.plan_id, on_select=self.select_plan, menu_items=[
            ft.PopupMenuItem(content=ft.Text("Rename…"), icon=ft.Icons.EDIT_OUTLINED, on_click=lambda _e, p=plan: self._rename(p)),
            ft.PopupMenuItem(content=ft.Text("Duplicate"), icon=ft.Icons.CONTENT_COPY_OUTLINED, on_click=lambda _e, p=plan: self._duplicate(p)),
            ft.PopupMenuItem(content=ft.Text("Move up"), icon=ft.Icons.ARROW_UPWARD, disabled=idx == 0, on_click=lambda _e, p=plan: self._move(p, -1)),
            ft.PopupMenuItem(content=ft.Text("Move down"), icon=ft.Icons.ARROW_DOWNWARD, disabled=idx == len(self.plans) - 1, on_click=lambda _e, p=plan: self._move(p, 1)),
            ft.PopupMenuItem(),
            ft.PopupMenuItem(content=ft.Text("Delete…"), icon=ft.Icons.DELETE_OUTLINE, on_click=lambda _e, p=plan: self._delete(p)),
        ])

    def _show_empty(self, control: ft.Control) -> None:
        self._body.visible = False
        self._empty.content = control
        self._empty.visible = True
        self._copy_all.disabled = True
        self._update()

    def select_plan(self, plan_id: str) -> None:
        if plan_id == self.plan_id:
            return
        self.plan_id = plan_id
        self.ctx.prefs.set(PREF_PLAN, plan_id)
        self._render()

    # -- editing (EditorActions) ----------------------------------------------------------

    def _update_plan(self, plan_id: str, **changes: Any) -> Plan | None:
        try:
            saved = self.store.update(plan_id, **changes)
        except (KeyError, ValueError) as exc:
            self.ctx.toast(str(exc), "error")
            return None
        self._replace(saved)
        return saved

    def _set_note(self, plan_id: str, index: int, text: str) -> Plan | None:
        saved = self.store.set_threat_note(plan_id, index, text)
        self._replace(saved)
        return saved

    def _replace(self, plan: Plan) -> None:
        """Keep the list in step with an edit without redrawing the editor under the cursor."""
        self.plans = [plan if p.plan_id == plan.plan_id else p for p in self.plans]
        self._list.controls = [self._row(p) for p in self.plans]
        if is_mounted(self._list):
            self._list.update()

    def _open_in_calc(self, pokemon: PokemonState) -> None:
        self.ctx.bus.emit(events.CALC_REQUESTED, CalcRequest(defender=pokemon))

    def copy_plan(self, plan: Plan) -> None:
        self.ctx.copy_to_clipboard(self.store.plan_markdown(plan.plan_id))
        self.ctx.toast(f"Copied “{plan.name}” as Markdown", "success")

    def copy_all(self) -> None:
        if not self.team_id or not self.plans:
            return
        self.ctx.copy_to_clipboard(self.store.team_markdown(self.team_id, self.team_name()))
        self.ctx.toast(f"Copied {len(self.plans)} plan{'s' if len(self.plans) != 1 else ''} as Markdown", "success")

    def _rename(self, plan: Plan) -> None:
        async def run() -> None:
            name = await self.ctx.prompt_text("Rename plan", "Name", value=plan.name)
            if name is None or not name.strip() or name.strip() == plan.name:
                return
            self._update_plan(plan.plan_id, name=name)
            self._reload_plans(keep=plan.plan_id)
        self.ctx.page.run_task(run)

    def _duplicate(self, plan: Plan) -> None:
        copy = self.store.duplicate(plan.plan_id, f"{plan.name} (copy)")
        self._reload_plans(keep=copy.plan_id)
        self.ctx.bus.emit(events.PLANS_CHANGED, self.team_id)

    def _move(self, plan: Plan, delta: int) -> None:
        self.store.move(plan.plan_id, delta)
        self._reload_plans(keep=self.plan_id)

    def _delete(self, plan: Plan) -> None:
        async def run() -> None:
            if not await self.ctx.confirm("Delete plan?", f"“{plan.name}” and its pinned calcs will be deleted."):
                return
            self.store.delete(plan.plan_id)
            self._reload_plans(keep=None if plan.plan_id == self.plan_id else self.plan_id)
            self.ctx.bus.emit(events.PLANS_CHANGED, self.team_id)
            self.ctx.toast(f"Deleted “{plan.name}”", "info")
        self.ctx.page.run_task(run)

    # -- adding a plan --------------------------------------------------------------------

    def create_plan(self, draft: PlanDraft, *, team_id: str | None = None) -> Plan | None:
        """Save a draft to a team (this view's by default) and open it."""
        target = team_id or self.team_id
        if not target:
            self.ctx.toast("Build a team first: plans are made for one of your teams", "warning")
            return None
        plan = self.store.create_from_draft(target, draft)
        if target != self.team_id:
            self.select_team(target)
        self._reload_plans(keep=plan.plan_id)
        self.ctx.prefs.set(PREF_PLAN, plan.plan_id)
        self.ctx.bus.emit(events.PLANS_CHANGED, target)
        return plan

    def _add_from_meta(self) -> None:
        self.ctx.bus.emit(events.NAVIGATE, "meta")
        self.ctx.toast("Pick a lineup in Meta › Top teams, or a team in Events, and use “Add to plan…”", "info")

    def open_paste(self) -> None:
        if not self.team_id:
            self.ctx.toast("Build a team first: plans are made for one of your teams", "warning")
            return
        dialog = PasteDialog(title="Plan against a team", submit_label="Add plan", on_cancel=self._close_dialog,
                             on_submit=lambda name, text: self._import_paste(dialog, name, text))
        self._open_dialog(dialog)

    def _import_paste(self, dialog: PasteDialog, name: str, text: str, *, plan: Plan | None = None) -> None:
        from ..calc.rival_store import rivals_from_text_or_url

        dialog.set_busy(True)

        def work():
            return rivals_from_text_or_url(text, self.store.catalogs)

        def done(result) -> None:
            members, skipped, source = result
            if not members:
                dialog.set_error("No Pokémon in the Champions species catalogue were found in that paste")
                return
            self._close_dialog()
            if plan is None:
                draft = PlanDraft(name=name or _default_name(self.store, list(self.store.normalise_megas(members))), members=tuple(members), source=source)
                self.create_plan(draft)
            else:
                self._replace_opponent(plan, members)
            if skipped:
                self.ctx.toast(f"Skipped (not in the species catalogue): {', '.join(skipped)}", "warning")

        def failed(exc: BaseException) -> None:
            dialog.set_error(f"Couldn't read that team: {exc}")

        self.ctx.run_in_background(work, on_done=done, on_error=failed)

    def open_edit_paste(self, plan: Plan) -> None:
        text = "\n\n".join(pokemon_to_showdown(m.pokemon, self.store.species_name(m.pokemon.species)) for m in plan.opponent)
        dialog = PasteDialog(title=f"Their team · {plan.name}", submit_label="Save", on_cancel=self._close_dialog, name=None, text=text,
                             note="Edit their sets. A note stays with its slot (the first Pokémon's note with the first Pokémon).",
                             on_submit=lambda _name, t: self._import_paste(dialog, "", t, plan=plan))
        self._open_dialog(dialog)

    def _replace_opponent(self, plan: Plan, members: list) -> None:
        self.store.replace_opponent(plan.plan_id, members)
        self._reload_plans(keep=plan.plan_id)

    def open_presets(self) -> None:
        if not self.team_id:
            self.ctx.toast("Build a team first: plans are made for one of your teams", "warning")
            return

        def work() -> list[RivalTeam]:
            rivals = self._rival_store()
            rivals.load()
            return list(rivals.presets)

        def done(presets: list[RivalTeam]) -> None:
            self._open_dialog(PresetPickerDialog(presets, self.store.catalogs, on_pick=self._from_preset, on_cancel=self._close_dialog))

        self.ctx.run_in_background(work, on_done=done, on_error=lambda exc: self.ctx.toast(f"Couldn't load rival presets: {exc}", "error"))

    def _from_preset(self, team: RivalTeam) -> None:
        self._close_dialog()
        self.create_plan(PlanDraft(name=team.name, members=tuple(team.members), source=f"Rival preset · {team.source}" if team.source else "Rival preset"))

    def _rival_store(self):
        if self._rival_store_factory is not None:
            return self._rival_store_factory()
        from ..calc.rival_store import RivalStore
        return RivalStore()

    # -- dialogs --------------------------------------------------------------------------

    def _open_dialog(self, dialog: ft.AlertDialog) -> None:
        self._dialog = dialog
        self.ctx.page.show_dialog(dialog)

    def _close_dialog(self) -> None:
        if self._dialog is not None:
            self._dialog = None
            self.ctx.page.pop_dialog()

    # -- outside changes ------------------------------------------------------------------

    def _on_team_store_change(self, change: tuple) -> None:
        kind = change[0]
        if kind == "teams":
            self._mark_stale(teams=True)
        else:
            active = self.team_store.active_team_id
            if active is not None:
                self.store.invalidate(str(active))
            if active is not None and str(active) == self.team_id:
                self._mark_stale()

    def _mark_stale(self, *, teams: bool = False) -> None:
        if teams:
            self.store.invalidate()
        self._stale = True

    def _on_catalogs_reloaded(self, _kind: Any) -> None:
        self.store.catalogs = self.ctx.catalogs
        self.editor.catalogs = self.ctx.catalogs
        self.store.invalidate()
        self._stale = True

    def _update(self) -> None:
        if is_mounted(self):
            self.update()


def _default_name(store: PlanStore, members: list) -> str:
    names = [store.species_name(m.pokemon.species) for m in members[:3]]
    return " + ".join(names) + ("…" if len(members) > 3 else "") if names else "New plan"


__all__ = ["PlansView", "PREF_PLAN", "PREF_TEAM"]

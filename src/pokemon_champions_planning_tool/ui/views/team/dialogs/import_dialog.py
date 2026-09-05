"""Stepped Showdown/Poképaste import: Paste → Preview → Readiness → Done."""

from __future__ import annotations

from collections.abc import Callable
from uuid import UUID

import flet as ft

from .....services.showdown_service import ImportReadinessReport, ParsedSlot, ParsedTeamResult
from .....domain.stat_calc import format_points
from .... import events
from ....components import EmptyState, StatusChip
from ....components.banner import InlineBanner
from ....components.pokemon import IdentityRow
from ....context import AppContext
from ....tasks import is_mounted
from ....theme import Palette, Radius, Space
from ..store import TeamStore

STEPS = ("Paste", "Preview", "Readiness", "Done")


class ImportDialog(ft.AlertDialog):
    def __init__(
        self,
        ctx: AppContext,
        store: TeamStore,
        *,
        initial_text: str = "",
        initial_title: str = "",
        on_done: Callable[[UUID], None] | None = None,
    ) -> None:
        super().__init__(modal=True, scrollable=True)
        self.ctx = ctx
        self.store = store
        self._on_done = on_done
        self.parsed: ParsedTeamResult | None = None
        self.readiness: ImportReadinessReport | None = None
        self.result_team_id: UUID | None = None
        self._result_team_name: str | None = None
        self.step = 0
        self._use_planned = False

        # -- step indicator ---------------------------------------------------------------
        self._step_dots: list[ft.Container] = []
        indicator_controls: list[ft.Control] = []
        for i, label in enumerate(STEPS):
            dot = ft.Container(content=ft.Text(str(i + 1), theme_style=ft.TextThemeStyle.LABEL_MEDIUM, weight=ft.FontWeight.W_600),
                               width=24, height=24, border_radius=Radius.PILL, alignment=ft.Alignment.CENTER)
            self._step_dots.append(dot)
            indicator_controls.append(ft.Row(spacing=Space.XS, tight=True, controls=[dot, ft.Text(label, theme_style=ft.TextThemeStyle.LABEL_MEDIUM, color=Palette.ON_SURFACE_VARIANT)]))
            if i < len(STEPS) - 1:
                indicator_controls.append(ft.Container(width=24, height=1, bgcolor=Palette.OUTLINE_VARIANT))
        self._indicator = ft.Row(spacing=Space.SM, alignment=ft.MainAxisAlignment.CENTER, vertical_alignment=ft.CrossAxisAlignment.CENTER, controls=indicator_controls)

        # -- step 1: paste --------------------------------------------------------------------
        self._input = ft.TextField(
            hint_text="Paste Showdown text or a pokepast.es URL", multiline=True, min_lines=8, max_lines=14, value=initial_text,
            text_style=ft.TextStyle(font_family="monospace", size=12), on_change=lambda _e: self._input_changed(),
        )
        self._paste_status = ft.Text("", theme_style=ft.TextThemeStyle.BODY_SMALL, color=Palette.ON_SURFACE_VARIANT)
        self._paste_spinner = ft.ProgressRing(width=16, height=16, stroke_width=2, visible=False)
        self._paste_banner = InlineBanner(visible=False)

        # -- step 2: preview -------------------------------------------------------------------
        self._team_name = ft.TextField(label="Team name", value=initial_title, dense=True, width=320)
        self._preview = ft.Column(spacing=Space.XS, tight=True)
        self._preview_banner = InlineBanner(visible=False)

        # -- step 3: readiness -----------------------------------------------------------------
        self._readiness_summary = ft.Text("", theme_style=ft.TextThemeStyle.BODY_MEDIUM, color=Palette.ON_SURFACE)
        self._option_owned = self._option_card("Add missing to box & import", "Missing Pokémon are added to your box as owned entries.", recommended=True, planned=False)
        self._option_planned = self._option_card("Import as template", "Missing Pokémon become planned entries — visible on the team, hidden from the roster.", recommended=False, planned=True)
        self._readiness_banner = InlineBanner(visible=False)

        # -- step 4: done ---------------------------------------------------------------------
        self._done = EmptyState(ft.Icons.CHECK_CIRCLE_OUTLINE, "Team imported", "")

        self._body = ft.Column(spacing=Space.MD, tight=True)
        self._back = ft.TextButton("Back", on_click=lambda _e: self._go(self.step - 1))
        self._cancel = ft.TextButton("Cancel", on_click=lambda _e: self._cancel_clicked())
        self._next = ft.FilledButton("Next", on_click=lambda _e: self._advance())
        self._import_spinner = ft.ProgressRing(width=16, height=16, stroke_width=2, visible=False)
        self.title = ft.Text("Import team")
        self.content = ft.Container(width=720, content=ft.Column(spacing=Space.LG, tight=True, controls=[self._indicator, self._body]))
        self.actions = [self._back, self._cancel, self._import_spinner, self._next]
        self.actions_alignment = ft.MainAxisAlignment.END

        if initial_text.strip():
            self._parse_text(initial_text)
            self._go(1 if self.parsed and self.parsed.is_valid else 0)
        else:
            self._go(0)

    # -- option cards --------------------------------------------------------------------------

    def _option_card(self, title: str, caption: str, *, recommended: bool, planned: bool) -> ft.Container:
        badge = [StatusChip("Recommended", "info")] if recommended else []
        card = ft.Container(
            content=ft.Column(spacing=Space.XS, tight=True, controls=[
                ft.Row(spacing=Space.SM, controls=[ft.Text(title, theme_style=ft.TextThemeStyle.BODY_LARGE, color=Palette.ON_SURFACE), *badge]),
                ft.Text(caption, theme_style=ft.TextThemeStyle.BODY_SMALL, color=Palette.ON_SURFACE_VARIANT),
            ]),
            bgcolor=Palette.SURFACE_2, border_radius=Radius.MD, padding=Space.MD, border=ft.Border.all(1, Palette.OUTLINE_VARIANT), ink=True,
            on_click=lambda _e, planned=planned: self._choose(planned),
        )
        return card

    def _choose(self, planned: bool) -> None:
        self._use_planned = planned
        for card, is_planned in ((self._option_owned, False), (self._option_planned, True)):
            card.border = ft.Border.all(2, Palette.PRIMARY) if is_planned == planned else ft.Border.all(1, Palette.OUTLINE_VARIANT)
        self._refresh()

    # -- steps -----------------------------------------------------------------------------------

    def _go(self, step: int) -> None:
        self.step = max(0, min(len(STEPS) - 1, step))
        for i, dot in enumerate(self._step_dots):
            if i < self.step:
                dot.bgcolor, dot.content.color = Palette.SUCCESS_CONTAINER, Palette.ON_SUCCESS_CONTAINER
            elif i == self.step:
                dot.bgcolor, dot.content.color = Palette.PRIMARY, Palette.ON_PRIMARY
            else:
                dot.bgcolor, dot.content.color = Palette.SURFACE_3, Palette.ON_SURFACE_VARIANT
        if self.step == 0:
            self._body.controls = [self._input, ft.Row(spacing=Space.SM, controls=[self._paste_spinner, self._paste_status]), self._paste_banner]
        elif self.step == 1:
            self._render_preview()
            self._body.controls = [self._team_name, self._preview_banner, self._preview]
        elif self.step == 2:
            self._render_readiness()
            self._body.controls = [self._readiness_summary, self._readiness_banner, self._option_owned, self._option_planned]
        else:
            self.modal = False
            self._body.controls = [ft.Container(content=self._done, alignment=ft.Alignment.CENTER, padding=ft.Padding.symmetric(vertical=Space.MD))]
        self._refresh()

    def _refresh(self) -> None:
        self._back.visible = 0 < self.step < 3
        self._cancel.visible = True
        self._cancel.content = "Cancel" if self.step < 3 else "Close"
        if self.step == 0:
            self._next.content = "Next"
            self._next.disabled = not (self.parsed and self.parsed.is_valid)
        elif self.step == 1:
            self._next.content = "Next"
            self._next.disabled = False
        elif self.step == 2:
            blocked = bool(self.readiness and self.readiness.illegal_species)
            self._next.content = "Import"
            self._next.disabled = blocked
        else:
            self._next.content = "Open team"
            self._next.disabled = False
        if is_mounted(self):
            self.update()

    def _cancel_clicked(self) -> None:
        name = self._result_team_name if self.step == 3 else None
        self.close()
        if name:
            self.ctx.toast(f"Imported {name}", "success")

    def _advance(self) -> None:
        if self.step == 0:
            self._go(1)
        elif self.step == 1:
            self.readiness = self.store.readiness(self.parsed) if self.parsed else None
            if self.readiness and not self.readiness.illegal_species and not self.readiness.missing and not self.readiness.unresolvable:
                self._commit(use_planned=False)
            else:
                self._go(2)
        elif self.step == 2:
            self._commit(use_planned=self._use_planned)
        else:
            name = self._result_team_name
            team_id = self.result_team_id
            self.close()
            if name:
                self.ctx.toast(f"Imported {name}", "success")
            if self._on_done and team_id:
                self._on_done(team_id)

    def close(self) -> None:
        page = getattr(self.ctx, "page", None)
        if page is not None:
            if hasattr(page, "_dialogs") and hasattr(page._dialogs, "controls"):
                for _ in range(len(page._dialogs.controls) + 1):
                    if not (self in page._dialogs.controls and self.open):
                        break
                    popped = page.pop_dialog()
                    if popped is self:
                        break
            elif hasattr(page, "dialogs"):
                while page.dialogs:
                    popped = page.pop_dialog()
                    if popped is self or popped is None:
                        break
            elif hasattr(page, "pop_dialog"):
                page.pop_dialog()
        self.open = False

    # -- paste ---------------------------------------------------------------------------------

    def _input_changed(self) -> None:
        text = self._input.value or ""
        if not text.strip():
            self.parsed = None
            self._paste_status.value = ""
            self._refresh()
            return
        if self.store.is_paste_url(text):
            self._paste_status.value = "Fetching from Poképast.es…"
            self._paste_banner.hide()

            def done(parsed: ParsedTeamResult) -> None:
                self.parsed = parsed
                if parsed.title and not (self._team_name.value or "").strip():
                    self._team_name.value = parsed.title
                self._paste_status.value = f"Found {len(parsed.slots)} Pokémon"
                self._refresh()

            def failed(exc: BaseException) -> None:
                self._paste_status.value = ""
                self._paste_banner.show(f"Couldn't fetch the paste: {exc}", "error")
                self._refresh()

            self.ctx.run_in_background(lambda: self.store.fetch_paste(text), on_done=done, on_error=failed, spinner=self._paste_spinner)
        else:
            self._parse_text(text)
            self._refresh()

    def _parse_text(self, text: str) -> None:
        self.parsed = self.store.parse(text)
        n = len(self.parsed.slots)
        self._paste_status.value = f"{n} Pokémon parsed" if self.parsed.is_valid else "Nothing recognisable yet"
        if self.parsed.title and not (self._team_name.value or "").strip():
            self._team_name.value = self.parsed.title

    # -- preview ---------------------------------------------------------------------------------

    def _render_preview(self) -> None:
        if not self.parsed:
            self._preview.controls = []
            return
        self.readiness = self.store.readiness(self.parsed)
        status_by_slot: dict[int, tuple[str, str]] = {}
        for slot in self.readiness.in_box:
            status_by_slot[id(slot)] = ("In box", "success")
        for slot in self.readiness.missing:
            status_by_slot[id(slot)] = ("Not in box", "warning")
        for slot in self.readiness.unresolvable:
            status_by_slot[id(slot)] = ("Unknown species", "error")
        for slot in self.readiness.illegal_species:
            status_by_slot[id(slot)] = ("Not Champions-legal", "error")

        rows: list[ft.Control] = []
        catalogs = self.store.catalogs
        for slot in self.parsed.slots[:6]:
            label, tone = status_by_slot.get(id(slot), ("", "neutral"))
            # Cheap dictionary lookups; None (no learnset known) never flags anything.
            cid = slot.resolved_canonical_id or slot.showdown_form_key
            flagged = [m for m in slot.moves if catalogs.move_legality(cid, m) is False]
            rows.append(self._slot_row(slot, label, tone, flagged_moves=flagged))
        self._preview.controls = rows
        warnings = list(self.parsed.warnings)
        if warnings:
            self._preview_banner.show("; ".join(warnings[:3]), "warning")
        else:
            self._preview_banner.hide()

    @staticmethod
    def _slot_row(slot: ParsedSlot, status: str, tone: str, *, flagged_moves: list[str] | None = None) -> ft.Control:
        from .....domain.pokemon_identity import get_pokemon_sprite_url

        bits = []
        if slot.item_name:
            bits.append(f"@ {slot.item_name}")
        if slot.ability_name:
            bits.append(slot.ability_name)
        if slot.tera_type:
            bits.append(f"Tera {slot.tera_type}")
        spread = format_points(slot.points)
        if spread:
            bits.append(f"{slot.nature or 'Hardy'} · {spread}")
        detail = ft.Column(spacing=2, tight=True, expand=True, controls=[
            ft.Text(" · ".join(bits), theme_style=ft.TextThemeStyle.BODY_SMALL, color=Palette.ON_SURFACE_VARIANT, visible=bool(bits)),
            ft.Text(" / ".join(slot.moves), theme_style=ft.TextThemeStyle.BODY_SMALL, color=Palette.ON_SURFACE_VARIANT, visible=bool(slot.moves)),
            ft.Row(spacing=Space.XS, tight=True, wrap=True, visible=bool(flagged_moves) or slot.points_converted, controls=[
                *([StatusChip(f"{len(flagged_moves or [])} move{'s' if len(flagged_moves or []) != 1 else ''} not in Champions learnset", "warning",
                              icon=ft.Icons.WARNING_AMBER_ROUNDED, tooltip=", ".join(flagged_moves or []))] if flagged_moves else []),
                *([StatusChip("Converted from EVs", "info", icon=ft.Icons.SWAP_VERT, tooltip="Champions uses stat points (0–32 per stat, 66 total); the EV spread was converted without changing its stats")] if slot.points_converted else []),
            ]),
        ])
        row = IdentityRow(name=slot.species_name, sprite_url=get_pokemon_sprite_url(slot.showdown_form_key or slot.species_name),
                          trailing=StatusChip(status, tone) if status else None)  # type: ignore[arg-type]
        return ft.Container(
            content=ft.Row(spacing=Space.MD, vertical_alignment=ft.CrossAxisAlignment.CENTER, controls=[ft.Container(content=row, width=300), detail]),
            padding=ft.Padding.symmetric(horizontal=Space.SM, vertical=Space.XS), border_radius=Radius.SM, bgcolor=Palette.SURFACE_2,
        )

    # -- readiness ------------------------------------------------------------------------------------

    def _render_readiness(self) -> None:
        r = self.readiness
        if r is None:
            return
        if r.illegal_species:
            names = ", ".join(s.species_name for s in r.illegal_species)
            self._readiness_summary.value = "This team can't be imported."
            self._readiness_banner.show(f"Not in the Champions Pokédex: {names}", "error")
            self._option_owned.visible = self._option_planned.visible = False
            return
        problems = list(r.missing) + list(r.unresolvable)
        self._readiness_summary.value = f"{len(r.in_box)} in box · {len(r.missing)} missing · {len(r.unresolvable)} unknown"
        self._readiness_banner.hide()
        self._option_owned.visible = self._option_planned.visible = bool(problems)
        self._choose(self._use_planned)

    def _commit(self, *, use_planned: bool) -> None:
        if not self.parsed:
            return
        name = (self._team_name.value or "").strip() or None

        def done(result) -> None:
            self.result_team_id = result.team_id
            self._result_team_name = result.team_name
            detail = f"{result.team_name} · {len(result.reused)} from your box"
            if result.created_owned:
                detail += f" · {len(result.created_owned)} added to box"
            if result.created_planned:
                detail += f" · {len(result.created_planned)} planned"
            self._done.set_text("Team imported", detail)
            self.ctx.bus.emit(events.TEAMS_CHANGED, result.team_id)
            self._go(3)

        def failed(exc: BaseException) -> None:
            self._readiness_banner.show(f"Import failed: {exc}", "error")
            self._go(2)

        self.ctx.run_in_background(lambda: self.store.import_parsed(self.parsed, use_planned=use_planned, team_name=name),
                                   on_done=done, on_error=failed, busy=[self._next], spinner=self._import_spinner)

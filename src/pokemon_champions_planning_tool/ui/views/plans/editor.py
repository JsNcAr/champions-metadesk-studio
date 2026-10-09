"""The plan editor: overview (difficulty, Lead, Back), game plan, and the opposing six with a
note on each. The view supplies the actions; the editor only lays a plan out and reports
edits, then shows the plan the store saved."""

from __future__ import annotations

from collections.abc import Callable, Sequence
from dataclasses import dataclass
from typing import Any

import flet as ft

from ...tasks import is_mounted
from ...theme import Accent, IconSize, Palette, Radius, Space, alpha
from ..calc.state import PokemonState, RivalMember
from .components import section, species_sprite
from .model import DIFFICULTIES, MAX_PICKS, MemberRef, Plan

GAME_PLAN_HINT = (
    "One step per line, like a team report:\n"
    "Tailwind + Fake Out T1, Kingambit in the back\n"
    "  If they lead Tyranitar + Excadrill, Wave Crash into Excadrill\n"
    "Save Raichu until Sinistcha is gone"
)
_ASSUMED_LABELS = {"moves": "moves", "item": "item", "ability": "ability", "nature": "nature", "points": "spread"}


@dataclass
class EditorActions:
    update: Callable[..., Plan | None]                 # (plan_id, **changes) -> saved plan
    set_note: Callable[[str, int, str], Plan | None]   # (plan_id, opponent index, text)
    open_in_calc: Callable[[PokemonState], None]       # load an opposing set as the Defender
    edit_paste: Callable[[Plan], None]                 # replace the opponent from a paste
    copy: Callable[[Plan], None]                       # this plan as Markdown
    rename: Callable[[Plan], None]
    duplicate: Callable[[Plan], None]
    delete: Callable[[Plan], None]


class PlanEditor(ft.Column):
    def __init__(self, *, catalogs: Any, actions: EditorActions) -> None:
        super().__init__(spacing=Space.MD, expand=True, scroll=ft.ScrollMode.AUTO)
        self.catalogs = catalogs
        self.actions = actions
        self.plan: Plan | None = None
        self._mine: list[tuple[str, PokemonState]] = []

        self._title = ft.Text("", theme_style=ft.TextThemeStyle.TITLE_MEDIUM, weight=ft.FontWeight.W_600, color=Palette.ON_SURFACE,
                              max_lines=1, overflow=ft.TextOverflow.ELLIPSIS, expand=True)
        self._source = ft.Text("", theme_style=ft.TextThemeStyle.BODY_SMALL, color=Palette.ON_SURFACE_VARIANT)
        self._menu = ft.PopupMenuButton(icon=ft.Icons.MORE_VERT, tooltip="Plan actions", items=[
            ft.PopupMenuItem(content=ft.Text("Rename…"), icon=ft.Icons.EDIT_OUTLINED, on_click=lambda _e: self._act(self.actions.rename)),
            ft.PopupMenuItem(content=ft.Text("Duplicate"), icon=ft.Icons.CONTENT_COPY_OUTLINED, on_click=lambda _e: self._act(self.actions.duplicate)),
            ft.PopupMenuItem(),
            ft.PopupMenuItem(content=ft.Text("Delete…"), icon=ft.Icons.DELETE_OUTLINE, on_click=lambda _e: self._act(self.actions.delete)),
        ])
        header = ft.Row(spacing=Space.SM, vertical_alignment=ft.CrossAxisAlignment.CENTER, controls=[
            ft.Column(spacing=2, tight=True, expand=True, controls=[self._title, self._source]),
            ft.OutlinedButton("Copy as Markdown", icon=ft.Icons.CONTENT_COPY, on_click=lambda _e: self._act(self.actions.copy),
                              tooltip="This plan as Markdown, like a team report's matchup entry"),
            self._menu,
        ])

        self._difficulty = ft.SegmentedButton(
            selected=["0"], allow_multiple_selection=False, allow_empty_selection=False, show_selected_icon=False,
            segments=[ft.Segment(value=str(i), label=ft.Text("—" if i == 0 else label)) for i, label in enumerate(DIFFICULTIES)],
            on_change=lambda e: self._set_difficulty(next(iter(e.control.selected or ["0"]))),
        )
        self._lead = ft.Row(spacing=Space.SM, wrap=True, run_spacing=Space.SM)
        self._back = ft.Row(spacing=Space.SM, wrap=True, run_spacing=Space.SM)
        overview = section(
            "Overview",
            ft.Row(spacing=Space.MD, wrap=True, vertical_alignment=ft.CrossAxisAlignment.CENTER, controls=[_label("Difficulty"), self._difficulty]),
            ft.Row(spacing=Space.MD, vertical_alignment=ft.CrossAxisAlignment.START, controls=[_label("Lead", width=56), ft.Container(content=self._lead, expand=True)]),
            ft.Row(spacing=Space.MD, vertical_alignment=ft.CrossAxisAlignment.START, controls=[_label("Back", width=56), ft.Container(content=self._back, expand=True)]),
            tip="Pick the two you lead with and the two you keep in the back (in Singles the first lead starts). A Pokémon is never in both.",
        )

        self._game_plan = ft.TextField(multiline=True, min_lines=6, max_lines=18, hint_text=GAME_PLAN_HINT, text_size=14,
                                       hint_style=ft.TextStyle(color=Palette.DISABLED, italic=True),   # an example, not your plan
                                       on_blur=lambda e: self._save_game_plan(e.control.value or ""))
        game_plan = section("Game plan", self._game_plan,
                            tip="Your plan, one step per line; indent a line for a sub-point. Copy as Markdown turns each line into a bullet.")

        self._opponent = ft.ResponsiveRow(spacing=Space.SM, run_spacing=Space.SM)
        self._opponent_section = section(
            "Their team", self._opponent,
            trailing=[ft.TextButton("Edit as paste…", icon=ft.Icons.EDIT_NOTE, on_click=lambda _e: self._act(self.actions.edit_paste),
                                    tooltip="Replace their sets with a Showdown paste; notes stay with each slot")],
            tip="The plan keeps its own copy of their six. Italic fields were filled from tournament data, not seen.",
        )

        self.controls = [header, overview, game_plan, self._opponent_section]

    # -- showing a plan -------------------------------------------------------------------

    def show(self, plan: Plan, mine: Sequence[tuple[str, PokemonState]]) -> None:
        """Lay a plan out (a different plan, or the same after an edit from elsewhere)."""
        same = self.plan is not None and self.plan.plan_id == plan.plan_id
        self.plan = plan
        self._mine = list(mine)
        self._title.value = plan.name
        self._source.value = f"From {plan.source}" if plan.source else ""
        self._source.visible = bool(plan.source)
        self._difficulty.selected = [str(plan.difficulty)]
        if not same or (self._game_plan.value or "") != plan.game_plan:
            self._game_plan.value = plan.game_plan
        self._render_picks()
        self._render_opponent()
        self._refresh()

    def set_mine(self, mine: Sequence[tuple[str, PokemonState]]) -> None:
        """The team changed: redraw the picks (names, and any that left the team)."""
        self._mine = list(mine)
        if self.plan is not None:
            self._render_picks()
            self._refresh()

    def _render_picks(self) -> None:
        plan = self.plan
        assert plan is not None
        self._lead.controls = self._pick_chips(plan.lead, "lead")
        self._back.controls = self._pick_chips(plan.back, "back")

    def _pick_chips(self, picked: tuple[MemberRef, ...], role: str) -> list[ft.Control]:
        if not self._mine and not picked:
            return [ft.Text("This team has no Pokémon yet.", theme_style=ft.TextThemeStyle.BODY_SMALL, color=Palette.ON_SURFACE_VARIANT)]
        order = {r.box_entry_id: i for i, r in enumerate(picked)}
        chips: list[ft.Control] = []
        for box_id, state in self._mine:
            chips.append(self._chip(box_id, state.species, role, order.get(box_id)))
        here = {box_id for box_id, _ in self._mine}
        for ref in picked:
            if ref.box_entry_id not in here:
                chips.append(self._chip(ref.box_entry_id, ref.species, role, order[ref.box_entry_id], gone=True))
        return chips

    def _chip(self, box_id: str, species: str | None, role: str, rank: int | None, *, gone: bool = False) -> ft.Control:
        name = self._name(species)
        on = rank is not None
        label = f"{name} (not in team)" if gone else name
        tip = (f"{'Lead' if role == 'lead' else 'Back'} pick — click to remove" if on else f"Pick for {'Lead' if role == 'lead' else 'Back'}")
        return ft.Container(
            content=ft.Row(spacing=Space.XS, tight=True, vertical_alignment=ft.CrossAxisAlignment.CENTER, controls=[
                species_sprite(species, self.catalogs, size=28, ring="missing" if gone else None),
                ft.Text(label, theme_style=ft.TextThemeStyle.BODY_SMALL, weight=ft.FontWeight.W_600 if on else None,
                        color=Palette.ON_SURFACE if on else Palette.ON_SURFACE_VARIANT),
            ]),
            padding=ft.Padding.only(left=Space.XS, right=Space.SM, top=2, bottom=2),
            border_radius=Radius.PILL,
            bgcolor=alpha(Accent.PLANS, 0.16) if on else None,
            border=ft.Border.all(1, Accent.PLANS if on else (Palette.ERROR if gone else Palette.OUTLINE_VARIANT)),
            tooltip=tip, ink=True,
            on_click=lambda _e, b=box_id, s=species or "": self._toggle_pick(role, b, s),
            data={"role": role, "box_entry_id": box_id, "picked": on},
        )

    def _render_opponent(self) -> None:
        plan = self.plan
        assert plan is not None
        if not plan.opponent:
            self._opponent.controls = [ft.Text("No opposing Pokémon: use Edit as paste… to add them.", col=12,
                                               theme_style=ft.TextThemeStyle.BODY_SMALL, color=Palette.ON_SURFACE_VARIANT)]
            return
        self._opponent.controls = [self._opponent_card(i, m) for i, m in enumerate(plan.opponent)]

    def _opponent_card(self, index: int, member: RivalMember) -> ft.Control:
        p = member.pokemon
        assumed = member.assumed

        def field_text(value: str, key: str) -> ft.Text:
            return ft.Text(value, theme_style=ft.TextThemeStyle.BODY_SMALL, color=Palette.ON_SURFACE_VARIANT,
                           italic=key in assumed, max_lines=2, overflow=ft.TextOverflow.ELLIPSIS,
                           tooltip="From tournament data, not seen" if key in assumed else None)

        moves = " / ".join(m for m in p.moves if m)
        build_bits = [b for b in (f"@ {p.item}" if p.item else "", p.ability or "") if b]
        lines: list[ft.Control] = [ft.Text(self._name(p.species), theme_style=ft.TextThemeStyle.BODY_MEDIUM, weight=ft.FontWeight.W_600, color=Palette.ON_SURFACE)]
        if build_bits:
            lines.append(field_text(" · ".join(build_bits), "item" if "item" in assumed else "ability"))
        if moves:
            lines.append(field_text(moves, "moves"))
        note = ft.TextField(
            value=self.plan.note_for(index) if self.plan else "", label="Threat note", hint_text="How you deal with it…",
            multiline=True, min_lines=1, max_lines=4, dense=True, text_size=13,
            on_blur=lambda e, i=index: self._save_note(i, e.control.value or ""),
        )
        return ft.Container(
            col={"xs": 12, "md": 6, "xl": 4},
            content=ft.Column(spacing=Space.SM, tight=True, horizontal_alignment=ft.CrossAxisAlignment.STRETCH, controls=[
                ft.Row(spacing=Space.SM, vertical_alignment=ft.CrossAxisAlignment.START, controls=[
                    species_sprite(p.species, self.catalogs, size=40),
                    ft.Column(spacing=2, tight=True, expand=True, controls=lines),
                    ft.IconButton(icon=ft.Icons.CALCULATE_OUTLINED, icon_size=IconSize.SM, tooltip="Open in Calc as the Defender",
                                  on_click=lambda _e, s=p: self.actions.open_in_calc(s)),
                ]),
                note,
            ]),
            bgcolor=Palette.SURFACE_3, border_radius=Radius.SM, padding=Space.SM,
            data={"opponent_index": index},
        )

    # -- edits ----------------------------------------------------------------------------

    def _toggle_pick(self, role: str, box_id: str, species: str) -> None:
        plan = self.plan
        if plan is None:
            return
        current = list(plan.lead if role == "lead" else plan.back)
        if any(r.box_entry_id == box_id for r in current):
            current = [r for r in current if r.box_entry_id != box_id]
        else:
            current.append(MemberRef(box_id, species))
            current = current[-MAX_PICKS:]   # a third pick drops the oldest
        saved = self.actions.update(plan.plan_id, **{role: current})
        if saved is not None:
            self.plan = saved
            self._render_picks()
            self._refresh()

    def _set_difficulty(self, value: str) -> None:
        if self.plan is None:
            return
        saved = self.actions.update(self.plan.plan_id, difficulty=int(value))
        if saved is not None:
            self.plan = saved

    def _save_game_plan(self, text: str) -> None:
        if self.plan is None or text == self.plan.game_plan:
            return
        saved = self.actions.update(self.plan.plan_id, game_plan=text)
        if saved is not None:
            self.plan = saved

    def _save_note(self, index: int, text: str) -> None:
        if self.plan is None or text == self.plan.note_for(index):
            return
        saved = self.actions.set_note(self.plan.plan_id, index, text)
        if saved is not None:
            self.plan = saved

    # -- helpers --------------------------------------------------------------------------

    def _act(self, fn: Callable[[Plan], None]) -> None:
        if self.plan is not None:
            fn(self.plan)

    def _name(self, canonical_id: str | None) -> str:
        if not canonical_id:
            return "?"
        species = self.catalogs.species_for(canonical_id)
        return species.name if species else canonical_id.replace("-", " ").title()

    def _refresh(self) -> None:
        if is_mounted(self):
            self.update()


def _label(text: str, *, width: int | None = None) -> ft.Text:
    return ft.Text(text, theme_style=ft.TextThemeStyle.LABEL_LARGE, color=Palette.ON_SURFACE_VARIANT, width=width)


__all__ = ["EditorActions", "GAME_PLAN_HINT", "PlanEditor"]

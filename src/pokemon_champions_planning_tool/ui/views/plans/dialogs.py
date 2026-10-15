"""Plans dialogs: a paste (new plan, or a plan's opponent) and a rival preset picker.

Both only collect input; the view does the parsing on a worker and the saving.
"""

from __future__ import annotations

from collections.abc import Callable, Sequence
from typing import Any

import flet as ft

from ...tasks import is_mounted
from ...theme import Accent, Palette, Radius, Space, alpha
from ..calc.state import RivalTeam
from .components import species_sprite

PASTE_HINT = "Showdown text of their six, or a pokepast.es link"
DIALOG_FIELD_W = 520   # a Dropdown keeps its own width in a stretched column: set it


class PasteDialog(ft.AlertDialog):
    """Name + paste. ``on_submit(name, text)`` starts the import; the view reports back with
    ``set_busy`` / ``set_error``, and closes the dialog when it worked."""

    def __init__(self, *, title: str, submit_label: str, on_submit: Callable[[str, str], None], on_cancel: Callable[[], None],
                 name: str | None = "", text: str = "", note: str | None = None) -> None:
        super().__init__(modal=True, scrollable=True)
        self._on_submit = on_submit
        self._name = ft.TextField(label="Plan name", value=name or "", hint_text="e.g. Big Six, Raptor (Sand)…", autofocus=True,
                                  visible=name is not None)
        self._text = ft.TextField(label="Their team", value=text, hint_text=PASTE_HINT, multiline=True, min_lines=10, max_lines=16, text_size=13,
                                  autofocus=name is None)
        self._error = ft.Text("", theme_style=ft.TextThemeStyle.BODY_SMALL, color=Palette.ERROR, visible=False)
        self._spinner = ft.ProgressRing(width=16, height=16, stroke_width=2, visible=False)
        self._submit = ft.FilledButton(submit_label, on_click=lambda _e: self._fire())
        controls: list[ft.Control] = [self._name, self._text]
        if note:
            controls.insert(0, ft.Text(note, theme_style=ft.TextThemeStyle.BODY_SMALL, color=Palette.ON_SURFACE_VARIANT))
        controls.append(ft.Row(spacing=Space.SM, controls=[self._spinner, self._error]))
        self.title = ft.Text(title)
        self.content = ft.Container(width=560, content=ft.Column(spacing=Space.MD, tight=True, horizontal_alignment=ft.CrossAxisAlignment.STRETCH, controls=controls))
        self.actions = [ft.TextButton("Cancel", on_click=lambda _e: on_cancel()), self._submit]
        self.actions_alignment = ft.MainAxisAlignment.END

    @property
    def name(self) -> str:
        return (self._name.value or "").strip()

    @property
    def text(self) -> str:
        return (self._text.value or "").strip()

    def _fire(self) -> None:
        if not self.text:
            self.set_error("Paste their team, or a pokepast.es link")
            return
        self._on_submit(self.name, self.text)

    def set_busy(self, busy: bool) -> None:
        self._spinner.visible = busy
        self._submit.disabled = busy
        if busy:
            self._error.visible = False
        self._refresh()

    def set_error(self, message: str) -> None:
        self._spinner.visible = False
        self._submit.disabled = False
        self._error.value = message
        self._error.visible = True
        self._refresh()

    def _refresh(self) -> None:
        if is_mounted(self):
            self.update()


class AddPlanDialog(ft.AlertDialog):
    """A team from Meta or Calc becomes a plan: which of your teams it is for, and its name."""

    def __init__(self, members: Sequence[Any], catalogs: Any, *, teams: Sequence[tuple[str, str]], team_id: str | None, name: str,
                 source: str, on_save: Callable[[str, str], None], on_cancel: Callable[[], None]) -> None:
        super().__init__(modal=True, scrollable=True)
        self._on_save = on_save
        self._team = ft.Dropdown(label="Plan for your team", value=team_id, leading_icon=ft.Icons.GROUPS_OUTLINED, width=DIALOG_FIELD_W,
                                 options=[ft.DropdownOption(key=t, text=n) for t, n in teams])
        self._name = ft.TextField(label="Plan name", value=name, hint_text="e.g. Big Six, Raptor (Sand)…", autofocus=True,
                                  on_submit=lambda _e: self._fire())
        self._error = ft.Text("", theme_style=ft.TextThemeStyle.BODY_SMALL, color=Palette.ERROR, visible=False)
        sprites = ft.Row(spacing=Space.XS, wrap=True, controls=[species_sprite(getattr(m, "pokemon", m).species, catalogs, size=36) for m in members[:6]])
        self.title = ft.Text("Add to a plan")
        self.content = ft.Container(width=520, content=ft.Column(spacing=Space.MD, tight=True, horizontal_alignment=ft.CrossAxisAlignment.STRETCH, controls=[
            ft.Text(f"Their team · {source}" if source else "Their team", theme_style=ft.TextThemeStyle.LABEL_MEDIUM, color=Palette.ON_SURFACE_VARIANT),
            sprites, self._team, self._name, self._error,
        ]))
        self.actions = [ft.TextButton("Cancel", on_click=lambda _e: on_cancel()), ft.FilledButton("Add plan", on_click=lambda _e: self._fire())]
        self.actions_alignment = ft.MainAxisAlignment.END

    def _fire(self) -> None:
        if not self._team.value:
            self._error.value, self._error.visible = "Pick one of your teams", True
            if is_mounted(self):
                self.update()
            return
        self._on_save(str(self._team.value), (self._name.value or "").strip())


class PinDialog(ft.AlertDialog):
    """Pin the calculator's calc to one of a team's plans.

    ``plans_for(team_id)`` lists a team's plans; ``match_mine(team_id, species)`` and
    ``match_theirs(plan_id, species)`` find the team member and the opponent a side can
    follow ((key, label) or None), so the link checkboxes name what the pin will track.
    """

    def __init__(self, *, left_name: str, right_name: str, teams: Sequence[tuple[str, str]], team_id: str | None, label: str,
                 left_species: str | None, right_species: str | None,
                 plans_for: Callable[[str], list[tuple[str, str]]], match_mine: Callable[[str, str | None], tuple[str, str] | None],
                 match_theirs: Callable[[str, str | None], tuple[int, str] | None],
                 on_save: Callable[[str, str, str, str, str | None, int | None], None], on_cancel: Callable[[], None]) -> None:
        super().__init__(modal=True, scrollable=True)
        self._on_save = on_save
        self._plans_for, self._match_mine, self._match_theirs = plans_for, match_mine, match_theirs
        self._species = {"left": left_species, "right": right_species}
        self._mine_value: tuple[str, str] | None = None
        self._theirs_value: tuple[int, str] | None = None
        self._team = ft.Dropdown(label="Team", value=team_id, leading_icon=ft.Icons.GROUPS_OUTLINED, width=DIALOG_FIELD_W,
                                 options=[ft.DropdownOption(key=t, text=n) for t, n in teams], on_select=lambda _e: self._team_changed())
        self._plan = ft.Dropdown(label="Plan", width=DIALOG_FIELD_W, on_select=lambda _e: self._links())
        self._label = ft.TextField(label="Label", value=label, hint_text="What this calc shows, e.g. Low Kick into their Kingambit")
        self._mine = ft.SegmentedButton(
            selected=["left"], allow_multiple_selection=False, allow_empty_selection=False, show_selected_icon=False,
            segments=[ft.Segment(value="left", label=ft.Text(f"Attacker · {left_name}")), ft.Segment(value="right", label=ft.Text(f"Defender · {right_name}"))],
            on_change=lambda _e: self._links(),
        )
        self._follow_mine = ft.Checkbox(value=True)
        self._follow_theirs = ft.Checkbox(value=True)
        self._error = ft.Text("", theme_style=ft.TextThemeStyle.BODY_SMALL, color=Palette.ERROR, visible=False)
        self.title = ft.Text("Pin to a plan")
        self.content = ft.Container(width=560, content=ft.Column(spacing=Space.MD, tight=True, horizontal_alignment=ft.CrossAxisAlignment.STRETCH, controls=[
            ft.Text("The pin keeps this calc's boosts, HP, status and field; a side that follows a Pokémon takes its current set each time.",
                    theme_style=ft.TextThemeStyle.BODY_SMALL, color=Palette.ON_SURFACE_VARIANT),
            self._team, self._plan, self._label,
            ft.Text("Your Pokémon is the", theme_style=ft.TextThemeStyle.LABEL_MEDIUM, color=Palette.ON_SURFACE_VARIANT), self._mine,
            self._follow_mine, self._follow_theirs, self._error,
        ]))
        self.actions = [ft.TextButton("Cancel", on_click=lambda _e: on_cancel()), ft.FilledButton("Pin", icon=ft.Icons.PUSH_PIN, on_click=lambda _e: self._fire())]
        self.actions_alignment = ft.MainAxisAlignment.END
        self._team_changed(refresh=False)

    @property
    def mine(self) -> str:
        return next(iter(self._mine.selected or ["left"]))

    def _team_changed(self, *, refresh: bool = True) -> None:
        plans = self._plans_for(self._team.value) if self._team.value else []
        self._plan.options = [ft.DropdownOption(key=p, text=n) for p, n in plans]
        self._plan.value = plans[0][0] if plans else None
        self._plan.disabled = not plans
        self._plan.hint_text = None if plans else "This team has no plans yet"
        self._links(refresh=refresh)

    def _links(self, *, refresh: bool = True) -> None:
        mine, theirs = self.mine, "right" if self.mine == "left" else "left"
        self._mine_value = self._match_mine(self._team.value, self._species[mine]) if self._team.value else None
        self._theirs_value = self._match_theirs(self._plan.value, self._species[theirs]) if self._plan.value else None
        self._follow_mine.label = f"Follow your {self._mine_value[1]} in the team" if self._mine_value else "Your side is not in this team: kept as pinned"
        self._follow_mine.disabled = self._mine_value is None
        self._follow_mine.value = self._mine_value is not None
        self._follow_theirs.label = f"Follow their {self._theirs_value[1]} in this plan" if self._theirs_value else "Their side is not in this plan: kept as pinned"
        self._follow_theirs.disabled = self._theirs_value is None
        self._follow_theirs.value = self._theirs_value is not None
        if refresh and is_mounted(self):
            self.update()

    def _fire(self) -> None:
        if not self._team.value or not self._plan.value:
            self._error.value, self._error.visible = "Pick a team and one of its plans", True
            if is_mounted(self):
                self.update()
            return
        box_id = self._mine_value[0] if self._mine_value and self._follow_mine.value else None
        opp_index = self._theirs_value[0] if self._theirs_value and self._follow_theirs.value else None
        self._on_save(str(self._team.value), str(self._plan.value), (self._label.value or "").strip(), self.mine, box_id, opp_index)


class LeadPairDialog(ft.AlertDialog):
    """Pick two of their six: the lead a scenario plans for, or their field on a turn.
    ``on_pick(indices)``; ``allow_clear`` adds "Same as before" (an empty pick)."""

    def __init__(self, members: Sequence[Any], catalogs: Any, *, title: str, on_pick: Callable[[tuple[int, ...]], None],
                 on_cancel: Callable[[], None], selected: Sequence[int] = (), allow_clear: bool = False, max_pick: int = 2) -> None:
        super().__init__(modal=True, scrollable=True)
        self._on_pick = on_pick
        self._max = max_pick
        self._picked: list[int] = [i for i in selected if 0 <= i < len(members)][:max_pick]
        self._members = list(members)
        self._catalogs = catalogs
        self._chips = ft.Row(spacing=Space.SM, wrap=True, run_spacing=Space.SM)
        self._ok = ft.FilledButton("Use these two", on_click=lambda _e: self._on_pick(tuple(self._picked)))
        actions: list[ft.Control] = [ft.TextButton("Cancel", on_click=lambda _e: on_cancel())]
        if allow_clear:
            actions.append(ft.TextButton("Same as before", on_click=lambda _e: self._on_pick(())))
        actions.append(self._ok)
        self.title = ft.Text(title)
        self.content = ft.Container(width=520, content=ft.Column(spacing=Space.MD, tight=True, controls=[
            ft.Text("Pick two of their Pokémon.", theme_style=ft.TextThemeStyle.BODY_SMALL, color=Palette.ON_SURFACE_VARIANT),
            self._chips,
        ]))
        self.actions = actions
        self.actions_alignment = ft.MainAxisAlignment.END
        self._render()

    def toggle(self, index: int) -> None:
        if index in self._picked:
            self._picked.remove(index)
        else:
            self._picked.append(index)
            self._picked = self._picked[-self._max:]
        self._render()
        if is_mounted(self):
            self.update()

    def _render(self) -> None:
        chips: list[ft.Control] = []
        for i, member in enumerate(self._members):
            p = getattr(member, "pokemon", member)
            on = i in self._picked
            species = self._catalogs.species_for(p.species) if p.species else None
            chips.append(ft.Container(
                content=ft.Row(spacing=Space.XS, tight=True, vertical_alignment=ft.CrossAxisAlignment.CENTER, controls=[
                    species_sprite(p.species, self._catalogs, size=32),
                    ft.Text(species.name if species else (p.species or "?"), theme_style=ft.TextThemeStyle.BODY_SMALL,
                            weight=ft.FontWeight.W_600 if on else None, color=Palette.ON_SURFACE if on else Palette.ON_SURFACE_VARIANT),
                ]),
                padding=ft.Padding.only(left=Space.XS, right=Space.SM, top=2, bottom=2), border_radius=Radius.PILL,
                bgcolor=alpha(Accent.PLANS, 0.16) if on else None, border=ft.Border.all(1, Accent.PLANS if on else Palette.OUTLINE_VARIANT),
                ink=True, on_click=lambda _e, i=i: self.toggle(i), data={"opp": i, "on": on},
            ))
        self._chips.controls = chips
        self._ok.disabled = len(self._picked) != self._max


class PresetPickerDialog(ft.AlertDialog):
    """Your saved rival presets (Calc); clicking one makes a plan against it."""

    def __init__(self, presets: Sequence[RivalTeam], catalogs: Any, *, on_pick: Callable[[RivalTeam], None], on_cancel: Callable[[], None]) -> None:
        super().__init__(modal=False, scrollable=True)
        rows: list[ft.Control] = []
        for team in presets:
            rows.append(ft.Container(
                content=ft.Row(spacing=Space.MD, vertical_alignment=ft.CrossAxisAlignment.CENTER, controls=[
                    ft.Column(spacing=2, tight=True, expand=True, controls=[
                        ft.Text(team.name, theme_style=ft.TextThemeStyle.BODY_MEDIUM, weight=ft.FontWeight.W_600, color=Palette.ON_SURFACE,
                                max_lines=1, overflow=ft.TextOverflow.ELLIPSIS),
                        ft.Text(team.source or "Rival preset", theme_style=ft.TextThemeStyle.BODY_SMALL, color=Palette.ON_SURFACE_VARIANT,
                                max_lines=1, overflow=ft.TextOverflow.ELLIPSIS),
                    ]),
                    ft.Row(spacing=0, controls=[species_sprite(m.pokemon.species, catalogs, size=28) for m in team.members[:6]]),
                ]),
                padding=Space.SM, border_radius=Radius.SM, ink=True,
                on_click=lambda _e, t=team: on_pick(t),
                on_hover=_hover,
                data=team.rival_team_id,
            ))
        if not rows:
            rows = [ft.Text("No rival presets yet. Save one in Calc (Rival team ▸ Load team…) or from a Meta team.",
                            theme_style=ft.TextThemeStyle.BODY_SMALL, color=Palette.ON_SURFACE_VARIANT)]
        self.title = ft.Text("Plan against a rival preset")
        self.content = ft.Container(width=560, content=ft.Column(spacing=2, tight=True, controls=rows))
        self.actions = [ft.TextButton("Cancel", on_click=lambda _e: on_cancel())]
        self.actions_alignment = ft.MainAxisAlignment.END


def _hover(e: ft.ControlEvent) -> None:
    on = getattr(e, "data", None) in ("true", True)
    e.control.bgcolor = alpha(Accent.PLANS, 0.10) if on else None
    if is_mounted(e.control):
        e.control.update()


__all__ = ["PASTE_HINT", "AddPlanDialog", "LeadPairDialog", "PasteDialog", "PinDialog", "PresetPickerDialog"]

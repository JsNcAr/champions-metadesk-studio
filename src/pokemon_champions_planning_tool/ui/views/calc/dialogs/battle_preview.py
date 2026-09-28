"""Load a rival team: into the "Current battle", or saved as a preset to plan against.

Four sources, one tab each:
- Team preview: the six species you see, filled with their most used tournament sets.
  Built for a live battle: type, Enter, next slot.
- Presets: rival teams saved before (from here, from a battle or from Meta).
- My teams: your own teams from the Teams view, with their real sets.
- Paste: a Showdown paste or a Poképaste link.
"""

from __future__ import annotations

from collections.abc import Callable, Sequence
from typing import Any

import flet as ft

from .....domain.pokemon_identity import get_pokemon_sprite_url
from .....services.sprite_cache_service import resolve_sprite_src
from ....components import Sprite
from ....components.banner import InlineBanner
from ....theme import Palette, Radius, Space
from ....tasks import safe_update
from ..rival_store import MAX_MEMBERS, rival_from_species, rivals_from_text_or_url
from ..rivals_panel import assumed_note
from ..state import RivalMember, RivalTeam

# on_start(members, source, name): name None starts "Current battle", a name saves a preset.
StartHandler = Callable[[list[RivalMember], str, str | None], None]
# load_team(team_id) -> (team name, members, slots that could not be read); reads the database.
TeamLoader = Callable[[Any], tuple[str, list[RivalMember], list[str]]]

MODES: tuple[tuple[str, str, str], ...] = (
    ("preview", "Team preview", ft.Icons.BOLT),
    ("presets", "Presets", ft.Icons.BOOKMARKS_OUTLINED),
    ("teams", "My teams", ft.Icons.GROUPS_OUTLINED),
    ("paste", "Paste", ft.Icons.CONTENT_PASTE),
)


def set_line(member: RivalMember) -> str:
    p = member.pokemon
    moves = ", ".join(m for m in p.moves if m)
    return " · ".join(x for x in (p.item, p.ability, moves) if x) or "No tournament set: plain spread, no moves"


def _hint(text: str) -> ft.Text:
    return ft.Text(text, theme_style=ft.TextThemeStyle.BODY_SMALL, color=Palette.ON_SURFACE_VARIANT)


class _Slot:
    """One team-preview slot: a species field and the set it will get."""

    def __init__(self, index: int, dialog: "BattleDialog") -> None:
        self.index = index
        self.member: RivalMember | None = None
        self.name = ""
        self.field = ft.TextField(label=f"Pokémon {index + 1}", dense=True, expand=True, autofocus=index == 0,
                                  on_change=lambda e: dialog._typed(self, e.control.value or ""),
                                  on_submit=lambda e: dialog._submit(self, e.control.value or ""),
                                  on_focus=lambda _e: dialog._focused(self))
        self.sprite = Sprite(None, size=32)
        self.caption = ft.Text("", theme_style=ft.TextThemeStyle.LABEL_SMALL, color=Palette.ON_SURFACE_VARIANT, max_lines=2,
                               overflow=ft.TextOverflow.ELLIPSIS)
        self.control = ft.Container(
            col={"xs": 12, "sm": 6, "md": 4},
            content=ft.Column(spacing=Space.XS, tight=True, controls=[
                ft.Row(spacing=Space.SM, vertical_alignment=ft.CrossAxisAlignment.CENTER, controls=[self.sprite, self.field]),
                self.caption,
            ]),
            padding=Space.SM, border_radius=Radius.SM, bgcolor=Palette.SURFACE_2, border=ft.Border.all(1, Palette.OUTLINE_VARIANT),
        )

    def show(self, member: RivalMember | None, name: str) -> None:
        self.member = member
        self.name = name if member else ""
        self.sprite.set_src(get_pokemon_sprite_url(member.pokemon.species) if member and member.pokemon.species else None)
        self.caption.value = set_line(member) if member else ""
        self.caption.tooltip = assumed_note(member) if member else None


class _Choice(ft.Container):
    """A selectable row in the Presets and My teams lists."""

    def __init__(self, title: str, subtitle: str, species: Sequence[str | None], *, on_click: Callable[[], None]) -> None:
        super().__init__()
        self.title = title
        self.content = ft.Row(spacing=Space.SM, vertical_alignment=ft.CrossAxisAlignment.CENTER, controls=[
            ft.Column(spacing=1, tight=True, expand=True, controls=[
                ft.Text(title, theme_style=ft.TextThemeStyle.BODY_MEDIUM, weight=ft.FontWeight.W_600, color=Palette.ON_SURFACE,
                        max_lines=1, overflow=ft.TextOverflow.ELLIPSIS),
                ft.Text(subtitle, theme_style=ft.TextThemeStyle.LABEL_SMALL, color=Palette.ON_SURFACE_VARIANT, max_lines=1,
                        overflow=ft.TextOverflow.ELLIPSIS),
            ]),
            ft.Row(spacing=2, tight=True, controls=[Sprite(get_pokemon_sprite_url(cid) if cid else None, size=28) for cid in species]),
        ])
        self.padding = ft.Padding.symmetric(horizontal=Space.SM, vertical=Space.XS)
        self.border_radius = Radius.SM
        self.ink = True
        self.on_click = lambda _e: on_click()
        self.set_selected(False)

    def set_selected(self, selected: bool) -> None:
        self.bgcolor = Palette.SURFACE_3 if selected else Palette.SURFACE_2
        self.border = ft.Border.all(1, Palette.PRIMARY if selected else Palette.OUTLINE_VARIANT)


class BattleDialog(ft.AlertDialog):
    def __init__(self, *, calc_store: Any, run_in_background: Callable[..., None], on_start: StartHandler, on_close: Callable[[], None],
                 mode: str = "preview", presets: Sequence[RivalTeam] = (), on_use_preset: Callable[[str], None] | None = None,
                 my_teams: Sequence[tuple[Any, str, int]] = (), load_team: TeamLoader | None = None) -> None:
        super().__init__(modal=True, scrollable=True)
        self.calc_store = calc_store
        self._run = run_in_background
        self._on_start = on_start
        self._on_use_preset = on_use_preset
        self._load_team = load_team
        self._mode = mode
        self._current: _Slot | None = None
        self._parsed: list[RivalMember] = []
        self._parsed_source = "Paste"
        self._presets = list(presets)
        self._preset: RivalTeam | None = None
        self._team_members: list[RivalMember] = []
        self._team_name = ""
        self._team_id: Any = None

        self._tabs = ft.SegmentedButton(
            segments=[ft.Segment(value=key, icon=ft.Icon(icon), label=ft.Text(label)) for key, label, icon in MODES],
            selected=[mode], show_selected_icon=False, on_change=lambda e: self._set_mode((e.control.selected or ["preview"])[0]),
        )
        self._banner = InlineBanner(visible=False)
        self._spinner = ft.ProgressRing(width=16, height=16, stroke_width=2, visible=False)

        # -- team preview
        self.slots = [_Slot(i, self) for i in range(MAX_MEMBERS)]
        self._suggestions = ft.Row(spacing=Space.XS, wrap=True, visible=False)
        self._preview = ft.Column(spacing=Space.SM, tight=True, controls=[
            _hint("Type each species you see; Enter picks the first match and moves on, Enter on an empty slot starts the battle. "
                  "Sets come from tournament data and count as guesses until the battle shows them."),
            ft.ResponsiveRow(spacing=Space.SM, run_spacing=Space.SM, controls=[s.control for s in self.slots]),
            self._suggestions,
        ])
        # -- presets
        self._preset_choices: dict[str, _Choice] = {}
        self._preset_members = ft.Column(spacing=Space.XS, tight=True, controls=[])
        preset_rows: list[ft.Control] = []
        for team in self._presets:
            choice = _Choice(team.name, f"{len(team.members)} Pokémon" + (f" · {team.source}" if team.source else ""),
                             [m.pokemon.species for m in team.members], on_click=lambda t=team: self.pick_preset(t))
            self._preset_choices[team.rival_team_id] = choice
            preset_rows.append(choice)
        self._presets_view = ft.Column(spacing=Space.SM, tight=True, controls=[
            _hint("Pick a preset to battle it. The preset itself stays as saved; what the battle reveals goes to the battle's copy.")
            if self._presets else
            _hint("No presets yet. Save one from the other tabs, from a battle (Save battle as preset…) or from Meta (a team's calculator menu)."),
            ft.Column(spacing=Space.XS, tight=True, controls=preset_rows),
            self._preset_members,
        ])
        # -- my teams
        self._team_choices: dict[Any, _Choice] = {}
        team_rows: list[ft.Control] = []
        for team_id, name, filled in my_teams:
            choice = _Choice(name or "Untitled team", f"{filled}/6 Pokémon", [], on_click=lambda tid=team_id: self.pick_team(tid))
            self._team_choices[team_id] = choice
            team_rows.append(choice)
        self._team_list = ft.Column(spacing=Space.XS, tight=True, controls=[])
        self._teams_view = ft.Column(spacing=Space.SM, tight=True, controls=[
            _hint("One of your teams from the Teams view, with its real sets: to test a mirror, or plan against a team you know.")
            if team_rows else _hint("You have no teams yet: build one in Teams."),
            ft.Column(spacing=Space.XS, tight=True, controls=team_rows),
            self._team_list,
        ])
        # -- paste
        self._paste = ft.TextField(label="Showdown paste or Poképaste link", multiline=True, min_lines=6, max_lines=12,
                                   text_style=ft.TextStyle(font_family="monospace", size=12), on_change=lambda _e: self._paste_changed())
        self._read = ft.OutlinedButton("Read team", icon=ft.Icons.PREVIEW, on_click=lambda _e: self._read_paste())
        self._parsed_list = ft.Column(spacing=Space.XS, tight=True, controls=[])
        self._paste_view = ft.Column(spacing=Space.SM, tight=True, controls=[self._paste, ft.Row(spacing=Space.SM, controls=[self._read]), self._parsed_list])

        # -- shared: save as a preset
        self._name = ft.TextField(label="Preset name", hint_text="e.g. Wolfe's sun team", dense=True, expand=True,
                                  on_change=lambda _e: self._sync_actions(), on_submit=lambda _e: self._save_team())
        self._save = ft.OutlinedButton("Save as preset", icon=ft.Icons.BOOKMARK_ADD_OUTLINED, on_click=lambda _e: self._save_team(),
                                       tooltip="Keep this team as a rival preset to plan against or battle later")
        self._save_row = ft.Row(spacing=Space.SM, vertical_alignment=ft.CrossAxisAlignment.CENTER, controls=[self._name, self._save])

        self._body = ft.Container(width=700)
        self.title = ft.Text("Load rival team")
        self.content = ft.Column(spacing=Space.MD, tight=True, controls=[
            self._tabs, self._body, ft.Row(spacing=Space.SM, controls=[self._spinner]), self._banner, self._save_row,
        ])
        self._start = ft.FilledButton("Start battle", icon=ft.Icons.SPORTS_MMA, on_click=lambda _e: self._start_battle(),
                                      tooltip="Load this team as the “Current battle”")
        self.actions = [ft.TextButton("Cancel", on_click=lambda _e: on_close()), self._start]
        self.actions_alignment = ft.MainAxisAlignment.END
        self._set_mode(mode, update=False)

    # -- mode ------------------------------------------------------------------------------------

    def _set_mode(self, mode: str, *, update: bool = True) -> None:
        self._mode = mode
        self._tabs.selected = [mode]
        self._body.content = {"preview": self._preview, "presets": self._presets_view, "teams": self._teams_view}.get(mode, self._paste_view)
        self._banner.hide()
        self._sync_actions(update=update)

    def members(self) -> list[RivalMember]:
        if self._mode == "preview":
            return [s.member for s in self.slots if s.member is not None]
        if self._mode == "presets":
            return list(self._preset.members) if self._preset else []
        if self._mode == "teams":
            return list(self._team_members)
        return list(self._parsed)

    def _sync_actions(self, *, update: bool = True) -> None:
        has = bool(self.members())
        self._start.disabled = not has
        self._start.content = "Use in battle" if self._mode == "presets" else "Start battle"
        self._save_row.visible = self._mode != "presets"      # a preset is already saved
        self._save.disabled = not has or not (self._name.value or "").strip()
        if update:
            safe_update(self)

    def _suggest_name(self, name: str) -> None:
        if name and not (self._name.value or "").strip():
            self._name.value = name

    # -- team preview --------------------------------------------------------------------------

    def _focused(self, slot: _Slot) -> None:
        self._current = slot

    def _typed(self, slot: _Slot, text: str) -> None:
        self._current = slot
        if slot.member is not None and text != slot.name:
            slot.show(None, "")      # edited after a pick: the old set no longer applies
            self._sync_actions(update=False)
        matches = self.calc_store.search_species(text) if text.strip() else []
        self._suggestions.controls = [
            ft.Chip(
                label=ft.Text(s.name, color=Palette.ON_SURFACE),
                leading=ft.Image(src=resolve_sprite_src(get_pokemon_sprite_url(s.canonical_id)), width=22, height=22, fit=ft.BoxFit.CONTAIN,
                                 error_content=ft.Icon(ft.Icons.CATCHING_POKEMON, size=16, color=Palette.ON_SURFACE_VARIANT)),
                show_checkmark=False, border_side=ft.BorderSide(1, Palette.PRIMARY) if i == 0 else None, tooltip="Enter picks this one" if i == 0 else None,
                on_click=lambda _e, cid=s.canonical_id, sl=slot: self.pick(sl, cid),
            )
            for i, s in enumerate(matches)
        ]
        self._suggestions.visible = bool(matches)
        safe_update(self)

    def _submit(self, slot: _Slot, text: str) -> None:
        if slot.member is not None and text == slot.name:
            self._focus_next(slot)
            return
        matches = self.calc_store.search_species(text) if text.strip() else []
        if matches:
            self.pick(slot, matches[0].canonical_id)
        elif not text.strip() and any(s.member for s in self.slots):
            self._start_battle()     # Enter on an empty slot: done, start
        # no match: keep the text so it can be corrected

    def pick(self, slot: _Slot, canonical_id: str) -> None:
        member = rival_from_species(self.calc_store, canonical_id)
        species = self.calc_store.catalogs.species_for(member.pokemon.species)
        name = species.name if species else canonical_id
        slot.field.value = name
        slot.show(member, name)
        self._suggestions.controls = []
        self._suggestions.visible = False
        self._sync_actions()
        self._focus_next(slot)

    def _focus_next(self, slot: _Slot) -> None:
        following = self.slots[slot.index + 1:] if slot.index + 1 < len(self.slots) else []
        target = next((s for s in following if s.member is None), following[0] if following else None)
        if target is None:
            return
        self._current = target
        try:
            if target.field.page is not None:
                target.field.page.run_task(target.field.focus)
        except RuntimeError:
            pass

    # -- presets and my teams ------------------------------------------------------------------

    def pick_preset(self, team: RivalTeam) -> None:
        self._preset = team
        for team_id, choice in self._preset_choices.items():
            choice.set_selected(team_id == team.rival_team_id)
        self._preset_members.controls = self._member_rows(list(team.members))
        self._sync_actions()

    def pick_team(self, team_id: Any) -> None:
        if self._load_team is None:
            return
        self._team_id = team_id
        for tid, choice in self._team_choices.items():
            choice.set_selected(tid == team_id)
        self._banner.hide()
        loader = self._load_team

        def done(result: tuple[str, list[RivalMember], list[str]]) -> None:
            if team_id != self._team_id:
                return      # another team was picked meanwhile
            name, members, skipped = result
            self._team_name = name
            self._team_members = members
            self._team_list.controls = self._member_rows(members)
            if not members:
                self._banner.show("That team has no Pokémon the calculator can read.", "warning")
            elif skipped:
                self._banner.show(f"Left out (not in the species catalogue): {', '.join(skipped)}", "warning")
            self._suggest_name(name)
            self._sync_actions()

        def failed(exc: BaseException) -> None:
            self._banner.show(f"Could not read the team: {exc}", "error")
            safe_update(self)

        self._run(lambda: loader(team_id), on_done=done, on_error=failed, spinner=self._spinner)

    # -- paste ---------------------------------------------------------------------------------

    def _paste_changed(self) -> None:
        if self._parsed:
            self._parsed = []
            self._parsed_list.controls = []
        self._banner.hide()
        self._sync_actions()

    def _read_paste(self) -> None:
        text = (self._paste.value or "").strip()
        if not text:
            self._banner.show("Paste a team or a Poképaste link first.", "info")
            safe_update(self)
            return
        self._banner.hide()

        def done(result: tuple[list[RivalMember], list[str], str]) -> None:
            members, skipped, source = result
            self.show_parsed(members, skipped, source)

        def failed(exc: BaseException) -> None:
            self._banner.show(f"Could not read the team: {exc}", "error")
            safe_update(self)

        catalogs = self.calc_store.catalogs
        self._run(lambda: rivals_from_text_or_url(text, catalogs), on_done=done, on_error=failed, busy=[self._read], spinner=self._spinner)

    def show_parsed(self, members: list[RivalMember], skipped: list[str], source: str) -> None:
        self._parsed = members
        self._parsed_source = source
        self._parsed_list.controls = self._member_rows(members)
        if not members:
            self._banner.show("No Pokémon in that text could be read.", "warning")
        elif skipped:
            self._banner.show(f"Not in the Champions catalogue, left out: {', '.join(skipped)}", "warning")
        else:
            self._banner.hide()
        if source.startswith("Poképaste · "):
            self._suggest_name(source.removeprefix("Poképaste · "))
        self._sync_actions()

    def _member_rows(self, members: list[RivalMember]) -> list[ft.Control]:
        rows: list[ft.Control] = []
        for m in members:
            species = self.calc_store.catalogs.species_for(m.pokemon.species)
            rows.append(ft.Row(spacing=Space.SM, vertical_alignment=ft.CrossAxisAlignment.CENTER, controls=[
                Sprite(get_pokemon_sprite_url(m.pokemon.species or ""), size=28),
                ft.Text(species.name if species else (m.pokemon.species or "?"), theme_style=ft.TextThemeStyle.BODY_MEDIUM, color=Palette.ON_SURFACE, width=150,
                        max_lines=1, overflow=ft.TextOverflow.ELLIPSIS),
                ft.Text(set_line(m), theme_style=ft.TextThemeStyle.LABEL_SMALL, color=Palette.ON_SURFACE_VARIANT, expand=True, max_lines=1,
                        overflow=ft.TextOverflow.ELLIPSIS, tooltip=assumed_note(m) or None),
            ]))
        return rows

    # -- finishing -----------------------------------------------------------------------------

    def _source(self) -> str:
        if self._mode == "preview":
            return "Team preview"
        if self._mode == "teams":
            return f"My team · {self._team_name}"
        return self._parsed_source

    def _start_battle(self) -> None:
        if self._mode == "presets":
            if self._preset is not None and self._on_use_preset is not None:
                self._on_use_preset(self._preset.rival_team_id)
            return
        members = self.members()
        if members:
            self._on_start(members, self._source(), None)

    def _save_team(self) -> None:
        members = self.members()
        name = (self._name.value or "").strip()
        if self._mode == "presets" or not members:
            return
        if not name:
            self._name.error = "Name the preset first"
            safe_update(self._name)
            return
        self._on_start(members, self._source(), name)


__all__ = ["BattleDialog", "MODES", "set_line"]

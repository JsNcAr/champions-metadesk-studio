"""New rival team: the six species seen at team preview (filled with tournament sets), or a
Showdown paste / Poképaste link. Built for a live battle: type, Enter, next slot."""

from __future__ import annotations

from collections.abc import Callable
from typing import Any

import flet as ft

from .....domain.pokemon_identity import get_pokemon_sprite_url
from ....components import Sprite
from ....components.banner import InlineBanner
from .....services.sprite_cache_service import resolve_sprite_src
from ....theme import Palette, Radius, Space
from ..rival_store import MAX_MEMBERS, rival_from_species, rivals_from_text_or_url
from ..rivals_panel import assumed_note
from ..state import RivalMember

# on_start(members, source, name): name None starts "Current battle", a name saves a rival team.
StartHandler = Callable[[list[RivalMember], str, str | None], None]


def set_line(member: RivalMember) -> str:
    p = member.pokemon
    moves = ", ".join(m for m in p.moves if m)
    return " · ".join(x for x in (p.item, p.ability, moves) if x) or "No tournament set: plain spread, no moves"


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


class BattleDialog(ft.AlertDialog):
    def __init__(self, *, calc_store: Any, run_in_background: Callable[..., None], on_start: StartHandler, on_close: Callable[[], None],
                 mode: str = "preview") -> None:
        super().__init__(modal=True, scrollable=True)
        self.calc_store = calc_store
        self._run = run_in_background
        self._on_start = on_start
        self._on_close = on_close
        self._mode = mode
        self._current: _Slot | None = None
        self._parsed: list[RivalMember] = []
        self._parsed_source = "Paste"

        self._tabs = ft.SegmentedButton(
            segments=[ft.Segment(value="preview", icon=ft.Icon(ft.Icons.BOLT), label=ft.Text("Team preview")),
                      ft.Segment(value="paste", icon=ft.Icon(ft.Icons.CONTENT_PASTE), label=ft.Text("Paste / Poképaste"))],
            selected=[mode], show_selected_icon=False, on_change=lambda e: self._set_mode((e.control.selected or ["preview"])[0]),
        )
        # -- team preview
        self.slots = [_Slot(i, self) for i in range(MAX_MEMBERS)]
        self._suggestions = ft.Row(spacing=Space.XS, wrap=True, visible=False)
        self._preview = ft.Column(spacing=Space.SM, tight=True, controls=[
            ft.Text("Type each species you see; Enter picks the first match and moves on. Sets come from tournament data and "
                    "count as guesses until the battle shows them.", theme_style=ft.TextThemeStyle.BODY_SMALL, color=Palette.ON_SURFACE_VARIANT),
            ft.ResponsiveRow(spacing=Space.SM, run_spacing=Space.SM, controls=[s.control for s in self.slots]),
            self._suggestions,
        ])
        # -- paste
        self._paste = ft.TextField(label="Showdown paste or Poképaste link", multiline=True, min_lines=6, max_lines=12,
                                   text_style=ft.TextStyle(font_family="monospace", size=12), on_change=lambda _e: self._paste_changed())
        self._read = ft.OutlinedButton("Read team", icon=ft.Icons.PREVIEW, on_click=lambda _e: self._read_paste())
        self._spinner = ft.ProgressRing(width=16, height=16, stroke_width=2, visible=False)
        self._banner = InlineBanner(visible=False)
        self._parsed_list = ft.Column(spacing=Space.XS, tight=True, controls=[])
        self._name = ft.TextField(label="Name, to save it as a rival team", dense=True, on_change=lambda _e: self._sync_actions())
        self._paste_view = ft.Column(spacing=Space.SM, tight=True, controls=[
            self._paste, ft.Row(spacing=Space.SM, controls=[self._read, self._spinner]), self._banner, self._parsed_list, self._name,
        ])

        self._body = ft.Container(width=680)
        self.title = ft.Text("New rival team")
        self.content = ft.Column(spacing=Space.MD, tight=True, controls=[self._tabs, self._body])
        self._start = ft.FilledButton("Start battle", icon=ft.Icons.SPORTS_MMA, on_click=lambda _e: self._start_battle(),
                                      tooltip="Replace the “Current battle” team with this one")
        self._save = ft.OutlinedButton("Save rival team", icon=ft.Icons.SAVE_OUTLINED, on_click=lambda _e: self._save_team())
        self.actions = [ft.TextButton("Cancel", on_click=lambda _e: on_close()), self._save, self._start]
        self.actions_alignment = ft.MainAxisAlignment.END
        self._set_mode(mode, update=False)

    # -- mode ------------------------------------------------------------------------------------

    def _set_mode(self, mode: str, *, update: bool = True) -> None:
        self._mode = mode
        self._tabs.selected = [mode]
        self._body.content = self._preview if mode == "preview" else self._paste_view
        self._sync_actions(update=update)

    def members(self) -> list[RivalMember]:
        if self._mode == "preview":
            return [s.member for s in self.slots if s.member is not None]
        return list(self._parsed)

    def _sync_actions(self, *, update: bool = True) -> None:
        has = bool(self.members())
        self._start.disabled = not has
        self._save.visible = self._mode == "paste"
        self._save.disabled = not has or not (self._name.value or "").strip()
        if update:
            self._safe_update(self)

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
        self._safe_update(self)

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
            self._safe_update(self)
            return
        self._banner.hide()

        def done(result: tuple[list[RivalMember], list[str], str]) -> None:
            members, skipped, source = result
            self.show_parsed(members, skipped, source)

        def failed(exc: BaseException) -> None:
            self._banner.show(f"Could not read the team: {exc}", "error")
            self._safe_update(self)

        catalogs = self.calc_store.catalogs
        self._run(lambda: rivals_from_text_or_url(text, catalogs), on_done=done, on_error=failed, busy=[self._read], spinner=self._spinner)

    def show_parsed(self, members: list[RivalMember], skipped: list[str], source: str) -> None:
        self._parsed = members
        self._parsed_source = source
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
        self._parsed_list.controls = rows
        if not members:
            self._banner.show("No Pokémon in that text could be read.", "warning")
        elif skipped:
            self._banner.show(f"Not in the Champions catalogue, left out: {', '.join(skipped)}", "warning")
        else:
            self._banner.hide()
        self._sync_actions()

    # -- finishing -----------------------------------------------------------------------------

    def _source(self) -> str:
        return "Team preview" if self._mode == "preview" else self._parsed_source

    def _start_battle(self) -> None:
        members = self.members()
        if members:
            self._on_start(members, self._source(), None)

    def _save_team(self) -> None:
        members = self.members()
        name = (self._name.value or "").strip()
        if members and name:
            self._on_start(members, self._source(), name)

    @staticmethod
    def _safe_update(control: ft.Control) -> None:
        try:
            if control.page is not None:
                control.update()
        except RuntimeError:
            pass


__all__ = ["BattleDialog", "set_line"]

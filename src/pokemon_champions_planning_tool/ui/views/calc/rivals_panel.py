"""Right column, "Rival team" mode: a saved rival team or the "Current battle" team, each
member classified against the Attacker, one click to load it as the Defender."""

from __future__ import annotations

from collections.abc import Callable

import flet as ft

from ....domain.pokemon_identity import get_pokemon_sprite_url
from ...components import Sprite, StatusChip
from ...components.section import SectionHeader
from ...theme import IconSize, Palette, Radius, Space
from .classes import CLASS_BG, CLASS_BORDER, CLASS_HELP, CLASS_TONES
from .rival_store import RivalStore
from .state import SWEEP_CLASSES, MoveResult, RivalMember, RivalTeam, TeamRating

RIGHT_MODES: tuple[tuple[str, str], ...] = (("all", "All opponents"), ("rival", "Rival team"))

# What each menu entry does; the view maps the keys to its handlers.
Action = Callable[[str], None]


def mode_switch(mode: str, on_change: Callable[[str], None]) -> ft.SegmentedButton:
    """The switch heading the right column; the view keeps one per panel, in sync."""
    return ft.SegmentedButton(
        segments=[ft.Segment(value=key, label=ft.Text(label)) for key, label in RIGHT_MODES],
        selected=[mode],
        show_selected_icon=False,
        on_change=lambda e: on_change((e.control.selected or [mode])[0]),
    )


def _hit(result: MoveResult | None, fallback: str) -> str:
    return f"{result.name} {result.min_pct:g}–{result.max_pct:g}%" if result else fallback


def assumed_note(member: RivalMember) -> str:
    """"Tournament set, not seen yet: item, moves", or "" when everything is known."""
    if not member.assumed:
        return ""
    order = ("item", "ability", "moves", "nature", "points")
    names = {"points": "stat points"}
    return "Tournament set, not seen yet: " + ", ".join(names.get(f, f) for f in order if f in member.assumed)


class RivalCard(ft.Container):
    """One rival member, in the opponents list's card look, from the Attacker's side."""

    def __init__(self, member: RivalMember, slot: int, *, name: str, rating: TeamRating | None, linked: bool, on_pick: Callable[[int], None]) -> None:
        super().__init__()
        p = member.pokemon
        self.slot = slot
        self.name = ft.Text(name, theme_style=ft.TextThemeStyle.BODY_MEDIUM, weight=ft.FontWeight.W_600, color=Palette.ON_SURFACE,
                            max_lines=1, overflow=ft.TextOverflow.ELLIPSIS, expand=True)
        head: list[ft.Control] = [self.name]
        note = assumed_note(member)
        self.assumed_mark = ft.Icon(ft.Icons.HELP_OUTLINE, size=14, color=Palette.ON_SURFACE_VARIANT, tooltip=note, visible=bool(note))
        head.append(self.assumed_mark)
        set_line = " · ".join(x for x in (p.item, p.ability) if x) or "No item or ability set"
        lines: list[ft.Control]
        if rating is not None:
            head.append(StatusChip(dict(SWEEP_CLASSES)[rating.klass], CLASS_TONES[rating.klass], tooltip=CLASS_HELP[rating.klass]))  # type: ignore[arg-type]
            speed = ft.Text(f"Spe {rating.their_speed} {'▲' if rating.faster else '▼'}", theme_style=ft.TextThemeStyle.LABEL_SMALL,
                            color=Palette.SUCCESS if rating.faster else Palette.ERROR,
                            tooltip="You move first" if rating.faster else ("Speed tie" if rating.your_speed == rating.their_speed else "They move first"))
            lines = [
                ft.Row(spacing=Space.XS, controls=[
                    speed,
                    ft.Text(f"You: {_hit(rating.your_best, 'no damage')}", theme_style=ft.TextThemeStyle.LABEL_SMALL, color=Palette.ON_SURFACE_VARIANT,
                            max_lines=1, overflow=ft.TextOverflow.ELLIPSIS, expand=True),
                ]),
                ft.Text(f"Them: {_hit(rating.their_best, 'no damaging move')}", theme_style=ft.TextThemeStyle.LABEL_SMALL, color=Palette.ON_SURFACE_VARIANT,
                        max_lines=1, overflow=ft.TextOverflow.ELLIPSIS),
            ]
            self.bgcolor = CLASS_BG.get(rating.klass, Palette.SURFACE_2)
            self.border = ft.Border.all(1, Palette.PRIMARY) if linked else CLASS_BORDER.get(rating.klass, ft.Border.all(1, Palette.OUTLINE_VARIANT))
        else:
            lines = [ft.Text(set_line, theme_style=ft.TextThemeStyle.LABEL_SMALL, color=Palette.ON_SURFACE_VARIANT, max_lines=1, overflow=ft.TextOverflow.ELLIPSIS)]
            self.bgcolor = Palette.SURFACE_3 if linked else Palette.SURFACE_2
            self.border = ft.Border.all(1, Palette.PRIMARY if linked else Palette.OUTLINE_VARIANT)
        self.content = ft.Row(spacing=Space.SM, vertical_alignment=ft.CrossAxisAlignment.CENTER, controls=[
            Sprite(get_pokemon_sprite_url(p.species or ""), size=36),
            ft.Column(spacing=1, tight=True, expand=True, controls=[
                ft.Row(spacing=Space.XS, vertical_alignment=ft.CrossAxisAlignment.CENTER, controls=head),
                *lines,
            ]),
        ])
        self.padding = ft.Padding.symmetric(horizontal=Space.SM, vertical=Space.XS)
        self.border_radius = Radius.SM
        self.ink = True
        tip = ["In the Defender panel" if linked else "Load as defender", set_line]
        if note:
            tip.append(note)
        self.tooltip = "\n".join(tip)
        self.on_click = lambda _e: on_pick(slot)


class RivalsPanel(ft.Container):
    def __init__(self, *, rivals: RivalStore, species_name: Callable[[str | None], str], accent: str,
                 on_pick: Callable[[int], None], on_action: Action) -> None:
        super().__init__()
        self.rivals = rivals
        self._species_name = species_name
        self._on_pick = on_pick
        self._on_action = on_action
        self._ratings: tuple[TeamRating | None, ...] = ()
        self._attacker = ""
        self._linked: int | None = None

        self._switch_slot = ft.Container()
        self._select = ft.Dropdown(label="Team", dense=True, text_size=12, expand=True, options=[],
                                   on_select=lambda e: self.rivals.set_active(e.control.value or None))
        # An icon trigger leaves the team names the width of the column.
        self._menu = ft.PopupMenuButton(icon=ft.Icons.MORE_VERT, tooltip="Rival team actions", items=[])
        self._preview = ft.FilledTonalButton("Team preview", icon=ft.Icons.BOLT, tooltip="Start a battle: enter the six Pokémon you see (Ctrl+B)",
                                             on_click=lambda _e: on_action("battle"))
        self._matrix = ft.OutlinedButton("Team vs team", icon=ft.Icons.GRID_VIEW, tooltip="Your team against theirs, every pairing",
                                         on_click=lambda _e: on_action("matrix"))
        # A saved plan is never changed by browsing it: edits to its member in the Defender
        # panel are kept only through this button (a battle team saves them by itself).
        self._update_member = ft.FilledTonalButton("", icon=ft.Icons.SAVE_AS_OUTLINED, visible=False,
                                                   tooltip="Keep the Defender's item, ability, moves, nature and stat points in this rival team",
                                                   on_click=lambda _e: on_action("update_member"))
        self._status = ft.Text("", theme_style=ft.TextThemeStyle.BODY_SMALL, color=Palette.ON_SURFACE_VARIANT)
        self._spinner = ft.ProgressRing(width=16, height=16, stroke_width=2, visible=False)
        self._list = ft.Column(spacing=Space.XS, tight=True, controls=[])
        self._empty = ft.Column(spacing=Space.SM, tight=True, horizontal_alignment=ft.CrossAxisAlignment.CENTER, visible=False, controls=[
            ft.Icon(ft.Icons.SPORTS_MMA_OUTLINED, size=IconSize.EMPTY_STATE, color=Palette.SECONDARY),
            ft.Text("No rival team yet", theme_style=ft.TextThemeStyle.BODY_LARGE, color=Palette.ON_SURFACE, text_align=ft.TextAlign.CENTER),
            ft.Text("Start a battle from team preview, paste a team, or save one from Meta (a team's calculator menu).",
                    theme_style=ft.TextThemeStyle.BODY_MEDIUM, color=Palette.ON_SURFACE_VARIANT, text_align=ft.TextAlign.CENTER),
            ft.FilledTonalButton("Team preview", icon=ft.Icons.BOLT, on_click=lambda _e: on_action("battle")),
            ft.TextButton("Paste a team", icon=ft.Icons.CONTENT_PASTE, on_click=lambda _e: on_action("paste")),
        ])
        self._controls_row = ft.Row(spacing=Space.SM, vertical_alignment=ft.CrossAxisAlignment.CENTER, controls=[self._select, self._menu])
        self._buttons_row = ft.Row(spacing=Space.SM, wrap=True, controls=[self._preview, self._matrix])
        help_text = "\n".join(
            ["Each member against the Attacker, from your side:"] + [f"{label}: {CLASS_HELP[key]}" for key, label in SWEEP_CLASSES]
            + ["", "? marks a tournament set that has not been seen yet.", "In a battle, what you set on the Defender (item, moves…) is saved to that member."]
        )
        self.content = ft.Column(spacing=Space.SM, controls=[
            self._switch_slot,
            SectionHeader("Rival team", accent=accent, action=ft.IconButton(icon=ft.Icons.HELP_OUTLINE, icon_size=IconSize.SM, tooltip=help_text)),
            self._controls_row, self._buttons_row, self._update_member,
            ft.Row(spacing=Space.SM, controls=[self._spinner, self._status]),
            self._empty,
            self._list,
        ])
        self.bgcolor = Palette.SURFACE_2
        self.border_radius = Radius.MD
        self.border = ft.Border.all(1, Palette.OUTLINE_VARIANT)
        self.padding = Space.MD

    def set_switch(self, switch: ft.Control) -> None:
        self._switch_slot.content = switch

    def set_scrolling(self, scrolling: bool) -> None:
        self._list.scroll = ft.ScrollMode.AUTO if scrolling else None
        self._list.expand = scrolling
        self._list.tight = not scrolling
        self.content.tight = not scrolling

    def set_busy(self, busy: bool) -> None:
        if busy != self._spinner.visible:
            self._spinner.visible = busy
            self._safe_update(self._spinner)

    def set_ratings(self, ratings: tuple[TeamRating | None, ...], attacker_name: str) -> None:
        self._ratings = ratings
        self._attacker = attacker_name
        self.render()

    def set_pending(self, name: str | None) -> None:
        """Offer "Save Defender to <name>" while a saved team's member was edited."""
        visible = name is not None
        label = f"Save Defender to {name}" if name else ""
        if visible != self._update_member.visible or label != self._update_member.content:
            self._update_member.visible = visible
            self._update_member.content = label
            self._safe_update(self._update_member)

    def set_linked(self, slot: int | None) -> None:
        if slot != self._linked:
            self._linked = slot
            self.render()

    # -- rendering -------------------------------------------------------------------------------

    def _menu_items(self, team: RivalTeam | None) -> list[ft.PopupMenuItem]:
        def item(label: str, icon: str, key: str) -> ft.PopupMenuItem:
            return ft.PopupMenuItem(content=ft.Text(label), icon=icon, on_click=lambda _e: self._on_action(key))

        items = [item("New battle (team preview)…", ft.Icons.BOLT, "battle"), item("New from paste / Poképaste…", ft.Icons.CONTENT_PASTE, "paste")]
        if team is None:
            return items
        items.append(ft.PopupMenuItem())   # divider
        if team.is_battle:
            items += [item("Save battle as rival team…", ft.Icons.SAVE_OUTLINED, "save_battle"), item("End battle", ft.Icons.STOP_CIRCLE_OUTLINED, "end_battle")]
        else:
            items += [item("Rename…", ft.Icons.EDIT_OUTLINED, "rename"), item("Duplicate", ft.Icons.COPY_ALL, "duplicate"),
                      item("Delete", ft.Icons.DELETE_OUTLINE, "delete")]
        return items

    def render(self) -> None:
        teams = self.rivals.teams
        team = self.rivals.active
        self._select.options = [ft.DropdownOption(key=t.rival_team_id, text=t.name) for t in teams]
        self._select.value = team.rival_team_id if team else None
        self._menu.items = self._menu_items(team)
        self._select.visible = bool(teams)
        self._matrix.disabled = team is None or not team.members
        self._empty.visible = team is None
        if team is None:
            self._list.controls = []
            self._status.value = ""
        else:
            ratings = self._ratings if len(self._ratings) == len(team.members) else ()
            self._list.controls = [
                RivalCard(m, i, name=self._species_name(m.pokemon.species), rating=ratings[i] if ratings else None,
                          linked=i == self._linked, on_pick=self._on_pick)
                for i, m in enumerate(team.members)
            ]
            guessed = sum(1 for m in team.members if m.assumed)
            parts = [f"{len(team.members)} Pokémon"]
            if ratings and self._attacker:
                parts.append(f"vs {self._attacker}")
            elif not self._attacker:
                parts.append("pick an attacker to rate them")
            if guessed:
                parts.append(f"{guessed} guessed")
            self._status.value = " · ".join(parts)
        self._safe_update(self)

    @staticmethod
    def _safe_update(control: ft.Control) -> None:
        try:
            if control.page is not None:
                control.update()
        except RuntimeError:
            pass


__all__ = ["RIGHT_MODES", "RivalCard", "RivalsPanel", "assumed_note", "mode_switch"]

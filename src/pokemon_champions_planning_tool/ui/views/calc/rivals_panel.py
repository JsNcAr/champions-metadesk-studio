"""The side panel's Rivals tab: a saved rival team or the "Current battle" team, each member
classified against the Attacker, one click to load it as the Defender."""

from __future__ import annotations

from collections.abc import Callable

import flet as ft

from ....domain.pokemon_identity import get_pokemon_sprite_url
from ...components import Sprite, StatusChip
from ...components.help_button import help_button
from ...components.section import SectionHeader
from ...theme import IconSize, Palette, Radius, Space
from .classes import CLASS_BG, CLASS_BORDER, CLASS_HELP, CLASS_TONES
from .rival_store import RivalStore
from .hit import hit_text
from .state import SWEEP_CLASSES, RivalMember, TeamRating

HELP_LINES: tuple[str, ...] = (
    "The rival team sits above the Defender: click a member to load it as the Defender (right-click: as the Attacker). Its menu holds "
    "team preview, loading, presets and the Team vs team grid; this tab lists the members in detail.",
    "The two kinds of rival team:",
    "Current battle: the team you are facing now. Team preview (Ctrl+B) takes the six species you see and fills each with its most "
    "used tournament set. What you set on a member in the Defender panel (item, ability, moves, nature, stat points) is kept for "
    "the rest of the battle.",
    "Presets: teams saved to plan against or to battle again. Save one from Load team… (a paste, a Poképaste link or one of your "
    "own teams), from a battle (the three-dot menu › Save battle as preset…) or from Meta (a team's calculator menu). Use in battle loads a preset "
    "into the Current battle and leaves the preset as saved. Browsing a preset never changes it: Save Defender to … does.",
    "Reading the cards:",
    "Each member is rated against your Attacker, from your side.",
    *(f"{label}: {CLASS_HELP[key]}." for key, label in SWEEP_CLASSES),
    "The ? mark lists the fields still guessed from tournament data. Click a member to load it as the Defender; your team strip "
    "then colours each of your Pokémon against it. Team vs team shows every pairing of your active team against theirs.",
)

# What each menu entry does; the view maps the keys to its handlers.
Action = Callable[[str], None]


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
                    ft.Text(f"You: {hit_text(rating.your_best, 'no damage')}", theme_style=ft.TextThemeStyle.LABEL_SMALL, color=Palette.ON_SURFACE_VARIANT,
                            max_lines=1, overflow=ft.TextOverflow.ELLIPSIS, expand=True),
                ]),
                ft.Text(f"Them: {hit_text(rating.their_best, 'no damaging move')}", theme_style=ft.TextThemeStyle.LABEL_SMALL, color=Palette.ON_SURFACE_VARIANT,
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
    """The side panel's Rivals tab: the rival team's members in detail (the strip above the
    Defender holds the team picker and every action)."""

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

        self._title = SectionHeader("Rival team", accent=accent, action=help_button("Rival teams", HELP_LINES, tooltip="How rival teams work"))
        self._status = ft.Text("", theme_style=ft.TextThemeStyle.BODY_SMALL, color=Palette.ON_SURFACE_VARIANT)
        self._spinner = ft.ProgressRing(width=16, height=16, stroke_width=2, visible=False)
        self._list = ft.Column(spacing=Space.XS, tight=True, controls=[])
        self._empty = ft.Column(spacing=Space.SM, tight=True, horizontal_alignment=ft.CrossAxisAlignment.CENTER, visible=False, controls=[
            ft.Icon(ft.Icons.SPORTS_MMA_OUTLINED, size=IconSize.EMPTY_STATE, color=Palette.SECONDARY),
            ft.Text("No rival team yet", theme_style=ft.TextThemeStyle.BODY_LARGE, color=Palette.ON_SURFACE, text_align=ft.TextAlign.CENTER),
            ft.Text("Start a battle from team preview, or load one of your teams, a paste or a Poképaste link. "
                    "Meta saves any tournament team as a preset from its calculator menu.",
                    theme_style=ft.TextThemeStyle.BODY_MEDIUM, color=Palette.ON_SURFACE_VARIANT, text_align=ft.TextAlign.CENTER),
            ft.FilledTonalButton("Team preview", icon=ft.Icons.BOLT, on_click=lambda _e: on_action("battle")),
            ft.TextButton("Load team…", icon=ft.Icons.FOLDER_OPEN_OUTLINED, on_click=lambda _e: on_action("load")),
        ])
        self.content = ft.Column(spacing=Space.SM, controls=[
            self._title,
            ft.Row(spacing=Space.SM, controls=[self._spinner, self._status]),
            self._empty,
            self._list,
        ])
        self.padding = 0

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

    def set_linked(self, slot: int | None) -> None:
        if slot != self._linked:
            self._linked = slot
            self.render()

    # -- rendering -------------------------------------------------------------------------------

    def render(self) -> None:
        team = self.rivals.active
        self._empty.visible = team is None
        self._title.set_label("Current battle" if team is not None and team.is_battle else (team.name if team is not None else "Rival team"))
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


__all__ = ["RivalCard", "RivalsPanel", "assumed_note"]

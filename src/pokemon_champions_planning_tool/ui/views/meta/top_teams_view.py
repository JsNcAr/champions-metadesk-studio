"""Meta's Top teams tab: every lineup ranked by usage, expanding to its item spread and
the teams that make it up. Reuses Meta's own filter bar; the actions (Import, Save as
rival, Damage calc vs…) are supplied by the view as plain callables so this module knows
nothing about the event bus or the import dialog."""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass

import flet as ft

from ....domain.pokemon_identity import get_pokemon_sprite_url
from ...components import EmptyState, Sprite, StatusChip, skeleton_rows
from ...format import absolute_time, plural
from ...tasks import is_mounted, open_url
from ...theme import IconSize, Motion, Palette, Radius, Space
from .top_teams import TopTeam, TopTeamEntry

_PAGE_SIZE = 20
_TEAM_LIST_LIMIT = 12


@dataclass
class TopTeamsActions:
    """What each button on a Top teams card does; supplied by MetaView."""

    import_team: Callable[[TopTeam], None]                 # the most common set
    import_entry: Callable[[TopTeamEntry], None]            # one player's team
    save_rival_team: Callable[[TopTeam], None]              # the most common set as a rival preset
    save_rival_entry: Callable[[TopTeamEntry], None]        # one player's team as a rival preset
    calc_vs_member: Callable[[TopTeam, int], None]          # the most common set's slot `index` as the Defender
    copy_team: Callable[[TopTeam], None]                    # the most common set as Showdown text


def _member_sprite(key: str, catalogs) -> Sprite:
    species = catalogs.species_for(key)
    is_mega = bool(species and species.is_mega)
    primary_type = species.types_lower[0] if species and species.types_lower else None
    return Sprite(get_pokemon_sprite_url(key), size=32, ring="mega" if is_mega else "type", primary_type=primary_type, tooltip=species.name if species else key)


def _member_name(key: str, catalogs) -> str:
    species = catalogs.species_for(key)
    return species.name if species else key.replace("-", " ").title()


def _trend_control(trend: float | None) -> ft.Control:
    if trend is None:
        return ft.Text("—", theme_style=ft.TextThemeStyle.LABEL_SMALL, color=Palette.ON_SURFACE_VARIANT, tooltip="Not enough recent data to show a trend")
    up = trend > 0
    arrow = "▲" if up else ("▼" if trend < 0 else "—")
    colour = Palette.SUCCESS if up else (Palette.ERROR if trend < 0 else Palette.ON_SURFACE_VARIANT)
    return ft.Text(f"{arrow} {trend:+.1f}", theme_style=ft.TextThemeStyle.LABEL_SMALL, color=colour,
                   tooltip="Share of teams in the last 30 days vs. the 30 days before, in percentage points")


class TopTeamCard(ft.Container):
    """One ranked lineup: usage, best finish, top-cut rate and trend, expanding to the
    item spread per member and the teams that brought it."""

    def __init__(self, team: TopTeam, *, rank: int, catalogs, actions: TopTeamsActions) -> None:
        super().__init__()
        self.team = team
        self._catalogs = catalogs
        self._actions = actions
        self._expanded = False
        self._body: ft.Control | None = None

        sprites = ft.Row(spacing=2, controls=[_member_sprite(key, catalogs) for key in team.members])
        bar = ft.Container(width=64, height=6, border_radius=Radius.PILL, bgcolor=Palette.SURFACE_3, content=ft.Container(
            width=max(2, round(64 * min(1.0, team.share))), height=6, border_radius=Radius.PILL, bgcolor=Palette.PRIMARY,
        ))
        share = ft.Text(f"{team.share:.1%}", theme_style=ft.TextThemeStyle.TITLE_SMALL, weight=ft.FontWeight.W_700, color=Palette.ON_SURFACE, width=52)
        count = ft.Text(plural(team.count, "team"), theme_style=ft.TextThemeStyle.BODY_SMALL, color=Palette.ON_SURFACE_VARIANT)
        best = ft.Text(
            f"{team.best.standing_label} · {team.best.tournament_name}", theme_style=ft.TextThemeStyle.BODY_SMALL, color=Palette.ON_SURFACE_VARIANT,
            max_lines=1, overflow=ft.TextOverflow.ELLIPSIS, expand=True, tooltip=f"{team.best.player_name} · {absolute_time(team.best.event_date)}",
        )
        top_cut = StatusChip(f"Top 8: {team.top_cut:.0%}", "info", tooltip="Share of this lineup's teams that placed top 8")

        calc_items = [
            ft.PopupMenuItem(content=ft.Text(f"Damage calc vs {_member_name(key, catalogs)}"), on_click=lambda _e, i=i: actions.calc_vs_member(team, i))
            for i, key in enumerate(team.members)
        ]
        menu = ft.PopupMenuButton(icon=ft.Icons.MORE_VERT, tooltip="More actions", items=[
            *calc_items, ft.PopupMenuItem(), ft.PopupMenuItem(content=ft.Text("Copy as Showdown text"), icon=ft.Icons.CONTENT_COPY, on_click=lambda _e: actions.copy_team(team)),
        ])
        self._chevron = ft.Icon(ft.Icons.EXPAND_MORE, size=IconSize.SM, color=Palette.ON_SURFACE_VARIANT)

        header = ft.Container(
            content=ft.Row(spacing=Space.MD, vertical_alignment=ft.CrossAxisAlignment.CENTER, controls=[
                ft.Text(f"#{rank}", theme_style=ft.TextThemeStyle.LABEL_LARGE, color=Palette.ON_SURFACE_VARIANT, width=32),
                sprites,
                ft.Column(spacing=2, tight=True, controls=[ft.Row(spacing=Space.SM, tight=True, controls=[share, bar]), count]),
                best,
                top_cut,
                _trend_control(team.trend),
                ft.IconButton(icon=ft.Icons.DOWNLOAD, icon_size=IconSize.MD, tooltip="Import the most common set", on_click=lambda _e: actions.import_team(team)),
                ft.IconButton(icon=ft.Icons.SPORTS_MMA_OUTLINED, icon_size=IconSize.MD, tooltip="Save the most common set as a rival preset", on_click=lambda _e: actions.save_rival_team(team)),
                menu,
                self._chevron,
            ]),
            height=56,
            padding=ft.Padding.symmetric(horizontal=Space.MD),
            on_click=lambda _e: self.toggle(),
            on_hover=self._hover,
            border_radius=Radius.SM,
            animate=ft.Animation(Motion.FAST_MS, Motion.CURVE),
        )
        self._header = header
        self._column = ft.Column(spacing=0, tight=True, controls=[header])
        self.content = self._column
        self.border = ft.Border.only(bottom=ft.BorderSide(1, Palette.OUTLINE_VARIANT))

    def _hover(self, e: ft.ControlEvent) -> None:
        hovering = getattr(e, "data", None) in ("true", True)
        self._header.bgcolor = Palette.SURFACE_3 if hovering else None
        if is_mounted(self._header):
            self._header.update()

    def toggle(self) -> None:
        self._expanded = not self._expanded
        self._chevron.name = ft.Icons.EXPAND_LESS if self._expanded else ft.Icons.EXPAND_MORE
        if self._expanded:
            if self._body is None:
                self._body = self._build_body()
            self._column.controls = [self._header, self._body]
        else:
            self._column.controls = [self._header]
        if is_mounted(self):
            self.update()

    def _build_body(self) -> ft.Control:
        team = self.team
        spread_rows: list[ft.Control] = []
        for key in team.members:
            spread = team.spread.get(key)
            caption_bits = [f"{name} {pct:.0%}" for name, pct in (spread.items if spread else ())]
            caption = " · ".join(caption_bits) or "No item"
            below = " · ".join(x for x in ((spread.ability if spread else None), (spread.nature if spread else None)) if x)
            spread_rows.append(ft.Row(spacing=Space.SM, vertical_alignment=ft.CrossAxisAlignment.CENTER, controls=[
                _member_sprite(key, self._catalogs),
                ft.Column(spacing=1, tight=True, expand=True, controls=[
                    ft.Text(_member_name(key, self._catalogs), theme_style=ft.TextThemeStyle.BODY_MEDIUM, color=Palette.ON_SURFACE),
                    ft.Text(caption, theme_style=ft.TextThemeStyle.BODY_SMALL, color=Palette.ON_SURFACE_VARIANT, max_lines=1, overflow=ft.TextOverflow.ELLIPSIS),
                    ft.Text(below, theme_style=ft.TextThemeStyle.LABEL_SMALL, color=Palette.ON_SURFACE_VARIANT, visible=bool(below)),
                ]),
            ]))

        team_rows = [self._team_row(entry) for entry in team.teams[:_TEAM_LIST_LIMIT]]
        remaining = len(team.teams) - _TEAM_LIST_LIMIT
        if remaining > 0:
            team_rows.append(ft.Text(f"+ {plural(remaining, 'more team')}", theme_style=ft.TextThemeStyle.BODY_SMALL, color=Palette.ON_SURFACE_VARIANT))

        return ft.Container(
            padding=ft.Padding.only(left=Space.MD, right=Space.MD, bottom=Space.MD, top=Space.XS),
            content=ft.ResponsiveRow(spacing=Space.LG, run_spacing=Space.MD, controls=[
                ft.Column(spacing=Space.XS, tight=True, col={"xs": 12, "lg": 6}, controls=[
                    ft.Text("ITEM SPREAD", theme_style=ft.TextThemeStyle.LABEL_SMALL, color=Palette.ON_SURFACE_VARIANT),
                    *spread_rows,
                ]),
                ft.Column(spacing=Space.XS, tight=True, col={"xs": 12, "lg": 6}, controls=[
                    ft.Text(f"TEAMS IN THIS GROUP · {plural(len(team.teams), 'team')}", theme_style=ft.TextThemeStyle.LABEL_SMALL, color=Palette.ON_SURFACE_VARIANT),
                    *team_rows,
                ]),
            ]),
        )

    def _team_row(self, entry: TopTeamEntry) -> ft.Control:
        controls: list[ft.Control] = [
            ft.Text(entry.standing_label, theme_style=ft.TextThemeStyle.LABEL_SMALL, color=Palette.ON_SURFACE_VARIANT, width=56),
            ft.Text(entry.player_name, theme_style=ft.TextThemeStyle.BODY_SMALL, color=Palette.ON_SURFACE, max_lines=1, overflow=ft.TextOverflow.ELLIPSIS, expand=True),
            ft.Text(absolute_time(entry.event_date).split(",")[0], theme_style=ft.TextThemeStyle.LABEL_SMALL, color=Palette.ON_SURFACE_VARIANT),
        ]
        if entry.pokepast_url:
            controls.append(ft.IconButton(icon=ft.Icons.OPEN_IN_NEW, icon_size=IconSize.SM, tooltip="Open Poképaste", on_click=lambda e, url=entry.pokepast_url: open_url(e.control.page, url)))
        controls.append(ft.IconButton(icon=ft.Icons.DOWNLOAD, icon_size=IconSize.SM, tooltip=f"Import {entry.player_name}'s team", on_click=lambda _e: self._actions.import_entry(entry)))
        controls.append(ft.IconButton(icon=ft.Icons.SPORTS_MMA_OUTLINED, icon_size=IconSize.SM, tooltip="Save as rival preset", on_click=lambda _e: self._actions.save_rival_entry(entry)))
        return ft.Row(spacing=Space.XS, vertical_alignment=ft.CrossAxisAlignment.CENTER, controls=controls)


class TopTeamsPanel(ft.Column):
    """The list of ranked lineups; ``reload()`` recomputes from the current filters."""

    def __init__(self, *, ctx, store, actions: TopTeamsActions) -> None:
        super().__init__(spacing=Space.SM, expand=True)
        self.ctx = ctx
        self.store = store
        self._actions = actions
        self._result = None
        self._limit = _PAGE_SIZE
        self._loading = False

        self._caption = ft.Text("", theme_style=ft.TextThemeStyle.BODY_SMALL, color=Palette.ON_SURFACE_VARIANT)
        self._progress = ft.ProgressBar(visible=False, bar_height=2, color=Palette.PRIMARY, bgcolor=Palette.OUTLINE_VARIANT)
        self._list = ft.ListView(expand=True, spacing=0, padding=ft.Padding.only(bottom=Space.XL))
        self.controls = [self._caption, self._progress, self._list]

    def reload(self) -> None:
        """Recompute from the current filters. A cache hit inside the store answers almost
        at once, so the skeleton only shows on the very first load — revisiting the tab
        with unchanged filters just quietly refreshes."""
        if self._loading:
            return
        self._loading = True
        self._limit = _PAGE_SIZE
        if self._result is None:
            self._list.controls = [skeleton_rows(6)]
            self._update_self()

        def work():
            return self.store.top_teams(catalogs=self.ctx.catalogs)

        def done(result) -> None:
            self._loading = False
            self._result = result
            self._render()

        def failed(exc: BaseException) -> None:
            self._loading = False
            self._list.controls = [EmptyState(ft.Icons.ERROR_OUTLINE, "Couldn't group tournament teams", str(exc), action_label="Retry", on_action=self.reload)]
            self._update_self()

        self.ctx.run_in_background(work, on_done=done, on_error=failed, spinner=self._progress)

    def _render(self) -> None:
        result = self._result
        if result is None:
            return
        bits = [plural(result.total_teams, "team"), f"{len(result.teams):,} lineup{'s' if len(result.teams) != 1 else ''} used twice or more"]
        if result.incomplete_teams:
            bits.append(f"{result.incomplete_teams} incomplete left out")
        self._caption.value = " · ".join(bits)
        if not result.teams:
            self._list.controls = [EmptyState(
                ft.Icons.GROUPS_OUTLINED, "No lineup repeats yet",
                "No two teams matching these filters share the same six Pokémon and Mega forms. Try a broader placement tier or a longer time window.",
            )]
            self._update_self()
            return
        shown = result.teams[: self._limit]
        self._list.controls = [TopTeamCard(team, rank=i + 1, catalogs=self.ctx.catalogs, actions=self._actions) for i, team in enumerate(shown)]
        if len(result.teams) > self._limit:
            remaining = len(result.teams) - self._limit
            self._list.controls.append(
                ft.Container(alignment=ft.Alignment.CENTER, padding=ft.Padding.symmetric(vertical=Space.SM),
                             content=ft.TextButton(f"Show more · {remaining} remaining", icon=ft.Icons.EXPAND_MORE, on_click=lambda _e: self._show_more()))
            )
        self._update_self()

    def _show_more(self) -> None:
        self._limit += _PAGE_SIZE
        self._render()

    def _update_self(self) -> None:
        if is_mounted(self):
            self.update()


__all__ = ["TopTeamCard", "TopTeamsActions", "TopTeamsPanel"]

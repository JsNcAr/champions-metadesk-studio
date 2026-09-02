"""Meta explorer rows: an event group header and a team row that expands to its sheet."""

from __future__ import annotations

from collections.abc import Callable

import flet as ft

from ....domain.event_tier import (
    TIER_COMMUNITY,
    TIER_EVENT_LABELS,
    TIER_INTERNATIONAL,
    TIER_REGIONAL,
    TIER_SPECIAL,
    TIER_WORLDS,
    is_official_tier,
)
from ....services.showdown_service import parse_showdown_text
from ....services.tournament_service import MetaTeamRow
from ...components import PlacementBadge, Sprite, StatusChip
from ...format import absolute_time, plural
from ...tasks import is_mounted
from ...theme import IconSize, Motion, Palette, Radius, Space, alpha


_TIER_TONES: dict[str, str] = {
    TIER_WORLDS: "primary",
    TIER_INTERNATIONAL: "tertiary",
    TIER_REGIONAL: "info",
    TIER_SPECIAL: "warning",
    TIER_COMMUNITY: "neutral",
}


def _tier_chip(tier: str) -> StatusChip:
    official = is_official_tier(tier)
    return StatusChip(
        TIER_EVENT_LABELS.get(tier, "Community"),
        _TIER_TONES.get(tier, "neutral"),
        icon=ft.Icons.VERIFIED if official else None,
        tooltip="Official Play! Pokémon event" if official else "Community-run event",
    )


class EventHeader(ft.Container):
    def __init__(self, row: MetaTeamRow, shown: int) -> None:
        super().__init__()
        self._count = ft.Text("", theme_style=ft.TextThemeStyle.BODY_SMALL, color=Palette.ON_SURFACE_VARIANT)
        meta_bits = [absolute_time(row.event_date).split(",")[0]]
        if row.organizer:
            meta_bits.append(row.organizer)
        if row.location:
            meta_bits.append(row.location)
        controls: list[ft.Control] = [
            ft.Icon(ft.Icons.EMOJI_EVENTS, size=IconSize.SM, color=Palette.TERTIARY),
            ft.Text(row.tournament_name, theme_style=ft.TextThemeStyle.BODY_LARGE, color=Palette.ON_SURFACE, max_lines=1, overflow=ft.TextOverflow.ELLIPSIS, expand=True, tooltip=row.tournament_name),
            _tier_chip(row.event_tier),
            StatusChip(row.regulation or "Unknown format", "tertiary"),
            ft.Text(" · ".join(meta_bits), theme_style=ft.TextThemeStyle.BODY_SMALL, color=Palette.ON_SURFACE_VARIANT),
            self._count,
        ]
        if row.source_url:
            controls.append(
                ft.IconButton(
                    icon=ft.Icons.OPEN_IN_NEW,
                    icon_size=IconSize.SM,
                    tooltip="Open event results",
                    on_click=lambda e, url=row.source_url: e.control.page.launch_url(url),
                )
            )
        self.content = ft.Row(spacing=Space.MD, vertical_alignment=ft.CrossAxisAlignment.CENTER, controls=controls)
        self.bgcolor = alpha(Palette.TERTIARY, 0.12)
        self.border = ft.Border.only(left=ft.BorderSide(3, Palette.TERTIARY))
        self.border_radius = Radius.SM
        self.padding = ft.Padding.symmetric(horizontal=Space.MD, vertical=Space.SM)
        self.margin = ft.Margin.only(top=Space.SM)
        self.total_players = row.total_players
        self.set_shown(shown)

    def set_shown(self, shown: int) -> None:
        if self.total_players:
            self._count.value = f"{shown} of {self.total_players:,} players"
        else:
            self._count.value = plural(shown, "team")


class TeamRow(ft.Container):
    """48px row: placement · player · six sprites · legality · Poképaste · Import."""

    def __init__(self, row: MetaTeamRow, *, on_import: Callable[[MetaTeamRow], None]) -> None:
        super().__init__()
        self.row = row
        self._on_import = on_import
        self._expanded = False
        self._details: ft.Control | None = None

        sprites = ft.Row(
            spacing=4,
            controls=[
                Sprite(m.sprite_url, size=32, ring="none" if m.is_legal else "error",
                       tooltip=m.species_name if m.is_legal else f"{m.species_name} — not in the Champions Pokédex")
                for m in row.members
            ],
        )
        if not row.legality_known:
            legality = StatusChip("Legality unknown", "neutral")
        elif row.is_legal:
            legality = StatusChip("Champions-legal", "success", icon=ft.Icons.CHECK)
        else:
            n = len(row.illegal_species)
            legality = StatusChip(f"{n} illegal", "error", icon=ft.Icons.BLOCK, tooltip=", ".join(row.illegal_species))

        actions: list[ft.Control] = []
        if row.pokepast_url:
            actions.append(ft.IconButton(icon=ft.Icons.OPEN_IN_NEW, icon_size=IconSize.MD, tooltip="Open Poképaste", on_click=lambda e, url=row.pokepast_url: e.control.page.launch_url(url)))
        if row.legality_known and not row.is_legal:
            actions.append(ft.OutlinedButton("Can't import", disabled=True, tooltip="Contains species outside the Champions Pokédex"))
        else:
            actions.append(ft.FilledTonalButton("Import", icon=ft.Icons.DOWNLOAD, on_click=lambda _e: self._on_import(self.row)))

        self._chevron = ft.Icon(ft.Icons.EXPAND_MORE, size=IconSize.SM, color=Palette.ON_SURFACE_VARIANT)
        self._summary = ft.Container(
            content=ft.Row(
                spacing=Space.MD,
                vertical_alignment=ft.CrossAxisAlignment.CENTER,
                controls=[
                    PlacementBadge(row.placement, row.standing_label if row.standing_label and not row.standing_label.startswith("Place #") else ""),
                    ft.Text(row.player_name, theme_style=ft.TextThemeStyle.BODY_LARGE, color=Palette.ON_SURFACE, max_lines=1, overflow=ft.TextOverflow.ELLIPSIS, width=180, tooltip=row.player_name),
                    sprites,
                    ft.Container(expand=True),
                    legality,
                    ft.Row(spacing=Space.XS, controls=actions),
                    self._chevron,
                ],
            ),
            height=48,
            padding=ft.Padding.symmetric(horizontal=Space.MD),
            on_click=lambda _e: self.toggle(),
            on_hover=self._hover,
            border_radius=Radius.SM,
            animate=ft.Animation(Motion.FAST_MS, Motion.CURVE),
        )
        self._body = ft.Column(spacing=0, tight=True, controls=[self._summary])
        self.content = self._body
        self.border = ft.Border.only(bottom=ft.BorderSide(1, Palette.OUTLINE_VARIANT))

    def _hover(self, e: ft.ControlEvent) -> None:
        hovering = getattr(e, "data", None) in ("true", True)
        self._summary.bgcolor = Palette.SURFACE_3 if hovering else None
        if is_mounted(self._summary):
            self._summary.update()

    def toggle(self) -> None:
        self._expanded = not self._expanded
        self._chevron.name = ft.Icons.EXPAND_LESS if self._expanded else ft.Icons.EXPAND_MORE
        if self._expanded:
            if self._details is None:
                self._details = self._build_details()
            self._body.controls = [self._summary, self._details]
        else:
            self._body.controls = [self._summary]
        if is_mounted(self):
            self.update()

    def _build_details(self) -> ft.Control:
        # The sheet is only stored as Showdown text; parse it lazily on first expand.
        # Parsed slots and stored members share the same order.
        parsed = parse_showdown_text(self.row.showdown_text)
        slots = list(parsed.slots)
        cards: list[ft.Control] = []
        for index, member in enumerate(self.row.members):
            slot = slots[index] if index < len(slots) else None
            lines: list[ft.Control] = [
                ft.Text(member.species_name, theme_style=ft.TextThemeStyle.BODY_LARGE, color=Palette.ON_SURFACE),
            ]
            if slot is not None:
                bits = []
                if slot.item_name:
                    bits.append(f"@ {slot.item_name}")
                if slot.ability_name:
                    bits.append(slot.ability_name)
                if slot.tera_type:
                    bits.append(f"Tera {slot.tera_type}")
                if bits:
                    lines.append(ft.Text(" · ".join(bits), theme_style=ft.TextThemeStyle.BODY_SMALL, color=Palette.ON_SURFACE_VARIANT))
                moves = list(slot.moves or ())
                if moves:
                    lines.append(ft.Text(" / ".join(moves), theme_style=ft.TextThemeStyle.BODY_SMALL, color=Palette.ON_SURFACE_VARIANT, max_lines=2))
            cards.append(
                ft.Container(
                    content=ft.Row(
                        spacing=Space.SM,
                        vertical_alignment=ft.CrossAxisAlignment.START,
                        controls=[Sprite(member.sprite_url, size=40), ft.Column(spacing=2, tight=True, controls=lines, expand=True)],
                    ),
                    bgcolor=Palette.SURFACE_2,
                    border_radius=Radius.SM,
                    padding=Space.SM,
                    col={"xs": 12, "sm": 6, "lg": 4},
                )
            )
        return ft.Container(
            content=ft.ResponsiveRow(controls=cards, spacing=Space.SM, run_spacing=Space.SM),
            padding=ft.Padding.only(left=Space.MD, right=Space.MD, bottom=Space.MD, top=Space.XS),
        )

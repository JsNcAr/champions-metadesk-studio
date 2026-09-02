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


EVENT_CARD_MAX_EXTENT = 340
EVENT_CARD_HEIGHT = 292


def _event_meta_bits(row: MetaTeamRow) -> list[str]:
    bits = [absolute_time(row.event_date).split(",")[0]]
    if row.organizer:
        bits.append(row.organizer)
    if row.location:
        bits.append(row.location)
    return bits


def _member_sprite(m, size: int) -> Sprite:
    if not m.is_legal:
        return Sprite(m.sprite_url, size=size, ring="error", tooltip=f"{m.species_name} — not in the Champions Pokédex")
    if m.in_box is False:
        return Sprite(m.sprite_url, size=size, ring="missing", tooltip=f"{m.species_name} — not in your box")
    return Sprite(m.sprite_url, size=size, ring="none", tooltip=m.species_name)


def _box_chip(row: MetaTeamRow) -> StatusChip | None:
    """"6/6 in box" (success), "5/6" (info), fewer (neutral); None when no box is known."""
    label = row.box_label
    if label is None or not row.members:
        return None
    missing = row.missing_count or 0
    tone = "success" if missing == 0 else ("info" if missing == 1 else "neutral")
    lacking = [m.species_name for m in row.members if m.in_box is False]
    return StatusChip(label, tone, icon=ft.Icons.INVENTORY_2_OUTLINED, tooltip=("Missing: " + ", ".join(lacking)) if lacking else "Every member is in your box")


class EventHeader(ft.Container):
    def __init__(self, row: MetaTeamRow, shown: int, *, on_toggle: Callable[[], None] | None = None) -> None:
        super().__init__()
        self._count = ft.Text("", theme_style=ft.TextThemeStyle.BODY_SMALL, color=Palette.ON_SURFACE_VARIANT)
        self._toggle = ft.TextButton(
            "Show more", icon=ft.Icons.EXPAND_MORE, visible=False,
            on_click=(lambda _e: on_toggle()) if on_toggle else None,
        )
        meta_bits = _event_meta_bits(row)
        controls: list[ft.Control] = [
            ft.Icon(ft.Icons.EMOJI_EVENTS, size=IconSize.SM, color=Palette.TERTIARY),
            # Weighted: the name keeps three fifths of the free width, the caption two, so a
            # narrow window shortens both instead of squeezing the name to one letter.
            ft.Text(row.tournament_name, theme_style=ft.TextThemeStyle.BODY_LARGE, color=Palette.ON_SURFACE, max_lines=1, overflow=ft.TextOverflow.ELLIPSIS, expand=3, tooltip=row.tournament_name),
            _tier_chip(row.event_tier),
            StatusChip(row.regulation or "Unknown format", "tertiary"),
            ft.Text(" · ".join(meta_bits), theme_style=ft.TextThemeStyle.BODY_SMALL, color=Palette.ON_SURFACE_VARIANT, max_lines=1, overflow=ft.TextOverflow.ELLIPSIS, expand=2, tooltip=" · ".join(meta_bits)),
            self._count,
            self._toggle,
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

    def set_collapsed(self, collapsed: bool, hidden: int) -> None:
        """Toggle label: "Show 7 more" while collapsed, "Show less" while open."""
        self._toggle.visible = hidden > 0 or not collapsed
        self._toggle.content = f"Show {hidden} more" if collapsed else "Show less"
        self._toggle.icon = ft.Icons.EXPAND_MORE if collapsed else ft.Icons.EXPAND_LESS


class EventGroup(ft.Column):
    """One event in the list: header plus its team rows, collapsible to the winner."""

    def __init__(self, header: EventHeader) -> None:
        super().__init__(spacing=0, tight=True)
        self.header = header
        self.rows: list[TeamRow] = []
        self.collapsed = False
        self._rows_column = ft.Column(spacing=0, tight=True)
        self.controls = [header, self._rows_column]

    @property
    def first_row(self) -> MetaTeamRow:
        return self.rows[0].row

    def add_row(self, row: "TeamRow") -> None:
        self.rows.append(row)
        self.header.set_shown(len(self.rows))
        self.set_collapsed(self.collapsed)

    def set_collapsed(self, collapsed: bool) -> None:
        self.collapsed = collapsed
        self._rows_column.controls = self.rows[:1] if collapsed else list(self.rows)
        self.header.set_collapsed(collapsed, max(0, len(self.rows) - 1))


class EventCard(ft.Container):
    """Event as a card: tier, name, winner's roster; click to open the whole standings."""

    def __init__(self, row: MetaTeamRow, shown: int, *, on_open: Callable[[str], None], on_import: Callable[[MetaTeamRow], None]) -> None:
        super().__init__()
        self.row = row
        self._count = ft.Text("", theme_style=ft.TextThemeStyle.BODY_SMALL, color=Palette.ON_SURFACE_VARIANT)
        winner_actions: list[ft.Control] = []
        if not row.legality_known or row.is_legal:
            winner_actions.append(ft.IconButton(icon=ft.Icons.DOWNLOAD, icon_size=IconSize.MD, tooltip=f"Import {row.player_name}'s team", on_click=lambda _e: on_import(self.row)))
        caption_bits = [row.regulation or "Unknown format"]
        if row.total_players:
            caption_bits.append(f"{row.total_players:,} players")
        if row.location:
            caption_bits.append(row.location)
        self.content = ft.Column(
            spacing=Space.SM,
            tight=True,
            controls=[
                ft.Row(alignment=ft.MainAxisAlignment.SPACE_BETWEEN, vertical_alignment=ft.CrossAxisAlignment.CENTER, controls=[
                    _tier_chip(row.event_tier),
                    ft.Text(absolute_time(row.event_date).split(",")[0], theme_style=ft.TextThemeStyle.BODY_SMALL, color=Palette.ON_SURFACE_VARIANT),
                ]),
                ft.Text(row.tournament_name, theme_style=ft.TextThemeStyle.BODY_LARGE, color=Palette.ON_SURFACE, max_lines=2, overflow=ft.TextOverflow.ELLIPSIS, tooltip=row.tournament_name),
                ft.Text(" · ".join(caption_bits), theme_style=ft.TextThemeStyle.BODY_SMALL, color=Palette.ON_SURFACE_VARIANT, max_lines=1, overflow=ft.TextOverflow.ELLIPSIS),
                ft.Row(spacing=Space.SM, vertical_alignment=ft.CrossAxisAlignment.CENTER, controls=[
                    PlacementBadge(row.placement, row.standing_label if row.standing_label and not row.standing_label.startswith("Place #") else ""),
                    ft.Text(row.player_name, theme_style=ft.TextThemeStyle.BODY_MEDIUM, weight=ft.FontWeight.W_600, color=Palette.ON_SURFACE, max_lines=1, overflow=ft.TextOverflow.ELLIPSIS, expand=True, tooltip=row.player_name),
                    *winner_actions,
                ]),
                ft.Row(spacing=4, controls=[_member_sprite(m, 36) for m in row.members]),
                *([ft.Row(controls=[_box_chip(row)])] if _box_chip(row) is not None else []),
                ft.Row(alignment=ft.MainAxisAlignment.SPACE_BETWEEN, vertical_alignment=ft.CrossAxisAlignment.CENTER, controls=[
                    self._count,
                    ft.TextButton("View standings", icon=ft.Icons.LIST_ALT, on_click=lambda _e: on_open(self.row.tournament_id)),
                ]),
            ],
        )
        self.bgcolor = Palette.SURFACE_2
        self.border = ft.Border.all(1, Palette.OUTLINE_VARIANT)
        self.border_radius = Radius.MD
        self.padding = Space.CARD_PADDING
        self.ink = True
        self.animate = ft.Animation(Motion.FAST_MS, Motion.CURVE)
        self.on_click = lambda _e: on_open(self.row.tournament_id)
        self.on_hover = self._hover
        self.set_shown(shown)

    def set_shown(self, shown: int) -> None:
        self._count.value = f"{shown} of {self.row.total_players:,} players" if self.row.total_players else plural(shown, "team")

    def _hover(self, e: ft.ControlEvent) -> None:
        hovering = getattr(e, "data", None) in ("true", True)
        self.bgcolor = Palette.SURFACE_3 if hovering else Palette.SURFACE_2
        self.border = ft.Border.all(1, Palette.OUTLINE if hovering else Palette.OUTLINE_VARIANT)
        if is_mounted(self):
            self.update()


class EventDialog(ft.AlertDialog):
    """Whole standings of one event, every placement, with the same team rows."""

    def __init__(self, first: MetaTeamRow, *, on_import: Callable[[MetaTeamRow], None], on_close: Callable[[], None]) -> None:
        super().__init__(modal=False, scrollable=False)
        self._on_import = on_import
        self._list = ft.ListView(spacing=0, expand=True)
        self._status = ft.Text("Loading standings…", theme_style=ft.TextThemeStyle.BODY_SMALL, color=Palette.ON_SURFACE_VARIANT)
        self._spinner = ft.ProgressRing(width=16, height=16, stroke_width=2)
        meta = _event_meta_bits(first)
        header_controls: list[ft.Control] = [
            _tier_chip(first.event_tier),
            StatusChip(first.regulation or "Unknown format", "tertiary"),
            ft.Text(" · ".join(meta), theme_style=ft.TextThemeStyle.BODY_SMALL, color=Palette.ON_SURFACE_VARIANT, expand=True),
        ]
        if first.source_url:
            header_controls.append(ft.TextButton("Open results", icon=ft.Icons.OPEN_IN_NEW, on_click=lambda e, url=first.source_url: e.control.page.launch_url(url)))
        self.title = ft.Text(first.tournament_name, max_lines=2, overflow=ft.TextOverflow.ELLIPSIS)
        self.content = ft.Container(
            width=960,
            height=560,
            content=ft.Column(
                spacing=Space.SM,
                controls=[
                    ft.Row(spacing=Space.SM, vertical_alignment=ft.CrossAxisAlignment.CENTER, controls=header_controls),
                    ft.Row(spacing=Space.SM, controls=[self._spinner, self._status]),
                    self._list,
                ],
            ),
        )
        self.actions = [ft.TextButton("Close", on_click=lambda _e: on_close())]
        self.actions_alignment = ft.MainAxisAlignment.END

    def set_rows(self, rows: list[MetaTeamRow]) -> None:
        self._list.controls = [TeamRow(r, on_import=self._on_import) for r in rows]
        self._spinner.visible = False
        self._status.value = plural(len(rows), "team") + " · best placement first"
        if is_mounted(self):
            self.update()

    def set_error(self, exc: BaseException) -> None:
        self._spinner.visible = False
        self._status.value = f"Couldn't load standings: {exc}"
        self._status.color = Palette.ERROR
        if is_mounted(self):
            self.update()


class TeamRow(ft.Container):
    """48px row: placement · player · six sprites · legality · Poképaste · Import."""

    def __init__(self, row: MetaTeamRow, *, on_import: Callable[[MetaTeamRow], None]) -> None:
        super().__init__()
        self.row = row
        self._on_import = on_import
        self._expanded = False
        self._details: ft.Control | None = None

        sprites = ft.Row(spacing=4, controls=[_member_sprite(m, 32) for m in row.members])
        box_chip = _box_chip(row)
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
                    *([box_chip] if box_chip is not None else []),
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

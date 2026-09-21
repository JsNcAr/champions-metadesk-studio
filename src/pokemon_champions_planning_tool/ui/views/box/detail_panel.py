"""Box detail panel: forms, stats, abilities, defensive matchups, notes, tags, actions."""

from __future__ import annotations

from collections.abc import Callable
from uuid import UUID

import flet as ft

from ....domain.type_chart import BUCKETS
from ...components import SectionHeader, Sprite
from ...components.banner import InlineBanner
from ...components.pokemon import BstPill, SidePanel, StatBlock, TypeChip
from ...tasks import is_mounted
from ...theme import Accent, IconSize, Palette, Space
from .store import BoxDetail

_BUCKET_LABELS: dict[float, str] = {4.0: "4×", 2.0: "2×", 1.0: "1×", 0.5: "½×", 0.25: "¼×", 0.0: "0×"}
_BUCKET_COLOURS: dict[float, str] = {
    4.0: Palette.ERROR, 2.0: Palette.ERROR, 1.0: Palette.ON_SURFACE_VARIANT,
    0.5: Palette.SUCCESS, 0.25: Palette.SUCCESS, 0.0: Palette.SECONDARY,
}


class DetailPanel(SidePanel):
    def __init__(
        self,
        *,
        on_close: Callable[[], None],
        on_form: Callable[[str], None],
        on_favorite: Callable[[UUID, bool], None],
        on_notes: Callable[[UUID, str], None],
        on_tags: Callable[[UUID, list[str]], None],
        on_toggle_planned: Callable[[UUID, bool], None],
        on_delete: Callable[[UUID], None],
        on_add_to_team: Callable[[UUID, UUID | None], None] | None = None,
        on_calc: Callable[[], None] | None = None,
        on_refresh: Callable[[UUID], None] | None = None,
    ) -> None:
        super().__init__("Details", on_close=on_close, accent=Accent.BOX)
        self.detail: BoxDetail | None = None
        self.form_id: str | None = None
        self._on_form = on_form
        self._on_favorite = on_favorite
        self._on_notes = on_notes
        self._on_tags = on_tags
        self._on_toggle_planned = on_toggle_planned
        self._on_delete = on_delete
        self._show_neutral = False

        self.sprite = Sprite(size=96)
        # Flet requires at least one segment even while hidden, so keep a placeholder.
        self._forms = ft.SegmentedButton(
            selected=["base"],
            allow_multiple_selection=False,
            allow_empty_selection=False,
            show_selected_icon=False,
            segments=[ft.Segment(value="base", label=ft.Text("Base"))],
            visible=False,
            on_change=lambda e: self._on_form(next(iter(e.control.selected or ["base"]))),
        )
        self._types = ft.Row(spacing=Space.XS, alignment=ft.MainAxisAlignment.CENTER, tight=True)
        self._subtitle = ft.Text("", theme_style=ft.TextThemeStyle.BODY_SMALL, color=Palette.ON_SURFACE_VARIANT, text_align=ft.TextAlign.CENTER)
        self._bst = BstPill()
        self._star = ft.IconButton(icon=ft.Icons.STAR_BORDER, icon_size=IconSize.MD, tooltip="Favourite", on_click=lambda _e: self._toggle_favorite())
        self._stats = StatBlock()
        self._abilities = ft.Row(spacing=Space.XS, wrap=True, tight=True)
        self._defensive = ft.Column(spacing=Space.XS, tight=True)
        self._teams = ft.Text("", theme_style=ft.TextThemeStyle.BODY_SMALL, color=Palette.ON_SURFACE_VARIANT, visible=False)
        self._notes_header = SectionHeader("Notes", accent=Accent.BOX)
        self._notes = ft.TextField(
            multiline=True, min_lines=2, max_lines=5, dense=True, hint_text="Nickname, role, reminders…",
            on_blur=lambda e: self._save_notes(e.control.value or ""),
        )
        self._tags = ft.Row(spacing=Space.XS, wrap=True, tight=True)
        self._tag_input = ft.TextField(hint_text="Add tag…", dense=True, width=160, on_submit=lambda e: self._add_tag(e.control.value or ""))
        self._planned_button = ft.OutlinedButton("Mark as planned", icon=ft.Icons.EDIT_NOTE, on_click=lambda _e: self._toggle_planned())
        self._on_refresh = on_refresh
        self._refresh_banner = InlineBanner(visible=False)
        self._refresh_button = ft.FilledTonalButton("Refresh data", icon=ft.Icons.REFRESH, visible=False,
                                                    on_click=lambda _e: self._on_refresh(self.detail.entry.box_entry_id) if (self._on_refresh and self.detail) else None)
        self._on_add_to_team = on_add_to_team
        self._team_items: list[ft.PopupMenuItem] = []
        self._add_to_team = ft.PopupMenuButton(
            content=ft.FilledTonalButton("Add to team", icon=ft.Icons.GROUP_ADD),
            items=[],
            tooltip="Add to a team's first empty slot",
            visible=on_add_to_team is not None,
        )
        self._calc_button = ft.FilledTonalButton("Damage calc", icon=ft.Icons.CALCULATE_OUTLINED, visible=on_calc is not None,
                                                 tooltip="Open in the damage calculator", on_click=lambda _e: on_calc() if on_calc else None)
        self._delete_button = ft.TextButton(
            "Remove from box", icon=ft.Icons.DELETE_OUTLINE,
            style=ft.ButtonStyle(color=Palette.ERROR),
            on_click=lambda _e: self._on_delete(self.detail.entry.box_entry_id) if self.detail else None,
        )

        self.body.controls = [
            ft.Column(
                spacing=Space.SM,
                horizontal_alignment=ft.CrossAxisAlignment.CENTER,
                tight=True,
                controls=[self.sprite, self._forms, self._types, self._subtitle,
                          ft.Row(spacing=Space.SM, alignment=ft.MainAxisAlignment.CENTER, controls=[self._bst, self._star])],
            ),
            ft.Column(spacing=Space.SM, tight=True, controls=[SectionHeader("Stats", accent=Accent.BOX), self._stats]),
            ft.Column(spacing=Space.SM, tight=True, controls=[SectionHeader("Abilities", accent=Accent.BOX), self._abilities]),
            ft.Column(spacing=Space.SM, tight=True, controls=[SectionHeader("Defensive", accent=Accent.BOX), self._defensive]),
            ft.Column(spacing=Space.SM, tight=True, controls=[self._notes_header, self._notes]),
            ft.Column(spacing=Space.SM, tight=True, controls=[SectionHeader("Tags", accent=Accent.BOX), self._tags, self._tag_input]),
            self._teams,
            self._refresh_banner,
            self._refresh_button,
            self._add_to_team,
            self._calc_button,
            ft.Row(alignment=ft.MainAxisAlignment.SPACE_BETWEEN, controls=[self._planned_button, self._delete_button]),
            ft.Container(height=Space.XL),
        ]

    # -- model -> controls --------------------------------------------------------------------

    def update_from(self, detail: BoxDetail, form_id: str | None = None) -> None:
        self.detail = detail
        self.form_id = form_id or "base"
        entry = detail.entry
        pokemon = entry.pokemon
        form = detail.form(self.form_id)

        self.set_title(pokemon.qualified_name)
        self.sprite.set_src(form.sprite_url or pokemon.sprite_url)
        self.sprite.set_tooltip(form.label)
        self.sprite.set_ring("planned" if entry.is_planned else ("mega" if form.is_mega else "type"), form.types[0] if form.types else None)

        self._forms.visible = len(detail.forms) > 1
        self._forms.segments = [ft.Segment(value=f.form_id, label=ft.Text(f.label)) for f in detail.forms] or [
            ft.Segment(value="base", label=ft.Text("Base"))
        ]
        self._forms.selected = [self.form_id if any(f.form_id == self.form_id for f in detail.forms) else "base"]

        self._types.controls = [TypeChip(t) for t in form.types]
        dex = f"#{pokemon.dex_number:03d}" if pokemon.dex_number else "#???"
        self._subtitle.value = f"{dex} · {form.label}" if form.is_mega else f"{dex} · {pokemon.form_name or 'Base'}"
        base_total = pokemon.total
        self._bst.set_total(form.stats.total, (form.stats.total - base_total) if form.is_mega else None)
        self._star.icon = ft.Icons.STAR if entry.is_favorite else ft.Icons.STAR_BORDER
        self._star.icon_color = Palette.PRIMARY if entry.is_favorite else Palette.ON_SURFACE_VARIANT

        self._stats.set_stats(form.stats)
        if form.is_mega and form.ability:
            self._abilities.controls = [
                ft.Chip(
                    label=ft.Text(form.ability),
                    show_checkmark=False,
                )
            ]
        else:
            self._abilities.controls = [
                ft.Chip(
                    label=ft.Text(a.name.replace("-", " ").title()),
                    leading=ft.Icon(ft.Icons.VISIBILITY_OFF, size=16) if a.is_hidden else None,
                    tooltip="Hidden ability" if a.is_hidden else None,
                    show_checkmark=False,
                )
                for a in pokemon.abilities
            ] or [ft.Text("No ability data", theme_style=ft.TextThemeStyle.BODY_SMALL, color=Palette.ON_SURFACE_VARIANT)]
        self._render_defensive(detail.defensive_buckets(self.form_id))

        self._notes.value = entry.notes or ""
        self._notes_header.set_status(None)
        self._render_tags(entry.tags)
        self._planned_button.content = "Mark as owned" if entry.is_planned else "Mark as planned"
        self._planned_button.icon = ft.Icons.INVENTORY_2_OUTLINED if entry.is_planned else ft.Icons.EDIT_NOTE
        if detail.teams:
            self._teams.value = "On teams: " + ", ".join(f"{name} (slot {slot})" for name, slot in detail.teams)
            self._teams.visible = True
        else:
            self._teams.visible = False
        self.set_incomplete(entry.pokemon.is_stub)
        self.visible = True

    def _render_defensive(self, buckets: dict[float, list[str]]) -> None:
        rows: list[ft.Control] = []
        for mult in BUCKETS:
            types = buckets.get(mult, [])
            if not types:
                continue
            if mult == 1.0 and not self._show_neutral:
                rows.append(ft.TextButton(f"1× · {len(types)} types", on_click=lambda _e: self._toggle_neutral()))
                continue
            rows.append(
                ft.Row(
                    spacing=Space.SM,
                    vertical_alignment=ft.CrossAxisAlignment.START,
                    controls=[
                        ft.Text(_BUCKET_LABELS[mult], theme_style=ft.TextThemeStyle.LABEL_MEDIUM, weight=ft.FontWeight.W_600, color=_BUCKET_COLOURS[mult], width=32),
                        ft.Row(spacing=Space.XS, wrap=True, tight=True, expand=True, controls=[TypeChip(t, size="sm") for t in types]),
                    ],
                )
            )
        self._defensive.controls = rows

    def _render_tags(self, tags: list[str]) -> None:
        self._tags.controls = [
            ft.Chip(label=ft.Text(tag), on_delete=lambda _e, tag=tag: self._remove_tag(tag), show_checkmark=False)
            for tag in tags
        ]

    # -- interaction ----------------------------------------------------------------------------

    def _toggle_neutral(self) -> None:
        self._show_neutral = not self._show_neutral
        if self.detail:
            self._render_defensive(self.detail.defensive_buckets(self.form_id))
            if is_mounted(self):
                self.update()

    def _toggle_favorite(self) -> None:
        if self.detail:
            self._on_favorite(self.detail.entry.box_entry_id, not self.detail.entry.is_favorite)

    def _save_notes(self, text: str) -> None:
        if self.detail and text != (self.detail.entry.notes or ""):
            self._on_notes(self.detail.entry.box_entry_id, text)
            self._notes_header.set_status("Saved", color=Palette.SUCCESS)
            if is_mounted(self._notes_header):
                self._notes_header.update()

    def _add_tag(self, text: str) -> None:
        if not self.detail:
            return
        new = [t.strip() for t in text.split(",") if t.strip()]
        if not new:
            return
        self._tag_input.value = ""
        self._on_tags(self.detail.entry.box_entry_id, list(self.detail.entry.tags) + new)

    def _remove_tag(self, tag: str) -> None:
        if self.detail:
            self._on_tags(self.detail.entry.box_entry_id, [t for t in self.detail.entry.tags if t != tag])

    def _toggle_planned(self) -> None:
        if self.detail:
            self._on_toggle_planned(self.detail.entry.box_entry_id, not self.detail.entry.is_planned)

    def set_incomplete(self, incomplete: bool) -> None:
        self._refresh_button.visible = incomplete and self._on_refresh is not None
        if incomplete:
            self._refresh_banner.show("No PokéAPI data is stored for this Pokémon (types and stats are missing). Refresh to fetch it.", "warning")
        else:
            self._refresh_banner.hide()

    def set_team_options(self, options: list[tuple[UUID | None, str]]) -> None:
        """(team id or None for "New team…", label) rows for the Add to team menu."""
        entry_id = self.detail.entry.box_entry_id if self.detail else None
        self._add_to_team.items = [
            ft.PopupMenuItem(content=ft.Text(label), icon=ft.Icons.ADD if team_id is None else None,
                             on_click=lambda _e, team_id=team_id: self._on_add_to_team(entry_id, team_id) if (self._on_add_to_team and entry_id) else None)
            for team_id, label in options
        ]

    def clear(self) -> None:
        self.detail = None
        self.visible = False

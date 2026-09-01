"""Box card: what a roster entry shows at a glance. One long-lived instance per entry."""

from __future__ import annotations

from collections.abc import Callable
from uuid import UUID

import flet as ft

from ....domain.entities.box_entry import BoxEntry
from ...components import Sprite, StatusChip
from ...components.pokemon import BstPill, StatBlock, TypeChip
from ...tasks import is_mounted
from ...theme import IconSize, Motion, Palette, Radius, Space

CARD_MAX_EXTENT = 210


class PokemonCard(ft.Container):
    def __init__(
        self,
        *,
        on_select: Callable[[UUID], None],
        on_favorite: Callable[[UUID, bool], None],
        on_tag: Callable[[str], None],
        on_check: Callable[[UUID, bool], None] | None = None,
    ) -> None:
        super().__init__()
        self.entry_id: UUID | None = None
        self._on_select = on_select
        self._on_favorite = on_favorite
        self._on_tag = on_tag
        self._on_check = on_check
        self._selected = False
        self._favorite = False
        self._checked = False
        self._selection_mode = False

        self._star = ft.IconButton(
            icon=ft.Icons.STAR_BORDER,
            icon_size=IconSize.MD,
            width=32,
            height=32,
            padding=0,
            tooltip="Favourite",
            on_click=lambda _e: self._toggle_favorite(),
        )
        self._check = ft.Checkbox(
            value=False,
            visible=False,
            width=32,
            height=32,
            tooltip="Select",
            on_change=lambda e: self._on_check(self.entry_id, bool(e.control.value)) if (self._on_check and self.entry_id) else None,
        )
        self._bst = BstPill()
        self._planned = StatusChip("Planned", "tertiary", icon=ft.Icons.EDIT_NOTE)
        self._planned.visible = False
        self.sprite = Sprite(size=72)
        self._name = ft.Text("", theme_style=ft.TextThemeStyle.BODY_LARGE, color=Palette.ON_SURFACE, max_lines=1, overflow=ft.TextOverflow.ELLIPSIS, text_align=ft.TextAlign.CENTER)
        self._form = ft.Text("", theme_style=ft.TextThemeStyle.BODY_SMALL, color=Palette.ON_SURFACE_VARIANT, visible=False, text_align=ft.TextAlign.CENTER)
        self._types = ft.Row(spacing=Space.XS, alignment=ft.MainAxisAlignment.CENTER, tight=True)
        self._mega = ft.Icon(ft.Icons.BOLT, size=IconSize.SM, color=Palette.PRIMARY, tooltip="Mega Evolution available", visible=False)
        self._tags = ft.Row(spacing=Space.XS, alignment=ft.MainAxisAlignment.CENTER, wrap=True, tight=True)
        self._stats = StatBlock(spacing=2)
        self._stats.visible = False

        self.content = ft.Column(
            spacing=Space.XS,
            horizontal_alignment=ft.CrossAxisAlignment.CENTER,
            tight=True,
            controls=[
                ft.Row(alignment=ft.MainAxisAlignment.SPACE_BETWEEN, vertical_alignment=ft.CrossAxisAlignment.CENTER, controls=[ft.Row(spacing=0, tight=True, controls=[self._check, self._star]), self._planned, self._bst]),
                self.sprite,
                self._name,
                self._form,
                ft.Row(spacing=Space.XS, alignment=ft.MainAxisAlignment.CENTER, tight=True, controls=[self._types, self._mega]),
                self._tags,
                self._stats,
            ],
        )
        self.bgcolor = Palette.SURFACE_2
        self.border_radius = Radius.MD
        self.border = ft.Border.all(1, Palette.OUTLINE_VARIANT)
        self.padding = Space.CARD_PADDING
        self.animate = ft.Animation(Motion.FAST_MS, Motion.CURVE)
        self.on_click = lambda _e: self._on_select(self.entry_id) if self.entry_id else None
        self.on_hover = self._hover

    # -- model -> controls -----------------------------------------------------------------

    def update_from(self, entry: BoxEntry, *, selected: bool, show_stats: bool, mega_capable: bool) -> None:
        pokemon = entry.pokemon
        self.entry_id = entry.box_entry_id
        self._selected = selected
        self._favorite = entry.is_favorite

        self._star.icon = ft.Icons.STAR if entry.is_favorite else ft.Icons.STAR_BORDER
        self._star.icon_color = Palette.PRIMARY if entry.is_favorite else Palette.ON_SURFACE_VARIANT
        self._bst.set_total(pokemon.total)
        self._planned.visible = entry.is_planned

        primary_type = pokemon.types[0] if pokemon.types else None
        self.sprite.set_src(pokemon.sprite_url)
        self.sprite.set_tooltip(pokemon.display_name)
        self.sprite.set_ring("planned" if entry.is_planned else ("mega" if mega_capable else "type"), primary_type)

        self._name.value = pokemon.display_name
        form = pokemon.form_name or ""
        self._form.value = form
        self._form.visible = bool(form) and form.lower() != "base"
        self._types.controls = [TypeChip(t, size="sm") for t in pokemon.types]
        self._mega.visible = mega_capable

        self._stats.visible = show_stats
        if show_stats:
            self._stats.set_stats(pokemon.stats)
            self._tags.visible = False
        else:
            self._tags.visible = bool(entry.tags)
            chips: list[ft.Control] = [
                ft.Container(
                    content=ft.Text(tag, theme_style=ft.TextThemeStyle.LABEL_MEDIUM, color=Palette.ON_SECONDARY_CONTAINER),
                    bgcolor=Palette.SECONDARY_CONTAINER,
                    border_radius=Radius.PILL,
                    padding=ft.Padding.symmetric(horizontal=Space.SM, vertical=1),
                    tooltip=f"Filter by #{tag}",
                    on_click=lambda _e, tag=tag: self._on_tag(tag),
                )
                for tag in entry.tags[:2]
            ]
            if len(entry.tags) > 2:
                chips.append(ft.Text(f"+{len(entry.tags) - 2}", theme_style=ft.TextThemeStyle.BODY_SMALL, color=Palette.ON_SURFACE_VARIANT, tooltip=", ".join(entry.tags[2:])))
            self._tags.controls = chips

        self.opacity = 0.85 if entry.is_planned else 1.0
        self._apply_frame(hovering=False)

    def set_selected(self, selected: bool) -> None:
        self._selected = selected
        self._apply_frame(hovering=False)

    def set_checked(self, checked: bool, *, selection_mode: bool) -> None:
        """Multi-select state. The checkbox shows while any entry is checked, or on hover."""
        self._checked = checked
        self._selection_mode = selection_mode
        self._check.value = checked
        self._check.visible = selection_mode or checked

    # -- interaction -------------------------------------------------------------------------

    def _toggle_favorite(self) -> None:
        if self.entry_id is None:
            return
        self._on_favorite(self.entry_id, not self._favorite)

    def _hover(self, e: ft.ControlEvent) -> None:
        hovering = getattr(e, "data", None) in ("true", True)
        self._apply_frame(hovering=hovering)
        if self._on_check is not None:
            self._check.visible = hovering or self._selection_mode or self._checked
        if is_mounted(self):
            self.update()

    def _apply_frame(self, *, hovering: bool) -> None:
        if self._selected:
            self.border = ft.Border.all(2, Palette.PRIMARY)
            self.bgcolor = Palette.SURFACE_2
        else:
            self.border = ft.Border.all(1, Palette.OUTLINE if hovering else Palette.OUTLINE_VARIANT)
            self.bgcolor = Palette.SURFACE_3 if hovering else Palette.SURFACE_2

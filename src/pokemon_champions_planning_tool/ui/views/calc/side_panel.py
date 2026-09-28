"""The calculator's side panel: Opponents (every species against the Attacker), Rivals (the
rival team in detail) and Box, behind one set of tabs. It closes from its header or the
page header, like the Teams analysis panel."""

from __future__ import annotations

from collections.abc import Callable

import flet as ft

from ....domain.pokemon_identity import get_pokemon_sprite_url
from ...components import Sprite
from ...components.inputs import SEARCH_FIELD_STYLE
from ...components.pokemon import TypeChip
from ...format import shortcut
from ...theme import Palette, Radius, Space
from ...tasks import safe_update
from .state import pokemon_from_species_id
from .store import CalcStore

SIDE_TABS: tuple[tuple[str, str], ...] = (("opponents", "Opponents"), ("rivals", "Rivals"), ("box", "Box"))
_BOX_LIMIT = 40   # cards per page of the box list; "Show more" adds another page


class BoxCard(ft.Container):
    def __init__(self, *, sprite_url: str | None, name: str, types: tuple[str, ...], caption: str, on_attacker: Callable[[], None], on_defender: Callable[[], None]) -> None:
        super().__init__()
        self.content = ft.Row(spacing=Space.SM, vertical_alignment=ft.CrossAxisAlignment.CENTER, controls=[
            Sprite(sprite_url, size=36, primary_type=types[0] if types else None),
            ft.Column(spacing=1, tight=True, expand=True, controls=[
                ft.Text(name, theme_style=ft.TextThemeStyle.BODY_MEDIUM, weight=ft.FontWeight.W_600, color=Palette.ON_SURFACE, max_lines=1, overflow=ft.TextOverflow.ELLIPSIS),
                ft.Row(spacing=Space.XS, tight=True, controls=[TypeChip(t, size="sm") for t in types]),
                ft.Text(caption, theme_style=ft.TextThemeStyle.LABEL_SMALL, color=Palette.ON_SURFACE_VARIANT, max_lines=1, overflow=ft.TextOverflow.ELLIPSIS),
            ]),
            ft.IconButton(icon=ft.Icons.SHIELD_OUTLINED, icon_size=16, width=30, height=30, padding=0, tooltip="Load as defender",
                          icon_color=Palette.ON_SURFACE_VARIANT, on_click=lambda _e: on_defender()),
        ])
        self.padding = ft.Padding.symmetric(horizontal=Space.SM, vertical=Space.XS)
        self.border_radius = Radius.SM
        self.bgcolor = Palette.SURFACE_3
        self.border = ft.Border.all(1, Palette.OUTLINE_VARIANT)
        self.ink = True
        self.tooltip = "Load as attacker"
        self.on_click = lambda _e: on_attacker()


class BoxList(ft.Container):
    """Your box, filterable; a click loads the species as the Attacker, the shield as the Defender."""

    def __init__(self, *, store: CalcStore, accent: str) -> None:
        super().__init__()
        self.store = store
        self._filter = ft.TextField(hint_text="Filter box…", dense=True, prefix_icon=ft.Icons.FILTER_LIST, **SEARCH_FIELD_STYLE,
                                    on_change=lambda e: self.refresh(e.control.value or ""))
        self._list = ft.Column(spacing=Space.XS, tight=True, controls=[])
        self._entries = None
        self._limit = _BOX_LIMIT
        self._query = ""
        self._filter.tooltip = "Box entries load as a plain set: first ability, no item, no stat points"
        self.content = ft.Column(spacing=Space.SM, controls=[self._filter, self._list])

    def set_scrolling(self, scrolling: bool) -> None:
        self._list.scroll = ft.ScrollMode.AUTO if scrolling else None
        self._list.expand = scrolling
        self._list.tight = not scrolling
        self.content.tight = not scrolling

    def invalidate(self) -> None:
        self._entries = None

    def ensure(self) -> None:
        """Build the list the first time it is shown (and after the box changed)."""
        if self._entries is None:
            self.refresh(self._filter.value or "")

    def refresh(self, query: str = "") -> None:
        if self._entries is None:
            self._entries = self.store.box_entries()
        q = query.strip().lower()
        if q != self._query:
            self._query = q
            self._limit = _BOX_LIMIT
        matches = [e for e in self._entries if not q or q in e.pokemon.display_name.lower()]
        cards: list[ft.Control] = []
        for entry in matches[:self._limit]:
            p = entry.pokemon
            species = self.store.catalogs.species_for(p.canonical_id)
            caption = f"Base Spe {species.stats.speed} · BST {species.stats.total}" if species else "not in the species catalogue"
            cards.append(BoxCard(
                sprite_url=get_pokemon_sprite_url(p.canonical_id), name=p.display_name, types=tuple(t.lower() for t in p.types), caption=caption,
                on_attacker=lambda cid=p.canonical_id: self._load("left", cid), on_defender=lambda cid=p.canonical_id: self._load("right", cid),
            ))
        if len(matches) > self._limit:
            cards.append(ft.TextButton(f"Show more ({len(matches) - self._limit})…", icon=ft.Icons.EXPAND_MORE, on_click=lambda _e: self._more()))
        if not cards:
            cards.append(ft.Text("Nothing in the box" if not q else "No match", theme_style=ft.TextThemeStyle.BODY_SMALL, color=Palette.ON_SURFACE_VARIANT))
        self._list.controls = cards
        safe_update(self._list)

    def _more(self) -> None:
        self._limit += _BOX_LIMIT
        self.refresh(self._filter.value or "")

    def _load(self, side: str, canonical_id: str) -> None:
        species = self.store.catalogs.species_for(canonical_id)
        if species is not None:
            self.store.load_pokemon(side, pokemon_from_species_id(species.canonical_id, species, source="Box"))


class SidePanel(ft.Container):
    def __init__(self, *, pages: dict[str, ft.Control], tab: str, on_tab: Callable[[str], None], on_close: Callable[[], None]) -> None:
        super().__init__()
        self.pages = pages
        self._on_tab = on_tab
        for page in pages.values():
            # The panel draws the card; the pages inside are plain.
            page.bgcolor = None
            page.border = None
            page.padding = 0
            page.expand = True
        self.tabs = ft.SegmentedButton(
            segments=[ft.Segment(value=key, label=ft.Text(label, size=12, max_lines=1)) for key, label in SIDE_TABS],
            selected=[tab if tab in pages else "opponents"], show_selected_icon=False, allow_empty_selection=False, expand=True,
            style=ft.ButtonStyle(visual_density=ft.VisualDensity.COMPACT, padding=ft.Padding.symmetric(horizontal=4)),
            on_change=lambda e: self.select((e.control.selected or ["opponents"])[0]),
        )
        self.tab = self.tabs.selected[0]
        self._body = ft.Container(content=pages[self.tab], expand=True)
        self.content = ft.Column(spacing=Space.SM, expand=True, controls=[
            ft.Row(spacing=Space.XS, vertical_alignment=ft.CrossAxisAlignment.CENTER, controls=[
                self.tabs, ft.IconButton(icon=ft.Icons.CLOSE, icon_size=18, tooltip=shortcut("Hide the side panel (Ctrl+\\)"), on_click=lambda _e: on_close()),
            ]),
            self._body,
        ])
        self.bgcolor = Palette.SURFACE_2
        self.border_radius = Radius.MD
        self.border = ft.Border.all(1, Palette.OUTLINE_VARIANT)
        self.padding = Space.MD

    def select(self, key: str) -> None:
        if key not in self.pages:
            return
        self.tabs.selected = [key]
        changed = key != self.tab
        self.tab = key
        self._body.content = self.pages[key]
        if changed:
            self._on_tab(key)
        safe_update(self)


__all__ = ["BoxCard", "BoxList", "SIDE_TABS", "SidePanel"]

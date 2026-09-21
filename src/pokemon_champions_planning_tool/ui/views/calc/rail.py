"""Left rail: the active team's members and the box, one click to load a side."""

from __future__ import annotations

from collections.abc import Callable

import flet as ft

from ....domain.pokemon_identity import get_pokemon_sprite_url
from ....domain.stat_calc import champions_stats
from ...components import Sprite
from ...components.inputs import SEARCH_FIELD_STYLE
from ...components.pokemon import TypeChip
from ...components.section import SectionHeader
from ...theme import Palette, Radius, Space
from .classes import CLASS_BG, CLASS_BORDER, CLASS_HELP
from .state import SWEEP_CLASSES, MoveResult, PokemonState, TeamRating, pokemon_from_slot, pokemon_from_species_id
from .store import CalcStore

_ATTACKER_HINT = "Load as attacker"
RATING_LEGEND = "\n".join(
    ["Each team member against the Defender:"] + [f"{label}: {CLASS_HELP[key]}" for key, label in SWEEP_CLASSES]
)

_BOX_LIMIT = 40   # cards per page of the box list; "Show more" adds another page


class RailCard(ft.Container):
    def __init__(self, *, sprite_url: str | None, name: str, types: tuple[str, ...], caption: str, on_attacker: Callable[[], None], on_defender: Callable[[], None],
                 mega: bool = False, highlight: bool = False) -> None:
        super().__init__()
        self.content = ft.Row(spacing=Space.SM, vertical_alignment=ft.CrossAxisAlignment.CENTER, controls=[
            Sprite(sprite_url, size=36, ring="mega" if mega else "type", primary_type=types[0] if types else None),
            ft.Column(spacing=1, tight=True, expand=True, controls=[
                ft.Text(name, theme_style=ft.TextThemeStyle.BODY_MEDIUM, weight=ft.FontWeight.W_600, color=Palette.ON_SURFACE, max_lines=1, overflow=ft.TextOverflow.ELLIPSIS),
                ft.Row(spacing=Space.XS, tight=True, controls=[TypeChip(t, size="sm") for t in types]),
                ft.Text(caption, theme_style=ft.TextThemeStyle.LABEL_SMALL, color=Palette.ON_SURFACE_VARIANT, max_lines=1, overflow=ft.TextOverflow.ELLIPSIS),
            ]),
            ft.IconButton(icon=ft.Icons.SHIELD_OUTLINED, icon_size=14, width=26, height=26, padding=0, tooltip="Load as defender", icon_color=Palette.ON_SURFACE_VARIANT, on_click=lambda _e: on_defender()),
        ])
        self.padding = ft.Padding.symmetric(horizontal=Space.SM, vertical=Space.XS)
        self.border_radius = Radius.SM
        self.ink = True
        self.on_click = lambda _e: on_attacker()
        self._highlight = highlight
        self._shown: tuple | None = None
        self.rating: TeamRating | None = None
        self.set_rating(None)

    def set_rating(self, rating: TeamRating | None, rival_name: str = "") -> bool:
        """Tint the card by how this member fares against the rival; False if unchanged.

        The loaded attacker keeps its highlight border, and only its background is tinted.
        """
        shown = (rating, rival_name)
        if shown == self._shown:
            return False
        self._shown = shown
        self.rating = rating
        if rating is None:
            self.bgcolor = Palette.SURFACE_3 if self._highlight else Palette.SURFACE_2
            self.border = ft.Border.all(1, Palette.PRIMARY if self._highlight else Palette.OUTLINE_VARIANT)
            self.tooltip = _ATTACKER_HINT
            return True
        self.bgcolor = CLASS_BG.get(rating.klass, Palette.SURFACE_2)
        self.border = ft.Border.all(1, Palette.PRIMARY) if self._highlight else CLASS_BORDER.get(rating.klass, ft.Border.all(1, Palette.OUTLINE_VARIANT))
        self.tooltip = rating_tooltip(rating, rival_name)
        return True


def _hit(result: MoveResult | None) -> str:
    if result is None:
        return "no damaging move"
    ko = f" ({result.ko_text})" if result.ko_text else ""
    return f"{result.name} {result.min_pct:g}–{result.max_pct:g}%{ko}"


def rating_tooltip(rating: TeamRating, rival_name: str) -> str:
    label = dict(SWEEP_CLASSES).get(rating.klass, rating.klass)
    if rating.your_speed == rating.their_speed:
        speed = f"Speed tie ({rating.your_speed})"
    else:
        speed = f"{'You move' if rating.faster else 'They move'} first ({rating.your_speed} vs {rating.their_speed})"
    return "\n".join((
        f"{_ATTACKER_HINT} · vs {rival_name}: {label}",
        f"You: {_hit(rating.your_best)}",
        f"Them: {_hit(rating.their_best)}",
        speed,
    ))


class CalcRail(ft.Container):
    def __init__(self, *, store: CalcStore, accent: str) -> None:
        super().__init__()
        self.store = store
        self._team_title = SectionHeader("Team", accent=accent)
        # Its own line: beside the team name it was cut short in the narrow rail.
        self._rating_caption = ft.Text("", theme_style=ft.TextThemeStyle.BODY_SMALL, color=Palette.ON_SURFACE_VARIANT, visible=False,
                                       max_lines=1, overflow=ft.TextOverflow.ELLIPSIS)
        self._team = ft.Column(spacing=Space.XS, tight=True, controls=[])
        self._box_filter = ft.TextField(hint_text="Filter box…", dense=True, prefix_icon=ft.Icons.FILTER_LIST, **SEARCH_FIELD_STYLE, on_change=lambda e: self.refresh_box(e.control.value or ""))
        self._box = ft.Column(spacing=Space.XS, tight=True, controls=[])
        self._box_entries = None
        self._team_cards: dict[str, RailCard] = {}
        self._ratings: dict[str, TeamRating] = {}
        self._rival_name = ""
        self._box_limit = _BOX_LIMIT
        self._box_query = ""
        self.content = ft.Column(spacing=Space.SM, tight=True, controls=[
            self._team_title, self._rating_caption, self._team,
            SectionHeader("Box", accent=accent), self._box_filter, self._box,
        ])
        self.bgcolor = Palette.SURFACE_2
        self.border_radius = Radius.MD
        self.border = ft.Border.all(1, Palette.OUTLINE_VARIANT)
        self.padding = Space.MD

    def set_scrolling(self, scrolling: bool) -> None:
        """Scroll on its own (a column of the wide layout) or grow with its content (stacked)."""
        self.content.scroll = ft.ScrollMode.AUTO if scrolling else None

    def refresh(self) -> None:
        """Called each time the calculator is shown.

        The team list is cheap and tracks the active team, so it is redrawn. The box list
        is up to a few dozen cards and only changes when the box does — BOX_CHANGED clears
        ``_box_entries`` — so it is rebuilt only then, not on every visit.
        """
        self.refresh_team()
        if self._box_entries is None:
            self.refresh_box(self._box_filter.value or "")

    def refresh_team(self) -> None:
        slots = self.store.team_slots()
        name = getattr(self.store.team_store, "active_team_name", "") if self.store.team_store is not None else ""
        self._team_title.set_label(f"Team · {name}" if name else "Team")
        cards: list[ft.Control] = []
        self._team_cards = {}
        team_id = getattr(self.store.team_store, "active_team_id", None) if self.store.team_store is not None else None
        left = self.store.state.left
        for slot in slots:
            form = slot.form
            stats = champions_stats(form.stats, slot.member.points, slot.member.nature) if form is not None else None
            caption = f"HP {stats.hp} · Spe {stats.speed}" if stats else ""
            cid = slot.member.selected_form if form is not None and form.is_mega else slot.entry.pokemon.canonical_id
            source = f"{name or 'Team'} · slot {slot.position}"
            card = RailCard(
                sprite_url=form.sprite_url if form is not None else get_pokemon_sprite_url(cid), name=form.label if (form is not None and form.is_mega) else slot.entry.pokemon.display_name,
                types=tuple(form.types) if form is not None else (), caption=caption, mega=bool(form and form.is_mega), highlight=left.species == cid and left.source == source,
                on_attacker=lambda slot=slot, source=source: self._load("left", pokemon_from_slot(slot, self.store.catalogs, source=source)),
                on_defender=lambda slot=slot, source=source: self._load("right", pokemon_from_slot(slot, self.store.catalogs, source=source)),
            )
            slot_key = f"{team_id}:{slot.position}"
            card.set_rating(self._ratings.get(slot_key), self._rival_name)   # rebuilt cards keep their colours
            self._team_cards[slot_key] = card
            cards.append(card)
        if not cards:
            cards.append(ft.Text("No team yet — build one in Teams.", theme_style=ft.TextThemeStyle.BODY_SMALL, color=Palette.ON_SURFACE_VARIANT))
        self._team.controls = cards
        self._safe_update(self._team)

    def apply_ratings(self, ratings: dict[str, TeamRating], rival_name: str) -> None:
        """Colour the team cards; only the cards whose rating changed are sent."""
        self._ratings, self._rival_name = ratings, rival_name
        for slot_key, card in self._team_cards.items():
            if card.set_rating(ratings.get(slot_key), rival_name):
                self._safe_update(card)
        rated = bool(ratings) and bool(rival_name)
        self._rating_caption.value = f"Coloured against {rival_name}" if rated else ""
        self._rating_caption.tooltip = RATING_LEGEND if rated else None
        self._rating_caption.visible = rated
        self._safe_update(self._rating_caption)

    def refresh_box(self, query: str = "") -> None:
        if self._box_entries is None:
            self._box_entries = self.store.box_entries()
        q = query.strip().lower()
        if q != self._box_query:
            self._box_query = q
            self._box_limit = _BOX_LIMIT
        matches = [e for e in self._box_entries if not q or q in e.pokemon.display_name.lower()]
        cards: list[ft.Control] = []
        for entry in matches[:self._box_limit]:
            p = entry.pokemon
            species = self.store.catalogs.species_for(p.canonical_id)
            caption = f"HP {species.stats.hp + 75} · Spe {species.stats.speed + 20}" if species else "not in the species catalogue"
            cards.append(RailCard(
                sprite_url=get_pokemon_sprite_url(p.canonical_id), name=p.display_name, types=tuple(t.lower() for t in p.types), caption=caption,
                on_attacker=lambda cid=p.canonical_id: self._load_species("left", cid), on_defender=lambda cid=p.canonical_id: self._load_species("right", cid),
            ))
        if len(matches) > self._box_limit:
            cards.append(ft.TextButton(f"Show more ({len(matches) - self._box_limit})…", icon=ft.Icons.EXPAND_MORE, on_click=lambda _e: self._more_box()))
        if not cards:
            cards.append(ft.Text("Nothing in the box" if not q else "No match", theme_style=ft.TextThemeStyle.BODY_SMALL, color=Palette.ON_SURFACE_VARIANT))
        self._box.controls = cards
        self._safe_update(self._box)

    def _more_box(self) -> None:
        self._box_limit += _BOX_LIMIT
        self.refresh_box(self._box_filter.value or "")

    def invalidate_box(self) -> None:
        self._box_entries = None

    def _load(self, side: str, pokemon: PokemonState | None) -> None:
        if pokemon is not None:
            self.store.load_pokemon(side, pokemon)

    def _load_species(self, side: str, canonical_id: str) -> None:
        species = self.store.catalogs.species_for(canonical_id)
        if species is not None:
            self.store.load_pokemon(side, pokemon_from_species_id(species.canonical_id, species, source="Box"))

    @staticmethod
    def _safe_update(control: ft.Control) -> None:
        try:
            if control.page is not None:
                control.update()
        except RuntimeError:
            pass

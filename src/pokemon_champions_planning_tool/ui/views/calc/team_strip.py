"""The two teams above the calculation: yours over the Attacker, the rival's over the Defender.

Each member is a sprite tinted by how the matchup goes — your members against the Defender,
the rival's against the Attacker — with the details in its tooltip. A click loads it on its
own side; a right-click loads it on the other side. The rival strip also holds every rival
team action (team preview, load, presets, the team grid) in its menu.
"""

from __future__ import annotations

from collections.abc import Callable
from typing import Any

import flet as ft

from ....domain.pokemon_identity import get_pokemon_sprite_url
from ...components import Sprite
from ...format import shortcut
from ...theme import Palette, Radius, Space, alpha
from ...tasks import safe_update
from .classes import CLASS_BG, CLASS_BORDER
from .hit import rating_legend, rating_tooltip
from .rival_store import RivalStore
from .rivals_panel import assumed_note
from .state import PokemonState, RivalTeam, TeamRating, pokemon_from_slot
from .store import CalcStore

AVATAR = 32
# (picker width, sprite size) from roomiest to tightest; the strips take the first that fits
# so all six members always show. The sprites shrink first: a team name cut to "Sa…" helps
# nobody, a 24 px sprite is still recognisable.
TIERS: tuple[tuple[int, int], ...] = ((190, 32), (190, 28), (170, 28), (170, 24), (150, 24), (150, 20), (130, 20))
STACK_BELOW = (150, 24)      # smaller than this, the view stacks the two cards instead
_INNER = 20          # room kept free on the side facing the "VS" badge
_PAD = 8 + 2         # card padding and border on the outer side
_ICON = 32           # the rival strip's icon buttons
_SMALL_ICON = {"icon_size": 18, "width": _ICON, "height": _ICON, "padding": 0}


def team_width(picker: int, sprite: int, members: int = 6) -> int:
    """What your strip needs: picker, the members, the colour legend."""
    return _PAD + _INNER + picker + Space.SM + members * (sprite + 8) + Space.SM + 16


def rival_width(picker: int, sprite: int, members: int = 6) -> int:
    """What the rival strip needs: the members, one action icon, the picker and the menu."""
    return _PAD + _INNER + members * (sprite + 8) + _ICON + picker + 2 * Space.XS + _ICON


def fit_tier(width: float) -> tuple[int, int]:
    """The roomiest (picker, sprite) both strips fit in ``width`` each."""
    for picker, sprite in TIERS:
        if max(team_width(picker, sprite), rival_width(picker, sprite)) <= width:
            return picker, sprite
    return TIERS[-1]
# The team pickers: compact, filled like the search fields (the card's tint says whose team it is).
PICKER_STYLE: dict = {"dense": True, "text_size": 13, "width": 190, "filled": True, "fill_color": Palette.SURFACE_3,
                      "border_color": Palette.OUTLINE_VARIANT, "focused_border_color": Palette.PRIMARY, "border_radius": Radius.SM,
                      "content_padding": ft.Padding.symmetric(horizontal=Space.SM, vertical=6)}
# Each team sits on its own card over its Pokémon's column, tinted by side: yours green, the rival's red.
SIDE_TINT = {"left": Palette.SUCCESS, "right": Palette.ERROR}


def side_card(control: ft.Container, side: str) -> None:
    control.bgcolor = alpha(SIDE_TINT[side], 0.07)
    control.border = ft.Border.all(1, alpha(SIDE_TINT[side], 0.35))
    control.border_radius = Radius.MD
    set_inner(control, side, True)


def set_inner(control: ft.Container, side: str, badge: bool) -> None:
    """Keep the side facing the "VS" badge clear while it shows."""
    inner = _INNER if badge else Space.SM
    control.padding = ft.Padding.only(left=Space.SM if side == "left" else inner, right=inner if side == "left" else Space.SM, top=6, bottom=6)


_LOAD_HINT = {"left": "Click: load as attacker · right-click: as defender", "right": "Click: load as defender · right-click: as attacker"}


class Avatar(ft.GestureDetector):
    """One team member: its sprite on a tile coloured by its rating."""

    def __init__(self, *, sprite_url: str | None, name: str, types: tuple[str, ...] = (), mega: bool = False, side: str,
                 on_primary: Callable[[], None], on_secondary: Callable[[], None] | None = None, size: int = AVATAR) -> None:
        self.name = name
        self.side = side
        self.rating: TeamRating | None = None
        self.highlight = False
        self._note = ""
        self._shown: tuple | None = None
        self.tile = ft.Container(
            content=Sprite(sprite_url, size=size, ring="mega" if mega else "type", primary_type=types[0] if types else None),
            padding=2, border_radius=Radius.MD,
        )
        super().__init__(content=self.tile, mouse_cursor=ft.MouseCursor.CLICK, on_tap=lambda _e: on_primary(),
                         on_secondary_tap=(lambda _e: on_secondary()) if on_secondary else None)
        self.on_primary = on_primary
        self.on_secondary = on_secondary
        self.set_rating(None)

    def set_rating(self, rating: TeamRating | None, rival_name: str = "", *, highlight: bool | None = None, note: str | None = None) -> bool:
        """Tint by the rating and ring the loaded one; False when nothing changed."""
        if highlight is not None:
            self.highlight = highlight
        if note is not None:
            self._note = note
        shown = (rating, rival_name, self.highlight, self._note)
        if shown == self._shown:
            return False
        self._shown = shown
        self.rating = rating
        tips = [self.name]
        if rating is not None:
            tips.append(rating_tooltip(rating, rival_name))
        if self._note:
            tips.append(self._note)
        tips.append("In the Attacker panel" if (self.highlight and self.side == "left") else "In the Defender panel" if self.highlight else _LOAD_HINT[self.side])
        self.tile.tooltip = "\n".join(tips)
        self.tile.bgcolor = CLASS_BG.get(rating.klass) if rating is not None else Palette.SURFACE_3
        if self.highlight:
            self.tile.border = ft.Border.all(2, Palette.PRIMARY)
        elif rating is not None:
            self.tile.border = CLASS_BORDER.get(rating.klass, ft.Border.all(1, Palette.OUTLINE_VARIANT))
        else:
            self.tile.border = ft.Border.all(1, Palette.OUTLINE_VARIANT)
        return True


class TeamStrip(ft.Container):
    """Your active team, each member coloured against the Defender."""

    def __init__(self, *, store: CalcStore, on_select_team: Callable[[Any], None]) -> None:
        super().__init__()
        self.store = store
        self._on_select_team = on_select_team
        self._select = ft.Dropdown(**PICKER_STYLE, options=[], tooltip="Your team (also the active team in Teams)",
                                   on_select=lambda e: self._team_picked(e.control.value))
        self._legend = ft.Icon(ft.Icons.PALETTE_OUTLINED, size=16, color=Palette.ON_SURFACE_VARIANT, visible=False)
        self._row = ft.Row(spacing=Space.XS, tight=True, controls=[])
        self._team_cards: dict[str, Avatar] = {}
        self._ratings: dict[str, TeamRating] = {}
        self._rival_name = ""
        # One line: the picker, then the six members.
        self.content = ft.Row(spacing=Space.SM, vertical_alignment=ft.CrossAxisAlignment.CENTER, controls=[self._select, self._row, self._legend])
        side_card(self, "left")
        self.sprite_size = AVATAR

    def fit(self, picker: int, sprite: int, *, badge: bool) -> None:
        """Size the picker and the members to the room the view measured."""
        set_inner(self, "left", badge)
        self._select.width = picker
        if sprite != self.sprite_size:
            self.sprite_size = sprite
            self.refresh_team()

    def _team_picked(self, value: str | None) -> None:
        teams = getattr(self.store.team_store, "teams", None) or []
        team = next((t for t in teams if str(getattr(t, "team_id", "")) == value), None)
        if team is not None:
            self._on_select_team(team.team_id)

    def refresh_team(self) -> None:
        team_store = self.store.team_store
        slots = self.store.team_slots()
        teams = [t for t in (getattr(team_store, "teams", None) or []) if hasattr(t, "team_id")] if team_store is not None else []
        active = getattr(team_store, "active_team_id", None) if team_store is not None else None
        name = getattr(team_store, "active_team_name", "") if team_store is not None else ""
        self._select.options = [ft.DropdownOption(key=str(t.team_id), text=t.name) for t in teams]
        self._select.value = str(active) if active is not None else None
        self._select.visible = bool(teams)
        left = self.store.state.left
        self._team_cards = {}
        avatars: list[ft.Control] = []
        for slot in slots:
            form = slot.form
            cid = slot.member.selected_form if form is not None and form.is_mega else slot.entry.pokemon.canonical_id
            source = f"{name or 'Team'} · slot {slot.position}"
            label = form.label if (form is not None and form.is_mega) else slot.entry.pokemon.display_name
            avatar = Avatar(
                size=self.sprite_size,
                sprite_url=form.sprite_url if form is not None else get_pokemon_sprite_url(cid), name=label,
                types=tuple(form.types) if form is not None else (), mega=bool(form and form.is_mega), side="left",
                on_primary=lambda slot=slot, source=source: self._load("left", pokemon_from_slot(slot, self.store.catalogs, source=source)),
                on_secondary=lambda slot=slot, source=source: self._load("right", pokemon_from_slot(slot, self.store.catalogs, source=source)),
            )
            slot_key = f"{active}:{slot.position}"
            avatar.set_rating(self._ratings.get(slot_key), self._rival_name, highlight=left.species == cid and left.source == source)
            self._team_cards[slot_key] = avatar
            avatars.append(avatar)
        if not avatars:
            avatars.append(ft.Text("No team yet — build one in Teams.", theme_style=ft.TextThemeStyle.BODY_SMALL, color=Palette.ON_SURFACE_VARIANT))
        self._row.controls = avatars
        safe_update(self)

    def apply_ratings(self, ratings: dict[str, TeamRating], rival_name: str) -> None:
        """Colour the members; only the ones whose rating changed are sent."""
        self._ratings, self._rival_name = ratings, rival_name
        for slot_key, avatar in self._team_cards.items():
            if avatar.set_rating(ratings.get(slot_key), rival_name):
                safe_update(avatar)
        rated = bool(ratings) and bool(rival_name)
        self._legend.visible = rated
        self._legend.tooltip = rating_legend(f"Coloured against {rival_name}:") if rated else None
        safe_update(self._legend)

    def _load(self, side: str, pokemon: PokemonState | None) -> None:
        if pokemon is not None:
            self.store.load_pokemon(side, pokemon)


class RivalStrip(ft.Container):
    """The rival team (the current battle or a preset), each member against the Attacker."""

    def __init__(self, *, rivals: RivalStore, species_name: Callable[[str | None], str], on_pick: Callable[[int], None],
                 on_pick_attacker: Callable[[int], None], on_action: Callable[[str], None]) -> None:
        super().__init__()
        self.rivals = rivals
        self._species_name = species_name
        self._on_pick = on_pick
        self._on_pick_attacker = on_pick_attacker
        self._on_action = on_action
        self._ratings: tuple[TeamRating | None, ...] = ()
        self._attacker = ""
        self._linked: int | None = None
        self._select = ft.Dropdown(**PICKER_STYLE, options=[], tooltip="Rival team: the current battle or a saved preset",
                                   on_select=lambda e: self.rivals.set_active(e.control.value or None))
        # Every rival action, the Team vs team grid included, is in this menu.
        self._menu = ft.PopupMenuButton(icon=ft.Icons.MORE_VERT, icon_size=20, width=_ICON, tooltip="Rival team actions", items=[])
        self._spinner = ft.ProgressRing(width=14, height=14, stroke_width=2, visible=False)
        self._use = ft.IconButton(icon=ft.Icons.PLAY_CIRCLE_OUTLINE, icon_color=Palette.PRIMARY, visible=False, **_SMALL_ICON,
                                  tooltip="Use in battle: load this preset as the “Current battle”; the preset itself stays as saved",
                                  on_click=lambda _e: on_action("use_preset"))
        # A saved plan is never changed by browsing it: edits to its member in the Defender
        # panel are kept only through this button (a battle team saves them by itself).
        self._update_member = ft.IconButton(icon=ft.Icons.SAVE_AS_OUTLINED, icon_color=Palette.WARNING, visible=False, **_SMALL_ICON,
                                            on_click=lambda _e: on_action("update_member"))
        self._preview = ft.TextButton("Team preview", icon=ft.Icons.BOLT, tooltip=shortcut("Start a battle: enter the six Pokémon you see (Ctrl+B)"),
                                             on_click=lambda _e: on_action("battle"))
        self._load = ft.TextButton("Load team…", icon=ft.Icons.FOLDER_OPEN_OUTLINED, tooltip="A preset, one of your teams or a paste",
                                   on_click=lambda _e: on_action("load"))
        self._empty = ft.Row(spacing=0, tight=True, controls=[self._preview, self._load])
        self._row = ft.Row(spacing=Space.XS, tight=True, controls=[])
        self.avatars: list[Avatar] = []
        # One line, mirroring yours: the members (or how to start), then the picker and actions.
        self.content = ft.Row(spacing=Space.XS, alignment=ft.MainAxisAlignment.END, vertical_alignment=ft.CrossAxisAlignment.CENTER, controls=[
            self._spinner, self._row, self._empty, self._update_member, self._use, self._select, self._menu,
        ])
        side_card(self, "right")
        self.sprite_size = AVATAR

    def fit(self, picker: int, sprite: int, *, badge: bool) -> None:
        set_inner(self, "right", badge)
        self._select.width = picker
        if sprite != self.sprite_size:
            self.sprite_size = sprite
            self.render()

    def set_busy(self, busy: bool) -> None:
        if busy != self._spinner.visible:
            self._spinner.visible = busy
            safe_update(self._spinner)

    def set_ratings(self, ratings: tuple[TeamRating | None, ...], attacker_name: str) -> None:
        self._ratings = ratings
        self._attacker = attacker_name
        self.render()

    def set_pending(self, name: str | None) -> None:
        """Offer "Save Defender to <name>" while a saved team's member was edited."""
        label = f"Save Defender to {name}: keep its item, ability, moves, nature and stat points in this preset" if name else None
        if (name is not None) != self._update_member.visible or label != self._update_member.tooltip:
            self._update_member.visible = name is not None
            self._update_member.tooltip = label
            safe_update(self._update_member)

    def set_linked(self, slot: int | None) -> None:
        if slot != self._linked:
            self._linked = slot
            self.render()

    def menu_items(self, team: RivalTeam | None) -> list[ft.PopupMenuItem]:
        def item(label: str, icon: str, key: str) -> ft.PopupMenuItem:
            return ft.PopupMenuItem(content=ft.Text(label), icon=icon, on_click=lambda _e: self._on_action(key))

        items = [item("New battle (team preview)…", ft.Icons.BOLT, "battle"),
                 item("Load team (presets, my teams, paste)…", ft.Icons.FOLDER_OPEN_OUTLINED, "load")]
        if team is None:
            return items
        items.append(item("Team vs team…", ft.Icons.GRID_VIEW, "matrix"))
        items.append(ft.PopupMenuItem())   # divider
        if team.is_battle:
            items += [item("Save battle as preset…", ft.Icons.BOOKMARK_ADD_OUTLINED, "save_battle"), item("End battle", ft.Icons.STOP_CIRCLE_OUTLINED, "end_battle")]
        else:
            items += [item("Use in battle", ft.Icons.SPORTS_MMA, "use_preset"), item("Rename preset…", ft.Icons.EDIT_OUTLINED, "rename"),
                      item("Duplicate preset", ft.Icons.COPY_ALL, "duplicate"), item("Delete preset", ft.Icons.DELETE_OUTLINE, "delete")]
        return items

    def render(self) -> None:
        teams = self.rivals.teams
        team = self.rivals.active
        self._select.options = [ft.DropdownOption(key=t.rival_team_id, text=t.name) for t in teams]
        self._select.value = team.rival_team_id if team else None
        self._select.visible = bool(teams)
        self._menu.items = self.menu_items(team)
        self._use.visible = team is not None and not team.is_battle and bool(team.members)
        self._empty.visible = team is None
        self.avatars = []
        if team is not None:
            ratings = self._ratings if len(self._ratings) == len(team.members) else ()
            for i, m in enumerate(team.members):
                p = m.pokemon
                avatar = Avatar(sprite_url=get_pokemon_sprite_url(p.species or ""), name=self._species_name(p.species), side="right", size=self.sprite_size,
                                on_primary=lambda i=i: self._on_pick(i), on_secondary=lambda i=i: self._on_pick_attacker(i))
                avatar.set_rating(ratings[i] if ratings else None, self._attacker, highlight=i == self._linked, note=assumed_note(m))
                self.avatars.append(avatar)
        self._row.controls = list(self.avatars)
        safe_update(self)


__all__ = ["AVATAR", "Avatar", "RivalStrip", "STACK_BELOW", "TIERS", "TeamStrip", "fit_tier", "rival_width", "team_width"]

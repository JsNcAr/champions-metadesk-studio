"""Legacy Flet UI — the pre-overhaul single-closure application.

Kept alive during the UI overhaul so the app works at every commit. ``build_legacy_views``
constructs the old views and returns them as mountable controls plus the reload callbacks
the new shell needs to keep them in sync; each migrated view deletes its slice from here.
This module is removed once the last view has moved.
"""

import threading
from dataclasses import dataclass
from typing import Any, Callable
import flet as ft
from uuid import UUID

from .theme import Colors, STAT_COLORS, TYPE_COLORS

_global_sync_lock = threading.Lock()
_global_sync_done = False

from ..domain.pokemon_identity import format_api_name, get_pokemon_sprite_url
from ..domain.entities.box_entry import BoxEntry
from ..domain.entities.team import Team
from ..domain.entities.team_member import TeamMember
from ..domain.entities.pokemon_move import PokemonMove
from sqlmodel import select
from ..infrastructure.database.database import get_session
from ..infrastructure.database.models import (
    TournamentRecord,
    TournamentTeamRecord,
    TournamentTeamMemberRecord,
    PokemonRecord,
)
from ..infrastructure.database.repositories import (
    BoxRepository,
    TeamRepository,
    PokemonRepository,
    ChampionsCatalogRepository,
    MegaEvolutionRepository,
    ItemRepository,
)

from ..services.pokemon_import_service import add_pokemon_to_box
from ..services.mega_evolution_service import (
    sync_all_champions_megas_on_startup,
    sync_mega_evolutions_for_species,
)
from ..services.items_catalog_service import (
    sync_items_catalog,
    load_items_catalog,
    check_items_catalog_staleness,
)
from ..services.item_effect_service import (
    compute_effective_stats,
    validate_item_assignment,
)
from ..infrastructure.csv.csv_operations import export_box_entries_to_csv
from ..services.showdown_service import (
    export_team_to_showdown_text,
    parse_showdown_text,
    resolve_import_readiness,
    import_from_pokepast_url,
    publish_to_pokepast,
    ParsedTeamResult,
    ImportReadinessReport,
)
from ..infrastructure.providers.pokepast_provider import (
    PokepastProvider,
    PokepastNetworkError,
)
from ..services.tournament_service import TournamentService
from pathlib import Path

SEED_FILE_PATH = Path(__file__).parent.parent / "data" / "seed_tournaments.json"




@dataclass
class LegacyViews:
    """Mountable legacy controls and the callbacks the shell uses to drive them."""

    box: ft.Control
    team: ft.Control
    meta: ft.Control
    on_activate_meta: Callable[[], None]
    open_settings: Callable[[], None]
    refresh_box: Callable[[], None]
    refresh_teams: Callable[[], None]
    render_team_builder: Callable[[], None]
    render_meta: Callable[[bool], None]
    invalidate_meta: Callable[[], None]
    reload_catalogs: Callable[[], None]
    reload_items: Callable[[], None]
    import_showdown_text: Callable[[str, str], None]
    open_import_modal: Callable[[], None]
    open_export_modal: Callable[[], None]


def _get_obj_attr(obj: Any, attr_name: str, default: str = "") -> str:
    """Safely retrieve attribute from Pydantic model, dictionary, or primitive string."""
    if obj is None:
        return default
    if isinstance(obj, str):
        return obj
    if isinstance(obj, dict):
        val = obj.get(attr_name, default)
        return str(val) if val is not None else default
    val = getattr(obj, attr_name, default)
    return str(val) if val is not None else default


def build_legacy_views(page: ft.Page, services: Any) -> LegacyViews:
    """Build the legacy views. ``services`` provides ``toast(message, is_error)``."""

    # --- Application State ---
    state = {
        "box_entries": [],
        "teams": [],
        "champions_catalog": [],      # ChampionsSpeciesRecord list
        "mega_species_set": set(),    # Set of species_names that have megas (cached)
        "all_pokemon_names": [],      # Flat list of display names for search autocomplete
        "selected_pokemon_id": None,  # UUID of BoxEntry
        "active_team_id": None,       # UUID of Team
        "search_query": "",
        "sort_by": "Name (Asc)",
        "all_stats_visible": False,
        "assigning_slot_position": None,  # Slot number when choosing from box
        "detail_form_id": "base",     # Active form shown in detail drawer
        # Box filter state
        "selected_type_filter": "all",  # "all" or a type string e.g. "fire"
        "favorites_only": False,
        "megas_only": False,
        "bst_min": 0,
        "bst_max": 999,
        # Item system state
        "items_catalog": [],          # list[ItemRecord]
        "items_by_id": {},            # dict[canonical_id, ItemRecord]
        "champions_items": [],        # list[ItemRecord] — Champions-legal only
        "mega_stone_map": {},         # dict[species_name, list[ItemRecord]]
        "item_picker_slot": None,     # Slot being assigned in item picker dialog
    }

    # --- Database Helpers ---
    def get_repositories():
        """Open a fresh session; caller is responsible for calling session.close()."""
        from ..infrastructure.database.database import get_engine
        from sqlmodel import Session as SqlSession
        session = SqlSession(get_engine())
        return BoxRepository(session), TeamRepository(session), MegaEvolutionRepository(session), session

    def load_champions_catalog():
        """Load all lookup caches from DB in a single pass at startup."""
        with get_session() as session:
            catalog_repo = ChampionsCatalogRepository(session)
            mega_repo = MegaEvolutionRepository(session)
            state["champions_catalog"] = catalog_repo.list_all()
            state["all_pokemon_names"] = [r.display_name for r in state["champions_catalog"]]
            state["mega_species_set"] = set(m.species_name.lower() for m in mega_repo.list_all())

    def load_items_to_state():
        """Prime item state dicts from local SQLite catalog (0ms during UI rendering)."""
        with get_session() as session:
            load_items_catalog(session, state)

    # --- Notifications ---
    def show_toast(message: str, is_error: bool = False):
        services.toast(message, is_error)

    # --- UI Component Declarations (to be wired later) ---
    suggestion_row = ft.Row(spacing=8, wrap=True, visible=False)

    search_input = ft.TextField(
        label="Add Pokemon by Name",
        hint_text="Type to search Champions roster...",
        expand=True,
        on_change=lambda e: handle_search_input_change(e.control.value),
        on_submit=lambda e: handle_add_pokemon()
    )
    add_button = ft.ElevatedButton("Add to Box", icon=ft.Icons.ADD, on_click=lambda e: handle_add_pokemon())
    add_spinner = ft.ProgressRing(visible=False, width=20, height=20)

    filter_search = ft.TextField(
        label="Filter Box",
        prefix_icon=ft.Icons.SEARCH,
        hint_text="Search local box by name or tag...",
        expand=True,
        on_change=lambda e: handle_filter_change(e.control.value)
    )

    sort_dropdown = ft.Dropdown(
        label="Sort By",
        width=180,
        value=state["sort_by"],
        options=[
            ft.dropdown.Option("Name (Asc)"),
            ft.dropdown.Option("Name (Desc)"),
            ft.dropdown.Option("Stat Total (Desc)"),
            ft.dropdown.Option("HP (Desc)"),
            ft.dropdown.Option("Attack (Desc)"),
            ft.dropdown.Option("Speed (Desc)"),
        ],
        on_select=lambda e: handle_sort_change(e.control.value)
    )

    all_stats_switch = ft.Switch(
        label="Show Stats on Cards",
        value=state["all_stats_visible"],
        on_change=lambda e: handle_stats_visibility_toggle(e.control.value)
    )

    box_grid = ft.GridView(
        expand=True,
        runs_count=3,
        max_extent=250,
        child_aspect_ratio=0.72,
        spacing=15,
        run_spacing=15,
    )
    # Filter bar widgets — populated by render_type_filter_bar()
    type_filter_row = ft.Row(wrap=True, spacing=6, run_spacing=4)
    quick_toggles_row = ft.Row(spacing=8)

    # --- Detail Drawer UI elements ---
    detail_container = ft.Column(spacing=12, expand=True, scroll=ft.ScrollMode.AUTO)
    detail_panel = ft.Container(
        content=detail_container,
        width=310,
        expand=True,
        bgcolor=Colors.PANEL_BG,
        padding=ft.Padding.all(16),
        border_radius=12,
        border=ft.Border.all(1, Colors.DIVIDER),
        visible=False
    )

    # --- Team Builder UI elements ---
    team_dropdown = ft.Dropdown(
        label="Select Active Team",
        expand=True,
        on_select=lambda e: handle_team_select(e.control.value)
    )
    team_grid = ft.GridView(
        expand=True,
        runs_count=3,
        max_extent=350,
        child_aspect_ratio=0.85,
        spacing=12,
        run_spacing=12,
    )
    team_totals_row = ft.Column(spacing=4)
    team_banner_row = ft.Row(spacing=10, alignment=ft.MainAxisAlignment.CENTER)
    team_validation_col = ft.Column(spacing=6)

    # --- MODAL: Assign Pokemon to Slot ---
    def close_modal(e=None):
        assign_modal.open = False
        page.update()

    assign_modal = ft.AlertDialog(
        title=ft.Text("Choose Pokémon from Box"),
        content=ft.Column(scroll=ft.ScrollMode.ALWAYS, height=400, spacing=10),
        actions=[ft.TextButton("Cancel", on_click=close_modal)],
    )
    page.overlay.append(assign_modal)

    # --- Modal: Create Team ---
    new_team_input = ft.TextField(label="Team Name", hint_text="e.g. Electric Storm")

    def create_team_action(e):
        name = new_team_input.value.strip()
        if not name:
            show_toast("Team name cannot be empty", is_error=True)
            return
        box_repo, team_repo, mega_repo, session = get_repositories()
        try:
            if team_repo.get_by_name(name) is not None:
                show_toast("A team with this name already exists", is_error=True)
                return
            new_team = team_repo.create(Team(name=name))
            state["active_team_id"] = new_team.team_id
            show_toast(f"Team '{name}' created successfully")
            new_team_input.value = ""
            new_team_modal.open = False
            refresh_teams()
        finally:
            session.close()

    def close_new_team_modal(e):
        new_team_modal.open = False
        page.update()

    new_team_modal = ft.AlertDialog(
        title=ft.Text("Create New Team"),
        content=new_team_input,
        actions=[
            ft.TextButton("Cancel", on_click=close_new_team_modal),
            ft.ElevatedButton("Create", on_click=create_team_action)
        ]
    )
    page.overlay.append(new_team_modal)

    # --- Data Refresher Functions ---
    def refresh_box():
        box_repo, _, _, session = get_repositories()
        try:
            state["box_entries"] = box_repo.list_entries()
            render_type_filter_bar()
            render_box_grid(update_page=False)
            render_detail_drawer(update_page=False)
            page.update()
        finally:
            session.close()

    def refresh_teams():
        _, team_repo, _, session = get_repositories()
        try:
            state["teams"] = team_repo.list_all()
            
            # Rebuild dropdown options
            team_dropdown.options = [
                ft.dropdown.Option(key=str(team.team_id), text=team.name)
                for team in state["teams"]
            ]
            
            if state["teams"]:
                if state["active_team_id"] is None or not any(t.team_id == state["active_team_id"] for t in state["teams"]):
                    state["active_team_id"] = state["teams"][0].team_id
                team_dropdown.value = str(state["active_team_id"])
            else:
                state["active_team_id"] = None
                team_dropdown.value = None

            render_team_builder()
            page.update()
        finally:
            session.close()

    # --- Event Handlers ---
    def handle_search_input_change(val: str):
        query = val.strip().lower()
        if not query or len(query) < 2:
            if suggestion_row.visible:
                suggestion_row.visible = False
                suggestion_row.controls.clear()
                page.update()
            return

        matches = [
            rec for rec in state["champions_catalog"]
            if query in rec.species_name.lower() or query in rec.display_name.lower()
        ][:6]

        if not matches:
            if suggestion_row.visible:
                suggestion_row.visible = False
                suggestion_row.controls.clear()
                page.update()
            return

        suggestion_row.controls = [
            ft.Container(
                content=ft.Row(
                    spacing=5,
                    tight=True,
                    controls=[
                        ft.Icon(ft.Icons.CATCHING_POKEMON, size=13, color=Colors.AMBER_400),
                        ft.Text(rec.display_name, size=12, weight=ft.FontWeight.W_600, color=Colors.WHITE)
                    ]
                ),
                bgcolor=Colors.CARD_SELECTED,
                padding=ft.Padding.symmetric(horizontal=10, vertical=6),
                border_radius=16,
                border=ft.Border.all(1, Colors.AMBER_700),
                on_click=lambda e, name=rec.display_name: select_suggestion(name)
            )
            for rec in matches
        ]
        suggestion_row.visible = True
        page.update()

    def select_suggestion(name: str):
        search_input.value = name
        suggestion_row.visible = False
        suggestion_row.controls.clear()
        page.update()
        handle_add_pokemon()

    def handle_add_pokemon():
        suggestion_row.visible = False
        suggestion_row.controls.clear()
        name = search_input.value.strip()
        if not name:
            return
        
        search_input.disabled = True
        add_button.disabled = True
        add_spinner.visible = True
        page.update()

        def background_add():
            try:
                # Query PokéAPI and upsert
                add_pokemon_to_box(name)
                refresh_box()
                if state["box_entries"]:
                    last_entry = state["box_entries"][-1]
                    show_toast(f"Added {last_entry.pokemon.display_name} to box")
            except Exception as ex:
                show_toast(f"Error querying PokéAPI: {str(ex)}", is_error=True)
            finally:
                search_input.disabled = False
                search_input.value = ""
                add_button.disabled = False
                add_spinner.visible = False
                page.update()

        threading.Thread(target=background_add, daemon=True).start()

    def handle_filter_change(query: str):
        state["search_query"] = query.strip().lower()
        render_box_grid()

    def handle_sort_change(sort_by: str):
        state["sort_by"] = sort_by
        render_box_grid()

    def handle_stats_visibility_toggle(visible: bool):
        state["all_stats_visible"] = visible
        render_box_grid()

    def handle_type_filter_change(type_name: str):
        state["selected_type_filter"] = type_name
        render_type_filter_bar()
        render_box_grid()

    def handle_toggle_favorites_only():
        state["favorites_only"] = not state["favorites_only"]
        render_type_filter_bar()
        render_box_grid()

    def handle_toggle_megas_only():
        state["megas_only"] = not state["megas_only"]
        render_type_filter_bar()
        render_box_grid()

    def handle_clear_filters():
        state["selected_type_filter"] = "all"
        state["favorites_only"] = False
        state["megas_only"] = False
        state["bst_min"] = 0
        state["bst_max"] = 999
        filter_search.value = ""
        state["search_query"] = ""
        render_type_filter_bar()
        render_box_grid()
        page.update()

    def render_type_filter_bar():
        """Re-render the type pills and quick toggles based on current state."""
        type_filter_row.controls.clear()
        quick_toggles_row.controls.clear()

        # "All" pill
        all_active = state["selected_type_filter"] == "all"
        type_filter_row.controls.append(
            ft.Container(
                content=ft.Text("All", size=10, weight=ft.FontWeight.BOLD,
                                color=Colors.WHITE if all_active else Colors.GREY_400),
                bgcolor=Colors.AMBER_700 if all_active else "#1e293b",
                border=ft.Border.all(1, Colors.AMBER_700 if all_active else "#334155"),
                border_radius=12, padding=ft.Padding.symmetric(horizontal=10, vertical=4),
                on_click=lambda e: handle_type_filter_change("all"), ink=True,
            )
        )
        # One pill per type
        for type_name, type_color in TYPE_COLORS.items():
            if type_name == "unknown":
                continue
            active = state["selected_type_filter"] == type_name
            type_filter_row.controls.append(
                ft.Container(
                    content=ft.Text(type_name.title(), size=10, weight=ft.FontWeight.BOLD,
                                    color=Colors.WHITE),
                    bgcolor=type_color if active else type_color + "44",
                    border=ft.Border.all(1, type_color),
                    border_radius=12, padding=ft.Padding.symmetric(horizontal=10, vertical=4),
                    on_click=lambda e, tn=type_name: handle_type_filter_change(tn), ink=True,
                )
            )

        # Favorites toggle pill
        fav_active = state["favorites_only"]
        quick_toggles_row.controls.append(
            ft.Container(
                content=ft.Row(spacing=4, controls=[
                    ft.Icon(ft.Icons.STAR, size=12,
                            color=Colors.YELLOW if fav_active else Colors.GREY_500),
                    ft.Text("Favorites", size=10, weight=ft.FontWeight.W_600,
                            color=Colors.WHITE if fav_active else Colors.GREY_400),
                ]),
                bgcolor=Colors.AMBER_700 + "33" if fav_active else "#1e293b",
                border=ft.Border.all(1, Colors.AMBER_700 if fav_active else "#334155"),
                border_radius=12, padding=ft.Padding.symmetric(horizontal=10, vertical=4),
                on_click=lambda e: handle_toggle_favorites_only(), ink=True,
            )
        )
        # Mega Capable toggle pill
        mega_active = state["megas_only"]
        quick_toggles_row.controls.append(
            ft.Container(
                content=ft.Row(spacing=4, controls=[
                    ft.Icon(ft.Icons.FLASH_ON, size=12,
                            color=Colors.AMBER_400 if mega_active else Colors.GREY_500),
                    ft.Text("Mega Capable", size=10, weight=ft.FontWeight.W_600,
                            color=Colors.WHITE if mega_active else Colors.GREY_400),
                ]),
                bgcolor="#291d03" if mega_active else "#1e293b",
                border=ft.Border.all(1, Colors.AMBER_700 if mega_active else "#334155"),
                border_radius=12, padding=ft.Padding.symmetric(horizontal=10, vertical=4),
                on_click=lambda e: handle_toggle_megas_only(), ink=True,
            )
        )
        # Clear Filters button — only shown when any filter is active
        any_active = (state["selected_type_filter"] != "all" or
                      state["favorites_only"] or state["megas_only"])
        if any_active:
            quick_toggles_row.controls.append(
                ft.Container(
                    content=ft.Row(spacing=4, controls=[
                        ft.Icon(ft.Icons.CLEAR, size=12, color=Colors.RED_400),
                        ft.Text("Clear Filters", size=10, color=Colors.RED_400,
                                weight=ft.FontWeight.W_600),
                    ]),
                    bgcolor="#1e293b",
                    border=ft.Border.all(1, Colors.RED_400),
                    border_radius=12, padding=ft.Padding.symmetric(horizontal=10, vertical=4),
                    on_click=lambda e: handle_clear_filters(), ink=True,
                )
            )
        page.update()

    def handle_pokemon_select(box_entry_id: UUID):
        state["selected_pokemon_id"] = box_entry_id
        state["detail_form_id"] = "base"  # Reset form on new selection
        render_box_grid(update_page=False)
        render_detail_drawer(update_page=False)
        page.update()

    def handle_toggle_favorite(box_entry: BoxEntry, fav_val: bool):
        box_repo, _, _, session = get_repositories()
        try:
            box_repo.update_metadata(box_entry.pokemon.canonical_id, is_favorite=fav_val)
            export_box_entries_to_csv(box_repo.list_entries())
            refresh_box()
        finally:
            session.close()

    def handle_delete_pokemon(box_entry_id: UUID):
        box_repo, team_repo, _, session = get_repositories()
        try:
            entry = box_repo.load_entry(str(box_entry_id))
            if entry:
                # Remove team member assignments first to avoid constraint failures
                team_repo.delete_members_by_box_entry_id(box_entry_id)
                # Delete from box
                box_repo.delete_by_canonical_id(entry.pokemon.canonical_id)
                # Sync CSV
                export_box_entries_to_csv(box_repo.list_entries())
                
                state["selected_pokemon_id"] = None
                show_toast(f"Removed {entry.pokemon.display_name} from box")
                refresh_box()
                refresh_teams()
        finally:
            session.close()

    def handle_save_notes(box_entry_id: UUID, notes: str):
        box_repo, _, _, session = get_repositories()
        try:
            entry = box_repo.load_entry(str(box_entry_id))
            if entry:
                box_repo.update_metadata(entry.pokemon.canonical_id, notes=notes)
                export_box_entries_to_csv(box_repo.list_entries())
                refresh_box()
                show_toast("Notes saved")
        finally:
            session.close()

    def handle_save_tags(box_entry_id: UUID, tags_str: str):
        tags = [tag.strip() for tag in tags_str.split(",") if tag.strip()]
        box_repo, _, _, session = get_repositories()
        try:
            entry = box_repo.load_entry(str(box_entry_id))
            if entry:
                box_repo.update_metadata(entry.pokemon.canonical_id, tags=tags)
                export_box_entries_to_csv(box_repo.list_entries())
                refresh_box()
                show_toast("Tags updated")
        finally:
            session.close()

    def handle_open_new_team_modal(e=None):
        new_team_modal.open = True
        page.update()

    def handle_team_select(team_id_str: str):
        if team_id_str:
            state["active_team_id"] = UUID(team_id_str)
        else:
            state["active_team_id"] = None
        render_team_builder()

    def handle_delete_team():
        if state["active_team_id"] is None:
            return
        box_repo, team_repo, _, session = get_repositories()
        try:
            team_record = team_repo.get(state["active_team_id"])
            if team_record:
                # delete all slots
                for m in team_repo.list_members(state["active_team_id"]):
                    team_repo.delete_member(state["active_team_id"], m.slot_position)
                team_repo.delete(state["active_team_id"])
                show_toast(f"Team '{team_record.name}' deleted")
                state["active_team_id"] = None
                refresh_teams()
        finally:
            session.close()

    def handle_export_csv():
        box_repo, _, _, session = get_repositories()
        try:
            entries = box_repo.list_entries()
            export_box_entries_to_csv(entries)
            show_toast("CSV Export refreshed in workspace root!")
        finally:
            session.close()

    # --- Slot Actions ---
    def handle_open_assign_modal(slot_position: int):
        state["assigning_slot_position"] = slot_position
        
        # Populate list of available box entry controls
        assign_modal.content.controls.clear()
        
        if not state["box_entries"]:
            assign_modal.content.controls.append(
                ft.Text("No Pokémon available in your box. Add some in the Box tab first!")
            )
        else:
            for entry in state["box_entries"]:
                def make_click_handler(e_id=entry.box_entry_id):
                    return lambda e: handle_assign_pokemon(e_id)

                assign_modal.content.controls.append(
                    ft.ListTile(
                        leading=ft.Image(src=entry.pokemon.sprite_url, width=40, height=40, fit=ft.BoxFit.CONTAIN) if entry.pokemon.sprite_url else ft.Icon(ft.Icons.IMAGE),
                        title=ft.Text(entry.pokemon.display_name),
                        subtitle=ft.Text(f"Form: {entry.pokemon.form_name} | BST: {entry.pokemon.total}"),
                        on_click=make_click_handler(),
                    )
                )
        
        assign_modal.open = True
        page.update()

    def handle_assign_pokemon(box_entry_id: UUID):
        if state["active_team_id"] is None or state["assigning_slot_position"] is None:
            return
        
        box_repo, team_repo, _, session = get_repositories()
        try:
            box_entry = box_repo.load_entry(str(box_entry_id))
            if box_entry:
                member = TeamMember(
                    box_entry_id=box_entry_id,
                    slot_position=state["assigning_slot_position"],
                    selected_form="base",
                    item=None,
                    moveset=[],
                    ability=_get_obj_attr(box_entry.pokemon.abilities[0], "name").title() if box_entry.pokemon.abilities else None,
                    notes=""
                )
                team_repo.upsert_member(state["active_team_id"], member)
                show_toast(f"Assigned {box_entry.pokemon.display_name} to slot {state['assigning_slot_position']}")
                assign_modal.open = False
                render_team_builder()
        finally:
            session.close()

    def handle_remove_member(slot_position: int):
        if state["active_team_id"] is None:
            return
        _, team_repo, _, session = get_repositories()
        try:
            team_repo.delete_member(state["active_team_id"], slot_position)
            show_toast(f"Cleared slot {slot_position}")
            render_team_builder()
        finally:
            session.close()

    def handle_update_member_field(
        slot_position: int,
        selected_form: str,
        ability: str,
        item: str,
        moves_str: str,
        notes: str,
        nature: str | None = None,
        level: int | None = None,
        evs: dict | None = None,
        ivs: dict | None = None,
    ):
        if state["active_team_id"] is None:
            return
        _, team_repo, _, session = get_repositories()
        try:
            member_recs = team_repo.list_members(state["active_team_id"])
            matching_rec = next((m for m in member_recs if m.slot_position == slot_position), None)
            if matching_rec:
                matching = matching_rec.to_domain()
                moves = [
                    PokemonMove(name=m_name.strip())
                    for m_name in moves_str.split(",")
                    if m_name.strip()
                ]
                updated_member = TeamMember(
                    team_member_id=matching.team_member_id,
                    box_entry_id=matching.box_entry_id,
                    slot_position=slot_position,
                    selected_form=selected_form,
                    item=item.strip() or None,
                    moveset=moves,
                    ability=ability.strip() or None,
                    notes=notes.strip(),
                    nature=nature if nature is not None else matching.nature,
                    level=level if level is not None else matching.level,
                    evs=evs if evs is not None else matching.evs,
                    ivs=ivs if ivs is not None else matching.ivs,
                )
                team_repo.upsert_member(state["active_team_id"], updated_member)
                show_toast("Team slot updated")
                render_team_builder()
        finally:
            session.close()


    # --- Renderers ---
    def render_box_grid(update_page: bool = True):
        has_tags_visible = any(e.tags for e in state["box_entries"])
        if state["all_stats_visible"]:
            box_grid.child_aspect_ratio = 0.55 if has_tags_visible else 0.60
        else:
            box_grid.child_aspect_ratio = 0.65 if has_tags_visible else 0.80

        mega_species = state.get("mega_species_set", set())

        def _passes_filter(entry) -> bool:
            # Text search: name OR tag OR type (OR within text search)
            if state["search_query"]:
                q = state["search_query"]
                if not (q in entry.pokemon.display_name.lower() or
                        any(q in t.lower() for t in entry.tags) or
                        any(q in t.lower() for t in entry.pokemon.types)):
                    return False
            # Type filter pill (AND with text search)
            if state["selected_type_filter"] != "all":
                if state["selected_type_filter"] not in [t.lower() for t in entry.pokemon.types]:
                    return False
            # Favorites toggle
            if state["favorites_only"] and not entry.is_favorite:
                return False
            # Mega capable toggle
            if state["megas_only"] and entry.pokemon.species_name.lower() not in mega_species:
                return False
            # BST range
            if not (state["bst_min"] <= entry.pokemon.total <= state["bst_max"]):
                return False
            return True

        filtered = [e for e in state["box_entries"] if _passes_filter(e)]

        # Sorting logic
        if state["sort_by"] == "Name (Asc)":
            filtered.sort(key=lambda e: e.pokemon.display_name.lower())
        elif state["sort_by"] == "Name (Desc)":
            filtered.sort(key=lambda e: e.pokemon.display_name.lower(), reverse=True)
        elif state["sort_by"] == "Stat Total (Desc)":
            filtered.sort(key=lambda e: e.pokemon.total, reverse=True)
        elif state["sort_by"] == "HP (Desc)":
            filtered.sort(key=lambda e: e.pokemon.stats.hp, reverse=True)
        elif state["sort_by"] == "Attack (Desc)":
            filtered.sort(key=lambda e: e.pokemon.stats.attack, reverse=True)
        elif state["sort_by"] == "Speed (Desc)":
            filtered.sort(key=lambda e: e.pokemon.stats.speed, reverse=True)

        new_cards = []
        for entry in filtered:
            has_megas = entry.pokemon.species_name.lower() in mega_species

            # Card styling
            types_row = ft.Row(
                alignment=ft.MainAxisAlignment.CENTER,
                spacing=5,
                controls=[
                    ft.Container(
                        content=ft.Text(t.upper(), size=10, weight=ft.FontWeight.BOLD, color=Colors.WHITE),
                        bgcolor=TYPE_COLORS.get(t.lower(), "#68A090"),
                        padding=ft.Padding.symmetric(horizontal=8, vertical=4),
                        border_radius=5
                    )
                    for t in entry.pokemon.types
                ]
            )

            def make_stat_cell(lbl: str, val: int, hex_col: str):
                return ft.Container(
                    expand=True,
                    bgcolor="#111827",
                    border_radius=4,
                    padding=ft.Padding.symmetric(horizontal=5, vertical=4),
                    content=ft.Column(
                        spacing=2,
                        controls=[
                            ft.Row(
                                alignment=ft.MainAxisAlignment.SPACE_BETWEEN,
                                controls=[
                                    ft.Text(lbl, size=9, weight=ft.FontWeight.BOLD, color=hex_col),
                                    ft.Text(str(val), size=9, weight=ft.FontWeight.BOLD, color=Colors.WHITE),
                                ]
                            ),
                            ft.ProgressBar(
                                value=min(1.0, max(0.0, val / 180.0)),
                                color=hex_col,
                                bgcolor="#374151",
                                height=3,
                                border_radius=2
                            )
                        ]
                    )
                )

            stats_block = ft.Container(visible=False)
            if state["all_stats_visible"]:
                stats_block = ft.Container(
                    margin=ft.Margin.only(top=4, bottom=4),
                    content=ft.Column(
                        spacing=3,
                        controls=[
                            ft.Row(
                                spacing=3,
                                controls=[
                                    make_stat_cell("HP", entry.pokemon.stats.hp, STAT_COLORS["hp"]),
                                    make_stat_cell("ATK", entry.pokemon.stats.attack, STAT_COLORS["attack"]),
                                    make_stat_cell("DEF", entry.pokemon.stats.defense, STAT_COLORS["defense"]),
                                ]
                            ),
                            ft.Row(
                                spacing=3,
                                controls=[
                                    make_stat_cell("SPA", entry.pokemon.stats.special_attack, STAT_COLORS["special_attack"]),
                                    make_stat_cell("SPD", entry.pokemon.stats.special_defense, STAT_COLORS["special_defense"]),
                                    make_stat_cell("SPE", entry.pokemon.stats.speed, STAT_COLORS["speed"]),
                                ]
                            ),
                        ]
                    )
                )
                stats_block.visible = True

            def make_select_handler(e_id=entry.box_entry_id):
                return lambda e: handle_pokemon_select(e_id)

            img_dim = 64 if state["all_stats_visible"] else 80

            card_info_controls = [
                ft.Text(entry.pokemon.display_name, size=15, weight=ft.FontWeight.BOLD, overflow=ft.TextOverflow.ELLIPSIS),
            ]
            if has_megas:
                card_info_controls.append(
                    ft.Container(
                        content=ft.Row(
                            alignment=ft.MainAxisAlignment.CENTER,
                            spacing=2,
                            tight=True,
                            controls=[
                                ft.Icon(ft.Icons.FLASH_ON, size=10, color=Colors.AMBER_400),
                                ft.Text("Mega Available", size=10, weight=ft.FontWeight.BOLD, color=Colors.AMBER_400)
                            ]
                        ),
                        bgcolor="#291d03",
                        border_radius=10,
                        padding=ft.Padding.symmetric(horizontal=6, vertical=2),
                        border=ft.Border.all(1, Colors.AMBER_400)
                    )
                )
            else:
                card_info_controls.append(
                    ft.Text(f"Form: {entry.pokemon.form_name}", size=11, color=Colors.GREY_400)
                )

            card_info_controls.extend([stats_block, types_row])

            # Clickable tag pills — clicking a tag filters the box to that tag
            if entry.tags:
                card_info_controls.append(
                    ft.Row(
                        wrap=True, spacing=4, run_spacing=4,
                        controls=[
                            ft.Container(
                                content=ft.Text(tag, size=9, color=Colors.BLUE_400),
                                bgcolor="#1e3a5f",
                                border=ft.Border.all(1, Colors.BLUE_400),
                                border_radius=6,
                                padding=ft.Padding.symmetric(horizontal=6, vertical=2),
                                on_click=lambda e, t=tag: handle_filter_change(t),
                                ink=True,
                            )
                            for tag in entry.tags
                        ]
                    )
                )

            card = ft.Card(
                content=ft.Container(
                    content=ft.Column(
                        alignment=ft.MainAxisAlignment.SPACE_BETWEEN,
                        controls=[
                            ft.Row(
                                alignment=ft.MainAxisAlignment.SPACE_BETWEEN,
                                controls=[
                                    ft.IconButton(
                                        icon=ft.Icons.STAR if entry.is_favorite else ft.Icons.STAR_BORDER,
                                        icon_color=Colors.YELLOW if entry.is_favorite else Colors.GREY_600,
                                        on_click=lambda e, ent=entry: handle_toggle_favorite(ent, not ent.is_favorite),
                                        tooltip="Favorite"
                                    ),
                                    ft.Text(f"BST {entry.pokemon.total}", size=12, weight=ft.FontWeight.BOLD, color=Colors.AMBER_400)
                                ]
                            ),
                            ft.Container(
                                content=ft.Image(
                                    src=entry.pokemon.sprite_url,
                                    width=img_dim,
                                    height=img_dim,
                                    fit=ft.BoxFit.CONTAIN,
                                ) if entry.pokemon.sprite_url else ft.Icon(ft.Icons.IMAGE, size=60),
                                alignment=ft.Alignment.CENTER
                            ),
                            ft.Column(
                                horizontal_alignment=ft.CrossAxisAlignment.CENTER,
                                controls=card_info_controls
                            )
                        ]
                    ),
                    padding=8,
                    on_click=make_select_handler()
                ),
                bgcolor=Colors.CARD_SELECTED if state["selected_pokemon_id"] == entry.box_entry_id else Colors.CARD_BG
            )
            new_cards.append(card)
        
        box_grid.controls = new_cards
        if update_page:
            page.update()

    def close_detail_container(e=None):
        state["selected_pokemon_id"] = None
        detail_panel.visible = False
        render_box_grid(update_page=False)
        page.update()

    def render_detail_drawer(update_page: bool = True):
        detail_container.controls.clear()
        
        if state["selected_pokemon_id"] is None:
            detail_panel.visible = False
            if update_page:
                page.update()
            return
        
        # Load the selected Pokemon & its Megas
        box_repo, _, mega_repo, session = get_repositories()
        try:
            entry = box_repo.load_entry(str(state["selected_pokemon_id"]))
            megas = sync_mega_evolutions_for_species(session, entry.pokemon.species_name) if entry else []
        finally:
            session.close()

        if entry is None:
            detail_panel.visible = False
            if update_page:
                page.update()
            return

        detail_panel.visible = True

        # Header
        detail_container.controls.append(
            ft.Container(
                content=ft.Row(
                    alignment=ft.MainAxisAlignment.SPACE_BETWEEN,
                    controls=[
                        ft.Row(spacing=8, controls=[
                            ft.Icon(ft.Icons.CATCHING_POKEMON, color=Colors.AMBER_400, size=16),
                            ft.Text("POKÉMON DETAILS", weight=ft.FontWeight.BOLD, size=13,
                                    color=Colors.AMBER_400)
                        ]),
                        ft.IconButton(
                            icon=ft.Icons.CLOSE, icon_size=18,
                            icon_color=Colors.GREY_400,
                            on_click=lambda e: close_detail_container()
                        )
                    ]
                ),
                bgcolor=Colors.CARD_BG,
                border_radius=8,
                padding=ft.Padding.symmetric(horizontal=12, vertical=8),
                border=ft.Border.all(1, Colors.DIVIDER)
            )
        )

        active_form_id = state.get("detail_form_id", "base")
        active_mega = next((m for m in megas if m.canonical_id == active_form_id), None)

        if active_mega:
            display_sprite = active_mega.sprite_url or entry.pokemon.sprite_url
            display_hp = active_mega.hp
            display_atk = active_mega.attack
            display_def = active_mega.defense
            display_spa = active_mega.special_attack
            display_spd = active_mega.special_defense
            display_spe = active_mega.speed
            display_sub = f"⚡ Mega Form · {active_mega.display_name}"
            display_types = active_mega.types
        else:
            display_sprite = entry.pokemon.sprite_url
            display_hp = entry.pokemon.stats.hp
            display_atk = entry.pokemon.stats.attack
            display_def = entry.pokemon.stats.defense
            display_spa = entry.pokemon.stats.special_attack
            display_spd = entry.pokemon.stats.special_defense
            display_spe = entry.pokemon.stats.speed
            display_sub = f"#{entry.pokemon.dex_number or '???'}  ·  {entry.pokemon.form_name}"
            display_types = entry.pokemon.types

        # Form Switcher Pills (if Megas exist)
        if megas:
            def set_detail_form(fid):
                state["detail_form_id"] = fid
                render_detail_drawer()

            form_pills = []
            base_active = (active_form_id == "base")
            form_pills.append(
                ft.Container(
                    content=ft.Text("Base Form", size=11, weight=ft.FontWeight.BOLD, color=Colors.AMBER_400 if base_active else Colors.WHITE),
                    bgcolor="#78350f" if base_active else "#1e293b",
                    padding=ft.Padding.symmetric(horizontal=10, vertical=4),
                    border_radius=12,
                    border=ft.Border.all(1, Colors.AMBER_400 if base_active else Colors.DIVIDER),
                    on_click=lambda e: set_detail_form("base")
                )
            )
            for m in megas:
                m_active = (active_form_id == m.canonical_id)
                form_pills.append(
                    ft.Container(
                        content=ft.Text(f"⚡ {m.form_name}", size=11, weight=ft.FontWeight.BOLD, color=Colors.AMBER_400 if m_active else Colors.WHITE),
                        bgcolor="#78350f" if m_active else "#1e293b",
                        padding=ft.Padding.symmetric(horizontal=10, vertical=4),
                        border_radius=12,
                        border=ft.Border.all(1, Colors.AMBER_400 if m_active else Colors.DIVIDER),
                        on_click=lambda e, fid=m.canonical_id: set_detail_form(fid)
                    )
                )

            detail_container.controls.append(
                ft.Row(controls=form_pills, alignment=ft.MainAxisAlignment.CENTER, spacing=6)
            )

        # Sprite avatar
        detail_container.controls.append(
            ft.Container(
                content=ft.Image(
                    src=display_sprite, width=110, height=110,
                    fit=ft.BoxFit.CONTAIN
                ) if display_sprite else ft.Icon(ft.Icons.IMAGE, size=80),
                bgcolor=Colors.CARD_BG,
                border_radius=55,
                width=130, height=130,
                alignment=ft.Alignment.CENTER,
                border=ft.Border.all(2, Colors.DIVIDER),
                margin=ft.Margin.symmetric(vertical=6)
            )
        )

        # Name / info & Type Badges
        type_badges = []
        for t in display_types:
            bg_col = TYPE_COLORS.get(t.lower(), "#777777")
            type_badges.append(
                ft.Container(
                    content=ft.Text(t.upper(), size=10, weight=ft.FontWeight.BOLD, color=Colors.WHITE),
                    bgcolor=bg_col,
                    border_radius=4,
                    padding=ft.Padding.symmetric(horizontal=6, vertical=2)
                )
            )

        detail_container.controls.append(
            ft.Column(
                horizontal_alignment=ft.CrossAxisAlignment.CENTER,
                spacing=4,
                controls=[
                    ft.Text(entry.pokemon.display_name, size=20, weight=ft.FontWeight.BOLD),
                    ft.Row(controls=type_badges, alignment=ft.MainAxisAlignment.CENTER, spacing=4),
                    ft.Container(
                        content=ft.Text(display_sub, size=12, color=Colors.GREY_400),
                        bgcolor=Colors.CARD_BG,
                        border_radius=6,
                        padding=ft.Padding.symmetric(horizontal=10, vertical=4)
                    ),
                ]
            )
        )

        # Section label helper
        def _section(label):
            return ft.Container(
                content=ft.Text(label, size=11, weight=ft.FontWeight.BOLD,
                                color=Colors.GREY_400),
                border=ft.Border(bottom=ft.BorderSide(1, Colors.DIVIDER)),
                padding=ft.Padding.only(bottom=4)
            )

        # Base Stats
        detail_container.controls.append(_section("STAT OVERVIEW"))
        stats_list = [
            ("HP",  display_hp,  Colors.RED_400),
            ("Atk", display_atk, Colors.ORANGE_400),
            ("Def", display_def, Colors.YELLOW_400),
            ("SpA", display_spa, Colors.BLUE_400),
            ("SpD", display_spd, Colors.GREEN_400),
            ("Spe", display_spe, Colors.PINK_400),
        ]
        stats_column = ft.Column(spacing=6)
        for label, val, color in stats_list:
            stats_column.controls.append(
                ft.Row(
                    alignment=ft.MainAxisAlignment.SPACE_BETWEEN,
                    spacing=8,
                    controls=[
                        ft.Container(
                            content=ft.Text(label, size=11, weight=ft.FontWeight.BOLD, color=color),
                            width=30
                        ),
                        ft.ProgressBar(
                            value=min(val / 255.0, 1.0),
                            color=color,
                            bgcolor=Colors.GREY_800,
                            expand=True,
                            height=7,
                            border_radius=4
                        ),
                        ft.Text(str(val), size=11, weight=ft.FontWeight.BOLD, width=30,
                                text_align=ft.TextAlign.RIGHT)
                    ]
                )
            )
        detail_container.controls.append(stats_column)

        # Notes
        detail_container.controls.append(_section("NOTES"))
        notes_field = ft.TextField(
            label="User Notes / Nickname",
            value=entry.notes,
            multiline=True,
            max_lines=3,
            text_size=13,
            on_submit=lambda e, e_id=entry.box_entry_id: handle_save_notes(e_id, e.control.value)
        )
        notes_btn = ft.TextButton(
            "Save Notes",
            icon=ft.Icons.SAVE,
            on_click=lambda e, e_id=entry.box_entry_id: handle_save_notes(e_id, notes_field.value)
        )
        detail_container.controls.append(ft.Column(spacing=4, controls=[notes_field, notes_btn]))

        # Tags
        detail_container.controls.append(_section("TAGS"))
        tags_field = ft.TextField(
            label="Tags (comma separated)",
            value=", ".join(entry.tags),
            text_size=13,
        )
        tags_btn = ft.TextButton(
            "Update Tags",
            icon=ft.Icons.TAG,
            on_click=lambda e, e_id=entry.box_entry_id: handle_save_tags(e_id, tags_field.value)
        )
        detail_container.controls.append(ft.Column(spacing=4, controls=[tags_field, tags_btn]))

        # Weaknesses placeholder
        detail_container.controls.append(_section("DEFENSIVE WEAKNESSES"))
        detail_container.controls.append(
            ft.Container(
                content=ft.Text(
                    "TODO: Type Effectiveness Matrix (Backend Integration)",
                    size=11, color=Colors.GREY_500, italic=True
                ),
                bgcolor=Colors.CARD_BG,
                border=ft.Border.all(1, Colors.DIVIDER),
                padding=ft.Padding.all(10),
                border_radius=8
            )
        )

        # Delete button
        detail_container.controls.append(
            ft.Container(
                content=ft.ElevatedButton(
                    "Delete From Box",
                    icon=ft.Icons.DELETE,
                    bgcolor="#991b1b",
                    color=Colors.WHITE,
                    on_click=lambda e, e_id=entry.box_entry_id: handle_delete_pokemon(e_id)
                ),
                alignment=ft.Alignment.CENTER,
                margin=ft.Margin.only(top=10)
            )
        )

        if update_page:
            page.update()

    def render_team_builder():
        team_grid.controls.clear()
        
        if state["active_team_id"] is None:
            team_grid.controls.append(
                ft.Container(
                    content=ft.Text("No active team. Please create a team above to start planning!"),
                    alignment=ft.Alignment.CENTER,
                    expand=True
                )
            )
            update_team_totals()
            page.update()
            return

        box_repo, team_repo, _, session = get_repositories()
        try:
            team = team_repo.load_team(state["active_team_id"])
            members = team_repo.list_members(state["active_team_id"])
        finally:
            session.close()

        if team is None:
            return

        # Render 6 slots
        for slot in range(1, 7):
            matching_member = next((m for m in members if m.slot_position == slot), None)
            
            if matching_member is None:
                # Render Empty Slot Card
                def make_open_handler(s_pos=slot):
                    return lambda e: handle_open_assign_modal(s_pos)

                slot_card = ft.Container(
                    content=ft.Column(
                        alignment=ft.MainAxisAlignment.CENTER,
                        horizontal_alignment=ft.CrossAxisAlignment.CENTER,
                        spacing=6,
                        controls=[
                            ft.Container(
                                content=ft.Text(f"{slot}", size=10, weight=ft.FontWeight.BOLD, color=Colors.GREY_500),
                                bgcolor="#1e293b", border_radius=10,
                                padding=ft.Padding.symmetric(horizontal=8, vertical=2),
                            ),
                            ft.Icon(ft.Icons.ADD_CIRCLE_OUTLINE, size=32, color=Colors.GREY_500),
                            ft.Text("Empty Slot", size=11, color=Colors.GREY_500),
                            ft.Container(
                                content=ft.Text("Assign Pokémon", size=11, color=Colors.AMBER_400,
                                                weight=ft.FontWeight.W_600),
                                border=ft.Border.all(1, Colors.AMBER_700),
                                border_radius=6,
                                padding=ft.Padding.symmetric(horizontal=10, vertical=6),
                                on_click=make_open_handler(),
                                ink=True,
                            )
                        ]
                    ),
                    border=ft.Border.all(1, "#334155"),
                    border_radius=10,
                    padding=16,
                    alignment=ft.Alignment.CENTER,
                    bgcolor="#111827",
                    height=160,
                )
            else:
                # Load corresponding box entry & species megas
                box_repo, _, mega_repo, session = get_repositories()
                try:
                    box_entry = box_repo.load_entry(str(matching_member.box_entry_id))
                    megas = sync_mega_evolutions_for_species(session, box_entry.pokemon.species_name) if box_entry else []
                finally:
                    session.close()

                if box_entry is None:
                    continue
                
                pokemon = box_entry.pokemon
                selected_form = matching_member.selected_form or "base"
                active_mega = next((m for m in megas if m.canonical_id == selected_form), None)

                if active_mega:
                    card_sprite = active_mega.sprite_url or pokemon.sprite_url
                    card_bst = active_mega.hp + active_mega.attack + active_mega.defense + active_mega.special_attack + active_mega.special_defense + active_mega.speed
                    card_name = f"{pokemon.display_name} (⚡ {active_mega.form_name})"
                else:
                    card_sprite = pokemon.sprite_url
                    card_bst = pokemon.total
                    card_name = pokemon.display_name

                # ── Auto-save helpers ────────────────────────────────────────
                def _auto_save_form(e, s_pos=slot, cur_ab=matching_member.ability, cur_item=matching_member.item, cur_moves=matching_member.moveset, cur_notes=matching_member.notes):
                    moves_str = ", ".join(_get_obj_attr(mv, "name") for mv in cur_moves)
                    handle_update_member_field(s_pos, e.control.value, cur_ab or "", cur_item or "", moves_str, cur_notes or "")

                def _auto_save_ability(e, s_pos=slot, cur_form=selected_form, cur_item=matching_member.item, cur_moves=matching_member.moveset, cur_notes=matching_member.notes):
                    moves_str = ", ".join(_get_obj_attr(mv, "name") for mv in cur_moves)
                    handle_update_member_field(s_pos, cur_form, e.control.value, cur_item or "", moves_str, cur_notes or "")

                # Form input elements for member attributes
                form_drop = None
                if megas:
                    form_options = [
                        ft.dropdown.Option("base", text=f"Base ({pokemon.form_name})"),
                        *[ft.dropdown.Option(m.canonical_id, text=f"⚡ {m.display_name}") for m in megas]
                    ]
                    form_drop = ft.Dropdown(
                        label="Active Form",
                        value=selected_form,
                        options=form_options,
                        text_size=12,
                        on_select=_auto_save_form,
                    )

                ability_options = [
                    ft.dropdown.Option(text=_get_obj_attr(ab, "name").title().replace("-", " "))
                    for ab in pokemon.abilities
                ]
                
                ability_drop = ft.Dropdown(
                    label="Ability",
                    value=matching_member.ability or (ability_options[0].text if ability_options else ""),
                    options=ability_options,
                    text_size=12,
                    on_select=_auto_save_ability,
                )
                
                # Build rich item slot widget ----------------------------------------
                current_item_id = matching_member.item
                current_item_rec = state["items_by_id"].get(current_item_id) if current_item_id else None

                # Run guardrail validation
                validation = validate_item_assignment(
                    current_item_rec,
                    species_name=pokemon.species_name,
                    team_items=[
                        state["items_by_id"].get(m.item)
                        for m in (team_repo.list_members(state["active_team_id"]) if False else [])
                        if m.item
                    ]
                ) if current_item_rec else None

                # Auto-unlock Mega form if Mega Stone matches this species
                if (current_item_rec and current_item_rec.target_species and
                        current_item_rec.target_species.lower() == pokemon.species_name.lower() and
                        current_item_rec.target_form):
                    # Inject Mega Stone unlocked form into the form drop if not already present
                    stone_target_id = next(
                        (m.canonical_id for m in megas if current_item_rec.target_form in m.canonical_id.lower()),
                        None
                    )
                    if stone_target_id and form_drop:
                        form_drop.value = stone_target_id
                        selected_form = stone_target_id
                        active_mega = next((m for m in megas if m.canonical_id == selected_form), None)
                        if active_mega:
                            card_sprite = active_mega.sprite_url or pokemon.sprite_url
                            card_bst = (active_mega.hp + active_mega.attack + active_mega.defense +
                                        active_mega.special_attack + active_mega.special_defense + active_mega.speed)
                            card_name = f"{pokemon.display_name} (⚡ {active_mega.form_name})"

                # Compute effective stats for modifier display
                effective_stats = compute_effective_stats(pokemon.stats, current_item_rec) if current_item_rec else pokemon.stats
                speed_modified = (effective_stats.speed != pokemon.stats.speed)

                # Item slot button label
                if current_item_rec:
                    item_label_txt = current_item_rec.display_name
                    item_label_col = Colors.WHITE
                    item_icon_src = current_item_rec.sprite_url
                else:
                    item_label_txt = "Select Held Item…"
                    item_label_col = Colors.GREY_500
                    item_icon_src = None

                # Guardrail badge
                guardrail_controls = []
                if validation and validation.error:
                    guardrail_controls.append(
                        ft.Container(
                            content=ft.Row(spacing=4, controls=[
                                ft.Icon(ft.Icons.ERROR, size=12, color=Colors.RED_400),
                                ft.Text(validation.error, size=10, color=Colors.RED_400,
                                        overflow=ft.TextOverflow.ELLIPSIS, max_lines=2),
                            ]),
                            bgcolor="#3b0000",
                            border=ft.Border.all(1, Colors.RED_400),
                            border_radius=5,
                            padding=ft.Padding.symmetric(horizontal=6, vertical=4),
                        )
                    )
                elif validation and validation.warning:
                    guardrail_controls.append(
                        ft.Container(
                            content=ft.Row(spacing=4, controls=[
                                ft.Icon(ft.Icons.WARNING_ROUNDED, size=12, color=Colors.AMBER_400),
                                ft.Text(validation.warning, size=10, color=Colors.AMBER_400,
                                        overflow=ft.TextOverflow.ELLIPSIS, max_lines=2),
                            ]),
                            bgcolor="#291d03",
                            border=ft.Border.all(1, Colors.AMBER_400),
                            border_radius=5,
                            padding=ft.Padding.symmetric(horizontal=6, vertical=4),
                        )
                    )

                # Multi-stat modifier badges (all stats with zero-guard)
                def _make_stat_badges(effective, base):
                    badges = []
                    for stat_key, label, color in [
                        ("attack",          "Atk", STAT_COLORS["attack"]),
                        ("defense",         "Def", STAT_COLORS["defense"]),
                        ("special_attack",  "SpA", STAT_COLORS["special_attack"]),
                        ("special_defense", "SpD", STAT_COLORS["special_defense"]),
                        ("speed",           "Spe", STAT_COLORS["speed"]),
                    ]:
                        eff = getattr(effective, stat_key)
                        base_v = getattr(base, stat_key)
                        if eff != base_v and base_v:  # zero-guard
                            delta = round((eff / base_v - 1) * 100)
                            sign = "+" if delta > 0 else ""
                            badges.append(ft.Container(
                                content=ft.Text(f"{label} {eff} ({sign}{delta}%)", size=9,
                                                weight=ft.FontWeight.BOLD, color=color),
                                bgcolor=Colors.CARD_BG,
                                border=ft.Border.all(1, color),
                                border_radius=4,
                                padding=ft.Padding.symmetric(horizontal=4, vertical=2),
                            ))
                    return badges

                stat_badges = _make_stat_badges(effective_stats, pokemon.stats)

                item_slot_widget = ft.Container(
                    content=ft.Column(spacing=4, controls=[
                        ft.Row(
                            alignment=ft.MainAxisAlignment.SPACE_BETWEEN,
                            controls=[
                                ft.Text("Held Item", size=10, weight=ft.FontWeight.BOLD,
                                        color=Colors.GREY_400),
                                ft.IconButton(
                                    icon=ft.Icons.CLOSE, icon_size=14,
                                    icon_color=Colors.GREY_500,
                                    tooltip="Remove Item",
                                    visible=current_item_rec is not None,
                                    on_click=lambda e, s=slot: _apply_item_to_slot(s, None),
                                )
                            ]
                        ),
                        ft.Container(
                            content=ft.Row(spacing=8, controls=[
                                ft.Image(src=item_icon_src, width=24, height=24, fit=ft.BoxFit.CONTAIN)
                                if item_icon_src else ft.Icon(ft.Icons.DIAMOND_OUTLINED, size=20, color=Colors.GREY_500),
                                ft.Text(item_label_txt, size=12, color=item_label_col, expand=True,
                                        overflow=ft.TextOverflow.ELLIPSIS),
                                ft.Icon(ft.Icons.ARROW_FORWARD_IOS, size=12, color=Colors.GREY_500),
                            ]),
                            bgcolor=Colors.CARD_BG,
                            border_radius=6,
                            border=ft.Border.all(1, Colors.DIVIDER),
                            padding=ft.Padding.symmetric(horizontal=8, vertical=8),
                            on_click=lambda e, s=slot: _open_item_picker(s),
                            ink=True,
                        ),
                        # Stat modifier badges below the item button
                        *([ ft.Row(wrap=True, spacing=4, run_spacing=4, controls=stat_badges) ]
                          if stat_badges else []),
                        *guardrail_controls,
                    ]),
                )
                # -------------------------------------------------------------------

                # ── 4-slot move chip UI ──────────────────────────────────────
                current_moves = [_get_obj_attr(mv, "name") for mv in matching_member.moveset]
                while len(current_moves) < 4:
                    current_moves.append("")

                def _save_move(slot_pos, move_idx, new_name, form_val, ability_val, item_val, notes_val, all_moves):
                    updated = list(all_moves)
                    updated[move_idx] = new_name.strip()
                    moves_str = ", ".join(m for m in updated if m)
                    handle_update_member_field(slot_pos, form_val, ability_val, item_val or "", moves_str, notes_val or "")

                def _make_move_chip(s_pos, m_idx, m_name, f_val, ab_val, item_val, notes_val, all_moves):
                    move_tf = ft.TextField(value=m_name, text_size=11, border_radius=6,
                                          hint_text=f"Move {m_idx+1}", expand=True,
                                          content_padding=ft.Padding.symmetric(horizontal=8, vertical=6))
                    def _on_submit(e, sp=s_pos, mi=m_idx, tf=move_tf, fv=f_val, av=ab_val, iv=item_val, nv=notes_val, am=all_moves):
                        _save_move(sp, mi, tf.value, fv, av, iv, nv, am)
                    move_tf.on_submit = _on_submit
                    move_tf.on_blur = _on_submit
                    return move_tf

                move_chips_row1 = ft.Row(spacing=4, controls=[
                    _make_move_chip(slot, i, current_moves[i],
                                    selected_form, matching_member.ability or "",
                                    current_item_id, matching_member.notes or "",
                                    current_moves)
                    for i in range(2)
                ])
                move_chips_row2 = ft.Row(spacing=4, controls=[
                    _make_move_chip(slot, i, current_moves[i],
                                    selected_form, matching_member.ability or "",
                                    current_item_id, matching_member.notes or "",
                                    current_moves)
                    for i in range(2, 4)
                ])
                moves_widget = ft.Column(spacing=4, controls=[
                    ft.Text("Moves", size=10, weight=ft.FontWeight.BOLD, color=Colors.GREY_400),
                    move_chips_row1,
                    move_chips_row2,
                ])

                notes_field = ft.TextField(
                    label="Planning Notes",
                    value=matching_member.notes or "",
                    text_size=11,
                    multiline=True, max_lines=2,
                )

                def make_update_handler(s_pos=slot, fm_dr=form_drop, ab_dr=ability_drop, item_id=current_item_id, mv=current_moves, nt_fl=notes_field):
                    return lambda e: handle_update_member_field(s_pos, fm_dr.value if fm_dr else "base", ab_dr.value, item_id or "", ", ".join(m for m in mv if m), nt_fl.value)

                def make_remove_handler(s_pos=slot):
                    return lambda e: handle_remove_member(s_pos)

                # Type-color hero header
                primary_type = (pokemon.types[0].lower() if pokemon.types else "normal")
                type_col = TYPE_COLORS.get(primary_type, "#A8A878")
                type_bg = type_col + "33"  # 20% alpha tint

                type_badges_header = [
                    ft.Container(
                        content=ft.Text(t.upper(), size=9, weight=ft.FontWeight.BOLD, color=Colors.WHITE),
                        bgcolor=TYPE_COLORS.get(t.lower(), "#777777"),
                        border_radius=4,
                        padding=ft.Padding.symmetric(horizontal=5, vertical=2)
                    ) for t in (pokemon.types if not active_mega else (getattr(active_mega, "types", None) or pokemon.types))
                ]

                hero_header = ft.Container(
                    content=ft.Row(
                        alignment=ft.MainAxisAlignment.SPACE_BETWEEN,
                        controls=[
                            ft.Row(spacing=8, controls=[
                                ft.Image(src=card_sprite, width=58, height=58, fit=ft.BoxFit.CONTAIN)
                                if card_sprite else ft.Icon(ft.Icons.IMAGE, size=48),
                                ft.Column(spacing=2, controls=[
                                    ft.Row(spacing=4, controls=[
                                        ft.Container(
                                            content=ft.Text(str(slot), size=9, weight=ft.FontWeight.BOLD, color=Colors.WHITE),
                                            bgcolor=type_col + "aa", border_radius=8,
                                            padding=ft.Padding.symmetric(horizontal=6, vertical=2),
                                        ),
                                        *([ft.Container(
                                            content=ft.Text("⚡ MEGA", size=8, weight=ft.FontWeight.BOLD, color=Colors.AMBER_400),
                                            bgcolor="#291d03", border_radius=8,
                                            border=ft.Border.all(1, Colors.AMBER_700),
                                            padding=ft.Padding.symmetric(horizontal=5, vertical=2),
                                        )] if active_mega else []),
                                        *([ft.Container(
                                            content=ft.Text("📋 PLANNED", size=8, weight=ft.FontWeight.BOLD, color=Colors.AMBER_300),
                                            bgcolor="#3b2d00", border_radius=8,
                                            border=ft.Border.all(1, Colors.AMBER_500),
                                            padding=ft.Padding.symmetric(horizontal=5, vertical=2),
                                            tooltip="This Pokémon is a planned template entry and is not in your live Box roster.",
                                        )] if getattr(box_entry, "is_planned", False) else [])
                                    ]),
                                    ft.Text(pokemon.display_name, size=13, weight=ft.FontWeight.BOLD, color=Colors.WHITE),
                                    ft.Row(spacing=3, controls=type_badges_header),
                                    ft.Text(f"BST {card_bst}", size=10, color=Colors.GREY_300),
                                ])
                            ]),
                            ft.IconButton(
                                icon=ft.Icons.DELETE_OUTLINE, icon_size=16,
                                icon_color=Colors.RED_400,
                                tooltip="Remove Member",
                                on_click=make_remove_handler()
                            )
                        ]
                    ),
                    bgcolor=type_bg,
                    border_radius=ft.BorderRadius(top_left=8, top_right=8, bottom_left=0, bottom_right=0),
                    padding=ft.Padding.symmetric(horizontal=10, vertical=8),
                    border=ft.Border(bottom=ft.BorderSide(1, type_col + "66")),
                )

                # Format EV summary string e.g. "252 HP / 252 Atk / 4 Spe"
                ev_parts = []
                stat_labels = {"hp": "HP", "attack": "Atk", "defense": "Def", "special_attack": "SpA", "special_defense": "SpD", "speed": "Spe"}
                for st, lbl in stat_labels.items():
                    if matching_member.evs and matching_member.evs.get(st, 0) > 0:
                        ev_parts.append(f"{matching_member.evs[st]} {lbl}")
                ev_str = " / ".join(ev_parts) if ev_parts else "No EVs set"
                nature_str = matching_member.nature or "Hardy"
                level_str = f"Lvl {matching_member.level or 50}"

                spread_summary_widget = ft.Container(
                    content=ft.Row(
                        alignment=ft.MainAxisAlignment.SPACE_BETWEEN,
                        controls=[
                            ft.Column(spacing=2, expand=True, controls=[
                                ft.Row(spacing=6, controls=[
                                    ft.Text(f"{nature_str} Nature", size=11, weight=ft.FontWeight.BOLD, color=Colors.AMBER_400),
                                    ft.Text(f"• {level_str}", size=11, color=Colors.GREY_400),
                                ]),
                                ft.Text(f"EVs: {ev_str}", size=10, color=Colors.GREY_300, overflow=ft.TextOverflow.ELLIPSIS),
                            ]),
                            ft.IconButton(
                                icon=ft.Icons.TUNE, icon_size=16, icon_color=Colors.AMBER_400,
                                tooltip="Edit Competitive Spread & EVs/IVs",
                                on_click=lambda e, s=slot, m=matching_member: _open_spread_modal(s, m),
                            )
                        ]
                    ),
                    bgcolor="#1e293b",
                    border_radius=6,
                    padding=ft.Padding.symmetric(horizontal=8, vertical=6),
                    border=ft.Border.all(1, Colors.DIVIDER),
                )

                # -----------------------------------------------
                # Dynamic Meta Partners Widget
                # -----------------------------------------------
                synergy_controls = []
                with get_session() as syn_session:
                    tourney_svc = TournamentService(syn_session)
                    partners = tourney_svc.get_top_partners(pokemon.canonical_id, limit=4)
                    
                    if partners:
                        partner_pills = []
                        for p in partners:
                            partner_pills.append(
                                ft.Container(
                                    content=ft.Row(spacing=4, controls=[
                                        ft.Image(
                                            src=p.sprite_url, width=20, height=20, fit=ft.BoxFit.CONTAIN,
                                            error_content=ft.Icon(ft.Icons.CATCHING_POKEMON, size=16, color=Colors.GREY_500),
                                        ) if p.sprite_url else ft.Icon(ft.Icons.CATCHING_POKEMON, size=16, color=Colors.GREY_500),
                                        ft.Text(p.display_name, size=10, weight=ft.FontWeight.W_600),
                                        ft.Text(f"{p.synergy_percentage:.0f}%", size=9, color=Colors.GREEN_400)
                                    ]),
                                    bgcolor=Colors.CARD_BG,
                                    border_radius=12,
                                    padding=ft.Padding.only(left=2, top=2, bottom=2, right=8),
                                    border=ft.Border.all(1, Colors.DIVIDER),
                                    tooltip=f"Appears together in {p.co_occurrence_count} teams",
                                )
                            )
                        
                        synergy_widget = ft.Container(
                            content=ft.Column(spacing=6, controls=[
                                ft.Row(spacing=4, controls=[
                                    ft.Icon(ft.Icons.GROUP_ADD, size=14, color=Colors.AMBER_400),
                                    ft.Text("Top Tournament Partners", size=10, weight=ft.FontWeight.BOLD, color=Colors.AMBER_400),
                                    # Percentages mean little without the sample they
                                    # came from, so state it next to the heading.
                                    ft.Text(
                                        f"· {partners[0].total_target_teams} teams",
                                        size=9, color=Colors.GREY_400,
                                        tooltip=f"Share of the {partners[0].total_target_teams} tournament teams containing this Pokemon",
                                    ),
                                ]),
                                ft.Row(spacing=6, wrap=True, controls=partner_pills)
                            ]),
                            bgcolor="#1e293b",
                            border_radius=8,
                            padding=ft.Padding.symmetric(horizontal=10, vertical=8),
                            border=ft.Border.all(1, Colors.DIVIDER),
                        )
                        synergy_controls.append(synergy_widget)

                slot_controls = [hero_header]
                if form_drop:
                    slot_controls.append(form_drop)
                slot_controls.extend([
                    ability_drop,
                    item_slot_widget,
                    moves_widget,
                    spread_summary_widget,
                    *synergy_controls,
                    notes_field,
                    ft.Container(
                        content=ft.TextButton("Save Notes", icon=ft.Icons.SAVE, on_click=make_update_handler()),
                        alignment=ft.Alignment.CENTER_RIGHT,
                    )
                ])


                card_border_col = Colors.AMBER_600 if getattr(box_entry, "is_planned", False) else type_col + "55"
                slot_card = ft.Container(
                    content=ft.Column(
                        spacing=0,
                        scroll=ft.ScrollMode.AUTO,
                        controls=[
                            hero_header,
                            ft.Container(
                                content=ft.Column(spacing=6, controls=slot_controls[1:]),
                                padding=ft.Padding.symmetric(horizontal=10, vertical=8),
                            )
                        ]
                    ),
                    bgcolor=Colors.CARD_BG,
                    border_radius=10,
                    border=ft.Border.all(1 if not getattr(box_entry, "is_planned", False) else 2, card_border_col),
                )


            team_grid.controls.append(slot_card)

        update_team_totals()
        update_team_banner(members)
        update_team_validation(members)
        page.update()

    def update_team_totals():
        team_totals_row.controls.clear()
        
        if state["active_team_id"] is None:
            page.update()
            return

        box_repo, team_repo, mega_repo, session = get_repositories()
        try:
            members = team_repo.list_members(state["active_team_id"])
            total_hp = total_attack = total_defense = total_spa = total_spd = total_speed = 0
            
            for m in members:
                b_entry = box_repo.load_entry(str(m.box_entry_id))
                if b_entry:
                    mega_rec = mega_repo.get(m.selected_form) if (m.selected_form and m.selected_form != "base") else None
                    if mega_rec:
                        total_hp += mega_rec.hp
                        total_attack += mega_rec.attack
                        total_defense += mega_rec.defense
                        total_spa += mega_rec.special_attack
                        total_spd += mega_rec.special_defense
                        total_speed += mega_rec.speed
                    else:
                        total_hp += b_entry.pokemon.stats.hp
                        total_attack += b_entry.pokemon.stats.attack
                        total_defense += b_entry.pokemon.stats.defense
                        total_spa += b_entry.pokemon.stats.special_attack
                        total_spd += b_entry.pokemon.stats.special_defense
                        total_speed += b_entry.pokemon.stats.speed
        finally:
            session.close()

        MAX_STAT = 6 * 255
        stat_rows = [
            ("HP",  total_hp,     STAT_COLORS["hp"]),
            ("Atk", total_attack, STAT_COLORS["attack"]),
            ("Def", total_defense,STAT_COLORS["defense"]),
            ("SpA", total_spa,    STAT_COLORS["special_attack"]),
            ("SpD", total_spd,    STAT_COLORS["special_defense"]),
            ("Spe", total_speed,  STAT_COLORS["speed"]),
        ]
        n = max(len(members), 1)
        team_totals_row.controls.append(
            ft.Text("TEAM TOTALS", weight=ft.FontWeight.BOLD, color=Colors.AMBER_400, size=11)
        )
        for label, val, color in stat_rows:
            team_totals_row.controls.append(
                ft.Row(spacing=6, controls=[
                    ft.Container(content=ft.Text(label, size=10, weight=ft.FontWeight.BOLD, color=color), width=28),
                    ft.ProgressBar(value=min(val / MAX_STAT, 1.0), color=color, bgcolor=Colors.GREY_800,
                                   expand=True, height=6, border_radius=3),
                    ft.Text(str(val), size=10, width=36, text_align=ft.TextAlign.RIGHT),
                ])
            )
        page.update()

    def update_team_banner(members):
        """Render 6 sprite circles as a compact overview banner."""
        team_banner_row.controls.clear()
        if state["active_team_id"] is None:
            return
        box_repo, _, _, session = get_repositories()
        try:
            member_map = {m.slot_position: m for m in members}
            for slot in range(1, 7):
                m = member_map.get(slot)
                if m and m.box_entry_id:
                    b_entry = box_repo.load_entry(str(m.box_entry_id))
                    sprite = b_entry.pokemon.sprite_url if b_entry else None
                    ptype = (b_entry.pokemon.types[0].lower() if b_entry and b_entry.pokemon.types else "normal")
                    is_planned = getattr(b_entry, "is_planned", False)
                    ring_col = Colors.AMBER_500 if is_planned else TYPE_COLORS.get(ptype, "#A8A878")
                    team_banner_row.controls.append(
                        ft.Container(
                            content=ft.Stack(controls=[
                                ft.Image(src=sprite, width=44, height=44, fit=ft.BoxFit.CONTAIN)
                                if sprite else ft.Icon(ft.Icons.CATCHING_POKEMON, size=28, color=Colors.GREY_500),
                                ft.Container(
                                    content=ft.Text(f"{slot}📋" if is_planned else str(slot), size=8, color=Colors.WHITE),
                                    bgcolor="#3b2d00" if is_planned else ring_col + "cc", border_radius=6,
                                    padding=ft.Padding.symmetric(horizontal=3, vertical=1),
                                    bottom=0, right=0,
                                )
                            ]),
                            width=52, height=52,
                            border_radius=26,
                            border=ft.Border.all(2, ring_col),
                            bgcolor="#1e293b",
                            alignment=ft.Alignment.CENTER,
                            tooltip=f"Slot {slot}: {b_entry.pokemon.display_name} {'(Planned Template)' if is_planned else ''}",
                        )
                    )
                else:
                    team_banner_row.controls.append(
                        ft.Container(
                            content=ft.Text(str(slot), size=10, color=Colors.GREY_500),
                            width=52, height=52, border_radius=26,
                            border=ft.Border.all(1, "#334155"),
                            bgcolor="#111827",
                            alignment=ft.Alignment.CENTER,
                        )
                    )
        finally:
            session.close()

    def update_team_validation(members):
        """Show simple team health checks below the grid."""
        team_validation_col.controls.clear()
        if state["active_team_id"] is None:
            return

        checks = []
        # Duplicate items check
        item_ids = [m.item for m in members if m.item]
        if len(item_ids) != len(set(item_ids)):
            checks.append((False, "Duplicate held items on team"))
        else:
            checks.append((True, "No duplicate held items"))

        # Mega Stone count
        mega_items = [m.item for m in members if m.item and m.item in state["items_by_id"]
                      and state["items_by_id"][m.item].target_species]
        n_megas = len(mega_items)
        if n_megas > 1:
            checks.append((False, f"Too many Mega Stones ({n_megas}/1 allowed)"))
        elif n_megas == 1:
            checks.append((True, "Mega Stone count: 1/1 ✓"))
        else:
            checks.append((True, "No Mega Stones equipped"))

        # Full team & planned count check
        filled = len([m for m in members])
        box_repo, _, _, session = get_repositories()
        try:
            planned_count = sum(
                1 for m in members
                if m.box_entry_id and getattr(box_repo.load_entry(str(m.box_entry_id)), "is_planned", False)
            )
        finally:
            session.close()

        if filled < 6:
            checks.append((None, f"Team incomplete: {filled}/6 slots filled"))
        else:
            checks.append((True, "Full team of 6"))

        if planned_count > 0:
            checks.append((None, f"Roster: {filled - planned_count} owned in Box, {planned_count} planned templates 📋"))
        else:
            checks.append((True, "All Pokémon owned in Box roster ✓"))


        team_validation_col.controls.append(
            ft.Text("TEAM HEALTH", size=10, weight=ft.FontWeight.BOLD, color=Colors.AMBER_400)
        )
        for ok, msg in checks:
            icon = ft.Icons.CHECK_CIRCLE if ok else (ft.Icons.WARNING_ROUNDED if ok is None else ft.Icons.ERROR)
            col = Colors.GREEN_400 if ok else (Colors.AMBER_400 if ok is None else Colors.RED_400)
            team_validation_col.controls.append(
                ft.Row(spacing=6, controls=[
                    ft.Icon(icon, size=12, color=col),
                    ft.Text(msg, size=11, color=col),
                ])
            )

    # --- UI Layout Assembly ---


    # Main Tabs Selection Controls — pill style


    # VIEW 1: Box Roster Layout
    box_tab_layout = ft.Row(
        expand=True,
        spacing=14,
        controls=[
            # Left panel - search, filters, list grid
            ft.Column(
                expand=2,
                spacing=10,
                controls=[
                    # Add Pokemon bar
                    ft.Container(
                        content=ft.Column(
                            spacing=8,
                            controls=[
                                ft.Row(
                                    controls=[
                                        search_input,
                                        ft.Container(
                                            content=ft.ElevatedButton(
                                                "Add to Box",
                                                icon=ft.Icons.ADD,
                                                on_click=lambda e: handle_add_pokemon(),
                                                bgcolor=Colors.AMBER_700,
                                                color=Colors.WHITE,
                                                style=ft.ButtonStyle(shape=ft.RoundedRectangleBorder(radius=8))
                                            ),
                                        ),
                                        add_spinner
                                    ]
                                ),
                                suggestion_row
                            ]
                        ),
                        bgcolor=Colors.CARD_BG,
                        border_radius=10,
                        padding=ft.Padding.symmetric(horizontal=12, vertical=10),
                        border=ft.Border.all(1, Colors.DIVIDER)
                    ),
                    # Filters toolbar
                    ft.Container(
                        content=ft.Row(
                            spacing=10,
                            controls=[
                                filter_search,
                                sort_dropdown,
                                all_stats_switch,
                                ft.IconButton(
                                    icon=ft.Icons.DOWNLOAD,
                                    icon_color=Colors.BLUE_300,
                                    on_click=lambda e: handle_export_csv(),
                                    tooltip="Export Box to CSV"
                                )
                            ]
                        ),
                        bgcolor=Colors.CARD_BG,
                        border_radius=10,
                        padding=ft.Padding.symmetric(horizontal=12, vertical=6),
                        border=ft.Border.all(1, Colors.DIVIDER)
                    ),
                    # Type filter pills
                    ft.Container(
                        content=ft.Column(spacing=6, controls=[
                            quick_toggles_row,
                            type_filter_row,
                        ]),
                        bgcolor=Colors.CARD_BG,
                        border_radius=10,
                        padding=ft.Padding.symmetric(horizontal=12, vertical=8),
                        border=ft.Border.all(1, Colors.DIVIDER),
                    ),
                    box_grid
                ]
            ),
            # Right panel - Detail Drawer
            detail_panel
        ]
    )

    # -----------------------------------------------------------------------
    # COMPETITIVE SPREAD / EV / IV / NATURE EDITOR MODAL
    # -----------------------------------------------------------------------
    _spread_slot_pos = [1]
    _spread_nature_drop = ft.Dropdown(
        label="Nature",
        options=[
            ft.dropdown.Option(n) for n in [
                "Adamant", "Bashful", "Bold", "Brave", "Calm", "Careful", "Docile",
                "Gentle", "Hardy", "Hasty", "Impish", "Jolly", "Lax", "Lonely",
                "Mild", "Modest", "Naive", "Naughty", "Quiet", "Quirky", "Rash",
                "Relaxed", "Sassy", "Serious", "Timid"
            ]
        ],
        text_size=12, width=180,
    )
    _spread_level_tf = ft.TextField(label="Level", value="50", width=80, text_size=12)

    _ev_inputs = {
        stat: ft.TextField(value="0", label=label, width=72, text_size=11, text_align=ft.TextAlign.RIGHT)
        for stat, label in [
            ("hp", "HP"), ("attack", "Atk"), ("defense", "Def"),
            ("special_attack", "SpA"), ("special_defense", "SpD"), ("speed", "Spe")
        ]
    }
    _iv_inputs = {
        stat: ft.TextField(value="31", label=label, width=72, text_size=11, text_align=ft.TextAlign.RIGHT)
        for stat, label in [
            ("hp", "HP"), ("attack", "Atk"), ("defense", "Def"),
            ("special_attack", "SpA"), ("special_defense", "SpD"), ("speed", "Spe")
        ]
    }
    _ev_total_text = ft.Text("Total EVs: 0 / 510", size=11, weight=ft.FontWeight.BOLD, color=Colors.AMBER_400)

    def _update_ev_total(e=None):
        tot = 0
        for tf in _ev_inputs.values():
            try:
                tot += int(tf.value or "0")
            except ValueError:
                pass
        _ev_total_text.value = f"Total EVs: {tot} / 510"
        _ev_total_text.color = Colors.RED_400 if tot > 510 else Colors.AMBER_400
        page.update()

    for tf in _ev_inputs.values():
        tf.on_change = _update_ev_total

    def _apply_preset_evs(preset_type: str):
        for tf in _ev_inputs.values():
            tf.value = "0"
        if preset_type == "physical_sweeper":
            _ev_inputs["attack"].value = "252"
            _ev_inputs["speed"].value = "252"
            _ev_inputs["hp"].value = "4"
        elif preset_type == "special_sweeper":
            _ev_inputs["special_attack"].value = "252"
            _ev_inputs["speed"].value = "252"
            _ev_inputs["hp"].value = "4"
        elif preset_type == "bulky_support":
            _ev_inputs["hp"].value = "252"
            _ev_inputs["defense"].value = "128"
            _ev_inputs["special_defense"].value = "128"
        _update_ev_total()

    def _apply_preset_ivs(preset_type: str):
        for tf in _iv_inputs.values():
            tf.value = "31"
        if preset_type == "no_good_atk":
            _iv_inputs["attack"].value = "0"
        elif preset_type == "trick_room":
            _iv_inputs["speed"].value = "0"
        page.update()

    def _save_spread_modal(e=None):
        slot_pos = _spread_slot_pos[0]
        nature = _spread_nature_drop.value or "Hardy"
        try:
            level = max(1, min(100, int(_spread_level_tf.value or "50")))
        except ValueError:
            level = 50

        evs = {}
        for stat, tf in _ev_inputs.items():
            try:
                val = max(0, min(252, int(tf.value or "0")))
                if val > 0:
                    evs[stat] = val
            except ValueError:
                pass

        if sum(evs.values()) > 510:
            show_toast(f"Total EVs cannot exceed 510 (currently {sum(evs.values())})", is_error=True)
            return

        ivs = {}
        for stat, tf in _iv_inputs.items():
            try:
                val = max(0, min(31, int(tf.value or "31")))
                if val != 31:
                    ivs[stat] = val
            except ValueError:
                pass


        _, team_repo, _, session = get_repositories()
        try:
            member_recs = team_repo.list_members(state["active_team_id"])
            matching_rec = next((m for m in member_recs if m.slot_position == slot_pos), None)
            if matching_rec:
                dom = matching_rec.to_domain()
                updated = TeamMember(
                    team_member_id=dom.team_member_id,
                    box_entry_id=dom.box_entry_id,
                    slot_position=dom.slot_position,
                    selected_form=dom.selected_form,
                    item=dom.item,
                    moveset=dom.moveset,
                    ability=dom.ability,
                    notes=dom.notes,
                    nature=nature,
                    level=level,
                    evs=evs,
                    ivs=ivs,
                )
                team_repo.upsert_member(state["active_team_id"], updated)
                show_toast("Competitive spread saved!")
                _spread_modal.open = False
                render_team_builder()
        finally:
            session.close()

    _spread_modal = ft.AlertDialog(
        title=ft.Text("Edit Competitive Spread & EVs/IVs", weight=ft.FontWeight.BOLD),
        content=ft.Column(
            spacing=10, width=540, scroll=ft.ScrollMode.AUTO,
            controls=[
                ft.Row(spacing=10, controls=[_spread_nature_drop, _spread_level_tf]),
                ft.Divider(),
                ft.Row(alignment=ft.MainAxisAlignment.SPACE_BETWEEN, controls=[
                    ft.Text("Effort Values (EVs)", weight=ft.FontWeight.BOLD, size=12),
                    _ev_total_text,
                ]),
                ft.Row(spacing=4, controls=[
                    ft.Text("Presets:", size=10, color=Colors.GREY_400),
                    ft.OutlinedButton("Phys Sweeper", on_click=lambda e: _apply_preset_evs("physical_sweeper")),
                    ft.OutlinedButton("Spec Sweeper", on_click=lambda e: _apply_preset_evs("special_sweeper")),
                    ft.OutlinedButton("Bulky Support", on_click=lambda e: _apply_preset_evs("bulky_support")),
                ]),
                ft.Row(spacing=4, controls=[_ev_inputs["hp"], _ev_inputs["attack"], _ev_inputs["defense"],
                                           _ev_inputs["special_attack"], _ev_inputs["special_defense"], _ev_inputs["speed"]]),
                ft.Divider(),
                ft.Row(alignment=ft.MainAxisAlignment.SPACE_BETWEEN, controls=[
                    ft.Text("Individual Values (IVs)", weight=ft.FontWeight.BOLD, size=12),
                    ft.Row(spacing=4, controls=[
                        ft.OutlinedButton("0 Atk", on_click=lambda e: _apply_preset_ivs("no_good_atk")),
                        ft.OutlinedButton("0 Spe", on_click=lambda e: _apply_preset_ivs("trick_room")),
                        ft.OutlinedButton("31 All", on_click=lambda e: _apply_preset_ivs("all_31")),
                    ]),
                ]),
                ft.Row(spacing=4, controls=[_iv_inputs["hp"], _iv_inputs["attack"], _iv_inputs["defense"],
                                           _iv_inputs["special_attack"], _iv_inputs["special_defense"], _iv_inputs["speed"]]),
            ]
        ),
        actions=[
            ft.ElevatedButton("Save Spread", icon=ft.Icons.CHECK, on_click=_save_spread_modal,
                              style=ft.ButtonStyle(bgcolor=Colors.AMBER_700, color=Colors.WHITE)),
            ft.TextButton("Cancel", on_click=lambda e: setattr(_spread_modal, "open", False) or page.update()),
        ],
        actions_alignment=ft.MainAxisAlignment.END,
    )
    page.overlay.append(_spread_modal)

    def _open_spread_modal(slot_pos: int, member_rec_or_dom):
        _spread_slot_pos[0] = slot_pos
        m_dom = member_rec_or_dom if isinstance(member_rec_or_dom, TeamMember) else member_rec_or_dom.to_domain()
        _spread_nature_drop.value = m_dom.nature or "Hardy"
        _spread_level_tf.value = str(m_dom.level or 50)
        for stat, tf in _ev_inputs.items():
            tf.value = str(m_dom.evs.get(stat, 0))
        for stat, tf in _iv_inputs.items():
            tf.value = str(m_dom.ivs.get(stat, 31))
        _update_ev_total()
        _spread_modal.open = True
        page.update()

    # -----------------------------------------------------------------------
    # SHOWDOWN EXPORT MODAL
    # -----------------------------------------------------------------------

    _export_text_field = ft.TextField(
        multiline=True, read_only=True, min_lines=12, max_lines=20,
        text_style=ft.TextStyle(font_family="monospace", size=11),
        bgcolor="#0f172a", border_color=Colors.DIVIDER,
        expand=True,
    )
    _export_pokepast_btn = ft.ElevatedButton(
        "🌐 Publish to Poképast.es",
        icon=ft.Icons.UPLOAD,
        style=ft.ButtonStyle(bgcolor=Colors.AMBER_700, color=Colors.WHITE),
    )
    _export_pokepast_link = ft.TextButton(
        "🔗 Open Paste", visible=False,
        style=ft.ButtonStyle(color=Colors.BLUE_400),
    )
    _export_spinner = ft.ProgressRing(visible=False, width=16, height=16, stroke_width=2)

    _export_modal = ft.AlertDialog(
        title=ft.Text("Export Team — Showdown Format", weight=ft.FontWeight.BOLD),
        content=ft.Column(
            spacing=10, width=620,
            controls=[
                _export_text_field,
                ft.Row(spacing=8, controls=[
                    ft.ElevatedButton(
                        "📋 Copy to Clipboard",
                        icon=ft.Icons.CONTENT_COPY,
                        on_click=lambda e: (
                            page.set_clipboard(_export_text_field.value or ""),
                            show_toast("Copied to clipboard!"),
                        ),
                    ),
                    _export_pokepast_btn,
                    _export_spinner,
                    _export_pokepast_link,
                ]),
            ],
        ),
        actions=[ft.TextButton("Close", on_click=lambda e: setattr(_export_modal, "open", False) or page.update())],
        actions_alignment=ft.MainAxisAlignment.END,
    )
    page.overlay.append(_export_modal)

    def _open_export_modal(e=None):
        """Build Showdown text from the active team and open the export modal."""
        if state["active_team_id"] is None:
            show_toast("No active team to export", is_error=True)
            return
        box_repo2, team_repo2, _, session2 = get_repositories()
        try:
            members = team_repo2.get_members(state["active_team_id"]) or []
            team_rec = team_repo2.resolve(str(state["active_team_id"]))
            team_name = team_rec.name if team_rec else "My Team"
            all_entries = box_repo2.list_entries(include_planned=True)
            entries_by_id = {e.box_entry_id: e for e in all_entries}
            text = export_team_to_showdown_text(members, entries_by_id)
            _export_text_field.value = text if text.strip() else "(No team members to export)"
            _export_pokepast_btn.text = "🌐 Publish to Poképast.es"
            _export_pokepast_btn.disabled = False
            _export_pokepast_link.visible = False
            _export_pokepast_link.url = None
            _export_spinner.visible = False

            # Capture for closure
            _members_snapshot = list(members)
            _entries_snapshot = dict(entries_by_id)
            _team_name_snapshot = team_name

            def _do_publish(e=None):
                _export_spinner.visible = True
                _export_pokepast_btn.disabled = True
                page.update()
                try:
                    provider = PokepastProvider()
                    result = publish_to_pokepast(
                        _members_snapshot, _entries_snapshot,
                        team_name=_team_name_snapshot,
                        team_id=str(state["active_team_id"]),
                        pokepast_provider=provider,
                    )
                    _export_pokepast_link.text = f"🔗 Open Paste: {result.pokepast_url}"
                    _export_pokepast_link.url = result.pokepast_url
                    _export_pokepast_link.visible = True
                    _export_pokepast_btn.text = "✅ Published!"
                    page.launch_url(result.pokepast_url)
                except PokepastNetworkError as err:
                    show_toast(f"Publish failed: {err}", is_error=True)
                    _export_pokepast_btn.disabled = False
                finally:
                    _export_spinner.visible = False
                    page.update()

            _export_pokepast_btn.on_click = lambda e: threading.Thread(target=_do_publish, daemon=True).start()
        finally:
            session2.close()

        _export_modal.open = True
        page.update()

    # -----------------------------------------------------------------------
    # SHOWDOWN IMPORT MODAL
    # -----------------------------------------------------------------------
    _import_input = ft.TextField(
        label="Paste Showdown text or Poképast URL",
        multiline=True, min_lines=8, max_lines=14,
        hint_text="https://pokepast.es/abc123  —  or paste raw Showdown text here",
        text_style=ft.TextStyle(font_family="monospace", size=11),
        bgcolor="#0f172a", border_color=Colors.DIVIDER,
        expand=True, on_change=lambda e: _on_import_input_change(),
    )
    _import_preview_row = ft.Row(wrap=True, spacing=8, run_spacing=8)
    _import_warning_col = ft.Column(spacing=4, visible=False)
    _import_spinner = ft.ProgressRing(visible=False, width=16, height=16, stroke_width=2)
    _import_status = ft.Text("", size=11, color=Colors.GREY_400)
    # Holds the last successfully parsed result for use by confirm buttons
    _last_parsed: list[ParsedTeamResult] = [None]
    _last_readiness: list[ImportReadinessReport] = [None]

    def _build_import_preview(parsed: ParsedTeamResult):
        """Populate the 6-slot preview cards from a ParsedTeamResult."""
        _import_preview_row.controls.clear()
        _import_warning_col.controls.clear()
        _import_warning_col.visible = False

        for slot in parsed.slots:
            has_warn = slot.resolved_canonical_id is None
            _import_preview_row.controls.append(
                ft.Container(
                    content=ft.Column(spacing=4, horizontal_alignment=ft.CrossAxisAlignment.CENTER, controls=[
                        ft.Text(slot.species_name, size=11, weight=ft.FontWeight.BOLD,
                                color=Colors.RED_400 if has_warn else Colors.WHITE,
                                text_align=ft.TextAlign.CENTER),
                        ft.Text(slot.item_name or "—", size=9, color=Colors.GREY_400, text_align=ft.TextAlign.CENTER),
                        ft.Text(slot.ability_name or "", size=9, color=Colors.GREY_400, text_align=ft.TextAlign.CENTER),
                        *[ft.Text(f"• {m}", size=9, color=Colors.BLUE_300) for m in slot.moves],
                    ]),
                    bgcolor="#1e293b" if not has_warn else "#3b0000",
                    border_radius=8,
                    border=ft.Border.all(1, Colors.RED_400 if has_warn else Colors.DIVIDER),
                    padding=ft.Padding.all(8),
                    width=120,
                )
            )

        if parsed.warnings:
            _import_warning_col.visible = True
            for w in parsed.warnings:
                _import_warning_col.controls.append(
                    ft.Row(spacing=4, controls=[
                        ft.Icon(ft.Icons.WARNING_ROUNDED, size=12, color=Colors.AMBER_400),
                        ft.Text(w, size=10, color=Colors.AMBER_400),
                    ])
                )

    def _on_import_input_change():
        text = _import_input.value or ""
        if not text.strip():
            _import_preview_row.controls.clear()
            _import_status.value = ""
            _last_parsed[0] = None
            _last_readiness[0] = None
            page.update()
            return

        if PokepastProvider.is_pokepast_url(text.strip()):
            # Async fetch from Pokepast
            def _fetch():
                _import_spinner.visible = True
                _import_status.value = "Fetching from Poképast.es…"
                page.update()
                try:
                    provider = PokepastProvider()
                    parsed = import_from_pokepast_url(text.strip(), provider)
                    _last_parsed[0] = parsed
                    _build_import_preview(parsed)
                    _import_status.value = f"✅ Found {len(parsed.slots)} Pokémon"
                    box_repo3, _, _, session3 = get_repositories()
                    try:
                        champions_repo = ChampionsCatalogRepository(session3)
                        legal_names = set(champions_repo.list_species_names())
                        if not legal_names:
                            pok_repo = PokemonRepository(session3)
                            legal_names = {p.species_name for p in pok_repo.list_all()}
                        _last_readiness[0] = resolve_import_readiness(parsed, box_repo3, legal_species_catalog=legal_names)
                    finally:
                        session3.close()
                except PokepastNetworkError as err:
                    _import_status.value = f"❌ Fetch failed: {err}"
                finally:
                    _import_spinner.visible = False
                    page.update()
            threading.Thread(target=_fetch, daemon=True).start()
        else:
            # Parse raw text immediately (synchronous — fast)
            parsed = parse_showdown_text(text)
            _last_parsed[0] = parsed
            _build_import_preview(parsed)
            _import_status.value = f"{'✅' if parsed.is_valid else '❌'} {len(parsed.slots)} Pokémon parsed"
            box_repo4, _, _, session4 = get_repositories()
            try:
                champions_repo4 = ChampionsCatalogRepository(session4)
                legal_names4 = set(champions_repo4.list_species_names())
                if not legal_names4:
                    pok_repo4 = PokemonRepository(session4)
                    legal_names4 = {p.species_name for p in pok_repo4.list_all()}
                _last_readiness[0] = resolve_import_readiness(parsed, box_repo4, legal_species_catalog=legal_names4)
            finally:
                session4.close()
            page.update()

    def _commit_team_import(use_planned: bool):
        """Write parsed team to DB. use_planned=True → missing entries become ghosts."""
        parsed = _last_parsed[0]
        readiness = _last_readiness[0]
        if parsed is None or not parsed.is_valid:
            return
        box_repo5, team_repo5, _, session5 = get_repositories()
        try:
            from ..domain.entities.team import Team as _Team
            from ..domain.entities.box_entry import BoxEntry as _BoxEntry
            from ..domain.entities.team_member import TeamMember as _TM

            # Create the new team
            team_name = parsed.title or "Imported Team"
            new_team = team_repo5.create(_Team(name=team_name))

            all_entries = box_repo5.list_entries(include_planned=True)
            entries_by_name = {e.pokemon.display_name.lower(): e for e in all_entries}
            entries_by_cid  = {e.pokemon.canonical_id: e for e in all_entries}

            pok_repo5 = PokemonRepository(session5)

            for i, slot in enumerate(parsed.slots[:6]):
                # Resolve existing box entry
                existing = (
                    entries_by_name.get(slot.species_name.lower()) or
                    entries_by_cid.get(slot.showdown_form_key)
                )
                if existing is None:
                    # Look up species in catalog first
                    cat_pok_rec = pok_repo5.get(slot.showdown_form_key) or pok_repo5.get(slot.species_name.lower())
                    if cat_pok_rec:
                        stub = cat_pok_rec.to_domain()
                    else:
                        from ..domain.entities.pokemon import Pokemon as _Pkmn
                        from ..domain.entities.pokemon_stats import PokemonStats as _Stats
                        stub = _Pkmn(
                            canonical_id=slot.showdown_form_key,
                            display_name=slot.species_name,
                            species_name=slot.showdown_form_key.split("-")[0],
                            form_name="base",
                            types=[],
                            stats=_Stats(hp=0, attack=0, defense=0, sp_atk=0, sp_def=0, speed=0),
                        )
                    stub_entry = _BoxEntry(
                        pokemon=stub,
                        tags=["imported", team_name],
                        is_planned=use_planned,
                    )
                    if use_planned:
                        record = box_repo5.create_planned_entry(stub_entry)
                    else:
                        record = box_repo5.upsert_box_entry(stub_entry)
                    box_entry_id = record.box_entry_id
                else:
                    box_entry_id = existing.box_entry_id

                moves = [PokemonMove(name=m, power=0, accuracy=0, type="") for m in slot.moves]
                member = _TM(
                    box_entry_id=box_entry_id,
                    slot_position=i + 1,
                    selected_form=slot.showdown_form_key or "base",
                    item=slot.item_name,
                    ability=slot.ability_name,
                    moveset=moves,
                    nature=slot.nature,
                    evs=dict(slot.evs),
                    ivs=dict(slot.ivs),
                    level=slot.level,
                )
                team_repo5.upsert_member(new_team.team_id, member)



            state["active_team_id"] = new_team.team_id
            show_toast(f"Team '{team_name}' imported successfully!")
            _import_modal.open = False
            refresh_teams()
        except Exception as err:
            show_toast(f"Import failed: {err}", is_error=True)
        finally:
            session5.close()

    def _show_readiness_dialog():
        """Show the 3-option dialog when missing Pokémon are detected."""
        readiness = _last_readiness[0]
        if readiness is None:
            return

        # Safeguard: Check if team contains non-Champions species
        if getattr(readiness, "illegal_species", None):
            illegal_names = [s.species_name for s in readiness.illegal_species]
            illegal_list = ft.Column(spacing=3, controls=[
                ft.Row(spacing=6, controls=[
                    ft.Icon(ft.Icons.CANCEL, size=14, color=Colors.RED_400),
                    ft.Text(n, size=12, weight=ft.FontWeight.BOLD, color=Colors.RED_300),
                ]) for n in illegal_names
            ])

            def _close_illegal_dialog(e=None):
                readiness_dialog.open = False
                page.update()

            readiness_dialog = ft.AlertDialog(
                title=ft.Row(spacing=8, controls=[
                    ft.Icon(ft.Icons.BLOCK, color=Colors.RED_400, size=22),
                    ft.Text("Cannot Import — Non-Champions Team", weight=ft.FontWeight.BOLD, color=Colors.RED_400),
                ]),
                content=ft.Column(spacing=10, width=460, controls=[
                    ft.Text(f"This team contains {len(illegal_names)} Pokémon that are NOT legal in Pokémon Champions:", size=12),
                    illegal_list,
                    ft.Container(
                        content=ft.Text(
                            "Pokémon Champions only supports species in the official Champions Pokédex catalog. "
                            "Rosters containing unreleased or illegal species cannot be imported into your Box or Team Builder.",
                            size=11, color=Colors.GREY_300
                        ),
                        bgcolor="#2a1215",
                        border_radius=6,
                        padding=ft.Padding.all(8),
                        border=ft.Border.all(1, Colors.RED_700),
                    )
                ]),
                actions=[
                    ft.TextButton("✖ Close / Cancel", on_click=_close_illegal_dialog),
                ],
                actions_alignment=ft.MainAxisAlignment.CENTER,
            )
            page.overlay.append(readiness_dialog)
            readiness_dialog.open = True
            page.update()
            return

        missing_names = [s.species_name for s in readiness.missing]
        unresolvable_names = [s.species_name for s in readiness.unresolvable]
        problem_names = missing_names + unresolvable_names


        if not problem_names:
            # All Pokémon in box — import directly
            _import_modal.open = False
            _commit_team_import(use_planned=False)
            return

        # Close import modal so only readiness_dialog is active
        _import_modal.open = False

        # Build the readiness decision dialog
        missing_list = ft.Column(spacing=2, controls=[
            ft.Text(f"• {n}", size=11, color=Colors.AMBER_400)
            for n in problem_names
        ])

        def _close_readiness(e=None):
            readiness_dialog.open = False
            page.update()

        def _handle_choice(use_planned: bool):
            readiness_dialog.open = False
            _import_modal.open = False
            _commit_team_import(use_planned=use_planned)

        readiness_dialog = ft.AlertDialog(
            title=ft.Text("⚠️ Import Notice", weight=ft.FontWeight.BOLD),
            content=ft.Column(spacing=10, width=420, controls=[
                ft.Text(f"{len(problem_names)} Pokémon in this team are not in your box:", size=12),
                missing_list,
                ft.Text("How would you like to proceed?", size=12, weight=ft.FontWeight.W_600),
            ]),
            actions=[
                ft.ElevatedButton(
                    "📥 Add to Box & Import",
                    style=ft.ButtonStyle(bgcolor=Colors.GREEN_ACCENT_700, color=Colors.WHITE),
                    on_click=lambda e: _handle_choice(use_planned=False),
                ),
                ft.ElevatedButton(
                    "📋 Import as Template",
                    style=ft.ButtonStyle(bgcolor=Colors.AMBER_700, color=Colors.WHITE),
                    on_click=lambda e: _handle_choice(use_planned=True),
                ),
                ft.TextButton("✖ Cancel", on_click=_close_readiness),
            ],
            actions_alignment=ft.MainAxisAlignment.CENTER,
        )
        page.overlay.append(readiness_dialog)
        readiness_dialog.open = True
        page.update()

    _import_modal = ft.AlertDialog(
        title=ft.Text("Import Team — Showdown / Poképast", weight=ft.FontWeight.BOLD),
        content=ft.Column(
            spacing=10, width=680, scroll=ft.ScrollMode.AUTO,
            controls=[
                _import_input,
                ft.Row(spacing=6, controls=[_import_spinner, _import_status]),
                _import_warning_col,
                _import_preview_row,
            ],
        ),
        actions=[
            ft.ElevatedButton(
                "✅ Import Team",
                icon=ft.Icons.DOWNLOAD,
                style=ft.ButtonStyle(bgcolor=Colors.AMBER_700, color=Colors.WHITE),
                on_click=lambda e: _show_readiness_dialog(),
            ),
            ft.TextButton("Cancel", on_click=lambda e: setattr(_import_modal, "open", False) or page.update()),
        ],
        actions_alignment=ft.MainAxisAlignment.END,
    )
    page.overlay.append(_import_modal)

    def _open_import_modal(e=None):
        _import_input.value = ""
        _import_preview_row.controls.clear()
        _import_warning_col.controls.clear()
        _import_warning_col.visible = False
        _import_status.value = ""
        _last_parsed[0] = None
        _last_readiness[0] = None
        _import_modal.open = True
        page.update()

    # VIEW 2: Team Builder Layout
    team_tab_layout = ft.Column(
        expand=True,
        spacing=12,
        controls=[
            ft.Row(
                spacing=10,
                controls=[
                    team_dropdown,
                    ft.ElevatedButton(
                        "New Team",
                        icon=ft.Icons.CREATE_NEW_FOLDER,
                        on_click=handle_open_new_team_modal
                    ),
                    ft.IconButton(
                        icon=ft.Icons.DELETE_FOREVER,
                        icon_color=Colors.RED_400,
                        on_click=lambda e: handle_delete_team(),
                        tooltip="Delete Active Team"
                    ),
                    ft.IconButton(
                        icon=ft.Icons.UPLOAD_FILE,
                        icon_color=Colors.BLUE_300,
                        on_click=_open_export_modal,
                        tooltip="Export team to Showdown / Poképast.es",
                    ),
                    ft.IconButton(
                        icon=ft.Icons.DOWNLOAD_FOR_OFFLINE,
                        icon_color=Colors.GREEN_400,
                        on_click=_open_import_modal,
                        tooltip="Import team from Showdown paste or Poképast URL",
                    ),
                ]
            ),

            # Team overview banner — 6 sprite circles
            ft.Container(
                content=team_banner_row,
                bgcolor=Colors.CARD_BG,
                border_radius=10,
                padding=ft.Padding.symmetric(horizontal=14, vertical=10),
                border=ft.Border.all(1, Colors.DIVIDER),
            ),
            # Stat distribution totals
            ft.Container(
                content=team_totals_row,
                bgcolor=Colors.CARD_BG,
                border_radius=10,
                padding=ft.Padding.symmetric(horizontal=14, vertical=10),
                border=ft.Border.all(1, Colors.DIVIDER),
            ),
            team_grid,
            # Team health validation summary
            ft.Container(
                content=team_validation_col,
                bgcolor=Colors.CARD_BG,
                border_radius=10,
                padding=ft.Padding.symmetric(horizontal=14, vertical=10),
                border=ft.Border.all(1, Colors.DIVIDER),
            ),
        ]
    )

    # -----------------------------------------------------------------------
    # VIEW 3: Meta & Tournament Explorer Layout
    # -----------------------------------------------------------------------
    _tourney_search_tf = ft.TextField(
        hint_text="Search species, player, or event...",
        width=220,
        text_size=12,
        height=40,
        on_submit=lambda e: _render_tourney_explorer(),
    )
    _tourney_game_drop = ft.Dropdown(
        value="All",
        options=[
            ft.dropdown.Option("All", text="All Games"),
            ft.dropdown.Option("Pokémon Champions", text="Pokémon Champions"),
            ft.dropdown.Option("Scarlet & Violet", text="Scarlet & Violet"),
        ],
        width=170,
        text_size=12,
        height=40,
        on_select=lambda e: _render_tourney_explorer(),
    )
    _tourney_recency_drop = ft.Dropdown(
        value="365",
        options=[
            ft.dropdown.Option("365", text="📅 Last 12 Months"),
            ft.dropdown.Option("180", text="📅 Last 6 Months"),
            ft.dropdown.Option("all", text="📅 All Time"),
        ],
        width=160,
        text_size=12,
        height=40,
        on_select=lambda e: _render_tourney_explorer(),
    )
    _tourney_format_drop = ft.Dropdown(
        value="All",
        options=[
            ft.dropdown.Option("All", text="All Formats"),
            ft.dropdown.Option("Regulation M-A", text="Regulation M-A"),
            ft.dropdown.Option("Regulation M-B", text="Regulation M-B"),
            ft.dropdown.Option("Regulation H", text="Regulation H"),
            ft.dropdown.Option("Regulation F", text="Regulation F"),
            ft.dropdown.Option("Regulation G", text="Regulation G"),
            ft.dropdown.Option("Champions Season 1", text="Champions Season 1"),
        ],
        width=160,
        text_size=12,
        height=40,
        on_select=lambda e: _render_tourney_explorer(),
    )
    _tourney_placement_drop = ft.Dropdown(
        # Default to Top 8: results are ordered newest-event-first, so "All Placements"
        # would fill the whole grid with the single most recent event's standings.
        value="8",
        options=[
            ft.dropdown.Option("all", text="All Placements"),
            ft.dropdown.Option("1", text="🥇 1st Place"),
            ft.dropdown.Option("2", text="🥈 Top 2"),
            ft.dropdown.Option("4", text="🏆 Top 4"),
            ft.dropdown.Option("8", text="🏅 Top 8"),
        ],
        width=140,
        text_size=12,
        height=40,
        on_select=lambda e: _render_tourney_explorer(),
    )


    _tourney_grid = ft.GridView(
        expand=True,
        max_extent=520,
        child_aspect_ratio=1.22,
        spacing=14,
        run_spacing=14,
    )

    _tourney_more_btn = ft.ElevatedButton(
        "Load more",
        icon=ft.Icons.EXPAND_MORE,
        visible=False,
    )

    def _import_tournament_team(showdown_text: str, team_title: str):
        _open_import_modal()
        _import_input.value = showdown_text
        _on_import_input_change()
        show_toast(f"Loaded '{team_title}' roster for import preview!")


    # Rendering the explorer builds roughly 38 Flet controls per card, so a full grid
    # is a few thousand. Re-entering the tab with unchanged filters used to rebuild all
    # of them for an identical result; these hold enough state to skip that and to load
    # further pages instead of fetching everything up front.
    _TOURNEY_PAGE_SIZE = 20
    _tourney_state = {"filter_key": None, "loaded": 0, "exhausted": False}

    def _tourney_filter_key() -> tuple:
        """Identity of the currently displayed result set."""
        return (
            (_tourney_search_tf.value or "").strip(),
            _tourney_format_drop.value,
            _tourney_game_drop.value,
            _tourney_recency_drop.value,
            _tourney_placement_drop.value,
        )

    def _invalidate_tourney_cache():
        """Force a rebuild on the next visit, e.g. after new data is synced."""
        _tourney_state["filter_key"] = None

    def _render_tourney_explorer(force: bool = False):
        """Show results for the current filters, reusing the grid when nothing changed."""
        key = _tourney_filter_key()
        if not force and key == _tourney_state["filter_key"] and _tourney_grid.controls:
            page.update()
            return

        _tourney_state.update({"filter_key": key, "loaded": 0, "exhausted": False})
        _tourney_grid.controls.clear()
        _load_tourney_page()

    def _load_tourney_page():
        with get_session() as session:
            # Seeding is a startup concern; doing it here re-read and re-parsed the
            # seed file on every single render.
            tourney_svc = TournamentService(session)
            champions_repo = ChampionsCatalogRepository(session)

            # Only the Champions catalogue defines legality. Falling back to the user's
            # own box (as this once did) would compare tournament rosters against a
            # handful of owned Pokemon and flag almost every team as illegal, so an
            # empty catalogue disables the check instead of guessing.
            raw_species_names = champions_repo.list_species_names()
            legality_known = bool(raw_species_names)

            # Pre-compute legal lookup set for O(1) checking
            champions_legal_set = set()
            for name in raw_species_names:
                if not name:
                    continue
                s_low = name.lower().strip()
                champions_legal_set.add(s_low)
                champions_legal_set.add(s_low.split("-")[0])

            q = _tourney_search_tf.value
            reg = _tourney_format_drop.value
            game_plat = _tourney_game_drop.value
            rec_val = _tourney_recency_drop.value
            max_days = int(rec_val) if rec_val and rec_val.isdigit() else None

            place_val = None
            if _tourney_placement_drop.value and _tourney_placement_drop.value != "all":
                try:
                    place_val = int(_tourney_placement_drop.value)
                except ValueError:
                    pass

            # One page at a time; "Load more" appends the next.
            # `query` already matches species, player and event name; passing it as
            # species_filter too would AND the two and reduce the search to species.
            teams = tourney_svc.search_teams(
                query=q,
                regulation_filter=reg,
                placement_filter=place_val,
                game_platform_filter=game_plat,
                max_age_days=max_days,
                limit=_TOURNEY_PAGE_SIZE,
                offset=_tourney_state["loaded"],
            )

            if not teams:
                _tourney_state["exhausted"] = True
                _tourney_more_btn.visible = False
                if _tourney_state["loaded"]:
                    page.update()
                    return
                _tourney_grid.controls.append(
                    ft.Container(
                        content=ft.Column(
                            horizontal_alignment=ft.CrossAxisAlignment.CENTER,
                            spacing=10,
                            controls=[
                                ft.Icon(ft.Icons.EMOJI_EVENTS_OUTLINED, size=48, color=Colors.GREY_500),
                                ft.Text("No tournament teams matched your filters.", size=14, color=Colors.GREY_400),
                            ],
                        ),
                        alignment=ft.Alignment.CENTER,
                        padding=ft.Padding.all(40),
                    )
                )
                page.update()
                return

            # Batch pre-fetch all tournaments, members, and sprites in 3 fast SQL queries
            team_ids = [t.tournament_team_id for t in teams]
            tourney_ids = list({t.tournament_id for t in teams})

            # 1. Fetch tournaments dict
            tourneys = session.exec(
                select(TournamentRecord).where(TournamentRecord.tournament_id.in_(tourney_ids))
            ).all()
            tourney_dict = {t.tournament_id: t for t in tourneys}

            # 2. Fetch all members for these teams
            all_members = session.exec(
                select(TournamentTeamMemberRecord).where(TournamentTeamMemberRecord.tournament_team_id.in_(team_ids))
            ).all()
            members_by_team: dict[UUID, list[TournamentTeamMemberRecord]] = {}
            for m in all_members:
                members_by_team.setdefault(m.tournament_team_id, []).append(m)

            # Sort members by slot_position
            for tid in members_by_team:
                members_by_team[tid].sort(key=lambda x: x.slot_position)

            # 3. Fetch all sprites
            all_canon_ids = list({m.canonical_id for m in all_members if m.canonical_id})
            pokemons = session.exec(
                select(PokemonRecord).where(PokemonRecord.canonical_id.in_(all_canon_ids))
            ).all()
            sprite_dict = {p.canonical_id: p.sprite_url for p in pokemons if p.sprite_url}

            for team in teams:
                tourney_rec = tourney_dict.get(team.tournament_id)
                tourney_name = tourney_rec.name if tourney_rec else team.tournament_id
                tourney_reg = tourney_rec.format_regulation if tourney_rec else "VGC"

                # Placement badge color
                badge_bg = Colors.PURPLE_900
                badge_color = Colors.WHITE
                badge_icon = "🏅"
                if team.placement == 1:
                    badge_bg = Colors.AMBER_700
                    badge_color = Colors.BLACK
                    badge_icon = "🥇"
                elif team.placement == 2:
                    badge_bg = Colors.BLUE_GREY_600
                    badge_color = Colors.WHITE
                    badge_icon = "🥈"
                elif team.placement <= 4:
                    badge_bg = Colors.BLUE_700
                    badge_color = Colors.WHITE
                    badge_icon = "🏆"

                # Members sprite row & legality check
                members = members_by_team.get(team.tournament_team_id, [])
                member_controls = []
                has_illegal_species = False

                for m in members:
                    sname = (m.species_name or "").lower().strip()
                    ckey = (m.canonical_id or "").lower().strip()
                    # O(1) set lookup; unknown legality is never reported as illegal.
                    is_leg = not legality_known or (
                        sname in champions_legal_set
                        or ckey in champions_legal_set
                        or ckey.split("-")[0] in champions_legal_set
                    )
                    if not is_leg:
                        has_illegal_species = True

                    sprite_url = (
                        sprite_dict.get(m.canonical_id)
                        or get_pokemon_sprite_url(m.canonical_id or m.species_name)
                    )

                    # Champions-exclusive forms have no sprite on the Showdown CDN, so
                    # degrade to a placeholder rather than a broken image. Kept to a
                    # single control: this grid already builds ~2.3k of them per entry,
                    # and the enclosing Container carries the species tooltip.
                    img_ctrl = ft.Image(
                        src=sprite_url, width=38, height=38, fit=ft.BoxFit.CONTAIN,
                        error_content=ft.Icon(ft.Icons.CATCHING_POKEMON, size=22, color=Colors.GREY_600),
                    )

                    border_color = Colors.RED_700 if not is_leg else Colors.DIVIDER
                    member_controls.append(
                        ft.Container(
                            content=img_ctrl,
                            bgcolor="#1c1917" if not is_leg else "#0f172a",
                            border_radius=10,
                            padding=ft.Padding.all(4),
                            border=ft.Border.all(1, border_color),
                            tooltip=f"{m.species_name} {'(⚠️ Non-Champions)' if not is_leg else ''}",
                        )
                    )

                legality_badge = ft.Container(
                    content=ft.Text("⚠️ Non-Champions Roster", size=9, weight=ft.FontWeight.BOLD, color=Colors.WHITE),
                    bgcolor="#881337",
                    border_radius=6,
                    padding=ft.Padding.symmetric(horizontal=6, vertical=3),
                    border=ft.Border.all(1, Colors.RED_700),
                ) if has_illegal_species else ft.Container(
                    content=ft.Text(
                        "✅ Champions Legal" if legality_known else "• Legality unknown",
                        size=9, weight=ft.FontWeight.BOLD, color=Colors.GREEN_300,
                    ),
                    bgcolor="#064e3b",
                    border_radius=6,
                    padding=ft.Padding.symmetric(horizontal=6, vertical=3),
                    border=ft.Border.all(1, Colors.GREEN_700),
                )

                # Card assembly
                card = ft.Container(
                    content=ft.Column(
                        spacing=10,
                        alignment=ft.MainAxisAlignment.SPACE_BETWEEN,
                        controls=[
                            # Header Row: Placement & Player Info
                            ft.Row(
                                alignment=ft.MainAxisAlignment.SPACE_BETWEEN,
                                vertical_alignment=ft.CrossAxisAlignment.START,
                                spacing=8,
                                controls=[
                                    ft.Row(
                                        spacing=8,
                                        expand=True,
                                        controls=[
                                            ft.Container(
                                                content=ft.Text(
                                                    f"{badge_icon} {team.standing_label}",
                                                    size=11,
                                                    weight=ft.FontWeight.BOLD,
                                                    color=badge_color,
                                                ),
                                                bgcolor=badge_bg,
                                                border_radius=6,
                                                padding=ft.Padding.symmetric(horizontal=8, vertical=4),
                                            ),
                                            ft.Column(
                                                spacing=1,
                                                expand=True,
                                                controls=[
                                                    ft.Text(
                                                        team.player_name,
                                                        size=13,
                                                        weight=ft.FontWeight.BOLD,
                                                        max_lines=1,
                                                        overflow=ft.TextOverflow.ELLIPSIS,
                                                    ),
                                                    ft.Text(
                                                        tourney_name,
                                                        size=10,
                                                        color=Colors.GREY_400,
                                                        max_lines=1,
                                                        overflow=ft.TextOverflow.ELLIPSIS,
                                                        tooltip=tourney_name,
                                                    ),
                                                ],
                                            ),
                                        ],
                                    ),
                                    ft.Column(
                                        horizontal_alignment=ft.CrossAxisAlignment.END,
                                        spacing=2,
                                        controls=[
                                            ft.Container(
                                                content=ft.Text(tourney_reg, size=10, weight=ft.FontWeight.W_600, color=Colors.AMBER_400),
                                                bgcolor="#1e293b",
                                                border_radius=6,
                                                padding=ft.Padding.symmetric(horizontal=6, vertical=3),
                                                border=ft.Border.all(1, Colors.AMBER_700),
                                            ),
                                            legality_badge,
                                        ],
                                    ),
                                ],
                            ),
                            # Roster Sprites Row
                            ft.Row(
                                spacing=6,
                                wrap=True,
                                controls=member_controls,
                            ),
                            # Footer Action Row
                            ft.Row(
                                alignment=ft.MainAxisAlignment.SPACE_BETWEEN,
                                controls=[
                                    ft.ElevatedButton(
                                        "⚠️ Import (Validation Check)" if has_illegal_species else "📥 Import Team",
                                        icon=ft.Icons.DOWNLOAD,
                                        style=ft.ButtonStyle(
                                            bgcolor=Colors.RED_900 if has_illegal_species else Colors.AMBER_700,
                                            color=Colors.WHITE
                                        ),
                                        on_click=lambda e, t_text=team.showdown_text, t_name=team.player_name: _import_tournament_team(t_text, t_name),
                                    ),
                                    ft.OutlinedButton(
                                        "PokéPaste",
                                        icon=ft.Icons.OPEN_IN_NEW,
                                        visible=bool(team.pokepast_url),
                                        on_click=lambda e, url=team.pokepast_url: page.launch_url(url) if url else None,
                                    ),
                                ],
                            ),
                        ],
                    ),
                    bgcolor=Colors.CARD_BG,
                    border_radius=12,
                    padding=ft.Padding.all(14),
                    border=ft.Border.all(1, Colors.DIVIDER),
                )
                _tourney_grid.controls.append(card)

            _tourney_state["loaded"] += len(teams)
            _tourney_state["exhausted"] = len(teams) < _TOURNEY_PAGE_SIZE
            _tourney_more_btn.visible = not _tourney_state["exhausted"]
            _tourney_more_btn.text = f"Load more ({_tourney_state['loaded']} shown)"

        page.update()

    _tourney_more_btn.on_click = lambda e: _load_tourney_page()

    tourney_tab_layout = ft.Column(
        expand=True,
        spacing=12,
        controls=[
            ft.Row(
                spacing=8,
                wrap=True,
                controls=[
                    _tourney_search_tf,
                    _tourney_game_drop,
                    _tourney_recency_drop,
                    _tourney_format_drop,
                    _tourney_placement_drop,
                    ft.ElevatedButton("Search Roster", icon=ft.Icons.SEARCH, on_click=lambda e: _render_tourney_explorer(force=True)),
                ],
            ),
            _tourney_grid,
            ft.Row(alignment=ft.MainAxisAlignment.CENTER, controls=[_tourney_more_btn]),
        ],
    )



    # -----------------------------------------------------------------------
    # SETTINGS / DATA MANAGEMENT MODAL
    # Centralised place for all manual DB sync actions.
    # -----------------------------------------------------------------------

    # Spinner refs used by Settings modal rows
    _spinner_megas = ft.ProgressRing(visible=False, width=14, height=14, stroke_width=2)
    _spinner_items = ft.ProgressRing(visible=False, width=14, height=14, stroke_width=2)
    _spinner_tourneys = ft.ProgressRing(visible=False, width=14, height=14, stroke_width=2)

    # Status text refs updated after each sync
    _status_megas = ft.Text("", size=11, color=Colors.GREY_400)
    _status_items = ft.Text("", size=11, color=Colors.GREY_400)
    _status_tourneys = ft.Text("", size=11, color=Colors.GREY_400)

    def _count_text(label: str, count: int, unit: str) -> str:
        return f"{count:,} {unit}" if count > 0 else "Not yet synced"

    def _refresh_settings_status():
        with get_session() as session:
            mega_repo = MegaEvolutionRepository(session)
            item_repo = ItemRepository(session)
            tourney_svc = TournamentService(session)
            mega_count = len(mega_repo.list_all())
            item_count = item_repo.count()
            tourney_count = len(tourney_svc.list_tournaments())
        _status_megas.value = _count_text("Megas", mega_count, "forms cached")
        _status_items.value = _count_text("Items", item_count, "items catalogued")
        _status_tourneys.value = _count_text("Tournaments", tourney_count, "events synced")
        page.update()

    def _handle_sync_megas(e=None):
        _spinner_megas.visible = True
        _status_megas.value = "Syncing…"
        page.update()
        def _bg():
            try:
                with get_session() as session:
                    res = sync_all_champions_megas_on_startup(session)
                load_champions_catalog()
                _status_megas.value = f"{res.get('total_local', 0):,} forms cached"
                show_toast(f"✅ Mega Evolutions synced! ({res.get('total_local', 0)} cached)")
            except Exception as ex:
                show_toast(f"Mega sync error: {ex}", is_error=True)
                _status_megas.value = "Sync failed"
            finally:
                _spinner_megas.visible = False
                page.update()
        threading.Thread(target=_bg, daemon=True).start()

    def _handle_sync_items(e=None):
        _spinner_items.visible = True
        _status_items.value = "Syncing…"
        page.update()
        def _bg():
            try:
                with get_session() as session:
                    res = sync_items_catalog(session, force=True)
                load_items_to_state()
                _status_items.value = f"{res.get('total', 0):,} items catalogued"
                show_toast(f"✅ Items catalog synced! ({res.get('added', 0)} added, {res.get('updated', 0)} updated)")
                render_team_builder()
            except Exception as ex:
                show_toast(f"Items sync error: {ex}", is_error=True)
                _status_items.value = "Sync failed"
            finally:
                _spinner_items.visible = False
                page.update()
        threading.Thread(target=_bg, daemon=True).start()

    def _handle_sync_tourneys(e=None):
        _spinner_tourneys.visible = True
        _status_tourneys.value = "Syncing…"
        page.update()
        def _bg():
            try:
                with get_session() as session:
                    tourney_svc = TournamentService(session)
                    res = tourney_svc.sync(force=True, max_age_days=365, include_official=True)
                    count = len(tourney_svc.list_tournaments())
                _status_tourneys.value = f"{count:,} events synced"
                show_toast("✅ Tournament datasets synced from Limitless & Victory Road!")
                # New rows landed; bypass the cached grid.
                _render_tourney_explorer(force=True)
            except Exception as ex:
                show_toast(f"Tournament sync error: {ex}", is_error=True)
                _status_tourneys.value = "Sync failed"
            finally:
                _spinner_tourneys.visible = False
                page.update()
        threading.Thread(target=_bg, daemon=True).start()

    def _make_settings_row(icon, title: str, status_ref, spinner_ref, on_sync) -> ft.Container:
        return ft.Container(
            content=ft.Row(
                alignment=ft.MainAxisAlignment.SPACE_BETWEEN,
                controls=[
                    ft.Row(spacing=10, controls=[
                        ft.Icon(icon, size=18, color=Colors.AMBER_400),
                        ft.Column(spacing=2, controls=[
                            ft.Text(title, size=13, weight=ft.FontWeight.W_600),
                            status_ref,
                        ])
                    ]),
                    ft.Row(spacing=6, controls=[
                        spinner_ref,
                        ft.Container(
                            content=ft.Row(spacing=4, controls=[
                                ft.Icon(ft.Icons.SYNC, size=13, color=Colors.WHITE),
                                ft.Text("Sync", size=11, weight=ft.FontWeight.W_600, color=Colors.WHITE),
                            ]),
                            bgcolor=Colors.AMBER_700,
                            border_radius=6,
                            padding=ft.Padding.symmetric(horizontal=10, vertical=6),
                            on_click=on_sync,
                        )
                    ])
                ]
            ),
            bgcolor=Colors.CARD_BG,
            border_radius=8,
            padding=ft.Padding.symmetric(horizontal=14, vertical=12),
            border=ft.Border.all(1, Colors.DIVIDER),
        )

    settings_modal = ft.AlertDialog(
        title=ft.Row(spacing=10, controls=[
            ft.Icon(ft.Icons.SETTINGS, color=Colors.AMBER_400),
            ft.Text("Data & Synchronization", weight=ft.FontWeight.BOLD, size=16),
        ]),
        content=ft.Container(
            width=460,
            content=ft.Column(
                spacing=10,
                tight=True,
                controls=[
                    ft.Text(
                        "Manage the local SQLite catalog. Sync pulls the latest data from PokéAPI, Showdown, Limitless & Victory Road.",
                        size=12, color=Colors.GREY_400
                    ),
                    ft.Divider(height=1, color=Colors.DIVIDER),
                    _make_settings_row(
                        ft.Icons.FLASH_ON, "Mega Evolutions",
                        _status_megas, _spinner_megas, _handle_sync_megas
                    ),
                    _make_settings_row(
                        ft.Icons.DIAMOND, "Held Items Catalog",
                        _status_items, _spinner_items, _handle_sync_items
                    ),
                    _make_settings_row(
                        ft.Icons.EMOJI_EVENTS, "Live Tournaments Meta",
                        _status_tourneys, _spinner_tourneys, _handle_sync_tourneys
                    ),
                ]
            )
        ),
        actions=[ft.TextButton("Close", on_click=lambda e: _close_settings())],
    )
    page.overlay.append(settings_modal)

    def _open_settings(e=None):
        _refresh_settings_status()
        settings_modal.open = True
        page.update()

    def _close_settings(e=None):
        settings_modal.open = False
        page.update()

    # -----------------------------------------------------------------------
    # ITEM PICKER MODAL
    # Opened when clicking the held-item slot of a team member card.
    # -----------------------------------------------------------------------

    _item_search_query = ft.Ref[ft.TextField]()
    _item_list_col = ft.Column(scroll=ft.ScrollMode.AUTO, height=380, spacing=6)
    _item_legal_only = ft.Ref[ft.Checkbox]()
    _item_category_filter = ft.Ref[ft.Dropdown]()

    def _render_item_picker_list():
        _item_list_col.controls.clear()
        query = (_item_search_query.current.value or "").strip().lower()
        legal_only = _item_legal_only.current.value if _item_legal_only.current else True
        cat_filter = _item_category_filter.current.value if _item_category_filter.current else "all"
        target_species = state.get("item_picker_species")

        source = state["champions_items"] if legal_only else state["items_catalog"]
        if cat_filter and cat_filter != "all":
            source = [i for i in source if (i.category or "").replace("-", " ") == cat_filter.replace("-", " ")]
        if query:
            source = [i for i in source if query in i.display_name.lower() or query in (i.short_effect or "").lower()]

        if not source:
            _item_list_col.controls.append(
                ft.Container(
                    content=ft.Text("No items found.", size=12, color=Colors.GREY_500, italic=True),
                    alignment=ft.Alignment.CENTER, padding=ft.Padding.all(20)
                )
            )
            page.update()
            return

        # Separate items into valid vs incompatible Mega Stones for target_species
        valid_items = []
        incompatible_megas = []

        for item in source:
            if target_species and item.target_species:
                if item.target_species.lower() != target_species.lower():
                    incompatible_megas.append(item)
                else:
                    valid_items.append(item)
            else:
                valid_items.append(item)

        # Helper to build an item row card control
        def _build_item_card(item, is_incompatible_mega: bool = False):
            is_legal = item.is_champions_legal

            if is_incompatible_mega:
                bg_col = "#241618"  # Dark muted red background
                border_col = Colors.RED_900
                badge_col = Colors.RED_400
                badge_txt = f"Species Mismatch (Requires {item.target_species.title()})"
                badge_icon = ft.Icons.ERROR_OUTLINE
                title_col = Colors.RED_200
            else:
                bg_col = Colors.CARD_BG
                border_col = Colors.DIVIDER
                badge_col = Colors.GREEN_400 if is_legal else Colors.AMBER_400
                badge_txt = "Champions Legal" if is_legal else "Banned in Champions"
                badge_icon = ft.Icons.CHECK_CIRCLE if is_legal else ft.Icons.WARNING_ROUNDED
                if item.target_species and target_species and item.target_species.lower() == target_species.lower():
                    badge_txt += f" — Compatible with {target_species.title()}"
                    badge_col = Colors.CYAN_400
                    badge_icon = ft.Icons.FLASH_ON
                title_col = Colors.WHITE

            return ft.Container(
                content=ft.Row(
                    spacing=10,
                    controls=[
                        ft.Image(src=item.sprite_url, width=32, height=32, fit=ft.BoxFit.CONTAIN)
                        if item.sprite_url else
                        ft.Icon(
                            ft.Icons.FLASH_ON if item.target_species else ft.Icons.DIAMOND,
                            size=24,
                            color=Colors.RED_400 if is_incompatible_mega else Colors.AMBER_400
                        ),
                        ft.Column(spacing=2, expand=True, controls=[
                            ft.Text(item.display_name, size=13, weight=ft.FontWeight.W_600, color=title_col),
                            ft.Text(item.short_effect or "", size=11, color=Colors.GREY_400,
                                    overflow=ft.TextOverflow.ELLIPSIS, max_lines=2),
                            ft.Row(spacing=4, controls=[
                                ft.Icon(badge_icon, size=11, color=badge_col),
                                ft.Text(badge_txt, size=10, color=badge_col, weight=ft.FontWeight.W_500),
                            ]),
                            # Stat modifier pills (e.g. Choice Band → +50% Atk)
                            *([ft.Row(wrap=True, spacing=4, run_spacing=4, controls=[
                                ft.Container(
                                    content=ft.Text(
                                        f"{'+'if round((mult-1)*100)>=0 else ''}{round((mult-1)*100)}% {k.replace('_',' ').title()}",
                                        size=9, color=STAT_COLORS.get(k, Colors.GREY_400)
                                    ),
                                    bgcolor=Colors.CARD_BG,
                                    border=ft.Border.all(1, STAT_COLORS.get(k, Colors.GREY_400)),
                                    border_radius=4,
                                    padding=ft.Padding.symmetric(horizontal=4, vertical=2),
                                )
                                for k, mult in (item.stat_modifiers or {}).items()
                                if mult != 1.0
                            ])] if item.stat_modifiers else []),
                        ]),
                    ]
                ),
                bgcolor=bg_col,
                border_radius=8,
                padding=ft.Padding.symmetric(horizontal=10, vertical=8),
                border=ft.Border.all(1, border_col),
                on_click=lambda e, it=item: _handle_item_selected(it),
                ink=True,
            )

        # Render valid items
        for item in valid_items[:80]:
            _item_list_col.controls.append(_build_item_card(item, is_incompatible_mega=False))

        # Render incompatible Mega Stones section divider and cards at bottom
        if incompatible_megas:
            _item_list_col.controls.append(
                ft.Container(
                    content=ft.Row(
                        spacing=8,
                        alignment=ft.MainAxisAlignment.CENTER,
                        controls=[
                            ft.Divider(height=1, expand=True, color=Colors.RED_900),
                            ft.Icon(ft.Icons.WARNING_AMBER_ROUNDED, size=14, color=Colors.RED_400),
                            ft.Text(
                                f"Incompatible Mega Stones ({len(incompatible_megas)})",
                                size=11, weight=ft.FontWeight.BOLD, color=Colors.RED_400
                            ),
                            ft.Divider(height=1, expand=True, color=Colors.RED_900),
                        ]
                    ),
                    padding=ft.Padding.symmetric(vertical=10)
                )
            )
            for item in incompatible_megas[:40]:
                _item_list_col.controls.append(_build_item_card(item, is_incompatible_mega=True))

        page.update()

    def _handle_item_selected(item):
        slot = state.get("item_picker_slot")
        if slot is None:
            return
        item_picker_modal.open = False
        page.update()
        # Persist choice via existing update handler flow
        _apply_item_to_slot(slot, item.canonical_id)

    def _apply_item_to_slot(slot_position: int, item_canonical_id: str | None):
        if state["active_team_id"] is None:
            return
        box_repo, team_repo, _, session = get_repositories()
        try:
            members = team_repo.list_members(state["active_team_id"])
            matching = next((m for m in members if m.slot_position == slot_position), None)
            if matching:
                selected_form = matching.selected_form or "base"

                if item_canonical_id and item_canonical_id in state["items_by_id"]:
                    item_rec = state["items_by_id"][item_canonical_id]
                    if item_rec.target_species and item_rec.target_form:
                        # Check species match
                        box_entry = box_repo.load_entry(str(matching.box_entry_id)) if matching.box_entry_id else None
                        species = box_entry.pokemon.species_name if box_entry else None
                        if species and item_rec.target_species.lower() == species.lower():
                            selected_form = item_rec.target_form
                    elif not item_rec.target_species and selected_form.startswith("mega"):
                        selected_form = "base"
                elif item_canonical_id is None and selected_form.startswith("mega"):
                    selected_form = "base"

                updated = TeamMember(
                    team_member_id=matching.team_member_id,
                    box_entry_id=matching.box_entry_id,
                    slot_position=slot_position,
                    selected_form=selected_form,
                    item=item_canonical_id,
                    moveset=matching.moveset,
                    ability=matching.ability,
                    notes=matching.notes or ""
                )
                team_repo.upsert_member(state["active_team_id"], updated)
        finally:
            session.close()
        render_team_builder()

    def _open_item_picker(slot_position: int):
        state["item_picker_slot"] = slot_position
        species_name = None
        if state["active_team_id"] is not None:
            box_repo, team_repo, _, session = get_repositories()
            try:
                members = team_repo.list_members(state["active_team_id"])
                matching = next((m for m in members if m.slot_position == slot_position), None)
                if matching and matching.box_entry_id:
                    box_entry = box_repo.load_entry(str(matching.box_entry_id))
                    if box_entry:
                        species_name = box_entry.pokemon.species_name
            finally:
                session.close()
        state["item_picker_species"] = species_name

        if _item_search_query.current:
            _item_search_query.current.value = ""
        _render_item_picker_list()
        item_picker_modal.open = True
        page.update()

    # Build category options from existing items
    def _get_category_options():
        seen = set()
        opts = [ft.dropdown.Option("all", text="All Categories")]
        for it in state["items_catalog"]:
            cat = (it.category or "other")
            if cat not in seen:
                seen.add(cat)
                opts.append(ft.dropdown.Option(cat, text=cat.replace("-", " ").title()))
        return opts

    item_picker_modal = ft.AlertDialog(
        title=ft.Row(spacing=8, controls=[
            ft.Icon(ft.Icons.DIAMOND, color=Colors.AMBER_400),
            ft.Text("Select Held Item", weight=ft.FontWeight.BOLD, size=16),
        ]),
        content=ft.Container(
            width=480,
            content=ft.Column(
                spacing=8,
                tight=True,
                controls=[
                    ft.Row(spacing=8, controls=[
                        ft.TextField(
                            ref=_item_search_query,
                            label="Search items…",
                            prefix_icon=ft.Icons.SEARCH,
                            expand=True,
                            text_size=13,
                            on_change=lambda e: _render_item_picker_list(),
                        ),
                        ft.Dropdown(
                            ref=_item_category_filter,
                            label="Category",
                            width=160,
                            text_size=12,
                            options=[ft.dropdown.Option("all", text="All")],
                            on_select=lambda e: _render_item_picker_list(),
                        ),
                    ]),
                    ft.Checkbox(
                        ref=_item_legal_only,
                        label="Champions-legal only",
                        value=True,
                        on_change=lambda e: _render_item_picker_list(),
                    ),
                    ft.Divider(height=1, color=Colors.DIVIDER),
                    _item_list_col,
                ]
            )
        ),
        actions=[
            ft.TextButton("Clear Item", on_click=lambda e: [
                setattr(item_picker_modal, "open", False),
                _apply_item_to_slot(state.get("item_picker_slot"), None),
                page.update(),
            ]),
            ft.TextButton("Cancel", on_click=lambda e: [
                setattr(item_picker_modal, "open", False),
                page.update(),
            ]),
        ],
    )
    page.overlay.append(item_picker_modal)


    # --- Initial State Load ---
    # Seed the bundled tournament dataset once per app start. This previously ran on
    # every Tournament Explorer render, re-reading and re-parsing the file each time.
    try:
        with get_session() as seed_session:
            TournamentService(seed_session, seed_file_path=SEED_FILE_PATH)
    except Exception as exc:
        print(f"⚠️ Tournament seed check skipped: {exc}")

    load_champions_catalog()
    load_items_to_state()
    # Populate item picker category dropdown after items are loaded
    if _item_category_filter.current:
        _item_category_filter.current.options = _get_category_options()
    refresh_box()
    refresh_teams()

    # --- Background Sync of Live Tournament Meta (Guarded to 1 run per process) ---
    def _startup_tourney_sync():
        global _global_sync_done
        with _global_sync_lock:
            if _global_sync_done:
                return
            _global_sync_done = True

        try:
            with get_session() as sync_sess:
                t_svc = TournamentService(sync_sess)
                res = t_svc.sync(force=False, max_age_days=365, include_official=True)
                print(f"✅ Startup tournament sync completed: {res}")
            # The grid may already have been built from pre-sync data.
            _invalidate_tourney_cache()
        except Exception as exc:
            print(f"⚠️ Startup tournament sync skipped/failed: {exc}")

    threading.Thread(target=_startup_tourney_sync, daemon=True).start()

    return LegacyViews(
        box=box_tab_layout,
        team=team_tab_layout,
        meta=tourney_tab_layout,
        on_activate_meta=lambda: _render_tourney_explorer(),
        open_settings=lambda: _open_settings(),
        refresh_box=refresh_box,
        refresh_teams=refresh_teams,
        render_team_builder=render_team_builder,
        render_meta=lambda force=False: _render_tourney_explorer(force=force),
        invalidate_meta=_invalidate_tourney_cache,
        reload_catalogs=load_champions_catalog,
        reload_items=load_items_to_state,
        import_showdown_text=_import_tournament_team,
        open_import_modal=lambda: _open_import_modal(),
        open_export_modal=lambda: _open_export_modal(),
    )

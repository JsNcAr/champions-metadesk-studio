"""Flet GUI application for Pokemon box and team management."""

import threading
import flet as ft
from uuid import UUID

# Bypass Flet's buggy deprecation wrapper on colors
class ColorsBypass:
    WHITE = "white"
    BLACK = "black"
    RED_ACCENT = "redaccent"
    GREEN_ACCENT_700 = "#16a34a"
    GREY_400 = "#9ca3af"
    YELLOW = "#fbbf24"
    GREY_600 = "#6b7280"
    AMBER_400 = "#fbbf24"
    AMBER_700 = "#d97706"
    AMBER_100 = "#fef3c7"
    # Surfaces
    BG_BASE = "#0f172a"         # page background
    CARD_BG = "#1e293b"         # default card surface
    CARD_SELECTED = "#1e3a5f"   # selected card highlight (blue tinted)
    PANEL_BG = "#111827"        # right panel / drawer
    TOOLBAR_BG = "#1e293b"      # filter toolbar bar
    HEADER_BG = "#0f172a"
    BLUE_GREY_900 = "#1e293b"
    BLUE_GREY_950 = "#111827"
    SURFACE_VARIANT = "#1e293b"
    DIVIDER = "#334155"
    # Text
    GREY_500 = "#6b7280"
    GREY_300 = "#d1d5db"
    # Semantic
    RED_400 = "#f87171"
    RED_700 = "#b91c1c"
    ORANGE_400 = "#fb923c"
    YELLOW_400 = "#facc15"
    BLUE_400 = "#60a5fa"
    BLUE_300 = "#93c5fd"
    GREEN_400 = "#4ade80"
    PINK_400 = "#f472b6"
    GREY_800 = "#374151"

ft.Colors = ColorsBypass

from ..config import APP_NAME
from ..domain.entities.box_entry import BoxEntry
from ..domain.entities.team import Team
from ..domain.entities.team_member import TeamMember
from ..domain.entities.pokemon_move import PokemonMove
from ..infrastructure.database.database import get_session
from ..infrastructure.database.repositories import (
    BoxRepository,
    TeamRepository,
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

# Pokémon Type Colors
TYPE_COLORS = {
    "normal": "#A8A878", "fire": "#F08030", "water": "#6890F0", "grass": "#78C030",
    "electric": "#F8D030", "ice": "#98D8D8", "fighting": "#C03028", "poison": "#A040A0",
    "ground": "#E0C068", "flying": "#A890F0", "psychic": "#F85888", "bug": "#A8B820",
    "rock": "#B8A038", "ghost": "#705898", "dragon": "#7038F8", "dark": "#705848",
    "steel": "#B8B8D0", "fairy": "#EE99AC", "unknown": "#68A090"
}

# Pokémon Stat Colors (Official Palette)
STAT_COLORS = {
    "hp": "#FF5959",
    "attack": "#F08030",
    "defense": "#F8D030",
    "special_attack": "#6890F0",
    "special_defense": "#78C850",
    "speed": "#F85888",
}


# Design constants
_C = ft.Colors  # alias

# Padding helpers
P_CARD = ft.Padding.symmetric(horizontal=12, vertical=10)
P_PANEL = ft.Padding.all(16)


def main(page: ft.Page):
    page.title = APP_NAME
    page.theme_mode = ft.ThemeMode.DARK
    page.bgcolor = ft.Colors.BG_BASE
    page.padding = ft.Padding.symmetric(horizontal=20, vertical=16)
    page.window_width = 1280
    page.window_height = 800
    page.spacing = 0
    page.fonts = {
        "Inter": "https://fonts.gstatic.com/s/inter/v13/UcCO3FwrK3iLTeHuS_fvQtMwCp50KnMw2boKoduKmMEVuLyfAZ9hiA.woff2"
    }

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
        snack = ft.SnackBar(
            content=ft.Text(message, color=ft.Colors.WHITE),
            bgcolor=ft.Colors.RED_ACCENT if is_error else ft.Colors.GREEN_ACCENT_700,
            duration=3000
        )
        page.overlay.append(snack)
        snack.open = True
        page.update()

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

    # --- Detail Drawer UI elements ---
    detail_container = ft.Column(spacing=12, expand=True, scroll=ft.ScrollMode.AUTO)
    detail_panel = ft.Container(
        content=detail_container,
        width=310,
        expand=True,
        bgcolor=ft.Colors.PANEL_BG,
        padding=ft.Padding.all(16),
        border_radius=12,
        border=ft.Border.all(1, ft.Colors.DIVIDER),
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
        child_aspect_ratio=0.75,
        spacing=15,
        run_spacing=15,
    )
    team_totals_row = ft.Row(spacing=15, alignment=ft.MainAxisAlignment.CENTER)

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
                        ft.Icon(ft.Icons.CATCHING_POKEMON, size=13, color=ft.Colors.AMBER_400),
                        ft.Text(rec.display_name, size=12, weight=ft.FontWeight.W_600, color=ft.Colors.WHITE)
                    ]
                ),
                bgcolor=ft.Colors.CARD_SELECTED,
                padding=ft.Padding.symmetric(horizontal=10, vertical=6),
                border_radius=16,
                border=ft.Border.all(1, ft.Colors.AMBER_700),
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
                    ability=box_entry.pokemon.abilities[0].name.title() if box_entry.pokemon.abilities else None,
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

    def handle_update_member_field(slot_position: int, selected_form: str, ability: str, item: str, moves_str: str, notes: str):
        if state["active_team_id"] is None:
            return
        _, team_repo, _, session = get_repositories()
        try:
            members = team_repo.list_members(state["active_team_id"])
            matching = next((m for m in members if m.slot_position == slot_position), None)
            if matching:
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
                    notes=notes.strip()
                )
                team_repo.upsert_member(state["active_team_id"], updated_member)
                show_toast("Team slot updated")
                render_team_builder()
        finally:
            session.close()

    # --- Renderers ---
    def render_box_grid(update_page: bool = True):
        box_grid.child_aspect_ratio = 0.60 if state["all_stats_visible"] else 0.80
        
        filtered = []
        for entry in state["box_entries"]:
            name_match = state["search_query"] in entry.pokemon.display_name.lower()
            tag_match = any(state["search_query"] in tag.lower() for tag in entry.tags)
            type_match = any(state["search_query"] in t.lower() for t in entry.pokemon.types)
            if state["search_query"] == "" or name_match or tag_match or type_match:
                filtered.append(entry)

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

        mega_species = state.get("mega_species_set", set())

        new_cards = []
        for entry in filtered:
            has_megas = entry.pokemon.species_name.lower() in mega_species

            # Card styling
            types_row = ft.Row(
                alignment=ft.MainAxisAlignment.CENTER,
                spacing=5,
                controls=[
                    ft.Container(
                        content=ft.Text(t.upper(), size=10, weight=ft.FontWeight.BOLD, color=ft.Colors.WHITE),
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
                                    ft.Text(str(val), size=9, weight=ft.FontWeight.BOLD, color=ft.Colors.WHITE),
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
                                ft.Icon(ft.Icons.FLASH_ON, size=10, color=ft.Colors.AMBER_400),
                                ft.Text("Mega Available", size=10, weight=ft.FontWeight.BOLD, color=ft.Colors.AMBER_400)
                            ]
                        ),
                        bgcolor="#291d03",
                        border_radius=10,
                        padding=ft.Padding.symmetric(horizontal=6, vertical=2),
                        border=ft.Border.all(1, ft.Colors.AMBER_400)
                    )
                )
            else:
                card_info_controls.append(
                    ft.Text(f"Form: {entry.pokemon.form_name}", size=11, color=ft.Colors.GREY_400)
                )

            card_info_controls.extend([stats_block, types_row])

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
                                        icon_color=ft.Colors.YELLOW if entry.is_favorite else ft.Colors.GREY_600,
                                        on_click=lambda e, ent=entry: handle_toggle_favorite(ent, not ent.is_favorite),
                                        tooltip="Favorite"
                                    ),
                                    ft.Text(f"BST {entry.pokemon.total}", size=12, weight=ft.FontWeight.BOLD, color=ft.Colors.AMBER_400)
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
                bgcolor=ft.Colors.CARD_SELECTED if state["selected_pokemon_id"] == entry.box_entry_id else ft.Colors.CARD_BG
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
                            ft.Icon(ft.Icons.CATCHING_POKEMON, color=ft.Colors.AMBER_400, size=16),
                            ft.Text("POKÉMON DETAILS", weight=ft.FontWeight.BOLD, size=13,
                                    color=ft.Colors.AMBER_400)
                        ]),
                        ft.IconButton(
                            icon=ft.Icons.CLOSE, icon_size=18,
                            icon_color=ft.Colors.GREY_400,
                            on_click=lambda e: close_detail_container()
                        )
                    ]
                ),
                bgcolor=ft.Colors.CARD_BG,
                border_radius=8,
                padding=ft.Padding.symmetric(horizontal=12, vertical=8),
                border=ft.Border.all(1, ft.Colors.DIVIDER)
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
                    content=ft.Text("Base Form", size=11, weight=ft.FontWeight.BOLD, color=ft.Colors.AMBER_400 if base_active else ft.Colors.WHITE),
                    bgcolor="#78350f" if base_active else "#1e293b",
                    padding=ft.Padding.symmetric(horizontal=10, vertical=4),
                    border_radius=12,
                    border=ft.Border.all(1, ft.Colors.AMBER_400 if base_active else ft.Colors.DIVIDER),
                    on_click=lambda e: set_detail_form("base")
                )
            )
            for m in megas:
                m_active = (active_form_id == m.canonical_id)
                form_pills.append(
                    ft.Container(
                        content=ft.Text(f"⚡ {m.form_name}", size=11, weight=ft.FontWeight.BOLD, color=ft.Colors.AMBER_400 if m_active else ft.Colors.WHITE),
                        bgcolor="#78350f" if m_active else "#1e293b",
                        padding=ft.Padding.symmetric(horizontal=10, vertical=4),
                        border_radius=12,
                        border=ft.Border.all(1, ft.Colors.AMBER_400 if m_active else ft.Colors.DIVIDER),
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
                bgcolor=ft.Colors.CARD_BG,
                border_radius=55,
                width=130, height=130,
                alignment=ft.Alignment.CENTER,
                border=ft.Border.all(2, ft.Colors.DIVIDER),
                margin=ft.Margin.symmetric(vertical=6)
            )
        )

        # Name / info & Type Badges
        type_badges = []
        for t in display_types:
            bg_col = TYPE_COLORS.get(t.lower(), "#777777")
            type_badges.append(
                ft.Container(
                    content=ft.Text(t.upper(), size=10, weight=ft.FontWeight.BOLD, color=ft.Colors.WHITE),
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
                        content=ft.Text(display_sub, size=12, color=ft.Colors.GREY_400),
                        bgcolor=ft.Colors.CARD_BG,
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
                                color=ft.Colors.GREY_400),
                border=ft.Border(bottom=ft.BorderSide(1, ft.Colors.DIVIDER)),
                padding=ft.Padding.only(bottom=4)
            )

        # Base Stats
        detail_container.controls.append(_section("STAT OVERVIEW"))
        stats_list = [
            ("HP",  display_hp,  ft.Colors.RED_400),
            ("Atk", display_atk, ft.Colors.ORANGE_400),
            ("Def", display_def, ft.Colors.YELLOW_400),
            ("SpA", display_spa, ft.Colors.BLUE_400),
            ("SpD", display_spd, ft.Colors.GREEN_400),
            ("Spe", display_spe, ft.Colors.PINK_400),
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
                            bgcolor=ft.Colors.GREY_800,
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
                    size=11, color=ft.Colors.GREY_500, italic=True
                ),
                bgcolor=ft.Colors.CARD_BG,
                border=ft.Border.all(1, ft.Colors.DIVIDER),
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
                    color=ft.Colors.WHITE,
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

                slot_card = ft.Card(
                    content=ft.Container(
                        content=ft.Column(
                            alignment=ft.MainAxisAlignment.CENTER,
                            horizontal_alignment=ft.CrossAxisAlignment.CENTER,
                            controls=[
                                ft.Icon(ft.Icons.ADD_BOX, size=40, color=ft.Colors.GREY_500),
                                ft.Text(f"Slot {slot}", weight=ft.FontWeight.BOLD, size=15),
                                ft.Text("Empty Slot", size=12, color=ft.Colors.GREY_500),
                                ft.ElevatedButton("Assign Pokémon", on_click=make_open_handler())
                            ]
                        ),
                        padding=15,
                        alignment=ft.Alignment.CENTER
                    ),
                    bgcolor=ft.Colors.BLUE_GREY_950
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
                        text_size=12
                    )

                ability_options = [
                    ft.dropdown.Option(text=ab.name.title().replace("-", " "))
                    for ab in pokemon.abilities
                ]
                
                ability_drop = ft.Dropdown(
                    label="Ability",
                    value=matching_member.ability or (ability_options[0].text if ability_options else ""),
                    options=ability_options,
                    text_size=12
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
                    item_label_col = ft.Colors.WHITE
                    item_icon_src = current_item_rec.sprite_url
                else:
                    item_label_txt = "Select Held Item…"
                    item_label_col = ft.Colors.GREY_500
                    item_icon_src = None

                # Guardrail badge
                guardrail_controls = []
                if validation and validation.error:
                    guardrail_controls.append(
                        ft.Container(
                            content=ft.Row(spacing=4, controls=[
                                ft.Icon(ft.Icons.ERROR, size=12, color=ft.Colors.RED_400),
                                ft.Text(validation.error, size=10, color=ft.Colors.RED_400,
                                        overflow=ft.TextOverflow.ELLIPSIS, max_lines=2),
                            ]),
                            bgcolor="#3b0000",
                            border=ft.Border.all(1, ft.Colors.RED_400),
                            border_radius=5,
                            padding=ft.Padding.symmetric(horizontal=6, vertical=4),
                        )
                    )
                elif validation and validation.warning:
                    guardrail_controls.append(
                        ft.Container(
                            content=ft.Row(spacing=4, controls=[
                                ft.Icon(ft.Icons.WARNING_ROUNDED, size=12, color=ft.Colors.AMBER_400),
                                ft.Text(validation.warning, size=10, color=ft.Colors.AMBER_400,
                                        overflow=ft.TextOverflow.ELLIPSIS, max_lines=2),
                            ]),
                            bgcolor="#291d03",
                            border=ft.Border.all(1, ft.Colors.AMBER_400),
                            border_radius=5,
                            padding=ft.Padding.symmetric(horizontal=6, vertical=4),
                        )
                    )

                # Speed modifier badge (shown inline in the stat row)
                speed_badge = None
                if speed_modified:
                    delta_pct = round((effective_stats.speed / pokemon.stats.speed - 1) * 100)
                    badge_sign = "+" if delta_pct > 0 else ""
                    badge_col = ft.Colors.BLUE_400 if delta_pct > 0 else ft.Colors.ORANGE_400
                    speed_badge = ft.Container(
                        content=ft.Text(f"Spe {effective_stats.speed} ({badge_sign}{delta_pct}%)",
                                        size=10, weight=ft.FontWeight.BOLD, color=badge_col),
                        bgcolor=ft.Colors.CARD_BG,
                        border=ft.Border.all(1, badge_col),
                        border_radius=4,
                        padding=ft.Padding.symmetric(horizontal=5, vertical=2),
                    )

                item_slot_widget = ft.Container(
                    content=ft.Column(spacing=4, controls=[
                        ft.Row(
                            alignment=ft.MainAxisAlignment.SPACE_BETWEEN,
                            controls=[
                                ft.Text("Held Item", size=10, weight=ft.FontWeight.BOLD,
                                        color=ft.Colors.GREY_400),
                                ft.Row(spacing=4, controls=[
                                    speed_badge if speed_badge else ft.Container(),
                                    ft.IconButton(
                                        icon=ft.Icons.CLOSE, icon_size=14,
                                        icon_color=ft.Colors.GREY_500,
                                        tooltip="Remove Item",
                                        visible=current_item_rec is not None,
                                        on_click=lambda e, s=slot: _apply_item_to_slot(s, None),
                                    )
                                ])
                            ]
                        ),
                        ft.Container(
                            content=ft.Row(spacing=8, controls=[
                                ft.Image(src=item_icon_src, width=24, height=24, fit=ft.BoxFit.CONTAIN)
                                if item_icon_src else ft.Icon(ft.Icons.DIAMOND_OUTLINED, size=20, color=ft.Colors.GREY_500),
                                ft.Text(item_label_txt, size=12, color=item_label_col, expand=True,
                                        overflow=ft.TextOverflow.ELLIPSIS),
                                ft.Icon(ft.Icons.ARROW_FORWARD_IOS, size=12, color=ft.Colors.GREY_500),
                            ]),
                            bgcolor=ft.Colors.CARD_BG,
                            border_radius=6,
                            border=ft.Border.all(1, ft.Colors.DIVIDER),
                            padding=ft.Padding.symmetric(horizontal=8, vertical=8),
                            on_click=lambda e, s=slot: _open_item_picker(s),
                            ink=True,
                        ),
                        *guardrail_controls,
                    ]),
                )
                # -------------------------------------------------------------------

                moves_str = ", ".join(m.name for m in matching_member.moveset)
                moves_field = ft.TextField(
                    label="Moveset (comma separated)",
                    value=moves_str,
                    hint_text="e.g. Thunderbolt, Ice Beam",
                    text_size=12
                )
                
                notes_field = ft.TextField(
                    label="Slot Planning Notes",
                    value=matching_member.notes or "",
                    text_size=12
                )

                def make_update_handler(s_pos=slot, fm_dr=form_drop, ab_dr=ability_drop, item_id=current_item_id, mv_fl=moves_field, nt_fl=notes_field):
                    return lambda e: handle_update_member_field(s_pos, fm_dr.value if fm_dr else "base", ab_dr.value, item_id or "", mv_fl.value, nt_fl.value)

                def make_remove_handler(s_pos=slot):
                    return lambda e: handle_remove_member(s_pos)

                slot_controls = [
                    ft.Row(
                        alignment=ft.MainAxisAlignment.SPACE_BETWEEN,
                        controls=[
                            ft.Text(f"Slot {slot}", weight=ft.FontWeight.BOLD, size=14, color=ft.Colors.AMBER_400),
                            ft.IconButton(ft.Icons.DELETE_FOREVER, icon_color=ft.Colors.RED_400, on_click=make_remove_handler(), tooltip="Remove Member")
                        ]
                    ),
                    ft.Row(
                        spacing=10,
                        controls=[
                            ft.Image(src=card_sprite, width=50, height=50, fit=ft.BoxFit.CONTAIN) if card_sprite else ft.Icon(ft.Icons.IMAGE),
                            ft.Column(
                                spacing=2,
                                controls=[
                                    ft.Text(card_name, size=14, weight=ft.FontWeight.BOLD),
                                    ft.Text(f"BST: {card_bst}", size=11, color=ft.Colors.GREY_400)
                                ]
                            )
                        ]
                    ),
                ]
                if form_drop:
                    slot_controls.append(form_drop)
                slot_controls.extend([
                    ability_drop,
                    item_slot_widget,
                    moves_field,
                    notes_field,
                    ft.ElevatedButton("Save Changes", icon=ft.Icons.SAVE, on_click=make_update_handler(), height=30)
                ])

                slot_card = ft.Card(
                    content=ft.Container(
                        content=ft.Column(
                            spacing=6,
                            scroll=ft.ScrollMode.AUTO,
                            controls=slot_controls
                        ),
                        padding=12
                    )
                )

            team_grid.controls.append(slot_card)

        update_team_totals()
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

        totals_list = [
            ("HP", total_hp), ("Atk", total_attack), ("Def", total_defense),
            ("SpA", total_spa), ("SpD", total_spd), ("Spe", total_speed)
        ]

        totals_controls = [
            ft.Text("TEAM TOTALS:", weight=ft.FontWeight.BOLD, color=ft.Colors.AMBER_400, size=13)
        ]
        for label, val in totals_list:
            totals_controls.append(
                ft.Container(
                    content=ft.Text(f"{label}: {val}", weight=ft.FontWeight.BOLD, size=12),
                    bgcolor=ft.Colors.BLUE_GREY_900,
                    padding=ft.Padding.symmetric(horizontal=10, vertical=6),
                    border_radius=5
                )
            )
        team_totals_row.controls.extend(totals_controls)
        page.update()

    # --- UI Layout Assembly ---

    # Main Tabs Selection Controls — pill style
    def _tab_pill(label, icon, active):
        return ft.Container(
            content=ft.Row(
                spacing=6,
                controls=[
                    ft.Icon(icon, size=16, color=ft.Colors.WHITE if active else ft.Colors.GREY_400),
                    ft.Text(label, size=13, weight=ft.FontWeight.W_600,
                            color=ft.Colors.WHITE if active else ft.Colors.GREY_400)
                ]
            ),
            bgcolor=ft.Colors.AMBER_700 if active else ft.Colors.CARD_BG,
            border_radius=20,
            padding=ft.Padding.symmetric(horizontal=16, vertical=8),
            border=ft.Border.all(1, ft.Colors.AMBER_700 if active else ft.Colors.DIVIDER)
        )

    box_tab_btn = ft.GestureDetector(
        content=_tab_pill("Box Roster", ft.Icons.INBOX, True),
        on_tap=lambda e: switch_tab(0)
    )
    team_tab_btn = ft.GestureDetector(
        content=_tab_pill("Team Builder", ft.Icons.PEOPLE, False),
        on_tap=lambda e: switch_tab(1)
    )
    tabs_row = ft.Row(controls=[box_tab_btn, team_tab_btn], spacing=8)

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
                                                bgcolor=ft.Colors.AMBER_700,
                                                color=ft.Colors.WHITE,
                                                style=ft.ButtonStyle(shape=ft.RoundedRectangleBorder(radius=8))
                                            ),
                                        ),
                                        add_spinner
                                    ]
                                ),
                                suggestion_row
                            ]
                        ),
                        bgcolor=ft.Colors.CARD_BG,
                        border_radius=10,
                        padding=ft.Padding.symmetric(horizontal=12, vertical=10),
                        border=ft.Border.all(1, ft.Colors.DIVIDER)
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
                                    icon_color=ft.Colors.BLUE_300,
                                    on_click=lambda e: handle_export_csv(),
                                    tooltip="Export Box to CSV"
                                )
                            ]
                        ),
                        bgcolor=ft.Colors.CARD_BG,
                        border_radius=10,
                        padding=ft.Padding.symmetric(horizontal=12, vertical=6),
                        border=ft.Border.all(1, ft.Colors.DIVIDER)
                    ),
                    box_grid
                ]
            ),
            # Right panel - Detail Drawer
            detail_panel
        ]
    )

    # VIEW 2: Team Builder Layout
    team_tab_layout = ft.Column(
        expand=True,
        spacing=15,
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
                        icon_color=ft.Colors.RED_400,
                        on_click=lambda e: handle_delete_team(),
                        tooltip="Delete Active Team"
                    )
                ]
            ),
            team_totals_row,
            team_grid,
            ft.Container(
                content=ft.Column(
                    spacing=5,
                    controls=[
                        ft.Text("Offensive Type Coverage Breakdown", weight=ft.FontWeight.BOLD, size=13),
                        ft.Container(
                            content=ft.Text("TODO: Implement Offensive Type Coverage Summary (Backend Integration)", size=11, color=ft.Colors.GREY_500, italic=True),
                            border=ft.Border.all(1, ft.Colors.GREY_800),
                            padding=8,
                            border_radius=5
                        )
                    ]
                )
            )
        ]
    )

    # Wire Tabs Switching
    container_holder = ft.Container(content=box_tab_layout, expand=True)

    def switch_tab(index):
        if index == 0:
            box_tab_btn.content = _tab_pill("Box Roster", ft.Icons.INBOX, True)
            team_tab_btn.content = _tab_pill("Team Builder", ft.Icons.PEOPLE, False)
            container_holder.content = box_tab_layout
        else:
            box_tab_btn.content = _tab_pill("Box Roster", ft.Icons.INBOX, False)
            team_tab_btn.content = _tab_pill("Team Builder", ft.Icons.PEOPLE, True)
            container_holder.content = team_tab_layout
        page.update()

    # -----------------------------------------------------------------------
    # SETTINGS / DATA MANAGEMENT MODAL
    # Centralised place for all manual DB sync actions.
    # -----------------------------------------------------------------------

    # Spinner refs used by Settings modal rows
    _spinner_megas = ft.ProgressRing(visible=False, width=14, height=14, stroke_width=2)
    _spinner_items = ft.ProgressRing(visible=False, width=14, height=14, stroke_width=2)

    # Status text refs updated after each sync
    _status_megas = ft.Text("", size=11, color=ft.Colors.GREY_400)
    _status_items = ft.Text("", size=11, color=ft.Colors.GREY_400)

    def _count_text(label: str, count: int, unit: str) -> str:
        return f"{count:,} {unit}" if count > 0 else "Not yet synced"

    def _refresh_settings_status():
        with get_session() as session:
            mega_repo = MegaEvolutionRepository(session)
            item_repo = ItemRepository(session)
            mega_count = len(mega_repo.list_all())
            item_count = item_repo.count()
        _status_megas.value = _count_text("Megas", mega_count, "forms cached")
        _status_items.value = _count_text("Items", item_count, "items catalogued")
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

    def _make_settings_row(icon, title: str, status_ref, spinner_ref, on_sync) -> ft.Container:
        return ft.Container(
            content=ft.Row(
                alignment=ft.MainAxisAlignment.SPACE_BETWEEN,
                controls=[
                    ft.Row(spacing=10, controls=[
                        ft.Icon(icon, size=18, color=ft.Colors.AMBER_400),
                        ft.Column(spacing=2, controls=[
                            ft.Text(title, size=13, weight=ft.FontWeight.W_600),
                            status_ref,
                        ])
                    ]),
                    ft.Row(spacing=6, controls=[
                        spinner_ref,
                        ft.Container(
                            content=ft.Row(spacing=4, controls=[
                                ft.Icon(ft.Icons.SYNC, size=13, color=ft.Colors.WHITE),
                                ft.Text("Sync", size=11, weight=ft.FontWeight.W_600, color=ft.Colors.WHITE),
                            ]),
                            bgcolor=ft.Colors.AMBER_700,
                            border_radius=6,
                            padding=ft.Padding.symmetric(horizontal=10, vertical=6),
                            on_click=on_sync,
                        )
                    ])
                ]
            ),
            bgcolor=ft.Colors.CARD_BG,
            border_radius=8,
            padding=ft.Padding.symmetric(horizontal=14, vertical=12),
            border=ft.Border.all(1, ft.Colors.DIVIDER),
        )

    settings_modal = ft.AlertDialog(
        title=ft.Row(spacing=10, controls=[
            ft.Icon(ft.Icons.SETTINGS, color=ft.Colors.AMBER_400),
            ft.Text("Data & Synchronization", weight=ft.FontWeight.BOLD, size=16),
        ]),
        content=ft.Container(
            width=460,
            content=ft.Column(
                spacing=10,
                tight=True,
                controls=[
                    ft.Text(
                        "Manage the local SQLite catalog. Sync pulls the latest data from PokéAPI & Pokémon Showdown.",
                        size=12, color=ft.Colors.GREY_400
                    ),
                    ft.Divider(height=1, color=ft.Colors.DIVIDER),
                    _make_settings_row(
                        ft.Icons.FLASH_ON, "Mega Evolutions",
                        _status_megas, _spinner_megas, _handle_sync_megas
                    ),
                    _make_settings_row(
                        ft.Icons.DIAMOND, "Held Items Catalog",
                        _status_items, _spinner_items, _handle_sync_items
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

    settings_btn = ft.IconButton(
        icon=ft.Icons.SETTINGS,
        icon_color=ft.Colors.GREY_400,
        tooltip="Data & Synchronization Settings",
        on_click=_open_settings,
    )

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

        source = state["champions_items"] if legal_only else state["items_catalog"]
        if cat_filter and cat_filter != "all":
            source = [i for i in source if (i.category or "").replace("-", " ") == cat_filter.replace("-", " ")]
        if query:
            source = [i for i in source if query in i.display_name.lower() or query in (i.short_effect or "").lower()]

        if not source:
            _item_list_col.controls.append(
                ft.Container(
                    content=ft.Text("No items found.", size=12, color=ft.Colors.GREY_500, italic=True),
                    alignment=ft.Alignment.CENTER, padding=ft.Padding.all(20)
                )
            )
        else:
            for item in source[:80]:  # cap for performance
                is_legal = item.is_champions_legal
                badge_col = ft.Colors.GREEN_400 if is_legal else ft.Colors.AMBER_400
                badge_txt = "Champions Legal" if is_legal else "Banned in Champions"
                badge_icon = ft.Icons.CHECK_CIRCLE if is_legal else ft.Icons.WARNING_ROUNDED

                _item_list_col.controls.append(
                    ft.Container(
                        content=ft.Row(
                            spacing=10,
                            controls=[
                                ft.Image(src=item.sprite_url, width=32, height=32, fit=ft.BoxFit.CONTAIN)
                                if item.sprite_url else
                                ft.Icon(ft.Icons.DIAMOND, size=28, color=ft.Colors.AMBER_400),
                                ft.Column(spacing=2, expand=True, controls=[
                                    ft.Text(item.display_name, size=13, weight=ft.FontWeight.W_600),
                                    ft.Text(item.short_effect or "", size=11, color=ft.Colors.GREY_400,
                                            overflow=ft.TextOverflow.ELLIPSIS, max_lines=2),
                                    ft.Row(spacing=4, controls=[
                                        ft.Icon(badge_icon, size=11, color=badge_col),
                                        ft.Text(badge_txt, size=10, color=badge_col),
                                    ])
                                ]),
                            ]
                        ),
                        bgcolor=ft.Colors.CARD_BG,
                        border_radius=8,
                        padding=ft.Padding.symmetric(horizontal=10, vertical=8),
                        border=ft.Border.all(1, ft.Colors.DIVIDER),
                        on_click=lambda e, it=item: _handle_item_selected(it),
                        ink=True,
                    )
                )
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
        _, team_repo, _, session = get_repositories()
        try:
            members = team_repo.list_members(state["active_team_id"])
            matching = next((m for m in members if m.slot_position == slot_position), None)
            if matching:
                updated = TeamMember(
                    team_member_id=matching.team_member_id,
                    box_entry_id=matching.box_entry_id,
                    slot_position=slot_position,
                    selected_form=matching.selected_form or "base",
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
            ft.Icon(ft.Icons.DIAMOND, color=ft.Colors.AMBER_400),
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
                    ft.Divider(height=1, color=ft.Colors.DIVIDER),
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

    # App header bar
    header = ft.Container(
        content=ft.Row(
            alignment=ft.MainAxisAlignment.SPACE_BETWEEN,
            controls=[
                ft.Row(
                    spacing=12,
                    controls=[
                        ft.Container(
                            content=ft.Icon(ft.Icons.CATCHING_POKEMON, color=ft.Colors.AMBER_400, size=28),
                            bgcolor="#1e293b",
                            border_radius=10,
                            padding=ft.Padding.all(8)
                        ),
                        ft.Column(
                            spacing=0,
                            controls=[
                                ft.Text(APP_NAME, size=20, weight=ft.FontWeight.BOLD,
                                        color=ft.Colors.AMBER_400),
                                ft.Text("Box & Team Planner", size=11,
                                        color=ft.Colors.GREY_400)
                            ]
                        )
                    ]
                ),
                ft.Row(spacing=10, controls=[tabs_row, settings_btn])
            ]
        ),
        bgcolor=ft.Colors.CARD_BG,
        padding=ft.Padding.symmetric(horizontal=20, vertical=12),
        border_radius=12,
        border=ft.Border.all(1, ft.Colors.DIVIDER),
        margin=ft.Margin.only(bottom=14)
    )

    page.add(header, container_holder)

    # --- Initial State Load ---
    load_champions_catalog()
    load_items_to_state()
    # Populate item picker category dropdown after items are loaded
    if _item_category_filter.current:
        _item_category_filter.current.options = _get_category_options()
    refresh_box()
    refresh_teams()


if __name__ == "__main__":
    ft.app(target=main, view=ft.AppView.WEB_BROWSER, port=8550)

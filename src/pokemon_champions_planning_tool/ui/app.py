"""Flet GUI application for Pokemon box and team management."""

import threading
import flet as ft
from uuid import UUID

# Bypass Flet's buggy deprecation wrapper on colors
class ColorsBypass:
    WHITE = "white"
    RED_ACCENT = "redaccent"
    GREEN_ACCENT_700 = "#388e3c"
    GREY_400 = "#bdbdbd"
    YELLOW = "yellow"
    GREY_600 = "#757575"
    AMBER_400 = "#ffca28"
    AMBER_700 = "#ffa000"
    BLUE_GREY_900 = "#263238"
    BLUE_GREY_950 = "#1a2327"
    SURFACE_VARIANT = "#37474f"
    GREY_500 = "#9e9e9e"
    RED_400 = "#ef5350"
    ORANGE_400 = "#ffa726"
    YELLOW_400 = "#ffee58"
    BLUE_400 = "#42a5f5"
    GREEN_400 = "#66bb6a"
    PINK_400 = "#ec407a"
    GREY_800 = "#424242"
    RED_700 = "#d32f2f"
    BLUE_300 = "#64b5f6"

ft.Colors = ColorsBypass

from ..config import APP_NAME
from ..domain.entities.box_entry import BoxEntry
from ..domain.entities.team import Team
from ..domain.entities.team_member import TeamMember
from ..domain.entities.pokemon_move import PokemonMove
from ..infrastructure.database.database import get_session
from ..infrastructure.database.repositories import BoxRepository, TeamRepository
from ..services.pokemon_import_service import add_pokemon_to_box
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


def main(page: ft.Page):
    page.title = APP_NAME
    page.theme_mode = ft.ThemeMode.DARK
    page.padding = 20
    page.window_width = 1280
    page.window_height = 800
    page.spacing = 15

    # --- Application State ---
    state = {
        "box_entries": [],
        "teams": [],
        "selected_pokemon_id": None,  # UUID of BoxEntry
        "active_team_id": None,       # UUID of Team
        "search_query": "",
        "sort_by": "Name (Asc)",
        "all_stats_visible": False,
        "assigning_slot_position": None,  # Slot number when choosing from box
    }

    # --- Database Helpers ---
    def get_repositories():
        session = get_session().__enter__()
        return BoxRepository(session), TeamRepository(session), session

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
    search_input = ft.TextField(
        label="Add Pokemon by Name",
        hint_text="e.g. Pikachu, Charizard, Mega Lucario",
        expand=True,
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
    detail_container = ft.Column(visible=False, spacing=10, expand=True)

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
        box_repo, team_repo, session = get_repositories()
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
        box_repo, _, session = get_repositories()
        try:
            state["box_entries"] = box_repo.list_entries()
            render_box_grid()
            render_detail_drawer()
        finally:
            session.close()

    def refresh_teams():
        _, team_repo, session = get_repositories()
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
    def handle_add_pokemon():
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
        render_box_grid()
        render_detail_drawer()

    def handle_toggle_favorite(box_entry: BoxEntry, fav_val: bool):
        box_repo, _, session = get_repositories()
        try:
            box_repo.update_metadata(box_entry.pokemon.canonical_id, is_favorite=fav_val)
            # Sync CSV
            export_box_entries_to_csv(box_repo.list_entries())
            refresh_box()
            show_toast(f"Favorite status updated for {box_entry.pokemon.display_name}")
        finally:
            session.close()

    def handle_delete_pokemon(box_entry_id: UUID):
        box_repo, team_repo, session = get_repositories()
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
        box_repo, _, session = get_repositories()
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
        box_repo, _, session = get_repositories()
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
        box_repo, team_repo, session = get_repositories()
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
        box_repo, _, session = get_repositories()
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
        
        box_repo, team_repo, session = get_repositories()
        try:
            box_entry = box_repo.load_entry(str(box_entry_id))
            if box_entry:
                member = TeamMember(
                    box_entry_id=box_entry_id,
                    slot_position=state["assigning_slot_position"],
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
        _, team_repo, session = get_repositories()
        try:
            team_repo.delete_member(state["active_team_id"], slot_position)
            show_toast(f"Cleared slot {slot_position}")
            render_team_builder()
        finally:
            session.close()

    def handle_update_member_field(slot_position: int, ability: str, item: str, moves_str: str, notes: str):
        if state["active_team_id"] is None:
            return
        _, team_repo, session = get_repositories()
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
                    item=item.strip() or None,
                    moveset=moves,
                    ability=ability.strip() or None,
                    notes=notes.strip()
                )
                team_repo.upsert_member(state["active_team_id"], updated_member)
                show_toast("Team slot updated")
                # Reload team totals without full refresh
                update_team_totals()
        finally:
            session.close()

    # --- Renderers ---
    def render_box_grid():
        box_grid.controls.clear()
        
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

        for entry in filtered:
            # Card styling
            types_row = ft.Row(
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
                    margin=ft.Margin.only(top=6),
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
                                    width=80,
                                    height=80,
                                    fit=ft.BoxFit.CONTAIN,
                                ) if entry.pokemon.sprite_url else ft.Icon(ft.Icons.IMAGE, size=60),
                                alignment=ft.Alignment.CENTER
                            ),
                            ft.Column(
                                horizontal_alignment=ft.CrossAxisAlignment.CENTER,
                                controls=[
                                    ft.Text(entry.pokemon.display_name, size=15, weight=ft.FontWeight.BOLD, overflow=ft.TextOverflow.ELLIPSIS),
                                    ft.Text(f"Form: {entry.pokemon.form_name}", size=11, color=ft.Colors.GREY_400),
                                    types_row,
                                    stats_block
                                ]
                            )
                        ]
                    ),
                    padding=10,
                    on_click=make_select_handler()
                ),
                bgcolor=ft.Colors.BLUE_GREY_900 if state["selected_pokemon_id"] == entry.box_entry_id else ft.Colors.SURFACE_VARIANT
            )
            box_grid.controls.append(card)
        
        page.update()

    def close_detail_container(e=None):
        detail_container.visible = False
        page.update()

    def render_detail_drawer():
        detail_container.controls.clear()
        
        if state["selected_pokemon_id"] is None:
            detail_container.visible = False
            page.update()
            return
        
        # Load the selected Pokemon
        box_repo, _, session = get_repositories()
        try:
            entry = box_repo.load_entry(str(state["selected_pokemon_id"]))
        finally:
            session.close()

        if entry is None:
            detail_container.visible = False
            page.update()
            return

        detail_container.visible = True
        
        # Header info
        detail_container.controls.append(
            ft.Row(
                alignment=ft.MainAxisAlignment.SPACE_BETWEEN,
                controls=[
                    ft.Text("POKÉMON DETAILS", weight=ft.FontWeight.BOLD, size=16, color=ft.Colors.AMBER_400),
                    ft.IconButton(
                        icon=ft.Icons.CLOSE,
                        on_click=lambda e: close_detail_container()
                    )
                ]
            )
        )

        detail_container.controls.append(
            ft.Row(
                alignment=ft.MainAxisAlignment.CENTER,
                controls=[
                    ft.Image(src=entry.pokemon.sprite_url, width=120, height=120, fit=ft.BoxFit.CONTAIN) if entry.pokemon.sprite_url else ft.Icon(ft.Icons.IMAGE, size=80)
                ]
            )
        )

        detail_container.controls.append(
            ft.Column(
                horizontal_alignment=ft.CrossAxisAlignment.CENTER,
                controls=[
                    ft.Text(entry.pokemon.display_name, size=20, weight=ft.FontWeight.BOLD),
                    ft.Text(f"Canonical ID: {entry.pokemon.canonical_id}", size=11, color=ft.Colors.GREY_500),
                    ft.Text(f"Dex Number: #{entry.pokemon.dex_number or '???'}", size=12, color=ft.Colors.GREY_400),
                ]
            )
        )

        # Base Stats Bars
        stats_list = [
            ("HP", entry.pokemon.stats.hp, ft.Colors.RED_400),
            ("Atk", entry.pokemon.stats.attack, ft.Colors.ORANGE_400),
            ("Def", entry.pokemon.stats.defense, ft.Colors.YELLOW_400),
            ("SpA", entry.pokemon.stats.special_attack, ft.Colors.BLUE_400),
            ("SpD", entry.pokemon.stats.special_defense, ft.Colors.GREEN_400),
            ("Spe", entry.pokemon.stats.speed, ft.Colors.PINK_400)
        ]
        
        stats_column = ft.Column(spacing=6)
        for label, val, color in stats_list:
            norm_val = min(val / 255.0, 1.0)
            stats_column.controls.append(
                ft.Column(
                    spacing=2,
                    controls=[
                        ft.Row(
                            alignment=ft.MainAxisAlignment.SPACE_BETWEEN,
                            controls=[
                                ft.Text(label, size=12, weight=ft.FontWeight.BOLD),
                                ft.Text(str(val), size=12, weight=ft.FontWeight.BOLD)
                            ]
                        ),
                        ft.ProgressBar(value=norm_val, color=color, bgcolor=ft.Colors.BLUE_GREY_900)
                    ]
                )
            )
        detail_container.controls.append(stats_column)

        # Notes and Nicknames
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
        detail_container.controls.append(ft.Column(spacing=2, controls=[notes_field, notes_btn]))

        # Tags Management
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
        detail_container.controls.append(ft.Column(spacing=2, controls=[tags_field, tags_btn]))

        # Type effectiveness multiplier placeholder
        detail_container.controls.append(
            ft.Container(
                content=ft.Column(
                    spacing=5,
                    controls=[
                        ft.Text("Defensive Weaknesses", weight=ft.FontWeight.BOLD, size=13),
                        ft.Container(
                            content=ft.Text("TODO: Implement Type Effectiveness Matrix (Backend Integration)", size=11, color=ft.Colors.GREY_500, italic=True),
                            border=ft.Border.all(1, ft.Colors.GREY_800),
                            padding=8,
                            border_radius=5
                        )
                    ]
                ),
                margin=ft.Margin.only(top=10)
            )
        )

        # Delete Button
        detail_container.controls.append(
            ft.ElevatedButton(
                "Delete from Box",
                icon=ft.Icons.DELETE,
                bgcolor=ft.Colors.RED_700,
                color=ft.Colors.WHITE,
                on_click=lambda e, e_id=entry.box_entry_id: handle_delete_pokemon(e_id)
            )
        )

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

        box_repo, team_repo, session = get_repositories()
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
                # Load corresponding box entry
                box_repo, _, session = get_repositories()
                try:
                    box_entry = box_repo.load_entry(str(matching_member.box_entry_id))
                finally:
                    session.close()

                if box_entry is None:
                    continue
                
                pokemon = box_entry.pokemon

                # Form input elements for member attributes
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
                
                item_field = ft.TextField(
                    label="Held Item",
                    value=matching_member.item or "",
                    text_size=12
                )
                
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

                def make_update_handler(s_pos=slot, ab_dr=ability_drop, it_fl=item_field, mv_fl=moves_field, nt_fl=notes_field):
                    return lambda e: handle_update_member_field(s_pos, ab_dr.value, it_fl.value, mv_fl.value, nt_fl.value)

                def make_remove_handler(s_pos=slot):
                    return lambda e: handle_remove_member(s_pos)

                slot_card = ft.Card(
                    content=ft.Container(
                        content=ft.Column(
                            spacing=6,
                            scroll=ft.ScrollMode.AUTO,
                            controls=[
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
                                        ft.Image(src=pokemon.sprite_url, width=50, height=50, fit=ft.BoxFit.CONTAIN) if pokemon.sprite_url else ft.Icon(ft.Icons.IMAGE),
                                        ft.Column(
                                            spacing=2,
                                            controls=[
                                                ft.Text(pokemon.display_name, size=14, weight=ft.FontWeight.BOLD),
                                                ft.Text(f"BST: {pokemon.total}", size=11, color=ft.Colors.GREY_400)
                                            ]
                                        )
                                    ]
                                ),
                                ability_drop,
                                item_field,
                                moves_field,
                                notes_field,
                                ft.ElevatedButton("Save Changes", icon=ft.Icons.SAVE, on_click=make_update_handler(), height=30)
                            ]
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

        box_repo, team_repo, session = get_repositories()
        try:
            members = team_repo.list_members(state["active_team_id"])
            total_hp = total_attack = total_defense = total_spa = total_spd = total_speed = 0
            
            for m in members:
                b_entry = box_repo.load_entry(str(m.box_entry_id))
                if b_entry:
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

    # Main Tabs Selection Controls
    box_tab_btn = ft.ElevatedButton(
        "Box Roster",
        icon=ft.Icons.INBOX,
        on_click=lambda e: switch_tab(0),
        bgcolor=ft.Colors.AMBER_700,
        color=ft.Colors.WHITE
    )
    team_tab_btn = ft.ElevatedButton(
        "Team Builder",
        icon=ft.Icons.PEOPLE,
        on_click=lambda e: switch_tab(1),
        bgcolor=ft.Colors.BLUE_GREY_900,
        color=ft.Colors.WHITE
    )
    tabs_row = ft.Row(
        controls=[box_tab_btn, team_tab_btn],
        spacing=10
    )

    # VIEW 1: Box Roster Layout
    box_tab_layout = ft.Row(
        expand=True,
        spacing=15,
        controls=[
            # Left panel - search, filters, list grid
            ft.Column(
                expand=2,
                spacing=12,
                controls=[
                    ft.Row(
                        controls=[
                            search_input,
                            add_button,
                            add_spinner
                        ]
                    ),
                    ft.Divider(height=10),
                    ft.Row(
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
                    box_grid
                ]
            ),
            # Right panel - Detail Drawer
            ft.Container(
                content=detail_container,
                width=300,
                bgcolor=ft.Colors.BLUE_GREY_950,
                padding=15,
                border_radius=10,
                border=ft.Border.all(1, ft.Colors.GREY_800),
            )
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
    tab_views = [box_tab_layout, team_tab_layout]
    container_holder = ft.Container(content=box_tab_layout, expand=True)

    def switch_tab(index):
        if index == 0:
            box_tab_btn.bgcolor = ft.Colors.AMBER_700
            team_tab_btn.bgcolor = ft.Colors.BLUE_GREY_900
            container_holder.content = box_tab_layout
        else:
            box_tab_btn.bgcolor = ft.Colors.BLUE_GREY_900
            team_tab_btn.bgcolor = ft.Colors.AMBER_700
            container_holder.content = team_tab_layout
        page.update()

    page.add(
        ft.Row(
            controls=[
                ft.Icon(ft.Icons.SETTINGS_ACCESSIBILITY, color=ft.Colors.AMBER_400, size=30),
                ft.Text(APP_NAME, size=24, weight=ft.FontWeight.BOLD, color=ft.Colors.AMBER_400)
            ],
            alignment=ft.MainAxisAlignment.START
        ),
        tabs_row,
        container_holder
    )

    # --- Initial State Load ---
    refresh_box()
    refresh_teams()


if __name__ == "__main__":
    ft.app(target=main, view=ft.AppView.WEB_BROWSER, port=8550)

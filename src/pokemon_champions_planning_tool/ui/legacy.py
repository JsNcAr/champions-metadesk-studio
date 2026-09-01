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
    ImportReadinessReport,
    ParsedTeamResult,
    commit_team_import,
    export_team_to_showdown_text,
    import_from_pokepast_url,
    parse_showdown_text,
    publish_to_pokepast,
    resolve_import_readiness,
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

    refresh_box_state: Callable[[], None]
    set_active_team: Callable[[Any], None]
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

    def _show_dialog(dialog: ft.AlertDialog):
        """Open a dialog through the 0.85 dialog stack.

        These dialogs are long-lived instances. The stack entry is only removed when
        the client reports the dismiss animation finished, so re-opening immediately
        after a close can still find the instance on the stack; in that case flip
        it back open instead of raising.
        """
        try:
            page.show_dialog(dialog)
        except RuntimeError:
            dialog.open = True
            page.update()

    # --- Data Refresher Functions ---
    def refresh_box_state():
        """Reload the cached box entries the assign modal reads. The box view itself
        has moved to ui/views/box."""
        with get_session() as session:
            state["box_entries"] = BoxRepository(session).list_entries()

    def set_active_team(team_id):
        """The new team builder tells us which team its dialogs should act on."""
        state["active_team_id"] = team_id

    # --- UI Layout Assembly ---


    # Main Tabs Selection Controls — pill style


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
                            services.copy_to_clipboard(_export_text_field.value or ""),
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

        _show_dialog(_export_modal)
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
        if parsed is None or not parsed.is_valid:
            return
        try:
            with get_session() as session:
                result = commit_team_import(session, parsed, use_planned=use_planned)
            state["active_team_id"] = result.team_id
            show_toast(f"Team '{result.team_name}' imported successfully!")
            _import_modal.open = False
            services.teams_changed(result.team_id)
        except Exception as err:
            show_toast(f"Import failed: {err}", is_error=True)

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
            _show_dialog(readiness_dialog)
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
        _show_dialog(readiness_dialog)
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

    def _open_import_modal(e=None):
        _import_input.value = ""
        _import_preview_row.controls.clear()
        _import_warning_col.controls.clear()
        _import_warning_col.visible = False
        _import_status.value = ""
        _last_parsed[0] = None
        _last_readiness[0] = None
        _show_dialog(_import_modal)
        page.update()

    def _import_tournament_team(showdown_text: str, team_title: str):
        _open_import_modal()
        _import_input.value = showdown_text
        _on_import_input_change()
        show_toast(f"Loaded '{team_title}' roster for import preview!")

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
    refresh_box_state()


    return LegacyViews(
        refresh_box_state=refresh_box_state,
        set_active_team=set_active_team,
        reload_catalogs=load_champions_catalog,
        reload_items=load_items_to_state,
        import_showdown_text=_import_tournament_team,
        open_import_modal=lambda: _open_import_modal(),
        open_export_modal=lambda: _open_export_modal(),
    )

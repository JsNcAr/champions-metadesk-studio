"""Meta explorer: service rows, store paging, and the view serialised headlessly."""

import contextlib
import shutil
import tempfile
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path

import flet as ft
from sqlmodel import Session, SQLModel, create_engine

from _ui_stubs import StubPage, serialise
from pokemon_champions_planning_tool.infrastructure.database.models import (
    ChampionsSpeciesRecord,
    TournamentRecord,
    TournamentTeamMemberRecord,
    TournamentTeamRecord,
)
from pokemon_champions_planning_tool.services.tournament_service import TournamentService
from pokemon_champions_planning_tool.ui import events
from pokemon_champions_planning_tool.ui.context import AppContext
from pokemon_champions_planning_tool.ui.views.meta import MetaFilters, MetaStore, MetaView
from pokemon_champions_planning_tool.ui.views.meta.store import PAGE_SIZE


class _TempDb:
    def __init__(self):
        self.dir = tempfile.mkdtemp()
        self.engine = create_engine(f"sqlite:///{Path(self.dir) / 'meta.db'}", connect_args={"check_same_thread": False})
        SQLModel.metadata.create_all(self.engine)

    @contextlib.contextmanager
    def session(self):
        with Session(self.engine) as s:
            yield s

    def close(self):
        self.engine.dispose()
        shutil.rmtree(self.dir)


def _seed(db: _TempDb, *, teams_per_event: int = 25, events: int = 2, with_catalog: bool = True):
    now = datetime(2026, 8, 30, tzinfo=timezone.utc)
    with db.session() as s:
        if with_catalog:
            for i, name in enumerate(["incineroar", "rillaboom", "urshifu-rapid-strike"], start=1):
                s.add(ChampionsSpeciesRecord(entry_number=i, species_name=name, display_name=name.title()))
        for e in range(events):
            t_id = f"t{e}"
            s.add(TournamentRecord(tournament_id=t_id, name=f"Event {e}", event_date=now - timedelta(days=e),
                                   format_regulation="Regulation M-B" if e == 0 else "Regulation M-A",
                                   game_platform="Pokémon Champions", total_players=64, standings_synced=True, updated_at=now,
                                   organizer="Play! Pokémon Premier Events" if e == 1 else "Limitless Community",
                                   event_tier="international" if e == 1 else "community"))
            s.commit()
            for p in range(1, teams_per_event + 1):
                team = TournamentTeamRecord(tournament_id=t_id, player_name=f"player-{e}-{p:02d}", placement=p,
                                            standing_label=f"Place #{p}", showdown_text="Incineroar @ Safety Goggles\nAbility: Intimidate\n- Fake Out\n\nRillaboom\n- Grassy Glide\n",
                                            pokepast_url=f"https://pokepast.es/{e}{p:02d}")
                s.add(team)
                s.commit()
                species = ["incineroar", "rillaboom"] + (["pikachu"] if p == 3 else [])
                for slot, name in enumerate(species, start=1):
                    s.add(TournamentTeamMemberRecord(tournament_team_id=team.tournament_team_id, slot_position=slot, canonical_id=name, species_name=name.title()))
            s.commit()


class TestSearchTeamRows(unittest.TestCase):
    def setUp(self):
        self.db = _TempDb()
        _seed(self.db)

    def tearDown(self):
        self.db.close()

    def test_rows_carry_event_context_roster_and_legality(self):
        with self.db.session() as s:
            svc = TournamentService(s)
            rows = svc.search_team_rows(placement_filter=8, limit=5)
            total = svc.count_teams(placement_filter=8)
        self.assertEqual(total, 16, "top-8 across two events")
        self.assertEqual(len(rows), 5)
        first = rows[0]
        self.assertEqual(first.tournament_name, "Event 0", "newest event first")
        self.assertEqual(first.placement, 1)
        self.assertEqual([m.species_name for m in first.members], ["Incineroar", "Rillaboom"])
        self.assertTrue(first.is_legal)
        third = next(r for r in rows if r.placement == 3)
        self.assertEqual(third.illegal_species, ["Pikachu"])
        self.assertFalse(third.is_legal)
        self.assertTrue(all(m.sprite_url for r in rows for m in r.members))

    def test_empty_catalogue_never_flags_illegal(self):
        db = _TempDb()
        _seed(db, teams_per_event=3, events=1, with_catalog=False)
        try:
            with db.session() as s:
                rows = TournamentService(s).search_team_rows(limit=3, placement_filter=None)
            self.assertTrue(all(not r.legality_known and r.illegal_species == [] for r in rows))
        finally:
            db.close()

    def test_regulations_and_summary(self):
        with self.db.session() as s:
            svc = TournamentService(s)
            self.assertEqual(set(svc.list_regulations()), {"Regulation M-A", "Regulation M-B"})
            summary = svc.meta_summary()
        self.assertEqual((summary.team_count, summary.event_count), (50, 2))
        self.assertIsNotNone(summary.synced_at)


class TestMetaStore(unittest.TestCase):
    def setUp(self):
        self.db = _TempDb()
        _seed(self.db)
        self.store = MetaStore(self.db.session)

    def tearDown(self):
        self.db.close()

    def test_paging_appends_without_overlap_and_exhausts(self):
        self.store.set_filters(MetaFilters(placement="all"))
        self.store.load_first_page()
        self.assertEqual((self.store.loaded, self.store.total, self.store.exhausted), (PAGE_SIZE, 50, False))
        self.store.load_more()
        self.store.load_more()
        self.assertEqual(self.store.loaded, 50)
        self.assertTrue(self.store.exhausted)
        self.assertEqual(len({r.team_id for r in self.store.rows}), 50, "no duplicates across pages")
        self.assertEqual(self.store.load_more(), [], "no-op once exhausted")

    def test_default_filters_show_top_8(self):
        self.store.load_first_page()
        self.assertEqual(self.store.total, 16)
        self.assertTrue(all(r.placement <= 8 for r in self.store.rows))

    def test_needs_load_tracks_filters_and_invalidation(self):
        self.assertTrue(self.store.needs_load)
        self.store.load_first_page()
        self.assertFalse(self.store.needs_load)
        self.store.set_filters(MetaFilters(query="player-0-01"))
        self.assertTrue(self.store.needs_load)
        self.store.load_first_page()
        self.assertEqual(self.store.total, 1)
        self.store.invalidate()
        self.assertTrue(self.store.needs_load)

    def test_active_filters_and_removal(self):
        f = MetaFilters(query="x", placement="all", regulation="Regulation M-A")
        self.assertEqual([field for field, _ in f.active()], ["query", "placement", "regulation"])
        self.assertEqual(f.without("placement").placement, "8")
        self.assertEqual(MetaFilters().active(), [])


class TestMetaView(unittest.TestCase):
    def setUp(self):
        self.db = _TempDb()
        _seed(self.db)
        self.page = StubPage()
        self.ctx = AppContext(self.page)
        self.view = MetaView(self.ctx, MetaStore(self.db.session))

    def tearDown(self):
        self.db.close()

    def test_loads_groups_rows_by_event_and_serialises(self):
        self.view.ensure_loaded()
        kinds = [type(c).__name__ for c in self.view._list.controls]
        self.assertEqual(kinds, ["EventGroup", "EventGroup"], "two events in the first page")
        self.assertEqual(sum(len(g.rows) for g in self.view._groups.values()), 16)
        self.assertEqual(self.view.header._count.content.value, "50")
        self.assertGreater(serialise(self.view), 200)
        self.assertFalse(self.view._more_button.visible, "16 rows fit in one page")

    def test_import_emits_request_with_showdown_text(self):
        self.view.ensure_loaded()
        got = []
        self.ctx.bus.on(events.IMPORT_REQUESTED, got.append)
        row = next(iter(self.view._groups.values())).rows[0]
        row._on_import(row.row)
        self.assertEqual(len(got), 1)
        text, title = got[0]
        self.assertIn("Incineroar", text)
        self.assertIn("Event 0", title)

    def test_row_expands_to_parsed_sheet(self):
        self.view.ensure_loaded()
        row = next(iter(self.view._groups.values())).rows[0]
        row.toggle()
        self.assertTrue(row._expanded)
        self.assertEqual(len(row._body.controls), 2)
        serialise(row)

    def test_meta_synced_shows_banner_instead_of_reshuffling(self):
        self.view.ensure_loaded()
        first_ids = [r.row.team_id for g in self.view._groups.values() for r in g.rows]
        self.ctx.bus.emit(events.META_SYNCED, {"limitless": {"added": 12}, "victory_road": {"added": 0}})
        self.assertTrue(self.view.banner.visible)
        self.assertIn("12 new teams", self.view.banner._text.value)
        self.assertEqual([r.row.team_id for g in self.view._groups.values() for r in g.rows], first_ids)
        self.assertTrue(self.view.store.needs_load)

    def test_empty_database_shows_first_run_state(self):
        db = _TempDb()
        try:
            view = MetaView(self.ctx, MetaStore(db.session))
            view.ensure_loaded()
            self.assertEqual(type(view._list.controls[0]).__name__, "EmptyState")
            self.assertIn("No tournament data yet", view._list.controls[0]._title.value)
        finally:
            db.close()




class TestEventTierFilters(unittest.TestCase):
    def setUp(self):
        self.db = _TempDb()
        _seed(self.db, teams_per_event=10, events=2)

    def tearDown(self):
        self.db.close()

    def test_store_filters_by_source_and_tier(self):
        from pokemon_champions_planning_tool.ui.views.meta.store import MetaFilters, MetaStore

        store = MetaStore(self.db.session)
        store.set_filters(MetaFilters(placement="all", source="official"))
        rows = store.load_first_page()
        self.assertEqual({r.tournament_id for r in rows}, {"t1"})
        self.assertEqual(store.total, 10)
        self.assertTrue(all(r.event_tier == "international" for r in rows))
        store.set_filters(MetaFilters(placement="all", source="community"))
        self.assertEqual({r.tournament_id for r in store.load_first_page()}, {"t0"})
        store.set_filters(MetaFilters(placement="all", source="official", tier="worlds"))
        self.assertEqual(store.load_first_page(), [])
        self.assertEqual(MetaFilters(source="official", tier="regional").active(), [("tier", "Official · Regionals")])
        self.assertEqual(MetaFilters(source="community").active(), [("source", "Community")])
        self.assertEqual(MetaFilters(source="official", tier="regional").without("source"), MetaFilters())

    def test_view_shows_tier_dropdown_only_for_official(self):
        from pokemon_champions_planning_tool.ui.views.meta.view import MetaView

        page = StubPage()
        ctx = AppContext(page)
        ctx.run_in_background = lambda work, on_done=None, on_error=None, **kw: on_done(work()) if on_done else work()
        view = MetaView(ctx, store=MetaStore(self.db.session))
        view.ensure_loaded()
        self.assertFalse(view._tier.visible)
        view._apply_source("official")
        self.assertTrue(view._tier.visible)
        self.assertEqual({r.tournament_id for r in view.store.rows}, {"t1"})
        view._apply(tier="worlds")
        self.assertEqual(view.store.rows, [])
        view._apply_source("All")
        self.assertFalse(view._tier.visible)
        self.assertEqual(view.store.filters.tier, "All")
        serialise(view)




class TestGroupingAndCards(unittest.TestCase):
    def setUp(self):
        self.db = _TempDb()
        _seed(self.db, teams_per_event=25, events=2)
        self.page = StubPage()
        self.ctx = AppContext(self.page)
        self.ctx.run_in_background = lambda work, on_done=None, on_error=None, **kw: on_done(work()) if on_done else work()
        from pokemon_champions_planning_tool.ui.views.meta.row import EventDialog

        self.EventDialog = EventDialog
        self.view = MetaView(self.ctx, MetaStore(self.db.session))
        self.view.ensure_loaded()

    def tearDown(self):
        self.db.close()

    def test_groups_collapse_to_the_winner_until_expanded(self):
        groups = self.view._groups
        self.assertEqual(set(groups), {"t0", "t1"})
        for group in groups.values():
            self.assertTrue(group.collapsed)
            self.assertEqual(len(group._rows_column.controls), 1)
            self.assertEqual(group._rows_column.controls[0].row.placement, 1)
            self.assertEqual(group.header._toggle.content, "Show 7 more")
        self.view._toggle_group("t0")
        self.assertEqual(len(groups["t0"]._rows_column.controls), 8)
        self.assertEqual(groups["t0"].header._toggle.content, "Show less")
        self.assertEqual(len(groups["t1"]._rows_column.controls), 1)
        self.view._toggle_all()
        self.assertFalse(self.view.collapsed)
        self.assertEqual(len(groups["t1"]._rows_column.controls), 8)
        self.assertEqual(self.view._collapse_button.content, "Collapse all")
        self.assertIn("16 teams shown", self.view._order_caption.value)
        serialise(self.view)

    def test_cards_mode_and_event_dialog_list_all_placements(self):
        self.view._set_view_mode("cards")
        self.assertTrue(self.view._grid.visible)
        self.assertFalse(self.view._list.visible)
        self.assertFalse(self.view._collapse_button.visible)
        self.assertEqual(len(self.view._grid.controls), 2)
        card = self.view._cards["t0"]
        self.assertEqual(card.row.placement, 1)
        self.assertIn("2 events shown", self.view._order_caption.value)
        serialise(self.view)
        self.view._open_event("t0")
        dialog = self.page.dialogs[-1]
        self.assertIsInstance(dialog, self.EventDialog)
        self.assertEqual(len(dialog._list.controls), 25, "dialog ignores the Top 8 filter")
        self.assertEqual([r.row.placement for r in dialog._list.controls[:3]], [1, 2, 3])
        serialise(dialog)
        emitted = []
        self.ctx.bus.on(events.IMPORT_REQUESTED, emitted.append)
        dialog._list.controls[1]._on_import(dialog._list.controls[1].row)
        self.assertEqual(len(emitted), 1)
        self.assertNotIn(dialog, self.page.dialogs)


if __name__ == "__main__":
    unittest.main()

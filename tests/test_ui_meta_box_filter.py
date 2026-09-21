"""Filter tournament teams by Pokémon missing from the box (FR-14)."""

import unittest
from datetime import datetime, timezone

from sqlmodel import Session, SQLModel, create_engine

from _ui_stubs import StubPage, serialise
from pokemon_champions_planning_tool.domain.entities.box_entry import BoxEntry
from pokemon_champions_planning_tool.domain.entities.pokemon import Pokemon
from pokemon_champions_planning_tool.domain.entities.pokemon_stats import PokemonStats
from pokemon_champions_planning_tool.infrastructure.database.models import TournamentRecord, TournamentTeamMemberRecord, TournamentTeamRecord
from pokemon_champions_planning_tool.infrastructure.database.repositories import BoxRepository, TournamentRepository
from pokemon_champions_planning_tool.services.tournament_service import TournamentService
from pokemon_champions_planning_tool.ui import events
from pokemon_champions_planning_tool.ui.context import AppContext
from pokemon_champions_planning_tool.ui.views.meta.store import MetaFilters, MetaStore
from pokemon_champions_planning_tool.ui.views.meta.view import MetaView

ROSTERS = {
    "full": ["charizard-mega-y", "incineroar", "rotom-wash"],       # mega -> charizard: all owned
    "one": ["charizard", "incineroar", "rotom-heat"],               # rotom-heat is a different form
    "two": ["garchomp", "kingambit", "incineroar"],
    "short": ["charizard", "incineroar"],                           # a 2-member paste, judged against 2
}


def _mon(cid):
    return Pokemon(canonical_id=cid, display_name=cid.title(), species_name=cid.split("-")[0], types=["normal"], stats=PokemonStats(hp=1, attack=1, defense=1, sp_atk=1, sp_def=1, speed=1))


class _Db(unittest.TestCase):
    def setUp(self):
        self.engine = create_engine("sqlite:///:memory:")
        SQLModel.metadata.create_all(self.engine)
        self.addCleanup(self.engine.dispose)
        self.sf = lambda: Session(self.engine)
        with self.sf() as s:
            s.add(TournamentRecord(tournament_id="t", name="T", event_date=datetime.now(timezone.utc), format_regulation="Regulation M-B", game_platform="Pokémon Champions", standings_synced=True))
            s.commit()
            for i, (name, roster) in enumerate(ROSTERS.items(), start=1):
                team = TournamentTeamRecord(tournament_id="t", player_name=name, placement=i, member_count=len(roster), showdown_text="\n\n".join(f"{c}\n- Protect" for c in roster))
                s.add(team); s.commit()
                for slot, cid in enumerate(roster, start=1):
                    s.add(TournamentTeamMemberRecord(tournament_team_id=team.tournament_team_id, slot_position=slot, canonical_id=cid, species_name=cid, base_canonical_id=cid.replace("-mega-y", "")))
            repo = BoxRepository(s)
            for cid in ("charizard", "incineroar", "rotom-wash"):
                repo.upsert_box_entry(BoxEntry(pokemon=_mon(cid)))
            repo.upsert_box_entry(BoxEntry(pokemon=_mon("garchomp"), is_planned=True))  # planned: does not count
            s.commit()

    def _players(self, **kw):
        with self.sf() as s:
            return sorted(t.player_name for t in TournamentRepository(s).search_teams(**kw))


class TestRepositoryFilter(_Db):
    OWNED = ["charizard", "incineroar", "rotom-wash"]

    def test_max_missing_counts_owned_base_species(self):
        self.assertEqual(self._players(owned_species=self.OWNED, max_missing=0), ["full", "short"])
        self.assertEqual(self._players(owned_species=self.OWNED, max_missing=1), ["full", "one", "short"])
        self.assertEqual(self._players(owned_species=self.OWNED, max_missing=2), ["full", "one", "short", "two"])
        with self.sf() as s:
            ordered = [t.player_name for t in TournamentRepository(s).search_teams(owned_species=self.OWNED, max_missing=2)]
        self.assertEqual(ordered[:2], ["full", "short"], "closest to the box first")
        self.assertEqual(ordered[-1], "two")
        self.assertEqual(self._players(owned_species=[], max_missing=1), [], "empty box matches nothing")
        self.assertEqual(len(self._players(owned_species=self.OWNED)), 4, "no threshold: no filtering")
        with self.sf() as s:
            repo = TournamentRepository(s)
            self.assertEqual(repo.count_teams(owned_species=self.OWNED, max_missing=1), 3, "count agrees with the page")
            self.assertEqual(repo.count_teams(owned_species=self.OWNED, max_missing=1, query="rotom"), 2, "combines with other filters")

    def test_rows_carry_marks(self):
        with self.sf() as s:
            rows = {r.player_name: r for r in TournamentService(s).search_team_rows(owned_species=self.OWNED)}
        self.assertEqual(rows["one"].missing_count, 1)
        self.assertEqual([m.in_box for m in rows["one"].members], [True, True, False])
        self.assertEqual(rows["one"].box_label, "2/3 in box")
        self.assertEqual(rows["full"].box_label, "3/3 in box")
        with self.sf() as s:
            plain = TournamentService(s).search_team_rows()
        self.assertIsNone(plain[0].missing_count)
        self.assertIsNone(plain[0].members[0].in_box)


class TestStoreAndView(_Db):
    def test_store_reads_owned_species_and_filters(self):
        store = MetaStore(self.sf)
        store.set_filters(MetaFilters(placement="all", box="1"))
        rows = store.load_first_page()
        self.assertEqual(store.box_species, frozenset({"charizard", "incineroar", "rotom-wash"}), "planned garchomp excluded")
        self.assertEqual(sorted(r.player_name for r in rows), ["full", "one", "short"])
        self.assertEqual(store.total, 3)
        self.assertEqual(MetaFilters(box="0").active(), [("box", "Box · All in my box")])
        self.assertEqual(MetaFilters(box="1").max_missing, 1)
        self.assertIsNone(MetaFilters().max_missing)
        # standings of an event carry the marks too
        self.assertTrue(all(r.missing_count is not None for r in store.teams_for_event("t")))
        # an empty box marks nothing but still makes the filter reject everything
        with self.sf() as s:
            repo = BoxRepository(s)
            for e in repo.list_entries(include_planned=True):
                repo.delete_by_canonical_id(e.pokemon.canonical_id)
            s.commit()
        store.refresh_box()
        store.set_filters(MetaFilters(placement="all"))
        self.assertTrue(all(r.missing_count is None for r in store.load_first_page()))
        store.set_filters(MetaFilters(placement="all", box="3"))
        self.assertEqual(store.load_first_page(), [])

    def test_view_dropdown_marks_chips_and_empty_states(self):
        page = StubPage()
        ctx = AppContext(page)
        view = MetaView(ctx, MetaStore(self.sf))
        view.ensure_loaded()
        row = next(iter(view._groups.values())).rows[0]
        self.assertEqual(row.row.player_name, "full")
        chip_labels = [c._label.value for c in row._summary.content.controls if hasattr(c, "_label")]
        self.assertIn("3/3 in box", chip_labels)
        view._apply(box="0")
        self.assertEqual(view._box.value, "0")
        self.assertEqual(sorted(r.row.player_name for g in view._groups.values() for r in g.rows), ["full", "short"])
        self.assertEqual([lbl for _f, lbl in view.store.filters.active() if lbl.startswith("Box")], ["Box · All in my box"])
        serialise(view)
        # box emptied -> the filter shows the empty-box state after BOX_CHANGED
        with self.sf() as s:
            repo = BoxRepository(s)
            for e in repo.list_entries(include_planned=True):
                repo.delete_by_canonical_id(e.pokemon.canonical_id)
            s.commit()
        ctx.bus.emit(events.BOX_CHANGED, None)
        self.assertEqual(view.store.box_species, frozenset())
        self.assertTrue(view.store.needs_load, "a hidden view reloads on its next visit")
        view.ensure_loaded()
        state = view._list.controls[0]
        self.assertEqual(type(state).__name__, "EmptyState")
        self.assertEqual(state._title.value, "Your box is empty")
        serialise(view)

    def test_adding_pokemon_updates_meta_view_without_restart(self):
        page = StubPage()
        ctx = AppContext(page)
        view = MetaView(ctx, MetaStore(self.sf))
        view.ensure_loaded()

        # Initially, team "two" has garchomp, kingambit, incineroar.
        # Box has charizard, incineroar, rotom-wash.
        # So "two" has 2 missing (garchomp and kingambit).
        with self.sf() as s:
            team_two_before = next(r for r in TournamentService(s).search_team_rows(owned_species=sorted(view.store.box_species)) if r.player_name == "two")
        self.assertEqual(team_two_before.missing_count, 2)

        # Now simulate adding garchomp into the box
        with self.sf() as s:
            repo = BoxRepository(s)
            repo.upsert_box_entry(BoxEntry(pokemon=_mon("garchomp"), is_planned=False))
            s.commit()

        # Emit BOX_CHANGED (as BoxView._add now does)
        ctx.bus.emit(events.BOX_CHANGED, None)

        # MetaView reloads on next visit / ensure_loaded without restarting app
        view.ensure_loaded()
        self.assertIn("garchomp", view.store.box_species)

        # Team "two" should now have garchomp in box and only 1 missing
        with self.sf() as s:
            team_two_after = next(r for r in TournamentService(s).search_team_rows(owned_species=sorted(view.store.box_species)) if r.player_name == "two")
        self.assertEqual(team_two_after.missing_count, 1)
        self.assertEqual(team_two_after.box_label, "2/3 in box")


if __name__ == "__main__":
    unittest.main()

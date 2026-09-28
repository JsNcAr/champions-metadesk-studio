"""Meta's Top teams tab, serialised headlessly: the tab switch, the ranked list, expanding
a card, and its actions (Import, Save as rival)."""

import shutil
import sys
import tempfile
import unittest
from pathlib import Path

import flet as ft
from sqlmodel import Session, SQLModel, create_engine

sys.path.insert(0, str(Path(__file__).resolve().parent))

from _ui_stubs import StubPage, serialise  # noqa: E402
from test_meta_top_teams import CATALOGS, CORE  # noqa: E402

from pokemon_champions_planning_tool.infrastructure.database.models import (  # noqa: E402
    TournamentRecord,
    TournamentTeamMemberRecord,
    TournamentTeamRecord,
)
from pokemon_champions_planning_tool.ui import events  # noqa: E402
from pokemon_champions_planning_tool.ui.context import AppContext  # noqa: E402
from pokemon_champions_planning_tool.ui.views.calc.rival_store import RivalStore  # noqa: E402
from pokemon_champions_planning_tool.ui.views.meta import MetaStore, MetaView  # noqa: E402
from pokemon_champions_planning_tool.ui.views.meta.top_teams_view import TopTeamCard  # noqa: E402


def _seed(sf, *, teams: int = 3, tyranitar_item: str = "Choice Scarf", tid: str = "t1", nature: str | None = None, name: str = "Top Teams Cup") -> None:
    with sf() as s:
        if s.get(TournamentRecord, tid) is None:
            s.add(TournamentRecord(tournament_id=tid, name=name, format_regulation="Regulation M-C", battle_format="doubles"))
            s.commit()
        for p in range(1, teams + 1):
            text = f"Tyranitar @ {tyranitar_item}\n- Rock Slide\n- Knock Off\n- Ice Punch\n- Low Kick"
            team = TournamentTeamRecord(tournament_id=tid, player_name=f"player-{p}", placement=p, standing_label=f"Place #{p}",
                                        showdown_text=text, pokepast_url=f"https://pokepast.es/{tid}{p}")
            s.add(team)
            s.commit()
            members = [TournamentTeamMemberRecord(tournament_team_id=team.tournament_team_id, slot_position=1, canonical_id="tyranitar", species_name="Tyranitar",
                                                   item=tyranitar_item, nature=nature, moves=["Rock Slide", "Knock Off", "Ice Punch", "Low Kick"])]
            members += [TournamentTeamMemberRecord(tournament_team_id=team.tournament_team_id, slot_position=i, canonical_id=cid, species_name=cid.title())
                       for i, cid in enumerate(CORE, start=2)]
            for m in members:
                s.add(m)
            s.commit()


class _Base(unittest.TestCase):
    def setUp(self):
        self.dir = tempfile.mkdtemp()
        self.engine = create_engine(f"sqlite:///{Path(self.dir) / 'db.sqlite'}", connect_args={"check_same_thread": False})
        SQLModel.metadata.create_all(self.engine)
        self.addCleanup(self.engine.dispose)
        self.addCleanup(shutil.rmtree, self.dir, True)
        self.sf = lambda: Session(self.engine)
        self.page = StubPage()
        self.ctx = AppContext(self.page)
        self.ctx.catalogs = CATALOGS
        self.ctx.run_in_background = lambda work, on_done=None, on_error=None, **kw: on_done(work()) if on_done else work()
        self.view = MetaView(self.ctx, MetaStore(self.sf))


class TestTabSwitch(_Base):
    def test_switching_tabs_shows_the_right_controls(self):
        self.assertEqual(self.view._tab, "events")
        self.assertFalse(self.view.top_teams_panel.visible)
        self.assertTrue(self.view._events_toolbar.visible)

        self.view._set_tab("top_teams")
        self.assertEqual(self.view._tab, "top_teams")
        self.assertTrue(self.view.top_teams_panel.visible)
        self.assertFalse(self.view._events_toolbar.visible)
        self.assertFalse(self.view._list.visible)
        self.assertFalse(self.view._grid.visible)
        self.assertFalse(self.view._more_row.visible)

        self.view._set_tab("events")
        self.assertFalse(self.view.top_teams_panel.visible)

    def test_the_tab_choice_is_remembered(self):
        self.view._set_tab("top_teams")
        self.assertEqual(self.ctx.prefs.get("meta.tab"), "top_teams")
        again = MetaView(self.ctx, MetaStore(self.sf))
        self.assertEqual(again._tab, "top_teams")

    def test_ensure_loaded_loads_whichever_tab_is_active(self):
        _seed(self.sf)
        self.view._set_tab("top_teams")
        self.view.ensure_loaded()
        self.assertIsNotNone(self.view.top_teams_panel._result)
        self.assertEqual(self.view.top_teams_panel._result.total_teams, 3)


class TestRankedList(_Base):
    def setUp(self):
        super().setUp()
        _seed(self.sf, teams=3, tyranitar_item="Choice Scarf", nature="Adamant")
        _seed(self.sf, teams=1, tyranitar_item="Choice Scarf", tid="t2", nature="Adamant", name="Second Regional")   # a second event, same lineup
        self.view._set_tab("top_teams")
        self.view.ensure_loaded()

    def test_the_lineup_is_ranked_and_serialises(self):
        cards = [c for c in self.view.top_teams_panel._list.controls if isinstance(c, TopTeamCard)]
        self.assertEqual(len(cards), 1)
        self.assertEqual(cards[0].team.count, 4)
        self.assertIn("4 teams", self.view.top_teams_panel._caption.value)
        self.assertGreater(serialise(self.view), 100)

    def test_expanding_shows_the_item_spread_and_the_teams(self):
        card = next(c for c in self.view.top_teams_panel._list.controls if isinstance(c, TopTeamCard))
        card.toggle()
        self.assertTrue(card._expanded)
        serialise(card)
        card.toggle()
        self.assertFalse(card._expanded)

    def test_expanding_shows_the_most_common_moves_too(self):
        card = next(c for c in self.view.top_teams_panel._list.controls if isinstance(c, TopTeamCard))
        card.toggle()
        spread_column = card._body.content.controls[0]
        tyranitar_row = spread_column.controls[1]   # controls[0] is the "MOST COMMON SET" header row
        moves_text = tyranitar_row.controls[1].controls[-1].value
        self.assertIn("Rock Slide", moves_text)
        self.assertIn("100%", moves_text, "run by every team in the seed")

    def test_expanding_shows_the_natures_share_too(self):
        card = next(c for c in self.view.top_teams_panel._list.controls if isinstance(c, TopTeamCard))
        card.toggle()
        spread_column = card._body.content.controls[0]
        tyranitar_row = spread_column.controls[1]   # controls[0] is the "MOST COMMON SET" header row
        below_text = tyranitar_row.controls[1].controls[2].value
        self.assertIn("Adamant", below_text)
        self.assertIn("100%", below_text, "run by every team in the seed")

    def test_the_teams_in_this_group_show_their_own_tournament_name(self):
        card = next(c for c in self.view.top_teams_panel._list.controls if isinstance(c, TopTeamCard))
        card.toggle()
        teams_column = card._body.content.controls[1]
        names = {
            row.controls[1].controls[1].value
            for row in teams_column.controls[1:]
            if isinstance(row, ft.Row)
        }
        self.assertEqual(names, {"Top Teams Cup", "Second Regional"})

    def test_preview_shows_one_players_own_set_not_the_consensus(self):
        card = next(c for c in self.view.top_teams_panel._list.controls if isinstance(c, TopTeamCard))
        entry = card.team.teams[0]
        card._actions.preview_entry(entry)
        self.assertEqual(len(self.page.dialogs), 1)
        dialog = self.page.dialogs[-1]
        self.assertIn(entry.player_name, dialog.title.value)
        serialise(dialog)
        dialog.actions[0].on_click(None)
        self.assertEqual(len(self.page.dialogs), 0)

    def test_import_the_most_common_set(self):
        card = next(c for c in self.view.top_teams_panel._list.controls if isinstance(c, TopTeamCard))
        got = []
        self.ctx.bus.on(events.IMPORT_REQUESTED, got.append)
        card._actions.import_team(card.team)
        self.assertEqual(len(got), 1)
        text, title = got[0]
        self.assertIn("Tyranitar @ Choice Scarf", text)
        self.assertIn("Top team", title)

    def test_import_one_players_team_reuses_meta_import(self):
        card = next(c for c in self.view.top_teams_panel._list.controls if isinstance(c, TopTeamCard))
        got = []
        self.ctx.bus.on(events.IMPORT_REQUESTED, got.append)
        entry = card.team.teams[0]
        card._actions.import_entry(entry)
        self.assertEqual(len(got), 1)
        text, title = got[0]
        self.assertEqual(text, entry.showdown_text)
        self.assertIn(entry.player_name, title)

    def test_save_the_most_common_set_as_a_rival_preset(self):
        card = next(c for c in self.view.top_teams_panel._list.controls if isinstance(c, TopTeamCard))
        card._actions.save_rival_team(card.team)
        rivals = RivalStore(self.sf)
        rivals.load()
        self.assertTrue(any(t.source == "Meta · Top teams" for t in rivals.teams))

    def test_calc_vs_a_member_emits_calc_requested(self):
        card = next(c for c in self.view.top_teams_panel._list.controls if isinstance(c, TopTeamCard))
        got = []
        self.ctx.bus.on(events.CALC_REQUESTED, got.append)
        card._actions.calc_vs_member(card.team, 0)
        self.assertEqual(len(got), 1)
        self.assertIsNotNone(got[0].defender)

    def test_copy_the_most_common_set(self):
        card = next(c for c in self.view.top_teams_panel._list.controls if isinstance(c, TopTeamCard))
        copied = []
        self.ctx.copy_to_clipboard = copied.append   # a real Clipboard needs a live page; stub it here
        card._actions.copy_team(card.team)
        self.assertIn("Tyranitar", copied[0])
        snack = self.page.dialogs[-1]
        self.assertEqual(snack.content.controls[1].value, "Copied")


class TestEmptyState(_Base):
    def test_no_repeated_lineup_shows_an_empty_state(self):
        _seed(self.sf, teams=1, tyranitar_item="Choice Scarf")
        self.view._set_tab("top_teams")
        self.view.ensure_loaded()
        self.assertEqual(type(self.view.top_teams_panel._list.controls[0]).__name__, "EmptyState")


if __name__ == "__main__":
    unittest.main()

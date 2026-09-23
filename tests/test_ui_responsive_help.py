"""Narrow-window layout (split pane overlay, compact rail) and the Help dialog."""

import unittest
from types import SimpleNamespace

import flet as ft

from _ui_stubs import StubPage, serialise
from pokemon_champions_planning_tool.ui.components.layout import SplitPane
from pokemon_champions_planning_tool.ui.components.pokemon import SidePanel
from pokemon_champions_planning_tool.ui.context import AppContext
from pokemon_champions_planning_tool.ui.help import SHORTCUTS, HelpDialog
from pokemon_champions_planning_tool.ui.shell import AppShell
from pokemon_champions_planning_tool.ui.theme import Layout


def _key(key, ctrl=False):
    return SimpleNamespace(key=key, ctrl=ctrl, shift=False, alt=False, meta=ctrl)  # ctrl = the shortcut modifier, Cmd on macOS


class TestSplitPane(unittest.TestCase):
    def test_wide_row_and_narrow_overlay_reuse_the_same_controls(self):
        main = ft.Column(controls=[ft.Text("main")])
        panel = SidePanel("Details", on_close=lambda: None)
        split = SplitPane(main, panel)
        self.assertIsInstance(split.content, ft.Row)
        self.assertIs(split.content.controls[1], panel)
        self.assertTrue(split.set_narrow(True))
        self.assertIsInstance(split.content, ft.Stack)
        self.assertIs(split.content.controls[1], panel)
        self.assertEqual((panel.right, panel.top, panel.bottom), (0, 0, 0))
        self.assertIsNotNone(panel.shadow)
        self.assertIsNone(split._main_wide.content, "main lives in exactly one parent")
        self.assertIs(split._main_narrow.content, main)
        serialise(split)
        self.assertFalse(split.set_narrow(True), "no change reported")
        self.assertTrue(split.set_narrow(False))
        self.assertIsNone(panel.right)
        self.assertIsNone(panel.shadow)
        serialise(split)


class TestShellResponsiveAndHelp(unittest.TestCase):
    def setUp(self):
        self.page = StubPage()
        self.ctx = AppContext(self.page)
        self.shell = AppShell(self.ctx)
        self.sizes = []
        view = ft.Column()
        view.handle_resize = lambda w, h: self.sizes.append(w)
        self.shell.register_view("v", label="V", icon=ft.Icons.INFO, selected_icon=ft.Icons.INFO, control=view)
        hidden = ft.Column()
        hidden.handle_resize = lambda w, h: self.sizes.append(("hidden", w))
        self.shell.register_view("h", label="H", icon=ft.Icons.INFO, selected_icon=ft.Icons.INFO, control=hidden)
        self.shell.navigate("v")

    def test_rail_compacts_below_the_breakpoint_and_every_view_hears_resizes(self):
        self.page.width, self.page.height = 1000, 700
        self.shell._on_resize(None)
        self.assertTrue(self.shell.compact)
        self.assertEqual(self.shell.rail.label_type, ft.NavigationRailLabelType.NONE)
        self.assertEqual(self.shell.rail.min_width, Layout.RAIL_WIDTH_COMPACT)
        self.assertIn(1000.0, self.sizes)
        self.assertIn(("hidden", 1000.0), self.sizes, "hidden views are sized too")
        self.page.width = 1440
        self.shell._on_resize(None)
        self.assertFalse(self.shell.compact)
        self.assertEqual(self.shell.rail.label_type, ft.NavigationRailLabelType.ALL)
        serialise(self.shell)

    def test_f1_and_ctrl_slash_open_help(self):
        self.shell._on_key(_key("F1"))
        self.assertIsInstance(self.page.dialogs[-1], HelpDialog)
        dialog = self.page.dialogs[-1]
        serialise(dialog)
        self.assertGreaterEqual(len(SHORTCUTS), 10)
        self.shell._on_key(_key("Escape"))
        self.assertEqual(self.page.dialogs, [])
        self.shell._on_key(_key("/", ctrl=True))
        self.assertIsInstance(self.page.dialogs[-1], HelpDialog)


class TestViewsGoNarrow(unittest.TestCase):
    def test_box_and_team_views_overlay_their_panels_when_narrow(self):
        from sqlmodel import SQLModel, Session, create_engine

        from pokemon_champions_planning_tool.ui.views.box.store import BoxStore
        from pokemon_champions_planning_tool.ui.views.box.view import BoxView
        from pokemon_champions_planning_tool.ui.views.team import TeamStore
        from pokemon_champions_planning_tool.ui.views.team.view import TeamView

        engine = create_engine("sqlite:///:memory:")
        SQLModel.metadata.create_all(engine)
        self.addCleanup(engine.dispose)
        sf = lambda: Session(engine)  # noqa: E731
        ctx = AppContext(StubPage())
        box = BoxView(ctx, BoxStore(ctx.catalogs, sf))
        team = TeamView(ctx, TeamStore(ctx.catalogs, sf))
        for view, panel, split in ((box, box.detail, box.split), (team, team.summary, team._body)):
            view.handle_resize(1000, 700)
            self.assertTrue(view._narrow)
            self.assertIsInstance(split.content, ft.Stack)
            self.assertEqual(panel.width, Layout.SIDE_PANEL_WIDTH_COMPACT)
            view.handle_resize(1200, 800)
            self.assertFalse(view._narrow)
            self.assertIsInstance(split.content, ft.Row)
            self.assertEqual(panel.width, Layout.SIDE_PANEL_WIDTH_COMPACT, "compact width between the breakpoints")
            view.handle_resize(1440, 900)
            self.assertEqual(panel.width, Layout.SIDE_PANEL_WIDTH)
            serialise(view)

    def test_meta_ctrl_f_focuses_search(self):
        from sqlmodel import SQLModel, Session, create_engine

        from pokemon_champions_planning_tool.ui.views.meta.store import MetaStore
        from pokemon_champions_planning_tool.ui.views.meta.view import MetaView

        engine = create_engine("sqlite:///:memory:")
        SQLModel.metadata.create_all(engine)
        self.addCleanup(engine.dispose)
        view = MetaView(AppContext(StubPage()), MetaStore(lambda: Session(engine)))
        self.assertFalse(view.handle_key(_key("f", ctrl=True)), "unmounted search: nothing to focus, key not consumed")
        self.assertFalse(view.handle_key(_key("x", ctrl=True)))


if __name__ == "__main__":
    unittest.main()

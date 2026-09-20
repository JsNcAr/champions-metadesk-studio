"""Tests for the UI infrastructure: event bus, background tasks, debouncer, shell."""

import asyncio
import unittest
from types import SimpleNamespace

import flet as ft

from pokemon_champions_planning_tool.ui import events
from pokemon_champions_planning_tool.ui.context import AppContext
from pokemon_champions_planning_tool.ui.events import EventBus
from pokemon_champions_planning_tool.ui.shell import AppShell
from pokemon_champions_planning_tool.ui.tasks import Debouncer, run_in_background


class StubPage(SimpleNamespace):
    """Runs workers inline and coroutines to completion, in the calling thread."""

    def __init__(self):
        super().__init__(overlay=[], controls=[], on_keyboard_event=None, dialogs=[])

    def run_thread(self, fn, *args):
        fn(*args)

    def run_task(self, coro_fn, *args):
        asyncio.run(coro_fn(*args))

    def show_dialog(self, dlg):
        self.dialogs.append(dlg)

    def pop_dialog(self):
        return self.dialogs.pop() if self.dialogs else None

    def update(self, *_):
        pass

    def add(self, *controls):
        self.controls.extend(controls)


def _key(key: str, *, ctrl: bool) -> SimpleNamespace:
    """The shell reads only .key/.ctrl; a stand-in avoids Flet's event constructor."""
    return SimpleNamespace(key=key, ctrl=ctrl, shift=False, alt=False, meta=False)


class TestEventBus(unittest.TestCase):
    def test_emit_delivers_payload_in_order_and_unsubscribes(self):
        bus = EventBus()
        seen = []
        off = bus.on("x", lambda p: seen.append(("a", p)))
        bus.on("x", lambda p: seen.append(("b", p)))
        bus.emit("x", 1)
        off()
        bus.emit("x", 2)
        self.assertEqual(seen, [("a", 1), ("b", 1), ("b", 2)])
        self.assertEqual(bus.listener_count("x"), 1)

    def test_failing_listener_does_not_block_others(self):
        bus = EventBus()
        seen = []

        def boom(_):
            raise RuntimeError("boom")

        bus.on("x", boom)
        bus.on("x", lambda p: seen.append(p))
        with self.assertRaises(RuntimeError):
            bus.emit("x", 42)
        self.assertEqual(seen, [42], "listener after the failing one still ran")

    def test_emit_without_listeners_is_a_noop(self):
        EventBus().emit("nobody-home", None)


class TestRunInBackground(unittest.TestCase):
    def test_success_path_restores_busy_and_spinner(self):
        page = StubPage()
        button, spinner = ft.Button("go"), ft.ProgressRing(visible=False)
        results = []
        run_in_background(page, lambda: 21 * 2, on_done=results.append, busy=[button], spinner=spinner)
        self.assertEqual(results, [42])
        self.assertFalse(button.disabled)
        self.assertFalse(spinner.visible)
        self.assertEqual(page.dialogs, [], "no error toast on success")

    def test_error_path_calls_on_error_and_restores_state(self):
        page = StubPage()
        button = ft.Button("go")
        errors = []

        def work():
            raise ValueError("nope")

        run_in_background(page, work, on_done=lambda _: self.fail("on_done must not run"), on_error=errors.append, busy=[button])
        self.assertEqual([type(e) for e in errors], [ValueError])
        self.assertFalse(button.disabled)

    def test_error_without_handler_shows_error_toast(self):
        page = StubPage()

        def work():
            raise ValueError("nope")

        run_in_background(page, work)
        self.assertEqual(len(page.dialogs), 1)
        self.assertIsInstance(page.dialogs[0], ft.SnackBar)


class TestDebouncer(unittest.TestCase):
    def test_only_the_last_value_fires(self):
        loop = asyncio.new_event_loop()
        pending = []
        page = SimpleNamespace(run_task=lambda fn, *a: pending.append(loop.create_task(fn(*a))))
        fired = []
        debounce = Debouncer(page, 20, fired.append)
        # create_task needs a running loop; drive it manually.

        async def scenario():
            debounce("a")
            debounce("ab")
            debounce("abc")
            await asyncio.gather(*pending)

        loop.run_until_complete(scenario())
        loop.close()
        self.assertEqual(fired, ["abc"])


class TestAppShell(unittest.TestCase):
    def _shell(self):
        page = StubPage()
        ctx = AppContext(page)
        shell = AppShell(ctx)
        shell.register_view("one", label="One", icon=ft.Icons.INBOX, selected_icon=ft.Icons.INBOX, control=ft.Text("one"))
        built = []

        def factory():
            built.append(1)
            return ft.Text("two")

        shell.register_view("two", label="Two", icon=ft.Icons.GROUPS, selected_icon=ft.Icons.GROUPS, factory=factory)
        return page, ctx, shell, built

    def test_registration_builds_rail_and_navigates(self):
        page, ctx, shell, built = self._shell()
        self.assertEqual([d.label for d in shell.rail.destinations], ["One", "Two"])
        shell.navigate("one")
        self.assertEqual(shell.current, "one")
        self.assertEqual(shell.rail.selected_index, 0)
        self.assertEqual(built, [], "factory views are lazy")
        shell.navigate("two")
        shell.navigate("two")
        self.assertEqual(built, [1], "factory runs once and the instance is kept")
        self.assertEqual(shell.host.content.value, "two")

    def test_on_activate_runs_each_visit(self):
        page, ctx, shell, _ = self._shell()
        visits = []
        shell.register_view("three", label="Three", icon=ft.Icons.STAR, selected_icon=ft.Icons.STAR, control=ft.Text("3"), on_activate=lambda: visits.append(1))
        shell.navigate("three")
        shell.navigate("one")
        shell.navigate("three")
        self.assertEqual(visits, [1, 1])

    def test_navigate_event_and_keyboard_shortcuts(self):
        page, ctx, shell, _ = self._shell()
        ctx.bus.emit(events.NAVIGATE, "two")
        self.assertEqual(shell.current, "two")
        page.on_keyboard_event(_key("1", ctrl=True))
        self.assertEqual(shell.current, "one")
        page.on_keyboard_event(_key("2", ctrl=False))
        self.assertEqual(shell.current, "one", "digits without ctrl must not navigate — the user may be typing")
        opened = []
        shell.register_settings(lambda: opened.append(1))
        page.on_keyboard_event(_key(",", ctrl=True))
        self.assertEqual(opened, [1])

    def test_register_view_requires_exactly_one_source(self):
        page, ctx, shell, _ = self._shell()
        with self.assertRaises(ValueError):
            shell.register_view("bad", label="Bad", icon=ft.Icons.STAR, selected_icon=ft.Icons.STAR)




class TestLayoutLint(unittest.TestCase):
    def test_expand_child_inside_wrapping_row_is_rejected(self):
        from _ui_stubs import check_layout

        bad = ft.Column(controls=[ft.Row(wrap=True, controls=[ft.Text("a"), ft.Container(expand=True)])])
        with self.assertRaises(AssertionError) as ctx:
            check_layout(bad)
        self.assertIn("Row(wrap=True)", str(ctx.exception))
        check_layout(ft.Row(controls=[ft.Row(wrap=True, expand=True, controls=[ft.Text("a")]), ft.Container(expand=True)]))




class TestGridTileAspect(unittest.TestCase):
    def test_matches_flutter_max_extent_delegate(self):
        from pokemon_champions_planning_tool.ui.tasks import grid_tile_aspect

        # 1311px → 6 columns of (1311 - 5*12)/6 = 208.5px; height held at 240.
        self.assertAlmostEqual(grid_tile_aspect(1311, max_extent=210, spacing=12, tile_height=240), 208.5 / 240, places=4)
        # Narrower window → fewer, narrower tiles → smaller ratio, same height.
        narrow = grid_tile_aspect(700, max_extent=210, spacing=12, tile_height=240)
        self.assertLess(narrow, 208.5 / 240)
        self.assertAlmostEqual(narrow, ((700 - 3 * 12) / 4) / 240, places=4)
        self.assertGreater(grid_tile_aspect(0, max_extent=210, spacing=12, tile_height=240), 0)




class TestShellEscape(unittest.TestCase):
    def test_escape_closes_the_top_dialog_first(self):
        from types import SimpleNamespace

        from _ui_stubs import StubPage
        from pokemon_champions_planning_tool.ui.context import AppContext
        from pokemon_champions_planning_tool.ui.shell import AppShell

        page = StubPage()
        shell = AppShell(AppContext(page))
        seen = []
        shell.register_view("v", label="V", icon=ft.Icons.INFO, selected_icon=ft.Icons.INFO,
                            control=type("V", (ft.Column,), {"handle_key": lambda self, e: seen.append(e.key)})())
        shell.navigate("v")
        esc = SimpleNamespace(key="Escape", ctrl=False, shift=False, alt=False, meta=False)
        page.show_dialog(ft.AlertDialog(modal=True))
        shell._on_key(esc)
        self.assertEqual(page.dialogs, [], "Escape popped the dialog")
        self.assertEqual(seen, [], "the view did not see the key while a dialog was open")
        shell._on_key(esc)
        self.assertEqual(seen, ["Escape"], "with no dialog open, Escape reaches the view")


class TestDialogs(unittest.IsolatedAsyncioTestCase):
    async def test_confirm_resolves_true_on_confirm_click(self):
        from _ui_stubs import StubPage
        from pokemon_champions_planning_tool.ui.dialogs import confirm

        page = StubPage()
        task = asyncio.create_task(confirm(page, "Delete item?", "Are you sure?"))
        await asyncio.sleep(0.01)

        self.assertEqual(len(page.dialogs), 1)
        dialog = page.dialogs[0]
        # actions[1] is the confirm FilledButton
        dialog.actions[1].on_click(None)
        result = await task
        self.assertTrue(result)

    async def test_confirm_resolves_false_on_cancel_click(self):
        from _ui_stubs import StubPage
        from pokemon_champions_planning_tool.ui.dialogs import confirm

        page = StubPage()
        task = asyncio.create_task(confirm(page, "Delete item?", "Are you sure?"))
        await asyncio.sleep(0.01)

        dialog = page.dialogs[0]
        # actions[0] is the cancel TextButton
        dialog.actions[0].on_click(None)
        result = await task
        self.assertFalse(result)

    async def test_prompt_text_resolves_text_on_submit(self):
        from _ui_stubs import StubPage
        from pokemon_champions_planning_tool.ui.dialogs import prompt_text

        page = StubPage()
        task = asyncio.create_task(prompt_text(page, "Tag item", "Tag", value="sweeper"))
        await asyncio.sleep(0.01)

        dialog = page.dialogs[0]
        # actions[1] is the submit FilledButton
        dialog.actions[1].on_click(None)
        result = await task
        self.assertEqual(result, "sweeper")


if __name__ == "__main__":
    unittest.main()


class TestShellStatusBanner(unittest.TestCase):
    """The app-wide banner the first-run catalogue download reports through."""

    def _shell(self):
        page = StubPage()
        shell = AppShell(AppContext(page))
        shell.register_view("v", label="V", icon=ft.Icons.INFO, selected_icon=ft.Icons.INFO, control=ft.Text("v"))
        return shell

    def test_hidden_until_something_sets_it(self):
        shell = self._shell()
        self.assertFalse(shell.status.visible, "no banner on a normal launch")

    def test_set_and_clear(self):
        shell = self._shell()
        shell.set_status("Setting up — downloading the Pokédex", "info")
        self.assertTrue(shell.status.visible)
        self.assertIn("downloading", shell.status._text.value)
        shell.clear_status()
        self.assertFalse(shell.status.visible)

    def test_offers_an_action(self):
        shell = self._shell()
        opened = []
        shell.set_status("Could not download", "warning", action_label="Settings", on_action=lambda: opened.append(1))
        self.assertTrue(shell.status._action.visible)
        shell.status._on_action()
        self.assertEqual(opened, [1])

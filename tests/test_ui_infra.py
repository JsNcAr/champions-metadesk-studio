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


def _in_event_context(fn):
    """Run ``fn`` the way Flet runs a handler: in its own context, auto-update reset.

    Returns whether Flet would still auto-update after it.
    """
    import contextvars

    def run():
        ft.context.reset_auto_update()
        ft.context.enable_auto_update()   # every Flet event starts with it on
        fn()
        return ft.context.auto_update_enabled()

    return contextvars.copy_context().run(run)


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

    def test_a_keystroke_skips_flets_auto_update(self):
        # Otherwise each keystroke re-diffs the whole view (~0.4 s on a full Box) and
        # those diffs queue ahead of the filtered result.
        page = SimpleNamespace(run_task=lambda fn, *a: fn(*a).close())
        debounce = Debouncer(page, 20, lambda _v: None)
        self.assertTrue(_in_event_context(lambda: None), "control: a plain handler auto-updates")
        self.assertFalse(_in_event_context(lambda: debounce("a")))


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
        self.assertEqual(shell.current_control.value, "two")

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

    def test_a_control_placed_twice_is_rejected(self):
        from _ui_stubs import check_layout

        name = ft.Text("Charizard")
        with self.assertRaises(AssertionError) as ctx:
            check_layout(ft.Column(controls=[ft.Row(controls=[name]), ft.Row(controls=[name])]))
        self.assertIn("Text placed twice", str(ctx.exception))
        check_layout(ft.Column(controls=[ft.Row(controls=[ft.Text("a")]), ft.Row(controls=[ft.Text("a")])]))


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

    def test_an_unhandled_key_skips_flets_auto_update(self):
        from types import SimpleNamespace

        from _ui_stubs import StubPage
        from pokemon_champions_planning_tool.ui.context import AppContext
        from pokemon_champions_planning_tool.ui.shell import AppShell

        shell = AppShell(AppContext(StubPage()))
        handled = {"x": False}
        shell.register_view("v", label="V", icon=ft.Icons.INFO, selected_icon=ft.Icons.INFO,
                            control=type("V", (ft.Column,), {"handle_key": lambda self, e: handled["x"]})())
        shell.navigate("v")
        key = SimpleNamespace(key="a", ctrl=False, shift=False, alt=False, meta=False)
        self.assertFalse(_in_event_context(lambda: shell._on_key(key)), "plain typing sends nothing")
        handled["x"] = True
        self.assertTrue(_in_event_context(lambda: shell._on_key(key)), "a handled key keeps the default")


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


class TestShellDeck(unittest.TestCase):
    """Views are layered, not swapped: the first is a base layer, the rest overlays.

    Swapping the host's content detached views (a return trip re-sent the whole tree),
    and any update containing a view makes Flet walk all of it — so views are isolated,
    the stack's child list never changes after registration, and hidden overlays stay
    built but transparent, click-through and disabled (disabled keeps keyboard focus out).
    """

    def _shell(self):
        page = StubPage()
        shell = AppShell(AppContext(page))
        activations = []
        for key in ("base", "one", "two"):
            shell.register_view(key, label=key, icon=ft.Icons.INFO, selected_icon=ft.Icons.INFO,
                                control=ft.TextField(label=key), on_activate=lambda key=key: activations.append(key))
        shell.register_view("lazy", label="lazy", icon=ft.Icons.INFO, selected_icon=ft.Icons.INFO,
                            factory=lambda: ft.TextField(label="lazy"))
        return shell, activations

    @staticmethod
    def _shown(shell):
        return sorted(k for k, s in shell._slots.items()
                      if s.visible and s.opacity == 1.0 and not s.ignore_interactions and not s.disabled)

    def test_every_view_has_a_slot_from_registration_and_the_deck_never_changes(self):
        shell, _ = self._shell()
        slots = list(shell.deck.controls)
        self.assertEqual(len(slots), 4)
        for key in ("base", "one", "lazy", "two", "base"):
            shell.navigate(key)
        shell.preload("two")
        self.assertEqual(shell.deck.controls, slots, "same slot objects, same order")

    def test_views_are_isolated_so_slot_updates_do_not_walk_them(self):
        shell, _ = self._shell()
        shell.navigate("base")
        shell.navigate("lazy")
        for key in ("base", "one", "two", "lazy"):
            self.assertTrue(shell._entries[key].control.is_isolated(), key)

    def test_only_the_current_view_is_interactive(self):
        shell, _ = self._shell()
        shell.navigate("base")
        self.assertEqual(self._shown(shell), ["base"])
        shell.navigate("two")                     # above the base
        self.assertEqual(self._shown(shell), ["two"])
        shell.navigate("one")                     # arriving *below* the overlay on screen
        self.assertEqual(self._shown(shell), ["one"])
        shell.navigate("two")                     # and above again
        self.assertEqual(self._shown(shell), ["two"])
        shell.navigate("base")
        self.assertEqual(self._shown(shell), ["base"])
        self.assertEqual(shell.current_control.label, "base")

    def test_a_hidden_overlay_stays_built_but_cannot_be_reached(self):
        """Stays mounted (showing it again is a property change, not a rebuild), while
        clicks pass through it and disabled keeps keyboard focus out."""
        shell, _ = self._shell()
        shell.navigate("base")
        shell.navigate("one")
        shell.navigate("base")
        one = shell._slots["one"]
        self.assertTrue(one.visible, "kept built on the client")
        self.assertEqual((one.opacity, one.ignore_interactions, one.disabled), (0.0, True, True))

    def test_the_base_is_disabled_while_covered_and_enabled_when_shown(self):
        """The base stays under every overlay; without this, Tab reached its fields."""
        shell, _ = self._shell()
        shell.navigate("base")
        base = shell._slots["base"]
        self.assertFalse(base.disabled)
        shell.navigate("one")
        self.assertTrue(base.disabled)
        self.assertEqual(base.opacity, 1.0, "still painted under the overlay")
        shell.navigate("base")
        self.assertFalse(base.disabled)

    def test_preload_mounts_hidden_and_can_activate(self):
        shell, activations = self._shell()
        shell.navigate("base")
        shell.preload("lazy")
        lazy = shell._slots["lazy"]
        self.assertEqual(lazy.content.label, "lazy", "built into its slot")
        self.assertEqual((lazy.opacity, lazy.ignore_interactions, lazy.disabled), (0.0, True, True), "but hidden")
        shell.preload("one", activate=True)
        self.assertIn("one", activations)
        self.assertEqual(shell.current, "base")

    def test_a_deferred_hide_that_arrives_after_a_return_is_ignored(self):
        """Hiding completes after the fade; if the user came straight back, it must not."""
        shell, _ = self._shell()
        shell.navigate("base")
        shell.navigate("one")
        shell._settle("one")                      # a late settle for the view now current
        self.assertEqual(self._shown(shell), ["one"])
        shell._cover_base()
        shell.navigate("base")
        shell._cover_base()                       # a late cover after returning to the base
        self.assertFalse(shell._slots["base"].disabled)


class TestShellColdBuild(unittest.TestCase):
    """A view that is not built yet: acknowledge the click, then build on the next tick."""

    def setUp(self):
        from unittest.mock import patch

        self.page = StubPage()
        self.queued = []
        self.page.run_task = lambda fn, *a: self.queued.append((fn, a))
        self.shell = AppShell(AppContext(self.page))
        self.shell.register_view("base", label="b", icon=ft.Icons.INFO, selected_icon=ft.Icons.INFO, control=ft.Text("b"))
        self.built = []
        for key in ("cold", "other"):
            self.shell.register_view(key, label=key, icon=ft.Icons.INFO, selected_icon=ft.Icons.INFO,
                                     factory=lambda key=key: self.built.append(key) or ft.Text(key))
        self.patches = [
            patch("pokemon_champions_planning_tool.ui.shell.shell.is_mounted", lambda _c: True),
            patch.object(AppShell, "_update", lambda self, *c: None),
        ]
        for p in self.patches:
            p.start()
        self.shell.navigate("base")
        self._drain()

    def tearDown(self):
        for p in self.patches:
            p.stop()

    def _drain(self):
        while self.queued:
            fn, args = self.queued.pop(0)
            asyncio.run(fn(*args))

    def test_the_click_is_acknowledged_before_the_build(self):
        self.shell.navigate("cold")
        self.assertEqual(self.shell.rail.selected_index, 1, "rail moved at once")
        self.assertTrue(self.shell.progress.visible, "bar showing")
        self.assertEqual(self.built, [], "not built on the click")
        self._drain()
        self.assertEqual(self.built, ["cold"])
        self.assertFalse(self.shell.progress.visible)
        self.assertTrue(self.shell._slots["cold"].visible)

    def test_a_build_overtaken_by_another_click_is_dropped(self):
        self.shell.navigate("cold")
        self.shell.navigate("other")
        self._drain()
        self.assertEqual(self.built, ["other"], "the abandoned view is not built")
        self.assertEqual(self.shell.current, "other")

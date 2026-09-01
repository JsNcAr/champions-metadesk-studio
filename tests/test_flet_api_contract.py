"""Pins the Flet 0.85 APIs the UI relies on.

Flet's API moved a lot between versions (``page.open`` → ``page.show_dialog``,
``Dropdown.on_change`` → ``on_select``, ``ElevatedButton`` → ``Button``…). The shell,
dialog helpers and background-task helper are written against the shapes below; a Flet
bump that changes any of them fails here instead of at the first click.
"""

import dataclasses
import unittest

import flet as ft


def _fields(cls) -> set[str]:
    return {f.name for f in dataclasses.fields(cls)}


class TestFletApiContract(unittest.TestCase):
    def test_page_dialog_and_async_api(self):
        for name in ("show_dialog", "pop_dialog", "run_thread", "run_task", "add", "update", "navigate"):
            self.assertTrue(hasattr(ft.Page, name), f"ft.Page.{name} missing")
        self.assertIn("on_keyboard_event", _fields(ft.Page))
        self.assertTrue({"key", "ctrl", "shift", "alt", "meta"} <= _fields(ft.KeyboardEvent))

    def test_removed_page_apis_stay_removed(self):
        """Documents the traps: the legacy code used these and they do not exist."""
        for name in ("set_clipboard", "open", "close", "dialog", "window_width", "window_height"):
            self.assertFalse(hasattr(ft.Page, name), f"ft.Page.{name} unexpectedly exists — revisit dialogs/clipboard code")

    def test_navigation_controls(self):
        self.assertTrue(
            {"destinations", "selected_index", "extended", "label_type", "leading", "trailing", "min_width", "on_change"}
            <= _fields(ft.NavigationRail)
        )
        self.assertTrue({"icon", "selected_icon", "label"} <= _fields(ft.NavigationRailDestination))
        self.assertEqual({m.name for m in ft.NavigationRailLabelType}, {"NONE", "ALL", "SELECTED"})
        self.assertTrue(hasattr(ft, "VerticalDivider"))

    def test_overlay_controls(self):
        self.assertTrue({"content", "action", "on_action", "duration", "show_close_icon", "behavior"} <= _fields(ft.SnackBar))
        self.assertTrue({"modal", "title", "content", "actions", "actions_alignment", "on_dismiss", "scrollable"} <= _fields(ft.AlertDialog))
        self.assertTrue(hasattr(ft, "Clipboard") and hasattr(ft.Clipboard, "set"))

    def test_buttons_and_inputs(self):
        for name in ("Button", "FilledButton", "FilledTonalButton", "OutlinedButton", "TextButton", "IconButton"):
            self.assertTrue(hasattr(ft, name), f"ft.{name} missing")
        self.assertIn("on_select", _fields(ft.Dropdown))
        self.assertNotIn("on_change", _fields(ft.Dropdown), "Dropdown grew on_change back — check handlers")
        self.assertTrue({"prefix_icon", "suffix", "helper", "error", "on_change", "on_submit", "on_blur"} <= _fields(ft.TextField))
        for name in ("AutoComplete", "RangeSlider", "Slider", "SegmentedButton", "Chip", "DataTable", "DataColumn", "Draggable", "DragTarget", "AnimatedSwitcher", "ResponsiveRow"):
            self.assertTrue(hasattr(ft, name), f"ft.{name} missing")
        self.assertTrue({"sort_column_index", "sort_ascending"} <= _fields(ft.DataTable))
        self.assertIn("on_sort", _fields(ft.DataColumn))
        self.assertIn("on_select", _fields(ft.Chip))
        self.assertIn("error_content", _fields(ft.Image))

    def test_theme_api(self):
        self.assertTrue(
            {"color_scheme", "text_theme", "font_family", "use_material3", "visual_density", "card_theme", "dialog_theme", "navigation_rail_theme", "chip_theme", "snackbar_theme"}
            <= _fields(ft.Theme)
        )
        self.assertTrue(callable(getattr(ft.Colors, "with_opacity", None)))

    def test_serialiser_and_canvas(self):
        from flet.controls.object_patch import ObjectPatch

        self.assertTrue(hasattr(ObjectPatch, "from_diff"))
        import flet.canvas  # noqa: F401 - custom drawing fallback for charts


if __name__ == "__main__":
    unittest.main()

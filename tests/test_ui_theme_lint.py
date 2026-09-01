"""Guards the design-token rule: no hex colour literals in UI code outside ``ui/theme``.

The pre-overhaul UI accumulated 72 inline hex literals, which is how thirteen copies of
the card colour and three different "unknown type" greens crept in. New UI code reads
every colour from ``ui/theme/tokens.py``; this test fails the build if a literal appears
anywhere else.
"""

import re
import unittest
from pathlib import Path

UI_ROOT = Path(__file__).resolve().parents[1] / "src" / "pokemon_champions_planning_tool" / "ui"

# No exemptions remain now that the legacy UI is gone.
LEGACY_ALLOWLIST: set[str] = set()

_HEX = re.compile(r"#[0-9a-fA-F]{6}\b")


class TestNoHexLiteralsOutsideTheme(unittest.TestCase):
    def test_ui_code_uses_tokens(self):
        offenders: list[str] = []
        for path in sorted(UI_ROOT.rglob("*.py")):
            if "theme" in path.relative_to(UI_ROOT).parts:
                continue
            if path.name in LEGACY_ALLOWLIST:
                continue
            for lineno, line in enumerate(path.read_text(encoding="utf-8").splitlines(), 1):
                if _HEX.search(line):
                    offenders.append(f"{path.relative_to(UI_ROOT)}:{lineno}: {line.strip()}")
        self.assertEqual(
            offenders, [], "hex colour literals belong in ui/theme/tokens.py:\n" + "\n".join(offenders)
        )

    def test_theme_builds(self):
        from pokemon_champions_planning_tool.ui.theme import build_theme

        theme = build_theme()
        self.assertIsNotNone(theme.color_scheme)
        self.assertEqual(theme.font_family, "Inter")

    def test_theme_serialises_like_runtime(self):
        """Walks the theme through Flet's own diff/serialise path.

        A bad enum or field value in a sub-theme only surfaces when a client session
        connects, which no headless check exercises. ``ObjectPatch.from_diff`` is exactly
        what ``Session.patch_control`` runs at runtime, so it catches those here.
        """
        import flet as ft
        from flet.controls.base_control import BaseControl
        from flet.controls.object_patch import ObjectPatch

        from pokemon_champions_planning_tool.ui.theme import build_theme

        control = ft.Container(content=ft.Text("probe"), theme=build_theme())
        patch, added, _removed = ObjectPatch.from_diff(None, control, control_cls=BaseControl)
        message = patch.to_message()
        self.assertTrue(message, "empty patch — nothing was serialised")
        self.assertTrue(added, "control was not registered as added")


if __name__ == "__main__":
    unittest.main()

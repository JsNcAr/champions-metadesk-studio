"""The app's logo files: the icon containers built by scripts/build_icons.py, the files the app ships,
the web icons copied into the assets folder, and the logo in the rail."""

from __future__ import annotations

import importlib.util
import struct
import sys
import tempfile
import unittest
from pathlib import Path

import flet as ft

from _ui_stubs import StubPage
from pokemon_champions_planning_tool import brand
from pokemon_champions_planning_tool.ui.context import AppContext
from pokemon_champions_planning_tool.ui.shell import AppShell

ROOT = Path(__file__).resolve().parents[1]
_spec = importlib.util.spec_from_file_location("build_icons_script", ROOT / "scripts" / "build_icons.py")
build_icons = importlib.util.module_from_spec(_spec)
sys.modules[_spec.name] = build_icons
_spec.loader.exec_module(build_icons)


def _png(size: int) -> bytes:
    """A minimal PNG header with the given size (enough for the containers, which never decode it)."""
    return build_icons.PNG_MAGIC + struct.pack(">I", 13) + b"IHDR" + struct.pack(">II", size, size) + b"\x08\x06\x00\x00\x00"


class TestIconContainers(unittest.TestCase):
    def test_ico_lists_each_size_and_points_at_its_png(self):
        images = {16: _png(16), 32: _png(32), 256: _png(256)}
        data = build_icons.build_ico(images)
        reserved, kind, count = struct.unpack("<HHH", data[:6])
        self.assertEqual((reserved, kind, count), (0, 1, 3))
        for i, size in enumerate(sorted(images)):
            w, h, _c, _r, planes, bits, length, offset = struct.unpack("<BBBBHHII", data[6 + 16*i: 22 + 16*i])
            self.assertEqual((w, h), (size % 256, size % 256), "256 is stored as 0")
            self.assertEqual((planes, bits), (1, 32))
            self.assertEqual(data[offset:offset + length], images[size])

    def test_icns_is_a_chain_of_typed_png_chunks(self):
        chunks = [("icp4", _png(16)), ("ic07", _png(128))]
        data = build_icons.build_icns(chunks)
        self.assertEqual(data[:4], b"icns")
        self.assertEqual(struct.unpack(">I", data[4:8])[0], len(data))
        pos, seen = 8, []
        while pos < len(data):
            kind, length = data[pos:pos + 4].decode(), struct.unpack(">I", data[pos + 4:pos + 8])[0]
            self.assertTrue(data[pos + 8:pos + 16].startswith(build_icons.PNG_MAGIC))
            seen.append(kind)
            pos += length
        self.assertEqual(seen, ["icp4", "ic07"])

    def test_a_png_of_the_wrong_size_is_refused(self):
        with tempfile.TemporaryDirectory() as tmp:
            (Path(tmp) / "tile-32.png").write_bytes(_png(16))
            with self.assertRaises(ValueError):
                build_icons.read_png(32, Path(tmp))


class TestShippedFiles(unittest.TestCase):
    def test_the_committed_icons_are_valid_and_complete(self):
        for name in ("app.ico", "app.icns"):
            self.assertTrue((ROOT / "packaging" / "icons" / name).is_file(), name)
        self.assertEqual((ROOT / "packaging" / "icons" / "app.icns").read_bytes()[:4], b"icns")
        ico = (ROOT / "packaging" / "icons" / "app.ico").read_bytes()
        self.assertEqual(struct.unpack("<HHH", ico[:6])[2], len(build_icons.ICO_SIZES))
        for name in ("rail.png", "favicon.png", *brand.WEB_FILES):
            path = brand.BRAND_DIR / name
            self.assertTrue(path.is_file(), name)
            if name.endswith(".png"):
                self.assertEqual(path.read_bytes()[:8], build_icons.PNG_MAGIC, name)
        self.assertEqual(brand.WINDOW_ICON.read_bytes(), ico, "the window icon is the build's .ico")


class TestWebIcons(unittest.TestCase):
    def test_copied_once_then_left_alone(self):
        with tempfile.TemporaryDirectory() as tmp:
            self.assertEqual(brand.install_web_icons(tmp), len(brand.WEB_FILES))
            self.assertTrue((Path(tmp) / "favicon.png").is_file())
            self.assertTrue((Path(tmp) / "icons" / "icon-192.png").is_file())
            self.assertEqual(brand.install_web_icons(tmp), 0, "nothing changed: nothing written")
            (Path(tmp) / "favicon.png").write_bytes(b"old")
            self.assertEqual(brand.install_web_icons(tmp), 1, "a changed file is replaced")

    def test_an_unwritable_folder_is_logged_not_raised(self):
        with tempfile.TemporaryDirectory() as tmp:
            blocker = Path(tmp) / "file"
            blocker.write_text("x")
            with self.assertLogs("pokemon_champions_planning_tool.brand", "WARNING"):
                self.assertEqual(brand.install_web_icons(blocker), 0)


class TestRailLogo(unittest.TestCase):
    def test_the_rail_shows_the_app_logo(self):
        shell = AppShell(AppContext(StubPage()))
        leading = shell.rail.leading.content
        self.assertIsInstance(leading, ft.Image)
        self.assertEqual(leading.src, brand.RAIL_IMAGE.read_bytes())
        self.assertEqual(shell.rail.leading.tooltip, "Champions MetaDesk Studio")


if __name__ == "__main__":
    unittest.main()

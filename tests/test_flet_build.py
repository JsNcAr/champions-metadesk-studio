"""`flet build` support: the project settings it reads, the src/main.py entry point, and how the app
behaves inside a built app (FLET_PLATFORM set by the Flutter host)."""

from __future__ import annotations

import importlib
import importlib.util
import os
import sys
import tempfile
import tomllib
import unittest
from pathlib import Path
from unittest.mock import MagicMock, patch

from pokemon_champions_planning_tool import config, flet_client
from pokemon_champions_planning_tool import main as app_main
from pokemon_champions_planning_tool.services.sprite_cache_service import SpriteCacheService

ROOT = Path(__file__).resolve().parents[1]


class TestProjectSettings(unittest.TestCase):
    def setUp(self):
        self.flet = tomllib.loads((ROOT / "pyproject.toml").read_text(encoding="utf-8"))["tool"]["flet"]

    def test_the_app_folder_is_src_and_its_entry_point_exists(self):
        self.assertEqual(self.flet["app"]["path"], "src")
        self.assertEqual(self.flet["app"]["module"], "main")
        self.assertTrue((ROOT / "src" / "main.py").is_file())

    def test_the_bundle_id_is_the_apps_linux_id(self):
        self.assertEqual(self.flet["bundle_id"], flet_client.APP_ID)

    def test_the_icons_flet_build_looks_for_exist(self):
        assets = ROOT / "src" / "assets"
        self.assertEqual((assets / "icon.png").read_bytes()[:8], b"\x89PNG\r\n\x1a\n")
        self.assertEqual((assets / "icon_windows.ico").read_bytes()[:4], b"\x00\x00\x01\x00")
        self.assertEqual((assets / "icon_macos.icns").read_bytes()[:4], b"icns")


class TestEntryPoint(unittest.TestCase):
    def _load(self, env):
        spec = importlib.util.spec_from_file_location("flet_build_entry", ROOT / "src" / "main.py")
        module = importlib.util.module_from_spec(spec)
        with patch.object(app_main, "run") as run, patch.dict(os.environ, env, clear=False):
            if "FLET_PLATFORM" not in env:
                os.environ.pop("FLET_PLATFORM", None)
            spec.loader.exec_module(module)
        return run

    def test_importing_it_does_not_start_the_app(self):
        self._load({}).assert_not_called()

    def test_the_flutter_host_starts_the_app_however_it_loads_the_file(self):
        self._load({"FLET_PLATFORM": "linux"}).assert_called_once()


class TestEmbeddedConfig(unittest.TestCase):
    def tearDown(self):
        importlib.reload(config)

    def _reload(self, env):
        with patch.dict(os.environ, env), patch.object(sys, "frozen", False, create=True):
            for key in ("PCPT_DATABASE", "PCPT_SPRITE_SRC", "PCPT_ASSETS_DIR"):
                if key not in env:
                    os.environ.pop(key, None)
            importlib.reload(config)

    def test_a_built_app_uses_the_same_per_user_folder_as_a_packed_one(self):
        with tempfile.TemporaryDirectory() as tmp:
            self._reload({"FLET_PLATFORM": "linux", "XDG_DATA_HOME": tmp, "HOME": tmp, "FLET_APP_STORAGE_DATA": "/elsewhere"})
            self.assertTrue(config.EMBEDDED)
            self.assertTrue(config.PACKAGED)
            expected = config.user_data_dir(env={"XDG_DATA_HOME": tmp, "LOCALAPPDATA": tmp}, home=Path(tmp))
            self.assertEqual(config.DATA_DIR, expected)
            self.assertNotIn("/elsewhere", str(config.DATA_DIR), "not the host's storage folder: data stays where it was")

    def test_sprites_come_from_the_cdn_in_a_built_app_unless_overridden(self):
        self._reload({"FLET_PLATFORM": "linux"})
        self.assertEqual(config.SPRITE_SRC, "remote")
        self._reload({"FLET_PLATFORM": "linux", "PCPT_SPRITE_SRC": "file"})
        self.assertEqual(config.SPRITE_SRC, "file")
        os.environ.pop("FLET_PLATFORM", None)
        self._reload({})
        self.assertFalse(config.EMBEDDED)
        self.assertEqual(config.SPRITE_SRC, "asset")


class TestSpriteSourceModes(unittest.TestCase):
    URL = "https://play.pokemonshowdown.com/sprites/gen5/pikachu.png"

    def _service(self, mode):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        cache = Path(tmp.name) / "sprites"
        cache.mkdir()
        service = SpriteCacheService(cache_dir=cache, assets_dir=tmp.name, src_mode="asset")
        name = service.filename_for_url(self.URL)
        (cache / name).write_bytes(b"png")
        service = SpriteCacheService(cache_dir=cache, assets_dir=tmp.name, src_mode=mode)   # sees it at start
        self.addCleanup(service.shutdown)
        return service, cache / name

    def test_asset_mode_serves_the_cached_file_from_assets(self):
        service, _ = self._service("asset")
        self.assertTrue(service.resolve_sprite_src(self.URL, background_download=False).startswith("/sprites/"))

    def test_file_mode_uses_the_absolute_path(self):
        service, path = self._service("file")
        self.assertEqual(service.resolve_sprite_src(self.URL, background_download=False), str(path.resolve()))

    def test_remote_mode_always_uses_the_cdn(self):
        service, _ = self._service("remote")
        self.assertEqual(service.resolve_sprite_src(self.URL, background_download=False), self.URL)


class TestRunEmbedded(unittest.TestCase):
    def test_no_client_patching_or_web_icons_but_the_linux_entry_stays(self):
        fake_ft = MagicMock()
        with patch.dict(sys.modules, {"flet": fake_ft}), \
                patch.object(app_main, "prepare_sprite_cache_dir", return_value=True), \
                patch.object(app_main, "install_linux_desktop_entry") as entry, \
                patch.object(app_main, "install_web_icons") as web_icons, \
                patch.object(app_main.flet_client, "prepare") as prepare, \
                patch.object(app_main.sys, "platform", "linux"), patch.object(app_main.sys, "argv", ["main.py", "--web"]), \
                self.assertLogs("pokemon_champions_planning_tool.main", "WARNING") as logs:
            app_main.run_embedded()
        entry.assert_called_once_with(flet_client.APP_ID)
        web_icons.assert_not_called()
        prepare.assert_not_called()
        self.assertNotIn("view", fake_ft.run.call_args.kwargs, "the host is the window; there is no view to pick")
        self.assertIn("--web", logs.output[0])


if __name__ == "__main__":
    unittest.main()

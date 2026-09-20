"""Unit tests for SpriteCacheService."""

from __future__ import annotations

import tempfile
import unittest
from pathlib import Path
from unittest.mock import MagicMock, patch

from pokemon_champions_planning_tool.services.sprite_cache_service import SpriteCacheService


class TestSpriteCacheService(unittest.TestCase):
    def setUp(self) -> None:
        self.tmpdir = tempfile.TemporaryDirectory()
        self.cache_path = Path(self.tmpdir.name) / "sprites"
        self.service = SpriteCacheService(cache_dir=self.cache_path, assets_dir=self.tmpdir.name)

    def tearDown(self) -> None:
        self.tmpdir.cleanup()

    def test_filename_for_url(self) -> None:
        showdown_url = "https://play.pokemonshowdown.com/sprites/gen5/flutter-mane.png"
        self.assertEqual(self.service.filename_for_url(showdown_url), "flutter-mane.png")

        item_url = "https://raw.githubusercontent.com/PokeAPI/sprites/master/sprites/items/poke-ball.png"
        self.assertEqual(self.service.filename_for_url(item_url), "item-poke-ball.png")

        self.assertIsNone(self.service.filename_for_url(""))
        self.assertIsNone(self.service.filename_for_url(None))

    def test_resolve_sprite_src_uncached_returns_url_and_enqueues(self) -> None:
        url = "https://play.pokemonshowdown.com/sprites/gen5/pikachu.png"
        with patch.object(self.service, "enqueue_download") as mock_enqueue:
            resolved = self.service.resolve_sprite_src(url, background_download=True)
            self.assertEqual(resolved, url)
            mock_enqueue.assert_called_once_with(url, "pikachu.png")

    def test_a_sprite_on_disk_at_startup_is_served_locally(self) -> None:
        """The second launch onwards: the file was there before the app opened."""
        self.cache_path.mkdir(parents=True, exist_ok=True)
        (self.cache_path / "pikachu.png").write_bytes(b"\x89PNG\r\n\x1a\nfake")
        service = SpriteCacheService(cache_dir=self.cache_path, assets_dir=self.tmpdir.name)

        url = "https://play.pokemonshowdown.com/sprites/gen5/pikachu.png"
        with patch.object(service, "enqueue_download") as mock_enqueue:
            self.assertEqual(service.resolve_sprite_src(url), "/sprites/pikachu.png")
            mock_enqueue.assert_not_called()

    def test_a_sprite_that_lands_mid_session_keeps_showing_the_cdn_copy(self) -> None:
        """It is already on screen from the CDN, and it will be served locally next launch."""
        url = "https://play.pokemonshowdown.com/sprites/gen5/pikachu.png"
        self.service.ensure_cache_dir()
        (self.cache_path / "pikachu.png").write_bytes(b"\x89PNG\r\n\x1a\nfake")
        self.service._known_local.add("pikachu.png")   # as a finished download would

        with patch.object(self.service, "enqueue_download") as mock_enqueue:
            self.assertEqual(self.service.resolve_sprite_src(url), url)
            mock_enqueue.assert_not_called()
        self.assertFalse(self.service.is_servable("pikachu.png"))
        # A service starting now — the next launch — does serve it.
        self.assertTrue(
            SpriteCacheService(cache_dir=self.cache_path, assets_dir=self.tmpdir.name).is_servable("pikachu.png")
        )

    def test_resolve_sprite_src_handles_non_urls_and_local_paths(self) -> None:
        self.assertIsNone(self.service.resolve_sprite_src(None))
        self.assertEqual(self.service.resolve_sprite_src(""), "")
        self.assertEqual(self.service.resolve_sprite_src("/sprites/custom.png"), "/sprites/custom.png")

    def test_download_sprite_sync(self) -> None:
        url = "https://play.pokemonshowdown.com/sprites/gen5/mew.png"
        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.content = b"fake-png-content"

        with patch("requests.get", return_value=mock_response):
            success = self.service.download_sprite_sync(url, "mew.png")
            self.assertTrue(success)
            dest = self.cache_path / "mew.png"
            self.assertTrue(dest.exists())
            self.assertEqual(dest.read_bytes(), b"fake-png-content")
            self.assertTrue(self.service.is_cached("mew.png"))

    def test_prefetch_and_cache_stats(self) -> None:
        with patch.object(self.service, "enqueue_download") as mock_enqueue:
            count = self.service.prefetch(["pikachu", "charizard"])
            self.assertEqual(count, 2)
            self.assertEqual(mock_enqueue.call_count, 2)

        # Cache stats
        self.service.ensure_cache_dir()
        (self.cache_path / "a.png").write_bytes(b"1234")
        (self.cache_path / "b.png").write_bytes(b"123456")
        files, total_bytes = self.service.cache_stats()
        self.assertEqual(files, 2)
        self.assertEqual(total_bytes, 10)

        # Clear cache
        cleared = self.service.clear_cache()
        self.assertEqual(cleared, 2)
        files_after, bytes_after = self.service.cache_stats()
        self.assertEqual(files_after, 0)
        self.assertEqual(bytes_after, 0)


if __name__ == "__main__":
    unittest.main()


class TestAssetsDirIsServable(unittest.TestCase):
    """The assets path must be absolute or Flet quietly serves nothing from it.

    ``ft.run(assets_dir=...)`` resolves a *relative* path against the directory of
    ``sys.argv[0]``, not the working directory. "assets" therefore became
    ``src/pokemon_champions_planning_tool/assets``, which does not exist, so Flet
    discarded it and every ``/sprites/...`` request 404'd — while the cache wrote to
    ``./assets/sprites``. Nothing the cache downloaded was ever reachable.
    """

    def test_configured_paths_are_absolute(self):
        from pokemon_champions_planning_tool.config import DEFAULT_ASSETS_DIR, DEFAULT_SPRITE_CACHE_DIR

        self.assertTrue(Path(DEFAULT_ASSETS_DIR).is_absolute(), DEFAULT_ASSETS_DIR)
        self.assertTrue(Path(DEFAULT_SPRITE_CACHE_DIR).is_absolute(), DEFAULT_SPRITE_CACHE_DIR)

    def test_the_cache_lives_under_the_directory_flet_serves(self):
        """The served root and the write target must be the same tree, or they never meet."""
        import os

        if os.environ.get("PCPT_SPRITE_CACHE_DIR"):
            self.skipTest("cache directory overridden for this run")
        from pokemon_champions_planning_tool.config import DEFAULT_ASSETS_DIR, DEFAULT_SPRITE_CACHE_DIR

        self.assertEqual(Path(DEFAULT_SPRITE_CACHE_DIR).parent, Path(DEFAULT_ASSETS_DIR))
        self.assertEqual(Path(DEFAULT_SPRITE_CACHE_DIR).name, "sprites",
                         "the served URL prefix is /sprites/, set by get_local_src")


class TestSpriteControlUsesTheCache(unittest.TestCase):
    """The Sprite control is where the cache pays off; assert the wiring, not just the service."""

    def setUp(self) -> None:
        self.tmpdir = tempfile.TemporaryDirectory()
        self.cache_path = Path(self.tmpdir.name) / "sprites"
        self.cache_path.mkdir(parents=True)
        (self.cache_path / "pikachu.png").write_bytes(b"\x89PNG\r\n\x1a\nfake")
        self.service = SpriteCacheService(cache_dir=self.cache_path, assets_dir=self.tmpdir.name)

    def tearDown(self) -> None:
        self.tmpdir.cleanup()

    def test_sprite_src_points_at_the_local_copy(self):
        from pokemon_champions_planning_tool.ui.components.sprite import Sprite

        url = "https://play.pokemonshowdown.com/sprites/gen5/pikachu.png"
        with patch("pokemon_champions_planning_tool.ui.components.sprite.resolve_sprite_src",
                   self.service.resolve_sprite_src):
            cached = Sprite(url, size=40)
            self.assertEqual(cached._image.src, "/sprites/pikachu.png")
            self.assertTrue(cached._image.visible)

            uncached = Sprite("https://play.pokemonshowdown.com/sprites/gen5/mew.png", size=40)
            self.assertEqual(uncached._image.src, "https://play.pokemonshowdown.com/sprites/gen5/mew.png")

            cached.set_src("https://play.pokemonshowdown.com/sprites/gen5/pikachu.png")
            self.assertEqual(cached._image.src, "/sprites/pikachu.png", "set_src resolves too")

    def test_no_url_still_falls_back_to_the_icon(self):
        from pokemon_champions_planning_tool.ui.components.sprite import Sprite

        blank = Sprite(None, size=40)
        self.assertEqual(blank._image.src, "")
        self.assertFalse(blank._image.visible)
        self.assertTrue(blank._fallback.visible)

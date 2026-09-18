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

    def test_resolve_sprite_src_cached_returns_local_asset_path(self) -> None:
        self.service.ensure_cache_dir()
        cached_file = self.cache_path / "pikachu.png"
        cached_file.write_bytes(b"\x89PNG\r\n\x1a\nfake")
        # Invalidate in-memory lookup to test disk detection
        self.service._known_local.clear()

        url = "https://play.pokemonshowdown.com/sprites/gen5/pikachu.png"
        with patch.object(self.service, "enqueue_download") as mock_enqueue:
            resolved = self.service.resolve_sprite_src(url)
            self.assertEqual(resolved, "/sprites/pikachu.png")
            mock_enqueue.assert_not_called()

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

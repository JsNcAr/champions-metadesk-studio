"""Local disk/memory sprite cache for Pokémon and item sprites.

Stores Showdown and PokeAPI sprites locally in ``assets/sprites`` so they can be
served instantly by Flet at 0ms latency with zero network requests and full offline
readiness. When a sprite is not yet cached locally, the remote URL is returned so
the UI displays immediately, while a background thread downloads the sprite to disk
for subsequent views.
"""

from __future__ import annotations

import os
import threading
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from typing import Sequence
from urllib.parse import urlparse

import requests

from ..config import DEFAULT_ASSETS_DIR, DEFAULT_SPRITE_CACHE_DIR, TOURNAMENT_USER_AGENT
from ..domain.pokemon_identity import get_pokemon_sprite_url, get_showdown_sprite_slug


class SpriteCacheService:
    """Manages two-tier (memory + disk) caching for Pokémon and item sprites."""

    def __init__(
        self,
        cache_dir: str | Path | None = None,
        assets_dir: str | Path | None = None,
    ) -> None:
        self.assets_dir = Path(assets_dir or DEFAULT_ASSETS_DIR)
        self.cache_dir = Path(cache_dir or DEFAULT_SPRITE_CACHE_DIR)
        self._lock = threading.Lock()
        self._in_flight: set[str] = set()
        self._known_local: set[str] = set()
        self._executor = ThreadPoolExecutor(max_workers=2, thread_name_prefix="sprite-cache")
        self._scan_existing()

    def _scan_existing(self) -> None:
        """Populates in-memory lookup set from existing files on disk."""
        if not self.cache_dir.is_dir():
            return
        try:
            for entry in os.scandir(self.cache_dir):
                if entry.is_file() and entry.name.endswith((".png", ".gif", ".webp", ".jpg", ".svg")):
                    if entry.stat().st_size > 0:
                        self._known_local.add(entry.name)
        except OSError:
            pass

    def ensure_cache_dir(self) -> Path:
        """Ensures the cache directory exists."""
        self.cache_dir.mkdir(parents=True, exist_ok=True)
        return self.cache_dir

    def filename_for_url(self, url: str) -> str | None:
        """Extracts or derives a safe cache filename for an image URL."""
        if not url:
            return None
        parsed = urlparse(url)
        path = parsed.path.rstrip("/")
        if not path:
            return None

        # Showdown sprite: /sprites/gen5/slug.png -> slug.png
        if "pokemonshowdown.com" in parsed.netloc:
            name = Path(path).name
            return name if name.endswith(".png") else f"{name}.png"

        # PokeAPI item: .../sprites/items/item-name.png -> item-item-name.png
        if "items" in path:
            name = Path(path).name
            return f"item-{name}" if not name.startswith("item-") else name

        name = Path(path).name
        return name or None

    def is_cached(self, filename: str) -> bool:
        """Checks whether the file is cached locally."""
        if filename in self._known_local:
            return True
        target = self.cache_dir / filename
        if target.is_file() and target.stat().st_size > 0:
            with self._lock:
                self._known_local.add(filename)
            return True
        return False

    def get_local_src(self, filename: str) -> str:
        """Returns the local asset path for Flet controls."""
        return f"/sprites/{filename}"

    def resolve_sprite_src(
        self,
        src: str | None,
        *,
        background_download: bool = True,
    ) -> str | None:
        """Resolves an image source: returns local asset path if cached, or remote URL.

        If not cached and ``background_download`` is True, enqueues an asynchronous
        download to warm the cache for subsequent renders.
        """
        if not src:
            return src

        # Already an asset path or local file
        if src.startswith(("/sprites/", "sprites/", "assets/")):
            return src

        # Only process HTTP/HTTPS URLs
        if not src.startswith(("http://", "https://")):
            return src

        filename = self.filename_for_url(src)
        if not filename:
            return src

        if self.is_cached(filename):
            return self.get_local_src(filename)

        # Cache miss: return remote URL for instant display, trigger background download
        if background_download:
            self.enqueue_download(src, filename)

        return src

    def enqueue_download(self, url: str, filename: str) -> None:
        """Asynchronously downloads a sprite into the local cache."""
        with self._lock:
            if filename in self._known_local or filename in self._in_flight:
                return
            self._in_flight.add(filename)

        self._executor.submit(self._download_worker, url, filename)

    def _download_worker(self, url: str, filename: str) -> None:
        try:
            self.download_sprite_sync(url, filename)
        except Exception:  # noqa: BLE001 - background downloads are best-effort
            pass
        finally:
            with self._lock:
                self._in_flight.discard(filename)

    def download_sprite_sync(self, url: str, filename: str) -> bool:
        """Downloads a sprite synchronously and saves it to the cache directory."""
        self.ensure_cache_dir()
        dest = self.cache_dir / filename
        tmp = dest.with_suffix(f".{os.getpid()}.tmp")

        headers = {"User-Agent": TOURNAMENT_USER_AGENT}
        resp = requests.get(url, headers=headers, timeout=6)
        if resp.status_code != 200 or not resp.content:
            return False

        tmp.write_bytes(resp.content)
        tmp.replace(dest)

        with self._lock:
            self._known_local.add(filename)
        return True

    def prefetch(self, species_or_cids: Sequence[str]) -> int:
        """Enqueues background downloads for a sequence of Pokémon identifiers.

        Returns the number of downloads enqueued.
        """
        count = 0
        for mon in species_or_cids:
            slug = get_showdown_sprite_slug(mon)
            if not slug:
                continue
            filename = f"{slug}.png"
            if not self.is_cached(filename):
                url = get_pokemon_sprite_url(mon)
                self.enqueue_download(url, filename)
                count += 1
        return count

    def cache_stats(self) -> tuple[int, int]:
        """Returns ``(file_count, total_bytes)`` for the current sprite cache."""
        if not self.cache_dir.is_dir():
            return 0, 0
        count = 0
        total_bytes = 0
        try:
            for entry in os.scandir(self.cache_dir):
                if entry.is_file():
                    count += 1
                    total_bytes += entry.stat().st_size
        except OSError:
            pass
        return count, total_bytes

    def clear_cache(self) -> int:
        """Empties the sprite cache directory and resets lookup state."""
        count = 0
        if not self.cache_dir.is_dir():
            return 0
        try:
            for entry in os.scandir(self.cache_dir):
                if entry.is_file():
                    try:
                        os.unlink(entry.path)
                        count += 1
                    except OSError:
                        pass
        except OSError:
            pass
        with self._lock:
            self._known_local.clear()
        return count


# Default shared service instance
sprite_cache = SpriteCacheService()


def resolve_sprite_src(src: str | None) -> str | None:
    """Convenience helper to resolve sprite URL or local cached path."""
    return sprite_cache.resolve_sprite_src(src)

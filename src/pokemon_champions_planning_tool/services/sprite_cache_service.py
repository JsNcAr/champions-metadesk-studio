"""Local disk/memory sprite cache for Pokémon and item sprites.

Stores Showdown and PokeAPI sprites locally in ``assets/sprites`` so they can be
served instantly by Flet at 0ms latency with zero network requests and full offline
readiness. When a sprite is not yet cached locally, the remote URL is returned so
the UI displays immediately, while a background thread downloads the sprite to disk
for subsequent views.

A species' primary (``gen5``) sprite can 404 for a form too new to have hand-drawn art
yet — every newly added Pokémon Champions Mega starts this way. Rather than hard-coding
which ids currently need a workaround, a failed download automatically retries the
``ani`` directory (auto-generated per dex entry, usually already there) and, if that
works, caches it under its own filename — self-healing for the *next* launch, the same
one-launch delay any newly-discovered sprite already has. See ``_try_fallback_download``.
"""

from __future__ import annotations

import atexit
import os
import threading
import weakref
from concurrent.futures import ThreadPoolExecutor
from concurrent.futures.thread import _worker
from pathlib import Path
from typing import Sequence
from urllib.parse import urlparse

import requests

from ..config import DEFAULT_ASSETS_DIR, DEFAULT_SPRITE_CACHE_DIR, TOURNAMENT_USER_AGENT
from ..domain.pokemon_identity import (
    get_pokemon_sprite_url,
    get_showdown_ani_sprite_url,
    get_showdown_sprite_slug,
)


# What counts as a cached sprite. Anything else in the folder (the tracked .gitkeep, a
# download's temporary file) is neither counted nor served.
_SPRITE_SUFFIXES = (".png", ".gif", ".webp", ".jpg", ".svg")


def _is_sprite(entry: os.DirEntry) -> bool:
    return entry.is_file() and entry.name.endswith(_SPRITE_SUFFIXES) and entry.stat().st_size > 0


class _DaemonThreadPoolExecutor(ThreadPoolExecutor):
    """ThreadPoolExecutor whose workers are daemon threads so app exit is instant."""

    def _adjust_thread_count(self) -> None:
        if self._idle_semaphore.acquire(timeout=0):
            return

        def weakref_cb(_, q=self._work_queue):
            q.put(None)

        num_threads = len(self._threads)
        if num_threads < self._max_workers:
            thread_name = f"{self._thread_name_prefix or self}_{num_threads}"
            t = threading.Thread(
                name=thread_name,
                target=_worker,
                args=(
                    weakref.ref(self, weakref_cb),
                    self._work_queue,
                    self._initializer,
                    self._initargs,
                ),
                daemon=True,
            )
            t.start()
            self._threads.add(t)


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
        # Found nowhere this session (primary and fallback both failed): not re-queued on
        # every render or Pre-cache click. In memory only, so the next launch tries again.
        self._failed: set[str] = set()
        # Filenames already on disk when the app started. Only these are served from
        # ``/sprites/``: a file downloaded mid-session is already on screen from the CDN,
        # so switching its src would gain nothing, and whether every Flet runtime picks up
        # a file that appeared after launch is not something this project can verify.
        self._present_at_start: frozenset[str] = frozenset()
        # stem ("raichu-megay") -> filename ("raichu-megay.gif"), for every sprite present
        # at start. Lets a species/form whose primary (gen5 .png) URL 404s but whose
        # self-healed fallback (ani .gif) was cached on a previous launch resolve locally
        # even though that fallback's filename differs from what the primary URL implies.
        self._stem_at_start: dict[str, str] = {}
        self._executor = _DaemonThreadPoolExecutor(max_workers=2, thread_name_prefix="sprite-cache")
        atexit.register(self.shutdown)
        self._scan_existing()
        self._present_at_start = frozenset(self._known_local)
        self._stem_at_start = {Path(name).stem: name for name in self._known_local}

    def shutdown(self) -> None:
        """Immediately release executor resources and cancel queued futures."""
        try:
            self._executor.shutdown(wait=False, cancel_futures=True)
        except Exception:
            pass

    def _scan_existing(self) -> None:
        """Populates in-memory lookup set from existing files on disk."""
        if not self.cache_dir.is_dir():
            return
        try:
            for entry in os.scandir(self.cache_dir):
                if _is_sprite(entry):
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

        # Showdown sprite: /sprites/gen5/slug.png -> slug.png (or /sprites/ani/slug.gif ->
        # slug.gif — the fallback _try_fallback_download saves under, when the primary
        # gen5 icon 404s).
        if "pokemonshowdown.com" in parsed.netloc:
            name = Path(path).name
            return name if "." in name else f"{name}.png"

        # PokeAPI item: .../sprites/items/item-name.png -> item-item-name.png
        if "items" in path:
            name = Path(path).name
            return f"item-{name}" if not name.startswith("item-") else name

        name = Path(path).name
        return name or None

    def is_servable(self, filename: str) -> bool:
        """Was this file on disk before the app started, and so safe to serve locally?"""
        return filename in self._present_at_start

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

    def is_cached_or_healed(self, filename: str) -> bool:
        """``is_cached``, or a self-healed fallback (``<stem>.gif``) already stands in for
        it — so a healed sprite isn't queued, and its fallback re-downloaded, every launch."""
        return self.is_cached(filename) or self.is_cached(f"{Path(filename).stem}.gif")

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

        if self.is_servable(filename):
            return self.get_local_src(filename)

        # A previous launch's self-heal (see _try_fallback_download) may have cached this
        # species/form under a different extension than the primary URL implies.
        fallback = self._stem_at_start.get(Path(filename).stem)
        if fallback is not None:
            return self.get_local_src(fallback)

        # Not served locally this session: show the CDN copy now and cache it for the next
        # launch, when ``_present_at_start`` will contain it.
        if background_download and not self.is_cached_or_healed(filename):
            self.enqueue_download(src, filename)

        return src

    def enqueue_download(self, url: str, filename: str) -> None:
        """Asynchronously downloads a sprite into the local cache."""
        with self._lock:
            if filename in self._known_local or filename in self._in_flight or filename in self._failed:
                return
            self._in_flight.add(filename)

        self._executor.submit(self._download_worker, url, filename)

    def _download_worker(self, url: str, filename: str) -> None:
        ok = False
        try:
            ok = self.download_sprite_sync(url, filename)
        except Exception:  # noqa: BLE001 - background downloads are best-effort
            pass
        if not ok:   # a network error on the primary still gets the fallback a try
            try:
                ok = self._try_fallback_download(url, filename)
            except Exception:  # noqa: BLE001
                pass
        with self._lock:
            self._in_flight.discard(filename)
            if not ok:
                self._failed.add(filename)

    def unavailable_count(self) -> int:
        """Sprites found nowhere this session (see ``_failed``)."""
        return len(self._failed)

    def _try_fallback_download(self, url: str, filename: str) -> bool:
        """A gen5 icon can 404 for a form too new to have hand-drawn art yet (a
        just-added Pokémon Champions Mega, say); the ``ani`` directory (auto-generated per
        dex entry) often already has a static render under the same slug. This self-heals
        the cache for the *next* launch — like any newly-discovered sprite, this session
        still shows the CDN copy or the fallback icon (see ``_present_at_start``)."""
        if "pokemonshowdown.com" not in urlparse(url).netloc:
            return False
        stem = Path(filename).stem
        ani_url = get_showdown_ani_sprite_url(stem)
        if not ani_url or ani_url == url:
            return False
        return self.download_sprite_sync(ani_url, f"{stem}.gif")

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
            if not get_showdown_sprite_slug(mon):
                continue
            url = get_pokemon_sprite_url(mon)
            filename = self.filename_for_url(url)
            if not filename or filename in self._failed or filename in self._in_flight:
                continue
            if not self.is_cached_or_healed(filename):
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
                if _is_sprite(entry):
                    count += 1
                    total_bytes += entry.stat().st_size
        except OSError:
            pass
        return count, total_bytes

    def clear_cache(self) -> int:
        """Deletes the cached sprites (and stray download temp files); returns sprites deleted.

        Other files are left alone, notably the .gitkeep that keeps the folder in git.
        """
        count = 0
        if not self.cache_dir.is_dir():
            return 0
        try:
            for entry in os.scandir(self.cache_dir):
                sprite = _is_sprite(entry)
                if sprite or (entry.is_file() and entry.name.endswith(".tmp")):
                    try:
                        os.unlink(entry.path)
                        count += int(sprite)
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
    """Local cached path when there is one, else the remote URL. Never downloads.

    Building a control must not reach the network: the UI calls this for every sprite it
    draws, including under test. Filling the cache is a deliberate act — see ``prefetch``,
    which the app runs in the background once the window is up.
    """
    return sprite_cache.resolve_sprite_src(src, background_download=False)

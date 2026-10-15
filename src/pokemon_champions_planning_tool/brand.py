"""The app's own logo files, shipped in data/brand (built by scripts/build_icons.py from assets/brand)."""

from __future__ import annotations

import logging
import os
from pathlib import Path

log = logging.getLogger(__name__)

BRAND_DIR = Path(__file__).resolve().parent / "data" / "brand"
RAIL_IMAGE = BRAND_DIR / "rail.png"          # the crimson tile, for the navigation rail
WINDOW_ICON = BRAND_DIR / "app.ico"          # window and taskbar icon (Flet applies it on Windows)
# Files the web build serves from assets_dir in place of Flet's own (favicon and PWA icons).
WEB_FILES = ("favicon.png", "icons/icon-192.png", "icons/icon-512.png", "icons/icon-maskable-192.png",
             "icons/icon-maskable-512.png", "icons/apple-touch-icon-192.png")


def rail_image() -> bytes | None:
    try:
        return RAIL_IMAGE.read_bytes()
    except OSError:
        log.warning("Logo image missing at %s; the rail shows no logo", RAIL_IMAGE)
        return None


def install_web_icons(assets_dir: str | os.PathLike[str]) -> int:
    """Copy the favicon and web icons into the assets folder Flet serves first, so the browser tab
    and an installed web app show the app's logo instead of Flet's. Only missing or changed files
    are written; returns how many. Never raises (the app works without them)."""
    written = 0
    for name in WEB_FILES:
        source, target = BRAND_DIR / name, Path(assets_dir) / name
        try:
            data = source.read_bytes()
            if target.is_file() and target.read_bytes() == data:
                continue
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_bytes(data)
            written += 1
        except OSError as exc:
            log.warning("Couldn't install the web icon %s: %s", name, exc)
    return written


__all__ = ["BRAND_DIR", "RAIL_IMAGE", "WEB_FILES", "WINDOW_ICON", "install_web_icons", "rail_image"]

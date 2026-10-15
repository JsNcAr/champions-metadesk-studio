"""The app's own logo files, shipped in data/brand (built by scripts/build_icons.py from assets/brand)."""

from __future__ import annotations

import logging
import os
import shutil
import subprocess
import sys
from collections.abc import Mapping
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


# -- Linux: the dock/taskbar icon -------------------------------------------------------------------------
# GNOME, KDE and other Linux desktops don't take a window's icon from the program: they look for a .desktop
# file named after the window's app ID and use its Icon. The app runs its own copy of Flet's client with the
# app ID io.metadesk.champ (see flet_client.py), so the entry below belongs to this app alone.
FLET_SHARED_APP_ID = "com.appveyor.flet"      # Flet's own client: an entry under this name is no longer written
ICON_NAME = "champions-metadesk"
LINUX_ICON_SIZES = (48, 128, 256, 512)
OWNER_KEY = "X-Champions-MetaDesk-Studio"   # marks entries this app wrote


def desktop_entry(app_id: str, exec_path: str) -> str:
    return (
        "[Desktop Entry]\n"
        "Type=Application\n"
        "Name=Champions MetaDesk Studio\n"
        f"Icon={ICON_NAME}\n"
        f"Exec={exec_path}\n"
        "NoDisplay=true\n"                   # only there to give the window its icon; not a menu entry
        f"StartupWMClass={app_id}\n"
        f"{OWNER_KEY}=true\n"
    )


def install_linux_desktop_entry(app_id: str, *, platform: str = sys.platform, env: Mapping[str, str] = os.environ,
                                home: Path | None = None) -> bool:
    """Give the desktop app its icon in the Linux dock and taskbar: write
    ~/.local/share/applications/<app_id>.desktop and the icon in the user's icon theme, and remove the
    shared Flet entry an earlier version wrote. Returns True when something was written; never raises."""
    if not platform.startswith("linux"):
        return False
    data_home = Path(env.get("XDG_DATA_HOME") or (home or Path.home()) / ".local" / "share")
    apps = data_home / "applications"
    entry_path = apps / f"{app_id}.desktop"
    content = desktop_entry(app_id, sys.executable if getattr(sys, "frozen", False) else "true")
    try:
        legacy = apps / f"{FLET_SHARED_APP_ID}.desktop"
        if legacy.is_file() and OWNER_KEY in legacy.read_text(encoding="utf-8", errors="replace"):
            legacy.unlink()                                   # it gave every Flet app this icon
        current = entry_path.read_text(encoding="utf-8", errors="replace") if entry_path.is_file() else None
        if current is not None and OWNER_KEY not in current:
            log.info("%s was not written by this app; leaving it", entry_path)
            return False
        wrote = False
        for size in LINUX_ICON_SIZES:
            source = BRAND_DIR / "linux" / f"{size}.png"
            target = data_home / "icons" / "hicolor" / f"{size}x{size}" / "apps" / f"{ICON_NAME}.png"
            data = source.read_bytes()
            if not target.is_file() or target.read_bytes() != data:
                target.parent.mkdir(parents=True, exist_ok=True)
                target.write_bytes(data)
                wrote = True
        if current != content:
            apps.mkdir(parents=True, exist_ok=True)
            entry_path.write_text(content, encoding="utf-8")
            wrote = True
    except OSError as exc:
        log.warning("Couldn't install the Linux desktop entry for the app icon: %s", exc)
        return False
    if wrote:
        log.info("Installed the app icon for the Linux dock (%s)", entry_path)
        _refresh_desktop_caches(data_home)
    return wrote


def _refresh_desktop_caches(data_home: Path) -> None:
    """Ask the desktop to notice the new entry and icon at once (both tools are optional)."""
    for cmd in (["update-desktop-database", str(data_home / "applications")],
                ["gtk-update-icon-cache", "-q", "-t", "-f", str(data_home / "icons" / "hicolor")]):
        if shutil.which(cmd[0]):
            try:
                subprocess.run(cmd, check=False, timeout=10, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
            except (OSError, subprocess.SubprocessError):
                pass


__all__ = ["BRAND_DIR", "RAIL_IMAGE", "WEB_FILES", "WINDOW_ICON", "install_linux_desktop_entry",
           "install_web_icons", "rail_image"]

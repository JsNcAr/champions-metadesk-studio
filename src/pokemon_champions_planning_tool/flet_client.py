"""Linux: run Flet's desktop client under the app's own app ID, so the dock shows the app's icon.

Linux desktops pick a window's icon from the .desktop file named after its app ID. Flet's prebuilt
Linux client is compiled with the app ID ``com.appveyor.flet``, shared by every Flet app, so an icon
installed for it would show for all of them. Instead, the app runs its own copy of the client:

- the 24 KB executable is copied and its app ID (one 17-byte string) replaced by ``io.metadesk.champ``,
  which has the same length, so nothing else in the binary moves;
- ``lib/`` and ``data/`` are symlinks to Flet's own cache (the executable loads ``$ORIGIN/lib``), so
  nothing big is duplicated and Flet's cache itself is never modified;
- ``FLET_VIEW_PATH`` (Flet's documented override) points the launch at it.

The copy lives in ``$XDG_CACHE_HOME/champions-metadesk-studio/flet-client/<flet version>/``. If anything
fails (a Flet release changed the binary, no write access), the app runs Flet's client unchanged.
"""

from __future__ import annotations

import logging
import os
import shutil
import sys
from collections.abc import Callable, Mapping
from pathlib import Path

log = logging.getLogger(__name__)

FLET_APP_ID = b"com.appveyor.flet"
APP_ID = "io.metadesk.champ"            # same length as Flet's, so the binary is patched in place
assert len(APP_ID.encode()) == len(FLET_APP_ID)
LINKED = ("lib", "data")


class ClientError(Exception):
    """The client can't be given the app's ID (an unexpected binary, a missing file)."""


def patch_app_id(binary: bytes) -> bytes:
    """Flet's client with the app's ID. Refuses unless Flet's ID appears exactly once."""
    count = binary.count(FLET_APP_ID)
    if count != 1:
        raise ClientError(f"expected Flet's app ID once in the client, found it {count} times")
    return binary.replace(FLET_APP_ID, APP_ID.encode())


def build_client(source: Path, target: Path) -> Path:
    """Make ``target`` a runnable client with the app's ID from Flet's client folder ``source``
    (the folder holding the ``flet`` executable, ``lib/`` and ``data/``). Idempotent; returns ``target``."""
    exe = source / "flet"
    if not exe.is_file():
        raise ClientError(f"no Flet client at {exe}")
    patched = patch_app_id(exe.read_bytes())
    target.mkdir(parents=True, exist_ok=True)
    out = target / "flet"
    if not out.is_file() or out.read_bytes() != patched:
        tmp = out.with_name("flet.partial")
        tmp.write_bytes(patched)
        tmp.chmod(0o755)
        os.replace(tmp, out)
    for name in LINKED:
        link, real = target / name, (source / name).resolve()
        if not real.exists():
            raise ClientError(f"Flet's client has no {name}/")
        if link.is_symlink() and Path(os.readlink(link)) == real:
            continue
        if link.is_symlink() or link.is_file():
            link.unlink()
        elif link.is_dir():
            shutil.rmtree(link)
        link.symlink_to(real, target_is_directory=True)
    return target


def cache_root(env: Mapping[str, str] = os.environ, home: Path | None = None) -> Path:
    base = Path(env.get("XDG_CACHE_HOME") or (home or Path.home()) / ".cache")
    return base / "champions-metadesk-studio" / "flet-client"


def prepare(*, platform: str = sys.platform, env: Mapping[str, str] = os.environ,
            locate: Callable[[], tuple[Path, str]] | None = None, root: Path | None = None) -> str | None:
    """On Linux, build the app's client and return the folder for ``FLET_VIEW_PATH``; None to run
    Flet's own client (other systems, an override already set, or anything going wrong)."""
    if not platform.startswith("linux") or env.get("FLET_VIEW_PATH"):
        return None
    try:
        source, version = (locate or _flet_client)()
        root = root or cache_root(env)
        target = build_client(source, root / version)
        for old in root.iterdir():                      # clients of earlier Flet versions
            if old != target and old.is_dir():
                shutil.rmtree(old, ignore_errors=True)
        return str(target)
    except Exception as exc:  # noqa: BLE001 - the app still runs with Flet's own client
        log.warning("Running Flet's client unchanged; the dock may show a generic icon (%s)", exc)
        return None


def _flet_client() -> tuple[Path, str]:
    """Flet's client folder (downloaded or unpacked into Flet's cache on first use) and its version."""
    import flet_desktop
    import flet_desktop.version

    return Path(flet_desktop.ensure_client_cached()) / "flet", flet_desktop.version.version


__all__ = ["APP_ID", "ClientError", "build_client", "cache_root", "patch_app_id", "prepare"]

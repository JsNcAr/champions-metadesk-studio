"""Build the app's icon files from the brand PNGs in assets/brand/png (standard library only).

    python scripts/build_icons.py            # write packaging/icons/app.ico + app.icns, refresh data/brand/

The PNGs are rendered from the SVG masters in assets/brand (tile.svg; tile-small.svg for 16–48 px). Both
container formats hold PNG data as is, so no imaging library is needed:

- app.ico   Windows (16–256 px; PNG entries are valid in ICO since Windows Vista)
- app.icns  macOS (16–1024 px, PNG chunks icp4–ic14)

It also copies what the running app needs into src/…/data/brand/ (shipped with the package and the
builds): the rail image, the window icon and the web favicon and icon set.
"""

from __future__ import annotations

import shutil
import struct
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
PNG_DIR = ROOT / "assets" / "brand" / "png"
WEB_DIR = ROOT / "assets" / "brand" / "web"
OUT_DIR = ROOT / "packaging" / "icons"
DATA_DIR = ROOT / "src" / "pokemon_champions_planning_tool" / "data" / "brand"

PNG_MAGIC = b"\x89PNG\r\n\x1a\n"
ICO_SIZES = (16, 24, 32, 48, 64, 128, 256)
# icns chunk type -> pixel size of the PNG it holds (the @2x types hold the doubled size)
ICNS_TYPES = (("icp4", 16), ("icp5", 32), ("icp6", 64), ("ic07", 128), ("ic08", 256), ("ic09", 512),
              ("ic10", 1024), ("ic11", 32), ("ic12", 64), ("ic13", 256), ("ic14", 512))


def png_size(data: bytes) -> tuple[int, int]:
    """Width and height from a PNG's IHDR chunk."""
    if data[:8] != PNG_MAGIC or data[12:16] != b"IHDR":
        raise ValueError("not a PNG")
    return struct.unpack(">II", data[16:24])


def read_png(size: int, folder: Path = PNG_DIR) -> bytes:
    data = (folder / f"tile-{size}.png").read_bytes()
    if png_size(data) != (size, size):
        raise ValueError(f"tile-{size}.png is {png_size(data)}, expected {size}×{size}")
    return data


def build_ico(images: dict[int, bytes]) -> bytes:
    """An ICO holding one PNG per size (256 is written as 0 in the 1-byte size fields)."""
    sizes = sorted(images)
    header = struct.pack("<HHH", 0, 1, len(sizes))
    offset = 6 + 16 * len(sizes)
    entries, blobs = b"", b""
    for s in sizes:
        data = images[s]
        entries += struct.pack("<BBBBHHII", s % 256, s % 256, 0, 0, 1, 32, len(data), offset)
        blobs += data
        offset += len(data)
    return header + entries + blobs


def build_icns(chunks: list[tuple[str, bytes]]) -> bytes:
    """An ICNS file: 'icns' + total length, then one (type, length, PNG) chunk each."""
    body = b"".join(kind.encode("ascii") + struct.pack(">I", 8 + len(data)) + data for kind, data in chunks)
    return b"icns" + struct.pack(">I", 8 + len(body)) + body


def runtime_files() -> dict[str, Path]:
    """data/brand/<name> -> its source: what the app reads at runtime."""
    return {
        "rail.png": PNG_DIR / "tile-128.png",              # the rail's 40 px tile, sharp on 2×/3× screens
        "favicon.png": PNG_DIR / "tile-48.png",            # the small cut, as browsers show favicons at 16–32 px
        "app.ico": OUT_DIR / "app.ico",                    # window and taskbar icon (Windows)
        "icons/icon-192.png": WEB_DIR / "icon-192.png",    # Flet web serves these over its own defaults
        "icons/icon-512.png": WEB_DIR / "icon-512.png",
        "icons/icon-maskable-192.png": WEB_DIR / "maskable-512.png",
        "icons/icon-maskable-512.png": WEB_DIR / "maskable-512.png",
        "icons/apple-touch-icon-192.png": WEB_DIR / "apple-touch-icon.png",
    }


def main() -> int:
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    (OUT_DIR / "app.ico").write_bytes(build_ico({s: read_png(s) for s in ICO_SIZES}))
    (OUT_DIR / "app.icns").write_bytes(build_icns([(kind, read_png(size)) for kind, size in ICNS_TYPES]))
    for name, source in runtime_files().items():
        target = DATA_DIR / name
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(source, target)
    print(f"wrote {OUT_DIR.relative_to(ROOT)}/app.ico, app.icns and {len(runtime_files())} files in {DATA_DIR.relative_to(ROOT)}")
    return 0


if __name__ == "__main__":
    sys.exit(main())

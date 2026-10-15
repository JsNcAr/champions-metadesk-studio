# Packaging and Building Executables

This document describes how to package **Champions MetaDesk Studio** as a native desktop app on Windows, Linux and macOS: with `flet build` (the release path, locally or in GitHub Actions), and the older `flet pack` and Docker routes.

---

## 1. Automated Multi-Platform Releases (GitHub Actions)

The repository includes a GitHub Actions workflow at [`.github/workflows/release.yml`](../.github/workflows/release.yml) that builds standalone executables across all three major platforms whenever a Git version tag is published. It runs in three stages:

1. **verify**: fails unless the tag matches the version in `pyproject.toml` and the package `__version__`, runs the test suite, and checks that CHANGELOG.md has a section for the version.
2. **build**: the three platform builds below, stamped with the version.
3. **publish**: once all three succeed, creates one GitHub release named after the tag, with that CHANGELOG.md section as its notes and the three archives attached. Versions with a suffix (`1.0.0-rc.1`) are marked as pre-releases.

Running the workflow by hand (*Run workflow* in the Actions tab) builds and uploads the archives as workflow artifacts without publishing anything.

### Matrix Build Configuration
Each job runs `scripts/build_desktop.sh <os>` (`flet build`, section 2) with Flutter cached between runs.
* **Windows** (`windows-latest`): the `champions-metadesk` folder (`champions-metadesk.exe`, Flutter's DLLs, `data/`), signed when the signing secrets exist, zipped into `champions-metadesk-windows-x64.zip`.
* **Linux** (`ubuntu-latest`): the bundle plus icons and `install.sh`, in `champions-metadesk-linux-x64.tar.gz`.
* **macOS** (`macos-latest`): `ChampionsMetaDeskStudio.app`, signed and notarized when the secrets exist, in `champions-metadesk-macos.zip`.

### Publishing a Release

Run `poetry run python scripts/release.py prepare minor` from an up-to-date `main`.
It bumps the version, writes the changelog, tags, and pushes the tag that starts this
workflow. The full procedure, and how to write the release description, is in
**[releasing.md](releasing.md)**.

Do not create the tag or the release in the GitHub web UI: the tag would skip the
version and changelog checks, and a hand-made release can collide with the one the
workflow publishes.

---

## 2. Native Build with `flet build` (the release path)

`flet build` compiles a dedicated Flutter app for this project, so each OS sees **our** app: its own
name, app ID (`io.metadesk.champ`) and icon, one bundle to sign, and no client unpacked into `~/.flet` at
first launch. It reads `[tool.flet]` in `pyproject.toml`: the app folder is `src/` (`src/main.py` starts
the app) and the icons are `src/assets/icon.png`, `icon_windows.ico` and `icon_macos.icns`, written by
`scripts/build_icons.py`. Each OS builds on itself (no cross-compiling). The first build downloads
Flutter 3.41.7 (about 2 GB) into `~/flutter`.

### Linux (tested on openSUSE; apt and dnf work too)

```bash
scripts/flet_build_prereqs.sh          # lists Flutter's toolchain packages: ok / missing / not found by name
scripts/flet_build_prereqs.sh --yes    # installs the missing ones (sudo)
scripts/build_desktop.sh linux         # icons, flet build, then the archive
dist/linux/champions-metadesk          # run the built app
```

The build writes everything it prints to `dist/build-linux.log`, and `flutter doctor -v` to
`dist/doctor.txt`. `dist/champions-metadesk-linux-x64.tar.gz` is the release archive: the app, its icons,
and `install.sh` (installs into `~/.local` with a menu entry, no sudo; `--uninstall` removes it).

**What to send back after a test build:** `dist/build-linux.log`, `dist/doctor.txt`, the app's
`app.log` from its first launch (Settings › About › Log file; its `Runtime:` line records what the
built app's host provides), and whether the dock shows the crimson tile.

### macOS and Windows

`scripts/build_desktop.sh macos` (Xcode and CocoaPods installed) builds `dist/macos/ChampionsMetaDeskStudio.app`;
`scripts/build_desktop.sh windows` from Git Bash (Visual Studio with "Desktop development with C++") builds
`dist/windows/`. The release workflow signs and zips both.

### How a built app differs from a run from source
- It is detected by `FLET_PLATFORM`, which the Flutter host sets (`config.EMBEDDED`). It keeps its data in
  the same per-user folder as the `flet pack` builds, so switching keeps the user's data.
- `--cli` and `--web` aren't available in it (use a run from source or a pip install).
- Sprites come from the CDN (`PCPT_SPRITE_SRC=remote`): the host serves its own bundled assets, not the
  sprite cache. `PCPT_SPRITE_SRC=file` shows cached sprites by file path instead, if that works on the platform.
- On Linux it writes a hidden `io.metadesk.champ.desktop` and the icon, unless `install.sh` made a real
  menu entry, since `flet build` provides no Linux desktop entry of its own.

### Troubleshooting
| Symptom | What to do |
|---|---|
| CMake or `gtk/gtk.h` errors | Flutter's Linux toolchain is incomplete: run `scripts/flet_build_prereqs.sh` again |
| `flutter doctor` lists missing pieces | `dist/doctor.txt` says which; install them and rebuild |
| A stale or broken template | `poetry run flet build linux --clear-cache --yes` |
| The window opens without the icon in the dock | Log out and back in once (the desktop caches icons); check `~/.local/share/applications/io.metadesk.champ.desktop` |

---

## 3. Legacy: Native Build with `flet pack`

To build a standalone executable directly on your development machine:

### Prerequisites
* Python `>=3.13,<3.16`
* [Poetry](https://python-poetry.org/) package manager

### Build Commands

```bash
# 1. Install dependencies
poetry install

# 2. Build for your operating system:

# Linux:
poetry run flet pack run.py -n "champions-metadesk" --product-name "Champions MetaDesk Studio" \
  --add-data "src/pokemon_champions_planning_tool/data:pokemon_champions_planning_tool/data" \
  --add-data "src/pokemon_champions_planning_tool/domain/damage/reference_data.json:pokemon_champions_planning_tool/domain/damage" -y

# Windows (PowerShell):
poetry run flet pack run.py -n "champions-metadesk" --product-name "Champions MetaDesk Studio" `
  --add-data "src/pokemon_champions_planning_tool/data;pokemon_champions_planning_tool/data" `
  --add-data "src/pokemon_champions_planning_tool/domain/damage/reference_data.json;pokemon_champions_planning_tool/domain/damage" -y

# macOS:
poetry run flet pack run.py -n "ChampionsMetaDeskStudio" --product-name "Champions MetaDesk Studio" \
  --bundle-id "com.champions.metadesk" \
  --add-data "src/pokemon_champions_planning_tool/data:pokemon_champions_planning_tool/data" \
  --add-data "src/pokemon_champions_planning_tool/domain/damage/reference_data.json:pokemon_champions_planning_tool/domain/damage" -y
```

The resulting binary will be placed in the `dist/` directory.

---

## 4. Cross-Compiling Windows Executables (`.exe`) via Docker

If you are developing on a Linux host system and need to build a native standalone Windows `.exe` binary locally without a Windows machine:

### Prerequisites
* [Docker Engine](https://docs.docker.com/engine/install/) or Docker Desktop running on your host system.

### Build Step
```bash
./scripts/build_windows_docker.sh
```

The container downloads all Windows-compatible wheels, installs them into a headless Wine Python runtime, runs PyInstaller, and extracts `dist/ChampionsMetaDeskStudio.exe`.

---

## 5. Configuration & Database Behavior in Frozen Builds

When running the standalone executable:

* **Data folder**: A frozen build (`sys.frozen`) keeps `pokemon_champions.db`, `preferences.json`, `logs/` and the sprite cache in the per-user folder from `config.user_data_dir()`: `%LOCALAPPDATA%\Champions MetaDesk Studio` on Windows, `~/Library/Application Support/Champions MetaDesk Studio` on macOS, `$XDG_DATA_HOME` or `~/.local/share/champions-metadesk-studio` on Linux. `storage.prepare_data_dir()` creates it at launch. A run from source keeps the working directory. `PCPT_DATABASE` overrides the database path in both.
* **Older data**: On the first launch with an empty data folder, `storage.migrate_legacy_data()` copies a `pokemon_champions.db` found in the launch folder or beside the executable (through SQLite's backup API, so changes still in its `-wal` file come along) plus its `preferences.json`, and leaves the originals in place. A failed copy is logged and the app starts fresh.
* **Exports**: Box exports and the CSV go to `~/Downloads` (the home folder if there is none).
* **User Preferences**: Configuration and UI settings are persisted to `preferences.json` beside the database file.
* **Seed Data**: Tournaments and reference damage calculation assets are unpacked from the bundled archive automatically on first launch.

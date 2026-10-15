# Packaging and Building Executables

This document describes how to package **Champions MetaDesk Studio** into standalone executables across Windows, Linux, and macOS using GitHub Actions, local `flet pack`, or Docker.

---

## 1. Automated Multi-Platform Releases (GitHub Actions)

The repository includes a GitHub Actions workflow at [`.github/workflows/release.yml`](../.github/workflows/release.yml) that builds standalone executables across all three major platforms whenever a Git version tag is published. It runs in three stages:

1. **verify**: fails unless the tag matches the version in `pyproject.toml` and the package `__version__`, runs the test suite, and checks that CHANGELOG.md has a section for the version.
2. **build**: the three platform builds below, stamped with the version.
3. **publish**: once all three succeed, creates one GitHub release named after the tag, with that CHANGELOG.md section as its notes and the three archives attached. Versions with a suffix (`1.0.0-rc.1`) are marked as pre-releases.

Running the workflow by hand (*Run workflow* in the Actions tab) builds and uploads the archives as workflow artifacts without publishing anything.

### Matrix Build Configuration
* **Windows** (`windows-latest`): Builds `champions-metadesk.exe` and packages it into `champions-metadesk-windows-x64.zip`.
* **Linux** (`ubuntu-latest`): Builds the Linux standalone binary and packages it into `champions-metadesk-linux-x64.tar.gz`.
* **macOS** (`macos-latest`): Builds the `ChampionsMetaDeskStudio.app` bundle and packages it into `champions-metadesk-macos.zip`.

### Publishing a Release

Run `poetry run python scripts/release.py prepare minor` from an up-to-date `main`.
It bumps the version, writes the changelog, tags, and pushes the tag that starts this
workflow. The full procedure, and how to write the release description, is in
**[releasing.md](releasing.md)**.

Do not create the tag or the release in the GitHub web UI: the tag would skip the
version and changelog checks, and a hand-made release can collide with the one the
workflow publishes.

---

## 2. Native Build on Current Host OS (`flet pack`)

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

## 3. Cross-Compiling Windows Executables (`.exe`) via Docker

If you are developing on a Linux host system and need to build a native standalone Windows `.exe` binary locally without a Windows machine:

### Prerequisites
* [Docker Engine](https://docs.docker.com/engine/install/) or Docker Desktop running on your host system.

### Build Step
```bash
./scripts/build_windows_docker.sh
```

The container downloads all Windows-compatible wheels, installs them into a headless Wine Python runtime, runs PyInstaller, and extracts `dist/ChampionsMetaDeskStudio.exe`.

---

## 4. Configuration & Database Behavior in Frozen Builds

When running the standalone executable:

* **Data folder**: A frozen build (`sys.frozen`) keeps `pokemon_champions.db`, `preferences.json`, `logs/` and the sprite cache in the per-user folder from `config.user_data_dir()`: `%LOCALAPPDATA%\Champions MetaDesk Studio` on Windows, `~/Library/Application Support/Champions MetaDesk Studio` on macOS, `$XDG_DATA_HOME` or `~/.local/share/champions-metadesk-studio` on Linux. `storage.prepare_data_dir()` creates it at launch. A run from source keeps the working directory. `PCPT_DATABASE` overrides the database path in both.
* **Older data**: On the first launch with an empty data folder, `storage.migrate_legacy_data()` copies a `pokemon_champions.db` found in the launch folder or beside the executable (through SQLite's backup API, so changes still in its `-wal` file come along) plus its `preferences.json`, and leaves the originals in place. A failed copy is logged and the app starts fresh.
* **Exports**: Box exports and the CSV go to `~/Downloads` (the home folder if there is none).
* **User Preferences**: Configuration and UI settings are persisted to `preferences.json` beside the database file.
* **Seed Data**: Tournaments and reference damage calculation assets are unpacked from the bundled archive automatically on first launch.

# Packaging and Building Executables

This document describes how to package **Champions MetaDesk Studio** into standalone executables across Windows, Linux, and macOS using GitHub Actions, local `flet pack`, or Docker.

---

## 1. Automated Multi-Platform Releases (GitHub Actions)

The repository includes a GitHub Actions workflow at [`.github/workflows/release.yml`](../.github/workflows/release.yml) that builds standalone executables across all three major platforms whenever a Git version tag is published.

### Matrix Build Configuration
* **Windows** (`windows-latest`): Builds `champions-metadesk.exe` and packages it into `champions-metadesk-windows-x64.zip`.
* **Linux** (`ubuntu-latest`): Builds the Linux standalone binary and packages it into `champions-metadesk-linux-x64.tar.gz`.
* **macOS** (`macos-latest`): Builds the `ChampionsMetaDeskStudio.app` bundle and packages it into `champions-metadesk-macos.zip`.

### Publishing a Release
```bash
git tag v0.1.0
git push origin v0.1.0
```
Or draft a release via the GitHub Web UI. Once the workflow completes, all 3 archives are automatically attached as assets to the release.

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

* **Database Storage**: The application connects to `pokemon_champions.db`. You can override the database path by setting the `PCPT_DATABASE` environment variable.
* **User Preferences**: Configuration and UI settings are persisted to `preferences.json` beside the database file.
* **Seed Data**: Tournaments and reference damage calculation assets are unpacked from the bundled archive automatically on first launch.

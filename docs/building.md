# Packaging and Building Executables

This document describes how to package the **Pokemon Champions Planning Tool** into standalone executables for native host environments (Linux / macOS / Windows) and cross-compile portable Windows `.exe` binaries from Linux using Docker and Wine.

---

## 1. Native Build (Host OS)

To build a single-file executable directly on your current host operating system (Linux, macOS, or Windows):

### Prerequisites
* Python `>=3.13,<3.16`
* [Poetry](https://python-poetry.org/) package manager

### Build Steps

1. Install project dependencies (including development tools):
   ```bash
   poetry install
   ```

2. Run PyInstaller using the project specification file:
   ```bash
   poetry run pyinstaller pokemon_champions.spec --noconfirm --clean
   ```

3. The generated executable will be placed in the `dist/` directory:
   * **Linux**: `dist/PokemonChampionsPlanningTool`
   * **Windows**: `dist/PokemonChampionsPlanningTool.exe`
   * **macOS**: `dist/PokemonChampionsPlanningTool` (or `.app` bundle)

---

## 2. Cross-Compiling Windows Executables (`.exe`) via Docker

If you are developing on a Linux host system and need to build a native standalone Windows `.exe` binary, use the automated Docker + Wine pipeline provided in `scripts/build_windows_docker.sh`.

### Prerequisites
* [Docker Engine](https://docs.docker.com/engine/install/) or Docker Desktop installed and running on your host system.

### Build Step

Run the provided automation script from the root of the repository:

```bash
./scripts/build_windows_docker.sh
```

### How the Docker Cross-Compilation Works

The automated script builds a container image (`pcpt-windows-builder`) defined in `Dockerfile.windows`:

1. **Environment Setup**: Uses Ubuntu 24.04 with headless Wine (`xvfb-run`), Python 3.13 Windows Embeddable runtime, and Linux Python.
2. **Offline Dependency Wheel Resolution**: Due to Wine network socket constraints, the host Linux container pre-downloads all Windows-target `.whl` dependencies (including PyInstaller, SQLModel, Flet, requests, etc.) into `/tmp/wheels`.
3. **Offline Installation**: Windows Python inside Wine installs all pre-downloaded wheels locally without requiring network sockets.
4. **Binary Packaging**: PyInstaller compiles `pokemon_champions.spec` inside Wine into a single-file `PokemonChampionsPlanningTool.exe`.
5. **Output Export**: The container automatically copies the compiled binary to `dist/PokemonChampionsPlanningTool.exe` on your host machine using mounted volume labeling (`:z` flag for SELinux compatibility).

---

## 3. Configuration & Database Behavior in Frozen Builds

When running the compiled executable:

* **Database Storage**: The executable reads `PCPT_DATABASE` environment variable if set. By default, it creates/uses `pokemon_champions.db` in the active working directory or user data folder.
* **User Preferences**: Saved to `preferences.json` beside the database file.

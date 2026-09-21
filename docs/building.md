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

Use `scripts/release.py` from an up-to-date, clean `main`:

```bash
poetry run python scripts/release.py prepare minor --dry-run   # preview the version and notes
poetry run python scripts/release.py prepare minor             # 0.1.0 -> 0.2.0
```

`prepare` takes `patch`, `minor`, `major`, or an explicit version such as `1.0.0-rc.1`. It:

1. refuses to run off `main`, with uncommitted changes, behind `origin`, or if the tag exists;
2. runs the test suite;
3. writes the version into `pyproject.toml` and `src/pokemon_champions_planning_tool/__init__.py`;
4. moves the **Unreleased** section of `CHANGELOG.md` under the new version. If
   Unreleased is empty, it generates the section from the Conventional Commit subjects
   (`feat`, `fix`, `perf`, `refactor`, `docs`, breaking changes) since the last tag. With
   `$EDITOR` set, it offers to open the changelog first;
5. commits `chore(release): vX.Y.Z` and creates an annotated tag carrying the notes;
6. asks, then pushes `main` and the tag together (`git push --atomic`), which starts
   the workflow.

Options: `--no-push` stops after the local commit and tag, `--skip-tests`, and `--yes`
answers every question (for scripted use). If anything fails before the commit, the
files are restored. Until the push nothing has left your machine, and
`git tag -d vX.Y.Z && git reset --hard HEAD~1` undoes the release commit.

Good practice between releases: add user-facing entries under **Unreleased** in
`CHANGELOG.md` as changes land, and write commit subjects as Conventional Commits
(`type(scope): summary`). After the workflow finishes, download at least one archive
and check that it starts.

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

* **Database Storage**: The application connects to `pokemon_champions.db`. You can override the database path by setting the `PCPT_DATABASE` environment variable.
* **User Preferences**: Configuration and UI settings are persisted to `preferences.json` beside the database file.
* **Seed Data**: Tournaments and reference damage calculation assets are unpacked from the bundled archive automatically on first launch.

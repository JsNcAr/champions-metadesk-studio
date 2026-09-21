# Releasing

How to publish a new version of Champions MetaDesk Studio, and how to write the
description people read on the release page.

## How a release is put together

```text
CHANGELOG.md "Unreleased"  ──►  scripts/release.py prepare  ──►  commit + tag vX.Y.Z  ──►  push
                                                                                           │
GitHub release (notes + 3 archives)  ◄──  publish  ◄──  build ×3  ◄──  verify  ◄───────────┘
```

- **The description** is the `## [Unreleased]` section of [CHANGELOG.md](../CHANGELOG.md).
  The release script renames it to the version, and the workflow publishes that section
  as the release notes, word for word.
- **The script** (`scripts/release.py`) bumps the version, updates the changelog,
  commits, tags, and pushes.
- **The workflow** (`.github/workflows/release.yml`) runs on the pushed tag in three
  stages:
  1. **verify**: the tag matches the version, the tests pass, and the notes exist.
  2. **build**: Linux, Windows and macOS, in parallel.
  3. **publish**: one GitHub release, created only when all three builds succeed.

## Choosing the version

The project follows [Semantic Versioning](https://semver.org/). While the version is
`0.x`:

| Release contains | Command | Example |
|---|---|---|
| Only bug fixes | `prepare patch` | 0.2.0 → 0.2.1 |
| New features, improvements, or anything user-visible beyond fixes | `prepare minor` | 0.2.1 → 0.3.0 |
| A break, such as a database or file format older versions cannot read, or removed features | `prepare minor`, with the break under **Breaking changes** | 0.3.0 → 0.4.0 |
| First stable release | `prepare 1.0.0` | 0.9.0 → 1.0.0 |

From 1.0.0 on, breaking changes take `prepare major`.

For a test build ahead of a release, give an explicit pre-release version:
`prepare 1.0.0-rc.1`. It is published as a **pre-release**, so GitHub does not show it
as "Latest". A later `prepare patch|minor|major` from `1.0.0-rc.N` finishes it as `1.0.0`.

## Step by step

### 1. Write the release description

Make sure the **Unreleased** section of `CHANGELOG.md` describes everything since the
last release (see [Writing the release description](#writing-the-release-description)).
Ideally each PR already added its own entry, so this is a final read-through. Merge any
edits to `main` like any other change.

### 2. Check `main`

```bash
git switch main
git pull
poetry run python -m unittest discover -s tests
```

Optionally build for your own platform (see [building.md](building.md#2-native-build-on-current-host-os-flet-pack))
and start the executable from a folder other than the repository, to catch packaging
problems before CI does.

### 3. Preview

```bash
poetry run python scripts/release.py prepare minor --dry-run
```

This prints the new version, the notes exactly as they will be published, and any local
commits that would be pushed with them. It changes nothing.

### 4. Release

```bash
poetry run python scripts/release.py prepare minor
```

The script:

1. Refuses to continue if you are not on `main`, have uncommitted changes, are behind
   `origin/main`, or the tag already exists.
2. Runs the test suite.
3. Writes the version into `pyproject.toml` and `src/pokemon_champions_planning_tool/__init__.py`.
4. Moves the Unreleased notes under `## [X.Y.Z] - <today>`, leaving Unreleased empty.
5. If `$EDITOR` (or `$VISUAL`) is set, offers to open `CHANGELOG.md` for a last edit.
6. Asks, then commits `chore(release): vX.Y.Z` and creates an annotated tag holding the notes.
7. Asks, then pushes `main` and the tag in one atomic push, which starts the workflow.

Answer **no** at the push question, or pass `--no-push`, to stop with everything still
local. Push later with the command it prints, or undo with:

```bash
git tag -d vX.Y.Z && git reset --hard HEAD~1
```

Other options:
- `--skip-tests`: only when you have just run them.
- `--yes`: answers every question, for scripted use.

### 5. Watch the workflow

Open the repository's **Actions** tab. The release appears under **Releases** when the
*publish* job finishes, after about as long as the slowest platform build.

### 6. Check the published release

- The notes read correctly and the three archives are attached.
- Download at least one archive, start it, and confirm **Settings → About** shows the new version.

## Writing the release description

### Where it lives and when to write it

Everything under `## [Unreleased]` in `CHANGELOG.md` becomes the release description.
Add entries **in the same PR as the change**, while you still remember why it matters.
Writing a whole release's notes from memory at release time is how entries get lost.

If Unreleased is empty at release time, the script generates the notes from the commit
subjects (see [Generated notes](#generated-notes)). That fallback is complete but
terse, so prefer written notes for anything users will read.

### Structure

Use `###` headings, in this order, and leave out any that would be empty:

| Heading | For |
|---|---|
| `### Breaking changes` | Anything that stops working the way it used to, plus what to do about it |
| `### Added` | New features |
| `### Changed` | Changes to existing behaviour |
| `### Performance` | Faster or lighter, with a number when you measured one |
| `### Fixed` | Bugs fixed |
| `### Removed` | Features taken out |
| `### Security` | Vulnerability fixes |
| `### Documentation` | Docs users would care about; not internal notes |

You may put one or two plain sentences above the first heading to summarise the
release. That text is published too.

### Style

- **Write for someone using the app, not for the code.** Say what they will notice:
  "Switching between sections is near-instant" rather than "isolate views in the shell".
- **One entry per change, one or two lines.** Start with the thing that changed. Leave
  the reasoning to the PR.
- **Fixed entries describe the problem that is gone.** "'Sync sprites' failed on any
  non-empty box." Readers look for the symptom they hit.
- **Numbers when you have them, measured and honest.** "~2.4 s → ~0.35 s", not "much faster".
- **Name UI the way the app does:** *Box*, *Teams*, *Meta*, *Calc*, *Settings → About*.
- **Breaking changes say what to do.** "Existing databases are migrated on first launch;
  back up `pokemon_champions.db` first if you want to go back to 0.2."
- **Link issues or PRs when they exist:** `(#12)`.
- **Leave out housekeeping:** refactors with no visible effect, CI, tests, dependency
  bumps, unless one changes behaviour.

Example:

```markdown
## [Unreleased]

Faster everywhere, and sprites finally work in the browser build.

### Performance
- Switching between Box, Teams, Meta and Calc is near-instant and crossfades.
- Box filter results appear ~0.35 s after you stop typing instead of ~2.4 s.

### Fixed
- "Sync sprites" in Settings failed on any non-empty box.
- Keyboard focus (Tab) could land in the Box while another section was on screen.
```

Avoid:

```markdown
- perf(shell): isolate views and skip Flet auto-updates      ← commit subject, internal names
- Fixed a bug                                                  ← which one? what did users see?
- Improved performance                                         ← of what, by how much?
```

### Generated notes

With Unreleased empty, `prepare` builds the notes from the commit subjects since the
last tag. It reads subjects written as [Conventional Commits](https://www.conventionalcommits.org/),
`type(scope): summary`:

| Commit type | Published under |
|---|---|
| `feat` | Added |
| `fix` | Fixed |
| `perf` | Performance |
| `refactor` | Changed |
| `docs` | Documentation |
| `!` after the type (`feat!:`), or `BREAKING CHANGE:` in the body | Breaking changes |
| `chore`, `ci`, `test`, `build`, `style`, merges, other subjects | left out |

Each entry is the summary with its scope in bold and the short commit hash. The
fallback is only as good as the subjects, so write summaries a user could understand.

### Changing notes later

- **Before committing:** accept the script's offer to open `CHANGELOG.md` in `$EDITOR`.
- **After committing, before pushing:** undo (`git tag -d vX.Y.Z && git reset --hard HEAD~1`),
  fix Unreleased, and run `prepare` again.
- **After publishing:** fix the version's section in `CHANGELOG.md` through a normal PR,
  then update the release page to match:

  ```bash
  python scripts/release.py notes X.Y.Z > notes.md
  gh release edit vX.Y.Z --notes-file notes.md
  ```

  Or paste the section into **Edit release** on GitHub. The annotated tag keeps the
  original text; that is expected.

## Troubleshooting

| Problem | What to do |
|---|---|
| `prepare` says `main` is behind `origin/main` | `git pull`, then run it again. |
| `prepare` says "nothing to release" | Unreleased is empty and no `feat`, `fix`, `perf`, `refactor` or `docs` commits exist since the last tag. Write the notes under Unreleased. |
| The push was rejected (for example, branch protection on `main`) | Nothing was pushed, because the push is atomic. Either allow the push, or push the release commit through a PR and push the tag after merging: `git push origin vX.Y.Z` (the tag must point at the merged commit). |
| *verify* fails on the version check | The tag was not made by the script, or the version files were edited by hand. Delete the tag (`git push --delete origin vX.Y.Z && git tag -d vX.Y.Z`), fix, and release again. Nothing was published. |
| One *build* job fails | Nothing is published. If it was a flaky runner, use **Re-run failed jobs** on the workflow run. If the code is at fault, fix it on `main`, delete the tag as above, and release the next patch version rather than reusing the number. |
| *publish* fails | Re-run the failed job; the archives from the builds are reused. |

Never re-point or reuse a tag that has a published release. Anyone who already
downloaded it would have a different build under the same version. Release the next
patch version instead.

## Hotfixes

For an urgent fix: merge the fix to `main` with a `### Fixed` entry under Unreleased,
then `prepare patch`. Everything else on `main` since the last release ships with it.
Release often enough that `main` is never far from releasable.

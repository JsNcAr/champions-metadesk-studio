"""Cut a release: bump the version, write the changelog, tag, and push.

Pushing a ``v*`` tag starts ``.github/workflows/release.yml``, which runs the tests,
checks the tag against ``pyproject.toml``, builds Linux, Windows and macOS, and
publishes a GitHub release whose notes are this version's CHANGELOG.md section.

    poetry run python scripts/release.py prepare minor          # 0.1.0 -> 0.2.0
    poetry run python scripts/release.py prepare patch --dry-run
    poetry run python scripts/release.py prepare 1.0.0-rc.1     # explicit; a pre-release

``prepare`` refuses to run unless you are on an up-to-date, clean ``main``. It runs the
test suite, writes the version into ``pyproject.toml`` and the package ``__version__``,
and adds a CHANGELOG.md section. That section is whatever you wrote under
``## [Unreleased]``, or, if that is empty, one generated from the Conventional Commit
subjects since the last tag. It then commits ``chore(release): vX.Y.Z``, creates an
annotated tag carrying the notes, and asks before pushing both in one atomic push.
Until that push nothing has left your machine; undo it with
``git tag -d vX.Y.Z && git reset --hard HEAD~1``.

Used by CI:

    python scripts/release.py check-version v0.2.0   # exit 1 unless pyproject says 0.2.0
    python scripts/release.py notes 0.2.0             # print that CHANGELOG section
    python scripts/release.py version                 # print the project version

Standard library only, so CI can run it before installing anything.
"""

from __future__ import annotations

import argparse
import datetime as dt
import os
import re
import shlex
import subprocess
import sys
from dataclasses import dataclass
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
PYPROJECT = ROOT / "pyproject.toml"
PACKAGE_INIT = ROOT / "src" / "pokemon_champions_planning_tool" / "__init__.py"
CHANGELOG = ROOT / "CHANGELOG.md"
RELEASE_BRANCH = "main"
REMOTE = "origin"

# X.Y.Z with an optional pre-release suffix (1.0.0-rc.1). No build metadata: it has no
# meaning in a tag and PEP 440 cannot express it.
VERSION_RE = re.compile(r"^(\d+)\.(\d+)\.(\d+)(?:-([0-9A-Za-z.-]+))?$")
UNRELEASED = "## [Unreleased]"

CHANGELOG_HEADER = """# Changelog

All notable changes to Champions MetaDesk Studio. The format follows
[Keep a Changelog](https://keepachangelog.com/en/1.1.0/) and the project uses
[Semantic Versioning](https://semver.org/spec/v2.0.0.html).

Add entries under **Unreleased** in the same PR as the change; that section becomes
the next release's description. See [docs/releasing.md](docs/releasing.md#writing-the-release-description)
for the headings and style.

"""

# Conventional Commit type -> changelog heading, in display order. Types not listed
# (chore, ci, test, build, style) are housekeeping and left out of the notes.
SECTIONS = {
    "feat": "Added",
    "refactor": "Changed",
    "perf": "Performance",
    "fix": "Fixed",
    "docs": "Documentation",
}
BREAKING = "Breaking changes"
COMMIT_RE = re.compile(r"^(?P<type>[a-z]+)(?:\((?P<scope>[^)]+)\))?(?P<bang>!)?: (?P<desc>.+)$")


class ReleaseError(Exception):
    """A precondition failed; the message says what to do about it."""


# -- versions ---------------------------------------------------------------------------


def parse_version(text: str) -> tuple[int, int, int, str | None]:
    match = VERSION_RE.match(text.strip())
    if not match:
        raise ReleaseError(f"not a version: {text!r} (expected X.Y.Z or X.Y.Z-rc.N)")
    major, minor, patch, pre = match.groups()
    return int(major), int(minor), int(patch), pre


def bump(current: str, part: str) -> str:
    """``part`` is patch, minor, major, or an explicit version."""
    if part not in ("patch", "minor", "major"):
        parse_version(part)
        if _sort_key(part) <= _sort_key(current):
            raise ReleaseError(f"{part} is not newer than the current {current}")
        return part
    major, minor, patch, pre = parse_version(current)
    if pre:
        # 1.0.0-rc.2 -> 1.0.0 whatever the part: finishing a pre-release.
        return f"{major}.{minor}.{patch}"
    if part == "major":
        return f"{major + 1}.0.0"
    if part == "minor":
        return f"{major}.{minor + 1}.0"
    return f"{major}.{minor}.{patch + 1}"


def _sort_key(version: str) -> tuple:
    major, minor, patch, pre = parse_version(version)
    # A pre-release sorts before its release (1.0.0-rc.1 < 1.0.0).
    return major, minor, patch, pre is None, pre or ""


def is_prerelease(version: str) -> bool:
    return parse_version(version)[3] is not None


def read_version(pyproject: str) -> str:
    match = re.search(r'(?m)^\[project\][^\[]*?^version\s*=\s*"([^"]+)"', pyproject, re.S)
    if not match:
        raise ReleaseError("no version under [project] in pyproject.toml")
    return match.group(1)


def write_version(pyproject: str, version: str) -> str:
    updated, count = re.subn(
        r'(?ms)(^\[project\][^\[]*?^version\s*=\s*")[^"]+(")', rf"\g<1>{version}\g<2>", pyproject, count=1
    )
    if count != 1:
        raise ReleaseError("could not update the version in pyproject.toml")
    return updated


def write_package_version(init_text: str, version: str) -> str:
    updated, count = re.subn(r'(?m)^__version__\s*=\s*"[^"]*"', f'__version__ = "{version}"', init_text, count=1)
    if count != 1:
        raise ReleaseError(f"no __version__ line in {PACKAGE_INIT.relative_to(ROOT)}")
    return updated


# -- changelog --------------------------------------------------------------------------


@dataclass(frozen=True)
class Commit:
    sha: str
    subject: str
    body: str = ""


def render_section(commits: list[Commit]) -> str:
    """Changelog entries grouped by Conventional Commit type; '' if nothing to list."""
    groups: dict[str, list[str]] = {}
    for commit in commits:
        match = COMMIT_RE.match(commit.subject)
        if not match:
            continue   # not conventional (merges and the like): nothing to classify it by
        kind, scope, desc = match["type"], match["scope"], match["desc"]
        if kind == "chore" and scope == "release":
            continue
        breaking = bool(match["bang"]) or "BREAKING CHANGE:" in commit.body
        heading = BREAKING if breaking else SECTIONS.get(kind)
        if heading is None:
            continue
        prefix = f"**{scope}:** " if scope else ""
        groups.setdefault(heading, []).append(f"- {prefix}{desc} ({commit.sha[:7]})")
    order = [BREAKING, *SECTIONS.values()]
    parts = [f"### {h}\n" + "\n".join(groups[h]) for h in order if h in groups]
    return "\n\n".join(parts)


def split_unreleased(changelog: str) -> tuple[str, str, str]:
    """(text before the Unreleased heading, its body, text from the next section on)."""
    start = changelog.find(UNRELEASED)
    if start < 0:
        raise ReleaseError(f"CHANGELOG.md has no '{UNRELEASED}' heading")
    body_start = start + len(UNRELEASED)
    next_heading = re.search(r"(?m)^## ", changelog[body_start:])
    end = body_start + next_heading.start() if next_heading else len(changelog)
    return changelog[:start], changelog[body_start:end].strip(), changelog[end:]


def add_release(changelog: str, version: str, generated: str, date: dt.date) -> tuple[str, str]:
    """Insert the version's section and empty Unreleased. Returns (changelog, notes)."""
    head, unreleased, rest = split_unreleased(changelog)
    notes = unreleased or generated
    if not notes:
        raise ReleaseError(
            "nothing to release: Unreleased in CHANGELOG.md is empty and no feat/fix/perf/"
            "refactor/docs commits since the last tag. Write the notes under Unreleased."
        )
    section = f"## [{version}] - {date.isoformat()}\n\n{notes}\n\n"
    updated = f"{head}{UNRELEASED}\n\n{section}{rest.lstrip()}"
    return updated.rstrip() + "\n", notes


def release_notes(changelog: str, version: str) -> str:
    """The body of ``## [version]`` in CHANGELOG.md."""
    match = re.search(rf"(?m)^## \[{re.escape(version)}\][^\n]*\n", changelog)
    if not match:
        raise ReleaseError(f"CHANGELOG.md has no section for {version}")
    following = re.search(r"(?m)^## ", changelog[match.end():])
    end = match.end() + following.start() if following else len(changelog)
    return changelog[match.end():end].strip()


# -- git --------------------------------------------------------------------------------


def git(*args: str, check: bool = True) -> str:
    result = subprocess.run(["git", *args], cwd=ROOT, capture_output=True, text=True)
    if check and result.returncode != 0:
        raise ReleaseError(f"git {' '.join(args)} failed:\n{result.stderr.strip()}")
    return result.stdout.strip()


def last_tag() -> str | None:
    tag = git("describe", "--tags", "--abbrev=0", "--match", "v[0-9]*", check=False)
    return tag or None


def commits_since(tag: str | None) -> list[Commit]:
    span = f"{tag}..HEAD" if tag else "HEAD"
    raw = git("log", span, "--no-merges", "--reverse", "--format=%H%x1f%s%x1f%b%x1e")
    commits = []
    for record in raw.split("\x1e"):
        if record.strip():
            sha, subject, body = (record.strip("\n").split("\x1f") + ["", ""])[:3]
            commits.append(Commit(sha, subject, body))
    return commits


def preflight(tag: str, *, allow_branch: bool) -> None:
    branch = git("rev-parse", "--abbrev-ref", "HEAD")
    if branch != RELEASE_BRANCH and not allow_branch:
        raise ReleaseError(f"releases are cut from {RELEASE_BRANCH}; you are on {branch}")
    if git("status", "--porcelain"):
        raise ReleaseError("the working tree has uncommitted changes; commit or stash them first")
    git("fetch", "--tags", REMOTE)
    upstream = f"{REMOTE}/{branch}"
    behind = git("rev-list", "--count", f"HEAD..{upstream}", check=False)
    if behind and behind != "0":
        raise ReleaseError(f"{branch} is {behind} commit(s) behind {upstream}; pull first")
    if git("tag", "--list", tag):
        raise ReleaseError(f"tag {tag} already exists")
    if git("ls-remote", "--tags", REMOTE, f"refs/tags/{tag}"):
        raise ReleaseError(f"tag {tag} already exists on {REMOTE}")


def unpushed_commits(branch: str) -> list[str]:
    out = git("log", "--oneline", f"{REMOTE}/{branch}..HEAD", check=False)
    return out.splitlines() if out else []


# -- commands ---------------------------------------------------------------------------


def confirm(question: str, assume_yes: bool) -> bool:
    if assume_yes:
        return True
    if not sys.stdin.isatty():
        raise ReleaseError(f"{question} needs an answer; rerun with --yes to proceed non-interactively")
    return input(f"{question} [y/N] ").strip().lower() in ("y", "yes")


def run_tests() -> None:
    print("Running the test suite…")
    result = subprocess.run([sys.executable, "-m", "unittest", "discover", "-s", "tests", "-q"], cwd=ROOT)
    if result.returncode != 0:
        raise ReleaseError("tests failed; nothing was changed")


def cmd_prepare(args: argparse.Namespace) -> None:
    current = read_version(PYPROJECT.read_text())
    version = bump(current, args.part)
    tag = f"v{version}"
    preflight(tag, allow_branch=args.allow_branch)

    previous = last_tag()
    generated = render_section(commits_since(previous))
    changelog = CHANGELOG.read_text() if CHANGELOG.exists() else CHANGELOG_HEADER + UNRELEASED + "\n"
    new_changelog, notes = add_release(changelog, version, generated, dt.date.today())

    print(f"\nRelease {tag} (from {current}, changes since {previous or 'the first commit'})"
          f"{'  [pre-release]' if is_prerelease(version) else ''}\n")
    print(notes, "\n")
    branch = git("rev-parse", "--abbrev-ref", "HEAD")
    extra = unpushed_commits(branch)
    if extra:
        print(f"Also pushed with it: {len(extra)} commit(s) not yet on {REMOTE}/{branch}:")
        print("\n".join(f"  {line}" for line in extra), "\n")

    if args.dry_run:
        print("Dry run: nothing written.")
        return
    if not args.skip_tests:
        run_tests()

    files = {
        PYPROJECT: write_version(PYPROJECT.read_text(), version),
        PACKAGE_INIT: write_package_version(PACKAGE_INIT.read_text(), version),
        CHANGELOG: new_changelog,
    }
    originals = {path: path.read_text() if path.exists() else None for path in files}
    try:
        for path, text in files.items():
            path.write_text(text)
        editor = os.environ.get("VISUAL") or os.environ.get("EDITOR")
        if editor and not args.yes and sys.stdin.isatty() and confirm("Edit CHANGELOG.md before committing?", False):
            subprocess.run([*shlex.split(editor), str(CHANGELOG)], check=True)
            notes = release_notes(CHANGELOG.read_text(), version)
        if not confirm(f"Commit and tag {tag}?", args.yes):
            raise ReleaseError("stopped before committing")
        git("add", *(str(path.relative_to(ROOT)) for path in files))
        git("commit", "-m", f"chore(release): {tag}")
    except BaseException:
        for path, text in originals.items():
            if text is None:
                path.unlink(missing_ok=True)
            else:
                path.write_text(text)
        git("reset", "-q", "--", *(str(path.relative_to(ROOT)) for path in files), check=False)
        print("The version files were restored; nothing was committed.")
        raise
    git("tag", "-a", tag, "-m", f"{tag}\n\n{notes}")
    print(f"Committed and tagged {tag} locally.")

    push = ["push", "--atomic", REMOTE, branch, tag]
    if args.no_push or not confirm(f"Push {branch} and {tag} to {REMOTE} (starts the release build)?", args.yes):
        print(f"Not pushed. When ready:  git {' '.join(push)}")
        print(f"To undo instead:         git tag -d {tag} && git reset --hard HEAD~1")
        return
    git(*push)
    print(f"Pushed. The release build is running: https://github.com/{repo_slug()}/actions")


def repo_slug() -> str:
    url = git("remote", "get-url", REMOTE, check=False)
    match = re.search(r"github\.com[:/](.+?)(?:\.git)?$", url)
    return match.group(1) if match else "<owner>/<repo>"


def cmd_notes(args: argparse.Namespace) -> None:
    print(release_notes(CHANGELOG.read_text(), args.version.removeprefix("v")))


def cmd_check_version(args: argparse.Namespace) -> None:
    version = read_version(PYPROJECT.read_text())
    tag_version = args.tag.removeprefix("refs/tags/").removeprefix("v")
    package = re.search(r'(?m)^__version__\s*=\s*"([^"]*)"', PACKAGE_INIT.read_text())
    problems = []
    if tag_version != version:
        problems.append(f"tag {args.tag} does not match pyproject.toml version {version}")
    if not package or package.group(1) != version:
        problems.append(f"__version__ in {PACKAGE_INIT.relative_to(ROOT)} does not match {version}")
    if problems:
        raise ReleaseError("; ".join(problems))
    print(f"ok: {version}{' (pre-release)' if is_prerelease(version) else ''}")
    # Lets a workflow step read these as outputs.
    if output := os.environ.get("GITHUB_OUTPUT"):
        with open(output, "a", encoding="utf-8") as fh:
            write_outputs(fh, version)


def write_outputs(fh, version: str) -> None:
    major, minor, patch, _pre = parse_version(version)
    fh.write(f"version={version}\nnumeric={major}.{minor}.{patch}\n"
             f"prerelease={'true' if is_prerelease(version) else 'false'}\n")


def cmd_version(_args: argparse.Namespace) -> None:
    version = read_version(PYPROJECT.read_text())
    print(version)
    if output := os.environ.get("GITHUB_OUTPUT"):
        with open(output, "a", encoding="utf-8") as fh:
            write_outputs(fh, version)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    sub = parser.add_subparsers(dest="command", required=True)

    prepare = sub.add_parser("prepare", help="bump, changelog, commit, tag and push a release")
    prepare.add_argument("part", help="patch, minor, major, or an explicit version such as 1.0.0-rc.1")
    prepare.add_argument("--dry-run", action="store_true", help="show what would happen; change nothing")
    prepare.add_argument("--skip-tests", action="store_true", help="do not run the test suite first")
    prepare.add_argument("--no-push", action="store_true", help="commit and tag locally only")
    prepare.add_argument("--yes", "-y", action="store_true", help="answer yes to every question")
    prepare.add_argument("--allow-branch", action="store_true", help=f"release from a branch other than {RELEASE_BRANCH}")
    prepare.set_defaults(func=cmd_prepare)

    notes = sub.add_parser("notes", help="print a version's CHANGELOG section")
    notes.add_argument("version")
    notes.set_defaults(func=cmd_notes)

    check = sub.add_parser("check-version", help="fail unless the tag matches the project version")
    check.add_argument("tag")
    check.set_defaults(func=cmd_check_version)

    current = sub.add_parser("version", help="print the project version")
    current.set_defaults(func=cmd_version)

    args = parser.parse_args(argv)
    try:
        args.func(args)
    except ReleaseError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 1
    except KeyboardInterrupt:
        print("\ninterrupted", file=sys.stderr)
        return 130
    return 0


if __name__ == "__main__":
    sys.exit(main())

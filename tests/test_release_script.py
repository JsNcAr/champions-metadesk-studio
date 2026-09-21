"""scripts/release.py: version bumps, changelog handling, and a full prepare run."""

from __future__ import annotations

import datetime as dt
import importlib.util
import os
import shutil
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
SCRIPT = ROOT / "scripts" / "release.py"

_spec = importlib.util.spec_from_file_location("release_script", SCRIPT)
release = importlib.util.module_from_spec(_spec)
sys.modules[_spec.name] = release   # dataclasses look their module up here
_spec.loader.exec_module(release)

PYPROJECT = """[project]
name = "demo"
version = "0.1.0"
dependencies = [
    "requests (>=2,<3)",
]

[tool.poetry]
packages = [{include = "demo", from = "src"}]

[tool.other]
version = "9.9.9"
"""


class TestVersions(unittest.TestCase):
    def test_bumps(self):
        self.assertEqual(release.bump("0.1.0", "patch"), "0.1.1")
        self.assertEqual(release.bump("0.1.3", "minor"), "0.2.0")
        self.assertEqual(release.bump("0.4.3", "major"), "1.0.0")

    def test_a_bump_from_a_prerelease_finishes_it(self):
        self.assertEqual(release.bump("1.0.0-rc.2", "patch"), "1.0.0")

    def test_explicit_versions_must_be_newer(self):
        self.assertEqual(release.bump("0.9.0", "1.0.0-rc.1"), "1.0.0-rc.1")
        self.assertEqual(release.bump("1.0.0-rc.1", "1.0.0"), "1.0.0")
        with self.assertRaises(release.ReleaseError):
            release.bump("1.0.0", "1.0.0-rc.1")
        with self.assertRaises(release.ReleaseError):
            release.bump("0.2.0", "0.2.0")
        with self.assertRaises(release.ReleaseError):
            release.bump("0.2.0", "v0.3")

    def test_prerelease_detection(self):
        self.assertTrue(release.is_prerelease("1.0.0-rc.1"))
        self.assertFalse(release.is_prerelease("1.0.0"))

    def test_only_the_project_version_is_read_and_written(self):
        self.assertEqual(release.read_version(PYPROJECT), "0.1.0")
        updated = release.write_version(PYPROJECT, "0.2.0")
        self.assertEqual(release.read_version(updated), "0.2.0")
        self.assertIn('[tool.other]\nversion = "9.9.9"', updated)
        self.assertEqual(updated.replace('"0.2.0"', '"0.1.0"', 1), PYPROJECT)

    def test_package_version(self):
        text = '"""Pkg."""\n\n__version__ = "0.1.0"\n'
        self.assertEqual(release.write_package_version(text, "0.2.0"), '"""Pkg."""\n\n__version__ = "0.2.0"\n')
        with self.assertRaises(release.ReleaseError):
            release.write_package_version('"""No version."""\n', "0.2.0")


class TestChangelog(unittest.TestCase):
    def test_commits_are_grouped_by_type(self):
        commits = [
            release.Commit("a" * 40, "feat(shell): crossfade between views"),
            release.Commit("b" * 40, "fix: sprites never served"),
            release.Commit("c" * 40, "perf(box): chunked fill"),
            release.Commit("d" * 40, "chore(release): v0.1.0"),
            release.Commit("e" * 40, "ci: cache poetry"),
            release.Commit("f" * 40, "Merge pull request #1 from x/y"),
            release.Commit("1" * 40, "feat(api)!: drop the CSV importer"),
            release.Commit("2" * 40, "refactor: split store", body="BREAKING CHANGE: new file layout"),
        ]
        section = release.render_section(commits)
        self.assertEqual(section, "\n\n".join([
            "### Breaking changes\n- **api:** drop the CSV importer (1111111)\n- split store (2222222)",
            "### Added\n- **shell:** crossfade between views (aaaaaaa)",
            "### Performance\n- **box:** chunked fill (ccccccc)",
            "### Fixed\n- sprites never served (bbbbbbb)",
        ]))

    def test_nothing_releasable_renders_empty(self):
        self.assertEqual(release.render_section([release.Commit("a" * 40, "chore: tidy")]), "")

    CHANGELOG = "# Changelog\n\nIntro.\n\n## [Unreleased]\n\n{unreleased}## [0.1.0] - 2026-09-14\n\nFirst.\n"

    def test_written_unreleased_notes_win_and_are_emptied(self):
        text = self.CHANGELOG.format(unreleased="### Fixed\n- by hand\n\n")
        updated, notes = release.add_release(text, "0.2.0", "### Added\n- generated", dt.date(2026, 9, 21))
        self.assertEqual(notes, "### Fixed\n- by hand")
        self.assertEqual(updated, (
            "# Changelog\n\nIntro.\n\n## [Unreleased]\n\n"
            "## [0.2.0] - 2026-09-21\n\n### Fixed\n- by hand\n\n"
            "## [0.1.0] - 2026-09-14\n\nFirst.\n"
        ))

    def test_empty_unreleased_uses_the_generated_notes(self):
        updated, notes = release.add_release(self.CHANGELOG.format(unreleased=""), "0.2.0",
                                             "### Added\n- generated", dt.date(2026, 9, 21))
        self.assertEqual(notes, "### Added\n- generated")
        self.assertEqual(release.release_notes(updated, "0.2.0"), notes)
        self.assertEqual(release.release_notes(updated, "0.1.0"), "First.")

    def test_no_notes_at_all_is_an_error(self):
        with self.assertRaises(release.ReleaseError):
            release.add_release(self.CHANGELOG.format(unreleased=""), "0.2.0", "", dt.date(2026, 9, 21))

    def test_missing_section_is_an_error(self):
        with self.assertRaises(release.ReleaseError):
            release.release_notes(self.CHANGELOG.format(unreleased=""), "0.3.0")


class TestRepositoryIsReleasable(unittest.TestCase):
    """The real files the script and the workflow operate on."""

    def test_package_version_matches_pyproject(self):
        from pokemon_champions_planning_tool import __version__

        self.assertEqual(__version__, release.read_version((ROOT / "pyproject.toml").read_text()))

    def test_changelog_has_an_unreleased_section_and_the_current_version(self):
        changelog = (ROOT / "CHANGELOG.md").read_text()
        release.split_unreleased(changelog)
        current = release.read_version((ROOT / "pyproject.toml").read_text())
        self.assertTrue(release.release_notes(changelog, current))

    def test_check_version(self):
        import contextlib
        import io
        from unittest import mock

        current = release.read_version((ROOT / "pyproject.toml").read_text())
        env = {k: v for k, v in os.environ.items() if k != "GITHUB_OUTPUT"}   # not the CI step's outputs
        with mock.patch.dict(os.environ, env, clear=True), \
                contextlib.redirect_stdout(io.StringIO()), contextlib.redirect_stderr(io.StringIO()) as err:
            self.assertEqual(release.main(["check-version", f"v{current}"]), 0)
            self.assertEqual(release.main(["check-version", "v99.0.0"]), 1)
        self.assertIn("does not match", err.getvalue())


@unittest.skipUnless(shutil.which("git"), "git not installed")
class TestPrepareEndToEnd(unittest.TestCase):
    """``prepare`` in a throwaway repository with a bare 'origin'."""

    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        base = Path(self._tmp.name)
        self.origin = base / "origin.git"
        self.repo = base / "repo"
        self.env = {
            **os.environ,
            "GIT_AUTHOR_NAME": "Test", "GIT_AUTHOR_EMAIL": "test@example.com",
            "GIT_COMMITTER_NAME": "Test", "GIT_COMMITTER_EMAIL": "test@example.com",
            "GIT_CONFIG_GLOBAL": os.devnull, "GIT_CONFIG_NOSYSTEM": "1",
        }
        self.env.pop("VISUAL", None)
        self.env.pop("EDITOR", None)
        self.git_in(base, "init", "-q", "--bare", "-b", "main", str(self.origin))
        self.git_in(base, "init", "-q", "-b", "main", str(self.repo))
        (self.repo / "scripts").mkdir()
        shutil.copy(SCRIPT, self.repo / "scripts" / "release.py")
        package = self.repo / "src" / "pokemon_champions_planning_tool"
        package.mkdir(parents=True)
        (package / "__init__.py").write_text('__version__ = "0.1.0"\n')
        (self.repo / "pyproject.toml").write_text(PYPROJECT)
        (self.repo / "CHANGELOG.md").write_text(
            "# Changelog\n\n## [Unreleased]\n\n## [0.1.0] - 2026-09-14\n\nFirst.\n"
        )
        self.git("add", ".")
        self.git("commit", "-q", "-m", "chore: initial")
        self.git("tag", "-a", "v0.1.0", "-m", "v0.1.0")
        (self.repo / "feature.txt").write_text("x")
        self.git("add", ".")
        self.git("commit", "-q", "-m", "feat(box): a new thing")
        self.git("remote", "add", "origin", str(self.origin))
        self.git("push", "-q", "origin", "main", "v0.1.0")

    def tearDown(self):
        self._tmp.cleanup()

    def git_in(self, cwd, *args):
        return subprocess.run(["git", *args], cwd=cwd, env=self.env, check=True,
                              capture_output=True, text=True).stdout.strip()

    def git(self, *args):
        return self.git_in(self.repo, *args)

    def prepare(self, *args):
        return subprocess.run(
            [sys.executable, "scripts/release.py", "prepare", *args, "--skip-tests", "--yes"],
            cwd=self.repo, env=self.env, capture_output=True, text=True, stdin=subprocess.DEVNULL,
        )

    def test_release_commits_tags_and_pushes_atomically(self):
        result = self.prepare("minor")
        self.assertEqual(result.returncode, 0, result.stderr + result.stdout)
        self.assertEqual(self.git("log", "-1", "--format=%s"), "chore(release): v0.2.0")
        self.assertIn('version = "0.2.0"', (self.repo / "pyproject.toml").read_text())
        self.assertIn('__version__ = "0.2.0"',
                      (self.repo / "src" / "pokemon_champions_planning_tool" / "__init__.py").read_text())
        changelog = (self.repo / "CHANGELOG.md").read_text()
        self.assertIn("## [Unreleased]\n\n## [0.2.0] - ", changelog)
        self.assertIn("### Added\n- **box:** a new thing", changelog)
        self.assertEqual(self.git("cat-file", "-t", "v0.2.0"), "tag", "an annotated tag")
        self.assertIn("a new thing", self.git("tag", "-l", "--format=%(contents)", "v0.2.0"))
        self.assertEqual(self.git_in(self.origin, "rev-parse", "main"), self.git("rev-parse", "HEAD"))
        self.assertEqual(self.git_in(self.origin, "rev-parse", "v0.2.0^{}"), self.git("rev-parse", "HEAD"))

    def test_no_push_keeps_everything_local(self):
        result = self.prepare("patch", "--no-push")
        self.assertEqual(result.returncode, 0, result.stderr + result.stdout)
        self.assertEqual(self.git("tag", "-l", "v0.1.1"), "v0.1.1")
        self.assertEqual(self.git_in(self.origin, "tag", "-l", "v0.1.1"), "")
        self.assertIn("git push --atomic origin main v0.1.1", result.stdout)

    def test_dry_run_changes_nothing(self):
        before = self.git("rev-parse", "HEAD")
        result = self.prepare("minor", "--dry-run")
        self.assertEqual(result.returncode, 0, result.stderr + result.stdout)
        self.assertIn("a new thing", result.stdout)
        self.assertEqual(self.git("rev-parse", "HEAD"), before)
        self.assertEqual(self.git("status", "--porcelain"), "")
        self.assertEqual(self.git("tag", "-l", "v0.2.0"), "")

    def test_refuses_a_dirty_tree_and_other_branches(self):
        (self.repo / "feature.txt").write_text("changed")
        self.assertIn("uncommitted changes", self.prepare("minor").stderr)
        self.git("checkout", "-q", "--", "feature.txt")
        self.git("switch", "-q", "-c", "topic")
        self.assertIn("releases are cut from main", self.prepare("minor").stderr)

    def test_refuses_when_behind_origin(self):
        other = Path(self._tmp.name) / "other"
        self.git_in(self._tmp.name, "clone", "-q", str(self.origin), str(other))
        (other / "more.txt").write_text("y")
        self.git_in(other, "add", ".")
        self.git_in(other, "commit", "-q", "-m", "fix: elsewhere")
        self.git_in(other, "push", "-q", "origin", "main")
        self.assertIn("behind origin/main", self.prepare("minor").stderr)

    def test_a_failure_before_committing_restores_the_files(self):
        # A stdin that is not a terminal, without --yes, cannot answer "Commit and tag?".
        result = subprocess.run(
            [sys.executable, "scripts/release.py", "prepare", "minor", "--skip-tests"],
            cwd=self.repo, env=self.env, capture_output=True, text=True, stdin=subprocess.DEVNULL,
        )
        self.assertEqual(result.returncode, 1)
        self.assertIn("--yes", result.stderr)
        self.assertEqual(self.git("status", "--porcelain"), "", "version files restored")
        self.assertEqual(self.git("tag", "-l", "v0.2.0"), "")


if __name__ == "__main__":
    unittest.main()

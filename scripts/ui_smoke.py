"""Headless smoke test for the UI.

In an environment without a browser, ``--web`` never gets a client session, so
``main(page)`` never runs and a server boot proves nothing about the control tree. This
script builds the UI against a stub page and walks every view through Flet's real
diff/serialise path (``ObjectPatch.from_diff`` — what ``Session.patch_control`` calls at
runtime), which is where invalid control or theme values actually fail.

Usage (from the repo root, against a COPY of the real database):

    cp pokemon_champions.db /tmp/smoke.db
    poetry run python scripts/ui_smoke.py --db /tmp/smoke.db

Exit status is non-zero on any exception. Prints control counts and timings.
"""

from __future__ import annotations

import argparse
import os
import sys
import time
from pathlib import Path
from types import SimpleNamespace

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))


class StubPage(SimpleNamespace):
    """Just enough of ``ft.Page`` for view construction; no session, no client."""

    def __init__(self):
        super().__init__(
            overlay=[],
            controls=[],
            dialogs=[],
            services=[],
            on_keyboard_event=None,
            title="",
            theme=None,
            dark_theme=None,
            theme_mode=None,
            fonts=None,
            bgcolor=None,
            padding=None,
            spacing=None,
            width=1440,
            height=900,
            window=SimpleNamespace(width=None, height=None),
        )

    def update(self, *_controls):
        pass

    def add(self, *controls):
        self.controls.extend(controls)

    def launch_url(self, url):
        print(f"[stub] launch_url({url})")

    def run_thread(self, fn, *args):
        return fn(*args)

    def run_task(self, coro_fn, *args):
        """Re-entrant like a real page: a completion callback may schedule more work."""
        import asyncio
        import threading

        try:
            asyncio.get_running_loop()
        except RuntimeError:
            return asyncio.run(coro_fn(*args))
        failure: list[BaseException] = []

        def _run():
            try:
                asyncio.run(coro_fn(*args))
            except BaseException as exc:  # noqa: BLE001 - re-raised on the caller's thread
                failure.append(exc)

        worker = threading.Thread(target=_run)
        worker.start()
        worker.join()
        if failure:
            raise failure[0]

    def show_dialog(self, dlg):
        dlg.open = True  # like the real page, so open-state checks behave
        self.dialogs.append(dlg)

    def pop_dialog(self):
        dlg = self.dialogs.pop() if self.dialogs else None
        if dlg is not None:
            dlg.open = False
        return dlg


def _check_layout(control) -> None:
    """Same Flutter-side layout lint the unit tests run (tests/_ui_stubs.check_layout)."""
    sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "tests"))
    from _ui_stubs import check_layout

    check_layout(control)


def _serialise(control) -> int:
    _check_layout(control)
    from flet.controls.base_control import BaseControl
    from flet.controls.object_patch import ObjectPatch

    patch, added, _removed = ObjectPatch.from_diff(None, control, control_cls=BaseControl)
    patch.to_message()
    return len(added)


def _integrity(db_path: Path) -> int:
    """Structural checks on the database copy; returns the number of failures."""
    import sqlite3

    conn = sqlite3.connect(db_path)
    failures = 0
    checks = {
        "roster rows without a base species id": "SELECT COUNT(*) FROM tournament_team_members WHERE base_canonical_id = ''",
        "teams whose member_count disagrees with their rows": (
            "SELECT COUNT(*) FROM tournament_teams t WHERE member_count != (SELECT COUNT(*) FROM tournament_team_members m WHERE m.tournament_team_id = t.tournament_team_id)"
        ),
        "box entries pointing at a missing Pokémon record": "SELECT COUNT(*) FROM box_entries b WHERE NOT EXISTS (SELECT 1 FROM pokemon_records p WHERE p.canonical_id = b.pokemon_canonical_id)",
    }
    for label, sql in checks.items():
        n = conn.execute(sql).fetchone()[0]
        print(f"  integrity: {label}: {n}" + ("  <-- FAIL" if n else ""))
        failures += 1 if n else 0
    info = conn.execute("SELECT COUNT(*) FROM box_entries b JOIN pokemon_records p ON p.canonical_id = b.pokemon_canonical_id WHERE p.is_placeholder = 1").fetchone()[0]
    print(f"  integrity: box entries with placeholder data (repairable): {info}")
    conn.close()
    return failures


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--db", required=True, help="path to a COPY of the SQLite database")
    args = parser.parse_args()

    db_path = Path(args.db).resolve()
    if not db_path.exists():
        print(f"database not found: {db_path}", file=sys.stderr)
        return 2
    # The app resolves the DB relative to cwd; point it at the copy.
    os.chdir(db_path.parent)
    import pokemon_champions_planning_tool.config as config

    config.DEFAULT_DATABASE_FILENAME = db_path.name
    import pokemon_champions_planning_tool.infrastructure.database.database as db

    db.DEFAULT_DATABASE_FILENAME = db_path.name  # the module bound the name at import
    db.get_session.__defaults__ = (db_path.name,)
    db.initialize_database.__defaults__ = (db_path.name,)
    db.get_engine.__defaults__ = (db_path.name,)

    from pokemon_champions_planning_tool.ui import app as app_module

    app_module.STARTUP_SYNC_ENABLED = False  # never hit the network from a smoke test

    page = StubPage()
    t0 = time.perf_counter()
    app_module.main(page)
    print(f"main(page): {(time.perf_counter() - t0) * 1000:.0f} ms")

    shell = page.controls[0]
    failures = 0
    for key in ("box", "team", "meta", "calc", "settings"):
        t = time.perf_counter()
        try:
            shell.navigate(key)
            added = _serialise(shell)
            print(f"  {key:<5} serialised {added:>5} controls (whole shell)  {(time.perf_counter() - t) * 1000:6.0f} ms")
        except Exception as exc:  # noqa: BLE001 - report everything
            failures += 1
            print(f"  {key:<5} FAILED: {type(exc).__name__}: {exc}")

    print(f"overlay entries: {len(page.overlay)}  dialogs shown: {len(page.dialogs)}")
    failures += _integrity(db_path)
    return 1 if failures else 0


if __name__ == "__main__":
    sys.exit(main())

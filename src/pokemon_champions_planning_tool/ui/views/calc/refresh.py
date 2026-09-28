"""Keeps a result that is slow to compute in step with the calculation.

The opponents list, your team's colours and the rival team's colours all work the same way:
a key says what the result depends on; when it changes the job runs on a worker once edits
pause, and if the key moved on while it ran, it runs again. When there is nothing to
compute (no attacker, no team…) the result is cleared at once instead.
"""

from __future__ import annotations

from collections.abc import Callable
from typing import Any

from ...context import AppContext
from ...tasks import Debouncer

Progress = Callable[[Any], None]


def _noop(*_args: Any) -> None:
    pass


class BackgroundRefresh:
    def __init__(
        self,
        ctx: AppContext,
        *,
        name: str,
        key: Callable[[], str],
        job: Callable[[Progress], Callable[[], Any]],
        apply: Callable[[Any], None],
        idle: Callable[[], bool] = lambda: False,
        clear: Callable[[], None] = _noop,
        fresh: Callable[[str], bool] | None = None,
        busy: Callable[[bool], None] = _noop,
        on_progress: Callable[[Any], None] = _noop,
        on_error: Callable[[], None] = _noop,
    ) -> None:
        """
        ``key``: what the result depends on. ``job(progress)`` is called on the UI loop (so it
        can take a snapshot) and returns the work for the worker; the work may report partial
        results through ``progress``. ``apply`` shows a finished result. ``idle`` says there is
        nothing to compute, and ``clear`` then empties the result. ``fresh(key)`` says the
        result is current (default: the key of the last applied result).
        """
        self.ctx = ctx
        self.name = name
        self._key = key
        self._job = job
        self._apply = apply
        self._idle = idle
        self._clear = clear
        self._fresh = fresh or (lambda k: k == self.done_key)
        self._busy = busy
        self._on_progress = on_progress
        self._on_error = on_error
        self.done_key: str | None = None
        self.running = False
        self._later: Debouncer | None = None

    def attach(self, page: Any, delay_ms: int) -> None:
        """On a live page: start once edits pause for ``delay_ms`` (tests run at once)."""
        self._later = Debouncer(page, delay_ms, lambda _v: self._start(), quiet_event=False)

    def detach(self) -> None:
        self._later = None

    def request(self) -> None:
        """Bring the result up to date: clear it, schedule the job, or nothing if current."""
        if self.running:
            return          # the running job re-checks the key when it finishes
        key = self._key()
        if self._fresh(key):
            return
        if self._idle():
            self.done_key = key
            self._clear()
            return
        if self._later is not None:
            self._later(None)
        else:
            self._start()

    def _start(self) -> None:
        key = self._key()
        if self.running or self._fresh(key):
            return
        if self._idle():
            self.request()
            return
        self.running = True
        self._busy(True)

        def progress(value: Any) -> None:
            self.ctx.post(lambda v: self._on_progress(v) if self.running and self._key() == key else None, value)

        work = self._job(progress)

        def done(result: Any) -> None:
            self.running = False
            self._busy(False)
            if self._key() != key:
                self.request()          # the calculation moved on meanwhile
                return
            self.done_key = key
            self._apply(result)

        def failed(exc: BaseException) -> None:
            self.running = False
            self._busy(False)
            self._on_error()
            print(f"⚠️ {self.name} failed: {exc}")

        try:
            self.ctx.run_in_background(work, on_done=done, on_error=failed)
        except Exception:  # noqa: BLE001 - no page loop (tests): compute inline
            done(work())


__all__ = ["BackgroundRefresh", "Progress"]

"""Background work that ends in a UI update — the one threading pattern the UI uses.

Flet 0.85 runs handlers on an asyncio loop. ``page.run_thread`` moves blocking work to a
thread pool; ``page.run_task`` is the thread-safe way to get back onto the loop.
``page.update()`` is not thread-safe, so a worker must never touch controls. Every place
the old UI spawned a ``threading.Thread`` and mutated controls from it now goes through
``run_in_background``:

    run_in_background(
        page,
        work=lambda: add_species(name),        # runs off-loop; opens its own DB session
        on_done=lambda entry: store.add(entry),  # runs on the loop; may touch controls
        busy=[add_button], spinner=ring,
    )
"""

from __future__ import annotations

import asyncio
from collections.abc import Callable, Sequence
from typing import Any, Generic, TypeVar

import flet as ft

T = TypeVar("T")

ErrorHandler = Callable[[BaseException], None]


def is_mounted(control: ft.Control | None) -> bool:
    """True if the control is attached to a page.

    In Flet 0.85 reading ``control.page`` on an unmounted control raises
    ``RuntimeError`` rather than returning ``None``, so ``getattr`` is not enough.
    """
    if control is None:
        return False
    try:
        return control.page is not None
    except RuntimeError:
        return False


def _safe_update(control: ft.Control | None) -> None:
    """Update a control if it is mounted; a no-op otherwise."""
    if not is_mounted(control):
        return
    try:
        control.update()
    except Exception:  # noqa: BLE001 - never let a stale control kill the callback
        pass


def run_in_background(
    page: ft.Page,
    work: Callable[[], T],
    *,
    on_done: Callable[[T], None] | None = None,
    on_error: ErrorHandler | None = None,
    busy: Sequence[ft.Control] = (),
    spinner: ft.Control | None = None,
) -> None:
    """Run ``work`` on a worker thread, then ``on_done(result)`` on the UI loop.

    ``work`` receives nothing and returns plain data; it must open its own database
    session and must not touch controls. While it runs, ``busy`` controls are disabled
    and ``spinner`` is made visible; both are restored before the callback runs. If
    ``work`` raises, ``on_error`` is called instead (defaulting to an error toast).
    """
    for control in busy:
        control.disabled = True
        _safe_update(control)
    if spinner is not None:
        spinner.visible = True
        _safe_update(spinner)

    async def _finish(result: Any, exc: BaseException | None) -> None:
        for control in busy:
            control.disabled = False
            _safe_update(control)
        if spinner is not None:
            spinner.visible = False
            _safe_update(spinner)
        if exc is not None:
            if on_error is not None:
                on_error(exc)
            else:
                from .dialogs import toast  # local import: dialogs imports nothing from here

                toast(page, f"Something went wrong: {exc}", kind="error")
        elif on_done is not None:
            on_done(result)

    def _worker() -> None:
        try:
            result = work()
        except BaseException as exc:  # noqa: BLE001 - surfaced through on_error
            page.run_task(_finish, None, exc)
        else:
            page.run_task(_finish, result, None)

    page.run_thread(_worker)


class Debouncer(Generic[T]):
    """Collapse a burst of calls into one, ``delay_ms`` after the last.

    Used for text filters so a query runs once per pause rather than once per
    keystroke. ``fn`` runs on the UI loop with the most recent value.
    """

    def __init__(self, page: ft.Page, delay_ms: int, fn: Callable[[T], None]) -> None:
        self._page = page
        self._delay = delay_ms / 1000.0
        self._fn = fn
        self._generation = 0

    def __call__(self, value: T) -> None:
        self._generation += 1
        generation = self._generation

        async def _fire() -> None:
            await asyncio.sleep(self._delay)
            if generation == self._generation:
                self._fn(value)

        self._page.run_task(_fire)

    def cancel(self) -> None:
        self._generation += 1

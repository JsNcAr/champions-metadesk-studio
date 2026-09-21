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
            try:
                on_done(result)
            except BaseException as callback_exc:  # noqa: BLE001
                if on_error is not None:
                    on_error(callback_exc)
                else:
                    from .dialogs import toast

                    toast(page, f"Something went wrong: {callback_exc}", kind="error")

    def _worker() -> None:
        try:
            result = work()
        except BaseException as exc:  # noqa: BLE001 - surfaced through on_error
            page.run_task(_finish, None, exc)
        else:
            page.run_task(_finish, result, None)

    page.run_thread(_worker)


def open_url(page: ft.Page, url: str) -> None:
    """Open ``url`` in the browser (a new tab on the web build), from a sync handler.

    In Flet 0.85 ``page.launch_url`` is a deprecated coroutine. Called like the old
    synchronous API it only created a coroutine nobody awaited, so links did nothing.
    Its ``@deprecated`` wrapper also hides the coroutine from ``page.run_task``, which
    rejects it. So this goes through the ``UrlLauncher`` service in a coroutine of its own.
    ``run_task`` makes ``page`` current, and the service registers itself with it.
    """
    if not url:
        return

    async def _open() -> None:
        await ft.UrlLauncher().launch_url(url)

    page.run_task(_open)


def skip_auto_update() -> None:
    """Tell Flet not to auto-update after the event handler that is running now.

    Flet re-diffs the nearest isolated ancestor after any handler that did not call
    ``update()``. Use this in handlers that changed nothing. ``disable_auto_update``
    alone mutates whatever ``UpdateBehavior`` is current, and outside an event that is
    Flet's process-wide default; resetting first gives this context its own copy.
    """
    ft.context.reset_auto_update()
    ft.context.disable_auto_update()


class Debouncer(Generic[T]):
    """Collapse a burst of calls into one, ``delay_ms`` after the last.

    Used for text filters so a query runs once per pause rather than once per
    keystroke. ``fn`` runs on the UI loop with the most recent value.

    Calling it also switches off Flet's auto-update for the event that made the call.
    Otherwise, after every keystroke handler that did not call ``update()`` itself,
    Flet re-diffs the nearest isolated ancestor (a whole view: ~0.4 s for a full Box),
    and those diffs queue up ahead of the debounced result. The keystroke has nothing
    to send, since the text already sits in the client's field; ``fn`` updates what it
    changes explicitly.
    """

    def __init__(self, page: ft.Page, delay_ms: int, fn: Callable[[T], None], *, quiet_event: bool = True) -> None:
        """``quiet_event=False`` when the caller is not a no-op keystroke: the event that
        schedules the call may have changed other controls and still needs its refresh."""
        self._page = page
        self._delay = delay_ms / 1000.0
        self._fn = fn
        self._quiet_event = quiet_event
        self._generation = 0

    def __call__(self, value: T) -> None:
        if self._quiet_event:
            skip_auto_update()
        self._generation += 1
        generation = self._generation

        async def _fire() -> None:
            await asyncio.sleep(self._delay)
            if generation == self._generation:
                self._fn(value)

        self._page.run_task(_fire)

    def cancel(self) -> None:
        self._generation += 1


def grid_tile_aspect(available_width: float, *, max_extent: int, spacing: int, tile_height: int) -> float:
    """``child_aspect_ratio`` that gives GridView tiles a fixed height at this width.

    Mirrors Flutter's SliverGridDelegateWithMaxCrossAxisExtent: the column count is
    ``ceil(width / (max_extent + spacing))`` and tiles share the remaining width, so the
    only way to hold tile *height* constant across window sizes is to recompute the
    aspect ratio whenever the width changes.
    """
    return max(0.1, grid_tile_width(available_width, max_extent=max_extent, spacing=spacing) / float(tile_height))


def grid_tile_width(available_width: float, *, max_extent: int, spacing: int) -> float:
    """Width Flutter will give each GridView tile (max-extent delegate)."""
    import math

    width = max(1.0, float(available_width))
    columns = max(1, math.ceil(width / (max_extent + spacing)))
    return (width - spacing * (columns - 1)) / columns

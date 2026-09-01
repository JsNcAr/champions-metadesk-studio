"""Shared stand-ins for UI tests: a page without a session, and a serialiser check."""

from __future__ import annotations

import asyncio
from types import SimpleNamespace

import flet as ft


class StubPage(SimpleNamespace):
    """Runs workers inline and coroutines to completion, on the calling thread."""

    def __init__(self):
        super().__init__(overlay=[], controls=[], services=[], on_keyboard_event=None, dialogs=[])

    def run_thread(self, fn, *args):
        fn(*args)

    def run_task(self, coro_fn, *args):
        """Run the coroutine to completion before returning.

        A real page's run_task is re-entrant (run_coroutine_threadsafe onto the session
        loop). Inside an already-running loop asyncio.run() would raise, so fall back to
        a helper thread with its own loop and wait for it.
        """
        try:
            asyncio.get_running_loop()
        except RuntimeError:
            asyncio.run(coro_fn(*args))
            return
        import threading

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
        self.dialogs.append(dlg)

    def pop_dialog(self):
        return self.dialogs.pop() if self.dialogs else None

    def update(self, *_):
        pass

    def add(self, *controls):
        self.controls.extend(controls)


def serialise(control: ft.Control) -> int:
    """Walk a control through Flet's runtime diff/serialise path; returns controls added.

    This is what ``Session.patch_control`` does when a client is connected, and it is
    where an invalid enum, colour or nested value actually fails.
    """
    from flet.controls.base_control import BaseControl
    from flet.controls.object_patch import ObjectPatch

    patch, added, _removed = ObjectPatch.from_diff(None, control, control_cls=BaseControl)
    patch.to_message()
    return len(added)

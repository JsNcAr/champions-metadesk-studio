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
        dlg.open = True  # like the real page, so open-state checks behave
        self.dialogs.append(dlg)

    def pop_dialog(self):
        dlg = self.dialogs.pop() if self.dialogs else None
        if dlg is not None:
            dlg.open = False
            if hasattr(dlg, "on_dismiss") and callable(dlg.on_dismiss):
                dlg.on_dismiss(None)
        return dlg

    def update(self, *_):
        pass

    def add(self, *controls):
        self.controls.extend(controls)


def check_layout(control: ft.Control) -> None:
    """Fail on control-tree shapes Flutter rejects at build time but Flet serialises happily.

    - An ``expand`` child inside a wrapping Row/Column. Flutter's Wrap widget throws
      "Incorrect use of ParentDataWidget" for Expanded, and the release client paints the
      whole subtree as a grey error box (this is how the Box view once rendered blank).
    - One control instance placed in two parents. The client draws it twice, and Flet
      tracks a control by a single parent and id, so updates to it can go astray. The
      Calc panels once showed the species name twice this way.
    """
    from dataclasses import fields
    from flet.controls.base_control import BaseControl

    problems: list[str] = []
    seen: dict[int, str] = {}

    def walk(c, path: str) -> None:
        if id(c) in seen:
            problems.append(f"{type(c).__name__} placed twice: {seen[id(c)]} and {path}")
            return
        seen[id(c)] = path
        if isinstance(c, (ft.Row, ft.Column)) and getattr(c, "wrap", False):
            for i, child in enumerate(getattr(c, "controls", None) or []):
                if getattr(child, "expand", None) or getattr(child, "expand_loose", None):
                    problems.append(f"{path}: {type(c).__name__}(wrap=True) child #{i} {type(child).__name__} has expand set")
        for f in fields(c):
            if f.name.startswith("_") or f.name in ("parent", "page"):
                continue
            value = getattr(c, f.name, None)
            if isinstance(value, BaseControl):
                walk(value, f"{path}.{f.name}")
            elif isinstance(value, (list, tuple)):
                for i, item in enumerate(value):
                    if isinstance(item, BaseControl):
                        walk(item, f"{path}.{f.name}[{i}]")

    walk(control, type(control).__name__)
    if problems:
        raise AssertionError("layout shapes Flutter rejects:\n" + "\n".join(problems))


def serialise(control: ft.Control) -> int:
    """Walk a control through Flet's runtime diff/serialise path; returns controls added.

    This is what ``Session.patch_control`` does when a client is connected, and it is
    where an invalid enum, colour or nested value actually fails. ``check_layout`` runs
    first for the shapes that only fail inside Flutter.
    """
    check_layout(control)
    import msgpack
    from flet.controls.base_control import BaseControl
    from flet.controls.object_patch import ObjectPatch
    from flet.messaging.flet_socket_server import configure_encode_object_for_msgpack

    patch, added, _removed = ObjectPatch.from_diff(None, control, control_cls=BaseControl)
    msg = patch.to_message()
    msgpack.packb(["patch", msg], default=configure_encode_object_for_msgpack(BaseControl))
    return len(added)

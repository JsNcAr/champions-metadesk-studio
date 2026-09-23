"""Per-session application context handed to the shell, views and stores."""

from __future__ import annotations

from collections.abc import Callable, Sequence
from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Any

import flet as ft

from . import dialogs, tasks
from .events import FORMAT_CHANGED, EventBus
from .preferences import Preferences

if TYPE_CHECKING:
    from .formats import FormatRegistry


@dataclass
class AppContext:
    """What every view needs: the page, the event bus, and bound helpers.

    ``catalogs`` is populated by the shell once the startup catalogue caches exist
    (later migration step); until then it is ``None``.
    """

    page: ft.Page
    bus: EventBus = field(default_factory=EventBus)
    catalogs: Any = None
    prefs: Preferences = field(default_factory=Preferences)   # in-memory unless the app installs a file-backed one
    _clipboard: Any = field(default=None, init=False, repr=False)
    _formats: Any = field(default=None, init=False, repr=False)
    _shutdown_hooks: list[Callable[[], None]] = field(default_factory=list, init=False, repr=False)

    @property
    def formats(self) -> "FormatRegistry":
        """The formats (built-in and custom) over the current preferences. Rebuilt when the
        app installs its file-backed preferences after the context was created."""
        from .formats import FormatRegistry

        if self._formats is None or self._formats.prefs is not self.prefs:
            self._formats = FormatRegistry(self.prefs)
            self._formats.subscribe(lambda _e: self.bus.emit(FORMAT_CHANGED, None))
        return self._formats

    def on_shutdown(self, fn: Callable[[], None]) -> None:
        """Run ``fn`` when the session ends: window closed, browser tab gone, or the app
        sent to the background. Hooks may run more than once, so they must be idempotent
        (flush pending writes, and do nothing when there is nothing to flush)."""
        if fn not in self._shutdown_hooks:
            self._shutdown_hooks.append(fn)

    def run_shutdown_hooks(self) -> None:
        for fn in list(self._shutdown_hooks):
            try:
                fn()
            except Exception as exc:  # noqa: BLE001 - one failing hook must not stop the others
                print(f"⚠️ Shutdown hook failed: {exc}")

    def post(self, fn, *args) -> None:
        """Run ``fn(*args)`` on the UI loop from any thread (progress callbacks)."""

        async def _call() -> None:
            fn(*args)

        self.page.run_task(_call)

    def sync_tournaments(self, work, *, on_done=None, on_error=None, busy=(), spinner=None) -> None:
        """Run a tournament sync off the loop, relaying SyncProgress to the bus."""
        from . import events as _events

        def relay(progress) -> None:
            self.post(self.bus.emit, _events.SYNC_PROGRESS, progress)

        self.run_in_background(lambda: work(relay), on_done=on_done, on_error=on_error, busy=busy, spinner=spinner)

    def toast(
        self,
        message: str,
        kind: dialogs.ToastKind = "info",
        *,
        action: str | None = None,
        on_action: Callable[[], None] | None = None,
    ) -> None:
        dialogs.toast(self.page, message, kind, action=action, on_action=on_action)

    async def confirm(self, title: str, body: str, **kwargs: Any) -> bool:
        return await dialogs.confirm(self.page, title, body, **kwargs)

    async def prompt_text(self, title: str, label: str, **kwargs: Any) -> str | None:
        return await dialogs.prompt_text(self.page, title, label, **kwargs)

    def run_in_background(
        self,
        work: Callable[[], Any],
        *,
        on_done: Callable[[Any], None] | None = None,
        on_error: tasks.ErrorHandler | None = None,
        busy: Sequence[ft.Control] = (),
        spinner: ft.Control | None = None,
    ) -> None:
        tasks.run_in_background(
            self.page, work, on_done=on_done, on_error=on_error, busy=busy, spinner=spinner
        )

    def copy_to_clipboard(self, text: str) -> None:
        """Copy via the ``ft.Clipboard`` service (``page.set_clipboard`` no longer exists).

        The service is registered on first use; ``Clipboard.set`` is a coroutine, so it
        is scheduled with ``page.run_task`` and works from sync handlers.
        """
        if self._clipboard is None:
            self._clipboard = ft.Clipboard()
            self.page.services.append(self._clipboard)
            try:
                self.page.update()
            except Exception:  # noqa: BLE001 - page may not be mounted yet (tests)
                pass
        self.page.run_task(self._clipboard.set, text)

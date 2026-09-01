"""Per-session application context handed to the shell, views and stores."""

from __future__ import annotations

from collections.abc import Callable, Sequence
from dataclasses import dataclass, field
from typing import Any

import flet as ft

from . import dialogs, tasks
from .events import EventBus


@dataclass
class AppContext:
    """What every view needs: the page, the event bus, and bound helpers.

    ``catalogs`` is populated by the shell once the startup catalogue caches exist
    (later migration step); until then it is ``None``.
    """

    page: ft.Page
    bus: EventBus = field(default_factory=EventBus)
    catalogs: Any = None
    _clipboard: Any = field(default=None, init=False, repr=False)

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

    # The legacy views only know ``services.toast(message, is_error)``.
    def legacy_toast(self, message: str, is_error: bool = False) -> None:
        self.toast(message, "error" if is_error else "success")

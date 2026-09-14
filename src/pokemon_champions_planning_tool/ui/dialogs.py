"""Dialog and toast helpers built on Flet 0.85's dialog stack.

All overlays go through ``page.show_dialog`` / ``page.pop_dialog`` with a fresh instance
each time — the old UI toggled ``.open`` on long-lived dialogs and appended a new
``SnackBar`` to ``page.overlay`` on every toast, which leaked and, in 0.85, is not the
supported path at all.
"""

from __future__ import annotations

import asyncio
from collections.abc import Callable
from typing import Literal

import flet as ft

from .theme import Palette

ToastKind = Literal["info", "success", "error"]

_TOAST_DURATION_MS: dict[ToastKind, int] = {"info": 4000, "success": 4000, "error": 8000}
_TOAST_ICON: dict[ToastKind, str] = {
    "info": ft.Icons.INFO_OUTLINE,
    "success": ft.Icons.CHECK_CIRCLE_OUTLINE,
    "error": ft.Icons.ERROR_OUTLINE,
}
_TOAST_ICON_COLOR: dict[ToastKind, str] = {
    "info": Palette.SECONDARY,
    "success": Palette.SUCCESS,
    "error": Palette.ERROR,
}


def toast(
    page: ft.Page,
    message: str,
    kind: ToastKind = "info",
    *,
    action: str | None = None,
    on_action: Callable[[], None] | None = None,
) -> None:
    """Show a floating snackbar. Errors stay longer and carry a close icon."""
    snack = ft.SnackBar(
        content=ft.Row(
            spacing=8,
            controls=[
                ft.Icon(_TOAST_ICON[kind], size=20, color=_TOAST_ICON_COLOR[kind]),
                ft.Text(message, expand=True, color=Palette.ON_SURFACE),
            ],
        ),
        action=action,
        on_action=(lambda _e: on_action()) if on_action else None,
        duration=_TOAST_DURATION_MS[kind],
        show_close_icon=kind == "error",
    )
    page.show_dialog(snack)


async def confirm(
    page: ft.Page,
    title: str,
    body: str,
    *,
    confirm_label: str = "Delete",
    cancel_label: str = "Cancel",
    destructive: bool = True,
) -> bool:
    """Modal yes/no. Resolves False on cancel or on dismissing the barrier."""
    loop = asyncio.get_running_loop()
    future: asyncio.Future[bool] = loop.create_future()

    def close(result: bool) -> None:
        if not future.done():
            future.set_result(result)
        page.pop_dialog()

    def dismissed(_e: ft.ControlEvent) -> None:
        if not future.done():
            future.set_result(False)

    confirm_style = (
        ft.ButtonStyle(bgcolor=Palette.ERROR, color=Palette.ON_ERROR) if destructive else None
    )
    dialog = ft.AlertDialog(
        modal=True,
        title=ft.Text(title),
        content=ft.Text(body),
        actions=[
            ft.TextButton(cancel_label, on_click=lambda _e: close(False)),
            ft.FilledButton(confirm_label, style=confirm_style, on_click=lambda _e: close(True)),
        ],
        actions_alignment=ft.MainAxisAlignment.END,
        on_dismiss=dismissed,
    )
    page.show_dialog(dialog)
    return await future


async def prompt_text(
    page: ft.Page,
    title: str,
    label: str,
    *,
    value: str = "",
    submit_label: str = "Save",
    validate: Callable[[str], str | None] | None = None,
) -> str | None:
    """Modal single-field prompt. ``validate`` returns an error message or None.
    Resolves None on cancel."""
    loop = asyncio.get_running_loop()
    future: asyncio.Future[str | None] = loop.create_future()

    field = ft.TextField(label=label, value=value, autofocus=True, dense=True)

    def submit(_e: ft.ControlEvent | None = None) -> None:
        text = (field.value or "").strip()
        error = validate(text) if validate else None
        if error:
            field.error = error
            field.update()
            return
        if not future.done():
            future.set_result(text)
        page.pop_dialog()

    def cancel(_e: ft.ControlEvent | None = None) -> None:
        if not future.done():
            future.set_result(None)
        page.pop_dialog()

    def dismissed(_e: ft.ControlEvent) -> None:
        if not future.done():
            future.set_result(None)

    field.on_submit = submit
    dialog = ft.AlertDialog(
        modal=True,
        title=ft.Text(title),
        content=ft.Container(content=field, width=400),
        actions=[
            ft.TextButton("Cancel", on_click=cancel),
            ft.FilledButton(submit_label, on_click=submit),
        ],
        actions_alignment=ft.MainAxisAlignment.END,
        on_dismiss=dismissed,
    )
    page.show_dialog(dialog)
    return await future

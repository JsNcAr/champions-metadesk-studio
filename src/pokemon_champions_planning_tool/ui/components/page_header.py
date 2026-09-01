"""Page header: title, optional count chip and caption, right-aligned actions.

Every view owns one (there is no global app bar). 56px tall with a hairline below.
"""

from __future__ import annotations

from collections.abc import Sequence

import flet as ft

from ..theme import Layout, Palette, Radius, Space


class PageHeader(ft.Container):
    def __init__(
        self,
        title: str,
        *,
        count: int | str | None = None,
        caption: str | None = None,
        actions: Sequence[ft.Control] = (),
    ) -> None:
        super().__init__()
        self._title = ft.Text(title, theme_style=ft.TextThemeStyle.TITLE_LARGE, color=Palette.ON_SURFACE)
        self._count = ft.Container(
            content=ft.Text("", theme_style=ft.TextThemeStyle.BODY_SMALL, color=Palette.ON_SURFACE_VARIANT),
            bgcolor=Palette.SURFACE_3,
            border_radius=Radius.PILL,
            padding=ft.Padding.symmetric(horizontal=Space.SM, vertical=2),
            visible=False,
        )
        self._caption = ft.Text(
            "", theme_style=ft.TextThemeStyle.BODY_SMALL, color=Palette.ON_SURFACE_VARIANT, visible=False
        )
        self._actions = ft.Row(spacing=Space.SM, controls=list(actions))

        self.content = ft.Row(
            alignment=ft.MainAxisAlignment.SPACE_BETWEEN,
            vertical_alignment=ft.CrossAxisAlignment.CENTER,
            controls=[
                ft.Row(
                    spacing=Space.MD,
                    vertical_alignment=ft.CrossAxisAlignment.CENTER,
                    controls=[self._title, self._count, self._caption],
                ),
                self._actions,
            ],
        )
        self.height = Layout.PAGE_HEADER_HEIGHT
        self.border = ft.Border.only(bottom=ft.BorderSide(1, Palette.OUTLINE_VARIANT))
        self.margin = ft.Margin.only(bottom=Space.LG)
        self.set_count(count)
        self.set_caption(caption)

    def set_title(self, title: str) -> None:
        self._title.value = title

    def set_count(self, count: int | str | None) -> None:
        self._count.visible = count is not None
        self._count.content.value = f"{count:,}" if isinstance(count, int) else (count or "")

    def set_caption(self, caption: str | None) -> None:
        self._caption.visible = bool(caption)
        self._caption.value = caption or ""

    @property
    def actions(self) -> ft.Row:
        return self._actions

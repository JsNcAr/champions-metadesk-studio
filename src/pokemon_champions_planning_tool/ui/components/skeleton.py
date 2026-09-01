"""Loading skeletons: pulsing surface blocks used for the first paint of a collection."""

from __future__ import annotations

import flet as ft

from ..theme import Palette, Radius, Space


def skeleton_block(*, width: int | None = None, height: int = 16, expand: bool = False) -> ft.Container:
    return ft.Container(
        width=width,
        height=height,
        expand=expand,
        bgcolor=Palette.SURFACE_3,
        border_radius=Radius.SM,
        opacity=0.7,
        animate_opacity=900,
    )


def skeleton_rows(count: int = 8, *, height: int = 48) -> ft.Column:
    """A list of row-shaped placeholders."""
    rows = []
    for _ in range(count):
        rows.append(
            ft.Container(
                height=height,
                padding=ft.Padding.symmetric(horizontal=Space.MD, vertical=Space.SM),
                content=ft.Row(
                    spacing=Space.MD,
                    vertical_alignment=ft.CrossAxisAlignment.CENTER,
                    controls=[
                        skeleton_block(width=40, height=24),
                        skeleton_block(width=160, height=14),
                        ft.Row(spacing=4, controls=[skeleton_block(width=28, height=28) for _ in range(6)]),
                        skeleton_block(expand=True, height=12),
                        skeleton_block(width=80, height=28),
                    ],
                ),
            )
        )
    return ft.Column(spacing=Space.XS, controls=rows, tight=True)

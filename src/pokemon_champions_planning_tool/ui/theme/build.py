"""Turns the design tokens into a Flet ``Theme`` and applies it to a page.

Material role → token mapping (so components can use ``ft.Colors.<ROLE>``):

    SURFACE                    Palette.BG          page background
    SURFACE_CONTAINER_LOW      Palette.SURFACE_1   side panels, table rows
    SURFACE_CONTAINER          Palette.SURFACE_2   cards, inputs, toolbars
    SURFACE_CONTAINER_HIGH     Palette.SURFACE_3   hover, selected rows, chips, menus
    SURFACE_CONTAINER_HIGHEST  Palette.SURFACE_4   dialogs, sheets, tooltips
    ON_SURFACE / ON_SURFACE_VARIANT, OUTLINE / OUTLINE_VARIANT, PRIMARY..., ERROR...

Colours with no Material role (warning, success, type, stat) are read from ``tokens``.
"""

from __future__ import annotations

import flet as ft

from .tokens import FontSize, Layout, Palette, Radius

# Inter variable font (latin subset). Declared once on the page; referenced by family name.
INTER_FONT_URL = (
    "https://fonts.gstatic.com/s/inter/v13/"
    "UcCO3FwrK3iLTeHuS_fvQtMwCp50KnMw2boKoduKmMEVuLyfAZ9hiA.woff2"
)
FONT_FAMILY = "Inter"

DEFAULT_WINDOW_WIDTH = 1440
DEFAULT_WINDOW_HEIGHT = 900


def _style(size: int, line: int, weight: ft.FontWeight, color: str | None = None,
           letter_spacing: float | None = None) -> ft.TextStyle:
    return ft.TextStyle(
        size=size,
        height=line / size,
        weight=weight,
        color=color,
        letter_spacing=letter_spacing,
        font_family=FONT_FAMILY,
    )


def build_color_scheme() -> ft.ColorScheme:
    return ft.ColorScheme(
        primary=Palette.PRIMARY,
        on_primary=Palette.ON_PRIMARY,
        primary_container=Palette.PRIMARY_CONTAINER,
        on_primary_container=Palette.ON_PRIMARY_CONTAINER,
        secondary=Palette.SECONDARY,
        on_secondary=Palette.ON_SECONDARY,
        secondary_container=Palette.SECONDARY_CONTAINER,
        on_secondary_container=Palette.ON_SECONDARY_CONTAINER,
        tertiary=Palette.TERTIARY,
        on_tertiary=Palette.ON_TERTIARY,
        tertiary_container=Palette.TERTIARY_CONTAINER,
        on_tertiary_container=Palette.ON_TERTIARY_CONTAINER,
        error=Palette.ERROR,
        on_error=Palette.ON_ERROR,
        error_container=Palette.ERROR_CONTAINER,
        on_error_container=Palette.ON_ERROR_CONTAINER,
        surface=Palette.BG,
        on_surface=Palette.ON_SURFACE,
        on_surface_variant=Palette.ON_SURFACE_VARIANT,
        surface_container_lowest=Palette.BG,
        surface_container_low=Palette.SURFACE_1,
        surface_container=Palette.SURFACE_2,
        surface_container_high=Palette.SURFACE_3,
        surface_container_highest=Palette.SURFACE_4,
        outline=Palette.OUTLINE,
        outline_variant=Palette.OUTLINE_VARIANT,
        scrim=Palette.SCRIM,
        shadow=Palette.SCRIM,
    )


def build_text_theme() -> ft.TextTheme:
    """The type scale: title-lg 22/600 · title 17/600 · body-lg 15/500 · body 13/400 ·
    label 12/500 · caption 11/400 · overline 11/600 (uppercase is applied by components)."""
    w400, w500, w600 = ft.FontWeight.W_400, ft.FontWeight.W_500, ft.FontWeight.W_600
    return ft.TextTheme(
        display_small=_style(28, 34, w600),
        headline_small=_style(FontSize.TITLE_LG, 28, w600),
        title_large=_style(FontSize.TITLE_LG, 28, w600),
        title_medium=_style(FontSize.TITLE, 24, w600),
        title_small=_style(FontSize.BODY_LG, 22, w600),
        body_large=_style(FontSize.BODY_LG, 22, w500),
        body_medium=_style(FontSize.BODY, 20, w400),
        body_small=_style(FontSize.CAPTION, 14, w400, Palette.ON_SURFACE_VARIANT),
        label_large=_style(FontSize.LABEL, 16, w500),
        label_medium=_style(FontSize.LABEL, 16, w500),
        label_small=_style(FontSize.OVERLINE, 14, w600, Palette.ON_SURFACE_VARIANT, letter_spacing=0.6),
    )


def build_theme() -> ft.Theme:
    rounded_md = ft.RoundedRectangleBorder(radius=Radius.MD)
    rounded_lg = ft.RoundedRectangleBorder(radius=Radius.LG)
    label = _style(FontSize.LABEL, 16, ft.FontWeight.W_500)

    return ft.Theme(
        color_scheme=build_color_scheme(),
        text_theme=build_text_theme(),
        font_family=FONT_FAMILY,
        use_material3=True,
        visual_density=ft.VisualDensity.COMPACT,
        card_theme=ft.CardTheme(
            color=Palette.SURFACE_2,
            elevation=0,
            shape=rounded_md,
            margin=ft.Margin.all(0),
        ),
        dialog_theme=ft.DialogTheme(
            bgcolor=Palette.SURFACE_4,
            shape=rounded_lg,
            title_text_style=_style(FontSize.TITLE, 24, ft.FontWeight.W_600, Palette.ON_SURFACE),
            content_text_style=_style(FontSize.BODY, 20, ft.FontWeight.W_400, Palette.ON_SURFACE),
        ),
        navigation_rail_theme=ft.NavigationRailTheme(
            bgcolor=Palette.BG,
            use_indicator=True,
            indicator_color=Palette.PRIMARY_CONTAINER,
            indicator_shape=rounded_md,
            min_width=Layout.RAIL_WIDTH,
            selected_label_text_style=_style(FontSize.LABEL, 16, ft.FontWeight.W_600, Palette.ON_SURFACE),
            unselected_label_text_style=_style(FontSize.LABEL, 16, ft.FontWeight.W_500, Palette.ON_SURFACE_VARIANT),
        ),
        chip_theme=ft.ChipTheme(
            bgcolor=Palette.SURFACE_2,
            selected_color=Palette.PRIMARY_CONTAINER,
            check_color=Palette.ON_PRIMARY_CONTAINER,
            shape=ft.StadiumBorder(),
            border_side=ft.BorderSide(1, Palette.OUTLINE),
            label_text_style=label,
            show_checkmark=True,
        ),
        snackbar_theme=ft.SnackBarTheme(
            bgcolor=Palette.SURFACE_4,
            content_text_style=_style(FontSize.BODY, 20, ft.FontWeight.W_400, Palette.ON_SURFACE),
            action_text_color=Palette.PRIMARY,
            behavior=ft.SnackBarBehavior.FLOATING,
            shape=rounded_md,
            width=440,
        ),
        divider_theme=ft.DividerTheme(color=Palette.OUTLINE_VARIANT, thickness=1, space=1),
        data_table_theme=ft.DataTableTheme(
            heading_row_height=36,
            data_row_min_height=40,
            data_row_max_height=48,
            column_spacing=16,
            divider_thickness=0,
            heading_text_style=_style(FontSize.LABEL, 16, ft.FontWeight.W_500, Palette.ON_SURFACE_VARIANT),
            data_text_style=_style(FontSize.BODY, 20, ft.FontWeight.W_400, Palette.ON_SURFACE),
        ),
        tooltip_theme=ft.TooltipTheme(
            text_style=_style(FontSize.CAPTION, 14, ft.FontWeight.W_400, Palette.ON_SURFACE),
        ),
    )


def apply_theme(page: ft.Page) -> None:
    """Install the theme on a page. Callers set ``page.padding`` themselves."""
    page.theme = build_theme()
    page.dark_theme = page.theme
    page.theme_mode = ft.ThemeMode.DARK
    page.fonts = {FONT_FAMILY: INTER_FONT_URL}
    page.bgcolor = Palette.BG
    page.spacing = 0
    # Desktop window size; ignored (harmlessly) when serving to a browser.
    try:
        page.window.width = DEFAULT_WINDOW_WIDTH
        page.window.height = DEFAULT_WINDOW_HEIGHT
    except Exception:
        pass

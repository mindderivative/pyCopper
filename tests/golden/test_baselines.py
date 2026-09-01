"""Golden-image baselines: the whole pipeline, compared pixel by pixel.

These catch what property assertions cannot -- a shader regression that still
produces "some antialiased coverage in roughly the right place". Baselines are
committed; see conftest.py for how to regenerate them.
"""

from __future__ import annotations

import numpy as np
import pytest

from pycopper import App, Theme
from pycopper.paint import DisplayList

pytestmark = pytest.mark.gpu

SEED = "#6750A4"


def test_primitives_baseline(render_scene, assert_golden) -> None:
    """Every SDF primitive kind in one frame."""

    def paint(dl: DisplayList) -> None:
        dl.add_shadow(
            24,
            24,
            100,
            60,
            blur=10.0,
            offset=(0.0, 4.0),
            color=(0.0, 0.0, 0.0, 0.5),
            radii=(16,) * 4,
        )
        dl.add_box(24, 24, 100, 60, color=(0.80, 0.75, 0.92, 1.0), radii=(16,) * 4)
        dl.add_box(
            150,
            24,
            100,
            60,
            color=(0.25, 0.22, 0.30, 1.0),
            radii=(28, 4, 28, 4),
            border_width=3.0,
            border_color=(0.80, 0.75, 0.92, 1.0),
        )
        dl.add_box(
            24,
            110,
            226,
            50,
            color=(0.55, 0.45, 0.85, 1.0),
            clip=(60, 110, 150, 50),
            clip_radii=(24,) * 4,
        )

    frame, _ = render_scene(paint, width=280, height=180, theme=Theme(seed=SEED, dark=True))
    assert_golden("primitives", frame)


def test_text_baseline(render_scene, assert_golden) -> None:
    """Shaped text through the atlas: ligatures, kerning, two sizes."""
    _, engine = render_scene(
        lambda dl: None, width=360, height=120, theme=Theme(seed=SEED, dark=True)
    )

    def paint(dl: DisplayList) -> None:
        engine.text.emit(
            dl,
            engine.text.layout("Hamburgefons fi fl", px=26),
            x=16,
            y=14,
            token=engine.palette.index("primary"),
        )
        engine.text.emit(
            dl,
            engine.text.layout("AVATAR To Wa. quick brown fox", px=14),
            x=16,
            y=62,
            token=engine.palette.index("on_surface"),
        )

    engine.painter = paint
    engine.canvas.request_draw(engine.draw_frame)
    assert_golden("text", np.asarray(engine.canvas.draw()))


def test_wrapped_text_baseline(render_scene, assert_golden) -> None:
    """Line breaking and alignment."""
    _, engine = render_scene(
        lambda dl: None, width=300, height=160, theme=Theme(seed=SEED, dark=True)
    )
    body = "The quick brown fox jumps over the lazy dog and keeps running"

    def paint(dl: DisplayList) -> None:
        engine.text.emit(
            dl,
            engine.text.layout(body, px=14, max_width=260),
            x=20,
            y=16,
            token=engine.palette.index("on_surface"),
        )
        engine.text.emit(
            dl,
            engine.text.layout("centred", px=14, max_width=260, alignment="center"),
            x=20,
            y=110,
            token=engine.palette.index("primary"),
        )

    engine.painter = paint
    engine.canvas.request_draw(engine.draw_frame)
    assert_golden("text_wrapped", np.asarray(engine.canvas.draw()))


def test_widget_tree_baseline(render_scene, assert_golden) -> None:
    """A real App through the full four-tree pipeline."""
    view = {
        "id": "root",
        "widget": "Column",
        "style": {
            "background": "surface",
            "padding": 16,
            "spacing": 12,
            "width": "expand",
            "height": "expand",
            "cross_alignment": "stretch",
        },
        "children": [
            {
                "id": "title",
                "widget": "Text",
                "text": "Gallery",
                "style": {"color": "on_surface", "font_size": 20},
            },
            {
                "id": "card",
                "widget": "Container",
                "style": {
                    "height": 70,
                    "background": "surface_container_high",
                    "corner_radius": 16,
                    "padding": 14,
                    "border": {"width": 1, "color": "outline_variant"},
                    "shadow": {"blur": 12, "offset_y": 3},
                },
                "children": [
                    {
                        "id": "body",
                        "widget": "Text",
                        "text": "Elevated card",
                        "style": {"color": "on_surface_variant", "font_size": 14},
                    }
                ],
            },
            {
                "id": "row",
                "widget": "Row",
                "style": {"height": 44, "spacing": 10, "width": "expand"},
                "children": [
                    {
                        "id": "primary",
                        "widget": "Button",
                        "text": "Confirm",
                        "style": {
                            "width": 140,
                            "height": 44,
                            "background": "primary",
                            "color": "on_primary",
                            "corner_radius": 22,
                        },
                    },
                    {
                        "id": "tonal",
                        "widget": "Button",
                        "text": "Cancel",
                        "style": {
                            "width": 120,
                            "height": 44,
                            "background": "secondary_container",
                            "color": "on_secondary_container",
                            "corner_radius": 22,
                        },
                    },
                ],
            },
        ],
    }
    _, engine = render_scene(
        lambda dl: None, width=340, height=220, theme=Theme(seed=SEED, dark=True)
    )
    app = App(view, theme=Theme(seed=SEED, dark=True))
    app.attach(engine)
    engine.canvas.request_draw(engine.draw_frame)
    assert_golden("widget_tree", np.asarray(engine.canvas.draw()))


def test_light_theme_baseline(render_scene, assert_golden) -> None:
    """The same tokens in the light scheme -- catches palette regressions."""
    theme = Theme(seed=SEED, dark=False)
    _, engine = render_scene(lambda dl: None, width=260, height=120, theme=theme)

    def paint(dl: DisplayList) -> None:
        for i, token in enumerate(["primary", "secondary", "tertiary", "error"]):
            dl.add_box(16 + i * 58, 16, 48, 48, token=engine.palette.index(token), radii=(12,) * 4)
        engine.text.emit(
            dl,
            engine.text.layout("Light scheme", px=16),
            x=16,
            y=76,
            token=engine.palette.index("on_surface"),
        )

    engine.painter = paint
    engine.canvas.request_draw(engine.draw_frame)
    assert_golden("light_theme", np.asarray(engine.canvas.draw()))


def test_gallery_baseline(render_scene, assert_golden) -> None:
    """The full gallery example -- every widget kind in one frame.

    This is the corpus test: it exercises Container, Row, Column, Stack, Text,
    Button and Spacer together, so a regression anywhere in the four-tree
    pipeline shows up here.
    """
    import sys
    from pathlib import Path

    gallery = Path(__file__).resolve().parents[2] / "examples" / "gallery"
    sys.path.insert(0, str(gallery))
    try:
        import app as demo
    finally:
        sys.path.remove(str(gallery))

    _, engine = render_scene(
        lambda dl: None, width=560, height=460, theme=Theme(seed=SEED, dark=True)
    )
    demo.app.attach(engine)
    demo.clicks.set(3)
    engine.canvas.request_draw(engine.draw_frame)
    assert_golden("gallery", np.asarray(engine.canvas.draw()))


def test_icons_baseline(render_scene, assert_golden) -> None:
    """Material Symbols through the glyph atlas, across both live axes."""
    _, engine = render_scene(
        lambda dl: None, width=420, height=170, theme=Theme(seed=SEED, dark=True)
    )

    def paint(dl: DisplayList) -> None:
        on_surface = engine.palette.index("on_surface")
        primary = engine.palette.index("primary")
        row = [
            "home",
            "search",
            "settings",
            "person",
            "favorite",
            "star",
            "check_circle",
            "delete",
            "share",
            "menu",
        ]
        for i, name in enumerate(row):
            engine.text.emit_icon(dl, name, x=14 + i * 38, y=16, size=24, token=on_surface)
        # FILL 0 -> 1
        for i in range(5):
            engine.text.emit_icon(
                dl, "favorite", x=14 + i * 44, y=62, size=32, fill=i / 4, token=primary
            )
        # weight 200 -> 700
        for i, w in enumerate((200, 300, 400, 500, 700)):
            engine.text.emit_icon(
                dl,
                "bolt",
                x=14 + i * 44,
                y=112,
                size=32,
                weight=w,
                token=engine.palette.index("tertiary"),
            )

    engine.painter = paint
    engine.canvas.request_draw(engine.draw_frame)
    assert_golden("icons", np.asarray(engine.canvas.draw()))

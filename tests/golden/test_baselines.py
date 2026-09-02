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
        "name": "root",
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
                "name": "title",
                "widget": "Text",
                "text": "Gallery",
                "style": {"color": "on_surface", "font_size": 20},
            },
            {
                "name": "card",
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
                        "name": "body",
                        "widget": "Text",
                        "text": "Elevated card",
                        "style": {"color": "on_surface_variant", "font_size": 14},
                    }
                ],
            },
            {
                "name": "row",
                "widget": "Row",
                "style": {"height": 44, "spacing": 10, "width": "expand"},
                "children": [
                    {
                        "name": "primary",
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
                        "name": "tonal",
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
        lambda dl: None, width=620, height=720, theme=Theme(seed=SEED, dark=True)
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


def test_focus_ring_baseline(render_scene, assert_golden) -> None:
    """The ring must follow each control's shape -- a rectangle around a circle
    reads as a bug, and only a rendered image catches that."""
    from pycopper.runtime.events import EventType, KeyEvent

    view = {
        "name": "root",
        "widget": "Column",
        "style": {"background": "surface", "padding": 16},
        "children": [
            {
                "name": "row",
                "widget": "Row",
                "style": {"height": 56, "spacing": 20, "cross_alignment": "center"},
                "children": [
                    {
                        "name": "btn",
                        "widget": "Button",
                        "text": "Filled",
                        "style": {"width": 110, "height": 40, "variant": "filled"},
                    },
                    {"name": "cb", "widget": "Checkbox", "value": "true"},
                    {"name": "rd", "widget": "Radio", "value": "true"},
                    {"name": "sw", "widget": "Switch", "value": "false"},
                    {
                        "name": "ib",
                        "widget": "IconButton",
                        "text": "favorite",
                        "style": {"variant": "filled_tonal"},
                    },
                    {"name": "fab", "widget": "Fab", "text": "add", "style": {"variant": "small"}},
                ],
            }
        ],
    }
    _, engine = render_scene(
        lambda dl: None, width=520, height=88, theme=Theme(seed=SEED, dark=True)
    )
    app = App(view, theme=Theme(seed=SEED, dark=True))
    app.attach(engine)
    app.update()
    # Tab three times: focus lands on the radio, whose ring must be circular.
    for _ in range(3):
        app.dispatcher.post(KeyEvent(EventType.KEY_DOWN, key="Tab"))
    app.dispatcher.drain()
    engine.canvas.request_draw(engine.draw_frame)
    assert_golden("focus_ring", np.asarray(engine.canvas.draw()))


def test_navigation_baseline(render_scene, assert_golden) -> None:
    """Wave 2 in one frame: rail, app bar, tabs, progress, segments, lists."""
    from pycopper import Signal

    view = {
        "name": "root",
        "widget": "Row",
        "style": {"background": "surface", "width": "expand", "height": "expand"},
        "children": [
            {
                "name": "rail",
                "widget": "NavigationRail",
                "value": "{{ dest.get() }}",
                "style": {"spacing": 8, "padding": [0, 12]},
                "children": [
                    {
                        "name": "r_home",
                        "widget": "NavItem",
                        "text": "home",
                        "supporting_text": "Home",
                    },
                    {
                        "name": "r_search",
                        "widget": "NavItem",
                        "text": "search",
                        "supporting_text": "Search",
                    },
                    {
                        "name": "r_set",
                        "widget": "NavItem",
                        "text": "settings",
                        "supporting_text": "Settings",
                    },
                ],
            },
            {
                "name": "main",
                "widget": "Column",
                "style": {"width": "expand"},
                "children": [
                    {
                        "name": "bar",
                        "widget": "TopAppBar",
                        "text": "Wave 2",
                        "style": {"width": "expand"},
                    },
                    {
                        "name": "tabs",
                        "widget": "Tabs",
                        "value": "{{ tab.get() }}",
                        "style": {"width": "expand"},
                        "children": [
                            {"name": "t1", "widget": "Tab", "text": "Overview"},
                            {"name": "t2", "widget": "Tab", "text": "Details"},
                            {"name": "t3", "widget": "Tab", "text": "History"},
                        ],
                    },
                    {
                        "name": "prog",
                        "widget": "LinearProgress",
                        "value": "0.62",
                        "style": {"width": "expand"},
                    },
                    {
                        "name": "body",
                        "widget": "Column",
                        "style": {"padding": 16, "spacing": 14, "width": "expand"},
                        "children": [
                            {
                                "name": "seg",
                                "widget": "SegmentedButton",
                                "value": "{{ seg.get() }}",
                                "children": [
                                    {"name": "s1", "widget": "Segment", "text": "Day"},
                                    {"name": "s2", "widget": "Segment", "text": "Week"},
                                    {"name": "s3", "widget": "Segment", "text": "Month"},
                                ],
                            },
                            {
                                "name": "li1",
                                "widget": "ListItem",
                                "text": "Single line item",
                                "style": {"width": "expand"},
                            },
                            {"name": "dv", "widget": "Divider", "style": {"width": "expand"}},
                            {
                                "name": "li2",
                                "widget": "ListItem",
                                "text": "Two line item",
                                "supporting_text": "With supporting text beneath",
                                "style": {"width": "expand"},
                            },
                        ],
                    },
                ],
            },
        ],
    }
    _, engine = render_scene(
        lambda dl: None, width=680, height=400, theme=Theme(seed=SEED, dark=True)
    )
    app = App(view, theme=Theme(seed=SEED, dark=True))
    app.expose(dest=Signal("r_search"), tab=Signal("t2"), seg=Signal("s2"))
    app.attach(engine)
    engine.canvas.request_draw(engine.draw_frame)
    assert_golden("navigation", np.asarray(engine.canvas.draw()))


def test_overlay_baseline(render_scene, assert_golden) -> None:
    """A modal dialog over a 32% scrim, and an anchored menu beside it."""
    from pycopper import Signal

    view = {
        "root": {
            "name": "root",
            "widget": "Column",
            "style": {"background": "surface", "padding": 20, "spacing": 12},
            "children": [
                {
                    "name": "open_btn",
                    "widget": "Button",
                    "text": "Open dialog",
                    "style": {"width": 170, "height": 40},
                },
                {
                    "name": "menu_btn",
                    "widget": "Button",
                    "text": "Menu",
                    "style": {"width": 120, "height": 40, "variant": "outlined"},
                },
                {
                    "name": "li",
                    "widget": "ListItem",
                    "text": "Background content",
                    "supporting_text": "Dimmed by the scrim",
                    "style": {"width": "expand"},
                },
            ],
        },
        "overlays": [
            {
                "name": "menu",
                "widget": "Card",
                "open": "true",
                "style": {
                    "width": 190,
                    "placement": "anchor",
                    "anchor": "menu_btn",
                    "variant": "filled",
                    "corner_radius": 4,
                    "padding": 0,
                },
                "children": [
                    {
                        "name": "mcol",
                        "widget": "Column",
                        "style": {"width": "expand"},
                        "children": [
                            {
                                "name": "m1",
                                "widget": "ListItem",
                                "text": "Rename",
                                "style": {"width": "expand"},
                            },
                            {
                                "name": "m2",
                                "widget": "ListItem",
                                "text": "Duplicate",
                                "style": {"width": "expand"},
                            },
                        ],
                    }
                ],
            },
            {
                "name": "dlg",
                "widget": "Card",
                "open": "{{ show.get() }}",
                "style": {
                    "width": 280,
                    "height": 140,
                    "placement": "center",
                    "modal": True,
                    "scrim": True,
                    "variant": "elevated",
                    "corner_radius": 28,
                    "padding": 24,
                },
                "children": [
                    {
                        "name": "dt",
                        "widget": "Text",
                        "text": "Modal dialog",
                        "style": {"font_size": 20},
                    }
                ],
            },
        ],
    }
    _, engine = render_scene(
        lambda dl: None, width=470, height=280, theme=Theme(seed=SEED, dark=True)
    )
    app = App(view, theme=Theme(seed=SEED, dark=True))
    app.expose(show=Signal(True))
    app.attach(engine)
    engine.canvas.request_draw(engine.draw_frame)
    assert_golden("overlay", np.asarray(engine.canvas.draw()))


def test_overlay_components_baseline(render_scene, assert_golden) -> None:
    """The six real M3 overlay components, rather than hand-built stand-ins.

    Deliberately separate from `test_overlay_baseline`, which stays as it is:
    that one proves the *host* can float an arbitrary widget, this one proves
    the components themselves render to their M3 anatomy. A side sheet, an
    anchored menu, a tooltip and a snackbar are placed at once because their
    placements do not collide.
    """
    view = {
        "root": {
            "name": "root",
            "widget": "Column",
            "style": {"background": "surface", "padding": 20, "spacing": 12},
            "children": [
                {
                    "name": "top",
                    "widget": "Row",
                    "style": {"width": "expand", "height": 40, "spacing": 12},
                    "children": [
                        {
                            "name": "menu_btn",
                            "widget": "Button",
                            "text": "Actions",
                            "style": {"width": 130, "height": 40, "variant": "outlined"},
                        },
                        {"name": "gap", "widget": "Spacer", "style": {"width": 30}},
                        {
                            "name": "tip_btn",
                            "widget": "IconButton",
                            "text": "info",
                            "style": {"variant": "standard"},
                        },
                    ],
                },
            ],
        },
        "overlays": [
            {
                "name": "menu",
                "widget": "Menu",
                "open": "true",
                "style": {"placement": "anchor", "anchor": "menu_btn", "width": 200},
                "children": [
                    {"name": "cut", "widget": "MenuItem", "text": "Cut", "supporting_text": "^X"},
                    {"name": "copy", "widget": "MenuItem", "text": "Copy", "supporting_text": "^C"},
                    {"name": "paste", "widget": "MenuItem", "text": "Paste"},
                ],
            },
            {
                "name": "tip",
                "widget": "Tooltip",
                "text": "More information",
                "open": "true",
                "style": {"placement": "anchor", "anchor": "tip_btn"},
            },
            {
                "name": "sheet",
                "widget": "SideSheet",
                "open": "true",
                "style": {"placement": "right", "width": 190},
                "children": [
                    {
                        "name": "sheet_title",
                        "widget": "Text",
                        "text": "Side sheet",
                        "style": {"font_size": 16},
                    }
                ],
            },
            {
                "name": "snack",
                "widget": "Snackbar",
                "text": "Item archived",
                "supporting_text": "Undo",
                "open": "true",
                "style": {"placement": "bottom", "width": 320},
            },
        ],
    }
    _, engine = render_scene(
        lambda dl: None, width=560, height=320, theme=Theme(seed=SEED, dark=True)
    )
    app = App(view, theme=Theme(seed=SEED, dark=True))
    app.attach(engine)
    engine.canvas.request_draw(engine.draw_frame)
    assert_golden("overlay_components", np.asarray(engine.canvas.draw()))


def test_dialog_baseline(render_scene, assert_golden) -> None:
    """A modal Dialog over its 32% scrim, shrink-wrapped around its content.

    Its own frame: a centred modal dialog would sit on top of the
    bottom-anchored snackbar in the frame above.
    """
    view = {
        "root": {
            "name": "root",
            "widget": "Column",
            "style": {"background": "surface", "padding": 20, "spacing": 12},
            "children": [
                {
                    "name": "bg",
                    "widget": "ListItem",
                    "text": "Background content",
                    "supporting_text": "Dimmed by the 32% scrim",
                    "style": {"width": "expand"},
                }
            ],
        },
        "overlays": [
            {
                "name": "dlg",
                "widget": "Dialog",
                "text": "Delete this item?",
                "supporting_text": "This action cannot be undone, and the item "
                "will not be recoverable.",
                "open": "true",
                "style": {"modal": True, "scrim": True, "width": 360},
                "children": [
                    {
                        "name": "actions",
                        "widget": "Row",
                        "style": {
                            "width": "expand",
                            "height": 40,
                            "spacing": 8,
                            "main_alignment": "end",
                        },
                        "children": [
                            {
                                "name": "cancel",
                                "widget": "Button",
                                "text": "Cancel",
                                "style": {"width": 90, "height": 40, "variant": "text"},
                            },
                            {
                                "name": "delete",
                                "widget": "Button",
                                "text": "Delete",
                                "style": {"width": 90, "height": 40, "variant": "filled"},
                            },
                        ],
                    }
                ],
            },
        ],
    }
    _, engine = render_scene(
        lambda dl: None, width=460, height=300, theme=Theme(seed=SEED, dark=True)
    )
    app = App(view, theme=Theme(seed=SEED, dark=True))
    app.attach(engine)
    engine.canvas.request_draw(engine.draw_frame)
    assert_golden("dialog", np.asarray(engine.canvas.draw()))


def test_bottom_sheet_baseline(render_scene, assert_golden) -> None:
    """A BottomSheet with its drag handle, flush with the window's bottom edge.

    Its own frame too -- it shares the bottom placement with the snackbar.
    The handle is drawn but not draggable; see `BottomSheetElement`.
    """
    view = {
        "root": {
            "name": "root",
            "widget": "Column",
            "style": {"background": "surface", "padding": 20},
            "children": [
                {
                    "name": "bg",
                    "widget": "Text",
                    "text": "Background content",
                    "style": {"font_size": 16},
                }
            ],
        },
        "overlays": [
            {
                "name": "sheet",
                "widget": "BottomSheet",
                "open": "true",
                "style": {"handle": True, "scrim": True, "modal": True},
                "children": [
                    {
                        "name": "sheet_title_pad",
                        "widget": "Container",
                        "style": {"padding": [16, 16, 16, 4]},
                        "children": [
                            {
                                "name": "sheet_title",
                                "widget": "Text",
                                "text": "Bottom sheet",
                                "style": {"font_size": 16},
                            }
                        ],
                    },
                    {
                        "name": "sheet_item",
                        "widget": "ListItem",
                        "text": "An action",
                        "supporting_text": "With supporting text",
                        "style": {"width": "expand"},
                    },
                ],
            },
        ],
    }
    _, engine = render_scene(
        lambda dl: None, width=440, height=300, theme=Theme(seed=SEED, dark=True)
    )
    app = App(view, theme=Theme(seed=SEED, dark=True))
    app.attach(engine)
    engine.canvas.request_draw(engine.draw_frame)
    assert_golden("bottom_sheet", np.asarray(engine.canvas.draw()))


def test_scroll_baseline(render_scene, assert_golden) -> None:
    """A scrolled viewport: rows clipped at both edges, scrollbar part-way down.

    The mid-scroll position is the point -- it proves the clip is real (the
    first visible row is cut off at the top, not merely absent) and that the
    scrollbar thumb tracks the offset.
    """
    view = {
        "root": {
            "name": "root",
            "widget": "Column",
            "style": {"background": "surface", "padding": 16, "spacing": 10},
            "children": [
                {
                    "name": "heading",
                    "widget": "Text",
                    "text": "Scrollable list",
                    "style": {"font_size": 16},
                },
                {
                    "name": "sv",
                    "widget": "ScrollView",
                    "style": {
                        "height": 180,
                        "width": "expand",
                        "background": "surface_container",
                        "corner_radius": 12,
                    },
                    "children": [
                        {
                            "name": "col",
                            "widget": "Column",
                            "style": {"width": "expand"},
                            "children": [
                                {
                                    "name": f"row{i}",
                                    "widget": "ListItem",
                                    "text": f"Item {i}",
                                    "supporting_text": "Supporting text",
                                    "style": {"width": "expand"},
                                }
                                for i in range(10)
                            ],
                        }
                    ],
                },
            ],
        }
    }
    _, engine = render_scene(
        lambda dl: None, width=380, height=260, theme=Theme(seed=SEED, dark=True)
    )
    app = App(view, theme=Theme(seed=SEED, dark=True))
    app.attach(engine)
    app.mount()
    app.update()
    app.root.find("sv").set_scroll(90.0)
    engine.canvas.request_draw(engine.draw_frame)
    assert_golden("scroll", np.asarray(engine.canvas.draw()))

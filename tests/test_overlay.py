"""The overlay layer: placement, modality, scrim, dismissal, hit testing."""

from __future__ import annotations

import pytest

from pycopper import App, Signal, Theme
from pycopper.paint import DisplayList
from pycopper.runtime.events import EventType, KeyEvent, PointerEvent
from pycopper.runtime.overlay import SCRIM_OPACITY
from pycopper.theme import Palette

PAL = Palette(Theme(dark=True))


def make(overlays, root_children=None, **signals):
    view = {
        "root": {
            "name": "root",
            "widget": "Column",
            "style": {"background": "surface", "padding": 20, "spacing": 10},
            "children": root_children
            if root_children is not None
            else [
                {
                    "name": "btn",
                    "widget": "Button",
                    "text": "Open",
                    "style": {"width": 150, "height": 40},
                }
            ],
        },
        "overlays": overlays,
    }
    app = App(view, theme=Theme(dark=True))
    app.expose(**signals)
    app.mount()
    app.update()
    return app


def dialog(**style):
    base = {"width": 200, "height": 120, "placement": "center"}
    base.update(style)
    return {"name": "dlg", "widget": "Card", "open": "{{ show.get() }}", "style": base}


def paint(app) -> DisplayList:
    dl = DisplayList()
    app.paint(dl)
    return dl


# ------------------------------------------------------------- declaration


def test_overlays_are_not_part_of_the_root_tree() -> None:
    """A dialog must not be laid out or clipped by whatever opened it."""
    app = make([dialog()], show=Signal(True))
    assert "dlg" not in [e.name for e in app.root.walk_elements()]
    assert app.overlays.find("dlg") is not None


def test_hidden_by_default() -> None:
    app = make([dialog()], show=Signal(False))
    assert app.overlays.visible() == []


def test_open_binding_shows_it() -> None:
    show = Signal(False)
    app = make([dialog()], show=show)
    show.set(True)
    app.update()
    assert [e.element.name for e in app.overlays.visible()] == ["dlg"]


def test_overlay_contributes_nothing_to_root_layout() -> None:
    closed = make([dialog()], show=Signal(False))
    opened = make([dialog()], show=Signal(True))
    assert closed.root.size == opened.root.size
    assert closed.root.find("btn").offset == opened.root.find("btn").offset


# ---------------------------------------------------------------- placement


def test_centred_placement() -> None:
    app = make([dialog()], show=Signal(True))
    entry = app.overlays.visible()[0]
    window = app.logical_size()
    rect = entry.rect()
    assert rect.x == pytest.approx((window.width - rect.width) / 2)
    assert rect.y == pytest.approx((window.height - rect.height) / 2)


@pytest.mark.parametrize("edge", ["top", "bottom", "left", "right"])
def test_edge_placements_stay_inside_the_window(edge: str) -> None:
    app = make([dialog(placement=edge)], show=Signal(True))
    rect = app.overlays.visible()[0].rect()
    window = app.logical_size()
    assert rect.x >= 0 and rect.y >= 0
    assert rect.right <= window.width and rect.bottom <= window.height


def test_anchored_overlay_sits_below_its_anchor() -> None:
    app = make([dialog(placement="anchor", anchor="btn", height=60)], show=Signal(True))
    rect = app.overlays.visible()[0].rect()
    anchor = app.root.find("btn").absolute_rect()
    assert rect.y >= anchor.bottom


def test_anchored_overlay_flips_above_when_it_would_overflow() -> None:
    """A menu that runs off the bottom is useless, so anchoring flips it."""
    app = make(
        [dialog(placement="anchor", anchor="btn", height=2000)],
        show=Signal(True),
    )
    rect = app.overlays.visible()[0].rect()
    assert rect.y >= 0


def test_missing_anchor_falls_back_rather_than_crashing() -> None:
    app = make([dialog(placement="anchor", anchor="nonexistent")], show=Signal(True))
    assert app.overlays.visible()[0].rect().y >= 0


# ------------------------------------------------------------------- paint


def test_scrim_is_emitted_at_the_m3_opacity() -> None:
    app = make([dialog(scrim=True, modal=True)], show=Signal(True))
    scrims = [
        s
        for s in paint(app).view
        if int(s["flags"][2]) == PAL.index("scrim")
        and abs(float(s["fill"][3]) - SCRIM_OPACITY) < 1e-4
    ]
    assert len(scrims) == 1


def test_scrim_covers_the_window_exactly() -> None:
    """Not an arbitrarily large quad -- that wastes fill and hurts precision."""
    app = make([dialog(scrim=True, modal=True)], show=Signal(True))
    window = app.logical_size()
    scrim = next(s for s in paint(app).view if int(s["flags"][2]) == PAL.index("scrim"))
    assert float(scrim["rect"][2]) == pytest.approx(window.width)
    assert float(scrim["rect"][3]) == pytest.approx(window.height)


def test_no_scrim_without_the_flag() -> None:
    app = make([dialog(modal=True)], show=Signal(True))
    assert not any(int(s["flags"][2]) == PAL.index("scrim") for s in paint(app).view)


def test_overlay_paints_above_the_tree() -> None:
    app = make([dialog(scrim=True, modal=True)], show=Signal(True))
    dl = paint(app)
    scrim_index = next(i for i, s in enumerate(dl.view) if int(s["flags"][2]) == PAL.index("scrim"))
    # The root background is instance 0; the scrim comes after it.
    assert scrim_index > 0


def test_closed_overlay_paints_nothing() -> None:
    closed = len(paint(make([dialog()], show=Signal(False))))
    opened = len(paint(make([dialog()], show=Signal(True))))
    assert opened > closed


# -------------------------------------------------------------- hit testing


def test_click_inside_an_overlay_hits_it() -> None:
    app = make([dialog(modal=True)], show=Signal(True))
    rect = app.overlays.visible()[0].rect()
    path = app.dispatcher.hit_path(rect.x + 10, rect.y + 10)
    assert path and path[-1].name == "dlg"


def test_modal_blocks_the_tree_beneath() -> None:
    """Otherwise a click on the scrim falls through to the blocked interface."""
    app = make([dialog(modal=True, scrim=True)], show=Signal(True))
    assert app.dispatcher.hit_path(25, 25) == []


def test_non_modal_lets_the_tree_through() -> None:
    app = make([dialog(modal=False)], show=Signal(True))
    assert app.dispatcher.hit_path(25, 25) != []


def test_closed_overlay_does_not_block() -> None:
    app = make([dialog(modal=True)], show=Signal(False))
    assert app.dispatcher.hit_path(25, 25) != []


# --------------------------------------------------------------- dismissal


def test_escape_dismisses_the_top_overlay() -> None:
    app = make([dialog(modal=True)], show=Signal(True))
    app.dispatcher.post(KeyEvent(EventType.KEY_DOWN, key="Escape"))
    app.dispatcher.drain()
    app.update()
    assert app.overlays.visible() == []


def test_escape_does_not_dismiss_a_non_dismissable_overlay() -> None:
    app = make([dialog(modal=True, dismissable=False)], show=Signal(True))
    app.dispatcher.post(KeyEvent(EventType.KEY_DOWN, key="Escape"))
    app.dispatcher.drain()
    app.update()
    assert len(app.overlays.visible()) == 1


def test_clicking_outside_a_modal_dismisses_it() -> None:
    app = make([dialog(modal=True, scrim=True)], show=Signal(True))
    app.dispatcher.post(PointerEvent(EventType.POINTER_DOWN, x=5, y=5))
    app.dispatcher.drain()
    app.update()
    assert app.overlays.visible() == []


def test_clicking_inside_does_not_dismiss() -> None:
    app = make([dialog(modal=True)], show=Signal(True))
    rect = app.overlays.visible()[0].rect()
    app.dispatcher.post(PointerEvent(EventType.POINTER_DOWN, x=rect.x + 10, y=rect.y + 10))
    app.dispatcher.drain()
    app.update()
    assert len(app.overlays.visible()) == 1


def test_reopening_after_a_dismissal_works() -> None:
    """A dismissal must not outlive the state change that closed it."""
    show = Signal(True)
    app = make([dialog(modal=True)], show=show)
    app.dispatcher.post(KeyEvent(EventType.KEY_DOWN, key="Escape"))
    app.dispatcher.drain()
    app.update()
    assert app.overlays.visible() == []

    show.set(False)
    app.update()
    show.set(True)
    app.update()
    assert len(app.overlays.visible()) == 1


def test_escape_dismisses_before_clearing_focus() -> None:
    app = make([dialog(modal=True)], show=Signal(True))
    app.dispatcher.focus(app.root.find("btn"), keyboard=True)
    app.dispatcher.post(KeyEvent(EventType.KEY_DOWN, key="Escape"))
    app.dispatcher.drain()
    app.update()
    assert app.overlays.visible() == []
    assert app.dispatcher.focused is not None, "focus was cleared as well"


# ------------------------------------------------------------------ z-order


def test_declaration_order_is_z_order() -> None:
    a = {"name": "a", "widget": "Card", "open": "true", "style": {"width": 100, "height": 100}}
    b = {"name": "b", "widget": "Card", "open": "true", "style": {"width": 100, "height": 100}}
    app = make([a, b])
    assert [e.element.name for e in app.overlays.visible()] == ["a", "b"]


def test_topmost_overlay_wins_hit_testing() -> None:
    a = {"name": "a", "widget": "Card", "open": "true", "style": {"width": 200, "height": 200}}
    b = {"name": "b", "widget": "Card", "open": "true", "style": {"width": 200, "height": 200}}
    app = make([a, b])
    rect = app.overlays.visible()[0].rect()
    path = app.dispatcher.hit_path(rect.x + 10, rect.y + 10)
    assert path[-1].name == "b"


# ----------------------------------------------------------------- handlers


def test_handlers_inside_an_overlay_resolve() -> None:
    calls: list[str] = []
    view = {
        "root": {"name": "root", "widget": "Column", "children": []},
        "overlays": [
            {
                "name": "dlg",
                "widget": "Card",
                "open": "true",
                "style": {"width": 200, "height": 100},
                "children": [
                    {
                        "name": "ok",
                        "widget": "Button",
                        "text": "OK",
                        "style": {"width": 80, "height": 40},
                        "handlers": {"on_click": "confirm"},
                    }
                ],
            }
        ],
    }
    app = App(view, theme=Theme(dark=True))
    app.handler(lambda e: calls.append("ok"))  # type: ignore[arg-type]
    app._handlers["confirm"] = lambda e: calls.append("confirm")
    app.mount()
    app.update()
    ok = app.overlays.find("ok")
    rect = ok.absolute_rect()
    entry = app.overlays.visible()[0]
    x = entry.origin.x + rect.x + 5
    y = entry.origin.y + rect.y + 5
    app.dispatcher.post(PointerEvent(EventType.POINTER_DOWN, x=x, y=y))
    app.dispatcher.post(PointerEvent(EventType.POINTER_UP, x=x, y=y))
    app.dispatcher.drain()
    assert "confirm" in calls


# ------------------------------------------------------- single-child guard


def test_single_child_container_rejects_extra_children() -> None:
    """It lays out only the first but paints them all, so extras would overlap."""
    with pytest.raises(ValueError, match="single child"):
        App(
            {
                "name": "r",
                "widget": "Column",
                "children": [
                    {
                        "name": "c",
                        "widget": "Card",
                        "children": [
                            {"name": "a", "widget": "Text", "text": "one"},
                            {"name": "b", "widget": "Text", "text": "two"},
                        ],
                    }
                ],
            },
            theme=Theme(dark=True),
        )


def test_column_sized_only_on_width_does_not_fill_vertically() -> None:
    """A Column's main axis is its HEIGHT; keying fill off `width` made a
    menu stretch to the bottom of the window."""
    app = App(
        {
            "name": "r",
            "widget": "Column",
            "style": {"background": "surface"},
            "children": [
                {
                    "name": "c",
                    "widget": "Column",
                    "style": {"width": "expand"},
                    "children": [
                        {
                            "name": "a",
                            "widget": "ListItem",
                            "text": "one",
                            "style": {"width": "expand"},
                        },
                        {
                            "name": "b",
                            "widget": "ListItem",
                            "text": "two",
                            "style": {"width": "expand"},
                        },
                    ],
                }
            ],
        },
        theme=Theme(dark=True),
    )
    app.mount()
    app.update()
    assert app.root.find("c").size.height == pytest.approx(112.0)

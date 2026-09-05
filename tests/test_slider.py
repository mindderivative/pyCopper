"""Slider: a value picked from a range by dragging, clicking, or the keyboard.

M3's own explicit behaviours, verified one at a time: "Select & drag",
"Select jump", "Select & arrow" (`COMPONENT_SLIDERS.md`'s own "Behaviors"
section) -- plus the dimensions its own measurement table gives for XS.
"""

from __future__ import annotations

import pytest

from pycopper.layout import INF, Constraints, Offset
from pycopper.paint import DisplayList, Kind
from pycopper.runtime.events import EventDispatcher, EventType, KeyEvent, PointerEvent
from pycopper.spec import WidgetKind, parse_view
from pycopper.theme import Palette, Theme
from pycopper.tree.element import PaintContext
from pycopper.widgets import build_element
from pycopper.widgets.base import _REGISTRY, create_element
from pycopper.widgets.slider import SliderElement

PAL = Palette(Theme(dark=True))


def slider(width: float = 200.0, **spec) -> SliderElement:
    node = {"name": "s", "widget": "Slider", **spec}
    element = build_element(parse_view(node).root)
    element.layout(Constraints(0.0, width, 0.0, 200.0))
    return element


def driver(element, *, focus: bool = True) -> EventDispatcher:
    dispatcher = EventDispatcher()
    dispatcher.root = element
    if focus:
        dispatcher.focus(element)
    return dispatcher


def press(dispatcher, key: str) -> None:
    dispatcher.post(KeyEvent(EventType.KEY_DOWN, key=key))
    dispatcher.drain()


def press_at(dispatcher, element: SliderElement, fraction: float) -> None:
    rect = element.absolute_rect()
    x = rect.x + fraction * (element.size.width - element.HANDLE_WIDTH) + element.HANDLE_WIDTH / 2
    y = rect.y + element.size.height / 2
    dispatcher.post(PointerEvent(EventType.POINTER_DOWN, x=x, y=y))
    dispatcher.drain()


def drag_to(dispatcher, element: SliderElement, fraction: float) -> None:
    rect = element.absolute_rect()
    x = rect.x + fraction * (element.size.width - element.HANDLE_WIDTH) + element.HANDLE_WIDTH / 2
    y = rect.y + element.size.height / 2
    dispatcher.post(PointerEvent(EventType.POINTER_MOVE, x=x, y=y, button=1))
    dispatcher.drain()


def painted(element: SliderElement) -> DisplayList:
    dl = DisplayList()
    ctx = PaintContext(display_list=dl, palette=PAL)
    element.paint(ctx, Offset(0.0, 0.0))
    return dl


# --------------------------------------------------------------- registered


def test_kind_builds() -> None:
    assert slider() is not None


def test_every_kind_is_registered() -> None:
    create_element(parse_view({"name": "x", "widget": "Slider"}).root)
    assert WidgetKind.SLIDER in _REGISTRY


def test_is_focusable() -> None:
    from pycopper.runtime.events import FOCUSABLE_KINDS

    assert "Slider" in FOCUSABLE_KINDS


# ------------------------------------------------------ M3 dimensions (dp)


def test_handle_height_sets_the_overall_height() -> None:
    """M3 XS anatomy: 44dp handle, taller than the 16dp track it sits on."""
    e = slider()
    assert e.size.height == SliderElement.HANDLE_HEIGHT == 44.0


def test_an_unbounded_width_falls_back_to_its_own_minimum() -> None:
    node = {"name": "s", "widget": "Slider"}
    element = build_element(parse_view(node).root)
    element.layout(Constraints(0.0, INF, 0.0, 200.0))
    assert element.size.width == SliderElement.MIN_WIDTH


def test_a_bounded_width_is_honoured() -> None:
    assert slider(width=350.0).size.width == 350.0


# ------------------------------------------------------------------ bounds


def test_default_bounds_are_zero_to_one() -> None:
    e = slider(value="0.5")
    assert e.number == 0.5


def test_explicit_bounds_are_used() -> None:
    e = slider(value="50", style={"min": 0, "max": 100})
    assert e._fraction() == pytest.approx(0.5)


def test_value_is_clamped_to_bounds() -> None:
    e = slider(value="150", style={"min": 0, "max": 100})
    # Reading _fraction (not .number, which reports the raw bound value)
    # proves the widget treats an out-of-range value as pinned to the end
    # of the track rather than drawing the handle off it.
    assert e._fraction() == pytest.approx(1.0)


# --------------------------------------------------------- select and jump


def test_pointer_down_jumps_to_the_press_position() -> None:
    """M3: "Select jump -- Select a value by selecting part of the track"."""
    e = slider(value="0", style={"min": 0, "max": 100})
    dispatcher = driver(e)
    press_at(dispatcher, e, 0.5)
    assert e.number == pytest.approx(50.0, abs=1.0)


def test_pointer_down_fires_on_change() -> None:
    e = slider(value="0", style={"min": 0, "max": 100}, handlers={"on_change": "changed"})
    dispatcher = driver(e)
    seen: list[str] = []
    dispatcher.bind_handlers({"changed": lambda event: seen.append(event.value)})
    press_at(dispatcher, e, 1.0)
    assert seen == ["100"]


# --------------------------------------------------------------- select and drag


def test_dragging_after_press_keeps_committing_the_value() -> None:
    """M3: "Select & drag -- The handle drags smoothly" and "Changes made
    with sliders must take effect immediately", not only on release."""
    e = slider(value="0", style={"min": 0, "max": 100})
    dispatcher = driver(e)
    press_at(dispatcher, e, 0.2)
    assert e.number == pytest.approx(20.0, abs=1.0)
    drag_to(dispatcher, e, 0.8)
    assert e.number == pytest.approx(80.0, abs=1.0)


def test_moving_without_a_prior_press_does_nothing() -> None:
    e = slider(value="10", style={"min": 0, "max": 100})
    dispatcher = driver(e)
    drag_to(dispatcher, e, 0.9)
    assert e.number == 10.0


def test_pointer_up_stops_the_drag() -> None:
    e = slider(value="0", style={"min": 0, "max": 100})
    dispatcher = driver(e)
    press_at(dispatcher, e, 0.5)
    dispatcher.post(PointerEvent(EventType.POINTER_UP, x=0.0, y=0.0))
    dispatcher.drain()
    drag_to(dispatcher, e, 1.0)
    assert e.number == pytest.approx(50.0, abs=1.0)


# ------------------------------------------------------------- select and arrow


def test_arrow_keys_step_by_the_configured_step() -> None:
    """M3: "Arrows -- Selected value increases or decreases by one value"."""
    e = slider(value="20", style={"min": 0, "max": 100, "step": 5})
    dispatcher = driver(e)
    press(dispatcher, "ArrowRight")
    assert e.number == 25.0
    press(dispatcher, "ArrowLeft")
    assert e.number == 20.0


def test_home_and_end_jump_to_the_bounds() -> None:
    """M3: "Home or End -- Set the slider to the first and last values"."""
    e = slider(value="50", style={"min": 0, "max": 100})
    dispatcher = driver(e)
    press(dispatcher, "Home")
    assert e.number == 0.0
    press(dispatcher, "End")
    assert e.number == 100.0


def test_arrow_keys_do_not_move_past_the_bounds() -> None:
    e = slider(value="100", style={"min": 0, "max": 100, "step": 5})
    dispatcher = driver(e)
    press(dispatcher, "ArrowRight")
    assert e.number == 100.0


# --------------------------------------------------------------------- misc


def test_a_disabled_slider_ignores_pointer_and_keyboard() -> None:
    e = slider(value="10", disabled="true", style={"min": 0, "max": 100})
    dispatcher = driver(e)
    press_at(dispatcher, e, 0.9)
    press(dispatcher, "End")
    assert e.number == 10.0


def test_painting_does_not_crash() -> None:
    dl = painted(slider(value="50", style={"min": 0, "max": 100}))
    assert dl.view.shape[0] > 0


def test_a_higher_value_paints_a_wider_active_track() -> None:
    def active_widths(dl: DisplayList) -> list[float]:
        return [float(s["rect"][2]) for s in dl.view if int(s["flags"][2]) == PAL.index("primary")]

    low = painted(slider(value="10", style={"min": 0, "max": 100}))
    high = painted(slider(value="90", style={"min": 0, "max": 100}))
    assert max(active_widths(high)) > max(active_widths(low))


def test_the_handle_is_drawn_taller_than_the_track() -> None:
    """M3's own visual point: a vertical bar, not a circular thumb like Switch."""
    dl = painted(slider(value="50", style={"min": 0, "max": 100}))
    heights = {round(float(s["rect"][3]), 3) for s in dl.view if s["flags"][0] == Kind.BOX}
    assert round(SliderElement.HANDLE_HEIGHT, 3) in heights
    assert round(SliderElement.TRACK_HEIGHT, 3) in heights

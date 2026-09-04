"""DockSplit, DockGroup, DockPanel: a resizable, tabbed panel layout.

No M3 grounding exists for any of the three -- checked directly, not
assumed absent, the same way every other ungrounded widget this session was.
"""

from __future__ import annotations

import pytest

from pycopper import App, Signal, Theme
from pycopper.layout import Constraints, Size
from pycopper.paint import DisplayList
from pycopper.runtime.events import EventType, KeyEvent, PointerEvent
from pycopper.spec import WidgetKind, parse_view
from pycopper.theme import Palette
from pycopper.widgets import build_element

PAL = Palette(Theme(dark=True))
LOOSE = Constraints.loose(Size(1000.0, 800.0))


def laid_out(spec: dict, constraints: Constraints = LOOSE):
    element = build_element(parse_view(spec).root)
    element.layout(constraints)
    return element


def app(view: dict, **signals) -> App:
    a = App(view, theme=Theme(dark=True))
    a.expose(**signals)
    a.mount()
    a.update()
    return a


def paint(a: App) -> DisplayList:
    dl = DisplayList()
    a.paint(dl)
    return dl


def click(a: App, x: float, y: float) -> None:
    a.dispatcher.post(PointerEvent(EventType.POINTER_DOWN, x=x, y=y))
    a.dispatcher.post(PointerEvent(EventType.POINTER_UP, x=x, y=y))
    a.dispatcher.drain()


def panel(name: str, text: str) -> dict:
    return {
        "name": name,
        "widget": "DockPanel",
        "text": text,
        "children": [{"widget": "Text", "text": text}],
    }


# --------------------------------------------------------------- registered


@pytest.mark.parametrize("kind", ["DockSplit", "DockGroup", "DockPanel"])
def test_kind_builds(kind: str) -> None:
    assert laid_out({"name": "w", "widget": kind}) is not None


def test_every_kind_is_registered() -> None:
    from pycopper.widgets.base import _REGISTRY, create_element

    create_element(parse_view({"name": "x", "widget": "DockSplit"}).root)
    assert set(_REGISTRY) == set(WidgetKind)


# -------------------------------------------------------------- DockPanel


def test_a_panel_sizes_to_its_content() -> None:
    e = laid_out(
        {
            "name": "w",
            "widget": "DockPanel",
            "children": [{"widget": "Container", "style": {"width": 200, "height": 100}}],
        }
    )
    assert e.size == Size(200, 100)


def test_an_empty_panel_is_a_box_around_nothing() -> None:
    assert laid_out({"name": "w", "widget": "DockPanel"}).size == Size(0, 0)


# -------------------------------------------------------------- DockGroup


def _group(*, value: str | None = None, handlers: dict | None = None) -> dict:
    spec: dict = {
        "name": "g",
        "widget": "DockGroup",
        "children": [panel("a", "Files"), panel("b", "Search")],
    }
    if value is not None:
        spec["value"] = value
    if handlers is not None:
        spec["handlers"] = handlers
    return spec


def test_group_defaults_to_the_first_panel() -> None:
    e = laid_out(_group())
    assert e._active_name() == "a"


def test_an_explicit_value_selects_that_panel() -> None:
    e = laid_out(_group(value="b"))
    assert e._active_name() == "b"


def test_an_unmatched_value_falls_back_to_the_first_panel() -> None:
    e = laid_out(_group(value="nope"))
    assert e._active_name() == "a"


def test_only_the_active_panel_gets_real_size() -> None:
    e = laid_out(_group(value="a"), Constraints.tight(Size(400.0, 300.0)))
    a_panel = e.find("a")
    b_panel = e.find("b")
    assert a_panel.size.height > 0.0
    assert b_panel.size == Size(0.0, 0.0)


def test_the_active_panel_is_marked_selected() -> None:
    e = laid_out(_group(value="b"), Constraints.tight(Size(400.0, 300.0)))
    assert e.find("b").selected
    assert not e.find("a").selected


def test_clicking_a_tab_switches_the_active_panel() -> None:
    view = {"name": "root", "widget": "Column", "children": [_group(value="a")]}
    a = app(view)
    g = a.root.find("g")
    _, x, w = g._tab_rects()[1]
    rect = g.absolute_rect()
    click(a, rect.x + x + w / 2, rect.y + 20)
    assert g._active_name() == "b"


def test_on_change_carries_the_new_panel_name() -> None:
    calls = []
    view = {
        "name": "root",
        "widget": "Column",
        "children": [_group(value="a", handlers={"on_change": "switch"})],
    }
    a = App(view, theme=Theme(dark=True))
    a._handlers["switch"] = lambda e: calls.append(e.value)
    a.mount()
    a.update()
    g = a.root.find("g")
    _, x, w = g._tab_rects()[1]
    rect = g.absolute_rect()
    click(a, rect.x + x + w / 2, rect.y + 20)
    assert calls == ["b"]


def test_value_is_bindable_to_a_signal() -> None:
    view = {
        "name": "root",
        "widget": "Column",
        "children": [_group(value="{{ tab.get() }}")],
    }
    tab = Signal("a")
    a = app(view, tab=tab)
    assert a.root.find("g")._active_name() == "a"
    tab.set("b")
    a.update()
    assert a.root.find("g")._active_name() == "b"


def test_selected_tab_uses_primary() -> None:
    view = {"name": "root", "widget": "Column", "children": [_group(value="a")]}
    a = app(view)
    tokens = {int(s["flags"][2]) for s in paint(a).view}
    assert PAL.index("primary") in tokens


# -------------------------------------------------------------- DockSplit


def _split(*, value: str | None = None, axis: str | None = None) -> dict:
    style = {}
    if axis is not None:
        style["axis"] = axis
    spec: dict = {
        "name": "s",
        "widget": "DockSplit",
        "style": style,
        "children": [
            {"name": "left", "widget": "DockPanel", "children": [{"widget": "Text", "text": "L"}]},
            {"name": "right", "widget": "DockPanel", "children": [{"widget": "Text", "text": "R"}]},
        ],
    }
    if value is not None:
        spec["value"] = value
    return spec


def test_defaults_to_an_even_split() -> None:
    e = laid_out(_split(), Constraints.tight(Size(1000.0, 500.0)))
    left = e.find("left")
    right = e.find("right")
    assert left.size.width == pytest.approx(right.size.width, abs=1.0)


def test_a_ratio_divides_unevenly() -> None:
    e = laid_out(_split(value="0.25"), Constraints.tight(Size(1000.0, 500.0)))
    left = e.find("left")
    right = e.find("right")
    assert left.size.width < right.size.width
    assert left.size.width == pytest.approx(1000.0 * 0.25 - 2.0, abs=2.0)


def test_defaults_to_horizontal_not_the_shared_field_default() -> None:
    """`axis` defaults to `vertical` for ScrollView; DockSplit must not
    silently inherit that -- side by side is the ordinary reading of
    "split", and this is what a wrong-but-valid layout looks like."""
    e = laid_out(_split(), Constraints.tight(Size(1000.0, 500.0)))
    left = e.find("left")
    assert left.size.height == 500.0
    assert left.size.width < 1000.0


def test_explicit_vertical_axis_stacks_instead() -> None:
    e = laid_out(_split(axis="vertical"), Constraints.tight(Size(1000.0, 500.0)))
    left = e.find("left")
    assert left.size.width == 1000.0
    assert left.size.height < 500.0


def test_a_third_child_is_rejected() -> None:
    with pytest.raises(ValueError):
        laid_out(
            {
                "name": "s",
                "widget": "DockSplit",
                "children": [
                    {"name": "a", "widget": "DockPanel"},
                    {"name": "b", "widget": "DockPanel"},
                    {"name": "c", "widget": "DockPanel"},
                ],
            }
        )


def test_dragging_the_divider_changes_the_ratio() -> None:
    view = {"name": "root", "widget": "Column", "children": [_split(value="0.5")]}
    a = app(view)
    s = a.root.find("s")
    rect = s.absolute_rect()
    divider_x = rect.x + s._divider_main + 1
    a.dispatcher.post(PointerEvent(EventType.POINTER_DOWN, x=divider_x, y=rect.y + 100))
    a.dispatcher.post(PointerEvent(EventType.POINTER_MOVE, x=divider_x + 150, y=rect.y + 100))
    a.dispatcher.drain()
    assert s._ratio() > 0.5


def test_on_change_carries_the_new_ratio() -> None:
    calls = []
    view = {
        "name": "root",
        "widget": "Column",
        "children": [{**_split(value="0.5"), "handlers": {"on_change": "resize"}}],
    }
    a = App(view, theme=Theme(dark=True))
    a._handlers["resize"] = lambda e: calls.append(e.value)
    a.mount()
    a.update()
    s = a.root.find("s")
    rect = s.absolute_rect()
    divider_x = rect.x + s._divider_main + 1
    a.dispatcher.post(PointerEvent(EventType.POINTER_DOWN, x=divider_x, y=rect.y + 100))
    a.dispatcher.post(PointerEvent(EventType.POINTER_MOVE, x=divider_x + 50, y=rect.y + 100))
    a.dispatcher.drain()
    assert calls and float(calls[-1]) != 0.5


def test_arrow_keys_step_the_ratio() -> None:
    view = {"name": "root", "widget": "Column", "children": [_split(value="0.5")]}
    a = app(view)
    s = a.root.find("s")
    a.dispatcher.focus(s)
    a.dispatcher.post(KeyEvent(EventType.KEY_DOWN, key="Right"))
    a.dispatcher.drain()
    assert s._ratio() == pytest.approx(0.52)
    a.dispatcher.post(KeyEvent(EventType.KEY_DOWN, key="Left"))
    a.dispatcher.drain()
    assert s._ratio() == pytest.approx(0.50)


def test_arrow_keys_use_the_splits_own_axis_when_vertical() -> None:
    """`Right`/`Left` only make sense for a horizontal split; a vertical one
    must answer to `Down`/`Up` instead, the same axis-aware mapping its own
    layout already uses."""
    view = {"name": "root", "widget": "Column", "children": [_split(value="0.5", axis="vertical")]}
    a = app(view)
    s = a.root.find("s")
    a.dispatcher.focus(s)
    a.dispatcher.post(KeyEvent(EventType.KEY_DOWN, key="Down"))
    a.dispatcher.drain()
    assert s._ratio() == pytest.approx(0.52)
    a.dispatcher.post(KeyEvent(EventType.KEY_DOWN, key="Up"))
    a.dispatcher.drain()
    assert s._ratio() == pytest.approx(0.50)


def test_a_pane_never_shrinks_below_the_minimum() -> None:
    from pycopper.widgets.dock import DockSplitElement

    e = laid_out(_split(value="0.0"), Constraints.tight(Size(1000.0, 500.0)))
    left = e.find("left")
    assert left.size.width == pytest.approx(DockSplitElement.MIN_PANE)


def test_nesting_a_split_inside_a_split() -> None:
    view = {
        "name": "root",
        "widget": "DockSplit",
        "children": [
            {"name": "left", "widget": "DockPanel", "children": [{"widget": "Text", "text": "L"}]},
            {
                "name": "nested",
                "widget": "DockSplit",
                "style": {"axis": "vertical"},
                "children": [
                    {
                        "name": "top",
                        "widget": "DockPanel",
                        "children": [{"widget": "Text", "text": "T"}],
                    },
                    {
                        "name": "bottom",
                        "widget": "DockPanel",
                        "children": [{"widget": "Text", "text": "B"}],
                    },
                ],
            },
        ],
    }
    e = build_element(parse_view(view).root)
    e.layout(Constraints.tight(Size(1000.0, 500.0)))
    top = e.find("top")
    bottom = e.find("bottom")
    assert top.size.height > 0.0
    assert bottom.size.height > 0.0
    assert top.size.width == bottom.size.width < 1000.0


def test_divider_uses_outline_variant() -> None:
    view = {"name": "root", "widget": "Column", "children": [_split()]}
    a = app(view)
    tokens = {int(s["flags"][2]) for s in paint(a).view}
    assert PAL.index("outline_variant") in tokens


# ------------------------------------------------------------------ focus


@pytest.mark.parametrize("kind", ["DockGroup", "DockSplit"])
def test_are_focusable(kind: str) -> None:
    from pycopper.runtime.events import FOCUSABLE_KINDS

    assert kind in FOCUSABLE_KINDS

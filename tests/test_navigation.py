"""Wave 2: navigation, app bar, tabs, segmented buttons, lists, progress."""

from __future__ import annotations

import pytest

from pycopper import App, Signal, Theme
from pycopper.layout import Constraints, Size
from pycopper.paint import NO_TOKEN, DisplayList, Kind
from pycopper.spec import WidgetKind, parse_view
from pycopper.theme import Palette
from pycopper.widgets import build_element

PAL = Palette(Theme(dark=True))


def laid_out(spec, width=600.0, height=400.0):
    e = build_element(parse_view(spec).root)
    e.layout(Constraints.loose(Size(width, height)))
    return e


def app_with(children, value=None, widget="Tabs", style=None):
    view = {
        "id": "root",
        "widget": "Column",
        "style": {"background": "surface", "width": "expand"},
        "children": [
            {
                "id": "c",
                "widget": widget,
                "style": style or {},
                **({"value": value} if value else {}),
                "children": children,
            }
        ],
    }
    a = App(view, theme=Theme(dark=True))
    a.mount()
    a.update()
    return a


def paint(app) -> DisplayList:
    dl = DisplayList()
    app.paint(dl)
    return dl


def tokens(dl) -> set[int]:
    return {int(s["flags"][2]) for s in dl.view} - {NO_TOKEN}


TABS = [
    {"id": f"t{i}", "widget": "Tab", "text": n}
    for i, n in enumerate(("Overview", "Details", "History"))
]
RAIL = [
    {"id": f"r{i}", "widget": "NavItem", "text": ic, "supporting_text": lb}
    for i, (ic, lb) in enumerate([("home", "Home"), ("search", "Search"), ("settings", "Settings")])
]


# --------------------------------------------------------------- registered


@pytest.mark.parametrize(
    "kind",
    [
        "NavigationRail",
        "NavigationDrawer",
        "NavItem",
        "TopAppBar",
        "Tabs",
        "Tab",
        "SegmentedButton",
        "Segment",
        "ListItem",
        "LinearProgress",
    ],
)
def test_kind_builds(kind: str) -> None:
    assert laid_out({"id": "w", "widget": kind}) is not None


def test_every_kind_is_registered() -> None:
    from pycopper.widgets.base import _REGISTRY, create_element

    create_element(parse_view({"id": "x", "widget": "Tabs"}).root)
    assert set(_REGISTRY) == set(WidgetKind)


# ------------------------------------------------------ M3 dimensions (dp)


def test_rail_is_eighty_wide() -> None:
    """M3 4.5."""
    e = laid_out({"id": "w", "widget": "NavigationRail", "children": RAIL})
    assert e.size.width == 80.0


def test_top_app_bar_is_sixty_four_high() -> None:
    """M3 4.2 small / center-aligned."""
    e = laid_out({"id": "w", "widget": "TopAppBar", "text": "Title"})
    assert e.size.height == 64.0


def test_tabs_are_forty_eight_high() -> None:
    """M3 4.7."""
    e = laid_out({"id": "w", "widget": "Tabs", "children": TABS})
    assert e.size.height == 48.0


def test_segmented_button_is_forty_high() -> None:
    """M3 1.4."""
    e = laid_out(
        {
            "id": "w",
            "widget": "SegmentedButton",
            "children": [{"id": "s", "widget": "Segment", "text": "A"}],
        }
    )
    assert e.size.height == 40.0


def test_linear_progress_is_four_high() -> None:
    """M3 2.2."""
    e = laid_out({"id": "w", "widget": "LinearProgress", "style": {"width": "expand"}})
    assert e.size.height == 4.0


@pytest.mark.parametrize(
    ("spec", "expected"),
    [
        ({"text": "One"}, 56.0),
        ({"text": "One", "supporting_text": "Two"}, 72.0),
        ({"text": "One", "style": {"variant": "three_line"}}, 88.0),
    ],
)
def test_list_item_heights(spec: dict, expected: float) -> None:
    """M3 3.7: 56 / 72 / 88dp."""
    e = laid_out({"id": "w", "widget": "ListItem", **spec})
    assert e.size.height == expected


def test_drawer_width_is_within_the_m3_range() -> None:
    """M3 4.4: 240-360dp."""
    e = laid_out({"id": "w", "widget": "NavigationDrawer", "children": RAIL})
    assert 240.0 <= e.size.width <= 360.0


# ---------------------------------------------------------------- selection


def test_container_marks_only_the_named_child() -> None:
    app = app_with(TABS, value="t1")
    sel = [c.id for c in app.root.find("c").children if c.selected]
    assert sel == ["t1"]


def test_selection_is_bindable() -> None:
    view = {
        "id": "root",
        "widget": "Column",
        "children": [{"id": "c", "widget": "Tabs", "value": "{{ t.get() }}", "children": TABS}],
    }
    a = App(view, theme=Theme(dark=True))
    t = Signal("t0")
    a.expose(t=t)
    a.mount()
    a.update()
    assert a.root.find("t0").selected
    t.set("t2")
    a.update()
    assert a.root.find("t2").selected
    assert not a.root.find("t0").selected


def test_no_value_selects_nothing() -> None:
    app = app_with(TABS)
    assert not any(c.selected for c in app.root.find("c").children)


def test_unknown_id_selects_nothing() -> None:
    app = app_with(TABS, value="nope")
    assert not any(c.selected for c in app.root.find("c").children)


# ---------------------------------------------------------------- rendering


def test_tabs_draw_an_indicator_under_the_active_tab() -> None:
    """M3 4.7: a 3dp active indicator."""
    app = app_with(TABS, value="t1")
    active = app.root.find("t1")
    bars = [
        s
        for s in paint(app).view
        if abs(float(s["rect"][3]) - 3.0) < 0.01 and int(s["flags"][2]) == PAL.index("primary")
    ]
    assert len(bars) == 1
    assert float(bars[0]["rect"][2]) == pytest.approx(active.size.width)


def test_tabs_with_no_selection_draw_no_indicator() -> None:
    app = app_with(TABS)
    bars = [s for s in paint(app).view if abs(float(s["rect"][3]) - 3.0) < 0.01]
    assert bars == []


def test_selected_nav_item_uses_the_active_indicator_colour() -> None:
    """M3 4.5/4.4: secondary_container."""
    app = app_with(RAIL, value="r1", widget="NavigationRail")
    assert PAL.index("secondary_container") in tokens(paint(app))


def test_unselected_rail_has_no_active_indicator() -> None:
    app = app_with(RAIL, widget="NavigationRail")
    assert PAL.index("secondary_container") not in tokens(paint(app))


def test_selected_nav_item_fills_its_icon() -> None:
    """M3 uses the icon FILL axis for selection, not a different icon name."""
    sel = app_with(RAIL, value="r1", widget="NavigationRail")
    unsel = app_with(RAIL, widget="NavigationRail")
    # A filled glyph is a distinct atlas entry, so the two frames differ.
    assert paint(sel).view["uv"].tobytes() != paint(unsel).view["uv"].tobytes()


def test_selected_segment_shows_a_checkmark() -> None:
    """M3 1.4: the active segment includes an 18dp checkmark."""
    segs = [{"id": f"s{i}", "widget": "Segment", "text": n} for i, n in enumerate(("Day", "Week"))]
    sel = app_with(segs, value="s0", widget="SegmentedButton")
    unsel = app_with(segs, widget="SegmentedButton")
    glyphs = lambda dl: sum(1 for s in dl.view if s["flags"][0] == Kind.GLYPH)  # noqa: E731
    assert glyphs(paint(sel)) == glyphs(paint(unsel)) + 1


def test_segmented_button_shrinks_to_content_by_default() -> None:
    """Otherwise the outline runs on past the last segment."""
    segs = [{"id": f"s{i}", "widget": "Segment", "text": "X"} for i in range(3)]
    app = app_with(segs, widget="SegmentedButton")
    group = app.root.find("c")
    assert group.size.width == pytest.approx(sum(c.size.width for c in group.children))


def test_segmented_button_divides_an_explicit_width_equally() -> None:
    segs = [{"id": f"s{i}", "widget": "Segment", "text": "X"} for i in range(3)]
    app = app_with(segs, widget="SegmentedButton", style={"width": "expand"})
    widths = [c.size.width for c in app.root.find("c").children]
    assert max(widths) - min(widths) < 1.0


def test_linear_progress_fills_proportionally() -> None:
    def filled(value: str) -> float:
        e = laid_out(
            {"id": "w", "widget": "LinearProgress", "value": value, "style": {"width": "expand"}},
            width=200,
        )
        return e.progress

    assert filled("0") == 0.0
    assert filled("0.5") == 0.5
    assert filled("1") == 1.0


def test_progress_is_clamped() -> None:
    e = laid_out(
        {"id": "w", "widget": "LinearProgress", "value": "5", "style": {"width": "expand"}}
    )
    assert e.progress == 1.0


def test_list_item_renders_both_lines() -> None:
    one = laid_out({"id": "w", "widget": "ListItem", "text": "Only"})
    two = laid_out({"id": "w", "widget": "ListItem", "text": "Head", "supporting_text": "Support"})
    assert two.size.height > one.size.height


def test_supporting_text_is_bindable() -> None:
    view = {
        "id": "root",
        "widget": "Column",
        "children": [
            {"id": "li", "widget": "ListItem", "text": "H", "supporting_text": "{{ s.get() }}"}
        ],
    }
    a = App(view, theme=Theme(dark=True))
    s = Signal("first")
    a.expose(s=s)
    a.mount()
    assert a.root.find("li").supporting == "first"
    s.set("second")
    assert a.root.find("li").supporting == "second"


def test_centered_app_bar_title_differs_from_left_aligned() -> None:
    def first_glyph_x(variant: str) -> float:
        view = {
            "id": "root",
            "widget": "Column",
            "style": {"width": "expand", "background": "surface"},
            "children": [
                {
                    "id": "b",
                    "widget": "TopAppBar",
                    "text": "Title",
                    "style": {"variant": variant, "width": "expand"},
                }
            ],
        }
        a = App(view, theme=Theme(dark=True))
        a.mount()
        dl = paint(a)
        return min(float(s["rect"][0]) for s in dl.view if s["flags"][0] == Kind.GLYPH)

    assert first_glyph_x("center_aligned") > first_glyph_x("filled")


# ------------------------------------------------------------------- focus


@pytest.mark.parametrize("kind", ["NavItem", "Tab", "Segment", "ListItem"])
def test_items_are_focusable(kind: str) -> None:
    from pycopper.runtime.events import FOCUSABLE_KINDS

    assert kind in FOCUSABLE_KINDS

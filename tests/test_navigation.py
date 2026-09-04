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
        "name": "root",
        "widget": "Column",
        "style": {"background": "surface", "width": "expand"},
        "children": [
            {
                "name": "c",
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
    {"name": f"t{i}", "widget": "Tab", "text": n}
    for i, n in enumerate(("Overview", "Details", "History"))
]
RAIL = [
    {"name": f"r{i}", "widget": "NavItem", "text": ic, "supporting_text": lb}
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
        "TreeView",
        "TreeItem",
        "StatusBar",
    ],
)
def test_kind_builds(kind: str) -> None:
    assert laid_out({"name": "w", "widget": kind}) is not None


def test_every_kind_is_registered() -> None:
    from pycopper.widgets.base import _REGISTRY, create_element

    create_element(parse_view({"name": "x", "widget": "Tabs"}).root)
    assert set(_REGISTRY) == set(WidgetKind)


# ------------------------------------------------------ M3 dimensions (dp)


def test_rail_is_eighty_wide() -> None:
    """M3 4.5."""
    e = laid_out({"name": "w", "widget": "NavigationRail", "children": RAIL})
    assert e.size.width == 80.0


def test_top_app_bar_is_sixty_four_high() -> None:
    """M3 4.2 small / center-aligned."""
    e = laid_out({"name": "w", "widget": "TopAppBar", "text": "Title"})
    assert e.size.height == 64.0


def test_tabs_are_forty_eight_high() -> None:
    """M3 4.7."""
    e = laid_out({"name": "w", "widget": "Tabs", "children": TABS})
    assert e.size.height == 48.0


def test_segmented_button_is_forty_high() -> None:
    """M3 1.4."""
    e = laid_out(
        {
            "name": "w",
            "widget": "SegmentedButton",
            "children": [{"name": "s", "widget": "Segment", "text": "A"}],
        }
    )
    assert e.size.height == 40.0


def test_linear_progress_is_four_high() -> None:
    """M3 2.2."""
    e = laid_out({"name": "w", "widget": "LinearProgress", "style": {"width": "expand"}})
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
    e = laid_out({"name": "w", "widget": "ListItem", **spec})
    assert e.size.height == expected


def test_drawer_width_is_within_the_m3_range() -> None:
    """M3 4.4: 240-360dp."""
    e = laid_out({"name": "w", "widget": "NavigationDrawer", "children": RAIL})
    assert 240.0 <= e.size.width <= 360.0


# ---------------------------------------------------------------- selection


def test_container_marks_only_the_named_child() -> None:
    app = app_with(TABS, value="t1")
    sel = [c.name for c in app.root.find("c").children if c.selected]
    assert sel == ["t1"]


def test_selection_is_bindable() -> None:
    view = {
        "name": "root",
        "widget": "Column",
        "children": [{"name": "c", "widget": "Tabs", "value": "{{ t.get() }}", "children": TABS}],
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
    segs = [
        {"name": f"s{i}", "widget": "Segment", "text": n} for i, n in enumerate(("Day", "Week"))
    ]
    sel = app_with(segs, value="s0", widget="SegmentedButton")
    unsel = app_with(segs, widget="SegmentedButton")
    glyphs = lambda dl: sum(1 for s in dl.view if s["flags"][0] == Kind.GLYPH)  # noqa: E731
    assert glyphs(paint(sel)) == glyphs(paint(unsel)) + 1


def test_segmented_button_shrinks_to_content_by_default() -> None:
    """Otherwise the outline runs on past the last segment."""
    segs = [{"name": f"s{i}", "widget": "Segment", "text": "X"} for i in range(3)]
    app = app_with(segs, widget="SegmentedButton")
    group = app.root.find("c")
    assert group.size.width == pytest.approx(sum(c.size.width for c in group.children))


def test_segmented_button_divides_an_explicit_width_equally() -> None:
    segs = [{"name": f"s{i}", "widget": "Segment", "text": "X"} for i in range(3)]
    app = app_with(segs, widget="SegmentedButton", style={"width": "expand"})
    widths = [c.size.width for c in app.root.find("c").children]
    assert max(widths) - min(widths) < 1.0


def test_linear_progress_fills_proportionally() -> None:
    def filled(value: str) -> float:
        e = laid_out(
            {"name": "w", "widget": "LinearProgress", "value": value, "style": {"width": "expand"}},
            width=200,
        )
        return e.progress

    assert filled("0") == 0.0
    assert filled("0.5") == 0.5
    assert filled("1") == 1.0


def test_progress_is_clamped() -> None:
    e = laid_out(
        {"name": "w", "widget": "LinearProgress", "value": "5", "style": {"width": "expand"}}
    )
    assert e.progress == 1.0


def test_list_item_renders_both_lines() -> None:
    one = laid_out({"name": "w", "widget": "ListItem", "text": "Only"})
    two = laid_out(
        {"name": "w", "widget": "ListItem", "text": "Head", "supporting_text": "Support"}
    )
    assert two.size.height > one.size.height


def test_supporting_text_is_bindable() -> None:
    view = {
        "name": "root",
        "widget": "Column",
        "children": [
            {"name": "li", "widget": "ListItem", "text": "H", "supporting_text": "{{ s.get() }}"}
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
            "name": "root",
            "widget": "Column",
            "style": {"width": "expand", "background": "surface"},
            "children": [
                {
                    "name": "b",
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


# --------------------------------------------------------------- tree view


def _tree_view(*, root_value: str = "true", leaf_value: str = "false") -> dict:
    return {
        "name": "tv",
        "widget": "TreeView",
        "children": [
            {
                "name": "src",
                "widget": "TreeItem",
                "text": "src",
                "value": root_value,
                "children": [
                    {"name": "main", "widget": "TreeItem", "text": "main.py"},
                    {
                        "name": "utils",
                        "widget": "TreeItem",
                        "text": "utils",
                        "value": leaf_value,
                        "children": [
                            {"name": "helpers", "widget": "TreeItem", "text": "helpers.py"}
                        ],
                    },
                ],
            },
            {"name": "readme", "widget": "TreeItem", "text": "README.md"},
        ],
    }


def test_a_leaf_is_a_header_row_only() -> None:
    e = laid_out({"name": "w", "widget": "TreeItem", "text": "leaf"})
    assert e.size.height == 56.0


def test_two_line_tree_item_is_seventy_two_dp() -> None:
    e = laid_out({"name": "w", "widget": "TreeItem", "text": "leaf", "supporting_text": "detail"})
    assert e.size.height == 72.0


def test_a_collapsed_branch_shows_only_its_header() -> None:
    e = laid_out(
        {
            "name": "w",
            "widget": "TreeItem",
            "text": "src",
            "value": "false",
            "children": [{"name": "c", "widget": "TreeItem", "text": "child"}],
        }
    )
    assert e.size.height == 56.0


def test_an_expanded_branch_sums_its_children() -> None:
    e = laid_out(
        {
            "name": "w",
            "widget": "TreeItem",
            "text": "src",
            "value": "true",
            "children": [
                {"name": "c1", "widget": "TreeItem", "text": "one"},
                {"name": "c2", "widget": "TreeItem", "text": "two"},
            ],
        }
    )
    assert e.size.height == 56.0 + 56.0 + 56.0


def test_depth_is_derived_from_ancestry() -> None:
    e = laid_out(_tree_view())
    assert e.find("src").depth == 0
    assert e.find("utils").depth == 1
    assert e.find("helpers").depth == 2
    assert e.find("readme").depth == 0


def test_only_branches_draw_a_chevron() -> None:
    """A leaf gets no `expand_more`/`expand_less` -- nothing to expand.

    Both variants share one label and an empty-text child, so the only
    possible difference in glyph count is the chevron itself -- a body child
    with real text would add its own glyphs regardless of the parent's own
    collapsed state, since the clip only hides them, it does not cull them
    from the display list (see AccordionElement's own chevron test).
    """

    def render(children: list[dict]) -> DisplayList:
        view = {
            "name": "root",
            "widget": "Column",
            "children": [{"name": "w", "widget": "TreeItem", "text": "item", "children": children}],
        }
        app = App(view, theme=Theme(dark=True))
        app.mount()
        dl = DisplayList()
        app.paint(dl)
        return dl

    leaf = render([])
    branch = render([{"name": "c", "widget": "TreeItem", "text": ""}])
    glyphs = lambda dl: sum(1 for s in dl.view if s["flags"][0] == Kind.GLYPH)  # noqa: E731
    assert glyphs(branch) == glyphs(leaf) + 1


def test_tree_selection_is_bindable_at_any_depth() -> None:
    view = {
        "name": "root",
        "widget": "Column",
        "children": [
            {
                "name": "tv",
                "widget": "TreeView",
                "value": "{{ sel.get() }}",
                "children": [_tree_view()["children"][0]],
            }
        ],
    }
    app = App(view, theme=Theme(dark=True))
    sel = Signal("helpers")
    app.expose(sel=sel)
    app.mount()
    app.update()
    assert app.root.find("helpers").selected
    assert not app.root.find("src").selected
    sel.set("src")
    app.update()
    assert app.root.find("src").selected
    assert not app.root.find("helpers").selected


def test_expand_state_is_bindable() -> None:
    """Layout-invalidating `animated()` retargets but does not jump on the
    first `update()` -- same two-step as AccordionElement's own binding test
    and `test_motion.py`'s switch, driven by `app.motion.tick`."""
    view = {
        "name": "root",
        "widget": "Column",
        "children": [
            {
                "name": "src",
                "widget": "TreeItem",
                "text": "src",
                "value": "{{ open.get() }}",
                "children": [{"name": "c", "widget": "TreeItem", "text": "child"}],
            }
        ],
    }
    app = App(view, theme=Theme(dark=True))
    open_ = Signal(False)
    app.expose(open=open_)
    app.mount()
    app.update()
    collapsed = app.root.find("src").size.height

    open_.set(True)
    app.update()
    assert app.root.find("src").size.height == collapsed

    app.motion.tick(1.0)
    app.update()
    assert app.root.find("src").size.height > collapsed


def test_collapsing_an_ancestor_clips_every_descendant() -> None:
    """A tree item's clip intersects its ancestor's rather than replacing it
    -- unlike Accordion/ScrollView (never nested inside their own kind in
    practice), a tree item routinely is. Collapsing `a` must hide `c` even
    though `b`, in between, is itself expanded.
    """
    view = {
        "name": "root",
        "widget": "Column",
        "style": {"background": "surface"},
        "children": [
            {
                "name": "a",
                "widget": "TreeItem",
                "text": "a",
                "value": "false",
                "children": [
                    {
                        "name": "b",
                        "widget": "TreeItem",
                        "text": "b",
                        "value": "true",
                        "children": [{"name": "c", "widget": "TreeItem", "text": "c"}],
                    }
                ],
            }
        ],
    }
    app = App(view, theme=Theme(dark=True))
    app.mount()
    dl = DisplayList()
    app.paint(dl)

    glyphs = [s for s in dl.view if s["flags"][0] == Kind.GLYPH]
    above_fold = [s for s in glyphs if s["rect"][1] < 56.0]
    below_fold = [s for s in glyphs if s["rect"][1] >= 56.0]
    assert above_fold, "expected a's own header glyph to exist"
    assert below_fold, "expected b/c's glyphs to exist further down the display list"

    def visible(clip, rect) -> bool:
        """Would the shader's per-pixel clip test let any of `rect` through.

        Mirrors `ui.wgsl` exactly: `if (clip.z > 0.0 && clip.w > 0.0)` is the
        real gate -- EITHER dimension being zero (not just both) means "no
        clip at all", which is why a naive `Rect.intersect` result cannot be
        used to hide content directly (see `TreeItemElement.HIDDEN_EXTENT`).

        A clip rect can also have real area and still hide its own content
        -- b's header clip is a's own restrictive (0, 0, w, 56) rect, which
        has plenty of area but sits nowhere near where b is actually
        positioned (b starts at y=56, entirely below it). So this checks
        overlap with the glyph's own rect too, not just whether the clip
        rect itself is degenerate.
        """
        cx, cy, cw, ch = (float(v) for v in clip)
        if cw <= 0.0 or ch <= 0.0:  # ui.wgsl's own "unclipped" gate
            return True
        rx, ry, rw, rh = (float(v) for v in rect)
        return rx < cx + cw and rx + rw > cx and ry < cy + ch and ry + rh > cy

    # a is at the root with no ancestor clip, so its own header is visible.
    assert all(visible(s["clip"], s["rect"]) for s in above_fold)
    # b and c sit below a's collapsed 56px boundary -- both are hidden by
    # a's clip regardless of b's own (expanded) state.
    assert not any(visible(s["clip"], s["rect"]) for s in below_fold)


# --------------------------------------------------------------- status bar


def test_status_bar_is_twenty_four_high() -> None:
    e = laid_out({"name": "w", "widget": "StatusBar"})
    assert e.size.height == 24.0


def test_status_bar_uses_surface_container() -> None:
    app = app_with([{"name": "label", "widget": "Text", "text": "Ready"}], widget="StatusBar")
    assert PAL.index("surface_container") in tokens(paint(app))


def test_a_spacer_splits_leading_and_trailing_groups() -> None:
    """A Spacer styled `width: expand` must actually claim the free space --
    StatusBar extends Flex directly, not _FlexElement, so without its own
    flex_of override a Spacer here would be measured as an ordinary
    inflexible child and swallow the room meant to be shared, starving
    whatever comes after it (the same gap TopAppBar has and does not need
    to close, since it never puts a Spacer among its own children)."""
    view = {
        "name": "root",
        "widget": "Column",
        "style": {"background": "surface", "width": "expand"},
        "children": [
            {
                "name": "bar",
                "widget": "StatusBar",
                "children": [
                    {"name": "lead", "widget": "Text", "text": "Ready"},
                    {"name": "gap", "widget": "Spacer", "style": {"width": "expand"}},
                    {"name": "trail", "widget": "Text", "text": "UTF-8"},
                ],
            }
        ],
    }
    a = App(view, theme=Theme(dark=True))
    a.mount()
    a.update()
    bar = a.root.find("bar")
    lead = a.root.find("lead")
    trail = a.root.find("trail")
    assert trail.size.width > 0.0, "the trailing label was starved of space"
    assert trail.offset.x + trail.size.width <= bar.size.width, "it overflowed the bar"
    assert trail.offset.x > lead.offset.x + lead.size.width, "the spacer did nothing"


def test_status_bar_pads_both_edges() -> None:
    """The Flex layout happens against the deflated width, not the full one
    with padding bolted on afterwards -- otherwise the last child's own
    right edge would run PAD_X past the bar's right edge."""
    from pycopper.widgets.navigation import StatusBarElement

    view = {
        "name": "root",
        "widget": "Column",
        "style": {"background": "surface", "width": "expand"},
        "children": [
            {
                "name": "bar",
                "widget": "StatusBar",
                "children": [{"name": "label", "widget": "Text", "text": "Ready"}],
            }
        ],
    }
    a = App(view, theme=Theme(dark=True))
    a.mount()
    a.update()
    label = a.root.find("label")
    assert label.offset.x == StatusBarElement.PAD_X

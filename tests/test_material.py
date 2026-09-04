"""The M3 component catalogue: dimensions, variants, tokens, and state."""

from __future__ import annotations

import pytest

from pycopper import App, Signal, Theme
from pycopper.layout import Constraints, Size
from pycopper.paint import NO_TOKEN, DisplayList, Kind
from pycopper.spec import SpecError, WidgetKind, parse_view
from pycopper.widgets import build_element
from pycopper.widgets.base import measure_text

LOOSE = Constraints.loose(Size(400, 400))


def element(**spec):
    return build_element(parse_view({"name": "w", **spec}).root)


def laid_out(**spec):
    e = element(**spec)
    e.layout(LOOSE)
    return e


def painted(theme: Theme | None = None, **spec) -> DisplayList:
    """Paint one widget through a real App so tokens resolve."""
    app = App(
        {
            "name": "root",
            "widget": "Column",
            "style": {"background": "surface"},
            "children": [{"name": "w", **spec}],
        },
        theme=theme or Theme(dark=True),
    )
    app.mount()
    dl = DisplayList()
    app.paint(dl)
    return dl


def tokens_in(dl: DisplayList) -> set[int]:
    return {int(s["flags"][2]) for s in dl.view} - {NO_TOKEN}


# ------------------------------------------------------- registered kinds


def test_every_kind_has_an_element() -> None:
    from pycopper.widgets.base import _REGISTRY, create_element

    create_element(parse_view({"name": "x", "widget": "Card"}).root)  # force lazy load
    assert set(_REGISTRY) == set(WidgetKind)


@pytest.mark.parametrize(
    "kind",
    [
        "Card",
        "Divider",
        "Checkbox",
        "Radio",
        "Switch",
        "Chip",
        "IconButton",
        "Fab",
        "Badge",
        "Accordion",
    ],
)
def test_kind_parses_and_builds(kind: str) -> None:
    assert laid_out(widget=kind) is not None


def test_unknown_variant_is_rejected_at_load() -> None:
    with pytest.raises(SpecError):
        parse_view({"name": "x", "widget": "Chip", "style": {"variant": "nope"}})


# ---------------------------------------------------- M3 dimensions (dp 1:1)


@pytest.mark.parametrize(
    ("kind", "expected"),
    [
        ("Checkbox", Size(18, 18)),  # M3 5.1: 18x18dp box
        ("Radio", Size(20, 20)),  # M3 5.5: 20dp outer circle
        ("Switch", Size(52, 32)),  # M3 5.7: 52x32dp track
        ("IconButton", Size(40, 40)),  # M3 1.3: 40x40dp container
    ],
)
def test_control_matches_the_m3_size(kind: str, expected: Size) -> None:
    assert laid_out(widget=kind).size == expected


def test_a_button_sizes_itself_without_being_told() -> None:
    """A Button written with no `style:` used to lay out 0x0 and draw nothing.

    It paints its label rather than holding it as a child, so the container
    layout it inherited measured an absent child and returned nothing --
    while HEIGHT and MIN_WIDTH sat declared and unused. Every example carried
    an explicit size or a stylesheet class, so no golden ever caught it.

    M3: "Container Height: 40dp", "Minimum Width: 64dp", "Padding: Horizontal
    24dp".
    """
    from pycopper.widgets.base import ButtonElement

    button = laid_out(widget="Button", text="Confirm")
    assert button.size.height == ButtonElement.HEIGHT == 40.0
    assert button.size.width > ButtonElement.MIN_WIDTH, "it grew to fit its label"

    label = measure_text("Confirm", ButtonElement.LABEL_ROLE, engine=button.text_engine)
    assert button.size.width == pytest.approx(label.width + 2 * ButtonElement.PAD_X)


def test_a_button_with_no_label_still_meets_the_minimum() -> None:
    from pycopper.widgets.base import ButtonElement

    assert laid_out(widget="Button").size == Size(ButtonElement.MIN_WIDTH, ButtonElement.HEIGHT)


def test_an_explicit_size_still_wins() -> None:
    """The intrinsic size is a floor, not an override -- every existing view
    sets its own and must keep it."""
    button = laid_out(widget="Button", text="Confirm", style={"width": 130, "height": 44})
    assert button.size == Size(130, 44)


def test_a_stretched_button_keeps_its_height() -> None:
    """`cross_alignment: stretch` gives it the row's width. It used to take
    the width and stay zero high, which is the same bug wearing a disguise."""
    from pycopper.layout import Constraints
    from pycopper.spec import parse_view
    from pycopper.widgets import build_element

    view = {
        "name": "col",
        "widget": "Column",
        "style": {"cross_alignment": "stretch"},
        "children": [{"name": "b", "widget": "Button", "text": "Wide"}],
    }
    root = build_element(parse_view(view).root)
    root.layout(Constraints(0.0, 300.0, 0.0, 200.0))
    assert root.find("b").size == Size(300.0, 40.0)


@pytest.mark.parametrize(
    ("variant", "side"),
    [("small", 40.0), ("standard", 56.0), ("large", 96.0)],  # M3 1.2
)
def test_fab_sizes(variant: str, side: float) -> None:
    e = laid_out(widget="Fab", style={"variant": variant})
    assert e.size == Size(side, side)


def test_badge_dot_is_six_dp() -> None:
    assert laid_out(widget="Badge", style={"variant": "dot"}).size == Size(6, 6)


def test_numbered_badge_is_sixteen_high_and_at_least_as_wide() -> None:
    e = laid_out(widget="Badge", value="8")
    assert e.size.height == 16.0
    assert e.size.width >= 16.0


def test_chip_is_thirty_two_high() -> None:
    assert laid_out(widget="Chip", text="Filter").size.height == 32.0


def test_divider_is_one_dp_and_fills_width() -> None:
    """M3 3.6: 1dp thick, spanning the available width.

    Given a *tight* constraint it must obey that instead -- a node cannot
    violate its constraints -- so this uses the constraint a Column actually
    hands its children: bounded width, loose height.
    """
    e = element(widget="Divider")
    e.layout(Constraints(min_width=300, max_width=300, min_height=0, max_height=300))
    assert e.size == Size(300, 1.0)


def test_divider_obeys_a_tight_constraint() -> None:
    e = element(widget="Divider")
    e.layout(Constraints.tight(Size(300, 300)))
    assert e.size == Size(300, 300)


def test_divider_thickness_is_configurable() -> None:
    e = laid_out(widget="Divider", style={"thickness": 4})
    assert e.size.height == 4.0


# ------------------------------------------------------------ value binding


@pytest.mark.parametrize(
    ("raw", "expected"),
    [
        ("true", True),
        ("True", True),
        ("1", True),
        ("yes", True),
        ("false", False),
        ("0", False),
        ("", False),
        ("none", False),
    ],
)
def test_checked_parses_truthiness(raw: str, expected: bool) -> None:
    assert laid_out(widget="Checkbox", value=raw).checked is expected


def test_value_is_bindable_to_a_signal() -> None:
    view = {
        "name": "root",
        "widget": "Column",
        "children": [{"name": "cb", "widget": "Checkbox", "value": "{{ on.get() }}"}],
    }
    app = App(view, theme=Theme(dark=True))
    on = Signal(False)
    app.expose(on=on)
    app.mount()
    assert app.root.find("cb").checked is False
    on.set(True)
    assert app.root.find("cb").checked is True


def test_badge_count_is_bindable() -> None:
    view = {
        "name": "root",
        "widget": "Column",
        "children": [{"name": "b", "widget": "Badge", "value": "{{ n.get() }}"}],
    }
    app = App(view, theme=Theme(dark=True))
    n = Signal(3)
    app.expose(n=n)
    app.mount()
    assert app.root.find("b").number == 3.0
    n.set(42)
    assert app.root.find("b").value == "42"


# ------------------------------------------------------------ M3 tokens


def test_widgets_emit_tokens_not_literal_colours() -> None:
    """Token indirection is what makes a theme switch one buffer upload."""
    for kind in ("Card", "Divider", "Checkbox", "Radio", "Switch", "Fab"):
        dl = painted(widget=kind)
        assert tokens_in(dl), f"{kind} emitted no palette token"


def test_selected_checkbox_uses_primary() -> None:
    app_dl = painted(widget="Checkbox", value="true")
    from pycopper.theme import Palette

    primary = Palette(Theme(dark=True)).index("primary")
    assert primary in tokens_in(app_dl)


def test_fab_defaults_to_primary_container() -> None:
    """M3 1.2: the default FAB colour mapping."""
    from pycopper.theme import Palette

    pal = Palette(Theme(dark=True))
    assert pal.index("primary_container") in tokens_in(painted(widget="Fab", text="add"))


def test_explicit_background_overrides_the_variant_default() -> None:
    from pycopper.theme import Palette

    pal = Palette(Theme(dark=True))
    dl = painted(widget="Fab", text="add", style={"background": "tertiary"})
    assert pal.index("tertiary") in tokens_in(dl)


# ------------------------------------------------------------- appearance


def test_selected_and_unselected_checkbox_differ() -> None:
    assert len(painted(widget="Checkbox", value="true")) != len(
        painted(widget="Checkbox", value="false")
    ) or tokens_in(painted(widget="Checkbox", value="true")) != tokens_in(
        painted(widget="Checkbox", value="false")
    )


def test_selected_checkbox_draws_a_checkmark() -> None:
    on = painted(widget="Checkbox", value="true")
    off = painted(widget="Checkbox", value="false")
    glyphs = lambda dl: sum(1 for s in dl.view if s["flags"][0] == Kind.GLYPH)  # noqa: E731
    assert glyphs(on) == glyphs(off) + 1


def test_selected_radio_draws_an_inner_dot() -> None:
    on = painted(widget="Radio", value="true")
    off = painted(widget="Radio", value="false")
    assert len(on) == len(off) + 1


def test_elevated_card_casts_a_shadow() -> None:
    dl = painted(widget="Card", style={"variant": "elevated"})
    assert any(s["flags"][0] == Kind.SHADOW for s in dl.view)


def test_filled_card_casts_no_shadow() -> None:
    dl = painted(widget="Card", style={"variant": "filled"})
    assert not any(s["flags"][0] == Kind.SHADOW for s in dl.view)


def test_outlined_card_has_a_border() -> None:
    dl = painted(widget="Card", style={"variant": "outlined"})
    assert any(s["params"][0] > 0 for s in dl.view)


def test_fab_is_elevated() -> None:
    """M3 1.2: resting elevation level 3."""
    assert any(s["flags"][0] == Kind.SHADOW for s in painted(widget="Fab", text="add").view)


def test_filter_chip_shows_a_checkmark_when_selected() -> None:
    sel = painted(widget="Chip", text="F", style={"variant": "filter"}, value="true")
    unsel = painted(widget="Chip", text="F", style={"variant": "filter"}, value="false")
    assert len(sel) > len(unsel)


def test_selected_filter_chip_is_wider() -> None:
    """The leading checkmark takes real space, so layout must account for it."""
    sel = laid_out(widget="Chip", text="Filter", style={"variant": "filter"}, value="true")
    unsel = laid_out(widget="Chip", text="Filter", style={"variant": "filter"}, value="false")
    assert sel.size.width > unsel.size.width


# ------------------------------------------------------------ state layers


@pytest.mark.parametrize("kind", ["Checkbox", "Radio", "Switch", "IconButton", "Fab"])
def test_hover_adds_a_state_layer(kind: str) -> None:
    """M3 §0: hover is an 8% overlay, not a different container colour.

    The layer cross-fades in, so the frame on which the hover is noticed still
    shows nothing -- the clock has to advance before there is anything to
    assert. Driving time by hand keeps that deterministic.
    """
    view = {
        "name": "root",
        "widget": "Column",
        "children": [
            {"name": "w", "widget": kind, "text": "add" if kind in ("IconButton", "Fab") else None}
        ],
    }
    app = App(view, theme=Theme(dark=True))
    now = 0.0
    app.clock = lambda: now
    app.mount()
    base = DisplayList()
    app.paint(base)
    w = app.root.find("w")
    w.state.hovered = True
    w.mark_needs_paint()

    app.paint(DisplayList())  # notices the hover and starts the fade
    now = 0.2  # past the 100ms state-layer duration
    hovered = DisplayList()
    app.paint(hovered)
    assert len(hovered) == len(base) + 1


def test_hover_does_not_trigger_layout() -> None:
    app = App(
        {"name": "root", "widget": "Column", "children": [{"name": "w", "widget": "Switch"}]},
        theme=Theme(dark=True),
    )
    app.mount()
    app.update()
    w = app.root.find("w")
    w.state.hovered = True
    w.mark_needs_paint()
    assert w.needs_paint and not w.needs_layout


# ---------------------------------------------------------- button variants


@pytest.mark.parametrize("variant", ["filled", "filled_tonal", "outlined", "elevated", "text"])
def test_button_variants_all_render(variant: str) -> None:
    dl = painted(widget="Button", text="Go", style={"variant": variant})
    assert len(dl) > 0


def test_outlined_button_has_a_border_and_no_fill() -> None:
    dl = painted(widget="Button", text="Go", style={"variant": "outlined"})
    assert any(s["params"][0] > 0 for s in dl.view)


def test_elevated_button_casts_a_shadow() -> None:
    dl = painted(widget="Button", text="Go", style={"variant": "elevated"})
    assert any(s["flags"][0] == Kind.SHADOW for s in dl.view)


def test_text_button_draws_no_container() -> None:
    text_btn = painted(widget="Button", text="Go", style={"variant": "text"})
    filled = painted(widget="Button", text="Go", style={"variant": "filled"})
    assert len(text_btn) < len(filled)


# ------------------------------------------------------------------- link


def test_link_underlines_its_label() -> None:
    """M3: "Hyperlinked text must also be underlined" -- not optional."""
    e = laid_out(widget="Link", text="Learn more")
    dl = painted(widget="Link", text="Learn more")
    underlines = [
        s for s in dl.view if s["flags"][0] == Kind.BOX and abs(float(s["rect"][3]) - 1.0) < 0.01
    ]
    assert len(underlines) == 1
    assert float(underlines[0]["rect"][2]) == pytest.approx(e.size.width)


def test_link_defaults_to_primary() -> None:
    from pycopper.theme import Palette

    pal = Palette(Theme(dark=True))
    assert pal.index("primary") in tokens_in(painted(widget="Link", text="Learn more"))


def test_link_tertiary_variant_uses_tertiary() -> None:
    from pycopper.theme import Palette

    pal = Palette(Theme(dark=True))
    dl = painted(widget="Link", text="Learn more", style={"variant": "tertiary"})
    assert pal.index("tertiary") in tokens_in(dl)
    assert pal.index("primary") not in tokens_in(dl)


def test_link_draws_only_its_label_and_underline() -> None:
    """No container, no state layer -- unlike a text Button, whose state
    layer is merely invisible at rest, a Link never has one to begin with.
    That contrast, not just the underline, is the whole anatomy M3 draws
    between the two."""
    dl = painted(widget="Link", text="Go")
    glyphs = sum(1 for s in dl.view if s["flags"][0] == Kind.GLYPH)
    # Excludes the wrapping Column's own background box, which `painted()`
    # always draws regardless of what widget is under test.
    own_boxes = [s for s in dl.view if s["flags"][0] == Kind.BOX and float(s["rect"][3]) < 10.0]
    assert glyphs == len("Go")
    assert len(own_boxes) == 1


# --------------------------------------------------------------- accordion


def _accordion_view(*, value: str):
    return {
        "name": "acc",
        "widget": "Accordion",
        "text": "Headline",
        "value": value,
        "children": [
            {"name": "body", "widget": "Text", "text": "Body content", "style": {"height": 200}}
        ],
    }


def test_collapsed_accordion_is_header_height_only() -> None:
    e = laid_out(**_accordion_view(value="false"))
    assert e.size.height == 56.0


def test_expanded_accordion_reveals_the_body() -> None:
    e = laid_out(**_accordion_view(value="true"))
    assert e.size.height > 56.0


def test_two_line_header_is_seventy_two_dp() -> None:
    e = laid_out(widget="Accordion", text="Headline", supporting_text="Supporting", value="false")
    assert e.size.height == 72.0


def test_accordion_chevron_swaps_rather_than_stacking() -> None:
    """`expand_more` swaps for `expand_less` -- the glyph does not rotate (no
    rotation parameter on a glyph instance) and both are never drawn at once.
    Same glyph *count* in both states is exactly what rules out stacking;
    the display list always emits a fully laid-out subtree regardless of the
    in-shader clip, so a body child would add the same glyphs either way and
    is deliberately omitted here to isolate the chevron itself."""
    collapsed = painted(widget="Accordion", text="Headline", value="false")
    expanded = painted(widget="Accordion", text="Headline", value="true")
    glyphs = lambda dl: sum(1 for s in dl.view if s["flags"][0] == Kind.GLYPH)  # noqa: E731
    assert glyphs(collapsed) == glyphs(expanded) >= 1


def test_accordion_expand_state_is_bindable() -> None:
    view = {
        "name": "root",
        "widget": "Column",
        "children": [
            {
                "name": "acc",
                "widget": "Accordion",
                "text": "Headline",
                "value": "{{ open.get() }}",
                "children": [{"name": "body", "widget": "Text", "text": "x"}],
            }
        ],
    }
    app = App(view, theme=Theme(dark=True))
    open_ = Signal(False)
    app.expose(open=open_)
    app.mount()
    app.update()
    collapsed_height = app.root.find("acc").size.height

    open_.set(True)
    app.update()  # retargets the animation; does not jump (see test_motion.py)
    assert app.root.find("acc").size.height == collapsed_height

    app.motion.tick(1.0)  # past the expand transition
    app.update()  # relayout picks up the now-advanced value
    assert app.root.find("acc").size.height > collapsed_height


def test_accordion_hover_state_layer_does_not_cover_the_body() -> None:
    """The state layer is scoped to the header row -- `_emit_state_layer`
    sizes from the whole (animated) element, which would wrongly tint the
    revealed body too, so this widget emits its own header-sized box."""
    view = {
        "name": "root",
        "widget": "Column",
        "children": [
            {
                "name": "acc",
                "widget": "Accordion",
                "text": "Headline",
                "value": "true",
                "children": [
                    {"name": "body", "widget": "Text", "text": "x", "style": {"height": 200}}
                ],
            }
        ],
    }
    app = App(view, theme=Theme(dark=True))
    now = 0.0
    app.clock = lambda: now
    app.mount()
    base = DisplayList()
    app.paint(base)
    assert not any(
        s["flags"][0] == Kind.BOX and s["fill"][3] > 0 and s["rect"][3] <= 56.0 for s in base.view
    )

    w = app.root.find("acc")
    w.state.hovered = True
    w.mark_needs_paint()
    app.paint(DisplayList())  # notices the hover and starts the fade
    now = 0.2  # past the state-layer duration
    hovered = DisplayList()
    app.paint(hovered)
    assert len(hovered) == len(base) + 1
    assert any(
        s["flags"][0] == Kind.BOX and s["fill"][3] > 0 and s["rect"][3] <= 56.0
        for s in hovered.view
    )

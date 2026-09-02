"""M3 Carousel: the two scroll behaviours the spec distinguishes.

M3 draws an explicit line: uncontained items "don't change size", while hero
and multi-browse items "automatically change size and snap into place". These
tests pin that difference, because it is the whole reason a Carousel is not a
styled horizontal ScrollView.
"""

from __future__ import annotations

import pytest

from pycopper import App, Settings, Theme
from pycopper.layout import Constraints, Offset, Size
from pycopper.paint import NO_TOKEN, DisplayList
from pycopper.runtime.events import EventType, WheelEvent
from pycopper.spec import parse_view
from pycopper.theme import Palette
from pycopper.widgets import build_element
from pycopper.widgets.carousel import CarouselElement, CarouselItemElement

PALETTE = Palette(Theme(dark=True))
WIDTH = 400.0


def carousel(variant: str = "multi_browse", n: int = 6, width: float = WIDTH, **style):
    base = {"variant": variant, "height": 160, "width": width}
    base.update(style)
    spec = {
        "name": "c",
        "widget": "Carousel",
        "style": base,
        "children": [
            {"name": f"i{j}", "widget": "CarouselItem", "text": f"Item {j}"} for j in range(n)
        ],
    }
    element = build_element(parse_view(spec).root)
    element.layout(Constraints.loose(Size(width, 300)))
    return element


def widths(c) -> list[float]:
    return [child.size.width for child in c.children]


# ------------------------------------------------------------ M3 geometry


def test_the_strip_uses_the_m3_padding() -> None:
    """M3: leading/trailing 16dp, top/bottom 8dp, 8dp between elements."""
    c = carousel()
    assert c.children[0].offset.x == CarouselElement.PAD_X == 16.0
    assert c.children[0].offset.y == CarouselElement.PAD_Y == 8.0
    gap = c.children[1].offset.x - (c.children[0].offset.x + c.children[0].size.width)
    assert gap == CarouselElement.GAP == 8.0


def test_items_are_vertically_centred_in_the_strip() -> None:
    """M3: "Alignment | Vertically centered"."""
    c = carousel()
    item = c.children[0]
    assert item.offset.y == CarouselElement.PAD_Y
    assert item.offset.y + item.size.height == c.size.height - CarouselElement.PAD_Y


def test_items_have_a_28dp_corner_radius() -> None:
    """M3: "Item corner radius | 28dp"."""
    assert carousel().children[0].effective_radii == (28.0,) * 4


def test_multi_browse_shows_a_large_a_medium_and_a_small_item() -> None:
    """M3: "shows at least one large, medium, and small carousel item"."""
    large, medium, small, *rest = widths(carousel("multi_browse"))
    assert large > medium > small
    assert small == CarouselElement.SMALL_MAX
    assert medium == CarouselElement.MEDIUM
    assert all(w == small for w in rest)


def test_hero_shows_one_large_and_one_small_item() -> None:
    """M3: "shows at least one large and one small item at a time"."""
    large, small, *rest = widths(carousel("hero"))
    assert large > small == CarouselElement.SMALL_MAX
    assert all(w == small for w in rest)


def test_small_items_stay_inside_the_m3_range() -> None:
    """M3: "Small carousel items have a minimum width of 40dp and a maximum
    width of 56dp"."""
    for variant in ("multi_browse", "hero"):
        for w in widths(carousel(variant))[-2:]:
            assert CarouselElement.SMALL_MIN <= w <= CarouselElement.SMALL_MAX


def test_the_large_item_absorbs_the_leftover_width() -> None:
    """M3 calls the large item's width "Dynamic", so the visible slots should
    together fill the strip exactly."""
    c = carousel("multi_browse")
    large, medium, small = widths(c)[:3]
    total = CarouselElement.PAD_X * 2 + large + medium + small + CarouselElement.GAP * 2
    assert total == pytest.approx(c.size.width)


def test_a_wider_strip_grows_the_large_item_not_the_small_ones() -> None:
    narrow = widths(carousel("multi_browse", width=400))
    wide = widths(carousel("multi_browse", width=600))
    assert wide[0] > narrow[0]
    assert wide[1] == narrow[1] and wide[2] == narrow[2]


def test_the_large_item_never_collapses_below_a_small_one() -> None:
    """A strip too narrow for the pattern must not produce a negative width."""
    c = carousel("multi_browse", width=120)
    assert min(widths(c)) > 0
    assert widths(c)[0] >= CarouselElement.SMALL_MAX


# ------------------------------------------------- resize-and-snap layouts


def settle(c) -> None:
    """Run the snap animation to completion on a bare (un-hosted) element."""
    for _ in range(40):
        c.ticker.tick(0.05)
        c.layout(Constraints.loose(Size(WIDTH, 300)))
        if not c.ticker.active:
            break


def test_advancing_promotes_the_next_item_to_the_large_slot() -> None:
    """M3: items "automatically change size and snap into place".

    Asserted once the snap has landed -- the travel between states is covered
    by the animation tests further down.
    """
    c = carousel("multi_browse")
    first_large = c.children[0].size.width
    assert c.set_index(1) is True
    c.layout(Constraints.loose(Size(WIDTH, 300)))
    settle(c)

    assert c.children[0].size.width == CarouselElement.SMALL_MAX
    assert c.children[1].size.width == first_large
    assert c.children[1].offset.x == CarouselElement.PAD_X, "not snapped to the keyline"
    assert c.children[0].offset.x < 0, "the passed item did not move off the leading edge"


def test_the_index_is_clamped_to_the_items_present() -> None:
    c = carousel("hero", n=3)
    assert c.set_index(99) is True
    assert c.index == 2
    assert c.set_index(99) is False
    assert c.set_index(-5) is True
    assert c.index == 0


def test_a_snapping_carousel_relayouts_because_widths_depend_on_position() -> None:
    """The deliberate exception to the scrolling rule.

    A `ScrollView` must never relayout to scroll; a snapping carousel must,
    because which item is on the keyline is what decides every width. It stays
    cheap because a carousel holds a handful of items.
    """
    c = carousel("multi_browse")
    c.set_index(1)
    assert c.needs_layout


def test_an_uncontained_carousel_does_not_relayout_to_scroll() -> None:
    """Its widths do not depend on the offset, so it translates at paint time
    like any other viewport."""
    c = carousel("uncontained")
    assert c.set_scroll(60.0) is True
    assert c.needs_paint
    assert not c.needs_layout
    assert c.child_origin(Offset(0.0, 0.0)) == Offset(-60.0, 0.0)


# --------------------------------------------------------------- uncontained


def test_uncontained_items_keep_their_own_width() -> None:
    """M3: "Since items don't change size, this layout can be customized"."""
    spec = {
        "name": "c",
        "widget": "Carousel",
        "style": {"variant": "uncontained", "height": 160, "width": WIDTH},
        "children": [
            {"name": "a", "widget": "CarouselItem", "style": {"width": 150}},
            {"name": "b", "widget": "CarouselItem"},
            {"name": "d", "widget": "CarouselItem", "style": {"width": 260}},
        ],
    }
    c = build_element(parse_view(spec).root)
    c.layout(Constraints.loose(Size(WIDTH, 300)))
    assert widths(c) == [150.0, CarouselElement.UNCONTAINED_WIDTH, 260.0]


def test_uncontained_scroll_is_clamped_to_the_strip() -> None:
    c = carousel("uncontained", n=4)
    c.set_scroll(10_000)
    assert c.scroll_x == c._max_scroll > 0
    c.set_scroll(-50)
    assert c.scroll_x == 0.0


def test_an_uncontained_strip_that_fits_does_not_scroll() -> None:
    c = carousel("uncontained", n=1, width=600)
    assert c._max_scroll == 0.0
    assert c.set_scroll(100) is False


# -------------------------------------------------------------------- wheel


def hosted(variant: str, n: int = 6) -> App:
    app = App(
        {
            "root": {
                "name": "root",
                "widget": "Column",
                "style": {"background": "surface"},
                "children": [
                    {
                        "name": "c",
                        "widget": "Carousel",
                        "style": {"variant": variant, "height": 160, "width": "expand"},
                        "children": [
                            {"name": f"i{j}", "widget": "CarouselItem", "text": f"Item {j}"}
                            for j in range(n)
                        ],
                    }
                ],
            }
        },
        theme=Theme(dark=True),
        settings=Settings(width=int(WIDTH), height=300),
    )
    app.mount()
    app.update()
    return app


def wheel(app: App, **kw) -> None:
    app.dispatcher.post(WheelEvent(EventType.WHEEL, x=100, y=50, **kw))
    app.dispatcher.drain()
    app.update()


def test_a_vertical_wheel_drives_the_horizontal_strip() -> None:
    """Most desktop mice have no horizontal wheel, so requiring one would
    leave the carousel unusable for most people."""
    app = hosted("multi_browse")
    wheel(app, dy=100.0)
    assert app.root.find("c").index == 1


def test_a_horizontal_wheel_drives_it_too() -> None:
    app = hosted("multi_browse")
    wheel(app, dx=100.0)
    assert app.root.find("c").index == 1


def test_the_wheel_steps_one_item_regardless_of_magnitude() -> None:
    """Snapping means an item at a time, not a proportional distance."""
    app = hosted("multi_browse")
    wheel(app, dy=1000.0)
    assert app.root.find("c").index == 1


def test_the_wheel_reverses() -> None:
    app = hosted("hero")
    wheel(app, dy=100.0)
    wheel(app, dy=100.0)
    assert app.root.find("c").index == 2
    wheel(app, dy=-100.0)
    assert app.root.find("c").index == 1


def test_the_wheel_chains_outwards_at_the_last_item() -> None:
    """Same rule as ScrollView: consume the wheel only if something moved."""
    app = hosted("hero", n=2)
    c = app.root.find("c")
    c.set_index(1)
    app.update()
    event = WheelEvent(EventType.WHEEL, x=100, y=50, dy=100.0)
    c.on_wheel(event)
    assert not event.stopped


# -------------------------------------------------------------------- paint


def painted(variant: str) -> DisplayList:
    app = hosted(variant)
    dl = DisplayList()
    app.paint(dl)
    return dl


def test_items_paint_a_palette_token() -> None:
    dl = painted("multi_browse")
    tokens = {int(s["flags"][2]) for s in dl.view if int(s["flags"][2]) != NO_TOKEN}
    assert PALETTE.index("surface_container_high") in tokens


def test_items_are_clipped_to_the_strip() -> None:
    """An item scrolled past the leading edge must not spill out of it."""
    app = hosted("multi_browse")
    app.root.find("c").set_index(2)
    app.update()
    dl = DisplayList()
    app.paint(dl)
    assert any(s["clip"][2] > 0.0 for s in dl.view), "nothing was clipped"


def paint_item(width: float, text: str = "A very long label") -> DisplayList:
    from pycopper.text import TextEngine
    from pycopper.tree.element import PaintContext

    item = build_element(parse_view({"name": "i", "widget": "CarouselItem", "text": text}).root)
    item.layout(Constraints(min_width=width, max_width=width, min_height=144.0, max_height=144.0))
    dl = DisplayList()
    ctx = PaintContext(display_list=dl, palette=PALETTE, text=TextEngine(), pixel_ratio=1.0)
    item.set_text_engine(ctx.text)
    item.paint(ctx, Offset(0.0, 0.0))
    return dl


def test_a_label_too_wide_for_a_shrunken_item_is_dropped() -> None:
    """A clipped half-word reads as a rendering bug; no label reads as design.

    A small item is 56dp wide, which cannot hold a label, so it must draw the
    surface alone -- one instance, no glyphs.
    """
    narrow = paint_item(CarouselElement.SMALL_MAX)
    wide = paint_item(240.0)
    assert len(narrow) == 1, "the small item drew more than its surface"
    assert len(wide) > len(narrow), "the large item drew no label"


def test_carousel_item_takes_the_box_the_strip_assigns() -> None:
    """An item does not choose its own width in a resizing layout -- that is
    the point of the component."""
    item = build_element(
        parse_view({"name": "i", "widget": "CarouselItem", "style": {"width": 999}}).root
    )
    item.layout(Constraints(min_width=80, max_width=80, min_height=100, max_height=100))
    assert item.size == Size(80.0, 100.0)
    assert isinstance(item, CarouselItemElement)


# ---------------------------------------------------------- snap animation


def animated_carousel(n: int = 6, variant: str = "multi_browse"):
    """A hosted carousel with a hand-driven clock."""
    app = hosted(variant, n=n)
    clock = {"t": 0.0}
    app.clock = lambda: clock["t"]
    app.paint(DisplayList())
    return app, app.root.find("c"), clock


def test_the_strip_travels_instead_of_jumping() -> None:
    """M3: items "automatically change size and snap into place". The snap now
    has travel -- previously the layout was correct only at rest."""
    app, c, clock = animated_carousel()
    assert c.position == 0.0

    c.set_index(1)
    app.paint(DisplayList())
    assert c.position == 0.0, "it teleported to the new item"

    clock["t"] = 0.05
    app.paint(DisplayList())
    assert 0.0 < c.position < 1.0, "the strip did not move"

    for _ in range(12):
        clock["t"] += 0.05
        app.paint(DisplayList())
    assert c.position == pytest.approx(1.0)
    assert not app.motion.active


def test_items_resize_continuously_while_travelling() -> None:
    """The defining behaviour: an item promoted from medium to large grows as
    it moves, rather than switching size on arrival."""
    app, c, clock = animated_carousel()
    large, medium = widths(c)[0], widths(c)[1]

    c.set_index(1)
    app.paint(DisplayList())
    clock["t"] = 0.06
    app.paint(DisplayList())

    shrinking, growing = widths(c)[0], widths(c)[1]
    assert medium < growing < large, "the second item did not grow on its way in"
    assert CarouselElement.SMALL_MAX < shrinking < large, "the first did not shrink"


def test_it_lands_exactly_on_the_keyline() -> None:
    """Interpolating the shift must not leave the strip a fraction off."""
    app, c, clock = animated_carousel()
    c.set_index(2)
    for _ in range(16):
        clock["t"] += 0.05
        app.paint(DisplayList())
    assert c.position == pytest.approx(2.0)
    assert c.children[2].offset.x == pytest.approx(CarouselElement.PAD_X)
    assert c.children[2].size.width == pytest.approx(widths(c)[2])


def test_the_travel_invalidates_layout_not_just_paint() -> None:
    """Item widths depend on position here, so paint alone would draw the old
    geometry. This is the one place `invalidates="layout"` is used."""
    app, c, _clock = animated_carousel()
    c.set_index(1)
    app.paint(DisplayList())
    c._needs_paint = False
    app.motion.tick(0.05)
    assert c.needs_layout


def test_a_travelling_carousel_costs_one_layout_per_frame() -> None:
    """Relaying out every frame is the deliberate exception to the scrolling
    rule; doing it *more* than once a frame would not be."""
    app, c, clock = animated_carousel(n=20)
    calls: list[int] = []
    original = type(c).perform_layout
    type(c).perform_layout = lambda self, k: (calls.append(1), original(self, k))[1]
    try:
        c.set_index(1)
        frames = 0
        while app.motion.active or frames == 0:
            clock["t"] += 1 / 60
            app.paint(DisplayList())
            frames += 1
            if frames > 60:
                break
        assert len(calls) == frames, "the carousel laid out more than once per frame"
        assert frames < 30, "a 300ms snap took too many frames to settle"
    finally:
        type(c).perform_layout = original


def test_reduce_motion_snaps_without_travel() -> None:
    app = App(
        {
            "root": {
                "name": "root",
                "widget": "Column",
                "style": {"background": "surface"},
                "children": [
                    {
                        "name": "c",
                        "widget": "Carousel",
                        "style": {"variant": "hero", "height": 120, "width": "expand"},
                        "children": [{"name": f"i{j}", "widget": "CarouselItem"} for j in range(4)],
                    }
                ],
            }
        },
        theme=Theme(dark=True),
        settings=Settings(width=int(WIDTH), height=300, reduce_motion=True),
    )
    app.mount()
    app.paint(DisplayList())
    c = app.root.find("c")
    c.set_index(2)
    app.paint(DisplayList())
    assert c.position == 2.0
    assert not app.motion.active


def test_an_uncontained_carousel_still_does_not_relayout_to_scroll() -> None:
    """Only the resizing layouts pay for animation; uncontained keeps the
    cheap paint-time translation."""
    _app, c, _clock = animated_carousel(variant="uncontained")
    assert not c.snaps
    c.set_scroll(60.0)
    assert c.needs_paint
    assert not c.needs_layout

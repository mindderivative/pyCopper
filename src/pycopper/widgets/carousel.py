"""M3 Carousel: a horizontal strip of items that resize as they scroll.

Two behaviours, and M3 draws the line between them explicitly:

* **uncontained** items "don't change size", and both free and snap scrolling
  suit it -- so this scrolls by pixels, like any horizontal viewport.
* **hero** and **multi_browse** items "automatically change size and snap into
  place to maintain the same layout" -- so these scroll by *item*, and an
  item's width comes from its position in the strip rather than its content.

That second mode is what makes a carousel a carousel rather than a horizontal
list, and it is why this is a widget of its own instead of a styled
`ScrollView`.

**What is missing is the transition, not the layout.** M3 resizes items
continuously as they travel and snaps them home; with no motion system the
snap is instantaneous and the resize happens in one step. At rest the geometry
is exactly what M3 specifies -- it is the movement between rest states that is
absent. The parallax on item visuals is likewise unimplemented.

Dimensions are quoted from `COMPONENT_CAROUSEL.md`. The medium item width is
the one exception and is marked where it is defined.
"""

from __future__ import annotations

from typing import Any, Final

from ..layout import Axis, Constraints, Flex, Offset, Size
from ..runtime.events import WheelEvent
from ..spec import WidgetSpec
from ..tree.element import PaintContext
from .base import _StyledMixin, measure_text, paint_text, paired_content_token
from .material import _box

__all__ = ["CarouselElement", "CarouselItemElement"]

#: "Item corner radius | 28dp"
ITEM_RADIUS: Final = 28.0


class CarouselElement(_StyledMixin, Flex):
    """The strip. Children are `CarouselItem`s.

    | Attribute | Value |
    |---|---|
    | Leading/trailing padding | 16dp |
    | Top/bottom padding | 8dp |
    | Padding between elements | 8dp |
    | Small item width | 40-56dp |
    | Alignment | vertically centred |
    """

    PAD_X: Final = 16.0
    PAD_Y: Final = 8.0
    GAP: Final = 8.0
    SMALL_MIN: Final = 40.0
    SMALL_MAX: Final = 56.0
    #: **Not sourced.** M3 calls the medium item "dynamic" and gives no figure,
    #: so this is pyCopper's choice: twice the largest small item, which keeps
    #: the three sizes visibly distinct.
    MEDIUM: Final = 112.0
    #: Also not sourced -- the spec's size tables are images. Set `height:`.
    HEIGHT: Final = 160.0
    #: Width of an uncontained item that does not set its own.
    UNCONTAINED_WIDTH: Final = 200.0

    #: Item widths by position, for the layouts whose items change size.
    PATTERNS: Final = {
        "hero": ("large", "small"),
        "multi_browse": ("large", "medium", "small"),
    }

    axis = Axis.HORIZONTAL

    def __init__(self, spec: WidgetSpec) -> None:
        Flex.__init__(self, axis=Axis.HORIZONTAL, spacing=self.GAP)
        self.init_element(spec)
        #: Total strip width including padding; set during layout.
        self._extent = 0.0

    def configure(self) -> None:
        self._spacing = self.GAP

    # ----------------------------------------------------------------- mode

    @property
    def layout_name(self) -> str:
        variant = self.style.variant
        return variant if variant in ("uncontained", "hero", "multi_browse") else "uncontained"

    @property
    def snaps(self) -> bool:
        """M3 recommends snap-scrolling for the layouts whose items resize."""
        return self.layout_name in self.PATTERNS

    # ---------------------------------------------------------------- index

    @property
    def index(self) -> int:
        """First item at the leading keyline. Only meaningful when snapping."""
        return int(self.state.data.get("carousel_index", 0))

    def set_index(self, value: int) -> bool:
        """Move to an item, clamped. Returns whether it moved.

        Unlike a scroll offset this marks **layout**, because in a snapping
        carousel an item's width genuinely depends on its position -- that is
        the behaviour M3 is describing. It stays cheap because a carousel holds
        a handful of items, not the thousand rows a `ScrollView` must assume.
        """
        clamped = max(0, min(value, max(0, len(self.children) - 1)))
        if clamped == self.index:
            return False
        self.state.data["carousel_index"] = clamped
        self.mark_needs_layout()
        return True

    @property
    def scroll_x(self) -> float:
        return self.state.scroll.x

    def set_scroll(self, value: float) -> bool:
        """Free pixel scrolling, for the uncontained layout."""
        clamped = max(0.0, min(value, self._max_scroll))
        if clamped == self.state.scroll.x:
            return False
        self.state.scroll = Offset(clamped, self.state.scroll.y)
        self.mark_needs_paint()
        return True

    # --------------------------------------------------------------- events

    def on_wheel(self, event: WheelEvent) -> None:
        """A horizontal strip takes either wheel axis.

        Most desktop mice have only a vertical wheel, so requiring a horizontal
        one would leave the carousel unusable for most users.
        """
        delta = event.dx if event.dx else event.dy
        if delta == 0.0:
            return
        step = 1 if delta > 0 else -1
        moved = (
            self.set_index(self.index + step)
            if self.snaps
            else self.set_scroll(self.scroll_x + delta * 0.5)
        )
        if moved:
            event.stop_propagation()

    # --------------------------------------------------------------- layout

    def _item_width(self, position: int, large: float) -> float:
        """Width for the item `position` places after the leading keyline."""
        pattern = self.PATTERNS[self.layout_name]
        if position < 0:
            return self.SMALL_MAX  # already scrolled past the leading edge
        slot = pattern[min(position, len(pattern) - 1)]
        if slot == "large":
            return large
        return self.MEDIUM if slot == "medium" else self.SMALL_MAX

    def _uncontained_width(self, child: Any) -> float:
        style = getattr(child, "style", None)
        if style is not None and style.width.kind == "fixed":
            return float(style.width.value)
        return self.UNCONTAINED_WIDTH

    def _large_width(self, available: float) -> float:
        """Whatever the fixed slots leave over, which is M3's "dynamic"."""
        pattern = self.PATTERNS[self.layout_name]
        fixed = sum(
            self.MEDIUM if slot == "medium" else self.SMALL_MAX
            for slot in pattern
            if slot != "large"
        )
        gaps = self.GAP * (len(pattern) - 1)
        return max(self.SMALL_MAX, available - fixed - gaps)

    def perform_layout(self, constraints: Constraints) -> Size:
        outer = self.sized(constraints, self.style)
        width = outer.max_width if outer.has_bounded_width else 0.0
        height = (
            float(self.style.height.value)
            if self.style.height.kind == "fixed"
            else (outer.max_height if outer.has_bounded_height else self.HEIGHT)
        )
        item_height = max(0.0, height - self.PAD_Y * 2)
        available = max(0.0, width - self.PAD_X * 2)

        children = list(self.children)
        if not children:
            self._extent = 0.0
            return outer.constrain(Size(width, height))

        # One width per item, computed before any child is laid out, so each
        # child is measured exactly once.
        if self.snaps:
            large = self._large_width(available)
            index = min(self.index, len(children) - 1)
            widths = [self._item_width(j - index, large) for j in range(len(children))]
        else:
            # Uncontained items "don't change size": each keeps its own width
            # and the strip scrolls past them.
            widths = [self._uncontained_width(child) for child in children]

        # Cumulative positions, then shift so the current item sits on the
        # leading keyline (snapping) or by the scroll offset (uncontained).
        positions: list[float] = []
        cursor = self.PAD_X
        for w in widths:
            positions.append(cursor)
            cursor += w + self.GAP
        self._extent = cursor - self.GAP + self.PAD_X

        # A snapping layout shifts during layout, because which item sits on
        # the leading keyline is what decides every item's width -- the two
        # cannot be separated. An uncontained layout shifts at paint time
        # instead, via `child_origin`, exactly as `ScrollView` does: its widths
        # do not depend on the offset, so relaying out to scroll would be waste.
        if self.snaps:
            index = min(self.index, len(children) - 1)
            shift = positions[index] - self.PAD_X
        else:
            shift = 0.0
            # Re-clamp: items may have been removed since the last frame.
            self.state.scroll = Offset(
                min(self.scroll_x, self._max_scroll_for(width)), self.state.scroll.y
            )

        for child, w, x in zip(children, widths, positions, strict=True):
            child.layout(
                Constraints(
                    min_width=w, max_width=w, min_height=item_height, max_height=item_height
                )
            )
            child.offset = Offset(x - shift, self.PAD_Y)  # vertically centred by the padding

        return outer.constrain(Size(width, height))

    def _max_scroll_for(self, width: float) -> float:
        return max(0.0, self._extent - width)

    @property
    def _max_scroll(self) -> float:
        return self._max_scroll_for(self.size.width)

    # ---------------------------------------------------------------- paint

    def child_origin(self, absolute: Offset) -> Offset:
        """Paint-time translation for the uncontained layout.

        A snapping layout has already positioned its items during layout, so
        there is nothing left to translate.
        """
        if self.snaps:
            return absolute
        return Offset(absolute.x - self.scroll_x, absolute.y)

    def child_paint_context(self, ctx: PaintContext, absolute: Any) -> PaintContext:
        """Clip items to the strip, so one scrolled off does not spill out."""
        dpr = ctx.pixel_ratio
        return PaintContext(
            display_list=ctx.display_list,
            palette=ctx.palette,
            text=ctx.text,
            pixel_ratio=dpr,
            clip=(
                absolute.x * dpr,
                absolute.y * dpr,
                self.size.width * dpr,
                self.size.height * dpr,
            ),
            clip_radii=tuple(r * dpr for r in self.effective_radii),  # type: ignore[arg-type]
        )


class CarouselItemElement(_StyledMixin, Flex):
    """One item: a 28dp-rounded surface with an optional label.

    Sized entirely by its parent -- an item does not choose its own width in a
    resizing layout, which is the point of the component. `text:` is drawn over
    the bottom of the surface, where M3 puts an item's label.
    """

    RADIUS: Final = ITEM_RADIUS
    LABEL: Final = 14.0
    LABEL_PAD: Final = 12.0

    axis = Axis.VERTICAL

    def __init__(self, spec: WidgetSpec) -> None:
        Flex.__init__(self, axis=Axis.VERTICAL, spacing=spec.style.spacing)
        self.init_element(spec)

    def configure(self) -> None:
        self._spacing = self.style.spacing

    @property
    def effective_radii(self) -> tuple[float, float, float, float]:
        radii = self.style.corner_radius
        return radii if any(radii) else (self.RADIUS,) * 4

    def perform_layout(self, constraints: Constraints) -> Size:
        # Takes exactly the box the carousel assigned it.
        size = Size(
            constraints.max_width if constraints.has_bounded_width else 0.0,
            constraints.max_height if constraints.has_bounded_height else 0.0,
        )
        for child in self.children:
            child.layout(Constraints.loose(size))
            child.offset = Offset(0.0, 0.0)
        return constraints.constrain(size)

    def paint_self(self, ctx: PaintContext, absolute: Any) -> None:
        style = self.style
        radii = self.effective_radii
        _box(
            ctx,
            absolute.x,
            absolute.y,
            self.size.width,
            self.size.height,
            token=ctx.palette.index(style.background or "surface_container_high"),
            radius=radii[0],
        )
        label = self._text.strip()
        if not label or self.size.width < self.LABEL_PAD * 2:
            return
        metrics = measure_text(label, self.LABEL, engine=self.text_engine)
        if metrics.width > self.size.width - self.LABEL_PAD * 2:
            return  # a clipped label is worse than none in a shrinking item
        paint_text(
            ctx,
            absolute.x + self.LABEL_PAD,
            absolute.y + self.size.height - metrics.height - self.LABEL_PAD,
            label,
            self.LABEL,
            paired_content_token(ctx, style, "on_surface"),
        )

    def child_paint_context(self, ctx: PaintContext, absolute: Any) -> PaintContext:
        """Clip content to the rounded item -- M3 items hold images."""
        dpr = ctx.pixel_ratio
        return PaintContext(
            display_list=ctx.display_list,
            palette=ctx.palette,
            text=ctx.text,
            pixel_ratio=dpr,
            clip=(
                absolute.x * dpr,
                absolute.y * dpr,
                self.size.width * dpr,
                self.size.height * dpr,
            ),
            clip_radii=tuple(r * dpr for r in self.effective_radii),  # type: ignore[arg-type]
        )

"""Scrolling: a clipped viewport over content larger than itself.

The whole design rests on one decision: **scrolling is a paint-time
translation, not a relayout.** The content is measured once against unbounded
space on the scroll axis and keeps the offsets layout gave it; changing the
scroll position only changes the origin its subtree is painted from
(`ElementMixin.child_origin`). A wheel notch therefore costs one paint of the
viewport, not a layout pass over every row -- which matters here more than in
most toolkits, because Python is this framework's bottleneck and a relayout per
wheel event would be visible (ARCHITECTURE.md 12).

M3 has no scrollbar spec -- the catalogue mentions only that a scrolling menu
"shows a persistent scrollbar" -- so the indicator's dimensions here are
pyCopper's own, and marked as such rather than presented as Material.
"""

from __future__ import annotations

from typing import Any, Final

from ..layout import INF, Axis, Constraints, Offset, Padding, Size
from ..runtime.events import WheelEvent
from ..spec import WidgetSpec
from ..tree.element import PaintContext
from .base import _StyledMixin
from .material import _box

__all__ = ["ScrollViewElement"]


class ScrollViewElement(_StyledMixin, Padding):
    """A viewport that clips one oversized child and scrolls it.

    Wraps a single child, normally a Column::

        - name: list
          widget: ScrollView
          style: {height: 300, width: expand}
          children:
            - widget: Column
              children: [ ... many rows ... ]

    The viewport **must be bounded on its scroll axis**. A ScrollView that
    shrink-wrapped to its content would be exactly as tall as the thing it is
    supposed to be scrolling, so this raises rather than silently doing
    nothing -- the same choice `Flex` makes for flexible children in unbounded
    space.
    """

    #: Not from M3, which specifies no scrollbar. Sized to read as an indicator
    #: rather than a drag target, since there is no drag handling yet.
    BAR_THICKNESS: Final = 4.0
    BAR_MARGIN: Final = 2.0
    BAR_MIN_LENGTH: Final = 32.0
    BAR_RADIUS: Final = 2.0
    BAR_OPACITY: Final = 0.55

    #: One wheel notch is ~100 units from the backend; scrolling a full 100px
    #: per notch is jarring on a short list, so it is scaled to a line-ish step.
    WHEEL_SCALE: Final = 0.5

    def __init__(self, spec: WidgetSpec) -> None:
        Padding.__init__(self, None, spec.style.padding)
        self.init_element(spec)
        self._content = Size(0.0, 0.0)

    def configure(self) -> None:
        self._padding = self.style.padding

    # ----------------------------------------------------------------- axis

    @property
    def axis(self) -> Axis:
        return Axis.HORIZONTAL if self.style.axis == "horizontal" else Axis.VERTICAL

    @property
    def horizontal(self) -> bool:
        return self.axis is Axis.HORIZONTAL

    def _main(self, size: Size) -> float:
        return size.width if self.horizontal else size.height

    # --------------------------------------------------------------- extent

    @property
    def content_size(self) -> Size:
        """Size of the scrolled content, measured against unbounded space."""
        return self._content

    @property
    def max_scroll(self) -> float:
        """How far the content can travel. 0 when it already fits."""
        pad = self._padding
        inset = pad.horizontal if self.horizontal else pad.vertical
        return max(0.0, self._main(self._content) + inset - self._main(self.size))

    @property
    def scroll_offset(self) -> float:
        return self.state.scroll.x if self.horizontal else self.state.scroll.y

    @property
    def scrollable(self) -> bool:
        return self.max_scroll > 0.0

    def set_scroll(self, value: float) -> bool:
        """Move to an absolute offset, clamped. Returns whether it moved.

        Marks paint only. Nothing about the content's geometry has changed, so
        marking layout here would throw away the entire point of the design.
        """
        clamped = max(0.0, min(value, self.max_scroll))
        if clamped == self.scroll_offset:
            return False
        self.state.scroll = (
            Offset(clamped, self.state.scroll.y)
            if self.horizontal
            else Offset(self.state.scroll.x, clamped)
        )
        self.mark_needs_paint()
        return True

    def scroll_by(self, delta: float) -> bool:
        return self.set_scroll(self.scroll_offset + delta)

    # ---------------------------------------------------------------- events

    def on_wheel(self, event: WheelEvent) -> None:
        """Consume the wheel, but only as far as this viewport can actually go.

        Propagation stops **only if the content moved**. At the end of a list
        the wheel keeps travelling to an enclosing scroll view, which is what
        every desktop toolkit does -- swallowing it unconditionally would trap
        the pointer in a fully-scrolled inner pane.
        """
        delta = event.dx if self.horizontal else event.dy
        if self.scroll_by(delta * self.WHEEL_SCALE):
            event.stop_propagation()

    # ---------------------------------------------------------------- layout

    def perform_layout(self, constraints: Constraints) -> Size:
        outer = self.sized(constraints, self.style)
        bounded = outer.has_bounded_width if self.horizontal else outer.has_bounded_height
        if not bounded:
            axis = "width" if self.horizontal else "height"
            raise ValueError(
                f"ScrollView needs a bounded {axis}; it was given unbounded space, "
                f"so it would size to its content and never scroll. Set style.{axis} "
                f"or place it inside something that constrains it."
            )

        viewport = Size(
            outer.max_width if outer.has_bounded_width else 0.0,
            outer.max_height if outer.has_bounded_height else 0.0,
        )
        pad = self._padding
        child = self.child
        if child is None:
            self._content = Size(0.0, 0.0)
        else:
            # Unbounded along the scroll axis so the content reports its true
            # extent; bounded across it so text wraps to the viewport.
            inner = Constraints(
                min_width=0.0,
                max_width=INF if self.horizontal else max(0.0, viewport.width - pad.horizontal),
                min_height=0.0,
                max_height=max(0.0, viewport.height - pad.vertical) if self.horizontal else INF,
            )
            child.layout(inner)
            child.offset = pad.top_left
            self._content = child.size

        size = outer.constrain(viewport)
        # Content may have shrunk since the last frame -- a hot reload that
        # removed rows can leave the offset past the new end.
        self.state.scroll = self._clamped_scroll(size)
        return size

    def _clamped_scroll(self, size: Size) -> Offset:
        pad = self._padding
        inset = pad.horizontal if self.horizontal else pad.vertical
        limit = max(0.0, self._main(self._content) + inset - self._main(size))
        current = self.state.scroll
        value = current.x if self.horizontal else current.y
        clamped = max(0.0, min(value, limit))
        return Offset(clamped, current.y) if self.horizontal else Offset(current.x, clamped)

    # ----------------------------------------------------------------- paint

    def child_origin(self, absolute: Offset) -> Offset:
        """Translate the content. This is the whole scroll mechanism."""
        scroll = self.state.scroll
        return Offset(absolute.x - scroll.x, absolute.y - scroll.y)

    def child_paint_context(self, ctx: PaintContext, absolute: Any) -> PaintContext:
        """Clip content to the viewport.

        In-shader clipping, not scissor: the display list is one instanced draw
        call, so a scissor rect would have to break the batch (ARCHITECTURE.md
        5.8).
        """
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

    def paint_self(self, ctx: PaintContext, absolute: Any) -> None:
        super().paint_self(ctx, absolute)
        if self.style.scrollbar and self.scrollable:
            self._paint_scrollbar(ctx, absolute)

    def _paint_scrollbar(self, ctx: PaintContext, absolute: Any) -> None:
        track = self._main(self.size) - self.BAR_MARGIN * 2
        if track <= 0.0:
            return
        content = self._main(self._content)
        visible = self._main(self.size)
        thumb = max(self.BAR_MIN_LENGTH, track * (visible / content)) if content else track
        thumb = min(thumb, track)
        travel = track - thumb
        progress = (self.scroll_offset / self.max_scroll) if self.max_scroll else 0.0
        along = self.BAR_MARGIN + travel * progress

        if self.horizontal:
            x = absolute.x + along
            y = absolute.y + self.size.height - self.BAR_THICKNESS - self.BAR_MARGIN
            w, h = thumb, self.BAR_THICKNESS
        else:
            x = absolute.x + self.size.width - self.BAR_THICKNESS - self.BAR_MARGIN
            y = absolute.y + along
            w, h = self.BAR_THICKNESS, thumb

        _box(
            ctx,
            x,
            y,
            w,
            h,
            token=ctx.palette.index(self.style.color or "outline_variant"),
            radius=self.BAR_RADIUS,
            alpha=self.BAR_OPACITY,
        )

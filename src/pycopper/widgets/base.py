"""Concrete widgets: an element mixin combined with a layout algorithm.

Each class is ``ElementMixin`` (empty ``__slots__``, so no layout contribution)
plus exactly one M1 layout node. The subclass declares no ``__slots__`` of its
own, so it gains a ``__dict__`` for the element fields -- which is what lets a
slotted layout base and the mixin coexist without an instance-layout conflict.
"""

from __future__ import annotations

from typing import Any

from ..layout import (
    Alignment,
    Axis,
    Constraints,
    CrossAxisAlignment,
    EdgeInsets,
    Flex,
    MainAxisAlignment,
    MainAxisSize,
    Padding,
    Size,
    Stack,
)
from ..spec import StyleSpec, WidgetKind, WidgetSpec
from ..tree.element import ElementMixin, PaintContext

__all__ = [
    "ADVANCE",
    "ButtonElement",
    "ColumnElement",
    "ContainerElement",
    "RowElement",
    "SpacerElement",
    "StackElement",
    "TextElement",
    "build_element",
    "create_element",
    "measure_text",
    "paint_text",
]

_MAIN = {
    "start": MainAxisAlignment.START,
    "end": MainAxisAlignment.END,
    "center": MainAxisAlignment.CENTER,
    "space_between": MainAxisAlignment.SPACE_BETWEEN,
    "space_around": MainAxisAlignment.SPACE_AROUND,
    "space_evenly": MainAxisAlignment.SPACE_EVENLY,
}
_CROSS = {
    "start": CrossAxisAlignment.START,
    "end": CrossAxisAlignment.END,
    "center": CrossAxisAlignment.CENTER,
    "stretch": CrossAxisAlignment.STRETCH,
}


def _resolve_axis(spec_size: Any, available: float, _content: float = 0.0) -> float | None:
    """Turn a SizeSpec into a concrete extent, or None to mean 'use content'."""
    match spec_size.kind:
        case "fixed":
            return float(spec_size.value)
        case "expand":
            return available
        case "percent":
            return available * float(spec_size.value)
        case _:
            return None


class _StyledMixin(ElementMixin):
    """Applies width/height/padding from the spec around a layout algorithm."""

    def sized(self, constraints: Constraints, style: StyleSpec) -> Constraints:
        w = _resolve_axis(style.width, constraints.max_width, 0.0)
        h = _resolve_axis(style.height, constraints.max_height, 0.0)
        return constraints.tighten(width=w, height=h)


class ContainerElement(_StyledMixin, Padding):
    """A styled box with padding and at most one child."""

    def __init__(self, spec: WidgetSpec) -> None:
        Padding.__init__(self, None, spec.style.padding)
        self.init_element(spec)

    def configure(self) -> None:
        self._padding = self.style.padding

    def perform_layout(self, constraints: Constraints) -> Size:
        outer = self.sized(constraints, self.style)
        inner = super().perform_layout(outer.loosen() if not outer.is_tight else outer)
        return outer.constrain(inner)


class _FlexElement(_StyledMixin, Flex):
    axis: Axis = Axis.HORIZONTAL

    def __init__(self, spec: WidgetSpec) -> None:
        style = spec.style
        Flex.__init__(
            self,
            axis=self.axis,
            main_alignment=_MAIN[style.main_alignment],
            cross_alignment=_CROSS[style.cross_alignment],
            main_size=MainAxisSize.MAX if style.width.kind != "auto" else MainAxisSize.MIN,
            spacing=style.spacing,
        )
        self._padding = style.padding
        self.init_element(spec)

    def configure(self) -> None:
        style = self.style
        self._main_alignment = _MAIN[style.main_alignment]
        self._cross_alignment = _CROSS[style.cross_alignment]
        self._spacing = style.spacing
        self._main_size = MainAxisSize.MAX if style.width.kind != "auto" else MainAxisSize.MIN
        self._padding = style.padding

    def perform_layout(self, constraints: Constraints) -> Size:
        outer = self.sized(constraints, self.style)
        pad: EdgeInsets = self._padding
        inner = super().perform_layout(outer.deflate(pad))
        for child in self.children:
            child.offset = child.offset + pad.top_left
        return outer.constrain(inner.inflate(pad))


class RowElement(_FlexElement):
    axis = Axis.HORIZONTAL


class ColumnElement(_FlexElement):
    axis = Axis.VERTICAL


class StackElement(_StyledMixin, Stack):
    def __init__(self, spec: WidgetSpec) -> None:
        Stack.__init__(self, alignment=Alignment(spec.style.align_x, spec.style.align_y))
        self.init_element(spec)

    def configure(self) -> None:
        self._alignment = Alignment(self.style.align_x, self.style.align_y)

    def perform_layout(self, constraints: Constraints) -> Size:
        return super().perform_layout(self.sized(constraints, self.style))


ADVANCE = 0.55  # em per character; a rough sans-serif average


def measure_text(text: str, font_size: float) -> Size:
    """Placeholder metrics. M4 replaces this with real shaped advances."""
    return Size(len(text) * font_size * ADVANCE, font_size * 1.4)


def paint_text(
    ctx: PaintContext, x: float, y: float, text: str, font_size: float, token: int
) -> None:
    """Placeholder glyph painting: one rounded box per character.

    Deliberately crude. It exists so layout, bindings, reconciliation, and
    events can be built and tested now; M4 swaps in shaped glyphs from the
    atlas without changing any caller.
    """
    dpr = ctx.pixel_ratio
    advance = font_size * ADVANCE * dpr
    for i, char in enumerate(text):
        if char.isspace():
            continue
        ctx.display_list.add_box(
            x + i * advance,
            y,
            advance * 0.72,
            font_size * 0.72 * dpr,
            token=token,
            color=(1.0, 1.0, 1.0, 1.0),
            radii=(1.0, 1.0, 1.0, 1.0),
            clip=ctx.clip,
            clip_radii=ctx.clip_radii,
        )


class ButtonElement(ContainerElement):
    """A container that reacts to pointer state and centres its own label."""

    def paint_self(self, ctx: PaintContext, absolute: Any) -> None:
        super().paint_self(ctx, absolute)
        dpr = ctx.pixel_ratio
        size = self.size
        token = ctx.palette.index(self.style.color)
        radii = tuple(r * dpr for r in self.style.corner_radius)

        # MD3 state layer: over the container surface, under the label.
        if self.state.pressed or self.state.hovered:
            ctx.display_list.add_box(
                absolute.x * dpr,
                absolute.y * dpr,
                size.width * dpr,
                size.height * dpr,
                token=token,
                color=(1.0, 1.0, 1.0, 0.16 if self.state.pressed else 0.08),
                radii=radii,  # type: ignore[arg-type]
                clip=ctx.clip,
                clip_radii=ctx.clip_radii,
            )

        if self._text.strip():
            font = self.style.font_size
            label = measure_text(self._text, font)
            paint_text(
                ctx,
                (absolute.x + (size.width - label.width) / 2) * dpr,
                (absolute.y + (size.height - font * 0.72) / 2) * dpr,
                self._text,
                font,
                token,
            )


class TextElement(_StyledMixin, Padding):
    """Text placeholder.

    M4 replaces the measurement and painting here with the real text pipeline.
    Until then a glyph is approximated as a fixed-advance box so layout,
    reconciliation, and bindings can be built and tested now.
    """

    ADVANCE = 0.55  # em per character, roughly a sans-serif average

    def __init__(self, spec: WidgetSpec) -> None:
        Padding.__init__(self, None, spec.style.padding)
        self.init_element(spec)

    def configure(self) -> None:
        self._padding = self.style.padding

    def measure(self) -> Size:
        return measure_text(self._text, self.style.font_size)

    def perform_layout(self, constraints: Constraints) -> Size:
        outer = self.sized(constraints, self.style)
        return outer.constrain(self.measure().inflate(self._padding))

    def paint_self(self, ctx: PaintContext, absolute: Any) -> None:
        super().paint_self(ctx, absolute)
        if not self._text.strip():
            return
        dpr = ctx.pixel_ratio
        font = self.style.font_size
        token = ctx.palette.index(self.style.color)
        x = (absolute.x + self._padding.left) * dpr
        y = (absolute.y + self._padding.top + font * 0.25) * dpr
        advance = font * self.ADVANCE * dpr
        for i, char in enumerate(self._text):
            if char.isspace():
                continue
            ctx.display_list.add_box(
                x + i * advance,
                y,
                advance * 0.72,
                font * 0.72 * dpr,
                token=token,
                color=(1.0, 1.0, 1.0, 1.0),
                radii=(1.0, 1.0, 1.0, 1.0),
                clip=ctx.clip,
                clip_radii=ctx.clip_radii,
            )


class SpacerElement(_StyledMixin, Padding):
    def __init__(self, spec: WidgetSpec) -> None:
        Padding.__init__(self, None, EdgeInsets())
        self.init_element(spec)

    def perform_layout(self, constraints: Constraints) -> Size:
        outer = self.sized(constraints, self.style)
        return outer.constrain(outer.smallest)


_REGISTRY: dict[WidgetKind, type] = {
    WidgetKind.CONTAINER: ContainerElement,
    WidgetKind.ROW: RowElement,
    WidgetKind.COLUMN: ColumnElement,
    WidgetKind.STACK: StackElement,
    WidgetKind.BUTTON: ButtonElement,
    WidgetKind.TEXT: TextElement,
    WidgetKind.SPACER: SpacerElement,
}


def create_element(spec: WidgetSpec) -> Any:
    """Construct the element for one spec node (no children)."""
    return _REGISTRY[spec.widget](spec)


def build_element(spec: WidgetSpec) -> Any:
    """Construct a whole element subtree from a spec subtree."""
    element = create_element(spec)
    for child_spec in spec.children:
        element.add_child(build_element(child_spec))
    return element

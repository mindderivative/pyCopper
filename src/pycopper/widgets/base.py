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
from ..text import FontRequest, TextEngine
from ..text.layout import Alignment as TextAlignment
from ..tree.element import ElementMixin, PaintContext, default_text_engine

__all__ = [
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


def _resolve_axis(spec_size: Any, available: float) -> float | None:
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
        w = _resolve_axis(style.width, constraints.max_width)
        h = _resolve_axis(style.height, constraints.max_height)
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


def measure_text(
    text: str,
    font_size: float,
    *,
    engine: TextEngine | None = None,
    max_width: float | None = None,
) -> Size:
    """Shaped metrics for *text*. Memoised by the engine."""
    return (engine or default_text_engine()).measure(text, px=font_size, max_width=max_width)


def paint_text(
    ctx: PaintContext,
    x: float,
    y: float,
    text: str,
    font_size: float,
    token: int,
    *,
    max_width: float | None = None,
    alignment: str = TextAlignment.START,
) -> int:
    """Emit shaped glyphs at logical position ``(x, y)``.

    ``x``/``y`` are the top-left of the text block; the baseline offset comes
    from the font's own ascent, so lines sit correctly whatever face is used.
    """
    paragraph = ctx.text.layout(text, px=font_size, max_width=max_width, alignment=alignment)
    return ctx.text.emit(
        ctx.display_list,
        paragraph,
        x=x,
        y=y,
        pixel_ratio=ctx.pixel_ratio,
        token=token,
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
            label = measure_text(self._text, font, engine=self.text_engine)
            metrics = self.text_engine.db.face_for(FontRequest()).metrics(font)
            paint_text(
                ctx,
                absolute.x + (size.width - label.width) / 2,
                absolute.y + (size.height - metrics.line_height) / 2,
                self._text,
                font,
                token,
            )


class TextElement(_StyledMixin, Padding):
    """A run of text, shaped and wrapped to the available width."""

    def __init__(self, spec: WidgetSpec) -> None:
        Padding.__init__(self, None, spec.style.padding)
        self.init_element(spec)

    def configure(self) -> None:
        self._padding = self.style.padding

    def _wrap_width(self, constraints: Constraints) -> float | None:
        """Width available for text, or None when the box is unbounded."""
        width = _resolve_axis(self.style.width, constraints.max_width)
        if width is None:
            if not constraints.has_bounded_width:
                return None
            width = constraints.max_width
        return max(0.0, width - self._padding.horizontal)

    def measure(self, constraints: Constraints | None = None) -> Size:
        wrap = self._wrap_width(constraints) if constraints is not None else None
        return measure_text(
            self._text,
            self.style.font_size,
            engine=self.text_engine,
            max_width=wrap,
        )

    def perform_layout(self, constraints: Constraints) -> Size:
        outer = self.sized(constraints, self.style)
        return outer.constrain(self.measure(constraints).inflate(self._padding))

    def paint_self(self, ctx: PaintContext, absolute: Any) -> None:
        super().paint_self(ctx, absolute)
        if not self._text.strip():
            return
        paint_text(
            ctx,
            absolute.x + self._padding.left,
            absolute.y + self._padding.top,
            self._text,
            self.style.font_size,
            ctx.palette.index(self.style.color),
            max_width=max(0.0, self.size.width - self._padding.horizontal) or None,
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

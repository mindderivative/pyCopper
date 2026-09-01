"""Concrete widgets: an element mixin combined with a layout algorithm.

Each class is ``ElementMixin`` (empty ``__slots__``, so no layout contribution)
plus exactly one M1 layout node. The subclass declares no ``__slots__`` of its
own, so it gains a ``__dict__`` for the element fields -- which is what lets a
slotted layout base and the mixin coexist without an instance-layout conflict.
"""

from __future__ import annotations

from typing import Any, Final

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
from ..paint import NO_TOKEN
from ..spec import StyleSpec, WidgetKind, WidgetSpec
from ..text import TextEngine
from ..text.layout import Alignment as TextAlignment
from ..tree.element import ElementMixin, PaintContext, default_text_engine

__all__ = [
    "ButtonElement",
    "ColumnElement",
    "ContainerElement",
    "IconElement",
    "RowElement",
    "SpacerElement",
    "StackElement",
    "TextElement",
    "build_element",
    "content_token",
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


def content_token(ctx: PaintContext, style: StyleSpec, default: str) -> int:
    """Palette index for a widget's content colour.

    `style.color` of None means "use this widget's M3 default for its variant",
    so each component supplies its own rather than inheriting a global one.
    """
    return ctx.palette.index(style.color or default)


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


def _main_size_for(axis: Axis, style: StyleSpec) -> MainAxisSize:
    """Fill the main axis only when the view sized THAT axis.

    The main axis of a Column is its HEIGHT. Keying this off `width` made a
    Column with `width: expand` greedily fill vertically as well.
    """
    sized = style.width if axis is Axis.HORIZONTAL else style.height
    return MainAxisSize.MAX if sized.kind != "auto" else MainAxisSize.MIN


class _FlexElement(_StyledMixin, Flex):
    axis: Axis = Axis.HORIZONTAL

    def __init__(self, spec: WidgetSpec) -> None:
        style = spec.style
        Flex.__init__(
            self,
            axis=self.axis,
            main_alignment=_MAIN[style.main_alignment],
            cross_alignment=_CROSS[style.cross_alignment],
            main_size=_main_size_for(self.axis, style),
            spacing=style.spacing,
        )
        self._padding = style.padding
        self.init_element(spec)

    def flex_of(self, child: Any) -> int:
        """A child styled `expand` or `flex:n` along the main axis is flexible.

        Without this a Spacer with `width: expand` is treated as inflexible,
        measured against all remaining space, and starves its siblings.
        """
        explicit = super().flex_of(child)
        if explicit:
            return explicit
        if not isinstance(child, ElementMixin):
            return 0
        size = child.style.width if self.axis is Axis.HORIZONTAL else child.style.height
        if size.kind == "flex":
            return max(1, int(size.value))
        return 1 if size.kind == "expand" else 0

    def configure(self) -> None:
        style = self.style
        self._main_alignment = _MAIN[style.main_alignment]
        self._cross_alignment = _CROSS[style.cross_alignment]
        self._spacing = style.spacing
        self._main_size = _main_size_for(self.axis, style)
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
    """M3 Common Button: 40dp high, full radius, five variants.

    M3 describes these as one component in five configurations, so they are one
    widget with a `variant`, not five widget kinds. Container and content
    tokens come from the variant unless the view sets them explicitly.
    """

    HEIGHT: Final = 40.0
    MIN_WIDTH: Final = 64.0

    #: variant -> (container token or None, content token, outlined, elevated)
    VARIANTS: Final = {
        "filled": ("primary", "on_primary", False, False),
        "filled_tonal": ("secondary_container", "on_secondary_container", False, False),
        "outlined": (None, "primary", True, False),
        "elevated": ("surface_container_low", "primary", False, True),
        "text": (None, "primary", False, False),
    }

    @property
    def effective_radii(self) -> tuple[float, float, float, float]:
        radii = self.style.corner_radius
        return radii if any(radii) else (self.size.height / 2,) * 4

    def _variant(self) -> tuple[str | None, str, bool, bool]:
        return self.VARIANTS.get(self.style.variant, self.VARIANTS["filled"])

    def paint_self(self, ctx: PaintContext, absolute: Any) -> None:
        style = self.style
        container, content, outlined, elevated = self._variant()
        size = self.size
        dpr = ctx.pixel_ratio
        radii = style.corner_radius
        if not any(radii):
            radii = (size.height / 2,) * 4
        token = content_token(ctx, style, content)

        if elevated:
            ctx.display_list.add_shadow(
                absolute.x * dpr,
                absolute.y * dpr,
                size.width * dpr,
                size.height * dpr,
                blur=5.0 * dpr,
                offset=(0.0, 1.0 * dpr),
                color=(0.0, 0.0, 0.0, 0.30),
                radii=tuple(r * dpr for r in radii),  # type: ignore[arg-type]
                clip=ctx.clip,
                clip_radii=ctx.clip_radii,
            )

        fill = style.background or container
        if fill is not None:
            ctx.display_list.add_box(
                absolute.x * dpr,
                absolute.y * dpr,
                size.width * dpr,
                size.height * dpr,
                token=ctx.palette.index(fill),
                color=(1.0, 1.0, 1.0, style.opacity),
                radii=tuple(r * dpr for r in radii),  # type: ignore[arg-type]
                border_width=1.0 * dpr if outlined else 0.0,
                border_token=ctx.palette.index("outline") if outlined else NO_TOKEN,
                border_color=(1.0, 1.0, 1.0, 1.0),
                clip=ctx.clip,
                clip_radii=ctx.clip_radii,
            )
        elif outlined:
            ctx.display_list.add_box(
                absolute.x * dpr,
                absolute.y * dpr,
                size.width * dpr,
                size.height * dpr,
                token=ctx.palette.index("outline"),
                color=(1.0, 1.0, 1.0, 0.0),
                radii=tuple(r * dpr for r in radii),  # type: ignore[arg-type]
                border_width=1.0 * dpr,
                border_token=ctx.palette.index("outline"),
                border_color=(1.0, 1.0, 1.0, 1.0),
                clip=ctx.clip,
                clip_radii=ctx.clip_radii,
            )

        # MD3 state layer: over the container, under the label.
        if self.state.pressed or self.state.hovered or self.state.focused:
            alpha = 0.10 if (self.state.pressed or self.state.focused) else 0.08
            ctx.display_list.add_box(
                absolute.x * dpr,
                absolute.y * dpr,
                size.width * dpr,
                size.height * dpr,
                token=token,
                color=(1.0, 1.0, 1.0, alpha),
                radii=tuple(r * dpr for r in radii),  # type: ignore[arg-type]
                clip=ctx.clip,
                clip_radii=ctx.clip_radii,
            )

        if self._text.strip():
            font = style.font_size
            label = measure_text(self._text, font, engine=self.text_engine)
            paint_text(
                ctx,
                absolute.x + (size.width - label.width) / 2,
                absolute.y + (size.height - label.height) / 2,
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
            content_token(ctx, self.style, "on_surface"),
            max_width=max(0.0, self.size.width - self._padding.horizontal) or None,
        )


class IconElement(_StyledMixin, Padding):
    """A Material Symbols icon.

    The icon name comes from `text:`, so binding expressions work on it -- an
    icon can switch with state exactly the way a label can.
    """

    def __init__(self, spec: WidgetSpec) -> None:
        Padding.__init__(self, None, spec.style.padding)
        self.init_element(spec)

    def configure(self) -> None:
        self._padding = self.style.padding

    def perform_layout(self, constraints: Constraints) -> Size:
        style = self.style
        outer = self.sized(constraints, style)
        natural = Size(style.icon_size, style.icon_size).inflate(self._padding)
        return outer.constrain(natural)

    def paint_self(self, ctx: PaintContext, absolute: Any) -> None:
        super().paint_self(ctx, absolute)
        name = self._text.strip()
        if not name:
            return
        style = self.style
        size = style.icon_size
        # Centre the glyph box within whatever the element was given, so an
        # icon in a fixed-size button sits correctly rather than at its corner.
        ctx.text.emit_icon(
            ctx.display_list,
            name,
            x=absolute.x + (self.size.width - size) / 2,
            y=absolute.y + (self.size.height - size) / 2,
            size=size,
            fill=style.icon_fill,
            weight=style.icon_weight,
            pixel_ratio=ctx.pixel_ratio,
            token=content_token(ctx, style, "on_surface"),
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


def _material_registry() -> dict[WidgetKind, type]:
    """Imported lazily: material.py imports helpers from this module."""
    from . import material as m
    from . import navigation as n

    return {
        WidgetKind.CARD: m.CardElement,
        WidgetKind.DIVIDER: m.DividerElement,
        WidgetKind.CHECKBOX: m.CheckboxElement,
        WidgetKind.RADIO: m.RadioElement,
        WidgetKind.SWITCH: m.SwitchElement,
        WidgetKind.CHIP: m.ChipElement,
        WidgetKind.ICON_BUTTON: m.IconButtonElement,
        WidgetKind.FAB: m.FabElement,
        WidgetKind.BADGE: m.BadgeElement,
        WidgetKind.NAVIGATION_RAIL: n.NavigationRailElement,
        WidgetKind.NAVIGATION_DRAWER: n.NavigationDrawerElement,
        WidgetKind.NAV_ITEM: n.NavItemElement,
        WidgetKind.TOP_APP_BAR: n.TopAppBarElement,
        WidgetKind.TABS: n.TabsElement,
        WidgetKind.TAB: n.TabElement,
        WidgetKind.SEGMENTED_BUTTON: n.SegmentedButtonElement,
        WidgetKind.SEGMENT: n.SegmentElement,
        WidgetKind.LIST_ITEM: n.ListItemElement,
        WidgetKind.LINEAR_PROGRESS: n.LinearProgressElement,
    }


_REGISTRY: dict[WidgetKind, type] = {
    WidgetKind.CONTAINER: ContainerElement,
    WidgetKind.ROW: RowElement,
    WidgetKind.COLUMN: ColumnElement,
    WidgetKind.STACK: StackElement,
    WidgetKind.BUTTON: ButtonElement,
    WidgetKind.TEXT: TextElement,
    WidgetKind.SPACER: SpacerElement,
    WidgetKind.ICON: IconElement,
}

_REGISTRY_COMPLETE = False


def create_element(spec: WidgetSpec) -> Any:
    """Construct the element for one spec node (no children)."""
    if not _REGISTRY_COMPLETE:
        _REGISTRY.update(_material_registry())
        globals()["_REGISTRY_COMPLETE"] = True
    return _REGISTRY[spec.widget](spec)


def build_element(spec: WidgetSpec) -> Any:
    """Construct a whole element subtree from a spec subtree."""
    element = create_element(spec)
    for child_spec in spec.children:
        element.add_child(build_element(child_spec))
    return element

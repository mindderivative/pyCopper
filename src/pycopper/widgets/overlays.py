"""Material Design 3 overlay components: Dialog, Menu, Tooltip, Snackbar, Sheets.

These are the six components the overlay layer exists for (`runtime/overlay.py`).
That host already owns placement, the scrim, modality and dismissal, so what
these classes add is M3's **anatomy** -- container tokens, shape, and the
padding between the parts -- and no positioning logic of their own. A Dialog
does not know it is centred; it knows it is 28dp-rounded `surface_container_high`
that is at least 280dp and at most 560dp wide.

Every dimension below is cited from `M3-References`. Where the scraped spec has
no table -- Snackbar's corner radius is the one case -- the value is taken from
the shape scale and marked as inferred rather than quietly invented.
"""

from __future__ import annotations

from typing import Any, ClassVar, Final

from ..layout import (
    Axis,
    Constraints,
    EdgeInsets,
    Flex,
    MainAxisSize,
    Offset,
    Padding,
    Size,
)
from ..spec import StyleSpec, WidgetSpec
from ..tree.element import PaintContext
from .base import _StyledMixin, content_token, measure_text, paint_text
from .material import _box, _emit_state_layer

__all__ = [
    "BottomSheetElement",
    "DialogElement",
    "MenuElement",
    "MenuItemElement",
    "SideSheetElement",
    "SnackbarElement",
    "TooltipElement",
]


def _surface(
    ctx: PaintContext,
    absolute: Any,
    size: Size,
    *,
    token: int,
    radii: tuple[float, float, float, float],
    alpha: float = 1.0,
) -> None:
    """`_box` with per-corner radii, which the sheets need.

    A bottom sheet rounds only its top corners and a side sheet only its
    leading edge, so the single-radius helper in `material.py` cannot express
    them.
    """
    dpr = ctx.pixel_ratio
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


def _clamp(value: float, low: float, high: float) -> float:
    return max(low, min(high, value))


def _clamped_width(
    constraints: Constraints,
    style: StyleSpec,
    *,
    minimum: float,
    maximum: float,
    unbounded: float,
) -> float:
    """M3's min/max width, reconciled with the constraints actually given.

    Three rules, in order:

    1. An explicit `width:` in the view always wins.
    2. Otherwise the component **fills the width it is offered**, capped at the
       M3 maximum. pyCopper has no intrinsic-sizing pass -- layout is one
       downward pass of constraints (ARCHITECTURE.md 5.4) -- so a menu cannot
       ask "how wide is my widest item?". Filling the offer is the honest
       fallback, and a designer who wants content width sets `width:`.
    3. With **unbounded** width there is nothing to fill, so the component
       takes *unbounded* -- its M3 minimum for a menu or dialog, its maximum
       for a sheet, which is meant to span the window.

    The final `constrain_width` is not optional: a layout node must return a
    size its constraints permit (`layout/node.py` asserts this). M3's minimum
    is therefore an aspiration that yields to a narrower parent -- without it a
    Menu offered 50dp raised outright rather than shrinking.
    """
    if style.width.kind == "fixed":
        return constraints.constrain_width(float(style.width.value))
    available = constraints.max_width if constraints.has_bounded_width else unbounded
    return constraints.constrain_width(_clamp(available, minimum, maximum))


class _PaddedFlex(_StyledMixin, Flex):
    """A Flex that reserves padding around its children.

    `Flex` has no padding of its own, so it is applied by deflating the
    constraints, laying out normally, then translating each child by the
    top-left inset. Child offsets are assigned during `Flex.perform_layout`
    and are safe to adjust immediately afterwards.
    """

    axis: Axis = Axis.VERTICAL
    #: Subclass hook: the M3 padding for this component.
    INSETS: ClassVar[EdgeInsets] = EdgeInsets()

    def __init__(self, spec: WidgetSpec) -> None:
        Flex.__init__(self, axis=self.axis, spacing=spec.style.spacing)
        self.init_element(spec)

    def configure(self) -> None:
        self._spacing = self.style.spacing

    def insets(self) -> EdgeInsets:
        pad = self.style.padding
        return pad if pad != EdgeInsets() else self.INSETS

    def perform_layout(self, constraints: Constraints) -> Size:
        pad = self.insets()
        self._main_size = MainAxisSize.MIN
        inner = super().perform_layout(constraints.deflate(pad))
        for child in self.children:
            child.offset = child.offset + pad.top_left
        return constraints.constrain(inner.inflate(pad))


# ------------------------------------------------------------------- dialog


class DialogElement(_StyledMixin, Padding):
    """M3 basic dialog.

    Anatomy, from `COMPONENT_DIALOGS.md`: an optional 24dp icon, a headline
    (`text:`), supporting text (`supporting_text:`), and an actions area --
    supplied as the single child, normally a Row of buttons.

    The dialog **shrink-wraps its height** ("Container height: Dynamic") and
    clamps its width to 280-560dp. That is the point of having the widget: the
    view file no longer guesses a fixed height that breaks the moment the body
    text rewraps.
    """

    RADIUS: Final = 28.0
    PADDING: Final = 24.0
    MIN_WIDTH: Final = 280.0
    MAX_WIDTH: Final = 560.0
    HEADLINE: Final = 24.0
    BODY: Final = 14.0
    #: "Padding between title and body: 16dp"
    GAP_TITLE_BODY: Final = 16.0
    #: "Padding between body and actions: 24dp"
    GAP_BODY_ACTIONS: Final = 24.0

    @property
    def effective_radii(self) -> tuple[float, float, float, float]:
        radii = self.style.corner_radius
        return radii if any(radii) else (self.RADIUS,) * 4

    def __init__(self, spec: WidgetSpec) -> None:
        Padding.__init__(self, None, self._insets(spec.style))
        self.init_element(spec)

    @staticmethod
    def _insets(style: StyleSpec) -> EdgeInsets:
        pad = style.padding
        return pad if pad != EdgeInsets() else EdgeInsets.all(DialogElement.PADDING)

    def configure(self) -> None:
        self._padding = self._insets(self.style)

    def _width(self, constraints: Constraints) -> float:
        return _clamped_width(
            constraints,
            self.style,
            minimum=self.MIN_WIDTH,
            maximum=self.MAX_WIDTH,
            unbounded=self.MIN_WIDTH,
        )

    def _blocks(self, inner_width: float) -> tuple[float, float]:
        """Measured heights of the headline and supporting text."""
        engine = self.text_engine
        head = self._text.strip()
        body = self._supporting.strip()
        head_h = (
            measure_text(head, self.HEADLINE, engine=engine, max_width=inner_width).height
            if head
            else 0.0
        )
        body_h = (
            measure_text(body, self.BODY, engine=engine, max_width=inner_width).height
            if body
            else 0.0
        )
        if head_h and body_h:
            body_h += self.GAP_TITLE_BODY
        return head_h, body_h

    def perform_layout(self, constraints: Constraints) -> Size:
        pad = self._padding
        width = self._width(constraints)
        inner_width = max(0.0, width - pad.horizontal)
        head_h, body_h = self._blocks(inner_width)
        text_h = head_h + body_h

        actions_h = 0.0
        child = self.child
        if child is not None:
            child.layout(
                Constraints(
                    min_width=0.0,
                    max_width=inner_width,
                    min_height=0.0,
                    max_height=constraints.max_height,
                )
            )
            actions_h = child.size.height
            gap = self.GAP_BODY_ACTIONS if text_h else 0.0
            child.offset = Offset(pad.left, pad.top + text_h + gap)
            actions_h += gap

        height = pad.vertical + text_h + actions_h
        if self.style.height.kind == "fixed":
            height = float(self.style.height.value)
        return constraints.constrain(Size(width, height))

    def paint_self(self, ctx: PaintContext, absolute: Any) -> None:
        style = self.style
        radii = self.effective_radii
        _surface(
            ctx,
            absolute,
            self.size,
            token=ctx.palette.index(style.background or "surface_container_high"),
            radii=radii,
        )

        pad = self._padding
        inner_width = max(0.0, self.size.width - pad.horizontal)
        x = absolute.x + pad.left
        y = absolute.y + pad.top
        head = self._text.strip()
        body = self._supporting.strip()

        if head:
            paint_text(
                ctx,
                x,
                y,
                head,
                self.HEADLINE,
                content_token(ctx, style, "on_surface"),
                max_width=inner_width,
            )
            y += measure_text(
                head, self.HEADLINE, engine=self.text_engine, max_width=inner_width
            ).height
        if body:
            if head:
                y += self.GAP_TITLE_BODY
            paint_text(
                ctx,
                x,
                y,
                body,
                self.BODY,
                ctx.palette.index("on_surface_variant"),
                max_width=inner_width,
            )


# --------------------------------------------------------------------- menu


class MenuElement(_PaddedFlex):
    """M3 baseline menu: 4dp corners, 112-280dp wide, 8dp vertical padding.

    Values from `COMPONENT_MENUS.md` ("Baseline menu padding and size
    measurements"). The vertical-menu variant M3 now leads with adds shape
    morphing and vibrant colour, both of which need motion and a theme engine
    pyCopper does not have yet -- so the baseline is what is implemented, and
    that is a deliberate choice rather than an oversight.
    """

    RADIUS: Final = 4.0
    MIN_WIDTH: Final = 112.0
    MAX_WIDTH: Final = 280.0
    PAD_Y: Final = 8.0
    INSETS: ClassVar[EdgeInsets] = EdgeInsets.symmetric(vertical=PAD_Y)
    axis = Axis.VERTICAL

    @property
    def effective_radii(self) -> tuple[float, float, float, float]:
        radii = self.style.corner_radius
        return radii if any(radii) else (self.RADIUS,) * 4

    def perform_layout(self, constraints: Constraints) -> Size:
        width = _clamped_width(
            constraints,
            self.style,
            minimum=self.MIN_WIDTH,
            maximum=self.MAX_WIDTH,
            unbounded=self.MIN_WIDTH,
        )
        inner = constraints.copy_with(min_width=width, max_width=width)
        return super().perform_layout(inner)

    def paint_self(self, ctx: PaintContext, absolute: Any) -> None:
        _surface(
            ctx,
            absolute,
            self.size,
            token=ctx.palette.index(self.style.background or "surface_container"),
            radii=self.effective_radii,
        )


class MenuItemElement(_StyledMixin, Padding):
    """One row of a Menu: 48dp tall, 12dp side padding.

    Distinct from `ListItem`, whose M3 heights are 56/72/88dp -- a menu row is
    denser. `supporting_text:` is the trailing text (a keyboard shortcut, in
    practice), drawn `on_surface_variant` at the far edge.
    """

    HEIGHT: Final = 48.0
    PAD_X: Final = 12.0
    LABEL: Final = 14.0

    def __init__(self, spec: WidgetSpec) -> None:
        Padding.__init__(self, None, EdgeInsets())
        self.init_element(spec)

    def perform_layout(self, constraints: Constraints) -> Size:
        outer = self.sized(constraints, self.style)
        width = outer.max_width if outer.has_bounded_width else MenuElement.MIN_WIDTH
        height = (
            float(self.style.height.value) if self.style.height.kind == "fixed" else self.HEIGHT
        )
        return outer.constrain(Size(width, height))

    def paint_self(self, ctx: PaintContext, absolute: Any) -> None:
        style = self.style
        label_token = content_token(ctx, style, "on_surface")
        if style.background:
            _surface(
                ctx,
                absolute,
                self.size,
                token=ctx.palette.index(style.background),
                radii=(0.0,) * 4,
            )
        _emit_state_layer(ctx, self, absolute, label_token, (0.0,) * 4)

        label = self._text.strip()
        if label:
            metrics = measure_text(label, self.LABEL, engine=self.text_engine)
            paint_text(
                ctx,
                absolute.x + self.PAD_X,
                absolute.y + (self.size.height - metrics.height) / 2,
                label,
                self.LABEL,
                label_token,
            )
        trailing = self._supporting.strip()
        if trailing:
            metrics = measure_text(trailing, self.LABEL, engine=self.text_engine)
            paint_text(
                ctx,
                absolute.x + self.size.width - self.PAD_X - metrics.width,
                absolute.y + (self.size.height - metrics.height) / 2,
                trailing,
                self.LABEL,
                ctx.palette.index("on_surface_variant"),
            )


# ------------------------------------------------------------------ tooltip


class TooltipElement(_StyledMixin, Padding):
    """M3 plain tooltip: 24dp minimum height, 8dp padding, inverse colours.

    From `COMPONENT_TOOLTIPS.md`: container `inverse_surface`, label
    `inverse_on_surface`. Never modal and never scrimmed -- a tooltip explains
    what is underneath it, so covering that would defeat it.
    """

    RADIUS: Final = 4.0
    MIN_HEIGHT: Final = 24.0
    #: The spec table gives a single "Padding: 8dp". It has to mean the
    #: horizontal inset: 8dp above and below a body-small label would exceed
    #: the 24dp container height the same table specifies. So 8dp on the sides,
    #: and the vertical inset is whatever centres the label in 24dp.
    PAD_X: Final = 8.0
    PAD_Y: Final = 4.0
    LABEL: Final = 12.0

    @property
    def effective_radii(self) -> tuple[float, float, float, float]:
        radii = self.style.corner_radius
        return radii if any(radii) else (self.RADIUS,) * 4

    def __init__(self, spec: WidgetSpec) -> None:
        Padding.__init__(self, None, EdgeInsets())
        self.init_element(spec)

    def perform_layout(self, constraints: Constraints) -> Size:
        outer = self.sized(constraints, self.style)
        label = self._text.strip()
        metrics = measure_text(label, self.LABEL, engine=self.text_engine) if label else Size(0, 0)
        return outer.constrain(
            Size(
                metrics.width + self.PAD_X * 2,
                max(self.MIN_HEIGHT, metrics.height + self.PAD_Y * 2),
            )
        )

    def paint_self(self, ctx: PaintContext, absolute: Any) -> None:
        style = self.style
        _surface(
            ctx,
            absolute,
            self.size,
            token=ctx.palette.index(style.background or "inverse_surface"),
            radii=self.effective_radii,
        )
        label = self._text.strip()
        if not label:
            return
        metrics = measure_text(label, self.LABEL, engine=self.text_engine)
        paint_text(
            ctx,
            absolute.x + self.PAD_X,
            absolute.y + (self.size.height - metrics.height) / 2,
            label,
            self.LABEL,
            content_token(ctx, style, "inverse_on_surface"),
        )


# ----------------------------------------------------------------- snackbar


class SnackbarElement(_StyledMixin, Padding):
    """M3 snackbar: `inverse_surface`, 48dp single line growing to 64dp.

    Colours and the 48-64dp growth are from `COMPONENT_SNACKBAR.md`. That page
    carries no measurement table, so two values here are **inferred, not
    quoted**: the 4dp corner radius comes from the extra-small step of the
    shape scale (`styles/M3-Styles-Shape-CornerRadiusScale.md`), and the 600dp
    width cap is a desktop-reasonable choice, since the spec constrains a
    snackbar only by "a fixed distance from the leading, trailing, and bottom
    edges". Both are flagged because every other number in this module is
    sourced.

    `supporting_text:` is the optional action label, drawn `inverse_primary` at
    the trailing edge.
    """

    RADIUS: Final = 4.0
    MIN_HEIGHT: Final = 48.0
    MAX_HEIGHT: Final = 64.0
    PAD_X: Final = 16.0
    LABEL: Final = 14.0
    MAX_WIDTH: Final = 600.0
    DEFAULT_PLACEMENT = "bottom"

    @property
    def effective_radii(self) -> tuple[float, float, float, float]:
        radii = self.style.corner_radius
        return radii if any(radii) else (self.RADIUS,) * 4

    def __init__(self, spec: WidgetSpec) -> None:
        Padding.__init__(self, None, EdgeInsets())
        self.init_element(spec)

    def _action_width(self) -> float:
        action = self._supporting.strip()
        if not action:
            return 0.0
        return measure_text(action, self.LABEL, engine=self.text_engine).width + self.PAD_X

    def perform_layout(self, constraints: Constraints) -> Size:
        outer = self.sized(constraints, self.style)
        width = _clamped_width(
            outer, self.style, minimum=0.0, maximum=self.MAX_WIDTH, unbounded=self.MAX_WIDTH
        )

        text_width = max(0.0, width - self.PAD_X * 2 - self._action_width())
        label = self._text.strip()
        metrics = (
            measure_text(label, self.LABEL, engine=self.text_engine, max_width=text_width)
            if label
            else Size(0, 0)
        )
        return outer.constrain(Size(width, self._height_for(metrics.height)))

    def _height_for(self, text_height: float) -> float:
        """M3 gives two heights, not a formula: 48dp for one line, 64dp for two.

        So this counts lines rather than padding the measured height -- an
        arithmetic version landed on 62dp for two lines, which is not a number
        the spec contains.
        """
        one_line = measure_text("Ag", self.LABEL, engine=self.text_engine).height
        return self.MIN_HEIGHT if text_height <= one_line + 1.0 else self.MAX_HEIGHT

    def paint_self(self, ctx: PaintContext, absolute: Any) -> None:
        style = self.style
        _surface(
            ctx,
            absolute,
            self.size,
            token=ctx.palette.index(style.background or "inverse_surface"),
            radii=self.effective_radii,
        )
        label_token = content_token(ctx, style, "inverse_on_surface")
        action = self._supporting.strip()
        action_w = self._action_width()

        label = self._text.strip()
        if label:
            text_width = max(0.0, self.size.width - self.PAD_X * 2 - action_w)
            metrics = measure_text(label, self.LABEL, engine=self.text_engine, max_width=text_width)
            paint_text(
                ctx,
                absolute.x + self.PAD_X,
                absolute.y + (self.size.height - metrics.height) / 2,
                label,
                self.LABEL,
                label_token,
                max_width=text_width,
            )
        if action:
            metrics = measure_text(action, self.LABEL, engine=self.text_engine)
            paint_text(
                ctx,
                absolute.x + self.size.width - self.PAD_X - metrics.width,
                absolute.y + (self.size.height - metrics.height) / 2,
                action,
                self.LABEL,
                ctx.palette.index("inverse_primary"),
            )


# ------------------------------------------------------------------- sheets


class BottomSheetElement(_PaddedFlex):
    """M3 bottom sheet: full width to a 640dp max, 28dp top corners.

    From `COMPONENT_BOTTOM_SHEETS.md`: `surface_container_low`, an optional
    32x4dp drag handle centred with 22dp padding above and below, and a 640dp
    max width. Only the top corners round, because the sheet is flush with the
    bottom edge of the window.

    The handle is drawn but **not draggable**: dragging it needs pointer
    capture wired to the sheet's height, which is not built. Motion exists
    (5.17), so this is now a gesture gap rather than an animation one.
    `handle:` is off by default for that reason.
    """

    RADIUS: Final = 28.0
    MAX_WIDTH: Final = 640.0
    HANDLE_WIDTH: Final = 32.0
    HANDLE_HEIGHT: Final = 4.0
    HANDLE_PAD: Final = 22.0
    DEFAULT_PLACEMENT = "bottom"
    DOCKED = True
    axis = Axis.VERTICAL

    @property
    def effective_radii(self) -> tuple[float, float, float, float]:
        radii = self.style.corner_radius
        return radii if any(radii) else (self.RADIUS, self.RADIUS, 0.0, 0.0)

    def _handle_band(self) -> float:
        """Vertical space the drag handle occupies, including its padding."""
        if not self.style.handle:
            return 0.0
        return self.HANDLE_HEIGHT + self.HANDLE_PAD * 2

    def insets(self) -> EdgeInsets:
        pad = super().insets()
        band = self._handle_band()
        return EdgeInsets(pad.left, pad.top + band, pad.right, pad.bottom) if band else pad

    def perform_layout(self, constraints: Constraints) -> Size:
        width = _clamped_width(
            constraints,
            self.style,
            minimum=0.0,
            maximum=self.MAX_WIDTH,
            unbounded=self.MAX_WIDTH,
        )
        inner = constraints.copy_with(min_width=width, max_width=width)
        return super().perform_layout(inner)

    def paint_self(self, ctx: PaintContext, absolute: Any) -> None:
        _surface(
            ctx,
            absolute,
            self.size,
            token=ctx.palette.index(self.style.background or "surface_container_low"),
            radii=self.effective_radii,
        )
        if not self.style.handle:
            return
        _box(
            ctx,
            absolute.x + (self.size.width - self.HANDLE_WIDTH) / 2,
            absolute.y + self.HANDLE_PAD,
            self.HANDLE_WIDTH,
            self.HANDLE_HEIGHT,
            token=ctx.palette.index("on_surface_variant"),
            radius=self.HANDLE_HEIGHT / 2,
            alpha=0.4,
        )


class SideSheetElement(_PaddedFlex):
    """M3 side sheet: 400dp max width, full height, 16dp leading corners.

    From `COMPONENT_SIDE_SHEETS.md`: `surface_container_low`, 24dp start/end
    padding, 400dp max width, 16dp corner radius. Which corners round depends
    on the edge it is docked to, taken from `placement:` -- a right-hand sheet
    rounds its left corners and vice versa.
    """

    RADIUS: Final = 16.0
    MAX_WIDTH: Final = 400.0
    PADDING: Final = 24.0
    INSETS: ClassVar[EdgeInsets] = EdgeInsets.all(PADDING)
    DEFAULT_PLACEMENT = "right"
    DOCKED = True
    axis = Axis.VERTICAL

    @property
    def effective_radii(self) -> tuple[float, float, float, float]:
        radii = self.style.corner_radius
        if any(radii):
            return radii
        r = self.RADIUS
        # Round only the edge that faces into the window.
        if self.resolved_placement == "left":
            return (0.0, r, r, 0.0)
        return (r, 0.0, 0.0, r)

    def perform_layout(self, constraints: Constraints) -> Size:
        style = self.style
        width = _clamped_width(
            constraints, style, minimum=0.0, maximum=self.MAX_WIDTH, unbounded=self.MAX_WIDTH
        )
        height = (
            float(style.height.value)
            if style.height.kind == "fixed"
            else (constraints.max_height if constraints.has_bounded_height else 0.0)
        )
        inner = constraints.copy_with(min_width=width, max_width=width)
        if height:
            inner = inner.copy_with(min_height=height, max_height=height)
        return super().perform_layout(inner)

    def paint_self(self, ctx: PaintContext, absolute: Any) -> None:
        _surface(
            ctx,
            absolute,
            self.size,
            token=ctx.palette.index(self.style.background or "surface_container_low"),
            radii=self.effective_radii,
        )

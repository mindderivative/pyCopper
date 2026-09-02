"""Material Design 3 components.

Each class translates one M3 spec into pyCopper's element model. Dimensions are
M3's own dp figures used directly, since layout runs in logical units and dp
maps 1:1 (ARCHITECTURE.md 7). Colours are palette **tokens**, never literals,
so a theme switch stays a single buffer upload.

Where pyCopper cannot express part of a spec, the class says so rather than
quietly approximating.

**pyCopper is a desktop framework and does not target touch.** M3's 48x48dp
minimum touch target is a finger-precision requirement; a mouse pointer is
precise to the pixel, so hit rects deliberately match the painted control.
Desktop affordances M3 treats as secondary -- hover, focus rings, keyboard
traversal, right-click -- matter correspondingly more.
"""

from __future__ import annotations

from typing import Any, Final

from ..layout import Constraints, EdgeInsets, Padding, Size
from ..spec import StyleSpec, WidgetSpec
from ..text.icons import DEFAULT_ICON_SIZE
from ..tree.element import PaintContext
from .base import _StyledMixin, content_token, measure_text, paint_text

__all__ = [
    "BadgeElement",
    "CardElement",
    "CheckboxElement",
    "ChipElement",
    "DividerElement",
    "FabElement",
    "IconButtonElement",
    "RadioElement",
    "SwitchElement",
]

#: M3 state-layer opacities (M3_COMPONENT_SPECS.md §0).
HOVER: Final = 0.08
FOCUS: Final = 0.10
PRESS: Final = 0.10


#: "Selection controls have a short duration of 200ms with Standard easing"
#: -- M3 states this outright, and it covers the whole family: checkbox, radio,
#: switch, and the filter chip's checkmark.
SELECTION_MOTION: Final = "short4"
SELECTION_CURVE: Final = "standard"

#: State layers cross-fade rather than snapping. **Not sourced** -- M3 gives no
#: duration for a state layer, and the "begin and end on screen" pair (Standard,
#: 300ms) is about elements arriving, not an in-place emphasis change. 100ms is
#: chosen because a hover response slower than that reads as lag.
STATE_LAYER_MOTION: Final = "short2"
STATE_LAYER_CURVE: Final = "standard"


def _state_alpha(element: Any) -> float:
    """State-layer opacity for the element's current interaction state.

    Animated, so a hover fades in and out instead of blinking. Every component
    that emits a state layer gets this from one place -- which is the whole
    reason `_emit_state_layer` is shared.
    """
    if element.state.pressed:
        target = PRESS
    elif element.state.focused:
        target = FOCUS
    elif element.state.hovered:
        target = HOVER
    else:
        target = 0.0
    alpha: float = element.animated(
        "state_layer", target, duration=STATE_LAYER_MOTION, curve=STATE_LAYER_CURVE
    )
    return alpha


def _emit_state_layer(
    ctx: PaintContext,
    element: Any,
    absolute: Any,
    token: int,
    radii: tuple[float, float, float, float],
) -> None:
    """M3 state layer: a tinted overlay above the container, below the content."""
    alpha = _state_alpha(element)
    if alpha <= 0.001:
        # Below this the layer is invisible; emitting it would cost an instance
        # a frame for nothing, and the fade-out has effectively landed.
        return
    dpr = ctx.pixel_ratio
    ctx.display_list.add_box(
        absolute.x * dpr,
        absolute.y * dpr,
        element.size.width * dpr,
        element.size.height * dpr,
        token=token,
        color=(1.0, 1.0, 1.0, alpha),
        radii=tuple(r * dpr for r in radii),  # type: ignore[arg-type]
        clip=ctx.clip,
        clip_radii=ctx.clip_radii,
    )


def _box(
    ctx: PaintContext,
    x: float,
    y: float,
    w: float,
    h: float,
    *,
    token: int,
    radius: float,
    alpha: float = 1.0,
    border_width: float = 0.0,
    border_token: int | None = None,
    border_alpha: float = 1.0,
) -> None:
    """Emit one token-coloured rounded box in logical coordinates."""
    from ..paint import NO_TOKEN

    dpr = ctx.pixel_ratio
    ctx.display_list.add_box(
        x * dpr,
        y * dpr,
        w * dpr,
        h * dpr,
        token=token,
        color=(1.0, 1.0, 1.0, alpha),
        radii=(radius * dpr,) * 4,
        border_width=border_width * dpr,
        border_token=NO_TOKEN if border_token is None else border_token,
        border_color=(1.0, 1.0, 1.0, border_alpha),
        clip=ctx.clip,
        clip_radii=ctx.clip_radii,
    )


def _arc(
    ctx: PaintContext,
    x: float,
    y: float,
    w: float,
    h: float,
    *,
    token: int,
    thickness: float,
    start: float,
    sweep: float,
    alpha: float = 1.0,
) -> None:
    """Emit one token-coloured stroked arc in logical coordinates.

    Angles are radians clockwise from 12 o'clock, which is the direction M3
    specifies for circular progress.
    """
    dpr = ctx.pixel_ratio
    ctx.display_list.add_arc(
        x * dpr,
        y * dpr,
        w * dpr,
        h * dpr,
        thickness=thickness * dpr,
        start=start,
        sweep=sweep,
        token=token,
        color=(1.0, 1.0, 1.0, alpha),
        clip=ctx.clip,
        clip_radii=ctx.clip_radii,
    )


#: M3's six elevation levels and their dp heights, quoted from
#: `styles/M3-Styles-Elevation-Tokens.md`. Levels 0-3 are resting states;
#: "+4 and +5 are reserved for user-interacted states such as hover and
#: dragged".
ELEVATION_DP: Final = {0: 0.0, 1: 1.0, 2: 3.0, 3: 6.0, 4: 8.0, 5: 12.0}

#: Turning a dp height into a shadow. **Not sourced** -- the spec describes the
#: relationship ("larger, softer shadows express more distance") and shows it in
#: images, without giving blur or offset figures. The constants are anchored on
#: the value the Card already used for level 1, so the family scales out from a
#: shape that was already reviewed rather than from an invention.
SHADOW_BASE_BLUR: Final = 4.0
SHADOW_BLUR_PER_DP: Final = 2.0
SHADOW_OPACITY: Final = 0.30


def elevation_shadow(
    ctx: PaintContext,
    x: float,
    y: float,
    w: float,
    h: float,
    *,
    level: int,
    radii: tuple[float, float, float, float],
) -> None:
    """Emit the shadow for an M3 elevation level. Level 0 draws nothing.

    Shared rather than hand-tuned per widget: three components had their own
    blur values, so a dialog and a FAB at the same M3 level did not look like
    they were at the same height.
    """
    dp = ELEVATION_DP.get(level, 0.0)
    if dp <= 0.0:
        return
    dpr = ctx.pixel_ratio
    ctx.display_list.add_shadow(
        x * dpr,
        y * dpr,
        w * dpr,
        h * dpr,
        blur=(SHADOW_BASE_BLUR + dp * SHADOW_BLUR_PER_DP) * dpr,
        offset=(0.0, dp * dpr),
        color=(0.0, 0.0, 0.0, SHADOW_OPACITY),
        radii=tuple(r * dpr for r in radii),  # type: ignore[arg-type]
        clip=ctx.clip,
        clip_radii=ctx.clip_radii,
    )


# ------------------------------------------------------------------- cards


class CardElement(_StyledMixin, Padding):
    """M3 Card: 12dp radius, 16dp padding, three variants.

    Elevated is level 1, filled uses `surface_container_highest`, outlined uses
    `surface` with a 1dp `outline_variant` border. Elevation is approximated by
    shadow alone -- the tonal surface shift M3 also specifies is not modelled.
    """

    RADIUS: Final = 12.0
    PADDING: Final = 16.0
    #: M3 resting levels: "Card (elevated)" is level 1; filled and outlined
    #: cards are level 0. The level therefore depends on the variant.
    ELEVATED_LEVEL: Final = 1

    @property
    def resting_elevation(self) -> int:
        return self.ELEVATED_LEVEL if self.style.variant == "elevated" else 0

    CONTAINERS: Final = {
        "elevated": "surface_container_low",
        "filled": "surface_container_highest",
        "outlined": "surface",
    }

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
        return pad if pad != EdgeInsets() else EdgeInsets.all(CardElement.PADDING)

    def configure(self) -> None:
        self._padding = self._insets(self.style)

    def perform_layout(self, constraints: Constraints) -> Size:
        outer = self.sized(constraints, self.style)
        inner = super().perform_layout(outer.loosen() if not outer.is_tight else outer)
        return outer.constrain(inner)

    def paint_self(self, ctx: PaintContext, absolute: Any) -> None:
        style = self.style
        variant = style.variant if style.variant in self.CONTAINERS else "filled"
        radius = style.corner_radius[0] or self.RADIUS
        container = ctx.palette.index(style.background or self.CONTAINERS[variant])

        if variant == "elevated":
            elevation_shadow(
                ctx,
                absolute.x,
                absolute.y,
                self.size.width,
                self.size.height,
                # Not `or ELEVATED_LEVEL`: an explicit `elevation: 0` is an
                # override, and `or` cannot tell zero from unset.
                level=self.elevation,
                radii=(radius,) * 4,
            )
        _box(
            ctx,
            absolute.x,
            absolute.y,
            self.size.width,
            self.size.height,
            token=container,
            radius=radius,
            border_width=1.0 if variant == "outlined" else 0.0,
            border_token=ctx.palette.index("outline_variant"),
        )


# ---------------------------------------------------------------- dividers


class DividerElement(_StyledMixin, Padding):
    """M3 Divider: 1dp of `outline_variant`, full-bleed or inset."""

    def __init__(self, spec: WidgetSpec) -> None:
        Padding.__init__(self, None, EdgeInsets())
        self.init_element(spec)

    def perform_layout(self, constraints: Constraints) -> Size:
        outer = self.sized(constraints, self.style)
        width = outer.max_width if outer.has_bounded_width else 0.0
        return outer.constrain(Size(width, self.style.thickness))

    def paint_self(self, ctx: PaintContext, absolute: Any) -> None:
        style = self.style
        inset = style.inset if style.variant == "inset" else 0.0
        _box(
            ctx,
            absolute.x + inset,
            absolute.y,
            max(0.0, self.size.width - inset),
            style.thickness,
            token=ctx.palette.index(style.background or "outline_variant"),
            radius=0.0,
        )


# -------------------------------------------------------- selection controls


class CheckboxElement(_StyledMixin, Padding):
    """M3 Checkbox: 18dp box, 2dp radius, checkmark when selected.

    Hit-tested at its 18dp visual size: M3's 48dp touch target is a
    finger-precision rule and does not apply to a pointer.
    """

    BOX: Final = 18.0
    RADIUS: Final = 2.0
    CURSOR = "pointer"

    @property
    def effective_radii(self) -> tuple[float, float, float, float]:
        return (self.RADIUS,) * 4

    def __init__(self, spec: WidgetSpec) -> None:
        Padding.__init__(self, None, EdgeInsets())
        self.init_element(spec)

    def perform_layout(self, constraints: Constraints) -> Size:
        return self.sized(constraints, self.style).constrain(Size(self.BOX, self.BOX))

    def paint_self(self, ctx: PaintContext, absolute: Any) -> None:
        selected = self.checked
        outline = ctx.palette.index("on_surface_variant")
        primary = ctx.palette.index(self.style.background or "primary")
        on_primary = content_token(ctx, self.style, "on_primary")

        _emit_state_layer(ctx, self, absolute, primary, (self.RADIUS,) * 4)
        t = self.animated(
            "selected",
            1.0 if selected else 0.0,
            duration=SELECTION_MOTION,
            curve=SELECTION_CURVE,
        )
        # Empty outline fading out, filled container fading in. Two instances
        # only while in flight -- at either end one of them is skipped.
        if t < 1.0:
            _box(
                ctx,
                absolute.x,
                absolute.y,
                self.BOX,
                self.BOX,
                token=outline,
                radius=self.RADIUS,
                alpha=0.0,
                border_width=2.0,
                border_token=outline,
                border_alpha=1.0 - t,
            )
        if t > 0.0:
            _box(
                ctx,
                absolute.x,
                absolute.y,
                self.BOX,
                self.BOX,
                token=primary,
                radius=self.RADIUS,
                alpha=t,
            )
            # M3 draws the checkmark on; a glyph cannot be drawn progressively,
            # so it fades -- an approximation, and the honest one available.
            ctx.text.emit_icon(
                ctx.display_list,
                "check",
                x=absolute.x,
                y=absolute.y,
                size=self.BOX,
                weight=500,
                pixel_ratio=ctx.pixel_ratio,
                token=on_primary,
                color=(1.0, 1.0, 1.0, t),
                clip=ctx.clip,
                clip_radii=ctx.clip_radii,
            )


class RadioElement(_StyledMixin, Padding):
    """M3 Radio: 20dp outer circle, 10dp inner dot when selected."""

    OUTER: Final = 20.0
    INNER: Final = 10.0
    CURSOR = "pointer"

    @property
    def effective_radii(self) -> tuple[float, float, float, float]:
        return (self.OUTER / 2,) * 4

    def __init__(self, spec: WidgetSpec) -> None:
        Padding.__init__(self, None, EdgeInsets())
        self.init_element(spec)

    def perform_layout(self, constraints: Constraints) -> Size:
        return self.sized(constraints, self.style).constrain(Size(self.OUTER, self.OUTER))

    def paint_self(self, ctx: PaintContext, absolute: Any) -> None:
        selected = self.checked
        active = ctx.palette.index(self.style.background or "primary")
        inactive = ctx.palette.index("on_surface_variant")
        ring = active if selected else inactive
        _emit_state_layer(ctx, self, absolute, ring, (self.OUTER / 2,) * 4)

        t = self.animated(
            "selected",
            1.0 if selected else 0.0,
            duration=SELECTION_MOTION,
            curve=SELECTION_CURVE,
        )
        # A circle is a rounded box with radius = half the side. Tokens cannot
        # be interpolated -- the palette is resolved in the shader -- so the
        # ring colour is cross-faded by drawing both rings instead.
        for token, weight in ((inactive, 1.0 - t), (active, t)):
            if weight > 0.0:
                _box(
                    ctx,
                    absolute.x,
                    absolute.y,
                    self.OUTER,
                    self.OUTER,
                    token=token,
                    radius=self.OUTER / 2,
                    alpha=0.0,
                    border_width=2.0,
                    border_token=token,
                    border_alpha=weight,
                )
        # The dot grows out of the centre rather than appearing whole.
        inner = self.INNER * t
        if inner > 0.5:
            pad = (self.OUTER - inner) / 2
            _box(
                ctx,
                absolute.x + pad,
                absolute.y + pad,
                inner,
                inner,
                token=active,
                radius=inner / 2,
            )


class SwitchElement(_StyledMixin, Padding):
    """M3 Switch: 52x32dp track; thumb 16dp unselected, 24dp selected.

    The thumb slides and grows rather than jumping. M3 states the timing for
    this directly -- "Selection controls have a short duration of 200ms with
    Standard easing" -- so it is `short4` and `standard`, not a guess.

    Position and size animate on separate curves-in-name-only (both are the
    same token) but as separate values, because they travel different
    distances and interrupting one must not disturb the other.
    """

    TRACK_W: Final = 52.0
    TRACK_H: Final = 32.0
    CURSOR = "pointer"
    THUMB_OFF: Final = 16.0
    THUMB_ON: Final = 24.0
    MOTION: Final = SELECTION_MOTION
    CURVE: Final = SELECTION_CURVE

    @property
    def effective_radii(self) -> tuple[float, float, float, float]:
        return (self.TRACK_H / 2,) * 4

    def __init__(self, spec: WidgetSpec) -> None:
        Padding.__init__(self, None, EdgeInsets())
        self.init_element(spec)

    def perform_layout(self, constraints: Constraints) -> Size:
        return self.sized(constraints, self.style).constrain(Size(self.TRACK_W, self.TRACK_H))

    def paint_self(self, ctx: PaintContext, absolute: Any) -> None:
        on = self.checked
        track = ctx.palette.index(
            (self.style.background or "primary") if on else "surface_container_highest"
        )
        thumb = ctx.palette.index("on_primary" if on else "outline")
        radius = self.TRACK_H / 2

        _box(
            ctx,
            absolute.x,
            absolute.y,
            self.TRACK_W,
            self.TRACK_H,
            token=track,
            radius=radius,
            border_width=0.0 if on else 2.0,
            border_token=ctx.palette.index("outline"),
        )
        _emit_state_layer(ctx, self, absolute, track, (radius,) * 4)

        size = self.animated(
            "thumb_size",
            self.THUMB_ON if on else self.THUMB_OFF,
            duration=self.MOTION,
            curve=self.CURVE,
        )
        # Travel is expressed as 0..1 and mapped to pixels afterwards, so the
        # thumb keeps ending flush with the track however its size animates.
        travel = self.animated(
            "thumb_pos", 1.0 if on else 0.0, duration=self.MOTION, curve=self.CURVE
        )
        margin = (self.TRACK_H - size) / 2
        x = absolute.x + margin + (self.TRACK_W - size - margin * 2) * travel
        _box(ctx, x, absolute.y + margin, size, size, token=thumb, radius=size / 2)


# ------------------------------------------------------------------- chips


class ChipElement(_StyledMixin, Padding):
    """M3 Chip: 32dp high, 8dp radius, 1dp outline, optional 18dp leading icon.

    A filter chip shows a leading checkmark when selected, which is what the
    `value:` binding drives.
    """

    HEIGHT: Final = 32.0
    RADIUS: Final = 8.0
    ICON: Final = 18.0
    CURSOR = "pointer"
    GAP: Final = 6.0
    PAD_X: Final = 12.0

    @property
    def effective_radii(self) -> tuple[float, float, float, float]:
        return (self.RADIUS,) * 4

    def __init__(self, spec: WidgetSpec) -> None:
        Padding.__init__(self, None, EdgeInsets())
        self.init_element(spec)

    @property
    def _is_filter(self) -> bool:
        return self.style.variant == "filter"

    @property
    def _leading(self) -> str:
        return "check" if self._is_filter and self.checked else ""

    def _check_progress(self) -> float:
        """How far the leading checkmark has slid in, 0 to 1.

        This changes the chip's **width**, so it invalidates layout rather than
        paint -- the label and every sibling in the row move with it, which is
        the behaviour M3 describes. A chip row is a handful of elements, so the
        relayout is affordable; see the Carousel (5.16) for the same trade.
        """
        if not self._is_filter:
            return 0.0
        value: float = self.animated(
            "selected",
            1.0 if self.checked else 0.0,
            duration=SELECTION_MOTION,
            curve=SELECTION_CURVE,
            invalidates="layout",
        )
        return value

    def perform_layout(self, constraints: Constraints) -> Size:
        style = self.style
        label = measure_text(self._text, style.font_size, engine=self.text_engine)
        width = self.PAD_X * 2 + label.width + (self.ICON + self.GAP) * self._check_progress()
        return self.sized(constraints, style).constrain(Size(width, self.HEIGHT))

    def paint_self(self, ctx: PaintContext, absolute: Any) -> None:
        style = self.style
        selected = self._is_filter and self.checked
        t = self._check_progress()
        content = style.color or ("on_secondary_container" if selected else "on_surface_variant")
        content_tok = ctx.palette.index(content)

        containers: tuple[tuple[int, float], ...]
        if style.background:
            containers = ((ctx.palette.index(style.background), 1.0),)
        else:
            # Cross-fade the container the same way as the Radio's ring: the
            # palette is resolved in the shader, so two boxes, not one lerp.
            containers = (
                (ctx.palette.index("surface"), 1.0 - t),
                (ctx.palette.index("secondary_container"), t),
            )
        for token, weight in containers:
            if weight <= 0.0:
                continue
            # The outline belongs to the unselected chip and fades with it. The
            # width must drop to zero as well, not just the alpha: the shader
            # insets the fill by the border width, so a fully transparent 1dp
            # border would leave a transparent ring where the fill should reach.
            border_alpha = (1.0 - t) * weight
            _box(
                ctx,
                absolute.x,
                absolute.y,
                self.size.width,
                self.size.height,
                token=token,
                radius=self.RADIUS,
                alpha=weight,
                border_width=1.0 if border_alpha > 0.0 else 0.0,
                border_token=ctx.palette.index("outline_variant"),
                border_alpha=border_alpha,
            )
        _emit_state_layer(ctx, self, absolute, content_tok, (self.RADIUS,) * 4)

        x = absolute.x + self.PAD_X
        if t > 0.0:
            # The checkmark grows into the space being made for it. Drawn at
            # full size it would overlap the label, which has only travelled a
            # fraction of the way -- visible as "check-Filter" mid-transition.
            icon = self.ICON * t
            ctx.text.emit_icon(
                ctx.display_list,
                "check",
                x=x,
                y=absolute.y + (self.HEIGHT - icon) / 2,
                size=icon,
                pixel_ratio=ctx.pixel_ratio,
                token=content_tok,
                color=(1.0, 1.0, 1.0, t),
                clip=ctx.clip,
                clip_radii=ctx.clip_radii,
            )
            x += (self.ICON + self.GAP) * t
        if self._text.strip():
            label = measure_text(self._text, style.font_size, engine=self.text_engine)
            paint_text(
                ctx,
                x,
                absolute.y + (self.HEIGHT - label.height) / 2,
                self._text,
                style.font_size,
                content_tok,
            )


# ------------------------------------------------------------- icon buttons


class IconButtonElement(_StyledMixin, Padding):
    """M3 Icon Button: 40dp container, 24dp icon, full radius, four variants."""

    SIZE: Final = 40.0

    #: variant -> (container token or None for uncontained, content token)
    VARIANTS: Final = {
        "standard": (None, "on_surface_variant"),
        "filled": ("primary", "on_primary"),
        "filled_tonal": ("secondary_container", "on_secondary_container"),
        "outlined": (None, "on_surface_variant"),
    }

    @property
    def effective_radii(self) -> tuple[float, float, float, float]:
        return (self.size.height / 2,) * 4

    def __init__(self, spec: WidgetSpec) -> None:
        Padding.__init__(self, None, EdgeInsets())
        self.init_element(spec)

    def perform_layout(self, constraints: Constraints) -> Size:
        return self.sized(constraints, self.style).constrain(Size(self.SIZE, self.SIZE))

    def paint_self(self, ctx: PaintContext, absolute: Any) -> None:
        style = self.style
        variant = style.variant if style.variant in self.VARIANTS else "standard"
        container, content = self.VARIANTS[variant]
        radius = self.size.height / 2
        content_tok = ctx.palette.index(style.color or content)

        if style.background or container:
            _box(
                ctx,
                absolute.x,
                absolute.y,
                self.size.width,
                self.size.height,
                token=ctx.palette.index(style.background or container or "primary"),
                radius=radius,
            )
        if variant == "outlined":
            _box(
                ctx,
                absolute.x,
                absolute.y,
                self.size.width,
                self.size.height,
                token=ctx.palette.index("outline"),
                radius=radius,
                alpha=0.0,
                border_width=1.0,
                border_token=ctx.palette.index("outline"),
            )

        _emit_state_layer(ctx, self, absolute, content_tok, (radius,) * 4)

        icon = style.icon_size or DEFAULT_ICON_SIZE
        if self._text.strip():
            ctx.text.emit_icon(
                ctx.display_list,
                self._text.strip(),
                x=absolute.x + (self.size.width - icon) / 2,
                y=absolute.y + (self.size.height - icon) / 2,
                size=icon,
                fill=style.icon_fill,
                weight=style.icon_weight,
                pixel_ratio=ctx.pixel_ratio,
                token=content_tok,
                clip=ctx.clip,
                clip_radii=ctx.clip_radii,
            )


class FabElement(_StyledMixin, Padding):
    """M3 FAB: standard 56dp/16dp radius, small 40/12, large 96/28 with a 36dp icon.

    Defaults to `primary_container` on `on_primary_container`, M3's default
    colour mapping. M3 puts a FAB at resting **level 3**, alongside modal
    dialogs -- the highest resting level any component uses.
    """

    RESTING_ELEVATION = 3

    #: variant -> (container size, corner radius, icon size)
    SIZES: Final = {
        "small": (40.0, 12.0, 24.0),
        "standard": (56.0, 16.0, 24.0),
        "medium": (80.0, 20.0, 28.0),
        "large": (96.0, 28.0, 36.0),
    }

    @property
    def effective_radii(self) -> tuple[float, float, float, float]:
        return (self._geometry()[1],) * 4

    def __init__(self, spec: WidgetSpec) -> None:
        Padding.__init__(self, None, EdgeInsets())
        self.init_element(spec)

    def _geometry(self) -> tuple[float, float, float]:
        variant = self.style.variant
        return self.SIZES.get(variant, self.SIZES["standard"])

    def perform_layout(self, constraints: Constraints) -> Size:
        size, _, _ = self._geometry()
        return self.sized(constraints, self.style).constrain(Size(size, size))

    def paint_self(self, ctx: PaintContext, absolute: Any) -> None:
        style = self.style
        _, radius, icon = self._geometry()
        container = ctx.palette.index(style.background or "primary_container")
        content = content_token(ctx, style, "on_primary_container")

        # Elevation level 3, shadow only -- the tonal half is not modelled.
        elevation_shadow(
            ctx,
            absolute.x,
            absolute.y,
            self.size.width,
            self.size.height,
            level=self.elevation,
            radii=(radius,) * 4,
        )
        _box(
            ctx,
            absolute.x,
            absolute.y,
            self.size.width,
            self.size.height,
            token=container,
            radius=radius,
        )
        _emit_state_layer(ctx, self, absolute, content, (radius,) * 4)

        if self._text.strip():
            ctx.text.emit_icon(
                ctx.display_list,
                self._text.strip(),
                x=absolute.x + (self.size.width - icon) / 2,
                y=absolute.y + (self.size.height - icon) / 2,
                size=icon,
                fill=style.icon_fill,
                weight=style.icon_weight,
                pixel_ratio=ctx.pixel_ratio,
                token=content,
                clip=ctx.clip,
                clip_radii=ctx.clip_radii,
            )


# ------------------------------------------------------------------ badges


class BadgeElement(_StyledMixin, Padding):
    """M3 Badge: a 6dp dot, or a 16dp-high numbered pill with 4dp padding.

    `value:` carries the count, so it tracks a signal.
    """

    DOT: Final = 6.0
    HEIGHT: Final = 16.0
    PAD_X: Final = 4.0
    LABEL_SIZE: Final = 11.0

    @property
    def effective_radii(self) -> tuple[float, float, float, float]:
        return (self.size.height / 2,) * 4

    def __init__(self, spec: WidgetSpec) -> None:
        Padding.__init__(self, None, EdgeInsets())
        self.init_element(spec)

    @property
    def _label(self) -> str:
        return self._value.strip() or self._text.strip()

    @property
    def _is_dot(self) -> bool:
        return self.style.variant == "dot" or not self._label

    def perform_layout(self, constraints: Constraints) -> Size:
        outer = self.sized(constraints, self.style)
        if self._is_dot:
            return outer.constrain(Size(self.DOT, self.DOT))
        label = measure_text(self._label, self.LABEL_SIZE, engine=self.text_engine)
        width = max(self.HEIGHT, label.width + self.PAD_X * 2)
        return outer.constrain(Size(width, self.HEIGHT))

    def paint_self(self, ctx: PaintContext, absolute: Any) -> None:
        style = self.style
        container = ctx.palette.index(style.background or "error")
        content = content_token(ctx, style, "on_error")
        radius = self.size.height / 2

        _box(
            ctx,
            absolute.x,
            absolute.y,
            self.size.width,
            self.size.height,
            token=container,
            radius=radius,
        )
        if self._is_dot:
            return
        label = measure_text(self._label, self.LABEL_SIZE, engine=self.text_engine)
        paint_text(
            ctx,
            absolute.x + (self.size.width - label.width) / 2,
            absolute.y + (self.size.height - label.height) / 2,
            self._label,
            self.LABEL_SIZE,
            content,
        )

"""Material Design 3 navigation, app bar, tabs, lists, and progress.

Four of these -- NavigationRail, NavigationDrawer, Tabs, SegmentedButton --
share one shape: a container of items where exactly one is selected. That is
modelled once here:

* the container carries ``value:``, the id of the selected child;
* during layout it calls ``set_selected`` on each child;
* the item renders its own selected appearance and reads the icon FILL axis
  from it, which is precisely what M3 uses FILL for.

**Bottom-anchored navigation is deliberately absent.** M3's Navigation Bar and
Bottom App Bar are mobile patterns; the rail and drawer are their desktop
counterparts (ARCHITECTURE.md 1.2.1).
"""

from __future__ import annotations

import math
from typing import Any, Final

from ..layout import (
    Axis,
    Constraints,
    EdgeInsets,
    Flex,
    MainAxisSize,
    Padding,
    Size,
)
from ..spec import WidgetSpec
from ..tree.element import PaintContext
from .base import _StyledMixin, content_token, measure_text, paint_text
from .material import _arc, _box, _emit_state_layer

__all__ = [
    "CircularProgressElement",
    "LinearProgressElement",
    "ListItemElement",
    "NavItemElement",
    "NavigationDrawerElement",
    "NavigationRailElement",
    "SegmentElement",
    "SegmentedButtonElement",
    "TabElement",
    "TabsElement",
    "TopAppBarElement",
]

LABEL_SIZE: Final = 12.0
TITLE_SIZE: Final = 22.0
TAB_LABEL_SIZE: Final = 14.0
ICON: Final = 24.0

#: One full turn, for the circular progress sweep.
TAU: Final = 2.0 * math.pi


class _SelectionContainer(_StyledMixin, Flex):
    """A Flex whose ``value:`` names the selected child by id."""

    axis: Axis = Axis.HORIZONTAL

    def __init__(self, spec: WidgetSpec) -> None:
        Flex.__init__(self, axis=self.axis, spacing=spec.style.spacing)
        self.init_element(spec)

    def configure(self) -> None:
        self._spacing = self.style.spacing

    def apply_selection(self) -> None:
        """Push the selected id down to the children. Called before layout."""
        active = self._value.strip()
        for child in self.children:
            if hasattr(child, "set_selected"):
                child.set_selected(bool(active) and child.name == active)

    def perform_layout(self, constraints: Constraints) -> Size:
        self.apply_selection()
        return super().perform_layout(constraints)

    def selected_child(self) -> Any | None:
        return next((c for c in self.children if getattr(c, "selected", False)), None)


# --------------------------------------------------------- navigation rail


class NavItemElement(_StyledMixin, Padding):
    """One destination in a rail or drawer.

    `text:` is the icon name and `supporting_text` the label. The icon's FILL
    axis goes to 1 when selected -- M3's own mechanism for expressing
    selection, rather than swapping to a different icon.
    """

    RAIL_W: Final = 80.0
    RAIL_H: Final = 56.0
    INDICATOR_W: Final = 56.0
    INDICATOR_H: Final = 32.0
    DRAWER_H: Final = 56.0
    DRAWER_RADIUS: Final = 28.0
    DRAWER_PAD: Final = 16.0

    def __init__(self, spec: WidgetSpec) -> None:
        Padding.__init__(self, None, EdgeInsets())
        self.init_element(spec)

    @property
    def _in_drawer(self) -> bool:
        return isinstance(self.parent, NavigationDrawerElement)

    @property
    def effective_radii(self) -> tuple[float, float, float, float]:
        return (self.DRAWER_RADIUS,) * 4 if self._in_drawer else (self.INDICATOR_H / 2,) * 4

    def perform_layout(self, constraints: Constraints) -> Size:
        outer = self.sized(constraints, self.style)
        if self._in_drawer:
            width = outer.max_width if outer.has_bounded_width else 240.0
            return outer.constrain(Size(width, self.DRAWER_H))
        label = self._label_height()
        return outer.constrain(Size(self.RAIL_W, self.INDICATOR_H + label + 4.0))

    def _label_height(self) -> float:
        if not (self._supporting).strip():
            return 0.0
        return measure_text(self._supporting, LABEL_SIZE, engine=self.text_engine).height

    def paint_self(self, ctx: PaintContext, absolute: Any) -> None:
        selected = self.selected
        size = self.size
        active_bg = ctx.palette.index("secondary_container")
        content = content_token(
            ctx,
            self.style,
            "on_secondary_container" if selected else "on_surface_variant",
        )
        label_text = (self._supporting).strip()

        if self._in_drawer:
            if selected:
                _box(
                    ctx,
                    absolute.x,
                    absolute.y,
                    size.width,
                    size.height,
                    token=active_bg,
                    radius=self.DRAWER_RADIUS,
                )
            _emit_state_layer(ctx, self, absolute, content, self.effective_radii)
            x = absolute.x + self.DRAWER_PAD
            if self._text.strip():
                ctx.text.emit_icon(
                    ctx.display_list,
                    self._text.strip(),
                    x=x,
                    y=absolute.y + (size.height - ICON) / 2,
                    size=ICON,
                    fill=1.0 if selected else 0.0,
                    pixel_ratio=ctx.pixel_ratio,
                    token=content,
                    clip=ctx.clip,
                    clip_radii=ctx.clip_radii,
                )
                x += ICON + 12.0
            if label_text:
                label = measure_text(label_text, 14.0, engine=self.text_engine)
                paint_text(
                    ctx, x, absolute.y + (size.height - label.height) / 2, label_text, 14.0, content
                )
            return

        # Rail: a 56x32dp indicator pill behind the icon, label beneath.
        ind_x = absolute.x + (size.width - self.INDICATOR_W) / 2
        if selected:
            _box(
                ctx,
                ind_x,
                absolute.y,
                self.INDICATOR_W,
                self.INDICATOR_H,
                token=active_bg,
                radius=self.INDICATOR_H / 2,
            )
        _emit_state_layer(ctx, self, absolute, content, self.effective_radii)
        if self._text.strip():
            ctx.text.emit_icon(
                ctx.display_list,
                self._text.strip(),
                x=absolute.x + (size.width - ICON) / 2,
                y=absolute.y + (self.INDICATOR_H - ICON) / 2,
                size=ICON,
                fill=1.0 if selected else 0.0,
                pixel_ratio=ctx.pixel_ratio,
                token=content,
                clip=ctx.clip,
                clip_radii=ctx.clip_radii,
            )
        if label_text:
            label = measure_text(label_text, LABEL_SIZE, engine=self.text_engine)
            paint_text(
                ctx,
                absolute.x + (size.width - label.width) / 2,
                absolute.y + self.INDICATOR_H + 4.0,
                label_text,
                LABEL_SIZE,
                content,
            )


class NavigationRailElement(_SelectionContainer):
    """M3 Navigation Rail: 80dp wide, vertical, 56x32dp active indicator."""

    WIDTH: Final = 80.0
    axis = Axis.VERTICAL

    def perform_layout(self, constraints: Constraints) -> Size:
        inner = constraints.copy_with(min_width=self.WIDTH, max_width=self.WIDTH)
        return super().perform_layout(inner)

    def paint_self(self, ctx: PaintContext, absolute: Any) -> None:
        _box(
            ctx,
            absolute.x,
            absolute.y,
            self.size.width,
            self.size.height,
            token=ctx.palette.index(self.style.background or "surface"),
            radius=0.0,
        )


class NavigationDrawerElement(_SelectionContainer):
    """M3 Navigation Drawer: 240-360dp wide, 56dp items, full-radius active pill."""

    DEFAULT_W: Final = 300.0
    MAX_W: Final = 360.0
    axis = Axis.VERTICAL

    def perform_layout(self, constraints: Constraints) -> Size:
        width = min(self.MAX_W, self.DEFAULT_W)
        w = _resolved_width(self.style, constraints, width)
        inner = constraints.copy_with(min_width=w, max_width=w)
        return super().perform_layout(inner)

    def paint_self(self, ctx: PaintContext, absolute: Any) -> None:
        _box(
            ctx,
            absolute.x,
            absolute.y,
            self.size.width,
            self.size.height,
            token=ctx.palette.index(self.style.background or "surface_container_low"),
            radius=0.0,
        )


def _resolved_width(style: Any, constraints: Constraints, default: float) -> float:
    if style.width.kind == "fixed":
        return float(style.width.value)
    if style.width.kind == "expand" and constraints.has_bounded_width:
        return constraints.max_width
    return default


# ------------------------------------------------------------- top app bar


class TopAppBarElement(_StyledMixin, Flex):
    """M3 Top App Bar: 64dp small/center-aligned, title-large.

    Only the collapsed forms are implemented; the medium and large variants
    expand on scroll (112dp/152dp), which needs the scroll system.
    """

    HEIGHT: Final = 64.0
    PAD: Final = 16.0

    def __init__(self, spec: WidgetSpec) -> None:
        Flex.__init__(self, axis=Axis.HORIZONTAL, spacing=spec.style.spacing or 8.0)
        self.init_element(spec)

    def configure(self) -> None:
        self._spacing = self.style.spacing or 8.0

    def perform_layout(self, constraints: Constraints) -> Size:
        outer = constraints.copy_with(min_height=self.HEIGHT, max_height=self.HEIGHT)
        size = super().perform_layout(outer)
        for child in self.children:
            child.offset = child.offset + EdgeInsets.all(self.PAD).top_left
        return size

    def paint_self(self, ctx: PaintContext, absolute: Any) -> None:
        style = self.style
        _box(
            ctx,
            absolute.x,
            absolute.y,
            self.size.width,
            self.size.height,
            token=ctx.palette.index(style.background or "surface"),
            radius=0.0,
        )
        title = self._text.strip()
        if not title:
            return
        token = content_token(ctx, style, "on_surface")
        size = style.font_size if style.font_size != 14.0 else TITLE_SIZE
        label = measure_text(title, size, engine=self.text_engine)
        x = (
            absolute.x + (self.size.width - label.width) / 2
            if style.variant == "center_aligned"
            else absolute.x + self.PAD
        )
        paint_text(ctx, x, absolute.y + (self.size.height - label.height) / 2, title, size, token)


# ------------------------------------------------------------------- tabs


class TabElement(_StyledMixin, Padding):
    """One tab. The active indicator is drawn by the parent Tabs container."""

    HEIGHT: Final = 48.0
    PAD_X: Final = 16.0

    def __init__(self, spec: WidgetSpec) -> None:
        Padding.__init__(self, None, EdgeInsets())
        self.init_element(spec)

    def perform_layout(self, constraints: Constraints) -> Size:
        label = measure_text(self._text, TAB_LABEL_SIZE, engine=self.text_engine)
        return self.sized(constraints, self.style).constrain(
            Size(label.width + self.PAD_X * 2, self.HEIGHT)
        )

    def paint_self(self, ctx: PaintContext, absolute: Any) -> None:
        token = content_token(ctx, self.style, "primary" if self.selected else "on_surface_variant")
        _emit_state_layer(ctx, self, absolute, token, (0.0,) * 4)
        if not self._text.strip():
            return
        label = measure_text(self._text, TAB_LABEL_SIZE, engine=self.text_engine)
        paint_text(
            ctx,
            absolute.x + (self.size.width - label.width) / 2,
            absolute.y + (self.size.height - label.height) / 2,
            self._text,
            TAB_LABEL_SIZE,
            token,
        )


class TabsElement(_SelectionContainer):
    """M3 Tabs: 48dp high, 3dp active indicator.

    Primary tabs anchor the indicator to the bottom edge with rounded top
    corners; secondary tabs use a flat full-width stroke.
    """

    HEIGHT: Final = 48.0
    INDICATOR_H: Final = 3.0
    axis = Axis.HORIZONTAL

    def perform_layout(self, constraints: Constraints) -> Size:
        inner = constraints.copy_with(min_height=self.HEIGHT, max_height=self.HEIGHT)
        return super().perform_layout(inner)

    def paint_self(self, ctx: PaintContext, absolute: Any) -> None:
        _box(
            ctx,
            absolute.x,
            absolute.y,
            self.size.width,
            self.size.height,
            token=ctx.palette.index(self.style.background or "surface"),
            radius=0.0,
        )
        active = self.selected_child()
        if active is None:
            return
        primary = self.style.variant != "secondary"
        y = absolute.y + self.size.height - self.INDICATOR_H
        _box(
            ctx,
            absolute.x + active.offset.x,
            y,
            active.size.width,
            self.INDICATOR_H,
            token=ctx.palette.index("primary"),
            radius=self.INDICATOR_H if primary else 0.0,
        )


# ------------------------------------------------------- segmented buttons


class SegmentElement(_StyledMixin, Padding):
    """One segment. Selected segments show a leading 18dp checkmark."""

    HEIGHT: Final = 40.0
    PAD_X: Final = 12.0
    CHECK: Final = 18.0
    GAP: Final = 6.0

    def __init__(self, spec: WidgetSpec) -> None:
        Padding.__init__(self, None, EdgeInsets())
        self.init_element(spec)

    def perform_layout(self, constraints: Constraints) -> Size:
        label = measure_text(self._text, TAB_LABEL_SIZE, engine=self.text_engine)
        width = label.width + self.PAD_X * 2
        if self.selected:
            width += self.CHECK + self.GAP
        return self.sized(constraints, self.style).constrain(Size(width, self.HEIGHT))

    def paint_self(self, ctx: PaintContext, absolute: Any) -> None:
        selected = self.selected
        token = content_token(
            ctx, self.style, "on_secondary_container" if selected else "on_surface"
        )
        if selected:
            _box(
                ctx,
                absolute.x,
                absolute.y,
                self.size.width,
                self.size.height,
                token=ctx.palette.index("secondary_container"),
                radius=0.0,
            )
        _emit_state_layer(ctx, self, absolute, token, (0.0,) * 4)

        x = absolute.x + self.PAD_X
        if selected:
            ctx.text.emit_icon(
                ctx.display_list,
                "check",
                x=x,
                y=absolute.y + (self.size.height - self.CHECK) / 2,
                size=self.CHECK,
                pixel_ratio=ctx.pixel_ratio,
                token=token,
                clip=ctx.clip,
                clip_radii=ctx.clip_radii,
            )
            x += self.CHECK + self.GAP
        if self._text.strip():
            label = measure_text(self._text, TAB_LABEL_SIZE, engine=self.text_engine)
            paint_text(
                ctx,
                x,
                absolute.y + (self.size.height - label.height) / 2,
                self._text,
                TAB_LABEL_SIZE,
                token,
            )


class SegmentedButtonElement(_SelectionContainer):
    """M3 Segmented Buttons: 40dp high, 1dp outline, 20dp outer corners.

    Internal segments share flat borders, so the outline is drawn once around
    the whole container plus a divider between each pair -- not per segment,
    which would double every internal edge.
    """

    HEIGHT: Final = 40.0
    RADIUS: Final = 20.0
    axis = Axis.HORIZONTAL

    @property
    def effective_radii(self) -> tuple[float, float, float, float]:
        return (self.RADIUS,) * 4

    @property
    def _stretches(self) -> bool:
        """True when the view gave the group a width to fill."""
        return self.style.width.kind in ("fixed", "expand", "percent")

    def flex_of(self, child: Any) -> int:
        """With an explicit width, segments divide it equally -- M3's stretched
        form. Without one the group shrinks to its content, so the outline
        never runs on past the last segment."""
        return 1 if self._stretches else super().flex_of(child)

    def perform_layout(self, constraints: Constraints) -> Size:
        inner = constraints.copy_with(min_height=self.HEIGHT, max_height=self.HEIGHT)
        self._main_size = MainAxisSize.MAX if self._stretches else MainAxisSize.MIN
        return super().perform_layout(inner)

    def child_paint_context(self, ctx: PaintContext, absolute: Any) -> PaintContext:
        """Clip segments to the rounded container so a selected end segment's
        square fill does not poke past the outline."""
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
            clip_radii=(self.RADIUS * dpr,) * 4,
        )

    def paint_self(self, ctx: PaintContext, absolute: Any) -> None:
        outline = ctx.palette.index("outline")
        _box(
            ctx,
            absolute.x,
            absolute.y,
            self.size.width,
            self.size.height,
            token=outline,
            radius=self.RADIUS,
            alpha=0.0,
            border_width=1.0,
            border_token=outline,
        )
        for child in list(self.children)[1:]:
            _box(
                ctx,
                absolute.x + child.offset.x,
                absolute.y,
                1.0,
                self.size.height,
                token=outline,
                radius=0.0,
            )


# ------------------------------------------------------------------ lists


class ListItemElement(_StyledMixin, Padding):
    """M3 List item: 56dp one-line, 72dp two-line, 88dp three-line.

    `text:` is the headline, `supporting_text` the second line, and an icon
    name in `style.background`-adjacent fields is not used -- a leading icon is
    given as a child Icon widget instead.
    """

    HEIGHTS: Final = {"one_line": 56.0, "two_line": 72.0, "three_line": 88.0}
    PAD_X: Final = 16.0
    HEADLINE: Final = 16.0
    SUPPORTING: Final = 14.0

    def __init__(self, spec: WidgetSpec) -> None:
        Padding.__init__(self, None, EdgeInsets())
        self.init_element(spec)

    def _height(self) -> float:
        variant = self.style.variant
        if variant in self.HEIGHTS:
            return self.HEIGHTS[variant]
        return 72.0 if (self._supporting).strip() else 56.0

    def perform_layout(self, constraints: Constraints) -> Size:
        outer = self.sized(constraints, self.style)
        width = outer.max_width if outer.has_bounded_width else 320.0
        return outer.constrain(Size(width, self._height()))

    def paint_self(self, ctx: PaintContext, absolute: Any) -> None:
        style = self.style
        headline = content_token(ctx, style, "on_surface")
        supporting = ctx.palette.index("on_surface_variant")
        if style.background:
            _box(
                ctx,
                absolute.x,
                absolute.y,
                self.size.width,
                self.size.height,
                token=ctx.palette.index(style.background),
                radius=0.0,
            )
        _emit_state_layer(ctx, self, absolute, headline, (0.0,) * 4)

        second = (self._supporting).strip()
        x = absolute.x + self.PAD_X
        if second:
            top = measure_text(self._text, self.HEADLINE, engine=self.text_engine)
            bottom = measure_text(second, self.SUPPORTING, engine=self.text_engine)
            block = top.height + bottom.height
            y = absolute.y + (self.size.height - block) / 2
            paint_text(ctx, x, y, self._text, self.HEADLINE, headline)
            paint_text(ctx, x, y + top.height, second, self.SUPPORTING, supporting)
        elif self._text.strip():
            label = measure_text(self._text, self.HEADLINE, engine=self.text_engine)
            paint_text(
                ctx,
                x,
                absolute.y + (self.size.height - label.height) / 2,
                self._text,
                self.HEADLINE,
                headline,
            )


# --------------------------------------------------------------- progress


class LinearProgressElement(_StyledMixin, Padding):
    """M3 Linear Progress: 4dp high with rounded ends.

    Determinate only -- `value:` is the fraction complete, 0 to 1. The
    indeterminate form is an animation and pyCopper has no motion system.

    Colour roles are shared with `CircularProgress`: active `primary`, track
    `secondary_container`. This widget originally used `surface_variant` for
    the track, which the spec does not say -- corrected when the circular
    variant was built and the two had to agree.
    """

    HEIGHT: Final = 4.0

    def __init__(self, spec: WidgetSpec) -> None:
        Padding.__init__(self, None, EdgeInsets())
        self.init_element(spec)

    @property
    def effective_radii(self) -> tuple[float, float, float, float]:
        return (self.HEIGHT / 2,) * 4

    @property
    def progress(self) -> float:
        return max(0.0, min(1.0, self.number))

    def perform_layout(self, constraints: Constraints) -> Size:
        outer = self.sized(constraints, self.style)
        width = outer.max_width if outer.has_bounded_width else 0.0
        return outer.constrain(Size(width, self.HEIGHT))

    def paint_self(self, ctx: PaintContext, absolute: Any) -> None:
        radius = self.HEIGHT / 2
        _box(
            ctx,
            absolute.x,
            absolute.y,
            self.size.width,
            self.size.height,
            token=ctx.palette.index(self.style.background or "secondary_container"),
            radius=radius,
        )
        filled = self.size.width * self.progress
        if filled > 0:
            _box(
                ctx,
                absolute.x,
                absolute.y,
                filled,
                self.size.height,
                token=content_token(ctx, self.style, "primary"),
                radius=radius,
            )


class CircularProgressElement(_StyledMixin, Padding):
    """M3 Circular Progress: a 4dp ring, filled clockwise from 12 o'clock.

    Determinate only -- `value:` is the fraction complete, 0 to 1. The
    indeterminate form is an animation and pyCopper has no motion system, the
    same reason `LinearProgress` is determinate only.

    Sourced from `COMPONENT_PROGRESS_INDICATORS.md`: "Track thickness: Fixed
    (4dp)", the shared colour roles (active `primary`, track
    `secondary_container`), and "circular indicators animate from the top of
    the track, clockwise by default" -- which is why angles here are measured
    clockwise from 12 o'clock rather than from the +X axis.

    The **48dp default diameter is not sourced**: that page's size table is an
    image, so the scrape carries no text for it. Set `width:` to override.
    """

    DIAMETER: Final = 48.0
    THICKNESS: Final = 4.0

    def __init__(self, spec: WidgetSpec) -> None:
        Padding.__init__(self, None, EdgeInsets())
        self.init_element(spec)

    @property
    def progress(self) -> float:
        return max(0.0, min(1.0, self.number))

    @property
    def thickness(self) -> float:
        """`style.thickness` defaults to 1dp for Divider's sake, so an explicit
        value is distinguished from the field default rather than compared to
        it."""
        if "thickness" in self.style.model_fields_set:
            return float(self.style.thickness)
        return self.THICKNESS

    def _diameter(self, constraints: Constraints) -> float:
        style = self.style
        if style.width.kind == "fixed":
            return float(style.width.value)
        if style.height.kind == "fixed":
            return float(style.height.value)
        return self.DIAMETER

    def perform_layout(self, constraints: Constraints) -> Size:
        outer = self.sized(constraints, self.style)
        d = self._diameter(constraints)
        # Square by default. A view that sets *both* width and height gets the
        # box it asked for -- constraints are not negotiable -- and the circle
        # is then inscribed in the shorter side and centred by paint_self,
        # rather than stretched into an ellipse.
        return outer.constrain(Size(d, d))

    def paint_self(self, ctx: PaintContext, absolute: Any) -> None:
        style = self.style
        thickness = self.thickness
        side = min(self.size.width, self.size.height)
        x = absolute.x + (self.size.width - side) / 2
        y = absolute.y + (self.size.height - side) / 2

        _arc(
            ctx,
            x,
            y,
            side,
            side,
            token=ctx.palette.index(style.background or "secondary_container"),
            thickness=thickness,
            start=0.0,
            sweep=TAU,
        )
        sweep = TAU * self.progress
        if sweep > 0.0:
            _arc(
                ctx,
                x,
                y,
                side,
                side,
                token=content_token(ctx, style, "primary"),
                thickness=thickness,
                start=0.0,
                sweep=sweep,
            )

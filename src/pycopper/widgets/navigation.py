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
    INF,
    Axis,
    Constraints,
    EdgeInsets,
    Flex,
    LayoutNode,
    MainAxisSize,
    Offset,
    Padding,
    Rect,
    Size,
)
from ..spec import WidgetSpec
from ..spec.typescale import TYPE_SCALE
from ..tree.element import ElementMixin, PaintContext
from .base import _StyledMixin, content_token, measure_text, paint_text
from .material import SELECTION_CURVE, SELECTION_MOTION, _arc, _box, _emit_state_layer, _state_alpha

__all__ = [
    "CircularProgressElement",
    "LinearProgressElement",
    "ListItemElement",
    "NavItemElement",
    "NavigationDrawerElement",
    "NavigationRailElement",
    "SegmentElement",
    "SegmentedButtonElement",
    "StatusBarElement",
    "TabElement",
    "TabsElement",
    "TopAppBarElement",
    "TreeItemElement",
    "TreeViewElement",
]

#: The components' own M3 type roles, quoted from M3_COMPONENT_SPECS.md: a
#: navigation bar's "Text Label Typography" is `label-medium` (12sp), an
#: app-bar title is `title-large` (22sp), a tab is `title-small` (14sp).
#:
#: Each is held as the whole role rather than as loose numbers, so its size,
#: weight and tracking reach a widget's measure and its paint together. They
#: cannot be half-applied, which is what a separate SIZE/WEIGHT pair allowed.
#:
#: A Segment reuses the Tab role. Only the Tab's is sourced; a segmented button
#: is its sibling control and looking different from it would be worse than
#: following it. The navigation *drawer* is not here: section 4.4 states no
#: typography, so its label keeps a plain size rather than borrowing a role it
#: was never given.
LABEL_ROLE: Final = TYPE_SCALE["label-medium"]
TITLE_ROLE: Final = TYPE_SCALE["title-large"]
TAB_LABEL_ROLE: Final = TYPE_SCALE["title-small"]
TITLE_SIZE: Final = TITLE_ROLE.size
ICON: Final = 24.0

#: One full turn, for the circular progress sweep.
TAU: Final = 2.0 * math.pi

#: An indicator sliding or growing "begins and ends on screen"; M3's suggested
#: pairs table offers Emphasized/500ms or Standard/300ms for that. The standard
#: row is the right one: these respond to a click and are repeated freely, and
#: half a second of emphasis on every tab change would drag.
INDICATOR_MOTION: Final = "medium2"
INDICATOR_CURVE: Final = "standard"

#: How finely the icon FILL axis is stepped while animating.
#:
#: FILL is a variable-font axis, and the axis coordinates are part of the glyph
#: atlas key (`render/atlas.py`). The atlas has no per-entry eviction -- when it
#: fills it resets wholesale and re-rasterises everything -- so animating FILL
#: continuously would pack a fresh rasterisation every frame and force repeated
#: resets. Six steps still reads as a transition and bounds the entries per
#: icon at six.
ICON_FILL_STEPS: Final = 6


def _stepped_fill(t: float) -> float:
    """Quantise an animated FILL so the atlas sees a bounded set of values."""
    return round(t * ICON_FILL_STEPS) / ICON_FILL_STEPS


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

    #: "Navigation drawer (modal)" is level 1; the rail is level 0.
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
        return measure_text(self._supporting, LABEL_ROLE, engine=self.text_engine).height

    def paint_self(self, ctx: PaintContext, absolute: Any) -> None:
        selected = self.selected
        size = self.size
        active_bg = ctx.palette.index("secondary_container")
        t = self.animated(
            "selected",
            1.0 if selected else 0.0,
            duration=INDICATOR_MOTION,
            curve=INDICATOR_CURVE,
        )
        content = content_token(
            ctx,
            self.style,
            "on_secondary_container" if selected else "on_surface_variant",
        )
        label_text = (self._supporting).strip()

        if self._in_drawer:
            if t > 0.0:
                _box(
                    ctx,
                    absolute.x,
                    absolute.y,
                    size.width,
                    size.height,
                    token=active_bg,
                    radius=self.DRAWER_RADIUS,
                    alpha=t,
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
                    fill=_stepped_fill(t),
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

        # Rail: a 56x32dp indicator pill behind the icon, label beneath. It
        # grows outward from a circle around the icon rather than appearing at
        # full width, which is how M3 expands it.
        if t > 0.0:
            width = self.INDICATOR_H + (self.INDICATOR_W - self.INDICATOR_H) * t
            _box(
                ctx,
                absolute.x + (size.width - width) / 2,
                absolute.y,
                width,
                self.INDICATOR_H,
                token=active_bg,
                radius=self.INDICATOR_H / 2,
                alpha=t,
            )
        _emit_state_layer(ctx, self, absolute, content, self.effective_radii)
        if self._text.strip():
            ctx.text.emit_icon(
                ctx.display_list,
                self._text.strip(),
                x=absolute.x + (size.width - ICON) / 2,
                y=absolute.y + (self.INDICATOR_H - ICON) / 2,
                size=ICON,
                fill=_stepped_fill(t),
                pixel_ratio=ctx.pixel_ratio,
                token=content,
                clip=ctx.clip,
                clip_radii=ctx.clip_radii,
            )
        if label_text:
            label = measure_text(label_text, LABEL_ROLE, engine=self.text_engine)
            paint_text(
                ctx,
                absolute.x + (size.width - label.width) / 2,
                absolute.y + self.INDICATOR_H + 4.0,
                label_text,
                LABEL_ROLE,
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
    if style.width.kind == "percent" and constraints.has_bounded_width:
        return constraints.max_width * float(style.width.value)
    return default


# ------------------------------------------------------------- top app bar


class TopAppBarElement(_StyledMixin, Flex):
    """M3 Top App Bar: 64dp small/center-aligned, 112dp medium, 152dp large.

    A medium or large bar **collapses into a small one as its page scrolls** --
    "when scrolled, medium and large app bars can transform into small app
    bars; they should remain small until the page is scrolled back to the top".
    Name the scrolling view with `collapses_with:`::

        - {name: bar, widget: TopAppBar, text: Inbox,
           style: {variant: large, collapses_with: body}}
        - {name: body, widget: ScrollView, style: {height: expand}}

    This is **scroll-linked**, not timed: there is no animation clock involved,
    the height is a direct function of the offset. The bar registers as a
    follower of that scroll view, which relayouts it as the view moves -- the
    scrolled content itself is untouched and still travels at paint time.

    The expanded heights are **not sourced**: that spec page's measurements are
    images. The behaviour and the colour change are quoted.
    """

    HEIGHT: Final = 64.0
    PAD: Final = 16.0
    #: variant -> expanded height. Small and centre-aligned do not collapse.
    EXPANDED: Final = {"medium": 112.0, "large": 152.0}
    #: The expanded headline, shrinking to title-large on collapse. Held as a
    #: role so the size and the line height shrink together -- interpolating
    #: one and pinning the other would tighten the leading as the bar moved.
    HEADLINE_ROLE: Final = TYPE_SCALE["headline-medium"]
    HEADLINE: Final = HEADLINE_ROLE.size

    def __init__(self, spec: WidgetSpec) -> None:
        Flex.__init__(self, axis=Axis.HORIZONTAL, spacing=spec.style.spacing or 8.0)
        self.init_element(spec)
        self._followed: Any = None

    def configure(self) -> None:
        self._spacing = self.style.spacing or 8.0
        self._followed = None  # the view may have been renamed by a reload

    @property
    def expanded_height(self) -> float:
        return self.EXPANDED.get(str(self.style.variant), self.HEIGHT)

    def _scroll_source(self) -> Any:
        """The ScrollView named by `collapses_with:`, resolved once.

        Looked up from the root rather than a sibling search: an app bar and
        the view it follows need not share a parent, and often will not.
        """
        name = self.style.collapses_with
        if name is None:
            return None
        if self._followed is None:
            node: Any = self
            while node.parent is not None:
                node = node.parent
            found = node.find(name) if hasattr(node, "find") else None
            if found is not None and hasattr(found, "scroll_offset"):
                found.follow(self)
                self._followed = found
        return self._followed

    @property
    def collapse(self) -> float:
        """How far collapsed, 0 (fully expanded) to 1 (a small bar)."""
        expanded = self.expanded_height
        travel = expanded - self.HEIGHT
        if travel <= 0.0:
            return 0.0
        source = self._scroll_source()
        if source is None:
            return 0.0
        return max(0.0, min(1.0, float(source.scroll_offset) / travel))

    @property
    def current_height(self) -> float:
        expanded = self.expanded_height
        return expanded - (expanded - self.HEIGHT) * self.collapse

    def perform_layout(self, constraints: Constraints) -> Size:
        height = self.current_height
        outer = constraints.copy_with(min_height=height, max_height=height)
        size = super().perform_layout(outer)
        for child in self.children:
            child.offset = child.offset + EdgeInsets.all(self.PAD).top_left
        return size

    def paint_self(self, ctx: PaintContext, absolute: Any) -> None:
        style = self.style
        t = self.collapse
        containers: tuple[tuple[int, float], ...]
        if style.background:
            containers = ((ctx.palette.index(style.background), 1.0),)
        else:
            # "On scroll, the container changes color to surface container."
            # Tokens resolve in the shader, so this is two boxes, not a lerp.
            containers = (
                (ctx.palette.index("surface"), 1.0),
                (ctx.palette.index("surface_container"), t),
            )
        for token_index, weight in containers:
            if weight <= 0.0:
                continue
            _box(
                ctx,
                absolute.x,
                absolute.y,
                self.size.width,
                self.size.height,
                token=token_index,
                radius=0.0,
                alpha=weight,
            )
        title = self._text.strip()
        if not title:
            return
        token = content_token(ctx, style, "on_surface")
        size = style.font_size if style.font_size != 14.0 else TITLE_SIZE
        leading = TITLE_ROLE.line_height
        if self.expanded_height > self.HEIGHT:
            # The headline shrinks to title-large as the bar becomes a small
            # one, so the two forms agree at the moment of arrival.
            size = self.HEADLINE + (size - self.HEADLINE) * t
            leading = (
                self.HEADLINE_ROLE.line_height + (leading - self.HEADLINE_ROLE.line_height) * t
            )
        label = measure_text(
            title,
            size,
            engine=self.text_engine,
            weight=TITLE_ROLE.weight,
            tracking=TITLE_ROLE.tracking,
            line_height=leading,
        )
        x = (
            absolute.x + (self.size.width - label.width) / 2
            if style.variant == "center_aligned"
            else absolute.x + self.PAD
        )
        paint_text(
            ctx,
            x,
            absolute.y + (self.size.height - label.height) / 2,
            title,
            size,
            token,
            weight=TITLE_ROLE.weight,
            tracking=TITLE_ROLE.tracking,
            line_height=leading,
        )


# --------------------------------------------------------------- status bar


class StatusBarElement(_StyledMixin, Flex):
    """A thin, informational bar docked to a window edge -- word count,
    encoding, a git branch, connection state.

    M3 has neither this widget nor the phrase "status bar" anywhere in its
    own vocabulary -- checked directly rather than assumed absent, the same
    way `Pagination`'s grounding was checked. Its cousin from the same
    docked-bar family that DOES exist, the docked toolbar (M3's replacement
    for the deprecated bottom app bar), is a different thing: a row of
    *action* buttons, not an informational strip, so this does not borrow
    its anatomy despite sitting at the same edge of a window.

    Built the way `TopAppBar` is: a plain `Flex` a view populates with
    whatever `Text`/`Icon`/`Divider` children it wants. There is no special
    "leading"/"trailing" slot to learn -- a `Spacer` does that split the same
    way it would in any other `Row`.

    `surface_container` background, no drawn border, follows this
    framework's existing convention for a docked surface (`Card`, `Menu`,
    `TopAppBar`, both sheets all read the same way): a tonal shift says "this
    is a separate surface" without a hard line. The 24dp height and 16dp
    horizontal padding are not sourced -- there is nothing to source them
    from -- chosen to read as clearly thinner than every interactive
    control's own 40dp+ density in this framework, which is the one thing a
    purely informational bar should never be mistaken for.
    """

    HEIGHT: Final = 24.0
    PAD_X: Final = 16.0

    def __init__(self, spec: WidgetSpec) -> None:
        Flex.__init__(self, axis=Axis.HORIZONTAL, spacing=spec.style.spacing or 8.0)
        self.init_element(spec)

    def configure(self) -> None:
        self._spacing = self.style.spacing or 8.0

    def flex_of(self, child: Any) -> int:
        """A child styled `expand` or `flex:n` is flexible, matching Row and
        Column's own `_FlexElement.flex_of`.

        This widget extends `Flex` directly rather than `_FlexElement`, so
        without this override a `Spacer` meant to push trailing items to the
        far edge -- the documented way to split this bar into leading and
        trailing groups -- is measured as an ordinary inflexible child. It
        would then be sized against nearly all the remaining width and
        starve whatever comes after it, rather than sharing the space.
        """
        explicit = super().flex_of(child)
        if explicit:
            return explicit
        if not isinstance(child, ElementMixin):
            return 0
        size = child.style.width
        if size.kind == "flex":
            return max(1, int(size.value))
        return 1 if size.kind == "expand" else 0

    def perform_layout(self, constraints: Constraints) -> Size:
        outer = constraints.copy_with(min_height=self.HEIGHT, max_height=self.HEIGHT)
        pad = EdgeInsets.symmetric(horizontal=self.PAD_X)
        inner = super().perform_layout(outer.deflate(pad))
        for child in self.children:
            child.offset = child.offset + pad.top_left
        return outer.constrain(inner.inflate(pad))

    def paint_self(self, ctx: PaintContext, absolute: Any) -> None:
        token = ctx.palette.index(self.style.background or "surface_container")
        _box(
            ctx, absolute.x, absolute.y, self.size.width, self.size.height, token=token, radius=0.0
        )


# ------------------------------------------------------------------- tabs


class TabElement(_StyledMixin, Padding):
    """One tab. The active indicator is drawn by the parent Tabs container."""

    HEIGHT: Final = 48.0
    PAD_X: Final = 16.0

    def __init__(self, spec: WidgetSpec) -> None:
        Padding.__init__(self, None, EdgeInsets())
        self.init_element(spec)

    def perform_layout(self, constraints: Constraints) -> Size:
        label = measure_text(self._text, TAB_LABEL_ROLE, engine=self.text_engine)
        return self.sized(constraints, self.style).constrain(
            Size(label.width + self.PAD_X * 2, self.HEIGHT)
        )

    def paint_self(self, ctx: PaintContext, absolute: Any) -> None:
        token = content_token(ctx, self.style, "primary" if self.selected else "on_surface_variant")
        _emit_state_layer(ctx, self, absolute, token, (0.0,) * 4)
        if not self._text.strip():
            return
        label = measure_text(self._text, TAB_LABEL_ROLE, engine=self.text_engine)
        paint_text(
            ctx,
            absolute.x + (self.size.width - label.width) / 2,
            absolute.y + (self.size.height - label.height) / 2,
            self._text,
            TAB_LABEL_ROLE,
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
        # The indicator belongs to the container, not to a tab, which is what
        # lets it travel between them. Both edges animate, so it stretches and
        # settles rather than jumping -- and this costs paint only, since the
        # tabs themselves have not moved.
        x = self.animated(
            "indicator_x",
            active.offset.x,
            duration=INDICATOR_MOTION,
            curve=INDICATOR_CURVE,
        )
        width = self.animated(
            "indicator_w",
            active.size.width,
            duration=INDICATOR_MOTION,
            curve=INDICATOR_CURVE,
        )
        _box(
            ctx,
            absolute.x + x,
            y,
            width,
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

    def _check_progress(self) -> float:
        """How far the leading checkmark has arrived, 0 to 1.

        Changes the segment's width, so it invalidates layout -- the label and
        the neighbouring segments move with it. The same trade as the filter
        Chip, and affordable for the same reason: a segmented button holds two
        or three children.
        """
        value: float = self.animated(
            "selected",
            1.0 if self.selected else 0.0,
            duration=INDICATOR_MOTION,
            curve=INDICATOR_CURVE,
            invalidates="layout",
        )
        return value

    def perform_layout(self, constraints: Constraints) -> Size:
        label = measure_text(self._text, TAB_LABEL_ROLE, engine=self.text_engine)
        width = label.width + self.PAD_X * 2 + (self.CHECK + self.GAP) * self._check_progress()
        return self.sized(constraints, self.style).constrain(Size(width, self.HEIGHT))

    def paint_self(self, ctx: PaintContext, absolute: Any) -> None:
        selected = self.selected
        token = content_token(
            ctx, self.style, "on_secondary_container" if selected else "on_surface"
        )
        t = self._check_progress()
        if t > 0.0:
            _box(
                ctx,
                absolute.x,
                absolute.y,
                self.size.width,
                self.size.height,
                token=ctx.palette.index("secondary_container"),
                radius=0.0,
                alpha=t,
            )
        _emit_state_layer(ctx, self, absolute, token, (0.0,) * 4)

        x = absolute.x + self.PAD_X
        if t > 0.0:
            # Grows into the space being made for it, or it would overlap a
            # label that has only travelled part of the way.
            check = self.CHECK * t
            ctx.text.emit_icon(
                ctx.display_list,
                "check",
                x=x,
                y=absolute.y + (self.size.height - check) / 2,
                size=check,
                pixel_ratio=ctx.pixel_ratio,
                token=token,
                color=(1.0, 1.0, 1.0, t),
                clip=ctx.clip,
                clip_radii=ctx.clip_radii,
            )
            x += (self.CHECK + self.GAP) * t
        if self._text.strip():
            label = measure_text(self._text, TAB_LABEL_ROLE, engine=self.text_engine)
            paint_text(
                ctx,
                x,
                absolute.y + (self.size.height - label.height) / 2,
                self._text,
                TAB_LABEL_ROLE,
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

    CLIPS_CHILDREN = True

    def child_paint_context(self, ctx: PaintContext, absolute: Any) -> PaintContext:
        """Clip segments to the rounded container so a selected end segment's
        square fill does not poke past the outline."""
        dpr = ctx.pixel_ratio
        return PaintContext(
            display_list=ctx.display_list,
            palette=ctx.palette,
            text=ctx.text,
            images=ctx.images,
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


# --------------------------------------------------------------- tree view


class TreeViewElement(_SelectionContainer):
    """M3 has no Tree component -- the same gap Accordion fills, and the same
    source: Lists' "List items containing other list items can expand and
    collapse in a folder-like manner" (`COMPONENT_LISTS.md`). A tree is that
    statement applied recursively rather than once.

    Reuses `_SelectionContainer`'s shape -- `value:` names the selected item
    -- but a tree's selected item can sit at any depth, not just among direct
    children, so `apply_selection` is overridden to walk the whole subtree
    instead of one level.
    """

    axis = Axis.VERTICAL

    def apply_selection(self) -> None:
        active = self._value.strip()

        def walk(node: Any) -> None:
            for child in node.children:
                if isinstance(child, TreeItemElement):
                    child.set_selected(bool(active) and child.name == active)
                    walk(child)

        walk(self)


class TreeItemElement(_StyledMixin, LayoutNode):
    """One node. `children:` of further `TreeItem`s makes it a branch; none
    makes it a leaf, with no chevron and nothing to expand.

    **Anatomy is `ListItem`'s**, exactly as Accordion's is, for the same
    reason: M3 gives this nothing of its own. **Expand state, the chevron
    swap, and the height-animation-plus-clip reveal are Accordion's
    mechanism reused verbatim** -- see `AccordionElement`'s docstring for why
    each of those is shaped the way it is; a tree node is an accordion that
    can nest.

    **Two things ARE new here, because recursion makes them unavoidable:**

    - **Indentation.** Each level indents by one chevron-width (`INDENT`).
      Not sourced from M3 -- no tree page exists to source it from -- chosen
      to line a child's content up under where its own children's chevrons
      would begin, the common convention across desktop tree views.
    - **The clip intersects its ancestor's, rather than replacing it.**
      Accordion and `ScrollView` both simply overwrite the incoming
      `ctx.clip` with their own rect, which is safe only because neither is
      ever nested inside its own kind in practice. A tree item routinely is:
      collapsing a node must hide every descendant regardless of which of
      them are individually expanded, so a grandchild's effective clip has
      to be its own rect intersected with everything above it, not just its
      immediate parent's.

    Selection is a **separate, orthogonal concern** owned by the enclosing
    `TreeView` (`value:` naming the selected node), not by this class --
    the same split Accordion has none of, because it never had a container.
    """

    HEADER_ONE_LINE: Final = 56.0
    HEADER_TWO_LINE: Final = 72.0
    PAD_X: Final = 16.0
    HEADLINE: Final = 16.0
    SUPPORTING: Final = 14.0
    CHEVRON: Final = 24.0
    #: One chevron-width per nesting level -- see the class docstring.
    INDENT: Final = CHEVRON
    CURSOR = "pointer"
    CLIPS_CHILDREN = True

    def __init__(self, spec: WidgetSpec) -> None:
        LayoutNode.__init__(self)
        self.init_element(spec)

    @property
    def depth(self) -> int:
        """Nesting level, derived from ancestry rather than stored -- the
        same idiom `NavItemElement._in_drawer` uses for its own context."""
        depth = 0
        node = self.parent
        while node is not None:
            if isinstance(node, TreeItemElement):
                depth += 1
            node = node.parent
        return depth

    def _header_height(self) -> float:
        return self.HEADER_TWO_LINE if self._supporting.strip() else self.HEADER_ONE_LINE

    def _progress(self) -> float:
        """0 (collapsed) to 1 (fully expanded) -- see `AccordionElement._progress`."""
        return self.animated(
            "expanded",
            1.0 if self.checked else 0.0,
            duration=SELECTION_MOTION,
            curve=SELECTION_CURVE,
            invalidates="layout",
        )

    def perform_layout(self, constraints: Constraints) -> Size:
        outer = self.sized(constraints, self.style)
        width = outer.max_width if outer.has_bounded_width else 320.0
        header_h = self._header_height()

        # Every child is laid out and stacked at its NATURAL height regardless
        # of this node's own current (animated) height -- same reasoning as
        # Accordion's single child, generalised to however many there are.
        cursor = header_h
        if self._children:
            child_constraints = Constraints(
                min_width=width, max_width=width, min_height=0.0, max_height=INF
            )
            for child in self._children:
                size = child.layout(child_constraints)
                child.offset = Offset(0.0, cursor)
                cursor += size.height
        body_h = cursor - header_h

        revealed = body_h * self._progress()
        return outer.constrain(Size(width, header_h + revealed))

    #: Real, but far below one physical pixel -- passes the shader's own
    #: `clip.z/w > 0.0` gate (`ui.wgsl`: "a zero-size clip rect means
    #: unclipped") without leaving any rasterisable area. `Rect.intersect`
    #: clamps a no-overlap result to an exact zero in the degenerate
    #: dimension, which that same shader gate reads as "no clip at all" --
    #: the opposite of what a collapsed ancestor needs. Confirmed by
    #: rendering a real frame: a grandchild's label was still on screen
    #: with the un-floored intersection, despite the clip rect looking
    #: correct from the Python side.
    HIDDEN_EXTENT: Final = 0.01

    def child_paint_context(self, ctx: PaintContext, absolute: Any) -> PaintContext:
        """Clip to this node's own (animated) size, INTERSECTED with whatever
        clip already reached it -- see the class docstring for why this
        cannot simply replace the incoming clip the way Accordion's does."""
        dpr = ctx.pixel_ratio
        own = Rect(
            absolute.x * dpr, absolute.y * dpr, self.size.width * dpr, self.size.height * dpr
        )
        clip = own if ctx.clip[2] == 0.0 and ctx.clip[3] == 0.0 else Rect(*ctx.clip).intersect(own)
        width = clip.width if clip.width > 0.0 else self.HIDDEN_EXTENT
        height = clip.height if clip.height > 0.0 else self.HIDDEN_EXTENT
        return PaintContext(
            display_list=ctx.display_list,
            palette=ctx.palette,
            text=ctx.text,
            images=ctx.images,
            pixel_ratio=dpr,
            clip=(clip.x, clip.y, width, height),
            clip_radii=ctx.clip_radii,
        )

    def paint_self(self, ctx: PaintContext, absolute: Any) -> None:
        style = self.style
        header_h = self._header_height()
        headline_tok = content_token(ctx, style, "on_surface")
        supporting_tok = ctx.palette.index("on_surface_variant")

        if self.selected:
            dpr = ctx.pixel_ratio
            ctx.display_list.add_box(
                absolute.x * dpr,
                absolute.y * dpr,
                self.size.width * dpr,
                header_h * dpr,
                token=ctx.palette.index("secondary_container"),
                clip=ctx.clip,
                clip_radii=ctx.clip_radii,
            )
            headline_tok = ctx.palette.index("on_secondary_container")

        # Scoped to the header row alone -- see AccordionElement.paint_self
        # for why `_emit_state_layer` (sized from the whole animated element)
        # is the wrong helper here.
        alpha = _state_alpha(self)
        if alpha > 0.001:
            dpr = ctx.pixel_ratio
            ctx.display_list.add_box(
                absolute.x * dpr,
                absolute.y * dpr,
                self.size.width * dpr,
                header_h * dpr,
                token=headline_tok,
                color=(1.0, 1.0, 1.0, alpha),
                clip=ctx.clip,
                clip_radii=ctx.clip_radii,
            )

        indent = self.PAD_X + self.depth * self.INDENT
        x = absolute.x + indent
        if self._children:
            icon = "expand_less" if self.checked else "expand_more"
            ctx.text.emit_icon(
                ctx.display_list,
                icon,
                x=x,
                y=absolute.y + (header_h - self.CHEVRON) / 2,
                size=self.CHEVRON,
                pixel_ratio=ctx.pixel_ratio,
                token=supporting_tok,
                clip=ctx.clip,
                clip_radii=ctx.clip_radii,
            )
        # A leaf's label starts where a branch's would, chevron or not, so
        # sibling labels stay aligned regardless of which ones can expand.
        x += self.CHEVRON + 8.0

        second = self._supporting.strip()
        if second:
            top = measure_text(self._text, self.HEADLINE, engine=self.text_engine)
            bottom = measure_text(second, self.SUPPORTING, engine=self.text_engine)
            block = top.height + bottom.height
            y = absolute.y + (header_h - block) / 2
            paint_text(ctx, x, y, self._text, self.HEADLINE, headline_tok)
            paint_text(ctx, x, y + top.height, second, self.SUPPORTING, supporting_tok)
        elif self._text.strip():
            label = measure_text(self._text, self.HEADLINE, engine=self.text_engine)
            y = absolute.y + (header_h - label.height) / 2
            paint_text(ctx, x, y, self._text, self.HEADLINE, headline_tok)


# --------------------------------------------------------------- progress


#: Indeterminate cycle length. **Not sourced** -- M3 describes the behaviour
#: ("move along a fixed track, growing and shrinking in size") but the scrape
#: carries no cycle duration, so this is the longest M3 duration token.
INDETERMINATE_CYCLE: Final = "extra_long4"


class LinearProgressElement(_StyledMixin, Padding):
    """M3 Linear Progress: 4dp high with rounded ends.

    Omitting `value:` selects the **indeterminate** form, which M3 describes as
    moving "along a fixed track, growing and shrinking in size". Supplying a
    value makes it determinate -- and M3 notes an indicator should change from
    indeterminate to determinate as information arrives, which here is just
    binding `value:` to a signal that starts empty.

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
    def indeterminate(self) -> bool:
        """No resolved value at all means the wait time is unknown.

        Read from the live `_value` rather than the static `spec.value` --
        `value:` is templated like `text:`, so a signal bound through it that
        starts empty must be able to flip this determinate on its own once it
        reports one, per docs/view-reference.md's "changes from indeterminate
        to determinate ... as information arrives". `spec.value` is only ever
        the unrendered template source, which is never None once `value:` is
        written at all.
        """
        return not self._value.strip()

    @property
    def progress(self) -> float:
        return max(0.0, min(1.0, self.number))

    def perform_layout(self, constraints: Constraints) -> Size:
        outer = self.sized(constraints, self.style)
        width = outer.max_width if outer.has_bounded_width else 0.0
        return outer.constrain(Size(width, self.HEIGHT))

    def _indeterminate_span(self) -> tuple[float, float]:
        """Leading edge and length of the travelling bar, as fractions.

        One repeating value drives both, so the bar grows out of the leading
        edge, crosses, and shrinks into the trailing one -- "growing and
        shrinking in size" without a second animation to keep in step.
        """
        # Linear, not eased: a looping animation on an ease curve decelerates
        # into the wrap and jumps back to full speed, which reads as a stutter
        # once a second. Eased curves are for transitions that end.
        t = self.animated(
            "indeterminate", 1.0, duration=INDETERMINATE_CYCLE, curve="linear", repeat=True
        )
        head = min(1.0, t * 2.0)
        tail = max(0.0, t * 2.0 - 1.0)
        return tail, head - tail

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
        if self.indeterminate:
            start, length = self._indeterminate_span()
            offset, filled = self.size.width * start, self.size.width * length
        else:
            # A bound `value:` can flip this element determinate without a
            # dispose -- nothing else stops the repeat=True animation already
            # registered with the ticker, so it would keep firing forever.
            running = self.animation("indeterminate")
            if running is not None:
                self.ticker.discard(running)
            offset, filled = 0.0, self.size.width * self.progress
        if filled > 0:
            _box(
                ctx,
                absolute.x + offset,
                absolute.y,
                filled,
                self.size.height,
                token=content_token(ctx, self.style, "primary"),
                radius=radius,
            )


class CircularProgressElement(_StyledMixin, Padding):
    """M3 Circular Progress: a 4dp ring, filled clockwise from 12 o'clock.

    Omitting `value:` selects the **indeterminate** form: a fixed-length arc
    that rotates continuously, since a circular track has no leading or
    trailing edge for a bar to grow out of.

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

    #: How much of the ring the spinning arc covers.
    INDETERMINATE_SWEEP: Final = 0.75

    @property
    def indeterminate(self) -> bool:
        """Same rule as `LinearProgress.indeterminate` -- see its docstring."""
        return not self._value.strip()

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
        if self.indeterminate:
            turn = self.animated(
                "spin", 1.0, duration=INDETERMINATE_CYCLE, curve="linear", repeat=True
            )
            start, sweep = TAU * turn, TAU * self.INDETERMINATE_SWEEP
        else:
            # Same repeat=True leak as LinearProgress -- see its paint_self.
            running = self.animation("spin")
            if running is not None:
                self.ticker.discard(running)
            start, sweep = 0.0, TAU * self.progress
        if sweep > 0.0:
            _arc(
                ctx,
                x,
                y,
                side,
                side,
                token=content_token(ctx, style, "primary"),
                thickness=thickness,
                start=start,
                sweep=sweep,
            )

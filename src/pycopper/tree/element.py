"""The Element tree: mutable runtime nodes that persist across hot reloads.

This is tree 2 of the four (ARCHITECTURE.md 4). It holds everything the frozen
Spec cannot: resolved style, focus, hover, scroll offset, signal subscriptions,
and the cached instance slice that makes repainting a clean subtree a memcpy.

Elements are LayoutNode subclasses, so layout machinery -- constraints, relayout
boundaries, caching -- comes from M1 unchanged. Concrete widgets in
:mod:`pycopper.widgets` combine :class:`ElementMixin` with a layout algorithm.
``ElementMixin`` deliberately declares no ``__slots__``: Python rejects an
instance layout built from two bases that each carry NON-EMPTY slots, so the
mixin supplies the ``__dict__`` and the layout node supplies the slots.
"""

from __future__ import annotations

from collections.abc import Callable, Iterator
from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Any

import numpy as np

from ..layout import OFFSET_ZERO, Offset, Rect
from ..motion import Animation, Ticker, default_ticker
from ..paint import NO_TOKEN, DisplayList
from ..runtime.signals import Effect
from ..spec import StyleSpec, Template, WidgetSpec
from ..text import TextEngine
from ..theme import Palette

if TYPE_CHECKING:
    from ..layout import LayoutNode

__all__ = ["ElementMixin", "PaintContext", "WidgetState"]

_NO_CLIP = (0.0, 0.0, 0.0, 0.0)

#: M3 accessibility: a focused element renders a high-visibility 2dp stroke
#: around its boundary. The reference says "high contrast colour" without
#: naming a token; `secondary` is M3 Web's choice and contrasts with the
#: primary-coloured components it most often surrounds.
FOCUS_RING_WIDTH = 2.0
FOCUS_RING_OFFSET = 2.0
FOCUS_RING_TOKEN = "secondary"

_DEFAULT_TEXT: TextEngine | None = None


def default_text_engine() -> TextEngine:
    """Process-wide CPU-only engine for elements built outside an App.

    An App installs its own on mount; this exists so a widget can be measured
    in a unit test without standing up an application.
    """
    global _DEFAULT_TEXT
    if _DEFAULT_TEXT is None:
        _DEFAULT_TEXT = TextEngine()
    return _DEFAULT_TEXT


@dataclass(slots=True)
class WidgetState:
    """Runtime state. Survives hot reload; the Spec never holds any of this."""

    hovered: bool = False
    pressed: bool = False
    focused: bool = False
    #: True only when focus arrived via the keyboard. Desktop convention: a
    #: mouse click focuses without showing a ring, Tab shows one. Without this
    #: split every click leaves a ring behind, which reads as a bug.
    focus_visible: bool = False
    scroll: Offset = OFFSET_ZERO
    data: dict[str, Any] = field(default_factory=dict)


@dataclass(slots=True)
class PaintContext:
    """Everything paint needs that is not on the element itself."""

    display_list: DisplayList
    palette: Palette
    text: TextEngine = field(default_factory=default_text_engine)
    pixel_ratio: float = 1.0
    clip: tuple[float, float, float, float] = _NO_CLIP
    clip_radii: tuple[float, float, float, float] = _NO_CLIP


class ElementMixin:
    """Shared element behaviour. Combined with a layout algorithm by widgets."""

    spec: WidgetSpec
    parent: Any
    children: Any
    offset: Any
    size: Any
    state: WidgetState
    handlers: dict[str, Callable[[Any], None]]
    _effect: Effect | None
    _text: str
    _template: Template | None
    _value_template: Template | None
    _value: str
    _supporting_template: Template | None
    _supporting: str
    _open_template: Template | None
    _open: str
    _cached: np.ndarray | None
    _cached_origin: Offset | None
    _needs_paint: bool
    _text_engine: TextEngine | None
    _ticker: Ticker | None
    _animations: dict[str, Animation]

    def init_element(self, spec: WidgetSpec) -> None:
        self.spec = spec
        self.state = WidgetState()
        self.handlers = {}
        self._effect = None
        self._template = spec.template()
        self._text = spec.text or ""
        self._value_template = spec.value_template()
        self._value = spec.value or ""
        self._supporting_template = spec.supporting_template()
        self._supporting = spec.supporting_text or ""
        self._open_template = spec.open_template()
        self._open = spec.open or ""
        self._cached = None
        self._cached_origin = None
        self._needs_paint = True
        self._text_engine = None
        self._ticker = None
        #: Named animations owned by this element. They survive `update_spec`
        #: with the rest of the runtime state, so a hot reload does not restart
        #: a transition that is mid-flight.
        self._animations = {}

    def update_spec(self, spec: WidgetSpec) -> None:
        """Adopt a new spec, keeping all runtime state. The reconciler's core
        operation -- this is why editing a view file does not lose focus."""
        self.spec = spec
        self._template = spec.template()
        if self._template is None or self._template.is_static:
            self._text = spec.text or ""
        self._value_template = spec.value_template()
        if self._value_template is None or self._value_template.is_static:
            self._value = spec.value or ""
        self._supporting_template = spec.supporting_template()
        if self._supporting_template is None or self._supporting_template.is_static:
            self._supporting = spec.supporting_text or ""
        self._open_template = spec.open_template()
        if self._open_template is None or self._open_template.is_static:
            self._open = spec.open or ""
        self.configure()
        self.mark_needs_layout()

    def configure(self) -> None:
        """Push spec-derived values into layout parameters. Overridden by
        widgets whose layout config is captured at construction."""

    @property
    def text_engine(self) -> TextEngine:
        """The engine used to measure this element's text during layout."""
        return self._text_engine if self._text_engine is not None else default_text_engine()

    def set_text_engine(self, engine: TextEngine) -> None:
        self._text_engine = engine
        for child in self.children:
            if isinstance(child, ElementMixin):
                child.set_text_engine(engine)

    # -------------------------------------------------------------- motion

    @property
    def ticker(self) -> Ticker:
        return self._ticker if self._ticker is not None else default_ticker()

    def set_ticker(self, ticker: Ticker) -> None:
        self._ticker = ticker
        for child in self.children:
            if isinstance(child, ElementMixin):
                child.set_ticker(ticker)

    def animated(
        self,
        key: str,
        target: float,
        *,
        duration: str | float = "short4",
        curve: str = "standard",
        repeat: bool = False,
        invalidates: str = "paint",
    ) -> float:
        """Current value of a named animation heading towards `target`.

        Call it wherever the value is needed and use what comes back -- the
        first call settles on the target immediately (there is nothing to
        animate *from*), and a later call with a different target retargets
        from wherever the value currently is.

        Marks this element for **paint** each frame. Pass
        `invalidates="layout"` only when the animated value genuinely changes
        geometry -- it then relayouts on every frame of the transition, which
        is affordable for a handful of children and not for a long list. The
        parameter exists so that cost is visible at the call site rather than
        hidden in a widget.
        """
        if invalidates not in ("paint", "layout"):
            raise ValueError(f"invalidates must be 'paint' or 'layout', not {invalidates!r}")
        notify = self.mark_needs_layout if invalidates == "layout" else self.mark_needs_paint
        animation = self._animations.get(key)
        if animation is None:
            # A one-shot settles on its target at once -- there is nothing to
            # animate *from* on the first frame. A repeating one must sweep,
            # so it starts at zero; created like a one-shot it would
            # interpolate from a value to itself and never move.
            animation = Animation(
                0.0 if repeat else target,
                target,
                duration=duration,
                curve=curve,
                repeat=repeat,
                on_change=notify,
            )
            self._animations[key] = animation
            if repeat:
                self.ticker.add(animation)
                return animation.value
            return target
        if repeat:
            self.ticker.add(animation)
            return animation.value
        if animation.end != target:
            # Timing is passed through on every retarget, so a caller can give
            # a transition different enter and exit pairs -- which M3 does.
            animation.retarget(target, duration=duration, curve=curve)
            self.ticker.add(animation)
        return animation.value

    def animation(self, key: str) -> Animation | None:
        """The named animation, for tests and for widgets that need its state."""
        return self._animations.get(key)

    # ------------------------------------------------------------- identity

    @property
    def id(self) -> str:
        """Positional identity, assigned by the loader. Internal."""
        return self.spec.id

    @property
    def name(self) -> str | None:
        """The designer's handle, if this node was given one."""
        return self.spec.name

    @property
    def classes(self) -> tuple[str, ...]:
        """Categories for the theme engine and stylesheet to select on."""
        return self.spec.classes

    def has_class(self, name: str) -> bool:
        return name in self.spec.classes

    @property
    def style(self) -> StyleSpec:
        return self.spec.style

    @property
    def text(self) -> str:
        """Rendered text, after binding expressions have been evaluated."""
        return self._text

    @property
    def value(self) -> str:
        """Rendered `value:` binding -- selection, count, or progress."""
        return self._value

    @property
    def is_open(self) -> bool:
        """Whether an overlay is showing. False when `open:` was not given."""
        return self._open.strip().lower() not in ("", "false", "0", "none", "no")

    @property
    def supporting(self) -> str:
        """Rendered `supporting_text` binding -- a list item's second line."""
        return self._supporting

    @property
    def selected(self) -> bool:
        """Whether a parent container has marked this item as the active one.

        Set by NavigationRail/Drawer, Tabs and SegmentedButton on their
        children during layout, so an item renders its own selected appearance
        without reaching back up the tree.
        """
        return bool(self.state.data.get("selected", False))

    def set_selected(self, value: bool) -> None:
        if bool(self.state.data.get("selected", False)) != value:
            self.state.data["selected"] = value
            self.mark_needs_paint()

    @property
    def checked(self) -> bool:
        """`value` as a boolean. Empty, "false", "0" and "none" are all false."""
        return self._value.strip().lower() not in ("", "false", "0", "none", "no")

    @property
    def number(self) -> float:
        """`value` as a number, or 0.0 when it is not one."""
        try:
            return float(self._value)
        except ValueError:
            return 0.0

    # ----------------------------------------------------------- invalidation

    @property
    def needs_paint(self) -> bool:
        return self._needs_paint

    def mark_needs_paint(self) -> None:
        """Visual-only invalidation: does NOT trigger layout.

        This is the distinction a single global dirty flag cannot make, and the
        reason a colour change costs almost nothing (ARCHITECTURE.md 5.2).
        """
        node = self
        while isinstance(node, ElementMixin):
            if node._needs_paint:
                return
            node._needs_paint = True
            node._cached = None
            node = node.parent

    def mark_needs_layout(self) -> None:
        self.mark_needs_paint()
        super().mark_needs_layout()  # type: ignore[misc]

    # -------------------------------------------------------------- bindings

    def bind(self, context: dict[str, Any]) -> None:
        """Subscribe to whatever the text template reads.

        The Effect re-evaluates on change and marks only this element dirty --
        the fine-grained half of fine-grained reactivity.
        """
        bound: list[tuple[str, Template]] = [
            (name, tpl)
            for name, tpl in (
                ("_text", self._template),
                ("_value", self._value_template),
                ("_supporting", self._supporting_template),
                ("_open", self._open_template),
            )
            if tpl is not None and not tpl.is_static
        ]
        if not bound:
            return

        def refresh() -> None:
            changed = False
            for attr, tpl in bound:
                rendered = tpl.render(context)
                if rendered != getattr(self, attr):
                    setattr(self, attr, rendered)
                    changed = True
            if changed:
                self.mark_needs_layout()

        self._effect = Effect(refresh)

    def dispose(self) -> None:
        """Release subscriptions. Called when reconciliation drops a node."""
        if self._effect is not None:
            self._effect.dispose()
            self._effect = None
        for child in self.children:
            if isinstance(child, ElementMixin):
                child.dispose()

    # ------------------------------------------------------------------ paint

    def paint(self, ctx: PaintContext, origin: Offset) -> None:
        """Emit this subtree into the display list, back to front.

        A clean subtree at an unchanged origin is spliced from its cached slice
        -- 0.002 ms per 1000 instances versus 3.27 ms to rebuild (§12.1).
        """
        absolute = origin + self.offset

        if not self._needs_paint and self._cached is not None and self._cached_origin == absolute:
            ctx.display_list.extend(self._cached)
            return

        start = len(ctx.display_list)
        self.paint_self(ctx, absolute)
        child_ctx = self.child_paint_context(ctx, absolute)
        child_origin = self.child_origin(absolute)
        for child in self.children:
            if isinstance(child, ElementMixin):
                child.paint(child_ctx, child_origin)

        self.paint_focus_ring(ctx, absolute)
        self._cached = ctx.display_list.snapshot(start)
        self._cached_origin = absolute
        self._needs_paint = False

    #: Where this widget sits when used as an overlay and the view does not
    #: say. A component named `BottomSheet` should not need `placement: bottom`
    #: spelled out; None means "no opinion", which resolves to `style.placement`.
    DEFAULT_PLACEMENT: str | None = None

    #: Docked overlays sit flush against their window edge; floating ones keep
    #: a margin. This is the same distinction M3 draws by rounding only a
    #: sheet's inner corners -- the outer edge is against the window, so a gap
    #: there would leave the unrounded corners hanging in mid-air.
    DOCKED: bool = False

    @property
    def resolved_placement(self) -> str:
        """Placement actually used, in precedence order.

        1. An explicit `placement:` in the view always wins -- detected with
           pydantic's `model_fields_set`, so an explicitly written `center` is
           distinguishable from the field's default of `center`.
        2. An `anchor:` with no placement means the designer wants anchoring;
           naming an anchor and then centring the overlay is never intended.
        3. Otherwise the component's own default.
        """
        style = self.style
        if "placement" in style.model_fields_set:
            return str(style.placement)
        if style.anchor:
            return "anchor"
        return self.DEFAULT_PLACEMENT or str(style.placement)

    @property
    def effective_radii(self) -> tuple[float, float, float, float]:
        """Corner radii this element actually paints with.

        Distinct from ``style.corner_radius`` because several components
        compute their own -- a Button is a pill at height/2 when the view sets
        no radius. The focus ring follows this, or it would draw a rectangle
        around a rounded control.
        """
        return self.style.corner_radius

    def paint_focus_ring(self, ctx: PaintContext, absolute: Offset) -> None:
        """Draw the M3 focus indicator, on top of this element's whole subtree.

        Implemented once here rather than per widget, so every focusable
        component gets a correct ring without opting in. Only drawn for
        keyboard focus (see WidgetState.focus_visible).
        """
        if not (self.state.focused and self.state.focus_visible):
            return
        size = self.size
        if size.is_empty:
            return
        dpr = ctx.pixel_ratio
        offset = FOCUS_RING_OFFSET
        radii = tuple((r + offset) if r > 0 else 0.0 for r in self.effective_radii)
        ctx.display_list.add_box(
            (absolute.x - offset) * dpr,
            (absolute.y - offset) * dpr,
            (size.width + offset * 2) * dpr,
            (size.height + offset * 2) * dpr,
            token=ctx.palette.index(FOCUS_RING_TOKEN),
            color=(1.0, 1.0, 1.0, 0.0),  # ring only, no fill
            radii=tuple(r * dpr for r in radii),  # type: ignore[arg-type]
            border_width=FOCUS_RING_WIDTH * dpr,
            border_token=ctx.palette.index(FOCUS_RING_TOKEN),
            border_color=(1.0, 1.0, 1.0, 1.0),
            clip=ctx.clip,
            clip_radii=ctx.clip_radii,
        )

    def child_paint_context(self, ctx: PaintContext, absolute: Offset) -> PaintContext:
        """Override to introduce a clip for children (scroll views, cards)."""
        return ctx

    def child_origin(self, absolute: Offset) -> Offset:
        """Origin children are positioned from. Default: this element's own.

        A scroll view returns `absolute - scroll`, which is what makes
        scrolling a **paint-time** translation rather than a relayout: the
        content keeps the offsets layout gave it and the whole subtree simply
        draws somewhere else. Hit testing threads the same origin, so the
        pointer follows the pixels.
        """
        return absolute

    def paint_self(self, ctx: PaintContext, absolute: Offset) -> None:
        """Emit this element's own primitives. Default: background, border, shadow."""
        style = self.style
        size = self.size
        if size.is_empty:
            return

        dpr = ctx.pixel_ratio
        x, y = absolute.x * dpr, absolute.y * dpr
        w, h = size.width * dpr, size.height * dpr
        radii = tuple(r * dpr for r in style.corner_radius)
        dl = ctx.display_list

        if style.shadow is not None and style.background is not None:
            sh = style.shadow
            dl.add_shadow(
                x,
                y,
                w,
                h,
                blur=sh.blur * dpr,
                offset=(sh.offset_x * dpr, sh.offset_y * dpr),
                color=(0.0, 0.0, 0.0, sh.opacity),
                radii=radii,  # type: ignore[arg-type]
                clip=ctx.clip,
                clip_radii=ctx.clip_radii,
            )

        if style.background is None:
            return

        border = style.border
        dl.add_box(
            x,
            y,
            w,
            h,
            token=self._token(ctx, style.background),
            color=(1.0, 1.0, 1.0, 1.0),
            radii=radii,  # type: ignore[arg-type]
            border_width=(border.width * dpr) if border else 0.0,
            border_token=self._token(ctx, border.color) if border else NO_TOKEN,
            border_color=(1.0, 1.0, 1.0, 1.0),
            clip=ctx.clip,
            clip_radii=ctx.clip_radii,
            opacity=style.opacity,
        )

    @staticmethod
    def _token(ctx: PaintContext, name: str) -> int:
        return NO_TOKEN if name.startswith("#") else ctx.palette.index(name)

    # ------------------------------------------------------------- hit testing

    def absolute_rect(self, origin: Offset | None = None) -> Rect:
        """This element's rect in root coordinates.

        With no *origin* the ancestor chain is walked, so the result really is
        absolute. Passing an origin is the fast path for callers that already
        know it -- paint and hit testing both thread it down the tree.
        """
        if origin is None:
            offset = self.offset
            node = self.parent
            while node is not None:
                offset = offset + node.offset
                node = node.parent
            return Rect.from_offset_size(offset, self.size)
        return Rect.from_offset_size(origin + self.offset, self.size)

    def hit_test(self, x: float, y: float, origin: Offset = OFFSET_ZERO) -> list[Any]:
        """Topmost-first path of elements under the point.

        Children are visited in REVERSE order because later siblings paint on
        top; a naive forward walk would report the wrong target whenever
        anything overlaps.
        """
        absolute = origin + self.offset
        rect = Rect.from_offset_size(absolute, self.size)
        if not rect.contains(x, y):
            return []
        child_origin = self.child_origin(absolute)
        for child in reversed(self.children):
            if isinstance(child, ElementMixin):
                found = child.hit_test(x, y, child_origin)
                if found:
                    return [*found, self]
        return [self]

    def walk_elements(self) -> Iterator[Any]:
        yield self
        for child in self.children:
            if isinstance(child, ElementMixin):
                yield from child.walk_elements()

    def find(self, name: str) -> Any | None:
        """The element with this `name`. Names, not positional ids, are the
        handle a designer writes and application code refers to."""
        return next((e for e in self.walk_elements() if e.name == name), None)

    def find_all(self, class_name: str) -> list[Any]:
        """Every element carrying *class_name*. Classes repeat by design."""
        return [e for e in self.walk_elements() if class_name in e.classes]

    def __repr__(self) -> str:
        label = self.spec.name or self.spec.id
        return f"<{type(self).__name__} {label!r} size={self.size}>"


def element_children(node: LayoutNode) -> list[Any]:
    return [c for c in node.children if isinstance(c, ElementMixin)]

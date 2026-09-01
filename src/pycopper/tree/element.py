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
    _cached: np.ndarray | None
    _cached_origin: Offset | None
    _needs_paint: bool
    _text_engine: TextEngine | None

    def init_element(self, spec: WidgetSpec) -> None:
        self.spec = spec
        self.state = WidgetState()
        self.handlers = {}
        self._effect = None
        self._template = spec.template()
        self._text = spec.text or ""
        self._value_template = spec.value_template()
        self._value = spec.value or ""
        self._cached = None
        self._cached_origin = None
        self._needs_paint = True
        self._text_engine = None

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

    # ------------------------------------------------------------- identity

    @property
    def id(self) -> str:
        return self.spec.id

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
        text_t = self._template
        value_t = self._value_template
        dynamic_text = text_t is not None and not text_t.is_static
        dynamic_value = value_t is not None and not value_t.is_static
        if not (dynamic_text or dynamic_value):
            return

        def refresh() -> None:
            changed = False
            if dynamic_text and text_t is not None:
                rendered = text_t.render(context)
                if rendered != self._text:
                    self._text = rendered
                    changed = True
            if dynamic_value and value_t is not None:
                rendered = value_t.render(context)
                if rendered != self._value:
                    self._value = rendered
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
        for child in self.children:
            if isinstance(child, ElementMixin):
                child.paint(child_ctx, absolute)

        self.paint_focus_ring(ctx, absolute)
        self._cached = ctx.display_list.snapshot(start)
        self._cached_origin = absolute
        self._needs_paint = False

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
        for child in reversed(self.children):
            if isinstance(child, ElementMixin):
                found = child.hit_test(x, y, absolute)
                if found:
                    return [*found, self]
        return [self]

    def walk_elements(self) -> Iterator[Any]:
        yield self
        for child in self.children:
            if isinstance(child, ElementMixin):
                yield from child.walk_elements()

    def find(self, widget_id: str) -> Any | None:
        return next((e for e in self.walk_elements() if e.id == widget_id), None)

    def __repr__(self) -> str:
        return f"<{type(self).__name__} {self.spec.id!r} size={self.size}>"


def element_children(node: LayoutNode) -> list[Any]:
    return [c for c in node.children if isinstance(c, ElementMixin)]

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
from typing import TYPE_CHECKING, Any, Final

import numpy as np

from ..layout import EDGE_ZERO, OFFSET_ZERO, EdgeInsets, Offset, Rect
from ..motion import Animation, Ticker, default_ticker
from ..paint import NO_TOKEN, DisplayList
from ..paint.display_list import Kind
from ..render.atlas import ImageAtlas
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


_DEFAULT_IMAGES: ImageAtlas | None = None


def default_image_atlas() -> ImageAtlas:
    """Process-wide CPU-only atlas for elements built outside an App.

    Mirrors `default_text_engine` exactly, for the same reason: `Image` can
    be laid out and painted (into a CPU-only `DisplayList`) in a unit test
    with no device and no App standing behind it.
    """
    global _DEFAULT_IMAGES
    if _DEFAULT_IMAGES is None:
        _DEFAULT_IMAGES = ImageAtlas()
    return _DEFAULT_IMAGES


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
    images: ImageAtlas = field(default_factory=default_image_atlas)
    pixel_ratio: float = 1.0
    clip: tuple[float, float, float, float] = _NO_CLIP
    clip_radii: tuple[float, float, float, float] = _NO_CLIP


#: M3's disabled treatment: "Container opacity 12%, Content opacity 38%", and
#: both take the `on_surface` role rather than fading their own colour.
DISABLED_CONTAINER: Final = 0.12
DISABLED_CONTENT: Final = 0.38


def _apply_disabled(
    display_list: DisplayList,
    start: int,
    palette: Palette,
    size: Any,
    pixel_ratio: float,
) -> None:
    """Recolour everything a disabled element drew.

    Applied to the display-list slice rather than threaded through every emit
    site, the same mechanism the overlay fade uses -- one vectorised numpy pass
    in one place, and it catches a cached subtree spliced in whole.

    M3 does not fade a disabled control's own colours; it **replaces** them with
    `on_surface` at 12% for the container and 38% for the content. Container is
    identified as a box covering the element's own bounds, which distinguishes a
    button's filled container from a radio's dot or a switch's thumb -- content
    that happens to be drawn as a box and would be near-invisible at 12%.
    """
    view = display_list.view[start:]
    if len(view) == 0:
        return
    token = palette.index("on_surface")
    width = size.width * pixel_ratio
    height = size.height * pixel_ratio
    covers = (np.abs(view["rect"][:, 2] - width) < 0.5) & (
        np.abs(view["rect"][:, 3] - height) < 0.5
    )
    alpha = np.where(covers, DISABLED_CONTAINER, DISABLED_CONTENT).astype(np.float32)

    view["fill"][:, 3] = alpha
    view["flags"][:, 2] = token
    has_border = view["flags"][:, 3] != NO_TOKEN
    view["border"][:, 3] = np.where(has_border, alpha, view["border"][:, 3])
    view["flags"][:, 3] = np.where(has_border, token, view["flags"][:, 3])


#: Antialiasing reaches about 1.5px past a shape's own rect (the vertex stage
#: pads by exactly that), so the measured extent is grown a little before it is
#: trusted. Cheaper than being wrong at a viewport edge.
_AA_PAD: Final = 2.0


def _painted_extent(
    instances: np.ndarray, absolute: Offset, dpr: float
) -> tuple[float, float, float, float]:
    """Bounding box of what a subtree really painted, in physical px, relative
    to `absolute`.

    Measured from the instances rather than inferred from the element's size,
    because the two are not the same thing: a shadow reaches past its box, a
    focus ring sits outside its control, and a child may overflow its parent.
    Deriving the bound from the element's rect would cull all three, and the
    failures would be intermittent -- visible only near a viewport edge.

    A shadow's ink extends past its rect by the blur, so it is padded here by
    the same formula the vertex stage uses for the same reason. Anything else
    gets the antialiasing pad.
    """
    if len(instances) == 0:
        return (0.0, 0.0, 0.0, 0.0)
    rect = instances["rect"]
    pad = np.full(len(instances), _AA_PAD, dtype=np.float64)
    shadows = instances["flags"][:, 0] == Kind.SHADOW
    if shadows.any():
        params = instances["params"][shadows].astype(np.float64)
        pad[shadows] = (
            params[:, 1] * 3.0 + np.maximum(np.abs(params[:, 2]), np.abs(params[:, 3])) + 2.0
        )
    x = rect[:, 0].astype(np.float64)
    y = rect[:, 1].astype(np.float64)
    ox = absolute.x * dpr
    oy = absolute.y * dpr
    return (
        float((x - pad).min()) - ox,
        float((y - pad).min()) - oy,
        float((x + rect[:, 2] + pad).max()) - ox,
        float((y + rect[:, 3] + pad).max()) - oy,
    )


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
    _disabled_template: Template | None
    _disabled: str
    _error_template: Template | None
    _error: str
    _path_template: Template | None
    _path: str
    _cached: np.ndarray | None
    #: Everything the cached slice was built from. Compared whole, because a
    #: cached slice holds *resolved physical geometry* -- if any of these
    #: differs, the instances in it are drawn in the wrong place or at the
    #: wrong size, and nothing downstream will notice.
    _cached_key: tuple[Any, ...] | None
    _needs_paint: bool
    _text_engine: TextEngine | None
    _image_atlas: ImageAtlas | None
    _ticker: Ticker | None
    _animations: dict[str, Animation]
    _hit_overflow: float
    _hit_insets: EdgeInsets | None
    _hit_pad: EdgeInsets | None
    _min_hit: float | None

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
        self._disabled_template = spec.disabled_template()
        self._disabled = spec.disabled or ""
        self._error_template = spec.error_template()
        self._error = spec.error or ""
        self._path_template = spec.path_template()
        self._path = spec.path or ""
        self._cached = None
        self._cached_key = None
        #: Bounding box of everything this subtree actually painted, in
        #: physical px **relative to this element's absolute origin**, with the
        #: pixel ratio it was measured at. Relative so it survives the element
        #: moving, which is the whole point: scrolling moves every row, and the
        #: extent is what lets an off-screen one be skipped without laying a
        #: finger on it. None until the first paint.
        self._paint_extent: tuple[float, float, float, float] | None = None
        self._paint_extent_dpr = 0.0
        #: Whether this element was skipped by the last paint, and whether the
        #: extent it holds is therefore a lower bound rather than the truth.
        #: See `_culled` -- an extent measured while descendants were skipped
        #: describes what survived, not what exists.
        self._skipped = False
        self._extent_partial = False
        self._needs_paint = True
        self._text_engine = None
        self._image_atlas = None
        self._ticker = None
        #: Named animations owned by this element. They survive `update_spec`
        #: with the rest of the runtime state, so a hot reload does not restart
        #: a transition that is mid-flight.
        self._animations = {}
        self._hit_overflow = 0.0
        self._hit_insets = None
        self._read_hit_style()

    def update_spec(self, spec: WidgetSpec) -> None:
        """Adopt a new spec, keeping all runtime state. The reconciler's core
        operation -- this is why editing a view file does not lose focus."""
        self.spec = spec
        self._read_hit_style()
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
        # `disabled:` was missing here: a reload that changed it updated the
        # spec and kept the old value, because only `init_element` read it.
        self._disabled_template = spec.disabled_template()
        if self._disabled_template is None or self._disabled_template.is_static:
            self._disabled = spec.disabled or ""
        self._error_template = spec.error_template()
        if self._error_template is None or self._error_template.is_static:
            self._error = spec.error or ""
        self._path_template = spec.path_template()
        if self._path_template is None or self._path_template.is_static:
            self._path = spec.path or ""
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

    @property
    def image_atlas(self) -> ImageAtlas:
        """The atlas used to decode and pack images during layout and paint.

        Mirrors `text_engine` exactly, and for the same reason: `Image` needs
        an atlas to learn a decoded image's natural size during layout, not
        only to sample it during paint -- `perform_layout` has no
        `PaintContext` to reach `ctx.images` through, the same gap
        `text_engine` exists to close for `measure_text`.
        """
        return self._image_atlas if self._image_atlas is not None else default_image_atlas()

    def set_image_atlas(self, atlas: ImageAtlas) -> None:
        self._image_atlas = atlas
        for child in self.children:
            if isinstance(child, ElementMixin):
                child.set_image_atlas(atlas)

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
    def disabled(self) -> bool:
        """Whether this element itself is marked disabled."""
        return self._disabled.strip().lower() in ("true", "1", "yes")

    @property
    def in_error(self) -> bool:
        """Whether this control is showing an error. Only `TextField` paints it."""
        return self._error.strip().lower() in ("true", "1", "yes")

    @property
    def _ancestor_disabled(self) -> bool:
        node = self.parent
        while node is not None:
            if isinstance(node, ElementMixin) and node.disabled:
                return True
            node = node.parent
        return False

    @property
    def effective_disabled(self) -> bool:
        """Disabled by its own flag *or* by any ancestor's.

        Inherited, so disabling a form section disables the controls inside it
        -- which is the case people actually reach for. Walking the parent
        chain is O(depth), and depth is small; nothing caches it because a
        cached answer would go stale the moment a signal flipped an ancestor.
        """
        return self.disabled or self._ancestor_disabled

    @property
    def supporting(self) -> str:
        """Rendered `supporting_text` binding -- a list item's second line."""
        return self._supporting

    @property
    def path(self) -> str:
        """Rendered `path` binding -- the file an `Image` decodes and shows."""
        return self._path

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
                ("_disabled", self._disabled_template),
                ("_error", self._error_template),
                ("_path", self._path_template),
            )
            if tpl is not None and not tpl.is_static
        ]
        # `mount()` re-binds every element on every hot reload, not only newly
        # created ones (ARCHITECTURE.md 4) -- without disposing the old effect
        # first, a reused element would pick up a second subscription on top
        # of the first, and a session with many reloads would end up with one
        # live, still-firing `Effect` per past reload.
        if self._effect is not None:
            self._effect.dispose()
            self._effect = None
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
        """Release subscriptions and running animations. Called when
        reconciliation drops a node."""
        if self._effect is not None:
            self._effect.dispose()
            self._effect = None
        # A `repeat=True` animation (a caret blink, a spinner sweep) never
        # finishes on its own, so without this the ticker would keep firing
        # it forever after the widget that owns it is gone -- the app would
        # never go idle again for the rest of the process.
        for animation in self._animations.values():
            self.ticker.discard(animation)
        for child in self.children:
            if isinstance(child, ElementMixin):
                child.dispose()

    # ------------------------------------------------------------------ paint

    def _culled(self, ctx: PaintContext, absolute: Offset) -> bool:
        """Whether this subtree can be skipped because it lies outside the clip.

        Virtualised scrolling, and it is a *paint* optimisation rather than a
        different kind of list: the content is still laid out, so scroll
        extents, hit testing and the scrollbar all keep working unchanged. What
        stops happening is building instances the shader would discard anyway
        -- clipping is analytic and in-shader (§5.8), so anything wholly
        outside the clip contributes nothing to the frame. Skipping it is
        exactly equivalent, not an approximation.

        Measured on a 2000-row list in a 600px viewport: 138 ms per scroll
        frame before, because cost tracked the number of rows rather than the
        number visible.

        **Only a clean element is skipped, and that is what makes it safe.**
        The extent is the bounding box of what this subtree really painted last
        time, so it is exact -- but only while the content has not changed. A
        dirty element repaints and re-measures; the alternative would be to
        trust a stale extent, and an element whose content grew off-screen
        would then stay wrongly hidden. Position may change freely, which is
        the case that matters: scrolling moves every row and changes nothing
        about what any of them draws.
        """
        clip = ctx.clip
        if clip[2] <= 0.0 or clip[3] <= 0.0:
            return False  # unclipped: nothing to be outside of
        extent = self._paint_extent
        if extent is None or self._needs_paint:
            return False
        if self._extent_partial:
            # Measured while its own descendants were being skipped, so it
            # describes what survived rather than what is there. Culling
            # against it is circular, and it bites exactly once the list has
            # been scrolled: a Column that painted four rows reports a
            # four-row extent, and at the next scroll position that extent
            # falls outside the viewport and takes the whole list with it.
            # Found by watching a 60-row list paint one instance.
            return False
        if self._paint_extent_dpr != ctx.pixel_ratio:
            return False  # measured at another scale; the numbers do not carry
        dpr = ctx.pixel_ratio
        dx = absolute.x * dpr
        dy = absolute.y * dpr
        return (
            extent[2] + dx <= clip[0]
            or extent[3] + dy <= clip[1]
            or extent[0] + dx >= clip[0] + clip[2]
            or extent[1] + dy >= clip[1] + clip[3]
        )

    def paint(self, ctx: PaintContext, origin: Offset) -> None:
        """Emit this subtree into the display list, back to front.

        A clean subtree whose geometry has not moved is spliced from its cached
        slice -- 0.002 ms per 1000 instances versus 3.27 ms to rebuild (§12.1).

        **Geometry, not just position.** The key used to be the absolute origin
        alone, which made a window resize paint stale frames: a stretched row
        keeps its origin and changes width, so it passed the check and was
        spliced from its old, narrower slice. Rows that happened to shift
        vertically repainted and rows that did not stayed stale, which is why
        the symptom was several different widths in one frame rather than an
        obviously frozen window. Size, pixel ratio and the inherited clip are
        all in the key for the same reason -- each is baked into the instances
        the slice holds.
        """
        absolute = origin + self.offset
        if self._culled(ctx, absolute):
            self._skipped = True
            return
        self._skipped = False

        key = (absolute, self.size, ctx.pixel_ratio, ctx.clip, ctx.clip_radii)
        if not self._needs_paint and self._cached is not None and self._cached_key == key:
            ctx.display_list.extend(self._cached)
            return

        start = len(ctx.display_list)
        outermost_disabled = self.disabled and not self._ancestor_disabled
        self.paint_self(ctx, absolute)
        child_ctx = self.child_paint_context(ctx, absolute)
        child_origin = self.child_origin(absolute)
        partial = False
        for child in self.children:
            if isinstance(child, ElementMixin):
                child.paint(child_ctx, child_origin)
                partial = partial or child._skipped or child._extent_partial
        self._extent_partial = partial
        self.paint_foreground(ctx, absolute)
        if outermost_disabled:
            _apply_disabled(ctx.display_list, start, ctx.palette, self.size, ctx.pixel_ratio)

        self.paint_focus_ring(ctx, absolute)
        self._cached = ctx.display_list.snapshot(start)
        self._cached_key = key
        self._paint_extent = _painted_extent(self._cached, absolute, ctx.pixel_ratio)
        self._paint_extent_dpr = ctx.pixel_ratio
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

    #: Pointer shape this widget asks for when nothing overrides it. `None`
    #: means "no opinion" -- the shape then comes from whatever is underneath.
    CURSOR: str | None = None

    def cursor_at(self, x: float, y: float) -> str | None:
        """Pointer shape over this element at a point, or None for no opinion.

        Takes a position because some widgets want different shapes in
        different regions -- a scroll view is a resize cursor over its thumb
        and nothing over its content.
        """
        if self.style.cursor is not None:
            return str(self.style.cursor)
        if self.effective_disabled:
            # A control that cannot be used should say so before it is clicked.
            return "not-allowed"
        return self.CURSOR

    #: This component's M3 resting elevation level, from the spec's own table.
    #: A view's `elevation:` overrides it. Override `resting_elevation` instead
    #: where the level depends on the variant, as it does for Card and Button.
    RESTING_ELEVATION: int = 0

    @property
    def resting_elevation(self) -> int:
        return self.RESTING_ELEVATION

    @property
    def elevation(self) -> int:
        """The level this element actually sits at.

        M3: elevation "is only used to determine where the component sits in
        relation to other components, including when hovered or focused (which
        usually raises elevation by one level)". The raise applies only to
        something already raised -- a flat filled button growing a shadow on
        hover is not what the spec means, and "usually" is not licence to do it
        everywhere.
        """
        level = self.style.elevation
        if level is None:
            level = self.resting_elevation
        if level > 0 and (self.state.hovered or self.state.focused):
            level = min(5, level + 1)
        return level

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

    def paint_foreground(self, ctx: PaintContext, absolute: Offset) -> None:
        """Emit primitives that belong **above** this element's children.

        `paint_self` runs before them, which is right for a background and
        wrong for anything that must sit over content -- a carousel item's
        label over its image, a scrim under text. Inside the cached range, so
        a clean subtree still splices correctly.
        """

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

    #: Whether this element confines its children to its own rect. A widget
    #: that clips what it paints must clip what it hits too, or a control
    #: scrolled just past the edge would still take clicks it cannot show a
    #: response to.
    CLIPS_CHILDREN: bool = False

    #: Whether a focused instance wants Tab routed to its own `on_key_down`
    #: instead of the dispatcher's default focus-traversal
    #: (`EventDispatcher._dispatch_to_focused` checks this before treating
    #: Tab as "move to the next control" -- Tab is intercepted before ANY
    #: element's own handler runs, so there is no other way for one to see
    #: the keypress at all). `Escape` still defocuses unconditionally, so
    #: trapping Tab this way never traps the keyboard -- Escape, then Tab,
    #: always reaches the next control. `CodeEditor` is the first, and so
    #: far only, user (Tab inserts indentation there).
    CAPTURES_TAB: bool = False

    def _read_hit_style(self) -> None:
        """Lift the two hit-rect properties off the spec, once.

        They are fixed for a given spec -- the stylesheet has already folded in
        by the time an element exists -- so reading them here keeps a pydantic
        attribute chain out of the layout pass, which touches every element
        every time anything resizes. Both are `None` for the overwhelming
        majority of nodes, which makes the check downstream two loads and a
        branch.
        """
        style = self.spec.style
        pad = style.hit_padding
        self._hit_pad = pad if (pad.left or pad.top or pad.right or pad.bottom) else None
        self._min_hit = style.min_hit_size
        if self._hit_pad is None and self._min_hit is None:
            self._hit_insets = None
        else:
            # Not left to the next layout pass: a reload that changes only
            # these two marks paint, not layout, so nothing would refresh them.
            self._refresh_hit_overflow()

    def hit_insets(self) -> EdgeInsets:
        """How far this element's hit rect extends past what it paints.

        Two ways to ask for it, because M3 states the rule two ways. A minimum
        size is the one the spec actually writes -- "at least 48x48dp" -- and
        it stays correct when the control's size changes; padding is for the
        asymmetric cases a minimum cannot express.
        """
        insets = self._hit_pad or EDGE_ZERO
        minimum = self._min_hit
        if minimum is None:
            return insets
        grow_x = max(0.0, (minimum - self.size.width - insets.horizontal) / 2.0)
        grow_y = max(0.0, (minimum - self.size.height - insets.vertical) / 2.0)
        if not grow_x and not grow_y:
            return insets
        return EdgeInsets(
            insets.left + grow_x,
            insets.top + grow_y,
            insets.right + grow_x,
            insets.bottom + grow_y,
        )

    def hit_rect(self, absolute: Offset) -> Rect:
        """The rect this element accepts clicks in, given its absolute origin.

        Reads the insets cached at layout time rather than deriving them: this
        runs for every element the pointer passes over, on every mouse move,
        and recomputing from the style there measured half again the cost of
        the whole hit test.
        """
        insets = self._hit_insets
        if insets is None:
            return Rect.from_offset_size(absolute, self.size)
        return Rect(
            absolute.x - insets.left,
            absolute.y - insets.top,
            self.size.width + insets.horizontal,
            self.size.height + insets.vertical,
        )

    def absolute_hit_rect(self) -> Rect:
        """The hit rect in root coordinates, walking the ancestor chain."""
        offset = self.offset
        node = self.parent
        while node is not None:
            offset = offset + node.offset
            node = node.parent
        return self.hit_rect(offset)

    def _refresh_hit_overflow(self) -> None:
        """Publish how far this element's hit rect reaches past what it paints.

        Hit testing used to stop at any element that did not contain the point,
        which is correct only while a hit rect never leaves its parent. Now one
        can, so each ancestor needs to descend into a region wider than itself
        -- and recomputing that union on every pointer move would put an O(n)
        walk on the most frequent event there is.

        So the reach is pushed *up* at layout time instead, and only by the few
        elements that ask for an enlarged target. An element with neither
        property does two attribute loads and stops, which is what keeps this
        off the layout budget of a tree that does not use the feature.

        The published figure only ever needs to be an **upper bound**: too
        large wastes a little recursion, and acceptance is still tested against
        exact rects. That is what makes it safe to grow a value up the ancestor
        chain and never shrink it, rather than tracking invalidation for a
        property that changes about as often as a view file is edited.
        """
        if self._hit_pad is None and self._min_hit is None:
            return
        insets = self.hit_insets()
        self._hit_insets = insets
        reach = max(insets.left, insets.top, insets.right, insets.bottom)
        node = self.parent
        while isinstance(node, ElementMixin) and node._hit_overflow < reach:
            node._hit_overflow = reach
            node = node.parent

    def layout(self, constraints: Any, *, parent_uses_size: bool = True) -> Any:
        size = super().layout(constraints, parent_uses_size=parent_uses_size)  # type: ignore[misc]
        self._refresh_hit_overflow()
        return size

    def _layout_without_resize(self) -> None:
        # A relayout boundary never goes through `layout`, so without this a
        # subtree relayout would leave a target it just resized unpublished.
        super()._layout_without_resize()  # type: ignore[misc]
        self._refresh_hit_overflow()

    def hit_test(self, x: float, y: float, origin: Offset = OFFSET_ZERO) -> list[Any]:
        """Topmost-first path of elements under the point.

        Children are visited in REVERSE order because later siblings paint on
        top; a naive forward walk would report the wrong target whenever
        anything overlaps. That ordering is also what resolves two enlarged hit
        rects that overlap each other: the one drawn on top takes the point.
        """
        absolute = origin + self.offset
        rect = self.hit_rect(absolute)
        inside = rect.contains(x, y)
        if not inside:
            # The widened descent region, built only when there is one: a tree
            # that asks for no enlarged targets takes exactly the branch it did
            # before hit and paint rects were split.
            overflow = self._hit_overflow
            if not overflow or self.CLIPS_CHILDREN:
                return []
            if not (
                rect.x - overflow <= x < rect.right + overflow
                and rect.y - overflow <= y < rect.bottom + overflow
            ):
                return []
        child_origin = self.child_origin(absolute)
        for child in reversed(self.children):
            if isinstance(child, ElementMixin):
                found = child.hit_test(x, y, child_origin)
                if found:
                    return [*found, self]
        # Not `[self]` unconditionally: the point may be in the widened descent
        # region and outside this element's own rect, which is a miss for it
        # even though a child could have claimed it.
        return [self] if inside else []

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

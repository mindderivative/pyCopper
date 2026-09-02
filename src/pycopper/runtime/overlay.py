"""The overlay layer: content that renders above the tree.

Six M3 components -- Dialog, Menu, Tooltip, Snackbar, and both Sheet types --
share one requirement the four-tree model cannot otherwise express: they must
render **above** everything, positioned independently of whatever opened them
and clipped by nothing.

Overlays are therefore declared in a top-level ``overlays:`` list rather than
hoisted out of the widget tree. A dialog is not laid out or clipped by the
button that opened it, so declaring it as that button's child would be a lie
about the geometry -- and would leave the parent's Flex trying to reserve space
for something that floats.

The host owns its own layout and paint pass, run after the main tree's, and is
consulted **first** during hit testing because it is on top.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Final

from ..layout import OFFSET_ZERO, Constraints, Offset, Rect, Size
from ..paint import DisplayList
from ..spec import WidgetSpec
from ..theme import Palette

__all__ = ["SCRIM_OPACITY", "OverlayEntry", "OverlayHost"]

#: M3: modal surfaces sit behind a 32% scrim.
SCRIM_OPACITY: Final = 0.32

#: Keep an overlay this far inside the window edge.
MARGIN: Final = 8.0

#: M3's own easing/duration pairs, from the "suggested pairs" table:
#: "Emphasized decelerate | 400ms | Enter the screen" and
#: "Emphasized accelerate | 200ms | Exit the screen". A thing arrives gently
#: and departs briskly, which is why the two are not symmetric.
ENTER_DURATION: Final = "medium4"
ENTER_CURVE: Final = "emphasized_decelerate"
EXIT_DURATION: Final = "short4"
EXIT_CURVE: Final = "emphasized_accelerate"


@dataclass(slots=True)
class OverlayEntry:
    """One declared overlay and its resolved position."""

    element: Any
    origin: Offset = OFFSET_ZERO

    @property
    def spec(self) -> WidgetSpec:
        spec: WidgetSpec = self.element.spec
        return spec

    @property
    def showing(self) -> bool:
        """Whether the application wants this overlay up."""
        return bool(self.element.is_open)

    @property
    def opacity(self) -> float:
        """Fade level, advanced by the element's own animation clock."""
        target = 1.0 if self.showing else 0.0
        entering = target > 0.0
        value: float = self.element.animated(
            "overlay_opacity",
            target,
            duration=ENTER_DURATION if entering else EXIT_DURATION,
            curve=ENTER_CURVE if entering else EXIT_CURVE,
        )
        return value

    @property
    def visible(self) -> bool:
        return bool(self.element.is_open)

    @property
    def modal(self) -> bool:
        return bool(self.element.style.modal)

    @property
    def scrim(self) -> bool:
        return bool(self.element.style.scrim)

    @property
    def dismissable(self) -> bool:
        return bool(self.element.style.dismissable)

    @property
    def placement(self) -> str:
        """Resolved placement -- see `ElementMixin.resolved_placement`."""
        return str(self.element.resolved_placement)

    @property
    def key(self) -> str:
        """Stable handle for dismissal tracking: the name if given, else the
        positional id."""
        key: str = self.element.name or self.element.id
        return key

    def rect(self) -> Rect:
        return Rect.from_offset_size(self.origin, self.element.size)


def _fade(display_list: DisplayList, start: int, opacity: float) -> None:
    """Scale the alpha of everything an overlay just emitted.

    Applied to the display-list slice rather than threaded through the paint
    context, because that keeps subtree opacity in one place instead of
    obliging every emit site to multiply. The display list is a numpy
    structured array, so this is a single vectorised pass over a view -- and it
    catches cached subtrees spliced in at full alpha, which a context flag
    would have missed.
    """
    view = display_list.view[start:]
    if len(view) == 0:
        return
    view["fill"][:, 3] *= opacity
    view["border"][:, 3] *= opacity


class OverlayHost:
    """Owns every overlay: layout, paint, hit testing, and dismissal."""

    __slots__ = ("_dismissed", "entries")

    def __init__(self) -> None:
        self.entries: list[OverlayEntry] = []
        #: Ids dismissed by a click-outside or Escape. Cleared when the
        #: application reopens them, so a signal-driven overlay still wins.
        self._dismissed: set[str] = set()

    # ------------------------------------------------------------- lifecycle

    def build(
        self,
        specs: tuple[WidgetSpec, ...],
        *,
        text_engine: Any = None,
        ticker: Any = None,
    ) -> None:
        from ..widgets import build_element

        self.entries = []
        for spec in specs:
            element = build_element(spec)
            if text_engine is not None:
                element.set_text_engine(text_engine)
            # Without this an overlay animates against the process-wide default
            # ticker, which the App never advances -- so its fade never moved.
            if ticker is not None:
                element.set_ticker(ticker)
            self.entries.append(OverlayEntry(element))
        self._dismissed.clear()

    def bind(self, context: dict[str, Any]) -> None:
        for entry in self.entries:
            for element in entry.element.walk_elements():
                element.bind(context)

    def elements(self) -> list[Any]:
        """Every element in every overlay, for handler resolution."""
        return [e for entry in self.entries for e in entry.element.walk_elements()]

    def find(self, name: str) -> Any | None:
        for entry in self.entries:
            if entry.element.name == name:
                return entry.element
            found = entry.element.find(name)
            if found is not None:
                return found
        return None

    # -------------------------------------------------------------- visibility

    def visible(self) -> list[OverlayEntry]:
        """Overlays that are **interactive**, bottom to top.

        Deliberately excludes one that is fading out. A dialog the user has
        just dismissed must stop swallowing clicks the moment it is dismissed,
        not 200ms later -- so hit testing, modality and dismissal all read this
        list, while layout and paint read `rendered()`.
        """
        return [e for e in self.entries if e.showing and e.key not in self._dismissed]

    def rendered(self) -> list[OverlayEntry]:
        """Overlays that must be **drawn**: the interactive ones, plus any
        still fading out. Declaration order is z-order."""
        live = {id(e) for e in self.visible()}
        return [e for e in self.entries if id(e) in live or e.opacity > 0.0]

    @property
    def has_modal(self) -> bool:
        return any(e.modal for e in self.visible())

    def dismiss(self, entry: OverlayEntry) -> None:
        if entry.dismissable:
            self._dismissed.add(entry.key)
            entry.element.mark_needs_paint()

    def dismiss_top(self) -> bool:
        """Dismiss the topmost dismissable overlay. Returns whether one closed."""
        for entry in reversed(self.visible()):
            if entry.dismissable:
                self.dismiss(entry)
                return True
        return False

    def reopen(self, entry: OverlayEntry) -> None:
        self._dismissed.discard(entry.key)

    def sync_dismissals(self) -> None:
        """Forget dismissals for overlays the application has closed itself.

        Without this, an overlay closed by clicking outside could never be
        reopened by its signal: the dismissal would outlive the state change.
        """
        self._dismissed &= {e.key for e in self.entries if e.visible}

    # ------------------------------------------------------------------ layout

    def layout(self, window: Size, root: Any) -> None:
        """Size and place every visible overlay against the window."""
        self.sync_dismissals()
        for entry in self.rendered():
            element = entry.element
            element.layout(Constraints.loose(window))
            entry.origin = self._place(entry, window, root)

    def _place(self, entry: OverlayEntry, window: Size, root: Any) -> Offset:
        style = entry.element.style
        size = entry.element.size
        placement = entry.placement
        #: A docked overlay (a sheet) is flush with its edge; a floating one
        #: (snackbar, menu, tooltip) keeps clear of it.
        margin = 0.0 if entry.element.DOCKED else MARGIN

        if placement == "anchor" and style.anchor:
            return self._anchored(entry, window, root)
        if placement == "top":
            return Offset((window.width - size.width) / 2, margin)
        if placement == "bottom":
            return Offset((window.width - size.width) / 2, window.height - size.height - margin)
        if placement == "left":
            return Offset(margin, (window.height - size.height) / 2)
        if placement == "right":
            return Offset(window.width - size.width - margin, (window.height - size.height) / 2)
        return Offset((window.width - size.width) / 2, (window.height - size.height) / 2)

    def _anchored(self, entry: OverlayEntry, window: Size, root: Any) -> Offset:
        """Below the anchor, flipping above it when it would overflow.

        A menu that runs off the bottom of the window is useless, so the flip
        is part of anchoring rather than something the caller must handle.
        """
        style = entry.element.style
        size = entry.element.size
        target = root.find(style.anchor) if root is not None else None
        if target is None:
            return Offset((window.width - size.width) / 2, MARGIN)

        rect = target.absolute_rect()
        x = min(max(MARGIN, rect.x), max(MARGIN, window.width - size.width - MARGIN))
        below = rect.bottom + style.offset
        if below + size.height <= window.height - MARGIN:
            return Offset(x, below)
        above = rect.y - style.offset - size.height
        if above >= MARGIN:
            return Offset(x, above)
        return Offset(x, max(MARGIN, window.height - size.height - MARGIN))

    # ------------------------------------------------------------------- paint

    def paint(self, ctx: Any, palette: Palette, window: Size) -> int:
        """Paint scrims and overlays above the main tree. Returns the count."""
        from ..tree.element import PaintContext

        painted = 0
        for entry in self.rendered():
            opacity = entry.opacity
            if opacity <= 0.0:
                continue
            start = len(ctx.display_list)
            if entry.scrim:
                self._paint_scrim(ctx, palette, window)
            child_ctx = PaintContext(
                display_list=ctx.display_list,
                palette=ctx.palette,
                text=ctx.text,
                pixel_ratio=ctx.pixel_ratio,
            )
            entry.element.offset = entry.origin
            entry.element.paint(child_ctx, OFFSET_ZERO)
            if opacity < 1.0:
                _fade(ctx.display_list, start, opacity)
            painted += 1
        return painted

    @staticmethod
    def _paint_scrim(ctx: Any, palette: Palette, window: Size) -> None:
        """M3's 32% backdrop, covering exactly the window.

        Sized to the window rather than an arbitrarily large quad: an oversized
        rect wastes fill rate and pushes the SDF far from the origin, where
        float precision is worse.
        """
        dpr = ctx.pixel_ratio
        display_list: DisplayList = ctx.display_list
        display_list.add_box(
            0.0,
            0.0,
            window.width * dpr,
            window.height * dpr,
            token=palette.index("scrim"),
            color=(1.0, 1.0, 1.0, SCRIM_OPACITY),
        )

    # -------------------------------------------------------------- hit testing

    def hit_path(self, x: float, y: float) -> list[Any]:
        """Topmost overlay path under the point, or empty."""
        for entry in reversed(self.visible()):
            entry.element.offset = entry.origin
            found = entry.element.hit_test(x, y, OFFSET_ZERO)
            if found:
                return list(found)
        return []

    def entry_at(self, x: float, y: float) -> OverlayEntry | None:
        for entry in reversed(self.visible()):
            if entry.rect().contains(x, y):
                return entry
        return None

    def handle_press(self, x: float, y: float) -> bool:
        """Returns True when the press was consumed by the overlay layer.

        A click inside an overlay belongs to it. A click outside a *modal*
        overlay is swallowed and dismisses it if allowed -- it must never reach
        the blocked tree beneath.
        """
        for entry in reversed(self.visible()):
            if entry.rect().contains(x, y):
                return True
            if entry.modal:
                self.dismiss(entry)
                return True
            if entry.dismissable and entry.placement == "anchor":
                self.dismiss(entry)
        return self.has_modal

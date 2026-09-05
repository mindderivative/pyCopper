"""M3 Slider: a value picked from a range by dragging, clicking, or the keyboard.

Standard variant, XS size -- M3's own stated default (`COMPONENT_SLIDERS.md`'s
size table: XS is "existing default"; S/M/L/XL are M3 Expressive additions,
same shape as `Fab`'s own small/standard/medium/large ladder). Discrete
(stop indicators) and Range (two handles) are real M3 variants, deliberately
out of scope for this pass -- each is a materially separate widget shape, not
a style tweak on this one.

**This is the one gap that mattered most.** `SpinBox` (`material.py`) was
built once already citing this same page ("Icon buttons placed outside the
slider should have the button role"), but the actual slider -- the thing
with a track and a draggable handle -- was never built. Nothing here is
therefore inferred; every behaviour quoted below is the page's own words.

**Anatomy, XS (`COMPONENT_SLIDERS.md`'s own measurement table):** 16dp track
height, 8dp track corner radius, a 4dp-wide by 44dp-tall handle -- taller
than the track by design ("A handle changes shape when it's being pressed or
dragged"; M3's visual refresh gave it "a vertical handle that narrows when
pressed", not a circular thumb the way `Switch`'s handle is one). Colour
roles are not fully specified in the scraped tokens table (an interactive
image, not text -- the same gap `CircularProgress`'s own default diameter
has), so this reuses M3's own established selection-control pairing directly:
`primary` for the active track and the handle, `secondary_container` for the
inactive track -- the identical role `Chip`/`Segment` already use for
"filled and selected".

**All three named M3 behaviours are implemented, not just one:**

* **"Select & drag"**: `on_pointer_down` jumps to the press position and
  starts a drag; `on_pointer_move` (while pressed) keeps committing the
  value under the pointer -- "the handle drags smoothly", and per "Changes
  made with sliders must take effect immediately", not only on release.
* **"Select jump"**: the same `on_pointer_down` -- M3 describes this as a
  separate interaction ("Select a value by selecting part of the track") but
  it is the identical first frame of a drag here, not a second code path.
* **"Select & arrow"**: `on_key_down` -- Left/Down decrement, Right/Up
  increment, both by `style.step`; Home/End jump to the bound minimum/
  maximum, exactly the page's own keyboard table.

`value:` is the current number, read through the same generic `number`
property every other value-bearing widget uses (`ElementMixin.number`).
`style.min`/`max` bound it, falling back to 0.0/1.0 when unset (see
`StyleSpec.min`'s own docstring for why that differs from `SpinBox`'s
"unbounded" convention); `style.step` is the same field `SpinBox` already
has, and defaults identically. `on_change` fires with the value already
clamped and snapped to the nearest step -- the same split `SpinBox._step`
and `TextField._commit` already make between updating the display and
telling the application what changed.

**Deliberately out of scope for this pass**, matching M3's own "optional"
anatomy: the value indicator (a label that appears above the handle while
dragging), stop indicators, the inset icon, and vertical orientation.
"""

from __future__ import annotations

from typing import Any, Final

from ..layout import Constraints, EdgeInsets, Padding, Size
from ..runtime.events import ChangeEvent, EventType
from ..spec import WidgetSpec
from ..tree.element import PaintContext
from .base import _StyledMixin
from .material import _box, _state_alpha

__all__ = ["SliderElement"]


class SliderElement(_StyledMixin, Padding):
    """M3 Slider, Standard variant, XS size. See the module docstring."""

    TRACK_HEIGHT: Final = 16.0
    TRACK_RADIUS: Final = 8.0
    HANDLE_WIDTH: Final = 4.0
    HANDLE_HEIGHT: Final = 44.0
    HANDLE_RADIUS: Final = 2.0
    #: The halo a hover/press/focus state layer draws around the handle --
    #: not an M3-quoted figure (the state-layer table gives opacities, not a
    #: size), chosen generously enough to read as a real affordance without
    #: implying a bigger hit area than the handle itself has.
    STATE_LAYER_SIZE: Final = 32.0
    #: No M3 figure for a bare slider's own minimum width either; matches
    #: `TextField.MIN_WIDTH`'s own reasoning -- enough room for the handle to
    #: travel visibly rather than sitting on top of itself.
    MIN_WIDTH: Final = 120.0
    CURSOR = "pointer"

    def __init__(self, spec: WidgetSpec) -> None:
        Padding.__init__(self, None, EdgeInsets())
        self.init_element(spec)

    # ------------------------------------------------------------- bounds

    def _bounds(self) -> tuple[float, float]:
        style = self.style
        lo = style.min if style.min is not None else 0.0
        hi = style.max if style.max is not None else 1.0
        return (lo, hi) if hi > lo else (lo, lo + 1.0)

    def _clamped(self, value: float) -> float:
        lo, hi = self._bounds()
        step = self.style.step
        snapped = round((value - lo) / step) * step + lo
        return max(lo, min(hi, snapped))

    def _fraction(self) -> float:
        lo, hi = self._bounds()
        return (max(lo, min(hi, self.number)) - lo) / (hi - lo)

    @staticmethod
    def _format(n: float) -> str:
        return str(int(n)) if n == int(n) else str(n)

    def _commit(self, value: float) -> None:
        formatted = self._format(value)
        if formatted == self._value:
            return
        self._value = formatted
        handler = self.handlers.get("on_change")
        if handler is not None:
            handler(ChangeEvent(EventType.CHANGE, target=self, value=formatted))
        self.mark_needs_paint()

    # -------------------------------------------------------------- layout

    def perform_layout(self, constraints: Constraints) -> Size:
        outer = self.sized(constraints, self.style)
        width = outer.max_width if outer.has_bounded_width else self.MIN_WIDTH
        return outer.constrain(Size(width, self.HANDLE_HEIGHT))

    def _usable_width(self) -> float:
        return float(max(1.0, self.size.width - self.HANDLE_WIDTH))

    def _handle_x(self) -> float:
        return self._fraction() * self._usable_width()

    # ------------------------------------------------------------- pointer

    def _value_at(self, x: float) -> float:
        rect = self.absolute_rect()
        local = x - rect.x - self.HANDLE_WIDTH / 2
        fraction = max(0.0, min(1.0, local / self._usable_width()))
        lo, hi = self._bounds()
        return self._clamped(lo + fraction * (hi - lo))

    def on_pointer_down(self, event: Any) -> None:
        if self.effective_disabled:
            return
        self.state.data["slider_dragging"] = True
        event.capture()
        self._commit(self._value_at(event.x))

    def on_pointer_move(self, event: Any) -> None:
        if self.effective_disabled or not self.state.data.get("slider_dragging"):
            return
        self._commit(self._value_at(event.x))

    def on_pointer_up(self, event: Any) -> None:
        self.state.data["slider_dragging"] = False

    # ---------------------------------------------------------------- keys

    def on_key_down(self, event: Any) -> None:
        if self.effective_disabled:
            return
        key = str(getattr(event, "key", "")).lower()
        lo, hi = self._bounds()
        step = self.style.step
        if key in ("arrowleft", "left", "arrowdown", "down"):
            self._commit(self._clamped(self.number - step))
        elif key in ("arrowright", "right", "arrowup", "up"):
            self._commit(self._clamped(self.number + step))
        elif key == "home":
            self._commit(lo)
        elif key == "end":
            self._commit(hi)

    # --------------------------------------------------------------- paint

    def paint_self(self, ctx: PaintContext, absolute: Any) -> None:
        style = self.style
        active = ctx.palette.index(style.background or "primary")
        inactive = ctx.palette.index("secondary_container")
        track_y = absolute.y + (self.size.height - self.TRACK_HEIGHT) / 2
        handle_x = absolute.x + self._handle_x()

        # Inactive track first, full width, so the active segment painted
        # over it never has to account for what it's covering.
        _box(
            ctx,
            absolute.x,
            track_y,
            self.size.width,
            self.TRACK_HEIGHT,
            token=inactive,
            radius=self.TRACK_RADIUS,
        )
        active_width = handle_x + self.HANDLE_WIDTH / 2 - absolute.x
        if active_width > 0.0:
            _box(
                ctx,
                absolute.x,
                track_y,
                active_width,
                self.TRACK_HEIGHT,
                token=active,
                radius=self.TRACK_RADIUS,
            )

        alpha = _state_alpha(self)
        if alpha > 0.001:
            halo = self.STATE_LAYER_SIZE
            _box(
                ctx,
                handle_x + self.HANDLE_WIDTH / 2 - halo / 2,
                absolute.y + self.size.height / 2 - halo / 2,
                halo,
                halo,
                token=active,
                radius=halo / 2,
                alpha=alpha,
            )

        _box(
            ctx,
            handle_x,
            absolute.y + (self.size.height - self.HANDLE_HEIGHT) / 2,
            self.HANDLE_WIDTH,
            self.HANDLE_HEIGHT,
            token=active,
            radius=self.HANDLE_RADIUS,
        )

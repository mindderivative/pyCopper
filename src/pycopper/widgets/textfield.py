"""M3 Text field: the one widget that takes typing.

Everything else in the catalogue reads state and paints it. This one *owns*
state, which is why the editing rules live in `text/editing.py` where they can
be tested without a window, and this file is about the parts that genuinely
need pixels: where the label sits, what the caret does, and how the view
scrolls to keep the caret visible.

Dimensions are quoted from M3_COMPONENT_SPECS.md 5.8 and COMPONENT_TEXT_FIELDS:
a container 56dp high, 16dp left/right padding without icons, 8dp top/bottom,
4dp corner radius, a 1dp indicator that becomes 2dp when focused, and
supporting text 4dp below the container. The label "floats upward to 12sp
typography scale when focused or populated" -- quoted, and the reason the two
label sizes here are `body-large` and `body-small` rather than chosen numbers.

Those figures happen to tile the container exactly, which is worth stating
because it is the whole vertical layout: 8dp padding, a 16dp floated label
line, a 24dp input line, 8dp padding. 8 + 16 + 24 + 8 = 56.
"""

from __future__ import annotations

from typing import Any, Final

from ..layout import Constraints, EdgeInsets, Offset, Padding, Size
from ..runtime.clipboard import clipboard
from ..runtime.events import ChangeEvent, EventType, is_accelerator, modifiers_of
from ..spec import WidgetSpec
from ..spec.typescale import TYPE_SCALE
from ..text.editing import (
    Editor,
    delete_backward,
    delete_forward,
    insert,
    move,
    word_bounds,
)
from ..text.selection import caret_at, index_at, rects_for
from ..tree.element import PaintContext
from .base import _StyledMixin, content_token, measure_text, paint_text
from .material import _box, _emit_state_layer

__all__ = ["TextFieldElement"]

#: Key names as `rendercanvas` reports them, lower-cased on arrival. Both the
#: GLFW spelling and the bare one are accepted -- a synthetic event in a test
#: has no reason to know that "ArrowLeft" is what a real window sends.
_MOTIONS: Final = {
    "arrowleft": "left",
    "left": "left",
    "arrowright": "right",
    "right": "right",
    "home": "home",
    "end": "end",
}


class TextFieldElement(_StyledMixin, Padding):
    """M3 Text field, filled or outlined.

    `text:` is the label, `value:` is the content, `supporting_text:` is the
    line beneath. That mapping reuses the fields every other widget already
    has rather than inventing a `label:`, and it puts the content on `value:`
    where a binding can drive it -- `value: "{{ name.get() }}"` makes the field
    controlled, and editing it fires `on_change` with the new text.

    Editing is by grapheme cluster throughout, so a backspace removes an
    accented character rather than its accent.
    """

    HEIGHT: Final = 56.0
    PAD_X: Final = 16.0
    PAD_Y: Final = 8.0
    RADIUS: Final = 4.0
    INDICATOR: Final = 1.0
    INDICATOR_FOCUSED: Final = 2.0
    SUPPORTING_GAP: Final = 4.0
    #: M3 states no minimum width for a text field. 120dp is pyCopper's own
    #: floor, chosen so an unsized field in a Row is still usable rather than
    #: collapsing to its label -- said plainly because it is not sourced.
    MIN_WIDTH: Final = 120.0

    #: "Label Behavior: Floats upward to 12sp typography scale when focused or
    #: populated" -- quoted. 12sp is `body-small`; at rest it matches the input.
    INPUT_ROLE: Final = TYPE_SCALE["body-large"]
    FLOAT_ROLE: Final = TYPE_SCALE["body-small"]

    #: A 2dp caret, matching the focused indicator's weight rather than the
    #: 1dp resting one: a hairline caret disappears against text at this size.
    CARET_WIDTH: Final = 2.0
    #: One second per blink, half of it visible. The convention every desktop
    #: toolkit uses; M3 does not specify a caret at all.
    BLINK_PERIOD: Final = 1.0
    SELECTION_ALPHA: Final = 0.30

    CURSOR = "text"

    def __init__(self, spec: WidgetSpec) -> None:
        Padding.__init__(self, None, EdgeInsets())
        self.init_element(spec)
        self._editor = Editor(spec.value or "")
        #: The last value seen from the spec or a binding. An edit updates it
        #: too, so the widget can tell "the application changed this" from "I
        #: changed this" without a controlled/uncontrolled flag.
        self._external = spec.value or ""
        self._scroll_x = 0.0

    def configure(self) -> None:
        self._adopt_external()

    # ---------------------------------------------------------------- state

    def _adopt_external(self) -> None:
        """Take the bound `value:` if the application has moved it."""
        if self._value != self._external:
            self._external = self._value
            self._editor.set_text(self._value)
            self._scroll_x = 0.0

    @property
    def editor(self) -> Editor:
        self._adopt_external()
        return self._editor

    @property
    def content(self) -> str:
        return self.editor.text

    @property
    def floated(self) -> bool:
        """Whether the label sits above the input rather than in it."""
        return bool(self.content) or self.state.focused

    @property
    def label(self) -> str:
        return self._text.strip()

    def _commit(self, changed: bool) -> None:
        """Publish an edit: mirror it onto `value:` and fire `on_change`."""
        if changed:
            self._value = self._editor.text
            self._external = self._editor.text
            handler = self.handlers.get("on_change")
            if handler is not None:
                handler(ChangeEvent(EventType.CHANGE, target=self, value=self._editor.text))
        self._scroll_to_caret()
        self.mark_needs_paint()

    # --------------------------------------------------------------- layout

    def _inner_width(self) -> float:
        return max(0.0, float(self.size.width) - 2 * self.PAD_X)

    def _paragraph(self) -> Any:
        """The input text, laid out unwrapped.

        A text field is one line: `max_width=None` so a long value scrolls
        sideways instead of wrapping into a box that cannot show it.
        """
        return self.text_engine.layout(
            self.content,
            px=self.INPUT_ROLE.size,
            tracking=self.INPUT_ROLE.tracking,
            line_height=self.INPUT_ROLE.line_height,
        )

    def _supporting_height(self) -> float:
        if not self._supporting.strip():
            return 0.0
        return self.SUPPORTING_GAP + self.FLOAT_ROLE.line_height

    def perform_layout(self, constraints: Constraints) -> Size:
        outer = self.sized(constraints, self.style)
        width = outer.max_width if outer.has_bounded_width else self.MIN_WIDTH
        width = max(width, min(self.MIN_WIDTH, outer.max_width))
        return outer.constrain(Size(width, self.HEIGHT + self._supporting_height()))

    # ---------------------------------------------------------------- paint

    def _text_origin(self) -> Offset:
        """Top-left of the input text, relative to the element."""
        return Offset(self.PAD_X, self.PAD_Y + self.FLOAT_ROLE.line_height)

    def _scroll_to_caret(self) -> None:
        """Keep the caret in view, and never scroll past the text.

        Both halves matter: without the first the caret walks off the end of a
        long value, and without the second deleting from the end leaves the
        field showing empty space where the text used to be.
        """
        para = self._paragraph()
        inner = self._inner_width()
        caret = caret_at(para, self.editor.state.caret).x
        if caret - self._scroll_x > inner:
            self._scroll_x = caret - inner
        if caret - self._scroll_x < 0.0:
            self._scroll_x = caret
        self._scroll_x = max(0.0, min(self._scroll_x, max(0.0, para.size.width - inner)))

    def _inner_context(self, ctx: PaintContext, absolute: Any) -> PaintContext:
        """A context clipping to the input area, for the text and the caret.

        In-shader clipping, like everything else that clips: the display list
        is one instanced draw call and a scissor rect would break the batch.
        """
        dpr = ctx.pixel_ratio
        origin = self._text_origin()
        return PaintContext(
            display_list=ctx.display_list,
            palette=ctx.palette,
            text=ctx.text,
            pixel_ratio=dpr,
            clip=(
                (absolute.x + self.PAD_X) * dpr,
                (absolute.y + origin.y) * dpr,
                self._inner_width() * dpr,
                self.INPUT_ROLE.line_height * dpr,
            ),
            clip_radii=(0.0, 0.0, 0.0, 0.0),
        )

    def _accent(self, ctx: PaintContext) -> int:
        """The token that says what state the field is in."""
        if self.in_error:
            return ctx.palette.index("error")
        if self.state.focused:
            return ctx.palette.index("primary")
        return ctx.palette.index("on_surface_variant")

    def paint_self(self, ctx: PaintContext, absolute: Any) -> None:
        style = self.style
        outlined = style.variant == "outlined"
        width = self.size.width
        focused = self.state.focused
        stroke = self.INDICATOR_FOCUSED if focused else self.INDICATOR
        accent = self._accent(ctx)
        on_surface = content_token(ctx, style, "on_surface")

        if outlined:
            _box(
                ctx,
                absolute.x + stroke / 2,
                absolute.y + stroke / 2,
                width - stroke,
                self.HEIGHT - stroke,
                token=ctx.palette.index("surface"),
                radius=self.RADIUS,
                alpha=0.0,
                border_width=stroke,
                border_token=accent if (focused or self.in_error) else ctx.palette.index("outline"),
            )
        else:
            # Top corners only: "rounded top corners and square bottom corners"
            # -- the shader takes per-corner radii, so this is still one box.
            dpr = ctx.pixel_ratio
            ctx.display_list.add_box(
                absolute.x * dpr,
                absolute.y * dpr,
                width * dpr,
                self.HEIGHT * dpr,
                token=ctx.palette.index(style.background or "surface_container_highest"),
                color=(1.0, 1.0, 1.0, 1.0),
                radii=(self.RADIUS * dpr, self.RADIUS * dpr, 0.0, 0.0),
                clip=ctx.clip,
                clip_radii=ctx.clip_radii,
            )
            _emit_state_layer(ctx, self, absolute, on_surface, (self.RADIUS, self.RADIUS, 0.0, 0.0))
            _box(
                ctx,
                absolute.x,
                absolute.y + self.HEIGHT - stroke,
                width,
                stroke,
                token=accent,
                radius=0.0,
            )

        self._paint_content(ctx, absolute, on_surface, accent)
        self._paint_label(ctx, absolute, accent, outlined)
        self._paint_supporting(ctx, absolute)

    def _paint_content(
        self, ctx: PaintContext, absolute: Any, on_surface: int, accent: int
    ) -> None:
        origin = self._text_origin()
        inner = self._inner_context(ctx, absolute)
        x = absolute.x + origin.x - self._scroll_x
        y = absolute.y + origin.y
        state = self.editor.state
        para = self._paragraph()

        if state.has_selection:
            low, high = state.selection
            for rect in rects_for(para, low, high):
                _box(
                    inner,
                    x + rect.x,
                    y + rect.y,
                    rect.width,
                    rect.height,
                    token=ctx.palette.index("primary"),
                    radius=0.0,
                    alpha=self.SELECTION_ALPHA,
                )

        if self.content:
            paint_text(inner, x, y, self.content, self.INPUT_ROLE, on_surface)

        if self.state.focused and not self.effective_disabled and self._caret_visible():
            caret = caret_at(para, state.caret)
            _box(
                inner,
                x + caret.x,
                y + caret.y,
                self.CARET_WIDTH,
                caret.height,
                token=accent,
                radius=0.0,
            )

    def _caret_visible(self) -> bool:
        """Half of each blink, or solid when the user has asked for less motion.

        `reduce_motion` makes timed transitions arrive at once everywhere else;
        the equivalent for something that never arrives is to stop it moving.
        A caret that blinked anyway would be the one piece of animation the
        setting did not reach.
        """
        if self.ticker.reduce_motion:
            return True
        phase = self.animated("caret", 1.0, duration=self.BLINK_PERIOD, curve="linear", repeat=True)
        return phase < 0.5

    def _paint_label(self, ctx: PaintContext, absolute: Any, accent: int, outlined: bool) -> None:
        label = self.label
        if not label:
            return
        # One animation drives the size and the height together, so the label
        # cannot be caught half-floated in one and settled in the other.
        t = self.animated("float", 1.0 if self.floated else 0.0, duration="short4")
        size = self.INPUT_ROLE.size + (self.FLOAT_ROLE.size - self.INPUT_ROLE.size) * t
        tracking = (
            self.INPUT_ROLE.tracking + (self.FLOAT_ROLE.tracking - self.INPUT_ROLE.tracking) * t
        )
        resting = (self.HEIGHT - self.INPUT_ROLE.line_height) / 2
        y = resting + (self.PAD_Y - resting) * t
        token = (
            accent
            if (self.state.focused or self.in_error)
            else ctx.palette.index("on_surface_variant")
        )
        metrics = measure_text(
            label, size, engine=self.text_engine, weight=self.INPUT_ROLE.weight, tracking=tracking
        )

        if outlined and t > 0.0:
            # M3 cuts the outline where the label crosses it. The shader draws
            # no notch, so the label gets a patch of the surface behind it --
            # which assumes the field sits on `surface`. Stated rather than
            # hidden: on a tinted container the patch will show.
            _box(
                ctx,
                absolute.x + self.PAD_X - 4.0,
                absolute.y,
                metrics.width + 8.0,
                self.INDICATOR_FOCUSED,
                token=ctx.palette.index("surface"),
                radius=0.0,
                alpha=t,
            )

        paint_text(
            ctx,
            absolute.x + self.PAD_X,
            absolute.y + y,
            label,
            size,
            token,
            weight=self.INPUT_ROLE.weight,
            tracking=tracking,
        )

    def _paint_supporting(self, ctx: PaintContext, absolute: Any) -> None:
        supporting = self._supporting.strip()
        if not supporting:
            return
        token = (
            ctx.palette.index("error") if self.in_error else ctx.palette.index("on_surface_variant")
        )
        paint_text(
            ctx,
            absolute.x + self.PAD_X,
            absolute.y + self.HEIGHT + self.SUPPORTING_GAP,
            supporting,
            self.FLOAT_ROLE,
            token,
        )

    # --------------------------------------------------------------- events

    def _offset_at(self, x: float) -> int:
        rect = self.absolute_rect()
        local = x - rect.x - self.PAD_X + self._scroll_x
        return index_at(self._paragraph(), local, 0.0)

    def on_pointer_down(self, event: Any) -> None:
        if self.effective_disabled:
            return
        offset = self._offset_at(event.x)
        if self.state.data.pop("field_double", False):
            self.editor.select(*word_bounds(self.content, offset))
        else:
            self.editor.set_caret(offset)
        self.state.data["field_anchor"] = self.editor.state.anchor
        event.capture()
        self._commit(False)

    def on_pointer_move(self, event: Any) -> None:
        if self.effective_disabled or "field_anchor" not in self.state.data:
            return
        if event.button or self.state.pressed:
            self.editor.select(int(self.state.data["field_anchor"]), self._offset_at(event.x))
            self._commit(False)

    def on_click(self, event: Any) -> None:
        """Counted, not timed -- the same rule `Text` uses for double-click,
        because there is no wall clock in the event path."""
        self.state.data["field_double"] = not self.state.data.get("field_double", False)

    def on_text(self, event: Any) -> None:
        """Committed characters. Control codes are dropped rather than inserted
        as unprintable glyphs -- a backend that reports Enter as text exists."""
        if self.effective_disabled:
            return
        text = str(getattr(event, "text", ""))
        if not text or text < " ":
            return
        editor = self.editor
        self._commit(editor.edit(insert(editor.state, text), "type"))
        event.stop_propagation()

    def on_key_down(self, event: Any) -> None:
        if self.effective_disabled:
            return
        key = str(getattr(event, "key", "")).lower()
        mods = modifiers_of(event)
        accel = is_accelerator(mods)
        shift = "shift" in mods
        word = "ctrl" in mods or "alt" in mods
        editor = self.editor
        state = editor.state
        handled = True

        if key in _MOTIONS:
            motion = _MOTIONS[key]
            if word and motion in ("left", "right"):
                motion = f"word_{motion}"
            editor.state = move(state, motion, extend=shift)
            self._commit(False)
        elif key == "backspace":
            self._commit(editor.edit(delete_backward(state, word=word), "delete"))
        elif key == "delete":
            self._commit(editor.edit(delete_forward(state, word=word), "delete"))
        elif accel and key == "a":
            editor.state = state.select_all()
            self._commit(False)
        elif accel and key in ("c", "x") and state.has_selection:
            clipboard.set_text(state.selected_text)
            if key == "x":
                self._commit(editor.edit(delete_backward(state), "delete"))
        elif accel and key == "v":
            pasted = clipboard.get_text()
            if pasted:
                self._commit(editor.edit(insert(state, pasted), "paste"))
        elif accel and key == "z" and not shift:
            self._commit(editor.undo())
        elif accel and (key == "y" or (key == "z" and shift)):
            self._commit(editor.redo())
        else:
            handled = False

        if handled:
            event.stop_propagation()

    def on_focus(self, event: Any) -> None:
        self.mark_needs_paint()

    def on_blur(self, event: Any) -> None:
        self.mark_needs_paint()

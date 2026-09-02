"""The editing model: text, a selection, and the operations that change them.

Kept apart from any widget on purpose. Editing is where the fiddly rules live
-- what a backspace removes, where a word ends, when two keystrokes are one
undo step -- and every one of them is testable without a window, a font, or a
GPU. `TextFieldElement` supplies keys and pixels; this supplies the answers.

An :class:`EditState` is immutable, so an operation returns a new one and the
undo stack is a list of states rather than a list of inverse operations. For
the sizes a text field holds that is the cheaper thing as well as the simpler
one: no operation needs an inverse, and no inverse can be subtly wrong.

Offsets are Python string indices, and every one this module produces sits on a
**grapheme cluster** boundary (`segment.py`, UAX #29). Backspacing an accented
character removes the character, not the accent; the caret never lands inside a
flag emoji. Selection made the same promise, and an editor that broke it would
be a different kind of surprise: the text would actually change.
"""

from __future__ import annotations

from dataclasses import dataclass, replace
from typing import Final

from .segment import cluster_boundaries

__all__ = [
    "EditState",
    "Editor",
    "delete_backward",
    "delete_forward",
    "insert",
    "move",
    "word_bounds",
]

#: Where a caret may go. `word_*` use the whitespace rule below.
MOTIONS: Final = frozenset({"left", "right", "word_left", "word_right", "home", "end"})


@dataclass(frozen=True, slots=True)
class EditState:
    """Text plus a selection.

    Two offsets, not a start and a length: `anchor` is where the selection was
    begun and `focus` is where the caret is now, so shift-arrow knows which end
    to move and a backwards selection is representable rather than normalised
    away the moment it is made.
    """

    text: str = ""
    anchor: int = 0
    focus: int = 0

    @property
    def caret(self) -> int:
        return _clamp(self.text, self.focus)

    @property
    def selection(self) -> tuple[int, int]:
        """The selected range, low end first, clamped into the text.

        Clamped because this is a plain dataclass a caller can build with any
        pair of numbers, and every operation below reads the range through
        here. An out-of-range caret that silently deleted nothing would be the
        worst of the available failures: no error, no effect, no clue.
        """
        low = _clamp(self.text, min(self.anchor, self.focus))
        high = _clamp(self.text, max(self.anchor, self.focus))
        return (low, high)

    @property
    def has_selection(self) -> bool:
        return self.anchor != self.focus

    @property
    def selected_text(self) -> str:
        low, high = self.selection
        return self.text[low:high]

    def collapsed(self, offset: int) -> EditState:
        """This state with the caret at *offset* and nothing selected."""
        at = _snap(self.text, offset)
        return replace(self, anchor=at, focus=at)

    def selecting(self, anchor: int, focus: int) -> EditState:
        return replace(self, anchor=_snap(self.text, anchor), focus=_snap(self.text, focus))

    def select_all(self) -> EditState:
        return replace(self, anchor=0, focus=len(self.text))


def _clamp(text: str, offset: int) -> int:
    return max(0, min(offset, len(text)))


def _snap(text: str, offset: int) -> int:
    """Clamp *offset* into the text and onto a grapheme boundary."""
    if not text:
        return 0
    offset = max(0, min(offset, len(text)))
    bounds = cluster_boundaries(text)
    if offset in bounds:
        return offset
    return min(bounds, key=lambda b: (abs(b - offset), b))


def _previous(text: str, offset: int) -> int:
    """The grapheme boundary before *offset*, or 0."""
    previous = [b for b in cluster_boundaries(text) if b < offset]
    return previous[-1] if previous else 0


def _next(text: str, offset: int) -> int:
    """The grapheme boundary after *offset*, or the end."""
    following = [b for b in cluster_boundaries(text) if b > offset]
    return following[0] if following else len(text)


def word_bounds(text: str, offset: int) -> tuple[int, int]:
    """The whitespace-delimited word around *offset*.

    The same rule `selection.word_at` uses for double-click, deliberately: the
    two must agree, or double-clicking a word and then Ctrl-Backspacing it
    would take different amounts of text. It is not UAX #29 word segmentation,
    and saying so is better than implying a Unicode guarantee that is not here.
    """
    if not text:
        return (0, 0)
    offset = max(0, min(offset, len(text)))
    if offset >= len(text) or text[offset].isspace():
        offset = max(0, offset - 1)
    if offset < len(text) and text[offset].isspace():
        return (offset, offset)
    start = offset
    while start > 0 and not text[start - 1].isspace():
        start -= 1
    end = offset
    while end < len(text) and not text[end].isspace():
        end += 1
    return (start, end)


def _word_left(text: str, offset: int) -> int:
    """Start of the word before the caret, skipping any whitespace first."""
    index = offset
    while index > 0 and text[index - 1].isspace():
        index -= 1
    while index > 0 and not text[index - 1].isspace():
        index -= 1
    return index


def _word_right(text: str, offset: int) -> int:
    """End of the word after the caret, skipping any whitespace first."""
    index = offset
    length = len(text)
    while index < length and text[index].isspace():
        index += 1
    while index < length and not text[index].isspace():
        index += 1
    return index


def move(state: EditState, motion: str, *, extend: bool = False) -> EditState:
    """Move the caret. ``extend`` keeps the anchor, which is shift-arrow.

    Without ``extend``, a horizontal move out of a selection lands on the
    *edge* rather than moving from the caret -- press Right with three words
    selected and the caret goes to the end of them, not one character past
    wherever the caret happened to be. Every editor does this, and it is
    invisible until it is missing.
    """
    if motion not in MOTIONS:
        raise ValueError(f"unknown motion {motion!r}")
    text = state.text
    low, high = state.selection

    if not extend and state.has_selection and motion in ("left", "right"):
        return state.collapsed(low if motion == "left" else high)

    focus = state.focus
    if motion == "left":
        target = _previous(text, focus)
    elif motion == "right":
        target = _next(text, focus)
    elif motion == "word_left":
        target = _word_left(text, focus)
    elif motion == "word_right":
        target = _word_right(text, focus)
    elif motion == "home":
        target = 0
    else:
        target = len(text)

    if extend:
        return state.selecting(state.anchor, target)
    return state.collapsed(target)


def insert(state: EditState, text: str) -> EditState:
    """Insert *text*, replacing the selection if there is one."""
    if not text:
        return state
    low, high = state.selection
    body = state.text[:low] + text + state.text[high:]
    at = low + len(text)
    return EditState(body, at, at)


def delete_backward(state: EditState, *, word: bool = False) -> EditState:
    """Backspace. Deletes the selection if there is one, otherwise one cluster."""
    low, high = state.selection
    if low != high:
        return EditState(state.text[:low] + state.text[high:], low, low)
    if low == 0:
        return state
    start = _word_left(state.text, low) if word else _previous(state.text, low)
    return EditState(state.text[:start] + state.text[low:], start, start)


def delete_forward(state: EditState, *, word: bool = False) -> EditState:
    """Delete. Deletes the selection if there is one, otherwise one cluster."""
    low, high = state.selection
    if low != high:
        return EditState(state.text[:low] + state.text[high:], low, low)
    if high >= len(state.text):
        return state
    end = _word_right(state.text, high) if word else _next(state.text, high)
    return EditState(state.text[:low] + state.text[end:], low, low)


class Editor:
    """An :class:`EditState` with undo and redo around it.

    Typing coalesces: a run of single characters entered one after another is
    one undo step, because undoing a sentence letter by letter is nobody's idea
    of undo. The run breaks when the kind of edit changes, when the caret is
    somewhere the run did not leave it, or when a selection is replaced -- the
    same three rules a text editor uses, and the reason the last kind and the
    expected caret are both tracked rather than just the state.

    A pure caret move is not an edit and is not recorded. Undo restores the
    text *and* the selection, which is what makes an undone deletion leave you
    where you were rather than at the end of the field.
    """

    __slots__ = ("_last_caret", "_last_kind", "_redo", "_undo", "limit", "state")

    def __init__(self, text: str = "", *, limit: int = 200) -> None:
        end = len(text)
        self.state = EditState(text, end, end)
        self._undo: list[EditState] = []
        self._redo: list[EditState] = []
        self._last_kind: str | None = None
        self._last_caret: int = -1
        #: A bounded history: a long-lived field would otherwise keep every
        #: state anyone ever typed into it for the life of the process.
        self.limit = limit

    # ------------------------------------------------------------- content

    @property
    def text(self) -> str:
        return self.state.text

    @property
    def can_undo(self) -> bool:
        return bool(self._undo)

    @property
    def can_redo(self) -> bool:
        return bool(self._redo)

    def set_text(self, text: str) -> None:
        """Replace the content from outside -- a bound `value:` changing.

        Clears the history rather than recording a step. The new text did not
        come from the user, so offering to undo back to what they had typed
        would restore something the application has already moved past.
        """
        if text == self.state.text:
            return
        end = len(text)
        self.state = EditState(text, end, end)
        self._undo.clear()
        self._redo.clear()
        self._last_kind = None

    # --------------------------------------------------------------- edits

    def edit(self, new: EditState, kind: str) -> bool:
        """Adopt *new* as an edit of the given kind. Returns whether text changed.

        `kind` is what decides coalescing, so it is the caller's statement of
        intent rather than something inferred from the diff: two states can
        look alike whether the user typed a letter or pasted one.
        """
        if new.text == self.state.text:
            self.state = new
            return False
        coalesce = (
            kind == "type"
            and self._last_kind == "type"
            and self.state.caret == self._last_caret
            and not self.state.has_selection
        )
        if not coalesce:
            self._undo.append(self.state)
            if len(self._undo) > self.limit:
                del self._undo[0]
        self._redo.clear()
        self.state = new
        self._last_kind = kind
        self._last_caret = new.caret
        return True

    def select(self, anchor: int, focus: int) -> None:
        self.state = self.state.selecting(anchor, focus)
        self._last_kind = None

    def set_caret(self, offset: int) -> None:
        self.state = self.state.collapsed(offset)
        self._last_kind = None

    def undo(self) -> bool:
        if not self._undo:
            return False
        self._redo.append(self.state)
        self.state = self._undo.pop()
        self._last_kind = None
        return True

    def redo(self) -> bool:
        if not self._redo:
            return False
        self._undo.append(self.state)
        self.state = self._redo.pop()
        self._last_kind = None
        return True

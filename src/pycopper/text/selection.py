"""Mapping between points and character offsets in a laid-out paragraph.

Selection needs two questions answered, and they are inverses:

* which character is under this point (placing a caret),
* which rectangles cover this character range (drawing the highlight).

Both are derived from `Paragraph` as it already exists. A `ShapedRun` carries
cluster indices into **its own** text rather than into the paragraph, and no
offset back to it -- but the runs of a line concatenate in order, so walking
them while accumulating `len(run.text)` recovers the paragraph offset without
touching the shaping structures or the shape cache's key.

Advances come from `ShapedRun.advances_px`, the same call the paint pass uses,
so a caret cannot land somewhere the glyphs are not -- letter spacing in
particular has to be in both or neither.

Offsets are snapped to **grapheme cluster** boundaries (`segment.py`, UAX #29),
so a selection edge never lands inside a flag emoji or between a base character
and its combining mark.
"""

from __future__ import annotations

from dataclasses import dataclass

from .layout import Paragraph, TextLine
from .segment import cluster_boundaries

__all__ = [
    "SelectionRect",
    "caret_at",
    "index_at",
    "line_end",
    "line_index_at",
    "rects_for",
    "word_at",
]

#: Hard terminators, as `layout.HARD_BREAK_CHARS` spells them.
_BREAKS = "\n\r\v\f\u2028\u2029\u0085"


@dataclass(frozen=True, slots=True)
class SelectionRect:
    """One highlight rectangle, in the paragraph's own coordinate space."""

    x: float
    y: float
    width: float
    height: float


def line_index_at(para: Paragraph, y: float) -> int:
    """Index of the line containing `y`, clamped to the paragraph."""
    if not para.lines:
        return 0
    top = 0.0
    for index, line in enumerate(para.lines):
        if y < top + line.height:
            return index
        top += line.height
    return len(para.lines) - 1


def line_end(para: Paragraph, line: TextLine) -> int:
    """Where a caret goes at the end of *line*.

    Not `line.end`, which is where the *next* line starts and therefore sits
    after a newline. Pressing End on the first of two lines has to leave the
    caret before the break, or it lands at the start of the line below and
    typing appears on the wrong one.
    """
    end = line.end
    while end > line.start and para.text[end - 1] in _BREAKS:
        end -= 1
    return end


def _snap(text: str, offset: int) -> int:
    """Move an offset to the nearest grapheme boundary."""
    if not text:
        return 0
    bounds = cluster_boundaries(text)
    return min(bounds, key=lambda b: (abs(b - offset), b))


def index_at(para: Paragraph, x: float, y: float) -> int:
    """Character offset nearest the point, snapped to a grapheme boundary.

    The *nearest* edge, not the containing glyph: clicking the left half of a
    character puts the caret before it and the right half after it, which is
    what every text control does and what makes click-and-drag feel right.
    """
    if not para.lines or not para.text:
        return 0
    line = para.lines[line_index_at(para, y)]
    pen = line.x
    char = line.start

    for run in line.runs:
        advances = run.advances_px(para.px, para.tracking)
        for i in range(len(run)):
            advance = float(advances[i])
            if x < pen + advance / 2.0:
                return _snap(para.text, char + int(run.clusters[i]))
            pen += advance
        char += len(run.text)
    return _snap(para.text, line_end(para, line))


def _span_x(line: TextLine, para: Paragraph, start: int, end: int) -> tuple[float, float]:
    """Horizontal extent of `[start, end)` within one line."""
    pen = line.x
    char = line.start
    left: float | None = None
    right = line.x

    for run in line.runs:
        advances = run.advances_px(para.px, para.tracking)
        for i in range(len(run)):
            advance = float(advances[i])
            position = char + int(run.clusters[i])
            if start <= position < end:
                if left is None:
                    left = pen
                right = pen + advance
            pen += advance
        char += len(run.text)
    return (left if left is not None else line.x, right)


def caret_at(para: Paragraph, offset: int) -> SelectionRect:
    """Where a caret sitting *before* `offset` belongs, as a zero-width rect.

    The inverse of `index_at`, and it must walk advances the same way that does
    -- through `ShapedRun.advances_px` -- or clicking would put the caret
    somewhere the caret then would not draw.
    """
    if not para.lines:
        return SelectionRect(0.0, 0.0, 0.0, 0.0)
    top = 0.0
    line = para.lines[0]
    for candidate in para.lines:
        if candidate.start <= offset <= candidate.end:
            line = candidate
            break
        top += candidate.height
    else:
        line = para.lines[-1]
        top -= line.height

    pen = line.x
    char = line.start
    for run in line.runs:
        advances = run.advances_px(para.px, para.tracking)
        for i in range(len(run)):
            if char + int(run.clusters[i]) >= offset:
                return SelectionRect(pen, top, 0.0, line.height)
            pen += float(advances[i])
        char += len(run.text)
    return SelectionRect(pen, top, 0.0, line.height)


def rects_for(para: Paragraph, start: int, end: int) -> list[SelectionRect]:
    """Highlight rectangles covering `[start, end)`, one per line touched.

    Empty when the range is empty -- a caret is not a selection, and drawing a
    zero-width rectangle for one would put a stray sliver on screen.
    """
    lo, hi = min(start, end), max(start, end)
    if lo == hi or not para.lines:
        return []

    rects: list[SelectionRect] = []
    top = 0.0
    for line in para.lines:
        if line.end > lo and line.start < hi:
            left, right = _span_x(line, para, max(lo, line.start), min(hi, line.end))
            if right > left:
                rects.append(SelectionRect(left, top, right - left, line.height))
        top += line.height
    return rects


def word_at(text: str, offset: int) -> tuple[int, int]:
    """The word around an offset, for double-click.

    Whitespace-delimited rather than UAX #29 word segmentation: the boundary
    algorithm is not exposed by the segmentation module, and inventing a
    half-version of it here would be worse than a rule that is simple and
    predictable. Stated plainly rather than presented as Unicode-correct.
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

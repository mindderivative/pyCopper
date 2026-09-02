"""Mapping between points and character offsets in a laid-out paragraph.

Selection needs two questions answered, and they are inverses:

* which character is under this point (placing a caret),
* which rectangles cover this character range (drawing the highlight).

Both are derived from `Paragraph` as it already exists. A `ShapedRun` carries
cluster indices into **its own** text rather than into the paragraph, and no
offset back to it -- but the runs of a line concatenate in order, so walking
them while accumulating `len(run.text)` recovers the paragraph offset without
touching the shaping structures or the shape cache's key.

Offsets are snapped to **grapheme cluster** boundaries (`segment.py`, UAX #29),
so a selection edge never lands inside a flag emoji or between a base character
and its combining mark.
"""

from __future__ import annotations

from dataclasses import dataclass

from .layout import Paragraph, TextLine
from .segment import cluster_boundaries

__all__ = ["SelectionRect", "index_at", "line_index_at", "rects_for", "word_at"]


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
        scale = run.face.scale_for(para.px)
        for i in range(len(run)):
            advance = float(run.advances[i]) * scale
            if x < pen + advance / 2.0:
                return _snap(para.text, char + int(run.clusters[i]))
            pen += advance
        char += len(run.text)
    return _snap(para.text, line.end)


def _span_x(line: TextLine, para: Paragraph, start: int, end: int) -> tuple[float, float]:
    """Horizontal extent of `[start, end)` within one line."""
    pen = line.x
    char = line.start
    left: float | None = None
    right = line.x

    for run in line.runs:
        scale = run.face.scale_for(para.px)
        for i in range(len(run)):
            advance = float(run.advances[i]) * scale
            position = char + int(run.clusters[i])
            if start <= position < end:
                if left is None:
                    left = pen
                right = pen + advance
            pen += advance
        char += len(run.text)
    return (left if left is not None else line.x, right)


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

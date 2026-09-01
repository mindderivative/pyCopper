"""Paragraph layout: shaped runs become positioned lines.

Stages 4 and 5 of the pipeline interleave (ARCHITECTURE.md 5.7.1). Line
breaking needs measured advances, which only shaping produces, but shaping
context can cross a break. pyCopper shapes each candidate segment and breaks on
measured width -- so a break that lands inside a ligature is resolved on
*source clusters*, never on glyph indices.
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass, field
from typing import Final

from ..layout import SIZE_ZERO, Size
from .font import Face
from .fontdb import FontDB, FontRequest
from .itemize import Direction, itemize
from .segment import break_opportunities
from .shaping import ShapeCache, ShapedRun

__all__ = ["Alignment", "GlyphPlacement", "Paragraph", "TextLine", "layout_text"]

#: Hard line terminators, written as escapes -- the literal characters are
#: invisible in source and trip ambiguous-character lints.
HARD_BREAK_CHARS: Final = "\n\r\v\f\u2028\u2029\u0085"


class Alignment:
    START = "start"
    CENTER = "center"
    END = "end"


@dataclass(frozen=True, slots=True)
class GlyphPlacement:
    """One glyph, positioned in paragraph-local pixels."""

    face: Face
    gid: int
    x: float
    y: float  # baseline y
    cluster: int


@dataclass(slots=True)
class TextLine:
    """One laid-out line."""

    runs: list[ShapedRun] = field(default_factory=list)
    start: int = 0
    end: int = 0
    width: float = 0.0
    baseline: float = 0.0
    height: float = 0.0
    x: float = 0.0

    @property
    def top(self) -> float:
        return self.baseline - self.height


@dataclass(slots=True)
class Paragraph:
    """A fully laid-out block of text."""

    text: str
    lines: list[TextLine] = field(default_factory=list)
    size: Size = SIZE_ZERO
    #: Width the text was wrapped and aligned to. `size.width` is the INK
    #: extent -- the widest line -- so a Text widget shrink-wraps instead of
    #: claiming its whole wrap box and starving its siblings in a Row.
    box_width: float = 0.0
    px: float = 14.0
    base_direction: str = Direction.LTR

    @property
    def line_count(self) -> int:
        return len(self.lines)

    def placements(self) -> list[GlyphPlacement]:
        """Every glyph with its final position. Consumed by the paint pass."""
        out: list[GlyphPlacement] = []
        for line in self.lines:
            pen = line.x
            for run in line.runs:
                scale = run.face.scale_for(self.px)
                for i in range(len(run)):
                    ox, oy = run.offsets[i]
                    out.append(
                        GlyphPlacement(
                            face=run.face,
                            gid=int(run.glyphs[i]),
                            x=pen + float(ox) * scale,
                            y=line.baseline - float(oy) * scale,
                            cluster=int(run.clusters[i]),
                        )
                    )
                    pen += float(run.advances[i]) * scale
        return out


def _line_metrics(runs: list[ShapedRun], px: float, fallback: Face) -> tuple[float, float]:
    """``(ascent, height)`` for a line, taken from the tallest face it uses."""
    faces = [r.face for r in runs] or [fallback]
    return (
        max(f.metrics(px).ascent for f in faces),
        max(f.metrics(px).line_height for f in faces),
    )


def layout_text(
    text: str,
    db: FontDB,
    *,
    px: float = 14.0,
    max_width: float | None = None,
    request: FontRequest | None = None,
    alignment: str = Alignment.START,
    cache: ShapeCache | None = None,
) -> Paragraph:
    """Shape, break, and position *text*.

    ``max_width`` of None lays the text out as a single unwrapped line.
    """
    req = request or FontRequest()
    # NOT `cache or ShapeCache()`: an empty ShapeCache is falsy (__len__ == 0),
    # so that form silently discards the caller's cache on first use.
    shaper = ShapeCache() if cache is None else cache
    primary = db.face_for(req)
    para = Paragraph(text=text, px=px)

    if not text:
        para.size = Size(0.0, primary.metrics(px).line_height)
        para.box_width = max_width or 0.0
        return para

    items = itemize(text, db, req)
    para.base_direction = items[0].direction if items else Direction.LTR

    def shape_segment(segment: str) -> tuple[list[ShapedRun], float]:
        runs: list[ShapedRun] = []
        width = 0.0
        for item in itemize(segment, db, req):
            run = shaper.get(item.text, item.face, direction=item.direction, script=item.script)
            runs.append(run)
            width += run.width(px)
        return runs, width

    # Hard breaks split the paragraph first; wrapping happens inside each block.
    blocks: list[tuple[int, str]] = []
    start = 0
    for op in break_opportunities(text):
        if op.mandatory:
            blocks.append((start, text[start : op.offset]))
            start = op.offset
    if start < len(text):
        blocks.append((start, text[start:]))
    if not blocks:
        blocks = [(0, text)]

    lines: list[TextLine] = []
    for offset, block in blocks:
        lines.extend(_wrap_block(block, offset, max_width, shape_segment))

    # Stack the lines, then apply horizontal alignment.
    y = 0.0
    widest = 0.0
    for line in lines:
        ascent, height = _line_metrics(line.runs, px, primary)
        line.height = height
        line.baseline = y + ascent
        y += height
        widest = max(widest, line.width)

    box_width = widest if max_width is None else max_width
    for line in lines:
        slack = max(0.0, box_width - line.width)
        if alignment == Alignment.CENTER:
            line.x = slack / 2
        elif alignment == Alignment.END:
            line.x = slack

    para.lines = lines
    para.box_width = box_width
    para.size = Size(widest, y)
    return para


def _wrap_block(
    block: str,
    offset: int,
    max_width: float | None,
    shape_segment: Callable[[str], tuple[list[ShapedRun], float]],
) -> list[TextLine]:
    """Greedy wrap of one hard-break-delimited block."""
    stripped = block.rstrip(HARD_BREAK_CHARS)
    if not stripped.strip():
        return [TextLine([], offset, offset + len(block), 0.0)]

    if max_width is None:
        runs, width = shape_segment(stripped)
        return [TextLine(runs, offset, offset + len(block), width)]

    lines: list[TextLine] = []
    line_start = 0
    last_fit = 0

    for op in [o.offset for o in break_opportunities(stripped)]:
        candidate = stripped[line_start:op].rstrip()
        _, width = shape_segment(candidate) if candidate else ([], 0.0)
        if width <= max_width:
            last_fit = op
            continue
        # Overflowed. Emit up to the last opportunity that fitted; if none did,
        # this one unbreakable unit overflows on its own line rather than
        # vanishing.
        cut = last_fit if last_fit > line_start else op
        runs, w = shape_segment(stripped[line_start:cut].rstrip())
        lines.append(TextLine(runs, offset + line_start, offset + cut, w))
        line_start = cut
        last_fit = cut

    if line_start < len(stripped):
        runs, w = shape_segment(stripped[line_start:].rstrip())
        lines.append(TextLine(runs, offset + line_start, offset + len(block), w))

    return lines or [TextLine([], offset, offset + len(block), 0.0)]

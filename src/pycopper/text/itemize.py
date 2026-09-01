"""Itemisation: splitting a paragraph into runs that can each be shaped.

Shaping requires a run uniform in **script, direction, and font** all at once,
so a paragraph is split three times, in this order (ARCHITECTURE.md 5.7.1):

1. **Bidi** (UAX #9) first, because it operates on the whole paragraph and
   produces the embedding levels every later stage needs.
2. **Script** (UAX #24) next, using ``fontTools.unicodedata``.
3. **Font** last, by coverage, since which face is needed depends on the
   characters that survived the first two splits.
"""

from __future__ import annotations

from dataclasses import dataclass

from bidi import get_display
from fontTools import unicodedata as ftud

from .font import Face
from .fontdb import FontDB, FontRequest
from .segment import clusters

__all__ = ["Direction", "ItemRun", "itemize", "resolve_base_direction", "script_runs"]

#: Script codes that carry no direction of their own and join whichever run
#: they appear in. Splitting on them would fragment ordinary punctuated text.
_NEUTRAL = frozenset({"Zyyy", "Zinh", "Zzzz"})


class Direction:
    LTR = "ltr"
    RTL = "rtl"


@dataclass(frozen=True, slots=True)
class ItemRun:
    """A maximal span uniform in script, direction, and face."""

    start: int
    end: int
    text: str
    script: str
    direction: str
    face: Face

    @property
    def length(self) -> int:
        return self.end - self.start

    @property
    def is_rtl(self) -> bool:
        return self.direction == Direction.RTL


def resolve_base_direction(text: str) -> str:
    """Paragraph direction from the first strong character (UAX #9 rule P2)."""
    for char in text:
        script = ftud.script(char)
        if script in _NEUTRAL:
            continue
        if ftud.script_horizontal_direction(script, "LTR") == "RTL":
            return Direction.RTL
        return Direction.LTR
    return Direction.LTR


def reorder_for_display(text: str, base: str | None = None) -> str:
    """Logical order -> visual order via the bidi algorithm."""
    return str(get_display(text, base_dir="R" if base == Direction.RTL else "L"))


def script_runs(text: str) -> list[tuple[int, int, str]]:
    """``(start, end, script)`` spans. Neutral characters extend the run
    they follow, so ``"Hello, world!"`` stays a single Latin run."""
    if not text:
        return []
    runs: list[tuple[int, int, str]] = []
    start = 0
    current: str | None = None
    for i, char in enumerate(text):
        script = ftud.script(char)
        if script in _NEUTRAL:
            continue
        if current is None:
            current = script
        elif script != current:
            runs.append((start, i, current))
            start, current = i, script
    runs.append((start, len(text), current or "Zyyy"))
    return runs


def itemize(
    text: str,
    db: FontDB,
    request: FontRequest | None = None,
    base_direction: str | None = None,
) -> list[ItemRun]:
    """Split *text* into runs ready for shaping."""
    if not text:
        return []
    req = request or FontRequest()
    base = base_direction or resolve_base_direction(text)

    out: list[ItemRun] = []
    for start, end, script in script_runs(text):
        direction = (
            Direction.RTL
            if ftud.script_horizontal_direction(script, "LTR") == "RTL"
            else Direction.LTR
        )
        # Split again by face. Resolution is per grapheme cluster so a base
        # character and its combining marks always land on the same font.
        offset = start
        run_face: Face | None = None
        run_start = start
        for cluster in clusters(text[start:end]):
            face = db.resolve(cluster, req)
            if run_face is None:
                run_face = face
            elif face is not run_face:
                out.append(
                    ItemRun(run_start, offset, text[run_start:offset], script, direction, run_face)
                )
                run_start, run_face = offset, face
            offset += len(cluster)
        if run_face is not None and offset > run_start:
            out.append(
                ItemRun(run_start, offset, text[run_start:offset], script, direction, run_face)
            )

    out.sort(key=lambda r: r.start)
    if base == Direction.RTL:
        # Visual order for an RTL paragraph is the reverse of logical order at
        # the run level; glyph order inside each run is HarfBuzz's job.
        out.reverse()
    return out

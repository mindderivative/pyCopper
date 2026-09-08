"""M3 Button Group: an invisible container that spaces buttons and, for the
connected variant, merges their outer shape into one pill.

**`COMPONENT_BUTTON_GROUPS.md`'s own words**: "Button groups are invisible
containers that add padding between buttons and modify button shape." A
`Flex` row with M3's spacing and, for `variant: connected`, per-child
corner overrides -- plus, now, the width/shape *morph* on press and
selection M3's own demo videos show. The morph itself (round<->square,
sourced dp figures) lives entirely on `ButtonElement` (`base.py`) -- it
applies to any toggle button, grouped or not. This module's own
contribution is narrower and specific to the "Selection & activation"
section of `COMPONENT_BUTTON_GROUPS.md`: a **standard** group's selected
button also grows WIDTH (unsourced amount -- the spec gives none, only
that it happens; see `ButtonElement.GROUP_SELECT_PAD_EXTRA`), which
visibly shifts every later sibling along the row as an ordinary
consequence of this already being a plain `Flex` row -- nothing new was
needed for that. A **connected** group's own selection changes shape only,
per the spec's own "don't add any interaction between buttons... only
affect the shape."

Still not built: the XS/S/M/L/XL size ladder button groups are meant to
span -- `ButtonElement` itself has only one size today, so there is no
ladder to select from yet (the same shared gap `Slider`'s own size ladder
already closed for itself).

**Spacing**: `COMPONENT_BUTTON_GROUPS.md`'s own "between-space" table gives
one row per size (XS 18dp, S 12dp, M/L/XL 8dp); with `Button` at a single
size, the M/L/XL row (8dp) is the one that applies. Connected groups use a
flat 2dp at every size, quoted directly ("For all connected button groups,
use 2dp padding... This provides visual consistency at scale").

**Connected shape**: "the outer shape is fully round, and the inner shape
remains square with the following corner sizes" (4dp at XS rising to 20dp
at XL) -- read here as the whole group's outward-facing ends staying fully
rounded while every corner where two buttons meet squares off to the M-size
figure (8dp), the shape a segmented control reads as from a short visual
description with no diagram in the scraped source. Applied only to plain
`Button` children: M3 says a group "can contain buttons and icon buttons",
but `IconButtonElement.effective_radii` is hardcoded to full-round and does
not consult an override the way `ButtonElement`'s now does -- extending it
is a small follow-up, not done here.
"""

from __future__ import annotations

from typing import Final

from ..layout import Axis, Constraints, Flex, Size
from ..spec import WidgetSpec
from .base import ButtonElement, _StyledMixin

__all__ = ["ButtonGroupElement"]


class ButtonGroupElement(_StyledMixin, Flex):
    """M3 Button Group, M size only. See the module docstring."""

    STANDARD_SPACING: Final = 8.0
    CONNECTED_SPACING: Final = 2.0
    INNER_RADIUS: Final = 8.0

    axis: Axis = Axis.HORIZONTAL

    def __init__(self, spec: WidgetSpec) -> None:
        Flex.__init__(self, axis=self.axis, spacing=self._spacing_for(spec.style.variant))
        self.init_element(spec)

    def _spacing_for(self, variant: str) -> float:
        return self.CONNECTED_SPACING if variant == "connected" else self.STANDARD_SPACING

    def configure(self) -> None:
        self._spacing = self._spacing_for(self.style.variant)

    def _apply_shape(self) -> None:
        buttons = [c for c in self.children if isinstance(c, ButtonElement)]
        if self.style.variant != "connected":
            for child in buttons:
                child._group_radii = None
            return
        last = len(buttons) - 1
        for i, child in enumerate(buttons):
            outer = child.size.height / 2
            leading = outer if i == 0 else self.INNER_RADIUS
            trailing = outer if i == last else self.INNER_RADIUS
            child._group_radii = (leading, trailing, trailing, leading)

    def perform_layout(self, constraints: Constraints) -> Size:
        # Unlike `_apply_shape()` below (paint-only, needs each child's
        # already-computed `size.height`, so it runs after), this flag
        # needs to be set BEFORE `super().perform_layout()` -- each Button
        # child's own `perform_layout` (called from inside that same
        # `super()` call) reads it to compute its own WIDTH. It depends
        # only on `self.style.variant`, known immediately, so no
        # post-layout data is needed for it.
        standard = self.style.variant != "connected"
        for child in self.children:
            if isinstance(child, ButtonElement):
                child._group_standard = standard
        size = super().perform_layout(constraints)
        self._apply_shape()
        return size

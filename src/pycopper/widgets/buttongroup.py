"""M3 Button Group: an invisible container that spaces buttons and, for the
connected variant, merges their outer shape into one pill.

**`COMPONENT_BUTTON_GROUPS.md`'s own words**: "Button groups are invisible
containers that add padding between buttons and modify button shape." That
is exactly the scope built here -- a `Flex` row with M3's spacing and, for
`variant: connected`, per-child corner overrides. What is deliberately not
built: the width/shape *morph* animation on press and selection (M3's own
demo videos show adjacent buttons visibly resizing), and the XS/S/M/L/XL
size ladder button groups are meant to span -- `ButtonElement` itself has
only one size today, so there is no ladder to select from yet. Both are
motion- and sizing-system work belonging to `Button`, not to this
container, and are flagged rather than silently approximated.

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
        size = super().perform_layout(constraints)
        self._apply_shape()
        return size

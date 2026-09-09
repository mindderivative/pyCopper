"""Button Group demo's logic: three independent toggles in the standard
group, one single-select switch in the connected group, and the two
source panels.

See app.py in this directory for the entry point.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

from pycopper import Signal, ViewModel


class ButtonGroupDemo(ViewModel):
    """State and commands for `ButtonGroup_View.yaml`."""

    def __init__(self) -> None:
        # Standard group -- a formatting toolbar. Each button is an
        # independent toggle (the same value:/on_click: convention Chip's
        # filter variant already uses) since bold/italic/underline
        # legitimately stack.
        self.bold = Signal(False, name="bold")
        self.italic = Signal(False, name="italic")
        self.underline = Signal(False, name="underline")
        # Connected group -- a time-period switcher. One shared Signal
        # names which button is active; each button's own value: compares
        # against it, and clicking always SETS it (not a toggle-flip) --
        # exactly one of the three is ever selected, the same
        # single-select pattern `COMPONENT_BUTTON_GROUPS.md` names as the
        # connected variant's replacement for the deprecated segmented
        # button. phil: "connected buttons should not hold the square
        # state they should switch between them" -- an independent
        # per-button toggle (this demo's first cut) let more than one
        # look selected at once, which doesn't read as a real switch.
        self.period = Signal("day", name="period")

        # Size-ladder demo -- one standard group per size, each with its own
        # independent toggle on the "A" button (same convention as bold/
        # italic/underline above), so clicking it genuinely grows/shrinks
        # and shifts its siblings at every size, not just morphs shape.
        self.ladder_xs = Signal(True, name="ladder_xs")
        self.ladder_s = Signal(True, name="ladder_s")
        self.ladder_m = Signal(True, name="ladder_m")
        self.ladder_l = Signal(True, name="ladder_l")
        self.ladder_xl = Signal(True, name="ladder_xl")

        self.view_source = (Path(__file__).parent / "ButtonGroup_View.yaml").read_text()
        self.viewmodel_source = Path(__file__).read_text()

    def toggle_bold(self, event: Any) -> None:
        self.bold.update(lambda v: not v)

    def toggle_italic(self, event: Any) -> None:
        self.italic.update(lambda v: not v)

    def toggle_underline(self, event: Any) -> None:
        self.underline.update(lambda v: not v)

    def select_day(self, event: Any) -> None:
        self.period.set("day")

    def select_week(self, event: Any) -> None:
        self.period.set("week")

    def select_month(self, event: Any) -> None:
        self.period.set("month")

    def toggle_ladder_xs(self, event: Any) -> None:
        self.ladder_xs.update(lambda v: not v)

    def toggle_ladder_s(self, event: Any) -> None:
        self.ladder_s.update(lambda v: not v)

    def toggle_ladder_m(self, event: Any) -> None:
        self.ladder_m.update(lambda v: not v)

    def toggle_ladder_l(self, event: Any) -> None:
        self.ladder_l.update(lambda v: not v)

    def toggle_ladder_xl(self, event: Any) -> None:
        self.ladder_xl.update(lambda v: not v)

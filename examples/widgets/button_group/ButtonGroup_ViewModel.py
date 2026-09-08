"""Button Group demo's logic: six independent toggles (one per button), and
the two source panels.

See app.py in this directory for the entry point.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

from pycopper import Signal, ViewModel


class ButtonGroupDemo(ViewModel):
    """State and commands for `ButtonGroup_View.yaml`."""

    def __init__(self) -> None:
        # Standard group -- a formatting toolbar, each button an
        # independent toggle (the same value:/on_click: convention Chip's
        # filter variant already uses).
        self.bold = Signal(False, name="bold")
        self.italic = Signal(False, name="italic")
        self.underline = Signal(False, name="underline")
        # Connected group.
        self.day = Signal(False, name="day")
        self.week = Signal(False, name="week")
        self.month = Signal(False, name="month")

        self.view_source = (Path(__file__).parent / "ButtonGroup_View.yaml").read_text()
        self.viewmodel_source = Path(__file__).read_text()

    def toggle_bold(self, event: Any) -> None:
        self.bold.update(lambda v: not v)

    def toggle_italic(self, event: Any) -> None:
        self.italic.update(lambda v: not v)

    def toggle_underline(self, event: Any) -> None:
        self.underline.update(lambda v: not v)

    def toggle_day(self, event: Any) -> None:
        self.day.update(lambda v: not v)

    def toggle_week(self, event: Any) -> None:
        self.week.update(lambda v: not v)

    def toggle_month(self, event: Any) -> None:
        self.month.update(lambda v: not v)

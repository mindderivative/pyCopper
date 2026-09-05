"""Navigation Rail demo's logic: selection and collapse state, and the
two source panels.

See app.py in this directory for the entry point.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

from pycopper import Signal, ViewModel


class NavigationRailDemo(ViewModel):
    """State and commands for `NavigationRail_View.yaml`."""

    def __init__(self) -> None:
        self.selected = Signal("home", name="selected")
        self.collapsed = Signal(False, name="collapsed")

        self.view_source = (Path(__file__).parent / "NavigationRail_View.yaml").read_text()
        self.viewmodel_source = Path(__file__).read_text()

    def select(self, event: Any) -> None:
        self.selected.set(event.target.name)

    def toggle_collapsed(self, event: Any) -> None:
        self.collapsed.update(lambda on: not on)

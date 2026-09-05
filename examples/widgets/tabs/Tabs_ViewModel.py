"""Tabs demo's logic: two independent selections, and the two source panels.

See app.py in this directory for the entry point.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

from pycopper import Signal, ViewModel


class TabsDemo(ViewModel):
    """State and commands for `Tabs_View.yaml`."""

    def __init__(self) -> None:
        self.tab = Signal("t0", name="tab")
        self.tab2 = Signal("s0", name="tab2")

        self.view_source = (Path(__file__).parent / "Tabs_View.yaml").read_text()
        self.viewmodel_source = Path(__file__).read_text()

    def select_tab(self, event: Any) -> None:
        self.tab.set(event.target.name)

    def select_tab2(self, event: Any) -> None:
        self.tab2.set(event.target.name)

"""Tree Item demo's logic: one selection, and the two source panels.

See app.py in this directory for the entry point.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

from pycopper import Signal, ViewModel


class TreeItemDemo(ViewModel):
    """State and commands for `TreeItem_View.yaml`."""

    def __init__(self) -> None:
        self.selected = Signal("main", name="selected")

        self.view_source = (Path(__file__).parent / "TreeItem_View.yaml").read_text()
        self.viewmodel_source = Path(__file__).read_text()

    def select(self, event: Any) -> None:
        self.selected.set(event.target.name)

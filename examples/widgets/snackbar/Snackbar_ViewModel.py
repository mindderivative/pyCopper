"""Snackbar demo's logic: open/close state, and the two source panels.

See app.py in this directory for the entry point.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

from pycopper import Signal, ViewModel


class SnackbarDemo(ViewModel):
    """State and commands for `Snackbar_View.yaml`."""

    def __init__(self) -> None:
        self.bar_open = Signal(False, name="bar_open")

        self.view_source = (Path(__file__).parent / "Snackbar_View.yaml").read_text()
        self.viewmodel_source = Path(__file__).read_text()

    def archive(self, event: Any) -> None:
        self.bar_open.set(True)

    def close(self, event: Any) -> None:
        self.bar_open.set(False)

    def undo(self, event: Any) -> None:
        self.bar_open.set(False)

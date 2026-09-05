"""Dialog demo's logic: open/close state, and the two source panels.

See app.py in this directory for the entry point.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

from pycopper import Signal, ViewModel


class DialogDemo(ViewModel):
    """State and commands for `Dialog_View.yaml`."""

    def __init__(self) -> None:
        self.dialog_open = Signal(False, name="dialog_open")
        self.dismissals = Signal(0, name="dismissals")

        self.view_source = (Path(__file__).parent / "Dialog_View.yaml").read_text()
        self.viewmodel_source = Path(__file__).read_text()

    def open_dialog(self, event: Any) -> None:
        self.dialog_open.set(True)

    def close_dialog(self, event: Any) -> None:
        self.dialog_open.set(False)
        self.dismissals.update(lambda n: n + 1)

    def confirm_delete(self, event: Any) -> None:
        self.dialog_open.set(False)

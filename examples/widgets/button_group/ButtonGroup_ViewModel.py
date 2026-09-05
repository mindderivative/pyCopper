"""Button Group demo's logic: nothing to toggle, just the two source panels.

See app.py in this directory for the entry point.
"""

from __future__ import annotations

from pathlib import Path

from pycopper import ViewModel


class ButtonGroupDemo(ViewModel):
    """State for `ButtonGroup_View.yaml`. No commands -- the buttons carry no state here."""

    def __init__(self) -> None:
        self.view_source = (Path(__file__).parent / "ButtonGroup_View.yaml").read_text()
        self.viewmodel_source = Path(__file__).read_text()

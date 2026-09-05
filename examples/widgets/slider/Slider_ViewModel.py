"""Slider demo's logic: one bound value, and the two source panels.

See app.py in this directory for the entry point.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

from pycopper import Signal, ViewModel


class SliderDemo(ViewModel):
    """State and commands for `Slider_View.yaml`."""

    def __init__(self) -> None:
        self.volume = Signal(40, name="volume")

        self.view_source = (Path(__file__).parent / "Slider_View.yaml").read_text()
        self.viewmodel_source = Path(__file__).read_text()

    def change_volume(self, event: Any) -> None:
        self.volume.set(event.value)

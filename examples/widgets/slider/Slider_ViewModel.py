"""Slider demo's logic: one bound value per size row, and the two source panels.

See app.py in this directory for the entry point.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

from pycopper import Signal, ViewModel


class SliderDemo(ViewModel):
    """State and commands for `Slider_View.yaml`."""

    def __init__(self) -> None:
        # One Signal per size row -- the live example shows all five sizes
        # at once, so each needs its own independent bound value.
        self.volume_xs = Signal(40, name="volume_xs")
        self.volume_s = Signal(40, name="volume_s")
        self.volume_m = Signal(40, name="volume_m")
        self.volume_l = Signal(40, name="volume_l")
        self.volume_xl = Signal(40, name="volume_xl")

        self.view_source = (Path(__file__).parent / "Slider_View.yaml").read_text()
        self.viewmodel_source = Path(__file__).read_text()

    def change_volume_xs(self, event: Any) -> None:
        self.volume_xs.set(event.value)

    def change_volume_s(self, event: Any) -> None:
        self.volume_s.set(event.value)

    def change_volume_m(self, event: Any) -> None:
        self.volume_m.set(event.value)

    def change_volume_l(self, event: Any) -> None:
        self.volume_l.set(event.value)

    def change_volume_xl(self, event: Any) -> None:
        self.volume_xl.set(event.value)

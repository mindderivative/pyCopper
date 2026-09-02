"""The gallery's logic: its state, and what its controls do.

This is where the application's behaviour lives. `app.py` next door is the
entry point -- it builds the window and says which ViewModel drives which view,
and nothing else. Moving one function into `app.py` would be the first step
back towards a single global namespace, which is what a ViewModel exists to
avoid.

One view file, one ViewModel: this pairs with `gallery_View.yaml`, and the
fragments it includes may have their own.
"""

from __future__ import annotations

from typing import Any

from pycopper import Signal, Theme, ViewModel

#: The gallery's M3 source colour. The theme is rebuilt from it on a switch.
SEED = "#6750A4"


class Gallery(ViewModel):
    """State and commands for `gallery_View.yaml`.

    Public attributes are the names its `{{ }}` expressions can read; public
    methods are the handlers its `handlers:` can name. Nothing has to be
    registered twice.
    """

    def __init__(self) -> None:
        self.clicks = Signal(0, name="clicks")
        self.dark = Signal(True, name="dark")
        self.confirming = Signal(False, name="confirming")
        self.locking = Signal(False, name="locking")

    # ------------------------------------------------------------- commands

    def confirm(self, event: Any) -> None:
        self.clicks.update(lambda n: n + 1)

    def reset(self, event: Any) -> None:
        self.clicks.set(0)

    def ask(self, event: Any) -> None:
        """Opens the dialog in parts/confirm_dialog_View.yaml."""
        self.confirming.set(True)

    def lock(self, event: Any) -> None:
        """Opens the locked dialog, which a click outside will not close."""
        self.locking.set(True)

    def toggle_theme(self, event: Any) -> None:
        """A theme switch is a single palette-buffer upload -- no relayout.

        One of the few things that is the *application's* rather than the
        view's, which is why it reaches for `self.app`.
        """
        self.dark.update(lambda on: not on)
        self.app.set_theme(Theme(seed=SEED, dark=self.dark.peek()))

"""pyCopper widget gallery -- the entry point, and nothing else.

    python examples/gallery/app.py

This file builds the window and says which ViewModel drives which view. The
behaviour lives in `gallery_ViewModel.py`, beside the view it belongs to.
Moving one handler back in here would be the first step towards a single
global namespace, which is what a ViewModel exists to avoid.

The gallery exercises every widget kind and doubles as the corpus for the
golden-image suite. Hot reload is on: edit `gallery_View.yaml` while it runs
and the window updates without losing the click count or which button has
focus.
"""

from pathlib import Path

from gallery_ViewModel import SEED, Gallery
from parts.confirm_dialog_ViewModel import ConfirmDialog
from parts.locked_dialog_ViewModel import LockedDialog

from pycopper import App, Settings, Theme

VIEW = Path(__file__).parent / "gallery_View.yaml"

app = App(
    VIEW,
    theme=Theme(seed=SEED, dark=True),
    settings=Settings(
        title="pyCopper gallery",
        width=620,
        height=720,
        hot_reload=True,
        # Ask the compositor for the window frame instead of libdecor. On KDE
        # Plasma that skips libdecor entirely, including the "Failed to load
        # plugin 'libdecor-gtk.so'" warning a missing GTK produces.
        #
        # Note if you run this on GNOME: it offers no server-side decorations
        # for xdg-shell, so this leaves the window with no title bar and no
        # close button. Drop this line there -- the default is "auto".
        wayland_decorations="server",
    ),
)

#: One view file, one ViewModel -- for fragments too. This file is the
#: composition root: it builds each ViewModel and hands the dialogs the gallery
#: signal they act on, because whether a dialog is open is the gallery's state
#: rather than the dialog's. A child view cannot be passed an object through
#: `with:` (parameters are textual substitution into YAML), so sharing between
#: ViewModels happens here, in Python, where it is visible.
gallery = app.bind_view_model("gallery_View.yaml", Gallery())
app.bind_view_model("parts/confirm_dialog_View.yaml", ConfirmDialog(gallery.confirming))
app.bind_view_model("parts/locked_dialog_View.yaml", LockedDialog(gallery.locking))

if __name__ == "__main__":
    app.run()

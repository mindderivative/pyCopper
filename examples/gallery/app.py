"""pyCopper widget gallery.

    python examples/gallery/app.py

Exercises every widget kind, and doubles as the corpus for the golden-image
suite. Hot reload is on: edit view.yaml while it runs and the window updates
without losing the click count or which button has focus.
"""

from pathlib import Path

from pycopper import App, Settings, Signal, Theme

VIEW = Path(__file__).parent / "view.yaml"
SEED = "#6750A4"

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

clicks = Signal(0, name="clicks")
dark = Signal(True, name="dark")
confirming = Signal(False, name="confirming")
app.expose(clicks=clicks, dark=dark, confirming=confirming)


@app.handler
def confirm(event) -> None:
    clicks.update(lambda n: n + 1)


@app.handler
def ask(event) -> None:
    """Opens the dialog defined in parts/confirm_dialog.yaml."""
    confirming.set(True)


@app.handler
def dismiss(event) -> None:
    """Closes the dialog. Both of its buttons use this.

    The overlay host also closes it on Escape or a click outside, but a
    dialog's own actions must work without relying on that.
    """
    confirming.set(False)


@app.handler
def reset(event) -> None:
    clicks.set(0)


@app.handler
def toggle_theme(event) -> None:
    """A theme switch is a single palette-buffer upload -- no relayout."""
    dark.update(lambda d: not d)
    app.set_theme(Theme(seed=SEED, dark=dark.peek()))


if __name__ == "__main__":
    app.run()

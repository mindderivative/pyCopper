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
    settings=Settings(title="pyCopper gallery", width=620, height=720, hot_reload=True),
)

clicks = Signal(0, name="clicks")
dark = Signal(True, name="dark")
app.expose(clicks=clicks, dark=dark)


@app.handler
def confirm(event) -> None:
    clicks.update(lambda n: n + 1)


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

"""Chip demo -- its own window, own process.

python examples/widgets/chip/app.py
"""

from pathlib import Path

from Chip_ViewModel import ChipDemo

from pycopper import App, Settings, Theme

VIEW = Path(__file__).parent / "Chip_View.yaml"

app = App(
    VIEW,
    theme=Theme(seed="#6750A4", dark=True),
    settings=Settings(title="pyCopper widgets -- Chip", width=760, height=760),
)
app.bind_view_model(VIEW.name, ChipDemo())

if __name__ == "__main__":
    app.run()

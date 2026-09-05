"""Navigation Drawer demo -- its own window, own process.

python examples/widgets/navigation_drawer/app.py
"""

from pathlib import Path

from NavigationDrawer_ViewModel import NavigationDrawerDemo

from pycopper import App, Settings, Theme

VIEW = Path(__file__).parent / "NavigationDrawer_View.yaml"

app = App(
    VIEW,
    theme=Theme(seed="#6750A4", dark=True),
    settings=Settings(title="pyCopper widgets -- Navigation Drawer", width=800, height=800),
)
app.bind_view_model(VIEW.name, NavigationDrawerDemo())

if __name__ == "__main__":
    app.run()

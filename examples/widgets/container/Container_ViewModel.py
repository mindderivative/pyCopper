"""Container demo's logic: cycling padding and corner radius via
self.app.reload(...), and the two source panels.

See app.py in this directory for the entry point.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

from pycopper import ViewModel

_PADDING_STEPS = (8, 24, 48)
_CORNER_STEPS = (0, 12, 999)

_EXPLANATION = (
    "Container is pyCopper's own layout primitive, not an M3 component -- "
    "the plainest possible box, with room for exactly one child. "
    "style.padding insets that child; style.border and style.corner_radius "
    "decorate the box itself. Since these are plain style properties rather "
    "than one of the handful of templated fields (text:, value:, ...), they "
    "can't be bound to a Signal with a double-curly-brace expression "
    "directly -- the buttons below "
    "work by calling self.app.reload(...) with a freshly built view each "
    "click, the same mechanism hot reload itself uses.\n\n"
    "Use cases: any time content needs a background, a border, or spacing "
    "around it with no other layout behaviour -- the base every other "
    "styled widget in the catalogue is built on top of."
)


class ContainerDemo(ViewModel):
    """State and commands for `Container_View.yaml`.

    `padding` and `corner_radius` are plain `style.*` properties, not one
    of the handful of templated fields (`text:`, `value:`, ...), so they
    cannot be bound to a Signal with `{{ }}`. Each button instead rebuilds
    the whole view as a Python dict with the new values baked in and calls
    `self.app.reload(...)` -- the same mechanism hot reload itself uses.
    Reconciliation matches by `name:`, so everything outside `live_demo`
    (scroll position included) survives the reload untouched.
    """

    def __init__(self) -> None:
        self._padding_index = 0
        self._corner_index = 0

        self.view_source = (Path(__file__).parent / "Container_View.yaml").read_text()
        self.viewmodel_source = Path(__file__).read_text()

    def _view(self) -> dict[str, Any]:
        padding = _PADDING_STEPS[self._padding_index]
        corner = _CORNER_STEPS[self._corner_index]
        label = f"padding: {padding}, corner_radius: {corner}"
        return {
            "name": "root",
            "widget": "ScrollView",
            "style": {"width": "expand", "height": "expand"},
            "children": [
                {
                    "widget": "Column",
                    "style": {
                        "background": "surface",
                        "padding": 32,
                        "spacing": 20,
                        "width": "expand",
                        "cross_alignment": "stretch",
                    },
                    "children": [
                        {
                            "name": "title",
                            "widget": "Text",
                            "text": "Container",
                            "style": {"text_style": "headline-small", "color": "on_surface"},
                        },
                        {
                            "name": "summary",
                            "widget": "Text",
                            "text": (
                                "A styled box: background, border, corner radius, "
                                "and padding around a single child."
                            ),
                            "style": {"text_style": "body-large", "color": "on_surface_variant"},
                        },
                        {"name": "div1", "widget": "Divider", "style": {"width": "expand"}},
                        {
                            "name": "explanation",
                            "widget": "Text",
                            "text": _EXPLANATION,
                            "style": {"text_style": "body-medium", "color": "on_surface_variant"},
                        },
                        {"name": "div2", "widget": "Divider", "style": {"width": "expand"}},
                        {
                            "name": "live_heading",
                            "widget": "Text",
                            "text": "Live example -- click to change padding and corner radius",
                            "style": {"text_style": "title-medium", "color": "primary"},
                        },
                        {
                            "name": "live_demo",
                            "widget": "Container",
                            "style": {
                                "padding": padding,
                                "corner_radius": corner,
                                "background": "primary_container",
                                "width": 240,
                                "height": 120,
                            },
                            "children": [
                                {
                                    "widget": "Text",
                                    "text": label,
                                    "style": {"color": "on_primary_container"},
                                }
                            ],
                        },
                        {
                            "name": "controls",
                            "widget": "Row",
                            "style": {"spacing": 8},
                            "children": [
                                {
                                    "widget": "Button",
                                    "text": "Cycle padding",
                                    "style": {"variant": "outlined"},
                                    "handlers": {"on_click": "cycle_padding"},
                                },
                                {
                                    "widget": "Button",
                                    "text": "Cycle corner radius",
                                    "style": {"variant": "outlined"},
                                    "handlers": {"on_click": "cycle_corner"},
                                },
                            ],
                        },
                        {"name": "div3", "widget": "Divider", "style": {"width": "expand"}},
                        {
                            "name": "code_heading",
                            "widget": "Text",
                            "text": "Source",
                            "style": {"text_style": "title-medium", "color": "primary"},
                        },
                        {
                            "name": "code_panels",
                            "widget": "Row",
                            "style": {"spacing": 16, "width": "expand", "height": 260},
                            "children": [
                                {
                                    "name": "yaml_source",
                                    "widget": "CodeEditor",
                                    "value": "{{ view_source }}",
                                    "style": {
                                        "width": "expand",
                                        "height": "expand",
                                        "language": "yaml",
                                        "read_only": True,
                                    },
                                },
                                {
                                    "name": "python_source",
                                    "widget": "CodeEditor",
                                    "value": "{{ viewmodel_source }}",
                                    "style": {
                                        "width": "expand",
                                        "height": "expand",
                                        "language": "python",
                                        "read_only": True,
                                    },
                                },
                            ],
                        },
                    ],
                }
            ],
        }

    def cycle_padding(self, event: Any) -> None:
        self._padding_index = (self._padding_index + 1) % len(_PADDING_STEPS)
        self.app.reload(self._view())

    def cycle_corner(self, event: Any) -> None:
        self._corner_index = (self._corner_index + 1) % len(_CORNER_STEPS)
        self.app.reload(self._view())

"""Stack demo's logic: cycling the front child's align_x/align_y via
self.app.reload(...), and the two source panels.

See app.py in this directory for the entry point.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

from pycopper import ViewModel

_CORNERS = ((0.0, 0.0), (1.0, 0.0), (1.0, 1.0), (0.0, 1.0), (0.5, 0.5))

_EXPLANATION = (
    "Every child is laid out against the Stack's own size and then "
    "positioned by its own style.align_x/align_y (0.0 to 1.0, fraction "
    "of the leftover space) rather than by a shared main/cross axis the "
    "way Row/Column place children relative to each other. Later "
    "children paint on top of earlier ones -- the same convention Badge "
    "uses to sit on an icon's corner in its own demo. Since "
    "align_x/align_y are plain style properties, the button below drives "
    "the front child's position by rebuilding the view in Python and "
    "calling self.app.reload(...).\n\n"
    "Use cases: overlaying content -- a badge on an icon, a loading "
    "spinner over disabled content, a caption over an image."
)


class StackDemo(ViewModel):
    """State and commands for `Stack_View.yaml`."""

    def __init__(self) -> None:
        self._corner_index = 0

        self.view_source = (Path(__file__).parent / "Stack_View.yaml").read_text()
        self.viewmodel_source = Path(__file__).read_text()

    def _view(self) -> dict[str, Any]:
        align_x, align_y = _CORNERS[self._corner_index]
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
                            "text": "Stack",
                            "style": {"text_style": "headline-small", "color": "on_surface"},
                        },
                        {
                            "name": "summary",
                            "widget": "Text",
                            "text": (
                                "A z-order container: children paint in declaration "
                                "order, each positioned independently within the same box."
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
                            "text": "Live example -- click to move the front square",
                            "style": {"text_style": "title-medium", "color": "primary"},
                        },
                        {
                            "name": "live_demo",
                            "widget": "Stack",
                            "style": {
                                "width": 260,
                                "height": 160,
                                "background": "surface_container_low",
                                "corner_radius": 8,
                            },
                            "children": [
                                {
                                    "widget": "Container",
                                    "style": {
                                        "width": 220,
                                        "height": 120,
                                        "background": "secondary_container",
                                        "corner_radius": 8,
                                        "align_x": 0.5,
                                        "align_y": 0.5,
                                    },
                                },
                                {
                                    "widget": "Container",
                                    "style": {
                                        "width": 64,
                                        "height": 64,
                                        "background": "primary",
                                        "corner_radius": 8,
                                        "align_x": align_x,
                                        "align_y": align_y,
                                    },
                                },
                            ],
                        },
                        {
                            "name": "label",
                            "widget": "Text",
                            "text": f"front square: align_x={align_x}, align_y={align_y}",
                            "style": {"color": "on_surface_variant"},
                        },
                        {
                            "name": "controls",
                            "widget": "Row",
                            "style": {"spacing": 8},
                            "children": [
                                {
                                    "widget": "Button",
                                    "text": "Move front square",
                                    "style": {"variant": "outlined"},
                                    "handlers": {"on_click": "cycle_alignment"},
                                }
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

    def cycle_alignment(self, event: Any) -> None:
        self._corner_index = (self._corner_index + 1) % len(_CORNERS)
        self.app.reload(self._view())

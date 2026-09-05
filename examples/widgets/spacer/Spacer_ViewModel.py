"""Spacer demo's logic: cycling the two spacers' flex ratio via
self.app.reload(...), and the two source panels.

See app.py in this directory for the entry point.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

from pycopper import ViewModel

_RATIOS = ((1, 1), (3, 1), (1, 3))

_EXPLANATION = (
    "A child styled width: flex:N (Row) or height: flex:N shares the "
    "parent's leftover space in proportion to its own weight against "
    "every other flexible sibling's -- a plain Spacer is just a widget "
    "with nothing else to draw, used purely for that weight. Two "
    "spacers with equal weight split the remaining room evenly; a 3:1 "
    "split gives one three times the other's share. Since the weight is "
    "part of style.width, the button below drives it by rebuilding the "
    "view in Python and calling self.app.reload(...).\n\n"
    "Use cases: pinning one item to each end of a Row (a single Spacer "
    "between them), or distributing space between several items in a "
    "known ratio."
)


class SpacerDemo(ViewModel):
    """State and commands for `Spacer_View.yaml`."""

    def __init__(self) -> None:
        self._ratio_index = 0

        self.view_source = (Path(__file__).parent / "Spacer_View.yaml").read_text()
        self.viewmodel_source = Path(__file__).read_text()

    def _view(self) -> dict[str, Any]:
        weight_a, weight_b = _RATIOS[self._ratio_index]
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
                            "text": "Spacer",
                            "style": {"text_style": "headline-small", "color": "on_surface"},
                        },
                        {
                            "name": "summary",
                            "widget": "Text",
                            "text": (
                                "Pure flex-filler: with no flex or size of its own "
                                "there is none to take, so it only does anything "
                                "inside a Row or Column."
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
                            "text": "Live example -- click to change the flex ratio",
                            "style": {"text_style": "title-medium", "color": "primary"},
                        },
                        {
                            "name": "live_demo",
                            "widget": "Row",
                            "style": {
                                "width": "expand",
                                "height": 56,
                                "background": "surface_container_low",
                                "corner_radius": 8,
                                "padding": {"left": 12, "right": 12},
                            },
                            "children": [
                                {
                                    "widget": "Container",
                                    "style": {
                                        "width": 40,
                                        "height": 32,
                                        "background": "primary",
                                        "corner_radius": 6,
                                    },
                                },
                                {
                                    "name": "spacer_a",
                                    "widget": "Spacer",
                                    "style": {"width": f"flex:{weight_a}"},
                                },
                                {
                                    "widget": "Container",
                                    "style": {
                                        "width": 40,
                                        "height": 32,
                                        "background": "secondary",
                                        "corner_radius": 6,
                                    },
                                },
                                {
                                    "name": "spacer_b",
                                    "widget": "Spacer",
                                    "style": {"width": f"flex:{weight_b}"},
                                },
                                {
                                    "widget": "Container",
                                    "style": {
                                        "width": 40,
                                        "height": 32,
                                        "background": "tertiary",
                                        "corner_radius": 6,
                                    },
                                },
                            ],
                        },
                        {
                            "name": "label",
                            "widget": "Text",
                            "text": f"spacer ratio: {weight_a} : {weight_b}",
                            "style": {"color": "on_surface_variant"},
                        },
                        {
                            "name": "controls",
                            "widget": "Row",
                            "style": {"spacing": 8},
                            "children": [
                                {
                                    "widget": "Button",
                                    "text": "Cycle ratio",
                                    "style": {"variant": "outlined"},
                                    "handlers": {"on_click": "cycle_ratio"},
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

    def cycle_ratio(self, event: Any) -> None:
        self._ratio_index = (self._ratio_index + 1) % len(_RATIOS)
        self.app.reload(self._view())

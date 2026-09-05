"""Row demo's logic: cycling main_alignment via self.app.reload(...), and
the two source panels.

See app.py in this directory for the entry point.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

from pycopper import ViewModel

_ALIGNMENTS = ("start", "end", "center", "space_between", "space_around", "space_evenly")

_EXPLANATION = (
    "pyCopper's layout is one downward pass: constraints go down, sizes "
    "come back up. Row lays every child out along its main axis "
    "(horizontal) first, then positions them per style.main_alignment -- "
    "start, end, center, or one of three spacing modes -- and per "
    "style.cross_alignment on the perpendicular axis (vertical). "
    "style.spacing adds a fixed gap between children on top of whichever "
    "alignment is chosen. These are plain style properties, so the "
    "buttons below drive them by rebuilding the view in Python and "
    "calling self.app.reload(...), the same mechanism hot reload uses.\n\n"
    "Use cases: any horizontal arrangement -- a toolbar, a form's "
    "label-and-field pairing, a set of action buttons -- where the exact "
    "spacing and alignment matter."
)


class RowDemo(ViewModel):
    """State and commands for `Row_View.yaml`."""

    def __init__(self) -> None:
        self._alignment_index = 0

        self.view_source = (Path(__file__).parent / "Row_View.yaml").read_text()
        self.viewmodel_source = Path(__file__).read_text()

    def _view(self) -> dict[str, Any]:
        alignment = _ALIGNMENTS[self._alignment_index]
        swatch = {"style": {"width": 48, "height": 48, "corner_radius": 8}}
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
                            "text": "Row",
                            "style": {"text_style": "headline-small", "color": "on_surface"},
                        },
                        {
                            "name": "summary",
                            "widget": "Text",
                            "text": (
                                "A flex container laying its children out horizontally, "
                                "with control over their spacing and alignment."
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
                            "text": "Live example -- click to change alignment",
                            "style": {"text_style": "title-medium", "color": "primary"},
                        },
                        {
                            "name": "live_demo",
                            "widget": "Row",
                            "style": {
                                "main_alignment": alignment,
                                "width": "expand",
                                "height": 72,
                                "background": "surface_container_low",
                                "corner_radius": 8,
                            },
                            "children": [
                                {
                                    "widget": "Container",
                                    "style": {**swatch["style"], "background": "primary"},
                                },
                                {
                                    "widget": "Container",
                                    "style": {**swatch["style"], "background": "secondary"},
                                },
                                {
                                    "widget": "Container",
                                    "style": {**swatch["style"], "background": "tertiary"},
                                },
                            ],
                        },
                        {
                            "name": "label",
                            "widget": "Text",
                            "text": f"main_alignment: {alignment}",
                            "style": {"color": "on_surface_variant"},
                        },
                        {
                            "name": "controls",
                            "widget": "Row",
                            "style": {"spacing": 8},
                            "children": [
                                {
                                    "widget": "Button",
                                    "text": "Cycle main_alignment",
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
        self._alignment_index = (self._alignment_index + 1) % len(_ALIGNMENTS)
        self.app.reload(self._view())

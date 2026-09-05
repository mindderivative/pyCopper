"""Column demo's logic: cycling cross_alignment via self.app.reload(...),
and the two source panels.

See app.py in this directory for the entry point.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

from pycopper import ViewModel

_ALIGNMENTS = ("start", "end", "center", "stretch")

_EXPLANATION = (
    "The same Flex algorithm Row uses, with the main axis rotated to "
    "vertical: children lay out top to bottom first, then "
    "style.cross_alignment positions each one horizontally -- start, "
    "end, center, or stretch to the column's own width. stretch is what "
    "most pages in this whole set of demos use for their own outer "
    "Column, which is why headings, dividers, and code panels all read "
    "full width by default. Since this is a plain style property, the "
    "button below drives it by rebuilding the view in Python and "
    "calling self.app.reload(...).\n\n"
    "Use cases: any vertical stack of content -- a form, a settings "
    "page, a list of cards -- where children of different widths need "
    "consistent horizontal alignment."
)


class ColumnDemo(ViewModel):
    """State and commands for `Column_View.yaml`."""

    def __init__(self) -> None:
        self._alignment_index = 0

        self.view_source = (Path(__file__).parent / "Column_View.yaml").read_text()
        self.viewmodel_source = Path(__file__).read_text()

    def _view(self) -> dict[str, Any]:
        alignment = _ALIGNMENTS[self._alignment_index]
        widths = (160, 100, 220)
        colors = ("primary", "secondary", "tertiary")
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
                            "text": "Column",
                            "style": {"text_style": "headline-small", "color": "on_surface"},
                        },
                        {
                            "name": "summary",
                            "widget": "Text",
                            "text": (
                                "A flex container laying its children out vertically, "
                                "with control over their spacing and cross-axis alignment."
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
                            "text": "Live example -- click to change cross_alignment",
                            "style": {"text_style": "title-medium", "color": "primary"},
                        },
                        {
                            "name": "live_demo",
                            "widget": "Column",
                            "style": {
                                "cross_alignment": alignment,
                                "spacing": 8,
                                "width": "expand",
                                "background": "surface_container_low",
                                "corner_radius": 8,
                                "padding": 12,
                            },
                            "children": [
                                {
                                    "widget": "Container",
                                    "style": {
                                        "width": width,
                                        "height": 32,
                                        "background": color,
                                        "corner_radius": 6,
                                    },
                                }
                                for width, color in zip(widths, colors, strict=True)
                            ],
                        },
                        {
                            "name": "label",
                            "widget": "Text",
                            "text": f"cross_alignment: {alignment}",
                            "style": {"color": "on_surface_variant"},
                        },
                        {
                            "name": "controls",
                            "widget": "Row",
                            "style": {"spacing": 8},
                            "children": [
                                {
                                    "widget": "Button",
                                    "text": "Cycle cross_alignment",
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

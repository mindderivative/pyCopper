"""Button Group: an invisible container that spaces buttons and, for the
connected variant, merges their outer shape into one pill.

See the module docstring in `buttongroup.py` for what is and is not built --
the shape/spacing container only, not the press/selection width-morph
animation or the XS/S/L/XL size ladder (`Button` itself has one size).
"""

from __future__ import annotations

from pycopper import App, Theme
from pycopper.layout import Offset
from pycopper.paint import DisplayList
from pycopper.spec import WidgetKind, parse_view
from pycopper.theme import Palette
from pycopper.tree.element import PaintContext
from pycopper.widgets.base import _REGISTRY, create_element
from pycopper.widgets.buttongroup import ButtonGroupElement


def _app(variant: str, count: int = 3):
    view = {
        "name": "root",
        "widget": "Vertical",
        "children": [
            {
                "name": "bg",
                "widget": "ButtonGroup",
                "style": {"variant": variant},
                "children": [
                    {"name": f"btn{i}", "widget": "Button", "text": f"Item {i}"}
                    for i in range(count)
                ],
            }
        ],
    }
    app = App(view, theme=Theme(dark=True))
    app.mount()
    app.update()
    group = app.root.find("bg")
    buttons = [app.root.find(f"btn{i}") for i in range(count)]
    return app, group, buttons


# --------------------------------------------------------------- registered


def test_kind_builds() -> None:
    create_element(parse_view({"name": "x", "widget": "ButtonGroup"}).root)
    assert WidgetKind.BUTTON_GROUP in _REGISTRY


# --------------------------------------------------------------------- spacing


def test_standard_variant_uses_the_m_size_between_space() -> None:
    _, group, _buttons = _app("standard")
    assert group._spacing == ButtonGroupElement.STANDARD_SPACING == 8.0


def test_connected_variant_uses_two_dp_at_every_size() -> None:
    _, group, _buttons = _app("connected")
    assert group._spacing == ButtonGroupElement.CONNECTED_SPACING == 2.0


def test_default_variant_is_standard_spacing() -> None:
    _, group, _buttons = _app("filled")  # not a button-group variant at all
    assert group._spacing == ButtonGroupElement.STANDARD_SPACING


# ----------------------------------------------------------------------- shape


def test_standard_variant_leaves_every_button_fully_rounded() -> None:
    _, _group, buttons = _app("standard")
    for button in buttons:
        assert button.effective_radii == (button.size.height / 2,) * 4


def test_connected_variant_rounds_only_the_two_outer_ends() -> None:
    _, _group, (first, middle, last) = _app("connected")
    outer = first.size.height / 2
    inner = ButtonGroupElement.INNER_RADIUS
    assert first.effective_radii == (outer, inner, inner, outer)
    assert middle.effective_radii == (inner, inner, inner, inner)
    assert last.effective_radii == (inner, outer, outer, inner)


def test_a_single_connected_button_is_rounded_on_both_outer_ends() -> None:
    _, _group, (only,) = _app("connected", count=1)
    outer = only.size.height / 2
    assert only.effective_radii == (outer, outer, outer, outer)


def test_switching_back_to_standard_clears_the_override() -> None:
    """Reconciliation must undo a shape override, not just stop setting it."""
    view_connected = {
        "name": "root",
        "widget": "Vertical",
        "children": [
            {
                "name": "bg",
                "widget": "ButtonGroup",
                "style": {"variant": "connected"},
                "children": [
                    {"name": "a", "widget": "Button", "text": "A"},
                    {"name": "b", "widget": "Button", "text": "B"},
                ],
            }
        ],
    }
    app = App(view_connected, theme=Theme(dark=True))
    app.mount()
    app.update()
    a = app.root.find("a")
    assert a.effective_radii != (a.size.height / 2,) * 4

    app.reload(
        {
            "name": "root",
            "widget": "Vertical",
            "children": [
                {
                    "name": "bg",
                    "widget": "ButtonGroup",
                    "style": {"variant": "standard"},
                    "children": [
                        {"name": "a", "widget": "Button", "text": "A"},
                        {"name": "b", "widget": "Button", "text": "B"},
                    ],
                }
            ],
        }
    )
    app.update()
    a = app.root.find("a")
    assert a.effective_radii == (a.size.height / 2,) * 4


# --------------------------------------------------------------------- paint


def test_painting_does_not_crash() -> None:
    app, _group, _buttons = _app("connected")
    dl = DisplayList()
    ctx = PaintContext(display_list=dl, palette=Palette(Theme(dark=True)))
    app.root.paint(ctx, Offset(0.0, 0.0))
    assert dl.view.shape[0] > 0

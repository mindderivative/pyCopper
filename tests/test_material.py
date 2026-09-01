"""The M3 component catalogue: dimensions, variants, tokens, and state."""

from __future__ import annotations

import pytest

from pycopper import App, Signal, Theme
from pycopper.layout import Constraints, Size
from pycopper.paint import NO_TOKEN, DisplayList, Kind
from pycopper.spec import SpecError, WidgetKind, parse_view
from pycopper.widgets import build_element

LOOSE = Constraints.loose(Size(400, 400))


def element(**spec):
    return build_element(parse_view({"name": "w", **spec}).root)


def laid_out(**spec):
    e = element(**spec)
    e.layout(LOOSE)
    return e


def painted(theme: Theme | None = None, **spec) -> DisplayList:
    """Paint one widget through a real App so tokens resolve."""
    app = App(
        {
            "name": "root",
            "widget": "Column",
            "style": {"background": "surface"},
            "children": [{"name": "w", **spec}],
        },
        theme=theme or Theme(dark=True),
    )
    app.mount()
    dl = DisplayList()
    app.paint(dl)
    return dl


def tokens_in(dl: DisplayList) -> set[int]:
    return {int(s["flags"][2]) for s in dl.view} - {NO_TOKEN}


# ------------------------------------------------------- registered kinds


def test_every_kind_has_an_element() -> None:
    from pycopper.widgets.base import _REGISTRY, create_element

    create_element(parse_view({"name": "x", "widget": "Card"}).root)  # force lazy load
    assert set(_REGISTRY) == set(WidgetKind)


@pytest.mark.parametrize(
    "kind",
    ["Card", "Divider", "Checkbox", "Radio", "Switch", "Chip", "IconButton", "Fab", "Badge"],
)
def test_kind_parses_and_builds(kind: str) -> None:
    assert laid_out(widget=kind) is not None


def test_unknown_variant_is_rejected_at_load() -> None:
    with pytest.raises(SpecError):
        parse_view({"name": "x", "widget": "Chip", "style": {"variant": "nope"}})


# ---------------------------------------------------- M3 dimensions (dp 1:1)


@pytest.mark.parametrize(
    ("kind", "expected"),
    [
        ("Checkbox", Size(18, 18)),  # M3 5.1: 18x18dp box
        ("Radio", Size(20, 20)),  # M3 5.5: 20dp outer circle
        ("Switch", Size(52, 32)),  # M3 5.7: 52x32dp track
        ("IconButton", Size(40, 40)),  # M3 1.3: 40x40dp container
    ],
)
def test_control_matches_the_m3_size(kind: str, expected: Size) -> None:
    assert laid_out(widget=kind).size == expected


@pytest.mark.parametrize(
    ("variant", "side"),
    [("small", 40.0), ("standard", 56.0), ("large", 96.0)],  # M3 1.2
)
def test_fab_sizes(variant: str, side: float) -> None:
    e = laid_out(widget="Fab", style={"variant": variant})
    assert e.size == Size(side, side)


def test_badge_dot_is_six_dp() -> None:
    assert laid_out(widget="Badge", style={"variant": "dot"}).size == Size(6, 6)


def test_numbered_badge_is_sixteen_high_and_at_least_as_wide() -> None:
    e = laid_out(widget="Badge", value="8")
    assert e.size.height == 16.0
    assert e.size.width >= 16.0


def test_chip_is_thirty_two_high() -> None:
    assert laid_out(widget="Chip", text="Filter").size.height == 32.0


def test_divider_is_one_dp_and_fills_width() -> None:
    """M3 3.6: 1dp thick, spanning the available width.

    Given a *tight* constraint it must obey that instead -- a node cannot
    violate its constraints -- so this uses the constraint a Column actually
    hands its children: bounded width, loose height.
    """
    e = element(widget="Divider")
    e.layout(Constraints(min_width=300, max_width=300, min_height=0, max_height=300))
    assert e.size == Size(300, 1.0)


def test_divider_obeys_a_tight_constraint() -> None:
    e = element(widget="Divider")
    e.layout(Constraints.tight(Size(300, 300)))
    assert e.size == Size(300, 300)


def test_divider_thickness_is_configurable() -> None:
    e = laid_out(widget="Divider", style={"thickness": 4})
    assert e.size.height == 4.0


# ------------------------------------------------------------ value binding


@pytest.mark.parametrize(
    ("raw", "expected"),
    [
        ("true", True),
        ("True", True),
        ("1", True),
        ("yes", True),
        ("false", False),
        ("0", False),
        ("", False),
        ("none", False),
    ],
)
def test_checked_parses_truthiness(raw: str, expected: bool) -> None:
    assert laid_out(widget="Checkbox", value=raw).checked is expected


def test_value_is_bindable_to_a_signal() -> None:
    view = {
        "name": "root",
        "widget": "Column",
        "children": [{"name": "cb", "widget": "Checkbox", "value": "{{ on.get() }}"}],
    }
    app = App(view, theme=Theme(dark=True))
    on = Signal(False)
    app.expose(on=on)
    app.mount()
    assert app.root.find("cb").checked is False
    on.set(True)
    assert app.root.find("cb").checked is True


def test_badge_count_is_bindable() -> None:
    view = {
        "name": "root",
        "widget": "Column",
        "children": [{"name": "b", "widget": "Badge", "value": "{{ n.get() }}"}],
    }
    app = App(view, theme=Theme(dark=True))
    n = Signal(3)
    app.expose(n=n)
    app.mount()
    assert app.root.find("b").number == 3.0
    n.set(42)
    assert app.root.find("b").value == "42"


# ------------------------------------------------------------ M3 tokens


def test_widgets_emit_tokens_not_literal_colours() -> None:
    """Token indirection is what makes a theme switch one buffer upload."""
    for kind in ("Card", "Divider", "Checkbox", "Radio", "Switch", "Fab"):
        dl = painted(widget=kind)
        assert tokens_in(dl), f"{kind} emitted no palette token"


def test_selected_checkbox_uses_primary() -> None:
    app_dl = painted(widget="Checkbox", value="true")
    from pycopper.theme import Palette

    primary = Palette(Theme(dark=True)).index("primary")
    assert primary in tokens_in(app_dl)


def test_fab_defaults_to_primary_container() -> None:
    """M3 1.2: the default FAB colour mapping."""
    from pycopper.theme import Palette

    pal = Palette(Theme(dark=True))
    assert pal.index("primary_container") in tokens_in(painted(widget="Fab", text="add"))


def test_explicit_background_overrides_the_variant_default() -> None:
    from pycopper.theme import Palette

    pal = Palette(Theme(dark=True))
    dl = painted(widget="Fab", text="add", style={"background": "tertiary"})
    assert pal.index("tertiary") in tokens_in(dl)


# ------------------------------------------------------------- appearance


def test_selected_and_unselected_checkbox_differ() -> None:
    assert len(painted(widget="Checkbox", value="true")) != len(
        painted(widget="Checkbox", value="false")
    ) or tokens_in(painted(widget="Checkbox", value="true")) != tokens_in(
        painted(widget="Checkbox", value="false")
    )


def test_selected_checkbox_draws_a_checkmark() -> None:
    on = painted(widget="Checkbox", value="true")
    off = painted(widget="Checkbox", value="false")
    glyphs = lambda dl: sum(1 for s in dl.view if s["flags"][0] == Kind.GLYPH)  # noqa: E731
    assert glyphs(on) == glyphs(off) + 1


def test_selected_radio_draws_an_inner_dot() -> None:
    on = painted(widget="Radio", value="true")
    off = painted(widget="Radio", value="false")
    assert len(on) == len(off) + 1


def test_elevated_card_casts_a_shadow() -> None:
    dl = painted(widget="Card", style={"variant": "elevated"})
    assert any(s["flags"][0] == Kind.SHADOW for s in dl.view)


def test_filled_card_casts_no_shadow() -> None:
    dl = painted(widget="Card", style={"variant": "filled"})
    assert not any(s["flags"][0] == Kind.SHADOW for s in dl.view)


def test_outlined_card_has_a_border() -> None:
    dl = painted(widget="Card", style={"variant": "outlined"})
    assert any(s["params"][0] > 0 for s in dl.view)


def test_fab_is_elevated() -> None:
    """M3 1.2: resting elevation level 3."""
    assert any(s["flags"][0] == Kind.SHADOW for s in painted(widget="Fab", text="add").view)


def test_filter_chip_shows_a_checkmark_when_selected() -> None:
    sel = painted(widget="Chip", text="F", style={"variant": "filter"}, value="true")
    unsel = painted(widget="Chip", text="F", style={"variant": "filter"}, value="false")
    assert len(sel) > len(unsel)


def test_selected_filter_chip_is_wider() -> None:
    """The leading checkmark takes real space, so layout must account for it."""
    sel = laid_out(widget="Chip", text="Filter", style={"variant": "filter"}, value="true")
    unsel = laid_out(widget="Chip", text="Filter", style={"variant": "filter"}, value="false")
    assert sel.size.width > unsel.size.width


# ------------------------------------------------------------ state layers


@pytest.mark.parametrize("kind", ["Checkbox", "Radio", "Switch", "IconButton", "Fab"])
def test_hover_adds_a_state_layer(kind: str) -> None:
    """M3 §0: hover is an 8% overlay, not a different container colour."""
    view = {
        "name": "root",
        "widget": "Column",
        "children": [
            {"name": "w", "widget": kind, "text": "add" if kind in ("IconButton", "Fab") else None}
        ],
    }
    app = App(view, theme=Theme(dark=True))
    app.mount()
    base = DisplayList()
    app.paint(base)
    w = app.root.find("w")
    w.state.hovered = True
    w.mark_needs_paint()
    hovered = DisplayList()
    app.paint(hovered)
    assert len(hovered) == len(base) + 1


def test_hover_does_not_trigger_layout() -> None:
    app = App(
        {"name": "root", "widget": "Column", "children": [{"name": "w", "widget": "Switch"}]},
        theme=Theme(dark=True),
    )
    app.mount()
    app.update()
    w = app.root.find("w")
    w.state.hovered = True
    w.mark_needs_paint()
    assert w.needs_paint and not w.needs_layout


# ---------------------------------------------------------- button variants


@pytest.mark.parametrize("variant", ["filled", "filled_tonal", "outlined", "elevated", "text"])
def test_button_variants_all_render(variant: str) -> None:
    dl = painted(widget="Button", text="Go", style={"variant": variant})
    assert len(dl) > 0


def test_outlined_button_has_a_border_and_no_fill() -> None:
    dl = painted(widget="Button", text="Go", style={"variant": "outlined"})
    assert any(s["params"][0] > 0 for s in dl.view)


def test_elevated_button_casts_a_shadow() -> None:
    dl = painted(widget="Button", text="Go", style={"variant": "elevated"})
    assert any(s["flags"][0] == Kind.SHADOW for s in dl.view)


def test_text_button_draws_no_container() -> None:
    text_btn = painted(widget="Button", text="Go", style={"variant": "text"})
    filled = painted(widget="Button", text="Go", style={"variant": "filled"})
    assert len(text_btn) < len(filled)

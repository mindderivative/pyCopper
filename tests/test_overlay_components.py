"""The six M3 overlay components: anatomy, dimensions, tokens, and hosting.

Dimensions asserted here are quoted from `M3-References`; where a value is
inferred rather than sourced the test says so, so that a future correction to
the spec has an obvious place to land.
"""

from __future__ import annotations

import pytest

from pycopper import App, Settings, Theme
from pycopper.layout import INF, Constraints, Size
from pycopper.paint import NO_TOKEN, DisplayList
from pycopper.spec import WidgetKind, parse_view
from pycopper.theme import Palette
from pycopper.widgets import build_element
from pycopper.widgets.overlays import (
    BottomSheetElement,
    DialogElement,
    MenuElement,
    MenuItemElement,
    SideSheetElement,
    SnackbarElement,
    TooltipElement,
)

WINDOW = Constraints.loose(Size(1000, 700))

OVERLAY_KINDS = [
    "Dialog",
    "Popover",
    "Menu",
    "MenuItem",
    "Tooltip",
    "Snackbar",
    "BottomSheet",
    "SideSheet",
]


def laid_out(spec: dict, constraints: Constraints = WINDOW):
    element = build_element(parse_view(spec).root)
    element.layout(constraints)
    return element


def hosted(overlay: dict, *, root_children: list | None = None, size=(1024, 768)) -> App:
    """An App with one visible overlay, driven through a real frame."""
    app = App(
        {
            "root": {
                "name": "root",
                "widget": "Column",
                "style": {"background": "surface"},
                "children": root_children or [],
            },
            "overlays": [{"name": "ov", "open": "true", **overlay}],
        },
        theme=Theme(dark=True),
        settings=Settings(width=size[0], height=size[1]),
    )
    app.mount()
    app.update()
    return app


def painted(spec: dict) -> DisplayList:
    app = hosted(spec)
    dl = DisplayList()
    app.paint(dl)
    return dl


PALETTE = Palette(Theme(dark=True))


def tokens_in(dl: DisplayList) -> set[int]:
    return {int(s["flags"][2]) for s in dl.view} - {NO_TOKEN}


def literal_fills(dl: DisplayList) -> list[tuple[float, ...]]:
    """Instances painted with a real colour instead of a palette token."""
    return [tuple(s["fill"]) for s in dl.view if int(s["flags"][2]) == NO_TOKEN]


# ------------------------------------------------------------ registration


@pytest.mark.parametrize("kind", OVERLAY_KINDS)
def test_each_overlay_kind_parses_and_builds(kind: str) -> None:
    element = build_element(parse_view({"name": "w", "widget": kind}).root)
    assert element.spec.widget == WidgetKind(kind)


def test_every_widget_kind_is_registered() -> None:
    """The catalogue and the registry must not drift apart."""
    from pycopper.widgets.base import _REGISTRY, create_element

    create_element(parse_view({"name": "x", "widget": "Dialog"}).root)  # force lazy load
    assert set(_REGISTRY) == set(WidgetKind)


# ------------------------------------------------------------------ dialog


def test_dialog_caps_width_at_the_m3_maximum() -> None:
    """M3: "Container width: Min 280dp; Max 560dp"."""
    wide = laid_out({"widget": "Dialog", "text": "T"}, Constraints.loose(Size(1000, 700)))
    assert wide.size.width == DialogElement.MAX_WIDTH == 560.0


def test_dialog_and_menu_take_their_m3_minimum_when_width_is_unbounded() -> None:
    """With nothing to fill, the M3 minimum is the size to take.

    This is the only situation in which the minimum binds -- see
    `_clamped_width`. Everywhere else these components fill the offered width.
    """
    unbounded = Constraints(min_width=0.0, max_width=INF, min_height=0.0, max_height=700.0)
    assert laid_out({"widget": "Dialog", "text": "T"}, unbounded).size.width == 280.0
    assert laid_out({"widget": "Menu"}, unbounded).size.width == 112.0


def test_the_m3_minimum_width_yields_to_a_narrower_constraint() -> None:
    """A layout node must return a size its constraints allow.

    So M3's 280dp minimum is an aspiration, not a floor it can enforce: in a
    window narrower than the minimum the dialog fills the window instead of
    overflowing it. The same rule applies to the Menu, whose 112dp minimum
    previously raised outright in a 50dp space.
    """
    dialog = laid_out({"widget": "Dialog", "text": "T"}, Constraints.loose(Size(120, 700)))
    menu = laid_out({"widget": "Menu"}, Constraints.loose(Size(50, 700)))
    assert dialog.size.width == 120.0
    assert menu.size.width == 50.0


def test_dialog_height_is_dynamic_not_fixed() -> None:
    """M3: "Container height: Dynamic". A longer body must make it taller.

    This is the whole reason the widget exists -- the hand-built dialog it
    replaces carried a hardcoded `height: 170`.
    """
    short = laid_out({"widget": "Dialog", "text": "Title", "supporting_text": "One line."})
    tall = laid_out(
        {
            "widget": "Dialog",
            "text": "Title",
            "supporting_text": "A considerably longer body that is certain to "
            "wrap onto several lines inside a 560dp dialog, which must "
            "increase the dialog's measured height.",
        }
    )
    assert tall.size.height > short.size.height


def test_dialog_uses_the_m3_shape_and_padding() -> None:
    dialog = laid_out({"widget": "Dialog", "text": "T"})
    assert dialog.effective_radii == (28.0,) * 4
    assert dialog.padding.left == DialogElement.PADDING == 24.0


def test_dialog_places_actions_below_the_text_block() -> None:
    """M3: 16dp between title and body, 24dp between body and actions."""
    dialog = laid_out(
        {
            "widget": "Dialog",
            "text": "Title",
            "supporting_text": "Body",
            "children": [{"widget": "Row", "style": {"height": 40}}],
        }
    )
    actions = dialog.children[0]
    assert actions.offset.x == 24.0
    # Below the padding, the headline, the 16dp gap, the body, and the 24dp gap.
    assert actions.offset.y > 24.0 + DialogElement.GAP_BODY_ACTIONS


def test_dialog_without_actions_still_lays_out() -> None:
    dialog = laid_out({"widget": "Dialog", "text": "Title only"})
    assert dialog.children == []
    assert dialog.size.height > DialogElement.PADDING * 2


def test_dialog_paints_the_m3_container_token() -> None:
    dl = painted({"widget": "Dialog", "text": "Title", "style": {"modal": True, "scrim": True}})
    assert PALETTE.index("surface_container_high") in tokens_in(dl)


# -------------------------------------------------------------------- menu


def test_menu_caps_width_at_the_m3_maximum() -> None:
    """M3 baseline menu: "Container width: 112dp min, 280dp max"."""
    wide = laid_out({"widget": "Menu"}, Constraints.loose(Size(1000, 700)))
    assert wide.size.width == MenuElement.MAX_WIDTH == 280.0


def test_an_explicit_width_overrides_the_m3_range() -> None:
    menu = laid_out({"widget": "Menu", "style": {"width": 200}}, Constraints.loose(Size(1000, 700)))
    assert menu.size.width == 200.0


def test_menu_has_a_4dp_corner_radius() -> None:
    assert laid_out({"widget": "Menu"}).effective_radii == (4.0,) * 4


def test_menu_applies_8dp_vertical_padding() -> None:
    """M3 shows 8dp above the first item and below the last."""
    menu = laid_out(
        {
            "widget": "Menu",
            "children": [
                {"widget": "MenuItem", "text": "Cut"},
                {"widget": "MenuItem", "text": "Copy"},
            ],
        }
    )
    first, last = menu.children
    assert first.offset.y == MenuElement.PAD_Y == 8.0
    assert menu.size.height == 8.0 + 48.0 * 2 + 8.0
    assert last.offset.y == 8.0 + 48.0


def test_menu_item_is_48dp_not_a_list_item_height() -> None:
    """A menu row is denser than a List item (56/72/88dp)."""
    item = laid_out({"widget": "MenuItem", "text": "Cut"})
    assert item.size.height == MenuItemElement.HEIGHT == 48.0


def test_menu_item_paints_label_and_trailing_shortcut() -> None:
    dl = painted(
        {
            "widget": "Menu",
            "children": [{"widget": "MenuItem", "text": "Cut", "supporting_text": "Ctrl+X"}],
        }
    )
    tokens = tokens_in(dl)
    assert PALETTE.index("on_surface") in tokens
    assert PALETTE.index("on_surface_variant") in tokens


# ----------------------------------------------------------------- tooltip


def test_tooltip_is_24dp_tall_for_a_single_line() -> None:
    """M3: "Container height: 24dp". The label must fit inside it, not exceed it."""
    tooltip = laid_out({"widget": "Tooltip", "text": "Save file"})
    assert tooltip.size.height == TooltipElement.MIN_HEIGHT == 24.0


def test_tooltip_width_follows_its_label_plus_8dp_each_side() -> None:
    short = laid_out({"widget": "Tooltip", "text": "Hi"})
    long = laid_out({"widget": "Tooltip", "text": "A much longer tooltip label"})
    assert long.size.width > short.size.width
    assert short.size.width > TooltipElement.PAD_X * 2


def test_tooltip_uses_inverse_colour_roles() -> None:
    """M3: container `inverse surface`, label `inverse on surface`."""
    dl = painted({"widget": "Tooltip", "text": "Save"})
    tokens = tokens_in(dl)
    assert PALETTE.index("inverse_surface") in tokens
    assert PALETTE.index("inverse_on_surface") in tokens


# ---------------------------------------------------------------- snackbar


def test_snackbar_is_at_least_48dp() -> None:
    """M3: snackbars expand vertically from 48dp to 64dp."""
    bar = laid_out({"widget": "Snackbar", "text": "Archived"})
    assert bar.size.height == SnackbarElement.MIN_HEIGHT == 48.0


def test_snackbar_grows_to_64dp_for_two_lines_and_no_further() -> None:
    bar = laid_out(
        {
            "widget": "Snackbar",
            "text": "A snackbar message long enough to wrap onto a second line "
            "and then onto a third and a fourth line as well, which must not "
            "push it past the 64dp ceiling.",
        }
    )
    assert bar.size.height == SnackbarElement.MAX_HEIGHT == 64.0


def test_snackbar_action_uses_inverse_primary() -> None:
    dl = painted({"widget": "Snackbar", "text": "Archived", "supporting_text": "Undo"})
    assert PALETTE.index("inverse_primary") in tokens_in(dl)


def test_snackbar_reserves_room_for_its_action() -> None:
    """The label must not run underneath the action label."""
    plain = laid_out({"widget": "Snackbar", "text": "x" * 200})
    with_action = laid_out({"widget": "Snackbar", "text": "x" * 200, "supporting_text": "Undo"})
    # Same container width, but less room for the message, so it wraps sooner.
    assert plain.size.width == with_action.size.width
    assert with_action.size.height >= plain.size.height


# ------------------------------------------------------------------ sheets


def test_bottom_sheet_caps_at_640dp() -> None:
    """M3: "Width: Full width, up to max-width 640dp"."""
    sheet = laid_out({"widget": "BottomSheet"}, Constraints.loose(Size(1400, 700)))
    assert sheet.size.width == BottomSheetElement.MAX_WIDTH == 640.0


def test_bottom_sheet_is_full_width_when_the_window_is_narrower() -> None:
    sheet = laid_out({"widget": "BottomSheet"}, Constraints.loose(Size(500, 700)))
    assert sheet.size.width == 500.0


def test_bottom_sheet_rounds_only_its_top_corners() -> None:
    """M3: 28dp top corner radius. It is flush with the window's bottom edge."""
    assert laid_out({"widget": "BottomSheet"}).effective_radii == (28.0, 28.0, 0.0, 0.0)


def test_bottom_sheet_handle_is_opt_in_and_reserves_space() -> None:
    without = laid_out({"widget": "BottomSheet", "children": [{"widget": "Container"}]})
    with_handle = laid_out(
        {
            "widget": "BottomSheet",
            "style": {"handle": True},
            "children": [{"widget": "Container"}],
        }
    )
    band = BottomSheetElement.HANDLE_HEIGHT + BottomSheetElement.HANDLE_PAD * 2
    assert without.children[0].offset.y == 0.0
    assert with_handle.children[0].offset.y == band == 48.0


def test_side_sheet_caps_at_400dp() -> None:
    """M3: "Max-width: 400dp"."""
    sheet = laid_out({"widget": "SideSheet"}, Constraints.loose(Size(1000, 700)))
    assert sheet.size.width == SideSheetElement.MAX_WIDTH == 400.0


def test_side_sheet_rounds_the_edge_facing_into_the_window() -> None:
    """A right-docked sheet rounds its left corners, and the reverse."""
    right = laid_out({"widget": "SideSheet", "style": {"placement": "right"}})
    left = laid_out({"widget": "SideSheet", "style": {"placement": "left"}})
    assert right.effective_radii == (16.0, 0.0, 0.0, 16.0)
    assert left.effective_radii == (0.0, 16.0, 16.0, 0.0)


def test_side_sheet_fills_the_window_height() -> None:
    sheet = laid_out({"widget": "SideSheet"}, Constraints.loose(Size(1000, 700)))
    assert sheet.size.height == 700.0


def test_sheets_use_surface_container_low() -> None:
    expected = PALETTE.index("surface_container_low")
    assert expected in tokens_in(painted({"widget": "BottomSheet", "style": {"handle": True}}))
    assert expected in tokens_in(painted({"widget": "SideSheet"}))


# ----------------------------------------------------- theming and hosting


@pytest.mark.parametrize("kind", OVERLAY_KINDS)
def test_overlay_components_paint_tokens_not_literal_colours(kind: str) -> None:
    """A literal colour opts the element out of theming entirely."""
    dl = painted({"widget": kind, "text": "Label", "supporting_text": "Sub"})
    assert tokens_in(dl), f"{kind} painted nothing token-coloured"
    for fill in literal_fills(dl):
        assert fill[3] == 0.0, f"{kind} painted an opaque literal colour {fill}"


def test_a_dialog_declared_as_an_overlay_is_modal_and_scrimmed() -> None:
    app = hosted({"widget": "Dialog", "text": "Delete?", "style": {"modal": True, "scrim": True}})
    assert app.overlays.has_modal
    entry = app.overlays.visible()[0]
    assert entry.scrim and entry.modal


def test_an_anchored_menu_positions_against_its_anchor() -> None:
    app = hosted(
        {
            "widget": "Menu",
            "style": {"placement": "anchor", "anchor": "trigger"},
            "children": [{"widget": "MenuItem", "text": "Cut"}],
        },
        root_children=[
            {"name": "trigger", "widget": "Button", "text": "Open", "style": {"height": 40}}
        ],
    )
    trigger = app.root.find("trigger")
    entry = app.overlays.visible()[0]
    # Directly below the anchor, offset by the 4dp default gap.
    assert entry.origin.y == pytest.approx(trigger.absolute_rect().bottom + 4.0)


# -------------------------------------------------- placement without saying


def test_a_sheet_does_not_need_its_placement_spelled_out() -> None:
    """A widget named `BottomSheet` should not require `placement: bottom`.

    Before this, both sheets silently defaulted to the global `center`, so a
    bottom sheet floated in the middle of the window.
    """
    assert hosted({"widget": "BottomSheet"}).overlays.visible()[0].placement == "bottom"
    assert hosted({"widget": "SideSheet"}).overlays.visible()[0].placement == "right"
    assert hosted({"widget": "Snackbar", "text": "x"}).overlays.visible()[0].placement == "bottom"
    assert hosted({"widget": "Dialog", "text": "x"}).overlays.visible()[0].placement == "center"


def test_an_explicit_placement_beats_the_component_default() -> None:
    """Written `center` must be distinguishable from the field's default."""
    app = hosted({"widget": "BottomSheet", "style": {"placement": "center"}})
    assert app.overlays.visible()[0].placement == "center"


def test_naming_an_anchor_implies_anchor_placement() -> None:
    """Naming an anchor and then centring the overlay is never what was meant."""
    app = hosted(
        {"widget": "Tooltip", "text": "Tip", "style": {"anchor": "trigger"}},
        root_children=[
            {"name": "trigger", "widget": "Button", "text": "T", "style": {"height": 40}}
        ],
    )
    assert app.overlays.visible()[0].placement == "anchor"


def test_docked_sheets_sit_flush_while_floating_overlays_keep_a_margin() -> None:
    """M3 rounds only a sheet's inner corners, which only works flush.

    A gap outside an unrounded corner would leave it hanging in mid-air.
    """
    sheet = hosted({"widget": "BottomSheet"}, size=(440, 300)).overlays.visible()[0]
    side = hosted({"widget": "SideSheet"}, size=(440, 300)).overlays.visible()[0]
    bar = hosted({"widget": "Snackbar", "text": "x"}, size=(440, 300)).overlays.visible()[0]

    assert sheet.origin.y + sheet.element.size.height == 300.0
    assert side.origin.x + side.element.size.width == 440.0
    # The snackbar floats clear of the edge instead.
    assert bar.origin.y + bar.element.size.height < 300.0


# ---------------------------------------------------------------- popover


def test_popover_shrinks_to_fit_a_short_subhead() -> None:
    """The claim the whole widget rests on: unlike Dialog and Menu, which have
    an M3-stated MINIMUM and so fill the width they are offered, Popover has
    only a stated MAXIMUM (320dp) and shrinks to its content. A one-word
    subhead in a 1000px-wide window must come back far narrower than 320dp,
    or this is silently behaving like Dialog instead."""
    element = laid_out({"widget": "Popover", "text": "Hi"})
    assert element.size.width < 100.0


def test_popover_caps_at_the_m3_maximum() -> None:
    long_body = "word " * 200
    element = laid_out({"widget": "Popover", "supporting_text": long_body})
    assert element.size.width == pytest.approx(320.0)


def test_an_explicit_width_overrides_shrink_to_fit() -> None:
    element = laid_out({"widget": "Popover", "text": "Hi", "style": {"width": 200}})
    assert element.size.width == pytest.approx(200.0)


def test_popover_has_a_12dp_corner_radius() -> None:
    """`shape.corner.medium`, from the condensed spec's Rich Tooltip row --
    distinct from Dialog's 28dp and Menu's 4dp."""
    element = laid_out({"widget": "Popover", "text": "Hi"})
    assert element.effective_radii == (12.0, 12.0, 12.0, 12.0)


def test_popover_padding_is_asymmetric() -> None:
    """'Top padding: 12dp / Bottom padding: 8dp / Left and right padding:
    16dp' -- not the same value on every side, unlike Dialog's uniform 24dp.

    Checked on the element directly, in element-local coordinates -- painting
    through a hosted `App` would place the glyph at wherever the overlay host
    positions the popover on screen, not at an offset from its own padding.
    """
    from pycopper.layout import OFFSET_ZERO
    from pycopper.paint import DisplayList
    from pycopper.tree.element import PaintContext

    popover = laid_out({"widget": "Popover", "text": "Head"})
    dl = DisplayList()
    ctx = PaintContext(display_list=dl, palette=PALETTE, text=popover.text_engine, pixel_ratio=1.0)
    popover.paint(ctx, OFFSET_ZERO)
    glyphs = [s for s in dl.view if int(s["flags"][0]) == 1]
    assert glyphs, "the subhead did not paint"
    # A small tolerance for the glyph's own left/top bearing -- the pen sits
    # exactly at the padding, but a glyph's ink does not start exactly there.
    assert min(float(g["rect"][0]) for g in glyphs) == pytest.approx(16.0, abs=2.0)
    assert min(float(g["rect"][1]) for g in glyphs) == pytest.approx(12.0, abs=2.0)


def test_popover_subhead_and_body_use_on_surface_variant() -> None:
    """Both text roles in the rich tooltip's colour table -- distinct from
    Dialog, whose headline is `on_surface`, not the variant."""
    tokens = tokens_in(painted({"widget": "Popover", "text": "Head", "supporting_text": "Body"}))
    assert PALETTE.index("on_surface_variant") in tokens
    assert PALETTE.index("on_surface") not in tokens


def test_popover_container_is_surface_container_high() -> None:
    dl = painted({"widget": "Popover", "text": "x"})
    assert PALETTE.index("surface_container_high") in tokens_in(dl)


def test_popover_places_its_action_row_below_the_text() -> None:
    """Mirrors Dialog's own actions-below-body layout: an optional single
    child is the action row, positioned after subhead + body + the gap."""
    element = laid_out(
        {
            "widget": "Popover",
            "text": "Head",
            "children": [{"widget": "Button", "text": "Learn more", "style": {"height": 32}}],
        }
    )
    button = element.child
    assert button is not None
    assert button.offset.y > 12.0  # below the top padding and the subhead


def test_popover_defaults_to_anchor_placement_with_no_anchor_named() -> None:
    """A Popover with nothing to attach to still resolves to `anchor` --
    unlike Tooltip, which only implies it once an `anchor:` is actually named.
    A popover with no anchor centres near the top, the same fallback
    `_anchored` already gives any anchored overlay whose target is missing."""
    assert hosted({"widget": "Popover", "text": "x"}).overlays.visible()[0].placement == "anchor"


def test_an_anchored_popover_positions_against_its_anchor() -> None:
    app = hosted(
        {"widget": "Popover", "text": "Tip", "style": {"anchor": "trigger"}},
        root_children=[
            {"name": "trigger", "widget": "Button", "text": "Open", "style": {"height": 40}}
        ],
    )
    trigger = app.root.find("trigger")
    entry = app.overlays.visible()[0]
    assert entry.origin.y == pytest.approx(trigger.absolute_rect().bottom + 4.0)


def test_a_popover_is_not_modal_and_dismisses_like_a_menu() -> None:
    """M3's persistent rich tooltip is never scrimmed and dismisses on
    outside interaction -- the StyleSpec defaults (`modal: False`,
    `dismissable: True`) are already exactly right and need no override."""
    element = laid_out({"widget": "Popover", "text": "x"})
    assert element.style.modal is False
    assert element.style.dismissable is True

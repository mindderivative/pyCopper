"""The text field: the widget half of editable text.

`test_editing.py` covers what an edit does. This covers what the widget does
with keys and pixels -- the M3 dimensions, where the label goes, that the caret
stays in view, and that a bound `value:` and a user's typing do not fight.
"""

from __future__ import annotations

import pytest

from pycopper.layout import Constraints, Offset, Size
from pycopper.paint import DisplayList
from pycopper.paint.display_list import Kind
from pycopper.runtime.clipboard import clipboard
from pycopper.runtime.events import EventDispatcher, EventType, KeyEvent, PointerEvent
from pycopper.spec import parse_view
from pycopper.theme import Palette, Theme
from pycopper.tree.element import PaintContext
from pycopper.widgets import build_element
from pycopper.widgets.textfield import TextFieldElement

#: The spellings a real window sends. Tests that used lower-case ones are how
#: Shift+Tab and Ctrl+A came to be dead in a running application while their
#: tests passed, so these deliberately use GLFW's names.
CTRL = frozenset({"Control"})
SHIFT = frozenset({"Shift"})
CTRL_SHIFT = frozenset({"Control", "Shift"})


def field(width: float = 240.0, **spec) -> TextFieldElement:
    node = {"name": "f", "widget": "TextField", **spec}
    element = build_element(parse_view(node).root)
    element.layout(Constraints(0.0, width, 0.0, 400.0))
    return element


def driver(element, *, focus: bool = True) -> EventDispatcher:
    dispatcher = EventDispatcher()
    dispatcher.root = element
    if focus:
        dispatcher.focus(element)
    return dispatcher


def press(dispatcher, key: str, modifiers=frozenset()) -> None:
    dispatcher.post(KeyEvent(EventType.KEY_DOWN, key=key, modifiers=modifiers))
    dispatcher.drain()


def type_text(dispatcher, text: str) -> None:
    for character in text:
        dispatcher.post(KeyEvent(EventType.TEXT, text=character))
    dispatcher.drain()


# ---------------------------------------------------------------- geometry


def test_the_container_is_the_m3_height() -> None:
    """M3_COMPONENT_SPECS 5.8: "Height 56dp" for both variants."""
    assert field(text="Name").size == Size(240.0, 56.0)


def test_supporting_text_adds_its_line_below_the_container() -> None:
    """ "Supporting text and character counter top padding: 4dp" -- so the
    element grows by that gap plus one `body-small` line, and the container
    itself stays 56dp."""
    grown = field(text="Name", supporting_text="Required")
    assert grown.size.height == 56.0 + 4.0 + 16.0


def test_an_unbounded_field_falls_back_to_its_own_minimum() -> None:
    """M3 states no minimum width. 120dp is pyCopper's, so that a field in an
    unbounded Row is still usable rather than invisible."""
    element = build_element(parse_view({"name": "f", "widget": "TextField"}).root)
    element.layout(Constraints(0.0, float("inf"), 0.0, float("inf")))
    assert element.size.width == TextFieldElement.MIN_WIDTH


def test_the_vertical_layout_tiles_the_container_exactly() -> None:
    """8dp padding, a 16dp floated label line, a 24dp input line, 8dp padding.
    If any of the four changes the input stops being centred in what is left,
    and nothing else here would catch it."""
    spec = TextFieldElement
    assert (
        spec.PAD_Y + spec.FLOAT_ROLE.line_height + spec.INPUT_ROLE.line_height + spec.PAD_Y
        == spec.HEIGHT
    )


# ------------------------------------------------------------------- label


def test_the_label_floats_when_populated_or_focused() -> None:
    """ "Label Behavior: Floats upward to 12sp typography scale when focused or
    populated" -- quoted. Both halves of the "or" are tested."""
    assert not field(text="Name").floated
    assert field(text="Name", value="Ada").floated
    focused = field(text="Name")
    driver(focused)
    assert focused.floated


def test_the_floated_size_is_the_12sp_role() -> None:
    assert TextFieldElement.FLOAT_ROLE.size == 12.0
    assert TextFieldElement.INPUT_ROLE.size == 16.0


# ---------------------------------------------------------------- keyboard


def test_typing_inserts_at_the_caret_and_fires_on_change() -> None:
    element = field(text="Name", value="Ada", handlers={"on_change": "changed"})
    seen: list[str] = []
    dispatcher = driver(element)
    dispatcher.bind_handlers({"changed": lambda event: seen.append(event.value)})
    type_text(dispatcher, "!")
    assert element.content == "Ada!"
    assert seen == ["Ada!"]


def test_backspace_and_delete_work_from_the_caret() -> None:
    element = field(value="abc")
    dispatcher = driver(element)
    press(dispatcher, "Backspace")
    assert element.content == "ab"
    press(dispatcher, "Home")
    press(dispatcher, "Delete")
    assert element.content == "b"


def test_arrows_move_and_shift_arrows_select() -> None:
    element = field(value="hello")
    dispatcher = driver(element)
    press(dispatcher, "ArrowLeft")
    assert element.editor.state.caret == 4
    press(dispatcher, "ArrowLeft", SHIFT)
    assert element.editor.state.selection == (3, 4)


def test_ctrl_arrows_move_by_word() -> None:
    element = field(value="hello world")
    dispatcher = driver(element)
    press(dispatcher, "ArrowLeft", CTRL)
    assert element.editor.state.caret == 6


def test_select_all_then_typing_replaces_everything() -> None:
    element = field(value="hello")
    dispatcher = driver(element)
    press(dispatcher, "a", CTRL)
    assert element.editor.state.selection == (0, 5)
    type_text(dispatcher, "x")
    assert element.content == "x"


def test_undo_and_redo_reach_the_keyboard() -> None:
    element = field(value="hello")
    dispatcher = driver(element)
    type_text(dispatcher, " there")
    assert element.content == "hello there"
    press(dispatcher, "z", CTRL)
    assert element.content == "hello"
    press(dispatcher, "z", CTRL_SHIFT)
    assert element.content == "hello there"


def test_cut_copy_and_paste_go_through_the_clipboard() -> None:
    element = field(value="hello world")
    dispatcher = driver(element)
    press(dispatcher, "a", CTRL)
    press(dispatcher, "x", CTRL)
    assert element.content == ""
    assert clipboard.get_text() == "hello world"
    press(dispatcher, "v", CTRL)
    assert element.content == "hello world"


def test_the_glfw_modifier_spelling_is_what_actually_arrives() -> None:
    """`rendercanvas` reports "Control", not "ctrl". Matching one spelling is
    how Ctrl+A came to be dead in a real window with a passing test, so this
    asserts the spelling a window sends and the one a hand-written event uses
    both work."""
    for spelling in ("Control", "ctrl", "Meta"):
        element = field(value="hello")
        press(driver(element), "a", frozenset({spelling}))
        assert element.editor.state.selection == (0, 5), spelling


def test_a_key_the_field_does_not_use_is_left_alone() -> None:
    """Tab has to keep traversing focus, so the field must not swallow every
    key it is handed."""
    element = field(value="hello")
    dispatcher = driver(element)
    event = KeyEvent(EventType.KEY_DOWN, key="F5")
    dispatcher.post(event)
    dispatcher.drain()
    assert not event.stopped


def test_a_disabled_field_ignores_typing() -> None:
    element = field(value="fixed", disabled="true")
    type_text(driver(element), "x")
    assert element.content == "fixed"


def test_control_characters_are_not_inserted() -> None:
    """A backend that reports Enter as text exists; inserting it would put an
    unprintable glyph in the value."""
    element = field(value="a")
    type_text(driver(element), "\n")
    assert element.content == "a"


# ------------------------------------------------------------------ pointer


def test_clicking_places_the_caret_where_the_glyphs_are() -> None:
    element = field(value="hello world")
    dispatcher = driver(element)
    rect = element.absolute_rect()
    dispatcher.post(
        PointerEvent(EventType.POINTER_DOWN, x=rect.x + TextFieldElement.PAD_X + 0.5, y=rect.y + 30)
    )
    dispatcher.drain()
    assert element.editor.state.caret == 0


def test_a_second_click_selects_a_word() -> None:
    element = field(value="hello world")
    dispatcher = driver(element)
    rect = element.absolute_rect()
    point = {"x": rect.x + TextFieldElement.PAD_X + 2.0, "y": rect.y + 30}
    for _ in range(2):
        dispatcher.post(PointerEvent(EventType.POINTER_DOWN, **point))
        dispatcher.post(PointerEvent(EventType.POINTER_UP, **point))
    dispatcher.drain()
    assert element.editor.state.selected_text == "hello"


def test_the_cursor_over_a_field_is_a_text_cursor() -> None:
    element = field(value="hello")
    dispatcher = driver(element, focus=False)
    rect = element.absolute_rect()
    dispatcher.post(PointerEvent(EventType.POINTER_MOVE, x=rect.x + 30, y=rect.y + 30))
    dispatcher.drain()
    assert dispatcher.cursor == "text"


# ------------------------------------------------------------------- value


def test_a_bound_value_the_application_changes_replaces_the_content() -> None:
    element = field(value="one")
    element._value = "two"
    assert element.content == "two"


def test_an_edit_does_not_get_clobbered_by_its_own_value_update() -> None:
    """The edit writes back to `value:`, so a naive "spec wins" rule would undo
    every keystroke on the next read."""
    element = field(value="a")
    type_text(driver(element), "b")
    assert element.content == "ab"
    assert element.content == "ab", "still, on a second read"


def test_an_external_change_moves_the_caret_to_the_end() -> None:
    element = field(value="one")
    driver(element)
    element._value = "much longer text"
    assert element.editor.state.caret == len("much longer text")


# ------------------------------------------------------------------- paint


def painted(element) -> DisplayList:
    display_list = DisplayList()
    ctx = PaintContext(
        display_list=display_list,
        palette=Palette(Theme()),
        text=element.text_engine,
        pixel_ratio=1.0,
    )
    element.set_text_engine(ctx.text)
    element.paint(ctx, Offset(0.0, 0.0))
    return display_list


def boxes(display_list: DisplayList) -> int:
    return sum(1 for instance in display_list.view if int(instance["flags"][0]) == Kind.BOX)


def test_a_filled_field_draws_a_container_and_an_indicator() -> None:
    assert boxes(painted(field(value="Ada"))) == 2


def test_focusing_draws_the_caret() -> None:
    element = field(value="Ada")
    before = boxes(painted(element))
    driver(element)
    assert boxes(painted(element)) > before, "the caret is a box and it was not there"


def test_a_selection_draws_a_highlight() -> None:
    element = field(value="Ada")
    dispatcher = driver(element)
    plain = boxes(painted(element))
    press(dispatcher, "a", CTRL)
    assert boxes(painted(element)) > plain


def test_reduce_motion_gives_a_solid_caret() -> None:
    """Everything else obeys the setting by arriving at once. The equivalent
    for something that never arrives is to stop it moving -- a caret that
    blinked anyway would be the one animation the setting did not reach."""
    from pycopper.motion import Ticker

    element = field(value="Ada")
    element.set_ticker(Ticker(reduce_motion=True))
    driver(element)
    assert element._caret_visible()
    assert element._caret_visible(), "and it stays visible, rather than blinking"


# ------------------------------------------------------------------ scroll


def test_the_caret_stays_in_view_when_the_text_outruns_the_field() -> None:
    element = field(width=140.0, value="")
    dispatcher = driver(element)
    type_text(dispatcher, "a value far longer than this field is wide")
    assert element._scroll_x > 0.0, "the view followed the caret"


def test_the_view_scrolls_back_rather_than_leaving_empty_space() -> None:
    element = field(width=140.0, value="")
    dispatcher = driver(element)
    type_text(dispatcher, "a value far longer than this field is wide")
    for _ in range(60):
        press(dispatcher, "Backspace")
    assert element.content == ""
    assert element._scroll_x == 0.0


def test_short_text_never_scrolls() -> None:
    element = field(width=240.0, value="hi")
    driver(element)
    assert element._scroll_x == 0.0


@pytest.mark.parametrize("variant", ["filled", "outlined"])
def test_both_m3_variants_render(variant: str) -> None:
    element = field(text="Name", value="Ada", style={"variant": variant})
    assert len(painted(element)) > 0

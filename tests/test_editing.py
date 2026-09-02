"""The editing model, with no widget attached.

Every rule a text field has to get right is here rather than behind a window:
what a backspace removes, where a word ends, when two keystrokes are one undo
step. A test that has to open a canvas to check that Ctrl-Backspace eats a word
is a test nobody runs.
"""

from __future__ import annotations

import pytest

from pycopper.text.editing import (
    Editor,
    EditState,
    delete_backward,
    delete_forward,
    insert,
    move,
    word_bounds,
)

HELLO = EditState("hello world", 11, 11)
#: "e" plus a combining acute -- two code points, one grapheme cluster.
DECOMPOSED = "cafe\u0301"
#: A regional-indicator pair. Python sees two characters, a reader sees a flag.
FLAG = "a\U0001f1ec\U0001f1e7"


# ---------------------------------------------------------------- selection


def test_a_selection_remembers_which_end_the_caret_is_on() -> None:
    """Anchor and focus, not start and length: shift-arrow has to know which
    end to move, and a backwards selection is a real thing a user makes."""
    backwards = EditState("hello", 4, 1)
    assert backwards.selection == (1, 4)
    assert backwards.caret == 1
    assert backwards.selected_text == "ell"


def test_an_empty_selection_is_not_a_selection() -> None:
    assert not EditState("hello", 2, 2).has_selection
    assert EditState("hello", 2, 3).has_selection


def test_offsets_snap_to_grapheme_boundaries() -> None:
    """The caret cannot land between a letter and its accent, because the next
    keystroke would then split them."""
    assert EditState(DECOMPOSED).collapsed(5).caret == 5
    assert EditState(DECOMPOSED).collapsed(4).caret in (3, 5), "never inside the cluster"


def test_offsets_outside_the_text_are_clamped() -> None:
    assert EditState("abc").collapsed(99).caret == 3
    assert EditState("abc").collapsed(-5).caret == 0


# ------------------------------------------------------------------ motion


def test_arrow_keys_move_one_cluster() -> None:
    assert move(HELLO, "left").caret == 10
    assert move(HELLO.collapsed(0), "right").caret == 1


def test_moving_over_a_combining_mark_takes_the_whole_cluster() -> None:
    state = EditState(DECOMPOSED, 5, 5)
    assert move(state, "left").caret == 3, "e and its accent move together"


def test_moving_over_a_flag_takes_both_halves() -> None:
    state = EditState(FLAG, len(FLAG), len(FLAG))
    assert move(state, "left").caret == 1


def test_home_and_end_go_to_the_ends() -> None:
    assert move(HELLO, "home").caret == 0
    assert move(HELLO.collapsed(0), "end").caret == 11


def test_word_motion_skips_the_space_before_the_word() -> None:
    assert move(HELLO, "word_left").caret == 6
    assert move(EditState("hello world", 6, 6), "word_left").caret == 0
    assert move(EditState("hello world", 0, 0), "word_right").caret == 5


def test_shift_arrow_extends_from_the_anchor() -> None:
    extended = move(move(HELLO, "left", extend=True), "left", extend=True)
    assert extended.selection == (9, 11)
    assert extended.anchor == 11, "the anchor stayed where the selection began"


def test_an_unextended_arrow_collapses_to_the_edge_of_a_selection() -> None:
    """Press Right with three words selected and the caret goes to the end of
    them -- not one character past wherever the caret happened to sit. Every
    editor does this, and it is invisible until it is missing.
    """
    selected = EditState("hello world", 2, 8)
    assert move(selected, "right").caret == 8
    assert move(selected, "left").caret == 2
    assert not move(selected, "left").has_selection


def test_an_unknown_motion_is_an_error() -> None:
    with pytest.raises(ValueError, match="unknown motion"):
        move(HELLO, "sideways")


# ------------------------------------------------------------------- edits


def test_insert_puts_text_at_the_caret() -> None:
    assert insert(EditState("hello", 5, 5), "!").text == "hello!"
    assert insert(EditState("hello", 0, 0), ">").caret == 1


def test_insert_replaces_a_selection() -> None:
    assert insert(EditState("hello world", 6, 11), "there").text == "hello there"


def test_backspace_removes_one_cluster_not_one_character() -> None:
    """The whole reason offsets go through the segmenter: backspacing an
    accented character has to remove the character, not leave a bare accent."""
    assert delete_backward(EditState(DECOMPOSED, 5, 5)).text == "caf"
    assert delete_backward(EditState(FLAG, 3, 3)).text == "a"


def test_backspace_removes_a_selection_whole() -> None:
    assert delete_backward(EditState("hello world", 5, 11)).text == "hello"


def test_backspace_at_the_start_does_nothing() -> None:
    start = EditState("hello", 0, 0)
    assert delete_backward(start) == start


def test_delete_removes_forwards() -> None:
    assert delete_forward(EditState("hello", 0, 0)).text == "ello"
    assert delete_forward(EditState("hello", 5, 5)).text == "hello", "at the end, nothing"


def test_word_deletion_matches_word_motion() -> None:
    assert delete_backward(HELLO, word=True).text == "hello "
    assert delete_forward(EditState("hello world", 0, 0), word=True).text == " world"


def test_an_out_of_range_caret_still_edits_sanely() -> None:
    """Nothing in the widget produces one, but `EditState` is a plain dataclass
    and a caller can build anything. Silently deleting nothing would be the
    worst of the options."""
    assert delete_backward(EditState("abc", 99, 99)).text == "ab"


# ------------------------------------------------------------------- words


def test_word_bounds_agrees_with_selection_double_click() -> None:
    """They must: double-clicking a word and then Ctrl-Backspacing it should
    take the same text. Both use the whitespace rule, which is not UAX #29 and
    is documented as such rather than implied to be Unicode-correct."""
    from pycopper.text.selection import word_at

    for offset in range(len("hello world")):
        assert word_bounds("hello world", offset) == word_at("hello world", offset)


# -------------------------------------------------------------------- undo


def test_typing_a_run_is_one_undo_step() -> None:
    """Undoing a sentence letter by letter is nobody's idea of undo."""
    editor = Editor("")
    for character in "hello":
        editor.edit(insert(editor.state, character), "type")
    assert editor.text == "hello"
    assert editor.undo()
    assert editor.text == ""


def test_a_caret_move_breaks_the_run() -> None:
    editor = Editor("")
    for character in "ab":
        editor.edit(insert(editor.state, character), "type")
    editor.set_caret(0)
    editor.edit(insert(editor.state, "X"), "type")
    editor.undo()
    assert editor.text == "ab", "the move started a new step"


def test_a_deletion_is_its_own_step() -> None:
    editor = Editor("hello")
    editor.edit(insert(editor.state, "!"), "type")
    editor.edit(delete_backward(editor.state), "delete")
    assert editor.text == "hello"
    editor.undo()
    assert editor.text == "hello!"


def test_undo_restores_the_selection_too() -> None:
    """So an undone deletion leaves you where you were, rather than at the end
    of the field wondering what happened."""
    editor = Editor("hello world")
    editor.select(6, 11)
    editor.edit(delete_backward(editor.state), "delete")
    assert editor.text == "hello "
    editor.undo()
    assert editor.state.selection == (6, 11)


def test_redo_replays_and_a_new_edit_discards_it() -> None:
    editor = Editor("a")
    editor.edit(insert(editor.state, "b"), "type")
    editor.undo()
    assert editor.can_redo
    editor.redo()
    assert editor.text == "ab"
    editor.undo()
    editor.edit(insert(editor.state, "c"), "type")
    assert not editor.can_redo, "the redo branch was abandoned"


def test_undo_on_an_untouched_editor_reports_it_did_nothing() -> None:
    editor = Editor("hello")
    assert not editor.undo()
    assert not editor.redo()
    assert editor.text == "hello"


def test_an_external_value_clears_the_history() -> None:
    """A bound `value:` changing did not come from the user, so offering to
    undo back to what they typed would restore something the application has
    already moved past."""
    editor = Editor("draft")
    editor.edit(insert(editor.state, "!"), "type")
    editor.set_text("from the application")
    assert not editor.can_undo
    assert editor.text == "from the application"


def test_the_history_is_bounded() -> None:
    """A long-lived field would otherwise keep every state anyone ever typed
    into it for the life of the process."""
    editor = Editor("", limit=5)
    for index in range(20):
        # A kind that never coalesces, so every one is its own step.
        editor.edit(insert(editor.state, str(index)), "delete")
    assert len(editor._undo) == 5


def test_an_edit_that_changes_nothing_is_not_a_step() -> None:
    editor = Editor("hello")
    assert not editor.edit(delete_backward(EditState("hello", 0, 0)), "delete")
    assert not editor.can_undo

"""Mouse text selection.

Two layers: the geometry in `text/selection.py`, which maps points to
character offsets and back, and the `Text` widget that drives it.
"""

from __future__ import annotations

import pytest

from pycopper import App, Settings, Theme
from pycopper.paint import DisplayList
from pycopper.runtime.clipboard import Clipboard, clipboard
from pycopper.runtime.events import EventType, KeyEvent, PointerEvent
from pycopper.text import TextEngine
from pycopper.text.selection import index_at, rects_for, word_at

ENGINE = TextEngine()


def para(text: str, px: float = 20.0, max_width: float | None = None):
    return ENGINE.layout(text, px=px, max_width=max_width)


# ---------------------------------------------------------------- geometry


def test_a_point_maps_to_a_character_offset() -> None:
    p = para("Hello world")
    assert index_at(p, 0.0, 5.0) == 0
    assert index_at(p, 10_000.0, 5.0) == len(p.text)


def test_the_offset_increases_across_the_line() -> None:
    p = para("Hello world")
    offsets = [index_at(p, x, 5.0) for x in range(0, 120, 10)]
    assert offsets == sorted(offsets)


def test_the_nearest_edge_wins_not_the_containing_glyph() -> None:
    """Clicking the left half of a character puts the caret before it. Anything
    else makes click-and-drag feel like it lags a character behind."""
    p = para("Hello")
    rects = rects_for(p, 0, 1)
    first = rects[0]
    assert index_at(p, first.width * 0.1, 5.0) == 0
    assert index_at(p, first.width * 0.9, 5.0) == 1


def test_an_offset_never_lands_inside_a_grapheme_cluster() -> None:
    """A base character and its combining accent are one unit; a caret between
    them would render as a stray mark."""
    text = "ábc"  # 'a' + combining acute
    p = para(text)
    reachable = {index_at(p, x, 5.0) for x in range(0, 80, 2)}
    assert 1 not in reachable, "the caret split a combining sequence"
    assert reachable <= {0, 2, 3, 4}


def test_an_empty_range_produces_no_rectangle() -> None:
    """A caret is not a selection; a zero-width rect is a stray sliver."""
    assert rects_for(para("Hello"), 3, 3) == []


def test_a_reversed_range_is_normalised() -> None:
    """Dragging right-to-left must highlight the same thing."""
    p = para("Hello world")
    assert rects_for(p, 7, 2) == rects_for(p, 2, 7)


def test_a_wrapped_selection_gives_one_rectangle_per_line() -> None:
    p = para("the quick brown fox jumps over the lazy dog", px=16, max_width=120)
    assert len(p.lines) > 1
    rects = rects_for(p, 0, len(p.text))
    assert len(rects) == len(p.lines)
    assert [r.y for r in rects] == sorted(r.y for r in rects)


def test_a_point_below_the_text_clamps_to_the_last_line() -> None:
    p = para("one\ntwo", max_width=200)
    assert index_at(p, 0.0, 10_000.0) >= p.lines[-1].start


def test_empty_text_maps_to_zero() -> None:
    assert index_at(para(""), 50.0, 50.0) == 0
    assert rects_for(para(""), 0, 5) == []


@pytest.mark.parametrize(
    ("offset", "expected"),
    [(0, "Hello"), (3, "Hello"), (7, "world"), (11, "world")],
)
def test_word_at_finds_the_surrounding_word(offset: int, expected: str) -> None:
    text = "Hello world"
    start, end = word_at(text, offset)
    assert text[start:end] == expected


def test_word_at_on_empty_text_is_safe() -> None:
    assert word_at("", 0) == (0, 0)


# ------------------------------------------------------------------ widget


def hosted(*, selectable: bool = True, text: str = "Hello selectable world"):
    app = App(
        {
            "root": {
                "name": "root",
                "widget": "Column",
                "style": {"background": "surface", "padding": 10},
                "children": [
                    {
                        "name": "t",
                        "widget": "Text",
                        "text": text,
                        "style": {
                            "font_size": 20,
                            "selectable": selectable,
                            "width": 300,
                            "height": 40,
                        },
                    },
                    {"name": "plain", "widget": "Text", "text": "label", "style": {"height": 30}},
                ],
            }
        },
        theme=Theme(dark=True),
        settings=Settings(width=340, height=140),
    )
    app.mount()
    app.paint(DisplayList())
    return app, app.root.find("t")


def drag(app: App, widget, x0: float, x1: float, y: float = 14.0) -> None:
    app.dispatcher.post(PointerEvent(EventType.POINTER_DOWN, x=x0, y=y))
    app.dispatcher.drain()
    widget.state.pressed = True
    app.dispatcher.post(PointerEvent(EventType.POINTER_MOVE, x=x1, y=y))
    app.dispatcher.drain()
    app.dispatcher.post(PointerEvent(EventType.POINTER_UP, x=x1, y=y))
    app.dispatcher.drain()
    app.paint(DisplayList())


def test_dragging_selects_text() -> None:
    app, text = hosted()
    drag(app, text, 12, 70)
    assert text.selected_text
    assert text.selected_text in "Hello selectable world"


def test_a_plain_label_selects_nothing() -> None:
    """Selectable is off by default: a label that shows a text cursor and
    swallows drags is wrong for most of the text in an interface."""
    app, text = hosted(selectable=False)
    drag(app, text, 12, 70)
    assert text.selected_text == ""


def test_selectable_text_takes_focus_so_it_can_be_copied() -> None:
    """Key events go to the focused element, so without this Ctrl+C reaches
    nothing at all."""
    app, text = hosted()
    drag(app, text, 12, 70)
    assert app.dispatcher.focused is text


def test_a_plain_label_is_not_focusable() -> None:
    app, _text = hosted()
    assert not app.dispatcher._focusable(app.root.find("plain"))


def test_ctrl_c_copies_the_selection() -> None:
    app, text = hosted()
    drag(app, text, 12, 70)
    expected = text.selected_text
    clipboard.install(None)
    app.dispatcher.post(KeyEvent(EventType.KEY_DOWN, key="c", modifiers=frozenset({"ctrl"})))
    app.dispatcher.drain()
    assert clipboard.get_text() == expected


def test_ctrl_a_selects_everything() -> None:
    app, text = hosted()
    app.dispatcher.post(PointerEvent(EventType.POINTER_DOWN, x=12, y=14))
    app.dispatcher.drain()
    app.dispatcher.post(KeyEvent(EventType.KEY_DOWN, key="a", modifiers=frozenset({"ctrl"})))
    app.dispatcher.drain()
    assert text.selected_text == "Hello selectable world"


def test_a_bare_key_does_nothing() -> None:
    app, text = hosted()
    text.select_all()
    app.dispatcher.post(KeyEvent(EventType.KEY_DOWN, key="c"))
    app.dispatcher.drain()
    assert text.selected_text == "Hello selectable world", "an unmodified key changed it"


def test_selectable_text_shows_a_text_cursor() -> None:
    app, _text = hosted()
    app.dispatcher.post(PointerEvent(EventType.POINTER_MOVE, x=50, y=14))
    app.dispatcher.drain()
    assert app.dispatcher.cursor == "text"


def test_an_explicit_cursor_still_wins() -> None:
    app = App(
        {
            "root": {
                "name": "root",
                "widget": "Column",
                "style": {"background": "surface"},
                "children": [
                    {
                        "name": "t",
                        "widget": "Text",
                        "text": "hi",
                        "style": {
                            "selectable": True,
                            "cursor": "crosshair",
                            "width": 200,
                            "height": 40,
                        },
                    }
                ],
            }
        },
        theme=Theme(dark=True),
        settings=Settings(width=240, height=100),
    )
    app.mount()
    app.paint(DisplayList())
    app.dispatcher.post(PointerEvent(EventType.POINTER_MOVE, x=20, y=10))
    app.dispatcher.drain()
    assert app.dispatcher.cursor == "crosshair"


def test_the_highlight_is_painted_behind_the_glyphs() -> None:
    """Over them it would tint the letters it is meant to sit behind."""
    from pycopper.paint import Kind

    app, text = hosted()
    text.select_all()
    dl = DisplayList()
    app.paint(dl)
    kinds = [int(s["flags"][0]) for s in dl.view]
    boxes = [i for i, k in enumerate(kinds) if k == int(Kind.BOX)]
    glyphs = [i for i, k in enumerate(kinds) if k == int(Kind.GLYPH)]
    assert boxes and glyphs
    assert min(boxes) < min(glyphs)


def test_selecting_nothing_paints_no_highlight() -> None:
    app, text = hosted()
    before = len(list(iter_view(app)))
    text.select_all()
    after = len(list(iter_view(app)))
    assert after > before
    text.clear_selection()
    assert len(list(iter_view(app))) == before


def iter_view(app: App):
    dl = DisplayList()
    app.paint(dl)
    return list(dl.view)


# --------------------------------------------------------------- clipboard


def test_the_clipboard_is_in_process_by_default() -> None:
    """pyCopper ships no system clipboard: rendercanvas exposes none, and the
    only route is the backend's private window handle."""
    board = Clipboard()
    assert not board.system_backed
    assert board.set_text("hi") is False
    assert board.get_text() == "hi", "the in-process copy must still work"


def test_an_application_can_install_a_real_one() -> None:
    board = Clipboard()
    seen: list[str] = []

    class Fake:
        def set_text(self, text: str) -> bool:
            seen.append(text)
            return True

        def get_text(self) -> str:
            return "from system"

    board.install(Fake())
    assert board.system_backed
    assert board.set_text("copied") is True
    assert seen == ["copied"]
    assert board.get_text() == "from system"


def test_a_failing_backend_never_breaks_a_frame() -> None:
    board = Clipboard()

    class Broken:
        def set_text(self, text: str) -> bool:
            raise RuntimeError("no clipboard here")

        def get_text(self) -> str:
            raise RuntimeError("no clipboard here")

    board.install(Broken())
    assert board.set_text("x") is False
    assert board.get_text() == "x", "it lost the in-process copy on failure"

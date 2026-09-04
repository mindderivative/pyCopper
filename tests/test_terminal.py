"""Terminal: a real shell, spawned and parsed internally.

M3 has no terminal component -- checked directly, not assumed absent, the
same way every other ungrounded widget this session was.

Most tests here never spawn a real process: `TerminalElement` only starts
its PTY session from `set_ticker()` (called by `App`, never by a bare
`build_element(...).layout(...)`), so rendering and key-forwarding logic is
exercised by attaching a `pyte` screen directly (`_attach_screen`) or by
injecting a fake session (`_FakeSession`) -- the same seam the widget's own
`_feed()` method exists for. A handful of tests at the bottom spawn a real
`/bin/sh` to prove the actual pipeline works end to end, skipped if
`pyte`/`pexpect` are not installed.
"""

from __future__ import annotations

import sys
import time

import pytest

from pycopper.layout import INF, Constraints, Size
from pycopper.motion.animation import Ticker
from pycopper.runtime.events import (
    FOCUSABLE_KINDS,
    EventDispatcher,
    EventType,
    KeyEvent,
    WheelEvent,
)
from pycopper.spec import WidgetKind, parse_view
from pycopper.widgets import build_element
from pycopper.widgets.base import _REGISTRY
from pycopper.widgets.terminal import (
    _PTY_AVAILABLE,
    _PYTE_AVAILABLE,
    TerminalElement,
    _cell_color,
)

try:
    import pyte
except ImportError:
    pyte = None  # type: ignore[assignment]

CTRL = frozenset({"Control"})
SHIFT = frozenset({"Shift"})

REAL_PTY = _PYTE_AVAILABLE and _PTY_AVAILABLE and sys.platform != "win32"


def terminal(width: float = 400.0, height: float = 200.0, **spec) -> TerminalElement:
    node = {"name": "t", "widget": "Terminal", **spec}
    element = build_element(parse_view(node).root)
    element.layout(Constraints(0.0, width, 0.0, height))
    return element


def _attach_screen(element: TerminalElement, cols: int = 20, rows: int = 5) -> None:
    """Give the element a real pyte screen with no real PTY behind it."""
    element._cols, element._rows = cols, rows
    screen = pyte.HistoryScreen(cols, rows, history=200)
    element._screen = screen
    element._stream = pyte.ByteStream(screen)


class _FakeSession:
    def __init__(self, alive: bool = True) -> None:
        self.alive = alive
        self.written: list[bytes] = []

    def write(self, data: bytes) -> None:
        self.written.append(data)


def driver(element, *, focus: bool = True) -> EventDispatcher:
    dispatcher = EventDispatcher()
    dispatcher.root = element
    if focus:
        dispatcher.focus(element)
    return dispatcher


def press(dispatcher, key: str, modifiers=frozenset()) -> None:
    dispatcher.post(KeyEvent(EventType.KEY_DOWN, key=key, modifiers=modifiers))
    dispatcher.drain()


# --------------------------------------------------------------- registered


def test_kind_builds() -> None:
    assert terminal() is not None


def test_every_kind_is_registered() -> None:
    assert set(_REGISTRY) == set(WidgetKind)


def test_is_focusable() -> None:
    assert "Terminal" in FOCUSABLE_KINDS


def test_never_started_shows_the_unavailable_message_not_a_crash() -> None:
    """No `set_ticker` call means no PTY session -- `build_element(...)
    .layout(...)` alone must never spawn a process."""
    element = terminal()
    assert element._session is None
    assert element._screen is None


# ------------------------------------------------------------------ layout


def test_an_unbounded_size_falls_back_to_the_default_grid() -> None:
    element = build_element(parse_view({"name": "t", "widget": "Terminal"}).root)
    element.layout(Constraints(0.0, INF, 0.0, INF))
    assert element._cols == TerminalElement.DEFAULT_COLS
    assert element._rows == TerminalElement.DEFAULT_ROWS


def test_a_bounded_size_is_honoured() -> None:
    element = terminal(width=500.0, height=300.0)
    assert element.size == Size(500.0, 300.0)


def test_the_grid_follows_the_pixel_size() -> None:
    small = terminal(width=200.0, height=100.0)
    large = terminal(width=800.0, height=400.0)
    assert large._cols > small._cols
    assert large._rows > small._rows


def test_resizing_updates_an_attached_screens_dimensions() -> None:
    element = terminal(width=300.0, height=150.0)
    _attach_screen(element, cols=element._cols, rows=element._rows)
    before = (element._screen.columns, element._screen.lines)
    element.layout(Constraints(0.0, 900.0, 0.0, 450.0))
    after = (element._screen.columns, element._screen.lines)
    assert after != before
    assert element._screen.columns == element._cols
    assert element._screen.lines == element._rows


# ------------------------------------------------------------------ command


def test_shell_defaults_to_the_environment(monkeypatch) -> None:
    monkeypatch.setenv("SHELL", "/bin/zsh")
    element = terminal()
    assert element._command() == "/bin/zsh"


def test_shell_falls_back_when_unset(monkeypatch) -> None:
    monkeypatch.delenv("SHELL", raising=False)
    element = terminal()
    assert element._command() == "/bin/sh"


def test_an_explicit_shell_style_wins(monkeypatch) -> None:
    monkeypatch.setenv("SHELL", "/bin/zsh")
    element = terminal(style={"shell": "bash -l"})
    assert element._command() == "bash -l"


# ------------------------------------------------------------------- colour


def test_named_ansi_colours_resolve() -> None:
    assert _cell_color("red", (0, 0, 0, 1)) != (0, 0, 0, 1)
    assert _cell_color("brightblue", (0, 0, 0, 1)) != (0, 0, 0, 1)


def test_default_falls_back_to_the_given_colour() -> None:
    default = (0.1, 0.2, 0.3, 1.0)
    assert _cell_color("default", default) == default


def test_a_hex_colour_is_parsed() -> None:
    """`ff8000` is sRGB 100%/50%/0% -- converted to linear, red stays at 1.0
    (a fixed point of the sRGB curve) but green drops well below its sRGB
    reading, which is exactly the point of the conversion (see `_srgb`)."""
    r, g, b, a = _cell_color("ff8000", (0, 0, 0, 1))
    assert round(r, 2) == 1.0
    assert 0.15 < g < 0.30
    assert b == 0.0
    assert a == 1.0


def test_an_unrecognised_name_falls_back() -> None:
    default = (0.1, 0.2, 0.3, 1.0)
    assert _cell_color("not-a-colour", default) == default


# -------------------------------------------------------------- rendering


@pytest.mark.skipif(pyte is None, reason="pyte not installed")
def test_feeding_bytes_renders_without_crashing() -> None:
    element = terminal()
    _attach_screen(element)
    element._feed(b"hello\r\n")
    from pycopper.paint import DisplayList
    from pycopper.theme import Palette, Theme
    from pycopper.tree.element import PaintContext

    ctx = PaintContext(display_list=DisplayList(), palette=Palette(Theme(dark=True)))
    element.paint(ctx, element.offset.__class__(0.0, 0.0))
    assert len(ctx.display_list.view) > 0


@pytest.mark.skipif(pyte is None, reason="pyte not installed")
def test_coloured_output_paints_more_than_plain_text() -> None:
    from pycopper.paint import DisplayList
    from pycopper.theme import Palette, Theme
    from pycopper.tree.element import PaintContext

    def render(data: bytes) -> int:
        element = terminal()
        _attach_screen(element)
        element._feed(data)
        ctx = PaintContext(display_list=DisplayList(), palette=Palette(Theme(dark=True)))
        element.paint(ctx, element.offset.__class__(0.0, 0.0))
        return len(ctx.display_list.view)

    plain = render(b"plain text\r\n")
    coloured = render(b"\x1b[41mred background\x1b[0m\r\n")
    assert coloured > plain


# --------------------------------------------------------------- scrollback


@pytest.mark.skipif(pyte is None, reason="pyte not installed")
def test_wheel_up_scrolls_back_through_history() -> None:
    element = terminal()
    _attach_screen(element, cols=20, rows=5)
    for i in range(40):
        element._feed(f"line{i}\r\n".encode())
    before = element._screen.history.position
    element.on_wheel(WheelEvent(EventType.WHEEL, dy=-100.0))
    assert element._screen.history.position < before


@pytest.mark.skipif(pyte is None, reason="pyte not installed")
def test_wheel_down_returns_toward_the_bottom() -> None:
    element = terminal()
    _attach_screen(element, cols=20, rows=5)
    for i in range(40):
        element._feed(f"line{i}\r\n".encode())
    element.on_wheel(WheelEvent(EventType.WHEEL, dy=-100.0))
    scrolled = element._screen.history.position
    element.on_wheel(WheelEvent(EventType.WHEEL, dy=100.0))
    assert element._screen.history.position > scrolled


def test_wheel_with_no_screen_does_nothing() -> None:
    element = terminal()
    element.on_wheel(WheelEvent(EventType.WHEEL, dy=-100.0))  # must not raise


# ------------------------------------------------------------------ keyboard


def test_typing_forwards_utf8_bytes() -> None:
    element = terminal()
    element._session = _FakeSession()
    element.on_text(KeyEvent(EventType.TEXT, text="q"))
    assert element._session.written == [b"q"]


def test_control_characters_in_on_text_are_ignored() -> None:
    """`on_key_down` handles named/control keys by name; `on_text` must not
    also forward their raw control-code text, or a key like Enter would be
    sent to the shell twice."""
    element = terminal()
    element._session = _FakeSession()
    element.on_text(KeyEvent(EventType.TEXT, text="\r"))
    assert element._session.written == []


def test_arrow_keys_send_the_expected_escape_sequences() -> None:
    element = terminal()
    element._session = _FakeSession()
    element.on_key_down(KeyEvent(EventType.KEY_DOWN, key="ArrowUp"))
    element.on_key_down(KeyEvent(EventType.KEY_DOWN, key="ArrowDown"))
    element.on_key_down(KeyEvent(EventType.KEY_DOWN, key="ArrowLeft"))
    element.on_key_down(KeyEvent(EventType.KEY_DOWN, key="ArrowRight"))
    assert element._session.written == [b"\x1b[A", b"\x1b[B", b"\x1b[D", b"\x1b[C"]


def test_enter_and_backspace() -> None:
    element = terminal()
    element._session = _FakeSession()
    element.on_key_down(KeyEvent(EventType.KEY_DOWN, key="Enter"))
    element.on_key_down(KeyEvent(EventType.KEY_DOWN, key="Backspace"))
    assert element._session.written == [b"\r", b"\x7f"]


def test_ctrl_c_sends_the_interrupt_byte_not_a_copy() -> None:
    element = terminal()
    element._session = _FakeSession()
    element.on_key_down(KeyEvent(EventType.KEY_DOWN, key="c", modifiers=CTRL))
    assert element._session.written == [b"\x03"]


def test_ctrl_d_sends_end_of_transmission() -> None:
    element = terminal()
    element._session = _FakeSession()
    element.on_key_down(KeyEvent(EventType.KEY_DOWN, key="d", modifiers=CTRL))
    assert element._session.written == [b"\x04"]


def test_tab_sends_a_tab_byte_and_shift_tab_sends_back_tab() -> None:
    element = terminal()
    element._session = _FakeSession()
    element.on_key_down(KeyEvent(EventType.KEY_DOWN, key="Tab"))
    element.on_key_down(KeyEvent(EventType.KEY_DOWN, key="Tab", modifiers=SHIFT))
    assert element._session.written == [b"\t", b"\x1b[Z"]


def test_tab_does_not_move_focus_away_from_the_terminal() -> None:
    """The same dispatcher-level fix `CodeEditor` needed: `CAPTURES_TAB`
    keeps Tab routed here instead of the dispatcher's default focus
    traversal."""
    element = terminal()
    element._session = _FakeSession()
    dispatcher = driver(element)
    press(dispatcher, "Tab")
    assert dispatcher.focused is element
    assert element._session.written == [b"\t"]


def test_paste_writes_the_clipboard() -> None:
    from pycopper.runtime.clipboard import clipboard

    clipboard.set_text("pasted text")
    element = terminal()
    element._session = _FakeSession()
    element.on_key_down(KeyEvent(EventType.KEY_DOWN, key="v", modifiers=CTRL))
    assert element._session.written == [b"pasted text"]


def test_disabled_terminal_ignores_input() -> None:
    element = terminal(disabled="true")
    element._session = _FakeSession()
    element.on_text(KeyEvent(EventType.TEXT, text="q"))
    element.on_key_down(KeyEvent(EventType.KEY_DOWN, key="Enter"))
    assert element._session.written == []


def test_no_session_means_no_crash_on_input() -> None:
    element = terminal()
    element.on_text(KeyEvent(EventType.TEXT, text="q"))
    element.on_key_down(KeyEvent(EventType.KEY_DOWN, key="Enter"))  # must not raise


def test_write_input_is_public_and_reaches_the_session() -> None:
    element = terminal()
    element._session = _FakeSession()
    element.write_input("echo hi\n")
    assert element._session.written == [b"echo hi\n"]


# --------------------------------------------------------------- disposal


def test_dispose_stops_the_session() -> None:
    element = terminal()
    stopped = []

    class _Session(_FakeSession):
        def stop(self) -> None:
            stopped.append(True)

    element._session = _Session()
    element.dispose()
    assert stopped == [True]
    assert element._session is None


# -------------------------------------------------------- real end to end


@pytest.mark.skipif(not REAL_PTY, reason="pyte/pexpect not available on this platform")
def test_a_real_shell_produces_visible_output() -> None:
    element = terminal(width=400.0, height=200.0, style={"shell": "/bin/sh -c 'echo hello-pty'"})
    element.set_ticker(Ticker())
    try:
        deadline = time.monotonic() + 5.0
        found = False
        while time.monotonic() < deadline:
            element._drain_pty()
            if element._screen is not None and any(
                "hello-pty" in "".join(element._screen.buffer[r][c].data for c in range(20))
                for r in range(5)
            ):
                found = True
                break
            time.sleep(0.05)
        assert found, "the real shell's output never reached the pyte screen"
    finally:
        element.dispose()


@pytest.mark.skipif(not REAL_PTY, reason="pyte/pexpect not available on this platform")
def test_a_real_shell_receives_keyboard_input() -> None:
    element = terminal(width=400.0, height=200.0, style={"shell": "/bin/cat"})
    element.set_ticker(Ticker())
    try:
        element.on_text(KeyEvent(EventType.TEXT, text="p"))
        deadline = time.monotonic() + 5.0
        found = False
        while time.monotonic() < deadline:
            element._drain_pty()
            if element._screen is not None and "p" in "".join(
                element._screen.buffer[0][c].data for c in range(10)
            ):
                found = True
                break
            time.sleep(0.05)
        assert found, "typed input never echoed back through the real pty"
    finally:
        element.dispose()

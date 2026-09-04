"""Terminal: a real shell, spawned and parsed internally.

M3 has no terminal component -- checked directly against `M3-References`,
the same way every other ungrounded widget this session was. Asked of the
user directly, the same way `Video`'s frame-sink-vs-bundled-decoder fork
was: should this widget only render a cell grid an application feeds it
(`Video`'s own shape), or own the whole pipeline -- spawning the shell and
parsing its output -- internally? The answer was the latter: a view says
`widget: Terminal, style: {shell: "/bin/bash"}` and it works, with no
per-application PTY or VT-parsing boilerplate.

**Three layers, two of them someone else's problem.** Spawning a real
pseudo-terminal is OS-specific process management; interpreting its byte
stream is the VT/ANSI state machine every real terminal emulator implements
identically. Neither is this widget's own concern to reinvent -- `pexpect`
(ISC) gives POSIX PTY spawning, `pyte` (LGPLv3) gives the state machine, and
what is actually left for pyCopper to build is the third layer: rendering
whatever cell grid `pyte.Screen.buffer` says is currently true, and turning
keystrokes into the bytes a shell expects. Both are optional extras
(`pycopper[terminal]`), never hard dependencies -- `pyte`'s licence alone
would force that, the same rule `accesskit` already follows.

**Only POSIX is implemented and verified in this pass.** `pexpect.spawn`
was exercised directly (spawn a shell, read its output through
`read_nonblocking`, feed it to `pyte.ByteStream`, read the resulting
`screen.display` back) before being relied on. Windows needs a different
backend entirely -- `pywinpty` wrapping ConPTY; `pexpect.spawn` is
POSIX-only -- architected for (the platform check is a real branch) but not
built, since nothing here could verify it rather than guess. `sys.platform
== "win32"` leaves the widget simply unstarted rather than guessing at an
unverified API, the honest choice `AccessKit`'s own "untested on Windows and
macOS" precedent already sets.

**No PTY mutation happens off the engine thread.** The background reader
thread's only job is to append raw bytes to a lock-guarded buffer --
ARCHITECTURE.md 8's "the engine thread owns everything mutable" applies to
`pyte.Screen` exactly as it does to a `Signal`, so feeding the byte stream
and repainting both happen later, back on the engine thread, in
`_drain_pty()`. When a real `asyncio` loop can be captured, the reader
thread also calls `loop.call_soon_threadsafe(...)` to wake an idle app
promptly -- the identical pattern `VideoElement.push_frame`'s own docstring
already prescribes for "a worker thread has news". Whether or not that wake
succeeds, `paint_self` unconditionally drains pending bytes on every call it
gets for any reason -- and while a session is alive this widget keeps a
`repeat=True` animation running purely to guarantee a repaint (regardless of
focus, so a terminal nobody is looking at still updates), roughly twice a
second either way. The wake is an optimisation for instant updates, not a
correctness requirement -- output is never permanently stuck even if loop
capture fails.

**No bundled monospace font**, the identical gap `CodeEditor` documents --
only Roboto and Noto Sans ship, both proportional. `style.font_family`
requests a face by name through the same machinery; an application loads a
real monospace one itself with `app.text.db.load(path)` first. Cell
backgrounds and the cursor are positioned on an analytic `column *
cell_width` grid regardless of the resolved font's own metrics, so they
always line up; the *glyphs drawn inside* a run of same-styled cells are
laid out with the text engine's ordinary shaping, which only lands exactly
on that grid when the requested font is genuinely monospace -- a
proportional fallback still runs, just without the columns of `ls` or a
box-drawn table lining up.

**Deliberately out of scope for this pass**: mouse text selection and
copy (Ctrl+C is always the interrupt byte here, never a copy shortcut,
since there is nothing to copy without a selection), underline and
strikethrough rendering, function keys beyond F1-F4, true-colour-aware
theme adaptation (the ANSI palette is fixed, not part of the M3 theme), and
Windows support.
"""

from __future__ import annotations

import contextlib
import os
import shlex
import sys
import threading
from collections.abc import Callable
from typing import Any, Final

import numpy as np

from ..layout import Constraints, EdgeInsets, Offset, Padding, Size
from ..paint import NO_TOKEN
from ..runtime.clipboard import clipboard
from ..runtime.events import is_accelerator, modifiers_of
from ..spec import WidgetSpec
from ..text.fontdb import FontRequest
from ..theme import srgb_to_linear
from ..tree.element import PaintContext
from .base import _StyledMixin

__all__ = ["TerminalElement"]

try:
    import pyte

    _PYTE_AVAILABLE = True
except ImportError:
    _PYTE_AVAILABLE = False

if sys.platform != "win32":
    try:
        import pexpect

        _PTY_AVAILABLE = True
    except ImportError:
        _PTY_AVAILABLE = False
else:
    _PTY_AVAILABLE = False


def _srgb(r: float, g: float, b: float, a: float = 1.0) -> tuple[float, float, float, float]:
    """An sRGB-intended colour, converted to the linear RGBA every literal
    `color=` on the display list actually expects.

    Verified empirically, not assumed: the render target is
    `rgba8unorm-srgb` (ARCHITECTURE.md 5.6.1), which encodes linear values
    written to it -- a literal `color=(0.5, 0.5, 0.5, 1.0)` reads back as
    `(188, 188, 188)`, not `(128, 128, 128)`, unless converted first. Passing
    unconverted "looks about right" floats is exactly the double-encoding
    bug ARCHITECTURE.md 5.6.1 already documents for the palette upload path;
    this is the same mistake, once removed, on a literal colour instead.
    """
    lr, lg, lb = srgb_to_linear(np.array([r, g, b], dtype=np.float64))
    return (float(lr), float(lg), float(lb), a)


#: The conventional 16-colour ANSI palette. Not M3-sourced -- there is no M3
#: concept of terminal colour at all -- literal RGBA for the identical reason
#: `CodeEditor`'s syntax colours are: no semantic role exists to map any of
#: this onto. Tuned to read against a dark background; there is no light
#: variant, the same one-scheme choice `CodeEditor` makes. Written as the
#: sRGB values they are meant to look like; `_srgb()` converts each to the
#: linear form the shader actually wants.
_ANSI_COLORS: Final[dict[str, tuple[float, float, float, float]]] = {
    "black": _srgb(0.11, 0.11, 0.13),
    "red": _srgb(0.87, 0.35, 0.35),
    "green": _srgb(0.55, 0.75, 0.40),
    "brown": _srgb(0.85, 0.70, 0.35),  # pyte's own name for ANSI yellow
    "blue": _srgb(0.40, 0.60, 0.90),
    "magenta": _srgb(0.75, 0.50, 0.85),
    "cyan": _srgb(0.40, 0.75, 0.80),
    "white": _srgb(0.80, 0.80, 0.82),
    "brightblack": _srgb(0.40, 0.42, 0.46),
    "brightred": _srgb(0.95, 0.45, 0.45),
    "brightgreen": _srgb(0.65, 0.85, 0.50),
    "brightbrown": _srgb(0.95, 0.80, 0.45),
    "brightblue": _srgb(0.55, 0.70, 0.95),
    "brightmagenta": _srgb(0.85, 0.60, 0.95),
    "brightcyan": _srgb(0.55, 0.85, 0.90),
    "brightwhite": _srgb(0.95, 0.95, 0.97),
}
_DEFAULT_FG: Final = _srgb(0.85, 0.85, 0.88)
_DEFAULT_BG: Final = _srgb(0.10, 0.10, 0.12)


def _cell_color(
    name: str, default: tuple[float, float, float, float]
) -> tuple[float, float, float, float]:
    """A pyte cell colour name (`"red"`, `"brightblue"`, a 6-hex-digit
    256-colour/truecolour string, or `"default"`) resolved to linear RGBA."""
    if name == "default":
        return default
    known = _ANSI_COLORS.get(name)
    if known is not None:
        return known
    if len(name) == 6:
        try:
            return _srgb(
                int(name[0:2], 16) / 255.0,
                int(name[2:4], 16) / 255.0,
                int(name[4:6], 16) / 255.0,
            )
        except ValueError:
            pass
    return default


#: Named keys translated to the bytes a POSIX terminal sends for them
#: (xterm's own "normal" cursor-key mode, not application mode -- pyCopper
#: never negotiates DECCKM). Plain character keys are deliberately absent:
#: those arrive through `on_text` instead, and including them here would
#: send every printable character twice.
_KEY_BYTES: Final[dict[str, bytes]] = {
    "arrowup": b"\x1b[A",
    "up": b"\x1b[A",
    "arrowdown": b"\x1b[B",
    "down": b"\x1b[B",
    "arrowright": b"\x1b[C",
    "right": b"\x1b[C",
    "arrowleft": b"\x1b[D",
    "left": b"\x1b[D",
    "home": b"\x1b[H",
    "end": b"\x1b[F",
    "pageup": b"\x1b[5~",
    "pagedown": b"\x1b[6~",
    "delete": b"\x1b[3~",
    "insert": b"\x1b[2~",
    "f1": b"\x1bOP",
    "f2": b"\x1bOQ",
    "f3": b"\x1bOR",
    "f4": b"\x1bOS",
    "enter": b"\r",
    "return": b"\r",
    "backspace": b"\x7f",
    "escape": b"\x1b",
}


class _PtySession:
    """Owns exactly one background thread: reading a pty is a blocking
    syscall, and the only thing that thread does is append raw bytes to a
    lock-guarded buffer. Feeding them to `pyte` and repainting both happen
    later, back on the engine thread -- see the module docstring.
    """

    def __init__(self, command: str) -> None:
        self._command = command
        self._child: Any = None
        self._thread: threading.Thread | None = None
        self._stop = threading.Event()
        self._lock = threading.Lock()
        self._pending = bytearray()
        self._loop: Any = None
        self._on_output: Callable[[], None] | None = None

    @property
    def alive(self) -> bool:
        return self._child is not None and bool(self._child.isalive())

    def start(self, size: tuple[int, int], on_output: Callable[[], None]) -> None:
        self._on_output = on_output
        try:
            import asyncio

            self._loop = asyncio.get_running_loop()
        except RuntimeError:
            # No loop running yet (or ever) -- see the module docstring:
            # the periodic repaint fallback covers this, just less promptly.
            self._loop = None
        cols, rows = size
        parts = shlex.split(self._command) or ["/bin/sh"]
        self._child = pexpect.spawn(
            parts[0], parts[1:], dimensions=(rows, cols), encoding=None, timeout=None
        )
        self._thread = threading.Thread(target=self._run, name="pycopper-terminal", daemon=True)
        self._thread.start()

    def _run(self) -> None:
        while not self._stop.is_set():
            try:
                chunk = self._child.read_nonblocking(size=4096, timeout=0.2)
            except pexpect.TIMEOUT:
                continue
            except Exception:
                break  # EOF (process exited) or the fd was closed under us
            if not chunk:
                continue
            with self._lock:
                self._pending.extend(chunk)
            if self._loop is not None and self._on_output is not None:
                self._loop.call_soon_threadsafe(self._on_output)

    def drain(self) -> bytes:
        with self._lock:
            data, self._pending = bytes(self._pending), bytearray()
        return data

    def write(self, data: bytes) -> None:
        if self._child is not None and self._child.isalive():
            self._child.send(data)

    def resize(self, cols: int, rows: int) -> None:
        if self._child is not None and self._child.isalive():
            self._child.setwinsize(rows, cols)

    def stop(self) -> None:
        self._stop.set()
        if self._child is not None:
            with contextlib.suppress(Exception):
                self._child.close(force=True)
        if self._thread is not None:
            self._thread.join(timeout=2.0)
            self._thread = None


class TerminalElement(_StyledMixin, Padding):
    """A real shell, rendered as a grid of styled monospace cells.

    `style.shell` names the command line to run (`shlex.split`, so
    `"bash -l"` works); unset resolves `$SHELL`, falling back to `/bin/sh`.
    `style.font_family`/`font_size` pick the face and cell size, the same
    fields `CodeEditor` reads. `text:`/`value:` are unused -- there is no
    buffer to bind, only a live process.
    """

    PAD_X: Final = 4.0
    PAD_Y: Final = 4.0
    #: Not sourced -- there is no M3 page for this widget at all -- the
    #: classic default grid every terminal emulator without an explicit
    #: size falls back to.
    DEFAULT_COLS: Final = 80
    DEFAULT_ROWS: Final = 24
    #: Lines of history `pyte.HistoryScreen` keeps. Not exposed as a style
    #: property -- one more knob a v1 does not need.
    SCROLLBACK: Final = 2000
    CURSOR_BLINK_PERIOD: Final = 1.0
    CAPTURES_TAB = True
    CURSOR = "text"

    def __init__(self, spec: WidgetSpec) -> None:
        Padding.__init__(self, None, EdgeInsets())
        self.init_element(spec)
        self._session: _PtySession | None = None
        self._screen: Any = None
        self._stream: Any = None
        self._cols = self.DEFAULT_COLS
        self._rows = self.DEFAULT_ROWS

    # ------------------------------------------------------------- lifecycle

    def set_ticker(self, ticker: Any) -> None:
        super().set_ticker(ticker)
        self._ensure_started()

    def dispose(self) -> None:
        if self._session is not None:
            self._session.stop()
            self._session = None
        super().dispose()

    def _command(self) -> str:
        shell = self.style.shell
        if shell:
            return shell
        return os.environ.get("SHELL") or "/bin/sh"

    def _ensure_started(self) -> None:
        if self._session is not None or not (_PYTE_AVAILABLE and _PTY_AVAILABLE):
            return
        screen = pyte.HistoryScreen(self._cols, self._rows, history=self.SCROLLBACK)
        # An instance override of `Screen`'s own documented no-op extension
        # point (its docstring: "By default is a noop") -- simpler than a
        # subclass for one method, verified to work (no __slots__ on pyte's
        # Screen/HistoryScreen).
        screen.write_process_input = self._write_input  # type: ignore[method-assign]
        self._screen = screen
        self._stream = pyte.ByteStream(screen)
        session = _PtySession(self._command())
        self._session = session
        session.start((self._cols, self._rows), self._on_output)

    def _write_input(self, data: str) -> None:
        if self._session is not None:
            self._session.write(data.encode("utf-8", "ignore"))

    def _on_output(self) -> None:
        """The PTY wake callback -- may run via `call_soon_threadsafe` from
        the reader thread, so it must do nothing beyond what `_drain_pty`
        already does safely on the engine thread."""
        self._drain_pty()
        self.mark_needs_paint()

    def _drain_pty(self) -> None:
        if self._session is None or self._stream is None:
            return
        data = self._session.drain()
        if data:
            self._stream.feed(data)

    def _feed(self, data: bytes) -> None:
        """Feed bytes directly into the VT parser, bypassing any real PTY.

        The seam a test uses to exercise rendering without a real subprocess
        -- see `tests/test_terminal.py`.
        """
        if self._stream is not None:
            self._stream.feed(data)

    # ---------------------------------------------------------------- layout

    def _font_request(self) -> FontRequest:
        return FontRequest(family=self.style.font_family or "Roboto", weight=self.style.font_weight)

    def _cell_size(self) -> Size:
        style = self.style
        request = self._font_request()
        one = self.text_engine.measure(
            "M", px=style.font_size, request=request, line_height=style.line_height
        )
        two = self.text_engine.measure("MM", px=style.font_size, request=request)
        # A real monospace face reports every glyph at this same advance;
        # "M" is a conventional reference character for a fallback that is
        # not one. See the module docstring on grid alignment.
        width = two.width - one.width
        return Size(width if width > 0 else one.width, one.height)

    def perform_layout(self, constraints: Constraints) -> Size:
        outer = self.sized(constraints, self.style)
        cell = self._cell_size()
        width = (
            outer.max_width
            if outer.has_bounded_width
            else self.DEFAULT_COLS * cell.width + 2 * self.PAD_X
        )
        height = (
            outer.max_height
            if outer.has_bounded_height
            else self.DEFAULT_ROWS * cell.height + 2 * self.PAD_Y
        )
        size = outer.constrain(Size(width, height))
        cols = max(1, int((size.width - 2 * self.PAD_X) / cell.width))
        rows = max(1, int((size.height - 2 * self.PAD_Y) / cell.height))
        if (cols, rows) != (self._cols, self._rows):
            self._cols, self._rows = cols, rows
            if self._screen is not None:
                self._screen.resize(lines=rows, columns=cols)
            if self._session is not None:
                self._session.resize(cols, rows)
        return size

    # ----------------------------------------------------------------- paint

    def paint_self(self, ctx: PaintContext, absolute: Offset) -> None:
        self._drain_pty()
        if self.size.is_empty:
            return
        style = self.style
        dpr = ctx.pixel_ratio
        ctx.display_list.add_box(
            absolute.x * dpr,
            absolute.y * dpr,
            self.size.width * dpr,
            self.size.height * dpr,
            token=ctx.palette.index(style.background) if style.background else NO_TOKEN,
            color=(1.0, 1.0, 1.0, 1.0) if style.background else _DEFAULT_BG,
            radii=tuple(r * dpr for r in self.effective_radii),  # type: ignore[arg-type]
            clip=ctx.clip,
            clip_radii=ctx.clip_radii,
        )
        if self._screen is None:
            self._paint_unavailable(ctx, absolute)
            return

        cell = self._cell_size()
        origin = Offset(absolute.x + self.PAD_X, absolute.y + self.PAD_Y)
        self._paint_rows(ctx, origin, cell)
        if self._session is not None and self._session.alive:
            self._paint_cursor(ctx, origin, cell)
            # Keeps a repaint scheduled roughly twice a second for as long as
            # a session is alive, focused or not -- see the module docstring
            # on why output must not depend on an async wake succeeding.
            self.animated(
                "terminal_poll",
                1.0,
                duration=self.CURSOR_BLINK_PERIOD,
                curve="linear",
                repeat=True,
            )
        else:
            poll = self.animation("terminal_poll")
            if poll is not None:
                self.ticker.discard(poll)

    def _paint_unavailable(self, ctx: PaintContext, absolute: Offset) -> None:
        message = (
            "pyte/pexpect not installed (pycopper[terminal])"
            if not (_PYTE_AVAILABLE and _PTY_AVAILABLE)
            else "Terminal is not implemented on this platform"
        )
        self.text_engine.emit(
            ctx.display_list,
            self.text_engine.layout(message, px=self.style.font_size),
            x=absolute.x + self.PAD_X,
            y=absolute.y + self.PAD_Y,
            pixel_ratio=ctx.pixel_ratio,
            token=ctx.palette.index("error"),
            clip=ctx.clip,
            clip_radii=ctx.clip_radii,
        )

    def _paint_rows(self, ctx: PaintContext, origin: Offset, cell: Size) -> None:
        screen = self._screen
        dpr = ctx.pixel_ratio
        request = self._font_request()
        for row in range(self._rows):
            line = screen.buffer[row]
            y = origin.y + row * cell.height
            col = 0
            while col < self._cols:
                start = col
                first = line[col]
                fg_name, bg_name = first.fg, first.bg
                if first.reverse:
                    fg_name, bg_name = bg_name, fg_name
                text_chars: list[str] = []
                col += 1
                if first.data:
                    text_chars.append(first.data)
                while col < self._cols:
                    ch = line[col]
                    ch_fg, ch_bg = ch.fg, ch.bg
                    if ch.reverse:
                        ch_fg, ch_bg = ch_bg, ch_fg
                    if ch_fg != fg_name or ch_bg != bg_name:
                        break
                    if ch.data:
                        text_chars.append(ch.data)
                    col += 1
                width_cols = col - start
                bg = _cell_color(bg_name, _DEFAULT_BG)
                if bg != _DEFAULT_BG:
                    ctx.display_list.add_box(
                        (origin.x + start * cell.width) * dpr,
                        y * dpr,
                        width_cols * cell.width * dpr,
                        cell.height * dpr,
                        color=bg,
                        clip=ctx.clip,
                        clip_radii=ctx.clip_radii,
                    )
                text = "".join(text_chars)
                if text.strip():
                    fg = _cell_color(fg_name, _DEFAULT_FG)
                    paragraph = self.text_engine.layout(
                        text, px=self.style.font_size, request=request
                    )
                    self.text_engine.emit(
                        ctx.display_list,
                        paragraph,
                        x=origin.x + start * cell.width,
                        y=y,
                        pixel_ratio=dpr,
                        color=fg,
                        clip=ctx.clip,
                        clip_radii=ctx.clip_radii,
                    )

    def _paint_cursor(self, ctx: PaintContext, origin: Offset, cell: Size) -> None:
        screen = self._screen
        if screen.cursor.hidden or screen.history.position < screen.history.size:
            return
        if not self.state.focused:
            return
        phase = self.animated(
            "cursor_blink", 1.0, duration=self.CURSOR_BLINK_PERIOD, curve="linear", repeat=True
        )
        if not self.ticker.reduce_motion and phase >= 0.5:
            return
        dpr = ctx.pixel_ratio
        x = origin.x + screen.cursor.x * cell.width
        y = origin.y + screen.cursor.y * cell.height
        ctx.display_list.add_box(
            x * dpr,
            y * dpr,
            cell.width * dpr,
            cell.height * dpr,
            color=_ANSI_COLORS["brightwhite"],
            opacity=0.5,
            clip=ctx.clip,
            clip_radii=ctx.clip_radii,
        )

    # ------------------------------------------------------------- pointer

    def on_wheel(self, event: Any) -> None:
        if self._screen is None:
            return
        if event.dy < 0:
            self._screen.prev_page()
        elif event.dy > 0:
            self._screen.next_page()
        else:
            return
        self.mark_needs_paint()
        event.stop_propagation()

    def on_focus(self, event: Any) -> None:
        self.mark_needs_paint()

    def on_blur(self, event: Any) -> None:
        self.mark_needs_paint()

    # -------------------------------------------------------------- keyboard

    def write_input(self, text: str) -> None:
        """Send *text* to the shell as if it had been typed. Public: an
        application composing a terminal into a larger workflow (running a
        prepared command, say) has no other way to reach the PTY."""
        if self._session is not None:
            self._session.write(text.encode("utf-8", "ignore"))

    def on_text(self, event: Any) -> None:
        if self.effective_disabled or self._session is None:
            return
        text = str(getattr(event, "text", ""))
        if not text or text < " ":
            return
        self.write_input(text)
        event.stop_propagation()

    def on_key_down(self, event: Any) -> None:
        if self.effective_disabled or self._session is None:
            return
        key = str(getattr(event, "key", "")).lower()
        mods = modifiers_of(event)
        if key == "tab":
            self._session.write(b"\x1b[Z" if "shift" in mods else b"\t")
            event.stop_propagation()
            return
        if is_accelerator(mods) and key == "v":
            pasted = clipboard.get_text()
            if pasted:
                self.write_input(pasted)
            event.stop_propagation()
            return
        if "ctrl" in mods and len(key) == 1 and key.isalpha():
            self._session.write(bytes([ord(key.upper()) - 64]))
            event.stop_propagation()
            return
        data = _KEY_BYTES.get(key)
        if data is not None:
            self._session.write(data)
            event.stop_propagation()

"""Held-key repeat: App synthesizes it, because rendercanvas's GLFW backend
does not.

`rendercanvas.glfw._on_key` drops every `glfw.REPEAT` action outright
(confirmed by reading it directly: `else: # glfw.REPEAT / return`), so a
real held key never reaches pyCopper's own event system more than once --
without this, holding Backspace/Delete/an arrow key acts exactly once and
then does nothing until released and pressed again. Found live, holding
Backspace in the CodeEditor demo.
"""

from __future__ import annotations

from pycopper import App, Theme
from pycopper.app import KEY_REPEAT_DELAY, KEY_REPEAT_INTERVAL
from pycopper.paint import DisplayList
from pycopper.runtime.events import EventType

VIEW = {"name": "root", "widget": "Container", "style": {"width": 200, "height": 200}}


def app_with_frozen_clock() -> App:
    """An App whose clock is driven by hand -- `_advance_key_repeat` reads
    real elapsed time via `self.clock`, so a test needs to control it
    exactly rather than racing the wall clock."""
    a = App(VIEW, theme=Theme(dark=True))
    a._t = 0.0  # type: ignore[attr-defined]
    a.clock = lambda: a._t  # type: ignore[attr-defined]
    a.mount()
    a.paint(DisplayList())
    return a


def advance(app: App, seconds: float) -> None:
    """Simulate `seconds` of real time, in steps small enough that
    `_advance_key_repeat`'s own `MAX_FRAME_DELTA` clamp (the same one
    `Ticker.tick` uses, so a paused debugger does not fire a catch-up burst
    of repeats) never kicks in and silently eats simulated time -- a real
    held key elapses this way too, as many small frames, never one big
    jump."""
    from pycopper.motion.animation import MAX_FRAME_DELTA

    step = MAX_FRAME_DELTA / 2
    remaining = seconds
    while remaining > 0:
        this_step = min(step, remaining)
        app._t += this_step  # type: ignore[attr-defined]
        app.paint(DisplayList())
        remaining -= this_step


def press(app: App, key: str = "backspace") -> None:
    app._on_canvas_event({"event_type": "key_down", "key": key, "modifiers": ()})


def release(app: App, key: str = "backspace") -> None:
    app._on_canvas_event({"event_type": "key_up", "key": key, "modifiers": ()})


def spy_on_key_downs(app: App) -> list[str]:
    """Wrap the dispatcher's own `post` to record every KEY_DOWN key seen,
    real presses and synthesized repeats alike -- there is no widget in
    `VIEW` that reacts to one, and there does not need to be: this tests
    the repeat mechanism itself, not any widget's response to it."""
    seen: list[str] = []
    original = app.dispatcher.post

    def wrapped(event: object) -> None:
        if getattr(event, "type", None) == EventType.KEY_DOWN:
            seen.append(getattr(event, "key", ""))
        original(event)

    app.dispatcher.post = wrapped  # type: ignore[method-assign]
    return seen


def test_no_repeat_before_the_initial_delay() -> None:
    app = app_with_frozen_clock()
    seen = spy_on_key_downs(app)
    press(app)
    advance(app, KEY_REPEAT_DELAY - 0.05)
    assert seen == ["backspace"], "only the real press, nothing synthesized yet"


def test_a_repeat_fires_once_the_delay_passes() -> None:
    app = app_with_frozen_clock()
    seen = spy_on_key_downs(app)
    press(app)
    advance(app, KEY_REPEAT_DELAY + 0.01)
    assert seen == ["backspace", "backspace"], "the delay elapsed, so one repeat fired"


def test_repeats_keep_coming_at_the_interval_while_held() -> None:
    app = app_with_frozen_clock()
    seen = spy_on_key_downs(app)
    press(app)
    advance(app, KEY_REPEAT_DELAY)
    for _ in range(5):
        advance(app, KEY_REPEAT_INTERVAL)
    # 1 real press + 1 at the delay + 5 more at the interval.
    assert len(seen) == 7, seen


def test_releasing_the_key_stops_the_repeat() -> None:
    app = app_with_frozen_clock()
    seen = spy_on_key_downs(app)
    press(app)
    advance(app, KEY_REPEAT_DELAY)
    release(app)
    for _ in range(5):
        advance(app, KEY_REPEAT_INTERVAL)
    assert len(seen) == 2, "nothing fires after release, however many frames follow"


def test_pressing_a_different_key_restarts_the_delay() -> None:
    """Switching keys without releasing the first should not inherit
    however far the first key's repeat had gotten -- only the most
    recently pressed key repeats, the same rule a real OS follows."""
    app = app_with_frozen_clock()
    seen = spy_on_key_downs(app)
    press(app, "backspace")
    advance(app, KEY_REPEAT_DELAY)  # backspace is now repeating
    press(app, "delete")
    advance(app, KEY_REPEAT_DELAY - 0.05)
    assert seen[-1] == "delete", "the real press of the new key"
    assert seen.count("delete") == 1, "the new key's own delay has not elapsed yet"


def test_a_quick_tap_never_repeats() -> None:
    """The everyday case: pressing and releasing well inside the delay
    window must never synthesize anything."""
    app = app_with_frozen_clock()
    seen = spy_on_key_downs(app)
    press(app)
    advance(app, 0.05)
    release(app)
    advance(app, KEY_REPEAT_DELAY * 2)
    assert seen == ["backspace"]

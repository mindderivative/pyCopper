"""End-to-end: MD3 token -> palette -> GPU clear -> pixel readback.

This is the M0 acceptance test and the integration-level guard for the colour
space boundary (ARCHITECTURE.md 5.6.1). test_palette.py checks the maths; this
checks that the maths survives a real render pass on a real ``*-srgb`` surface.
"""

from __future__ import annotations

import numpy as np
import pytest
from materialyoucolor.dynamiccolor.material_dynamic_colors import MaterialDynamicColors
from materialyoucolor.scheme.scheme_tonal_spot import SchemeTonalSpot

from pycopper import Theme

pytestmark = pytest.mark.gpu


def md3_srgb(token: str, theme: Theme) -> np.ndarray:
    scheme = SchemeTonalSpot(theme.hct(), theme.dark, theme.contrast)
    attr = getattr(MaterialDynamicColors, token)
    return np.array(attr.get_rgba(scheme)[:3], dtype=np.float64)


def test_frame_has_expected_shape(render_once) -> None:
    frame = render_once(width=64, height=64)
    assert frame.shape == (64, 64, 4)
    assert frame.dtype == np.uint8


def test_clear_matches_md3_surface_token(render_once) -> None:
    """The rendered pixel must equal the MD3 surface token, not a washed-out one."""
    theme = Theme(seed="#6750A4", dark=True)
    frame = render_once(theme=theme)

    actual = frame[32, 32, :3].astype(np.float64)
    expected = md3_srgb("surface", theme)

    assert actual == pytest.approx(expected, abs=2.0), (
        f"expected ~{expected} got {actual}; a large positive delta means the "
        f"palette was uploaded sRGB-encoded and double-encoded by the surface"
    )


def test_clear_is_uniform(render_once) -> None:
    frame = render_once()
    assert np.all(frame[:, :, :3] == frame[0, 0, :3])


def test_light_theme_is_brighter(render_once) -> None:
    dark = render_once(theme=Theme(dark=True))[32, 32, :3].astype(int).sum()
    light = render_once(theme=Theme(dark=False))[32, 32, :3].astype(int).sum()
    assert light > dark


def test_frame_counter_advances(offscreen_engine) -> None:
    engine = offscreen_engine()
    engine.canvas.request_draw(engine.draw_frame)
    assert engine.frame_count == 0
    engine.canvas.draw()
    assert engine.frame_count == 1


def test_closing_releases_gpu_objects_in_order(offscreen_engine) -> None:
    """Closing the window used to segfault the process.

    rendercanvas terminates GLFW from a class attribute's `__del__` precisely
    so it happens late, because "the release of the surface should happen
    before the termination of glfw" -- otherwise the process segfaults on exit
    (pygfx/pygfx#642). An `Engine` reached from a module-level `App`, which is
    how every example here is written, stays alive until interpreter shutdown
    and loses that race: closing the window destroyed the native window and
    left a live wgpu surface pointing at it.

    `Engine.close` releases the surface first, then what the device owns, then
    the device, and `run()` calls it in a `finally`. The segfault itself needs
    a real windowed surface to reproduce; what is checkable here is that the
    ordering runs cleanly and that calling it twice -- `run()`'s `finally` plus
    an application closing explicitly -- is harmless.
    """
    engine = offscreen_engine()
    engine.canvas.request_draw(engine.draw_frame)
    engine.canvas.draw()
    engine.close()
    engine.close()
    assert getattr(engine, "context", None) is None
    assert getattr(engine, "device", None) is None


# ------------------------------------------------------- resize coalescing


def burst(engine, count: int, rate: float) -> tuple[int, int]:
    """Feed *count* configures a second apart at *rate*, as a drag does."""
    from pycopper.runtime.engine import DrawCancelled

    drawn = cancelled = 0
    now = [0.0]
    engine.clock = lambda: now[0]
    for i in range(count):
        now[0] += 1.0 / rate
        engine.canvas.set_logical_size(400 + i, 300)
        try:
            engine.draw_frame()
            drawn += 1
        except DrawCancelled:
            cancelled += 1
    return drawn, cancelled


def test_a_resize_burst_is_coalesced_to_the_display_rate(offscreen_engine) -> None:
    """The measured bug. rendercanvas draws and presents once per compositor
    configure during a resize, synchronously, bypassing its own fps throttle;
    a real drag produced 410 configures a second. With vsync each present
    waits for the display, so ~60 finish and the rest queue -- which is why
    the window trailed the pointer by seconds and then caught up.

    Declining the ones that arrive too close together has to bring the present
    rate down to something vsync can actually service.
    """
    engine = offscreen_engine(width=400, height=300)
    drawn, cancelled = burst(engine, 400, rate=410.0)
    assert drawn < 70, f"presented {drawn} times in a second; vsync can service ~60"
    assert cancelled > 300, "almost all of a 410/s burst should be declined"


def test_the_first_resize_after_a_pause_is_drawn_at_once(offscreen_engine) -> None:
    """The gate must not add latency to an ordinary resize -- only to a burst
    arriving faster than the display can show it."""
    from pycopper.runtime.engine import DrawCancelled

    engine = offscreen_engine(width=400, height=300)
    now = [10.0]
    engine.clock = lambda: now[0]
    engine.canvas.set_logical_size(500, 300)
    try:
        engine.draw_frame()
    except DrawCancelled:
        pytest.fail("a resize after a quiet period was declined")


def test_drawing_at_an_unchanged_size_is_never_declined(offscreen_engine) -> None:
    """The gate keys on the size changing, so ordinary animation frames -- a
    caret, a state layer, a progress sweep -- go through untouched however
    fast they arrive."""
    from pycopper.runtime.engine import DrawCancelled

    engine = offscreen_engine(width=400, height=300)
    now = [0.0]
    engine.clock = lambda: now[0]
    engine.canvas.request_draw(engine.draw_frame)
    engine.canvas.draw()
    for _ in range(50):
        now[0] += 0.0001
        try:
            engine.draw_frame()
        except DrawCancelled:
            pytest.fail("an animation frame was declined as if it were a resize")


def test_a_declined_frame_asks_to_come_back(offscreen_engine) -> None:
    """Otherwise the last configure of a drag could be the one that is
    declined, and the window would be left showing the size before it."""
    engine = offscreen_engine(width=400, height=300)
    asked: list[int] = []
    engine.canvas.request_draw = lambda *a: asked.append(1)  # type: ignore[method-assign]
    _, cancelled = burst(engine, 20, rate=410.0)
    assert cancelled, "the burst was not fast enough to decline anything"
    assert len(asked) == cancelled, "a declined frame did not schedule a replacement"


def test_the_very_first_frame_is_never_declined(offscreen_engine) -> None:
    """It has no previous present to be too close to. Getting this wrong makes
    an application open to an empty window until something else asks for a
    frame."""
    from pycopper.runtime.engine import DrawCancelled

    engine = offscreen_engine(width=400, height=300)
    engine.clock = lambda: 0.0
    try:
        engine.draw_frame()
    except DrawCancelled:
        pytest.fail("the first frame of the application was declined")


def test_wayland_decorations_defaults_to_the_portable_choice() -> None:
    """`server` is opt-in on purpose. GNOME offers no server-side decorations
    for xdg-shell, so defaulting to it would leave those users with a window
    that has no title bar and no way to close it."""
    from pycopper import Settings

    assert Settings().wayland_decorations == "auto"
    assert Settings(wayland_decorations="server").wayland_decorations == "server"
    with pytest.raises(ValueError):
        Settings(wayland_decorations="client")

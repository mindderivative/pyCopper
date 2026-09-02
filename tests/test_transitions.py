"""Overlay fades and state-layer cross-fades.

Both wire existing components to the motion system (5.17). The interesting
assertions are the ones about what must *not* change: a dismissed modal stops
swallowing clicks immediately, and an app whose transitions have landed goes
back to rendering nothing.
"""

from __future__ import annotations

import pytest

from pycopper import App, Settings, Signal, Theme
from pycopper.paint import NO_TOKEN, DisplayList
from pycopper.runtime.events import EventType, PointerEvent
from pycopper.runtime.overlay import ENTER_DURATION, EXIT_DURATION
from pycopper.widgets.material import HOVER, PRESS


class Clock:
    """A hand-driven clock, so a transition is sampled where we mean."""

    def __init__(self) -> None:
        self.t = 0.0

    def __call__(self) -> float:
        return self.t


def hosted(*, overlays=None, children=None, **settings):
    app = App(
        {
            "root": {
                "name": "root",
                "widget": "Column",
                "style": {"background": "surface"},
                "children": children or [{"name": "bg", "widget": "Text", "text": "behind"}],
            },
            "overlays": overlays or [],
        },
        theme=Theme(dark=True),
        settings=Settings(width=400, height=300, **settings),
    )
    return app


DIALOG = {
    "name": "dlg",
    "widget": "Dialog",
    "text": "Delete?",
    "open": "{{ show.get() }}",
    "style": {"modal": True, "scrim": True},
}


def dialog_app(**settings):
    show = Signal(False)
    app = hosted(overlays=[DIALOG], **settings)
    clock = Clock()
    app.expose(show=show)
    app.clock = clock
    app.mount()
    app.paint(DisplayList())
    return app, show, clock


# ------------------------------------------------------------ overlay fades


def test_an_overlay_fades_in_rather_than_appearing() -> None:
    app, show, clock = dialog_app()
    entry = app.overlays.entries[0]
    assert entry.opacity == 0.0

    show.set(True)
    app.paint(DisplayList())
    assert entry.opacity == 0.0, "it appeared at full opacity"

    clock.t = 0.05
    app.paint(DisplayList())
    assert 0.0 < entry.opacity < 1.0

    for step in range(10):
        clock.t = 0.05 + step * 0.05
        app.paint(DisplayList())
    assert entry.opacity == pytest.approx(1.0)


def test_an_overlay_keeps_rendering_while_it_fades_out() -> None:
    """The point of separating `rendered()` from `visible()`."""
    app, show, clock = dialog_app()
    show.set(True)
    for step in range(12):
        clock.t = step * 0.05
        app.paint(DisplayList())

    show.set(False)
    clock.t += 0.05
    app.paint(DisplayList())
    assert len(app.overlays.rendered()) == 1, "it vanished instead of fading"
    assert app.overlays.entries[0].opacity > 0.0


def test_a_dismissed_modal_stops_blocking_input_immediately() -> None:
    """It must not keep swallowing clicks for the 200ms it spends fading."""
    app, show, clock = dialog_app()
    show.set(True)
    for step in range(12):
        clock.t = step * 0.05
        app.paint(DisplayList())
    assert app.overlays.has_modal

    show.set(False)
    clock.t += 0.02
    app.paint(DisplayList())
    assert not app.overlays.has_modal, "a fading dialog still blocked the tree"
    assert app.overlays.visible() == []
    assert len(app.overlays.rendered()) == 1  # still on screen, just not live


def test_the_fade_out_finishes_and_the_app_goes_idle() -> None:
    app, show, clock = dialog_app()
    show.set(True)
    for step in range(12):
        clock.t = step * 0.05
        app.paint(DisplayList())
    show.set(False)
    for _ in range(12):
        clock.t += 0.05
        app.paint(DisplayList())

    assert app.overlays.rendered() == []
    assert not app.motion.active, "the overlay kept asking for frames after leaving"


def test_enter_and_exit_use_different_m3_timings() -> None:
    """M3's own table: "Emphasized decelerate | 400ms | Enter the screen" and
    "Emphasized accelerate | 200ms | Exit the screen". A thing arrives gently
    and departs briskly."""
    from pycopper.motion import DURATION

    assert DURATION[ENTER_DURATION] == 0.400
    assert DURATION[EXIT_DURATION] == 0.200

    app, show, clock = dialog_app()
    show.set(True)
    app.paint(DisplayList())
    animation = app.overlays.entries[0].element.animation("overlay_opacity")
    assert animation.duration == 0.400

    for step in range(12):
        clock.t = step * 0.05
        app.paint(DisplayList())
    show.set(False)
    clock.t += 0.02
    app.paint(DisplayList())
    assert animation.duration == 0.200, "the exit reused the enter timing"


def test_the_scrim_fades_with_the_dialog_it_backs() -> None:
    """The fade is applied to the display-list slice the overlay emitted, so
    the scrim -- drawn by the host, not the widget -- is scaled too. A scrim
    that stayed at full strength while its dialog faded would be glaring."""
    from pycopper.runtime.overlay import SCRIM_OPACITY
    from pycopper.theme import Palette

    scrim_token = Palette(Theme(dark=True)).index("scrim")

    def scrim_alpha(dl: DisplayList) -> float:
        return max(
            (float(s["fill"][3]) for s in dl.view if int(s["flags"][2]) == scrim_token),
            default=0.0,
        )

    app, show, clock = dialog_app()
    show.set(True)
    app.paint(DisplayList())
    clock.t = 0.05
    mid = DisplayList()
    app.paint(mid)
    assert 0.0 < app.overlays.entries[0].opacity < 1.0

    for _ in range(12):
        clock.t += 0.05
        app.paint(DisplayList())
    full = DisplayList()
    app.paint(full)

    assert scrim_alpha(full) == pytest.approx(SCRIM_OPACITY)
    assert 0.0 < scrim_alpha(mid) < scrim_alpha(full)


def test_an_overlay_that_starts_open_is_not_faded_in() -> None:
    """`animated()` settles on its first call, so a view that opens with a
    dialog already up shows it immediately rather than animating on launch."""
    app = hosted(overlays=[{**DIALOG, "open": "true"}])
    app.mount()
    app.paint(DisplayList())
    assert app.overlays.entries[0].opacity == 1.0
    assert not app.motion.active


def test_reduce_motion_shows_and_hides_an_overlay_at_once() -> None:
    show = Signal(False)
    app = hosted(overlays=[DIALOG], reduce_motion=True)
    app.expose(show=show)
    app.mount()
    app.paint(DisplayList())

    show.set(True)
    app.paint(DisplayList())
    assert app.overlays.entries[0].opacity == 1.0
    assert not app.motion.active


# ------------------------------------------------------- state layer fades


def button_app():
    app = hosted(
        children=[
            {"name": "b", "widget": "Button", "text": "Hi", "style": {"width": 100, "height": 40}}
        ]
    )
    clock = Clock()
    app.clock = clock
    app.mount()
    app.paint(DisplayList())
    return app, app.root.find("b"), clock


def test_a_state_layer_fades_in_instead_of_blinking() -> None:
    app, button, clock = button_app()
    assert button.animation("state_layer").value == 0.0

    button.state.hovered = True
    button.mark_needs_paint()
    app.paint(DisplayList())
    assert button.animation("state_layer").value == 0.0, "the layer blinked on"

    clock.t = 0.03
    app.paint(DisplayList())
    assert 0.0 < button.animation("state_layer").value < HOVER

    clock.t = 0.3
    app.paint(DisplayList())
    assert button.animation("state_layer").value == pytest.approx(HOVER)


def test_a_state_layer_fades_back_out_and_goes_idle() -> None:
    app, button, clock = button_app()
    button.state.hovered = True
    button.mark_needs_paint()
    for step in range(8):
        clock.t = step * 0.05
        app.paint(DisplayList())
    assert button.animation("state_layer").value == pytest.approx(HOVER)

    button.state.hovered = False
    button.mark_needs_paint()
    clock.t += 0.02
    app.paint(DisplayList())
    assert button.animation("state_layer").value > 0.0, "it vanished instead of fading"

    for _ in range(8):
        clock.t += 0.05
        app.paint(DisplayList())
    assert button.animation("state_layer").value == pytest.approx(0.0)
    assert not app.motion.active


def test_pressing_moves_towards_the_press_opacity() -> None:
    """M3's 10% press layer over the 8% hover one."""
    app, button, clock = button_app()
    button.state.hovered = True
    button.mark_needs_paint()
    for step in range(8):
        clock.t = step * 0.05
        app.paint(DisplayList())

    button.state.pressed = True
    button.mark_needs_paint()
    for _ in range(8):
        clock.t += 0.05
        app.paint(DisplayList())
    assert button.animation("state_layer").value == pytest.approx(PRESS)


def test_the_button_uses_the_shared_state_layer() -> None:
    """It had its own copy, which is why it alone did not cross-fade."""
    _app, button, _clock = button_app()
    assert button.animation("state_layer") is not None


def test_a_hover_through_the_dispatcher_animates() -> None:
    """The real path -- a pointer move, not a hand-set flag."""
    app, button, clock = button_app()
    app.dispatcher.post(PointerEvent(EventType.POINTER_MOVE, x=50, y=20))
    app.dispatcher.drain()
    app.paint(DisplayList())
    assert button.state.hovered
    clock.t = 0.05
    app.paint(DisplayList())
    assert button.animation("state_layer").value > 0.0


def test_state_layers_still_paint_a_palette_token() -> None:
    app, button, clock = button_app()
    button.state.hovered = True
    button.mark_needs_paint()
    for step in range(8):
        clock.t = step * 0.05
        app.paint(DisplayList())
    dl = DisplayList()
    app.paint(dl)
    layers = [s for s in dl.view if 0.0 < float(s["fill"][3]) < 0.2]
    assert layers, "no state layer was emitted"
    assert all(int(s["flags"][2]) != NO_TOKEN for s in layers)


def test_nothing_hovered_means_no_frames() -> None:
    app, _button, _clock = button_app()
    assert not app.motion.active

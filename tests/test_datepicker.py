"""Date Picker: a calendar month grid for choosing a single date.

Modal variant, single date only. Uses the stdlib `calendar` module for the
grid itself, so these tests focus on what pyCopper actually built: click-to-
select, month navigation, and the `value:`/`on_change` binding convention
every other value-bearing widget shares -- not on calendar arithmetic
`calendar` already gets right.
"""

from __future__ import annotations

import calendar
import datetime

from pycopper import App, Theme
from pycopper.layout import Offset
from pycopper.paint import DisplayList
from pycopper.runtime.events import EventType, PointerEvent
from pycopper.spec import WidgetKind, parse_view
from pycopper.theme import Palette
from pycopper.tree.element import PaintContext
from pycopper.widgets.base import _REGISTRY, create_element
from pycopper.widgets.datepicker import DatePickerElement


def _app(*, calls: list[str] | None = None, **spec):
    view = {
        "name": "root",
        "widget": "Vertical",
        "children": [{"name": "dp", "widget": "DatePicker", **spec}],
    }
    app = App(view, theme=Theme(dark=True))
    if calls is not None:

        def changed(event: object) -> None:
            calls.append(event.value)  # type: ignore[attr-defined]

        app.handler(changed)
    app.mount()
    app.update()
    return app, app.root.find("dp")


def _cell_center(dp: DatePickerElement, day: int) -> tuple[float, float]:
    rect = dp.absolute_rect()
    for row, week in enumerate(dp._weeks()):
        for col, d in enumerate(week):
            if d == day:
                return (
                    rect.x + dp.PAD_X + col * dp.CELL + dp.CELL / 2,
                    rect.y + dp._grid_top() + row * dp.CELL + dp.CELL / 2,
                )
    raise AssertionError(f"day {day} not found in the displayed month")


def _click(app: App, x: float, y: float) -> None:
    app.dispatcher.post(PointerEvent(EventType.POINTER_DOWN, x=x, y=y))
    app.dispatcher.drain()
    app.dispatcher.post(PointerEvent(EventType.POINTER_UP, x=x, y=y))
    app.dispatcher.drain()


# --------------------------------------------------------------- registered


def test_kind_builds() -> None:
    create_element(parse_view({"name": "x", "widget": "DatePicker"}).root)
    assert WidgetKind.DATE_PICKER in _REGISTRY


def test_is_focusable() -> None:
    from pycopper.runtime.events import FOCUSABLE_KINDS

    assert "DatePicker" in FOCUSABLE_KINDS


# ------------------------------------------------------------------ geometry


def test_width_is_fixed() -> None:
    _, dp = _app(value="2026-09-04")
    assert dp.size.width == DatePickerElement.WIDTH == 320.0


def test_the_grid_reserves_six_rows() -> None:
    _, dp = _app(value="2026-09-04")
    height = dp.HEADLINE_HEIGHT + dp.NAV_HEIGHT + dp.WEEKDAY_HEIGHT + dp.CELL * dp.ROWS
    assert dp.size.height == height


# ------------------------------------------------------------- initial state


def test_starts_on_the_month_of_the_bound_value() -> None:
    _, dp = _app(value="2026-03-15")
    assert (dp._view_year, dp._view_month) == (2026, 3)


def test_with_no_value_starts_on_the_current_month() -> None:
    _, dp = _app()
    today = datetime.date.today()
    assert (dp._view_year, dp._view_month) == (today.year, today.month)


def test_a_live_bound_value_also_starts_on_its_own_month() -> None:
    """`value: "{{ ... }}"` is a template, not a literal -- `spec.value` at
    construction time is the raw source string, not the rendered date, so
    `__init__` alone cannot derive the right month for a bound value the
    way it can for a static literal. `configure()` must run once after the
    binding's first render for this to work at all (`bind()` in
    `tree/element.py`) -- every other test in this file uses a literal
    value and would not catch a regression here."""
    from pycopper import App, Signal, Theme

    view = {
        "name": "root",
        "widget": "Vertical",
        "children": [{"name": "dp", "widget": "DatePicker", "value": "{{ chosen.get() }}"}],
    }
    app = App(view, theme=Theme(dark=True))
    chosen = Signal("2025-11-20", name="chosen")
    app.expose(chosen=chosen)
    app.mount()
    app.update()
    dp = app.root.find("dp")
    assert (dp._view_year, dp._view_month) == (2025, 11)


# ----------------------------------------------------------------- selection


def test_clicking_a_day_commits_it_and_fires_on_change() -> None:
    calls: list[str] = []
    app, dp = _app(calls=calls, value="2026-09-01", handlers={"on_change": "changed"})
    x, y = _cell_center(dp, 15)
    _click(app, x, y)
    assert dp._value == "2026-09-15"
    assert calls == ["2026-09-15"]


def test_clicking_the_same_day_twice_fires_on_change_once() -> None:
    calls: list[str] = []
    app, dp = _app(calls=calls, value="2026-09-15", handlers={"on_change": "changed"})
    x, y = _cell_center(dp, 15)
    _click(app, x, y)
    assert calls == []  # already selected -- no redundant fire


def test_a_disabled_date_picker_ignores_clicks() -> None:
    calls: list[str] = []
    app, dp = _app(
        calls=calls, value="2026-09-01", disabled="true", handlers={"on_change": "changed"}
    )
    x, y = _cell_center(dp, 15)
    _click(app, x, y)
    assert dp._value == "2026-09-01"
    assert calls == []


# ------------------------------------------------------------- navigation


def test_next_month_advances_the_displayed_month_without_changing_value() -> None:
    app, dp = _app(value="2026-09-04")
    rect = dp.absolute_rect()
    nav_x = rect.x + dp.WIDTH - dp.PAD_X - dp.CELL / 2
    nav_y = rect.y + dp.HEADLINE_HEIGHT + dp.NAV_HEIGHT / 2
    _click(app, nav_x, nav_y)
    assert (dp._view_year, dp._view_month) == (2026, 10)
    assert dp._value == "2026-09-04"


def test_previous_month_retreats_and_wraps_the_year() -> None:
    app, dp = _app(value="2026-01-04")
    rect = dp.absolute_rect()
    nav_x = rect.x + dp.PAD_X + dp.CELL / 2
    nav_y = rect.y + dp.HEADLINE_HEIGHT + dp.NAV_HEIGHT / 2
    _click(app, nav_x, nav_y)
    assert (dp._view_year, dp._view_month) == (2025, 12)


# ----------------------------------------------------------------- weeks


def test_weeks_match_the_standard_library_calendar() -> None:
    _, dp = _app(value="2026-02-01")
    expected = calendar.Calendar(firstweekday=6).monthdayscalendar(2026, 2)
    assert dp._weeks() == expected


# ------------------------------------------------------------------- paint


def test_painting_does_not_crash() -> None:
    _, dp = _app(value="2026-09-04")
    dl = DisplayList()
    ctx = PaintContext(display_list=dl, palette=Palette(Theme(dark=True)))
    dp.paint(ctx, Offset(0.0, 0.0))
    assert dl.view.shape[0] > 0

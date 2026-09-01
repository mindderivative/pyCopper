"""The universal SDF pipeline: boxes, corners, antialiasing, borders, clipping.

These are the M2 acceptance tests. They assert the properties the architecture
claims are *free* consequences of using a real distance field -- analytic AA and
rounded clipping -- rather than merely that something got drawn.
"""

from __future__ import annotations

import numpy as np
import pytest

from pycopper import Theme
from pycopper.paint import DisplayList
from pycopper.theme import Palette

pytestmark = pytest.mark.gpu

RED = (1.0, 0.0, 0.0, 1.0)
GREEN = (0.0, 1.0, 0.0, 1.0)
BLUE = (0.0, 0.0, 1.0, 1.0)


def linear_to_srgb8(c: float) -> float:
    s = c * 12.92 if c <= 0.0031308 else 1.055 * c ** (1 / 2.4) - 0.055
    return s * 255.0


# ------------------------------------------------------------------ basics


def test_solid_box_fills_its_rect(render_scene) -> None:
    frame, _ = render_scene(lambda dl: dl.add_box(20, 20, 60, 60, color=RED))
    assert tuple(frame[50, 50, :3]) == (255, 0, 0)


def test_outside_the_box_is_untouched(render_scene) -> None:
    frame, _ = render_scene(lambda dl: dl.add_box(20, 20, 60, 60, color=RED))
    assert frame[5, 5, 0] < 50, "box leaked outside its rect"


def test_box_edges_land_where_specified(render_scene) -> None:
    frame, _ = render_scene(lambda dl: dl.add_box(20, 20, 60, 60, color=RED))
    assert frame[50, 21, 0] > 200, "left edge missing"
    assert frame[50, 78, 0] > 200, "right edge missing"
    assert frame[50, 15, 0] < 50, "leaked left"
    assert frame[50, 85, 0] < 50, "leaked right"


def test_empty_display_list_draws_nothing(render_scene) -> None:
    frame, engine = render_scene(lambda dl: None)
    assert engine.instance_count == 0
    assert np.all(frame[:, :, :3] == frame[0, 0, :3])


# ---------------------------------------------------- rounded corners + AA


def test_rounded_corner_removes_the_square_corner(render_scene) -> None:
    def paint(dl: DisplayList) -> None:
        dl.add_box(20, 20, 60, 60, color=RED, radii=(20, 20, 20, 20))

    frame, _ = render_scene(paint)
    assert frame[22, 22, 0] < 50, "corner was not rounded away"
    assert frame[50, 50, 0] > 200, "centre should still be filled"


def test_each_corner_radius_is_independent(render_scene) -> None:
    """radii is (tl, tr, br, bl) -- only the top-left should be cut."""

    def paint(dl: DisplayList) -> None:
        dl.add_box(20, 20, 60, 60, color=RED, radii=(20, 0, 0, 0))

    frame, _ = render_scene(paint)
    assert frame[23, 23, 0] < 60, "top-left not rounded"
    assert frame[23, 76, 0] > 200, "top-right should be square"
    assert frame[76, 76, 0] > 200, "bottom-right should be square"
    assert frame[76, 23, 0] > 200, "bottom-left should be square"


def test_antialiasing_produces_intermediate_coverage(render_scene) -> None:
    """The whole point of an SDF: coverage is analytic, so edges are smooth
    without MSAA. A hard-edged rasteriser would give only 0 and 255 here."""

    def paint(dl: DisplayList) -> None:
        dl.add_box(20, 20, 60, 60, color=RED, radii=(25, 25, 25, 25))

    frame, _ = render_scene(paint)
    diagonal = np.array([frame[20 + i, 20 + i, 0] for i in range(20)], dtype=int)
    intermediate = [v for v in diagonal if 20 < v < 235]
    assert len(intermediate) >= 2, f"no soft edge found: {diagonal.tolist()}"


def test_antialiasing_is_monotonic_across_an_edge(render_scene) -> None:
    def paint(dl: DisplayList) -> None:
        dl.add_box(20.5, 20, 60, 60, color=RED)

    frame, _ = render_scene(paint)
    row = np.array([frame[50, x, 0] for x in range(18, 26)], dtype=int)
    assert row[0] < row[-1], "edge does not ramp from outside to inside"


# ---------------------------------------------------------------- borders


def test_border_ring_and_fill_are_distinct(render_scene) -> None:
    def paint(dl: DisplayList) -> None:
        dl.add_box(20, 20, 88, 88, color=RED, border_width=8.0, border_color=GREEN)

    frame, _ = render_scene(paint)
    assert frame[64, 23, 1] > 200, "border ring should be green"
    assert frame[64, 23, 0] < 60
    assert frame[64, 64, 0] > 200, "interior should be red"
    assert frame[64, 64, 1] < 60


def test_border_does_not_double_composite(render_scene) -> None:
    """Fill and border coverages are disjoint, so a semi-transparent pair must
    not stack into something more opaque than either."""

    def paint(dl: DisplayList) -> None:
        dl.add_box(
            20,
            20,
            88,
            88,
            color=(1.0, 0.0, 0.0, 0.5),
            border_width=10.0,
            border_color=(1.0, 0.0, 0.0, 0.5),
        )

    frame, _ = render_scene(paint)
    ring = int(frame[64, 25, 0])
    interior = int(frame[64, 64, 0])
    assert abs(ring - interior) < 12, f"ring {ring} vs interior {interior}"


# --------------------------------------------------------------- clipping


def test_clip_rect_removes_content_outside_it(render_scene) -> None:
    def paint(dl: DisplayList) -> None:
        dl.add_box(0, 0, 128, 128, color=RED, clip=(40, 40, 40, 40))

    frame, _ = render_scene(paint)
    assert frame[60, 60, 0] > 200, "inside the clip should be drawn"
    assert frame[10, 10, 0] < 50, "outside the clip should be removed"
    assert frame[110, 110, 0] < 50


def test_rounded_clip_cuts_corners(render_scene) -> None:
    """Something a scissor rect cannot express at all."""

    def paint(dl: DisplayList) -> None:
        dl.add_box(
            0,
            0,
            128,
            128,
            color=RED,
            clip=(30, 30, 68, 68),
            clip_radii=(30, 30, 30, 30),
        )

    frame, _ = render_scene(paint)
    assert frame[64, 64, 0] > 200, "clip interior missing"
    assert frame[33, 33, 0] < 60, "clip corner was not rounded"


def test_zero_size_clip_means_unclipped(render_scene) -> None:
    frame, _ = render_scene(lambda dl: dl.add_box(0, 0, 128, 128, color=RED, clip=(0, 0, 0, 0)))
    assert frame[64, 64, 0] > 200
    assert frame[5, 5, 0] > 200


# ------------------------------------------------------------------ theme


def test_palette_token_resolves_to_the_theme_colour(render_scene) -> None:
    """A token index in flags is looked up in the palette storage buffer, which
    is what makes a theme switch a single buffer upload."""
    theme = Theme(seed="#6750A4", dark=True)
    palette = Palette(theme)
    index = palette.index("primary")
    expected = [linear_to_srgb8(c) for c in palette.linear("primary")[:3]]

    frame, _ = render_scene(lambda dl: dl.add_box(20, 20, 88, 88, token=index), theme=theme)
    assert frame[64, 64, :3].astype(float) == pytest.approx(expected, abs=2.0)


# --------------------------------------------------- ordering and batching


def test_later_instances_paint_over_earlier_ones(render_scene) -> None:
    def paint(dl: DisplayList) -> None:
        dl.add_box(20, 20, 80, 80, color=RED)
        dl.add_box(40, 40, 40, 40, color=BLUE)

    frame, _ = render_scene(paint)
    assert tuple(frame[64, 64, :3]) == (0, 0, 255), "paint order not respected"
    assert tuple(frame[25, 25, :3]) == (255, 0, 0)


def test_many_primitives_are_one_draw_call(render_scene) -> None:
    """The central design constraint. 500 mixed primitives, one draw."""

    def paint(dl: DisplayList) -> None:
        for i in range(200):
            dl.add_box(i % 100, i % 100, 10, 10, color=RED, radii=(2, 2, 2, 2))
        for i in range(200):
            dl.add_shadow(i % 100, i % 100, 10, 10, blur=4.0)
        for i in range(100):
            dl.add_glyph(i, i, 4, 6, uv=(0, 0, 1, 1), color=GREEN)

    _, engine = render_scene(paint)
    assert engine.instance_count == 500


def test_alpha_blending_composites_correctly(render_scene) -> None:
    def paint(dl: DisplayList) -> None:
        dl.add_box(0, 0, 128, 128, color=(0.0, 0.0, 0.0, 1.0))
        dl.add_box(0, 0, 128, 128, color=(1.0, 1.0, 1.0, 0.5))

    frame, _ = render_scene(paint)
    grey = int(frame[64, 64, 0])
    assert 100 < grey < 220, f"half-transparent white over black gave {grey}"


# ----------------------------------------------------------------- shadow


def test_shadow_is_soft_at_its_edge(render_scene) -> None:
    def paint(dl: DisplayList) -> None:
        dl.add_shadow(40, 40, 48, 48, blur=10.0, color=(0.0, 0.0, 0.0, 1.0))

    frame, engine = render_scene(paint)
    assert engine.instance_count == 1
    centre = int(frame[64, 64, 0])
    edge = int(frame[64, 92, 0])
    far = int(frame[64, 120, 0])
    assert centre < edge < far, f"no shadow falloff: {centre}, {edge}, {far}"


def test_shadow_offset_shifts_it(render_scene) -> None:
    def paint(dl: DisplayList) -> None:
        dl.add_shadow(40, 40, 48, 48, blur=6.0, offset=(12.0, 0.0), color=(0.0, 0.0, 0.0, 1.0))

    frame, _ = render_scene(paint)
    left = int(frame[64, 36, 0])
    right = int(frame[64, 92, 0])
    assert right < left, "shadow did not shift right"

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

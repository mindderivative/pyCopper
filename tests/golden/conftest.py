"""Offscreen rendering fixtures. The only tests that need a GPU adapter."""

from __future__ import annotations

import numpy as np
import pytest


@pytest.fixture(scope="session")
def gpu_available() -> bool:
    try:
        import wgpu

        wgpu.gpu.request_adapter_sync(power_preference="high-performance")
    except Exception:
        return False
    return True


@pytest.fixture
def offscreen_engine(gpu_available: bool):
    """An Engine rendering to an offscreen canvas -- no window, deterministic."""
    if not gpu_available:
        pytest.skip("no wgpu adapter available")

    from rendercanvas.offscreen import RenderCanvas

    from pycopper import Engine, Settings

    def _make(width: int = 64, height: int = 64, **kw):
        canvas = RenderCanvas(size=(width, height))
        return Engine(canvas=canvas, settings=Settings(width=width, height=height), **kw)

    return _make


@pytest.fixture
def render_scene(offscreen_engine):
    """Render a painter callable and return the frame as (h, w, 4) uint8.

    Yields (frame, engine) so tests can also assert on the draw-call count.
    """

    def _render(painter, width: int = 128, height: int = 128, **kw):
        engine = offscreen_engine(width=width, height=height, **kw)
        engine.painter = painter
        engine.canvas.request_draw(engine.draw_frame)
        return np.asarray(engine.canvas.draw()), engine

    return _render


@pytest.fixture
def render_once(offscreen_engine):
    """Render a single frame and return it as an (h, w, 4) uint8 array."""

    def _render(**kw) -> np.ndarray:
        engine = offscreen_engine(**kw)
        engine.canvas.request_draw(engine.draw_frame)
        return np.asarray(engine.canvas.draw())

    return _render

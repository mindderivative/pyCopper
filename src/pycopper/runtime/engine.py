"""Engine: owns the canvas, the wgpu device, and the frame pipeline.

M0 scope -- acquires the device and clears to an MD3 surface colour. The frame
pipeline described in ARCHITECTURE.md 6 lands incrementally across M1-M5; the
hooks are named here so later milestones extend rather than restructure.

Note what this class does NOT contain: an event loop. rendercanvas owns the
scheduler (ARCHITECTURE.md 5.10) and its 'ondemand' update mode is the dirty
flag. Polling GLFW here would double-pump the event queue.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

import wgpu

from ..config import Settings
from ..theme import Palette, Theme

if TYPE_CHECKING:
    from collections.abc import Callable

__all__ = ["Engine"]


class Engine:
    def __init__(
        self,
        theme: Theme | None = None,
        settings: Settings | None = None,
        canvas: Any | None = None,
    ) -> None:
        self.settings = settings or Settings()
        self.palette = Palette(theme or Theme())
        self.canvas = canvas if canvas is not None else self._make_canvas()

        self.adapter = wgpu.gpu.request_adapter_sync(
            power_preference=self.settings.power_preference
        )
        self.device = self.adapter.request_device_sync()

        self.context = self.canvas.get_context("wgpu")
        self.format = self.context.get_preferred_format(self.adapter)
        self.context.configure(device=self.device, format=self.format)

        self._frame_count = 0

    def _make_canvas(self) -> Any:
        from rendercanvas.glfw import RenderCanvas

        s = self.settings
        return RenderCanvas(
            title=s.title,
            size=(s.width, s.height),
            update_mode=s.update_mode,
            min_fps=s.min_fps,
            max_fps=s.max_fps,
        )

    @property
    def pixel_ratio(self) -> float:
        """Device pixel ratio. Layout is in logical units; only paint uses this."""
        if self.settings.force_pixel_ratio > 0:
            return self.settings.force_pixel_ratio
        return float(self.canvas.get_pixel_ratio())

    @property
    def frame_count(self) -> int:
        return self._frame_count

    def set_theme(self, theme: Theme) -> None:
        """Swap the theme. One buffer upload -- no relayout, no display-list rebuild."""
        self.palette.rebuild(theme)
        self.request_draw()

    def request_draw(self) -> None:
        self.canvas.request_draw()

    # ---------------------------------------------------------------- frame

    def draw_frame(self) -> None:
        """One frame. Steps 7-9 of ARCHITECTURE.md 6; 1-6 arrive in M1-M4."""
        self._upload()
        encoder = self.device.create_command_encoder()
        render_pass = encoder.begin_render_pass(
            color_attachments=[
                {
                    "view": self.context.get_current_texture().create_view(),
                    "resolve_target": None,
                    "clear_value": self.palette.linear("surface"),
                    "load_op": wgpu.LoadOp.clear,
                    "store_op": wgpu.StoreOp.store,
                }
            ]
        )
        self._draw_ui(render_pass)
        render_pass.end()
        self.device.queue.submit([encoder.finish()])
        self._frame_count += 1

    def _upload(self) -> None:
        """Palette / atlas / instance uploads. M2 fills this in."""
        if self.palette.dirty:
            # M2: queue.write_buffer into the palette storage buffer.
            self.palette.mark_uploaded()

    def _draw_ui(self, render_pass: Any) -> None:
        """M2: bind pipeline + group 0, quad VB + instance VB, one instanced draw."""

    # ---------------------------------------------------------------- lifecycle

    def run(self, on_frame: Callable[[], None] | None = None) -> None:
        from rendercanvas.glfw import loop

        self.canvas.request_draw(on_frame or self.draw_frame)
        loop.run()

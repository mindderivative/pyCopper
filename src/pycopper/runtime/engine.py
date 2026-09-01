"""Engine: owns the canvas, the wgpu device, and the frame pipeline.

M2 scope -- acquires the device, clears to an MD3 surface colour, and issues the
frame's single instanced draw over the display list. Steps 1-5 of the frame
lifecycle (events, build, layout) arrive with the element tree in M3.

Note what this class does NOT contain: an event loop. rendercanvas owns the
scheduler (ARCHITECTURE.md 5.10) and its 'ondemand' update mode is the dirty
flag. Polling GLFW here would double-pump the event queue.
"""

from __future__ import annotations

from collections.abc import Callable
from typing import Any

import wgpu

from ..config import Settings
from ..paint import DisplayList
from ..render import UIPipeline
from ..text import TextEngine
from ..theme import Palette, Theme

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

        self.pipeline = UIPipeline(self.device, self.format)
        self.display_list = DisplayList()

        self.text = TextEngine(self.device)
        self.pipeline.bind_glyph_atlas(self.text.atlas.texture)

        #: Fills the display list each frame. M3 replaces this with a walk of
        #: the element tree; until then it is the way to draw anything.
        self.painter: Callable[[DisplayList], None] | None = None

        self._frame_count = 0
        self._instance_count = 0

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

    @property
    def instance_count(self) -> int:
        """Instances drawn in the last frame -- all in one draw call."""
        return self._instance_count

    def set_theme(self, theme: Theme) -> None:
        """Swap the theme. One buffer upload -- no relayout, no display-list rebuild."""
        self.palette.rebuild(theme)
        self.request_draw()

    def request_draw(self) -> None:
        self.canvas.request_draw()

    # ---------------------------------------------------------------- frame

    def draw_frame(self) -> None:
        """One frame. Steps 6-9 of ARCHITECTURE.md 6; 1-5 arrive in M3."""
        self.display_list.clear()
        if self.painter is not None:
            self.painter(self.display_list)
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
        """Palette, globals, and instance uploads (step 7)."""
        if self.palette.dirty:
            self.pipeline.upload_palette(self.palette.data)
            self.palette.mark_uploaded()

        # New glyphs may have been packed during paint; push them before the
        # draw that samples them.
        self.text.atlas.upload()

        width, height = self.canvas.get_physical_size()
        self.pipeline.upload_globals(width, height, self.pixel_ratio)

    def _draw_ui(self, render_pass: Any) -> None:
        """Step 8: the frame's single instanced draw."""
        self._instance_count = self.pipeline.draw(render_pass, self.display_list)

    # ---------------------------------------------------------------- lifecycle

    def run(self, on_frame: Callable[[], None] | None = None) -> None:
        from rendercanvas.glfw import loop

        self.canvas.request_draw(on_frame or self.draw_frame)
        loop.run()

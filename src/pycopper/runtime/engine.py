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
from typing import Any, Final

import wgpu

from ..config import Settings
from ..paint import DisplayList
from ..render import UIPipeline
from ..text import TextEngine
from ..theme import Palette, Theme
from .clipboard import GlfwClipboard, clipboard

__all__ = ["Engine"]


#: Frames the surface stays pinned after the last size change. A resize draws
#: synchronously per compositor configure, so this is a handful of frames after
#: the drag stops, not a wall-clock delay.
SETTLE_FRAMES: Final = 3


def surface_size_for(
    size: tuple[int, int],
    previous: tuple[int, int],
    settle: int,
    bucket: int,
) -> tuple[tuple[int, int], int]:
    """The size to configure the surface at, and the new settle countdown.

    Separated from `Engine` so the policy is testable without a window: it is
    a decision about integers, and the GPU has no opinion about it.
    """
    if bucket <= 0:
        return size, 0
    if size != previous:
        settle = SETTLE_FRAMES
    elif settle:
        settle -= 1
    if settle:
        return (-(-size[0] // bucket) * bucket, -(-size[1] // bucket) * bucket), settle
    return size, settle


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

        #: Configures the swapchain. Public wgpu-py API ("External code needs
        #: to set the framebuffer size"), reached through rendercanvas's
        #: wrapper; None on a canvas that has no swapchain at all, such as the
        #: offscreen one the golden suite renders through.
        self._set_surface_size = getattr(
            getattr(self.context, "_wgpu_context", None), "set_physical_size", None
        )
        #: Seeded with the real size so the first frame is never mistaken for a
        #: resize -- which is also what keeps offscreen rendering exact.
        self._last_size: tuple[int, int] = tuple(self.canvas.get_physical_size())
        self._settle = 0

    def _make_canvas(self) -> Any:
        from rendercanvas.glfw import RenderCanvas

        s = self.settings
        if s.wayland_decorations == "server":
            # Must precede GLFW's init, which rendercanvas defers until the
            # first canvas is constructed -- so this is the last moment it can
            # be set, and setting it after would silently do nothing. The hint
            # is ignored on platforms where it does not apply.
            import glfw

            glfw.init_hint(glfw.WAYLAND_LIBDECOR, glfw.WAYLAND_DISABLE_LIBDECOR)
        canvas = RenderCanvas(
            title=s.title,
            size=(s.width, s.height),
            update_mode=s.update_mode,
            min_fps=s.min_fps,
            max_fps=s.max_fps,
            vsync=s.vsync,
        )
        # A real window means GLFW is initialised, which is all the system
        # clipboard needs. Installed here rather than at import so headless and
        # offscreen use keeps the in-process one, and skipped if an application
        # has already supplied its own -- an explicit choice outranks a default.
        if not clipboard.system_backed:
            clipboard.install(GlfwClipboard())
        return canvas

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

    def _pin_surface(self) -> None:
        """Hold the swapchain at a coarse size while the window is resizing.

        wgpu reconfigures the surface whenever the size it is told differs from
        the one it is configured at, and reconfiguring tears down and recreates
        the `VkSwapchainKHR`. During a drag that happens on every pixel: 1.35
        to 1.88 ms per frame against 0.043 measured on KDE Plasma, and it is
        the whole of the pointer trailing (ARCHITECTURE.md 5.8.1).

        Rounding the size up to `Settings.resize_bucket` makes the rebuild
        happen once per bucket instead of once per pixel. **The buffer is then
        larger than the window, and the compositor scales it back down** --
        measured, not assumed; it does not crop. That is exactly why nothing
        else here changes: the projection already describes the window
        (`_upload`), so content is drawn across the whole oversized buffer and
        the compositor's squeeze undoes the stretch. Geometry comes out exact.

        The cost is one non-integer resample, which softens text slightly. So
        the pin is released a few frames after the last size change: soft while
        a drag is in flight, when nobody is reading, and pixel-exact the moment
        it stops. Nothing is skipped or throttled -- every frame is still drawn
        and committed, which the reverted throttle proved is not optional.
        """
        if self._set_surface_size is None:
            return
        size = tuple(self.canvas.get_physical_size())
        target, self._settle = surface_size_for(
            size, self._last_size, self._settle, self.settings.resize_bucket
        )
        self._last_size = size
        if target != tuple(self.context._wgpu_context.physical_size):
            self._set_surface_size(*target)

    def draw_frame(self) -> None:
        """One frame. Steps 6-9 of ARCHITECTURE.md 6; 1-5 arrive in M3.

        Every frame asked for is drawn and presented, including the hundreds a
        second a window resize produces. Skipping one is not the optimisation
        it looks like: a Wayland client is expected to commit a buffer in
        response to a configure, and declining leaves the compositor waiting.
        Measured on KDE Plasma, a throttle that skipped frames dropped a live
        resize from 466 redraws a second to 12 -- see ARCHITECTURE.md 5.8.1.
        """
        self._pin_surface()
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
        if self._settle:
            # Nothing else will ask for these. Without them an `ondemand`
            # application stops drawing the moment the drag does, and the
            # surface would stay pinned -- and so slightly soft -- until
            # something unrelated happened to need a frame.
            self.canvas.request_draw()

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
        try:
            loop.run()
        finally:
            self.close()

    def close(self) -> None:
        """Release every GPU object, in the order the surface requires.

        Not left to the garbage collector. rendercanvas terminates GLFW from a
        class attribute's `__del__` specifically so that it happens late,
        because "the release of the surface should happen before the
        termination of glfw" -- otherwise the process segfaults on exit
        (rendercanvas/glfw.py, citing pygfx/pygfx#642). An `Engine` reached
        from a module-level `App`, which is how every example is written,
        stays alive until interpreter shutdown and loses that race: closing
        the window destroyed the native window and left a live wgpu surface
        pointing at it.

        So the surface is unconfigured first, then the resources the device
        owns, then the device. Calling this twice is harmless.
        """
        context = getattr(self, "context", None)
        if context is not None:
            context.unconfigure()
            del self.context
        if getattr(self, "text", None) is not None:
            self.text.atlas.destroy()
        pipeline = getattr(self, "pipeline", None)
        if pipeline is not None:
            pipeline.destroy()
            del self.pipeline
        device = getattr(self, "device", None)
        if device is not None:
            device.destroy()
            del self.device
        if getattr(self, "adapter", None) is not None:
            del self.adapter

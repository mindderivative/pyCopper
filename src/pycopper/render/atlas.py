"""Glyph atlas: skyline packing into a single R8 coverage texture.

Keeping every glyph in one texture is what preserves the single-draw-call
property (ARCHITECTURE.md 5.8) -- a per-glyph texture would force a bind group
switch, and therefore a draw call, per glyph.

The packer is deliberately GPU-free and tested without a window; only
:class:`GlyphAtlas` touches wgpu.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any, Final

import numpy as np

from ..text.font import Face, GlyphBitmap

__all__ = ["AtlasEntry", "AtlasFullError", "AtlasKey", "GlyphAtlas", "SkylinePacker"]

#: (font path, quarter-pixel size, glyph id, subpixel bucket, axis coords)
AtlasKey = tuple[Path, int, int, int, tuple[float, ...]]

#: One transparent pixel between glyphs. Without it, linear filtering samples a
#: neighbour's coverage along shared edges and glyphs grow faint halos.
PADDING: Final = 1


class AtlasFullError(RuntimeError):
    """Raised when a glyph cannot be placed in the remaining space."""


@dataclass(frozen=True, slots=True)
class AtlasEntry:
    """Where a rasterised glyph lives, and how to place it when drawing."""

    x: int
    y: int
    width: int
    height: int
    left: float  # bearing from the pen position
    top: float  # bearing above the baseline
    generation: int

    def uv(self, atlas_size: int) -> tuple[float, float, float, float]:
        s = float(atlas_size)
        return (self.x / s, self.y / s, (self.x + self.width) / s, (self.y + self.height) / s)

    @property
    def is_blank(self) -> bool:
        return self.width == 0 or self.height == 0


class SkylinePacker:
    """Bottom-left skyline rectangle packer.

    Chosen over a shelf packer because glyph heights vary continuously with font
    size; shelves would waste most of a row whenever one tall glyph opened it.
    """

    __slots__ = ("_skyline", "height", "width")

    def __init__(self, width: int, height: int) -> None:
        self.width = width
        self.height = height
        # (x, y, width) spans, left to right, covering the full width.
        self._skyline: list[tuple[int, int, int]] = [(0, 0, width)]

    def reset(self) -> None:
        self._skyline = [(0, 0, self.width)]

    @property
    def occupancy(self) -> float:
        """Fraction of the atlas height consumed by the tallest skyline point."""
        return max((y for _, y, _ in self._skyline), default=0) / self.height

    def _fit(self, index: int, width: int, height: int) -> int | None:
        """Lowest y at which a rect of *width* fits starting at span *index*."""
        x = self._skyline[index][0]
        if x + width > self.width:
            return None
        y = 0
        remaining = width
        i = index
        while remaining > 0:
            if i >= len(self._skyline):
                return None
            span_x, span_y, span_w = self._skyline[i]
            y = max(y, span_y)
            if y + height > self.height:
                return None
            remaining -= span_w - max(0, x - span_x)
            i += 1
        return y

    def allocate(self, width: int, height: int) -> tuple[int, int]:
        """Place a rect and return its top-left. Raises :class:`AtlasFullError`."""
        if width <= 0 or height <= 0:
            return (0, 0)
        best: tuple[int, int, int] | None = None  # (y, x, index)
        for i in range(len(self._skyline)):
            y = self._fit(i, width, height)
            if y is None:
                continue
            x = self._skyline[i][0]
            if best is None or (y, x) < (best[0], best[1]):
                best = (y, x, i)
        if best is None:
            raise AtlasFullError(f"cannot place {width}x{height} in {self.width}x{self.height}")

        y, x, index = best
        self._insert(index, x, y + height, width)
        return (x, y)

    def _insert(self, index: int, x: int, top: int, width: int) -> None:
        skyline = self._skyline
        skyline.insert(index, (x, top, width))
        # Trim spans the new node covers.
        i = index + 1
        while i < len(skyline):
            sx, sy, sw = skyline[i]
            prev_end = skyline[i - 1][0] + skyline[i - 1][2]
            if sx >= prev_end:
                break
            shrink = prev_end - sx
            if sw <= shrink:
                skyline.pop(i)
                continue
            skyline[i] = (sx + shrink, sy, sw - shrink)
            break
        # Merge neighbours at the same height.
        i = 0
        while i < len(skyline) - 1:
            if skyline[i][1] == skyline[i + 1][1]:
                x0, y0, w0 = skyline[i]
                skyline[i] = (x0, y0, w0 + skyline[i + 1][2])
                skyline.pop(i + 1)
            else:
                i += 1


class GlyphAtlas:
    """CPU-side atlas image plus its GPU texture.

    Eviction is **wholesale**: a skyline allocator cannot free individual
    rectangles, so a full atlas is cleared and repopulated on demand. A
    generation counter invalidates entries handed out before the reset, which
    is why callers must not cache an :class:`AtlasEntry` across frames without
    checking it.
    """

    __slots__ = (
        "_cache",
        "_device",
        "_dirty",
        "_generation",
        "_packer",
        "_pixels",
        "_resets",
        "_texture",
        "size",
    )

    def __init__(self, device: Any = None, size: int = 1024) -> None:
        self.size = size
        self._packer = SkylinePacker(size, size)
        self._pixels = np.zeros((size, size), dtype=np.uint8)
        self._cache: dict[AtlasKey, AtlasEntry] = {}
        self._generation = 0
        self._resets = 0
        self._dirty = True
        self._device = device
        self._texture: Any = None
        if device is not None:
            self._create_texture()

    # ------------------------------------------------------------ CPU side

    @property
    def pixels(self) -> np.ndarray:
        return self._pixels

    @property
    def generation(self) -> int:
        return self._generation

    @property
    def resets(self) -> int:
        return self._resets

    @property
    def occupancy(self) -> float:
        return self._packer.occupancy

    def __len__(self) -> int:
        return len(self._cache)

    def reset(self) -> None:
        self._packer.reset()
        self._pixels[:] = 0
        self._cache.clear()
        self._generation += 1
        self._resets += 1
        self._dirty = True

    def add(self, key: AtlasKey, bitmap: GlyphBitmap) -> AtlasEntry:
        if bitmap.is_blank:
            entry = AtlasEntry(0, 0, 0, 0, bitmap.left, bitmap.top, self._generation)
            self._cache[key] = entry
            return entry

        w, h = bitmap.width, bitmap.height
        try:
            x, y = self._packer.allocate(w + PADDING, h + PADDING)
        except AtlasFullError:
            self.reset()
            x, y = self._packer.allocate(w + PADDING, h + PADDING)

        self._pixels[y : y + h, x : x + w] = bitmap.coverage
        entry = AtlasEntry(x, y, w, h, bitmap.left, bitmap.top, self._generation)
        self._cache[key] = entry
        self._dirty = True
        return entry

    def get(
        self,
        face: Face,
        gid: int,
        px: float,
        subpixel: int = 0,
        coords: tuple[float, ...] = (),
    ) -> AtlasEntry:
        """Entry for a glyph, rasterising and packing it on first use.

        ``coords`` is part of the key: a filled and an unfilled icon are the
        same glyph id at the same size, and would otherwise collide.
        """
        key = (face.path, round(px * 4), int(gid), subpixel, coords)
        entry = self._cache.get(key)
        if entry is not None and entry.generation == self._generation:
            return entry
        return self.add(key, face.rasterize(gid, px, subpixel, coords))

    # ------------------------------------------------------------ GPU side

    @property
    def texture(self) -> Any:
        return self._texture

    def attach_device(self, device: Any) -> None:
        """Give a CPU-only atlas a GPU texture.

        Lets an App own one atlas whether or not it is running on a window --
        headless tests share the same code path as a live application.
        """
        if self._device is device:
            return
        self._device = device
        self._create_texture()
        self._dirty = True

    @property
    def dirty(self) -> bool:
        return self._dirty

    def _create_texture(self) -> None:
        import wgpu

        self._texture = self._device.create_texture(
            size=(self.size, self.size, 1),
            format=wgpu.TextureFormat.r8unorm,
            usage=wgpu.TextureUsage.TEXTURE_BINDING | wgpu.TextureUsage.COPY_DST,
        )

    def upload(self) -> bool:
        """Push the CPU image to the GPU if it changed. Returns whether it did."""
        if self._device is None or not self._dirty:
            return False
        self._device.queue.write_texture(
            {"texture": self._texture},
            np.ascontiguousarray(self._pixels),
            {"bytes_per_row": self.size, "rows_per_image": self.size},
            (self.size, self.size, 1),
        )
        self._dirty = False
        return True

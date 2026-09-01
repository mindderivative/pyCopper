"""Text: shaping, segmentation, fallback, and glyph rasterisation.

`TextEngine` is the facade the rest of the framework uses. It owns the three
caches that make text affordable per frame (ARCHITECTURE.md 5.7.4): shaped
runs, paragraph layouts, and rasterised glyphs in the atlas.
"""

from __future__ import annotations

from typing import Any

import numpy as np

from ..layout import Size
from ..paint import NO_TOKEN, DisplayList
from ..render.atlas import GlyphAtlas
from .font import SUBPIXEL_BUCKETS, Face, FontMetrics, GlyphBitmap
from .fontdb import FontDB, FontRequest
from .icons import DEFAULT_ICON_SIZE, IconSet
from .itemize import Direction, ItemRun, itemize
from .layout import Alignment, GlyphPlacement, Paragraph, TextLine, layout_text
from .segment import break_opportunities, cluster_boundaries, clusters
from .shaping import ShapeCache, ShapedRun, shape_run

__all__ = [
    "DEFAULT_ICON_SIZE",
    "SUBPIXEL_BUCKETS",
    "Alignment",
    "Direction",
    "Face",
    "FontDB",
    "FontMetrics",
    "FontRequest",
    "GlyphBitmap",
    "GlyphPlacement",
    "IconSet",
    "ItemRun",
    "Paragraph",
    "ShapeCache",
    "ShapedRun",
    "TextEngine",
    "TextLine",
    "break_opportunities",
    "cluster_boundaries",
    "clusters",
    "itemize",
    "layout_text",
    "shape_run",
]

_NO_CLIP = (0.0, 0.0, 0.0, 0.0)


class TextEngine:
    """Owns fonts, caches, and the glyph atlas for one application."""

    __slots__ = ("_icons", "_layouts", "atlas", "db", "shaper")

    def __init__(self, device: Any = None, *, atlas_size: int = 1024) -> None:
        self.db = FontDB()
        self.shaper = ShapeCache()
        self.atlas = GlyphAtlas(device, size=atlas_size)
        self._layouts: dict[tuple[Any, ...], Paragraph] = {}
        self._icons: IconSet | None = None

    @property
    def icons(self) -> IconSet:
        """Material Symbols, loaded on first use -- an app with no icons pays
        nothing for the font."""
        if self._icons is None:
            self._icons = IconSet.bundled()
        return self._icons

    def emit_icon(
        self,
        display_list: DisplayList,
        name: str,
        *,
        x: float,
        y: float,
        size: float = DEFAULT_ICON_SIZE,
        fill: float = 0.0,
        weight: float = 400.0,
        pixel_ratio: float = 1.0,
        token: int = NO_TOKEN,
        color: tuple[float, float, float, float] = (1.0, 1.0, 1.0, 1.0),
        clip: tuple[float, float, float, float] = _NO_CLIP,
        clip_radii: tuple[float, float, float, float] = _NO_CLIP,
    ) -> bool:
        """Emit one icon at logical ``(x, y)``. Returns whether it drew anything.

        An icon is a glyph, so this reuses the atlas and the same GLYPH
        instance kind -- it costs no extra draw call.
        """
        icons = self.icons
        gid = icons.glyph(name)
        coords = icons.coords(fill=fill, weight=icons.suggested_weight(size, weight))
        entry = self.atlas.get(icons.face, gid, size * pixel_ratio, 0, coords)
        if entry.is_blank:
            return False
        display_list.add_glyph(
            x * pixel_ratio + entry.left,
            (y + size) * pixel_ratio - entry.top,
            float(entry.width),
            float(entry.height),
            uv=entry.uv(self.atlas.size),
            color=color,
            token=token,
            clip=clip,
            clip_radii=clip_radii,
        )
        return True

    def attach_device(self, device: Any) -> None:
        """Promote a CPU-only engine to a GPU-backed one."""
        self.atlas.attach_device(device)

    # ------------------------------------------------------------- layout

    def layout(
        self,
        text: str,
        *,
        px: float = 14.0,
        max_width: float | None = None,
        request: FontRequest | None = None,
        alignment: str = Alignment.START,
    ) -> Paragraph:
        """Lay out *text*, memoised. Static labels cost nothing after frame one."""
        req = request or FontRequest()
        key = (text, px, max_width, req.key(), alignment)
        hit = self._layouts.get(key)
        if hit is not None:
            return hit
        para = layout_text(
            text,
            self.db,
            px=px,
            max_width=max_width,
            request=req,
            alignment=alignment,
            cache=self.shaper,
        )
        self._layouts[key] = para
        return para

    def measure(
        self,
        text: str,
        *,
        px: float = 14.0,
        max_width: float | None = None,
        request: FontRequest | None = None,
    ) -> Size:
        return self.layout(text, px=px, max_width=max_width, request=request).size

    def clear_caches(self) -> None:
        self._layouts.clear()
        self.shaper.clear()

    # -------------------------------------------------------------- paint

    def emit(
        self,
        display_list: DisplayList,
        paragraph: Paragraph,
        *,
        x: float,
        y: float,
        pixel_ratio: float = 1.0,
        token: int = NO_TOKEN,
        color: tuple[float, float, float, float] = (1.0, 1.0, 1.0, 1.0),
        clip: tuple[float, float, float, float] = _NO_CLIP,
        clip_radii: tuple[float, float, float, float] = _NO_CLIP,
    ) -> int:
        """Emit glyph quads for *paragraph* at logical position ``(x, y)``.

        Rasterisation happens at the **physical** size, so text is sharp at any
        DPI; layout stays in logical units (ARCHITECTURE.md 7).
        """
        dpr = pixel_ratio
        px_physical = paragraph.px * dpr
        atlas_size = self.atlas.size

        # The atlas lookup is an unavoidable Python dict hit per glyph, but the
        # instance write is not: collect first, then write whole columns.
        rects: list[tuple[float, float, float, float]] = []
        uvs: list[tuple[float, float, float, float]] = []
        for place in paragraph.placements():
            pen_x = (x + place.x) * dpr
            pen_y = (y + place.y) * dpr
            bucket = int((pen_x % 1.0) * SUBPIXEL_BUCKETS) % SUBPIXEL_BUCKETS
            entry = self.atlas.get(place.face, place.gid, px_physical, bucket)
            if entry.is_blank:
                continue
            rects.append(
                (pen_x + entry.left, pen_y - entry.top, float(entry.width), float(entry.height))
            )
            uvs.append(entry.uv(atlas_size))

        if not rects:
            return 0
        display_list.add_glyphs(
            np.asarray(rects, dtype=np.float32),
            np.asarray(uvs, dtype=np.float32),
            color=color,
            token=token,
            clip=clip,
            clip_radii=clip_radii,
        )
        return len(rects)

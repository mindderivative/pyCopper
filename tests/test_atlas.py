"""Skyline packing and the glyph atlas. GPU-free."""

from __future__ import annotations

import numpy as np
import pytest

from pycopper.render.atlas import PADDING, AtlasFullError, GlyphAtlas, SkylinePacker
from pycopper.text import FontDB, FontRequest


@pytest.fixture(scope="module")
def face():
    return FontDB().face_for(FontRequest())


# ----------------------------------------------------------------- packer


def test_first_allocation_is_top_left() -> None:
    assert SkylinePacker(64, 64).allocate(10, 10) == (0, 0)


def test_allocations_do_not_overlap() -> None:
    packer = SkylinePacker(64, 64)
    rects = [(*packer.allocate(w, h), w, h) for w, h in [(20, 10), (20, 10), (30, 20), (8, 8)]]
    for i, (x0, y0, w0, h0) in enumerate(rects):
        for x1, y1, w1, h1 in rects[i + 1 :]:
            separated = x0 + w0 <= x1 or x1 + w1 <= x0 or y0 + h0 <= y1 or y1 + h1 <= y0
            assert separated, f"{rects[i]} overlaps {(x1, y1, w1, h1)}"


def test_allocations_stay_in_bounds() -> None:
    packer = SkylinePacker(32, 32)
    for _ in range(8):
        x, y = packer.allocate(7, 7)
        assert x >= 0 and x + 7 <= 32
        assert y >= 0 and y + 7 <= 32


def test_too_wide_raises() -> None:
    with pytest.raises(AtlasFullError):
        SkylinePacker(32, 32).allocate(64, 8)


def test_exhaustion_raises() -> None:
    packer = SkylinePacker(16, 16)
    with pytest.raises(AtlasFullError):
        for _ in range(100):
            packer.allocate(8, 8)


def test_zero_sized_allocation_is_free() -> None:
    packer = SkylinePacker(16, 16)
    assert packer.allocate(0, 0) == (0, 0)
    assert packer.occupancy == 0


def test_reset_reclaims_everything() -> None:
    packer = SkylinePacker(32, 32)
    packer.allocate(30, 30)
    packer.reset()
    assert packer.allocate(30, 30) == (0, 0)


# ------------------------------------------------------------------ atlas


def test_packs_glyphs_and_writes_pixels(face) -> None:
    atlas = GlyphAtlas(size=256)
    for ch in "Hello":
        atlas.get(face, face.glyph_for(ord(ch)), 24.0)
    assert len(atlas) == 4  # H e l o
    assert atlas.pixels.max() > 0


def test_blank_glyphs_consume_no_space(face) -> None:
    atlas = GlyphAtlas(size=128)
    entry = atlas.get(face, face.glyph_for(ord(" ")), 24.0)
    assert entry.is_blank
    assert atlas.occupancy == 0


def test_repeat_lookups_hit_the_cache(face) -> None:
    atlas = GlyphAtlas(size=128)
    gid = face.glyph_for(ord("A"))
    first = atlas.get(face, gid, 24.0)
    assert atlas.get(face, gid, 24.0) is first
    assert len(atlas) == 1


def test_size_and_subpixel_are_separate_entries(face) -> None:
    atlas = GlyphAtlas(size=256)
    gid = face.glyph_for(ord("A"))
    atlas.get(face, gid, 12.0, 0)
    atlas.get(face, gid, 24.0, 0)
    atlas.get(face, gid, 12.0, 1)
    assert len(atlas) == 3


def test_uv_is_normalised_and_ordered(face) -> None:
    atlas = GlyphAtlas(size=256)
    entry = atlas.get(face, face.glyph_for(ord("W")), 32.0)
    u0, v0, u1, v1 = entry.uv(256)
    assert 0.0 <= u0 < u1 <= 1.0
    assert 0.0 <= v0 < v1 <= 1.0


def test_glyphs_are_padded_apart(face) -> None:
    """Without padding, linear filtering bleeds a neighbour's coverage."""
    atlas = GlyphAtlas(size=256)
    a = atlas.get(face, face.glyph_for(ord("M")), 20.0)
    b = atlas.get(face, face.glyph_for(ord("W")), 20.0)
    assert b.x >= a.x + a.width + PADDING or b.y >= a.y + a.height + PADDING


def test_overflow_resets_and_keeps_working(face) -> None:
    """Eviction is wholesale: the skyline cannot free individual rectangles."""
    atlas = GlyphAtlas(size=64)
    entries = [atlas.get(face, face.glyph_for(ord(c)), 28.0) for c in "ABCDEFGHIJKLMNOPQRSTUVWXYZ"]
    assert atlas.resets >= 1
    assert atlas.generation >= 1
    assert entries[-1].generation == atlas.generation


def test_stale_entries_are_refreshed_after_a_reset(face) -> None:
    atlas = GlyphAtlas(size=128)
    gid = face.glyph_for(ord("A"))
    stale = atlas.get(face, gid, 20.0)
    atlas.reset()
    fresh = atlas.get(face, gid, 20.0)
    assert fresh.generation > stale.generation


def test_reset_clears_the_image(face) -> None:
    atlas = GlyphAtlas(size=128)
    atlas.get(face, face.glyph_for(ord("A")), 24.0)
    atlas.reset()
    assert np.all(atlas.pixels == 0)
    assert len(atlas) == 0


def test_upload_is_a_noop_without_a_device() -> None:
    assert GlyphAtlas(size=64).upload() is False

"""Holding the swapchain at a coarse size while a window is resizing.

wgpu reconfigures whenever the size it is told differs from the size it is
configured at, and reconfiguring recreates the `VkSwapchainKHR`. During a drag
that is once per pixel, and it is the whole of the pointer trailing: measured
on KDE Plasma Wayland, acquire costs 1.35-1.88 ms while rebuilding against
0.043 ms while not, and the resize path roughly doubles its frame rate when the
rebuild stops (ARCHITECTURE.md 5.8.1).

What the policy has to get right is when to STOP pinning. An oversized buffer
is scaled back down by the compositor rather than cropped -- verified by hand,
because the two are indistinguishable from any number pyCopper can measure --
and that resample softens text. It is the right trade while a drag is in
flight and the wrong one the moment it stops, so these tests are mostly about
the release.
"""

from __future__ import annotations

import pytest

from pycopper.config import Settings
from pycopper.runtime.engine import SETTLE_FRAMES, surface_size_for

BUCKET = 256


def drag(sizes: list[tuple[int, int]], bucket: int = BUCKET) -> list[tuple[int, int]]:
    """The surface sizes a sequence of window sizes would configure."""
    out, previous, settle = [], sizes[0], 0
    for size in sizes:
        target, settle = surface_size_for(size, previous, settle, bucket)
        previous = size
        out.append(target)
    return out


def test_a_still_window_is_configured_at_its_exact_size() -> None:
    """The steady state must be pixel-exact: this is every frame that is not a
    resize, which is nearly all of them."""
    assert drag([(900, 700)] * 5) == [(900, 700)] * 5


def test_a_changing_size_is_rounded_up_to_the_bucket() -> None:
    sizes = [(900, 700), (901, 700), (902, 701)]
    assert drag(sizes)[1:] == [(1024, 768), (1024, 768)]


def test_the_whole_of_a_drag_reuses_one_swapchain() -> None:
    """The point of the exercise. Every pixel between two bucket boundaries
    must configure the same size, or the rebuild is still per-pixel."""
    sizes = [(w, 700) for w in range(800, 1000)]
    assert len(set(drag(sizes)[1:])) == 1


def test_crossing_a_bucket_boundary_rebuilds_once() -> None:
    configured = drag([(w, 700) for w in range(1000, 1100)])
    assert len(set(configured[1:])) == 2, "one rebuild, at the boundary"


def test_the_pin_is_released_once_the_size_settles() -> None:
    """Soft text is the price of the pin, and it must be paid only while the
    drag is happening. A pin that outlived the drag would leave every
    application permanently, subtly blurry."""
    sizes = [(900, 700), (950, 700)] + [(950, 700)] * (SETTLE_FRAMES + 2)
    configured = drag(sizes)
    assert configured[1] == (1024, 768), "pinned while moving"
    assert configured[-1] == (950, 700), "exact once settled"


def test_the_release_takes_a_bounded_number_of_frames() -> None:
    sizes = [(900, 700), (950, 700)] + [(950, 700)] * 20
    configured = drag(sizes)
    pinned = [i for i, c in enumerate(configured) if c != (950, 700)]
    assert max(pinned) <= SETTLE_FRAMES + 1, f"still pinned at frame {max(pinned)}"


def test_a_resize_during_the_settle_re_arms_the_pin() -> None:
    """A drag is not a smooth stream of sizes -- a pause mid-drag must not drop
    the pin and hand the next pixel a full rebuild."""
    sizes = [(900, 700), (950, 700), (950, 700), (980, 700), (980, 700)]
    configured = drag(sizes)
    assert configured[3] == (1024, 768)
    assert configured[4] == (1024, 768), "the pin was re-armed, not counting down"


def test_a_zero_bucket_disables_pinning_entirely() -> None:
    """The escape hatch for a platform where the compositor does something
    other than scale the buffer. Nothing is rounded, ever."""
    sizes = [(900, 700), (901, 700), (902, 700)]
    assert drag(sizes, bucket=0) == sizes


def test_an_exact_multiple_of_the_bucket_is_left_alone() -> None:
    assert drag([(768, 512), (768, 512 + 1)], bucket=256)[1] == (768, 768)
    target, _ = surface_size_for((768, 512), (700, 500), 0, 256)
    assert target == (768, 512), "already on the grid; nothing to round"


def test_the_default_bucket_is_a_deliberate_number() -> None:
    """256 px was the value measured, and it bounds the waste: a buffer is
    never more than 255 px wider or taller than its window."""
    assert Settings().resize_bucket == 256


@pytest.mark.parametrize("bucket", [64, 128, 256, 512])
def test_the_buffer_never_exceeds_the_window_by_more_than_the_bucket(bucket: int) -> None:
    """The memory bound. Anything looser and a large window on a small GPU
    starts paying for this in VRAM rather than in frames."""
    for width in range(300, 2000, 7):
        target, _ = surface_size_for((width, 700), (0, 0), 0, bucket)
        assert 0 <= target[0] - width < bucket
        assert target[0] % bucket == 0

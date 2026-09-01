"""Bundled assets: the default font stack.

A font is bundled rather than resolved from the OS for two reasons
(ARCHITECTURE.md §5.7.2): a framework that renders nothing until the user
configures a font path is not usable out of the box, and golden-image tests
cannot be deterministic against whatever fonts a CI runner happens to have.

See ``fonts/README.md`` for provenance and licensing.
"""

from __future__ import annotations

from pathlib import Path
from typing import Final

__all__ = [
    "DEFAULT_FONT",
    "FALLBACK_CHAIN",
    "FONT_DIR",
    "MEDIUM_FONT",
    "font_path",
]

FONT_DIR: Final = Path(__file__).parent / "fonts"

#: Material Design 3's default typeface for its type scale.
DEFAULT_FONT: Final = FONT_DIR / "Roboto-Regular.ttf"

#: Weight 500, for `label-large` and other medium-weight type-scale roles.
MEDIUM_FONT: Final = FONT_DIR / "Roboto-Medium.ttf"

#: Resolution order for FontDB. Mirrors M3's Roboto -> Noto Sans chain;
#: Roboto Flex is excluded because M3 states it is not part of the typescale.
FALLBACK_CHAIN: Final = (DEFAULT_FONT, FONT_DIR / "NotoSans-Regular.ttf")


def font_path(name: str) -> Path:
    """Absolute path to a bundled font file. Raises if it is not present."""
    path = FONT_DIR / name
    if not path.is_file():
        available = sorted(p.name for p in FONT_DIR.glob("*.ttf"))
        raise FileNotFoundError(f"no bundled font {name!r}; available: {available}")
    return path

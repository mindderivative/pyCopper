"""pyCopper -- a GPU-accelerated declarative desktop GUI framework.

Everything re-exported here is the public API and is covered by semantic
versioning. Anything else is private and may change without a major bump.
"""

from __future__ import annotations

from .config import Settings
from .runtime import Engine
from .theme import TOKEN_ORDER, Palette, Theme, is_token

__version__ = "0.0.1"

__all__ = [
    "TOKEN_ORDER",
    "Engine",
    "Palette",
    "Settings",
    "Theme",
    "__version__",
    "is_token",
]

"""pyCopper -- a GPU-accelerated declarative desktop GUI framework.

Everything re-exported here is the public API and is covered by semantic
versioning. Anything else is private and may change without a major bump.
"""

from __future__ import annotations

from .app import App, run
from .config import Settings
from .runtime import Engine
from .runtime.signals import Computed, Effect, Signal, batch, untrack
from .spec import SpecError, ViewSpec, WidgetSpec, load_view
from .theme import TOKEN_ORDER, Palette, Theme, is_token

__version__ = "0.0.1"

__all__ = [
    "TOKEN_ORDER",
    "App",
    "Computed",
    "Effect",
    "Engine",
    "Palette",
    "Settings",
    "Signal",
    "SpecError",
    "Theme",
    "ViewSpec",
    "WidgetSpec",
    "__version__",
    "batch",
    "is_token",
    "load_view",
    "run",
    "untrack",
]

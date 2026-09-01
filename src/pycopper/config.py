"""Framework configuration. Every field is overridable via ``PYCOPPER_*`` env vars."""

from __future__ import annotations

from typing import Literal

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict

__all__ = ["Settings"]


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_prefix="PYCOPPER_", env_file=".env", extra="forbid")

    title: str = "pyCopper"
    width: int = Field(default=1024, gt=0)
    height: int = Field(default=768, gt=0)

    #: 'ondemand' draws only when requested -- see ARCHITECTURE.md 5.10.
    update_mode: Literal["ondemand", "continuous", "manual"] = "ondemand"
    #: 0 means a truly idle app renders zero frames.
    min_fps: float = Field(default=0.0, ge=0)
    max_fps: float = Field(default=60.0, gt=0)

    #: 'low-power' selects the integrated GPU on hybrid laptops -- wrong default
    #: for a framework that must handle full-window resizes at 60fps.
    power_preference: Literal["high-performance", "low-power"] = "high-performance"

    #: Override the OS device-pixel-ratio. 0 means "use the OS value".
    force_pixel_ratio: float = Field(default=0.0, ge=0)

    hot_reload: bool = False
    log_level: Literal["DEBUG", "INFO", "WARNING", "ERROR"] = "WARNING"

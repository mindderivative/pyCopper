"""Loading view files.

``yaml.safe_load`` only -- view files are treated as untrusted input, so no
object construction, no arbitrary tags.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

import yaml
from pydantic import ValidationError

from .models import ViewSpec, WidgetSpec

__all__ = ["SpecError", "load_view", "parse_view"]


class SpecError(ValueError):
    """A view file that is malformed or fails validation, with its location."""


def _format(exc: ValidationError, origin: str) -> str:
    lines = [f"{origin}: {exc.error_count()} validation error(s)"]
    for err in exc.errors():
        path = ".".join(str(p) for p in err["loc"]) or "<root>"
        lines.append(f"  {path}: {err['msg']}")
    return "\n".join(lines)


def parse_view(data: Any, *, origin: str = "<string>") -> ViewSpec:
    """Validate an already-decoded mapping into a :class:`ViewSpec`."""
    if not isinstance(data, dict):
        raise SpecError(f"{origin}: expected a mapping at the top level, got {type(data).__name__}")
    # A bare widget (no `version:`/`root:`) is accepted as the root, so trivial
    # view files stay trivial.
    payload = data if "root" in data else {"root": data}
    try:
        return ViewSpec.model_validate(payload)
    except ValidationError as exc:
        raise SpecError(_format(exc, origin)) from exc


def load_view(path: str | Path) -> ViewSpec:
    """Read and validate a YAML view file."""
    p = Path(path)
    try:
        text = p.read_text(encoding="utf-8")
    except OSError as exc:
        raise SpecError(f"cannot read view file {p}: {exc}") from exc
    try:
        data = yaml.safe_load(text)
    except yaml.YAMLError as exc:
        raise SpecError(f"{p}: invalid YAML: {exc}") from exc
    if data is None:
        raise SpecError(f"{p}: file is empty")
    return parse_view(data, origin=str(p))


def find_by_id(root: WidgetSpec, widget_id: str) -> WidgetSpec | None:
    return next((n for n in root.walk() if n.id == widget_id), None)

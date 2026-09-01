"""Spec: the validated, immutable document parsed from a view file."""

from .expressions import Expression, ExpressionError, Template
from .include import IncludeError, resolve_includes
from .loader import SpecError, load_view, parse_view
from .models import (
    BorderSpec,
    ShadowSpec,
    SizeSpec,
    StyleSpec,
    ViewSpec,
    WidgetKind,
    WidgetSpec,
)

__all__ = [
    "BorderSpec",
    "Expression",
    "ExpressionError",
    "IncludeError",
    "ShadowSpec",
    "SizeSpec",
    "SpecError",
    "StyleSpec",
    "Template",
    "ViewSpec",
    "WidgetKind",
    "WidgetSpec",
    "load_view",
    "parse_view",
    "resolve_includes",
]

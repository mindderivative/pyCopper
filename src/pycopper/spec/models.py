"""The Spec tree: validated, immutable, inert data parsed from a view file.

This is the framework's single validation boundary (ARCHITECTURE.md 1.3). A typo
in a YAML key or an unknown MD3 token fails HERE, at load, with a path -- not
later as a cryptic hardware error or a silently ignored style.

Spec nodes are frozen and hashable, so reconciliation can skip untouched
subtrees by identity. They hold no runtime state whatsoever; that lives on the
Element tree (ARCHITECTURE.md 4).
"""

from __future__ import annotations

from enum import StrEnum
from typing import Annotated, Any, Literal

from pydantic import BaseModel, BeforeValidator, ConfigDict, Field, field_validator

from ..layout import EdgeInsets
from ..theme import is_token
from .expressions import Template

__all__ = [
    "BorderSpec",
    "ShadowSpec",
    "SizeSpec",
    "StyleSpec",
    "ViewSpec",
    "WidgetKind",
    "WidgetSpec",
]

SCHEMA_VERSION = 1


class WidgetKind(StrEnum):
    """Enum, not a bare string -- an unknown widget fails at load."""

    CONTAINER = "Container"
    ROW = "Row"
    COLUMN = "Column"
    STACK = "Stack"
    TEXT = "Text"
    BUTTON = "Button"
    SPACER = "Spacer"
    ICON = "Icon"
    # Material Design 3 components
    CARD = "Card"
    DIVIDER = "Divider"
    CHECKBOX = "Checkbox"
    RADIO = "Radio"
    SWITCH = "Switch"
    CHIP = "Chip"
    ICON_BUTTON = "IconButton"
    FAB = "Fab"
    BADGE = "Badge"
    NAVIGATION_RAIL = "NavigationRail"
    NAVIGATION_DRAWER = "NavigationDrawer"
    NAV_ITEM = "NavItem"
    TOP_APP_BAR = "TopAppBar"
    TABS = "Tabs"
    TAB = "Tab"
    SEGMENTED_BUTTON = "SegmentedButton"
    SEGMENT = "Segment"
    LIST_ITEM = "ListItem"
    LINEAR_PROGRESS = "LinearProgress"


class SizeSpec:
    """``120`` | ``auto`` | ``expand`` | ``50%`` | ``flex:2``."""

    __slots__ = ("kind", "value")

    def __init__(self, kind: str, value: float = 0.0) -> None:
        self.kind = kind
        self.value = value

    @classmethod
    def parse(cls, raw: Any) -> SizeSpec:
        if isinstance(raw, SizeSpec):
            return raw
        if isinstance(raw, bool):
            raise ValueError(f"invalid size {raw!r}")
        if isinstance(raw, int | float):
            if raw < 0:
                raise ValueError(f"size must be non-negative, got {raw}")
            return cls("fixed", float(raw))
        if isinstance(raw, str):
            text = raw.strip().lower()
            if text == "auto":
                return cls("auto")
            if text == "expand":
                return cls("expand")
            if text.endswith("%"):
                return cls("percent", float(text[:-1]) / 100.0)
            if text.startswith("flex"):
                _, _, weight = text.partition(":")
                return cls("flex", float(weight) if weight else 1.0)
        raise ValueError(
            f"invalid size {raw!r}; expected a number, 'auto', 'expand', 'N%' or 'flex:N'"
        )

    def __eq__(self, other: object) -> bool:
        return isinstance(other, SizeSpec) and other.kind == self.kind and other.value == self.value

    def __hash__(self) -> int:
        return hash((self.kind, self.value))

    def __repr__(self) -> str:
        return f"SizeSpec({self.kind!r}, {self.value})"


AUTO = SizeSpec("auto")


def _parse_edges(raw: Any) -> EdgeInsets:
    """``8`` | ``[h, v]`` | ``[l, t, r, b]`` | mapping."""
    if isinstance(raw, EdgeInsets):
        return raw
    if isinstance(raw, int | float):
        return EdgeInsets.all(float(raw))
    if isinstance(raw, dict):
        return EdgeInsets(
            float(raw.get("left", 0)),
            float(raw.get("top", 0)),
            float(raw.get("right", 0)),
            float(raw.get("bottom", 0)),
        )
    if isinstance(raw, list | tuple):
        vals = [float(v) for v in raw]
        if len(vals) == 2:
            return EdgeInsets.symmetric(horizontal=vals[0], vertical=vals[1])
        if len(vals) == 4:
            return EdgeInsets(*vals)
    raise ValueError(f"invalid edge insets {raw!r}; expected number, [h,v], or [l,t,r,b]")


def _parse_corners(raw: Any) -> tuple[float, float, float, float]:
    """``16`` | ``[tl, tr, br, bl]``."""
    if isinstance(raw, int | float):
        return (float(raw),) * 4
    if isinstance(raw, list | tuple) and len(raw) == 4:
        return tuple(float(v) for v in raw)  # type: ignore[return-value]
    raise ValueError(f"invalid corner radius {raw!r}; expected a number or [tl,tr,br,bl]")


def _validate_token(raw: Any) -> str:
    """Reject unknown MD3 tokens at load, where the error is actionable."""
    if not isinstance(raw, str):
        raise ValueError(f"expected an MD3 token name, got {raw!r}")
    if raw.startswith("#"):
        return raw  # literal hex, validated by parse_hex downstream
    if not is_token(raw):
        raise ValueError(
            f"unknown MD3 token {raw!r}; use a token name (e.g. 'surface_variant') "
            f"or a '#RRGGBB' literal"
        )
    return raw


Size = Annotated[SizeSpec, BeforeValidator(SizeSpec.parse)]
Edges = Annotated[EdgeInsets, BeforeValidator(_parse_edges)]
Corners = Annotated[tuple[float, float, float, float], BeforeValidator(_parse_corners)]
TokenRef = Annotated[str, BeforeValidator(_validate_token)]


class _Frozen(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True, arbitrary_types_allowed=True)


class BorderSpec(_Frozen):
    width: float = Field(default=1.0, ge=0)
    color: TokenRef = "outline"


class ShadowSpec(_Frozen):
    blur: float = Field(default=8.0, ge=0)
    offset_x: float = 0.0
    offset_y: float = 2.0
    color: TokenRef = "shadow"
    opacity: float = Field(default=0.35, ge=0, le=1)


#: Every variant name any component accepts. A widget validates that the one it
#: was given is meaningful for it; declaring them centrally catches typos at
#: load, where the error names the path.
Variant = Literal[
    # buttons and cards
    "filled",
    "filled_tonal",
    "outlined",
    "elevated",
    "text",
    # sizes (FAB, icon button)
    "standard",
    "small",
    "medium",
    "large",
    # chips
    "assist",
    "filter",
    "input",
    "suggestion",
    # badges
    "dot",
    "numbered",
    # dividers
    "full_bleed",
    "inset",
    # app bars
    "center_aligned",
    # tabs (primary anchors a rounded indicator; secondary a flat stroke)
    "primary",
    "secondary",
    # list items
    "one_line",
    "two_line",
    "three_line",
]


class StyleSpec(_Frozen):
    """Visual and geometric properties. Note that `children` is NOT here --
    children are structure, and belong on the widget."""

    width: Size = AUTO
    height: Size = AUTO
    padding: Edges = EdgeInsets()
    margin: Edges = EdgeInsets()

    background: TokenRef | None = None
    #: None means "use this widget's own M3 default for its variant". An
    #: explicit token always wins.
    color: TokenRef | None = None
    corner_radius: Corners = (0.0, 0.0, 0.0, 0.0)
    border: BorderSpec | None = None
    shadow: ShadowSpec | None = None
    opacity: float = Field(default=1.0, ge=0, le=1)

    # flex / stack
    spacing: float = Field(default=0.0, ge=0)
    main_alignment: Literal[
        "start", "end", "center", "space_between", "space_around", "space_evenly"
    ] = "start"
    cross_alignment: Literal["start", "end", "center", "stretch"] = "start"
    align_x: float = Field(default=0.0, ge=0, le=1)
    align_y: float = Field(default=0.0, ge=0, le=1)

    # text
    font_size: float = Field(default=14.0, gt=0)

    #: Which M3 variant of the component to render.
    variant: Variant = "filled"
    #: Divider thickness and inset, in logical px.
    thickness: float = Field(default=1.0, gt=0)
    inset: float = Field(default=0.0, ge=0)

    # icons. `text:` carries the icon name, so a binding expression can switch
    # icons at runtime -- e.g. text: "{{ 'star' if saved.get() else 'star_border' }}"
    icon_size: float = Field(default=24.0, gt=0)
    #: 0 = outlined, 1 = filled. M3 uses this for selected/unselected states.
    icon_fill: float = Field(default=0.0, ge=0, le=1)
    icon_weight: float = Field(default=400.0, ge=100, le=700)


class WidgetSpec(_Frozen):
    id: str = Field(pattern=r"^[A-Za-z_][A-Za-z0-9_-]*$")
    widget: WidgetKind
    style: StyleSpec = StyleSpec()
    text: str | None = None
    #: A bound value: selection for Checkbox/Radio/Switch/Chip, count for
    #: Badge, progress for indicators. Templated like `text`, so
    #: `value: "{{ checked.get() }}"` tracks a signal.
    value: str | None = None
    #: A ListItem's second line. Content, not style, and templated like `text`.
    supporting_text: str | None = None
    handlers: dict[str, str] = Field(default_factory=dict)
    children: tuple[WidgetSpec, ...] = ()

    @field_validator("handlers")
    @classmethod
    def _check_handler_names(cls, value: dict[str, str]) -> dict[str, str]:
        for event in value:
            if not event.startswith("on_"):
                raise ValueError(f"handler key {event!r} must start with 'on_'")
        return value

    def template(self) -> Template | None:
        """Compiled text template, or None for a widget with no text."""
        return Template(self.text) if self.text is not None else None

    def value_template(self) -> Template | None:
        return Template(self.value) if self.value is not None else None

    def supporting_template(self) -> Template | None:
        return Template(self.supporting_text) if self.supporting_text is not None else None

    def walk(self) -> Any:
        yield self
        for child in self.children:
            yield from child.walk()


class ViewSpec(_Frozen):
    """A whole view file: a schema version plus one root widget."""

    version: int = SCHEMA_VERSION
    root: WidgetSpec

    @field_validator("version")
    @classmethod
    def _check_version(cls, value: int) -> int:
        if value != SCHEMA_VERSION:
            raise ValueError(
                f"view schema version {value} is not supported "
                f"(this build understands version {SCHEMA_VERSION})"
            )
        return value

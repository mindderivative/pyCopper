"""Resolving M3 type-scale roles to sizes.

**pyCopper ships no type-scale figures, deliberately.**

M3 defines 15 baseline type styles "from Display Large to Label Small", and the
role *names* are well established. The numbers behind them are not available to
this project: the reference library's token table
(`styles/M3-Styles-Typography-TypeScaleTokens.md`) is an interactive widget that
scraped empty, and the only figures anywhere in the library are six values
scattered through a condensed summary -- one of which, `headline-large`,
appears as **both 32sp and 36sp** in the same file. Four roles are sourced
unambiguously; ten have no value at all.

Baking a full scale in from recall and labelling it Material would be two
thirds invention. So the framework provides the *mechanism* -- a validated role
vocabulary, and `text_style:` resolved to `font_size` once at load -- and the
figures come from the application:

    type_scale:
      title-large: 22
      body-medium: 14

    root:
      widget: Text
      style: {text_style: title-large}

`examples/typescale.yaml` carries a complete scale that can be included with one
line. Its header states exactly what those numbers are and are not.

Naming a role with no scale entry is a **load-time error naming the role**, not
a silent fallback to the default size. A quiet default here would be an
invented number wearing a Material label, which is the failure this whole
module exists to avoid.
"""

from __future__ import annotations

from typing import Any

from .models import StyleSpec, ViewSpec, WidgetSpec

__all__ = ["TypeScaleError", "apply_type_scale"]


class TypeScaleError(ValueError):
    """A `text_style:` role that the view's `type_scale:` does not define."""


def _resolve(node: WidgetSpec, scale: dict[str, float]) -> WidgetSpec:
    children = tuple(_resolve(child, scale) for child in node.children)
    role = node.style.text_style
    style: StyleSpec | None = None
    if role is not None:
        if role not in scale:
            known = ", ".join(sorted(scale)) or "nothing"
            raise TypeScaleError(
                f"{node.id}: text_style {role!r} is not in this view's `type_scale:` "
                f"(which defines {known}). pyCopper ships no type-scale figures; "
                f"include one, e.g. `type_scale: {{source: typescale.yaml}}`."
            )
        fields: dict[str, Any] = {
            name: getattr(node.style, name) for name in node.style.model_fields_set
        }
        fields["font_size"] = float(scale[role])
        style = StyleSpec(**fields)

    if style is None and all(a is b for a, b in zip(children, node.children, strict=True)):
        return node
    update: dict[str, Any] = {"children": children}
    if style is not None:
        update["style"] = style
    return node.model_copy(update=update)


def apply_type_scale(view: ViewSpec) -> ViewSpec:
    """Resolve every `text_style:` to a concrete `font_size`.

    A no-op when no node names a role, so the common case pays nothing -- not
    even a tree walk's worth of copying.
    """
    scale = {str(k): float(v) for k, v in view.type_scale.items()}
    root = _resolve(view.root, scale)
    overlays = tuple(_resolve(o, scale) for o in view.overlays)
    if root is view.root and all(a is b for a, b in zip(overlays, view.overlays, strict=True)):
        return view
    return view.model_copy(update={"root": root, "overlays": overlays})

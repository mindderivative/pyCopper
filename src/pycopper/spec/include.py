"""View composition: ``source:`` pulls a subtree in from another file.

Resolution happens on the **decoded YAML**, before Pydantic validates anything.
A resolved include is therefore indistinguishable from inline content -- the
spec models, reconciliation, and the renderer never learn a file boundary
existed.

A fragment is a plain widget spec that may declare ``params:``; the call site
supplies them with ``with:``::

    # dialogs/confirm.yaml
    params: [title]
    widget: Card
    children:
      - {name: label, widget: Text, text: "{{ title }}"}

    # call site
    - name: delete_confirm
      source: dialogs/confirm.yaml
      with: {title: "Delete file?"}

Parameters are substituted **textually**, which is what makes them compose with
bindings: passing ``title: "{{ user.get() }}"`` leaves a live template behind,
while passing a plain string leaves static text. No separate reactive path is
needed.
"""

from __future__ import annotations

import re
from pathlib import Path
from typing import Any, Final

import yaml

__all__ = ["IncludeError", "resolve_includes"]

#: Keys that control inclusion rather than describing a widget.
SOURCE_KEY: Final = "source"
PARAMS_KEY: Final = "params"
WITH_KEY: Final = "with"

#: How deep includes may nest. A guard against pathological graphs; cycles are
#: caught separately and reported precisely.
MAX_DEPTH: Final = 32

_PARAM_RE: Final = re.compile(r"\{\{\s*([A-Za-z_][A-Za-z0-9_]*)\s*\}\}")


class IncludeError(ValueError):
    """An include that cannot be resolved, with the chain that led to it."""


def _chain_text(chain: tuple[Path, ...]) -> str:
    return " -> ".join(p.name for p in chain) if chain else "<root>"


def _resolve_path(raw: str, base: Path, root: Path, chain: tuple[Path, ...]) -> Path:
    """Resolve *raw* against the including file, confined under *root*.

    View files are untrusted input, so an include may not escape the view
    directory -- ``source: ../../../etc/passwd`` is refused rather than read.
    """
    candidate = (base / raw).resolve()
    try:
        candidate.relative_to(root.resolve())
    except ValueError:
        raise IncludeError(
            f"{_chain_text(chain)}: include {raw!r} resolves outside the view "
            f"directory ({root}); includes may not escape it"
        ) from None
    if not candidate.is_file():
        raise IncludeError(f"{_chain_text(chain)}: included file not found: {candidate}")
    return candidate


def _substitute(node: Any, values: dict[str, str]) -> Any:
    """Replace ``{{ name }}`` with the supplied text, throughout the fragment."""
    if isinstance(node, str):
        return _PARAM_RE.sub(
            lambda m: values[m.group(1)] if m.group(1) in values else m.group(0), node
        )
    if isinstance(node, dict):
        return {k: _substitute(v, values) for k, v in node.items()}
    if isinstance(node, list):
        return [_substitute(v, values) for v in node]
    return node


def _namespace_names(node: Any, prefix: str, local: set[str]) -> Any:
    """Qualify every `name` declared inside a fragment with the call-site name.

    Positional ids are inherently scoped by path, so only names need this --
    but they need it badly: including the same fragment twice would otherwise
    give two nodes the same name, and ``find()`` would return the wrong one.
    """
    if isinstance(node, list):
        return [_namespace_names(v, prefix, local) for v in node]
    if not isinstance(node, dict):
        return node

    out: dict[str, Any] = {}
    for key, value in node.items():
        if key == "name" and isinstance(value, str):
            out[key] = value if value == prefix else f"{prefix}.{value}"
        elif key == "anchor" and isinstance(value, str) and value in local:
            # An anchor naming a fragment-local id must follow it; one naming
            # an outer element is left alone.
            out[key] = f"{prefix}.{value}"
        else:
            out[key] = _namespace_names(value, prefix, local)
    return out


def _collect_names(node: Any, into: set[str]) -> None:
    if isinstance(node, dict):
        if isinstance(node.get("name"), str):
            into.add(node["name"])
        for value in node.values():
            _collect_names(value, into)
    elif isinstance(node, list):
        for value in node:
            _collect_names(value, into)


def _load_fragment(path: Path, chain: tuple[Path, ...]) -> dict[str, Any]:
    try:
        raw = yaml.safe_load(path.read_text(encoding="utf-8"))
    except yaml.YAMLError as exc:
        raise IncludeError(f"{_chain_text((*chain, path))}: invalid YAML: {exc}") from exc
    except OSError as exc:
        raise IncludeError(f"{_chain_text(chain)}: cannot read {path}: {exc}") from exc
    if not isinstance(raw, dict):
        raise IncludeError(
            f"{_chain_text((*chain, path))}: a fragment must be a mapping "
            f"(one widget), got {type(raw).__name__}"
        )
    return raw


def _expand(
    node: dict[str, Any],
    base: Path,
    root: Path,
    sources: set[Path],
    chain: tuple[Path, ...],
) -> dict[str, Any]:
    """Replace one ``source:`` node with the fragment it names."""
    if len(chain) >= MAX_DEPTH:
        raise IncludeError(f"{_chain_text(chain)}: includes nested more than {MAX_DEPTH} deep")

    path = _resolve_path(str(node[SOURCE_KEY]), base, root, chain)
    if path in chain:
        raise IncludeError(f"include cycle: {_chain_text((*chain, path))}")
    sources.add(path)

    fragment = _load_fragment(path, chain)
    declared = fragment.pop(PARAMS_KEY, []) or []
    if not isinstance(declared, list):
        raise IncludeError(f"{path.name}: `params:` must be a list of names")

    supplied = node.get(WITH_KEY) or {}
    if not isinstance(supplied, dict):
        raise IncludeError(f"{_chain_text((*chain, path))}: `with:` must be a mapping")

    missing = [p for p in declared if p not in supplied]
    if missing:
        raise IncludeError(
            f"{_chain_text((*chain, path))}: missing parameter(s) {missing}; "
            f"{path.name} declares {declared}"
        )
    unknown = [k for k in supplied if k not in declared]
    if unknown:
        raise IncludeError(
            f"{_chain_text((*chain, path))}: unknown parameter(s) {unknown}; "
            f"{path.name} declares {declared or '[]'}"
        )

    fragment = _substitute(fragment, {k: str(v) for k, v in supplied.items()})

    # Resolve the fragment's own includes relative to ITS directory.
    resolved = _walk(fragment, path.parent, root, sources, (*chain, path))
    fragment = resolved if isinstance(resolved, dict) else fragment

    call_name = node.get("name")
    if isinstance(call_name, str):
        local: set[str] = set()
        _collect_names(fragment, local)
        fragment = _namespace_names(fragment, call_name, local)
        fragment["name"] = call_name

    # Anything else at the call site (open:, style:, ...) is not merged --
    # parameters are the interface. Carrying `id` across is the one exception.
    for key in (SOURCE_KEY, WITH_KEY, "name"):
        node.pop(key, None)
    if node:
        raise IncludeError(
            f"{_chain_text((*chain, path))}: a `source:` node takes only `name:` "
            f"and `with:`; got {sorted(node)}. Pass configuration as parameters."
        )
    return fragment


def _walk(node: Any, base: Path, root: Path, sources: set[Path], chain: tuple[Path, ...]) -> Any:
    if isinstance(node, list):
        return [_walk(v, base, root, sources, chain) for v in node]
    if not isinstance(node, dict):
        return node
    if SOURCE_KEY in node:
        return _expand(dict(node), base, root, sources, chain)
    return {k: _walk(v, base, root, sources, chain) for k, v in node.items()}


def resolve_includes(
    data: Any,
    *,
    base: Path,
    root: Path | None = None,
    sources: set[Path] | None = None,
) -> Any:
    """Expand every ``source:`` in *data*.

    ``base`` is the directory of the file being resolved; ``root`` confines
    includes (defaults to *base*). Every file touched is added to ``sources``,
    which is what lets hot reload watch the whole graph rather than one file.
    """
    return _walk(
        data,
        base,
        root if root is not None else base,
        sources if sources is not None else set(),
        (),
    )

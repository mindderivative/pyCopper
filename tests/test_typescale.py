"""M3 type-scale roles.

pyCopper ships the role *vocabulary* and the resolution mechanism, and no
figures. The reference library's token table scraped empty, and the only sizes
anywhere in it are six values in a condensed summary -- one of which,
`headline-large`, appears as both 32sp and 36sp in the same file. A full scale
written from memory and labelled Material would be two thirds invention.

So the interesting tests here are about what happens when a size is *missing*.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from pycopper.spec import SpecError, parse_view
from pycopper.spec.loader import load_view
from pycopper.spec.models import TYPE_ROLES


def view(scale: dict | None, style: dict):
    payload: dict = {"root": {"name": "t", "widget": "Text", "text": "x", "style": style}}
    if scale is not None:
        payload["type_scale"] = scale
    return parse_view(payload)


# ------------------------------------------------------------ vocabulary


def test_there_are_fifteen_roles() -> None:
    """M3: "15 baseline" styles, "from Display Large to Label Small"."""
    assert len(TYPE_ROLES) == 15
    assert TYPE_ROLES[0] == "display-large"
    assert TYPE_ROLES[-1] == "label-small"


def test_every_group_has_three_steps() -> None:
    for group in ("display", "headline", "title", "body", "label"):
        steps = [r for r in TYPE_ROLES if r.startswith(f"{group}-")]
        assert len(steps) == 3, group


def test_a_name_outside_the_vocabulary_is_rejected() -> None:
    with pytest.raises(SpecError):
        view({"title-large": 22}, {"text_style": "title-enormous"})


# ------------------------------------------------------------ resolution


def test_a_role_resolves_to_a_font_size() -> None:
    parsed = view({"title-large": 22}, {"text_style": "title-large"})
    assert parsed.root.style.font_size == 22.0


def test_resolution_happens_at_load() -> None:
    """So every widget downstream keeps reading a plain float, and a role
    costs nothing per frame."""
    parsed = view({"body-medium": 14}, {"text_style": "body-medium"})
    assert isinstance(parsed.root.style.font_size, float)


def test_a_role_beats_an_explicit_size() -> None:
    """Naming a role is the more specific statement of intent."""
    parsed = view({"title-large": 22}, {"text_style": "title-large", "font_size": 99})
    assert parsed.root.style.font_size == 22.0


def test_text_without_a_role_is_untouched() -> None:
    parsed = view({"title-large": 22}, {"font_size": 17})
    assert parsed.root.style.font_size == 17.0
    assert parsed.root.style.text_style is None


def test_roles_resolve_inside_nested_nodes_and_overlays() -> None:
    parsed = parse_view(
        {
            "type_scale": {"title-large": 22},
            "root": {
                "name": "root",
                "widget": "Column",
                "children": [
                    {"name": "deep", "widget": "Text", "style": {"text_style": "title-large"}}
                ],
            },
            "overlays": [
                {
                    "name": "d",
                    "widget": "Dialog",
                    "open": "true",
                    "style": {"text_style": "title-large"},
                }
            ],
        }
    )
    assert parsed.root.children[0].style.font_size == 22.0
    assert parsed.overlays[0].style.font_size == 22.0


def test_a_view_with_no_roles_is_not_rewritten() -> None:
    """The common case must not pay for a tree copy."""
    from pycopper.spec.typescale import apply_type_scale

    parsed = parse_view({"name": "t", "widget": "Text", "text": "x"})
    assert apply_type_scale(parsed) is parsed


# --------------------------------------------------------- missing sizes


def test_an_undefined_role_is_an_error_not_a_default() -> None:
    """The whole point. A silent fallback to the default size would be an
    invented number wearing a Material label."""
    with pytest.raises(SpecError, match="display-large"):
        view({"title-large": 22}, {"text_style": "display-large"})


def test_the_error_says_what_the_scale_does_define() -> None:
    with pytest.raises(SpecError) as excinfo:
        view({"title-large": 22, "body-medium": 14}, {"text_style": "label-small"})
    message = str(excinfo.value)
    assert "title-large" in message and "body-medium" in message


def test_naming_a_role_with_no_scale_at_all_errors() -> None:
    with pytest.raises(SpecError):
        view(None, {"text_style": "title-large"})


# ---------------------------------------------------------------- sharing


def test_a_scale_can_live_in_its_own_file(tmp_path: Path) -> None:
    (tmp_path / "scale.yaml").write_text("title-large: 22\nbody-medium: 14\n")
    (tmp_path / "app.yaml").write_text(
        "type_scale: {source: scale.yaml}\n"
        "root: {name: t, widget: Text, text: x, style: {text_style: title-large}}\n"
    )
    parsed = load_view(tmp_path / "app.yaml")
    assert parsed.root.style.font_size == 22.0


def test_an_included_scale_is_watched_for_reload(tmp_path: Path) -> None:
    (tmp_path / "scale.yaml").write_text("title-large: 22\n")
    (tmp_path / "app.yaml").write_text(
        "type_scale: {source: scale.yaml}\n"
        "root: {name: t, widget: Text, text: x, style: {text_style: title-large}}\n"
    )
    sources: set[Path] = set()
    load_view(tmp_path / "app.yaml", sources=sources)
    assert {p.name for p in sources} == {"app.yaml", "scale.yaml"}


def test_a_scale_file_of_non_numbers_is_rejected(tmp_path: Path) -> None:
    (tmp_path / "scale.yaml").write_text("title-large: enormous\n")
    (tmp_path / "app.yaml").write_text(
        "type_scale: {source: scale.yaml}\nroot: {name: t, widget: Text, text: x}\n"
    )
    with pytest.raises(SpecError, match="maps each role to a number"):
        load_view(tmp_path / "app.yaml")


def test_the_shipped_example_only_claims_what_is_sourced() -> None:
    """`examples/typescale.yaml` must never grow unsourced figures. Of M3's
    fifteen roles only four appear with a size in the reference library; the
    rest are commented placeholders pointing at the spec."""
    import yaml

    path = Path(__file__).resolve().parents[1] / "examples/typescale.yaml"
    scale = yaml.safe_load(path.read_text())
    assert set(scale) == {"headline-medium", "title-large", "title-small", "label-medium"}
    text = path.read_text()
    assert "m3.material.io/styles/typography/type-scale-tokens" in text
    assert "32sp and 36sp" in text, "the contradiction must stay recorded"

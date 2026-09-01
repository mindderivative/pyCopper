"""The bundled font stack. Golden-image determinism depends on these existing."""

from __future__ import annotations

import pytest
from fontTools.ttLib import TTFont

from pycopper.assets import DEFAULT_FONT, FALLBACK_CHAIN, FONT_DIR, MEDIUM_FONT, font_path


def test_default_font_is_present() -> None:
    assert DEFAULT_FONT.is_file()


def test_fallback_chain_files_all_exist() -> None:
    for path in FALLBACK_CHAIN:
        assert path.is_file(), path


def test_chain_starts_with_the_default() -> None:
    """M3's chain is Roboto -> Noto Sans; Roboto must be tried first."""
    assert FALLBACK_CHAIN[0] == DEFAULT_FONT


def test_licences_are_shipped_beside_the_fonts() -> None:
    """OFL requires the licence to be redistributed with the font."""
    for name in ("LICENSE-Roboto.txt", "LICENSE-NotoSans.txt"):
        text = (FONT_DIR / name).read_text(encoding="utf-8")
        assert "SIL OPEN FONT LICENSE" in text.upper()


@pytest.mark.parametrize(
    ("path", "family", "weight"),
    [
        (DEFAULT_FONT, "Roboto", 400),
        (MEDIUM_FONT, "Roboto", 500),
        (FONT_DIR / "NotoSans-Regular.ttf", "Noto Sans", 400),
    ],
)
def test_font_metadata(path, family: str, weight: int) -> None:
    tt = TTFont(path, lazy=True)
    names = {r.nameID: str(r) for r in tt["name"].names if r.platformID == 3}
    assert (names.get(16) or names.get(1)) == family
    assert tt["OS/2"].usWeightClass == weight
    tt.close()


def test_fonts_are_openly_licensed() -> None:
    for path in FONT_DIR.glob("*.ttf"):
        tt = TTFont(path, lazy=True)
        licence = next(
            (str(r) for r in tt["name"].names if r.nameID == 13 and r.platformID == 3), ""
        )
        tt.close()
        assert "Open Font License" in licence, f"{path.name}: {licence[:60]!r}"


def test_fallback_widens_coverage() -> None:
    """The fallback tier must actually add codepoints, or it is dead weight."""

    def cps(p):
        tt = TTFont(p, lazy=True)
        out = set(tt.getBestCmap())
        tt.close()
        return out

    assert len(cps(FALLBACK_CHAIN[1]) - cps(DEFAULT_FONT)) > 1000


def test_font_path_rejects_unknown_names() -> None:
    with pytest.raises(FileNotFoundError, match="no bundled font"):
        font_path("Comic Sans.ttf")

# Bundled fonts

pyCopper ships a default font so that it renders text out of the box and so
that golden-image tests are deterministic (ARCHITECTURE.md §5.7.2, §11). Text
tests must never resolve a font through the OS: shaping output and rasterised
coverage vary between font versions, so a system-resolved face produces
different bytes on every machine and every CI image.

## What is here, and why

Material Design 3 names **Roboto** as the default typeface of its type scale,
and **Noto Sans** as the fallback collection, with the chain
`Roboto Flex -> Roboto -> Noto Sans`
(`M3-References/styles/M3-Styles-Typography-Fonts.md`). Roboto Flex is excluded
deliberately: the same page states it "isn't yet part of the M3 typescale".

| File | Size | Weight | Codepoints | Role |
|---|---|---|---|---|
| `Roboto-Regular.ttf` | 154 KB | 400 | 927 | Default face |
| `Roboto-Medium.ttf` | 154 KB | 500 | 927 | `label-large` and other medium-weight type-scale roles |
| `NotoSans-Regular.ttf` | 612 KB | 400 | 3094 | Fallback tier |
| `NotoSansMono-Regular.ttf` | 396 KB | 400 | 3490 | `MONOSPACE_FONT` -- Terminal's default face |

| `MaterialSymbolsOutlined-Subset.ttf` | 102 KB | variable | 218 icons | Material Symbols |

Total ≈ 1.4 MB.

## Monospace

M3 names no monospace typeface -- it has no such role. `NotoSansMono-Regular.ttf`
is bundled anyway, specifically for `Terminal` (`widgets/terminal.py`): a
terminal's cell/cursor grid is positioned by `column * cell_width` regardless
of what glyphs a run actually shapes to, which only lines up when every glyph
shares one advance width. Found live, 2026-09-08: with the previous default
(Roboto, proportional), five lowercase letters like `hello` measured ~2.5
cell-widths narrower than the grid assumed, so the cursor visibly detached
from typed text by several columns after only a few keystrokes -- confirmed
by direct measurement (`TextEngine.measure`), and confirmed fixed by the same
measurement against `NotoSansMono-Regular.ttf` (`M`/`i`/`hello` all land
exactly on the grid, zero drift). Not part of `FALLBACK_CHAIN` -- an ordinary
`Text` widget has no reason to fall back to a monospace face -- exported
separately as `assets.MONOSPACE_FONT` instead.

## Icons

Material Symbols is a **variable icon font**, so icons render through the same
glyph pipeline as text (ARCHITECTURE.md §5.7.8). The full outlined font is
10.6 MB for ~4,275 icons; this is a `fontTools` subset of a curated 218-icon
core set covering the M3 component catalogue, with `GRAD` and `opsz` pinned and
`FILL` (0–1) and `wght` (100–700) kept live — 102 KB, a 102× reduction.

Source:

```
https://github.com/google/material-design-icons/raw/master/variablefont/MaterialSymbolsOutlined[FILL,GRAD,opsz,wght].ttf
```

It is licensed **Apache-2.0**, not OFL, and embeds no licence name record — its
terms come from that repository's `LICENSE`, vendored here as
`LICENSE-MaterialSymbols.txt`. `material_symbols.json` maps icon names to
codepoints.

Noto Sans adds 2,187 codepoints beyond Roboto — 841 extended Latin, 289 Greek,
533 combining marks and modifiers, 129 Devanagari, 115 Cyrillic. It is the
**Latin/Greek/Cyrillic** Noto family, so it widens coverage *within* those
scripts; it does not add CJK, Arabic, or emoji. The full Noto Sans collection
is 119 MB (plus 299 MB for CJK) and cannot be shipped in a Python package, so
broader fallback depends on system font discovery, which is deferred past v1.

## Provenance

All three families were taken from the canonical `google/fonts` repository,
which publishes them only as variable fonts. The static faces here were
produced with `fontTools.varLib.instancer`, pinning `wght` (400 / 500) and
`wdth` (100):

```
https://github.com/google/fonts/raw/main/ofl/roboto/Roboto[wdth,wght].ttf
https://github.com/google/fonts/raw/main/ofl/notosans/NotoSans[wdth,wght].ttf
https://github.com/google/fonts/raw/main/ofl/notosansmono/NotoSansMono[wdth,wght].ttf
```

Instancing rather than shipping the variable fonts saves several MB and keeps
the font loader simple: no variation axes to configure at load time.

## Licensing

All three families are under the **SIL Open Font License 1.1** — see
`LICENSE-Roboto.txt`, `LICENSE-NotoSans.txt`, and `LICENSE-NotoSansMono.txt`,
which must be redistributed with them. OFL is compatible with pyCopper's MIT
licence; the fonts remain under OFL and are not relicensed.

Note that Roboto was **relicensed**: copies predating the move to `ofl/` in
`google/fonts` (for example the v2.137 build from 2017 still shipped by some
distributions) carry Apache-2.0 instead. The files here are OFL.

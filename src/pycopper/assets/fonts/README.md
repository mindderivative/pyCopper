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

Total ≈ 920 KB.

Noto Sans adds 2,187 codepoints beyond Roboto — 841 extended Latin, 289 Greek,
533 combining marks and modifiers, 129 Devanagari, 115 Cyrillic. It is the
**Latin/Greek/Cyrillic** Noto family, so it widens coverage *within* those
scripts; it does not add CJK, Arabic, or emoji. The full Noto Sans collection
is 119 MB (plus 299 MB for CJK) and cannot be shipped in a Python package, so
broader fallback depends on system font discovery, which is deferred past v1.

## Provenance

Both families were taken from the canonical `google/fonts` repository, which
publishes them only as variable fonts. The static faces here were produced with
`fontTools.varLib.instancer`, pinning `wght` (400 / 500) and `wdth` (100):

```
https://github.com/google/fonts/raw/main/ofl/roboto/Roboto[wdth,wght].ttf
https://github.com/google/fonts/raw/main/ofl/notosans/NotoSans[wdth,wght].ttf
```

Instancing rather than shipping the variable fonts saves ~1.6 MB and keeps the
font loader simple: no variation axes to configure at load time.

## Licensing

Both families are under the **SIL Open Font License 1.1** — see
`LICENSE-Roboto.txt` and `LICENSE-NotoSans.txt`, which must be redistributed
with them. OFL is compatible with pyCopper's MIT licence; the fonts remain
under OFL and are not relicensed.

Note that Roboto was **relicensed**: copies predating the move to `ofl/` in
`google/fonts` (for example the v2.137 build from 2017 still shipped by some
distributions) carry Apache-2.0 instead. The files here are OFL.

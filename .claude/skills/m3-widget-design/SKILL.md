---
name: m3-widget-design
description: Design, build, restyle, or audit a pyCopper widget using Material Design 3 as the baseline design system, translated into pyCopper's spec/element/layout/paint architecture. Use whenever the user asks to add a new pyCopper widget, redesign or restyle an existing one, or compare a widget against Material Design -- even without saying "M3", e.g. "let's build a radio button", "add a switch widget", "make the Slider look more standard", "does our Button match the M3 spec", "we need a card widget".
---

# M3-Baseline Widget Design for pyCopper

Material Design 3 is pyCopper's guiding design system for widget anatomy,
sizing, colour, and interaction. This is the process for turning an M3 spec
into a real widget in this codebase, and for the two related tasks: restyling
an existing widget toward M3, and auditing one against its spec without
changing anything.

**This is a living skill.** The framework is under active construction; the
"Current framework state" section at the bottom records what exists today and
what is still stubbed. Update that section (and anything else here that has
gone stale) as part of the work whenever a milestone changes the answer.
`ARCHITECTURE.md` is the authority if the two ever disagree.

## Step 1: Get the M3 baseline

Use the `m3-lookup` skill to find the component's spec before designing or
judging anything: variants, dp dimensions, corner radii, colour-role tokens,
states. If the spec points at a cross-cutting topic -- a colour role, an
elevation level, a motion pattern -- follow `m3-lookup`'s style path for that
topic too, rather than treating the component page as the whole story.

If the widget has no clean M3 analogue (pyCopper's `Row`, `Column`, `Stack`,
`Spacer` are layout primitives with no catalogue entry), say so and design from
pyCopper's own precedent instead of forcing a mapping.

## Step 2: Translate the spec

pyCopper's architecture happens to line up with M3 unusually well, so most of
this is direct. State each choice anyway -- a reader should see what M3 says,
what pyCopper does, and why they differ.

- **dp -> logical px is 1:1.** Layout runs entirely in logical, device-
  independent units and only converts to physical pixels in the paint pass
  (`ARCHITECTURE.md` §7). An M3 `40dp` container is `height: 40` in a view
  file. Do not scale for DPI anywhere in a widget -- `PaintContext.pixel_ratio`
  handles it, once, at emit time.
- **Colour roles map to real tokens.** pyCopper implements MD3 dynamic colour
  through `materialyoucolor`, so `md.sys.color.primary` is the token
  `"primary"`, `md.sys.color.on-surface-variant` is `"on_surface_variant"`.
  Names are **snake_case** in view files (the library's own attributes are
  camelCase; `theme/tokens.py` holds the generated mapping). Check a name with
  `pycopper.theme.is_token()`; the full frozen vocabulary is `TOKEN_ORDER`
  (59 tokens). Never hard-code a hex value for something that has a role.
- **Emit tokens, not colours.** Pass `token=palette.index("primary")` to the
  display list and leave the literal `color=` at `(1, 1, 1, 1)`. The shader
  resolves the index against the palette buffer, which is what makes a theme
  switch a single buffer upload with no relayout and no display-list rebuild.
  A literal colour opts that element out of theming entirely -- only correct
  for a genuinely fixed colour.
- **Shape scale maps to `corner_radius`.** M3's `none/4/8/12/16/28/full`
  becomes a number or `[tl, tr, br, bl]`. For "full", use half the height.
  Per-corner radii are supported all the way through to the shader.
- **State layers are the established pattern.** M3's hover 8% / focus 10% /
  press 10% / drag 16% overlays are how `ButtonElement` already works: emit an
  extra box above the container, tinted with the *content* role token, at the
  state opacity. Follow it rather than swapping to a different container
  colour per state.
- **Touch targets.** M3's 48x48dp minimum applies to hit testing, not to the
  visible container. A 40dp button with a 48dp target needs the hit rect to
  exceed the painted rect -- pyCopper does not model that split yet, so raise
  it as a real design question rather than silently painting a 48dp button.
- **Elevation is approximated.** M3 elevation is tonal surface shift *plus*
  shadow; pyCopper currently has only `ShadowSpec` (blur, offset, opacity).
  Pick a shadow that reads like the right level and say that the tonal half is
  missing.

## Step 3: Build it

The concrete sequence in this codebase. Read the neighbouring code first --
`src/pycopper/widgets/base.py` is short and every existing widget is a worked
example.

1. **Add the kind.** A new member of `WidgetKind` in `src/pycopper/spec/models.py`.
   That enum is the authoritative list of what a view file may name; an unknown
   widget fails at load.
2. **Add style properties if needed.** `StyleSpec` is `extra="forbid"` and
   `frozen=True`, so any new property must be declared there or the view file
   is rejected. Prefer reusing existing properties over adding near-duplicates.
   Validate MD3 token fields with the `TokenRef` annotation so a bad token
   fails at load with a path, not at render.
3. **Write the element class** in `src/pycopper/widgets/base.py`:
   `class FooElement(_StyledMixin, <LayoutAlgorithm>)`, choosing the M1 layout
   node that matches the widget's geometry (`Padding` for a styled box, `Flex`
   for a linear arrangement, `Stack` for overlays).
   - Declare **no `__slots__`** -- the mixin supplies `__dict__` and the layout
     base supplies slots. Two non-empty slotted bases would conflict.
   - `__init__` calls the layout base's `__init__` explicitly, then
     `self.init_element(spec)`.
   - Implement **`configure()`** if the constructor captures anything derived
     from the spec (padding, alignment, spacing). Reconciliation calls it on
     reload; without it, an edited view file updates the spec but keeps the old
     layout parameters.
   - Implement `perform_layout(constraints) -> Size`. It **must** return a size
     satisfying its constraints, and must not read its own offset or the
     parent's size. Pass `parent_uses_size=False` when the child's size genuinely
     doesn't affect yours -- that makes the child a relayout boundary.
   - Implement `paint_self(ctx, absolute)` for anything beyond the default
     background/border/shadow. Override `child_paint_context` to clip children.
   - Emit in back-to-front order: shadow, container, state layer, content.
4. **Register it** in `_REGISTRY`.
5. **Wire handlers** if it's interactive. View files name handlers under
   `handlers:` with `on_`-prefixed keys; the dispatcher resolves them against
   the app's registry at mount and errors on an unknown name. Read state from
   `self.state` (`hovered`, `pressed`, `focused`, `scroll`, `data`).
6. **Invalidate correctly.** `mark_needs_paint()` for a visual-only change,
   `mark_needs_layout()` when geometry changes. Using the heavier one "to be
   safe" silently costs frames and is exactly what the tests below catch.

## Step 4: Test it

Most of a widget is testable with no GPU. Match the existing suites:

- **Layout** (`tests/test_layout_*.py` style, no GPU): constraints in, size
  out; padding, alignment, and flex behaviour; the invariant that size depends
  only on constraints and children.
- **Spec** (`tests/test_spec.py`): the new kind parses, bad tokens and unknown
  style keys are rejected with a useful path.
- **Paint** (`tests/test_app.py` style): assert the widget emits the expected
  number of instances, in the expected order, **with palette token indices
  rather than literal colours**.
- **Invalidation**: assert that a state change marks paint and *not* layout.
- **Golden** (`tests/golden/`, marked `@pytest.mark.gpu`): render offscreen and
  assert real pixels for anything whose correctness is visual -- corner
  rounding, borders, clipping, state layers.

## Step 5: Verify and document

```bash
.venv/bin/ruff check . && .venv/bin/ruff format . && .venv/bin/mypy && .venv/bin/python -m pytest -q
```

`mypy` runs strict and the suite must be fully green, GPU tests included, before
the widget is done. Then update `ARCHITECTURE.md` -- the widget list, and the
M3-versus-pyCopper translation notes from Step 2, so the reasoning survives.

Commit when the user asks, using the `commit` skill or matching the existing
message style in `git log`. Pushing is always a separate, explicit request.

## Restyle and audit requests

If the ask is "make X match M3 better" or "does X match the spec" for a widget
that already exists, **do not jump to changing code**. Produce a gap list
first: dimensions, colour roles, shape, states, behaviour -- each with the M3
value, pyCopper's current value, and a suggested target where there's a clear
opinion. Some gaps are deliberate decisions already reasoned through, and some
are blocked on framework features that don't exist yet. Let the user choose
what to close before implementing.

## Current framework state

*Last updated: end of M5. Update this section whenever a milestone changes it.*

**Available:** spec/Pydantic validation with binding expressions; fine-grained
signals; element tree with state-preserving reconciliation; constraint layout
(Padding, Align, SizedBox, ConstrainedBox, Flex/Row/Column, Stack, Flexible,
Spacer); the single instanced SDF pipeline with per-corner radii, borders,
shadows, analytic antialiasing and rounded in-shader clipping; the full 59-token
MD3 palette with one-upload theme switching; events with hit testing,
capture/bubble, pointer capture, hover and focus.

**Text is real as of M4.** Shaped through HarfBuzz with GPOS kerning and
ligatures, wrapped per UAX #14, fallback resolved per grapheme cluster, and
rasterised into the shared glyph atlas. Roboto Regular/Medium and Noto Sans are
bundled (`pycopper.assets`), so M3's `label-large` medium weight is available.
Measure with `TextEngine.measure` / `measure_text`, paint with `paint_text` --
both take `font_size` in logical px, matching M3's `sp`/`dp` figures 1:1.

**Widgets today:** Container, Row, Column, Stack, Button, Text, Spacer.

**Sizing inside a Row or Column:** a child styled `width: expand` (or `flex:n`)
along the main axis is flexible and shares the free space; anything else is
measured first and takes what it needs. A `Text` widget shrink-wraps to its ink
extent, so it will not starve its siblings.

**Verifying a widget visually:** add it to `examples/gallery/view.yaml` and
regenerate the golden baseline (ARCHITECTURE.md §11.1). The gallery is the
golden corpus, so a widget that appears there is regression-tested from then
on. Run the example with hot reload on and edit the YAML live while iterating.

**Not available yet -- design around these, and say so when a spec needs one:**

- **The M3 type scale.** Widgets take a raw `font_size`; the 15 baseline and
  15 emphasized type-scale roles (`label-large`, `title-medium`, …) are not
  modelled as named styles. Note the scraped token tables in `M3-References`
  are empty and the scattered values disagree with themselves (`headline-large`
  appears as both 32sp and 36sp), so a real source is needed before hardcoding
  the scale.
- **RTL text.** Direction and run ordering work, but the bundled fonts carry no
  Arabic or Hebrew glyphs, and caret/selection across a direction boundary is
  unimplemented (risk R9).
- **Icons.** No icon pipeline. The image atlas and `Kind.IMAGE` exist in the
  shader, and the glyph atlas now proves the packing path works, but nothing
  loads or packs icons yet. Most M3 components assume a 24dp icon, so this
  blocks faithful FABs, icon buttons, chips, and nav items.
- **Scrolling / viewports.** No scroll element; `state.scroll` exists but
  nothing consumes it.
- **Separate hit and paint rects**, so M3's 48dp minimum touch target on a
  smaller visible container cannot be expressed.
- **Disabled state.** No `disabled` flag, so M3's 12%/38% disabled opacities
  have nowhere to attach.
- **Focus ring rendering.** Focus is tracked and dispatched, but nothing draws
  M3's 2dp high-contrast indicator.
- **Motion.** No animation or transition system; every state change is instant.
- **Tonal elevation.** Shadows only (see Step 2).

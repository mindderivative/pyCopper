# pyCopper — Architecture

**A GPU-accelerated declarative desktop GUI framework for Python 3.14**

Status: Design. Revision 1. Last updated 2026-08-31.

---

## 1. Purpose, Scope, and Non-Goals

pyCopper is a **distributable** desktop GUI framework: users `pip install pycopper`, author their interface declaratively in YAML, write application logic in Python, and get a hardware-accelerated Material Design 3 interface with no C toolchain on their machine.

### 1.1 In scope

- Declarative, hot-reloadable YAML layout with Pydantic validation.
- Fine-grained reactive state binding between Python logic and the view.
- A constraint-based layout engine that is deterministic, single-pass, and testable without a GPU.
- A single instanced WebGPU pipeline rendering every UI primitive — boxes, borders, shadows, glyphs, images — in one draw call, with analytic antialiasing.
- Full Material Design 3 dynamic colour from a seed, with zero-relayout theme switching.
- Non-blocking `asyncio` integration for application work.

### 1.2 Explicit non-goals (v1)

| Non-goal | Rationale |
|---|---|
| Web, mobile, or embedded targets | **Desktop-only, and not merely for now** — see §1.2.1. |
| Touch input | No touch, stylus, or gesture handling. Pointer, keyboard, and scroll wheel only. |
| Complex text shaping (Arabic, Devanagari, CJK vertical) | Requires HarfBuzz; a seam is designed in, see §5.7. |
| Screen-reader bridge (AT-SPI / UIA / NSAccessibility) | Native and per-OS. The *semantic tree* is built (§5.11); the bridge that would push it to a platform is not. |
| CSS compatibility | The style vocabulary is MD3-shaped, not CSS-shaped. |
| Hot-reload of Python application logic | YAML reload only. Python reload is a different, much harder problem. |
| Multi-window | Single window in v1; the engine is written so the canvas is not a singleton. |

#### 1.2.1 What "desktop-only" changes

This is a design stance, not a deferral, and it settles a class of questions
that would otherwise be argued repeatedly.

**M3 is written mobile-first.** Applying it faithfully to a desktop framework
means knowing which of its rules are about *fingers* and which are about
*design*. Rules that do not apply here:

- **The 48×48dp minimum touch target, by default.** A finger-precision
  requirement; a mouse pointer is precise to the pixel, so a control is
  hit-tested at the size it is drawn unless a view asks otherwise. It *can* now
  be asked for — `min_hit_size: 48` (§5.9.1) — because "expressible but off by
  default" and "not expressible" are different things, and only the first lets
  an application decide.
- **Touch ripple radiating from the contact point.** State layers still apply;
  the ripple's touch-origin behaviour does not.
- **Compact breakpoints (<600dp).** Desktop windows live in M3's Expanded,
  Large, and Extra Large classes. Window *resizing* still matters; phone-shaped
  layout does not.
- **Bottom-anchored navigation.** Navigation Bar and Bottom App Bar are
  explicitly mobile patterns in M3's own catalogue. Navigation Rail and
  Navigation Drawer are their desktop counterparts and take priority.

Correspondingly, affordances M3 treats as secondary are **primary** here, and
should be built before mobile-shaped components:

- **Hover** is a first-class state, not a progressive enhancement.
- **Focus rings and keyboard traversal** are how a desktop application is
  navigated (§5.11.1, built).
- **Visible scrollbars** and wheel-driven scrolling (§5.14, built).
- **Right-click and context menus**, **cursor shape**, and **mouse text
  selection** are desktop conventions with no mobile analogue, and are not
  built yet.

### 1.3 Design principles

1. **Separate the document from the runtime.** Parsed YAML is inert data. Live UI is a mutable tree. Never conflate them (§4).
2. **Layout must not know the GPU exists.** It is pure Python over numbers, so it is unit-testable and fast to iterate.
3. **Do the least work per frame.** Python, not the GPU, is the frame-time bottleneck. Every subsystem is designed around caching and dirty-subtree invalidation.
4. **Validate at the boundary.** Untrusted YAML becomes strictly-typed data once, at parse time. Nothing downstream re-checks or defensively guards.
5. **One draw call is a design constraint, not an aspiration.** Any feature that would force a pipeline or bind-group switch (scissor clipping, per-widget textures) is rejected or redesigned (§5.8).

---

## 2. Dependency Stack

Versions are those verified present in the project virtual environment on Python 3.14.6.

### 2.1 Windowing and graphics

| Package | Ver | Role |
|---|---|---|
| `wgpu` | 0.32.0 | Graphics API. Targets Vulkan / Metal / DX12 through `wgpu-native`. Ships prebuilt binaries — no user toolchain. |
| `rendercanvas` | 2.7.2 | Owns the window, the surface, the event loop, and the frame scheduler. See §5.10 — this is a larger role than it first appears. |
| `glfw` | 2.10.2 | Backend for `rendercanvas.glfw`. Used **directly** only for capabilities rendercanvas does not surface (monitor enumeration, clipboard). |
| `cffi`, `pycparser` | 2.1.1, 3.0 | GLFW binding substrate. Transitive; never imported by pyCopper. |

> **Correction to prior plan.** `wgpu.gui` was removed in wgpu-py; it does not exist in 0.32.0. The canvas import is `from rendercanvas.glfw import RenderCanvas`. Adapter and device acquisition are async by default: synchronous call sites must use `wgpu.gpu.request_adapter_sync()` and `adapter.request_device_sync()`.

### 2.2 Data, validation, configuration

| Package | Ver | Role |
|---|---|---|
| `PyYAML` | 6.0.3 | Parses view documents. **`safe_load` only** — view files are treated as untrusted input. |
| `pydantic` / `pydantic-core` | 2.13.5 | Validates the YAML dictionary into the strict Spec tree (§5.1). The single validation boundary in the system. |
| `pydantic-settings`, `python-dotenv` | 2.15.0, 1.2.3 | Framework configuration: DPI override, log level, vsync, backend selection, hot-reload toggle. |
| `numpy` | 2.5.2 | **Load-bearing.** Structured dtypes are the in-memory representation of the GPU instance buffer; display-list assembly is vectorised, not per-widget Python. Was omitted from the prior plan. |
| `annotated-types`, `typing_extensions`, `typing-inspection` | — | Pydantic transitive. |

### 2.3 Styling and text

| Package | Ver | Role |
|---|---|---|
| `materialyoucolor` | 3.0.4 | Derives the full MD3 tonal token set from a seed colour. Used as a **class**, not instantiated: `MaterialDynamicColors.primary.get_rgba(scheme)`. |
| `pillow` | 12.3.0 | Decodes user-supplied image assets (PNG/JPEG) into RGBA arrays for atlas upload. Not used for glyph staging; numpy suffices there. |

### 2.3.1 Text stack

Text is the one subsystem where a single library is not enough. Five packages divide the work along clean seams; each does exactly one job and none overlaps another.

| Package | Ver | Role | Standard |
|---|---|---|---|
| `uharfbuzz` | 0.56.1 | **Shaping.** Text + font + script + direction → positioned glyph IDs. Applies `GSUB` (ligatures, contextual forms) and `GPOS` (real kerning, mark attachment). | OpenType |
| `freetype-py` | 2.5.1 | **Rasterisation only.** Glyph ID + pixel size → 8-bit coverage bitmap, plus hinting and outline metrics. | — |
| `fontTools` | 4.64.0 | **Script itemisation** (`fontTools.unicodedata`), **font metadata** (`name`/`OS/2`/`head` tables), coverage indexing for the fallback chain. | UAX #24 |
| `python-bidi` | 0.6.11 | **Bidirectional reordering** — logical order → visual order for mixed LTR/RTL text. Rust-backed. | UAX #9 |
| `uniseg` | 0.10.1 | **Line break opportunities** and **grapheme cluster** segmentation. | UAX #14, UAX #29 |

`uharfbuzz` ships as a `cp310-abi3` wheel — it uses the CPython stable ABI, so it does not need recompilation for 3.14 or any future release. `python-bidi` and `fontTools` publish native `cp314` wheels. No user toolchain is required on any platform.

**Two corrections to the previous revision.** `freetype-py` was described as calculating "kerning and text layout"; it does neither in the sense required. Its role is now narrowly and accurately scoped to rasterisation. And the previous plan deferred shaping to a post-1.0 tier — with `uharfbuzz` present from the start, correct shaping is a v1 feature (§5.7).

Combined wheel footprint for the text stack is ≈16 MB, dominated by `uniseg`'s Unicode tables (8.2 MB) and `fontTools` (5.3 MB). Acceptable for a desktop framework; noted because it roughly triples install size.

### 2.4 Concurrency and tooling

| Package | Ver | Role |
|---|---|---|
| `anyio`, `idna` | 4.14.2, 3.19 | Structured concurrency primitives for application-level background work. |
| `watchfiles` | 1.2.0 | Rust-backed filesystem watching for YAML hot-reload (§5.11). |

---

## 3. System Overview

```text
┌─────────────────────────────────────────────────────────────────────────────┐
│  APPLICATION                                                                │
│  view.yaml  ──bindings──▶  Signals  ◀──reads/writes──  app.py (async)       │
└──────────────────────────────────┬──────────────────────────────────────────┘
                                   │
┌──────────────────────────────────▼──────────────────────────────────────────┐
│  FRAMEWORK CORE                          (single-threaded, engine thread)   │
│                                                                             │
│   spec/      ─▶  tree/       ─▶  layout/      ─▶  paint/                    │
│   Pydantic       Element         Constraints      Display list              │
│   Spec tree      tree +          down, sizes      (numpy structured         │
│   (immutable)    reconciler      up               array of instances)       │
│                                                                             │
│   runtime/  engine · events · signals · hot-reload                          │
│   theme/    MD3 token palette (one GPU buffer)                              │
│   text/     shaping seam · line breaking · glyph run cache                  │
└──────────────────────────────────┬──────────────────────────────────────────┘
                                   │
┌──────────────────────────────────▼──────────────────────────────────────────┐
│  RENDER                                                                     │
│  atlas (glyph R8 + image RGBA8) · ring-buffered instance upload             │
│  ONE render pass ─▶ ONE instanced draw ─▶ ui.wgsl (SDF + analytic AA)       │
└──────────────────────────────────┬──────────────────────────────────────────┘
                                   │
┌──────────────────────────────────▼──────────────────────────────────────────┐
│  wgpu-native  ▸  Vulkan (Linux) · Metal (macOS) · DirectX 12 (Windows)      │
└─────────────────────────────────────────────────────────────────────────────┘
```

---

## 4. The Four-Tree Model

The most important structural decision in pyCopper. Four representations exist, each with a distinct lifetime and mutability. Collapsing any two of them causes a class of bugs that is very expensive to unwind later.

| # | Tree | Type | Mutable | Lifetime | Owns |
|---|---|---|---|---|---|
| 1 | **Spec** | Pydantic models | No | Replaced wholesale on hot-reload | Declared structure, static style, binding expressions |
| 2 | **Element** | Plain Python objects | Yes | Persists across reloads | Resolved style, focus, scroll offset, hover state, animation clocks, signal subscriptions |
| 3 | **Layout** | Fields on Element | Yes | Per layout pass | `constraints`, `size`, `offset`, `relayout_boundary` |
| 4 | **Display list** | numpy structured array | Rebuilt | Per paint pass, cached per subtree | Flat, painter-ordered GPU instances |

Hot-reload is therefore **reconciliation**, not replacement: parse a new Spec tree, diff it against the previous one, and patch the Element tree in place, preserving runtime state wherever a node's `id` and widget type match. A user editing `corner_radius` in their YAML does not lose scroll position, focus, or text-field contents.

This is also what makes fine-grained invalidation possible: because Elements are stable objects, a signal can hold a durable subscription to one.

---

## 5. Subsystem Specifications

### 5.1 Spec layer — `spec/`

`spec/loader.py` reads YAML via `yaml.safe_load`. `spec/models.py` defines the Pydantic hierarchy.

```python
class StyleSpec(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    width: SizeSpec = SizeSpec.AUTO  # px | "auto" | "expand" | flex(n) | pct(n)
    height: SizeSpec = SizeSpec.AUTO
    padding: EdgeInsets = EdgeInsets.zero()
    margin: EdgeInsets = EdgeInsets.zero()
    background: TokenRef | None = None  # MD3 token name -> resolved to palette index
    corner_radius: Corners = Corners.all(0.0)
    border: BorderSpec | None = None
    shadow: ShadowSpec | None = None


class WidgetSpec(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    id: str
    widget: WidgetKind  # enum, not str
    style: StyleSpec = StyleSpec()
    bindings: dict[str, Expression] = {}  # "text": {{ user.name }}
    handlers: dict[str, str] = {}  # "on_click": "submit_form"
    children: list["WidgetSpec"] = []
```

Three deliberate choices:

- **`extra="forbid"`.** A typo in a YAML key is a startup error with a line number, not a silently ignored style.
- **`frozen=True`.** Spec nodes are immutable and safely shareable. Reconciliation compares them *structurally* (`==`) to skip untouched subtrees, and by identity as the fast path. They are deliberately not hashable — `handlers` is a mapping — and nothing requires them to be.
- **`WidgetKind` is an enum, and `background` is a validated `TokenRef`.** The prior plan's `background: str` deferred the failure to render time; here an unknown token name fails at load, where the error is actionable.

Note the **structural fix** to the prior `view.yaml`: `children` was nested under `style`. Children are structure, not styling; they belong on `WidgetSpec`.

`spec/expressions.py` parses `{{ … }}` binding expressions with :mod:`ast` — which does not execute anything — then walks the result against a strict node whitelist: attribute access, indexing, comparison, arithmetic, conditionals, and a small table of pure functions. **`eval` is never used on view content.** View files are data.

Rejected and covered by tests: `__import__`, `open`, `eval`, dunder and underscore-prefixed attributes, comprehensions, lambdas, and any method outside a short safe list. This matters because a view file is exactly the kind of artefact users copy from the internet.

### 5.2 Reactivity — `runtime/signals.py`

Fine-grained reactivity, in the SolidJS/Preact-signals tradition.

```python
class Signal[T]:
    def get(self) -> T: ...    # registers a dependency on the active tracking scope
    def set(self, value: T) -> None: ...   # notifies subscribers if != current

class Computed[T]:             # lazily recomputed, memoised, itself a dependency
class Effect:                  # side-effecting subscriber, used to drive Elements
```

A module-level tracking stack records which Element is currently rebuilding. Any `Signal.get()` during that rebuild adds the Element to the signal's subscriber set. A later `Signal.set()` therefore knows the exact set of Elements to invalidate.

**Invalidation is typed.** A single global dirty flag would redraw everything on every change; instead each Element carries three independent flags:

| Flag | Set when | Triggers |
|---|---|---|
| `needs_build` | A bound signal changed | Re-evaluate bindings; recompute resolved style |
| `needs_layout` | Resolved geometry changed | Layout pass from the nearest relayout boundary |
| `needs_paint` | Only visual properties changed | Display-list rebuild for that subtree |

Changing a button's colour sets `needs_paint` alone; layout does not run. Changing its label sets `needs_layout`, but propagation stops at the nearest relayout boundary (§5.4), so a label change inside a fixed-size panel never reaches the root.

**Threading contract:** signals are engine-thread-only. Background tasks marshal writes via `loop.call_soon_threadsafe` (§8).

### 5.3 Element tree and reconciliation — `tree/`

`tree/element.py` defines the mutable runtime node:

```python
class Element:
    spec: WidgetSpec
    parent: Element | None
    children: list[Element]

    # resolved
    style: ResolvedStyle  # tokens -> palette indices, sizes -> floats
    # layout (§5.4)
    constraints: Constraints
    size: Size
    offset: Offset  # relative to parent
    relayout_boundary: Element | None
    # runtime state — survives hot reload
    state: WidgetState  # focus, hover, pressed, scroll, animations
    subscriptions: set[Signal]
    # caching
    cached_instances: np.ndarray | None
    needs_build: bool
    needs_layout: bool
    needs_paint: bool
```

`tree/reconcile.py` implements keyed diffing. For each level, children are matched by `(id, widget)`. Matched nodes are updated in place and keep `state`; unmatched old nodes are disposed (subscriptions released); unmatched new nodes are constructed. Reordering is handled by index remapping rather than destroy-and-rebuild.

Structurally identical subtrees are **skipped entirely** — if `old.spec == new.spec`, nothing below can differ either, so the whole branch is left alone. `ReconcileStats` reports `created`/`updated`/`reused`/`disposed`/`skipped`, and the tests assert on those counts rather than merely on the resulting tree, which is what catches an accidental rebuild.

A widget kind change or an id change forces a rebuild: the old element is disposed and a fresh one constructed. Anything else would leave state attached to a node that no longer means the same thing.

### 5.4 Layout engine — `layout/`

**Constraints down, sizes up, parent positions children.** Single pass, O(n), no solver, fully deterministic.

```python
@dataclass(frozen=True, slots=True)
class Constraints:
    min_w: float
    max_w: float
    min_h: float
    max_h: float

    def tight(self) -> bool:
        return self.min_w == self.max_w and self.min_h == self.max_h
```

The protocol every widget implements:

```python
def layout(self, c: Constraints) -> Size:
    """Choose a size satisfying c. Call child.layout(...) for each child
    and assign child.offset. Must not read own offset or parent size."""
```

The final clause is the invariant that makes the whole thing work: a node's size depends only on its constraints and its children, never on its position or siblings. That is what permits subtree-local relayout.

**Relayout boundaries.** A node is a boundary when nothing beneath it can change its size, so dirt cannot propagate upward past it. There are **two independent conditions**, and the implementation found the second to be the more valuable one:

1. **Tight constraints** — the parent has already fixed the child's size.
2. **`parent_uses_size=False`** — the parent does not read the child's size at all, so it cannot care if it changes. This is strictly cheaper: it applies even under loose constraints, and it is the common case for `Align`, `Stack`, and any container that fills its own constraints.

`layout()` computes the boundary; subclasses implement `perform_layout()` and never call it directly. Marking `needs_layout` walks up only to the nearest boundary and schedules it on a `LayoutOwner`, which flushes dirty boundaries in **depth order** so a parent never relayouts a child twice.

Two consequences worth stating, both surfaced by tests:

- A fixed-size box containing padding makes **every** descendant a boundary, because deflating a tight constraint leaves it tight. This is the cheapest possible arrangement — dirt cannot escape the leaf at all.
- Relayout of a boundary uses `_layout_without_resize()`: its size provably cannot change, so the parent is never notified. That is precisely what makes subtree-local layout valid rather than merely an optimisation.

**Intrinsic sizing** (`get_min_intrinsic_width` etc.) is supported but explicitly opt-in and memoised per layout pass, because it is the one construct in this model that can go quadratic.

`layout/algorithms.py` provides: `Box` (single child + padding/alignment), `Row` / `Column` (main-axis flex distribution in two sub-passes — inflexible children first, then remaining space to flex weights), `Stack` (z-ordered overlay), `Scroll` (unbounded child constraint on one axis, clipping viewport), and `TextBox` (delegates to §5.7).

**This module imports nothing from `render/` or `wgpu`.** It is exercised entirely by unit tests.

### 5.5 Paint and the display list — `paint/`

The paint pass walks the Element tree in painter order (back to front, depth-first, children after parent) and emits GPU instances into a preallocated numpy structured array.

```python
INSTANCE_DTYPE = np.dtype(
    [
        ("rect", np.float32, 4),  # x, y, w, h — physical px, y-down
        ("radii", np.float32, 4),  # tl, tr, br, bl
        ("clip", np.float32, 4),  # ancestor clip rect
        ("clip_radii", np.float32, 4),
        ("fill", np.float32, 4),  # premultiplied RGBA, or tint for glyphs/images
        ("border", np.float32, 4),
        ("uv", np.float32, 4),  # atlas u0, v0, u1, v1
        ("params", np.float32, 4),  # border_width, shadow_blur, shadow_dx, shadow_dy
        ("flags", np.uint32, 4),  # kind, atlas_index, _, _
    ]
)  # 144 bytes; 10k instances = 1.4 MB/frame
```

Everything is `vec4`-aligned by construction, sidestepping WGSL alignment traps.

`flags.x` (kind) selects fragment behaviour: `0` = SDF box, `1` = glyph (atlas coverage × fill), `2` = image (atlas RGBA × tint), `3` = shadow, `4` = arc.

**Arcs are a fifth branch, not extra geometry** (§5.15). A test parses
`ui.wgsl` and asserts its `KIND_*` constants equal the Python `Kind` enum —
nothing else ties the two together, so a renumbered enum would silently draw
every box as a glyph rather than fail.

**Subtree caching.** Each Element caches the instance slice it produced. A clean subtree's cached slice is copied wholesale into the frame buffer; only `needs_paint` subtrees re-emit. Because instances carry absolute coordinates, a subtree that merely *moved* still needs re-emission — this is a deliberate simplicity trade, revisitable by adding a per-instance transform index.

**The cache key is the whole geometry the slice was built from** — absolute origin, size, pixel ratio, and the inherited clip — not the origin alone. Keying on origin alone shipped, and made window resizing paint stale frames: a row stretched across a Column keeps its origin when the window widens and changes only its width, so it passed the check and was spliced from its older, narrower slice. The symptom was not an obviously frozen window but *several different widths in one frame*, because rows that also shifted vertically did repaint and rows that did not stayed stale. Everything in the key is baked into the physical coordinates the slice holds, and nothing downstream can notice that they are wrong.

### 5.6 Theme — `theme/`

The MD3 token set is computed once from the seed via `materialyoucolor` and packed into a **single contiguous `float32` palette buffer** uploaded as a storage buffer.

Elements store a **`u32` palette index**, not an RGBA value.

The consequence is the point of the design: switching light/dark, changing the seed, or animating contrast is **one buffer write**. No relayout, no display-list rebuild, no Element traversal. A theme animation is free.

```python
class Palette:
    """Ordered, stable mapping of MD3 token name -> index -> RGBA."""

    def rebuild(self, seed: Hct, dark: bool, contrast: float) -> np.ndarray:
        scheme = SchemeTonalSpot(seed, dark, contrast)
        for i, name in enumerate(TOKEN_ORDER):
            r, g, b, a = getattr(MaterialDynamicColors, name).get_rgba(scheme)
            self.data[i] = (r / 255.0, g / 255.0, b / 255.0, a / 255.0)
        return self.data
```

#### 5.6.1 Colour space — a verified trap

The preferred surface format on this stack is **`rgba8unorm-srgb`**. That format treats every value written to it — clear values and fragment shader output alike — as **linear**, and applies the sRGB transfer function on write.

`materialyoucolor` returns **sRGB-encoded** 8-bit values. Dividing by 255 therefore yields sRGB-encoded floats, and handing those to an `-srgb` target double-encodes them.

This was measured, not theorised. The MD3 dark `surface` token is `(15, 13, 18)`. Uploaded naively as `15/255` and cleared to an `rgba8unorm-srgb` target, the rendered pixel reads back as **`(69, 64, 75)`** — a dark near-black rendered as mid-grey, and the error is largest exactly where MD3 puts its surface tones.

The palette builder therefore **linearises on upload**, and this is the only place the conversion occurs:

```python
def srgb_to_linear(c: np.ndarray) -> np.ndarray:
    return np.where(c <= 0.04045, c / 12.92, ((c + 0.055) / 1.055) ** 2.4)
```

Consequences that are load-bearing elsewhere:

- The palette buffer holds **linear** RGBA. All shader blending is therefore physically correct — alpha compositing and shadow falloff in linear space is the right answer, not an approximation.
- Alpha is **not** transformed; it is already linear.
- Colours the user supplies as literal hex in YAML go through the same function at parse time, so authored and tokenised colours agree.
- Golden-image tests compare in the sRGB output space, so this conversion is covered by them (§11).

**Public token names are snake_case; the library's are camelCase.** `materialyoucolor` exposes `surfaceVariant`, `onPrimaryContainer`, and so on. YAML authors write `surface_variant`, which is idiomatic for both YAML and Python, and `theme/tokens.py` holds the generated mapping. The vocabulary is 59 tokens, including the five `*_palette_key_color` entries — included for completeness because appending to a frozen order is safe and inserting into it is not.

Token order is a frozen, versioned constant — indices are baked into cached display lists, so reordering it is a breaking change.

### 5.7 Text — `text/`

Text is the largest subsystem in the framework and the one most often underestimated. It is specified here in full because retrofitting it is not practical: shaping, fallback, and bidi each change the data structures that layout and paint consume.

#### 5.7.1 The pipeline

Seven stages, each owned by exactly one dependency. Everything below the line was verified working against the installed versions (§5.7.6).

```text
  input: str + TextStyle (family, size, weight, features, lang)
    │
    ├─1─ Bidi resolution ......... python-bidi     UAX #9   → runs + embedding levels
    ├─2─ Script itemisation ...... fontTools.ud    UAX #24  → runs + script + direction
    ├─3─ Font resolution ......... FontDB coverage          → runs bound to a concrete face
    ├─4─ Shaping ................. uharfbuzz       OpenType → PositionedGlyph[] per run
    ├─5─ Line breaking ........... uniseg          UAX #14  → lines, from measured advances
    ├─6─ Rasterisation ........... freetype-py              → coverage bitmaps → atlas
    └─7─ Instance emission .......                          → display list (§5.5)
```

**Stage order is load-bearing.** Bidi runs first because it operates on the whole paragraph and produces the embedding levels every later stage needs. Itemisation then splits by script, and font resolution splits further by face — shaping requires a run that is uniform in *all three* of script, direction, and font.

**Stages 4 and 5 interleave.** Line breaking needs measured advances, which only shaping produces; but shaping context can cross a break.

Each block is shaped **once**. Candidate breaks are measured by looking up cumulative advances — one shaped pass attributes every glyph's advance to the source offset of its cluster, so any span costs a subtraction — and only the lines actually emitted are shaped again. That second shaping is not overhead: a line needs its own runs to paint, and shaping context legitimately differs either side of a break, which is also what corrects the table's two approximations (kerning across a cut, and a break falling inside a ligature).

**The M4 implementation did not do this**, and re-shaped the growing candidate prefix at every break opportunity. The cost that removed is worth stating precisely, because the original note here had it in the wrong variable. `line_start` advances after each emitted line, so the prefix restarts every line and the quadratic term is in break opportunities **per line**, not per paragraph — which is why paragraph length always measured linear and the regression hid. The cost therefore scaled with *how wide the window was*: one 351-character paragraph at a 120 px wrap width cost 15.5 ms, and the same text on one 3840 px line cost **107.9 ms**. A wide window holding a long line was the worst case, which is an entirely ordinary thing for a desktop application to be.

Measured after the change, the same sweep is flat at 13–15 ms across every width from 120 px to 3840 px — the worst case improving **8.4×** — and the width dependence is gone rather than reduced (§12.2).

**A femtopixel of slack is required, and that is not a fudge.** A `Text` shrink-wraps to its ink extent and the paint pass then lays it out again at *exactly* that width, so the fit test is evaluated at precise equality on every frame drawing unwrapped text. `np.sum` adds pairwise and `np.cumsum` sequentially; for `"title-small"` the two orders differ by 7e-15 px, which was enough to wrap it to "title-" / "small" so the widget measured one line and painted two. `FIT_EPSILON` is set far below a subpixel and far above float64 noise, and `test_text_laid_out_at_its_own_ink_width_stays_on_one_line` pins the invariant for all fifteen type-scale roles.

#### 5.7.2 Fonts, coverage, and fallback — `text/fontdb.py`

`FontDB` maps `(family, weight, style)` to a concrete face and owns the fallback chain.

Coverage is queried in bulk. `hb.Face.unicodes` returns the face's full codepoint set in one call — 5918 entries for DejaVu Sans — so a fallback index is built without opening every font through `fontTools`:

```python
class FontDB:
    def coverage(self, face_id: FaceId) -> frozenset[int]: ...  # from hb.Face.unicodes
    def resolve(self, cluster: str, style: TextStyle) -> FaceId:
        """First face in the chain covering every codepoint in the cluster."""
```

**Fallback resolves per grapheme cluster, not per codepoint.** Splitting a cluster across two faces produces visibly broken output for combining marks and ZWJ emoji sequences. Failure of the whole chain yields glyph `0` (`.notdef`), rendered as the font's missing-glyph box — a visible, debuggable result rather than a silent gap.

Measured on the installed stack, DejaVu Sans covers `U+0041 A` (gid 36) and `U+0627 ا` (gid 1365) but **not** `U+4F60 你` or `U+1F642 🙂`. Fallback is not a theoretical concern; it is needed for any font, for very ordinary text.

**A default font is bundled with the package.** This is not a convenience — it is required by two other parts of the architecture. Golden-image tests (§11) cannot be deterministic against whatever fonts a CI runner happens to have, and a framework that renders nothing until the user configures a font path is not usable out of the box. System font *enumeration* (fontconfig on Linux, DirectWrite on Windows, CoreText on macOS) is genuinely platform-specific and is deferred past v1; explicit font paths are supported from M4.

#### The bundled stack

Material Design 3 names **Roboto** as the default typeface of its type scale and **Noto Sans** as the fallback collection, with the chain `Roboto Flex → Roboto → Noto Sans`. Roboto Flex is excluded deliberately: M3 states it "isn't yet part of the M3 typescale".

| File | Size | Weight | Codepoints | Role |
|---|---|---|---|---|
| `Roboto-Regular.ttf` | 154 KB | 400 | 927 | Default face |
| `Roboto-Medium.ttf` | 154 KB | 500 | 927 | `label-large` and other medium-weight roles |
| `NotoSans-Regular.ttf` | 612 KB | 400 | 3,094 | Fallback tier |
| `MaterialSymbolsOutlined-Subset.ttf` | 102 KB | variable | 218 icons | Icons (§5.7.8) |

**≈1.0 MB total** (620 KB compressed in the wheel), exposed through `pycopper.assets` (`DEFAULT_FONT`, `MEDIUM_FONT`, `FALLBACK_CHAIN`) and `pycopper.text.icons`.

Three decisions worth recording:

- **M3's fallback collection cannot be shipped.** The full Noto Sans set is 119 MB, plus 299 MB for CJK — against PyPI's ~60 MB project cap. Only the Latin/Greek/Cyrillic Noto family is bundled. It adds **2,187 codepoints** over Roboto (841 extended Latin, 289 Greek, 533 combining marks and modifiers, 129 Devanagari, 115 Cyrillic), so the fallback chain is genuinely exercised in v1 rather than being dead code — but it widens coverage *within* those scripts and adds no CJK, Arabic, or emoji. Broader fallback waits on system font discovery.
- **Static instances, not variable fonts.** `google/fonts` publishes both families only as variable fonts. The bundled faces are produced with `fontTools.varLib.instancer`, pinning `wght` and `wdth`. That saves ~1.6 MB and keeps the loader free of variation-axis configuration.
- **Roboto's coverage matches Tier 1 exactly.** Its 927 codepoints span Latin, Greek, and Cyrillic — precisely the scope §5.7.7 commits to, so the bundled font and the documented text tier agree without either being bent to fit.

#### 5.7.3 Shaping — `text/shaping.py`

```python
@dataclass(frozen=True, slots=True)
class ShapedRun:
    face: FaceId
    glyphs: np.ndarray  # uint32 glyph IDs
    advances: np.ndarray  # float32, font units
    offsets: np.ndarray  # float32 (x, y) pairs — mark positioning
    clusters: np.ndarray  # uint32 byte index back into source text
```

`clusters` is what makes hit testing, caret placement, and selection possible after shaping has reordered and merged characters — it is the only link from a rendered glyph back to the source string, and it must be preserved through every later stage.

Output is numpy from the start, so stage 7 writes glyph instances vectorised (§12).

**Glyph IDs from HarfBuzz index the same table freetype rasterises from.** This is the seam the whole two-library design rests on, and it was verified directly: HarfBuzz returns gid 36 for `'A'` in DejaVu Sans, and `freetype.Face.get_char_index('A')` returns 36. No translation layer is needed or wanted.

#### 5.7.4 Caching

Four caches, in descending hit rate. Without them the perf budget in §12 is unreachable.

| Cache | Key | Value | Invalidated by |
|---|---|---|---|
| **Shaped run** | `(text, face, size, script, direction, features, lang)` | `ShapedRun` | Text or style change |
| **Paragraph layout** | `(run ids, available width, align)` | Line boxes | Reflow / resize |
| **Segmentation** | `text` | UAX #14 break positions, UAX #29 clusters | Nothing — bounded LRU |
| **Glyph raster** | `(face, px_size, gid, subpixel_bucket)` | Atlas rect | DPI change, LRU eviction |

Static labels — the majority of any interface — hit all four and cost nothing per frame beyond copying a cached instance slice.

**The segmentation cache is keyed on text alone**, which is what makes it the one that saves a resize. Break positions and grapheme clusters do not depend on the width being tried, but wrapping asks for them once per *candidate line* and again on every relayout — so dragging a window recomputed the same UAX #14 and #29 answers hundreds of times a second. Profiling a gallery resize put uniseg at **54% of the frame**; memoising these two pure functions took a resize frame from 17.6 ms to 7.3 ms, and 1.3 ms once line breaking was memoised as well. Bounded LRU, because the keys are arbitrary user text.

#### 5.7.5 Rasterisation and the atlas

Grayscale coverage bitmaps at exact device pixel size, as established in §5.8 — sharper and cheaper than SDF for UI text at known sizes. Three horizontal subpixel buckets. The `R8Unorm` glyph atlas with skyline packing and LRU eviction is unchanged.

**Colour emoji route to the RGBA8 image atlas instead.** freetype rasterises `CBDT`/`sbix`/`COLRv0` glyphs as colour bitmaps, which do not belong in an R8 coverage texture. The display-list `flags.x` kind is set to `2` (image) rather than `1` (glyph), so a colour emoji is an atlas-textured quad and needs no shader change at all — the existing two-texture bind group (§5.8) already accommodates it. `COLRv1` (gradient-capable) is out of scope.

#### 5.7.6 Verified behaviour

Each claim below was executed against the installed stack, not inferred from documentation:

| Capability | Evidence |
|---|---|
| GPOS kerning applied | `"AVA Wa To"` measured 10548 units shaped, 11289 with `kern` disabled — 6.6% tighter |
| Ligature substitution | `"fi film"` → 5 glyphs from 7 characters |
| HarfBuzz ↔ freetype gid agreement | Both return 36 for `'A'`; freetype rasterised gid 36 to a 23×22 bitmap, 213 ink pixels |
| Script itemisation with direction | `"Hello مرحبا 你好 हिन्दी!"` → `Latn`/LTR, `Arab`/RTL, `Hani`/LTR, `Deva`/LTR |
| Bidi reordering | `"The title is مرحبا today"` reorders the Arabic run for display |
| UAX #14 line breaking | `"can't"` kept intact; break offered after `dog-` |
| UAX #29 grapheme clusters | 13 code points → 6 clusters; `👩‍👩‍👧` and `🇯🇵` each one cluster |
| Coverage query | DejaVu Sans covers `A` and `ا`, not `你` or `🙂` |

#### 5.7.8 Icons

**M3's icon set is a variable icon font**, which is the single most useful fact
about it: an icon is a *glyph*, so icons need no rendering path of their own.
They flow through `FontDB`, the freetype rasteriser, the glyph atlas, and the
`GLYPH` instance kind unchanged — an icon costs **no extra draw call**.

Material Symbols exposes four axes; the bundle keeps two:

| Axis | Range | Kept | Why |
|---|---|---|---|
| `FILL` | 0–1 | ✅ | Load-bearing, not decorative — M3 uses it for the selected/unselected transition on navigation items and toggles |
| `wght` | 100–700 | ✅ | Pairs icon stroke weight with typography |
| `GRAD` | −50–200 | pinned | Fine-tuning |
| `opsz` | 20–48 | pinned | Fine-tuning |

**The bundle is a subset.** The full outlined variable font is **10.6 MB** for
~4,275 icons. Subsetting with `fontTools` to a curated 218-icon core set —
covering every component in the M3 catalogue — and pinning `GRAD`/`opsz` yields
**102 KB**, a 102× reduction. An icon outside the set raises a `KeyError`
naming the problem rather than silently rendering `.notdef`.

**Axis coordinates are part of the atlas key.** A filled and an unfilled icon
are the same glyph id at the same size, and would otherwise collide.

Two facts worth recording, both found by measurement:

- **`freetype-py`'s `set_var_design_coords` takes plain design values, not
  16.16 fixed point.** Passing scaled values silently clamps every axis to its
  maximum, which presents as "the axis does nothing" rather than as an error.
- **Material Symbols embeds no licence name record.** Its terms — Apache-2.0,
  unlike the OFL text faces — come from the repository `LICENSE`, vendored
  alongside it. The licence test therefore asserts per font rather than
  assuming one licence across the bundle.

The `Icon` widget takes its name from `text:`, so binding expressions work on
it: `text: "{{ 'star' if saved.get() else 'star_border' }}"` switches the icon
with state exactly the way a label does.

#### 5.7.7 Scope tiers

Revised upward from the previous revision, which deferred all shaping past v1. With the stack proven, the honest boundary is now much further out.

| Tier | Coverage | Status |
|---|---|---|
| **1** | Full OpenType shaping — ligatures, GPOS kerning, mark attachment, contextual forms. Grapheme clusters, UAX #14 breaking, font fallback. | ✅ **shipped, M4** |
| **2** | RTL and mixed-direction *rendering*. Itemisation resolves direction per run and orders runs visually; **glyph coverage for Arabic and Hebrew is absent from the bundled fonts**, so this is structurally present but not yet demonstrable without a system font. | partial, M4 |
| **3** | RTL *editing* — caret movement, affinity at direction boundaries, selection spanning runs. Genuinely hard UI work, independent of any dependency. | v1.1 |
| **4** | Vertical CJK, ruby annotation, `COLRv1` gradient emoji, variable-font axes. | post-1.0 |

The tier the release supports is stated in user-facing documentation. Tier 3 is called out separately because it is the one place where people assume that installing a bidi library finished the job: reordering glyphs is the easy half; a caret that moves sensibly through `"The title is مرحبا today"` is the hard half.

### 5.8 GPU pipeline — `render/`, `render/shaders/ui.wgsl`

One pipeline. One render pass. One instanced draw call per frame.

**Geometry.** A 4-vertex unit quad in a static vertex buffer, `triangle_strip`. Per-instance data arrives as a second vertex buffer with `step_mode="instance"`, chosen over a storage buffer for maximum backend portability.

**Colour resolution happens in the fragment stage, not the vertex stage.** The palette is a storage buffer, and storage-buffer visibility in the vertex stage is not guaranteed across backends (it is zero in some compatibility profiles). Resolving per-fragment costs nothing measurable and removes the portability risk entirely.

**Bind group 0** (bound once per frame):

| Binding | Resource |
|---|---|
| 0 | `uniform Globals { projection: mat4x4<f32>, viewport: vec2f, dpr: f32, _pad: f32 }` |
| 1 | `storage<read> palette: array<vec4<f32>>` — MD3 tokens (§5.6) |
| 2 | `texture_2d<f32>` — glyph atlas, R8Unorm |
| 3 | `texture_2d<f32>` — image atlas, RGBA8UnormSrgb |
| 4 | `sampler` — linear, clamp-to-edge |

**Signed distance field core.** A rounded box with independent corner radii:

```wgsl
fn sd_rounded_box(p: vec2<f32>, half: vec2<f32>, r: vec4<f32>) -> f32 {
    var rr: vec2<f32> = select(r.wz, r.xy, p.y < 0.0);   // top pair vs bottom pair
    let radius: f32   = select(rr.y, rr.x, p.x < 0.0);   // left vs right
    let q = abs(p) - half + radius;
    return min(max(q.x, q.y), 0.0) + length(max(q, vec2<f32>(0.0))) - radius;
}
```

**Analytic antialiasing.** Because the fragment shader has a true distance field, the coverage of an edge is available exactly — no MSAA, no post-process, no resolve target, and it is correct at any radius:

```wgsl
let d  = sd_rounded_box(local, half_size, in.radii);
let aa = fwidth(d);
var alpha = 1.0 - smoothstep(-aa, aa, d);
```

**Clipping in the shader, not the scissor rect.** Scissor state changes force the draw call to split, which would forfeit the central design constraint. Instead every instance carries its ancestor clip rect and radii, and coverage is multiplied by a second SDF evaluation:

```wgsl
let dc = sd_rounded_box(frag_pos - clip_center, clip_half, in.clip_radii);
alpha *= 1.0 - smoothstep(-fwidth(dc), fwidth(dc), dc);
```

This yields correctly antialiased **rounded** clipping — which scissor rects cannot express at all — while preserving one draw call.

**Borders** are a second SDF evaluation inset by `border_width`. The ring is the *difference* of the two coverages, so fill and border occupy disjoint regions and can simply be summed — they never double-composite, which a naive over-blend would do at every rounded corner.

**Shadows are a separate instance** (`kind = 3`) emitted *before* the box they sit behind, rather than a second pass inside the box's own fragment. This keeps the shader branch flat and lets a shadow be positioned, blurred, and clipped independently. The Gaussian is approximated by `smoothstep` across the blur radius over the offset distance field.

**`flags.z` and `flags.w` carry palette token indices** for fill and border, with `0xFFFFFFFF` meaning "use the literal colour in the instance". This is what makes a theme switch a single buffer upload while still allowing authored hex colours.

**Buffer strategy.** A ring of three instance buffers, rotated per frame so the CPU never writes a buffer the GPU may still be reading. Buffers grow by doubling and never shrink within a session. Upload is a single `queue.write_buffer` of a contiguous numpy slice.

### 5.9 Events and hit testing — `runtime/events.py`

Events arrive from `rendercanvas` callbacks and are pushed onto a queue drained once per frame (§6), so a burst of mouse-move events coalesces rather than triggering redundant work.

**Hit testing walks the Element tree in reverse painter order** and returns the topmost hit path, respecting ancestor clip rects. A naive full-tree recursion that visits every node — as in the prior draft — both ignores z-order and cannot express "the panel above intercepted this click".

The path is **the target followed by its ancestors**, not everything under the cursor. An occluded sibling that also contains the point is absent from it and receives nothing, which is the whole point of respecting paint order.

#### 5.8.1 Resize: every frame is drawn, and why

**During a resize, rendercanvas draws and presents once per compositor
configure, synchronously** — "during a resize, the `glfw.poll_events()`
function blocks, so our event-loop is on pause … we can use these to draw, to
get a smoother experience" (`rendercanvas/glfw.py`), via
`_draw_and_present(force_sync=True)`, which bypasses its own `max_fps`
throttle. Measured on KDE Plasma Wayland: **250 genuinely new sizes a second**.

The obvious response is to throttle — draw the latest size and skip the rest.
**That was tried, shipped, and reverted, and the reason is worth keeping.** A
Wayland client is expected to commit a buffer in response to a configure.
Declining a frame means not committing, which leaves the compositor waiting
before it offers the next size. The throttle did not merely fail to help; it
was the cause of the choppiness it was meant to fix:

| | redraws/s | gap between drawn frames | worst gap |
|---|---|---|---|
| throttled, vsync on | 12 | 86 ms | 1.1 s |
| throttled, vsync off | 12 | 66 ms | 0.7 s |
| unthrottled, vsync on | 99 | 0.04 ms | 7.9 s |
| unthrottled, vsync off | **466** | **0.04 ms** | none |

The inter-frame gap collapses by three orders of magnitude the moment
declining stops. So `draw_frame` presents every frame it is asked for, and
`vsync` is the only lever: with it on, this path still produces multi-second
stalls under a fast drag; with it off, a live resize runs at several hundred
redraws a second with none.

**`Settings.vsync` therefore defaults to False**, which is not the conventional
choice for an interface and is a deliberate trade. A window that lurches around
for seconds while being dragged is a worse defect than tearing during an
animation, and the usual argument for vsync — that an unsynchronised loop burns
the GPU — does not apply here: an idle pyCopper application renders no frames at
all (§5.10), so there is no loop to burn anything. Set it True on a platform
where the resize path behaves and tearing matters more.

**What remains, and where it lives.** With every frame drawn, a live resize on
KDE Plasma runs at several hundred redraws a second with no stall, and the
window still trails the pointer slightly. That residue is measured rather than
assumed. A resize frame is ~1.94 ms, split roughly half to pyCopper and half to
the platform:

| stage | median | share |
|---|---|---|
| layout | 0.34 ms | 27% |
| paint | 0.58 ms | 32% |
| upload | 0.01 ms | 1% |
| acquire (`get_current_texture`) | 0.48 ms | 33% |
| submit | 0.10 ms | 7% |

pyCopper's half is not waste: during a resize about half the element tree is
still spliced from its paint cache, no element is left spuriously dirty, and
the ones that rebuild are exactly those whose width changed.

**`acquire` is the swapchain rebuild**, and that was worth testing rather than
assuming — splitting it by whether the size actually changed gives a **12×
difference**: 0.476 ms median across 2346 rebuild frames against 0.039 ms
across 24 that reused the swapchain. wgpu reconfigures the surface whenever the
size differs, so during a drag it tears down and recreates the
`VkSwapchainKHR` on every pixel.

Amortising that would cut ~23% from the frame, which at ~385 configures a
second is roughly a halving of the queueing component of the lag. It cannot be
done from here. wgpu decides to reconfigure by comparing the canvas's physical
size against the configured one, and that size arrives from GLFW through
rendercanvas; pyCopper supplies only a draw callback and has no seam at which
to hold a stale swapchain. Rounding the swapchain up to a coarse multiple *is*
possible on Wayland in principle — commit an oversized buffer and declare a
smaller `xdg_surface.set_window_geometry`, which is how client-side shadows
work — but GLFW owns the `xdg_surface`, and neither rendercanvas nor wgpu
exposes window geometry or `wp_viewporter` cropping. `set_scissor_rect` does
not substitute: the swapchain image *is* the window's buffer, so an oversized
one is displayed oversized. This is an upstream limitation, recorded here with
the numbers that would support raising it.

**X11 is not the way out, and that was tested rather than assumed.** GLFW can
be pointed at its X11 backend with a `PLATFORM` init hint, and under a Wayland
session that runs through XWayland. The obvious hope is that X11's lack of a
configure/commit handshake — the constraint that made the throttle backfire —
would help. It does the opposite. The same drag:

| | Wayland | X11 via XWayland |
|---|---|---|
| redrawn at a new size | **425/s** | 151/s |
| frame median | 1.94 ms | 0.18 ms |
| gap mid-drag median | 0.04 ms | 0.34 ms |
| surface errors | none | continuous |

The 0.18 ms frame is not speed: wgpu could not obtain a usable surface texture
and returned a dummy for runs of 5, 12 and 25 frames at a time, logging
`SuccessSuboptimal` throughout. Only 151 frames a second produced a visible
update. It would also *look* worse — wgpu notes that on Linux a suboptimal
surface is "blitted to the window leaving either part of the texture invisible,
or making part of the window black/transparent". No `platform` setting is
exposed, because its only non-default value is strictly worse.

**The diagnosis took four wrong turns**, each from reasoning past the data
rather than measuring the next thing: blaming the frame cost (it was 2 ms),
blaming vsync alone (throttled-and-vsync-off was still 12/s), concluding the
compositor's present was an immovable ceiling (it was 0.04 ms unthrottled),
and only then instrumenting the throttle itself — which showed declines
clustering within 16 ms of a present and then 85 ms of total silence, the
signature of a stalled handshake rather than a busy GPU. The lesson worth
carrying: a *gap between* our frames is not evidence about what happens inside
them, and "the platform is slow" is the hypothesis to test last, not first.

### 5.8.2 Shutdown

`Engine.close()` releases the GPU objects in the order the surface requires —
context, then the atlas texture and pipeline buffers, then the device — and
`run()` calls it in a `finally`. Not left to the garbage collector: rendercanvas
terminates GLFW from a class attribute's `__del__` *specifically* so it happens
late, because "the release of the surface should happen before the termination
of glfw" or the process segfaults (citing pygfx/pygfx#642). An `Engine` reached
from a module-level `App` — how every example here is written — outlives even
that, so closing the window destroyed the native window and left a live wgpu
surface pointing at it.

### 5.11 The accessibility tree — `runtime/accessibility.py`

`App.accessibility_tree()` snapshots what the interface *means*: roles, names,
descriptions, values, states and bounds, derived from the element tree on
demand. Built when asked rather than maintained, because nothing consumes it
per frame and a tree rebuilt on request cannot go stale.

**The bridge is optional and lives in `accesskit_bridge.py`.** AccessKit owns
the per-platform half — AT-SPI over D-Bus on Linux, UIA on Windows,
NSAccessibility on macOS — so pyCopper does not. It is a native wheel, so it is
an extra (`pip install 'pycopper[a11y]'`) and an application opts in with
`App.bind_accessibility`. Without one bound, nothing reaches a screen reader.
Today's build serves AT-SPI; `available()` returns a *sentence* rather than a
bool, because "not available" with no reason is the least useful thing an
accessibility feature can say.

**Verified against the live accessibility bus**, not just unit-tested. With
`org.a11y.Status.ScreenReaderEnabled` set true, the gallery appears in the
AT-SPI registry and its window object reports `Name: 'pyCopper gallery'` with
its content beneath. Three things only that exercise could have found:

- **AccessKit stays dormant while nothing is listening.** With no screen reader
  the adapter never registers, which is `update_if_active` doing its job and is
  why a per-frame push costs nothing.
- **The tree's root must be a `WINDOW` carrying the title.** Handing AccessKit
  our own root — a `Column`, which converts to `GROUP` — left AT-SPI listing
  the application as `python3.14`, the process name, for want of anything
  better. The bridge now wraps the view in a titled window node.
- **The adapter must be shut down deterministically.** AccessKit runs a D-Bus
  task that calls back into Python, and left alive at interpreter shutdown it
  panics — "The Python interpreter is not initialized", from pyo3's GIL
  handling. Exactly the shape of the wgpu surface outliving its window (§5.8.2).
  `AccessKitBridge.close()` drops it and `App.run` calls it in a `finally`; a
  test suite that leaked one took the whole run down at exit, which is how this
  was found.

**Actions cross a thread boundary.** A reader activating a button calls back
from AccessKit's D-Bus task, and pyCopper's signals are thread-affine — acting
there raises `ThreadAffinityError`, the guardrail working. Requests are queued
and `App.update` drains them on the engine thread. A bridge that could only
*read* would be half a feature: announcing a button nobody can press is not
access.

The tree is worth its keep with or without a bridge: it is what the bridge is
handed, and it lets a test ask for "the button named Confirm" instead of for a
rectangle.

**Roles are sourced where M3 states one**, which is rarely: "The role is
'textbox'", the "role of 'progressbar'", a list is a "List box" so its items
are options, a navigation item's "role is 'tab'", and a navigation container's
"role is not announced". Everything else is the conventional ARIA role and is
marked as convention, so a reader can tell a quotation from a judgement. A test
asserts that every `WidgetKind` is either mapped or explicitly silenced, so a
new widget cannot quietly default to "group" — the role that says nothing.

Three rules the tree enforces, each of which is a bug it prevents:

- **A view file's `name:` is never announced.** It is a developer handle;
  "sw_primary" read aloud is worse than silence. It travels as `key` so tests
  can still find a node by it.
- **An icon name is never announced.** For `Icon`, `IconButton`, `Fab` and
  `NavItem`, `text:` holds a Material Symbols glyph name — a navigation item
  announced itself as "home" rather than "Home" until a test caught it. The
  label comes from `supporting_text:`, and an icon-only control without one
  reports *no* name, which is a real gap in the view rather than something to
  paper over.
- **Silent nodes do not bury their children.** A `Spacer` disappears and a
  navigation container's items are lifted into its place, so a reader never
  walks through a level that says only "group".

### 5.9.1 Editable text — `text/editing.py`, `widgets/textfield.py`

`TextField` is the only widget that *owns* state rather than reading it, which
is why the split runs where it does. **`text/editing.py` holds every rule and
knows nothing about pixels**: what a backspace removes, where a word ends, when
two keystrokes are one undo step. All of it is testable without a window, a
font, or a GPU, and a test that had to open a canvas to check Ctrl-Backspace is
a test nobody runs.

An `EditState` is frozen — text, anchor, focus — so an operation returns a new
one and **the undo stack is a list of states, not a list of inverse
operations**. At the sizes a field holds that is cheaper as well as simpler: no
operation needs an inverse, and no inverse can be subtly wrong. Anchor and
focus rather than start and length, so shift-arrow knows which end to move and
a backwards selection is representable instead of normalised away.

Every offset sits on a **grapheme cluster** boundary, reusing the segmenter
selection already went through. Backspace removes an accented character rather
than its accent. Word boundaries are the whitespace rule `selection.word_at`
uses, not UAX #29 — asserted equal to it in a test, because double-clicking a
word and then Ctrl-Backspacing it taking different amounts of text would be a
genuinely baffling bug.

Typing coalesces into one undo step, broken by a caret move, a replaced
selection, or a different kind of edit. A bound `value:` changing from the
application clears the history instead of recording a step: that text did not
come from the user, so offering to undo back to what they typed would restore
something the application has already moved past.

The widget half is the parts that need pixels. Its vertical layout is the
sourced M3 figures tiling the container exactly — 8dp padding, a 16dp floated
label line, a 24dp input line, 8dp padding, summing to the specified 56dp — and
a test asserts the sum so that changing one figure cannot silently decentre the
input. The label animates between `body-large` and `body-small` off one
animation value, so it cannot be caught half-floated in size and settled in
position. A field is one line and scrolls sideways to follow the caret, and
back rather than leaving empty space when text is deleted.

Two things it does not do. The **outlined** variant cannot notch its border,
because the shader draws no notch: the floating label gets a `surface`-coloured
patch behind it instead, which is wrong if the field sits on a tinted
container, and is stated at the call site rather than hidden. And the caret
**stops blinking under `reduce_motion`** rather than blinking on — the setting
makes timed transitions arrive at once everywhere else, and the equivalent for
something that never arrives is to stop it moving.

### 5.9.2 Hit rects are not paint rects

A control may accept clicks in an area larger than the one it draws. Two style
properties say so: `hit_padding` grows each edge, and `min_hit_size` states a
minimum square, which is how M3 writes the rule it actually cares about — "at
least 48×48dp" stays correct when the control's size changes, where 15dp of
hand-computed padding does not. Neither affects layout or paint: the control
keeps its size, its neighbours keep their positions, and the display list is
byte-identical.

Three consequences, each of which had to be handled rather than assumed away:

- **A hit rect can leave its parent.** The old walk returned early from any
  element that did not contain the point, which is correct only while a child
  cannot reach past its parent's edge — precisely the edges an enlarged target
  exists to cover. Each element therefore caches `_hit_overflow`, the furthest
  any descendant's hit rect can reach beyond its own, and descends into that
  wider region while still *accepting* only within its exact rect.

  That cache only ever has to be an **upper bound**. Too large costs a little
  wasted recursion and can never produce a wrong answer, which is what makes it
  safe to grow the value up the ancestor chain and never shrink it — instead of
  tracking invalidation for a property that changes about as often as a view
  file is edited. Recomputing the union per pointer move would put an O(n) walk
  on the most frequent event there is.

  The reach is therefore **pushed up at layout time by the few elements that
  ask for a target**, rather than pulled down by every element polling its
  children. An element with neither property does two attribute loads and
  stops. The first version did poll, and read the properties off the pydantic
  spec inside `hit_test`; measured against the gallery that cost +17% on a
  layout pass and +54% on a hit test. The version that ships costs +3% and +8%
  — a hit test is ~7µs against a 16ms frame, and it is stated here because
  "some overhead" is not a number.

- **A widget that clips what it paints must clip what it hits.** `ScrollView`,
  `Carousel`, `CarouselItem` and `SegmentedButton` set `CLIPS_CHILDREN`, so a
  control scrolled just past the edge cannot take a click it has no way to show
  a response to.

- **Enlarged targets can overlap where the drawn controls do not.** M3 asks for
  8dp between targets and nothing here can enforce it. The tie breaks the same
  way overlapping paint does: reverse sibling order, so the one on top wins.

The entire drain runs inside one signal `batch()`, so a handler writing several signals triggers dependent work once rather than once per write.

Dispatch follows a **capture → target → bubble** path over that hit path, with `Event.stop_propagation()`. Beyond raw clicks the system provides:

- **Pointer capture** — a widget may capture the pointer on press so drags continue outside its bounds.
- **Enter/leave** — computed by diffing the current hit path against the previous one.
- **Focus tree** — a tab-order traversal derived from document order, with `Tab`/`Shift-Tab` and focus-visible state.
- **Text input** — GLFW `char` callbacks for committed text, delivered as `EventType.TEXT` to the focused element. IME preedit is a known gap (§13).

**Modifier names are normalised on arrival.** `rendercanvas` reports GLFW's spellings — `"Control"`, `"Shift"`, `"Alt"`, `"Meta"` — and matching a raw string against one spelling is how Shift+Tab back-traversal and `Text`'s Ctrl+A both came to be dead in a running window while their tests passed: the tests posted `"shift"` and `"ctrl"`, which GLFW never sends. `modifiers_of()` folds every spelling to one vocabulary and `is_accelerator()` answers "is the platform's shortcut key held" without branching on platform. Both bugs were found while wiring the text field, and the tests for it deliberately use GLFW's spellings.

Handlers named in YAML (`on_click: submit_form`) resolve against a registry the application populates by decorator:

```python
@app.handler
def submit_form(event: PointerEvent) -> None: ...
```

Resolution happens at load time, so a handler named in YAML but absent in Python is a startup error.

### 5.10 Engine and the frame loop — `runtime/engine.py`

**The prior plan's hand-rolled loop is removed.** `rendercanvas` already owns a scheduler that does precisely what that loop attempted, and running `glfw.poll_events()` alongside it double-pumps the event queue.

Concretely, `rendercanvas` supplies:

| Prior plan | rendercanvas equivalent |
|---|---|
| `while not canvas.is_closed()` | `loop.run()` from `rendercanvas.asyncio` |
| `glfw.poll_events()` | Handled internally by the canvas group |
| `self._is_dirty = True` | `canvas.request_draw()` |
| `await asyncio.sleep(1/60 - elapsed)` | `update_mode="ondemand"`, `max_fps=60` |
| Idle redraw suppression | `min_fps=0` — genuinely zero frames when idle |

The engine's job is consequently much smaller: own the four trees, install the draw callback, drain the event queue, and run the frame pipeline.

```python
canvas = RenderCanvas(
    title="pyCopper",
    size=(1024, 768),
    update_mode="ondemand",  # draw only when requested
    min_fps=0,  # true idle: no frames at all
    max_fps=60,
)
adapter = wgpu.gpu.request_adapter_sync(power_preference="high-performance")
device = adapter.request_device_sync()
canvas.request_draw(engine.draw_frame)
loop.run()
```

`power_preference` is `"high-performance"`, not `"low-power"`: on hybrid-GPU laptops `"low-power"` selects the integrated GPU, which is the correct default for a compositor but the wrong one for a framework that must handle full-window resizes at 60fps. It is exposed as configuration.

`wayland_decorations` chooses who draws the window frame. `"auto"` leaves it to GLFW, which prefers libdecor — client-side decorations drawn by a plugin — and is the default because it is the only thing that works everywhere: GNOME does not offer server-side decorations for xdg-shell, so disabling libdecor there leaves a window with no title bar and no close button. `"server"` disables libdecor before GLFW initialises, which on a compositor that does offer server-side decorations (KDE Plasma) avoids the libdecor path entirely, including the `Failed to load plugin 'libdecor-gtk.so'` fallback a missing GTK produces. It must be set before `glfw.init()`, and rendercanvas defers that until the first canvas is constructed, so `_make_canvas` is the last moment it can take effect.

It is **not** a performance setting, and measurement says so: the same drag under both modes gave a 4.30 ms and a 4.17 ms median frame, the same p95 band, and one over-budget frame each. libdecor was never the cost.

### 5.11 Hot reload — `runtime/hotreload.py`

`watchfiles` runs in a background thread. On a change to a watched YAML file it posts a reload request to the engine thread — it never touches the trees itself.

The engine then: re-reads and re-validates the Spec tree; **on validation failure, logs the Pydantic error with file and line and keeps the previous tree running** (a syntax error mid-edit must not kill the app); on success, reconciles (§5.3), preserving all runtime state for nodes whose `id` and widget kind are unchanged; and requests a draw.

Handler *bindings* are re-resolved, but handler *bodies* are not reloaded — that is Python-level reload and is out of scope (§1.2).

### 5.11.1 Focus rings and keyboard traversal

M3 requires a focused element to render a **2dp high-visibility stroke around
its boundary**. On a pointer-and-keyboard framework this is not cosmetic:
keyboard traversal is a primary input path, so an invisible focus state is a
defect (§1.2.1).

Three decisions:

- **Drawn once, centrally.** `ElementMixin.paint()` emits the ring after the
  element's own subtree, so it lands on top and every focusable widget gets a
  correct ring without opting in.
- **`focus_visible` is separate from `focused`.** A mouse click focuses
  *silently*; Tab shows the ring. This is standard desktop behaviour, and
  without the split every click leaves a ring behind, which reads as a bug.
- **The ring follows the control's shape**, via `Element.effective_radii`.
  `style.corner_radius` is not enough: several components compute their own
  radius at paint time — a Button is a pill at height/2 when the view sets
  none — so a ring keyed on the raw style draws a rectangle around a circle.

`Tab` and `Shift+Tab` traverse the focus order, and `Escape` clears focus. Tab
is handled before delivery to the focused element, so it works from the
nothing-focused state an application starts in. Focus order is document order,
and `FOCUSABLE_KINDS` makes every interactive control reachable whether or not
the view file wired a handler.

### 5.1.0 Node identity: `id`, `name`, and `classes`

Three separate concerns that were once a single overloaded `id` field:

| Field | Written by | Cardinality | Purpose |
|---|---|---|---|
| `id` | **the loader** | unique | Positional identity, derived from the node's path (`/0/1/`). Never authored. |
| `name` | the designer, optionally | unique | The handle: `find()`, `anchor:`, a selection `value:`, and the reconciliation key. |
| `classes` | the designer, optionally | **repeatable** | Categories for the theme engine and stylesheet to select on. |

**Why the split.** Requiring an `id` on every node meant naming things nobody
referenced — the gallery declared 58 ids and referenced none of them by
`anchor:` or `find()`. Meanwhile a *category* (several buttons that should
style alike) and an *identity* (this specific button) are genuinely different
needs, and one field cannot be both: a repeatable value cannot be a lookup key.

**The reconciliation rule follows from it, in one line:**

> A **named** node has stable identity and keeps its state across a reorder.
> An **unnamed** node has positional identity: its state stays with the *slot*,
> not with the content that moved.

That second half is the honest cost, and it is precise — an unnamed node is not
rebuilt on a reorder, it is reused in place and handed the other node's spec.
For a `Divider` that is meaningless; for anything holding focus, scroll, or
text, it is exactly why you give it a name.

Positional ids use `/` as a separator, which the `name` pattern forbids, so an
authored name and a generated id can never collide.

**Uniqueness is enforced at load**, not merely documented. A duplicate name does
not fail loudly on its own — `find()` just returns whichever node was reached
first — so the loader walks the validated tree and rejects a collision with both
positional ids in the message (`duplicate name 'badge' (used at /6/1/ and
/8/8/)`). The gallery had exactly this bug: a `Badge` widget and an unrelated
`Container` both named `badge`. At load it is a one-line fix; at runtime it
looks like a widget mysteriously ignoring its handler.

`classes` was added before it had a consumer, deliberately: retrofitting a
selector target into a shipped view language costs far more than reserving one.
The stylesheet (§5.17.1) is that consumer, and it landed without changing the
identity model at all — which is the argument for having reserved it.

### 5.1.1 View composition — `spec/include.py`

A `source:` key pulls a subtree in from another file:

```yaml
# parts/confirm.yaml
params: [title, open]
id: dialog
widget: Card
open: "{{ open }}"
children:
  - {id: heading, widget: Text, text: "{{ title }}"}

# call site
overlays:
  - id: delete_confirm
    source: parts/confirm.yaml
    with: {title: "Delete file?", open: "{{ show.get() }}"}
```

**Resolution happens on the decoded YAML, before validation.** A resolved
include is therefore indistinguishable from inline content: the spec models,
reconciliation, and the renderer never learn a file boundary existed. That is
why this feature needed no changes below the loader.

**Parameters are the interface; there is no merge.** A `source:` node accepts
only `id:` and `with:`. The alternative — letting the call site override keys —
needs precedence rules nobody can predict ("does a local `style:` replace the
fragment's or merge into it?"). The cost is real and worth stating: *everything*
a call site needs to control must be a declared parameter, including `open:`.
In exchange there is nothing to memorise.

**Parameters substitute textually**, which is what makes them compose with
bindings. Passing `title: "Delete?"` leaves static text; passing
`title: "{{ user.get() }}"` leaves a live template evaluated against the
application context. No separate reactive path exists or is needed.

Four things this had to get right:

- **Name namespacing.** Positional ids are inherently scoped by path, but
  `name`s are not: including a fragment twice would give two nodes the same
  name, and `find()` would return the wrong one. Names inside a fragment are
  qualified with the call-site name (`delete_confirm.heading`), and `.` is
  reserved in the name pattern for exactly this.
- **Hot reload watches the whole graph.** `App.sources` records every file
  touched, and **a change to any of them reloads the entry view** — not the
  file that changed, which is not a view on its own and would fail on its
  `params:` block.
- **Error provenance.** Failures report the include chain
  (`a.yaml -> b.yaml -> a.yaml`), not just a line number.
- **Cycles and path confinement.** A cycle is refused with its chain, and an
  include may not escape the view directory — view files are untrusted input.

Deliberately absent: conditional includes, computed paths, and loops. This is
where a view format starts becoming a programming language. In particular
**includes are not the way to repeat a row a hundred times** — that needs a
`repeat:` construct with stable identity for reconciliation, which is a
separate and larger decision.

### 5.13 The overlay layer — `runtime/overlay.py`

Six M3 components — Dialog, Menu, Tooltip, Snackbar, and both Sheet types —
share one requirement the four-tree model cannot otherwise express: they render
**above** everything, positioned independently of whatever opened them and
clipped by nothing.

**Overlays are declared in a top-level `overlays:` list, not hoisted out of the
tree.** A dialog is not laid out or clipped by the button that opened it, so
declaring it as that button's child would be a lie about the geometry — and
would leave the parent's Flex reserving space for something that floats.

```yaml
root: { ... }
overlays:
  - name: confirm
    widget: Dialog
    open: "{{ show.get() }}"          # templated, like text: and value:
    style: { modal: true, scrim: true }
```

The host runs its own layout and paint pass after the main tree's, and is
consulted **first** during hit testing because it is on top.

| Concern | Behaviour |
|---|---|
| Placement | `center`, `anchor` (to another element's `name`), or an edge |
| Anchoring | placed below the anchor, **flipping above** when it would overflow |
| Scrim | M3's 32% `scrim` token, sized to the window |
| Modality | a modal swallows every press outside itself; the tree beneath is unreachable |
| Dismissal | Escape closes the topmost overlay *before* clearing focus; a press outside closes a modal |
| Z-order | declaration order — a later overlay's scrim dims an earlier one |

Dismissals are tracked separately from the `open:` binding and reconciled each
frame, so an overlay closed by clicking outside can still be reopened by its
signal — otherwise the dismissal would outlive the state change.

#### 5.13.2 Fading, and why rendered ≠ visible

Overlays enter and leave on M3's own pairs: **Emphasized decelerate over 400ms
to enter, Emphasized accelerate over 200ms to exit**, straight from the
suggested-pairs table. A thing arrives gently and departs briskly, which is why
the two are not symmetric.

Fading out forces a distinction the host did not previously need:

| Set | Contains | Used by |
|---|---|---|
| `visible()` | overlays the application wants up | hit testing, modality, dismissal |
| `rendered()` | those, **plus any still fading out** | layout and paint |

A dismissed modal must stop swallowing clicks the instant it is dismissed, not
200ms later, so it leaves `visible()` immediately while remaining in
`rendered()` until its exit finishes. Clicking through a half-faded dialog is
the deliberate consequence.

**Opacity is applied to the display-list slice**, not threaded through the
paint context. The host records the index before painting an overlay and scales
`fill.a` and `border.a` across everything emitted after it — one vectorised
numpy pass, in one place, instead of obliging every emit site to multiply. It
also catches a **cached subtree**, which is spliced in at full alpha and which
a context flag would have missed entirely, and the **scrim**, which the host
draws itself rather than the widget.

#### 5.13.1 Placement a component does not have to declare

`placement:` defaults to `center` for every widget, which is wrong for most of
the components that actually float: a widget named `BottomSheet` should not
have to be told it belongs at the bottom. Two rules fix that without taking
control away from the view, resolved in `ElementMixin.resolved_placement`:

1. An explicit `placement:` always wins. "Explicit" is decided by pydantic's
   `model_fields_set`, so a written `center` is distinguishable from the
   field's default of `center` — which a plain equality check cannot do.
2. Failing that, an `anchor:` implies `placement: anchor`. Naming an anchor and
   then centring the overlay is never what was meant.
3. Failing that, the component's own `DEFAULT_PLACEMENT`: `bottom` for
   Snackbar and BottomSheet, `right` for SideSheet, `center` for Dialog.

**Docked versus floating.** A sheet sits flush against its window edge; a
snackbar, menu or tooltip keeps an 8dp margin from it. This is not decoration:
M3 rounds only a sheet's *inner* corners, and a gap outside a square corner
leaves it hanging in mid-air. Components set `DOCKED` and the host drops the
margin for them.

Two bugs this work surfaced, both pre-existing and both now fixed:

- **A single-child container silently dropped extra children.** `Padding`-based
  widgets lay out `children[0]` only, but paint walks all of them — so a Card
  with two children rendered them unpositioned on top of each other with no
  error. Adding a second child now raises, naming the fix.
- **A Column sized only on `width` filled vertically.** `main_size` was chosen
  from `style.width` regardless of axis, and a Column's main axis is its
  *height*. An anchored menu stretched to the bottom of the window.

And one surfaced by building the components on top of it:

- **M3 minimum widths violated their constraints.** A Menu clamped itself to
  its 112dp minimum regardless of the space offered, so a Menu laid out in
  50dp raised outright (`layout/node.py` asserts that a node returns a size its
  constraints permit) while a Dialog was silently clipped. An M3 minimum is an
  aspiration that yields to a narrower parent, not a floor — see
  `_clamped_width`.

### 5.12 Material Design 3 components — `widgets/material.py`, `navigation.py`, `overlays.py`

Components translated from their M3 specs. Dimensions are M3's own dp
figures used directly, since layout runs in logical units and dp maps 1:1 (§7).

| Widget | M3 spec | Notes |
|---|---|---|
| `Card` | 12dp radius, 16dp padding | `elevated` / `filled` / `outlined` |
| `Divider` | 1dp, `outline_variant` | `full_bleed` / `inset` |
| `Checkbox` | 18dp box, 2dp radius | checkmark glyph when selected |
| `Radio` | 20dp outer, 10dp dot | a circle is a rounded box at radius = side/2 |
| `Switch` | 52×32dp track, 16/24dp thumb | thumb grows when selected |
| `Chip` | 32dp high, 8dp radius, 18dp icon | filter variant shows a leading checkmark |
| `IconButton` | 40dp container, 24dp icon | `standard` / `filled` / `filled_tonal` / `outlined` |
| `Fab` | 56dp standard, 40 small, 96 large | `primary_container`, elevation level 3 |
| `Badge` | 6dp dot, or 16dp-high pill | `value:` carries the count |

**Wave 2** added navigation and structure in `widgets/navigation.py`:

| Widget | M3 spec | Notes |
|---|---|---|
| `NavigationRail` + `NavItem` | 80dp wide, 56×32dp indicator | icon FILL 0→1 marks the active destination |
| `NavigationDrawer` | 240–360dp, 56dp items, 28dp pill | shares `NavItem` |
| `TopAppBar` | 64dp small, 112dp medium, 152dp large | medium and large collapse on scroll (§5.19) |
| `Tabs` + `Tab` | 48dp, 3dp indicator | primary rounds the indicator, secondary is flat |
| `SegmentedButton` + `Segment` | 40dp, 20dp outer corners | checkmark on the active segment |
| `ListItem` | 56 / 72 / 88dp | headline plus bindable `supporting_text` |
| `LinearProgress` | 4dp, rounded ends | determinate only — indeterminate is an animation |
| `CircularProgress` | 4dp ring, clockwise from 12 o'clock | determinate only; needs the arc primitive (§5.15). The 48dp default diameter is **not** sourced — that page's size table is an image |
| `Carousel` + `CarouselItem` | 28dp items, 16dp leading/trailing, 8dp gaps | three layouts; items resize and snap (§5.16) |

**Wave 3** added the six components the overlay layer (§5.13) exists for, in
`widgets/overlays.py`. They contribute M3 *anatomy* only — container token,
shape, and the padding between the parts — because the host already owns
placement, scrim, modality and dismissal. A Dialog does not know it is centred.

| Widget | M3 spec | Notes |
|---|---|---|
| `Dialog` | 28dp radius, 24dp padding, 280–560dp wide, height **dynamic** | headline + `supporting_text` + actions as its child |
| `Menu` | 4dp radius, 112–280dp wide, 8dp vertical padding | `surface_container` |
| `MenuItem` | 48dp high, 12dp side padding | denser than `ListItem`'s 56/72/88dp; `supporting_text` is the trailing shortcut |
| `Tooltip` | 24dp high, 8dp side padding | `inverse_surface` / `inverse_on_surface` |
| `Snackbar` | 48dp growing to 64dp | `inverse_surface`; action label in `inverse_primary` |
| `BottomSheet` | 28dp **top** corners, max 640dp wide | optional 32×4dp drag handle, 22dp above and below |
| `SideSheet` | 16dp leading corners, max 400dp, 24dp padding | corners follow the docked edge |

Three notes on fidelity, since the point of citing a spec is that the citation
can be checked:

- **Snackbar's page carries no measurement table.** Its 4dp radius is inferred
  from the extra-small step of the shape scale and its 600dp width cap is a
  desktop-reasonable choice. Both are marked as inferred in the source; every
  other number in the module is quoted.
- **Tooltip's table is internally inconsistent** — a 24dp container with "8dp
  padding" cannot also fit a body-small label, so the 8dp is read as the
  horizontal inset and the vertical one is whatever centres the label.
- **The menu implemented is M3's *baseline* menu, not the vertical menu** M3
  now leads with. The newer variant's shape morphing and vibrant colour need a
  theme engine, which does not exist yet.

**Bottom-anchored navigation is deliberately absent.** M3's Navigation Bar and
Bottom App Bar are mobile patterns (§1.2.1); the rail and drawer are their
desktop counterparts. A `BottomSheet` is not an exception to this: it is a
desktop-legitimate surface for secondary content, and its drag handle is drawn
as an affordance but is **not draggable**, since dragging needs the motion
system pyCopper does not have. It is off by default for that reason.

Four of these share one shape — a container of items where exactly one is
selected — modelled once as `_SelectionContainer`: the container carries
`value:`, the id of the selected child; during layout it calls `set_selected`
on each child; the item renders its own selected appearance. That is also where
the icon **FILL** axis finally earns its place, since it is exactly what M3 uses
to distinguish a selected destination.

Two sizing decisions worth recording:

- **A segmented group shrinks to its content by default**, and divides the
  width equally among segments only when the view gives it one. Filling by
  default left the outline running on past the last segment.
- **The group's outline is drawn once around the whole container**, with a 1dp
  divider between each pair — not per segment, which would double every
  internal edge.

`Button` gained the same treatment: M3 describes its five variants as **one
component in five configurations**, so they are one widget with a `variant`,
not five widget kinds.

**Selection is a binding, not style.** `Checkbox`, `Radio`, `Switch`, and the
filter `Chip` read a new `value:` field on the spec, templated exactly like
`text:` — so `value: "{{ checked.get() }}"` tracks a signal. `Element.checked`
and `Element.number` parse it. Style describes appearance; what a control *is*
is application state.

**Colour defaults live with the widget.** `style.color` is now `None` by
default, meaning "use this component's M3 default for its variant". An explicit
token always wins. Without this a global default would silently override every
variant's correct content colour.

**State layers are shared.** `_emit_state_layer` applies M3's 8% hover / 10%
focus / 10% press overlay above the container and below the content, so every
interactive component behaves identically rather than each reimplementing it.

Two gaps these components inherit, both stated rather than approximated:

- **No motion.** A switch thumb jumps between positions; M3 animates it.

M3's 48dp minimum touch target is deliberately **not** implemented: it is a
finger-precision rule and pyCopper is pointer-only (§1.2.1).

**One correction made later:** `LinearProgress` drew its track in
`surface_variant`, which the spec does not say. M3 gives progress indicators a
single colour-role table covering both variants — active `primary`, track
`secondary container` — so the track was corrected when `CircularProgress`
arrived and the two had to agree. A test now asserts they use the same token.

### 5.14 Scrolling — `widgets/scroll.py`

**Scrolling is a paint-time translation, not a relayout.** That single decision
shapes everything else here. Content is measured once against *unbounded* space
on the scroll axis and keeps the offsets layout gave it; moving the scroll
position only changes the origin its subtree is painted from
(`ElementMixin.child_origin`). A wheel notch costs one paint of the viewport,
not a layout pass over every row.

That matters more here than in a typical toolkit. Python, not the GPU, is this
framework's bottleneck (§12) — relaying out a thousand-row list per wheel event
would be plainly visible, while re-emitting its instances is the operation the
display list is already built for.

```yaml
- name: list
  widget: ScrollView
  style: {height: 300, width: expand}   # bounded on the scroll axis
  children:
    - widget: Column
      children: [ ... ]
```

| Concern | Behaviour |
|---|---|
| Extent | content measured unbounded along the axis, bounded across it, so text still wraps |
| Bounds | `max_scroll = content + padding − viewport`; the offset is clamped every layout |
| Clipping | in-shader, via the paint context — never scissor, which would break the single draw call (§5.8) |
| Hit testing | threads the same translated origin, so the pointer follows the pixels |
| Wheel | goes to whatever is under the **pointer**, not to the focused element |
| Chaining | propagation stops only if the content actually moved |
| State | the offset lives in `WidgetState.scroll`, so it survives hot reload like focus does |

Three decisions worth recording:

- **An unbounded scroll axis raises.** A `ScrollView` that shrink-wrapped would
  be exactly as tall as the content it is meant to be scrolling, and would
  simply never scroll. The error names the fix, matching what `Flex` already
  does for flexible children in unbounded space.
- **`scroll_by` returns whether it moved**, and the wheel handler stops
  propagation only then. At the end of an inner list the wheel keeps
  travelling outwards — swallowing it unconditionally would trap the pointer
  in a fully-scrolled pane.
- **The offset is re-clamped during layout**, not only when set. A hot reload
  that deletes rows would otherwise leave the view scrolled past the new end.

**The scrollbar is not Material.** M3 specifies none — the catalogue only notes
that a scrolling menu "shows a persistent scrollbar" — so its 4dp thickness and
32dp minimum thumb are pyCopper's own, and it is drawn as an indicator rather
than a drag target, since dragging it needs pointer capture wiring that is not
built. Visible scrollbars are a desktop convention with no mobile analogue
(§1.2), which is why one exists at all.

### 5.15 Arc rendering — `KIND_ARC`

The SDF shader drew only rounded boxes, so anything circular and *stroked* —
a circular progress indicator, a ring gauge — could not be expressed at all.
Arcs are a fifth fragment branch rather than tessellated geometry, which keeps
the single instanced draw call intact (§5.8): an arc is one more instance of
the same unit quad, and costs no extra draw call.

The distance field is the standard two-case arc:

```wgsl
fn sd_arc(p: vec2<f32>, sc: vec2<f32>, ra: f32, rb: f32) -> f32 {
    let q = vec2<f32>(abs(p.x), p.y);
    if (sc.y * q.x > sc.x * q.y) { return length(q - sc * ra) - rb; }  // past the cap
    return abs(length(q) - ra) - rb;                                   // on the ring
}
```

Inside the wedge the nearest point is on the circle, so the distance is to the
ring; outside it the nearest point is the cap centre, so the distance is to
that point. **That second case is what gives round caps for free** — M3's
rounded progress ends need no extra geometry, and antialiasing stays analytic
because the result is still a true distance field.

Three details that are not obvious:

- **A full turn takes a separate `sd_ring` branch.** At a half-aperture of π
  the wedge test degenerates and leaves a visible seam at the join. A test
  samples the ring's brightness at every degree and asserts it is uniform.
- **Angles are clockwise from 12 o'clock**, because M3 says circular
  indicators "animate from the top of the track, clockwise by default". Screen
  y grows downward, so the arc is rotated to put its midpoint on −Y before the
  +Y-symmetric field is evaluated.
- **`params` is reinterpreted per kind.** For an arc the vec4 that normally
  carries `(border_w, blur, shadow_dx, shadow_dy)` carries
  `(thickness, start, sweep, _)`. No struct growth: the instance stays 144
  bytes, and every field stays vec4-aligned.

### 5.17 Motion — `motion/`

One property governs the whole design: **an idle pyCopper application renders
zero frames** (§5.10). Animation is the one thing that legitimately needs
continuous frames, so it has to ask for them precisely while it is running and
stop the instant it is not. `Ticker.active` is that signal, and `App.paint`
requests the next frame only while it is true. A finished animation is dropped
from the ticker, so the application falls silent on its own.

**Easing and duration are M3's, not invented.** Six named curves and sixteen
duration tokens, quoted from the spec. The `emphasized` curve is the
interesting one: it is not a cubic bezier at all but a **two-segment path**,
and M3's own CSS row says "N/A (use Standard as a fallback)" because
`cubic-bezier()` cannot express two segments. pyCopper is not bound by CSS's
limits, so it implements the real curve — a test asserts the join lands on
0.4 at x=0.166666, exactly where the spec's path data puts it.

Solving a curve means finding the Bezier parameter `t` for a given x before
reading y. Newton-Raphson does that, with a bisection fallback where the slope
is flat — which it is at both ends of every M3 curve, so the fallback is not
hypothetical.

| Concern | Behaviour |
|---|---|
| Interruption | **retarget, not restart** — a new animation begins from the current value, so a switch toggled twice glides rather than snapping back |
| Frame delta | measured **once per frame** and handed to the ticker, never sampled by whoever asks — otherwise layout and paint disagree about where a moving thing is |
| Stalls | a delta over 100 ms is clamped: a debugger pause would otherwise teleport every animation to its end |
| Repeat | wraps instead of finishing, for indeterminate indicators |
| Accessibility | `Settings.reduce_motion` makes animations *arrive immediately* rather than not exist — widget code needs no branch, so it cannot forget the case |
| Invalidation | `animated()` marks **paint**, never layout. It runs every frame |

`ElementMixin.animated(key, target)` is the whole widget-facing API: call it
where the value is needed and use what comes back. The first call settles on
its target at once — there is nothing to animate *from* — and a later call with
a different target retargets. Animations live in element state, so a hot reload
does not restart a transition mid-flight.

**Time is injectable.** `App.clock` defaults to `time.perf_counter` and can be
replaced. This is not a testing nicety: without it an animated golden image
advances by however long the test setup happened to take, and the transition is
over before the frame is captured. That is exactly what happened while building
the motion baseline.

Four things are wired to it. Overlays fade in and out (§5.13.2) and **state
layers cross-fade** — hover, focus and press opacities animate instead of
blinking, which reaches every component at once because `_emit_state_layer` is
shared. It reached every component *except* `Button`, which turned out to have
its own private copy of the state-layer code; unifying it was the fix, and is a
small argument for shared helpers over duplicated ones.

The state-layer duration (100ms, standard) is **not sourced**: M3 gives none,
and its "begin and end on screen" pair is about elements arriving rather than
an in-place emphasis change. 100ms is chosen because a hover response slower
than that reads as lag.

**Indicators travel.** A tab indicator belongs to the `Tabs` container rather
than to a tab, which is what lets it move *between* them — both its x and its
width animate, so it stretches on the way and arrives the right length for a
label-width destination. It costs paint only: the tabs themselves have not
moved. A navigation rail's pill grows outward from a circle around the icon,
and a segment widens around its arriving checkmark (layout, like the chip).

**The icon FILL axis is animated in steps, not continuously.** FILL is a
variable-font axis and the axis coordinates are part of the glyph atlas key
(§5.7); the atlas has no per-entry eviction, and resets wholesale when full.
A continuously animated FILL would therefore pack a fresh rasterisation every
frame and force repeated full resets, re-rasterising every glyph in the
application. Six steps still reads as a transition and bounds the entries per
icon — a test asserts the atlas does not grow across a nav transition.

**Every selection control transitions**, on the one line M3 states outright:
"Selection controls have a short duration of 200ms with Standard easing". A
checkbox cross-fades its outline for its filled container and fades the
checkmark in; a radio cross-fades its ring colour and grows the dot out of the
centre; a filter chip grows its checkmark into the space being made for it.

Two things fall out of the architecture there. **Palette tokens cannot be
interpolated** — they are resolved in the shader against the palette buffer, so
a colour cross-fade is two boxes at complementary alpha, not one lerp. And a
**filter chip's transition changes its width**, so it is the second widget to
use `invalidates="layout"`; the label and every sibling in the row move with
it, which is the behaviour M3 describes.

The `Switch` thumb slides and grows on
timing M3 states directly — "Selection controls have a short duration of 200ms
with Standard easing" — and **indeterminate progress** now works: omitting
`value:` selects it, which is also how M3 describes an indicator changing from
indeterminate to determinate as information arrives. Both use `linear` easing
for the looping animations, because an eased loop decelerates into the wrap and
jumps back to full speed, reading as a stutter once a second. Eased curves are
for transitions that end.

#### 5.16.2 Parallax, and `paint_foreground`

M3: "carousel items move at a different speed than their content". An item lays
its children out wider than itself by the pan range on each side, then pans them
by where the item sits across the strip — one way at the leading edge, the other
at the trailing one, not at all in the middle. It is a paint-time translation,
the same mechanism as scrolling, so it costs nothing beyond the repaint the
movement already required, and being a pure function of position it stays exact
under a drag. The 12% pan range is **not sourced**; M3 describes the effect
without giving a figure.

Building it exposed a gap. `paint_self` runs *before* an element's children,
which is right for a background and wrong for anything that must sit over
content — and M3 carousel items hold images, so the item's label was drawn
underneath the very content it captions and was invisible in every realistic
use. `ElementMixin.paint_foreground` runs after the children and **inside the
cached range**, so a clean subtree still splices correctly.

### 5.17.1 Stylesheets — `spec/stylesheet.py`

`classes` was reserved as a selector target when node identity was split
(§5.1.0); this is its consumer.

**Resolved once, at load.** A rule's properties are folded into the node's own
`StyleSpec` before the element tree is built, so layout and paint read `style`
exactly as they always have and a stylesheet costs **nothing per frame**. The
alternative — resolving selectors during paint — would put a matching pass on
the hot path in the one language where that is least affordable (§12).

The merge rests on Pydantic's `model_fields_set`, the same mechanism that lets
a component distinguish an authored `placement:` from the field default
(§5.13.1). Only fields a rule actually wrote are applied. Without it every rule
would impose the full set of `StyleSpec` defaults, the last match would erase
every earlier one, and a node's own `style:` could never win — its unset fields
would be indistinguishable from deliberate values.

That composition matters in both directions: a stylesheet value lands on the
**explicit** side of `model_fields_set`, so a sheet can override a component's
own default (`CircularProgress`'s 4dp thickness, `BottomSheet`'s bottom
placement). A stylesheet is authorial intent, not a fallback.

| Precedence | |
|---|---|
| 1 | rules with no selector (a baseline) |
| 2 | `widget:` |
| 3 | `classes:` — more classes beat fewer |
| 4 | `name:` |
| 5 | the node's own inline `style:` |

Ties go to document order, later winning. Selectors are **structured**, not
CSS-like strings: `#name` would need quoting in every rule, since YAML reads
`#` as a comment, and a structured rule validates with a field path like the
rest of the format.

**Restyling a running application is a reload**, and reload reconciles rather
than replaces (§5.3) — so changing a stylesheet keeps focus, scroll, and text.

**Sheets share across files.** A `styles:` entry of the form `- source:`
splices in the rules that file names, and a sheet may import another. Rules
land in place, so ordering reads as written and an import placed after a local
rule overrides it.

This is a separate expansion path from widget includes, not a reuse of
`_expand`. A stylesheet is a **list** and a fragment is a **mapping**, so
including one where the other belongs reports that directly instead of failing
later as a validation error about a file that was perfectly valid. The guards
are the same, because a stylesheet reached from a view file is exactly as
untrusted as the view: confinement to the view directory, cycle detection, a
depth limit, and `yaml.safe_load` only.

Every sheet is registered in `sources`, so hot reload watches the whole graph —
editing a theme restyles a running application, and because reload reconciles,
it keeps focus, scroll and text. `examples/gallery` uses one.

### 5.17.2 Drag gestures

Two affordances were drawn long before they did anything: a scrollbar thumb and
a bottom sheet's handle. Both now work, and both needed the same missing piece.

**Claiming a drag.** Capture went to whatever was topmost under the press, which
is wrong for a control drawn *over* something else — a scrollbar thumb sits on
top of the rows, so the press lands on a row and the thumb would move for one
frame and then stop. `PointerEvent.capture()` lets an element handling the press
on the way up take the drag instead. `Event.current` was added alongside it: the
element whose handler is running, which during bubble is an ancestor of the
target, and which a shared handler needs in order to know which element it is
running for.

**A widget cannot reach the overlay host**, and giving it one would let any
element reach into the runtime. A sheet that wants to close raises
`dismiss_requested` on its own state and the host reads it once a frame.

| | |
|---|---|
| Thumb grab | its painted rect plus 6dp of slop — **pointer** precision, not M3's finger target (§1.2.1), since 4dp is unhittable with a mouse |
| Thumb travel | maps to scroll travel, so content keeps pace with the pointer |
| Cost | paint only, like every other scroll |
| Sheet handle | 48dp band, quoted from M3 |
| Sheet drag | downwards only — it is docked, and lifting it exposes the square corners the edge hides |
| Release | past 35% of its height dismisses (**not sourced**), short of it settles back on Emphasized decelerate |
| Click | closes, which is M3's required single-pointer alternative |

A drag tracks the pointer **exactly** — only the release is animated. Easing a
drag would make the sheet lag behind the thing moving it.

### 5.17.3 Elevation

This one began as "implement the tonal half of elevation" and turned into a
correction, because the spec says: **"Surface tint color is deprecated. Use
elevation level tokens (0–5) instead."** The tonal-overlay mechanism these docs
had recorded as the missing half is the mechanism M3 has withdrawn. Tonal
separation now comes from the `surface` and `surface_container_*` roles, which
the spec says are "not tied to elevation" — so choosing a container role and
setting a level are independent decisions, and the widget catalogue was already
doing the first correctly.

What was actually missing was the level system itself. Six levels, each with a
dp height, both quoted:

| Level | 0 | 1 | 2 | 3 | 4 | 5 |
|---|---|---|---|---|---|---|
| Height | 0dp | 1dp | 3dp | 6dp | 8dp | 12dp |

Levels 0–3 are resting states; "+4 and +5 are reserved for user-interacted
states such as hover and dragged". Each component carries the resting level
M3's own table assigns it, and `elevation:` in a view overrides that. Hovering
or focusing something **already raised** lifts it one level — the spec says
"usually", which is not licence to give every flat button a shadow under the
pointer.

**Shadows are derived, not chosen.** Three widgets had hand-tuned blur values,
so a dialog and a FAB at the same M3 level did not look like they were at the
same height. `elevation_shadow` now maps a level to one shadow for everything.
The dp→blur mapping is **not sourced** — the spec describes the relationship
("larger, softer shadows express more distance") in prose and images without
figures — so the constants are anchored on the value the Card already used at
level 1, letting the family scale out from a shape that had been reviewed
rather than from an invention.

**One bug worth recording.** The paint sites resolved their level as
`self.elevation or FALLBACK`, and `or` cannot tell an explicit `0` from unset —
so `elevation: 0` silently re-raised the component it was meant to flatten. It
survived the first round of tests because those asserted on the property, which
was correct, rather than on what was painted. Fixing it exposed the real
structure: Card and Button rest at level 1 only in their `elevated` variant, so
the resting level is a **property**, not a class constant.

### 5.17.4 Context menus

Two pieces, and both belong in the runtime rather than in a widget.

**A `CONTEXT_MENU` event**, synthesised from a secondary press the way `CLICK`
is synthesised from a press and release. A view writes `on_context_menu:` and
never learns which integer the backend calls "right" — which is worth hiding,
because the numbering is **one-based** (1 primary, 2 secondary, 3 middle),
checked against `rendercanvas/glfw.py` rather than assumed. Guessing it wrong
fails silently: nothing would ever fire.

The secondary button also no longer presses, focuses or clicks. It used to,
because `_dispatch_pointer` did not look at which button was down — so
right-clicking a button left it stuck in its pressed state, a bug that would
have appeared the first time anyone tried this feature.

**`placement: pointer`**, an overlay positioned at a *point* rather than
against an element. A context menu has no anchor element by definition. The
host records where the request happened and opens down and to the right of it,
flipping near an edge instead of clipping — the same rule anchoring already
uses — then clamps, so a menu taller than the window still starts on screen.

It dismisses on an outside press or Escape like any other transient surface.

### 5.17.5 Cursor shapes

The pointer shape is resolved from the element under it: the topmost one with
an opinion wins, falling back to the platform default. `cursor_at(x, y)` takes
a position rather than being a plain property, because some widgets want
different shapes in different regions — a scroll view is a resize cursor over
its thumb and has no opinion at all over its content.

Two details that are not obvious:

**It resolves from the *unfiltered* hit path.** A disabled control is removed
from the event path, correctly — it must receive nothing — but it still has to
show `not-allowed`. The cursor is feedback, not an event, so it reads the raw
path while dispatch reads the filtered one.

**The shape is pushed only when it changes.** The backend destroys and
recreates a native cursor object on every `set_cursor` call, so setting it each
frame would churn GLFW resources sixty times a second. `App` tracks the last
value; a test asserts three unchanged frames push nothing.

Names are the backend's own CSS-style vocabulary, validated at load so an
unknown one fails with a path instead of raising from inside a frame.

### 5.17.6 Text selection — `text/selection.py`

Selection needs two inverse questions answered: which character is under a
point, and which rectangles cover a character range. Both are derived from
`Paragraph` as it already existed, with **no change to the shaping structures
or the shape cache's key** — which matters, because that cache is on the text
hot path.

The obstacle was that a `ShapedRun` carries cluster indices into *its own* text
and no offset back to the paragraph. Adding one would have meant threading an
offset through itemisation, shaping, and the cache. It turned out to be
unnecessary: the runs of a line concatenate in order, so walking them while
accumulating `len(run.text)` recovers the paragraph offset exactly.

Offsets snap to **grapheme cluster** boundaries via the existing UAX #29
segmentation (§5.7), so an edge never lands inside a flag emoji or between a
base character and its combining mark — a test asserts the caret cannot reach
the interior of a combining sequence. Hit testing picks the **nearest edge**
rather than the containing glyph, which is what makes click-and-drag feel like
it tracks the pointer instead of lagging a character behind.

**Selectable text is focusable.** Key events go to the focused element, so
without that Ctrl+C reaches nothing at all — and being able to Tab to a block
of text and copy it is the accessible behaviour rather than an accident.

**The highlight is painted in `paint_self`**, before the glyphs. In
`paint_foreground` it would sit *over* the letters it is meant to be behind.

#### No system clipboard, deliberately

`rendercanvas` exposes no clipboard, and the only route to one is the backend's
private `canvas._window` handed to GLFW — platform-specific as well as private,
and it fails outright on Wayland without a real surface, which was checked
rather than assumed. Depending on that would be a contract that breaks on a
dependency upgrade.

Copying therefore fills an in-process clipboard, so copy-and-paste *within* an
application works, and `clipboard.install(...)` is the seam for an application
that wants the system one in three lines. A failing backend can never break a
frame: the in-process copy happens first and exceptions are swallowed.

#### Not implemented, and stated

Selection across widgets, and bidirectional selection. The second is risk R9:
the highlight is contiguous in character order, which is not what a caret
should do across a direction boundary. (Editable text was listed here until
`TextField` shipped -- see 5.9.1.) Double-click uses whitespace
delimiting rather than UAX #29 word segmentation — simple and predictable, and
labelled as such rather than presented as Unicode-correct.

### 5.17.7 Type-scale roles — `spec/typescale.py`

`text_style: title-large` resolves to `font_size` **once at load**, the same
decision the stylesheet makes (§5.17.1), so every widget downstream keeps
reading a plain float and a role costs nothing per frame. All fifteen roles
work out of the box; a view's `type_scale:` overrides them role by role, and a
scale can live in its own file and be shared.

**The sourcing is the interesting part**, and is recorded because it was not
straightforward. The spec page serves a JavaScript shell with **no body content
at all** — which is why the token table in `M3-References` scraped empty. That
was not a scraping mistake; the page has nothing to scrape. The figures come
instead from Google's autogenerated token source in the Material Web Components
repository (`tokens/versions/latest/sass/_md-sys-typescale.scss`, Material 3
version 34.0.21), converted from `rem` at 16px/rem.

Two independent checks make that trustworthy rather than merely convenient:

- it **agrees with all four values** the reference library corroborates on its
  own — headline-medium 28, title-large 22, title-small 14, label-medium 12;
- it **settles the one contradiction** in the library, where `headline-large`
  appeared as both 32sp and 36sp in the same file. It is 32.

Tests pin both, so a future change to the table that broke either would fail
rather than pass quietly.

**Size and weight are both applied.** A role resolves to `font_size` and
`font_weight`, and the bundled Roboto ships the Regular and Medium faces the
scale asks for, so `title-medium` is genuinely Medium rather than emboldened
Regular. The font database resolves an unavailable weight to the nearest within
the family, so a request for 700 renders as Medium instead of a smeared
Regular.

A weight is a **different face with different metrics**, which makes one rule
non-negotiable: a label's `measure_text` and its `paint_text` must pass the
same weight, or the box is sized for one face and drawn in another. Applying
this caught exactly that bug mid-change — a partial edit had left one widget
measuring at 400 and painting at 500 — and a test now walks the widget source
asserting every label call carries a weight.

Components take the weight their own M3 role specifies, where the reference
library documents one: a common button is `label-large`, quoted as "(14sp /
20dp line height, **medium weight**)"; nav labels are `label-medium`; tabs are
`title-small`. A segmented button reuses the tab's constants — only the tab's
role is sourced, and looking different from its sibling control would be worse
than following it.

**Tracking is applied too**, as `letter_spacing`. It is an absolute figure in
logical px — that is how the token source states it, and it is why a role's
tracking is only right at that role's size. Nine of the fifteen roles carry
one; the largest is half a pixel.

Letter spacing lands in exactly one place: `ShapedRun.advances_px(px, tracking)`.
Shaping stays size- and spacing-independent, so the shape cache is untouched
and one shaped run still serves every size and every spacing the same string is
drawn at. Everything downstream — a paragraph's width, the paint pen, caret
placement, selection rectangles — reads that one array rather than repeating
the arithmetic, because the same class of bug that a weight mismatch caused
would otherwise have three more places to appear.

Spacing is added per **grapheme cluster**, not per glyph: a ligature is one
glyph for several characters and a combining mark is several glyphs for one, and
spacing either apart from the inside would be wrong. It is added after the last
cluster on a line as well, as CSS `letter-spacing` is, which leaves centred text
off-centre by half a tracking value — a quarter-pixel at the scale's largest.
Trimming it would mean special-casing line ends in the measurement, the caret
and the pen independently, and those drifting apart is the worse bug.

Because three numbers now have to agree between a widget's measure and its
paint, a role travels as **one object**: `ButtonElement.LABEL_ROLE` is the
`TypeStyle` itself, and `measure_text`/`paint_text` take `float | TypeStyle`.
A role cannot half-arrive. The test for it uses the paragraph cache as a
mismatch detector — a label measured and painted with different metrics leaves
two entries where there should be one — and a deliberate mutation confirms it
fails when the tracking is dropped.

**Line height completes the scale.** A role's height replaces the font's own,
and the difference is split evenly above and below the glyphs -- CSS
half-leading. That distribution is the whole design: it means raising a line's
height does not move centred text. A button's label measures 20dp tall instead
of 17 and its baseline lands in exactly the same place, which is why applying
line height moved only three baselines out of a dozen. Text positioned from its
top does move, by half the difference.

Negative leading is allowed and occurs in the real scale -- Roboto wants 67px
at `display-large` where M3 asks for 64 -- so lines close up rather than glyphs
being cropped.

All four of a role's tokens are now applied. The `TypeStyle` a widget holds
carries every one of them, so the "cannot half-arrive" property scales with the
token set rather than degrading as it grows; the mismatch test compares the
whole metric tuple, and a positional `key[-1]` in it silently moved from
tracking to line height the moment the fourth token landed, which is why it now
indexes by name.

### 5.18 Disabled state

M3 states it outright: "Disabled: Container opacity 12% (0.12), Content opacity
38% (0.38)". Two details matter. It is a **replacement** with the `on_surface`
role, not a dimming of the control's own colours — which is why a disabled
filled button and a disabled outlined one look alike. And it is **state, not
style**: `disabled:` is a templated node field beside `value:` and `open:`, not
a `StyleSpec` property, because it changes what a control *is*.

**Inherited.** Disabling a container disables everything inside it, which is the
case people actually reach for. `effective_disabled` walks the parent chain;
nothing caches it, because a cached answer goes stale the moment a signal flips
an ancestor.

**Inert, and invisible to the keyboard.** A disabled element is removed from the
focus order as well as from the pointer path — leaving it Tab-reachable when the
mouse cannot touch it is the accessibility failure the state exists to prevent.
The hit path is **truncated, not filtered**: an enabled ancestor of a disabled
control still receives the event, so a disabled button inside a clickable card
does not swallow the card.

**Painting** reuses the display-list slice mechanism (§5.13.2): one vectorised
pass recolours everything the element drew. Container and content need different
opacities, and the split is made by geometry — a box covering the element's own
bounds is its container, anything else is content. Splitting on primitive *kind*
would have been simpler and wrong: a radio's dot and a switch's thumb are
content drawn as boxes, and at 12% they are all but invisible.

#### One thing found and deliberately not changed

A handler declared in a view is invoked in **both** the capture and bubble
phases, so a handler on an *ancestor* of the target runs twice for one event.
That looks like a bug and is not: an ancestor intercepting during capture is a
tested feature, and the view format registers one handler with no phase to
choose between them. Changing it would break a frozen 1.x API, so it is
documented in the view reference instead. `event.phase` distinguishes them.

Native widget behaviour (a scroll view consuming a wheel notch) *is* guarded to
the non-capture phases, because running it twice would double the scroll.

### 5.19 The collapsing app bar — scroll-linked motion

M3: "when scrolled, medium and large app bars can transform into small app
bars; they should remain small until the page is scrolled back to the top",
and "on scroll, the container changes color to surface container".

This is the one piece of motion in the framework that is **not driven by the
clock**. The bar's height is a direct function of a scroll offset, so it tracks
a drag exactly rather than chasing it, and the ticker is never involved. A view
links the two by name:

```yaml
- {name: bar,  widget: TopAppBar, style: {variant: large, collapses_with: body}}
- {name: body, widget: ScrollView, style: {height: expand}}
```

The bar registers as a **follower** of that view. Scrolling marks paint on the
view alone (§5.14), so anything whose *geometry* depends on the offset must be
told separately — `ScrollView.follow()` relayouts its followers when it moves.
The scrolled content itself is untouched and still travels at paint time.

#### The feedback loop, and where it had to be cut

The bar and the view size each other: collapsing the bar enlarges the viewport,
which shrinks `max_scroll`, which clamps the offset down, which un-collapses the
bar. Measured, the first implementation did not oscillate — it settled into a
**wrong** fixed point, a list back at its top with the bar stuck collapsed.

The instinct is to invalidate harder. That fails for a specific reason worth
recording: a `mark_needs_layout()` issued *during* a layout pass is cleared when
its ancestor finishes laying out, leaving the element permanently dirty and
never relaid out.

So the cycle is cut at its source instead. `ScrollView` measures its scrollable
extent against a viewport with its followers' collapse travel **added back**, so
`max_scroll` is identical whether the bar is expanded or collapsed. There is
then no loop to invalidate around, and a test asserts the extent does not vary
across a full collapse. The degenerate case — content only as tall as the
collapse frees — now scrolls exactly that far, collapses the bar, and stops.

### 5.16.1 The frozen surface

`pycopper.__all__` is the whole public API — 24 names — and is covered by
semantic versioning: adding to it is a minor release, removing or re-signing
anything in it is a major one. `tests/test_public_api.py` pins the list, so a
change to it is a decision rather than an accident.

Two things that audit surfaced:

- **The event classes were not exported.** Annotating a handler
  (`def save(event: PointerEvent)`) required importing from
  `pycopper.runtime.events`, i.e. from a private module. A surface that cannot
  type its own callbacks is not finished, so `Event`, `EventType`,
  `PointerEvent`, `KeyEvent`, and `WheelEvent` are public.
- **There was no `LICENSE` file**, despite `pyproject.toml` declaring MIT since
  M0. MIT requires the notice travel with the distribution, and the three
  bundled font licences needed the same guarantee — all four are now declared
  through `license-files` and verified present in the built wheel.

### 5.16 Carousel — `widgets/carousel.py`

M3 draws an explicit line through the carousel layouts, and it is the line
this implementation is built on:

- **uncontained** items "don't change size", and both free and snap scrolling
  suit it. So this scrolls by **pixels**, translating at paint time through
  `child_origin` exactly as a `ScrollView` does.
- **hero** and **multi_browse** items "automatically change size and snap into
  place to maintain the same layout". So these scroll by **item**, and an
  item's width comes from its position in the strip, not from its content.

That second mode is what makes a carousel a carousel rather than a horizontal
list, and it is why this is a widget rather than a styled `ScrollView`.

**It is also the deliberate exception to §5.14's rule.** A snapping carousel
*must* relayout to scroll, because which item sits on the leading keyline is
what decides every item's width — the two cannot be separated. That is
affordable precisely where the general rule is not: a carousel holds a handful
of items, while a `ScrollView` must assume a thousand rows. The two behaviours
live in one widget and each takes the mechanism that suits it.

Widths per layout, with the leftover going to the large item (M3 calls it
"Dynamic"):

| Layout | Slots |
|---|---|
| `multi_browse` | large, medium, small, then small |
| `hero` | large, small, then small |
| `uncontained` | each item's own `width:` |

**What is missing is the transition, not the layout.** M3 resizes items
continuously as they travel and snaps them home; here the snap is
instantaneous and the resize happens in one step. At rest the geometry is
exactly what M3 specifies — it is the movement between rest states that is
absent. The **medium item width
(112dp) is not sourced**: M3 calls it "dynamic" and gives no figure.

**The snap now travels** (§5.17). `position` is a continuous animated value
and every width and offset derives from it, so items resize *as they move*.

This is the single place in the framework where a transition invalidates
**layout** rather than paint. Item widths genuinely depend on position here, so
repainting alone would draw stale geometry — `animated(..., invalidates="layout")`
makes that cost explicit at the call site rather than hiding it. Measured, one
carousel layout per frame while travelling:

| Items | ms/frame | Share of a 16.7 ms budget |
|---|---|---|
| 6 | 0.20 | 1.2% |
| 100 | 0.79 | 4.8% |
| 300 | 2.24 | 13.4% |

Affordable at any sane carousel length — and precisely why `ScrollView`, which
must assume a thousand rows, may never do the same thing. The timing is M3's
"Standard | 300ms | Begin and end on screen" rather than the Emphasized/500ms
row on the same table: a snap is driven by a wheel notch and repeats as fast as
the user turns it, so half a second of emphasis would queue up behind itself.

One fix this surfaced: a `CarouselItem` label used `on_surface` whatever its
container, so it turned near-invisible the moment a view set a light
background. `paired_content_token` now follows M3's container/`on_` pairing —
`primary_container` implies `on_primary_container`. It is applied only where
the whole surface belongs to the widget; a component whose background is one
part of a larger anatomy keeps its variant's content token.

---

## 6. Frame Lifecycle

The authoritative sequence. Every step is skippable when nothing dirtied it.

```text
 0. Wake            rendercanvas scheduler fires (input, timer, or request_draw)
 1. Drain           pop OS + cross-thread event queue; coalesce motion
 2. Dispatch        hit-test -> capture/target/bubble -> handlers write Signals
 3. Notify          flush signal writes -> set needs_build/layout/paint flags
 4. Build           re-evaluate bindings on needs_build Elements; resolve styles
 5. Layout          from each dirty relayout boundary: constraints down, sizes up
 6. Paint           re-emit instances for needs_paint subtrees; splice cached rest
 7. Upload          palette (if theme dirty) | atlas (if new glyphs) | instances
 8. Encode          one render pass, one instanced draw of N instances
 9. Submit          device.queue.submit(); canvas presents
```

Idle costs zero frames. A hover highlight runs steps 0–4, 6–9 and skips layout entirely. A theme toggle runs 0, 3, 7 (palette write only), 8, 9 — no tree traversal at all.

---

## 7. Coordinate Systems and DPI

Three spaces, never mixed implicitly:

| Space | Unit | Used by |
|---|---|---|
| **Logical (DIP)** | Device-independent px | YAML authoring, layout, hit testing, all public API |
| **Physical** | Framebuffer px | Display list, atlas, shader, viewport |
| **Clip** | NDC, −1..1 | Vertex shader output only |

`scale = canvas.get_pixel_ratio()`. Conversion happens at exactly one place — the paint pass, when writing `rect` into the instance array. Layout never sees physical pixels; the shader never sees logical ones.

**Origin is top-left, Y grows downward**, matching every UI convention and both input APIs. The orthographic projection in `Globals` performs the Y flip into NDC, so no other code compensates.

On DPI change or monitor move, `scale` changes: the atlas is invalidated (glyphs were rasterised at the old scale), the display list is fully rebuilt, but **layout is untouched** because it operates in logical units.

---

## 8. Threading and Concurrency

**The engine thread owns everything mutable**: the wgpu device and surface, all four trees, all signals, the atlas. This is not a limitation to work around; it is what makes the invalidation model sound.

Application background work runs as `asyncio` tasks on the same loop that drives `rendercanvas`, so ordinary `async def` handlers need no marshalling. Work on genuine OS threads (blocking I/O, `anyio.to_thread`) must return to the engine thread before touching a signal:

```python
loop.call_soon_threadsafe(my_signal.set, value)
```

`Signal.set` asserts thread affinity in debug builds, converting a latent race into an immediate, located error.

Glyph rasterisation is synchronous in v1. It is a measured candidate for a worker thread (freetype releases the GIL for `FT_Render_Glyph`), deferred until profiling justifies the complexity.

---

## 9. Directory Structure

```text
pyCopper/
├── pyproject.toml               # hatchling; project metadata, deps, extras
├── ARCHITECTURE.md
├── README.md
├── src/
│   └── pycopper/
│       ├── __init__.py          # THE public API surface (§10)
│       ├── config.py            # pydantic-settings: PYCOPPER_* env overrides
│       ├── spec/
│       │   ├── loader.py        # yaml.safe_load + include resolution
│       │   ├── models.py        # Pydantic Spec tree
│       │   └── expressions.py   # {{ }} restricted AST — no eval
│       ├── runtime/
│       │   ├── engine.py        # frame pipeline, canvas/device ownership
│       │   ├── signals.py       # Signal / Computed / Effect, tracking scope
│       │   ├── events.py        # queue, hit test, capture/bubble, focus
│       │   └── hotreload.py     # watchfiles -> reconcile
│       ├── tree/
│       │   ├── element.py       # mutable runtime node
│       │   └── reconcile.py     # keyed diff, state preservation
│       ├── layout/
│       │   ├── constraints.py   # Constraints, Size, Offset, EdgeInsets
│       │   └── algorithms.py    # Box, Row, Column, Stack, Scroll, TextBox
│       ├── paint/
│       │   ├── display_list.py  # INSTANCE_DTYPE, painter-order walk, caching
│       │   └── commands.py      # box/glyph/image emitters
│       ├── render/
│       │   ├── pipeline.py      # bind groups, pipeline, render pass
│       │   ├── buffers.py       # ring buffer, growth, uploads
│       │   ├── atlas.py         # skyline packer, LRU, R8 + RGBA8 textures
│       │   └── shaders/
│       │       └── ui.wgsl      # the single universal primitive shader
│       ├── text/
│       │   ├── fontdb.py        # face registry, coverage index, fallback chain
│       │   ├── font.py          # freetype wrapper: rasterise gid -> coverage bitmap
│       │   ├── shaping.py       # uharfbuzz -> ShapedRun (numpy), shaped-run cache
│       │   ├── itemize.py       # bidi (UAX #9) + script runs (UAX #24)
│       │   ├── segment.py       # line breaks (UAX #14), graphemes (UAX #29)
│       │   └── layout.py        # line assembly, alignment, caret/selection geometry
│       ├── assets/
│       │   ├── __init__.py      # DEFAULT_FONT, MEDIUM_FONT, FALLBACK_CHAIN
│       │   └── fonts/           # BUNDLED fonts — required by golden tests (§11)
│       │       ├── Roboto-Regular.ttf   Roboto-Medium.ttf
│       │       ├── NotoSans-Regular.ttf # fallback tier
│       │       └── LICENSE-*.txt        # OFL 1.1, must ship with the fonts
│       ├── theme/
│       │   ├── tokens.py        # frozen TOKEN_ORDER (versioned!)
│       │   └── palette.py       # materialyoucolor -> float32 palette buffer
│       └── widgets/
│           ├── base.py          # primitives: container, row/column, stack, text, button, icon
│           ├── material.py      # M3 catalogue: card, checkbox, chip, fab, ...
│           ├── navigation.py    # rail, drawer, app bar, tabs, list item, progress
│           ├── overlays.py      # dialog, menu, tooltip, snackbar, sheets
│           └── scroll.py        # clipped viewport + wheel handling
├── examples/
│   ├── hello/            {app.py, view.yaml}
│   ├── counter/          # signals + handlers
│   └── gallery/          # every widget; doubles as the golden-image corpus
├── tests/
│   ├── test_layout.py           # pure, no GPU — the largest suite
│   ├── test_constraints.py
│   ├── test_signals.py          # dependency tracking, invalidation typing
│   ├── test_reconcile.py        # state preservation across reload
│   ├── test_spec_validation.py  # bad YAML -> good errors
│   ├── test_hit_testing.py
│   ├── test_palette.py
│   └── golden/
│       ├── conftest.py          # rendercanvas.offscreen fixture
│       └── baselines/*.png
└── docs/
```

**This is an installable package, not an application.** The prior root-level `core/` + `app.py` + `view.yaml` layout describes a program that happens to have a UI; `src/pycopper/` plus `examples/` describes a framework other people can depend on.

---

## 10. Public API Surface

Everything not re-exported from `pycopper/__init__.py` is private and may change without a major version bump. The v1 surface is deliberately small:

```python
from pycopper import App, Signal, Computed, Theme, run

theme = Theme(seed="#6750A4", dark=True)
app = App("view.yaml", theme=theme)

count = Signal(0)


@app.handler
def increment(event):
    count.set(count.get() + 1)


app.expose(count=count)  # names visible to {{ }} expressions
run(app)
```

Semantic versioning applies to this surface, to the YAML schema, and to `TOKEN_ORDER`. The YAML document carries a `version:` key so the loader can migrate or reject old documents explicitly.

---

## 11. Testing Strategy

The architecture was shaped partly by testability; this is the payoff.

| Layer | Approach | GPU? |
|---|---|---|
| Layout | Direct `Constraints` in, `Size` out. **Hypothesis** property tests over randomly generated trees (avg ~10 nodes, up to 49, depth 5) assert the invariant *a node's size depends only on its constraints and children* — by moving every node and re-laying out, then requiring identical sizes. Also: every layout result satisfies its constraints, layout is deterministic, and flex distribution sums exactly. | No |
| Signals | Assert exact invalidation sets: which Elements dirtied, and with which flag. Catches over-invalidation, which is silent but is the main performance risk. | No |
| Reconciliation | Reload a mutated Spec; assert scroll/focus/text state survived. | No |
| Spec validation | Malformed YAML corpus; assert error type, key path, and line number. | No |
| Hit testing | Synthetic trees with overlaps and clips; assert the hit path. | No |
| Intrinsic size | Lay every `WidgetKind` out with **no style at all** under loose constraints; assert a real size, with the legitimately-empty kinds listed individually alongside the reason. Every other suite hands its widgets an explicit size, so this is the only thing exercising the path. | No |
| Text pipeline | Shaping against the **bundled** font: assert glyph IDs, advances, cluster mapping. Fallback chain resolution. Break opportunities and grapheme counts against UAX test data. | No |
| Rendering | `rendercanvas.offscreen` → render → read texture → compare against a **committed baseline PNG**. Tolerance is 4/255 per channel with at most 0.2% of pixels allowed to exceed it — an exact match would be unmaintainable across drivers, anything looser stops catching real changes. `examples/gallery` is the corpus, plus an **unsized-widget** baseline that gives nothing a size and so catches a widget that draws nothing. | Yes |
| Shader | Covered indirectly by goldens. WGSL is kept small and branch-light for this reason. | Yes |

The overwhelming majority of the framework's logic is testable in CI with no GPU, on any runner. Golden tests run on a Linux runner with `lavapipe` (software Vulkan) for determinism, and are the only tests permitted to be platform-conditional.

**Every text test uses the bundled font, never a system font.** Shaping output, advances, and rasterised coverage all vary between font versions, so a test that resolves `"sans-serif"` through the OS produces different bytes on every machine and every CI image. This is the second architectural reason the default font is bundled (§5.7.2), and it is why system font discovery stays out of the golden path even after it ships.

---

## 12. Performance Budget

At 60fps the whole frame is **16.6ms**, and the realistic constraint is Python, not the GPU. Targets for a 1000-visible-element interface:

| Step | Budget | Strategy |
|---|---|---|
| Event dispatch | 0.5 ms | Coalesce motion; hit-test path, not full tree |
| Build (dirty only) | 1.0 ms | Fine-grained signals; typically <10 elements |
| Text (dirty only) | 1.5 ms | Three-level cache (§5.7.4); static labels cost zero |
| Layout (dirty only) | 2.0 ms | Relayout boundaries; typically a small subtree |
| Paint (dirty only) | 2.0 ms | Cached subtree instance slices, spliced |
| Upload | 1.0 ms | One contiguous `write_buffer` from numpy |
| Encode + submit | 0.5 ms | One pass, one draw |
| **Headroom** | **~8.1 ms** | |

Two rules follow directly and are non-negotiable in review:

1. **No per-widget Python in the steady state.** A frame in which nothing changed must execute zero tree traversals. The idle cost of a pyCopper app is a sleeping event loop.
2. **Display-list assembly is vectorised.** Instances are written into preallocated numpy slices. A per-widget Python loop appending to a list will not meet this budget and is the first thing to check when it is missed.
3. **No text is shaped twice.** HarfBuzz itself is fast C, but building buffers and marshalling results is Python, and shaping is the single most expensive text operation. A shaped-run cache miss on unchanged text is a bug, and is asserted against directly in tests.

A benchmark harness (`tests/bench/`) tracks steady-state idle cost, single-property invalidation cost, and full-rebuild cost, and is run per release.

### 12.2 Text measurements (M4)

Measured on the reference machine. The text budget from the table above is 1.5 ms:

| Path | Median | Verdict |
|---|---|---|
| Layout, warm cache | **0.001 ms** | ✅ |
| Cached subtree splice (static text) | **0.003 ms** | ✅ |
| Emit ~1000 glyphs, vectorised | **1.77 ms** | ⚠️ worst case only |
| Emit ~1000 glyphs, scalar (before optimisation) | 4.26 ms | ❌ replaced |
| Layout, cold cache (43 chars, wrapped) | **1.92 ms** | ⚠️ one-time per string; was 4.89 before §5.7.1 |
| Wrap, 351 chars on one 3840 px line | **12.8 ms** | ✅ was 107.9; the cost no longer scales with line width |

Two things this establishes:

1. **The M2 lesson repeats exactly.** The first `emit` wrote instances one glyph at a time and cost 4.26 ms per 1000 glyphs — over budget, for the same reason scalar box emission was. Collecting into arrays and writing whole columns (`DisplayList.add_glyphs`) cut it to 1.77 ms. §12 rule 2 is not specific to boxes.
2. **Steady state is essentially free.** A frame whose text has not changed costs 0.003 ms, because the display-list subtree cache turns it into a `memcpy`. The 1.77 ms figure is the pathological case of a thousand glyphs *all changing at once*, which no realistic interface does.

The remaining per-glyph cost is `Paragraph.placements()` allocating one object per glyph. Returning arrays instead would remove it; not done, because the cache makes it invisible in practice.

### 11.1 Regenerating golden baselines

```bash
PYCOPPER_REGEN_GOLDEN=1 .venv/bin/python -m pytest tests/golden -m gpu
```

**A regeneration run fails on purpose whenever it writes a file.** A baseline
that silently rewrote itself to match the current output would assert nothing;
forcing a failure means the new image has to be looked at and committed
deliberately. On a mismatch the harness writes `actual` and `diff` images to
`tests/golden/failures/` (gitignored) so the change can be seen rather than
guessed at.

### 12.1 First measurements (M2)

Measured on the reference machine, 1000 instances, integrated GPU over Vulkan:

| Path | Median | vs 2 ms paint budget |
|---|---|---|
| Scalar emit — per-widget Python loop | **3.27 ms** | ❌ **over budget** |
| Vectorised emit — numpy bulk write | **0.020 ms** | ✅ 165× faster |
| Cached subtree splice — memcpy | **0.002 ms** | ✅ 1451× faster |
| Full frame, 1000 instances, one draw call | 0.47 ms | includes upload + readback |
| Full frame, 0 instances (clear only) | 0.30 ms | — |

**R1 is confirmed, and the mitigations work.** Two conclusions follow, and neither is now a matter of opinion:

1. **The GPU is nearly free; Python is the whole cost.** Drawing 1000 instances costs roughly **0.17 ms** of GPU time (0.47 minus the 0.30 ms clear baseline). The Python that *assembles* those same instances costs **3.27 ms** — about **19× more than the work it feeds**. Every future performance decision should start from this ratio.
2. **The naive path genuinely does not fit.** Scalar per-widget emission exhausts the entire 2 ms paint budget at roughly **610 instances** — well below a realistic interface. This is precisely why §12 rule 2 is written as a hard rule rather than advice, and why display-list assembly is specified as numpy from the start.

The subtree cache is the strongest lever available: reusing a clean subtree's instance slice is a `memcpy` at 0.002 ms, three orders of magnitude cheaper than rebuilding it. That validates the four-tree model's cached `instances` field (§4) as a performance necessity, not a convenience.

---

## 13. Risks and Open Questions

| # | Risk | Severity | Mitigation / status |
|---|---|---|---|
| R1 | Python frame budget insufficient at high element counts | High | Retained mode + typed invalidation + numpy paint are all aimed here. Benchmark early, at M2, not at M6. |
| R2 | ~~Text scope creep~~ | **Closed** | **Delivered in M4.** Shaping, fallback, segmentation, itemisation, atlas, and paragraph layout all ship and are tested. Residual work is now RTL caret semantics (R9) alone; the quadratic wrap in §5.7.1 is closed. |
| R3 | `wgpu-native` backend variance across Vulkan/Metal/DX12 | Medium | Keep WGSL conservative; golden tests per platform; no optional GPU features. |
| R4 | Single draw call broken by a future feature | Medium | Stated as a design constraint (§1.3). Clipping already solved analytically; transforms and blend modes are the next pressure points. |
| R5 | IME / CJK text *input* unsupported | Medium | **Open.** GLFW preedit support is limited; likely needs platform code or a rendercanvas contribution. Note this is input only — CJK *rendering* is covered by Tier 1. |
| R9 | RTL caret/selection semantics (Tier 3) | Medium | Deferred to v1.1 and stated as such. Reordering is solved; bidirectional caret affinity is independent UI work. |
| R10 | ~~Bundled font licensing and size~~ | **Closed** | **Resolved.** Roboto and Noto Sans are both **SIL OFL 1.1**, compatible with MIT, with licence texts redistributed alongside them (§5.7.2). Note Roboto was *relicensed*: builds predating its move to `ofl/` in `google/fonts` — including the v2.137 copy some distributions still ship — are Apache-2.0 instead. Size resolved at ≈920 KB by instancing static faces and bundling only the Latin/Greek/Cyrillic Noto family. |
| R6 | ~~No accessibility tree~~ | **Closed** | **Delivered.** `runtime/accessibility.py` builds the semantic tree from the Element tree as reserved; `runtime/accesskit_bridge.py` pushes it to AT-SPI through AccessKit and was verified against a live screen reader. Windows and macOS need their own AccessKit platform wheels and are untested here, which `available()` reports rather than leaving to be discovered. |
| R7 | Over-invalidation silently costs frames | Medium | Tested directly (§11) rather than left to profiling. |
| R8 | Atlas thrashing under many fonts/sizes | Low | LRU + skyline; budgeted at 2048², growable to 4096². |

---

## 14. Milestones

| M | Deliverable | Proves |
|---|---|---|
| **M0** ✅ | `pyproject.toml`, package skeleton, CI matrix, `theme/` complete, a window that clears to an MD3 surface colour | **Done.** 33 tests green (5 on GPU), `ruff` clean, `mypy --strict` clean across 17 files |
| **M1** ✅ | `layout/` — constraints algebra, boundary/caching protocol, `LayoutOwner`, and `Padding`/`Align`/`SizedBox`/`ConstrainedBox`/`Row`/`Column`/`Flex`/`Stack`/`Spacer`. No rendering. | **Done.** 129 tests green, including Hypothesis property tests over random trees asserting the size invariant |
| **M2** ✅ | Instanced pipeline + `ui.wgsl`: rounded boxes, per-corner radii, borders, shadows, analytic AA, rounded shader clipping, palette tokens. **First benchmark.** | **Done.** 180 tests green (24 GPU); 500 mixed primitives verified as one draw call; **R1 quantified — see §12.1** |
| **M3** ✅ | `spec/` (Pydantic + sandboxed expressions), `runtime/signals.py`, `tree/` (element + reconcile), `runtime/events.py`, `widgets/`, and the public `App` | **Done.** 293 tests green. Full slice works: YAML → elements → layout → paint → click → signal → re-render, with state-preserving reload |
| **M4** ✅ | `text/` — Face/FontDB with coverage fallback, uharfbuzz shaping with a size-independent cache, bidi + script itemisation, UAX #14/#29 segmentation, paragraph layout with wrapping and alignment; `render/atlas.py` skyline packer; real `Text`/`Button` labels | **Done.** 371 tests green. Shaped, kerned, ligature-forming Roboto renders through the atlas in the same single draw call |
| **M5** ✅ | `runtime/hotreload.py` (watchfiles → engine thread), golden-image suite with six committed baselines, `examples/gallery` | **Done.** 390 tests green. Editing a view file updates the window without losing click count, focus, or scroll |
| **M6** ✅ | API freeze, `docs/view-reference.md`, `LICENSE`, packaging metadata, reproducible sdist/wheel | **Done.** 893 tests green. The public surface is pinned by `tests/test_public_api.py`; the reference is pinned by `tests/test_docs.py`, which fails when a widget, style property, node field, or handler key is added without documenting it. The wheel installs into a clean environment and renders text, icons, arcs, a carousel, and a modal overlay with no source tree present. **Publishing to PyPI is a separate, explicit step and has not been done.** |

---

## Appendix A — Bootstrap and M0 Findings

Three things surfaced while building M0 that belong in the record:

- **Surface formats differ by canvas.** The GLFW window reports `bgra8unorm-srgb`; the offscreen canvas reports `rgba8unorm-srgb`. Clear values and shader output are written in logical RGBA order either way, so nothing in the framework compensates — but golden tests read pixels back and must therefore run **offscreen only**, where channel order is known.
- **`requires-python = ">=3.12"`**, not 3.14. Nothing in the stack needs 3.14, and restricting a distributable framework to the newest interpreter costs most of its audience. Only 3.14.6 is verified locally; the CI matrix (3.12/3.13/3.14 × Linux/macOS/Windows) is what actually proves the floor.
- **`py.typed` is required.** Without the marker, `mypy` refuses to check the installed package at all and downstream users get no types from a fully-annotated library.

### A.1 Minimal bootstrap

The minimal M0 program. This was **executed** against the installed stack (Python 3.14.6, wgpu 0.32.0, rendercanvas 2.7.2): it acquires an adapter and device, reports `rgba8unorm-srgb` as the preferred format, and renders a frame whose pixels read back correctly. Contrast with the prior draft's `wgpu.gui` import and hand-rolled loop, neither of which functions on wgpu 0.32.0.

```python
import wgpu
from rendercanvas.glfw import RenderCanvas, loop
from materialyoucolor.hct import Hct
from materialyoucolor.scheme.scheme_tonal_spot import SchemeTonalSpot
from materialyoucolor.dynamiccolor.material_dynamic_colors import MaterialDynamicColors


def srgb_to_linear(c: float) -> float:  # see 5.6.1 - required
    return c / 12.92 if c <= 0.04045 else ((c + 0.055) / 1.055) ** 2.4


scheme = SchemeTonalSpot(Hct.from_int(0xFF6750A4), True, 0.0)
r, g, b, a = MaterialDynamicColors.surface.get_rgba(scheme)  # class, not instance
surface = (*(srgb_to_linear(v / 255) for v in (r, g, b)), a / 255)

canvas = RenderCanvas(
    title="pyCopper",
    size=(1024, 768),
    update_mode="ondemand",
    min_fps=0,
    max_fps=60,  # replaces the manual loop
)
adapter = wgpu.gpu.request_adapter_sync(power_preference="high-performance")
device = adapter.request_device_sync()
context = canvas.get_context("wgpu")
context.configure(device=device, format=context.get_preferred_format(adapter))


def draw_frame() -> None:
    encoder = device.create_command_encoder()
    rp = encoder.begin_render_pass(
        color_attachments=[
            {
                "view": context.get_current_texture().create_view(),
                "clear_value": surface,
                "load_op": wgpu.LoadOp.clear,
                "store_op": wgpu.StoreOp.store,
            }
        ]
    )
    # M2: bind pipeline, bind group 0, quad VB + instance VB, one instanced draw
    rp.end()
    device.queue.submit([encoder.finish()])


canvas.request_draw(draw_frame)
loop.run()
```

Swapping `rendercanvas.glfw` for `rendercanvas.offscreen` and calling `canvas.draw()` instead of `loop.run()` returns the frame as a `(h, w, 4)` array — this is verified working, and is the mechanism the golden-image suite is built on (§11).

## Appendix B — Changes from the Original Plan

The original `architectural_plan.md` has been superseded by this document and removed. Its substance is preserved below as a record of what changed and why.

| Area | Prior plan | Now | Why |
|---|---|---|---|
| Canvas | `wgpu.gui.glfw.WgpuCanvas` | `rendercanvas.glfw.RenderCanvas` | `wgpu.gui` does not exist in wgpu 0.32.0 |
| Adapter/device | `request_adapter()`, `request_device()` | `*_sync()` variants | Async by default in wgpu-py |
| Event loop | Hand-rolled `while` + `glfw.poll_events()` + `sleep` | rendercanvas scheduler, `ondemand` | Existing scheduler; manual polling double-pumps |
| Dirty state | One global `_is_dirty` | Typed per-element `build`/`layout`/`paint` | Global flag redraws everything on any change |
| UI tree | Pydantic `WidgetNode` used as live tree | Four-tree model (§4) | Pydantic models cannot hold runtime state |
| Hot reload | Re-parse and replace | Reconcile with state preservation | Replacement wipes focus, scroll, text on every save |
| Layout | One sentence, no module | `layout/` — Flutter constraints, boundaries | The core subsystem; needs a design and tests |
| Bindings | MVVM claimed, none present | `signals.py` + `{{ }}` + handler registry | The claim now has an implementation |
| MD3 colours | `MaterialDynamicColors()` instance | Class attributes | It is a class of class attributes |
| Theme storage | Per-widget RGBA arrays | Palette buffer + `u32` indices | Theme change becomes one buffer write |
| `children` | Nested under `style:` | On `WidgetSpec` | Children are structure, not styling |
| Clipping | Unaddressed | Analytic, in-shader, rounded | Scissor rects would split the draw call |
| Text | "freetype does layout" | Five-package pipeline (§2.3.1, §5.7), all verified | freetype rasterises; it does not shape, break, or reorder |
| Shaping | Deferred to v1.1 | **In v1** via `uharfbuzz` | Dependency proven on 3.14; GPOS kerning and ligatures confirmed working |
| Bidi / RTL | "post-1.0" | Rendering in v1; editing in v1.1 | `python-bidi` works; the residual work is caret semantics, not reordering |
| Font fallback | Unaddressed | `FontDB` coverage index, per-grapheme resolution | DejaVu Sans covers neither CJK nor emoji — fallback is required, not optional |
| Default font | Unaddressed | Bundled with the package | Golden tests cannot be deterministic against system fonts |
| Colour emoji | Unaddressed | Routed to the RGBA8 image atlas as kind=2 | Colour bitmaps do not belong in an R8 coverage texture; needs no shader change |
| `numpy` | Unlisted, used | First-class dependency | It is the instance-buffer representation |
| Colour space | Unaddressed | sRGB→linear on palette upload (§5.6.1) | Measured: `surface` rendered (69,64,75) instead of (15,13,18) |
| Power pref | `"low-power"` | `"high-performance"` | Picks the discrete GPU on hybrid laptops |
| Layout on disk | `core/` + root `app.py` | `src/pycopper/` + `examples/` | It is a distributable framework |
| Testing | Absent | §11, GPU-free majority + goldens | Shaped the architecture, not bolted on |

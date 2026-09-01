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
| Web, mobile, or embedded targets | Desktop-only keeps the windowing and input model coherent. |
| Complex text shaping (Arabic, Devanagari, CJK vertical) | Requires HarfBuzz; a seam is designed in, see §5.7. |
| Accessibility tree (AT-SPI / UIA / NSAccessibility) | Large, platform-specific. Architecturally reserved, not built. |
| CSS compatibility | The style vocabulary is MD3-shaped, not CSS-shaped. |
| Hot-reload of Python application logic | YAML reload only. Python reload is a different, much harder problem. |
| Multi-window | Single window in v1; the engine is written so the canvas is not a singleton. |

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

`flags.x` (kind) selects fragment behaviour: `0` = SDF box, `1` = glyph (atlas coverage × fill), `2` = image (atlas RGBA × tint).

**Subtree caching.** Each Element caches the instance slice it produced. A clean subtree's cached slice is copied wholesale into the frame buffer; only `needs_paint` subtrees re-emit. Because instances carry absolute coordinates, a subtree that merely *moved* still needs re-emission — this is a deliberate simplicity trade, revisitable by adding a per-instance transform index.

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

The intended design is to shape each run once for the paragraph, break on cumulative advances, and re-shape only lines whose break fell inside a cluster or ligature. **The M4 implementation does not do this yet**: `_wrap_block` re-shapes the growing candidate prefix at every break opportunity, which is quadratic in break count. The `ShapeCache` absorbs most of the repetition, but a cold 43-character wrapped line still measures **4.9 ms** (§12.2). It is one-time per unique string and free thereafter, so it does not affect steady-state frames — but it is a real deviation from this section and a tracked follow-up, not a design choice.

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

**≈920 KB total**, exposed through `pycopper.assets` (`DEFAULT_FONT`, `MEDIUM_FONT`, `FALLBACK_CHAIN`).

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

Three caches, in descending hit rate. Without them the perf budget in §12 is unreachable.

| Cache | Key | Value | Invalidated by |
|---|---|---|---|
| **Shaped run** | `(text, face, size, script, direction, features, lang)` | `ShapedRun` | Text or style change |
| **Paragraph layout** | `(run ids, available width, align)` | Line boxes | Reflow / resize |
| **Glyph raster** | `(face, px_size, gid, subpixel_bucket)` | Atlas rect | DPI change, LRU eviction |

Static labels — the majority of any interface — hit all three caches and cost nothing per frame beyond copying a cached instance slice.

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

The entire drain runs inside one signal `batch()`, so a handler writing several signals triggers dependent work once rather than once per write.

Dispatch follows a **capture → target → bubble** path over that hit path, with `Event.stop_propagation()`. Beyond raw clicks the system provides:

- **Pointer capture** — a widget may capture the pointer on press so drags continue outside its bounds.
- **Enter/leave** — computed by diffing the current hit path against the previous one.
- **Focus tree** — a tab-order traversal derived from document order, with `Tab`/`Shift-Tab` and focus-visible state.
- **Text input** — GLFW `char` callbacks for committed text. IME preedit is a known gap (§13).

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

### 5.11 Hot reload — `runtime/hotreload.py`

`watchfiles` runs in a background thread. On a change to a watched YAML file it posts a reload request to the engine thread — it never touches the trees itself.

The engine then: re-reads and re-validates the Spec tree; **on validation failure, logs the Pydantic error with file and line and keeps the previous tree running** (a syntax error mid-edit must not kill the app); on success, reconciles (§5.3), preserving all runtime state for nodes whose `id` and widget kind are unchanged; and requests a draw.

Handler *bindings* are re-resolved, but handler *bodies* are not reloaded — that is Python-level reload and is out of scope (§1.2).

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
│           ├── base.py          # Widget protocol: layout() + paint()
│           ├── container.py     ├── text.py       ├── button.py
│           ├── row.py           ├── column.py     ├── stack.py
│           └── scroll.py
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
| Text pipeline | Shaping against the **bundled** font: assert glyph IDs, advances, cluster mapping. Fallback chain resolution. Break opportunities and grapheme counts against UAX test data. | No |
| Rendering | `rendercanvas.offscreen` → render → read texture → compare against a **committed baseline PNG**. Tolerance is 4/255 per channel with at most 0.2% of pixels allowed to exceed it — an exact match would be unmaintainable across drivers, anything looser stops catching real changes. `examples/gallery` is the corpus. | Yes |
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
| Layout, cold cache (43 chars, wrapped) | **4.89 ms** | ⚠️ one-time per string |

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
| R2 | ~~Text scope creep~~ | **Closed** | **Delivered in M4.** Shaping, fallback, segmentation, itemisation, atlas, and paragraph layout all ship and are tested. Residual work is narrow and tracked separately: the quadratic wrap in §5.7.1, and RTL caret semantics (R9). |
| R3 | `wgpu-native` backend variance across Vulkan/Metal/DX12 | Medium | Keep WGSL conservative; golden tests per platform; no optional GPU features. |
| R4 | Single draw call broken by a future feature | Medium | Stated as a design constraint (§1.3). Clipping already solved analytically; transforms and blend modes are the next pressure points. |
| R5 | IME / CJK text *input* unsupported | Medium | **Open.** GLFW preedit support is limited; likely needs platform code or a rendercanvas contribution. Note this is input only — CJK *rendering* is covered by Tier 1. |
| R9 | RTL caret/selection semantics (Tier 3) | Medium | Deferred to v1.1 and stated as such. Reordering is solved; bidirectional caret affinity is independent UI work. |
| R10 | ~~Bundled font licensing and size~~ | **Closed** | **Resolved.** Roboto and Noto Sans are both **SIL OFL 1.1**, compatible with MIT, with licence texts redistributed alongside them (§5.7.2). Note Roboto was *relicensed*: builds predating its move to `ofl/` in `google/fonts` — including the v2.137 copy some distributions still ship — are Apache-2.0 instead. Size resolved at ≈920 KB by instancing static faces and bundling only the Latin/Greek/Cyrillic Noto family. |
| R6 | No accessibility tree | Medium | **Open.** Architecturally reserved: the Element tree is the natural source for AT-SPI/UIA. Not v1. |
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
| **M6** | API freeze, docs, PyPI release | v1.0 |

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

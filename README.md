# pyCopper

A GPU-accelerated declarative desktop GUI framework for Python.

Author your interface in YAML, write logic in Python, get a hardware-accelerated
Material Design 3 interface — rendered through WebGPU in **a single draw call**.

```yaml
# view.yaml
root:
  name: root
  widget: Column
  style: {background: surface, padding: 24, spacing: 16, width: expand}
  children:
    - name: label
      widget: Text
      text: "Clicked {{ clicks.get() }} times"
      style: {color: on_surface, font_size: 22}

    - name: go
      widget: Button
      text: "Click me"
      style: {width: 160, height: 40, variant: filled}
      handlers: {on_click: bump}
```

```python
# app.py
from pycopper import App, Signal, Theme

app = App("view.yaml", theme=Theme(seed="#6750A4", dark=True))

clicks = Signal(0)
app.expose(clicks=clicks)


@app.handler
def bump(event) -> None:
    clicks.update(lambda n: n + 1)


if __name__ == "__main__":
    app.run()
```

```bash
python app.py
```

Edit `view.yaml` while it runs and the window updates without losing the click
count, focus, or scroll position.

## Why

- **Native GPU, not OpenGL.** `wgpu` targets Vulkan, Metal, and DirectX 12 directly.
- **One draw call.** Every box, border, shadow, glyph, icon, and arc renders from
  a single instanced draw over a signed-distance-field shader — with analytic
  antialiasing and rounded clipping, and no MSAA.
- **Real text.** HarfBuzz shaping with kerning and ligatures, Unicode line
  breaking and grapheme segmentation, bidi, and font fallback. Not a bitmap-font
  approximation.
- **Material Design 3.** A full 59-token tonal palette from one seed colour, and
  38 components built to their published specs. Switching theme is a single
  buffer upload — no relayout, no display-list rebuild.
- **Fine-grained reactivity.** A signal write invalidates exactly the affected
  subtree with a typed reason — build, layout, or paint — not the frame.
- **Genuinely idle.** An app that is not doing anything renders zero frames.
- **Desktop-first.** Hover, focus rings, keyboard traversal, wheel scrolling and
  visible scrollbars are primary, not progressive enhancements.

## Install

Requires Python 3.12+. Every dependency ships prebuilt wheels — no toolchain
needed, and the fonts are bundled.

```bash
pip install pycopper
```

## Documentation

- **[View file reference](docs/view-reference.md)** — every widget, every style
  property, bindings, handlers, composition, and overlays.
- **[ARCHITECTURE.md](ARCHITECTURE.md)** — the design and the reasoning: the
  four-tree model, constraint layout, the single-draw-call pipeline, the text
  stack, and the measurements behind each decision.
- **[examples/](examples/)** — `hello`, `counter`, and `gallery`, which exercises
  every widget and doubles as the golden-image corpus.

## Status

**v1.1 — the public API is frozen.** `pycopper.__all__` is covered by semantic
versioning and pinned by a test; adding to it is a minor release, changing or
removing anything in it is a major one. (1.1 is that rule in action: motion
added four names and nothing else moved.)

Frozen does not mean finished. What is deliberately **not** built yet:

| Absent | Consequence |
|---|---|
| Motion is not everywhere | M3 easing and duration tokens, an injectable clock, and `reduce_motion`. Drives overlay fades, state layers, every selection control, tab and navigation indicators, indeterminate progress, and the carousel snap. Carousel parallax and app-bar collapse are still absent |
| Theme engine and stylesheet | `classes` is a reserved selector target with no consumer |
| Disabled state | M3's 12%/38% disabled opacities have nowhere to attach |
| M3 type scale as named roles | Widgets take a raw `font_size` |
| Separate hit and paint rects | M3's 48dp minimum touch target cannot be expressed — deliberate, as pyCopper is pointer-only |
| Right-click menus, cursor shapes, text selection | Desktop conventions still to come |

Mobile and touch are explicit non-goals.

## Performance

Python, not the GPU, is the bottleneck — which is what the architecture is
organised around. Retained mode, typed invalidation, numpy display-list
assembly, cached subtree splicing, and paint-time scrolling all exist to keep
work off the per-frame path. §12 of ARCHITECTURE.md has the measurements.

## Testing

745 tests, `ruff` and `mypy --strict` clean. Golden-image baselines cover the
rendered output; everything else — layout, reactivity, reconciliation, text
segmentation, event dispatch — runs with no GPU on any runner.

```bash
pytest                    # everything
pytest -m "not gpu"       # no GPU required
```

## License

MIT. See [LICENSE](LICENSE).

Bundled fonts keep their own licences: Roboto and Noto Sans under the SIL Open
Font License 1.1, Material Symbols under Apache 2.0. All three travel with every
distribution.

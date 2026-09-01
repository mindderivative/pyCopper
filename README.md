# pyCopper

A GPU-accelerated declarative desktop GUI framework for Python.

Author your interface in YAML, write logic in Python, get a hardware-accelerated
Material Design 3 interface — rendered through WebGPU in a single draw call.

> **Status: pre-alpha (M0).** The architecture is settled and documented; the
> implementation is early. See [ARCHITECTURE.md](ARCHITECTURE.md) for the full
> design and [§14](ARCHITECTURE.md#14-milestones) for the roadmap.

## Why

- **Native GPU, not OpenGL.** `wgpu` targets Vulkan, Metal, and DirectX 12 directly.
- **One draw call.** Every box, border, shadow, glyph, and image renders from a
  single instanced draw over a signed-distance-field shader — with analytic
  antialiasing and rounded clipping, and no MSAA.
- **Real text.** HarfBuzz shaping, Unicode line breaking and grapheme
  segmentation, bidi, and font fallback. Not a bitmap-font approximation.
- **Material Design 3.** A full tonal palette from one seed colour. Theme
  switching is a single buffer upload — no relayout, no rebuild.
- **Fine-grained reactivity.** A signal write invalidates exactly the affected
  subtree, not the frame.
- **Genuinely idle.** An app that isn't doing anything renders zero frames.

## Install

Requires Python 3.12+. All dependencies ship prebuilt wheels — no toolchain needed.

```bash
pip install pycopper
```

## Hello, window

```python
from pycopper import Engine, Theme

engine = Engine(theme=Theme(seed="#6750A4", dark=True))
engine.run()
```

## Development

```bash
python -m venv .venv && .venv/bin/pip install -e ".[dev]"
.venv/bin/python -m pytest              # full suite
.venv/bin/python -m pytest -m "not gpu" # no adapter required
```

The overwhelming majority of the framework — layout, reactivity, reconciliation,
text segmentation — is testable with no GPU on any runner.

## License

MIT

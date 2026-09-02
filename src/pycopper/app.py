"""The public application object: view + state + handlers + engine.

Ties the four trees together (ARCHITECTURE.md 4) and owns the frame pipeline
described in ARCHITECTURE.md 6.
"""

from __future__ import annotations

from collections.abc import Callable
from pathlib import Path
from typing import Any

from .config import Settings
from .layout import OFFSET_ZERO, Constraints, LayoutOwner, Size
from .paint import DisplayList
from .runtime.engine import Engine
from .runtime.events import EventDispatcher, EventType, KeyEvent, PointerEvent, WheelEvent
from .runtime.hotreload import HotReloader
from .runtime.overlay import OverlayHost
from .runtime.signals import batch, bind_thread
from .spec import SpecError, ViewSpec, load_view, parse_view
from .text import TextEngine
from .theme import Palette, Theme
from .tree.element import PaintContext
from .tree.reconcile import ReconcileStats, reconcile
from .widgets import build_element

__all__ = ["App", "run"]

_POINTER_EVENTS = {
    "pointer_down": EventType.POINTER_DOWN,
    "pointer_up": EventType.POINTER_UP,
    "pointer_move": EventType.POINTER_MOVE,
}


class App:
    """A pyCopper application."""

    def __init__(
        self,
        view: str | Path | ViewSpec | dict[str, Any],
        *,
        theme: Theme | None = None,
        settings: Settings | None = None,
    ) -> None:
        self.settings = settings or Settings()
        self.theme = theme or Theme()
        self.palette = Palette(self.theme)

        self._source = Path(view) if isinstance(view, str | Path) else None
        #: Every file the view was assembled from, including fragments pulled
        #: in with `source:`. Hot reload watches all of them.
        self.sources: set[Path] = set()
        self.view = self._load(view)
        self.root = build_element(self.view.root)
        self.layout_owner = LayoutOwner()
        self.root.attach(self.layout_owner)

        self.text = TextEngine()
        self.root.set_text_engine(self.text)

        self.overlays = OverlayHost()
        self.overlays.build(self.view.overlays, text_engine=self.text)

        self.dispatcher = EventDispatcher()
        self.dispatcher.root = self.root
        self.dispatcher.overlays = self.overlays

        self.context: dict[str, Any] = {}
        self._handlers: dict[str, Callable[[Any], None]] = {}
        self.engine: Engine | None = None
        self.reloader: HotReloader | None = None
        self.reload_errors: list[str] = []
        self._mounted = False

    def _load(self, view: str | Path | ViewSpec | dict[str, Any]) -> ViewSpec:
        if isinstance(view, ViewSpec):
            return view
        if isinstance(view, dict):
            return parse_view(view)
        self.sources = set()
        return load_view(view, sources=self.sources)

    # -------------------------------------------------------------- wiring

    def handler(self, fn: Callable[[Any], None]) -> Callable[[Any], None]:
        """Register an event handler by name, for view files to reference."""
        self._handlers[fn.__name__] = fn
        return fn

    def expose(self, **values: Any) -> None:
        """Publish names visible to ``{{ }}`` expressions in the view."""
        self.context.update(values)

    def mount(self) -> None:
        """Resolve handlers and subscribe bindings. Idempotent."""
        missing = self.dispatcher.bind_handlers(self._handlers, extra=self.overlays.elements())
        if missing:
            raise SpecError(
                "view references handlers that are not registered:\n  " + "\n  ".join(missing)
            )
        for element in self.root.walk_elements():
            element.bind(self.context)
        self.overlays.bind(self.context)
        self._mounted = True

    # ------------------------------------------------------------ hot reload

    @property
    def view_path(self) -> Path | None:
        """The file this view was loaded from, if any. Dict views have none."""
        return self._source

    def watch(self) -> HotReloader:
        """Start watching the view file for changes.

        Opt-in: a file watcher is unwanted overhead in a shipped application,
        so this is never started automatically unless Settings.hot_reload is on.
        """
        if self._source is None:
            raise ValueError("cannot watch a view that was not loaded from a file")
        # Watch the whole include graph: editing a fragment must reload the
        # view, or `source:` would silently break the best feature there is.
        watched = sorted(self.sources) or [self._source]
        if self.reloader is None or set(self.reloader.paths) != {p.resolve() for p in watched}:
            if self.reloader is not None:
                self.reloader.stop()
            self.reloader = HotReloader(watched)
        self.reloader.start()
        return self.reloader

    def unwatch(self) -> None:
        if self.reloader is not None:
            self.reloader.stop()

    def poll_reload(self) -> int:
        """Apply any pending file changes. Called from the engine thread.

        Returns the number of files reloaded successfully. A rejected reload is
        recorded in `reload_errors` and the previous tree keeps running.
        """
        if self.reloader is None:
            return 0
        # Any file in the include graph changing reloads the ENTRY view, not
        # the file that changed: a fragment is not a view on its own, and
        # loading one directly would fail on its `params:` block.
        entry = self._source
        events = self.reloader.apply(lambda _p: self.reload(entry) if entry else None)
        for event in events:
            if event.error:
                self.reload_errors.append(event.error)
        applied = sum(1 for e in events if not e.error and e.change != "DELETED")
        if applied and self.engine is not None:
            self.engine.request_draw()
        return applied

    def reload(self, view: str | Path | ViewSpec | dict[str, Any]) -> ReconcileStats:
        """Swap in a new view, preserving runtime state where ids still match."""
        new_view = self._load(view)
        root, stats = reconcile(self.root, new_view.root)
        self.root = root
        assert isinstance(stats, ReconcileStats)
        self.view = new_view
        self.root.attach(self.layout_owner)
        self.root.set_text_engine(self.text)
        self.dispatcher.root = self.root
        if self._mounted:
            self.mount()
        return stats

    # ----------------------------------------------------------------- frame

    def logical_size(self) -> Size:
        if self.engine is not None:
            w, h = self.engine.canvas.get_logical_size()
            return Size(float(w), float(h))
        return Size(float(self.settings.width), float(self.settings.height))

    def update(self) -> None:
        """Frame steps 1-5: drain events, flush signals, relayout."""
        self.poll_reload()
        self.dispatcher.drain()
        self.layout_owner.flush()
        size = self.logical_size()
        self.root.layout(Constraints.tight(size))
        self.overlays.layout(size, self.root)

    def paint(self, display_list: DisplayList) -> None:
        """Frame step 6: walk the element tree into the display list."""
        self.update()
        ctx = PaintContext(
            display_list=display_list,
            palette=self.palette,
            text=self.text,
            pixel_ratio=self.engine.pixel_ratio if self.engine else 1.0,
        )
        self.root.paint(ctx, OFFSET_ZERO)
        self.overlays.paint(ctx, self.palette, self.logical_size())

    def set_theme(self, theme: Theme) -> None:
        """One palette upload. No relayout, no display-list rebuild."""
        self.theme = theme
        self.palette.rebuild(theme)
        if self.engine is not None:
            self.engine.palette = self.palette
            self.engine.request_draw()

    # ------------------------------------------------------------- lifecycle

    def attach(self, engine: Engine) -> None:
        # One atlas per application: promote the App's CPU-only text engine to
        # the device rather than leaving the Engine's separate one bound.
        self.text.attach_device(engine.device)
        engine.text = self.text
        engine.pipeline.bind_glyph_atlas(self.text.atlas.texture)
        engine.palette = self.palette
        engine.painter = self.paint
        engine.canvas.add_event_handler(self._on_canvas_event, "*")
        self.engine = engine
        if not self._mounted:
            self.mount()
        if self.settings.hot_reload and self._source is not None:
            self.watch()

    def _on_canvas_event(self, event: dict[str, Any]) -> None:
        kind = event.get("event_type")
        if kind in _POINTER_EVENTS:
            self.dispatcher.post(
                PointerEvent(
                    _POINTER_EVENTS[kind],
                    x=float(event.get("x", 0.0)),
                    y=float(event.get("y", 0.0)),
                    button=int(event.get("button", 0) or 0),
                    modifiers=frozenset(event.get("modifiers", ())),
                )
            )
        elif kind == "wheel":
            self.dispatcher.post(
                WheelEvent(
                    EventType.WHEEL,
                    x=float(event.get("x", 0.0)),
                    y=float(event.get("y", 0.0)),
                    dx=float(event.get("dx", 0.0)),
                    dy=float(event.get("dy", 0.0)),
                    modifiers=frozenset(event.get("modifiers", ())),
                )
            )
        elif kind == "key_down":
            self.dispatcher.post(
                KeyEvent(
                    EventType.KEY_DOWN,
                    key=str(event.get("key", "")),
                    modifiers=frozenset(event.get("modifiers", ())),
                )
            )
        elif kind == "char":
            self.dispatcher.post(KeyEvent(EventType.TEXT, text=str(event.get("char", ""))))
        else:
            return
        if self.engine is not None:
            self.engine.request_draw()

    def run(self) -> None:
        bind_thread()
        engine = Engine(theme=self.theme, settings=self.settings)
        self.attach(engine)
        engine.run()


def run(app: App) -> None:
    """Run *app* until its window closes."""
    app.run()


def batched(fn: Callable[[], None]) -> None:
    """Apply several signal writes as one update."""
    with batch():
        fn()

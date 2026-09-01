"""Events: queue, hit testing, capture/bubble dispatch, hover, and focus.

Events are queued and drained once per frame (step 1 of ARCHITECTURE.md 6), so
a burst of pointer motion coalesces instead of triggering redundant work.

Hit testing walks the tree in REVERSE paint order and returns the topmost path.
A forward walk that visits every node -- which is what a naive implementation
does -- both ignores z-order and cannot express "the panel above intercepted it".
"""

from __future__ import annotations

from collections import deque
from collections.abc import Callable
from dataclasses import dataclass, field
from enum import Enum, StrEnum
from typing import Any

from ..layout import OFFSET_ZERO
from .signals import batch

__all__ = [
    "Event",
    "EventDispatcher",
    "EventType",
    "KeyEvent",
    "Phase",
    "PointerEvent",
]


class EventType(StrEnum):
    POINTER_DOWN = "pointer_down"
    POINTER_UP = "pointer_up"
    POINTER_MOVE = "pointer_move"
    POINTER_ENTER = "pointer_enter"
    POINTER_LEAVE = "pointer_leave"
    CLICK = "click"
    KEY_DOWN = "key_down"
    KEY_UP = "key_up"
    TEXT = "text"
    FOCUS = "focus"
    BLUR = "blur"


class Phase(Enum):
    CAPTURE = "capture"
    TARGET = "target"
    BUBBLE = "bubble"


@dataclass(slots=True)
class Event:
    type: EventType
    target: Any = None
    phase: Phase = Phase.TARGET
    _stopped: bool = False

    def stop_propagation(self) -> None:
        self._stopped = True

    @property
    def stopped(self) -> bool:
        return self._stopped


@dataclass(slots=True)
class PointerEvent(Event):
    x: float = 0.0
    y: float = 0.0
    button: int = 0
    modifiers: frozenset[str] = field(default_factory=frozenset)


@dataclass(slots=True)
class KeyEvent(Event):
    key: str = ""
    text: str = ""
    modifiers: frozenset[str] = field(default_factory=frozenset)


#: Event type -> the handler key a view file uses.
HANDLER_KEYS = {
    EventType.POINTER_DOWN: "on_pointer_down",
    EventType.POINTER_UP: "on_pointer_up",
    EventType.POINTER_MOVE: "on_pointer_move",
    EventType.POINTER_ENTER: "on_pointer_enter",
    EventType.POINTER_LEAVE: "on_pointer_leave",
    EventType.CLICK: "on_click",
    EventType.KEY_DOWN: "on_key_down",
    EventType.TEXT: "on_text",
    EventType.FOCUS: "on_focus",
    EventType.BLUR: "on_blur",
}


#: Widget kinds that take keyboard focus even without an explicit handler.
#: These are interactive controls: a user must be able to Tab to a checkbox
#: whether or not the view file wired an on_click.
FOCUSABLE_KINDS: frozenset[str] = frozenset(
    {
        "Button",
        "Checkbox",
        "Radio",
        "Switch",
        "Chip",
        "IconButton",
        "Fab",
        "NavItem",
        "Tab",
        "Segment",
        "ListItem",
    }
)


class EventDispatcher:
    """Owns the event queue, hover/press/focus state, and dispatch."""

    def __init__(self) -> None:
        self.root: Any = None
        #: The overlay layer, consulted before the tree because it is on top.
        self.overlays: Any = None
        self._queue: deque[Event] = deque()
        self._hover_path: list[Any] = []
        self._pressed: Any = None
        self._captured: Any = None
        self._focused: Any = None

    # ------------------------------------------------------------- queueing

    def post(self, event: Event) -> None:
        """Queue an event. Consecutive motion events coalesce."""
        if (
            event.type is EventType.POINTER_MOVE
            and self._queue
            and self._queue[-1].type is EventType.POINTER_MOVE
        ):
            self._queue[-1] = event
            return
        self._queue.append(event)

    @property
    def pending(self) -> int:
        return len(self._queue)

    def drain(self) -> int:
        """Dispatch everything queued. Returns how many events were handled.

        The whole drain runs in one signal batch, so a handler writing several
        signals triggers dependent work once, not once per write.
        """
        handled = 0
        with batch():
            while self._queue:
                self.dispatch(self._queue.popleft())
                handled += 1
        return handled

    # ------------------------------------------------------------ hit testing

    def hit_path(self, x: float, y: float) -> list[Any]:
        """Topmost-first list of elements under the point.

        The overlay layer is checked first because it renders above the tree,
        and a modal overlay swallows everything beneath it -- otherwise a click
        on a scrim would fall through to the blocked interface.
        """
        if self.overlays is not None:
            found: list[Any] = list(self.overlays.hit_path(x, y))
            if found:
                return found
            if self.overlays.has_modal:
                return []
        if self.root is None:
            return []
        return list(self.root.hit_test(x, y, OFFSET_ZERO))

    @property
    def focused(self) -> Any:
        return self._focused

    @property
    def hovered(self) -> Any:
        return self._hover_path[0] if self._hover_path else None

    # -------------------------------------------------------------- dispatch

    def dispatch(self, event: Event) -> None:
        if isinstance(event, PointerEvent):
            self._dispatch_pointer(event)
        elif isinstance(event, KeyEvent):
            self._dispatch_to_focused(event)

    def _dispatch_pointer(self, event: PointerEvent) -> None:
        # A captured pointer keeps receiving events outside its own bounds,
        # which is what makes dragging work.
        path = [self._captured] if self._captured is not None else self.hit_path(event.x, event.y)

        # A press outside a modal dismisses it and goes no further.
        if (
            event.type is EventType.POINTER_DOWN
            and self.overlays is not None
            and self._captured is None
            and self.overlays.handle_press(event.x, event.y)
            and not path
        ):
            return

        match event.type:
            case EventType.POINTER_MOVE:
                self._update_hover(path)
            case EventType.POINTER_DOWN:
                target = path[0] if path else None
                self._pressed = target
                self._captured = target
                if target is not None:
                    target.state.pressed = True
                    target.mark_needs_paint()
                self.focus(target if target and self._focusable(target) else None)
            case EventType.POINTER_UP:
                pressed = self._pressed
                self._captured = None
                self._pressed = None
                if pressed is not None:
                    pressed.state.pressed = False
                    pressed.mark_needs_paint()

        self._propagate(path, event)

        # A click is press and release over the same element.
        if event.type is EventType.POINTER_UP and path and path[0] is not None:
            live = self.hit_path(event.x, event.y)
            if live and live[0] is path[0]:
                self._propagate(live, PointerEvent(EventType.CLICK, x=event.x, y=event.y))

    def _update_hover(self, path: list[Any]) -> None:
        new_set = set(map(id, path))
        for element in self._hover_path:
            if id(element) not in new_set and element.state.hovered:
                element.state.hovered = False
                element.mark_needs_paint()
                self._propagate([element], Event(EventType.POINTER_LEAVE))
        old_set = set(map(id, self._hover_path))
        for element in path:
            if id(element) not in old_set:
                element.state.hovered = True
                element.mark_needs_paint()
                self._propagate([element], Event(EventType.POINTER_ENTER))
        self._hover_path = path

    def _dispatch_to_focused(self, event: Event) -> None:
        # Tab traversal is handled before delivery: it must work even when
        # nothing is focused yet, which is the state an app starts in.
        if isinstance(event, KeyEvent) and event.type is EventType.KEY_DOWN:
            if event.key in ("Tab", "tab"):
                self.focus_next(backwards="shift" in event.modifiers)
                return
            if event.key in ("Escape", "escape"):
                # Escape closes the topmost overlay before it clears focus.
                if self.overlays is not None and self.overlays.dismiss_top():
                    return
                if self._focused is not None:
                    self.focus(None)
                    return

        if self._focused is None:
            return
        path: list[Any] = []
        node = self._focused
        while node is not None:
            path.append(node)
            node = getattr(node, "parent", None)
        self._propagate(path, event)

    def _propagate(self, path: list[Any], event: Event) -> None:
        """Capture (root -> target), then target, then bubble (target -> root)."""
        if not path:
            return
        event.target = path[0]

        ancestors = path[1:]
        sequence: list[tuple[Phase, Any]] = [
            *((Phase.CAPTURE, e) for e in reversed(ancestors)),
            (Phase.TARGET, path[0]),
            *((Phase.BUBBLE, e) for e in ancestors),
        ]
        for phase, element in sequence:
            event.phase = phase
            self._invoke(element, event)
            if event.stopped:
                return

    @staticmethod
    def _invoke(element: Any, event: Event) -> None:
        handler = element.handlers.get(HANDLER_KEYS.get(event.type, ""))
        if handler is not None:
            handler(event)

    # ----------------------------------------------------------------- focus

    @staticmethod
    def _focusable(element: Any) -> bool:
        return bool(element.handlers) or str(element.spec.widget) in FOCUSABLE_KINDS

    def focus(self, element: Any, *, keyboard: bool = False) -> None:
        """Move focus. ``keyboard=True`` also shows the focus ring.

        Desktop convention: clicking focuses silently, Tab shows the indicator.
        """
        if element is self._focused:
            if element is not None and element.state.focus_visible != keyboard:
                element.state.focus_visible = keyboard
                element.mark_needs_paint()
            return
        if self._focused is not None:
            self._focused.state.focused = False
            self._focused.state.focus_visible = False
            self._focused.mark_needs_paint()
            self._propagate([self._focused], Event(EventType.BLUR))
        self._focused = element
        if element is not None:
            element.state.focused = True
            element.state.focus_visible = keyboard
            element.mark_needs_paint()
            self._propagate([element], Event(EventType.FOCUS))

    def focus_order(self) -> list[Any]:
        """Focusable elements in document order -- the Tab traversal."""
        if self.root is None:
            return []
        return [e for e in self.root.walk_elements() if self._focusable(e)]

    def focus_next(self, backwards: bool = False) -> Any:
        """Move focus along the Tab order. Always shows the ring."""
        order = self.focus_order()
        if not order:
            return None
        if self._focused is None or self._focused not in order:
            self.focus(order[-1] if backwards else order[0], keyboard=True)
            return self._focused
        index = order.index(self._focused)
        self.focus(order[(index + (-1 if backwards else 1)) % len(order)], keyboard=True)
        return self._focused

    def bind_handlers(
        self,
        registry: dict[str, Callable[[Any], None]],
        extra: list[Any] | None = None,
    ) -> list[str]:
        """Resolve handler names from view files against *registry*.

        Returns the names that could not be resolved, so the caller can fail at
        load rather than silently ignoring a typo'd handler.
        """
        missing: list[str] = []
        if self.root is None:
            return missing
        targets = list(self.root.walk_elements()) + list(extra or [])
        for element in targets:
            element.handlers = {}
            for event_key, name in element.spec.handlers.items():
                fn = registry.get(name)
                if fn is None:
                    label = element.spec.name or element.spec.id
                    missing.append(f"{label}.{event_key} -> {name!r}")
                else:
                    element.handlers[event_key] = fn
        return missing

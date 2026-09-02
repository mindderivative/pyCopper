"""The clipboard seam.

**pyCopper does not ship a system clipboard, deliberately.** `rendercanvas`
exposes none, and the only route to one is the backend's private window handle
(`canvas._window`) passed to GLFW -- which is platform-specific on top of being
private: on Wayland the call fails outright without a real surface. Depending
on that would be a contract that breaks on a dependency upgrade.

So copying fills an in-process clipboard, which makes copy-and-paste *within*
an application work, and leaves one obvious seam for an application that wants
the system one:

    from pycopper.runtime.clipboard import clipboard
    import pyperclip

    class SystemClipboard:
        def set_text(self, text: str) -> bool:
            pyperclip.copy(text)
            return True

        def get_text(self) -> str:
            return pyperclip.paste()

    clipboard.install(SystemClipboard())

Process-global on purpose, unlike the animation ticker: a clipboard genuinely
is one shared thing, so there is nothing for an App to own.
"""

from __future__ import annotations

from typing import Any, Protocol

__all__ = ["Clipboard", "ClipboardBackend", "clipboard"]


class ClipboardBackend(Protocol):
    """What an application supplies to reach the real system clipboard."""

    def set_text(self, text: str) -> bool: ...
    def get_text(self) -> str: ...


class Clipboard:
    """In-process clipboard, with a seam for a real one."""

    __slots__ = ("_backend", "_text")

    def __init__(self) -> None:
        self._text = ""
        self._backend: Any = None

    def install(self, backend: ClipboardBackend | None) -> None:
        """Route through a real clipboard. `None` returns to in-process only."""
        self._backend = backend

    @property
    def system_backed(self) -> bool:
        return self._backend is not None

    def set_text(self, text: str) -> bool:
        """Copy. Returns whether it reached a system clipboard.

        The in-process copy happens either way, so a failed system write still
        leaves the application able to paste into itself.
        """
        self._text = text
        if self._backend is None:
            return False
        try:
            return bool(self._backend.set_text(text))
        except Exception:  # pragma: no cover - a backend must never break a frame
            return False

    def get_text(self) -> str:
        if self._backend is not None:
            try:
                return str(self._backend.get_text())
            except Exception:  # pragma: no cover
                return self._text
        return self._text


#: The process-wide clipboard.
clipboard = Clipboard()

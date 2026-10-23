"""Platform-neutral native global hotkey facade."""

from __future__ import annotations

import sys
from typing import Protocol

from PySide6.QtCore import QObject, Qt, Signal, Slot


class _Backend(Protocol):
    def start(self) -> None: ...

    def stop(self) -> None: ...


class GlobalHotkey(QObject):
    """Expose the platform Ctrl/Cmd+0 registration as a queued Qt signal.

    ``start`` and ``stop`` are idempotent. Registration and teardown must be
    called on the QApplication thread because both native APIs bind delivery to
    the calling application's event loop.
    """

    activated = Signal()
    _native_activated = Signal()

    def __init__(self, parent: QObject | None = None) -> None:
        super().__init__(parent)
        self._native_activated.connect(
            self._deliver_activation, Qt.ConnectionType.QueuedConnection
        )
        self._backend: _Backend = self._make_backend()
        self._started = False

    def _make_backend(self) -> _Backend:
        # Import only the implementation that can run on this operating system;
        # importing WinDLL or loading Carbon is itself platform-specific.
        if sys.platform == "win32":
            from qckdrw.hotkeys.windows import WindowsHotkeyBackend

            return WindowsHotkeyBackend(self._native_activated.emit)
        if sys.platform == "darwin":
            from qckdrw.hotkeys.macos import MacOSHotkeyBackend

            return MacOSHotkeyBackend(self._native_activated.emit)
        raise RuntimeError(
            f"Global Ctrl/Cmd+0 hotkeys are not supported on {sys.platform!r}"
        )

    @Slot()
    def _deliver_activation(self) -> None:
        if self._started:
            self.activated.emit()

    def start(self) -> None:
        if self._started:
            return
        self._backend.start()
        self._started = True

    def stop(self) -> None:
        # Always delegate: a backend can retain a native reference if cleanup of
        # a partially failed start also failed. Its stop operation is idempotent.
        self._backend.stop()
        self._started = False

    def __del__(self) -> None:
        try:
            self.stop()
        except Exception:
            # Destructors cannot report cleanup errors safely. Explicit stop()
            # retains the detailed native error for normal application shutdown.
            pass


__all__ = ["GlobalHotkey"]

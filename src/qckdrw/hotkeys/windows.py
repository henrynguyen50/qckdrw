"""Win32 implementation of the Quick Canvas global hotkey."""

from __future__ import annotations

import ctypes
from collections.abc import Callable
from ctypes import wintypes

from PySide6.QtCore import QAbstractNativeEventFilter, QCoreApplication, QThread

_HOTKEY_ID = 0x5143
_WM_HOTKEY = 0x0312
_MOD_CONTROL = 0x0002
_MOD_NOREPEAT = 0x4000
_VK_0 = 0x30
_WINDOWS_EVENT_TYPES = {
    b"windows_dispatcher_MSG",
    b"windows_generic_MSG",
}

_WPARAM = ctypes.c_size_t
_LPARAM = ctypes.c_ssize_t


class _Point(ctypes.Structure):
    _fields_ = (("x", wintypes.LONG), ("y", wintypes.LONG))


class _Msg(ctypes.Structure):
    # This mirrors the native MSG definition, including its Windows 8+ private
    # field. ctypes supplies the pointer-size alignment required on 64-bit.
    _fields_ = (
        ("hwnd", wintypes.HWND),
        ("message", wintypes.UINT),
        ("wParam", _WPARAM),
        ("lParam", _LPARAM),
        ("time", wintypes.DWORD),
        ("pt", _Point),
        ("lPrivate", wintypes.DWORD),
    )


class _HotkeyEventFilter(QAbstractNativeEventFilter):
    def __init__(self, activate: Callable[[], None]) -> None:
        super().__init__()
        self._activate = activate

    def nativeEventFilter(self, event_type: bytes, message: int) -> tuple[bool, int]:  # noqa: N802
        # Qt 6.12 delivers thread-queue WM_HOTKEY messages as
        # windows_generic_MSG. Older Qt versions may use dispatcher_MSG.
        if bytes(event_type) not in _WINDOWS_EVENT_TYPES:
            return False, 0

        msg = _Msg.from_address(int(message))
        if msg.message == _WM_HOTKEY and msg.wParam == _HOTKEY_ID:
            self._activate()
        # Observing the message is sufficient. RegisterHotKey has already
        # prevented the keystroke from being delivered as an ordinary shortcut.
        return False, 0


class WindowsHotkeyBackend:
    """Owns one thread-bound Win32 Ctrl+0 registration."""

    def __init__(self, activate: Callable[[], None]) -> None:
        self._activate = activate
        self._filter: _HotkeyEventFilter | None = None
        self._registered = False

        user32 = ctypes.WinDLL("user32", use_last_error=True)
        user32.RegisterHotKey.argtypes = (
            wintypes.HWND,
            ctypes.c_int,
            wintypes.UINT,
            wintypes.UINT,
        )
        user32.RegisterHotKey.restype = wintypes.BOOL
        user32.UnregisterHotKey.argtypes = (wintypes.HWND, ctypes.c_int)
        user32.UnregisterHotKey.restype = wintypes.BOOL
        self._user32 = user32

    def start(self) -> None:
        if self._registered:
            return

        application = QCoreApplication.instance()
        if application is None:
            raise RuntimeError("Cannot register Ctrl+0 before creating QApplication")
        if QThread.currentThread() is not application.thread():
            raise RuntimeError("Ctrl+0 must be registered from the QApplication thread")

        event_filter = _HotkeyEventFilter(self._activate)
        application.installNativeEventFilter(event_filter)
        self._filter = event_filter

        ctypes.set_last_error(0)
        if not self._user32.RegisterHotKey(
            None, _HOTKEY_ID, _MOD_CONTROL | _MOD_NOREPEAT, _VK_0
        ):
            error_code = ctypes.get_last_error()
            application.removeNativeEventFilter(event_filter)
            self._filter = None
            try:
                detail = ctypes.FormatError(error_code).strip()
            except OSError:
                detail = "unknown Win32 error"
            raise RuntimeError(
                f"Could not register global Ctrl+0 hotkey "
                f"(Win32 error {error_code}: {detail}). The shortcut may be in use."
            )

        self._registered = True

    def stop(self) -> None:
        if not self._registered and self._filter is None:
            return

        unregister_error: RuntimeError | None = None
        if self._registered:
            ctypes.set_last_error(0)
            if self._user32.UnregisterHotKey(None, _HOTKEY_ID):
                self._registered = False
            else:
                error_code = ctypes.get_last_error()
                try:
                    detail = ctypes.FormatError(error_code).strip()
                except OSError:
                    detail = "unknown Win32 error"
                unregister_error = RuntimeError(
                    f"Could not unregister global Ctrl+0 hotkey "
                    f"(Win32 error {error_code}: {detail})"
                )

        if self._filter is not None:
            application = QCoreApplication.instance()
            if application is not None:
                application.removeNativeEventFilter(self._filter)
            self._filter = None

        if unregister_error is not None:
            raise unregister_error

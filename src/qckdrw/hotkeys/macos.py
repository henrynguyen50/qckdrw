"""Carbon implementation of the Quick Canvas global hotkey."""

from __future__ import annotations

import ctypes
from collections.abc import Callable

from PySide6.QtCore import QCoreApplication, QThread

_CARBON_PATH = "/System/Library/Frameworks/Carbon.framework/Carbon"

_OS_STATUS = ctypes.c_int32
_UINT32 = ctypes.c_uint32
_BYTE_COUNT = ctypes.c_size_t

_K_EVENT_CLASS_KEYBOARD = int.from_bytes(b"keyb", "big")
_K_EVENT_HOTKEY_PRESSED = 6
_K_EVENT_PARAM_DIRECT_OBJECT = int.from_bytes(b"----", "big")
_TYPE_EVENT_HOTKEY_ID = int.from_bytes(b"hkid", "big")
_K_VK_ANSI_0 = 0x1D
_CMD_KEY = 0x0100
_HOTKEY_SIGNATURE = int.from_bytes(b"QCDR", "big")
_HOTKEY_ID = 1
_EVENT_NOT_HANDLED_ERR = -9874


class _EventTypeSpec(ctypes.Structure):
    _fields_ = (("eventClass", _UINT32), ("eventKind", _UINT32))


class _EventHotKeyID(ctypes.Structure):
    _fields_ = (("signature", _UINT32), ("id", _UINT32))


_EventHandlerCallback = ctypes.CFUNCTYPE(
    _OS_STATUS,
    ctypes.c_void_p,  # EventHandlerCallRef
    ctypes.c_void_p,  # EventRef
    ctypes.c_void_p,  # userData
)


def _status_text(operation: str, status: int) -> str:
    unsigned = ctypes.c_uint32(status).value
    return f"{operation} failed with OSStatus {status} (0x{unsigned:08X})"


class MacOSHotkeyBackend:
    """Owns one Carbon Cmd+0 application hotkey and event handler."""

    def __init__(self, activate: Callable[[], None]) -> None:
        self._activate = activate
        self._handler_ref = ctypes.c_void_p()
        self._hotkey_ref = ctypes.c_void_p()
        # Carbon stores this function pointer; it must remain strongly held for
        # the complete lifetime of the installed handler.
        self._callback = _EventHandlerCallback(self._handle_event)

        carbon = ctypes.CDLL(_CARBON_PATH)
        carbon.GetApplicationEventTarget.argtypes = ()
        carbon.GetApplicationEventTarget.restype = ctypes.c_void_p

        carbon.InstallEventHandler.argtypes = (
            ctypes.c_void_p,
            _EventHandlerCallback,
            _UINT32,
            ctypes.POINTER(_EventTypeSpec),
            ctypes.c_void_p,
            ctypes.POINTER(ctypes.c_void_p),
        )
        carbon.InstallEventHandler.restype = _OS_STATUS

        carbon.RegisterEventHotKey.argtypes = (
            _UINT32,
            _UINT32,
            _EventHotKeyID,
            ctypes.c_void_p,
            _UINT32,
            ctypes.POINTER(ctypes.c_void_p),
        )
        carbon.RegisterEventHotKey.restype = _OS_STATUS

        carbon.GetEventParameter.argtypes = (
            ctypes.c_void_p,
            _UINT32,
            _UINT32,
            ctypes.POINTER(_UINT32),
            _BYTE_COUNT,
            ctypes.POINTER(_BYTE_COUNT),
            ctypes.c_void_p,
        )
        carbon.GetEventParameter.restype = _OS_STATUS

        carbon.UnregisterEventHotKey.argtypes = (ctypes.c_void_p,)
        carbon.UnregisterEventHotKey.restype = _OS_STATUS
        carbon.RemoveEventHandler.argtypes = (ctypes.c_void_p,)
        carbon.RemoveEventHandler.restype = _OS_STATUS
        self._carbon = carbon

    def _handle_event(
        self, _next_handler: int, event: int, _user_data: int
    ) -> int:
        hotkey_id = _EventHotKeyID()
        actual_size = _BYTE_COUNT()
        status = self._carbon.GetEventParameter(
            event,
            _K_EVENT_PARAM_DIRECT_OBJECT,
            _TYPE_EVENT_HOTKEY_ID,
            None,
            ctypes.sizeof(hotkey_id),
            ctypes.byref(actual_size),
            ctypes.byref(hotkey_id),
        )
        if (
            status != 0
            or actual_size.value != ctypes.sizeof(hotkey_id)
            or hotkey_id.signature != _HOTKEY_SIGNATURE
            or hotkey_id.id != _HOTKEY_ID
        ):
            return _EVENT_NOT_HANDLED_ERR

        self._activate()
        return 0

    def start(self) -> None:
        if self._hotkey_ref.value is not None:
            return

        application = QCoreApplication.instance()
        if application is None:
            raise RuntimeError("Cannot register Cmd+0 before creating QApplication")
        if QThread.currentThread() is not application.thread():
            raise RuntimeError("Cmd+0 must be registered from the QApplication thread")

        target = self._carbon.GetApplicationEventTarget()
        if not target:
            raise RuntimeError("Could not obtain the Carbon application event target")

        event_type = _EventTypeSpec(
            _K_EVENT_CLASS_KEYBOARD, _K_EVENT_HOTKEY_PRESSED
        )
        handler_ref = ctypes.c_void_p()
        status = self._carbon.InstallEventHandler(
            target,
            self._callback,
            1,
            ctypes.byref(event_type),
            None,
            ctypes.byref(handler_ref),
        )
        if status != 0:
            raise RuntimeError(_status_text("InstallEventHandler", status))
        if handler_ref.value is None:
            raise RuntimeError("InstallEventHandler succeeded without returning a handler")
        self._handler_ref = handler_ref

        hotkey_ref = ctypes.c_void_p()
        status = self._carbon.RegisterEventHotKey(
            _K_VK_ANSI_0,
            _CMD_KEY,
            _EventHotKeyID(_HOTKEY_SIGNATURE, _HOTKEY_ID),
            target,
            0,
            ctypes.byref(hotkey_ref),
        )
        if status == 0 and hotkey_ref.value is not None:
            self._hotkey_ref = hotkey_ref
            return

        registration_error = (
            _status_text("RegisterEventHotKey", status)
            if status != 0
            else "RegisterEventHotKey succeeded without returning a hotkey reference"
        )
        cleanup_status = self._carbon.RemoveEventHandler(self._handler_ref)
        if cleanup_status == 0:
            self._handler_ref = ctypes.c_void_p()
        else:
            registration_error += "; " + _status_text(
                "partial-failure RemoveEventHandler cleanup", cleanup_status
            )
        raise RuntimeError(
            f"Could not register global Cmd+0 hotkey. The shortcut may be in use: "
            f"{registration_error}"
        )

    def stop(self) -> None:
        errors: list[str] = []

        if self._hotkey_ref.value is not None:
            status = self._carbon.UnregisterEventHotKey(self._hotkey_ref)
            if status == 0:
                self._hotkey_ref = ctypes.c_void_p()
            else:
                errors.append(_status_text("UnregisterEventHotKey", status))

        if self._handler_ref.value is not None:
            status = self._carbon.RemoveEventHandler(self._handler_ref)
            if status == 0:
                self._handler_ref = ctypes.c_void_p()
            else:
                errors.append(_status_text("RemoveEventHandler", status))

        if errors:
            raise RuntimeError("; ".join(errors))

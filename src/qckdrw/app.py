from __future__ import annotations

import gc
from collections.abc import Callable
from typing import Protocol, cast

from PySide6.QtCore import QObject, QSettings, Qt, QTimer, Signal
from PySide6.QtGui import QAction, QColor, QIcon, QPainter, QPen, QPixmap
from PySide6.QtWidgets import QApplication, QMainWindow, QMenu, QMessageBox, QSystemTrayIcon

from qckdrw import autostart
from qckdrw.hotkeys import GlobalHotkey


class CanvasWindow(Protocol):
    dismissed: Signal
    completed: Signal

    def serialize_document(self) -> bytes: ...
    def release_resources(self) -> None: ...
    def deleteLater(self) -> None: ...
    def isMinimized(self) -> bool: ...
    def showNormal(self) -> None: ...
    def show(self) -> None: ...
    def raise_(self) -> None: ...
    def activateWindow(self) -> None: ...


WindowFactory = Callable[[bytes | None], QMainWindow]


def _tray_icon() -> QIcon:
    pixmap = QPixmap(64, 64)
    pixmap.fill(Qt.GlobalColor.transparent)
    painter = QPainter(pixmap)
    painter.setRenderHint(QPainter.RenderHint.Antialiasing)
    painter.setPen(QPen(QColor("#334155"), 3))
    painter.setBrush(QColor("#ffffff"))
    painter.drawRoundedRect(8, 8, 48, 48, 7, 7)
    painter.setPen(QPen(QColor("#2563eb"), 7, Qt.PenStyle.SolidLine, Qt.PenCapStyle.RoundCap))
    painter.drawLine(19, 43, 43, 19)
    painter.setPen(QPen(QColor("#93c5fd"), 3, Qt.PenStyle.SolidLine, Qt.PenCapStyle.RoundCap))
    painter.drawLine(18, 44, 25, 46)
    painter.end()
    return QIcon(pixmap)


class QuickCanvasApplication(QApplication):
    """Long-lived, windowless-until-activated Quick Canvas application."""

    def __init__(
        self,
        argv: list[str],
        window_factory: WindowFactory,
        *,
        hotkey_factory: Callable[[QObject], GlobalHotkey] = GlobalHotkey,
    ) -> None:
        super().__init__(argv)
        self.setQuitOnLastWindowClosed(False)
        self._window_factory = window_factory
        self._window: CanvasWindow | None = None
        self._document: bytes | None = None
        self._cleaned_up = False

        icon = _tray_icon()
        self.setWindowIcon(icon)
        self._tray = QSystemTrayIcon(icon, self)
        self._tray.setToolTip("Quick Canvas")
        self._menu = QMenu()
        self._open_action = QAction("Open", self._menu)
        self._open_action.triggered.connect(self.open_canvas)
        self._menu.addAction(self._open_action)
        self._autostart_action = QAction("Launch on Login", self._menu)
        self._autostart_action.setCheckable(True)
        self._autostart_action.triggered.connect(self._set_autostart)
        self._menu.addAction(self._autostart_action)
        self._menu.addSeparator()
        quit_action = QAction("Quit", self._menu)
        quit_action.triggered.connect(self.quit)
        self._menu.addAction(quit_action)
        self._tray.setContextMenu(self._menu)
        self._tray.activated.connect(self._tray_activated)
        self._tray.show()
        if not QSystemTrayIcon.isSystemTrayAvailable():
            self.report_error(
                "System Tray Unavailable",
                "Quick Canvas requires a system tray or menu bar to remain accessible.",
            )

        self._initialize_autostart()
        self._hotkey = hotkey_factory(self)
        self._hotkey.activated.connect(
            self.open_canvas, Qt.ConnectionType.QueuedConnection
        )
        try:
            self._hotkey.start()
        except Exception as error:
            self.report_error("Global Shortcut Unavailable", str(error))
        self.aboutToQuit.connect(self._cleanup)

    @property
    def document_snapshot(self) -> bytes | None:
        return self._document

    @property
    def canvas_window(self) -> CanvasWindow | None:
        return self._window

    def report_error(self, title: str, detail: str) -> None:
        message = detail or "An unknown error occurred."
        self._tray.showMessage(title, message, QSystemTrayIcon.MessageIcon.Critical)
        QTimer.singleShot(
            0,
            lambda: QMessageBox.critical(None, title, message),
        )

    def _initialize_autostart(self) -> None:
        settings = QSettings()
        initialized = settings.value("autostart/initialized", False, type=bool)
        try:
            if not initialized:
                autostart.set_enabled(True)
                settings.setValue("autostart/initialized", True)
            elif autostart.is_registered() and not autostart.is_enabled():
                autostart.set_enabled(True)
            enabled = autostart.is_enabled()
        except Exception as error:
            enabled = False
            self.report_error("Launch on Login Error", str(error))
        self._autostart_action.setChecked(enabled)

    def _set_autostart(self, enabled: bool) -> None:
        try:
            autostart.set_enabled(enabled)
            actual = autostart.is_enabled()
            self._autostart_action.setChecked(actual)
            if actual != enabled:
                raise RuntimeError("The operating system did not retain the requested setting.")
        except Exception as error:
            try:
                self._autostart_action.setChecked(autostart.is_enabled())
            except Exception:
                self._autostart_action.setChecked(not enabled)
            self.report_error("Launch on Login Error", str(error))

    def _tray_activated(self, reason: QSystemTrayIcon.ActivationReason) -> None:
        if reason in (
            QSystemTrayIcon.ActivationReason.Trigger,
            QSystemTrayIcon.ActivationReason.DoubleClick,
        ):
            self.open_canvas()

    def open_canvas(self) -> None:
        if self._window is None:
            try:
                window = cast(CanvasWindow, self._window_factory(self._document))
                window.dismissed.connect(lambda: self._dismiss(window))
                window.completed.connect(lambda: self._complete(window))
                self._window = window
                self._document = None
            except Exception as error:
                self.report_error("Unable to Open Canvas", str(error))
                return
        window = self._window
        if window.isMinimized():
            window.showNormal()
        else:
            window.show()
        window.raise_()
        window.activateWindow()

    def _dismiss(self, window: CanvasWindow) -> None:
        if window is not self._window:
            return
        try:
            snapshot = bytes(window.serialize_document())
        except Exception as error:
            self.report_error("Unable to Preserve Canvas", str(error))
            return
        self._document = snapshot
        self._release(window)

    def _complete(self, window: CanvasWindow) -> None:
        if window is not self._window:
            return
        self._document = None
        self._release(window)

    def _release(self, window: CanvasWindow) -> None:
        self._window = None
        try:
            window.release_resources()
        except Exception as error:
            self.report_error("Canvas Cleanup Error", str(error))
        finally:
            window.deleteLater()
            gc.collect()

    def _cleanup(self) -> None:
        if self._cleaned_up:
            return
        self._cleaned_up = True
        try:
            self._hotkey.stop()
        except Exception:
            pass
        if self._window is not None:
            window = self._window
            self._window = None
            try:
                window.release_resources()
            except Exception:
                pass
            finally:
                window.deleteLater()
        self._tray.hide()

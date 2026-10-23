from __future__ import annotations

import sys
import traceback
from pathlib import Path

from PySide6.QtCore import QLockFile, QStandardPaths
from PySide6.QtWidgets import QApplication, QMainWindow, QMessageBox

from qckdrw.app import QuickCanvasApplication


def _window_factory(document: bytes | None) -> QMainWindow:
    # Deliberately delayed: the resident background process does not load canvas
    # graphics or fail merely because no canvas has been opened yet.
    from qckdrw.window import CanvasWindow

    return CanvasWindow(document)


def _show_fatal_error(title: str, message: str) -> None:
    application = QApplication.instance()
    if application is not None:
        QMessageBox.critical(None, title, message)
        return
    if sys.platform == "win32":
        try:
            import ctypes

            ctypes.windll.user32.MessageBoxW(None, message, title, 0x10)
            return
        except Exception:
            pass
    print(f"{title}: {message}", file=sys.stderr)


def _instance_lock() -> QLockFile:
    location = QStandardPaths.writableLocation(
        QStandardPaths.StandardLocation.AppLocalDataLocation
    )
    if not location:
        raise RuntimeError("Qt could not determine an application data directory.")
    directory = Path(location)
    directory.mkdir(parents=True, exist_ok=True)
    lock = QLockFile(str(directory / "instance.lock"))
    lock.setStaleLockTime(0)
    return lock


def main() -> int:
    QApplication.setOrganizationName("QuickCanvas")
    QApplication.setOrganizationDomain("qckdrw.com")
    QApplication.setApplicationName("Quick Canvas")

    lock: QLockFile | None = None
    try:
        lock = _instance_lock()
        if not lock.tryLock(0):
            error = lock.error()
            if error == QLockFile.LockError.LockFailedError:
                return 0
            raise RuntimeError(
                f"Could not acquire the Quick Canvas instance lock: {error.name}."
            )

        app = QuickCanvasApplication(sys.argv, _window_factory)

        def report_uncaught(
            exception_type: type[BaseException],
            exception: BaseException,
            exception_traceback: object,
        ) -> None:
            detail = "".join(
                traceback.format_exception(
                    exception_type, exception, exception_traceback  # type: ignore[arg-type]
                )
            )
            app.report_error("Unexpected Quick Canvas Error", detail)

        sys.excepthook = report_uncaught
        return app.exec()
    except Exception as error:
        detail = "".join(traceback.format_exception(type(error), error, error.__traceback__))
        _show_fatal_error("Quick Canvas Startup Error", detail)
        return 1
    finally:
        if lock is not None and lock.isLocked():
            lock.unlock()


if __name__ == "__main__":
    raise SystemExit(main())

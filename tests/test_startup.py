from __future__ import annotations

import os
import plistlib
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtCore import QLockFile

from qckdrw import autostart
from qckdrw.app import QuickCanvasApplication
from qckdrw import main as startup


class _FailedLock:
    def __init__(self, error: QLockFile.LockError) -> None:
        self._error = error

    def tryLock(self, timeout: int) -> bool:
        self.timeout = timeout
        return False

    def error(self) -> QLockFile.LockError:
        return self._error

    def isLocked(self) -> bool:
        return False


class InstanceFailureTests(unittest.TestCase):
    def test_existing_instance_exits_cleanly(self) -> None:
        lock = _FailedLock(QLockFile.LockError.LockFailedError)
        with (
            patch.object(startup, "_instance_lock", return_value=lock),
            patch.object(startup, "_show_fatal_error") as show_error,
        ):
            self.assertEqual(startup.main(), 0)
        show_error.assert_not_called()

    def test_lock_permission_failure_reaches_fatal_handler(self) -> None:
        lock = _FailedLock(QLockFile.LockError.PermissionError)
        with (
            patch.object(startup, "_instance_lock", return_value=lock),
            patch.object(startup, "_show_fatal_error") as show_error,
        ):
            self.assertEqual(startup.main(), 1)
        title, detail = show_error.call_args.args
        self.assertEqual(title, "Quick Canvas Startup Error")
        self.assertIn("PermissionError", detail)


class MacAutostartTests(unittest.TestCase):
    def test_framework_python_source_launches_module_not_python_app(self) -> None:
        framework_python = (
            "/Library/Frameworks/Python.framework/Versions/3.14/Resources/"
            "Python.app/Contents/MacOS/Python"
        )
        with (
            patch.object(sys, "executable", framework_python),
            patch.object(sys, "frozen", False, create=True),
        ):
            self.assertEqual(
                autostart._mac_program_arguments(),
                [framework_python, "-m", "qckdrw.main"],
            )

    def test_stale_owned_launch_agent_is_present_but_not_enabled(self) -> None:
        with tempfile.TemporaryDirectory() as temporary_directory:
            agent_path = Path(temporary_directory) / "com.qckdrw.canvas.plist"
            old_arguments = ["/old/Python", "-m", "qckdrw.main"]
            agent_path.write_bytes(
                plistlib.dumps(
                    {
                        "Label": "com.qckdrw.canvas",
                        "ProgramArguments": old_arguments,
                        "RunAtLoad": True,
                    }
                )
            )
            with (
                patch.object(sys, "platform", "darwin"),
                patch.object(sys, "executable", "/new/Python"),
                patch.object(sys, "frozen", False, create=True),
                patch.object(autostart, "_launch_agent_path", return_value=agent_path),
            ):
                self.assertTrue(autostart.is_registered())
                self.assertFalse(autostart.is_enabled())
                autostart.set_enabled(True)
                self.assertTrue(autostart.is_enabled())
                payload = plistlib.loads(agent_path.read_bytes())
                self.assertEqual(
                    payload["ProgramArguments"],
                    ["/new/Python", "-m", "qckdrw.main"],
                )


class _Settings:
    def __init__(self, initialized: bool) -> None:
        self.initialized = initialized

    def value(self, key: str, default: bool, *, type: type[bool]) -> bool:
        del key, default, type
        return self.initialized

    def setValue(self, key: str, value: bool) -> None:
        del key
        self.initialized = value


class _Action:
    def __init__(self) -> None:
        self.checked: bool | None = None

    def setChecked(self, checked: bool) -> None:
        self.checked = checked


class _AutostartApplication:
    _initialize_autostart = QuickCanvasApplication._initialize_autostart

    def __init__(self) -> None:
        self._autostart_action = _Action()
        self.errors: list[tuple[str, str]] = []

    def report_error(self, title: str, detail: str) -> None:
        self.errors.append((title, detail))


class AutostartInitializationTests(unittest.TestCase):
    def test_initialized_stale_registration_is_refreshed(self) -> None:
        application = _AutostartApplication()
        current = False

        def set_enabled(enabled: bool) -> None:
            nonlocal current
            current = enabled

        with (
            patch("qckdrw.app.QSettings", return_value=_Settings(True)),
            patch.object(autostart, "is_registered", return_value=True),
            patch.object(autostart, "is_enabled", side_effect=lambda: current),
            patch.object(autostart, "set_enabled", side_effect=set_enabled) as setter,
        ):
            application._initialize_autostart()

        setter.assert_called_once_with(True)
        self.assertTrue(application._autostart_action.checked)
        self.assertEqual(application.errors, [])

    def test_initialized_absent_registration_remains_disabled(self) -> None:
        application = _AutostartApplication()
        with (
            patch("qckdrw.app.QSettings", return_value=_Settings(True)),
            patch.object(autostart, "is_registered", return_value=False),
            patch.object(autostart, "is_enabled", return_value=False),
            patch.object(autostart, "set_enabled") as setter,
        ):
            application._initialize_autostart()

        setter.assert_not_called()
        self.assertFalse(application._autostart_action.checked)
        self.assertEqual(application.errors, [])


class InstanceLockTests(unittest.TestCase):
    def test_live_process_lock_is_never_reaped_by_age(self) -> None:
        child_code = """
import os
import sys
from PySide6.QtCore import QLockFile
lock = QLockFile(sys.argv[1])
lock.setStaleLockTime(0)
if not lock.tryLock(0):
    raise SystemExit(2)
try:
    os.utime(sys.argv[1], (1, 1))
    print('locked', flush=True)
    sys.stdin.readline()
finally:
    lock.unlock()
"""
        with tempfile.TemporaryDirectory() as temporary_directory:
            lock_path = Path(temporary_directory) / "instance.lock"
            with subprocess.Popen(
                [sys.executable, "-c", child_code, str(lock_path)],
                stdin=subprocess.PIPE,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                text=True,
            ) as child:
                contender = None
                try:
                    self.assertEqual(child.stdout.readline().strip(), "locked")
                    contender = QLockFile(str(lock_path))
                    contender.setStaleLockTime(0)
                    self.assertFalse(contender.tryLock(0))
                    self.assertEqual(
                        contender.error(), QLockFile.LockError.LockFailedError
                    )
                finally:
                    if contender is not None:
                        if contender.isLocked():
                            contender.unlock()
                        del contender

from __future__ import annotations

import os
import plistlib
import subprocess
import sys
from pathlib import Path

_APP_NAME = "QuickCanvas"
_RUN_KEY = r"Software\Microsoft\Windows\CurrentVersion\Run"
_LAUNCH_AGENT_ID = "com.qckdrw.canvas"


def _windows_command() -> str:
    if getattr(sys, "frozen", False):
        executable = Path(sys.executable)
        arguments: list[str] = []
    else:
        executable = Path(sys.executable)
        if executable.name.lower() == "python.exe":
            candidate = executable.with_name("pythonw.exe")
            if candidate.is_file():
                executable = candidate
        arguments = ["-m", "qckdrw.main"]
    return subprocess.list2cmdline([str(executable), *arguments])


def _mac_bundle() -> Path | None:
    executable = Path(sys.executable).resolve()
    for parent in (executable, *executable.parents):
        if parent.suffix == ".app":
            return parent
    return None


def _launch_agent_path() -> Path:
    return Path.home() / "Library" / "LaunchAgents" / f"{_LAUNCH_AGENT_ID}.plist"


def _mac_program_arguments() -> list[str]:
    if getattr(sys, "frozen", False):
        bundle = _mac_bundle()
        if bundle is not None:
            return ["/usr/bin/open", "-a", str(bundle)]
    return [sys.executable, "-m", "qckdrw.main"]


def _mac_launch_agent() -> dict[object, object] | None:
    try:
        with _launch_agent_path().open("rb") as stream:
            payload = plistlib.load(stream)
    except (FileNotFoundError, OSError, plistlib.InvalidFileException):
        return None
    return payload if isinstance(payload, dict) else None


def is_registered() -> bool:
    """Return whether an autostart entry owned by Quick Canvas is present."""
    if sys.platform == "win32":
        import winreg

        try:
            with winreg.OpenKey(winreg.HKEY_CURRENT_USER, _RUN_KEY) as key:
                winreg.QueryValueEx(key, _APP_NAME)
        except FileNotFoundError:
            return False
        return True
    if sys.platform == "darwin":
        payload = _mac_launch_agent()
        return payload is not None and payload.get("Label") == _LAUNCH_AGENT_ID
    return False


def is_enabled() -> bool:
    if sys.platform == "win32":
        import winreg

        try:
            with winreg.OpenKey(winreg.HKEY_CURRENT_USER, _RUN_KEY) as key:
                value, _ = winreg.QueryValueEx(key, _APP_NAME)
        except FileNotFoundError:
            return False
        return value == _windows_command()
    if sys.platform == "darwin":
        payload = _mac_launch_agent()
        return (
            payload is not None
            and payload.get("Label") == _LAUNCH_AGENT_ID
            and payload.get("RunAtLoad") is True
            and payload.get("ProgramArguments") == _mac_program_arguments()
        )
    return False


def set_enabled(enabled: bool) -> None:
    if sys.platform == "win32":
        import winreg

        if enabled:
            with winreg.CreateKey(winreg.HKEY_CURRENT_USER, _RUN_KEY) as key:
                winreg.SetValueEx(key, _APP_NAME, 0, winreg.REG_SZ, _windows_command())
        else:
            try:
                with winreg.OpenKey(
                    winreg.HKEY_CURRENT_USER, _RUN_KEY, 0, winreg.KEY_SET_VALUE
                ) as key:
                    winreg.DeleteValue(key, _APP_NAME)
            except FileNotFoundError:
                pass
        return
    if sys.platform == "darwin":
        path = _launch_agent_path()
        if not enabled:
            path.unlink(missing_ok=True)
            return
        path.parent.mkdir(parents=True, exist_ok=True)
        payload = {
            "Label": _LAUNCH_AGENT_ID,
            "ProgramArguments": _mac_program_arguments(),
            "RunAtLoad": True,
        }
        temporary = path.with_name(f".{path.name}.{os.getpid()}.tmp")
        try:
            with temporary.open("wb") as stream:
                plistlib.dump(payload, stream, sort_keys=True)
            os.replace(temporary, path)
        finally:
            temporary.unlink(missing_ok=True)
        return
    raise RuntimeError(f"Launch on login is not supported on {sys.platform!r}")

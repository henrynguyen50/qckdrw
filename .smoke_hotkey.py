import ctypes
import subprocess
import sys
import threading
from PySide6.QtCore import QTimer
from PySide6.QtWidgets import QApplication
from qckdrw.hotkeys import GlobalHotkey

app = QApplication([])
app.setQuitOnLastWindowClosed(False)
hotkey = GlobalHotkey()
received = []
hotkey.activated.connect(lambda: received.append(threading.get_ident()))
hotkey.start()
# A genuinely separate process must not be able to claim Ctrl+0.
probe = "import ctypes; u=ctypes.WinDLL('user32',use_last_error=True); ok=u.RegisterHotKey(None,7319,0x4002,0x30); print(ok); u.UnregisterHotKey(None,7319) if ok else None"
p = subprocess.run([sys.executable, '-c', probe], capture_output=True, text=True, check=True)
assert p.stdout.strip() == '0', p.stdout
u = ctypes.WinDLL('user32', use_last_error=True)
def press():
    u.keybd_event(0x11, 0, 0, 0)
    u.keybd_event(0x30, 0, 0, 0)
    u.keybd_event(0x30, 0, 2, 0)
    u.keybd_event(0x11, 0, 2, 0)
QTimer.singleShot(100, press)
QTimer.singleShot(800, app.quit)
app.exec()
assert received == [threading.get_ident()], received
hotkey.stop()
p = subprocess.run([sys.executable, '-c', probe], capture_output=True, text=True, check=True)
assert p.stdout.strip() == '1', p.stdout
print('PASS: real Win32 Ctrl+0 registration, conflict rejection, OS key dispatch on GUI thread, unregister/reclaim')

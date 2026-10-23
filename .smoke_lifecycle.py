import ctypes
import gc
import time
import winreg
from PySide6.QtCore import QCoreApplication, QEvent, QSettings, QTimer, Signal
from PySide6.QtWidgets import QMainWindow
from qckdrw import autostart
from qckdrw.app import QuickCanvasApplication

run_key = r'Software\Microsoft\Windows\CurrentVersion\Run'
try:
    with winreg.OpenKey(winreg.HKEY_CURRENT_USER, run_key) as key:
        old = winreg.QueryValueEx(key, 'QuickCanvas')
except FileNotFoundError:
    old = None
QCoreApplication.setOrganizationName('QuickCanvasSmoke')
QCoreApplication.setApplicationName('ActivationSmoke')
settings = QSettings()
settings.setValue('autostart/initialized', True)
class Surface(QMainWindow):
    dismissed = Signal()
    completed = Signal()
    def __init__(self, document):
        super().__init__()
        self.document = document or b'preserved drawing'
        self.released = False
    def serialize_document(self):
        return self.document
    def release_resources(self):
        self.released = True
        self.hide()
app = None
try:
    autostart.set_enabled(True)
    assert autostart.is_enabled()
    with winreg.OpenKey(winreg.HKEY_CURRENT_USER, run_key) as key:
        value, _ = winreg.QueryValueEx(key, 'QuickCanvas')
    assert 'pythonw.exe' in value and '-m qckdrw.main' in value, value
    autostart.set_enabled(False)
    assert not autostart.is_enabled()
    app = QuickCanvasApplication([], Surface)
    assert app.canvas_window is None
    assert not any(w.isVisible() for w in app.topLevelWidgets())
    app.open_canvas()
    window = app.canvas_window
    app.processEvents()
    assert window.isVisible()
    window.dismissed.emit()
    assert app.canvas_window is None and app.document_snapshot == b'preserved drawing'
    assert window.released
    QCoreApplication.sendPostedEvents(None, QEvent.Type.DeferredDelete)
    del window
    gc.collect()
    app.open_canvas()
    window = app.canvas_window
    assert window.document == b'preserved drawing'
    window.completed.emit()
    assert app.canvas_window is None and app.document_snapshot is None
    QCoreApplication.sendPostedEvents(None, QEvent.Type.DeferredDelete)
    del window
    gc.collect()
    start_cpu = time.process_time()
    start = time.perf_counter()
    QTimer.singleShot(5000, app.quit)
    app.exec()
    elapsed = time.perf_counter() - start
    cpu = time.process_time() - start_cpu
    print(f'PASS: tray starts hidden; real registry enable/disable; dismissed snapshot survives; completed snapshot cleared; hidden idle {elapsed:.2f}s / {cpu:.6f}s CPU ({100*cpu/elapsed:.3f}% one core)')
finally:
    if app:
        app._cleanup()
    with winreg.CreateKey(winreg.HKEY_CURRENT_USER, run_key) as key:
        if old is None:
            try: winreg.DeleteValue(key, 'QuickCanvas')
            except FileNotFoundError: pass
        else:
            winreg.SetValueEx(key, 'QuickCanvas', 0, old[1], old[0])
    settings.clear()

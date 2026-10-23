import ctypes
import gc
import sys
import time
from PySide6.QtCore import QCoreApplication, QEvent, QPointF, QProcess, QSettings, Qt, QTimer
from PySide6.QtGui import QColor, QImage, QMouseEvent
from PySide6.QtTest import QTest
from qckdrw.app import QuickCanvasApplication
from qckdrw.canvas.items import EditableTextItem
from qckdrw.window import CanvasWindow

QCoreApplication.setOrganizationName('QuickCanvasSmoke')
QCoreApplication.setApplicationName('CompletionSmoke')
settings=QSettings()
settings.setValue('autostart/initialized',True)
app=QuickCanvasApplication([],CanvasWindow)
reader=QProcess(app)
result=[]

def hotkey():
    u=ctypes.windll.user32
    for key,flags in [(0x11,0),(0x30,0),(0x30,2),(0x11,2)]: u.keybd_event(key,0,flags,0)
    QTest.qWait(100)

def native_image_reader():
    code="""from PySide6.QtWidgets import QApplication
from PySide6.QtGui import QColor
app=QApplication([])
image=app.clipboard().image()
assert not image.isNull(), 'clipboard contains no readable image'
assert (image.width(),image.height())==(1200,800), image.size()
assert image.pixelColor(0,0)==QColor('white')
assert image.pixelColor(550,380).red()>180 and image.pixelColor(550,380).green()<130
assert any(image.pixelColor(x,y).lightness()<160 for x in range(90,310) for y in range(90,180)), 'active stroke lost'
assert all(image.pixelColor(x,y).alpha()==255 for x,y in [(0,0),(550,380),(1199,799)])
image.save('.smoke_export.png')
print('PASS: independent process reads concrete opaque 1200x800 clipboard image, white background, pasted image and committed active raw stroke')
"""
    reader.start(sys.executable,['-c',code])

def reader_finished(exit_code,status):
    output=bytes(reader.readAllStandardOutput()).decode()
    errors=bytes(reader.readAllStandardError()).decode()
    print(output,end='')
    if exit_code!=0:
        result.append(False)
        print(errors)
        app.quit()
        return
    result.append(True)
    QCoreApplication.sendPostedEvents(None,QEvent.Type.DeferredDelete)
    gc.collect()
    start=time.process_time()
    wall=time.perf_counter()
    def idle_finished():
        cpu=time.process_time()-start
        elapsed=time.perf_counter()-wall
        print(f'Hidden after Done: {elapsed:.3f}s elapsed, {cpu:.6f}s process CPU ({100*cpu/elapsed:.3f}% one core)')
        app.quit()
    QTimer.singleShot(5000,idle_finished)

reader.finished.connect(reader_finished)
try:
    hotkey()
    w=app.canvas_window
    assert w and w.isVisible()
    image=QImage(200,100,QImage.Format.Format_ARGB32_Premultiplied)
    image.fill(QColor('#e64b35'))
    app.clipboard().setImage(image)
    w.paste()
    app.clipboard().setText('Raw canvas clipboard')
    w.paste()
    text=next(i for i in w.scene.items() if isinstance(i,EditableTextItem))
    text.setPos(500,550)
    w._set_tool('draw')
    vp=w.view.viewport()
    def click(x,y): QTest.mouseClick(vp,Qt.MouseButton.LeftButton,pos=w.view.mapFromScene(QPointF(x,y)))
    click(100,100)
    for x,y in [(180,160),(240,110),(300,150)]:
        pos=w.view.mapFromScene(QPointF(x,y))
        event=QMouseEvent(QEvent.Type.MouseMove,QPointF(pos),QPointF(vp.mapToGlobal(pos)),Qt.MouseButton.NoButton,Qt.MouseButton.NoButton,Qt.KeyboardModifier.NoModifier)
        QCoreApplication.sendEvent(vp,event)
    assert w.view.drawing
    w.grab().save('.smoke_final_window.png')
    # Real toolbar click finalizes the still-active stroke and copies, then hides.
    done_button=w._toolbar.widgetForAction(w._done_action)
    QTest.mouseClick(done_button,Qt.MouseButton.LeftButton)
    assert app.canvas_window is None and app.document_snapshot is None
    assert not w.scene.items() and w.scene.undo_stack.count()==0
    assert not w.isVisible()
    # Reopening after Done must create an empty document.
    QCoreApplication.sendPostedEvents(None,QEvent.Type.DeferredDelete)
    hotkey()
    fresh=app.canvas_window
    assert fresh and not fresh.scene.items()
    # Dismiss the fresh document without touching exported clipboard contents.
    fresh.close()
    QCoreApplication.sendPostedEvents(None,QEvent.Type.DeferredDelete)
    native_image_reader()
    QTimer.singleShot(15000,app.quit)
    app.exec()
    assert result==[True],result
finally:
    app._cleanup()
    settings.clear()

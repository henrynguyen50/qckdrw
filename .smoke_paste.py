import ctypes
from PySide6.QtCore import QCoreApplication, QEvent, QPointF, QSettings, Qt
from PySide6.QtGui import QColor, QImage
from PySide6.QtTest import QTest
from qckdrw.app import QuickCanvasApplication
from qckdrw.canvas.items import EditableTextItem, ResizablePixmapItem
from qckdrw.window import CanvasWindow
QCoreApplication.setOrganizationName('QuickCanvasSmoke')
QCoreApplication.setApplicationName('PasteSmoke')
settings=QSettings()
settings.setValue('autostart/initialized',True)
app=QuickCanvasApplication([],CanvasWindow)
u=ctypes.windll.user32

def settle():
    QTest.qSleep(35)
    app.processEvents()
    QTest.qSleep(35)
    app.processEvents()
def move(view,point):
    pos=view.viewport().mapToGlobal(view.mapFromScene(point))
    assert u.SetCursorPos(pos.x(),pos.y())
    settle()
def drag(view,start,end):
    move(view,start)
    u.mouse_event(2,0,0,0,0)
    settle()
    for i in range(1,6): move(view,start+(end-start)*(i/5))
    u.mouse_event(4,0,0,0,0)
    settle()
try:
    app.open_canvas()
    w=app.canvas_window
    app.processEvents()
    image=QImage(200,100,QImage.Format.Format_ARGB32_Premultiplied)
    image.fill(QColor('#e64b35'))
    app.clipboard().setImage(image)
    QTest.keyClick(w.view.viewport(),Qt.Key.Key_V,Qt.KeyboardModifier.ControlModifier)
    app.processEvents()
    item=next(i for i in w.scene.items() if isinstance(i,ResizablePixmapItem))
    assert item.isSelected() and w.view.tool=='select'
    start=item.mapToScene(item.content_rect.center())
    original=QPointF(item.pos())
    drag(w.view,start,start+QPointF(-230,-130))
    assert (item.pos()-original-QPointF(-230,-130)).manhattanLength()<5,(item.pos(),original)
    before=item.content_rect
    anchor=item.mapToScene(before.topLeft())
    corner=item.mapToScene(before.bottomRight())
    drag(w.view,corner,corner+QPointF(80,40))
    assert item.content_rect.width()>before.width()+60,item.content_rect
    assert (item.mapToScene(item.content_rect.topLeft())-anchor).manhattanLength()<3
    app.clipboard().setText('Raw canvas\nsecond line')
    QTest.keyClick(w.view.viewport(),Qt.Key.Key_V,Qt.KeyboardModifier.ControlModifier)
    app.processEvents()
    text=next(i for i in w.scene.items() if isinstance(i,EditableTextItem))
    center=text.mapToScene(text.boundingRect().center())
    oldpos=QPointF(text.pos())
    drag(w.view,center,center+QPointF(100,100))
    assert (text.pos()-oldpos-QPointF(100,100)).manhattanLength()<5
    local=w.view.mapFromScene(text.mapToScene(text.boundingRect().center()))
    QTest.mouseDClick(w.view.viewport(),Qt.MouseButton.LeftButton,pos=local)
    app.processEvents()
    assert text.editing
    QTest.keyClick(w.view.viewport(),Qt.Key.Key_End,Qt.KeyboardModifier.ControlModifier)
    QTest.keyClicks(w.view.viewport(),' edited')
    assert text.toPlainText()=='Raw canvas\nsecond line edited',repr(text.toPlainText())
    # Native keyboard paste while editing must append text, not create another item.
    app.clipboard().setText(' pasted')
    u.keybd_event(0x11,0,0,0);u.keybd_event(0x56,0,0,0)
    u.keybd_event(0x56,0,2,0);u.keybd_event(0x11,0,2,0)
    settle()
    assert text.toPlainText()=='Raw canvas\nsecond line edited pasted',repr(text.toPlainText())
    assert sum(isinstance(i,EditableTextItem) for i in w.scene.items())==1
    done=[]
    w.scene.completion_requested.connect(lambda:done.append(True))
    QTest.keyClick(w.view.viewport(),Qt.Key.Key_Return,Qt.KeyboardModifier.ControlModifier)
    assert done==[True] and not text.editing
    assert not text.toPlainText().endswith('\n')
    expected_text=text.toPlainText()
    image_record=item.to_record()
    w.grab().save('.smoke_paste.png')
    app.clipboard().setText('dismiss sentinel')
    w.close()
    assert app.canvas_window is None and app.clipboard().text()=='dismiss sentinel'
    QCoreApplication.sendPostedEvents(None,QEvent.Type.DeferredDelete)
    app.open_canvas()
    w=app.canvas_window
    restored_image=next(i for i in w.scene.items() if isinstance(i,ResizablePixmapItem))
    restored_text=next(i for i in w.scene.items() if isinstance(i,EditableTextItem))
    assert restored_image.to_record()==image_record
    assert restored_text.toPlainText()==expected_text
    print('PASS: native Ctrl+V image/text; OS pointer drag; anchored corner resize; double-click editing; in-place native Ctrl+V; Ctrl+Enter no newline; hide/restore preserves image pixels/geometry and edited text; clipboard untouched on dismiss')
finally:
    app._cleanup()
    settings.clear()

import ctypes

from PySide6.QtCore import QCoreApplication, QEvent, QPoint, QPointF, QSettings, Qt
from PySide6.QtGui import QImage, QPainter
from PySide6.QtTest import QTest

from qckdrw.app import QuickCanvasApplication
from qckdrw.window import CanvasWindow

QCoreApplication.setOrganizationName("QuickCanvasSmoke")
QCoreApplication.setApplicationName("CanvasSmoke")
settings = QSettings()
settings.setValue("autostart/initialized", True)
app = QuickCanvasApplication([], CanvasWindow)
user32 = ctypes.windll.user32


def hotkey():
    for key, flags in [(0x11, 0), (0x30, 0), (0x30, 2), (0x11, 2)]:
        user32.keybd_event(key, 0, flags, 0)
    QTest.qWait(150)


def path_points(path):
    return [
        (round(path.elementAt(index).x), round(path.elementAt(index).y))
        for index in range(path.elementCount())
    ]


def dark_near(image, point, radius=4):
    return any(
        image.pixelColor(x, y).lightness() < 160
        for x in range(max(0, point.x() - radius), min(image.width(), point.x() + radius + 1))
        for y in range(max(0, point.y() - radius), min(image.height(), point.y() + radius + 1))
    )


def render_scene(scene):
    image = QImage(1200, 800, QImage.Format.Format_ARGB32_Premultiplied)
    image.fill(Qt.GlobalColor.white)
    painter = QPainter(image)
    scene.render(painter)
    painter.end()
    return image


def native_move(view, x, y):
    local = view.mapFromScene(QPointF(x, y))
    screen = view.viewport().mapToGlobal(local)
    assert user32.SetCursorPos(screen.x(), screen.y())
    # SetCursorPos queues a real WM_MOUSEMOVE. Sleeping before processing avoids
    # QTest's Windows mouseMove shortcut, which produced no viewport move event.
    QTest.qSleep(30)
    QCoreApplication.processEvents()
    QTest.qSleep(30)
    QCoreApplication.processEvents()


try:
    assert app.canvas_window is None
    app.clipboard().setText('clipboard sentinel')
    hotkey()
    w=app.canvas_window
    view = w.view
    scene = w.scene

    def vp(x, y):
        return view.mapFromScene(QPointF(x, y))

    expected_zigzag = [
        (150, 150),
        (220, 200),
        (280, 120),
        (350, 200),
        (420, 150),
        (450, 180),
    ]
    native_move(view, 150, 150)
    QTest.mouseClick(view.viewport(), Qt.MouseButton.LeftButton, pos=vp(150, 150))
    assert view.drawing
    for x, y in expected_zigzag[1:-1]:
        native_move(view, x, y)
    QTest.mouseClick(view.viewport(), Qt.MouseButton.LeftButton, pos=vp(450, 180))
    assert not view.drawing and scene.undo_stack.count() == 1
    assert path_points(scene.items()[0].path()) == expected_zigzag
    scene.undo_stack.undo()
    assert not scene.items()
    scene.undo_stack.redo()
    assert len(scene.items())==1
    before=scene.items()[0].path().elementCount()
    native_move(view, 600, 400)
    assert scene.items()[0].path().elementCount() == before
    QTest.mouseClick(view.viewport(), Qt.MouseButton.LeftButton, pos=vp(600, 400))
    native_move(view, 700, 420)
    assert view.drawing
    screenshot = w.grab()
    screenshot.save(".smoke_canvas.png")
    screenshot_image = screenshot.toImage()
    pixel_ratio = screenshot.devicePixelRatio()
    for x, y in expected_zigzag[1:-1] + [(650, 410), (700, 420)]:
        window_point = view.viewport().mapTo(w, vp(x, y))
        image_point = QPoint(
            round(window_point.x() * pixel_ratio),
            round(window_point.y() * pixel_ratio),
        )
        assert dark_near(screenshot_image, image_point), (x, y)
    w.close()
    assert app.canvas_window is None and app.document_snapshot
    assert app.clipboard().text()=='clipboard sentinel'
    assert scene.undo_stack.count()==0 and not scene.items()
    QCoreApplication.sendPostedEvents(None,QEvent.Type.DeferredDelete)
    hotkey()
    w=app.canvas_window
    assert w is not None and w.isVisible() and not w.view.drawing
    assert len(w.scene.items())==2
    restored = sorted(w.scene.items(), key=lambda item: item.sequence)
    assert path_points(restored[0].path()) == expected_zigzag
    assert path_points(restored[1].path()) == [(600, 400), (700, 420)]
    image = render_scene(w.scene)
    assert image.pixelColor(0, 0).name() == "#ffffff"
    for x, y in expected_zigzag[1:-1] + [(650, 410), (700, 420)]:
        assert dark_near(image, QPoint(x, y)), (x, y)
    print("PASS: native SetCursorPos free motion preserves every zigzag point; screenshot and restored image contain intermediate geometry; click/move/click, undo/redo, no ghost motion, dismissal snapshot, and clipboard preservation succeed")
finally:
    app._cleanup()
    settings.clear()

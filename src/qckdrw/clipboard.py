from __future__ import annotations

from PySide6.QtCore import QRectF, Qt
from PySide6.QtGui import QClipboard, QGuiApplication, QImage, QPainter
from PySide6.QtWidgets import QGraphicsScene

from qckdrw.canvas.scene import CANVAS_HEIGHT, CANVAS_WIDTH

_CANVAS_RECT = QRectF(0.0, 0.0, float(CANVAS_WIDTH), float(CANVAS_HEIGHT))


def render_canvas(scene: QGraphicsScene) -> QImage:
    """Render the fixed logical canvas eagerly onto an opaque white image."""
    image = QImage(
        CANVAS_WIDTH,
        CANVAS_HEIGHT,
        QImage.Format.Format_ARGB32_Premultiplied,
    )
    if image.isNull():
        raise RuntimeError("Unable to allocate the canvas image.")
    image.fill(Qt.GlobalColor.white)

    selected_items = scene.selectedItems()
    focused_item = scene.focusItem()
    scene.clearSelection()
    scene.clearFocus()
    try:
        painter = QPainter(image)
        if not painter.isActive():
            raise RuntimeError("Unable to start the canvas renderer.")
        try:
            painter.setRenderHint(QPainter.RenderHint.Antialiasing, True)
            scene.render(
                painter,
                QRectF(image.rect()),
                _CANVAS_RECT,
                Qt.AspectRatioMode.IgnoreAspectRatio,
            )
        finally:
            painter.end()
    finally:
        for item in selected_items:
            if item.scene() is scene:
                item.setSelected(True)
        if focused_item is not None and focused_item.scene() is scene:
            focused_item.setFocus(Qt.FocusReason.OtherFocusReason)

    return image


def copy_canvas(scene: QGraphicsScene) -> QImage:
    """Render *scene* and put the concrete image on the system clipboard."""
    image = render_canvas(scene)
    clipboard = QGuiApplication.clipboard()
    if clipboard is None:
        raise RuntimeError("The system clipboard is unavailable.")
    clipboard.setImage(image, QClipboard.Mode.Clipboard)
    return image

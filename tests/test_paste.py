from __future__ import annotations

import os
import unittest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtCore import QMimeData, QPointF, QTemporaryDir, QUrl, Qt
from PySide6.QtGui import QColor, QImage, QPainter, QPainterPath, QPen
from PySide6.QtWidgets import QApplication
from PySide6.QtTest import QTest

from qckdrw.canvas.commands import StrokeItem
from qckdrw.canvas.items import EditableTextItem, ResizablePixmapItem
from qckdrw.canvas.scene import CanvasScene
from qckdrw.window import CanvasWindow


class PasteTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.app = QApplication.instance() or QApplication([])

    def setUp(self) -> None:
        self.window = CanvasWindow()

    def tearDown(self) -> None:
        self.window.release_resources()
        self.window.deleteLater()
        QApplication.clipboard().clear()
        QApplication.processEvents()

    @staticmethod
    def _items_of_type(scene: CanvasScene, item_type: type) -> list:
        return [item for item in scene.items() if isinstance(item, item_type)]

    def test_image_data_takes_precedence_over_clipboard_text(self) -> None:
        image = QImage(32, 24, QImage.Format.Format_ARGB32_Premultiplied)
        image.fill(QColor("#d02020"))
        mime = QMimeData()
        mime.setImageData(image)
        mime.setText("this must not become a text item")
        QApplication.clipboard().setMimeData(mime)

        self.window.paste()

        images = self._items_of_type(self.window.scene, ResizablePixmapItem)
        self.assertEqual(len(images), 1)
        self.assertEqual(
            self._items_of_type(self.window.scene, EditableTextItem), []
        )
        self.assertEqual(images[0].content_rect.size().toSize(), image.size())
        self.assertEqual(self.window.view.tool, "select")
        self.assertTrue(images[0].isSelected())

    def test_plain_text_pastes_as_editable_item(self) -> None:
        mime = QMimeData()
        mime.setText("first line\nsecond line")
        QApplication.clipboard().setMimeData(mime)

        self.window.paste()

        text_items = self._items_of_type(self.window.scene, EditableTextItem)
        self.assertEqual(len(text_items), 1)
        self.assertEqual(text_items[0].toPlainText(), "first line\nsecond line")
        self.assertTrue(text_items[0].isSelected())

    def test_ctrl_v_with_canvas_focus_pastes_clipboard_image(self) -> None:
        image = QImage(28, 20, QImage.Format.Format_ARGB32_Premultiplied)
        image.fill(QColor("#5070d0"))
        mime = QMimeData()
        mime.setImageData(image)
        QApplication.clipboard().setMimeData(mime)

        self.window.show()
        self.window.activateWindow()
        self.window.view.setFocus(Qt.FocusReason.OtherFocusReason)
        QApplication.processEvents()
        QTest.keyClick(
            self.window.view,
            Qt.Key.Key_V,
            Qt.KeyboardModifier.ControlModifier,
        )
        QApplication.processEvents()

        self.assertEqual(
            len(self._items_of_type(self.window.scene, ResizablePixmapItem)),
            1,
        )


    def test_all_valid_local_image_urls_are_pasted_before_text(self) -> None:
        temporary = QTemporaryDir()
        self.assertTrue(temporary.isValid())
        paths: list[str] = []
        for name, color in (("one.png", "#1040d0"), ("two.png", "#20b050")):
            path = os.path.join(temporary.path(), name)
            image = QImage(18, 12, QImage.Format.Format_ARGB32_Premultiplied)
            image.fill(QColor(color))
            self.assertTrue(image.save(path))
            paths.append(path)

        mime = QMimeData()
        mime.setUrls(
            [QUrl.fromLocalFile(paths[0]), QUrl("https://example.invalid/a.png"), QUrl.fromLocalFile(paths[1])]
        )
        mime.setText("fallback only")
        QApplication.clipboard().setMimeData(mime)

        self.window.paste()

        self.assertEqual(
            len(self._items_of_type(self.window.scene, ResizablePixmapItem)), 2
        )
        self.assertEqual(
            self._items_of_type(self.window.scene, EditableTextItem), []
        )

    def test_mixed_content_snapshot_preserves_order_positions_and_rendering(self) -> None:
        self.window.show()
        QApplication.processEvents()
        self.window.resize(837, 613)
        QApplication.processEvents()

        scene = self.window.scene
        canvas_size = self.window.view.viewport().size()
        self.assertEqual(scene.sceneRect().size().toSize(), canvas_size)

        source = QImage(80, 60, QImage.Format.Format_ARGB32_Premultiplied)
        source.fill(QColor("#d04020"))
        image_item = ResizablePixmapItem(source)
        scene.addItem(image_item)
        image_item.setPos(QPointF(180.0, 140.0))

        path = QPainterPath(QPointF(150.0, 160.0))
        path.lineTo(360.0, 260.0)
        pen = QPen(QColor("#2040d0"), 14.0)
        pen.setCapStyle(Qt.PenCapStyle.RoundCap)
        stroke = StrokeItem(path, pen, scene.allocate_stroke_sequence())
        scene.addItem(stroke)
        stroke.setPos(QPointF(25.0, 15.0))

        text_item = EditableTextItem("Snapshot text")
        scene.addItem(text_item)
        text_item.setPos(QPointF(205.0, 175.0))
        scene.clearSelection()

        before = self._render(scene)
        snapshots: list[bytes] = []
        self.window.dismissed.connect(
            lambda: snapshots.append(self.window.serialize_document())
        )
        self.window.hide()
        QApplication.processEvents()
        self.assertEqual(len(snapshots), 1)

        restored = CanvasWindow(snapshots[0])
        try:
            restored.show()
            QApplication.processEvents()
            restored.scene.clearSelection()
            self.assertEqual(restored.view.viewport().size(), canvas_size)
            self.assertEqual(
                restored.scene.sceneRect().size().toSize(), canvas_size
            )
            ordered_types = [
                type(item)
                for item in restored.scene.items(Qt.SortOrder.AscendingOrder)
            ]
            self.assertEqual(
                ordered_types,
                [ResizablePixmapItem, StrokeItem, EditableTextItem],
            )
            restored_stroke = self._items_of_type(
                restored.scene, StrokeItem
            )[0]
            self.assertEqual(restored_stroke.pos(), QPointF(25.0, 15.0))
            self.assertEqual(self._render(restored.scene), before)
            restored.resize(791, 571)
            QApplication.processEvents()
            self.assertEqual(
                restored.scene.sceneRect().size().toSize(),
                restored.view.viewport().size(),
            )
        finally:
            restored.release_resources()
            restored.deleteLater()

    @staticmethod
    def _render(scene: CanvasScene) -> QImage:
        canvas_size = scene.sceneRect().size().toSize()
        image = QImage(
            canvas_size.width(),
            canvas_size.height(),
            QImage.Format.Format_ARGB32_Premultiplied,
        )
        image.fill(Qt.GlobalColor.white)
        painter = QPainter(image)
        scene.render(painter)
        painter.end()
        return image


if __name__ == "__main__":
    unittest.main()

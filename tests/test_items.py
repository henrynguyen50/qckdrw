from __future__ import annotations

import os
import unittest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtCore import QEvent, QPointF, QRectF, Qt
from PySide6.QtGui import QFont, QImage, QKeyEvent, QMouseEvent
from PySide6.QtTest import QSignalSpy
from PySide6.QtWidgets import QApplication, QGraphicsView

from qckdrw.canvas.items import EditableTextItem, ResizablePixmapItem
from qckdrw.canvas.scene import CanvasScene


class GraphicsItemTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.app = QApplication.instance() or QApplication([])

    def setUp(self) -> None:
        self.scene = CanvasScene()
        self.view = QGraphicsView(self.scene)
        self.view.resize(700, 500)
        self.view.show()
        QApplication.processEvents()

    def tearDown(self) -> None:
        self.view.close()
        self.scene.release_resources()
        self.view.deleteLater()
        self.scene.deleteLater()
        QApplication.processEvents()

    def _mouse(
        self,
        event_type: QEvent.Type,
        scene_position: QPointF,
        *,
        button: Qt.MouseButton = Qt.MouseButton.NoButton,
        buttons: Qt.MouseButton = Qt.MouseButton.NoButton,
        modifiers: Qt.KeyboardModifier = Qt.KeyboardModifier.NoModifier,
    ) -> None:
        local = self.view.mapFromScene(scene_position)
        global_position = self.view.viewport().mapToGlobal(local)
        event = QMouseEvent(
            event_type,
            QPointF(local),
            QPointF(global_position),
            button,
            buttons,
            modifiers,
        )
        QApplication.sendEvent(self.view.viewport(), event)
        QApplication.processEvents()

    def _drag(self, start: QPointF, finish: QPointF) -> None:
        self._mouse(
            QEvent.Type.MouseButtonPress,
            start,
            button=Qt.MouseButton.LeftButton,
            buttons=Qt.MouseButton.LeftButton,
        )
        self._mouse(
            QEvent.Type.MouseMove,
            finish,
            buttons=Qt.MouseButton.LeftButton,
        )
        self._mouse(
            QEvent.Type.MouseButtonRelease,
            finish,
            button=Qt.MouseButton.LeftButton,
        )

    @staticmethod
    def _image(width: int = 80, height: int = 40) -> QImage:
        image = QImage(width, height, QImage.Format.Format_ARGB32)
        image.fill(Qt.GlobalColor.transparent)
        for y in range(height):
            for x in range(width):
                image.setPixelColor(x, y, Qt.GlobalColor.red if x < width // 2 else Qt.GlobalColor.blue)
        return image

    def test_all_eight_resize_handles_keep_the_opposite_anchor(self) -> None:
        cases = {
            "top_left": QPointF(-20.0, -10.0),
            "top": QPointF(0.0, -12.0),
            "top_right": QPointF(20.0, -10.0),
            "right": QPointF(20.0, 0.0),
            "bottom_right": QPointF(20.0, 10.0),
            "bottom": QPointF(0.0, 12.0),
            "bottom_left": QPointF(-20.0, 10.0),
            "left": QPointF(-20.0, 0.0),
        }
        opposite = {
            "top_left": "bottom_right",
            "top": "bottom",
            "top_right": "bottom_left",
            "right": "left",
            "bottom_right": "top_left",
            "bottom": "top",
            "bottom_left": "top_right",
            "left": "right",
        }

        for handle_name, delta in cases.items():
            with self.subTest(handle=handle_name):
                item = ResizablePixmapItem(self._image())
                item.setPos(200.0, 180.0)
                self.scene.addItem(item)
                item.setSelected(True)
                QApplication.processEvents()
                old_handles = item._handle_rects()
                fixed_before = item.mapToScene(old_handles[opposite[handle_name]].center())
                start = item.mapToScene(old_handles[handle_name].center())

                self._drag(start, start + delta)

                fixed_after = item.mapToScene(
                    item._handle_rects()[opposite[handle_name]].center()
                )
                self.assertAlmostEqual(fixed_after.x(), fixed_before.x(), places=5)
                self.assertAlmostEqual(fixed_after.y(), fixed_before.y(), places=5)
                self.assertGreaterEqual(item.content_rect.width(), 1.0)
                self.assertGreaterEqual(item.content_rect.height(), 1.0)
                if "top_" in handle_name or "bottom_" in handle_name:
                    self.assertAlmostEqual(
                        item.content_rect.width() / item.content_rect.height(),
                        2.0,
                        places=5,
                    )
                self.scene.removeItem(item)
                self.scene.undo_stack.clear()

    def test_move_and_resize_each_create_one_undo_boundary(self) -> None:
        item = ResizablePixmapItem(self._image())
        item.setPos(120.0, 100.0)
        self.scene.addItem(item)
        original_position = item.pos()

        self._drag(item.mapToScene(item.content_rect.center()), QPointF(260.0, 210.0))
        moved_position = item.pos()
        self.assertNotEqual(moved_position, original_position)
        self.assertEqual(self.scene.undo_stack.count(), 1)
        self.scene.undo_stack.undo()
        self.assertEqual(item.pos(), original_position)
        self.scene.undo_stack.redo()
        self.assertEqual(item.pos(), moved_position)

        item.setSelected(True)
        QApplication.processEvents()
        old_rect = item.content_rect
        start = item.mapToScene(item._handle_rects()["right"].center())
        self._drag(start, start + QPointF(35.0, 0.0))
        resized_rect = item.content_rect
        self.assertGreater(resized_rect.width(), old_rect.width())
        self.assertEqual(self.scene.undo_stack.count(), 2)
        self.scene.undo_stack.undo()
        self.assertEqual(item.content_rect, old_rect)
        self.scene.undo_stack.redo()
        self.assertEqual(item.content_rect, resized_rect)

    def test_selection_decorations_are_not_painted_after_clear_selection(self) -> None:
        item = ResizablePixmapItem(self._image())
        self.scene.addItem(item)
        item.setSelected(True)
        self.assertTrue(item.isSelected())
        self.scene.clearSelection()
        self.assertFalse(item.isSelected())
        self.assertIsNone(item._handle_at(item.content_rect.topLeft()))

    def test_text_done_key_finishes_once_without_inserting_newline(self) -> None:
        item = EditableTextItem("alpha")
        item.setPos(100.0, 100.0)
        self.scene.addItem(item)
        spy = QSignalSpy(item.done_requested)
        center = item.mapToScene(item.boundingRect().center())
        self._mouse(
            QEvent.Type.MouseButtonDblClick,
            center,
            button=Qt.MouseButton.LeftButton,
            buttons=Qt.MouseButton.LeftButton,
        )
        self.assertTrue(item.editing)

        event = QKeyEvent(
            QEvent.Type.KeyPress,
            Qt.Key.Key_Return,
            Qt.KeyboardModifier.ControlModifier,
        )
        QApplication.sendEvent(self.view.viewport(), event)
        QApplication.processEvents()

        self.assertFalse(item.editing)
        self.assertEqual(item.toPlainText(), "alpha")
        self.assertEqual(spy.count(), 1)
        self.assertEqual(
            item.textInteractionFlags(), Qt.TextInteractionFlag.NoTextInteraction
        )

    def test_text_record_preserves_unicode_newlines_font_and_position(self) -> None:
        text = "Unicode: café 漢字 👋\nsecond line"
        item = EditableTextItem(text)
        font = QFont("Sans Serif", 17, QFont.Weight.Bold)
        font.setItalic(True)
        item.setFont(font)
        item.setPos(-12.5, 77.25)

        restored = EditableTextItem.from_record(item.to_record())

        self.assertEqual(restored.toPlainText(), text)
        self.assertEqual(restored.font().toString(), font.toString())
        self.assertEqual(restored.pos(), item.pos())

    def test_png_record_roundtrip_preserves_source_pixels_and_display_geometry(self) -> None:
        image = self._image(19, 11)
        item = ResizablePixmapItem(image)
        item.set_content_rect(QRectF(0.0, 0.0, 123.5, 62.25))
        item.setPos(14.25, -8.5)

        restored = ResizablePixmapItem.from_record(item.to_record())
        record_again = restored.to_record()
        decoded = QImage.fromData(
            __import__("base64").b64decode(record_again["png"]), "PNG"
        )

        self.assertEqual(decoded.size(), image.size())
        for point in (QPointF(0, 0), QPointF(18, 10), QPointF(9, 5)):
            x, y = int(point.x()), int(point.y())
            self.assertEqual(decoded.pixelColor(x, y), image.pixelColor(x, y))
        self.assertEqual(restored.content_rect, item.content_rect)
        self.assertEqual(restored.pos(), item.pos())


if __name__ == "__main__":
    unittest.main()

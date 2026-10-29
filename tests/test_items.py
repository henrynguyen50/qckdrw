from __future__ import annotations

import json
import os
import unittest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtCore import QEvent, QPointF, QRectF, Qt
from PySide6.QtGui import (
    QFont,
    QImage,
    QKeyEvent,
    QMouseEvent,
    QPainterPath,
    QPen,
)
from PySide6.QtTest import QSignalSpy
from PySide6.QtWidgets import QApplication, QGraphicsPathItem, QGraphicsView

from qckdrw.canvas.commands import StrokeItem
from qckdrw.canvas.items import EditableTextItem, ResizablePixmapItem
from qckdrw.canvas.scene import CANVAS_HEIGHT, CANVAS_WIDTH, CanvasScene


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

    def test_stroke_content_bounds_include_pen_without_recursive_shape(self) -> None:
        path = QPainterPath(QPointF(10.0, 20.0))
        path.lineTo(90.0, 20.0)
        item = StrokeItem(path, QPen(Qt.GlobalColor.black, 8.0))

        expected = QGraphicsPathItem.shape(item).boundingRect()
        self.assertEqual(item.content_rect, expected)
        self.assertLess(item.content_rect.left(), path.boundingRect().left())
        self.assertGreater(item.content_rect.right(), path.boundingRect().right())
        self.assertLess(item.content_rect.top(), path.boundingRect().top())
        self.assertGreater(item.content_rect.bottom(), path.boundingRect().bottom())

        item.setSelected(True)
        handles = item._handle_rects()
        self.assertEqual(handles["left"].center().x(), item.content_rect.left())
        self.assertEqual(handles["right"].center().x(), item.content_rect.right())
        for handle in handles.values():
            self.assertTrue(item.shape().contains(handle.center()))

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

    def test_stroke_and_text_resize_with_one_undo_boundary(self) -> None:
        path = QPainterPath(QPointF(0.0, 0.0))
        path.lineTo(80.0, 40.0)
        items = (
            StrokeItem(path, QPen(Qt.GlobalColor.black, 6.0)),
            EditableTextItem("Resizable text"),
        )

        for item in items:
            with self.subTest(item=type(item).__name__):
                item.setPos(160.0, 130.0)
                self.scene.addItem(item)
                item.setSelected(True)
                QApplication.processEvents()
                old_position = item.pos()
                old_scale = item.scale()
                old_handles = item._handle_rects()
                fixed_before = item.mapToScene(old_handles["left"].center())
                start = item.mapToScene(old_handles["right"].center())

                self._drag(start, start + QPointF(50.0, 0.0))

                resized_position = item.pos()
                resized_scale = item.scale()
                fixed_after = item.mapToScene(
                    item._handle_rects()["left"].center()
                )
                self.assertGreater(resized_scale, old_scale)
                self.assertAlmostEqual(fixed_after.x(), fixed_before.x(), places=5)
                self.assertAlmostEqual(fixed_after.y(), fixed_before.y(), places=5)
                self.assertEqual(self.scene.undo_stack.count(), 1)

                self.scene.undo_stack.undo()
                self.assertEqual(item.pos(), old_position)
                self.assertEqual(item.scale(), old_scale)
                self.scene.undo_stack.redo()
                self.assertEqual(item.pos(), resized_position)
                self.assertEqual(item.scale(), resized_scale)

                self.scene.undo_stack.clear()
                self.scene.removeItem(item)

    def test_snapshot_preserves_resized_stroke_text_and_image(self) -> None:
        path = QPainterPath(QPointF(5.0, 10.0))
        path.lineTo(75.0, 55.0)
        stroke = StrokeItem(path, QPen(Qt.GlobalColor.black, 5.0))
        stroke.setPos(20.0, 30.0)
        stroke.setScale(1.75)
        text = EditableTextItem("saved size")
        text.setPos(100.0, 120.0)
        text.setScale(2.25)
        image = ResizablePixmapItem(self._image())
        image.setPos(240.0, 180.0)
        image.set_content_rect(QRectF(0.0, 0.0, 145.0, 67.0))
        for item in (stroke, text, image):
            self.scene.addItem(item)

        document = self.scene.serialize_document()
        restored_scene = CanvasScene()
        try:
            restored_scene.restore_document(document)
            restored_stroke = next(
                item for item in restored_scene.items() if isinstance(item, StrokeItem)
            )
            restored_text = next(
                item
                for item in restored_scene.items()
                if isinstance(item, EditableTextItem)
            )
            restored_image = next(
                item
                for item in restored_scene.items()
                if isinstance(item, ResizablePixmapItem)
            )
            self.assertEqual(restored_stroke.scale(), stroke.scale())
            self.assertEqual(restored_stroke.pos(), stroke.pos())
            self.assertEqual(restored_text.scale(), text.scale())
            self.assertEqual(restored_text.pos(), text.pos())
            self.assertEqual(restored_image.content_rect, image.content_rect)
            self.assertEqual(restored_image.pos(), image.pos())
        finally:
            restored_scene.release_resources()
            restored_scene.deleteLater()

    def test_canvas_dimensions_roundtrip_and_legacy_default(self) -> None:
        self.scene.set_canvas_size(913, 547)
        restored = CanvasScene()
        legacy = CanvasScene()
        try:
            restored.restore_document(self.scene.serialize_document())
            self.assertEqual(restored.sceneRect(), QRectF(0.0, 0.0, 913.0, 547.0))

            legacy_document = json.dumps({"version": 1, "items": []}).encode()
            legacy.set_canvas_size(300, 200)
            legacy.restore_document(legacy_document)
            self.assertEqual(
                legacy.sceneRect(),
                QRectF(0.0, 0.0, float(CANVAS_WIDTH), float(CANVAS_HEIGHT)),
            )
        finally:
            restored.release_resources()
            legacy.release_resources()
            restored.deleteLater()
            legacy.deleteLater()

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
        item.setScale(1.8)

        restored = EditableTextItem.from_record(item.to_record())

        self.assertEqual(restored.toPlainText(), text)
        self.assertEqual(restored.font().toString(), font.toString())
        self.assertEqual(restored.pos(), item.pos())
        self.assertEqual(restored.scale(), item.scale())

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

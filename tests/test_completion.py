from __future__ import annotations

import os
import unittest
from unittest.mock import patch

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtCore import QEvent, QPointF, QRectF, Qt
from PySide6.QtGui import QColor, QImage, QKeyEvent, QMouseEvent, QPainterPath, QPen
from PySide6.QtWidgets import QApplication, QGraphicsPathItem

from qckdrw.canvas.items import EditableTextItem, ResizablePixmapItem
from qckdrw.canvas.scene import CANVAS_HEIGHT, CANVAS_WIDTH, CanvasScene
from qckdrw.clipboard import copy_canvas, render_canvas
from qckdrw.window import CanvasWindow


class ClipboardRenderingTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.app = QApplication.instance() or QApplication([])

    def setUp(self) -> None:
        self.scene = CanvasScene()

    def tearDown(self) -> None:
        self.scene.release_resources()
        self.scene.deleteLater()
        QApplication.clipboard().clear()
        QApplication.processEvents()

    def test_render_is_exact_opaque_canvas_and_clips_outside_content(self) -> None:
        self.scene.addRect(
            QRectF(-25.0, 90.0, 50.0, 40.0),
            QPen(Qt.PenStyle.NoPen),
            QColor("#d02020"),
        )

        image = render_canvas(self.scene)

        self.assertEqual(image.size().width(), CANVAS_WIDTH)
        self.assertEqual(image.size().height(), CANVAS_HEIGHT)
        self.assertEqual(image.format(), QImage.Format.Format_ARGB32_Premultiplied)
        self.assertEqual(image.pixelColor(5, 105), QColor("#d02020"))
        self.assertEqual(image.pixelColor(100, 100), QColor(Qt.GlobalColor.white))
        rgba = image.convertToFormat(QImage.Format.Format_RGBA8888)
        pixels = bytes(rgba.constBits())
        self.assertTrue(all(alpha == 255 for alpha in pixels[3::4]))

    def test_copy_uses_current_canvas_dimensions(self) -> None:
        self.scene.set_canvas_size(640, 360)
        self.scene.addRect(
            QRectF(600.0, 320.0, 40.0, 40.0),
            QPen(Qt.PenStyle.NoPen),
            QColor("#5030a0"),
        )

        returned = copy_canvas(self.scene)
        clipboard_image = QApplication.clipboard().image()

        self.assertEqual(returned.size().width(), 640)
        self.assertEqual(returned.size().height(), 360)
        self.assertEqual(clipboard_image, returned)
        self.assertEqual(clipboard_image.pixelColor(620, 340), QColor("#5030a0"))

    def test_antialiased_stroke_keeps_mixed_edge_pixels(self) -> None:
        path = QPainterPath(QPointF(100.0, 100.0))
        path.lineTo(240.0, 173.0)
        stroke = QGraphicsPathItem(path)
        stroke.setPen(QPen(Qt.GlobalColor.black, 3.0))
        self.scene.addItem(stroke)

        image = render_canvas(self.scene)
        colors = {
            image.pixelColor(x, y).rgb()
            for y in range(95, 180)
            for x in range(95, 246)
        }

        self.assertIn(QColor(Qt.GlobalColor.white).rgb(), colors)
        self.assertTrue(
            any(
                0 < QColor.fromRgb(color).red() < 255
                and QColor.fromRgb(color).red() == QColor.fromRgb(color).green()
                and QColor.fromRgb(color).green() == QColor.fromRgb(color).blue()
                for color in colors
            )
        )

    def test_selection_handles_are_excluded_without_changing_selection(self) -> None:
        source = QImage(40, 30, QImage.Format.Format_ARGB32_Premultiplied)
        source.fill(QColor("#2878d0"))
        item = ResizablePixmapItem(source)
        item.setPos(120.0, 140.0)
        self.scene.addItem(item)
        item.setSelected(True)

        selected_render = render_canvas(self.scene)
        self.assertTrue(item.isSelected())
        item.setSelected(False)
        plain_render = render_canvas(self.scene)

        self.assertEqual(selected_render, plain_render)

    def test_copy_canvas_places_an_eager_concrete_image_on_clipboard(self) -> None:
        self.scene.addRect(
            QRectF(300.0, 250.0, 100.0, 80.0),
            QPen(Qt.PenStyle.NoPen),
            QColor("#308050"),
        )

        returned = copy_canvas(self.scene)
        clipboard_image = QApplication.clipboard().image()

        self.assertFalse(clipboard_image.isNull())
        self.assertEqual(clipboard_image, returned)
        self.scene.clear()
        self.assertEqual(
            QApplication.clipboard().image().pixelColor(320, 270),
            QColor("#308050"),
        )


class CanvasWindowCompletionTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.app = QApplication.instance() or QApplication([])

    def setUp(self) -> None:
        QApplication.clipboard().clear()
        self.window = CanvasWindow()
        self.window.show()
        QApplication.processEvents()

    def tearDown(self) -> None:
        self.window.release_resources()
        self.window.deleteLater()
        QApplication.clipboard().clear()
        QApplication.processEvents()

    def test_finish_copies_clean_document_releases_and_next_window_is_fresh(self) -> None:
        source = QImage(60, 40, QImage.Format.Format_ARGB32_Premultiplied)
        source.fill(QColor("#c03050"))
        item = ResizablePixmapItem(source)
        self.window.scene.add_pasted_item(item)
        export_rect = self.window.scene.sceneRect().toAlignedRect()
        observed: list[tuple[bool, int]] = []

        def complete() -> None:
            observed.append(
                (
                    self.window.scene.undo_stack.isClean(),
                    len(self.window.scene.selectedItems()),
                )
            )
            self.window.release_resources()

        self.window.completed.connect(complete)
        self.window.finish()

        self.assertEqual(observed, [(True, 0)])
        self.assertTrue(self.window.isHidden())
        copied = QApplication.clipboard().image()
        self.assertEqual(copied.size(), export_rect.size())
        self.assertEqual(copied.pixelColor(export_rect.center()), QColor("#c03050"))

        fresh = CanvasWindow()
        try:
            self.assertEqual(fresh.scene.items(), [])
            self.assertTrue(fresh.scene.undo_stack.isClean())
        finally:
            fresh.release_resources()
            fresh.deleteLater()

    def test_export_failure_keeps_the_live_dirty_document(self) -> None:
        item = EditableTextItem("do not lose me")
        self.window.scene.add_pasted_item(item)
        completed: list[bool] = []
        self.window.completed.connect(lambda: completed.append(True))

        with (
            patch("qckdrw.window.copy_canvas", side_effect=RuntimeError("clipboard busy")),
            patch("qckdrw.window.QMessageBox.critical") as critical,
        ):
            self.window.finish()

        self.assertEqual(completed, [])
        self.assertFalse(self.window.isHidden())
        self.assertIn(item, self.window.scene.items())
        self.assertFalse(self.window.scene.undo_stack.isClean())
        self.assertEqual(item.toPlainText(), "do not lose me")
        critical.assert_called_once()
        self.assertIn("clipboard busy", self.window.statusBar().currentMessage())

    def test_finish_commits_an_active_preview_before_export(self) -> None:
        viewport = self.window.view.viewport()
        start = self.window.view.mapFromScene(QPointF(100.0, 100.0))
        finish = self.window.view.mapFromScene(QPointF(220.0, 170.0))
        press = QMouseEvent(
            QEvent.Type.MouseButtonPress,
            QPointF(start),
            QPointF(viewport.mapToGlobal(start)),
            Qt.MouseButton.LeftButton,
            Qt.MouseButton.LeftButton,
            Qt.KeyboardModifier.NoModifier,
        )
        move = QMouseEvent(
            QEvent.Type.MouseMove,
            QPointF(finish),
            QPointF(viewport.mapToGlobal(finish)),
            Qt.MouseButton.NoButton,
            Qt.MouseButton.NoButton,
            Qt.KeyboardModifier.NoModifier,
        )
        QApplication.sendEvent(viewport, press)
        QApplication.sendEvent(viewport, move)
        self.assertTrue(self.window.view.drawing)
        self.window.completed.connect(self.window.release_resources)

        self.window.finish()

        copied = QApplication.clipboard().image()
        self.assertTrue(
            any(
                copied.pixelColor(x, y) != QColor(Qt.GlobalColor.white)
                for y in range(95, 176)
                for x in range(95, 226)
            )
        )

    def test_primary_return_while_editing_text_completes_without_newline(self) -> None:
        text = EditableTextItem("keep this text")
        self.window.scene.add_pasted_item(text)
        self.window._set_tool("select")
        center = text.mapToScene(text.boundingRect().center())
        local = self.window.view.mapFromScene(center)
        global_position = self.window.view.viewport().mapToGlobal(local)
        double_click = QMouseEvent(
            QEvent.Type.MouseButtonDblClick,
            QPointF(local),
            QPointF(global_position),
            Qt.MouseButton.LeftButton,
            Qt.MouseButton.LeftButton,
            Qt.KeyboardModifier.NoModifier,
        )
        QApplication.sendEvent(self.window.view.viewport(), double_click)
        QApplication.processEvents()
        self.assertTrue(text.editing)
        text_bounds = text.sceneBoundingRect().toAlignedRect()
        completed: list[str] = []

        def complete() -> None:
            completed.append(text.toPlainText())
            self.window.release_resources()

        self.window.completed.connect(complete)
        key = QKeyEvent(
            QEvent.Type.KeyPress,
            Qt.Key.Key_Return,
            Qt.KeyboardModifier.ControlModifier,
        )
        QApplication.sendEvent(self.window.view.viewport(), key)
        QApplication.processEvents()

        self.assertEqual(completed, ["keep this text"])
        copied = QApplication.clipboard().image()
        visible_text_bounds = text_bounds.intersected(copied.rect())
        self.assertTrue(
            any(
                copied.pixelColor(x, y) != QColor(Qt.GlobalColor.white)
                for y in range(
                    visible_text_bounds.top(), visible_text_bounds.bottom() + 1
                )
                for x in range(
                    visible_text_bounds.left(), visible_text_bounds.right() + 1
                )
            )
        )

if __name__ == "__main__":
    unittest.main()

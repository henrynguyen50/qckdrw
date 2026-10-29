from __future__ import annotations

import os
import unittest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtCore import QEvent, QPointF, Qt
from PySide6.QtGui import QImage, QMouseEvent, QPainter
from PySide6.QtWidgets import QApplication

from qckdrw.canvas.commands import StrokeItem
from qckdrw.canvas.items import EditableTextItem
from qckdrw.canvas.scene import CanvasScene
from qckdrw.canvas.view import CanvasView
from qckdrw.window import CanvasWindow


class CanvasViewTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.app = QApplication.instance() or QApplication([])

    def setUp(self) -> None:
        self.scene = CanvasScene()
        self.view = CanvasView(self.scene)
        self.view.resize(900, 650)
        self.view.show()
        QApplication.processEvents()

    def tearDown(self) -> None:
        self.view.close()
        self.scene.release_resources()
        self.view.deleteLater()
        self.scene.deleteLater()
        QApplication.processEvents()

    def _send_mouse(
        self,
        event_type: QEvent.Type,
        point: tuple[float, float],
        *,
        button: Qt.MouseButton = Qt.MouseButton.NoButton,
        buttons: Qt.MouseButton = Qt.MouseButton.NoButton,
    ) -> None:
        local = self.view.mapFromScene(QPointF(*point))
        global_position = self.view.viewport().mapToGlobal(local)
        event = QMouseEvent(
            event_type,
            QPointF(local),
            QPointF(global_position),
            button,
            buttons,
            Qt.KeyboardModifier.NoModifier,
        )
        QApplication.sendEvent(self.view.viewport(), event)
        QApplication.processEvents()

    def _click(self, point: tuple[float, float]) -> None:
        self._send_mouse(
            QEvent.Type.MouseButtonPress,
            point,
            button=Qt.MouseButton.LeftButton,
            buttons=Qt.MouseButton.LeftButton,
        )
        self._send_mouse(
            QEvent.Type.MouseButtonRelease,
            point,
            button=Qt.MouseButton.LeftButton,
        )

    def _move(
        self,
        point: tuple[float, float],
        buttons: Qt.MouseButton = Qt.MouseButton.NoButton,
    ) -> None:
        self._send_mouse(QEvent.Type.MouseMove, point, buttons=buttons)

    def _strokes(self, scene: CanvasScene | None = None) -> list[StrokeItem]:
        target = scene or self.scene
        return sorted(
            (item for item in target.items() if isinstance(item, StrokeItem)),
            key=lambda item: item.sequence,
        )

    def assertPathPoints(
        self,
        item: StrokeItem,
        expected: list[tuple[float, float]],
    ) -> None:
        path = item.path()
        self.assertEqual(path.elementCount(), len(expected))
        for index, (expected_x, expected_y) in enumerate(expected):
            element = path.elementAt(index)
            self.assertAlmostEqual(element.x, expected_x, delta=1.0)
            self.assertAlmostEqual(element.y, expected_y, delta=1.0)

    def test_click_free_moves_click_commits_every_point(self) -> None:
        expected = [(100, 100), (180, 170), (260, 90), (340, 160)]

        self._click(expected[0])
        self.assertTrue(self.view.drawing)
        for point in expected[1:-1]:
            self._move(point)
        self._click(expected[-1])

        self.assertFalse(self.view.drawing)
        self.assertEqual(self.scene.undo_stack.count(), 1)
        strokes = self._strokes()
        self.assertEqual(len(strokes), 1)
        self.assertPathPoints(strokes[0], expected)

    def test_move_with_left_button_held_is_ignored(self) -> None:
        self._click((100, 100))
        self._move((200, 180), Qt.MouseButton.LeftButton)
        self._click((300, 120))

        strokes = self._strokes()
        self.assertEqual(len(strokes), 1)
        self.assertPathPoints(strokes[0], [(100, 100), (300, 120)])

    def test_switching_tool_and_hiding_finalize_active_strokes(self) -> None:
        self._click((100, 100))
        self._move((180, 160))
        self.view.set_tool("select")

        self.assertFalse(self.view.drawing)
        self.assertEqual(self.scene.undo_stack.count(), 1)
        self.assertPathPoints(self._strokes()[0], [(100, 100), (180, 160)])

        self.view.set_tool("draw")
        self._click((300, 300))
        self._move((380, 340))
        self.view.hide()
        QApplication.processEvents()

        self.assertFalse(self.view.drawing)
        self.assertEqual(self.scene.undo_stack.count(), 2)
        self.assertPathPoints(self._strokes()[1], [(300, 300), (380, 340)])

    def test_events_outside_canvas_do_not_extend_or_finish_stroke(self) -> None:
        self._click((100, 100))
        self._move((-40, 180))
        self._click((1240, 180))

        self.assertTrue(self.view.drawing)
        self.assertEqual(self.scene.undo_stack.count(), 0)

        self._move((200, 180))
        self._click((300, 120))
        strokes = self._strokes()
        self.assertEqual(len(strokes), 1)
        self.assertPathPoints(strokes[0], [(100, 100), (200, 180), (300, 120)])

    def test_text_click_adds_an_editable_item_and_switches_to_select(self) -> None:
        changes: list[str] = []
        self.view.tool_changed.connect(changes.append)
        self.view.set_tool("text")

        position = (240.0, 180.0)
        self._click(position)

        text_items = [
            item for item in self.scene.items() if isinstance(item, EditableTextItem)
        ]
        self.assertEqual(len(text_items), 1)
        item = text_items[0]
        self.assertEqual(item.pos(), QPointF(*position))
        self.assertTrue(item.editing)
        self.assertTrue(item.isSelected())
        self.assertEqual(self.scene.focusItem(), item)
        self.assertEqual(self.view.tool, "select")
        self.assertEqual(changes, ["text", "select"])
        self.assertEqual(self.scene.undo_stack.count(), 1)

        item.setPlainText("A meaningful canvas note")
        item.finish_editing()
        self.assertEqual(self.scene.undo_stack.count(), 2)
        self.scene.undo_stack.undo()
        self.assertEqual(item.toPlainText(), "")
        self.scene.undo_stack.undo()
        self.assertIsNone(item.scene())
        self.scene.undo_stack.redo()
        self.scene.undo_stack.redo()
        self.assertEqual(item.toPlainText(), "A meaningful canvas note")

        document = self.scene.serialize_document()
        restored = CanvasScene()
        try:
            restored.restore_document(document)
            restored_text = [
                candidate
                for candidate in restored.items()
                if isinstance(candidate, EditableTextItem)
            ]
            self.assertEqual(len(restored_text), 1)
            self.assertEqual(
                restored_text[0].toPlainText(), "A meaningful canvas note"
            )
            self.assertEqual(restored_text[0].pos(), QPointF(*position))
        finally:
            restored.release_resources()
            restored.deleteLater()

    def test_resize_uses_viewport_pixels_and_persists_canvas_dimensions(self) -> None:
        self.assertTrue(self.view.transform().isIdentity())
        self.assertEqual(
            self.scene.sceneRect().size().toSize(), self.view.viewport().size()
        )

        self.view.resize(713, 509)
        QApplication.processEvents()

        resized = self.view.viewport().size()
        self.assertEqual(self.scene.sceneRect().size().toSize(), resized)
        self.assertTrue(self.view.transform().isIdentity())

        restored = CanvasScene()
        try:
            restored.restore_document(self.scene.serialize_document())
            self.assertEqual(restored.sceneRect().size().toSize(), resized)
        finally:
            restored.release_resources()
            restored.deleteLater()

    def test_view_tool_signal_keeps_window_toolbar_selection_in_sync(self) -> None:
        window = CanvasWindow()
        window.show()
        QApplication.processEvents()
        try:
            window._text_action.trigger()
            self.assertEqual(window.view.tool, "text")
            self.assertTrue(window._text_action.isChecked())
            self.assertFalse(window._draw_action.isChecked())
            self.assertIn("click the canvas", window.statusBar().currentMessage())

            window.view.set_tool("select")
            self.assertTrue(window._select_action.isChecked())
            self.assertFalse(window._text_action.isChecked())
        finally:
            window.release_resources()
            window.deleteLater()
            QApplication.processEvents()

    def test_undo_redo_and_snapshot_preserve_full_geometry(self) -> None:
        expected = [(120, 130), (220, 210), (310, 110), (410, 190)]
        self._click(expected[0])
        for point in expected[1:-1]:
            self._move(point)
        self._click(expected[-1])

        self.scene.undo_stack.undo()
        self.assertEqual(self._strokes(), [])
        self.scene.undo_stack.redo()
        self.assertPathPoints(self._strokes()[0], expected)

        document = self.scene.serialize_document()
        restored = CanvasScene()
        try:
            restored.restore_document(document)
            strokes = self._strokes(restored)
            self.assertEqual(len(strokes), 1)
            self.assertPathPoints(strokes[0], expected)
        finally:
            restored.release_resources()
            restored.deleteLater()

    def test_click_only_stroke_renders_as_visible_dot(self) -> None:
        self._click((400, 300))
        self._click((400, 300))
        strokes = self._strokes()
        self.assertEqual(len(strokes), 1)
        self.assertEqual(strokes[0].path().elementCount(), 2)

        canvas_size = self.scene.sceneRect().size().toSize()
        image = QImage(
            canvas_size.width(),
            canvas_size.height(),
            QImage.Format.Format_ARGB32_Premultiplied,
        )
        painter = QPainter(image)
        self.scene.render(painter)
        painter.end()

        self.assertTrue(
            any(
                image.pixelColor(x, y).lightness() < 160
                for x in range(396, 405)
                for y in range(296, 305)
            )
        )


if __name__ == "__main__":
    unittest.main()

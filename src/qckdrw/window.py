from __future__ import annotations

from PySide6.QtCore import QEvent, Qt, Signal
from PySide6.QtGui import (
    QAction,
    QActionGroup,
    QCloseEvent,
    QHideEvent,
    QImage,
    QImageReader,
    QKeySequence,
    QPixmap,
    QResizeEvent,
)
from PySide6.QtWidgets import QApplication, QMainWindow, QMessageBox, QToolBar
from qckdrw.clipboard import copy_canvas

from qckdrw.canvas.items import EditableTextItem, ResizablePixmapItem
from qckdrw.canvas.scene import CanvasScene
from qckdrw.canvas.view import CanvasView


class CanvasWindow(QMainWindow):
    """A short-lived window containing one editable canvas document."""

    dismissed = Signal()
    completed = Signal()

    def __init__(self, document: bytes | None = None) -> None:
        super().__init__()
        self._dismissal_in_progress = False
        self._releasing = False
        self._released = False
        self._completion_in_progress = False

        self.setWindowTitle("Quick Canvas")
        self.setAttribute(Qt.WidgetAttribute.WA_DeleteOnClose, False)

        self.scene = CanvasScene(self)
        if document is not None:
            self.scene.restore_document(document)
        self.view = CanvasView(self.scene)
        self.setCentralWidget(self.view)

        self._toolbar = QToolBar("Canvas tools", self)
        self._toolbar.setObjectName("canvasTools")
        self._toolbar.setMovable(False)
        self._toolbar.setFloatable(False)
        self.addToolBar(Qt.ToolBarArea.TopToolBarArea, self._toolbar)
        self._create_actions()
        self.scene.completion_requested.connect(self.finish)

        self.statusBar().showMessage(
            "Draw: click once to start, move without holding a button, then click again to finish."
        )
        self.setMinimumSize(640, 460)
        available = self.screen().availableGeometry()
        self.resize(min(1000, available.width()), min(740, available.height()))
        self._fit_canvas()

    def _create_actions(self) -> None:
        tools = QActionGroup(self)
        tools.setExclusive(True)
        self._tool_actions = tools

        self._draw_action = QAction("Draw", self)
        self._draw_action.setCheckable(True)
        self._draw_action.setChecked(True)
        self._draw_action.setToolTip(
            "Draw: click to start, move without holding a button, and click to finish"
        )
        self._draw_action.setStatusTip(self._draw_action.toolTip())
        tools.addAction(self._draw_action)
        self._toolbar.addAction(self._draw_action)

        self._select_action = QAction("Select", self)
        self._select_action.setCheckable(True)
        self._select_action.setToolTip("Select and manipulate canvas items")
        self._select_action.setStatusTip(self._select_action.toolTip())
        tools.addAction(self._select_action)
        self._toolbar.addAction(self._select_action)

        self._draw_action.triggered.connect(lambda checked: checked and self._set_tool("draw"))
        self._select_action.triggered.connect(
            lambda checked: checked and self._set_tool("select")
        )
        self.view.set_tool("draw")

        self._toolbar.addSeparator()
        self._undo_action = self.scene.undo_stack.createUndoAction(self, "Undo")
        self._undo_action.setShortcuts(QKeySequence.StandardKey.Undo)
        self._undo_action.setToolTip("Undo the last canvas change")
        self._toolbar.addAction(self._undo_action)

        self._redo_action = self.scene.undo_stack.createRedoAction(self, "Redo")
        redo_shortcuts = list(QKeySequence.keyBindings(QKeySequence.StandardKey.Redo))
        for shortcut in (QKeySequence("Ctrl+Y"), QKeySequence("Shift+Ctrl+Z")):
            if shortcut not in redo_shortcuts:
                redo_shortcuts.append(shortcut)
        self._redo_action.setShortcuts(redo_shortcuts)
        self._redo_action.setToolTip("Redo the last undone canvas change")
        self._toolbar.addAction(self._redo_action)

        self._toolbar.addSeparator()
        self._paste_action = QAction("Paste", self)
        self._paste_action.setShortcuts(QKeySequence.StandardKey.Paste)
        self._paste_action.setShortcutContext(
            Qt.ShortcutContext.WindowShortcut
        )
        self._paste_action.setToolTip("Paste an image or text onto the canvas")
        self._paste_action.triggered.connect(self._paste_requested)
        self._toolbar.addAction(self._paste_action)
        self._toolbar.addSeparator()
        self._done_action = QAction("Done", self)
        self._done_action.setShortcuts(
            (QKeySequence("Ctrl+Return"), QKeySequence("Ctrl+Enter"))
        )
        self._done_action.setShortcutContext(Qt.ShortcutContext.WindowShortcut)
        self._done_action.setToolTip("Copy the canvas as an image and finish")
        self._done_action.triggered.connect(self.finish)
        self._toolbar.addAction(self._done_action)


        self._dismiss_action = QAction(self)
        self._dismiss_action.setShortcut(QKeySequence(Qt.Key.Key_Escape))
        self._dismiss_action.setShortcutContext(Qt.ShortcutContext.WindowShortcut)
        self._dismiss_action.triggered.connect(self._request_dismissal)
        self.addAction(self._dismiss_action)

    def _set_tool(self, tool: str) -> None:
        if self._released:
            return
        self.view.finish_stroke()
        self.scene.finish_editing()
        self.view.set_tool(tool)
        if tool == "draw":
            self.statusBar().showMessage(
                "Draw: click once to start, move without holding a button, then click again to finish."
            )
        else:
            self.statusBar().showMessage("Select: click an item to select or move it.")

    def _editing_text_item(self) -> EditableTextItem | None:
        item = self.scene.focusItem()
        if (
            isinstance(item, EditableTextItem)
            and item.textInteractionFlags()
            & Qt.TextInteractionFlag.TextEditorInteraction
        ):
            return item
        return None

    def _paste_requested(self) -> None:
        editing_item = self._editing_text_item()
        keyboard_paste = bool(
            QApplication.keyboardModifiers()
            & (Qt.KeyboardModifier.ControlModifier | Qt.KeyboardModifier.MetaModifier)
        )
        if editing_item is not None and keyboard_paste:
            mime = QApplication.clipboard().mimeData()
            if mime.hasText():
                cursor = editing_item.textCursor()
                cursor.insertText(mime.text())
                editing_item.setTextCursor(cursor)
            return
        self.paste()

    def paste(self) -> None:
        """Paste the highest-priority supported clipboard payload."""
        mime = QApplication.clipboard().mimeData()
        pasted_items: list[ResizablePixmapItem | EditableTextItem] = []

        if mime.hasImage():
            image_data = mime.imageData()
            if isinstance(image_data, QPixmap):
                image = image_data.toImage()
            elif isinstance(image_data, QImage):
                image = image_data
            else:
                image = QImage()
            if not image.isNull():
                pasted_items.append(ResizablePixmapItem(image))

        if not pasted_items and mime.hasUrls():
            for url in mime.urls():
                if not url.isLocalFile():
                    continue
                reader = QImageReader(url.toLocalFile())
                reader.setAutoTransform(True)
                image = reader.read()
                if not image.isNull():
                    pasted_items.append(ResizablePixmapItem(image))

        if not pasted_items and mime.hasText():
            text = mime.text()
            if text:
                pasted_items.append(EditableTextItem(text))

        if not pasted_items:
            return

        self.view.finish_stroke()
        self.scene.finish_editing()
        self._select_action.setChecked(True)
        self.view.set_tool("select")
        self.statusBar().showMessage("Select: click an item to select or move it.")
        for item in pasted_items:
            self.scene.add_pasted_item(item)

    def finish(self) -> None:
        """Copy the completed canvas and notify its lifecycle owner."""
        if (
            self._completion_in_progress
            or self._dismissal_in_progress
            or self._releasing
            or self._released
        ):
            return
        self._completion_in_progress = True
        selected_items = self.scene.selectedItems()
        try:
            self.view.finish_stroke()
            self.scene.finish_editing()
            self.scene.clearFocus()
            self.scene.clearSelection()
            copy_canvas(self.scene)
            self.scene.undo_stack.setClean()
        except Exception as error:
            for item in selected_items:
                if item.scene() is self.scene:
                    item.setSelected(True)
            self._completion_in_progress = False
            message = str(error) or "The canvas could not be copied."
            self.statusBar().showMessage(f"Unable to finish: {message}")
            QMessageBox.critical(self, "Unable to Finish Canvas", message)
            return
        self.completed.emit()

    def _request_dismissal(self) -> None:
        if (
            self._completion_in_progress
            or self._dismissal_in_progress
            or self._releasing
            or self._released
        ):
            return
        self._dismissal_in_progress = True
        try:
            self.view.finish_stroke()
            self.scene.finish_editing()
            self.dismissed.emit()
        finally:
            if not self._released:
                self._dismissal_in_progress = False

    def serialize_document(self) -> bytes:
        if self._released:
            raise RuntimeError("Canvas resources have already been released.")
        self.view.finish_stroke()
        self.scene.finish_editing()
        return self.scene.serialize_document()

    def release_resources(self) -> None:
        if self._released or self._releasing:
            return
        self._releasing = True
        try:
            self.view.finish_stroke()
            self.scene.finish_editing()
            self.view.setUpdatesEnabled(False)
            self.view.viewport().setUpdatesEnabled(False)
            self.scene.release_resources()
            self.view.setScene(None)
            view = self.takeCentralWidget()
            if view is not None:
                view.setParent(None)
                view.deleteLater()
            self.hide()
            self._released = True
        finally:
            self._releasing = False

    def _fit_canvas(self) -> None:
        if not self._released:
            self.view.fitInView(
                self.scene.sceneRect(), Qt.AspectRatioMode.KeepAspectRatio
            )

    def resizeEvent(self, event: QResizeEvent) -> None:
        super().resizeEvent(event)
        self._fit_canvas()

    def closeEvent(self, event: QCloseEvent) -> None:
        event.ignore()
        self._request_dismissal()

    def hideEvent(self, event: QHideEvent) -> None:
        super().hideEvent(event)
        if (
            not self._released
            and not self._releasing
            and not self._completion_in_progress
        ):
            self._request_dismissal()

    def changeEvent(self, event: QEvent) -> None:
        super().changeEvent(event)
        if (
            event.type() == QEvent.Type.WindowStateChange
            and self.isMinimized()
            and not self._releasing
            and not self._completion_in_progress
        ):
            self._request_dismissal()

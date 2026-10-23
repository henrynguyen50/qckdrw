from __future__ import annotations

from typing import TYPE_CHECKING

from PySide6.QtGui import QPainterPath, QPen, QUndoCommand
from PySide6.QtWidgets import QGraphicsItem, QGraphicsPathItem

if TYPE_CHECKING:
    from qckdrw.canvas.scene import CanvasScene


class StrokeItem(QGraphicsPathItem):
    """A committed stroke in canvas coordinates."""

    def __init__(self, path: QPainterPath, pen: QPen, sequence: int = 0) -> None:
        super().__init__(QPainterPath(path))
        self.sequence = sequence
        self.setPen(QPen(pen))
        self.setFlag(QGraphicsItem.GraphicsItemFlag.ItemIsSelectable, True)
        self.setFlag(QGraphicsItem.GraphicsItemFlag.ItemIsMovable, True)


class AddStrokeCommand(QUndoCommand):
    """Add one stroke while retaining it safely when it is outside the scene."""

    def __init__(
        self,
        scene: CanvasScene,
        path: QPainterPath,
        pen: QPen,
        sequence: int | None = None,
    ) -> None:
        super().__init__("Draw stroke")
        self._scene = scene
        self._item = StrokeItem(
            path,
            pen,
            scene.allocate_stroke_sequence() if sequence is None else sequence,
        )

    @property
    def item(self) -> StrokeItem:
        return self._item

    def redo(self) -> None:
        if self._item.scene() is None:
            self._scene.addItem(self._item)

    def undo(self) -> None:
        if self._item.scene() is self._scene:
            self._scene.removeItem(self._item)


class AddItemCommand(QUndoCommand):
    """Add an already-created graphics item to a scene."""

    def __init__(
        self,
        scene: CanvasScene,
        item: QGraphicsItem,
        text: str = "Paste item",
    ) -> None:
        super().__init__(text)
        self._scene = scene
        self._item = item

    @property
    def item(self) -> QGraphicsItem:
        return self._item

    def redo(self) -> None:
        if self._item.scene() is None:
            self._scene.addItem(self._item)

    def undo(self) -> None:
        if self._item.scene() is self._scene:
            self._scene.removeItem(self._item)


class MoveItemCommand(QUndoCommand):
    """Restore the scene position on either side of one completed drag."""

    def __init__(self, item: QGraphicsItem, old_position: object, new_position: object) -> None:
        super().__init__("Move item")
        from PySide6.QtCore import QPointF

        self._item = item
        self._old_position = QPointF(old_position)
        self._new_position = QPointF(new_position)

    def redo(self) -> None:
        self._item.setPos(self._new_position)

    def undo(self) -> None:
        self._item.setPos(self._old_position)


class ResizeItemCommand(QUndoCommand):
    """Restore a resizable item's position and content rectangle."""

    def __init__(
        self,
        item: QGraphicsItem,
        old_position: object,
        old_rect: object,
        new_position: object,
        new_rect: object,
    ) -> None:
        super().__init__("Resize image")
        from PySide6.QtCore import QPointF, QRectF

        self._item = item
        self._old_position = QPointF(old_position)
        self._old_rect = QRectF(old_rect)
        self._new_position = QPointF(new_position)
        self._new_rect = QRectF(new_rect)

    def _apply(self, position: object, rect: object) -> None:
        self._item.setPos(position)
        self._item.set_content_rect(rect)  # type: ignore[attr-defined]

    def redo(self) -> None:
        self._apply(self._new_position, self._new_rect)

    def undo(self) -> None:
        self._apply(self._old_position, self._old_rect)


class EditTextCommand(QUndoCommand):
    """Restore the plain text on either side of one editing session."""

    def __init__(self, item: QGraphicsItem, old_text: str, new_text: str) -> None:
        super().__init__("Edit text")
        self._item = item
        self._old_text = old_text
        self._new_text = new_text

    def redo(self) -> None:
        self._item.setPlainText(self._new_text)  # type: ignore[attr-defined]

    def undo(self) -> None:
        self._item.setPlainText(self._old_text)  # type: ignore[attr-defined]

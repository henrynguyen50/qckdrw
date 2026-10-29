from __future__ import annotations

import math
from typing import TYPE_CHECKING

from PySide6.QtCore import QPointF, QRectF, Qt
from PySide6.QtGui import QPainter, QPainterPath, QPen, QUndoCommand
from PySide6.QtWidgets import (
    QGraphicsItem,
    QGraphicsPathItem,
    QGraphicsSceneMouseEvent,
    QStyleOptionGraphicsItem,
    QWidget,
)

if TYPE_CHECKING:
    from qckdrw.canvas.scene import CanvasScene

_HANDLE_SIZE = 8.0
_MIN_DISPLAY_SIZE = 1.0


def _push_undo(item: QGraphicsItem, command: QUndoCommand) -> None:
    undo_stack = getattr(item.scene(), "undo_stack", None)
    if undo_stack is not None:
        undo_stack.push(command)


class ScalableItemMixin:
    """Add fixed-size selection handles and uniform resizing to a graphics item."""

    _HANDLE_NAMES = (
        "top_left",
        "top",
        "top_right",
        "right",
        "bottom_right",
        "bottom",
        "bottom_left",
        "left",
    )

    def _init_scalable_item(self) -> None:
        self._active_handle: str | None = None
        self._press_position = QPointF()
        self._press_scale = 1.0
        self._resize_anchor = QPointF()
        self._resize_local_anchor = QPointF()

    @property
    def content_rect(self) -> QRectF:
        return QRectF(super().boundingRect())  # type: ignore[misc]

    def _handles_visible(self) -> bool:
        return self.isSelected() and not bool(getattr(self, "editing", False))

    def _handle_size(self) -> float:
        scale = self.scale()
        return _HANDLE_SIZE / scale if scale > 0.0 else _HANDLE_SIZE

    def boundingRect(self) -> QRectF:
        margin = self._handle_size() / 2.0
        return self.content_rect.adjusted(-margin, -margin, margin, margin)

    def _handle_rects(self) -> dict[str, QRectF]:
        rect = self.content_rect
        size = self._handle_size()
        half = size / 2.0
        points = (
            rect.topLeft(),
            QPointF(rect.center().x(), rect.top()),
            rect.topRight(),
            QPointF(rect.right(), rect.center().y()),
            rect.bottomRight(),
            QPointF(rect.center().x(), rect.bottom()),
            rect.bottomLeft(),
            QPointF(rect.left(), rect.center().y()),
        )
        return {
            name: QRectF(point.x() - half, point.y() - half, size, size)
            for name, point in zip(self._HANDLE_NAMES, points, strict=True)
        }

    def _handle_at(self, position: QPointF) -> str | None:
        if not self._handles_visible():
            return None
        for name, rect in self._handle_rects().items():
            if rect.contains(position):
                return name
        return None

    def shape(self) -> QPainterPath:
        path = QPainterPath(super().shape())  # type: ignore[misc]
        if self._handles_visible():
            for rect in self._handle_rects().values():
                path.addRect(rect)
        return path

    def paint(
        self,
        painter: QPainter,
        option: QStyleOptionGraphicsItem,
        widget: QWidget | None = None,
    ) -> None:
        super().paint(painter, option, widget)  # type: ignore[misc]
        if not self._handles_visible():
            return
        pen = QPen(Qt.GlobalColor.darkGray, 1.0)
        pen.setCosmetic(True)
        painter.setPen(pen)
        painter.setBrush(Qt.BrushStyle.NoBrush)
        painter.drawRect(self.content_rect)
        painter.setBrush(Qt.GlobalColor.white)
        for rect in self._handle_rects().values():
            painter.drawRect(rect)

    def mousePressEvent(self, event: QGraphicsSceneMouseEvent) -> None:
        self._press_position = QPointF(self.pos())
        self._press_scale = self.scale()
        handle = self._handle_at(event.pos())
        if handle is None:
            super().mousePressEvent(event)  # type: ignore[misc]
            return

        rect = self.content_rect
        anchors = {
            "top_left": rect.bottomRight(),
            "top": QPointF(rect.center().x(), rect.bottom()),
            "top_right": rect.bottomLeft(),
            "right": QPointF(rect.left(), rect.center().y()),
            "bottom_right": rect.topLeft(),
            "bottom": QPointF(rect.center().x(), rect.top()),
            "bottom_left": rect.topRight(),
            "left": QPointF(rect.right(), rect.center().y()),
        }
        self._active_handle = handle
        self._resize_local_anchor = anchors[handle]
        self._resize_anchor = self.mapToScene(self._resize_local_anchor)
        event.accept()

    def mouseMoveEvent(self, event: QGraphicsSceneMouseEvent) -> None:
        if self._active_handle is None:
            super().mouseMoveEvent(event)  # type: ignore[misc]
            return
        self._resize_from_scene_point(self._active_handle, event.scenePos())
        event.accept()

    def mouseReleaseEvent(self, event: QGraphicsSceneMouseEvent) -> None:
        if self._active_handle is not None:
            self._active_handle = None
            if self.pos() != self._press_position or self.scale() != self._press_scale:
                _push_undo(
                    self,
                    ScaleItemCommand(
                        self,
                        self._press_position,
                        self._press_scale,
                        self.pos(),
                        self.scale(),
                    ),
                )
            event.accept()
            return

        super().mouseReleaseEvent(event)  # type: ignore[misc]
        if (
            not bool(getattr(self, "editing", False))
            and self.pos() != self._press_position
        ):
            _push_undo(self, MoveItemCommand(self, self._press_position, self.pos()))

    def _resize_from_scene_point(
        self,
        handle: str,
        scene_point: QPointF,
    ) -> None:
        rect = self.content_rect
        horizontal = handle not in {"top", "bottom"}
        vertical = handle not in {"left", "right"}
        width = max(rect.width(), _MIN_DISPLAY_SIZE)
        height = max(rect.height(), _MIN_DISPLAY_SIZE)
        dx = abs(scene_point.x() - self._resize_anchor.x())
        dy = abs(scene_point.y() - self._resize_anchor.y())

        if horizontal and vertical:
            scale = (dx * width + dy * height) / (width * width + height * height)
        elif horizontal:
            scale = dx / width
        else:
            scale = dy / height
        minimum_scale = max(_MIN_DISPLAY_SIZE / width, _MIN_DISPLAY_SIZE / height)
        scale = max(minimum_scale, scale)
        if not math.isfinite(scale):
            return

        self.prepareGeometryChange()
        self.setScale(scale)
        anchor_after = self.mapToScene(self._resize_local_anchor)
        scene_delta = self._resize_anchor - anchor_after
        parent = self.parentItem()
        if parent is None:
            self.setPos(self.pos() + scene_delta)
        else:
            self.setPos(
                self.pos()
                + parent.mapFromScene(self._resize_anchor)
                - parent.mapFromScene(anchor_after)
            )
        self.update()


class StrokeItem(ScalableItemMixin, QGraphicsPathItem):
    """A committed stroke with movable, uniformly resizable geometry."""

    @property
    def content_rect(self) -> QRectF:
        # Calling boundingRect() here re-enters this mixin's shape() override in
        # QGraphicsPathItem. The base shape includes the pen's caps and joins
        # without dispatching through the selection-handle shape.
        return QRectF(QGraphicsPathItem.shape(self).boundingRect())

    def __init__(self, path: QPainterPath, pen: QPen, sequence: int = 0) -> None:
        super().__init__(QPainterPath(path))
        self._init_scalable_item()
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

    def __init__(
        self,
        item: QGraphicsItem,
        old_position: object,
        new_position: object,
    ) -> None:
        super().__init__("Move item")
        self._item = item
        self._old_position = QPointF(old_position)
        self._new_position = QPointF(new_position)

    def redo(self) -> None:
        self._item.setPos(self._new_position)

    def undo(self) -> None:
        self._item.setPos(self._old_position)


class ScaleItemCommand(QUndoCommand):
    """Restore an item's position and uniform display scale."""

    def __init__(
        self,
        item: QGraphicsItem,
        old_position: object,
        old_scale: float,
        new_position: object,
        new_scale: float,
    ) -> None:
        super().__init__("Resize item")
        self._item = item
        self._old_position = QPointF(old_position)
        self._old_scale = old_scale
        self._new_position = QPointF(new_position)
        self._new_scale = new_scale

    def _apply(self, position: QPointF, scale: float) -> None:
        self._item.prepareGeometryChange()
        self._item.setScale(scale)
        self._item.setPos(position)
        self._item.update()

    def redo(self) -> None:
        self._apply(self._new_position, self._new_scale)

    def undo(self) -> None:
        self._apply(self._old_position, self._old_scale)


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

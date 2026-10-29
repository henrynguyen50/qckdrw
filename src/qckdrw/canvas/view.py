from __future__ import annotations

from typing import Literal

from PySide6.QtCore import QPointF, Signal, Qt
from PySide6.QtGui import (
    QColor,
    QHideEvent,
    QMouseEvent,
    QPainter,
    QPainterPath,
    QPen,
    QResizeEvent,
)
from PySide6.QtWidgets import QGraphicsPathItem, QGraphicsView, QWidget

from qckdrw.canvas.commands import AddItemCommand, AddStrokeCommand
from qckdrw.canvas.items import EditableTextItem
from qckdrw.canvas.scene import CanvasScene

Tool = Literal["draw", "text", "select"]
_DOT_SEGMENT_LENGTH = 0.01


def _drawing_pen() -> QPen:
    pen = QPen(QColor(Qt.GlobalColor.black))
    pen.setWidthF(4.0)
    pen.setStyle(Qt.PenStyle.SolidLine)
    pen.setCapStyle(Qt.PenCapStyle.RoundCap)
    pen.setJoinStyle(Qt.PenJoinStyle.RoundJoin)
    return pen


class CanvasView(QGraphicsView):
    """Canvas viewport for drawing, text creation, and item selection."""
    tool_changed = Signal(str)

    def __init__(
        self,
        scene: CanvasScene,
        parent: QWidget | None = None,
        *,
        track_canvas_size: bool = True,
    ) -> None:
        super().__init__(scene, parent)
        self._canvas_scene = scene
        self._track_canvas_size = track_canvas_size
        self._tool: Tool = "draw"
        self._active_path: QPainterPath | None = None
        self._preview: QGraphicsPathItem | None = None
        self._start_point: QPointF | None = None
        self._has_moved = False

        self.setRenderHint(QPainter.RenderHint.Antialiasing, True)
        self.setMouseTracking(True)
        self.viewport().setMouseTracking(True)
        self.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self.setVerticalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.setTransformationAnchor(QGraphicsView.ViewportAnchor.AnchorViewCenter)
        self.setResizeAnchor(QGraphicsView.ViewportAnchor.AnchorViewCenter)
        self.setDragMode(QGraphicsView.DragMode.NoDrag)

    @property
    def drawing(self) -> bool:
        return self._active_path is not None

    @property
    def tool(self) -> Tool:
        return self._tool

    def set_tool(self, tool: Tool) -> None:
        if tool not in ("draw", "text", "select"):
            raise ValueError(f"Unknown canvas tool: {tool}")
        if tool == self._tool:
            return
        self.finish_stroke()
        self._tool = tool
        if tool == "select":
            self.setDragMode(QGraphicsView.DragMode.RubberBandDrag)
        else:
            self.setDragMode(QGraphicsView.DragMode.NoDrag)
            self._canvas_scene.clearSelection()
        self.tool_changed.emit(tool)

    def finish_stroke(self) -> None:
        if self._active_path is None:
            return

        path = QPainterPath(self._active_path)
        preview = self._preview
        self._active_path = None
        self._preview = None
        self._start_point = None
        self._has_moved = False

        if preview is not None and preview.scene() is self._canvas_scene:
            self._canvas_scene.removeItem(preview)
        self._canvas_scene.undo_stack.push(
            AddStrokeCommand(self._canvas_scene, path, _drawing_pen())
        )

    def _point_in_canvas(self, event: QMouseEvent) -> QPointF | None:
        point = self.mapToScene(event.position().toPoint())
        if self._canvas_scene.sceneRect().contains(point):
            return point
        return None

    def _start_stroke(self, point: QPointF) -> None:
        path = QPainterPath()
        path.moveTo(point)
        # Qt does not consistently rasterize a zero-length path. A sub-pixel
        # round-capped segment gives a click-only stroke a visible dot.
        path.lineTo(point.x() + _DOT_SEGMENT_LENGTH, point.y())
        preview = QGraphicsPathItem(path)
        preview.setPen(_drawing_pen())
        preview.setZValue(1_000_000.0)
        self._canvas_scene.addItem(preview)

        self._active_path = path
        self._preview = preview
        self._start_point = QPointF(point)
        self._has_moved = False

    def _extend_stroke(self, point: QPointF) -> None:
        if self._active_path is None or self._preview is None:
            return
        if not self._has_moved:
            assert self._start_point is not None
            if point == self._start_point:
                return
            path = QPainterPath()
            path.moveTo(self._start_point)
            path.lineTo(point)
            self._active_path = path
            self._has_moved = True
        elif point != self._active_path.currentPosition():
            self._active_path.lineTo(point)
        self._preview.setPath(self._active_path)

    def _create_text(self, point: QPointF) -> None:
        item = EditableTextItem("")
        item.setPos(point)
        self._canvas_scene.clearSelection()
        item.done_requested.connect(self._canvas_scene.completion_requested.emit)
        self._canvas_scene.undo_stack.push(
            AddItemCommand(self._canvas_scene, item, "Add text")
        )
        item.setSelected(True)
        item.begin_editing()
        self.set_tool("select")

    def mousePressEvent(self, event: QMouseEvent) -> None:
        if self._tool == "select":
            super().mousePressEvent(event)
            return
        if event.button() == Qt.MouseButton.LeftButton:
            point = self._point_in_canvas(event)
            if point is not None:
                if self._tool == "text":
                    self._create_text(point)
                elif self.drawing:
                    self._extend_stroke(point)
                    self.finish_stroke()
                else:
                    self._start_stroke(point)
            event.accept()
            return
        event.accept()

    def mouseMoveEvent(self, event: QMouseEvent) -> None:
        if self._tool == "select":
            super().mouseMoveEvent(event)
            return
        if (
            self._tool == "draw"
            and self.drawing
            and event.buttons() == Qt.MouseButton.NoButton
        ):
            point = self._point_in_canvas(event)
            if point is not None:
                self._extend_stroke(point)
        event.accept()

    def mouseReleaseEvent(self, event: QMouseEvent) -> None:
        if self._tool == "select":
            super().mouseReleaseEvent(event)
            return
        event.accept()

    def set_canvas_size_tracking(self, enabled: bool) -> None:
        """Choose whether viewport resizes update the document dimensions."""
        self._track_canvas_size = enabled
        if enabled:
            self._update_canvas_size()

    def _update_canvas_size(self) -> None:
        if not self._track_canvas_size or self.scene() is not self._canvas_scene:
            return
        viewport_size = self.viewport().size()
        if viewport_size.width() <= 0 or viewport_size.height() <= 0:
            return
        self.resetTransform()
        self._canvas_scene.set_canvas_size(
            viewport_size.width(), viewport_size.height()
        )

    def resizeEvent(self, event: QResizeEvent) -> None:
        super().resizeEvent(event)
        self._update_canvas_size()

    def hideEvent(self, event: QHideEvent) -> None:
        self.finish_stroke()
        super().hideEvent(event)


from __future__ import annotations

import base64
import math
from typing import Any

from PySide6.QtCore import QByteArray, QBuffer, QEvent, QIODevice, QPointF, QRectF, Qt, Signal
from PySide6.QtGui import (
    QColor,
    QFont,
    QFocusEvent,
    QImage,
    QKeyEvent,
    QKeySequence,
    QPainter,
    QPainterPath,
    QPen,
    QPixmap,
)
from PySide6.QtWidgets import (
    QGraphicsItem,
    QGraphicsObject,
    QGraphicsSceneMouseEvent,
    QGraphicsTextItem,
    QStyleOptionGraphicsItem,
    QWidget,
)

from qckdrw.canvas.commands import (
    EditTextCommand,
    MoveItemCommand,
    ResizeItemCommand,
    ScalableItemMixin,
)

_MIN_SIZE = 1.0
_HANDLE_SIZE = 8.0


def _finite_number(value: object, name: str) -> float:
    try:
        number = float(value)
    except (TypeError, ValueError) as error:
        raise ValueError(f"Invalid {name}") from error
    if not math.isfinite(number):
        raise ValueError(f"Invalid {name}")
    return number


def _position_from_record(record: dict[str, Any]) -> QPointF:
    position = record.get("position")
    if not isinstance(position, dict):
        raise ValueError("Invalid item position")
    return QPointF(
        _finite_number(position.get("x"), "item position"),
        _finite_number(position.get("y"), "item position"),
    )


def _push_undo(item: QGraphicsItem, command: object) -> None:
    scene = item.scene()
    undo_stack = getattr(scene, "undo_stack", None)
    if undo_stack is not None:
        undo_stack.push(command)


class ResizablePixmapItem(QGraphicsObject):
    """A movable image with eight selection handles.

    Corner drags preserve the source aspect ratio. Holding Shift while dragging a
    corner permits a free-form resize; edge handles always resize one axis.
    The source pixmap is retained at its original resolution and is only scaled
    by the painter when displayed.
    """

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

    def __init__(self, image: QImage) -> None:
        super().__init__()
        if image.isNull():
            raise ValueError("Image must not be null")
        self._pixmap = QPixmap.fromImage(image)
        self._content_rect = QRectF(
            0.0,
            0.0,
            float(self._pixmap.width()),
            float(self._pixmap.height()),
        )
        self._active_handle: str | None = None
        self._press_position = QPointF()
        self._press_rect = QRectF()
        self._resize_anchor = QPointF()
        self.setFlags(
            QGraphicsItem.GraphicsItemFlag.ItemIsMovable
            | QGraphicsItem.GraphicsItemFlag.ItemIsSelectable
        )
        self.setAcceptHoverEvents(True)

    @property
    def content_rect(self) -> QRectF:
        return QRectF(self._content_rect)

    def set_content_rect(self, rect: object) -> None:
        target = QRectF(rect)
        if (
            not math.isfinite(target.width())
            or not math.isfinite(target.height())
            or target.width() < _MIN_SIZE
            or target.height() < _MIN_SIZE
        ):
            raise ValueError("Image dimensions must be positive and finite")
        self.prepareGeometryChange()
        self._content_rect = QRectF(0.0, 0.0, target.width(), target.height())
        self.update()

    def boundingRect(self) -> QRectF:
        margin = _HANDLE_SIZE / 2.0
        return self._content_rect.adjusted(-margin, -margin, margin, margin)

    def shape(self) -> QPainterPath:
        path = QPainterPath()
        path.addRect(self._content_rect)
        if self.isSelected():
            for rect in self._handle_rects().values():
                path.addRect(rect)
        return path

    def paint(
        self,
        painter: QPainter,
        option: QStyleOptionGraphicsItem,
        widget: QWidget | None = None,
    ) -> None:
        del option, widget
        painter.setRenderHint(QPainter.RenderHint.SmoothPixmapTransform, False)
        painter.drawPixmap(self._content_rect, self._pixmap, QRectF(self._pixmap.rect()))
        if not self.isSelected():
            return
        painter.setPen(QPen(QColor("#333333"), 1.0))
        painter.setBrush(Qt.BrushStyle.NoBrush)
        painter.drawRect(self._content_rect)
        painter.setBrush(Qt.GlobalColor.white)
        for rect in self._handle_rects().values():
            painter.drawRect(rect)

    def _handle_rects(self) -> dict[str, QRectF]:
        rect = self._content_rect
        half = _HANDLE_SIZE / 2.0
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
            name: QRectF(point.x() - half, point.y() - half, _HANDLE_SIZE, _HANDLE_SIZE)
            for name, point in zip(self._HANDLE_NAMES, points, strict=True)
        }

    def _handle_at(self, position: QPointF) -> str | None:
        if not self.isSelected():
            return None
        for name, rect in self._handle_rects().items():
            if rect.contains(position):
                return name
        return None

    def mousePressEvent(self, event: QGraphicsSceneMouseEvent) -> None:
        self._press_position = self.pos()
        self._press_rect = self.content_rect
        handle = self._handle_at(event.pos())
        if handle is None:
            super().mousePressEvent(event)
            return
        self._active_handle = handle
        rect = self._content_rect
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
        self._resize_anchor = self.mapToScene(anchors[handle])
        event.accept()

    def mouseMoveEvent(self, event: QGraphicsSceneMouseEvent) -> None:
        if self._active_handle is None:
            super().mouseMoveEvent(event)
            return
        preserve_aspect = not bool(
            event.modifiers() & Qt.KeyboardModifier.ShiftModifier
        )
        self._resize_from_scene_point(
            self._active_handle,
            event.scenePos(),
            preserve_aspect,
        )
        event.accept()

    def mouseReleaseEvent(self, event: QGraphicsSceneMouseEvent) -> None:
        if self._active_handle is not None:
            self._active_handle = None
            if self.pos() != self._press_position or self._content_rect != self._press_rect:
                _push_undo(
                    self,
                    ResizeItemCommand(
                        self,
                        self._press_position,
                        self._press_rect,
                        self.pos(),
                        self._content_rect,
                    ),
                )
            event.accept()
            return
        super().mouseReleaseEvent(event)
        if self.pos() != self._press_position:
            _push_undo(self, MoveItemCommand(self, self._press_position, self.pos()))

    def _resize_from_scene_point(
        self,
        handle: str,
        scene_point: QPointF,
        preserve_aspect: bool = True,
    ) -> None:
        anchor = self._resize_anchor
        left_side = handle in {"top_left", "left", "bottom_left"}
        top_side = handle in {"top_left", "top", "top_right"}
        horizontal = handle not in {"top", "bottom"}
        vertical = handle not in {"left", "right"}

        width = max(_MIN_SIZE, abs(scene_point.x() - anchor.x())) if horizontal else self._press_rect.width()
        height = max(_MIN_SIZE, abs(scene_point.y() - anchor.y())) if vertical else self._press_rect.height()
        if horizontal and vertical and preserve_aspect:
            ratio = self._pixmap.width() / self._pixmap.height()
            if width / height > ratio:
                height = width / ratio
            else:
                width = height * ratio

        if horizontal:
            x = anchor.x() - width if left_side else anchor.x()
        else:
            x = self._press_position.x()
        if vertical:
            y = anchor.y() - height if top_side else anchor.y()
        else:
            y = self._press_position.y()
        self.setPos(x, y)
        self.set_content_rect(QRectF(0.0, 0.0, width, height))

    def to_record(self) -> dict[str, Any]:
        data = QByteArray()
        buffer = QBuffer(data)
        if not buffer.open(QIODevice.OpenModeFlag.WriteOnly) or not self._pixmap.save(buffer, "PNG"):
            raise ValueError("Could not encode image")
        buffer.close()
        return {
            "type": "image",
            "png": bytes(data.toBase64()).decode("ascii"),
            "width": self._content_rect.width(),
            "height": self._content_rect.height(),
            "position": {"x": self.pos().x(), "y": self.pos().y()},
        }

    @classmethod
    def from_record(cls, record: object) -> ResizablePixmapItem:
        if not isinstance(record, dict) or record.get("type") != "image":
            raise ValueError("Invalid image record")
        encoded = record.get("png")
        if not isinstance(encoded, str):
            raise ValueError("Invalid image data")
        try:
            raw = base64.b64decode(encoded, validate=True)
        except (ValueError, UnicodeEncodeError) as error:
            raise ValueError("Invalid image data") from error
        image = QImage.fromData(raw, "PNG")
        if image.isNull():
            raise ValueError("Invalid image data")
        width = _finite_number(record.get("width"), "image width")
        height = _finite_number(record.get("height"), "image height")
        if width < _MIN_SIZE or height < _MIN_SIZE:
            raise ValueError("Image dimensions must be positive")
        item = cls(image)
        item.set_content_rect(QRectF(0.0, 0.0, width, height))
        item.setPos(_position_from_record(record))
        return item


class EditableTextItem(ScalableItemMixin, QGraphicsTextItem):
    """Movable, resizable plain text that edits on a double-click."""

    done_requested = Signal()

    def __init__(self, text: str) -> None:
        super().__init__(text)
        self._init_scalable_item()
        self.setDefaultTextColor(QColor(Qt.GlobalColor.black))
        self._editing = False
        self._text_before_edit = text
        self.setFlags(
            QGraphicsItem.GraphicsItemFlag.ItemIsMovable
            | QGraphicsItem.GraphicsItemFlag.ItemIsSelectable
        )
        self.setTextInteractionFlags(Qt.TextInteractionFlag.NoTextInteraction)

    @property
    def editing(self) -> bool:
        return self._editing


    def mouseDoubleClickEvent(self, event: QGraphicsSceneMouseEvent) -> None:
        self.begin_editing()
        super().mouseDoubleClickEvent(event)

    def begin_editing(self) -> None:
        if self._editing:
            return
        self._editing = True
        self._text_before_edit = self.toPlainText()
        self.document().setUndoRedoEnabled(True)
        self.setFlag(QGraphicsItem.GraphicsItemFlag.ItemIsFocusable, True)
        self.setTextInteractionFlags(Qt.TextInteractionFlag.TextEditorInteraction)
        self.setFocus(Qt.FocusReason.MouseFocusReason)

    def finish_editing(self) -> None:
        if not self._editing:
            return
        old_text = self._text_before_edit
        new_text = self.toPlainText()
        self._editing = False
        self.setTextInteractionFlags(Qt.TextInteractionFlag.NoTextInteraction)
        self.clearFocus()
        self.setFlag(QGraphicsItem.GraphicsItemFlag.ItemIsFocusable, False)
        self.document().clearUndoRedoStacks()
        self.document().setUndoRedoEnabled(False)
        if old_text != new_text:
            _push_undo(self, EditTextCommand(self, old_text, new_text))

    def focusOutEvent(self, event: QFocusEvent) -> None:
        self.finish_editing()
        super().focusOutEvent(event)

    def sceneEvent(self, event: QEvent) -> bool:
        if (
            self._editing
            and event.type() == QEvent.Type.ShortcutOverride
            and isinstance(event, QKeyEvent)
            and (
                event.matches(QKeySequence.StandardKey.Undo)
                or event.matches(QKeySequence.StandardKey.Redo)
            )
        ):
            event.accept()
            return True
        return super().sceneEvent(event)

    def keyPressEvent(self, event: QKeyEvent) -> None:
        modifiers = event.modifiers()
        if (
            self._editing
            and event.key() in (Qt.Key.Key_Return, Qt.Key.Key_Enter)
            and modifiers
            & (Qt.KeyboardModifier.ControlModifier | Qt.KeyboardModifier.MetaModifier)
        ):
            event.accept()
            self.finish_editing()
            self.done_requested.emit()
            return
        super().keyPressEvent(event)

    def to_record(self) -> dict[str, Any]:
        return {
            "type": "text",
            "text": self.toPlainText(),
            "font": self.font().toString(),
            "color": int(self.defaultTextColor().rgba()),
            "position": {"x": self.pos().x(), "y": self.pos().y()},
            "scale": self.scale(),
        }

    @classmethod
    def from_record(cls, record: object) -> EditableTextItem:
        if not isinstance(record, dict) or record.get("type") != "text":
            raise ValueError("Invalid text record")
        text = record.get("text")
        font_description = record.get("font")
        if not isinstance(text, str) or not isinstance(font_description, str):
            raise ValueError("Invalid text record")
        font = QFont()
        if not font.fromString(font_description):
            raise ValueError("Invalid text font")
        try:
            color = QColor.fromRgba(int(record.get("color")))
        except (TypeError, ValueError) as error:
            raise ValueError("Invalid text color") from error
        if not color.isValid():
            raise ValueError("Invalid text color")
        scale = _finite_number(record.get("scale", 1.0), "text scale")
        if scale <= 0.0:
            raise ValueError("Text scale must be positive")
        item = cls(text)
        item.setFont(font)
        item.setDefaultTextColor(color)
        item.setPos(_position_from_record(record))
        item.setScale(scale)
        return item

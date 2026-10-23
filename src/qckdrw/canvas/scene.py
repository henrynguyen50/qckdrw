from __future__ import annotations

import json
import math
from typing import Any

from PySide6.QtCore import QObject, QPointF, QRectF, Qt, Signal
from PySide6.QtGui import QColor, QPainterPath, QPen, QUndoStack
from PySide6.QtWidgets import QGraphicsItem, QGraphicsScene

from qckdrw.canvas.commands import AddItemCommand, StrokeItem
from qckdrw.canvas.items import EditableTextItem, ResizablePixmapItem
CANVAS_WIDTH = 1200
CANVAS_HEIGHT = 800
_DOCUMENT_VERSION = 1


def _enum_value(value: object) -> int:
    raw_value = getattr(value, "value", value)
    return int(raw_value)  # type: ignore[arg-type]


def _path_record(path: QPainterPath) -> list[dict[str, float | int]]:
    return [
        {
            "type": _enum_value(path.elementAt(index).type),
            "x": path.elementAt(index).x,
            "y": path.elementAt(index).y,
        }
        for index in range(path.elementCount())
    ]


def _path_from_record(elements: object) -> QPainterPath:
    if not isinstance(elements, list) or not elements:
        raise ValueError("A stroke must contain path elements")

    parsed: list[tuple[int, float, float]] = []
    for element in elements:
        if not isinstance(element, dict):
            raise ValueError("Invalid path element")
        try:
            element_type = int(element["type"])
            x = float(element["x"])
            y = float(element["y"])
        except (KeyError, TypeError, ValueError) as error:
            raise ValueError("Invalid path element") from error
        if not math.isfinite(x) or not math.isfinite(y):
            raise ValueError("Path coordinates must be finite")
        parsed.append((element_type, x, y))

    move_type = _enum_value(QPainterPath.ElementType.MoveToElement)
    line_type = _enum_value(QPainterPath.ElementType.LineToElement)
    curve_type = _enum_value(QPainterPath.ElementType.CurveToElement)
    curve_data_type = _enum_value(QPainterPath.ElementType.CurveToDataElement)

    path = QPainterPath()
    index = 0
    while index < len(parsed):
        element_type, x, y = parsed[index]
        if element_type == move_type:
            path.moveTo(x, y)
            index += 1
        elif element_type == line_type:
            path.lineTo(x, y)
            index += 1
        elif element_type == curve_type:
            if index + 2 >= len(parsed):
                raise ValueError("Incomplete cubic path element")
            second_type, second_x, second_y = parsed[index + 1]
            third_type, third_x, third_y = parsed[index + 2]
            if second_type != curve_data_type or third_type != curve_data_type:
                raise ValueError("Invalid cubic path element")
            path.cubicTo(x, y, second_x, second_y, third_x, third_y)
            index += 3
        else:
            raise ValueError("Unsupported path element type")
    return path


def _pen_record(pen: QPen) -> dict[str, Any]:
    return {
        "color": int(pen.color().rgba()),
        "width": pen.widthF(),
        "style": _enum_value(pen.style()),
        "cap": _enum_value(pen.capStyle()),
        "join": _enum_value(pen.joinStyle()),
        "cosmetic": pen.isCosmetic(),
        "dash_offset": pen.dashOffset(),
        "dash_pattern": list(pen.dashPattern()),
        "miter_limit": pen.miterLimit(),
    }


def _pen_from_record(record: object) -> QPen:
    if not isinstance(record, dict):
        raise ValueError("Invalid stroke pen")
    try:
        color = QColor.fromRgba(int(record["color"]))
        width = float(record["width"])
        style = Qt.PenStyle(int(record["style"]))
        cap = Qt.PenCapStyle(int(record["cap"]))
        join = Qt.PenJoinStyle(int(record["join"]))
        cosmetic = bool(record["cosmetic"])
        dash_offset = float(record["dash_offset"])
        dash_pattern = [float(value) for value in record["dash_pattern"]]
        miter_limit = float(record["miter_limit"])
    except (KeyError, TypeError, ValueError) as error:
        raise ValueError("Invalid stroke pen") from error
    if (
        not color.isValid()
        or not math.isfinite(width)
        or width < 0.0
        or not math.isfinite(dash_offset)
        or not math.isfinite(miter_limit)
        or any(not math.isfinite(value) or value <= 0.0 for value in dash_pattern)
    ):
        raise ValueError("Invalid stroke pen")

    pen = QPen(color)
    pen.setWidthF(width)
    pen.setStyle(style)
    pen.setCapStyle(cap)
    pen.setJoinStyle(join)
    pen.setCosmetic(cosmetic)
    pen.setDashOffset(dash_offset)
    if dash_pattern:
        pen.setDashPattern(dash_pattern)
    pen.setMiterLimit(miter_limit)
    return pen


class CanvasScene(QGraphicsScene):
    """A fixed logical canvas containing serializable drawing items."""

    completion_requested = Signal()

    def __init__(self, parent: QObject | None = None) -> None:
        super().__init__(parent)
        self.setSceneRect(QRectF(0.0, 0.0, CANVAS_WIDTH, CANVAS_HEIGHT))
        self.setBackgroundBrush(Qt.GlobalColor.white)
        self.undo_stack = QUndoStack(self)
        self._next_stroke_sequence = 0

    def allocate_stroke_sequence(self) -> int:
        sequence = self._next_stroke_sequence
        self._next_stroke_sequence += 1
        return sequence

    def _connect_item(self, item: QGraphicsItem) -> None:
        if isinstance(item, EditableTextItem):
            item.done_requested.connect(self.completion_requested.emit)

    def add_pasted_item(self, item: QGraphicsItem) -> None:
        """Center and select a newly pasted item, then add it through undo."""
        if isinstance(item, ResizablePixmapItem):
            content = item.content_rect
            if content.width() > 0.0 and content.height() > 0.0:
                fit_scale = min(
                    1.0,
                    self.sceneRect().width() / content.width(),
                    self.sceneRect().height() / content.height(),
                )
                if fit_scale < 1.0:
                    item.set_content_rect(
                        QRectF(
                            0.0,
                            0.0,
                            content.width() * fit_scale,
                            content.height() * fit_scale,
                        )
                    )

        bounds = item.boundingRect()
        scaled_center = bounds.center() * item.scale()
        item.setPos(self.sceneRect().center() - scaled_center)
        self.clearSelection()
        self._connect_item(item)
        self.undo_stack.push(AddItemCommand(self, item, "Paste item"))
        item.setSelected(True)

    def finish_editing(self) -> None:
        for item in self.items():
            if isinstance(item, EditableTextItem):
                item.finish_editing()

    @staticmethod
    def _item_record(item: QGraphicsItem) -> dict[str, Any]:
        if isinstance(item, StrokeItem):
            record: dict[str, Any] = {
                "type": "stroke",
                "path": _path_record(item.path()),
                "pen": _pen_record(item.pen()),
            }
        elif isinstance(item, (ResizablePixmapItem, EditableTextItem)):
            record = item.to_record()
        else:
            raise TypeError(f"Unsupported canvas item: {type(item).__name__}")
        record["position"] = {"x": item.pos().x(), "y": item.pos().y()}
        record["scale"] = item.scale()
        return record

    def serialize_document(self) -> bytes:
        self.finish_editing()
        records = [
            self._item_record(item)
            for item in self.items(Qt.SortOrder.AscendingOrder)
        ]
        document = {"version": _DOCUMENT_VERSION, "items": records}
        return json.dumps(
            document,
            ensure_ascii=False,
            allow_nan=False,
            separators=(",", ":"),
        ).encode("utf-8")

    def restore_document(self, document: bytes) -> None:
        try:
            decoded = json.loads(document.decode("utf-8"))
        except (UnicodeDecodeError, json.JSONDecodeError) as error:
            raise ValueError("Invalid canvas document") from error
        if not isinstance(decoded, dict) or decoded.get("version") != _DOCUMENT_VERSION:
            raise ValueError("Unsupported canvas document")
        records = decoded.get("items")
        if not isinstance(records, list):
            raise ValueError("Invalid canvas item list")

        restored_items: list[QGraphicsItem] = []
        for sequence, record in enumerate(records):
            if not isinstance(record, dict):
                raise ValueError("Invalid canvas item")
            item_type = record.get("type")
            if item_type == "stroke":
                item = StrokeItem(
                    _path_from_record(record.get("path")),
                    _pen_from_record(record.get("pen")),
                    sequence,
                )
            elif item_type == "image":
                item = ResizablePixmapItem.from_record(record)
            elif item_type == "text":
                item = EditableTextItem.from_record(record)
            else:
                raise ValueError("Unsupported canvas item")

            position = record.get("position", {"x": 0.0, "y": 0.0})
            try:
                if isinstance(position, dict):
                    x = float(position["x"])
                    y = float(position["y"])
                elif isinstance(position, list) and len(position) == 2:
                    x, y = (float(value) for value in position)
                else:
                    raise ValueError
                scale = float(record.get("scale", 1.0))
            except (KeyError, TypeError, ValueError) as error:
                raise ValueError("Invalid canvas item geometry") from error
            if (
                not math.isfinite(x)
                or not math.isfinite(y)
                or not math.isfinite(scale)
                or scale <= 0.0
            ):
                raise ValueError("Invalid canvas item geometry")
            item.setPos(QPointF(x, y))
            item.setScale(scale)
            restored_items.append(item)

        self.release_resources()
        for item in restored_items:
            self.addItem(item)
            self._connect_item(item)
        self._next_stroke_sequence = 1 + max(
            (
                item.sequence
                for item in restored_items
                if isinstance(item, StrokeItem)
            ),
            default=-1,
        )

    def release_resources(self) -> None:
        # Commands may own items while undone, and the scene owns redone items.
        # Releasing commands first makes both ownership states deterministic.
        self.undo_stack.clear()
        self.clear()
        self._next_stroke_sequence = 0

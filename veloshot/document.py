"""Screenshot document; all coordinates are desktop logical pixels."""

from dataclasses import dataclass, field
from math import atan2, cos, sin, pi

from PySide6.QtCore import QPointF, QRect, QRectF, Qt
from PySide6.QtGui import QColor, QFont, QImage, QPainter, QPainterPath, QPen, QPolygonF


@dataclass
class Annotation:
    kind: str
    points: list[QPointF]
    color: str = "#ff003b"
    width: int = 3
    text: str = ""
    filled: bool = False

    def bounds(self):
        a, b = self.points[0], self.points[-1]
        return QRectF(a, b).normalized()


@dataclass
class Document:
    background: QImage
    selection: QRect = field(default_factory=QRect)
    annotations: list[Annotation] = field(default_factory=list)
    future: list[Annotation] = field(default_factory=list)

    def commit(self, annotation):
        self.annotations.append(annotation)
        self.future.clear()

    def undo(self):
        if self.annotations:
            self.future.append(self.annotations.pop())

    def redo(self):
        if self.future:
            self.annotations.append(self.future.pop())

    def render(self, preview=None):
        image = self.background.copy().convertToFormat(QImage.Format.Format_ARGB32)
        for annotation in [*self.annotations, *([preview] if preview else [])]:
            paint_annotation(image, annotation)
        return image

    def export(self):
        area = self.selection.intersected(self.background.rect())
        if area.width() < 1 or area.height() < 1:
            raise ValueError("Selecciona un área antes de exportar.")
        return self.render().copy(area)


def paint_annotation(image, shape):
    area = shape.bounds().toAlignedRect().intersected(image.rect())
    if shape.kind in ("pixelate", "invert"):
        if area.isEmpty():
            return
        tile = image.copy(area)
        if shape.kind == "invert":
            tile.invertPixels()
        else:
            block = max(6, shape.width * 3)
            tile = tile.scaled(max(1, area.width() // block), max(1, area.height() // block),
                               Qt.AspectRatioMode.IgnoreAspectRatio,
                               Qt.TransformationMode.SmoothTransformation)
            tile = tile.scaled(area.size(), Qt.AspectRatioMode.IgnoreAspectRatio,
                               Qt.TransformationMode.FastTransformation)
        painter = QPainter(image)
        painter.setCompositionMode(QPainter.CompositionMode.CompositionMode_Source)
        painter.drawImage(area.topLeft(), tile)
        painter.end()
        return

    painter = QPainter(image)
    painter.setRenderHint(QPainter.RenderHint.Antialiasing)
    color = QColor(shape.color)
    width = shape.width
    if shape.kind == "marker":
        color.setAlpha(85)
        width = max(12, width * 5)
    painter.setPen(QPen(color, width, Qt.PenStyle.SolidLine,
                        Qt.PenCapStyle.RoundCap, Qt.PenJoinStyle.RoundJoin))
    painter.setBrush(color if shape.filled or shape.kind == "filled_rectangle" else Qt.BrushStyle.NoBrush)
    start, end = shape.points[0], shape.points[-1]
    if shape.kind in ("pencil", "marker"):
        path = QPainterPath(start)
        for point in shape.points[1:]:
            path.lineTo(point)
        if len(shape.points) == 1:
            painter.drawPoint(start)
        else:
            painter.drawPath(path)
    elif shape.kind in ("line", "arrow"):
        painter.drawLine(start, end)
        if shape.kind == "arrow":
            angle = atan2(end.y() - start.y(), end.x() - start.x())
            size = max(13, width * 4)
            wing1 = end - QPointF(cos(angle - pi / 6) * size, sin(angle - pi / 6) * size)
            wing2 = end - QPointF(cos(angle + pi / 6) * size, sin(angle + pi / 6) * size)
            painter.setBrush(color)
            painter.drawPolygon(QPolygonF([end, wing1, wing2]))
    elif shape.kind in ("rectangle", "filled_rectangle"):
        painter.drawRect(shape.bounds())
    elif shape.kind == "circle":
        painter.drawEllipse(shape.bounds())
    elif shape.kind == "text":
        font = QFont("Sans Serif")
        font.setPixelSize(max(14, width * 5))
        painter.setFont(font)
        painter.drawText(QRectF(start, QPointF(image.width(), image.height())),
                         Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignTop, shape.text)
    elif shape.kind == "counter":
        radius = max(13, width * 4)
        painter.setBrush(color)
        painter.drawEllipse(start, radius, radius)
        painter.setPen(Qt.GlobalColor.white)
        font = QFont("Sans Serif")
        font.setPixelSize(int(radius * 1.2))
        font.setBold(True)
        painter.setFont(font)
        painter.drawText(QRectF(start.x() - radius, start.y() - radius,
                                radius * 2, radius * 2), Qt.AlignmentFlag.AlignCenter, shape.text)
    painter.end()

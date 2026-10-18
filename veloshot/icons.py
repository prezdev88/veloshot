"""Small native vector icons drawn by Qt, with no external asset dependency."""

from PySide6.QtCore import QPointF, QRectF, Qt
from PySide6.QtGui import QColor, QIcon, QPainter, QPen, QPixmap, QPolygonF, QFont


def icon(name, color="#f4edff"):
    pixmap = QPixmap(28, 28)
    pixmap.fill(Qt.GlobalColor.transparent)
    p = QPainter(pixmap)
    p.setRenderHint(QPainter.RenderHint.Antialiasing)
    p.setPen(QPen(QColor(color), 1.8, Qt.PenStyle.SolidLine,
                  Qt.PenCapStyle.RoundCap, Qt.PenJoinStyle.RoundJoin))
    if name in ("rectangle", "filled_rectangle", "select", "capture"):
        if name == "filled_rectangle":
            p.setBrush(QColor(color))
        if name == "select":
            p.setPen(QPen(QColor(color), 1.8, Qt.PenStyle.DashLine))
        p.drawRoundedRect(QRectF(5, 6, 18, 16), 1, 1)
    elif name == "circle":
        p.drawEllipse(QRectF(5, 5, 18, 18))
    elif name in ("line", "arrow", "pencil", "marker"):
        if name in ("pencil", "marker"):
            p.setPen(QPen(QColor(color), 4 if name == "marker" else 2.5))
        p.drawLine(6, 22, 22, 6)
        if name == "arrow":
            p.drawLine(12, 6, 22, 6)
            p.drawLine(22, 6, 22, 16)
        if name == "pencil":
            p.drawLine(4, 24, 8, 22)
    elif name == "save":
        p.drawRect(5, 4, 18, 20)
        p.drawRect(9, 4, 10, 7)
        p.drawRect(9, 16, 10, 8)
    elif name == "copy":
        p.drawRoundedRect(QRectF(9, 9, 14, 15), 1, 1)
        p.drawLine(5, 19, 5, 4)
        p.drawLine(5, 4, 19, 4)
    elif name == "close":
        p.drawLine(7, 7, 21, 21)
        p.drawLine(21, 7, 7, 21)
    elif name == "pixelate":
        for x in range(5, 23, 6):
            for y in range(5, 23, 6):
                p.fillRect(x, y, 4, 4, QColor(color))
    elif name == "pin":
        p.drawLine(8, 5, 20, 5)
        p.drawLine(10, 5, 10, 13)
        p.drawLine(18, 5, 18, 13)
        p.drawLine(6, 15, 22, 15)
        p.drawLine(14, 15, 14, 25)
    elif name == "panel":
        p.drawRect(4, 5, 20, 18)
        p.drawLine(17, 5, 17, 23)
    elif name == "invert":
        p.drawEllipse(QRectF(5, 5, 18, 18))
        p.setBrush(QColor(color))
        p.drawPie(QRectF(5, 5, 18, 18), 90 * 16, 180 * 16)
    else:
        glyphs = {"undo": "↶", "redo": "↷", "text": "T", "counter": "①",
                  "move": "✥", "settings": "⚙", "accept": "✓", "open": "+"}
        p.setFont(QFont("Sans Serif", 18))
        p.drawText(pixmap.rect(), Qt.AlignmentFlag.AlignCenter, glyphs.get(name, name[:1]))
    p.end()
    return QIcon(pixmap)

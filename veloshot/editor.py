"""Desktop overlay, selection, annotation toolbar and pinned captures."""

from datetime import datetime
from contextlib import contextmanager
from pathlib import Path

from PySide6.QtCore import QPoint, QPointF, QRect, QRectF, QSize, Qt, QTimer, Signal
from PySide6.QtGui import (QColor, QCursor, QFont, QImage, QKeySequence, QPainter,
                           QPainterPath, QPen, QPixmap, QShortcut, QTransform)
from PySide6.QtWidgets import (QApplication, QCheckBox, QColorDialog, QFileDialog,
                               QFrame, QGridLayout, QHBoxLayout, QInputDialog,
                               QLabel, QMenu, QMessageBox, QPushButton, QSlider,
                               QToolButton, QVBoxLayout, QWidget)

from .document import Annotation, Document
from .icons import icon

TOOLS = [
    ("select", "Selección rectangular", "S"), ("pencil", "Lápiz", "P"),
    ("line", "Línea", "L"), ("arrow", "Flecha", "A"),
    ("rectangle", "Rectángulo", "R"), ("circle", "Círculo", "C"),
    ("filled_rectangle", "Rectángulo relleno", "F"),
    ("marker", "Marcador", "M"), ("text", "Texto", "T"),
    ("pixelate", "Pixelar", "B"), ("invert", "Invertir", "I"),
    ("counter", "Contador", "N"), ("move", "Mover selección", "V"),
]
COLORS = ["#ff003b", "#ff8900", "#ffd600", "#1add80", "#00c2ff", "#a855f7", "#ffffff", "#15151c"]
STYLE = """QFrame#toolbar { background: transparent; border: 0; }
QFrame#sidePanel { background: #efefef; border: 1px solid #bbbbbb; }
QToolButton { color: white; background: #8000a2; border: 1px solid #3c004b; border-radius: 19px; padding: 3px; }
QToolButton:hover { background: #a12bc0; }
QToolButton:checked { background: #a12bc0; border: 2px solid #f2d8ff; }
QLabel, QCheckBox { color: #202027; }
QToolTip { background: #251833; color: white; border: 1px solid #9e74bd; padding: 5px; }
"""


@contextmanager
def visible_dialog(parent):
    """Let managed/native dialogs appear above an unmanaged capture overlay."""
    window = parent.window() if parent is not None else None
    restore = (window is not None and window.isVisible() and
               bool(window.windowFlags() & Qt.WindowType.X11BypassWindowManagerHint))
    if restore:
        window.hide()
    try:
        yield
    finally:
        if restore:
            window.show()
            window.raise_()
            window.activateWindow()
            window.setFocus()


def save_image(parent, image, settings, output=None):
    directory = Path(settings.get("directory", str(Path.home() / "Pictures")))
    name = datetime.now().strftime(settings.get("pattern", "%Y-%m-%d_%H-%M-%S")) + ".png"
    path = output
    if path and Path(path).is_dir():
        path = str(Path(path) / name)
    if not path:
        with visible_dialog(parent):
            path, _ = QFileDialog.getSaveFileName(parent, "Guardar captura", str(directory / name),
                                                 "PNG (*.png);;JPEG (*.jpg *.jpeg);;BMP (*.bmp)")
    if not path:
        return None
    if not Path(path).suffix:
        path += ".png"
    try:
        if not image.save(path):
            raise OSError("No se pudo escribir la imagen en esa ruta.")
    except OSError as error:
        with visible_dialog(parent):
            QMessageBox.warning(parent, "No se pudo guardar", str(error))
        return None
    settings.set("directory", str(Path(path).absolute().parent))
    if settings.get("copy_save", False):
        QApplication.clipboard().setImage(image)
    return path


class PinnedImage(QLabel):
    def __init__(self, image, settings):
        super().__init__(None, Qt.WindowType.FramelessWindowHint | Qt.WindowType.WindowStaysOnTopHint)
        self.setAttribute(Qt.WidgetAttribute.WA_DeleteOnClose)
        self.image = image
        self.settings = settings
        self.drag = QPoint()
        self.setWindowTitle("VeloShot · Captura fijada")
        self.refresh()
        self.setToolTip("Arrastra para mover · Clic derecho para opciones · Esc para cerrar")
        self.show()

    def refresh(self):
        self.setPixmap(QPixmap.fromImage(self.image))
        self.resize(self.image.size())

    def mousePressEvent(self, event):
        if event.button() == Qt.MouseButton.LeftButton:
            self.drag = event.globalPosition().toPoint() - self.pos()

    def mouseMoveEvent(self, event):
        if event.buttons() & Qt.MouseButton.LeftButton:
            self.move(event.globalPosition().toPoint() - self.drag)

    def keyPressEvent(self, event):
        if event.key() == Qt.Key.Key_Escape:
            self.close()
        elif event.matches(QKeySequence.StandardKey.Copy):
            QApplication.clipboard().setImage(self.image)
        elif event.matches(QKeySequence.StandardKey.Save):
            save_image(self, self.image, self.settings)

    def wheelEvent(self, event):
        self.setWindowOpacity(max(0.15, min(1, self.windowOpacity() + event.angleDelta().y() / 1200)))

    def contextMenuEvent(self, event):
        menu = QMenu(self)
        menu.addAction("Copiar", lambda: QApplication.clipboard().setImage(self.image))
        menu.addAction("Guardar…", lambda: save_image(self, self.image, self.settings))
        menu.addAction("Girar a la derecha", lambda: self.rotate(90))
        menu.addAction("Girar a la izquierda", lambda: self.rotate(-90))
        menu.addSeparator()
        menu.addAction("Cerrar", self.close)
        menu.exec(event.globalPos())

    def rotate(self, angle):
        self.image = self.image.transformed(QTransform().rotate(angle))
        self.refresh()


class CaptureEditor(QWidget):
    completed = Signal(object, str)

    def __init__(self, image, geometry, settings, output=None):
        # A capture spans the virtual desktop, including on tiling window managers.
        # A normal frameless window can still be resized to one tile by i3.
        super().__init__(None, Qt.WindowType.FramelessWindowHint |
                         Qt.WindowType.WindowStaysOnTopHint |
                         Qt.WindowType.X11BypassWindowManagerHint)
        self.setWindowTitle("VeloShot · Seleccionar captura")
        self.setAttribute(Qt.WidgetAttribute.WA_DeleteOnClose)
        self.setGeometry(geometry)
        self.setMouseTracking(True)
        self.setFocusPolicy(Qt.FocusPolicy.StrongFocus)
        self.setCursor(Qt.CursorShape.CrossCursor)
        self.setStyleSheet(STYLE)
        self.document = Document(image)
        self.settings = settings
        self.output = output
        self.tool = "select"
        self.color = settings.get("color", "#ff003b")
        self.width_value = settings.get("width", 3)
        self.filled = False
        self.preview = None
        self.drag_mode = None
        self.anchor = QPoint()
        self.original_selection = QRect()
        self.render_cache = image.copy()
        self.accept_action = self.copy
        self.accept_on_select = False
        self.build_toolbar()
        self.build_panel()
        self.build_shortcuts()

    def showEvent(self, event):
        super().showEvent(event)
        # i3 may focus another managed window when a modal dialog closes.
        # Claim input only once the unmanaged overlay is mapped again.
        QTimer.singleShot(0, self.focus_keyboard)
        QTimer.singleShot(100, self.focus_keyboard)

    def focus_keyboard(self):
        if self.isVisible() and QApplication.platformName() == "xcb":
            QApplication.setActiveWindow(self)
            self.setFocus()
            self.grabKeyboard()

    def hideEvent(self, event):
        if QWidget.keyboardGrabber() is self:
            self.releaseKeyboard()
        super().hideEvent(event)

    def button(self, name, label, callback, checkable=False):
        button = QToolButton()
        button.setObjectName(name)
        button.setIcon(icon(name))
        button.setIconSize(QSize(25, 25))
        button.setFixedSize(38, 38)
        button.setToolTip(label)
        button.setCheckable(checkable)
        button.clicked.connect(callback)
        return button

    def build_toolbar(self):
        self.toolbar = QFrame(self)
        self.toolbar.setObjectName("toolbar")
        grid = QGridLayout(self.toolbar)
        grid.setContentsMargins(5, 5, 5, 5)
        grid.setHorizontalSpacing(7)
        grid.setVerticalSpacing(5)
        self.tool_buttons = {}
        entries = []
        order = ["pencil", "line", "arrow", "rectangle", "filled_rectangle", "circle", "marker",
                 "text", "counter", "pixelate", "invert", "move", "select"]
        for name, label, key in sorted(TOOLS, key=lambda item: order.index(item[0])):
            button = self.button(name, f"{label} ({key})", lambda checked=False, n=name: self.set_tool(n), True)
            self.tool_buttons[name] = button
            entries.append(button)
        for name, label, callback in [
            ("undo", "Deshacer (Ctrl+Z)", self.undo), ("redo", "Rehacer (Ctrl+Mayús+Z)", self.redo),
            ("copy", "Copiar (Ctrl+C / Enter)", self.copy),
            ("save", "Guardar (Ctrl+S)", self.save), ("close", "Cancelar (Esc)", self.close),
            ("pin", "Fijar en el escritorio", self.pin),
        ]:
            entries.append(self.button(name, label, callback))
        self.accept_button = self.button("accept", "Aceptar captura (Enter)", lambda: self.accept_action())
        entries.append(self.accept_button)
        # Two rows keep all actions usable on smaller screens.
        columns = min(len(entries), max(5, (self.width() - 30) // 45))
        for i, button in enumerate(entries):
            grid.addWidget(button, i // columns, i % columns)
        self.toolbar.adjustSize()
        self.toolbar.hide()
        self.accept_button.hide()
        self.tool_buttons["select"].setChecked(True)
        self.panel_button = QPushButton("Ajustes", self)
        self.panel_button.setStyleSheet("background: #8000a2; color: white; border: 0; padding: 6px;")
        self.panel_button.setToolTip("Abrir panel lateral (Espacio / Tab)")
        self.panel_button.clicked.connect(self.toggle_panel)
        self.panel_button.move(0, self.height() // 2 - 18)

    def build_panel(self):
        self.panel = QFrame(self)
        self.panel.setObjectName("sidePanel")
        self.panel.setFixedWidth(232)
        layout = QVBoxLayout(self.panel)
        layout.setContentsMargins(10, 10, 10, 10)
        layout.setSpacing(8)
        title = QLabel("AJUSTES DE HERRAMIENTA")
        title.setStyleSheet("font-size: 11px; font-weight: bold; padding: 8px 0;")
        layout.addWidget(title)
        colors = QHBoxLayout()
        for color in COLORS:
            button = QPushButton()
            button.setFixedSize(21, 24)
            button.setStyleSheet(f"background: {color}; border: 1px solid #baa1cc; border-radius: 3px;")
            button.clicked.connect(lambda checked=False, c=color: self.set_color(c))
            colors.addWidget(button)
        layout.addLayout(colors)
        choose = QPushButton("Más colores…")
        choose.clicked.connect(self.choose_color)
        layout.addWidget(choose)
        self.size_label = QLabel()
        layout.addWidget(self.size_label)
        self.slider = QSlider(Qt.Orientation.Horizontal)
        self.slider.setRange(1, 50)
        self.slider.setValue(self.width_value)
        self.slider.valueChanged.connect(self.set_width)
        layout.addWidget(self.slider)
        fill = QCheckBox("Rellenar figuras")
        fill.toggled.connect(lambda value: setattr(self, "filled", value))
        layout.addWidget(fill)
        self.selection_label = QLabel("Sin selección")
        layout.addWidget(self.selection_label)
        hint = QLabel("Rueda: grosor\nClic derecho: color\nCtrl+Z: deshacer\nV: mover selección")
        hint.setStyleSheet("color: #615766; padding: 8px 0;")
        layout.addWidget(hint)
        layout.addStretch(1)
        close = QPushButton("Cerrar panel")
        close.clicked.connect(self.toggle_panel)
        layout.addWidget(close)
        self.panel.adjustSize()
        self.panel.setFixedHeight(self.height())
        self.panel.move(0, 0)
        self.panel.hide()
        self.set_width(self.width_value)

    def build_shortcuts(self):
        self.shortcuts = []
        for key, callback in [("Ctrl+C", self.copy), ("Ctrl+S", self.save),
                               ("Ctrl+Z", self.undo), ("Ctrl+Shift+Z", self.redo),
                               ("Ctrl+Y", self.redo), ("Ctrl+A", self.select_all),
                               ("Tab", self.toggle_panel), ("Space", self.toggle_panel), ("Return", lambda: self.accept_action()),
                               ("Enter", lambda: self.accept_action()), ("Escape", self.close)]:
            shortcut = QShortcut(QKeySequence(key), self)
            shortcut.activated.connect(callback)
            self.shortcuts.append(shortcut)
        for name, _, key in TOOLS:
            shortcut = QShortcut(QKeySequence(key), self)
            shortcut.activated.connect(lambda n=name: self.set_tool(n))
            self.shortcuts.append(shortcut)

    def set_tool(self, name):
        self.tool = name
        for key, button in self.tool_buttons.items():
            button.setChecked(key == name)
        self.setCursor(Qt.CursorShape.SizeAllCursor if name == "move" else Qt.CursorShape.CrossCursor)
        self.setFocus()

    def set_color(self, color):
        self.color = color
        self.settings.set("color", color)
        self.update()

    def choose_color(self):
        with visible_dialog(self):
            color = QColorDialog.getColor(QColor(self.color), self, "Color de la herramienta")
        if color.isValid():
            self.set_color(color.name())
        self.setFocus()

    def set_width(self, width):
        self.width_value = width
        self.size_label.setText(f"Grosor: {width} px")
        self.settings.set("width", width)
        if self.slider.value() != width:
            self.slider.setValue(width)

    def toggle_panel(self):
        self.panel.setVisible(not self.panel.isVisible())
        if self.panel.isVisible():
            self.panel.raise_()

    def select_all(self):
        self.document.selection = self.document.background.rect()
        self.selection_changed()

    def selection_changed(self):
        area = self.document.selection
        self.selection_label.setText(f"{area.width()} × {area.height()} px · {area.x()}, {area.y()}")
        if area.width() >= 2 and area.height() >= 2:
            self.toolbar.show()
            x = max(8, min(area.center().x() - self.toolbar.width() // 2,
                           self.width() - self.toolbar.width() - 8))
            y = area.bottom() + 8
            if y + self.toolbar.height() > self.height() - 8:
                y = max(8, area.top() - self.toolbar.height() - 12)
            self.toolbar.move(x, y)
            self.toolbar.raise_()
        else:
            self.toolbar.hide()
        self.update()

    def paintEvent(self, event):
        painter = QPainter(self)
        painter.drawImage(0, 0, self.document.render(self.preview) if self.preview else self.render_cache)
        area = self.document.selection
        painter.setPen(Qt.PenStyle.NoPen)
        path = QPainterPath()
        path.addRect(QRectF(self.rect()))
        if not area.isEmpty():
            path.addRect(QRectF(area))
        painter.fillPath(path, QColor(0, 0, 0, 195))
        if not area.isEmpty():
            painter.setPen(QPen(QColor("#8000a2"), 1))
            painter.setBrush(Qt.BrushStyle.NoBrush)
            painter.drawRect(QRectF(area).adjusted(0, 0, -1, -1))
            painter.setBrush(QColor("#8000a2"))
            for point in self.handles().values():
                painter.drawEllipse(QPointF(point), 5, 5)
            label = f"{area.width()}x{area.height()}{area.x():+d}{area.y():+d}"
            rect = QRect(max(area.left(), area.right() - 160), max(area.top(), area.bottom() - 28), 160, 23)
            painter.fillRect(rect, QColor("#8000a2"))
            painter.setPen(Qt.GlobalColor.white)
            painter.drawText(rect, Qt.AlignmentFlag.AlignCenter, label)
        elif self.settings.get("help", True):
            box = QRect(self.width() // 2 - 195, self.height() // 2 - 85, 390, 170)
            painter.setBrush(QColor(112, 24, 150, 230))
            painter.setPen(QPen(Qt.GlobalColor.white, 1))
            painter.drawRoundedRect(box, 5, 5)
            painter.setPen(Qt.GlobalColor.white)
            painter.setFont(QFont("Sans Serif", 12, QFont.Weight.DemiBold))
            painter.drawText(box.adjusted(10, 10, -10, -125), Qt.AlignmentFlag.AlignCenter,
                             "Arrastra para seleccionar un área")
            painter.setFont(QFont("Sans Serif", 11))
            painter.drawText(box.adjusted(10, 42, -10, -8), Qt.AlignmentFlag.AlignCenter,
                             "Ctrl+S    Guardar captura\nCtrl+C    Copiar al portapapeles\n"
                             "Rueda    Cambiar grosor\nClic derecho    Cambiar color\n"
                             "Espacio    Abrir panel lateral\nEsc    Salir")
        painter.end()

    def handles(self):
        a = self.document.selection
        return {"tl": a.topLeft(), "tr": a.topRight(), "bl": a.bottomLeft(),
                "br": a.bottomRight(), "t": QPoint(a.center().x(), a.top()),
                "b": QPoint(a.center().x(), a.bottom()),
                "l": QPoint(a.left(), a.center().y()), "r": QPoint(a.right(), a.center().y())}

    def bounded(self, point):
        return QPoint(max(0, min(self.width() - 1, point.x())),
                      max(0, min(self.height() - 1, point.y())))

    def mousePressEvent(self, event):
        if event.button() == Qt.MouseButton.RightButton:
            self.choose_color()
            return
        if event.button() != Qt.MouseButton.LeftButton:
            return
        point = self.bounded(event.position().toPoint())
        self.anchor = point
        self.original_selection = QRect(self.document.selection)
        self.toolbar.hide()
        for name, handle in self.handles().items():
            if not self.document.selection.isEmpty() and (point - handle).manhattanLength() <= 8:
                self.drag_mode = "resize:" + name
                return
        if self.document.selection.isEmpty() or self.tool == "select":
            if self.document.selection.contains(point):
                self.drag_mode = "move"
            else:
                self.drag_mode = "selection"
                self.document.selection = QRect(point, point)
        elif self.tool == "move":
            self.drag_mode = "move"
        elif self.document.selection.contains(point):
            self.drag_mode = "draw"
            if self.tool == "text":
                with visible_dialog(self):
                    text, ok = QInputDialog.getMultiLineText(self, "Texto", "Texto de la anotación:")
                if ok and text:
                    self.document.commit(Annotation("text", [QPointF(point)], self.color,
                                                     self.width_value, text))
                    self.refresh()
                self.drag_mode = None
                self.selection_changed()
            elif self.tool == "counter":
                count = 1 + sum(a.kind == "counter" for a in self.document.annotations)
                self.document.commit(Annotation("counter", [QPointF(point)], self.color,
                                                 self.width_value, str(count)))
                self.refresh()
                self.drag_mode = None
                self.selection_changed()
            else:
                self.preview = Annotation(self.tool, [QPointF(point), QPointF(point)],
                                          self.color, self.width_value, filled=self.filled)
        self.update()

    def mouseMoveEvent(self, event):
        if not self.drag_mode:
            return
        point = self.bounded(event.position().toPoint())
        if self.drag_mode == "selection":
            self.document.selection = QRect(
                QPoint(min(self.anchor.x(), point.x()), min(self.anchor.y(), point.y())),
                QPoint(max(self.anchor.x(), point.x()), max(self.anchor.y(), point.y())))
        elif self.drag_mode == "move":
            area = QRect(self.original_selection)
            destination = area.topLeft() + point - self.anchor
            area.moveTo(max(0, min(self.width() - area.width(), destination.x())),
                        max(0, min(self.height() - area.height(), destination.y())))
            self.document.selection = area
        elif self.drag_mode.startswith("resize:"):
            handle = self.drag_mode.split(":")[1]
            area = QRect(self.original_selection)
            if "l" in handle:
                area.setLeft(point.x())
            if "r" in handle:
                area.setRight(point.x())
            if "t" in handle:
                area.setTop(point.y())
            if "b" in handle:
                area.setBottom(point.y())
            left, right = sorted((area.left(), area.right()))
            top, bottom = sorted((area.top(), area.bottom()))
            self.document.selection = QRect(QPoint(left, top), QPoint(right, bottom)).intersected(self.rect())
        elif self.preview:
            # Annotations stay inside the selected region.
            area = self.document.selection
            point = QPoint(max(area.left(), min(area.right(), point.x())),
                           max(area.top(), min(area.bottom(), point.y())))
            if event.modifiers() & Qt.KeyboardModifier.ShiftModifier:
                delta = point - self.anchor
                if self.tool in ("rectangle", "filled_rectangle", "circle"):
                    size = min(abs(delta.x()), abs(delta.y()))
                    point = self.anchor + QPoint(size if delta.x() >= 0 else -size,
                                                  size if delta.y() >= 0 else -size)
                elif self.tool in ("line", "arrow"):
                    point = QPoint(point.x(), self.anchor.y()) if abs(delta.x()) > abs(delta.y()) else QPoint(self.anchor.x(), point.y())
            if self.tool in ("pencil", "marker"):
                self.preview.points.append(QPointF(point))
            else:
                self.preview.points[-1] = QPointF(point)
        self.update()

    def mouseReleaseEvent(self, event):
        if event.button() != Qt.MouseButton.LeftButton:
            return
        if self.preview:
            self.document.commit(self.preview)
            self.preview = None
            self.refresh()
        selecting = self.drag_mode == "selection"
        self.drag_mode = None
        self.selection_changed()
        if selecting and self.accept_on_select and not self.document.selection.isEmpty():
            self.accept_action()

    def wheelEvent(self, event):
        self.set_width(max(1, min(50, self.width_value + (1 if event.angleDelta().y() > 0 else -1))))

    def keyPressEvent(self, event):
        offsets = {Qt.Key.Key_Left: (-1, 0), Qt.Key.Key_Right: (1, 0),
                   Qt.Key.Key_Up: (0, -1), Qt.Key.Key_Down: (0, 1)}
        if event.key() in offsets and not self.document.selection.isEmpty():
            dx, dy = offsets[event.key()]
            area = QRect(self.document.selection)
            if event.modifiers() & Qt.KeyboardModifier.ShiftModifier:
                area.setWidth(max(2, area.width() + dx))
                area.setHeight(max(2, area.height() + dy))
            else:
                area.translate(dx, dy)
                area.moveLeft(max(0, min(self.width() - area.width(), area.left())))
                area.moveTop(max(0, min(self.height() - area.height(), area.top())))
            self.document.selection = area.intersected(self.rect())
            self.selection_changed()
        else:
            super().keyPressEvent(event)

    def refresh(self):
        self.render_cache = self.document.render()
        self.update()

    def undo(self):
        self.document.undo()
        self.refresh()

    def redo(self):
        self.document.redo()
        self.refresh()

    def result(self):
        if self.document.selection.isEmpty():
            return None
        return self.document.export()

    def copy(self):
        image = self.result()
        if image is not None:
            QApplication.clipboard().setImage(image)
            self.completed.emit(image, "copy")
            self.close()

    def save(self):
        image = self.result()
        if image is not None and save_image(self, image, self.settings, self.output):
            self.completed.emit(image, "save")
            self.close()

    def pin(self):
        image = self.result()
        if image is not None:
            self.completed.emit(image, "pin")
            self.close()

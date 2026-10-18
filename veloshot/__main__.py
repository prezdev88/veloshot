"""VeloShot entry point, capture acquisition, launcher, and tray lifetime."""

import argparse
from datetime import datetime
import os
import re
from pathlib import Path
import signal
import sys

from PySide6.QtCore import QPoint, QRect, Qt, QTimer
from PySide6.QtGui import QColor, QCursor, QImage, QPainter
from PySide6.QtWidgets import (QApplication, QComboBox, QFileDialog, QHBoxLayout, QInputDialog, QLabel,
                               QMenu, QMessageBox, QPushButton, QSpinBox,
                               QSystemTrayIcon, QVBoxLayout, QWidget)

from . import __version__
from .editor import CaptureEditor, PinnedImage, save_image
from .icons import icon
from .settings import Settings, SettingsDialog


ASK_MONITOR = object()


def capture_targets(app):
    targets = [("Todas las pantallas", None)]
    for number, screen in enumerate(app.screens(), start=1):
        size = screen.geometry().size()
        primary = " · principal" if screen is app.primaryScreen() else ""
        label = f"Monitor {number} · {screen.name()} · {size.width()} × {size.height()}{primary}"
        targets.append((label, screen))
    return targets


def acquire_screen(app, screen_index=None):
    """Combine QScreen grabs in logical desktop coordinates, including negative origins."""
    screens = app.screens()
    if screen_index is not None:
        if not 0 <= screen_index < len(screens):
            raise ValueError(f"Monitor {screen_index} inexistente; disponibles: 0–{len(screens) - 1}.")
        screens = [screens[screen_index]]
    geometry = QRect()
    for screen in screens:
        geometry = geometry.united(screen.geometry())
    image = QImage(geometry.size(), QImage.Format.Format_ARGB32)
    image.fill(QColor("#101018"))
    painter = QPainter(image)
    try:
        for screen in screens:
            frame = screen.grabWindow(0).toImage()
            if frame.isNull():
                raise RuntimeError("El escritorio no permite capturar la pantalla. Usa una sesión X11.")
            destination = QRect(screen.geometry())
            destination.translate(-geometry.topLeft())
            painter.drawImage(destination, frame)
    finally:
        painter.end()
    return image, geometry


class Launcher(QWidget):
    def __init__(self, controller):
        super().__init__()
        self.controller = controller
        self.setWindowTitle("VeloShot")
        self.setWindowIcon(icon("capture", "#b87bf1"))
        self.setFixedSize(470, 330)
        self.setStyleSheet("""
            QWidget { background: #201a29; color: #f6efff; font-family: Sans Serif; }
            QPushButton { background: #4f237b; border: 1px solid #8055a1; border-radius: 7px; padding: 11px; }
            QPushButton:hover { background: #71409c; }
            QSpinBox { background: #342640; border: 1px solid #8055a1; padding: 5px; }
        """)
        layout = QVBoxLayout(self)
        layout.setContentsMargins(28, 24, 28, 24)
        title = QLabel("VeloShot")
        title.setStyleSheet("font-size: 29px; font-weight: bold;")
        layout.addWidget(title)
        label = QLabel("Captura, anota y comparte desde el portapapeles.")
        label.setStyleSheet("color: #c0accf; margin-bottom: 12px;")
        layout.addWidget(label)
        self.monitor_row = QWidget()
        monitor_layout = QHBoxLayout(self.monitor_row)
        monitor_layout.setContentsMargins(0, 0, 0, 0)
        monitor_layout.addWidget(QLabel("Pantalla"))
        self.monitor = QComboBox()
        self.monitor.setObjectName("captureMonitor")
        self.monitor.setStyleSheet("QComboBox { background: #342640; border: 1px solid #8055a1; padding: 6px; }")
        monitor_layout.addWidget(self.monitor, 1)
        layout.addWidget(self.monitor_row)
        self.refresh_monitors()
        controller.app.screenAdded.connect(self.refresh_monitors)
        controller.app.screenRemoved.connect(self.refresh_monitors)
        row = QHBoxLayout()
        row.addWidget(QLabel("Retardo"))
        self.delay = QSpinBox()
        self.delay.setRange(0, 60)
        self.delay.setSuffix(" s")
        self.delay.setValue(controller.settings.get("delay", 0))
        row.addWidget(self.delay)
        row.addStretch()
        layout.addLayout(row)
        button = QPushButton("Seleccionar un área de la pantalla")
        button.setIcon(icon("capture"))
        button.clicked.connect(self.capture)
        layout.addWidget(button)
        row = QHBoxLayout()
        full = QPushButton("Pantalla completa")
        full.clicked.connect(lambda: self.capture(full=True))
        row.addWidget(full)
        open_image = QPushButton("Abrir imagen…")
        open_image.clicked.connect(controller.open_image)
        row.addWidget(open_image)
        layout.addLayout(row)
        config = QPushButton("Configuración")
        config.clicked.connect(controller.configure)
        layout.addWidget(config)

    def capture(self, checked=False, full=False):
        screen = self.monitor.currentData()
        self.hide()
        self.controller.capture(delay_ms=max(180, self.delay.value() * 1000), select_all=full,
                                screen=screen)

    def refresh_monitors(self, *_):
        selected = self.monitor.currentData()
        self.monitor.clear()
        for label, screen in capture_targets(self.controller.app):
            self.monitor.addItem(label, screen)
            if selected is not None and screen is selected:
                self.monitor.setCurrentIndex(self.monitor.count() - 1)
        multiple = len(self.controller.app.screens()) > 1
        self.monitor_row.setVisible(multiple)
        self.setFixedHeight(390 if multiple else 330)

    def showEvent(self, event):
        self.refresh_monitors()
        super().showEvent(event)


class Controller:
    def __init__(self, app, args):
        self.app = app
        self.args = args
        self.settings = Settings()
        self.windows = []
        self.launcher = None
        self.tray = None
        self.clipboard_owner = False
        app.setQuitOnLastWindowClosed(False)
        app.lastWindowClosed.connect(lambda: QTimer.singleShot(0, self.maybe_quit))

    def retain(self, window):
        self.windows.append(window)
        window.destroyed.connect(lambda: self.release(window))
        return window

    def release(self, window):
        if window in self.windows:
            self.windows.remove(window)
        QTimer.singleShot(0, self.maybe_quit)

    def maybe_quit(self):
        if any(window.isVisible() for window in self.windows):
            return
        if self.tray is not None or self.clipboard_owner:
            return
        self.app.quit()

    def start(self):
        mode = self.args.mode
        if mode == "config":
            self.configure()
        elif mode in ("full", "screen"):
            QTimer.singleShot(self.args.delay, self.capture_direct)
        elif mode == "gui":
            self.capture(delay_ms=self.args.delay)
        elif mode == "edit":
            self.open_image(self.args.image)
        elif mode in ("tray", "no-gui"):
            self.setup_tray()
        else:
            self.setup_tray()
            self.show_launcher()

    def setup_tray(self):
        self.tray = QSystemTrayIcon(icon("capture", "#b87bf1"), self.app)
        self.tray.setToolTip("VeloShot · Capturar pantalla")
        menu = QMenu()
        menu.addAction("Tomar captura", lambda: self.capture(delay_ms=self.settings.get("delay", 0) * 1000))
        menu.addAction("Abrir lanzador", self.show_launcher)
        menu.addAction("Abrir imagen…", self.open_image)
        menu.addAction("Configuración", self.configure)
        menu.addSeparator()
        menu.addAction("Salir", self.app.quit)
        self.tray.setContextMenu(menu)
        self.tray.activated.connect(lambda reason: self.capture() if reason == QSystemTrayIcon.ActivationReason.Trigger else None)
        self.tray.show()

    def show_launcher(self):
        if self.launcher is None:
            self.launcher = self.retain(Launcher(self))
        self.launcher.show()
        self.launcher.raise_()
        self.launcher.activateWindow()

    def configure(self):
        dialog = self.retain(SettingsDialog(self.settings))
        dialog.setAttribute(Qt.WidgetAttribute.WA_DeleteOnClose)
        dialog.show()

    def capture(self, delay_ms=0, select_all=False, screen=ASK_MONITOR):
        if screen is ASK_MONITOR:
            screen = None
            if (len(self.app.screens()) > 1 and self.args.mode != "screen"
                    and not self.args.region and not self.args.last_region):
                targets = capture_targets(self.app)
                parent = self.launcher if self.launcher and self.launcher.isVisible() else None
                label, accepted = QInputDialog.getItem(parent, "Elegir pantalla", "Capturar:",
                                                       [label for label, _ in targets], 0, False)
                if not accepted:
                    self.maybe_quit()
                    return
                screen = next(target for name, target in targets if name == label)
        if self.launcher:
            self.launcher.hide()
        QTimer.singleShot(max(100, delay_ms), lambda: self.show_capture(select_all, screen))

    def show_capture(self, select_all=False, screen=None):
        try:
            index = self.monitor_index() if self.args.mode == "screen" else None
            if screen is not None:
                screens = self.app.screens()
                if screen not in screens:
                    raise ValueError("La pantalla seleccionada se desconectó. Vuelve a elegir una pantalla.")
                index = screens.index(screen)
            image, geometry = acquire_screen(self.app, index)
            target = self.app.screens()[index] if index is not None else None
            editor = self.create_editor(image, geometry, screen=target)
            region = self.args.region
            if self.args.last_region:
                region = self.settings.get("last_region", "")
            if region:
                editor.document.selection = parse_region(region).translated(-geometry.topLeft()).intersected(image.rect())
                if editor.document.selection.isEmpty():
                    editor.close()
                    raise ValueError("La región está fuera de la pantalla.")
                editor.selection_changed()
            elif select_all:
                editor.select_all()
        except (RuntimeError, ValueError) as error:
            self.fail(str(error))

    def create_editor(self, image, geometry, screen=None):
        editor = self.retain(CaptureEditor(image, geometry, self.settings, self.args.path))
        if screen is not None:
            editor.setScreen(screen)
            editor.setGeometry(geometry)
        editor.completed.connect(lambda image, action: self.editor_completed(editor, image, action))
        if self.args.raw or self.args.clipboard or self.args.pin or self.args.path or self.args.print_geometry or self.args.accept_on_select:
            editor.accept_action = lambda: self.accept_selection(editor)
            editor.accept_on_select = self.args.accept_on_select
            editor.accept_button.show()
        editor.show()
        editor.raise_()
        editor.activateWindow()
        editor.setFocus()
        return editor

    def editor_completed(self, editor, image, action):
        area = editor.document.selection.translated(editor.geometry().topLeft())
        self.settings.set("last_region", f"{area.width()}x{area.height()}{area.x():+d}{area.y():+d}")
        self.complete(image, action)

    def accept_selection(self, editor):
        image = editor.result()
        if image is None:
            return
        if self.args.path and not save_image(editor, image, self.settings, self.args.path):
            return
        if self.args.raw:
            write_png(image)
        elif self.args.print_geometry:
            area = editor.document.selection.translated(editor.geometry().topLeft())
            print(f"{area.width()}x{area.height()}{area.x():+d}{area.y():+d}", flush=True)
        action = "save" if self.args.path else "accept"
        if self.args.clipboard or not (self.args.raw or self.args.path or self.args.pin or self.args.print_geometry):
            self.app.clipboard().setImage(image)
            action = "copy"
        if self.args.pin:
            self.complete(image, "pin")
        editor.completed.emit(image, action)
        editor.close()

    def monitor_index(self):
        if self.args.number is not None:
            return self.args.number
        current = self.app.screenAt(QCursor.pos()) or self.app.primaryScreen()
        return self.app.screens().index(current)

    def open_image(self, path=None):
        if not isinstance(path, str):
            path, _ = QFileDialog.getOpenFileName(self.launcher, "Abrir imagen", "",
                                                 "Imágenes (*.png *.jpg *.jpeg *.bmp *.webp)")
        if not path:
            return
        image = QImage(path)
        if image.isNull():
            self.fail(f"No se pudo abrir la imagen: {path}")
            return
        screen = self.app.primaryScreen().geometry()
        if image.width() > screen.width() or image.height() > screen.height():
            image = image.scaled(screen.size(), Qt.AspectRatioMode.KeepAspectRatio,
                                  Qt.TransformationMode.SmoothTransformation)
        geometry = QRect(screen.topLeft(), image.size())
        if self.launcher:
            self.launcher.hide()
        editor = self.create_editor(image, geometry)
        editor.select_all()

    def complete(self, image, action):
        if action == "pin":
            pin = self.retain(PinnedImage(image, self.settings))
            pin.move(self.app.primaryScreen().availableGeometry().center() - pin.rect().center())
        elif action == "copy" or (action == "save" and self.settings.get("copy_save", False)):
            # X11 selection ownership must survive the editor closing.
            self.clipboard_owner = True
            self.setup_tray() if self.tray is None else None
            if self.tray:
                self.tray.showMessage("VeloShot", "Captura copiada al portapapeles.")
            self.app.clipboard().dataChanged.connect(self.clipboard_changed)

    def clipboard_changed(self):
        if not self.app.clipboard().ownsClipboard():
            self.clipboard_owner = False
            self.maybe_quit()

    def capture_direct(self):
        try:
            if self.args.edit:
                self.show_capture(select_all=True)
                return
            index = self.monitor_index() if self.args.mode == "screen" else None
            image, geometry = acquire_screen(self.app, index)
            if self.args.region:
                area = parse_region(self.args.region).translated(-geometry.topLeft()).intersected(image.rect())
                if area.isEmpty():
                    raise ValueError("La región está fuera de la pantalla.")
                image = image.copy(area)
            if self.args.raw:
                write_png(image)
            if self.args.clipboard:
                self.app.clipboard().setImage(image)
                self.complete(image, "copy")
            if self.args.pin:
                self.complete(image, "pin")
            if self.args.path or not (self.args.raw or self.args.clipboard or self.args.pin):
                directory = Path(self.settings.get("directory", str(Path.home() / "Pictures")))
                if self.args.path:
                    path = Path(self.args.path)
                else:
                    directory.mkdir(parents=True, exist_ok=True)
                    path = directory
                if path.is_dir():
                    name = datetime.now().strftime(self.settings.get("pattern", "%Y-%m-%d_%H-%M-%S-%f"))
                    path = path / (name + ".png")
                if not path.suffix:
                    path = path.with_suffix(".png")
                if not image.save(str(path)):
                    raise RuntimeError(f"No se pudo guardar la captura en {path}")
                if not self.args.raw:
                    print(path)
            self.maybe_quit()
        except (RuntimeError, ValueError, OSError) as error:
            print(f"VeloShot: {error}", file=sys.stderr)
            self.app.exit(1)

    def fail(self, message):
        print(f"VeloShot: {message}", file=sys.stderr)
        QMessageBox.critical(None, "VeloShot", message)
        self.maybe_quit()


def write_png(image):
    from PySide6.QtCore import QBuffer, QIODevice
    buffer = QBuffer()
    buffer.open(QIODevice.OpenModeFlag.WriteOnly)
    if not image.save(buffer, "PNG"):
        raise RuntimeError("No se pudo codificar la imagen PNG.")
    sys.stdout.buffer.write(bytes(buffer.data()))
    sys.stdout.buffer.flush()


def parse_region(value):
    match = re.fullmatch(r"([1-9]\d*)x([1-9]\d*)([+-]\d+)([+-]\d+)", value)
    if not match:
        raise ValueError("Región inválida: usa ANCHOxALTO+X+Y, por ejemplo 800x600+100+50.")
    width, height, x, y = map(int, match.groups())
    minimum, maximum = -(2**31), 2**31 - 1
    if not (width <= maximum and height <= maximum and minimum <= x <= maximum
            and minimum <= y <= maximum and x + width - 1 <= maximum
            and y + height - 1 <= maximum):
        raise ValueError("La región excede el rango de coordenadas admitido.")
    return QRect(x, y, width, height)


def parse_args(argv=None):
    parser = argparse.ArgumentParser(prog="veloshot", description="Captura y anota la pantalla con Qt.")
    parser.add_argument("--version", action="version", version=f"VeloShot {__version__}")
    subs = parser.add_subparsers(dest="mode")
    for mode, help_text in [("gui", "Seleccionar y anotar un área"),
                             ("full", "Capturar todos los monitores"),
                             ("screen", "Capturar un monitor"),
                             ("edit", "Anotar una imagen existente")]:
        sub = subs.add_parser(mode, help=help_text)
        sub.add_argument("-p", "--path", help="Archivo o carpeta de salida")
        sub.add_argument("-d", "--delay", type=int, default=0, metavar="MS", help="Retardo en milisegundos")
        if mode in ("gui", "full", "screen"):
            sub.add_argument("-c", "--clipboard", action="store_true", help="Copiar al portapapeles")
            sub.add_argument("-r", "--raw", action="store_true", help="Escribir PNG en stdout")
        if mode in ("gui", "screen"):
            sub.add_argument("--region", help="Región ANCHOxALTO+X+Y (coordenadas del escritorio)")
            sub.add_argument("--pin", action="store_true", help="Fijar imagen en el escritorio")
        if mode == "gui":
            sub.add_argument("--last-region", action="store_true", help="Repetir última selección")
            sub.add_argument("-g", "--print-geometry", action="store_true", help="Imprimir geometría al aceptar")
            sub.add_argument("-s", "--accept-on-select", action="store_true", help="Aceptar al terminar la selección")
        if mode == "screen":
            sub.add_argument("-n", "--number", type=int, help="Monitor, empezando por 0; por defecto el del cursor")
            sub.add_argument("-e", "--edit", action="store_true", help="Abrir captura en el editor")
        if mode == "edit":
            sub.add_argument("image", help="Ruta de la imagen")
    subs.add_parser("launcher", help="Abrir el lanzador")
    subs.add_parser("tray", aliases=["no-gui"],
                    help="Iniciar en segundo plano sin abrir una ventana")
    subs.add_parser("config", help="Configurar VeloShot")
    parser.set_defaults(path=None, delay=0, clipboard=False, raw=False, pin=False, region=None,
                        last_region=False, print_geometry=False, accept_on_select=False, edit=False)
    args = parser.parse_args(argv)
    if args.delay < 0:
        parser.error("El retardo no puede ser negativo.")
    if args.region:
        try:
            parse_region(args.region)
        except ValueError as error:
            parser.error(str(error))
    return args


def main(argv=None):
    args = parse_args(argv)
    if os.environ.get("XDG_SESSION_TYPE") == "wayland" and args.mode in (
            None, "gui", "full", "screen", "launcher", "tray", "no-gui"):
        print("VeloShot: la captura del escritorio requiere una sesión X11; el portal Wayland aún no está implementado.", file=sys.stderr)
        return 2
    app = QApplication([sys.argv[0]])
    app.setApplicationName("VeloShot")
    app.setApplicationVersion(__version__)
    app.setWindowIcon(icon("capture", "#b87bf1"))
    controller = Controller(app, args)
    signal.signal(signal.SIGINT, lambda *_: app.quit())
    timer = QTimer()
    timer.timeout.connect(lambda: None)
    timer.start(250)
    QTimer.singleShot(0, controller.start)
    return app.exec()


if __name__ == "__main__":
    sys.exit(main())

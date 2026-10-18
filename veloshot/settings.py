from pathlib import Path

from PySide6.QtCore import QSettings
from PySide6.QtWidgets import (QCheckBox, QColorDialog, QDialog, QDialogButtonBox,
                               QFileDialog, QFormLayout, QHBoxLayout, QLabel,
                               QLineEdit, QPushButton, QSpinBox, QTabWidget,
                               QVBoxLayout, QWidget)
from PySide6.QtGui import QColor


class Settings:
    def __init__(self):
        self.store = QSettings("VeloShot", "VeloShot")
        migration_key = "migrations/flareshot-settings"
        if not self.store.contains(migration_key):
            legacy = QSettings("FlareShot", "FlareShot")
            if not self.store.allKeys():
                for key in legacy.allKeys():
                    self.store.setValue(key, legacy.value(key))
            self.store.setValue(migration_key, True)
            self.store.sync()

    def get(self, key, default):
        return self.store.value(key, default, type=type(default))

    def set(self, key, value):
        self.store.setValue(key, value)


class SettingsDialog(QDialog):
    def __init__(self, settings, parent=None):
        super().__init__(parent)
        self.settings = settings
        self.setWindowTitle("VeloShot · Configuración")
        self.resize(560, 410)
        layout = QVBoxLayout(self)
        tabs = QTabWidget()
        layout.addWidget(tabs)
        general = QWidget()
        form = QFormLayout(general)
        self.directory = QLineEdit(settings.get("directory", str(Path.home() / "Pictures")))
        browse = QPushButton("Elegir…")
        browse.clicked.connect(self.browse)
        row = QHBoxLayout()
        row.addWidget(self.directory)
        row.addWidget(browse)
        form.addRow("Carpeta de capturas", row)
        self.pattern = QLineEdit(settings.get("pattern", "%Y-%m-%d_%H-%M-%S"))
        form.addRow("Nombre (strftime)", self.pattern)
        self.delay = QSpinBox()
        self.delay.setRange(0, 60)
        self.delay.setSuffix(" s")
        self.delay.setValue(settings.get("delay", 0))
        form.addRow("Retardo de captura", self.delay)
        self.help = QCheckBox("Mostrar ayuda al seleccionar")
        self.help.setChecked(settings.get("help", True))
        form.addRow(self.help)
        self.copy_save = QCheckBox("Copiar también al guardar")
        self.copy_save.setChecked(settings.get("copy_save", False))
        form.addRow(self.copy_save)
        tabs.addTab(general, "General")
        tools = QWidget()
        tool_form = QFormLayout(tools)
        self.width = QSpinBox()
        self.width.setRange(1, 50)
        self.width.setValue(settings.get("width", 3))
        tool_form.addRow("Grosor inicial", self.width)
        self.color = settings.get("color", "#ff003b")
        self.color_button = QPushButton(self.color)
        self.color_button.clicked.connect(self.choose_color)
        tool_form.addRow("Color inicial", self.color_button)
        tool_form.addRow(QLabel("La rueda cambia el grosor. Clic derecho abre los colores."))
        tabs.addTab(tools, "Herramientas")
        keys = QLabel("<b>Durante una captura</b><br><br>"
                      "P L A R C M T B I N → lápiz, línea, flecha, rectángulo,<br>"
                      "círculo, marcador, texto, pixelar, invertir, contador.<br><br>"
                      "Ctrl+C / Enter → copiar · Ctrl+S → guardar<br>"
                      "Ctrl+Z / Ctrl+Mayús+Z → deshacer / rehacer<br>"
                      "Ctrl+A → seleccionar todo · Tab → panel lateral<br>"
                      "V → mover selección · Espacio → panel lateral<br>Flechas → mover 1 px<br>"
                      "Mayús+flechas → cambiar tamaño · Esc → cancelar<br><br>"
                      "<b>Captura global</b><br>Asigna <code>run.sh gui</code> a Impr Pant<br>"
                      "en la configuración de teclado de tu escritorio.")
        keys.setWordWrap(True)
        tabs.addTab(keys, "Atajos")
        buttons = QDialogButtonBox(QDialogButtonBox.StandardButton.Save |
                                   QDialogButtonBox.StandardButton.Cancel)
        buttons.accepted.connect(self.save)
        buttons.rejected.connect(self.reject)
        layout.addWidget(buttons)

    def browse(self):
        path = QFileDialog.getExistingDirectory(self, "Carpeta de capturas", self.directory.text())
        if path:
            self.directory.setText(path)

    def choose_color(self):
        color = QColorDialog.getColor(QColor(self.color), self)
        if color.isValid():
            self.color = color.name()
            self.color_button.setText(self.color)

    def save(self):
        for key, value in {"directory": self.directory.text(), "pattern": self.pattern.text(),
                           "delay": self.delay.value(), "help": self.help.isChecked(),
                           "copy_save": self.copy_save.isChecked(), "width": self.width.value(),
                           "color": self.color}.items():
            self.settings.set(key, value)
        self.accept()

#!/usr/bin/env python3
"""Run on Xvfb with two X screens to exercise real QScreen choices and pixels."""
import argparse
import json
import os
import subprocess
from pathlib import Path
import sys
import tempfile
import time

from PySide6.QtCore import Qt
from PySide6.QtGui import QColor, QPainter
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QApplication, QPushButton, QWidget

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from veloshot.__main__ import Controller, parse_args
from veloshot.editor import CaptureEditor


class Fixture(QWidget):
    def __init__(self, screen, color):
        super().__init__(None, Qt.WindowType.FramelessWindowHint)
        self.color = QColor(color)
        self.setScreen(screen)
        self.setGeometry(screen.geometry())

    def paintEvent(self, event):
        painter = QPainter(self)
        painter.fillRect(self.rect(), self.color)
        painter.end()


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--output", type=Path, default=Path("analysis/monitor-picker"))
    args = parser.parse_args()
    display = os.environ.get("DISPLAY", "")
    if not display or display.split(".")[0] in (":0", ":1"):
        raise SystemExit("Use a private Xvfb with two -screen arguments.")
    output = args.output.resolve()
    output.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(prefix="veloshot-monitor-") as directory:
        os.environ.update(XDG_CONFIG_HOME=directory, QT_QPA_PLATFORM="xcb", XDG_SESSION_TYPE="x11")
        app = QApplication([])
        screens = app.screens()
        assert len(screens) == 2, f"Expected two real QScreen objects, got {len(screens)}"
        controller = Controller(app, parse_args([]))
        controller.setup_tray = lambda: None
        fixtures = [Fixture(screen, color) for screen, color in zip(screens, ("#b94430", "#246db8"))]

        def pump(seconds=0.4):
            until = time.monotonic() + seconds
            while time.monotonic() < until:
                app.processEvents()
                time.sleep(0.01)

        checks = []
        try:
            for fixture in fixtures:
                fixture.show()
            pump()
            for index, color in enumerate(("#b94430", "#246db8")):
                controller.show_launcher()
                pump()
                launcher = controller.launcher
                assert launcher.monitor_row.isVisible()
                assert launcher.monitor.count() == 3
                launcher.monitor.setCurrentIndex(index + 1)
                launcher.grab().save(str(output / f"launcher-monitor-{index + 1}.png"))
                button = next(button for button in launcher.findChildren(QPushButton)
                              if button.text() == "Pantalla completa")
                QTest.mouseClick(button, Qt.MouseButton.LeftButton)
                pump(0.6)
                editor = next(window for window in controller.windows if isinstance(window, CaptureEditor))
                native_geometry = subprocess.check_output(
                    ["xdotool", "getwindowgeometry", "--shell", str(int(editor.winId()))], text=True)
                assert f"SCREEN={index}\n" in native_geometry, "Editor opened on the wrong X screen"
                assert editor.geometry() == screens[index].geometry()
                result = editor.result()
                assert result.size() == screens[index].geometry().size()
                assert result.pixelColor(100, 100).name() == color
                assert result.save(str(output / f"monitor-{index + 1}.png"))
                geometry = screens[index].geometry().getRect()
                editor.copy()
                pump()
                assert app.clipboard().image() == result
                checks.append({"monitor": index + 1, "geometry": geometry,
                               "color": color, "clipboard": True})
            print(json.dumps({"passed": len(checks), "checks": checks}), flush=True)
        finally:
            (output / "verification.json").write_text(json.dumps({"checks": checks}, indent=2))
            for window in list(controller.windows) + fixtures:
                try:
                    window.close()
                except RuntimeError:
                    pass
            pump(0.1)


if __name__ == "__main__":
    main()

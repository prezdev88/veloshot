#!/usr/bin/env python3
"""Regression test for launcher capture with a private i3/Xvfb desktop."""
import argparse
import json
import os
from pathlib import Path
import subprocess
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


class BackgroundWindow(QWidget):
    def paintEvent(self, event):
        painter = QPainter(self)
        painter.fillRect(self.rect(), QColor("#217d62"))
        painter.end()


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--output", type=Path, default=Path("analysis/tiling-regression"))
    args = parser.parse_args()
    display = os.environ.get("DISPLAY", "")
    if not display or display.split(".")[0] in (":0", ":1"):
        raise SystemExit("Launch using xvfb-run on a private display.")
    output = args.output.resolve()
    output.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(prefix="veloshot-i3-") as directory:
        config = Path(directory) / "i3.conf"
        config.write_text("font pango:monospace 10\nfocus_follows_mouse no\n")
        os.environ.update(XDG_CONFIG_HOME=directory, XDG_SESSION_TYPE="x11", QT_QPA_PLATFORM="xcb")
        with open(output / "i3.log", "w") as log:
            wm = subprocess.Popen(["i3", "-c", str(config)], stdout=log, stderr=log)
            app = QApplication([])
            controller = Controller(app, parse_args([]))
            controller.setup_tray = lambda: None
            windows = []

            def pump(seconds=0.4):
                until = time.monotonic() + seconds
                while time.monotonic() < until:
                    app.processEvents()
                    time.sleep(0.01)

            try:
                pump(0.7)
                if wm.poll() is not None:
                    raise AssertionError("Private i3 failed to start; inspect i3.log")
                for index in range(2):
                    window = BackgroundWindow()
                    window.setWindowTitle(f"Tiled fixture {index}")
                    window.show()
                    windows.append(window)
                pump()
                controller.show_launcher()
                pump()
                button = next(b for b in controller.launcher.findChildren(QPushButton)
                              if b.text() == "Pantalla completa")
                QTest.mouseClick(button, Qt.MouseButton.LeftButton)
                pump(1)
                editor = next(w for w in controller.windows if isinstance(w, CaptureEditor))
                screen = app.primaryScreen().geometry()
                report = {
                    "screen": screen.getRect(),
                    "editor": editor.geometry().getRect(),
                    "background": [editor.document.background.width(), editor.document.background.height()],
                    "selection": editor.document.selection.getRect(),
                }
                editor.grab().save(str(output / "editor.png"))
                (output / "verification.json").write_text(json.dumps(report, indent=2))
                print(json.dumps(report), flush=True)
                assert editor.geometry() == screen, "i3 restricted the capture editor to a tile"
                assert editor.document.selection == editor.document.background.rect()
                background_size = editor.document.background.size()
                # Keyboard delivery and transfer out of the editor must still work.
                subprocess.run(["xdotool", "key", "ctrl+c"], check=True)
                pump()
                copied = app.clipboard().image()
                assert copied.size() == background_size, "Clipboard contains a partial image"
                assert editor not in controller.windows, "Copy keyboard shortcut was not delivered to the overlay"
                report["clipboard"] = [copied.width(), copied.height()]
                controller.show_launcher()
                pump()
                button = next(b for b in controller.launcher.findChildren(QPushButton)
                              if b.text() == "Seleccionar un área de la pantalla")
                QTest.mouseClick(button, Qt.MouseButton.LeftButton)
                pump(0.7)
                editor = next(w for w in controller.windows if isinstance(w, CaptureEditor))
                assert editor.geometry() == screen, "Area selection is confined to an i3 tile"
                # Select beyond the old 480-pixel tile, near the desktop's far edge.
                for command in (["mousemove", "1000", "700"], ["mousedown", "1"],
                                ["mousemove", "1370", "950"], ["mouseup", "1"]):
                    subprocess.run(["xdotool", *command], check=True)
                    pump(0.1)
                assert editor.document.selection.getRect() == (1000, 700, 371, 251)
                subprocess.run(["xdotool", "key", "ctrl+c"], check=True)
                pump()
                copied = app.clipboard().image()
                assert (copied.width(), copied.height()) == (371, 251)
                report["far_edge_selection"] = [1000, 700, 371, 251]
                (output / "verification.json").write_text(json.dumps(report, indent=2))
                print("PASS: full capture and far-edge area selection work under i3; Ctrl+C copies both", flush=True)
            finally:
                for window in list(controller.windows) + windows:
                    try:
                        window.close()
                    except RuntimeError:
                        pass
                app.processEvents()
                wm.terminate()
                wm.wait(timeout=5)


if __name__ == "__main__":
    main()

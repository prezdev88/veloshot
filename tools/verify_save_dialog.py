#!/usr/bin/env python3
"""Click Save and operate the real file dialog on a private i3/Xvfb desktop."""
import argparse
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import time

from PySide6.QtCore import QPoint, QRect, Qt, QTimer
from PySide6.QtGui import QColor, QImage
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QApplication, QFileDialog, QLineEdit, QToolButton, QWidget

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from veloshot.__main__ import Controller, parse_args


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--output", type=Path, default=Path("analysis/save-dialog"))
    args = parser.parse_args()
    display = os.environ.get("DISPLAY", "")
    if not display or display.split(".")[0] in (":0", ":1"):
        raise SystemExit("Use a private display with xvfb-run.")
    output = args.output.resolve()
    output.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(prefix="veloshot-save-") as temporary:
        config = Path(temporary) / "i3.conf"
        config.write_text("font pango:monospace 10\nfocus_follows_mouse no\n")
        os.environ.update(XDG_CONFIG_HOME=temporary, XDG_SESSION_TYPE="x11", QT_QPA_PLATFORM="xcb")
        with open(output / "i3.log", "w") as log:
            wm = subprocess.Popen(["i3", "-c", str(config)], stdout=log, stderr=log)
            app = QApplication([])
            controller = Controller(app, parse_args(["gui"]))
            controller.setup_tray = lambda: None
            fixture = QWidget()
            errors = []
            checks = []

            def pump(seconds=0.4):
                end = time.monotonic() + seconds
                while time.monotonic() < end:
                    app.processEvents()
                    time.sleep(0.01)

            def image():
                result = QImage(1440, 1000, QImage.Format.Format_ARGB32)
                result.fill(QColor("#257157"))
                return result

            def make_editor():
                editor = controller.create_editor(image(), QRect(0, 0, 1440, 1000))
                editor.document.selection = QRect(100, 100, 400, 300)
                editor.selection_changed()
                pump()
                return editor

            def handle_dialog(destination, cancel=False):
                dialog = app.activeModalWidget()
                try:
                    assert isinstance(dialog, QFileDialog), "Clicking Save did not open a file dialog"
                    actual = app.primaryScreen().grabWindow(0).toImage()
                    expected = dialog.grab().toImage()
                    origin = dialog.mapToGlobal(QPoint(0, 0))
                    matches = total = 0
                    for x in range(10, expected.width() - 10, 20):
                        for y in range(10, expected.height() - 10, 20):
                            if actual.rect().contains(origin + QPoint(x, y)):
                                total += 1
                                matches += actual.pixelColor(origin.x() + x, origin.y() + y) == expected.pixelColor(x, y)
                    ratio = matches / max(1, total)
                    actual.save(str(output / ("cancel-dialog.png" if cancel else "save-dialog.png")))
                    checks.append({"cancel": cancel, "dialog_screen_match": ratio})
                    assert ratio > 0.85, "File dialog is hidden behind the screenshot overlay"
                    if cancel:
                        dialog.reject()
                    else:
                        dialog.setDirectory(str(destination.parent))
                        name = dialog.findChild(QLineEdit, "fileNameEdit")
                        assert name is not None, "File name field is unavailable"
                        name.setFocus()
                        QTest.keyClick(name, Qt.Key.Key_A, Qt.KeyboardModifier.ControlModifier)
                        QTest.keyClicks(name, str(destination))
                        checks[-1]["selected_files"] = dialog.selectedFiles()
                        dialog.accept()
                except Exception as error:
                    errors.append(str(error))
                    if dialog:
                        dialog.reject()

            try:
                pump(0.7)
                assert wm.poll() is None, "Private i3 failed to start"
                fixture.setWindowTitle("Save dialog fixture")
                fixture.show()
                pump()
                editor = make_editor()
                destination = Path(temporary) / "capture.png"
                QTimer.singleShot(600, lambda: handle_dialog(destination))
                QTest.mouseClick(editor.findChild(QToolButton, "save"), Qt.MouseButton.LeftButton)
                assert not errors, errors
                saved = QImage(str(destination))
                assert not saved.isNull(), f"No image saved at {destination}; dialog: {checks}"
                assert saved.size() == QRect(0, 0, 400, 300).size()
                assert saved.pixelColor(50, 50).name() == "#257157"
                pump()
                assert editor not in controller.windows
                editor = make_editor()
                QTimer.singleShot(600, lambda: handle_dialog(None, cancel=True))
                QTest.mouseClick(editor.findChild(QToolButton, "save"), Qt.MouseButton.LeftButton)
                assert not errors, errors
                assert editor.isVisible() and editor.geometry() == QRect(0, 0, 1440, 1000)
                pump(0.3)
                checks.append({"after_cancel_active_window": app.activeWindow().windowTitle() if app.activeWindow() else None,
                               "focus_widget": app.focusWidget().metaObject().className() if app.focusWidget() else None,
                               "keyboard_grabber": QWidget.keyboardGrabber().windowTitle() if QWidget.keyboardGrabber() else None,
                               "selected_area": editor.document.selection.getRect()})
                subprocess.run(["xdotool", "key", "ctrl+c"], check=True)
                pump()
                assert app.clipboard().image().size() == QRect(0, 0, 400, 300).size()
                assert editor not in controller.windows, "Editor did not regain keyboard focus after cancellation"
                print("PASS: Save button shows its dialog under i3, writes PNG, and Cancel restores capture and keyboard focus", flush=True)
            finally:
                (output / "verification.json").write_text(json.dumps({"checks": checks, "errors": errors}, indent=2))
                for window in list(controller.windows) + [fixture]:
                    try:
                        window.close()
                    except RuntimeError:
                        pass
                pump(0.1)
                wm.terminate()
                wm.wait(timeout=5)


if __name__ == "__main__":
    main()

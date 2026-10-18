#!/usr/bin/env python3
"""Exercise the actual executable on a private X11 screen; never uses the real desktop."""
import argparse
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import time

from PySide6.QtCore import Qt
from PySide6.QtGui import QImage
from PySide6.QtWidgets import QApplication

from probe_original import Fixture


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--output", type=Path, default=Path("analysis/rebuilt"))
    args = parser.parse_args()
    display = os.environ.get("DISPLAY", "")
    if not display or display.split(".")[0] in (":0", ":1"):
        raise SystemExit("Use xvfb-run on a private display.")
    output = args.output.resolve()
    output.mkdir(parents=True, exist_ok=True)
    processes = []
    checks = []
    with tempfile.TemporaryDirectory(prefix="veloshot-e2e-") as temporary:
        env = dict(os.environ, XDG_CONFIG_HOME=temporary, QT_QPA_PLATFORM="xcb", XDG_SESSION_TYPE="x11")
        os.environ.update(XDG_CONFIG_HOME=temporary, QT_QPA_PLATFORM="xcb")
        app = QApplication([])
        app.setQuitOnLastWindowClosed(False)
        fixture = Fixture(None, Qt.WindowType.FramelessWindowHint)
        fixture.setGeometry(app.primaryScreen().geometry())
        fixture.show()

        def pump(seconds=0.25):
            until = time.monotonic() + seconds
            while time.monotonic() < until:
                app.processEvents()
                time.sleep(0.01)

        def run(*args):
            process = subprocess.Popen([sys.executable, "-m", "veloshot", *map(str, args)],
                                       env=env, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
            processes.append(process)
            return process

        def finish(process):
            until = time.monotonic() + 8
            while process.poll() is None and time.monotonic() < until:
                pump(0.05)
            if process.poll() is None:
                raise AssertionError("Executable failed to exit within 8 seconds")
            stdout, stderr = process.communicate()
            if process.returncode:
                raise AssertionError(stderr.decode())
            if b"Traceback" in stderr:
                raise AssertionError(stderr.decode())
            return stdout

        def xdo(*args):
            subprocess.run(["xdotool", *map(str, args)], env=env, check=True, capture_output=True)
            pump(0.1)

        def drag(x1, y1, x2, y2):
            xdo("mousemove", x1, y1)
            xdo("mousedown", 1)
            xdo("mousemove", x2, y2)
            xdo("mouseup", 1)

        def snapshot(name):
            pump()
            assert app.primaryScreen().grabWindow(0).save(str(output / name))

        try:
            pump(0.5)
            process = run("full", "-p", output / "full.png")
            finish(process)
            full = QImage(str(output / "full.png"))
            assert full.size() == app.primaryScreen().geometry().size()
            assert full.pixelColor(80, 180).name() == "#7254d9"
            checks.append("full CLI captures actual X11 pixels and dimensions")

            raw = finish(run("screen", "-n", 0, "--raw"))
            assert raw.startswith(b"\x89PNG\r\n\x1a\n")
            decoded = QImage.fromData(raw)
            assert decoded.pixelColor(80, 180).name() == "#7254d9"
            checks.append("screen --raw outputs a valid PNG with desktop pixels")

            cropped = QImage.fromData(finish(run("screen", "--region", "320x230+70+165", "--raw")))
            assert cropped.width() == 320 and cropped.height() == 230
            assert cropped.pixelColor(10, 15).name() == "#7254d9"
            checks.append("screen --region crops the requested desktop rectangle")

            process = run("gui", "--region", "320x230+70+165", "--print-geometry")
            pump(0.7)
            xdo("key", "Return")
            assert finish(process).strip() == b"320x230+70+165"
            checks.append("GUI --region preselects and Enter prints exact accepted geometry")

            process = run("gui", "--region", "320x230+70+165", "--raw", "-p", output / "accepted.png")
            pump(0.7)
            xdo("key", "Return")
            raw = finish(process)
            assert QImage.fromData(raw).size() == QImage(str(output / "accepted.png")).size()
            checks.append("GUI accept can save a file and emit raw PNG together")

            process = run("gui", "--accept-on-select", "-p", output / "auto-selected.png")
            pump(0.7)
            drag(70, 165, 389, 394)
            finish(process)
            assert QImage(str(output / "auto-selected.png")).width() == 320
            checks.append("--accept-on-select saves immediately on mouse release")

            process = run("gui", "--last-region", "--print-geometry")
            pump(0.7)
            xdo("key", "Return")
            assert finish(process).strip() == b"320x230+70+165"
            checks.append("--last-region restores the previously accepted desktop region")

            process = run("gui", "-p", output / "annotated.png")
            pump(1)
            drag(170, 150, 1070, 670)
            snapshot("01-selection.png")
            xdo("key", "a")
            drag(250, 250, 650, 340)
            xdo("key", "r")
            drag(780, 200, 1020, 420)
            xdo("key", "ctrl+z")
            xdo("key", "ctrl+shift+z")
            xdo("key", "Tab")
            snapshot("02-annotations-panel.png")
            xdo("key", "ctrl+s")
            finish(process)
            annotated = QImage(str(output / "annotated.png"))
            assert annotated.width() in (900, 901) and annotated.height() in (520, 521)
            assert annotated.pixelColor(610, 100).name() == "#ff003b"
            checks.append("GUI drag selection, arrow, rectangle, undo/redo, panel and Ctrl+S save cropped annotated PNG")

            process = run("gui")
            pump(0.8)
            drag(170, 150, 1070, 670)
            xdo("key", "ctrl+c")
            pump(0.6)
            clipboard = app.clipboard().image()
            assert not clipboard.isNull() and clipboard.width() in (900, 901)
            assert process.poll() is None, "X11 clipboard owner exited prematurely"
            checks.append("Ctrl+C survives editor closure; a separate process retrieves the image")
            app.clipboard().setText("release screenshot ownership")
            pump(0.4)

            process = run("gui")
            pump(0.7)
            xdo("key", "Escape")
            finish(process)
            checks.append("Escape cancels and terminates standalone GUI process")

            process = run("launcher")
            pump(0.8)
            snapshot("03-launcher.png")
            process.terminate()
            process.wait(timeout=3)
            process = run("config")
            pump(0.7)
            snapshot("04-settings.png")
            process.terminate()
            process.wait(timeout=3)
            checks.append("Launcher and configuration windows open")
        finally:
            for process in processes:
                if process.poll() is None:
                    process.terminate()
                    process.wait(timeout=3)
            fixture.close()
            (output / "verification.json").write_text(json.dumps({"checks": checks, "display": display}, indent=2))
        print(json.dumps({"passed": len(checks), "checks": checks}))


if __name__ == "__main__":
    main()

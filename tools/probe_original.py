#!/usr/bin/env python3
"""Observe installed Flameshot on a private Xvfb display and D-Bus session.

Run: xvfb-run -a -s '-screen 0 1440x1000x24' dbus-run-session -- \
    python3 tools/probe_original.py --output analysis/original
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
from pathlib import Path
import subprocess
import tempfile
import time

from PySide6.QtCore import QRect, Qt
from PySide6.QtGui import QColor, QFont, QPainter
from PySide6.QtWidgets import QApplication, QWidget


class Fixture(QWidget):
    def paintEvent(self, event):
        painter = QPainter(self)
        painter.fillRect(self.rect(), QColor("#edf2f8"))
        painter.fillRect(QRect(0, 0, self.width(), 88), QColor("#19324e"))
        painter.setPen(QColor("white"))
        painter.setFont(QFont("Sans Serif", 25, QFont.Weight.Bold))
        painter.drawText(42, 56, "Screenshot annotation test fixture")
        for index, color in enumerate(["#7254d9", "#03a6a1", "#f1a03b"]):
            x = 70 + index * 365
            painter.fillRect(QRect(x, 165, 320, 230), QColor(color))
            painter.setPen(QColor("white"))
            painter.setFont(QFont("Sans Serif", 19))
            painter.drawText(x + 25, 215, f"Card {index + 1}")
        painter.setPen(QColor("#19324e"))
        painter.setFont(QFont("Sans Serif", 17))
        painter.drawText(70, 470, "A controlled background; no personal desktop contents.")
        painter.drawText(70, 515, "Select an area, then annotate, copy or save.")


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, default=Path("analysis/original"))
    parser.add_argument("--cli-only", action="store_true", help="Collect offscreen CLI evidence when Xvfb sockets are unavailable")
    args = parser.parse_args()
    display = os.environ.get("DISPLAY", "")
    if not args.cli_only and (not display or display.split(".")[0] in (":0", ":1")):
        raise SystemExit("Refusing a real/default display. Launch with xvfb-run -a.")
    if not args.cli_only and not os.environ.get("DBUS_SESSION_BUS_ADDRESS"):
        raise SystemExit("A private D-Bus session is required; use dbus-run-session.")
    output = args.output.resolve()
    output.mkdir(parents=True, exist_ok=True)
    report = {
        "target": "/usr/bin/flameshot", "display": None if args.cli_only else display,
        "isolation": "Xvfb/private D-Bus plus temporary HOME/XDG config/data/cache/runtime",
        "commands": [], "observations": [], "screenshots": [],
        "limitations": [
            "Screenshots record one X11 virtual display; Wayland and multi-monitor behavior are untested.",
            "No network upload, real desktop, or existing user configuration is accessed.",
            "Documentation/translation strings are separate from behavior observed by this harness.",
        ],
    }
    with tempfile.TemporaryDirectory(prefix="flameshot-original-") as temporary:
        root = Path(temporary)
        env = dict(os.environ)
        env.update(HOME=str(root), XDG_CONFIG_HOME=str(root / "config"),
                   XDG_CACHE_HOME=str(root / "cache"), XDG_DATA_HOME=str(root / "data"),
                   XDG_RUNTIME_DIR=str(root / "runtime"), QT_QPA_PLATFORM="offscreen" if args.cli_only else "xcb",
                   XDG_SESSION_TYPE="x11", XDG_CURRENT_DESKTOP="i3", DESKTOP_SESSION="i3",
                   LANG="C.UTF-8", LC_ALL="C.UTF-8")
        env.pop("WAYLAND_DISPLAY", None)
        report["capture_environment"] = {key: env[key] for key in (
            "XDG_SESSION_TYPE", "XDG_CURRENT_DESKTOP", "DESKTOP_SESSION", "QT_QPA_PLATFORM")}
        report["capture_environment"]["WAYLAND_DISPLAY"] = None
        for key in ("XDG_CONFIG_HOME", "XDG_CACHE_HOME", "XDG_DATA_HOME", "XDG_RUNTIME_DIR"):
            Path(env[key]).mkdir(mode=0o700)
        config = Path(env["XDG_CONFIG_HOME"]) / "flameshot"
        config.mkdir()
        (config / "flameshot.ini").write_text(
            "[General]\nshowStartupLaunchMessage=false\nshowDesktopNotification=false\n"
            "useX11LegacyScreenshot=true\n", encoding="utf-8")
        report["capture_method"] = "Installed Flameshot official legacy X11 option: useX11LegacyScreenshot=true"
        # Keep Qt's own configuration and font/cache writes in the same temporary scope.
        os.environ.update({key: env[key] for key in (
            "HOME", "XDG_CONFIG_HOME", "XDG_CACHE_HOME", "XDG_DATA_HOME", "XDG_RUNTIME_DIR", "QT_QPA_PLATFORM",
            "XDG_SESSION_TYPE", "XDG_CURRENT_DESKTOP", "DESKTOP_SESSION")})
        os.environ.pop("WAYLAND_DISPLAY", None)
        app = QApplication(["flameshot-original-probe"])

        def pause(seconds=0.5):
            end = time.monotonic() + seconds
            while time.monotonic() < end:
                app.processEvents()
                time.sleep(0.02)

        def command(argv, timeout=10):
            try:
                result = subprocess.run(argv, env=env, capture_output=True, text=True, timeout=timeout)
                record = {"argv": argv, "exit_code": result.returncode,
                          "stdout": result.stdout, "stderr": result.stderr}
            except subprocess.TimeoutExpired as error:
                record = {"argv": argv, "timeout": timeout,
                          "stdout": str(error.stdout or ""), "stderr": str(error.stderr or "")}
            report["commands"].append(record)
            return record

        def xdo(*argv):
            result = command(["xdotool", *map(str, argv)], timeout=5)
            # Qt consumes X11 pointer events asynchronously; preserve each
            # pressed/moved/released state long enough for the target to see it.
            pause(0.12)
            return result

        def snapshot(name, description):
            pause()
            destination = output / f"{name}.png"
            success = app.primaryScreen().grabWindow(0).save(str(destination))
            report["screenshots"].append({"file": destination.name, "saved": success,
                                           "sha256": hashlib.sha256(destination.read_bytes()).hexdigest() if success else None,
                                           "description": description})

        for tail in (["--version"], ["--help"], ["gui", "--help"],
                     ["full", "--help"], ["screen", "--help"], ["config", "--help"]):
            command(["/usr/bin/flameshot", *tail])
        validation = command(["/usr/bin/flameshot", "config", "--check"])
        validation_text = validation.get("stdout", "") + validation.get("stderr", "")
        report["configuration_validation"] = {
            "exit_code": validation.get("exit_code"),
            "reported_error": any(text in validation_text.lower() for text in (
                "unrecognized setting", "bad value", "contains an error", "configuration file has errors")),
        }
        if validation.get("exit_code") != 0 or report["configuration_validation"]["reported_error"]:
            (output / "observations.json").write_text(json.dumps(report, indent=2), encoding="utf-8")
            raise SystemExit("Temporary Flameshot configuration failed validation; see observations.json")
        if args.cli_only:
            report["isolation"] = "offscreen CLI only; temporary HOME/XDG config/data/cache/runtime"
            report["limitations"].append("GUI capture was not performed: local sandbox rejected Xvfb/D-Bus UNIX socket creation.")
            (output / "observations.json").write_text(json.dumps(report, indent=2), encoding="utf-8")
            app.quit()
            print(json.dumps({"report": str(output / "observations.json"), "screenshots": 0,
                              "mode": "cli-only"}))
            return
        fixture = Fixture()
        fixture.setWindowTitle("Controlled screenshot background")
        # Xvfb has no window manager to honor the fullscreen request.
        fixture.setWindowFlags(Qt.WindowType.FramelessWindowHint)
        fixture.setGeometry(app.primaryScreen().geometry())
        fixture.show()
        report["fixture_geometry"] = {
            "x": fixture.x(), "y": fixture.y(), "width": fixture.width(), "height": fixture.height(),
        }
        pause(0.8)
        snapshot("00-background", "Controlled fixture before Flameshot starts.")
        background_hash = report["screenshots"][-1]["sha256"]
        processes = []
        logs = open(output / "runtime.log", "w", encoding="utf-8")
        try:
            daemon = subprocess.Popen(["/usr/bin/flameshot"], env=env, stdout=logs, stderr=logs)
            processes.append(daemon)
            pause(1)
            gui = subprocess.Popen(["/usr/bin/flameshot", "gui"], env=env, stdout=logs, stderr=logs)
            processes.append(gui)
            pause(1.5)
            # Some builds show the legacy-method notice as a modal warning.
            # Only acknowledge a dialog when the matching deprecation notice
            # was actually emitted; never press Return blindly in the capture UI.
            startup_log = (output / "runtime.log").read_text(encoding="utf-8")
            legacy_notice = "deprecated legacy x11 screenshot method" in startup_log.lower()
            report["legacy_deprecation_notice_logged"] = legacy_notice
            if legacy_notice:
                windows = xdo("search", "--onlyvisible", "--class", "[Ff]lameshot")
                for window_id in windows.get("stdout", "").split():
                    kind = command(["xprop", "-id", window_id, "_NET_WM_WINDOW_TYPE"])
                    if "_NET_WM_WINDOW_TYPE_DIALOG" not in kind.get("stdout", ""):
                        continue
                    title = xdo("getwindowname", window_id).get("stdout", "").strip()
                    if "configuration" in title.lower() or "error" in title.lower():
                        continue
                    snapshot("00a-legacy-warning", "Visible dialog after the logged official X11 legacy-method deprecation notice.")
                    report["observations"].append({"kind": "legacy-warning-acknowledged", "title": title,
                                                     "window_id": window_id, "action": "Return sent to that dialog only"})
                    xdo("windowfocus", window_id)
                    xdo("key", "--window", window_id, "Return")
                    pause(1)
                    break
            snapshot("01-capture-before-selection", "Capture overlay before drawing a region.")
            report["capture_overlay_changed_background"] = (
                report["screenshots"][-1]["sha256"] != background_hash)
            capture_log = (output / "runtime.log").read_text(encoding="utf-8")
            report["capture_start_errors"] = [line for line in capture_log.splitlines() if any(
                phrase in line.lower() for phrase in ("unable to capture", "could not locate", "screenshot aborted"))]
            if report["capture_start_errors"] or not report["capture_overlay_changed_background"]:
                raise RuntimeError("No capture overlay observed; inspect runtime.log and 01-capture-before-selection.png")
            resolver = xdo("search", "--onlyvisible", "--name", "Resolve configuration errors|Configuration errors")
            if resolver.get("exit_code") == 0 and resolver.get("stdout", "").strip():
                report["observations"].append({"kind": "configuration-error", "window_ids": resolver["stdout"].split()})
                raise RuntimeError("Flameshot displayed a configuration error; inspect 01-capture-before-selection.png")
            captures = xdo("search", "--onlyvisible", "--class", "^flameshot$")
            candidates = []
            for capture_window in captures.get("stdout", "").split():
                geometry_result = xdo("getwindowgeometry", "--shell", capture_window)
                geometry = dict(line.split("=", 1) for line in geometry_result.get("stdout", "").splitlines() if "=" in line)
                area = int(geometry.get("WIDTH", "0")) * int(geometry.get("HEIGHT", "0"))
                candidates.append((area, capture_window))
            if candidates:
                # The capture surface is the largest Flameshot window; tiny
                # clipboard/selection-owner helper windows must not get focus.
                _, capture_window = max(candidates)
                xdo("windowfocus", capture_window)
                report["capture_window_focused"] = capture_window
            xdo("mousemove", "--sync", 170, 150)
            xdo("mousedown", 1)
            for step in range(1, 11):
                xdo("mousemove", "--sync", 170 + 90 * step, 150 + 52 * step)
                pause(0.08)
            xdo("mouseup", 1)
            pause(1)
            snapshot("02-selection-toolbar", "After dragging a 900x520 region from (170,150) to (1070,670).")
            report["selection_verification"] = {
                "requested_drag": [170, 150, 1070, 670],
                "requested_size": [900, 520],
                "observed_size": None,
                "status": "Inspect the geometry label in 02-selection-toolbar.png; pointer coordinates alone do not verify selection size.",
            }
            command(["xwininfo", "-root", "-tree"])
            # The recorded hover is a position probe, not a claim about which tool is there.
            xdo("mousemove", 250, 697)
            pause(1.5)
            snapshot("03-toolbar-hover", "Hover probe below selection; tooltip availability depends on toolbar position.")
            xdo("key", "space")
            pause(0.7)
            snapshot("04-space-side-panel", "State after pressing Space once, as instructed by the original capture help.")
            xdo("key", "Escape")
            pause(0.5)
            snapshot("05-escape", "State after Escape; may include a quit-confirmation dialog.")
            # End the owned capture and daemon even if Escape opened a confirmation.
            # A fresh daemon state avoids feeding Return into an unknown dialog.
            for process in reversed(processes):
                if process.poll() is None:
                    process.terminate()
            for process in reversed(processes):
                if process.poll() is None:
                    try:
                        process.wait(timeout=3)
                    except subprocess.TimeoutExpired:
                        process.kill()
                        process.wait(timeout=3)
            pause(0.5)
            config_process = subprocess.Popen(["/usr/bin/flameshot", "config"], env=env,
                                              stdout=logs, stderr=logs)
            processes.append(config_process)
            pause(1.2)
            snapshot("06-configuration", "Original Flameshot configuration window at its initial tab.")
            command(["xwininfo", "-root", "-tree"])
            report["observations"].append({"kind": "capture-probe", "selection_drag": [170, 150, 1070, 670],
                                             "keys": ["Space", "Escape"],
                                             "configuration_launch": "Fresh process after terminating owned daemon/capture; no confirmation-button assumption.",
                                             "note": "Interpret images and command outcomes; actions alone do not prove UI transitions."})
        finally:
            for process in reversed(processes):
                if process.poll() is None:
                    process.terminate()
            for process in reversed(processes):
                try:
                    process.wait(timeout=3)
                except subprocess.TimeoutExpired:
                    process.kill()
                    process.wait(timeout=3)
            logs.close()
            report["process_exit_codes"] = [process.returncode for process in processes]
            report["runtime_log"] = (output / "runtime.log").read_text(encoding="utf-8")
            report["temporary_configuration"] = {
                str(path.relative_to(root)): path.read_text(encoding="utf-8")
                for path in config.glob("*.ini")
            }
            (output / "observations.json").write_text(json.dumps(report, indent=2), encoding="utf-8")
            fixture.close()
            app.quit()
    print(json.dumps({"report": str(output / "observations.json"),
                      "screenshots": len(report["screenshots"]), "display": display}))


if __name__ == "__main__":
    main()

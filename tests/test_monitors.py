"""Monitor choices must change captured pixels, desktop placement, and crop bounds."""
import os
from pathlib import Path
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import patch

os.environ["QT_QPA_PLATFORM"] = "offscreen"

from PySide6.QtCore import QCoreApplication, QEvent, QRect, QSettings, Qt
from PySide6.QtGui import QColor, QImage, QPixmap
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QApplication, QPushButton
from shiboken6 import isValid

from veloshot.__main__ import Controller, parse_args
from veloshot.editor import CaptureEditor


class MonitorTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])
        cls.app.setQuitOnLastWindowClosed(False)

    def setUp(self):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        path = str(Path(temporary.name) / "settings.ini")
        self.patches = []
        self.patch("veloshot.settings.QSettings", lambda *args: QSettings(path, QSettings.Format.IniFormat))
        self.quit_patch = patch.object(self.app, "quit")
        self.quit_patch.start()
        self.addCleanup(self.quit_patch.stop)
        self.screens = [self.screen("HDMI-1", QRect(-800, 0, 800, 600), "red"),
                        self.screen("DP-1", QRect(0, 0, 900, 480), "blue")]
        self.screens_patch = patch.object(self.app, "screens", side_effect=lambda: list(self.screens))
        self.screens_patch.start()
        self.addCleanup(self.screens_patch.stop)
        primary = patch.object(self.app, "primaryScreen", side_effect=lambda: self.screens[0])
        primary.start()
        self.addCleanup(primary.stop)
        self.controller = Controller(self.app, parse_args(["gui"]))
        self.controller.setup_tray = lambda: None
        screen_setter = patch.object(CaptureEditor, "setScreen")
        self.screen_setter = screen_setter.start()
        self.addCleanup(screen_setter.stop)

    def patch(self, name, replacement):
        active = patch(name, replacement)
        active.start()
        self.addCleanup(active.stop)

    @staticmethod
    def screen(name, geometry, color):
        image = QImage(geometry.size(), QImage.Format.Format_ARGB32)
        image.fill(QColor(color))
        return SimpleNamespace(name=lambda: name, geometry=lambda: QRect(geometry),
                               grabWindow=lambda _: QPixmap.fromImage(image))

    def tearDown(self):
        for window in list(self.controller.windows):
            if isValid(window):
                window.close()
                window.deleteLater()
        self.app.processEvents()
        QCoreApplication.sendPostedEvents(None, QEvent.Type.DeferredDelete)

    def launcher(self):
        self.controller.show_launcher()
        self.app.processEvents()
        return self.controller.launcher

    def editor(self):
        return next(window for window in self.controller.windows if isinstance(window, CaptureEditor))

    def test_launcher_lists_all_named_monitors_with_resolution(self):
        launcher = self.launcher()
        self.assertTrue(launcher.monitor_row.isVisible())
        self.assertEqual(launcher.monitor.count(), 3)
        self.assertEqual(launcher.monitor.itemText(0), "Todas las pantallas")
        self.assertIn("HDMI-1", launcher.monitor.itemText(1))
        self.assertIn("800 × 600", launcher.monitor.itemText(1))
        self.assertIn("principal", launcher.monitor.itemText(1))
        self.assertIn("DP-1", launcher.monitor.itemText(2))

    def test_full_button_captures_only_the_chosen_monitor(self):
        launcher = self.launcher()
        launcher.monitor.setCurrentIndex(2)
        button = next(button for button in launcher.findChildren(QPushButton)
                      if button.text() == "Pantalla completa")
        with patch("veloshot.__main__.QInputDialog.getItem", side_effect=AssertionError("Duplicate monitor prompt")):
            QTest.mouseClick(button, Qt.MouseButton.LeftButton)
            QTest.qWait(250)
        editor = self.editor()
        self.screen_setter.assert_called_once_with(self.screens[1])
        self.assertEqual(editor.geometry(), QRect(0, 0, 900, 480))
        self.assertEqual(editor.document.selection, QRect(0, 0, 900, 480))
        self.assertEqual(editor.result().pixelColor(899, 479), QColor("blue"))

    def test_area_button_uses_chosen_negative_origin_monitor(self):
        launcher = self.launcher()
        launcher.monitor.setCurrentIndex(1)
        button = next(button for button in launcher.findChildren(QPushButton)
                      if button.text() == "Seleccionar un área de la pantalla")
        QTest.mouseClick(button, Qt.MouseButton.LeftButton)
        QTest.qWait(250)
        editor = self.editor()
        self.screen_setter.assert_called_once_with(self.screens[0])
        self.assertEqual(editor.geometry(), QRect(-800, 0, 800, 600))
        self.assertTrue(editor.document.selection.isEmpty())
        self.assertEqual(editor.document.background.pixelColor(799, 599), QColor("red"))

    def test_all_monitors_combines_both_images(self):
        launcher = self.launcher()
        launcher.monitor.setCurrentIndex(0)
        launcher.capture(full=True)
        QTest.qWait(250)
        editor = self.editor()
        self.assertEqual(editor.geometry(), QRect(-800, 0, 1700, 600))
        image = editor.result()
        self.assertEqual(image.width(), 1700)
        self.assertEqual(image.pixelColor(799, 100), QColor("red"))
        self.assertEqual(image.pixelColor(800, 100), QColor("blue"))

    def test_gui_prompt_selection_reaches_capture(self):
        with patch("veloshot.__main__.QInputDialog.getItem", side_effect=lambda *args: (args[3][2], True)):
            self.controller.capture(select_all=True)
        QTest.qWait(150)
        self.assertEqual(self.editor().result().pixelColor(10, 10), QColor("blue"))

    def test_cancel_prompt_does_not_capture_or_hide_launcher(self):
        launcher = self.launcher()
        with patch("veloshot.__main__.QInputDialog.getItem", return_value=("", False)):
            self.controller.capture()
        QTest.qWait(150)
        self.assertTrue(launcher.isVisible())
        self.assertFalse(any(isinstance(window, CaptureEditor) for window in self.controller.windows))

    def test_disconnected_monitor_is_not_replaced_by_all_screens(self):
        chosen = self.screens[1]
        self.controller.capture(screen=chosen)
        self.screens.pop()
        with patch.object(self.controller, "fail") as fail:
            QTest.qWait(150)
        fail.assert_called_once()
        self.assertIn("desconectó", fail.call_args.args[0])
        self.assertFalse(any(isinstance(window, CaptureEditor) for window in self.controller.windows))

    def test_refresh_keeps_identity_after_monitor_order_changes(self):
        launcher = self.launcher()
        chosen = self.screens[1]
        launcher.monitor.setCurrentIndex(2)
        self.screens.reverse()
        launcher.refresh_monitors()
        self.assertIs(launcher.monitor.currentData(), chosen)
        self.screens.remove(chosen)
        launcher.refresh_monitors()
        self.assertIsNone(launcher.monitor.currentData())
        self.assertFalse(launcher.monitor_row.isVisible())


if __name__ == "__main__":
    unittest.main()

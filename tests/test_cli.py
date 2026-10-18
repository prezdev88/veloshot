"""CLI option combinations exercise real crops, PNG encoding, files, and pins."""

import io
import os
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

os.environ["QT_QPA_PLATFORM"] = "offscreen"

from PySide6.QtCore import QCoreApplication, QEvent, QPoint, QRect, QSettings, Qt
from PySide6.QtGui import QColor, QImage
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QApplication
from shiboken6 import isValid

from veloshot.__main__ import Controller, parse_args, parse_region
from veloshot.editor import PinnedImage


class RegionParsingTests(unittest.TestCase):
    def test_background_modes_parse_without_capture_options(self):
        self.assertEqual(parse_args(["tray"]).mode, "tray")
        self.assertEqual(parse_args(["no-gui"]).mode, "no-gui")

    def test_negative_desktop_origins_and_zero_are_valid(self):
        self.assertEqual(parse_region("640x480-1920+0"), QRect(-1920, 0, 640, 480))
        self.assertEqual(parse_region("1x1+0-100"), QRect(0, -100, 1, 1))
        self.assertEqual(parse_args(["gui", "--region", "640x480-1920+0"]).region,
                         "640x480-1920+0")

    def test_invalid_region_inputs_are_rejected(self):
        for value in ("", "640x480", "0x20+0+0", "20x0+0+0", "-1x20+0+0",
                      "20x30+1", "20x30++1+2", "20x30+1+2junk", " 20x30+1+2"):
            with self.subTest(value=value):
                with self.assertRaises(ValueError):
                    parse_region(value)

    def test_regions_that_overflow_qt_coordinates_raise_validation_error(self):
        for value in ("2147483648x30+0+0", "20x30-2147483649+0"):
            with self.subTest(value=value):
                with self.assertRaises(ValueError):
                    parse_region(value)

    def test_supported_gui_and_screen_combinations_parse(self):
        gui = parse_args(["gui", "--last-region", "--raw", "-g", "--pin", "-s", "-c"])
        self.assertTrue(all((gui.last_region, gui.raw, gui.print_geometry,
                             gui.pin, gui.accept_on_select, gui.clipboard)))
        screen = parse_args(["screen", "-e", "--region", "30x20-40-10", "--pin"])
        self.assertIsNone(screen.number)
        self.assertTrue(screen.edit)
        self.assertTrue(screen.pin)
        self.assertEqual(parse_args(["screen", "-n", "2"]).number, 2)

    def test_invalid_cli_region_exits_with_argparse_error(self):
        with patch("sys.stderr", new_callable=io.StringIO):
            with self.assertRaises(SystemExit) as error:
                parse_args(["gui", "--region", "0x20+0+0"])
        self.assertEqual(error.exception.code, 2)


class StartupModeTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])

    def test_tray_modes_do_not_open_launcher(self):
        for mode in ("tray", "no-gui"):
            with self.subTest(mode=mode):
                controller = Controller(self.app, parse_args([mode]))
                with patch.object(controller, "setup_tray") as setup_tray, \
                        patch.object(controller, "show_launcher") as show_launcher:
                    controller.start()
                setup_tray.assert_called_once_with()
                show_launcher.assert_not_called()


class AcceptSelectionTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])
        cls.app.setQuitOnLastWindowClosed(False)

    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        store_path = str(Path(self.temporary.name) / "settings.ini")
        settings_patch = patch("veloshot.settings.QSettings",
                               lambda *args: QSettings(store_path, QSettings.Format.IniFormat))
        settings_patch.start()
        self.addCleanup(settings_patch.stop)
        quit_patch = patch.object(self.app, "quit")
        self.quit_mock = quit_patch.start()
        self.addCleanup(quit_patch.stop)
        tray_patch = patch.object(Controller, "setup_tray")
        tray_patch.start()
        self.addCleanup(tray_patch.stop)
        self.controller = None

    def settle(self):
        self.app.processEvents()
        QCoreApplication.sendPostedEvents(None, QEvent.Type.DeferredDelete)
        self.app.processEvents()

    def tearDown(self):
        if self.controller:
            for window in list(self.controller.windows):
                if isValid(window):
                    window.close()
            self.settle()
            if self.controller.clipboard_owner:
                self.app.clipboard().dataChanged.disconnect(self.controller.clipboard_changed)
        self.app.clipboard().clear()
        self.settle()

    def editor(self, options):
        self.controller = Controller(self.app, parse_args(["gui", *options]))
        image = QImage(500, 400, QImage.Format.Format_ARGB32)
        image.fill(QColor("blue"))
        image.setPixelColor(30, 40, QColor("red"))
        editor = self.controller.create_editor(image, QRect(-300, -100, 500, 400))
        editor.document.selection = QRect(30, 40, 80, 60)
        editor.selection_changed()
        self.app.processEvents()
        return editor

    def capture_stdout(self, operation):
        stream = io.TextIOWrapper(io.BytesIO(), encoding="utf-8")
        with patch("sys.stdout", stream):
            operation()
            stream.flush()
            return stream.buffer.getvalue()

    def assert_selected_image(self, image):
        self.assertFalse(image.isNull())
        self.assertEqual(image.size(), QRect(0, 0, 80, 60).size())
        self.assertEqual(image.pixelColor(0, 0), QColor("red"))
        self.assertEqual(image.pixelColor(79, 59), QColor("blue"))

    def test_raw_file_clipboard_and_pin_receive_identical_real_crop(self):
        path = str(Path(self.temporary.name) / "result.png")
        editor = self.editor(["--raw", "--path", path, "--clipboard", "--pin"])
        stdout = self.capture_stdout(lambda: self.controller.accept_selection(editor))
        self.assertTrue(stdout.startswith(b"\x89PNG\r\n\x1a\n"))
        encoded = QImage.fromData(stdout, "PNG")
        self.assert_selected_image(encoded)
        self.assertEqual(QImage(path), encoded)
        self.assertEqual(self.app.clipboard().image(), encoded)
        pins = [window for window in self.controller.windows if isinstance(window, PinnedImage)]
        self.assertEqual(len(pins), 1)
        self.assertEqual(pins[0].image, encoded)
        self.assertTrue(self.controller.clipboard_owner)
        self.settle()
        self.assertFalse(isValid(editor))
        self.assertTrue(pins[0].isVisible())

    def test_geometry_and_file_output_use_desktop_coordinates(self):
        path = str(Path(self.temporary.name) / "geometry.png")
        editor = self.editor(["--print-geometry", "--path", path])
        stdout = self.capture_stdout(lambda: self.controller.accept_selection(editor))
        self.assertEqual(stdout.decode(), "80x60-270-60\n")
        self.assert_selected_image(QImage(path))
        self.assertEqual(self.controller.settings.get("last_region", ""), "80x60-270-60")
        self.assertFalse(self.controller.clipboard_owner)

    def test_copy_on_save_setting_retains_clipboard_after_accepting_path(self):
        path = str(Path(self.temporary.name) / "copy-on-save.png")
        editor = self.editor(["--path", path])
        self.controller.settings.set("copy_save", True)
        self.controller.accept_selection(editor)
        self.assert_selected_image(self.app.clipboard().image())
        self.assertEqual(QImage(path), self.app.clipboard().image())
        self.assertTrue(self.controller.clipboard_owner)
        self.settle()
        self.quit_mock.reset_mock()
        self.controller.maybe_quit()
        self.quit_mock.assert_not_called()

    def test_raw_only_does_not_copy_and_emits_exactly_one_png(self):
        editor = self.editor(["--raw"])
        self.app.clipboard().clear()
        stdout = self.capture_stdout(lambda: self.controller.accept_selection(editor))
        self.assert_selected_image(QImage.fromData(stdout, "PNG"))
        self.assertTrue(stdout.endswith(b"IEND\xaeB`\x82"))
        self.assertTrue(self.app.clipboard().image().isNull())
        self.assertFalse(self.controller.clipboard_owner)

    def test_accept_on_select_exports_without_a_second_confirmation(self):
        editor = self.editor(["--raw", "--accept-on-select"])
        editor.document.selection = QRect()
        editor.selection_changed()
        def select():
            QTest.mousePress(editor, Qt.MouseButton.LeftButton, pos=QPoint(30, 40))
            QTest.mouseMove(editor, QPoint(109, 99))
            QTest.mouseRelease(editor, Qt.MouseButton.LeftButton, pos=QPoint(109, 99))
        stdout = self.capture_stdout(select)
        self.assert_selected_image(QImage.fromData(stdout, "PNG"))
        self.assertFalse(editor.isVisible())


if __name__ == "__main__":
    unittest.main()

"""Exercise actual Qt widgets and image files with an isolated settings store."""

import os
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

os.environ["QT_QPA_PLATFORM"] = "offscreen"

from PySide6.QtCore import QCoreApplication, QEvent, QPoint, QRect, QSettings, Qt
from PySide6.QtGui import QColor, QImage, QPixmap
from PySide6.QtTest import QSignalSpy, QTest
from PySide6.QtWidgets import QApplication
from shiboken6 import isValid

from veloshot.__main__ import Controller, acquire_screen, parse_args
from veloshot.editor import CaptureEditor, PinnedImage, save_image
from veloshot.settings import Settings, SettingsDialog


def canvas(width=800, height=600, color="white"):
    image = QImage(width, height, QImage.Format.Format_ARGB32)
    image.fill(QColor(color))
    return image


class EditorTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.application = QApplication.instance() or QApplication([])
        cls.application.setQuitOnLastWindowClosed(False)

    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.settings_path = str(Path(self.temporary.name) / "settings.ini")
        self.settings_patch = patch("veloshot.settings.QSettings", self.settings_store)
        self.settings_patch.start()
        self.addCleanup(self.settings_patch.stop)
        self.settings = Settings()
        self.windows = []
        self.app = self.application
        self.quit_patch = patch.object(self.app, "quit")
        self.quit_mock = self.quit_patch.start()
        self.addCleanup(self.quit_patch.stop)

    def settings_store(self, *args):
        return QSettings(self.settings_path, QSettings.Format.IniFormat)

    def settle(self):
        self.app.processEvents()
        QCoreApplication.sendPostedEvents(None, QEvent.Type.DeferredDelete)
        self.app.processEvents()

    def tearDown(self):
        for window in self.windows:
            if isValid(window):
                window.close()
        self.settle()
        self.app.clipboard().clear()
        self.settle()

    def editor(self, output=None):
        editor = CaptureEditor(canvas(), QRect(0, 0, 800, 600), self.settings, output)
        self.windows.append(editor)
        editor.show()
        editor.activateWindow()
        editor.setFocus()
        self.settle()
        return editor

    def drag(self, editor, start, end):
        QTest.mousePress(editor, Qt.MouseButton.LeftButton, pos=QPoint(*start))
        QTest.mouseMove(editor, QPoint(*end))
        QTest.mouseRelease(editor, Qt.MouseButton.LeftButton, pos=QPoint(*end))
        self.app.processEvents()

    def select(self, editor):
        self.drag(editor, (80, 80), (480, 380))

    def controller(self):
        controller = Controller(self.app, parse_args(["gui"]))
        return controller

    def test_reverse_drag_selects_exact_pixels_and_reveals_toolbar(self):
        editor = self.editor()
        self.assertFalse(editor.toolbar.isVisible())
        self.drag(editor, (480, 380), (80, 80))
        self.assertEqual(editor.document.selection, QRect(80, 80, 401, 301))
        self.assertTrue(editor.toolbar.isVisible())
        self.assertEqual(editor.result().size(), editor.document.selection.size())

    def test_keyboard_select_all_and_panel_toggle(self):
        editor = self.editor()
        QTest.keyClick(editor, Qt.Key.Key_A, Qt.KeyboardModifier.ControlModifier)
        self.assertEqual(editor.document.selection, editor.document.background.rect())
        QTest.keyClick(editor, Qt.Key.Key_Tab)
        self.assertTrue(editor.panel.isVisible())
        QTest.keyClick(editor, Qt.Key.Key_Tab)
        self.assertFalse(editor.panel.isVisible())

    def test_keyboard_tool_draw_and_undo_redo_change_visible_pixels(self):
        editor = self.editor()
        self.select(editor)
        editor.set_color("#ff0000")
        QTest.keyClick(editor, Qt.Key.Key_L)
        self.assertEqual(editor.tool, "line")
        self.drag(editor, (160, 180), (350, 180))
        self.assertEqual(editor.render_cache.pixelColor(250, 180), QColor("red"))
        QTest.keyClick(editor, Qt.Key.Key_Z, Qt.KeyboardModifier.ControlModifier)
        self.assertEqual(editor.render_cache.pixelColor(250, 180), QColor("white"))
        QTest.keyClick(editor, Qt.Key.Key_Z,
                       Qt.KeyboardModifier.ControlModifier | Qt.KeyboardModifier.ShiftModifier)
        self.assertEqual(editor.render_cache.pixelColor(250, 180), QColor("red"))

    def test_annotation_drag_clamps_to_selection(self):
        editor = self.editor()
        self.select(editor)
        editor.set_tool("line")
        self.drag(editor, (200, 180), (750, 550))
        endpoint = editor.document.annotations[-1].points[-1]
        self.assertEqual(endpoint.toPoint(), QPoint(480, 380))

    def test_resize_corner_and_move_selection_preserve_expected_bounds(self):
        editor = self.editor()
        self.select(editor)
        self.drag(editor, (480, 380), (520, 410))
        self.assertEqual(editor.document.selection, QRect(80, 80, 441, 331))
        editor.set_tool("move")
        self.drag(editor, (200, 180), (780, 580))
        self.assertEqual(editor.document.selection, QRect(359, 269, 441, 331))

    def test_keyboard_moves_and_resizes_selection(self):
        editor = self.editor()
        self.select(editor)
        QTest.keyClick(editor, Qt.Key.Key_Right)
        QTest.keyClick(editor, Qt.Key.Key_Down)
        self.assertEqual(editor.document.selection, QRect(81, 81, 401, 301))
        QTest.keyClick(editor, Qt.Key.Key_Right, Qt.KeyboardModifier.ShiftModifier)
        self.assertEqual(editor.document.selection, QRect(81, 81, 402, 301))

    def test_resize_crossing_opposite_corner_preserves_both_endpoints(self):
        editor = self.editor()
        self.select(editor)
        self.drag(editor, (80, 80), (560, 440))
        self.assertEqual(editor.document.selection, QRect(480, 380, 81, 61))

    def test_text_dialog_and_counter_click_commit_annotations(self):
        editor = self.editor()
        self.select(editor)
        QTest.keyClick(editor, Qt.Key.Key_T)
        with patch("veloshot.editor.QInputDialog.getMultiLineText", return_value=("Hello", True)):
            QTest.mouseClick(editor, Qt.MouseButton.LeftButton, pos=QPoint(180, 180))
        self.assertEqual(editor.document.annotations[-1].text, "Hello")
        QTest.keyClick(editor, Qt.Key.Key_N)
        QTest.mouseClick(editor, Qt.MouseButton.LeftButton, pos=QPoint(250, 180))
        QTest.mouseClick(editor, Qt.MouseButton.LeftButton, pos=QPoint(300, 180))
        self.assertEqual([a.text for a in editor.document.annotations if a.kind == "counter"], ["1", "2"])

    def test_save_shortcut_writes_real_cropped_png_and_closes_editor(self):
        path = str(Path(self.temporary.name) / "capture.png")
        editor = self.editor(output=path)
        self.select(editor)
        editor.set_tool("rectangle")
        editor.filled = True
        editor.set_color("#ff0000")
        self.drag(editor, (180, 180), (260, 260))
        completed = QSignalSpy(editor.completed)
        with patch("veloshot.editor.QFileDialog.getSaveFileName", side_effect=AssertionError("Unexpected dialog")):
            QTest.keyClick(editor, Qt.Key.Key_S, Qt.KeyboardModifier.ControlModifier)
        saved = QImage(path)
        self.assertFalse(saved.isNull())
        self.assertEqual(saved.size(), QRect(0, 0, 401, 301).size())
        self.assertEqual(saved.pixelColor(120, 120), QColor("red"))
        self.assertEqual(completed.count(), 1)
        self.assertEqual(completed.at(0)[1], "save")
        self.assertFalse(editor.isVisible())
        self.assertEqual(self.settings.get("directory", ""), self.temporary.name)

    def test_copy_shortcut_populates_image_clipboard_with_selection(self):
        editor = self.editor()
        self.select(editor)
        completed = QSignalSpy(editor.completed)
        QTest.keyClick(editor, Qt.Key.Key_C, Qt.KeyboardModifier.ControlModifier)
        clipboard = self.app.clipboard().image()
        self.assertEqual(clipboard.size(), QRect(0, 0, 401, 301).size())
        self.assertEqual(clipboard.pixelColor(0, 0), QColor("white"))
        self.assertEqual(completed.at(0)[1], "copy")
        self.assertFalse(editor.isVisible())

    def test_empty_selection_copy_and_save_keep_editor_open(self):
        editor = self.editor(output=str(Path(self.temporary.name) / "empty.png"))
        completed = QSignalSpy(editor.completed)
        editor.copy()
        editor.save()
        self.assertEqual(completed.count(), 0)
        self.assertTrue(editor.isVisible())
        self.assertFalse((Path(self.temporary.name) / "empty.png").exists())

    def test_save_to_directory_uses_pattern_and_optional_clipboard(self):
        self.settings.set("pattern", "capture-test")
        self.settings.set("copy_save", True)
        image = canvas(40, 30, "blue")
        path = save_image(None, image, self.settings, self.temporary.name)
        self.assertEqual(path, str(Path(self.temporary.name) / "capture-test.png"))
        self.assertEqual(QImage(path), image)
        self.assertEqual(self.app.clipboard().image(), image)

    def test_cancelled_save_does_not_emit_completion(self):
        editor = self.editor()
        self.select(editor)
        completed = QSignalSpy(editor.completed)
        with patch("veloshot.editor.QFileDialog.getSaveFileName", return_value=("", "")):
            editor.save()
        self.assertEqual(completed.count(), 0)
        self.assertTrue(editor.isVisible())

    def test_failed_save_warns_and_keeps_editor_available(self):
        path = str(Path(self.temporary.name) / "missing-directory" / "capture.png")
        editor = self.editor(output=path)
        self.select(editor)
        completed = QSignalSpy(editor.completed)
        with patch("veloshot.editor.QMessageBox.warning") as warning:
            editor.save()
        warning.assert_called_once()
        self.assertEqual(completed.count(), 0)
        self.assertTrue(editor.isVisible())
        self.assertFalse(Path(path).exists())

    def test_pin_survives_editor_deletion_and_rotation_preserves_pixels(self):
        controller = self.controller()
        image = canvas(80, 40, "blue")
        image.setPixelColor(0, 0, QColor("red"))
        editor = controller.create_editor(image, QRect(0, 0, 80, 40))
        self.windows.append(editor)
        editor.select_all()
        editor.pin()
        pins = [window for window in controller.windows if isinstance(window, PinnedImage)]
        self.assertEqual(len(pins), 1)
        pin = pins[0]
        self.windows.append(pin)
        self.settle()
        self.assertFalse(isValid(editor))
        self.assertNotIn(editor, controller.windows)
        self.assertTrue(pin.isVisible())
        pin.rotate(90)
        self.assertEqual(pin.image.width(), 40)
        self.assertEqual(pin.image.height(), 80)
        self.assertEqual(pin.image.pixelColor(39, 0), QColor("red"))
        self.assertEqual(pin.size(), pin.image.size())
        QTest.keyClick(pin, Qt.Key.Key_Escape)
        self.settle()
        self.assertFalse(isValid(pin))
        self.assertEqual(controller.windows, [])

    def test_copy_completion_keeps_controller_alive_after_editor_deletion(self):
        controller = self.controller()
        with patch.object(controller, "setup_tray"):
            editor = controller.create_editor(canvas(80, 40), QRect(0, 0, 80, 40))
            self.windows.append(editor)
            editor.select_all()
            editor.copy()
        self.settle()
        self.assertTrue(controller.clipboard_owner)
        self.assertEqual(controller.windows, [])
        self.quit_mock.reset_mock()
        controller.maybe_quit()
        self.quit_mock.assert_not_called()
        with patch.object(self.app.clipboard(), "ownsClipboard", return_value=False):
            controller.clipboard_changed()
        self.assertFalse(controller.clipboard_owner)
        self.quit_mock.assert_called_once()

    def test_settings_dialog_saves_and_reloads_typed_values_in_temporary_file(self):
        dialog = SettingsDialog(self.settings)
        self.windows.append(dialog)
        dialog.directory.setText(self.temporary.name)
        dialog.pattern.setText("shot-%Y")
        dialog.delay.setValue(5)
        dialog.width.setValue(17)
        dialog.help.setChecked(False)
        dialog.copy_save.setChecked(True)
        dialog.color = "#00ccff"
        dialog.save()
        self.settings.store.sync()
        reloaded = Settings()
        self.assertEqual(reloaded.get("directory", ""), self.temporary.name)
        self.assertEqual(reloaded.get("pattern", ""), "shot-%Y")
        self.assertEqual(reloaded.get("delay", 0), 5)
        self.assertEqual(reloaded.get("width", 3), 17)
        self.assertFalse(reloaded.get("help", True))
        self.assertTrue(reloaded.get("copy_save", False))
        self.assertEqual(reloaded.get("color", ""), "#00ccff")
        self.assertEqual(Path(reloaded.store.fileName()), Path(self.settings_path))

    def test_cancel_settings_discards_unsaved_controls(self):
        self.settings.set("width", 7)
        dialog = SettingsDialog(self.settings)
        self.windows.append(dialog)
        dialog.width.setValue(25)
        dialog.reject()
        self.assertEqual(Settings().get("width", 3), 7)

    def test_acquire_screen_composes_negative_origin_monitors(self):
        screens = [SimpleNamespace(geometry=lambda: QRect(-20, 0, 20, 30),
                                   grabWindow=lambda _: QPixmap.fromImage(canvas(20, 30, "red"))),
                   SimpleNamespace(geometry=lambda: QRect(0, 0, 40, 30),
                                   grabWindow=lambda _: QPixmap.fromImage(canvas(40, 30, "blue")))]
        app = SimpleNamespace(screens=lambda: screens)
        image, geometry = acquire_screen(app)
        self.assertEqual(geometry, QRect(-20, 0, 60, 30))
        self.assertEqual(image.pixelColor(0, 0), QColor("red"))
        self.assertEqual(image.pixelColor(20, 0), QColor("blue"))
        self.assertEqual(image.pixelColor(59, 29), QColor("blue"))
        monitor, geometry = acquire_screen(app, 1)
        self.assertEqual(geometry, QRect(0, 0, 40, 30))
        self.assertEqual(monitor, canvas(40, 30, "blue"))
        with self.assertRaises(ValueError):
            acquire_screen(app, 2)


if __name__ == "__main__":
    unittest.main()

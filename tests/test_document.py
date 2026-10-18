"""Observable document and raster export behavior, without a display server."""

import os
import unittest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtCore import QPointF, QRect, QSize
from PySide6.QtGui import QColor, QImage
from PySide6.QtWidgets import QApplication

from veloshot.document import Annotation, Document


def canvas(width=100, height=80, color="white"):
    image = QImage(width, height, QImage.Format.Format_ARGB32)
    image.fill(QColor(color))
    return image


def shape(kind, start=(20, 20), end=(60, 50), **kwargs):
    return Annotation(kind, [QPointF(*start), QPointF(*end)], **kwargs)


def changed_pixels(image, reference):
    return [(x, y) for y in range(image.height()) for x in range(image.width())
            if image.pixel(x, y) != reference.pixel(x, y)]


class DocumentTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.application = QApplication.instance() or QApplication([])

    def test_export_clips_selection_to_background_and_preserves_pixels(self):
        background = canvas()
        for y in range(background.height()):
            for x in range(background.width()):
                background.setPixelColor(x, y, QColor(x, y, 37))
        document = Document(background, QRect(-5, 65, 30, 40))

        exported = document.export()

        self.assertEqual(exported.size(), QRect(0, 0, 25, 15).size())
        self.assertEqual(exported.pixelColor(0, 0), background.pixelColor(0, 65))
        self.assertEqual(exported.pixelColor(24, 14), background.pixelColor(24, 79))

    def test_hidpi_export_keeps_physical_resolution_and_ratio(self):
        background = QImage(200, 160, QImage.Format.Format_ARGB32)
        background.setDevicePixelRatio(2)
        background.fill(QColor("white"))
        background.setPixelColor(20, 30, QColor("red"))
        background.setPixelColor(59, 49, QColor("blue"))
        document = Document(background, QRect(10, 15, 20, 10))

        exported = document.export()

        self.assertEqual(document.bounds, QRect(0, 0, 100, 80))
        self.assertEqual(exported.size(), QSize(40, 20))
        self.assertEqual(exported.devicePixelRatio(), 2)
        self.assertEqual(exported.pixelColor(0, 0), background.pixelColor(20, 30))
        self.assertEqual(exported.pixelColor(39, 19), background.pixelColor(59, 49))

    def test_hidpi_annotations_render_at_physical_resolution(self):
        background = QImage(200, 160, QImage.Format.Format_ARGB32)
        background.setDevicePixelRatio(2)
        background.fill(QColor("white"))
        document = Document(background)
        document.commit(shape("filled_rectangle", (10, 10), (30, 30), color="#ff0000"))

        rendered = document.render()

        self.assertEqual(rendered.size(), QSize(200, 160))
        self.assertEqual(rendered.devicePixelRatio(), 2)
        self.assertEqual(rendered.pixelColor(40, 40), QColor("red"))
        self.assertEqual(rendered.pixelColor(10, 10), QColor("white"))

    def test_fractional_scale_crop_uses_consistent_pixel_boundaries(self):
        background = QImage(125, 100, QImage.Format.Format_ARGB32)
        background.setDevicePixelRatio(1.25)
        background.fill(QColor("white"))

        first = Document(background, QRect(0, 0, 1, 10)).export()
        second = Document(background, QRect(1, 0, 1, 10)).export()

        self.assertEqual(first.size(), QSize(1, 13))
        self.assertEqual(second.size(), QSize(2, 13))
        self.assertEqual(first.width() + second.width(), 3)

    def test_export_rejects_empty_or_completely_outside_selection(self):
        for selection in (QRect(), QRect(10, 10, 0, 5), QRect(120, 0, 10, 10)):
            with self.subTest(selection=selection):
                with self.assertRaises(ValueError):
                    Document(canvas(), selection).export()

    def test_export_contains_annotations_at_crop_relative_coordinates(self):
        document = Document(canvas(), QRect(30, 20, 20, 20))
        document.commit(shape("rectangle", (35, 25), (45, 35),
                              color="#ff0000", filled=True))

        exported = document.export()

        self.assertEqual(exported.pixelColor(10, 10), QColor("red"))
        self.assertEqual(exported.pixelColor(0, 0), QColor("white"))
        self.assertEqual(document.background.pixelColor(40, 30), QColor("white"))

    def test_preview_is_rendered_without_changing_history_or_background(self):
        background = canvas()
        original = background.copy()
        document = Document(background)
        preview = shape("line", (10, 25), (80, 25), color="#ff0000")

        rendered = document.render(preview)

        self.assertEqual(rendered.pixelColor(40, 25), QColor("red"))
        self.assertEqual(background, original)
        self.assertEqual(document.render(), original)
        self.assertEqual(document.annotations, [])
        self.assertEqual(document.future, [])

    def test_undo_redo_restore_visible_annotations_in_order(self):
        document = Document(canvas())
        red = shape("rectangle", (10, 10), (60, 60), color="#ff0000", filled=True)
        blue = shape("rectangle", (20, 20), (50, 50), color="#0000ff", filled=True)
        document.commit(red)
        document.commit(blue)
        self.assertEqual(document.render().pixelColor(30, 30), QColor("blue"))

        document.undo()
        self.assertEqual(document.render().pixelColor(30, 30), QColor("red"))
        document.undo()
        document.undo()  # Empty history is harmless.
        self.assertEqual(document.render().pixelColor(30, 30), QColor("white"))
        document.redo()
        self.assertEqual(document.render().pixelColor(30, 30), QColor("red"))
        document.redo()
        document.redo()
        self.assertEqual(document.render().pixelColor(30, 30), QColor("blue"))

    def test_new_annotation_after_undo_discards_redo_branch(self):
        document = Document(canvas())
        document.commit(shape("line", (10, 10), (70, 10), color="#ff0000"))
        document.undo()
        replacement = shape("line", (10, 40), (70, 40), color="#0000ff")
        document.commit(replacement)
        document.redo()

        self.assertEqual(document.future, [])
        self.assertEqual(document.annotations, [replacement])
        rendered = document.render()
        self.assertEqual(rendered.pixelColor(40, 10), QColor("white"))
        self.assertEqual(rendered.pixelColor(40, 40), QColor("blue"))

    def test_invert_uses_composited_image_and_changes_only_its_region(self):
        document = Document(canvas(color="#123456"))
        document.commit(shape("rectangle", (10, 10), (60, 60),
                              color="#ff0000", filled=True))
        document.commit(shape("invert", (20, 20), (40, 40)))

        rendered = document.render()

        self.assertEqual(rendered.pixelColor(30, 30), QColor("cyan"))
        self.assertEqual(rendered.pixelColor(50, 30), QColor("red"))
        self.assertEqual(rendered.pixelColor(5, 5), QColor("#123456"))

    def test_invert_clips_at_image_boundary_and_preserves_alpha(self):
        document = Document(canvas(color=QColor(10, 40, 70, 100)))
        document.commit(shape("invert", (-10, -10), (15, 15)))

        rendered = document.render()

        self.assertEqual(rendered.pixelColor(0, 0), QColor(245, 215, 185, 100))
        self.assertEqual(rendered.pixelColor(15, 15), QColor(10, 40, 70, 100))

    def test_pixelate_creates_flat_blocks_without_affecting_surroundings(self):
        background = canvas(48, 48)
        for y in range(48):
            for x in range(48):
                background.setPixelColor(x, y, QColor(x * 5, y * 5, (x + y) * 2))
        document = Document(background)
        document.commit(shape("pixelate", (12, 12), (36, 36), width=2))

        rendered = document.render()

        self.assertNotEqual(rendered, background)
        for y in range(48):
            for x in range(48):
                if not (12 <= x < 36 and 12 <= y < 36):
                    self.assertEqual(rendered.pixel(x, y), background.pixel(x, y))
        self.assertEqual(rendered.pixelColor(13, 13), rendered.pixelColor(16, 16))
        self.assertNotEqual(rendered.pixelColor(13, 13), rendered.pixelColor(31, 31))

    def test_pixelate_preserves_uniform_translucent_pixels(self):
        document = Document(canvas(color=QColor(20, 40, 60, 100)))
        document.commit(shape("pixelate", (10, 10), (40, 40), width=2))
        rendered = document.render()
        pixel = rendered.pixelColor(20, 20)
        self.assertEqual(pixel.alpha(), 100)
        # Resampling premultiplied colors can round an RGB channel by one.
        for actual, expected in zip(pixel.getRgb()[:3], (20, 40, 60)):
            self.assertLessEqual(abs(actual - expected), 1)
        self.assertEqual(rendered.pixelColor(5, 5), QColor(20, 40, 60, 100))

    def test_effect_outside_image_is_a_noop(self):
        for kind in ("pixelate", "invert"):
            with self.subTest(kind=kind):
                document = Document(canvas())
                document.commit(shape(kind, (-30, -30), (-5, -5)))
                self.assertEqual(document.render(), document.background)

    def test_rectangle_normalizes_reverse_drag_and_respects_fill(self):
        for filled in (False, True):
            with self.subTest(filled=filled):
                document = Document(canvas())
                document.commit(shape("rectangle", (60, 50), (20, 20),
                                      color="#ff0000", filled=filled))
                rendered = document.render()
                self.assertEqual(rendered.pixelColor(20, 35), QColor("red"))
                self.assertEqual(rendered.pixelColor(40, 35),
                                 QColor("red" if filled else "white"))
                self.assertEqual(rendered.pixelColor(5, 5), QColor("white"))

    def test_circle_has_curved_outline_and_filled_center(self):
        document = Document(canvas())
        document.commit(shape("circle", (20, 20), (60, 60),
                              color="#0000ff", filled=True))
        rendered = document.render()
        self.assertEqual(rendered.pixelColor(40, 40), QColor("blue"))
        self.assertEqual(rendered.pixelColor(20, 20), QColor("white"))
        self.assertEqual(rendered.pixelColor(40, 20), QColor("blue"))

    def test_arrow_draws_shaft_and_visible_head_on_both_sides(self):
        document = Document(canvas())
        document.commit(shape("arrow", (15, 40), (80, 40), color="#ff0000", width=3))
        rendered = document.render()
        self.assertEqual(rendered.pixelColor(40, 40), QColor("red"))
        self.assertEqual(rendered.pixelColor(71, 37), QColor("red"))
        self.assertEqual(rendered.pixelColor(71, 43), QColor("red"))
        self.assertEqual(rendered.pixelColor(40, 32), QColor("white"))

    def test_marker_is_broad_translucent_highlight(self):
        document = Document(canvas())
        document.commit(shape("marker", (15, 40), (80, 40), color="#ff0000", width=3))
        rendered = document.render()
        center = rendered.pixelColor(40, 40)
        self.assertEqual(center.red(), 255)
        self.assertTrue(160 <= center.green() <= 180)
        self.assertEqual(center.green(), center.blue())
        self.assertEqual(rendered.pixelColor(40, 35), center)
        self.assertEqual(rendered.pixelColor(40, 28), QColor("white"))

    def test_text_produces_ink_near_anchor(self):
        background = canvas()
        document = Document(background)
        document.commit(shape("text", (20, 20), (20, 20), text="Test", color="#000000"))
        rendered = document.render()
        ink = changed_pixels(rendered, background)
        self.assertGreater(len(ink), 20)
        # Glyph bearings and antialiasing may extend one pixel left of the
        # layout rectangle depending on the platform's Sans Serif font.
        self.assertTrue(all(x >= 19 and y >= 20 for x, y in ink))
        self.assertTrue(all(x < 70 and y < 50 for x, y in ink))

    def test_counter_draws_colored_badge_and_white_number(self):
        document = Document(canvas(color="black"))
        document.commit(shape("counter", (40, 40), (40, 40),
                              color="#ff0000", text="1", width=3))
        rendered = document.render()
        self.assertEqual(rendered.pixelColor(30, 40), QColor("red"))
        self.assertEqual(rendered.pixelColor(20, 40), QColor("black"))
        white_pixels = sum(rendered.pixelColor(x, y) == QColor("white")
                           for y in range(30, 50) for x in range(30, 50))
        self.assertGreater(white_pixels, 2)

    def test_single_point_pencil_leaves_a_visible_dot(self):
        document = Document(canvas())
        document.commit(Annotation("pencil", [QPointF(35, 35)], color="#ff0000", width=5))
        rendered = document.render()
        self.assertEqual(rendered.pixelColor(35, 35), QColor("red"))
        self.assertEqual(rendered.pixelColor(30, 30), QColor("white"))


if __name__ == "__main__":
    unittest.main()

import tempfile
import unittest
from pathlib import Path

from PIL import Image, ImageDraw

from video2agent.visual import text_coverage_for


class CoverageScaleTest(unittest.TestCase):
    def _frame(self, width, height):
        path = Path(tempfile.mkdtemp(prefix="vp-coverage-")) / "f.jpg"
        im = Image.new("RGB", (width, height), "white")
        ImageDraw.Draw(im).rectangle([0, 0, width, int(height * 0.1)], fill="black")
        im.save(path, "JPEG")
        return path

    def test_boxes_are_compared_in_thumbnail_space(self):
        path = self._frame(1280, 720)
        scale = 1024.0 / 1280
        box_w, box_h = 1280 * scale, 720 * 0.1 * scale
        boxes = [{"bbox": [0, 0, box_w, box_h]}]
        coverage = text_coverage_for(path, boxes)
        self.assertAlmostEqual(coverage, 0.1, delta=0.02)

    def test_empty_boxes_stay_zero(self):
        self.assertEqual(text_coverage_for(self._frame(1280, 720), []), 0.0)

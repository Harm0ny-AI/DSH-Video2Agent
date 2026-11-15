import tempfile
import unittest
from pathlib import Path

from PIL import Image

from video2agent.pipeline import _crop_image


class CropTests(unittest.TestCase):
    def test_crop_uses_normalized_box_and_scale(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "frame.jpg"
            Image.new("RGB", (100, 80), (10, 20, 30)).save(path)
            out, meta = _crop_image(path, (0.0, 0.0, 0.5, 0.5), 2.0)
            with Image.open(out) as im:
                self.assertEqual(im.size, (100, 80))
            self.assertEqual(meta["box_px"], [0, 0, 50, 40])
            self.assertEqual(meta["scale"], 2.0)

    def test_no_crop_is_a_noop(self):
        path = Path(tempfile.gettempdir()) / "does-not-matter.jpg"
        self.assertEqual(_crop_image(path, None, 1.0), (path, None))

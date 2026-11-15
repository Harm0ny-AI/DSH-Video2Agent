"""Cloud OCR guard: a picture description is not OCR text."""

import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from PIL import Image

from video2agent import pipeline
from video2agent.util import Video2AgentError


def _image(root: Path) -> Path:
    path = root / "frame.jpg"
    Image.new("RGB", (320, 180), (30, 40, 50)).save(path)
    return path


class CloudOcrGuardTests(unittest.TestCase):
    def test_a_picture_description_is_rejected(self):
        description = ("In the image, there is a man on the right side, wearing a black t-shirt "
                       "with a white logo on the left chest area, and a young male with curly hair.")
        self.assertTrue(pipeline._looks_like_cloud_description(description))
        self.assertTrue(pipeline._looks_like_cloud_description(
            "图片中有一名男子站在右侧，穿黑色上衣，胸前有白色标志，画面里还有一名卷发年轻球员。"))
        self.assertFalse(pipeline._looks_like_cloud_description("WALL STREET JOURNAL"))

    def test_description_raises_instead_of_becoming_ocr_text(self):
        with tempfile.TemporaryDirectory() as tmp:
            frame = _image(Path(tmp))
            description = ("In the image, there is a man on the right side, wearing a black t-shirt "
                           "with a white logo on the left chest area, and a young male with curly hair.")
            with patch("video2agent.cloud.ocr", return_value={"text": description}):
                with self.assertRaises(Video2AgentError) as ctx:
                    pipeline._cloud_ocr_boxes(None, frame)
            self.assertEqual(ctx.exception.code, "E_CLOUD_OCR_DESCRIPTION")
            self.assertTrue(ctx.exception.remedy)

    def test_real_page_text_returns_one_box(self):
        with tempfile.TemporaryDirectory() as tmp:
            frame = _image(Path(tmp))
            text = "THE WALL STREET JOURNAL\nThursday, December 20, 2012"
            with patch("video2agent.cloud.ocr", return_value={"text": text}):
                boxes = pipeline._cloud_ocr_boxes(None, frame)
            self.assertEqual(len(boxes), 1)
            self.assertTrue(boxes[0]["cloud"])
            self.assertIn("WALL STREET JOURNAL", boxes[0]["text"])


if __name__ == "__main__":
    unittest.main()

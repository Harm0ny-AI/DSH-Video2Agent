"""Pure-cloud two-stage OCR: grounding boxes then per-crop cloud reads."""

import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from PIL import Image

from video2agent import pipeline
from video2agent.config import load_config


class CloudGuidedOcrTests(unittest.TestCase):
    def test_grounding_boxes_drive_crops_without_local_ocr(self):
        with tempfile.TemporaryDirectory() as tmp:
            cfg = load_config(Path(tmp))
            image = Path(tmp) / "frame.jpg"
            Image.new("RGB", (1280, 720), "white").save(image)
            grounding = (
                "<|ref|>TOSHIBA<|/ref|><|det|>[[100,100,300,140]]<|/det|>\n"
                "<|ref|>9:24<|/ref|><|det|>[[600,700,700,760]]<|/det|>"
            )
            calls = []

            def fake_ocr(_cfg, path, prompt="Free OCR."):
                calls.append(prompt)
                if "grounding" in prompt:
                    return {"text": grounding}
                return {"text": "TOSHIBA" if len(calls) == 2 else "9:24"}

            with patch.object(pipeline.cloud, "ocr", side_effect=fake_ocr), \
                    patch.object(pipeline, "_local_ocr_boxes", side_effect=AssertionError("no local OCR")):
                boxes = pipeline._cloud_ocr_boxes(cfg, image, tiles=True)
        self.assertEqual(len(calls), 3, "one grounding call + two crop reads")
        self.assertEqual(boxes[0]["text"], "TOSHIBA\n9:24")
        self.assertTrue(boxes[0]["guided"])
        self.assertEqual(boxes[0]["boxes"], 2)

    def test_no_boxes_falls_back_to_full_frame(self):
        with tempfile.TemporaryDirectory() as tmp:
            cfg = load_config(Path(tmp))
            image = Path(tmp) / "frame.jpg"
            Image.new("RGB", (320, 180), "white").save(image)
            calls = []

            def fake_ocr(_cfg, path, prompt="Free OCR."):
                calls.append(prompt)
                return {"text": "" if "grounding" in prompt else "FULL FRAME"}

            with patch.object(pipeline.cloud, "ocr", side_effect=fake_ocr):
                boxes = pipeline._cloud_ocr_boxes(cfg, image, tiles=True)
        self.assertEqual(len(calls), 2)
        self.assertEqual(boxes[0]["text"], "FULL FRAME")

    def test_a_hallucinated_crop_falls_back_to_the_located_label(self):
        with tempfile.TemporaryDirectory() as tmp:
            cfg = load_config(Path(tmp))
            image = Path(tmp) / "frame.jpg"
            Image.new("RGB", (640, 360), "white").save(image)
            grounding = "<|ref|>TOSHIBA<|/ref|><|det|>[[100,100,300,140]]<|/det|>"
            calls = []

            def fake_ocr(_cfg, path, prompt="Free OCR."):
                calls.append(prompt)
                if "grounding" in prompt:
                    return {"text": grounding}
                return {"text": "The image shows a paper screenshot of a table."}

            with patch.object(pipeline.cloud, "ocr", side_effect=fake_ocr):
                boxes = pipeline._cloud_ocr_boxes(cfg, image, tiles=True)
        self.assertEqual(boxes[0]["text"], "TOSHIBA")

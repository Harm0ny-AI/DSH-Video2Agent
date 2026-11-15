"""ocr-window: text that changes inside a short window keeps every line and time."""

import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from PIL import Image

from video2agent import pipeline
from video2agent.config import load_config
from video2agent.db import Database

VID = "vid_ocr_window"


def fake_extract(_src, t, out, **_kwargs):
    # A different seed per moment: the frame-change check would otherwise skip
    # every frame after the first one.
    Image.new("RGB", (320, 180), (int(t) // 500 * 61 % 255, 40, 60)).save(out)


def static_extract(_src, _t, out, **_kwargs):
    Image.new("RGB", (320, 180), (20, 40, 60)).save(out)


class OcrWindowTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.cfg = load_config(Path(self.tmp.name))
        self.media = Path(self.tmp.name) / "media.mp4"
        self.media.write_bytes(b"stub")
        db = Database(self.cfg.db_path)
        try:
            db.upsert_video({
                "id": VID, "source_kind": "local", "source_uri": str(self.media),
                "source_path": str(self.media), "title": "ocr", "duration_ms": 120_000,
                "status": "ready", "analysis_version": "0.2",
            })
        finally:
            db.close()

    def test_a_changing_screen_keeps_both_lines_with_times(self):
        def fake_ocr(path, **_kwargs):
            # Derive the text from the extracted moment, not from call order:
            # OCR now runs on two worker threads.
            at = int(Path(path).stem.split("_")[-1])
            text = "Dude! You gotta come to BigStuf Camps!" if at < 61_000 else "BTW you got something in your teeth"
            return [{"text": text, "bbox": [0, 0, 1, 1]}]

        with patch.object(pipeline, "extract_frame", side_effect=fake_extract), \
                patch.object(pipeline, "ocr_image", side_effect=fake_ocr):
            data = pipeline.ocr_window(self.cfg, VID, start_ms=58_000, end_ms=62_000, fps=2, max_frames=5)
        self.assertTrue(data["ok"])
        self.assertEqual([line["text"] for line in data["lines"]],
                         ["Dude! You gotta come to BigStuf Camps!",
                          "BTW you got something in your teeth"])
        self.assertEqual(data["lines"][0]["timecode"], "00:00:58.000")
        self.assertEqual(data["lines"][1]["timecode"], "00:01:01.000")
        self.assertEqual(data["frames_scanned"], 5)

    def test_an_empty_window_says_so(self):
        with patch.object(pipeline, "extract_frame", side_effect=fake_extract), \
                patch.object(pipeline, "ocr_image", return_value=[]):
            data = pipeline.ocr_window(self.cfg, VID, start_ms=1_000, end_ms=2_000, fps=2)
        self.assertEqual(data["lines"], [])
        self.assertIn("OCR_EMPTY", [w["code"] for w in data["warnings"]])

    def test_an_unchanged_screen_is_read_once(self):
        # A banner held for two seconds must not pay one OCR pass per frame.
        with patch.object(pipeline, "extract_frame", side_effect=static_extract), \
                patch.object(pipeline, "ocr_image",
                             return_value=[{"text": "same", "bbox": [0, 0, 1, 1]}]) as read:
            data = pipeline.ocr_window(self.cfg, VID, start_ms=1_000, end_ms=3_000, fps=2)
        self.assertEqual(read.call_count, 1)
        self.assertEqual(data["frames_scanned"], 1)
        self.assertGreaterEqual(data["frames_skipped"], 1)
        self.assertEqual([line["text"] for line in data["lines"]], ["same"])

    def test_a_long_window_is_flagged_as_sampled(self):
        with patch.object(pipeline, "extract_frame", side_effect=fake_extract), \
                patch.object(pipeline, "ocr_image", return_value=[{"text": "x", "bbox": [0, 0, 1, 1]}]):
            data = pipeline.ocr_window(self.cfg, VID, start_ms=0, end_ms=10_000, fps=2, max_frames=2)
        self.assertTrue(data["sampled"])
        self.assertGreater(data["frames_planned"], data["frames_scanned"])
        self.assertIn("OCR_WINDOW_SAMPLED", [w["code"] for w in data["warnings"]])

    def test_one_frame_cap_does_not_crash(self):
        with patch.object(pipeline, "extract_frame", side_effect=fake_extract), \
                patch.object(pipeline, "ocr_image", return_value=[{"text": "x", "bbox": [0, 0, 1, 1]}]):
            data = pipeline.ocr_window(self.cfg, VID, start_ms=0, end_ms=10_000, fps=2, max_frames=1)
        self.assertTrue(data["sampled"])
        self.assertLessEqual(data["frames_scanned"], 1)

    def test_temp_frames_are_removed(self):
        with patch.object(pipeline, "extract_frame", side_effect=fake_extract), \
                patch.object(pipeline, "ocr_image", return_value=[{"text": "x", "bbox": [0, 0, 1, 1]}]):
            pipeline.ocr_window(self.cfg, VID, start_ms=0, end_ms=2_000, fps=2)
        leftovers = list((self.cfg.derived_dir / VID / "frames").glob("ocrwin_*"))
        self.assertEqual(leftovers, [])

    def test_repeat_call_is_served_from_cache(self):
        with patch.object(pipeline, "extract_frame", side_effect=fake_extract) as extract, \
                patch.object(pipeline, "ocr_image", return_value=[{"text": "x", "bbox": [0, 0, 1, 1]}]):
            first = pipeline.ocr_window(self.cfg, VID, start_ms=1_000, end_ms=3_000, fps=2)
            calls_after_first = extract.call_count
            second = pipeline.ocr_window(self.cfg, VID, start_ms=1_000, end_ms=3_000, fps=2)
        self.assertFalse(first["cached"])
        self.assertTrue(second["cached"])
        self.assertEqual(extract.call_count, calls_after_first, "cache hit must not extract again")
        self.assertEqual(first["lines"], second["lines"])

    def test_a_different_range_is_not_cached(self):
        with patch.object(pipeline, "extract_frame", side_effect=fake_extract), \
                patch.object(pipeline, "ocr_image", return_value=[{"text": "x", "bbox": [0, 0, 1, 1]}]):
            pipeline.ocr_window(self.cfg, VID, start_ms=1_000, end_ms=3_000, fps=2)
            other = pipeline.ocr_window(self.cfg, VID, start_ms=5_000, end_ms=7_000, fps=2)
        self.assertFalse(other["cached"])

    def test_cache_misses_when_the_source_changes(self):
        with patch.object(pipeline, "extract_frame", side_effect=fake_extract), \
                patch.object(pipeline, "ocr_image", return_value=[{"text": "x", "bbox": [0, 0, 1, 1]}]):
            pipeline.ocr_window(self.cfg, VID, start_ms=1_000, end_ms=3_000, fps=2)
            future = self.media.stat().st_mtime + 5
            os.utime(self.media, (future, future))
            again = pipeline.ocr_window(self.cfg, VID, start_ms=1_000, end_ms=3_000, fps=2)
        self.assertFalse(again["cached"])

    def test_a_failed_read_is_not_cached(self):
        with patch.object(pipeline, "extract_frame", side_effect=fake_extract), \
                patch.object(pipeline, "ocr_image", side_effect=RuntimeError("boom")):
            first = pipeline.ocr_window(self.cfg, VID, start_ms=1_000, end_ms=3_000, fps=2)
            second = pipeline.ocr_window(self.cfg, VID, start_ms=1_000, end_ms=3_000, fps=2)
        self.assertGreater(first["frames_failed"], 0)
        self.assertFalse(second["cached"], "a failed OCR pass must not be cached")
        self.assertEqual(second["frames_failed"], first["frames_failed"])

if __name__ == "__main__":
    unittest.main()

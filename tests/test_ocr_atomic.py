import tempfile
import unittest
from pathlib import Path

from video2agent.config import Config
from video2agent.db import Database


def _video(vid="vid_atomic"):
    return {
        "id": vid, "source_kind": "url", "source_uri": "https://example.com/v",
        "source_path": "x", "sha256": "a" * 64, "title": "atomic", "duration_ms": 10_000,
        "width": None, "height": None, "fps": None, "language": None,
        "platform": "url", "status": "ready", "analysis_version": "1",
        "meta_json": "{}", "warnings_json": "[]",
        "created_at": "2026-01-01T00:00:00+00:00", "updated_at": "2026-01-01T00:00:00+00:00",
    }


class OcrAtomicTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.cfg = Config(Path(self.tmp.name))
        self.db = Database(self.cfg.db_path)
        self.db.upsert_video(_video())
        self.db.insert_frames("vid_atomic", [{
            "pts_ms": 1000, "path": "frame.jpg", "ocr_status": "pending",
        }])
        self.reads = [{
            "pts_ms": 1000, "ocr_status": "ok", "text_coverage": 0.5,
            "has_text": True,
            "tracks": [{"text": "hello", "start_ms": 1000, "end_ms": 1100,
                        "tokens": "hello", "confidence": 0.9}],
        }]

    def tearDown(self):
        self.db.close()
        self.tmp.cleanup()

    def test_frame_and_track_commit_together(self):
        self.assertEqual(self.db.apply_ocr_reads("vid_atomic", self.reads), 1)
        frame = self.db.get_frames("vid_atomic")[0]
        self.assertEqual(frame["ocr_status"], "ok")
        self.assertEqual(self.db.count_ocr_tracks("vid_atomic"), 1)

    def test_failure_rolls_back_the_frame_status(self):
        # Make the OCR serialization fail after the frame UPDATE but before commit.
        bad = [{**self.reads[0], "tracks": [{**self.reads[0]["tracks"][0], "bbox": {object()}}]}]
        with self.assertRaises(TypeError):
            self.db.apply_ocr_reads("vid_atomic", bad)
        self.assertEqual(self.db.get_frames("vid_atomic")[0]["ocr_status"], "pending")
        self.assertEqual(self.db.count_ocr_tracks("vid_atomic"), 0)


if __name__ == "__main__":
    unittest.main()

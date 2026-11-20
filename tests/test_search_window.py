import tempfile
import unittest
from pathlib import Path

from video2agent.config import Config
from video2agent.db import Database


def _video(vid="vid_window"):
    return {
        "id": vid, "source_kind": "url", "source_uri": "https://example.com/v",
        "source_path": "x", "sha256": "a" * 64, "title": "window", "duration_ms": 10_000,
        "width": None, "height": None, "fps": None, "language": None,
        "platform": "url", "status": "ready", "analysis_version": "1",
        "meta_json": "{}", "warnings_json": "[]",
        "created_at": "2026-01-01T00:00:00+00:00", "updated_at": "2026-01-01T00:00:00+00:00",
    }


class SearchWindowTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.cfg = Config(Path(self.tmp.name))
        self.db = Database(self.cfg.db_path)
        self.db.upsert_video(_video())
        self.db.insert_segments("vid_window", [
            {"start_ms": 0, "end_ms": 1000, "text": "alpha outside", "tokens": "alpha outside", "source": "asr", "confidence": 0.9},
            {"start_ms": 5000, "end_ms": 5500, "text": "alpha inside", "tokens": "alpha inside", "source": "asr", "confidence": 0.9},
        ])
        self.db.insert_ocr_tracks("vid_window", [
            {"text": "alpha outside", "start_ms": 0, "end_ms": 1000, "tokens": "alpha outside", "confidence": 0.9},
            {"text": "alpha inside", "start_ms": 5000, "end_ms": 5500, "tokens": "alpha inside", "confidence": 0.9},
        ])

    def tearDown(self):
        self.db.close()
        self.tmp.cleanup()

    def test_segment_window_is_applied_before_limit(self):
        rows = self.db.search_segments("alpha", limit=1, start_ms=5000, end_ms=6000)
        self.assertEqual(len(rows), 1)
        self.assertIn("inside", rows[0]["text"])

    def test_ocr_window_is_applied_before_limit(self):
        rows = self.db.search_ocr("alpha", limit=1, start_ms=5000, end_ms=6000)
        self.assertEqual(len(rows), 1)
        self.assertIn("inside", rows[0]["text"])


if __name__ == "__main__":
    unittest.main()

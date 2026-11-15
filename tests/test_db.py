import tempfile
import unittest
from pathlib import Path

from video2agent.db import Database
from video2agent.util import now_iso


class DatabaseTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.db = Database(Path(self.tmp.name) / "test.db")
        self.video = self.db.upsert_video({
            "id": "vid_test",
            "source_kind": "local",
            "source_uri": "demo.mp4",
            "title": "demo",
            "duration_ms": 6000,
            "status": "ready",
            "created_at": now_iso(),
        })

    def tearDown(self):
        self.db.close()
        self.tmp.cleanup()

    def test_video_roundtrip(self):
        got = self.db.get_video("vid_test")
        self.assertIsNotNone(got)
        self.assertEqual(got["title"], "demo")

    def test_search_transcript(self):
        self.db.insert_segments("vid_test", [
            {"start_ms": 0, "end_ms": 2000, "text": "注意力机制", "source": "caption",
             "tokens": "注意 意力 力机 机制"},
            {"start_ms": 2000, "end_ms": 4000, "text": "一张表格", "source": "caption",
             "tokens": "一张 张表 表格"},
        ])
        rows = self.db.search_segments('"表格"', "vid_test")
        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0]["text"], "一张表格")

    def test_visual_filter(self):
        self.db.insert_visual_segments("vid_test", [
            {"start_ms": 2000, "end_ms": 4000, "label": "table_like", "score": 0.8, "signals": {}},
        ])
        rows = self.db.get_visual_segments("vid_test", types=["table_like"])
        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0]["label"], "table_like")

    def test_clear(self):
        self.db.insert_segments("vid_test", [{"start_ms": 0, "end_ms": 1, "text": "x", "tokens": "x"}])
        self.db.clear_video_analysis("vid_test")
        self.assertEqual(self.db.counts("vid_test")["segments"], 0)


if __name__ == "__main__":
    unittest.main()

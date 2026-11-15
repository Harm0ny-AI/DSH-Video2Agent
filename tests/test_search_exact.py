import tempfile
import unittest
from pathlib import Path

from video2agent.config import load_config
from video2agent.db import Database
from video2agent.pipeline import search


class ExactSearchTests(unittest.TestCase):
    def test_numeric_segment_query_returns_exact_segment(self):
        with tempfile.TemporaryDirectory() as tmp:
            cfg = load_config(Path(tmp))
            db = Database(cfg.db_path)
            try:
                db.upsert_video({
                    "id": "vid_exact", "source_kind": "local", "source_uri": "x.mp4",
                    "source_path": "x.mp4", "title": "long", "duration_ms": 3_600_000,
                    "status": "ready",
                })
                segs = []
                for i in range(1, 121):
                    text = f"第{i}段:这是第{i}个知识点的讲解。"
                    segs.append({
                        "start_ms": (i - 1) * 30_000, "end_ms": (i - 1) * 30_000 + 28_000,
                        "text": text, "source": "caption", "confidence": 1.0,
                    })
                db.insert_segments("vid_exact", segs)
            finally:
                db.close()

            result = search(cfg, "第42段", video_id="vid_exact", limit=5)
            self.assertTrue(result["results"])
            self.assertEqual(result["results"][0]["start_ms"], 41 * 30_000)
            self.assertEqual(result["results"][0]["modalities"], ["transcript"])


if __name__ == "__main__":
    unittest.main()

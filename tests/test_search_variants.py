import tempfile
import unittest
from pathlib import Path

from video2agent.config import load_config
from video2agent.db import Database
from video2agent.pipeline import search_queries


class SearchVariantTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.cfg = load_config(Path(self.tmp.name))
        self.db = Database(self.cfg.db_path)
        self.db.upsert_video({"id": "vid_a", "source_kind": "local", "source_uri": "test://a",
                              "title": "A", "duration_ms": 2000, "status": "ready"})
        self.db.insert_segments("vid_a", [
            {"start_ms": 0, "end_ms": 1000, "text": "HY4 是腾讯的新模型", "source": "caption"},
            {"start_ms": 1000, "end_ms": 2000, "text": "混元大模型正式发布", "source": "caption"},
        ])

    def tearDown(self):
        self.db.close()
        self.tmp.cleanup()

    def test_variants_merge_and_record_matches(self):
        data = search_queries(self.cfg, ["混元", "HY4"], video_id="vid_a", limit=5)
        snippets = {r["snippet"] for r in data["results"]}
        self.assertTrue(any("混元" in s for s in snippets))
        self.assertTrue(any("HY4" in s for s in snippets))
        self.assertTrue(all(r["matched_queries"] for r in data["results"]))
        self.assertEqual(data["groups"][0]["query"], "混元")

    def test_variants_empty_group_stays_visible(self):
        data = search_queries(self.cfg, ["不存在的词", "HY4"], video_id="vid_a", limit=5)
        self.assertTrue(data["groups"][0]["empty"])
        self.assertTrue(data["results"])


if __name__ == "__main__":
    unittest.main()

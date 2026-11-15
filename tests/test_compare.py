import tempfile
import unittest
from pathlib import Path

from video2agent.compare import compare_videos
from video2agent.config import load_config
from video2agent.db import Database


class CompareTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.cfg = load_config(Path(self.tmp.name))
        self.db = Database(self.cfg.db_path)
        for vid, label in (("vid_a", "A"), ("vid_b", "B")):
            self.db.upsert_video({
                "id": vid, "source_kind": "local", "source_uri": "test://" + vid,
                "title": label, "duration_ms": 10000, "status": "ready",
            })
            self.db.insert_segments(vid, [
                {"start_ms": i * 1000, "end_ms": i * 1000 + 900,
                 "text": ("价格" if i == 0 else "内容") + f" {label} {i}"}
                for i in range(120)
            ])

    def tearDown(self):
        self.db.close()
        self.tmp.cleanup()

    def test_compare_requires_two_videos(self):
        with self.assertRaises(Exception) as caught:
            compare_videos(self.cfg, ["vid_a"], aspects=["价格"])
        self.assertEqual(getattr(caught.exception, "code", ""), "E_COMPARE_COUNT")

    def test_compare_total_budget_is_hard(self):
        data = compare_videos(self.cfg, ["vid_a", "vid_b"], aspects=["价格"], max_chars=12000, max_total_chars=500)
        self.assertLessEqual(sum(v["transcript_chars"] for v in data["videos"]), 500)
        self.assertTrue(all(v["transcript"] for v in data["videos"]))

    def test_compare_unknown_id_is_an_error(self):
        with self.assertRaises(Exception) as caught:
            compare_videos(self.cfg, ["vid_a", "vid_missing"], aspects=["价格"])
        self.assertEqual(getattr(caught.exception, "code", ""), "E_NOT_FOUND")

    def test_compare_packs_each_video_and_samples_the_end(self):
        data = compare_videos(self.cfg, ["vid_a", "vid_b"], aspects=["价格"], max_chars=2000)
        self.assertEqual(len(data["videos"]), 2)
        for video in data["videos"]:
            self.assertEqual(video["transcript_mode"], "sampled")
            self.assertTrue(video["transcript"][0].startswith("[00:00:00"))
            self.assertTrue(video["transcript"][-1].startswith("[00:01:59"))
            self.assertEqual(video["aspects"][0]["coverage"], "hit")
            self.assertTrue(video["aspects"][0]["hits"])
            allowed = {"timecode", "start_ms", "end_ms", "snippet", "source",
                       "matched_terms", "why", "citation"}
            for hit in video["aspects"][0]["hits"]:
                self.assertTrue(set(hit) <= allowed, set(hit) - allowed)


if __name__ == "__main__":
    unittest.main()

import tempfile
import unittest
from pathlib import Path

from video2agent.config import load_config
from video2agent.db import Database
from video2agent.pipeline import search
from video2agent.text import tokens_for_search


def _library():
    tmp = tempfile.TemporaryDirectory()
    cfg = load_config(Path(tmp.name))
    db = Database(cfg.db_path)
    try:
        for vid, status in (("vid_ready", "ready"), ("vid_failed", "failed"),
                            ("vid_evicted", "evicted")):
            db.upsert_video({
                "id": vid, "source_kind": "local", "source_uri": vid + ".mp4",
                "source_path": vid + ".mp4", "title": vid, "duration_ms": 60_000,
                "status": status,
            })
        for vid in ("vid_ready", "vid_failed", "vid_evicted"):
            text = "needle in a " + vid
            db.insert_segments(vid, [{
                "start_ms": 0, "end_ms": 4000, "text": text, "source": "caption",
                "confidence": 1.0, "tokens": tokens_for_search(text),
            }])
    finally:
        db.close()
    return tmp, cfg


class SearchReadyFilterTest(unittest.TestCase):
    """A library search must never return a record its own readers reject."""

    def setUp(self):
        self.tmp, self.cfg = _library()

    def tearDown(self):
        self.tmp.cleanup()

    def test_only_ready_rows_are_returned(self):
        result = search(self.cfg, "needle")
        ids = {r.get("video_id") for r in result.get("results") or []}
        self.assertIn("vid_ready", ids)
        self.assertNotIn("vid_failed", ids)
        self.assertNotIn("vid_evicted", ids)

    def test_meta_hits_are_filtered_too(self):
        result = search(self.cfg, "vid_failed")
        ids = {r.get("video_id") for r in result.get("results") or []}
        self.assertNotIn("vid_failed", ids)


class SearchPoolNotStarvedTest(unittest.TestCase):
    """Stale non-ready rows must not fill the FTS pool and hide ready hits.

    The filter used to run in Python after LIMIT 200, so 250 matching stale rows
    pushed the only ready hit past the pool and the query read as NO_MATCH.
    """

    @classmethod
    def setUpClass(cls):
        cls.tmp = tempfile.TemporaryDirectory()
        cls.cfg = load_config(Path(cls.tmp.name))
        db = Database(cls.cfg.db_path)
        try:
            for i in range(250):
                vid = f"vid_stale{i:03d}"
                db.upsert_video({
                    "id": vid, "source_kind": "local", "source_uri": vid + ".mp4",
                    "source_path": vid + ".mp4", "title": vid, "duration_ms": 60_000,
                    "status": "failed",
                    # Explicit and old: equal timestamps make the ORDER BY tie
                    # arbitrary, which made this test flaky.
                    "created_at": "2026-01-01T00:00:00+00:00",
                })
                text = "价格 成本 " + ("填充" * 20) + str(i)
                db.insert_segments(vid, [{
                    "start_ms": 0, "end_ms": 4000, "text": text, "source": "caption",
                    "confidence": 1.0, "tokens": tokens_for_search(text),
                }])
            # The only ready record, created last so it is also the newest.
            db.upsert_video({
                "id": "vid_ready_alias", "source_kind": "local",
                "source_uri": "vid_ready_alias.mp4", "source_path": "vid_ready_alias.mp4",
                "title": "vid_ready_alias", "duration_ms": 60_000, "status": "ready",
                # Newest, so the 200-row window always keeps it.
                "created_at": "2026-06-01T00:00:00+00:00",
            })
            text = "成本 " + ("填充" * 30)
            db.insert_segments("vid_ready_alias", [{
                "start_ms": 0, "end_ms": 4000, "text": text, "source": "caption",
                "confidence": 1.0, "tokens": tokens_for_search(text),
            }])
        finally:
            db.close()

    @classmethod
    def tearDownClass(cls):
        cls.tmp.cleanup()

    def test_ready_hit_survives_a_flood_of_stale_rows(self):
        result = search(self.cfg, "价格")
        ids = {r.get("video_id") for r in result.get("results") or []}
        self.assertIn("vid_ready_alias", ids,
                      "a ready hit was dropped because stale rows filled the pool")
        self.assertFalse(any(i and i.startswith("vid_stale") for i in ids))



class ReadyTargetSetNotStarvedTest(unittest.TestCase):
    """The ready filter must run in SQL for the target set too.

    The target list used to take the newest 200 rows and filter them in Python, so
    200 newer failed rows emptied it and a real word read as NO_MATCH.
    """

    @classmethod
    def setUpClass(cls):
        cls.tmp = tempfile.TemporaryDirectory()
        cls.cfg = load_config(Path(cls.tmp.name))
        db = Database(cls.cfg.db_path)
        try:
            for i in range(201):
                vid = f"vid_newer_failed{i:03d}"
                db.upsert_video({
                    "id": vid, "source_kind": "local", "source_uri": vid + ".mp4",
                    "source_path": vid + ".mp4", "title": vid, "duration_ms": 60_000,
                    "status": "failed",
                    "created_at": "2026-06-01T00:00:00+00:00",
                })
            db.upsert_video({
                "id": "vid_old_ready", "source_kind": "local",
                "source_uri": "vid_old_ready.mp4", "source_path": "vid_old_ready.mp4",
                "title": "vid_old_ready", "duration_ms": 60_000, "status": "ready",
                # Older than every failed row: the 200-row window drops it.
                "created_at": "2026-01-01T00:00:00+00:00",
            })
            text = "边际成本 与 规模效应"
            db.insert_segments("vid_old_ready", [{
                "start_ms": 0, "end_ms": 4000, "text": text, "source": "caption",
                "confidence": 1.0, "tokens": tokens_for_search(text),
            }])
        finally:
            db.close()

    @classmethod
    def tearDownClass(cls):
        cls.tmp.cleanup()

    def test_an_old_ready_video_is_still_a_target(self):
        result = search(self.cfg, "边际成本")
        ids = {r.get("video_id") for r in result.get("results") or []}
        self.assertIn("vid_old_ready", ids,
                      "the ready filter after LIMIT dropped every ready target")
class NoReadyVideoTest(unittest.TestCase):
    """A library whose rows are all non-ready is not "no match"."""

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.cfg = load_config(Path(self.tmp.name))
        db = Database(self.cfg.db_path)
        try:
            db.upsert_video({
                "id": "vid_only_failed", "source_kind": "local",
                "source_uri": "f.mp4", "source_path": "f.mp4",
                "title": "f", "duration_ms": 60_000, "status": "failed",
            })
        finally:
            db.close()

    def tearDown(self):
        self.tmp.cleanup()

    def test_search_says_no_ready_video(self):
        from video2agent.util import Video2AgentError

        with self.assertRaises(Video2AgentError) as ctx:
            search(self.cfg, "anything")
        self.assertEqual(ctx.exception.as_dict()["code"], "E_NO_READY_VIDEO")


class LargeLibrarySearchTest(unittest.TestCase):
    """The index covers all ready videos even when per-video checks are capped."""

    @classmethod
    def setUpClass(cls):
        cls.tmp = tempfile.TemporaryDirectory()
        cls.cfg = load_config(Path(cls.tmp.name))
        db = Database(cls.cfg.db_path)
        try:
            for i in range(201):
                vid = f"vid_cap{i:03d}"
                db.upsert_video({
                    "id": vid, "source_kind": "local", "source_uri": vid + ".mp4",
                    "source_path": vid + ".mp4", "title": vid if i else "外接屏幕", "duration_ms": 60_000,
                    "status": "ready", "created_at": "2026-02-01" if i else "2026-01-01",
                })
            db.insert_segments("vid_cap000", [{
                "start_ms": 6000, "end_ms": 8000, "source": "caption",
                "text": "电容耦合", "tokens": tokens_for_search("电容耦合"),
            }])
            db.insert_ocr_tracks("vid_cap000", [{
                "start_ms": 10000, "end_ms": 12000,
                "text": "SubRip", "tokens": tokens_for_search("SubRip"),
            }])
        finally:
            db.close()

    @classmethod
    def tearDownClass(cls):
        cls.tmp.cleanup()

    def test_tokenless_query_keeps_the_cap(self):
        result = search(self.cfg, "Q K V")
        codes = {w.get("code") for w in result.get("warnings") or []}
        self.assertIn("SEARCH_TARGETS_CAPPED", codes,
                      "the cap was dropped on the empty-literal path: " + repr(codes))

    def test_indexed_modalities_find_the_oldest_video(self):
        for query, modality, start_ms, end_ms in (
            ("电容耦合", "transcript", 6000, 8000),
            ("SubRip", "ocr", 10000, 12000),
            ("外接屏幕", "video", None, None),
        ):
            with self.subTest(modality=modality):
                result = search(self.cfg, query, modalities=[modality], limit=1,
                                start_ms=start_ms, end_ms=end_ms)
                self.assertEqual([hit["video_id"] for hit in result["results"]], ["vid_cap000"])
                self.assertNotIn("SEARCH_TARGETS_CAPPED", {w["code"] for w in result["warnings"]})
                self.assertEqual(result["visual_index"]["sampled_videos"], 200)
                self.assertEqual(result["visual_index"]["total_videos"], 201)


if __name__ == "__main__":
    unittest.main()

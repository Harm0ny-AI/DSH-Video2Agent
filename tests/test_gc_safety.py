import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from video2agent import storage
from video2agent.config import Config
from video2agent.db import Database


def _row(vid, status, updated):
    return {
        "id": vid, "source_kind": "url", "source_uri": "https://example.com/" + vid,
        "source_path": "x", "sha256": None, "title": vid, "duration_ms": 1000,
        "width": None, "height": None, "fps": None, "language": None,
        # The live library stores the platform as the probe reports it: "BiliBili".
        "platform": "BiliBili", "status": status, "analysis_version": "1",
        "meta_json": "{}", "warnings_json": "[]",
        "created_at": "2026-01-01T00:00:00+00:00", "updated_at": updated,
    }


class GcSafetyTest(unittest.TestCase):
    def setUp(self):
        self.cfg = Config(Path(tempfile.mkdtemp(prefix="vp-gc-")))
        self.db = Database(self.cfg.db_path)
        for vid, status in (("vid_analyzing", "analyzing"), ("vid_ready", "ready")):
            self.db.upsert_video(_row(vid, status, "2026-01-02T00:00:00+00:00"))
            folder = self.cfg.media_dir / vid
            folder.mkdir(parents=True, exist_ok=True)
            (folder / "m.mp4").write_bytes(b"x" * 10)

    def tearDown(self):
        self.db.close()

    def test_purge_skips_analyzing(self):
        plan = storage.plan_cache_purge(self.cfg, self.db, older_than_days=1)
        self.assertNotIn("vid_analyzing", {p["video_id"] for p in plan})

    def test_evict_skips_analyzing(self):
        plan = storage.plan_evictions(self.cfg, self.db, older_than_days=1)
        self.assertNotIn("vid_analyzing", {p["video_id"] for p in plan})

    def test_purge_keeps_row_when_files_busy(self):
        with patch("video2agent.storage.shutil.rmtree", side_effect=OSError("busy")):
            result = storage.purge_video(self.cfg, self.db, "vid_ready")
        self.assertEqual(result.get("error"), "files_busy")
        self.assertIsNotNone(self.db.get_video("vid_ready"))

    def test_purge_deletes_the_bilibili_cover(self):
        # Covers are bili_<bvid>.jpg, not vid_<hash>*: the old glob never matched.
        self.db.update_video("vid_ready", source_uri="https://www.bilibili.com/video/BV1x411c7mDE")
        cover = self.cfg.covers_dir / "bili_BV1x411c7mDE.jpg"
        cover.parent.mkdir(parents=True, exist_ok=True)
        cover.write_bytes(b"cover")
        storage.purge_video(self.cfg, self.db, "vid_ready")
        self.assertFalse(cover.exists(), "the bilibili cover was left behind")

    def test_purge_keeps_a_cover_shared_by_another_part(self):
        # Multi-P: several rows share bili_<bvid>.jpg; purging one must not take
        # the other's cover with it.
        url = "https://www.bilibili.com/video/BV1x411c7mDE"
        self.db.upsert_video(_row("vid_part2", "ready", "2026-01-02T00:00:00+00:00"))
        self.db.update_video("vid_ready", source_uri=url + "?p=1")
        self.db.update_video("vid_part2", source_uri=url + "?p=2")
        cover = self.cfg.covers_dir / "bili_BV1x411c7mDE.jpg"
        cover.parent.mkdir(parents=True, exist_ok=True)
        cover.write_bytes(b"cover")
        storage.purge_video(self.cfg, self.db, "vid_ready")
        self.assertTrue(cover.exists(), "a cover shared with another part was deleted")

    def test_purge_keeps_the_cover_of_a_bilibili_record_for_a_local_file(self):
        # A local file whose path contains a BV id must not own bili_<bvid>.jpg.
        self.db.upsert_video(_row("vid_bili", "ready", "2026-01-02T00:00:00+00:00"))
        self.db.update_video("vid_bili", source_uri="https://www.bilibili.com/video/BV1x411c7mDE")
        self.db.update_video("vid_ready", source_uri="D:\\dl\\BV1x411c7mDE - title.mp4",
                             platform="local")
        cover = self.cfg.covers_dir / "bili_BV1x411c7mDE.jpg"
        cover.parent.mkdir(parents=True, exist_ok=True)
        cover.write_bytes(b"cover")
        storage.purge_video(self.cfg, self.db, "vid_ready")
        self.assertTrue(cover.exists(), "a local file deleted an unrelated video's cover")


    def test_purge_treats_an_unreadable_share_count_as_shared(self):
        # A sqlite error here is not an OSError: it used to escape with the media
        # already deleted and the row still ready. The cover must survive.
        import sqlite3
        self.db.update_video("vid_ready", source_uri="https://www.bilibili.com/video/BV1x411c7mDE")
        cover = self.cfg.covers_dir / "bili_BV1x411c7mDE.jpg"
        cover.parent.mkdir(parents=True, exist_ok=True)
        cover.write_bytes(b"cover")
        original_one = self.db.one

        def flaky_one(sql, params=()):
            if "COUNT(*)" in sql:
                raise sqlite3.Error("database is locked")
            return original_one(sql, params)

        with patch.object(self.db, "one", side_effect=flaky_one):
            result = storage.purge_video(self.cfg, self.db, "vid_ready")
        self.assertNotIn("error", result, "a locked database must not fail the purge" )
        self.assertTrue(cover.exists(), "an unreadable share count deleted the cover")
    def test_evict_keeps_row_when_files_busy(self):
        with patch("video2agent.storage.shutil.rmtree", side_effect=OSError("busy")):
            result = storage.evict_video(self.cfg, self.db, "vid_ready")
        self.assertEqual(result.get("error"), "files_busy")
        self.assertIsNotNone(self.db.get_video("vid_ready"))

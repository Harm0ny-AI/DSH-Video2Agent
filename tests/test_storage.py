import tempfile
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path

from video2agent.config import load_config
from video2agent.db import Database
from video2agent.storage import (
    cache_policy,
    cached_usage,
    evict_video,
    plan_cache_purge,
    plan_evictions,
    purge_video,
)


class StorageTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.home = Path(self.tmp.name)
        self.cfg = load_config(self.home)
        self.db = Database(self.cfg.db_path)
        now = datetime.now(timezone.utc)
        old = (now - timedelta(days=30)).isoformat(timespec="seconds")
        for vid, kind, created in (
            ("vid_old", "url", old),
            ("vid_new", "url", now.isoformat(timespec="seconds")),
            ("vid_local", "local", old),
        ):
            (self.cfg.media_dir / vid).mkdir(parents=True, exist_ok=True)
            (self.cfg.derived_dir / vid / "frames").mkdir(parents=True, exist_ok=True)
            (self.cfg.media_dir / vid / "source.mp4").write_bytes(b"x" * 1024)
            (self.cfg.derived_dir / vid / "frames" / "f.jpg").write_bytes(b"y" * 2048)
            self.db.upsert_video({
                "id": vid, "source_kind": kind, "source_uri": "test://" + vid,
                "source_path": str(self.cfg.media_dir / vid / "source.mp4"),
                "title": vid, "duration_ms": 1000, "status": "ready", "created_at": created,
            })
            self.db.conn.execute("UPDATE videos SET created_at=?, updated_at=? WHERE id=?", [created, created, vid])
        self.db.conn.commit()

    def tearDown(self):
        self.db.close()
        self.tmp.cleanup()

    def test_retention_only_url(self):
        plan = plan_evictions(self.cfg, self.db, older_than_days=1)
        ids = {p["video_id"] for p in plan}
        self.assertIn("vid_old", ids)
        self.assertNotIn("vid_new", ids)
        self.assertNotIn("vid_local", ids)

    def test_quota_evicts_oldest_url(self):
        plan = plan_evictions(self.cfg, self.db, max_gb=0.000001)
        ids = [p["video_id"] for p in plan]
        self.assertEqual(ids, ["vid_old", "vid_new"])
        self.assertNotIn("vid_local", ids)

    def test_evict_dry_run_keeps_files(self):
        before = cached_usage(self.cfg)
        result = evict_video(self.cfg, self.db, "vid_old", dry_run=True)
        self.assertEqual(result["bytes"], 3072)
        self.assertTrue((self.cfg.media_dir / "vid_old").exists())
        self.assertEqual(cached_usage(self.cfg), before)

    def test_evict_actual(self):
        evict_video(self.cfg, self.db, "vid_old", dry_run=False)
        self.assertFalse((self.cfg.media_dir / "vid_old").exists())
        self.assertFalse((self.cfg.derived_dir / "vid_old").exists())
        self.assertEqual(self.db.get_video("vid_old")["status"], "evicted")
        self.assertTrue((self.cfg.media_dir / "vid_local").exists())


    def test_cache_policy_defaults_and_clamps(self):
        self.assertEqual(cache_policy(self.cfg), {"expire": True, "days": 7, "limit_enabled": False, "limit_gb": 20})
        (self.home / "ui-settings.json").write_text('{"cacheExpire":false,"cacheDays":999,"cacheLimitEnabled":true,"cacheLimitGb":99}', encoding="utf-8")
        self.assertEqual(cache_policy(self.cfg), {"expire": False, "days": 365, "limit_enabled": True, "limit_gb": 20})

    def test_cache_expiry_includes_local_and_new(self):
        plan = plan_cache_purge(self.cfg, self.db, older_than_days=1)
        ids = {p["video_id"] for p in plan}
        self.assertIn("vid_old", ids)
        self.assertIn("vid_local", ids)
        self.assertNotIn("vid_new", ids)

    def test_cache_capacity_evicts_oldest(self):
        plan = plan_cache_purge(self.cfg, self.db, max_gb=0.000001)
        ids = [p["video_id"] for p in plan]
        self.assertEqual(ids, ["vid_old", "vid_local", "vid_new"])

    def test_purge_removes_files_and_record(self):
        result = purge_video(self.cfg, self.db, "vid_old")
        self.assertGreaterEqual(result["bytes"], 3072)
        self.assertFalse((self.cfg.media_dir / "vid_old").exists())
        self.assertIsNone(self.db.get_video("vid_old"))

if __name__ == "__main__":
    unittest.main()

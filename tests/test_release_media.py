import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from video2agent import storage
from video2agent.config import Config
from video2agent.db import Database


def _row(vid, status="ready", updated="2026-01-02T00:00:00+00:00"):
    return {
        "id": vid, "source_kind": "url", "source_uri": "https://example.com/" + vid,
        "source_path": "x", "sha256": "a" * 64, "title": vid, "duration_ms": 1000,
        "width": None, "height": None, "fps": None, "language": None,
        "platform": "url", "status": status, "analysis_version": "1",
        "meta_json": "{}", "warnings_json": "[]",
        "created_at": "2026-01-01T00:00:00+00:00", "updated_at": updated,
    }


class ReleaseMediaTest(unittest.TestCase):
    def setUp(self):
        self.cfg = Config(Path(tempfile.mkdtemp(prefix="vp-release-")))
        self.db = Database(self.cfg.db_path)
        self.db.upsert_video(_row("vid_ready"))
        (self.cfg.media_dir / "vid_ready").mkdir(parents=True)
        (self.cfg.media_dir / "vid_ready" / "source.mp4").write_bytes(b"x" * 10)
        self.db.update_video("vid_ready",
                             source_path=str(self.cfg.media_dir / "vid_ready" / "source.mp4"))
        (self.cfg.derived_dir / "vid_ready" / "frames").mkdir(parents=True)
        (self.cfg.derived_dir / "vid_ready" / "frames" / "f.jpg").write_bytes(b"y" * 5)

    def tearDown(self):
        self.db.close()

    def test_release_frees_files_but_keeps_the_record(self):
        self.db.insert_segments("vid_ready", [{
            "start_ms": 0, "end_ms": 1000, "text": "蓝莓为什么便宜", "source": "asr",
            "confidence": 0.9, "speaker": None, "words": None,
        }])
        self.db.insert_ocr_tracks("vid_ready", [{"start_ms": 0, "end_ms": 200, "text": "标签"}])
        self.db.conn.execute(
            "INSERT INTO evidence (id,video_id,start_ms,end_ms,payload_json,created_at) VALUES (?,?,?,?,?,?)",
            ["ev_kept", "vid_ready", 0, 200, "{}", "2026-01-01"],
        )
        self.db.update_video("vid_ready", warnings_json='[{"code":"MEDIA_TRUNCATED"}]')
        result = storage.release_media(self.cfg, self.db, "vid_ready")
        self.assertNotIn("error", result)
        self.assertEqual(result["cache_bytes"], 15)
        self.assertFalse((self.cfg.media_dir / "vid_ready").exists())
        self.assertFalse((self.cfg.derived_dir / "vid_ready").exists())
        row = self.db.get_video("vid_ready")
        self.assertIsNotNone(row, "releasing media must not delete the knowledge record")
        assert row is not None
        self.assertEqual(row["status"], "ready")
        self.assertTrue(row.get("media_released_at"))
        # The searchable rows are the point of keeping the record.
        self.assertEqual(len(self.db.get_segments("vid_ready")), 1)
        self.assertEqual(len(self.db.get_ocr_tracks("vid_ready")), 1)
        self.assertIsNotNone(self.db.one("SELECT id FROM evidence WHERE id='ev_kept'"))
        self.assertTrue(any(w.get("code") == "MEDIA_TRUNCATED" for w in row["warnings"]))
        self.assertTrue(any(w.get("code") == "MEDIA_RELEASED" for w in row["warnings"]))

    def test_release_counts_covers_separately_from_capped_cache(self):
        self.cfg.covers_dir.mkdir(parents=True)
        (self.cfg.covers_dir / "vid_ready.jpg").write_bytes(b"cover")
        result = storage.release_media(self.cfg, self.db, "vid_ready")
        self.assertEqual(result["cache_bytes"], 15)
        self.assertEqual(result["bytes"], 20)

    def test_partial_release_counts_only_freed_bytes(self):
        real_remove = storage.shutil.rmtree
        media_dir = self.cfg.media_dir / "vid_ready"

        def remove_one(target):
            if target == media_dir:
                raise OSError("media in use")
            return real_remove(target)

        with patch("video2agent.storage.shutil.rmtree", side_effect=remove_one):
            result = storage.release_media(self.cfg, self.db, "vid_ready")
        self.assertEqual(result["error"], "files_busy")
        self.assertEqual(result["cache_bytes"], 5)
        self.assertEqual(result["bytes"], 5)
        self.assertTrue(media_dir.exists())
        self.assertIsNone(self.db.get_video("vid_ready")["media_released_at"])

    def test_release_keeps_row_when_files_busy(self):
        with patch("video2agent.storage.shutil.rmtree", side_effect=OSError("busy")):
            result = storage.release_media(self.cfg, self.db, "vid_ready")
        self.assertEqual(result.get("error"), "files_busy")
        row = self.db.get_video("vid_ready")
        self.assertIsNotNone(row)
        assert row is not None
        self.assertIsNone(row.get("media_released_at"), "a partial release must be retried, not marked done")

    def test_a_local_source_is_never_deleted(self):
        local = Path(tempfile.mkdtemp(prefix="vp-local-")) / "mine.mp4"
        local.write_bytes(b"z" * 10)
        self.db.update_video("vid_ready", source_kind="local", source_path=str(local))
        result = storage.release_media(self.cfg, self.db, "vid_ready")
        self.assertNotIn("error", result)
        self.assertTrue(local.exists(), "the user's own file must not be deleted")
        row = self.db.get_video("vid_ready")
        assert row is not None
        self.assertFalse(result["source_removed"])
        self.assertIsNone(row.get("media_released_at"))
        self.assertTrue(any(w.get("code") == "FRAMES_RELEASED" for w in row["warnings"]))

    def test_a_local_source_in_the_cache_directory_is_not_removed(self):
        source = self.cfg.media_dir / "vid_ready" / "source.mp4"
        self.db.update_video("vid_ready", source_kind="local", source_path=str(source))
        result = storage.release_media(self.cfg, self.db, "vid_ready")
        self.assertTrue(source.is_file())
        self.assertEqual(result["cache_bytes"], 5)
        self.assertFalse(result["source_removed"])

    def test_release_skips_analyzing(self):
        self.db.update_video("vid_ready", status="analyzing")
        result = storage.release_media(self.cfg, self.db, "vid_ready")
        self.assertEqual(result.get("error"), "busy_analyzing")

    def test_release_skips_ready_video_during_rebuild(self):
        job = self.db.create_job("ingest", "sample", video_id="vid_ready")
        self.db.update_job(job, state="running")
        self.assertEqual(storage.plan_cache_purge(self.cfg, self.db, max_gb=0.000000001), [])
        self.assertEqual(storage.release_media(self.cfg, self.db, "vid_ready")["error"], "busy_analyzing")
        self.assertEqual(storage.cached_usage(self.cfg), 15)

    def test_known_dead_worker_does_not_pin_ready_cache(self):
        job = self.db.create_job("ingest", "sample", video_id="vid_ready")
        self.db.update_job(job, pid=4321, state="running")
        with patch("video2agent.storage.pid_alive", return_value=False):
            plan = storage.plan_cache_purge(self.cfg, self.db, max_gb=0.000000001)
            result = storage.release_media(self.cfg, self.db, "vid_ready")
        self.assertEqual([item["video_id"] for item in plan], ["vid_ready"])
        self.assertEqual(result["cache_bytes"], 15)

    def test_plan_skips_already_released(self):
        storage.release_media(self.cfg, self.db, "vid_ready")
        plan = storage.plan_cache_purge(self.cfg, self.db, older_than_days=1)
        self.assertNotIn("vid_ready", {p["video_id"] for p in plan})


if __name__ == "__main__":
    unittest.main()

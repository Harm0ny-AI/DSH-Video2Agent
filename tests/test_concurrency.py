import sqlite3
import tempfile
import threading
import time
import unittest
from pathlib import Path

from video2agent.config import load_config
from video2agent.db import SCHEMA_VERSION, Database


class ReadWhileWriterTests(unittest.TestCase):
    """A read-only CLI call must not wait for the ingest writer's lock.

    Regression: Database() used to run CREATE TABLE IF NOT EXISTS and bump
    PRAGMA user_version on every open, i.e. every `jobs --id` poll took the
    write lock while an ingest held it and blocked for seconds.
    """

    def test_open_and_read_while_writer_holds_lock(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        cfg = load_config(Path(tmp.name))
        with Database(cfg.db_path) as db:
            db.upsert_video({
                "id": "vid_lock", "source_kind": "local", "source_uri": "lock.mp4",
                "source_path": "lock.mp4", "title": "lock", "duration_ms": 1000,
                "status": "ready",
            })
        release = threading.Event()
        started = threading.Event()

        def writer():
            conn = sqlite3.connect(str(cfg.db_path), timeout=30)
            try:
                conn.execute("BEGIN IMMEDIATE")
                conn.execute(
                    "INSERT INTO jobs (id,kind,source,state,created_at) VALUES (?,?,?,?,?)",
                    ["job_lock", "ingest", "x", "running", "2026-01-01T00:00:00+00:00"],
                )
                started.set()
                release.wait(5)
                conn.commit()
            finally:
                conn.close()

        thread = threading.Thread(target=writer, daemon=True)
        thread.start()
        self.assertTrue(started.wait(5), "writer did not start")

        t0 = time.perf_counter()
        try:
            with Database(cfg.db_path) as db:
                rows = db.list_jobs()
            elapsed = time.perf_counter() - t0
        finally:
            release.set()
            thread.join(5)

        self.assertIsInstance(rows, list)
        # Old code waited for the writer (>=5s here); a read-only open is ~ms. The
        # bound is loose on purpose: this is the only wall-clock assertion in the
        # suite and an overloaded CI machine must not fail it (the pre-fix value was
        # 3.48s, so 3s still separates the two behaviours).
        self.assertLess(elapsed, 3.0, f"read-only open blocked for {elapsed:.2f}s")

    def test_reopen_keeps_schema_version_and_does_not_rewrite(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        cfg = load_config(Path(tmp.name))
        with Database(cfg.db_path) as db:
            self.assertEqual(db.schema_version, SCHEMA_VERSION)
        before = cfg.db_path.stat().st_size
        with Database(cfg.db_path) as db:
            self.assertEqual(db.schema_version, SCHEMA_VERSION)
            db.list_videos()
        self.assertEqual(cfg.db_path.stat().st_size, before)

    def test_fresh_database_creates_schema(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        cfg = load_config(Path(tmp.name))
        with Database(cfg.db_path) as db:
            self.assertEqual(db.schema_version, SCHEMA_VERSION)
            self.assertEqual(db.list_jobs(), [])


if __name__ == "__main__":
    unittest.main()

import json
import tempfile
import threading
import time
import unittest
from pathlib import Path

from video2agent.cli import _ingest_slot
from video2agent.config import load_config
from video2agent.db import Database
from video2agent.util import stable_id


class IngestSlotTests(unittest.TestCase):
    """Concurrency is the report's worst number: 3 at once was 4.3x one alone."""

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.cfg = load_config(Path(self.tmp.name))
        self.db = Database(self.cfg.db_path)
        self.addCleanup(self.db.close)
        self.job_id = self.db.create_job("ingest", "demo.mp4")

    def _sidecar(self):
        return Path(self.tmp.name) / "jobs" / f"{self.job_id}.json"

    def test_a_second_ingest_waits_and_says_so(self):
        order = []
        holder_ready = threading.Event()

        def holder():
            with _ingest_slot(self.cfg, self.job_id, timeout_s=10, stale_s=999):
                holder_ready.set()
                time.sleep(0.6)
                order.append("first")

        thread = threading.Thread(target=holder)
        thread.start()
        holder_ready.wait(2)
        started = time.monotonic()
        with _ingest_slot(self.cfg, self.job_id, timeout_s=10, stale_s=999):
            waited = time.monotonic() - started
            order.append("second")
        thread.join(5)
        self.assertEqual(order, ["first", "second"], "the lock must serialise, not interleave")
        self.assertGreater(waited, 0.3, "the second ingest should actually wait")

    def test_waiting_job_reports_the_queue_state(self):
        holder_ready = threading.Event()

        def holder():
            with _ingest_slot(self.cfg, self.job_id, timeout_s=10, stale_s=999):
                holder_ready.set()
                time.sleep(0.8)

        thread = threading.Thread(target=holder)
        thread.start()
        holder_ready.wait(2)
        with _ingest_slot(self.cfg, self.job_id, timeout_s=10, stale_s=999):
            pass
        thread.join(5)
        data = json.loads(self._sidecar().read_text(encoding="utf-8"))
        self.assertEqual(data["job"]["state"], "queued")
        self.assertIn("排队中", data["job"]["message"])

    def test_a_cancel_marker_is_terminal(self):
        marker = Path(self.tmp.name) / "jobs" / f"{self.job_id}.cancel"
        marker.parent.mkdir(parents=True, exist_ok=True)
        marker.write_text(str(time.time()), encoding="utf8")
        with self.assertRaises(Exception) as ctx:
            with _ingest_slot(self.cfg, self.job_id, timeout_s=5, stale_s=999):
                pass
        self.assertEqual(getattr(ctx.exception, "code", ""), "E_CANCELED")
        row = self.db.get_job(self.job_id)
        self.assertEqual(row["state"], "canceled")

    def test_a_stale_lock_is_stolen(self):
        lock = Path(self.tmp.name) / "jobs" / ".ingest.lock"
        lock.parent.mkdir(parents=True, exist_ok=True)
        lock.write_text("99999", encoding="ascii")
        old = time.time() - 600
        import os

        os.utime(lock, (old, old))
        started = time.monotonic()
        with _ingest_slot(self.cfg, self.job_id, timeout_s=5, stale_s=180):
            pass
        self.assertLess(time.monotonic() - started, 2.0, "a dead worker must not wedge the queue")
        self.assertFalse(lock.exists(), "the slot is released on exit")

    def test_a_stale_lock_closes_the_job_it_left_behind(self):
        # A SIGKILLed worker leaves `running` in the database; the card would poll it
        # forever. Stealing the lock must mark that job failed.
        lock = Path(self.tmp.name) / "jobs" / ".ingest.lock"
        lock.parent.mkdir(parents=True, exist_ok=True)
        dead_job = self.db.create_job("ingest", "dead.mp4")
        self.db.update_job(dead_job, state="running", progress=0.4)
        lock.write_text(f"99999 {dead_job}", encoding="ascii")
        old = time.time() - 600
        import os

        os.utime(lock, (old, old))
        with _ingest_slot(self.cfg, self.job_id, timeout_s=5, stale_s=180):
            pass
        row = self.db.get_job(dead_job)
        self.assertEqual(row["state"], "failed")
        self.assertEqual(row["error_code"], "E_WORKER_LOST")
        self.assertTrue(row["remedy"])

    def test_a_queue_timeout_leaves_a_terminal_state(self):
        lock = Path(self.tmp.name) / "jobs" / ".ingest.lock"
        lock.parent.mkdir(parents=True, exist_ok=True)
        lock.write_text("12345", encoding="ascii")  # fresh, never stolen
        with self.assertRaises(Exception) as ctx:
            with _ingest_slot(self.cfg, self.job_id, timeout_s=0, stale_s=999):
                pass
        self.assertEqual(getattr(ctx.exception, "code", ""), "E_BUSY")
        row = self.db.get_job(self.job_id)
        self.assertEqual(row["state"], "failed", "a queued job must not be polled forever")
        self.assertEqual(row["error_code"], "E_BUSY")
        self.assertTrue(row["remedy"])


class RepeatIngestTests(unittest.TestCase):
    """A repeat ingest of an indexed URL must not download anything again."""

    def test_known_url_returns_from_the_database(self):
        from video2agent.pipeline import analyze

        with tempfile.TemporaryDirectory() as tmp:
            cfg = load_config(Path(tmp))
            url = "https://www.bilibili.com/video/BV1xx411c7mD"
            # The look-up key is the canonical form (trailing slash), not the raw
            # input; seed the row with the same id the repeat ingest will use.
            from video2agent.links import canonical_video_url
            vid = stable_id("vid", canonical_video_url("BV1xx411c7mD"))
            db = Database(cfg.db_path)
            try:
                db.upsert_video({
                    "id": vid, "source_kind": "url", "source_uri": url,
                    "source_path": str(Path(tmp) / "missing.mp4"), "title": "cached",
                    "duration_ms": 1000, "status": "ready",
                })
            finally:
                db.close()
            started = time.monotonic()
            result = analyze(cfg, url, profile="fast")
            elapsed = time.monotonic() - started
        self.assertEqual(result["video_id"], vid)
        self.assertLess(elapsed, 2.0, "an indexed URL must not go back to the network")


if __name__ == "__main__":
    unittest.main()

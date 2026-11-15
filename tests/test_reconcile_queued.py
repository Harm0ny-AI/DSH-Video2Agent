import tempfile
import unittest
from pathlib import Path

from video2agent.config import load_config
from video2agent.db import Database

DEAD_PID = 999999


class ReconcileQueuedTest(unittest.TestCase):
    """A killed worker that was still queued must not stay 排队中 forever."""

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.cfg = load_config(Path(self.tmp.name))
        self.db = Database(self.cfg.db_path)
        self.addCleanup(self.db.close)

    def _job(self, state):
        job_id = self.db.create_job("ingest", "q.mp4")
        self.db.update_job(job_id, state=state, pid=DEAD_PID)
        return job_id

    def test_dead_queued_worker_is_reconciled(self):
        job_id = self._job("queued")
        row = self.db.reconcile_job(job_id)
        self.assertEqual(row["state"], "failed")
        self.assertEqual(row["error_code"], "E_WORKER_LOST")

    def test_dead_running_worker_is_reconciled(self):
        job_id = self._job("running")
        row = self.db.reconcile_job(job_id)
        self.assertEqual(row["state"], "failed")

    def test_finished_job_is_untouched(self):
        job_id = self._job("ready")
        row = self.db.reconcile_job(job_id)
        self.assertEqual(row["state"], "ready")


if __name__ == "__main__":
    unittest.main()

import json
import tempfile
import unittest
from pathlib import Path

from video2agent.db import Database


class JobSidecarTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.db = Database(Path(self.tmp.name) / "library.db")
        self.addCleanup(self.db.close)
        self.job_id = self.db.create_job("ingest", "https://example.com/v")

    def _sidecar(self) -> Path:
        return Path(self.tmp.name) / "jobs" / f"{self.job_id}.json"

    def test_progress_updates_mirror_into_a_json_file(self):
        self.db.update_job(self.job_id, state="running", stage="ocr", progress=0.42, message="读画面文字")
        self.assertTrue(self._sidecar().is_file(), "the host reads this file instead of spawning the CLI")
        data = json.loads(self._sidecar().read_text(encoding="utf-8"))
        self.assertTrue(data["ok"])
        self.assertEqual(data["job"]["state"], "running")
        self.assertEqual(data["job"]["stage"], "ocr")
        self.assertAlmostEqual(data["job"]["progress"], 0.42)
        self.assertEqual(data["job"]["message"], "读画面文字")

    def test_the_sidecar_matches_the_database(self):
        self.db.update_job(self.job_id, state="ready", progress=1.0, stage="done")
        sidecar = json.loads(self._sidecar().read_text(encoding="utf-8"))
        row = self.db.get_job(self.job_id)
        self.assertEqual(sidecar["job"]["state"], row["state"])
        self.assertEqual(sidecar["job"]["progress"], row["progress"])

    def test_failure_fields_reach_the_card(self):
        # The JobCard/ErrorCard reads `remedy` and the live card looks up the cover
        # by `source`; leaving them out of the mirror silently degraded both.
        url = "https://www.bilibili.com/video/BV1xx411c7mD"
        job_id = self.db.create_job("ingest", url)
        self.db.update_job(job_id, state="failed", stage="error", progress=0.3,
                           error_code="E_URL", error_message="bad url",
                           remedy="Paste a normal video link.")
        data = json.loads((Path(self.tmp.name) / "jobs" / f"{job_id}.json").read_text(encoding="utf-8"))
        self.assertEqual(data["job"]["remedy"], "Paste a normal video link.")
        self.assertEqual(data["job"]["source"], url)
        self.assertEqual(data["job"]["error_code"], "E_URL")

    def test_no_leftover_tmp_file(self):
        self.db.update_job(self.job_id, progress=0.1)
        leftovers = list((Path(self.tmp.name) / "jobs").glob("*.tmp"))
        self.assertEqual(leftovers, [], "the mirror is written atomically")


if __name__ == "__main__":
    unittest.main()

import json
import os
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

from video2agent.config import load_config
from video2agent.db import Database

ROOT = Path(__file__).resolve().parents[1]


class WorkerTests(unittest.TestCase):
    def _run(self, request):
        env = os.environ.copy()
        env["PYTHONPATH"] = str(ROOT / "src")
        proc = subprocess.run(
            [sys.executable, "-m", "video2agent.worker"],
            input=json.dumps(request, ensure_ascii=False) + "\n",
            text=True,
            encoding="utf-8",
            capture_output=True,
            env=env,
            timeout=30,
        )
        self.assertEqual(proc.returncode, 0, proc.stderr)
        lines = [line for line in proc.stdout.splitlines() if line.strip()]
        self.assertTrue(lines, proc.stderr)
        return json.loads(lines[0])

    def test_version_round_trip_and_protocol_stdout(self):
        data = self._run({"id": 7, "argv": ["--version"]})
        self.assertEqual(data["id"], 7)
        self.assertEqual(data["code"], 0)
        self.assertIn("video2agent", data["out"])
        self.assertEqual(data["err"], "")

    def test_chinese_query_is_not_mojibake(self):
        with tempfile.TemporaryDirectory() as tmp:
            cfg = load_config(Path(tmp))
            db = Database(cfg.db_path)
            try:
                db.upsert_video({
                    "id": "vid_worker", "source_kind": "local", "source_uri": "test://worker",
                    "title": "worker", "duration_ms": 1000, "status": "ready",
                })
                db.insert_segments("vid_worker", [
                    {"start_ms": 0, "end_ms": 500, "text": "价格是六元", "source": "caption"},
                ])
            finally:
                db.close()
            data = self._run({"id": 8, "argv": ["search", "价格", "--json", "--home", tmp]})
        self.assertEqual(data["id"], 8)
        self.assertIn("价格", data["out"])


if __name__ == "__main__":
    unittest.main()

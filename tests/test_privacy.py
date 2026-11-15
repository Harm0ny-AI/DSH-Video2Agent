"""Shareable artefacts must not carry the user's absolute paths.

An export is meant to leave the machine; a job log is kept for the same run. Both
used to contain full local paths (and the log was never pruned). These tests pin
the default redaction and the explicit opt-in.
"""
import json
import os
import tempfile
import time
import unittest
from pathlib import Path

from video2agent.cli import _prune_logs
from video2agent.config import load_config
from video2agent.db import Database
from video2agent.export import export_json, export_knowledge, export_markdown

VID = "vid_privacy"
WIN_PATH = r"C:\Users\someone\Videos\lecture.mp4"


class ExportRedactionTests(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        root = Path(self._tmp.name)
        self.cfg = load_config(root / "home")
        db = Database(self.cfg.db_path)
        try:
            db.upsert_video({
                "id": VID, "source_kind": "local", "source_uri": WIN_PATH,
                "source_path": WIN_PATH, "title": "lecture", "duration_ms": 60_000,
                "status": "ready",
            })
            db.insert_frames(VID, [{
                "pts_ms": 1000, "path": r"C:\Users\someone\derived\vid\frames\frame_00000.jpg",
                "width": 1280, "height": 720,
            }])
        finally:
            db.close()

    def test_markdown_redacts_an_absolute_source(self):
        out = Path(self._tmp.name) / "a.md"
        export_markdown(self.cfg, VID, out)
        text = out.read_text(encoding="utf-8")
        self.assertIn("lecture.mp4", text)
        self.assertNotIn("C:\\Users", text)
        self.assertNotIn("someone", text)

    def test_json_redacts_paths_by_default(self):
        out = Path(self._tmp.name) / "a.json"
        export_json(self.cfg, VID, out)
        data = json.loads(out.read_text(encoding="utf-8"))
        self.assertTrue(data["paths_redacted"])
        self.assertEqual(data["video"]["source_path"], "lecture.mp4")
        self.assertEqual(data["video"]["source_uri"], "lecture.mp4")
        self.assertEqual(data["frames"][0]["path"], "frame_00000.jpg")
        self.assertNotIn("someone", json.dumps(data, ensure_ascii=False))

    def test_json_keeps_paths_when_asked(self):
        out = Path(self._tmp.name) / "b.json"
        export_json(self.cfg, VID, out, include_paths=True)
        data = json.loads(out.read_text(encoding="utf-8"))
        self.assertFalse(data["paths_redacted"])
        self.assertEqual(data["video"]["source_path"], WIN_PATH)
        self.assertIn("someone", data["frames"][0]["path"])

    def test_knowledge_export_redacts_the_source(self):
        out = Path(self._tmp.name) / "c.knowledge.json"
        export_knowledge(self.cfg, VID, out)
        data = json.loads(out.read_text(encoding="utf-8"))
        self.assertEqual(data["video"]["source"], "lecture.mp4")

    def test_a_windows_path_is_redacted_on_every_host(self):
        from video2agent.export import _public_path

        self.assertEqual(_public_path(WIN_PATH), "lecture.mp4")
        self.assertEqual(_public_path(r"\\\\server\\share\\frame.jpg"), "frame.jpg")

    def test_a_url_source_is_not_redacted(self):
        url = "https://www.bilibili.com/video/BV1xx411c7mD"
        db = Database(self.cfg.db_path)
        try:
            db.update_video(VID, source_uri=url)
        finally:
            db.close()
        out = Path(self._tmp.name) / "d.md"
        export_markdown(self.cfg, VID, out)
        self.assertIn(url, out.read_text(encoding="utf-8"))


class LogPruningTests(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        self.cfg = load_config(Path(self._tmp.name) / "home")
        self.cfg.logs_dir.mkdir(parents=True, exist_ok=True)
        old = time.time() - 30 * 86400
        self.old_log = self.cfg.logs_dir / "job_old.log"
        self.old_log.write_text("old", encoding="utf-8")
        os.utime(self.old_log, (old, old))
        self.new_log = self.cfg.logs_dir / "job_new.log"
        self.new_log.write_text("new", encoding="utf-8")
        self.other = self.cfg.logs_dir / "notes.txt"
        self.other.write_text("keep", encoding="utf-8")
        os.utime(self.other, (old, old))

    def test_dry_run_lists_without_deleting(self):
        removed, freed = _prune_logs(self.cfg, 7, dry_run=True)
        self.assertEqual(removed, [str(self.old_log)])
        self.assertGreater(freed, 0)
        self.assertTrue(self.old_log.exists())

    def test_only_old_job_logs_are_deleted(self):
        removed, _ = _prune_logs(self.cfg, 7, dry_run=False)
        self.assertEqual(removed, [str(self.old_log)])
        self.assertFalse(self.old_log.exists())
        self.assertTrue(self.new_log.exists(), "a recent log must stay")
        self.assertTrue(self.other.exists(), "a non-job file must never be touched")

    def test_zero_days_removes_all_job_logs(self):
        removed, _ = _prune_logs(self.cfg, 0, dry_run=False)
        self.assertIn(str(self.new_log), removed)
        self.assertFalse(self.old_log.exists())
        self.assertFalse(self.new_log.exists())
        self.assertTrue(self.other.exists())


if __name__ == "__main__":
    unittest.main()

import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from video2agent.config import Config
from video2agent.db import Database
from video2agent.util import Video2AgentError


class AnalyzeFailureStatusTest(unittest.TestCase):
    def test_failed_analyze_marks_video_failed(self):
        home = tempfile.mkdtemp(prefix="vp-analyze-fail-")
        cfg = Config(Path(home))
        from video2agent import cli as cli_module

        with Database(cfg.db_path) as db:
            job_id = db.create_job("ingest", "local:x", video_id="vid_t1", options={})
            db.update_job(job_id, state="running", stage="transcribing", progress=0.1, message="running")
            db.upsert_video({
                "id": "vid_t1", "source_kind": "local", "source_uri": "local:x",
                "source_path": "x", "sha256": None, "title": "t", "duration_ms": 1000,
                "width": None, "height": None, "fps": None, "language": None,
                "platform": "local", "status": "analyzing", "analysis_version": "1",
                "meta_json": "{}", "warnings_json": "[]",
                "created_at": "2026-11-14T00:00:00+00:00", "updated_at": "2026-11-14T00:00:00+00:00",
            })

        def boom(*args, **kwargs):
            raise Video2AgentError("E_ASR_NOT_CONFIGURED", "no model", "install one")

        with patch.object(cli_module, "analyze", boom):
            with self.assertRaises(Video2AgentError):
                cli_module._run_job(job_id, cfg)

        with Database(cfg.db_path) as db:
            video = db.get_video("vid_t1")
        self.assertEqual(video.get("status"), "failed")

import tempfile
import unittest
from pathlib import Path

from video2agent.config import Config
from video2agent.db import Database
from video2agent.pipeline import search


class TimestampOnlySearchTest(unittest.TestCase):
    def test_bare_timecode_does_not_fts_match_digits(self):
        cfg = Config(Path(tempfile.mkdtemp(prefix="vp-ts-search-")))
        with Database(cfg.db_path) as db:
            db.upsert_video({
                "id": "vid_ts", "source_kind": "local", "source_uri": "local:x",
                "source_path": "x", "sha256": None, "title": "t", "duration_ms": 600000,
                "width": None, "height": None, "fps": None, "language": None,
                "platform": "local", "status": "ready", "analysis_version": "1",
                "meta_json": "{}", "warnings_json": "[]",
                "created_at": "2026-01-01T00:00:00+00:00", "updated_at": "2026-01-01T00:00:00+00:00",
            })
            db.insert_segments("vid_ts", [
                {"start_ms": 0, "end_ms": 3000, "text": "00 10 数字无关的片段"},
                {"start_ms": 590000, "end_ms": 600000, "text": "真正的结尾"},
            ])
        result = search(cfg, "00:10:00")
        texts = [r.get("text") or (r.get("snippet") or "") for r in result.get("results") or []]
        self.assertFalse(any("数字无关" in str(t) for t in texts), "a bare timecode must not FTS-match digits")

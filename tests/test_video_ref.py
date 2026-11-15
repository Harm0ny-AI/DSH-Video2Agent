import tempfile
import unittest
from pathlib import Path

from video2agent.cli import resolve_video_ref
from video2agent.config import load_config
from video2agent.db import Database

VID = "vid_abc12345"
URL = "https://www.bilibili.com/video/BV1GJ411x7h7"


class ResolveVideoRefTest(unittest.TestCase):
    """A read command must accept the BV id a model just saw in find results."""

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.cfg = load_config(Path(self.tmp.name))
        with Database(self.cfg.db_path) as db:
            db.upsert_video({
                "id": VID,
                "source_kind": "url",
                "source_uri": URL,
                "source_path": None,
                "title": "t",
                "duration_ms": 1000,
                "status": "ready",
            })

    def tearDown(self):
        self.tmp.cleanup()

    def test_vid_passes_through(self):
        self.assertEqual(resolve_video_ref(self.cfg, VID), VID)

    def test_bv_id_resolves(self):
        self.assertEqual(resolve_video_ref(self.cfg, "BV1GJ411x7h7"), VID)

    def test_url_resolves(self):
        self.assertEqual(resolve_video_ref(self.cfg, URL), VID)

    def test_full_url_with_query_resolves(self):
        self.assertEqual(resolve_video_ref(self.cfg, URL + "?p=2"), VID)

    def test_unknown_ref_is_returned_unchanged(self):
        self.assertEqual(resolve_video_ref(self.cfg, "BV1ZZZZZZZZZ"), "BV1ZZZZZZZZZ")

    def test_empty_ref_is_returned_unchanged(self):
        self.assertEqual(resolve_video_ref(self.cfg, ""), "")


if __name__ == "__main__":
    unittest.main()
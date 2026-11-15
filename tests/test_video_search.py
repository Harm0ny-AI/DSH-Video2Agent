import tempfile
import unittest
from pathlib import Path

from video2agent.config import load_config
from video2agent.db import Database


class VideoMetaSearchTests(unittest.TestCase):
    """A title that exists must be findable: it was not indexed at all before."""

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.cfg = load_config(Path(self.tmp.name))
        self.db = Database(self.cfg.db_path)
        self.addCleanup(self.db.close)

    def test_title_is_searchable_after_upsert(self):
        from video2agent.text import fts_match_query

        self.db.upsert_video({
            "id": "vid_neurips", "title": "NeurIPS 2026 投稿指南", "source_kind": "local",
            "source_uri": "x", "duration_ms": 60000, "status": "ready",
        })
        rows = self.db.search_videos(fts_match_query("NeurIPS"))
        self.assertEqual([r["id"] for r in rows], ["vid_neurips"])

    def test_platform_description_is_searchable(self):
        from video2agent.text import fts_match_query

        self.db.upsert_video({
            "id": "vid_desc", "title": "一段普通标题", "source_kind": "url", "source_uri": "y",
            "duration_ms": 60000, "status": "ready",
            "meta_json": '{"description": "本期讲 量子纠缠 与 贝尔不等式"}',
        })
        rows = self.db.search_videos(fts_match_query("贝尔不等式"))
        self.assertEqual([r["id"] for r in rows], ["vid_desc"])

    def test_backfill_indexes_rows_written_before_the_table_existed(self):
        from video2agent.text import fts_match_query

        self.db.upsert_video({
            "id": "vid_old", "title": "旧记录 索引回填", "source_kind": "local",
            "source_uri": "z", "duration_ms": 1000, "status": "ready",
        })
        self.db.conn.execute("DELETE FROM video_fts")
        self.db.conn.commit()
        self.assertEqual(self.db.search_videos(fts_match_query("索引回填")), [])
        self.assertEqual(self.db.backfill_video_fts(), 1)
        self.assertEqual(len(self.db.search_videos(fts_match_query("索引回填"))), 1)


if __name__ == "__main__":
    unittest.main()

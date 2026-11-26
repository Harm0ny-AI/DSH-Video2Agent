import json
import tempfile
import unittest
from datetime import datetime, timezone
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

from video2agent import discover
from video2agent.config import load_config
from video2agent.util import Video2AgentError

CANDIDATES = [
    {"candidate_id": "bili_BV1a", "platform": "bilibili", "video_id": "BV1a", "url": "u1",
     "title": "a", "uploader": "李永乐老师", "uploader_id": "111", "published_at": "2026-10-20",
     "published_ts": 1792454400, "description": "", "tags": ""},
    {"candidate_id": "bili_BV1b", "platform": "bilibili", "video_id": "BV1b", "url": "u2",
     "title": "b", "uploader": "影视飓风", "uploader_id": "222", "published_at": "2026-10-01",
     "published_ts": 1790812800, "description": "", "tags": ""},
    {"candidate_id": "bili_BV1c", "platform": "bilibili", "video_id": "BV1c", "url": "u3",
     "title": "c", "uploader": "李永乐老师", "uploader_id": "111", "published_at": "2026-08-01",
     "published_ts": 1785542400, "description": "", "tags": ""},
]


class DateBoundTests(unittest.TestCase):
    def test_iso_and_slash_dates(self):
        self.assertEqual(discover.parse_date_bound("2026-10-01"),
                         discover.parse_date_bound("2026/10/01"))
        self.assertIsNotNone(discover.parse_date_bound("2026-10-01"))

    def test_relative_days_weeks_months(self):
        now = datetime(2026, 10, 26, tzinfo=timezone.utc)
        week = discover.parse_date_bound("7d", now=now)
        two_weeks = discover.parse_date_bound("2w", now=now)
        month = discover.parse_date_bound("1m", now=now)
        self.assertEqual((now.timestamp() - week) / 86400, 7.0)
        self.assertEqual((now.timestamp() - two_weeks) / 86400, 14.0)
        self.assertEqual((now.timestamp() - month) / 86400, 30.0)

    def test_empty_is_none_and_nonsense_raises(self):
        self.assertIsNone(discover.parse_date_bound(""))
        self.assertIsNone(discover.parse_date_bound(None))
        with self.assertRaises(Video2AgentError) as ctx:
            discover.parse_date_bound("上周")
        self.assertEqual(ctx.exception.code, "E_DATE")


class FilterTests(unittest.TestCase):
    def test_uploader_by_name_and_by_uid(self):
        kept, report = discover.apply_filters(CANDIDATES, uploader="李永乐")
        self.assertEqual(len(kept), 2)
        self.assertEqual(report["dropped"], 1)
        by_uid, _ = discover.apply_filters(CANDIDATES, uploader="111")
        self.assertEqual({c["video_id"] for c in by_uid}, {"BV1a", "BV1c"})

    def test_date_window_keeps_only_the_range(self):
        kept, _ = discover.apply_filters(CANDIDATES, after="2026-10-10", before="2026-10-25")
        self.assertEqual([c["video_id"] for c in kept], ["BV1a"])

    def test_backwards_window_is_an_error(self):
        with self.assertRaises(Video2AgentError) as ctx:
            discover.apply_filters(CANDIDATES, after="2026-10-20", before="2026-10-01")
        self.assertEqual(ctx.exception.code, "E_DATE")

    def test_missing_timestamp_is_dropped_not_assumed(self):
        no_ts = [{"video_id": "BV1z", "uploader": "x", "published_ts": None}]
        kept, report = discover.apply_filters(no_ts, after="2026-01-01")
        self.assertEqual(kept, [])
        self.assertEqual(report["dropped"], 1)


class DiscoverWithFiltersTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.cfg = load_config(Path(self.tmp.name))

    def _run(self, **filters):
        pages = {1: list(CANDIDATES), 2: []}

        def fake(query, limit, page=1):  # noqa: ARG001
            return [dict(c) for c in pages.get(page, [])]

        with patch.object(discover, "_api_candidates", side_effect=fake):
            return discover.discover_bilibili("注意力", self.cfg, limit=5, covers=False, **filters)

    def test_filters_are_applied_and_reported(self):
        result = self._run(uploader="李永乐老师", after="2026-08-15")
        self.assertEqual({c["video_id"] for c in result["candidates"]}, {"BV1a"})
        self.assertEqual(result["filters"]["uploader"], "李永乐老师")
        self.assertEqual(result["filters"]["after"], "2026-08-15")
        self.assertEqual(result["filters"]["matched"], 1)
        self.assertEqual(result["filters"]["dropped"], 2)

    def test_no_match_says_so_instead_of_returning_empty(self):
        result = self._run(uploader="不存在的UP")
        self.assertEqual(result["candidates"], [])
        codes = [w["code"] for w in result["warnings"]]
        self.assertIn("FILTER_EMPTY", codes)

    def test_bad_date_is_an_error_not_a_silent_ignore(self):
        with self.assertRaises(Video2AgentError) as ctx:
            self._run(after="随便")
        self.assertEqual(ctx.exception.code, "E_DATE")

    def test_filtered_search_scans_page_two_even_when_page_one_is_full(self):
        page1 = [{"candidate_id": f"bili_BV1p{i}", "video_id": f"BV1p{i}", "url": f"u{i}",
                  "title": f"p{i}", "uploader": "其他人", "uploader_id": "1",
                  "published_at": "2026-10-20", "published_ts": 1792454400,
                  "description": "", "tags": ""} for i in range(20)]
        page2 = [{"candidate_id": "bili_BV2match", "video_id": "BV2match", "url": "u2",
                  "title": "match", "uploader": "目标UP", "uploader_id": "2",
                  "published_at": "2026-10-20", "published_ts": 1792454400,
                  "description": "", "tags": ""}]
        calls = []

        def fake(query, limit, page=1):  # noqa: ARG001
            calls.append(page)
            return page1 if page == 1 else page2 if page == 2 else []

        with patch.object(discover, "_api_candidates", side_effect=fake):
            result = discover.discover_bilibili("注意力", self.cfg, limit=8, covers=False, uploader="目标UP")
        self.assertEqual([c["video_id"] for c in result["candidates"]], ["BV2match"])
        self.assertIn(2, calls, "filtered search must scan page 2 when page 1 is full")

    def test_candidates_keep_the_uploader_id(self):
        result = self._run()
        self.assertTrue(all("uploader_id" in c for c in result["candidates"]))

    def test_fallback_keeps_only_candidates_with_verified_filters(self):
        entries = [
            {"id": "BV1match", "title": "匹配", "uploader_id": "123", "upload_date": "20260121"},
            {"id": "BV1other", "title": "其他作者", "uploader_id": "456", "upload_date": "20260121"},
            {"id": "BV1older", "title": "日期太早", "uploader_id": "123", "upload_date": "20240121"},
            {"id": "BV1unknown", "title": "日期缺失", "uploader_id": "123"},
        ]
        response = SimpleNamespace(ok=True, stdout="\n".join(json.dumps(row) for row in entries))
        with patch.object(discover, "_api_candidates", side_effect=RuntimeError("API unavailable")), \
                patch("video2agent.sources.run", return_value=response):
            result = discover.discover_bilibili(
                "注意力", self.cfg, covers=False, uploader="123", after="2026-01-01",
            )
            self.assertEqual([row["video_id"] for row in result["candidates"]], ["BV1match"])
            self.assertEqual(result["filters"]["dropped"], 3)
            self.assertEqual([w["code"] for w in result["warnings"]], ["SEARCH_FALLBACK"])

            empty = discover.discover_bilibili("注意力", self.cfg, covers=False, after="2030-01-01")
            self.assertEqual(empty["candidates"], [])
            self.assertIn("FILTER_EMPTY", {w["code"] for w in empty["warnings"]})


if __name__ == "__main__":
    unittest.main()

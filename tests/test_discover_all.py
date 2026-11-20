import unittest
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest.mock import patch

from video2agent.config import load_config
from video2agent.discover import discover_all
from video2agent.util import Video2AgentError


def _candidate(platform, video_id):
    return {"platform": platform, "video_id": video_id, "candidate_id": f"{platform}_{video_id}", "title": video_id}


class DiscoverAllTest(unittest.TestCase):
    def _cfg(self, td):
        return load_config(Path(td))

    def test_merges_both_platforms(self):
        bili = {"platform": "bilibili", "candidates": [_candidate("bilibili", "b1"), _candidate("bilibili", "b2")], "filters": {}, "warnings": []}
        douyin = {"platform": "douyin", "candidates": [_candidate("douyin", "d1"), _candidate("douyin", "d2")], "filters": {}, "warnings": []}
        with TemporaryDirectory() as td, \
                patch("video2agent.discover.discover_bilibili", return_value=bili), \
                patch("video2agent.douyin_search.discover_douyin", return_value=douyin):
            result = discover_all("x", self._cfg(td), limit=3)
        self.assertEqual(result["platform"], "all")
        self.assertEqual(result["platforms"], {"bilibili": 2, "douyin": 1})
        self.assertEqual(result["found"], {"bilibili": 2, "douyin": 2})
        self.assertEqual([c["video_id"] for c in result["candidates"]], ["b1", "d1", "b2"])

    def test_one_platform_failure_is_partial(self):
        bili = {"platform": "bilibili", "candidates": [_candidate("bilibili", "b1")], "filters": {}, "warnings": []}
        with TemporaryDirectory() as td, \
                patch("video2agent.discover.discover_bilibili", return_value=bili), \
                patch("video2agent.douyin_search.discover_douyin", side_effect=Video2AgentError("E_DOUYIN_LOGIN", "no login", "login")):
            result = discover_all("x", self._cfg(td), limit=3)
        self.assertEqual([c["video_id"] for c in result["candidates"]], ["b1"])
        self.assertTrue(any(w["code"] == "PLATFORM_FAILED" and w["platform"] == "douyin" for w in result["warnings"]))

    def test_both_failures_raise(self):
        with TemporaryDirectory() as td, \
                patch("video2agent.discover.discover_bilibili", side_effect=RuntimeError("bili down")), \
                patch("video2agent.douyin_search.discover_douyin", side_effect=Video2AgentError("E_DOUYIN_LOGIN", "no login", "login")):
            with self.assertRaises(Video2AgentError) as ctx:
                discover_all("x", self._cfg(td), limit=3)
        self.assertEqual(ctx.exception.code, "E_SEARCH")


if __name__ == "__main__":
    unittest.main()

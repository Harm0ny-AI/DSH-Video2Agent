import random
import tempfile
import unittest
from pathlib import Path
from unittest.mock import MagicMock, patch
from urllib.parse import parse_qs, urlsplit

from video2agent._abogus import ABogus, structure_error
from video2agent.config import load_config
from video2agent.douyin_search import _candidate, discover_douyin
from video2agent.util import Video2AgentError


class DouyinSearchTest(unittest.TestCase):
    def test_candidate_shape(self):
        item = {
            "aweme_info": {
                "aweme_id": "7619596768929484075",
                "desc": "蓝莓为什么便宜了",
                "create_time": 1763000000,
                "author": {"nickname": "科普作者", "uid": "123"},
                "video": {
                    "duration": 697878,
                    "cover": {"url_list": ["https://example.invalid/cover.jpg"]},
                },
                "statistics": {"play_count": 10, "digg_count": 3},
            }
        }
        c = _candidate(item)
        self.assertIsNotNone(c)
        assert c is not None
        self.assertEqual(c["platform"], "douyin")
        self.assertEqual(c["video_id"], "7619596768929484075")
        self.assertEqual(c["url"], "https://www.douyin.com/video/7619596768929484075")
        self.assertEqual(c["duration_ms"], 697878)
        self.assertEqual(c["uploader"], "科普作者")
        self.assertEqual(c["stats"], {"play_count": 10, "digg_count": 3})
        self.assertTrue(c["cover_url"].startswith("https://"))

    def test_search_requires_login(self):
        with tempfile.TemporaryDirectory() as td:
            cfg = load_config(Path(td))
            with self.assertRaises(Video2AgentError) as ctx:
                discover_douyin("蓝莓", cfg)
            self.assertEqual(ctx.exception.code, "E_DOUYIN_LOGIN")

    def _search_with_body(self, body):
        with tempfile.TemporaryDirectory() as td:
            cfg = load_config(Path(td))
            response = MagicMock()
            response.status_code = 200
            response.json.return_value = body
            with patch("video2agent.douyin_search._cookies", return_value=("s=1", {"UIFID": "u"})), \
                    patch("video2agent.douyin_search.requests.get", return_value=response):
                return discover_douyin("蓝莓", cfg, limit=3)

    def test_a_verify_check_nil_response_is_reported_as_risk(self):
        # Live 2026-11-20: after a few searches Douyin answered 200/status 0 with
        # an empty list and search_nil_info.search_nil_type="verify_check". The
        # old code called that NO_RESULTS, so a real block looked like a harmless
        # empty search.
        with patch("video2agent.browser.search_videos", side_effect=Video2AgentError("E_DOUYIN_VERIFY", "需要验证", "稍后重试")), \
                self.assertRaises(Video2AgentError) as ctx:
            self._search_with_body({
                "status_code": 0,
                "data": [],
                "search_nil_info": {"search_nil_type": "verify_check", "search_nil_item": "verify_check"},
            })
        self.assertEqual(ctx.exception.code, "E_DOUYIN_VERIFY")
        self.assertIn("人机验证", ctx.exception.message)

    def test_a_genuinely_empty_search_stays_no_results(self):
        result = self._search_with_body({
            "status_code": 0,
            "data": [],
            "search_nil_info": {"search_nil_type": "no_result"},
        })
        self.assertEqual(result["candidates"], [])
        self.assertEqual([w["code"] for w in result["warnings"]], ["NO_RESULTS"])

    def test_a_verify_marker_does_not_discard_real_results(self):
        result = self._search_with_body({
            "status_code": 0,
            "data": [{"aweme_info": {
                "aweme_id": "7619596768929484075",
                "desc": "蓝莓为什么便宜了",
                "author": {"nickname": "科普作者"},
            }}],
            "search_nil_info": {"search_nil_type": "verify_check"},
        })
        self.assertEqual(len(result["candidates"]), 1)

    def test_image_post_candidate_is_skipped(self):
        # Live 2026-11-23: a 图文 post (images, aweme_type 68, no duration) came back
        # first for "蓝莓" and ingesting it failed with a 404 on its music mp3.
        candidate = _candidate({"aweme_info": {
            "aweme_id": "7628547330606783739",
            "desc": "蓝莓发霉",
            "aweme_type": 68,
            "images": [{"url_list": ["https://example.invalid/a.jpg"]}],
        }})
        self.assertIsNone(candidate)

    def test_image_posts_are_skipped_with_a_warning(self):
        result = self._search_with_body({
            "status_code": 0,
            "has_more": 0,
            "data": [
                {"aweme_info": {"aweme_id": "7628547330606783739", "desc": "蓝莓发霉",
                                "images": [{"url_list": ["https://example.invalid/a.jpg"]}]}},
                {"aweme_info": {"aweme_id": "7619596768929484075", "desc": "蓝莓视频"}},
            ],
        })
        self.assertEqual([c["video_id"] for c in result["candidates"]], ["7619596768929484075"])
        self.assertIn("IMAGE_POSTS_SKIPPED", [w["code"] for w in result["warnings"]])

    def test_pagination_uses_cursor_and_search_id(self):
        first = MagicMock(status_code=200)
        first.json.return_value = {
            "status_code": 0,
            "data": [],
            "has_more": 1,
            "cursor": 20,
            "log_pb": {"impr_id": "s1"},
        }
        second = MagicMock(status_code=200)
        second.json.return_value = {
            "status_code": 0,
            "data": [{"aweme_info": {"aweme_id": "7619596768929484075", "desc": "蓝莓"}}],
            "has_more": 0,
            "cursor": 40,
        }
        with tempfile.TemporaryDirectory() as td:
            cfg = load_config(Path(td))
            with patch("video2agent.douyin_search._cookies", return_value=("s=1", {"UIFID": "u"})), \
                    patch("video2agent.douyin_search.requests.get", side_effect=[first, second]) as get:
                result = discover_douyin("蓝莓", cfg, limit=3)
        self.assertEqual(result["pages"], 2)
        self.assertEqual(len(result["candidates"]), 1)
        self.assertEqual(get.call_count, 2)
        second_query = parse_qs(urlsplit(get.call_args_list[1].args[0]).query)
        self.assertEqual(second_query["offset"], ["20"])
        self.assertEqual(second_query["search_id"], ["s1"])

    def test_success_is_cached(self):
        body = {"status_code": 0, "data": [{"aweme_info": {"aweme_id": "7619596768929484075", "desc": "蓝莓"}}], "has_more": 0}
        first = MagicMock(status_code=200)
        first.json.return_value = body
        with tempfile.TemporaryDirectory() as td:
            cfg = load_config(Path(td))
            with patch("video2agent.douyin_search._cookies", return_value=("s=1", {"UIFID": "u"})), \
                    patch("video2agent.douyin_search.requests.get", return_value=first):
                one = discover_douyin("蓝莓", cfg, limit=3)
            with patch("video2agent.douyin_search.requests.get", side_effect=AssertionError("cache miss")):
                two = discover_douyin("蓝莓", cfg, limit=3)
        self.assertEqual(one["candidates"], two["candidates"])
        self.assertTrue(two.get("cached"))

    def test_verify_is_retryable_without_cooldown(self):
        verify = MagicMock(status_code=200)
        verify.json.return_value = {
            "status_code": 0,
            "data": [],
            "search_nil_info": {"search_nil_type": "verify_check"},
        }
        success = MagicMock(status_code=200)
        success.json.return_value = {"status_code": 0, "data": [], "has_more": 0}
        with tempfile.TemporaryDirectory() as td:
            cfg = load_config(Path(td))
            with patch("video2agent.douyin_search._cookies", return_value=("s=1", {"UIFID": "u"})), \
                    patch("video2agent.douyin_search.requests.get", return_value=verify), \
                    patch("video2agent.browser.search_videos", side_effect=Video2AgentError("E_DOUYIN_VERIFY", "需要验证", "稍后重试")):
                with self.assertRaises(Video2AgentError) as ctx:
                    discover_douyin("蓝莓", cfg, limit=3)
            self.assertEqual(ctx.exception.code, "E_DOUYIN_VERIFY")
            with patch("video2agent.douyin_search._cookies", return_value=("s=1", {"UIFID": "u"})), \
                    patch("video2agent.douyin_search.requests.get", return_value=success):
                two = discover_douyin("蓝莓", cfg, limit=3)
            self.assertEqual(two["candidates"], [])
            self.assertEqual(two["warnings"][0]["code"], "NO_RESULTS")

    def test_verify_falls_back_to_logged_in_browser(self):
        verify = MagicMock(status_code=200)
        verify.json.return_value = {
            "status_code": 0,
            "data": [],
            "search_nil_info": {"search_nil_type": "verify_check"},
        }
        candidate = {
            "candidate_id": "douyin_7619596768929484075",
            "platform": "douyin",
            "video_id": "7619596768929484075",
            "url": "https://www.douyin.com/video/7619596768929484075",
            "title": "蓝莓",
            "cover_url": "",
            "duration_ms": 30000,
            "uploader": "科普作者",
            "uploader_id": None,
            "published_at": None,
            "published_ts": None,
            "description": "蓝莓",
            "tags": "",
            "stats": {},
        }
        with tempfile.TemporaryDirectory() as td:
            cfg = load_config(Path(td))
            with patch("video2agent.douyin_search._cookies", return_value=("s=1", {"UIFID": "u"})), \
                    patch("video2agent.douyin_search.requests.get", return_value=verify), \
                    patch("video2agent.browser.search_videos", return_value=[candidate]):
                result = discover_douyin("蓝莓", cfg, limit=3)
        self.assertEqual(len(result["candidates"]), 1)
        self.assertEqual(result["warnings"][0]["code"], "DOUYIN_BROWSER_FALLBACK")

    def test_abogus_is_well_formed(self):
        value = ABogus(
            "Mozilla/5.0 (Windows NT 10.0; Win64; x64) Chrome/146.0.0.0",
            rng=random.Random(0),
        ).get_value("a=1&b=2")
        self.assertTrue(value)
        self.assertIsNone(structure_error(value))


if __name__ == "__main__":
    unittest.main()

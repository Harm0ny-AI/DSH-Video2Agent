import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from video2agent import captions
from video2agent.config import load_config

COOKIE_LINES = [
    "# Netscape HTTP Cookie File",
    ".bilibili.com\tTRUE\t/\tFALSE\t1999999999\tSESSDATA\tabc%2C123",
    ".bilibili.com\tTRUE\t/\tFALSE\t1999999999\tbuvid3\ttest-buvid",
]


class CaptionParseTests(unittest.TestCase):
    def test_parse_body_to_millisecond_segments(self):
        payload = {"body": [
            {"from": 12.34, "to": 14.5, "content": "第一句"},
            {"from": 0.5, "to": 2.0, "content": "  开头一句  "},
            {"from": 3.0, "to": 4.0, "content": ""},
        ]}
        segments = captions.parse_caption_json(payload)
        self.assertEqual([s["start_ms"] for s in segments], [500, 12340])
        self.assertEqual(segments[0]["text"], "开头一句")
        self.assertEqual(segments[1]["end_ms"], 14500)
        self.assertTrue(all(s["source"] == "caption" for s in segments))

    def test_missing_or_broken_timing_is_tolerated(self):
        payload = {"body": [{"from": 5, "content": "无结尾"}, {"to": 9, "content": "无开头"}]}
        segments = captions.parse_caption_json(payload)
        self.assertEqual(len(segments), 2)
        by_text = {s["text"]: s for s in segments}
        self.assertEqual(by_text["无结尾"]["start_ms"], 5000)
        self.assertEqual(by_text["无结尾"]["end_ms"], 6500)
        self.assertEqual(by_text["无开头"]["start_ms"], 0)
        self.assertEqual(by_text["无开头"]["end_ms"], 9000)

    def test_non_body_payload_returns_empty(self):
        self.assertEqual(captions.parse_caption_json(None), [])
        self.assertEqual(captions.parse_caption_json({}), [])
        self.assertEqual(captions.parse_caption_json({"body": "nope"}), [])


class TrackPreferenceTests(unittest.TestCase):
    def test_human_chinese_beats_ai_chinese_beats_english(self):
        tracks = [
            {"lan": "en-US", "lan_doc": "English", "ai": False, "url": "en"},
            {"lan": "ai-zh", "lan_doc": "中文（AI）", "ai": True, "url": "ai-zh"},
            {"lan": "zh-Hans", "lan_doc": "中文（中国）", "ai": False, "url": "zh"},
        ]
        # rank_tracks is the production ordering; pick_track was its single-result
        # predecessor and has been removed.
        ranked = captions.rank_tracks(tracks)
        self.assertEqual(ranked[0]["url"], "zh")
        ai_only = [t for t in tracks if t["url"] != "zh"]
        self.assertEqual(captions.rank_tracks(ai_only)[0]["url"], "ai-zh")
        self.assertEqual(captions.rank_tracks([]), [])


class CookieTests(unittest.TestCase):
    def test_netscape_parsing_and_login_detection(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "cookies.txt"
            path.write_text("\n".join(COOKIE_LINES) + "\n", encoding="utf-8")
            jar = captions.load_netscape_cookies(path)
            self.assertEqual(jar["SESSDATA"], "abc%2C123")
            self.assertTrue(captions.is_logged_in(jar))
            self.assertFalse(captions.is_logged_in({}))
            self.assertEqual(captions.load_netscape_cookies(Path(tmp) / "missing.txt"), {})


class BilibiliCaptionsTests(unittest.TestCase):
    def _cfg(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        return load_config(Path(tmp.name))

    def test_video_cid_uses_the_requested_page(self):
        payload = {"data": {"pages": [{"cid": 11}, {"cid": 22}]}}
        with patch.object(captions, "_get_json", return_value=payload):
            self.assertEqual(captions.video_cid("BV1xx411c7mD", object(), page=2), 22)
            self.assertEqual(captions.video_cid("BV1xx411c7mD", object(), page=99), 11)

    def test_no_cid_reports_reason_without_raising(self):
        with patch.object(captions, "_session", return_value=(object(), False)), \
                patch.object(captions, "video_cid", return_value=None):
            result = captions.bilibili_captions("BV1xx411c7mD", self._cfg())
        self.assertEqual(result["segments"], [])
        self.assertEqual(result["reason"], "no_cid")
        self.assertFalse(result["logged_in"])

    def test_anonymous_empty_subtitles_is_reported_as_not_logged_in(self):
        with patch.object(captions, "_session", return_value=(object(), False)), \
                patch.object(captions, "video_cid", return_value=42), \
                patch.object(captions, "subtitle_tracks", return_value=[]):
            result = captions.bilibili_captions("BV1xx411c7mD", self._cfg())
        self.assertEqual(result["reason"], "no_tracks")
        self.assertFalse(result["logged_in"])

    def test_picks_track_and_returns_segments_with_provenance(self):
        tracks = [
            {"lan": "en-US", "lan_doc": "English", "ai": False, "url": "https://x/en.json"},
            {"lan": "zh-Hans", "lan_doc": "中文（中国）", "ai": False, "url": "https://x/zh.json"},
        ]
        payload = {"body": [{"from": 1.0, "to": 2.5, "content": "UP 主校验过的字幕"}]}
        with patch.object(captions, "_session", return_value=(object(), True)), \
                patch.object(captions, "video_cid", return_value=42), \
                patch.object(captions, "subtitle_tracks", return_value=tracks), \
                patch.object(captions, "fetch_track", return_value=captions.parse_caption_json(payload)):
            result = captions.bilibili_captions("BV1xx411c7mD", self._cfg())
        self.assertEqual(result["reason"], "ok")
        self.assertTrue(result["logged_in"])
        self.assertEqual(result["track"]["lan"], "zh-Hans")
        self.assertFalse(result["track"]["ai"])
        self.assertEqual(result["segments"][0]["text"], "UP 主校验过的字幕")
        self.assertEqual(result["segments"][0]["start_ms"], 1000)
        self.assertEqual(result["track"]["kind"], "human")
        self.assertEqual([t["lan"] for t in result["tracks"]], ["en-US", "zh-Hans"])

    def test_retries_when_the_track_list_is_rate_limited(self):
        """An empty subtitle_url means rate limiting; a retry must re-ask the API."""
        payload = {"body": [{"from": 1.0, "to": 2.0, "content": "第二次才拿到"}]}
        calls = {"n": 0}

        def fake_tracks(bvid, cid, session):
            calls["n"] += 1
            if calls["n"] == 1:
                return []
            return [{"lan": "ai-zh", "lan_doc": "中文（AI）", "ai": True, "kind": "ai", "url": "https://x/ai.json"}]

        with patch.object(captions, "_session", return_value=(object(), True)), \
                patch.object(captions, "video_cid", return_value=42), \
                patch.object(captions, "subtitle_tracks", side_effect=fake_tracks), \
                patch.object(captions, "fetch_track", return_value=captions.parse_caption_json(payload)), \
                patch.object(captions.time, "sleep", return_value=None):
            result = captions.bilibili_captions("BV1xx411c7mD", self._cfg())
        self.assertEqual(result["reason"], "ok")
        self.assertEqual(result["track"]["kind"], "ai")
        self.assertEqual(calls["n"], 2, "a rate-limited list must be re-requested")

    def test_empty_body_is_retried_then_reported(self):
        tracks = [{"lan": "zh-Hans", "lan_doc": "中文", "ai": False, "kind": "human", "url": "https://x/zh.json"}]
        with patch.object(captions, "_session", return_value=(object(), True)), \
                patch.object(captions, "video_cid", return_value=42), \
                patch.object(captions, "subtitle_tracks", return_value=tracks), \
                patch.object(captions, "fetch_track", return_value=[]), \
                patch.object(captions.time, "sleep", return_value=None) as slept:
            result = captions.bilibili_captions("BV1xx411c7mD", self._cfg(), attempts=3)
        self.assertEqual(result["reason"], "empty")
        self.assertEqual(result["segments"], [])
        self.assertEqual(slept.call_count, 2, "each failed attempt should back off before retrying")


if __name__ == "__main__":
    unittest.main()

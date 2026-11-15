import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from video2agent.config import load_config
from video2agent.pipeline import resolve_info
from video2agent.util import Video2AgentError

CANONICAL = "https://www.bilibili.com/video/BV17x411w7KC/"
META = {
    "title": "demo", "uploader": "tester", "duration": 90.5,
    "thumbnail": "http://i0.hdslb.com/cover.jpg",
    "webpage_url": "https://www.bilibili.com/video/BV17x411w7KC",
    "extractor_key": "BiliBili",
}


class ResolveTests(unittest.TestCase):
    def _resolve(self, url, meta=None):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        cfg = load_config(Path(tmp.name))
        with patch("video2agent.pipeline.assert_public_url"), \
                patch("video2agent.pipeline.bilibili_view_metadata", return_value=None), \
                patch("video2agent.pipeline.fetch_metadata", return_value=meta or META) as fetch:
            data = resolve_info(cfg, url)
        return data, fetch

    def test_video_link_shape_and_https_cover(self):
        data, _ = self._resolve("https://www.bilibili.com/video/BV17x411w7KC")
        self.assertEqual(data["kind"], "video-link")
        self.assertEqual(data["duration_ms"], 90500)
        self.assertTrue(data["cover_url"].startswith("https://"))
        self.assertEqual(data["title"], "demo")

    def test_existing_json_keys_are_kept(self):
        data, _ = self._resolve("https://www.bilibili.com/video/BV17x411w7KC")
        for key in ("ok", "kind", "url", "platform", "title", "uploader",
                    "duration_ms", "duration", "cover_url", "description"):
            self.assertIn(key, data)

    def test_av_url_resolves_as_bv(self):
        data, fetch = self._resolve("https://www.bilibili.com/video/av170001")
        self.assertEqual(fetch.call_args[0][0], CANONICAL)
        self.assertEqual(data["url"], CANONICAL)
        self.assertEqual(data["bvid"], "BV17x411w7KC")
        self.assertEqual(data["av_id"], 170001)

    def test_bare_bv_and_av_accepted(self):
        data, fetch = self._resolve("BV17x411w7KC")
        self.assertEqual(fetch.call_args[0][0], CANONICAL)
        self.assertEqual(data["url"], CANONICAL)
        self.assertEqual(data["input_kind"], "bv")
        data, fetch = self._resolve("av170001")
        self.assertEqual(fetch.call_args[0][0], CANONICAL)
        self.assertEqual(data["input_kind"], "av")

    def test_short_link_resolves_to_canonical_bv(self):
        with patch("video2agent.links._resolve_shortlink",
                   return_value="https://www.bilibili.com/video/BV17x411w7KC/?share_source=copy"):
            data, fetch = self._resolve("https://b23.tv/AbCdEf")
        self.assertEqual(fetch.call_args[0][0], CANONICAL)
        self.assertEqual(data["url"], CANONICAL)
        self.assertEqual(data["input_kind"], "shortlink")

    def test_short_link_failure_is_structured(self):
        boom = Video2AgentError("E_SHORTLINK", "Short link could not be resolved", "Paste the full URL.")
        with patch("video2agent.links._resolve_shortlink", side_effect=boom):
            with self.assertRaises(Video2AgentError) as ctx:
                self._resolve("https://b23.tv/AbCdEf")
        self.assertEqual(ctx.exception.code, "E_SHORTLINK")
        self.assertTrue(ctx.exception.remedy)

    def test_unknown_input_is_structured(self):
        with self.assertRaises(Video2AgentError) as ctx:
            self._resolve("这不是一个链接")
        self.assertEqual(ctx.exception.code, "E_URL")
        self.assertTrue(ctx.exception.remedy)


if __name__ == "__main__":
    unittest.main()

import tempfile
import unittest
from pathlib import Path
from unittest.mock import MagicMock, patch

from video2agent import douyin, links
from video2agent.config import load_config
from video2agent.util import Video2AgentError

FIXTURES = Path(__file__).resolve().parent / "fixtures"


class DouyinLinkTests(unittest.TestCase):
    def test_canonical_share_modal_and_share_text(self):
        cases = {
            "https://www.douyin.com/video/7704519391488134410": "7704519391488134410",
            "https://www.iesdouyin.com/share/video/7704519391488134410/": "7704519391488134410",
            "https://www.douyin.com/discover?modal_id=7704519391488134410": "7704519391488134410",
            "7.85 复制打开抖音 https://v.douyin.com/s-GVFhZGxtk/ 看看": "s-GVFhZGxtk",
        }
        for text, expected in cases.items():
            ref = links.extract_ref(text)
            self.assertIsNotNone(ref, text)
            self.assertEqual(ref["platform"], "douyin")
            if ref["kind"] == "douyin_shortlink":
                self.assertEqual(ref["token"], expected)
            else:
                self.assertEqual(ref["aweme_id"], expected)

    def test_bilibili_refs_still_work(self):
        ref = links.extract_ref("BV1xx411c7mD")
        self.assertEqual(ref["platform"] if ref.get("platform") else None, None)
        self.assertEqual(ref["bvid"], "BV1xx411c7mD")

    def test_shortlink_normalizes_to_canonical(self):
        with patch.object(links, "resolve_douyin_shortlink", return_value="7704519391488134410"):
            ref = links.normalize_video_ref("https://v.douyin.com/s-GVFhZGxtk/")
        self.assertEqual(ref["kind"], "douyin")
        self.assertEqual(ref["url"], "https://www.douyin.com/video/7704519391488134410")
        self.assertEqual(ref["input_kind"], "shortlink")

    def test_invalid_shortlink_raises(self):
        with patch("requests.get") as get:
            get.return_value = MagicMock(status_code=302, headers={"Location": "https://www.douyin.com/"})
            with self.assertRaises(Video2AgentError) as ctx:
                links.resolve_douyin_shortlink("bad-token")
        self.assertEqual(ctx.exception.code, "E_DOUYIN_SHORTLINK")


class DouyinParseTests(unittest.TestCase):
    def test_share_fixture_maps_fields(self):
        html = (FIXTURES / "douyin_share.html").read_text(encoding="utf-8")
        item = douyin.parse_share_html(html)
        self.assertEqual(item["aweme_id"], "7704519391488134410")
        self.assertIn("Token", item["title"])
        self.assertEqual(item["author"]["unique_id"], "abouttao")
        self.assertEqual(item["author"]["nickname"], "anChaOs")
        self.assertEqual(item["duration_ms"], 1225967)
        self.assertTrue(item["cover_url"].startswith("https://"))
        self.assertEqual(item["play_uri"], "v0d00fg10000dblup2nog65mudtj6ig0")
        self.assertEqual(item["stats"]["like"], 7)
        self.assertEqual(item["create_time"], 1794019200)

    def test_shell_page_has_no_item(self):
        self.assertIsNone(douyin.parse_share_html("<html>no data</html>"))

    def test_play_urls_prefer_no_watermark(self):
        item = {"play_uri": "v0d00fg", "play_url": "https://aweme.snssdk.com/playwm/?video_id=x"}
        urls = douyin.play_urls(item)
        self.assertTrue(urls[0].startswith("https://aweme.snssdk.com/aweme/v1/play/"))
        self.assertIn("video_id=v0d00fg", urls[0])
        self.assertIn("playwm", urls[-1])
        self.assertEqual(len(urls), len(set(urls)))


class _Resp:
    def __init__(self, status=200, text=""):
        self.status_code = status
        self.text = text


class DouyinFetchTests(unittest.TestCase):
    def test_get_item_retries_risk_page(self):
        html = (FIXTURES / "douyin_share.html").read_text(encoding="utf-8")
        responses = [_Resp(200, "<html>验证码中间页</html>"), _Resp(200, html)]

        class FakeSession:
            headers = {}

            def get(self, url, timeout=None):
                return responses.pop(0)

        with patch.object(douyin, "_bootstrap"), patch.object(douyin, "_session", return_value=FakeSession()), patch.object(douyin.time, "sleep"):
            item = douyin.get_item("7704519391488134410", attempts=2)
        self.assertEqual(item["aweme_id"], "7704519391488134410")

    def test_get_item_raises_risk_after_attempts(self):
        class FakeSession:
            headers = {}

            def get(self, url, timeout=None):
                return _Resp(200, "<html>验证码中间页</html>")

        with patch.object(douyin, "_bootstrap"), patch.object(douyin, "_session", return_value=FakeSession()), patch.object(douyin.time, "sleep"):
            with self.assertRaises(Video2AgentError) as ctx:
                douyin.get_item("7704519391488134410", attempts=2)
        self.assertEqual(ctx.exception.code, "E_DOUYIN_RISK")
        self.assertIn("verification", ctx.exception.message)


class DouyinDownloadTests(unittest.TestCase):
    def test_download_streams_mp4(self):
        with tempfile.TemporaryDirectory() as tmp:
            dest = Path(tmp) / "source.mp4"

            class Resp:
                status_code = 200
                headers = {"Content-Type": "video/mp4"}

                def __enter__(self):
                    return self

                def __exit__(self, *args):
                    return False

                def raise_for_status(self):
                    return None

                def iter_content(self, chunk_size=1):
                    yield b"x" * 60000

            with patch("requests.get", return_value=Resp()):
                out = douyin.download({"play_uri": "v0d00fg", "play_url": ""}, dest)
            self.assertEqual(out, dest)
            self.assertGreater(dest.stat().st_size, 50000)
            self.assertFalse(dest.with_suffix(".mp4.part").exists())


class DouyinSourceTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory(prefix="vp-dy-")
        self.cfg = load_config(self.tmp.name)

    def tearDown(self):
        self.tmp.cleanup()

    def test_source_builds_ingestable_dict(self):
        item = {
            "aweme_id": "7704519391488134410",
            "title": "测试视频",
            "description": "测试视频",
            "author": {"nickname": "anChaOs", "unique_id": "abouttao", "sec_uid": "sec", "uid": "1"},
            "duration_ms": 1225967,
            "cover_url": "https://example.com/cover.jpg",
            "play_uri": "v0d00fg",
            "play_url": "",
            "create_time": 1794019200,
            "stats": {"view": 1, "like": 2, "comment": 3, "share": 4, "collect": 5},
            "music": "原声",
        }

        def fake_download(_item, dest, **kwargs):
            path = Path(dest)
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_bytes(b"x" * 60000)
            return path

        from video2agent import sources
        from video2agent.links import canonical_douyin_url

        ref = {"kind": "douyin", "platform": "douyin", "aweme_id": item["aweme_id"],
               "url": canonical_douyin_url(item["aweme_id"]), "input_kind": "url"}
        with patch.object(douyin, "get_item", return_value=item), \
                patch.object(douyin, "download", side_effect=fake_download), \
                patch.object(sources, "probe", return_value={"duration": 1225.967, "title": "测试视频"}), \
                patch.object(sources, "download_cover", return_value=None):
            source = sources._douyin_source(ref, self.cfg)
        self.assertEqual(source["platform"], "douyin")
        self.assertEqual(source["title"], "测试视频")
        self.assertTrue(Path(source["path"]).is_file())
        self.assertEqual(source["meta"]["uploader"], "anChaOs")
        self.assertEqual(source["meta"]["uploader_id"], "abouttao")
        self.assertEqual(source["meta"]["view_count"], 1)
        self.assertEqual(source["subtitles"], [])
        self.assertTrue(source["uri"].startswith("https://www.douyin.com/video/"))

    def test_resolve_info_returns_douyin_metadata(self):
        from video2agent import pipeline

        ref = {"kind": "douyin", "platform": "douyin", "aweme_id": "7704519391488134410",
               "url": "https://www.douyin.com/video/7704519391488134410", "input_kind": "url"}
        item = {"aweme_id": "7704519391488134410", "title": "标题", "description": "描述",
                "duration_ms": 61000, "cover_url": "https://example.com/c.jpg",
                "author": {"nickname": "昵称", "unique_id": "uid"}}
        with patch.object(pipeline, "normalize_video_ref", return_value=ref), \
                patch.object(douyin, "get_item", return_value=item):
            out = pipeline.resolve_info(self.cfg, "https://www.douyin.com/video/7704519391488134410")
        self.assertTrue(out["ok"])
        self.assertEqual(out["platform"], "douyin")
        self.assertEqual(out["title"], "标题")
        self.assertEqual(out["uploader"], "昵称")
        self.assertEqual(out["duration_ms"], 61000)
        self.assertEqual(out["douyin_id"], "7704519391488134410")


class DouyinRiskStateTests(unittest.TestCase):
    """The four measured response states get distinct reasons (2026-11)."""

    def test_full_ssr_is_data(self):
        html = (FIXTURES / "douyin_share.html").read_text(encoding="utf-8")
        self.assertEqual(douyin._classify_html(html), "data")

    def test_shell_page_is_shell(self):
        html = "<html><script>window._ROUTER_DATA = {}</script></html>"
        self.assertEqual(douyin._classify_html(html), "shell")

    def test_captcha_middle_page_is_captcha(self):
        html = "<html><head><title>验证码中间页</title></head><body>x</body></html>"
        self.assertEqual(douyin._classify_html(html), "captcha")

    def test_hard_block_is_blocked(self):
        self.assertEqual(douyin._classify_html("<html>bootstrap</html>"), "blocked")

    def test_captcha_reason_mentions_verification(self):

        class FakeSession:
            headers = {}

            def get(self, url, timeout=None):
                return _Resp(200, "<html><title>验证码中间页</title></html>")

        with patch.object(douyin, "_bootstrap"), patch.object(douyin, "_session", return_value=FakeSession()), patch.object(douyin.time, "sleep"):
            with self.assertRaises(Video2AgentError) as ctx:
                douyin.get_item("7704519391488134410", attempts=2)
        self.assertIn("verification", ctx.exception.message)




class DouyinCacheTests(unittest.TestCase):
    """A risk-gated page makes repeated reads wasteful; cache the good item."""

    def test_success_is_cached_and_reused_when_blocked(self):
        html = (FIXTURES / "douyin_share.html").read_text(encoding="utf-8")
        calls = []

        def make_session(responses):
            class FakeSession:
                headers = {}

                def get(self, url, timeout=None):
                    calls.append(url)
                    return responses.pop(0)

            return FakeSession()

        with tempfile.TemporaryDirectory() as tmp:
            cache = Path(tmp) / "cache"
            with patch.object(douyin, "_bootstrap"), patch.object(douyin, "_session", return_value=make_session([_Resp(200, html)])), \
                    patch.object(douyin, "_register_ttwid"), patch.object(douyin.time, "sleep"):
                item = douyin.get_item("7704519391488134410", attempts=2, cache_dir=cache)
            self.assertEqual(item["aweme_id"], "7704519391488134410")
            self.assertTrue((cache / "7704519391488134410.json").is_file())
            with patch.object(douyin, "_bootstrap"), patch.object(douyin, "_session", return_value=make_session([_Resp(200, "<html>验证码中间页</html>")])), \
                    patch.object(douyin, "_register_ttwid"), patch.object(douyin.time, "sleep"):
                again = douyin.get_item("7704519391488134410", attempts=2, cache_dir=cache)
            self.assertEqual(again["aweme_id"], "7704519391488134410")
            self.assertTrue(again.get("_cached"), "a cached item should be marked as such")

    def test_stale_cache_is_used_after_total_failure(self):
        import json
        import os

        item = {"aweme_id": "7704519391488134410", "title": "old", "description": "old",
                "author": {}, "duration_ms": 1, "cover_url": "", "play_uri": "",
                "play_url": "", "create_time": None, "stats": {}, "music": ""}
        with tempfile.TemporaryDirectory() as tmp:
            cache = Path(tmp) / "cache"
            cache.mkdir()
            path = cache / "7704519391488134410.json"
            path.write_text(json.dumps(item), encoding="utf-8")
            old = 1_000_000
            os.utime(path, (old, old))

            class FakeSession:
                headers = {}

                def get(self, url, timeout=None):
                    return _Resp(200, "<html>验证码中间页</html>")

            with patch.object(douyin, "_bootstrap"), patch.object(douyin, "_session", return_value=FakeSession()), \
                    patch.object(douyin, "_register_ttwid"), patch.object(douyin.time, "sleep"):
                out = douyin.get_item("7704519391488134410", attempts=2, cache_dir=cache)
        self.assertEqual(out["title"], "old")
        self.assertTrue(out.get("_cached"))




class DouyinGuardTests(unittest.TestCase):
    """User pages and invalid ids must fail before a network fetch."""

    def test_ingesting_a_douyin_user_page_is_rejected(self):
        from video2agent import sources
        from video2agent.config import load_config

        with tempfile.TemporaryDirectory() as tmp:
            cfg = load_config(tmp)
            with self.assertRaises(Video2AgentError) as ctx:
                sources.resolve_source(
                    "https://www.douyin.com/user/MS4wLjABAAAAVrzMoIDUuKEjINFmMtB4YlgG2B5l4HaAsahmBxp1gUI",
                    cfg,
                )
        self.assertEqual(ctx.exception.code, "E_SOURCE")
        self.assertIn("主页", ctx.exception.message)

    def test_invalid_douyin_video_id_has_its_own_error(self):
        from video2agent import pipeline
        from video2agent.config import load_config

        with tempfile.TemporaryDirectory() as tmp:
            cfg = load_config(tmp)
            with self.assertRaises(Video2AgentError) as ctx:
                pipeline.resolve_info(cfg, "https://www.douyin.com/video/123")
        self.assertEqual(ctx.exception.code, "E_DOUYIN_ID")


if __name__ == "__main__":
    unittest.main()
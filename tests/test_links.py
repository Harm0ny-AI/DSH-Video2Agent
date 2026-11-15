import os
import socket
import unittest
from unittest.mock import patch

from video2agent.links import (
    av_to_bv,
    bv_to_av,
    canonical_video_url,
    extract_ref,
    normalize_video_ref,
)
from video2agent.util import Video2AgentError


def _online() -> bool:
    # Network tests are opt-in: CI must not depend on b23.tv (412/timeout would
    # turn both runners red for an external reason).
    if os.environ.get("VIDEO2AGENT_NETWORK_TESTS") != "1":
        return False
    try:
        socket.getaddrinfo("b23.tv", None)
        return True
    except OSError:
        return False


class AvBvConversionTests(unittest.TestCase):
    def test_known_pair(self):
        # Public reference pair: av170001 <-> BV17x411w7KC.
        self.assertEqual(av_to_bv(170001), "BV17x411w7KC")
        self.assertEqual(bv_to_av("BV17x411w7KC"), 170001)

    def test_roundtrip(self):
        for aid in (1, 2, 170001, 80433022, 1130000000):
            self.assertEqual(bv_to_av(av_to_bv(aid)), aid)

    def test_bv_to_av_rejects_garbage(self):
        self.assertIsNone(bv_to_av("not-a-bv"))
        self.assertIsNone(bv_to_av("BV!!!"))


class ExtractRefTests(unittest.TestCase):
    def test_bare_bv(self):
        ref = extract_ref("BV17x411w7KC")
        self.assertEqual(ref["kind"], "bv")
        self.assertEqual(ref["bvid"], "BV17x411w7KC")
        self.assertEqual(ref["av_id"], 170001)
        self.assertEqual(ref["input_kind"], "bv")
        self.assertEqual(ref["url"], "https://www.bilibili.com/video/BV17x411w7KC/")

    def test_bare_av(self):
        ref = extract_ref("av170001")
        self.assertEqual(ref["bvid"], "BV17x411w7KC")
        self.assertEqual(ref["input_kind"], "av")
        self.assertEqual(ref["url"], canonical_video_url("BV17x411w7KC"))

    def test_full_av_url(self):
        ref = extract_ref("https://www.bilibili.com/video/av170001")
        self.assertEqual(ref["bvid"], "BV17x411w7KC")
        self.assertEqual(ref["input_kind"], "url")
        self.assertEqual(ref["url"], "https://www.bilibili.com/video/BV17x411w7KC/")

    def test_full_bv_url_keeps_page(self):
        ref = extract_ref("https://www.bilibili.com/video/BV17x411w7KC/?p=3&spm_id_from=x")
        self.assertEqual(ref["url"], "https://www.bilibili.com/video/BV17x411w7KC/?p=3")

    def test_b23_link_with_bv_is_offline(self):
        ref = extract_ref("https://b23.tv/BV17x411w7KC")
        self.assertEqual(ref["bvid"], "BV17x411w7KC")
        self.assertEqual(ref["input_kind"], "shortlink")

    def test_b23_short_token_needs_resolution(self):
        ref = extract_ref("https://b23.tv/AbCdEf")
        self.assertEqual(ref["kind"], "shortlink")
        self.assertIsNone(ref["bvid"])

    def test_non_bilibili_input_is_ignored(self):
        self.assertIsNone(extract_ref("https://www.youtube.com/watch?v=abc"))
        self.assertIsNone(extract_ref(r"C:\videos\clip.mp4"))
        self.assertIsNone(extract_ref("随便一段文字"))


class NormalizeRefTests(unittest.TestCase):
    def test_av_url_canonicalizes_to_bv(self):
        ref = normalize_video_ref("https://www.bilibili.com/video/av170001")
        self.assertEqual(ref["url"], "https://www.bilibili.com/video/BV17x411w7KC/")

    def test_shortlink_uses_redirect(self):
        with patch("video2agent.links._resolve_shortlink",
                   return_value="https://www.bilibili.com/video/BV17x411w7KC/?share_source=copy") as m:
            ref = normalize_video_ref("https://b23.tv/AbCdEf")
        m.assert_called_once()
        self.assertEqual(ref["bvid"], "BV17x411w7KC")
        self.assertEqual(ref["input_kind"], "shortlink")
        self.assertEqual(ref["resolved_from"], "https://b23.tv/AbCdEf")
        self.assertEqual(ref["url"], "https://www.bilibili.com/video/BV17x411w7KC/")

    def test_shortlink_failure_is_structured(self):
        boom = Video2AgentError("E_SHORTLINK", "Short link could not be resolved", "Paste the full URL.")
        with patch("video2agent.links._resolve_shortlink", side_effect=boom):
            with self.assertRaises(Video2AgentError) as ctx:
                normalize_video_ref("https://b23.tv/AbCdEf")
        self.assertEqual(ctx.exception.code, "E_SHORTLINK")
        self.assertTrue(ctx.exception.remedy)

    def test_shortlink_to_foreign_host_is_rejected(self):
        with patch("video2agent.links._resolve_shortlink", return_value="https://example.com/nope"):
            with self.assertRaises(Video2AgentError) as ctx:
                normalize_video_ref("https://b23.tv/AbCdEf")
        self.assertEqual(ctx.exception.code, "E_SHORTLINK")


@unittest.skipUnless(_online(), "set VIDEO2AGENT_NETWORK_TESTS=1 to run real network tests")
class ShortlinkRedirectNetworkTests(unittest.TestCase):
    def test_real_redirect(self):
        # Network-optional: b23.tv/BV... redirects to the canonical page. This
        # exercises the actual requests redirect handling, not just parsing.
        from video2agent.links import _resolve_shortlink
        final = _resolve_shortlink("https://b23.tv/BV17x411w7KC", timeout=10)
        self.assertIn("bilibili.com/video/BV17x411w7KC", final)


if __name__ == "__main__":
    unittest.main()

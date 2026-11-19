import unittest
from unittest.mock import patch

from video2agent import net
from video2agent.net import assert_public_url
from video2agent.sources import path_allowed
from video2agent.util import Video2AgentError


class TunFakeIpTests(unittest.TestCase):
    """Clash TUN + fake-ip resolves every domain into 198.18.0.0/15.

    That answer comes from the local proxy; the proxy makes the real connection
    and resolves remotely, so it must not be read as a private-network target.
    """

    def _resolve_to(self, ip):
        return patch.object(net.socket, "getaddrinfo", return_value=[
            (2, 1, 6, "", (ip, 0)),
        ])

    def test_fake_ip_range_is_not_treated_as_private(self):
        with self._resolve_to("198.18.0.5"):
            net.assert_public_url("https://www.bilibili.com/video/BV1xx411c7mD")
            net.assert_public_url("https://www.bilivideo.com/x.m4s")
            net.assert_public_url("https://b23.tv/abc")

    def test_other_platform_hosts_also_work_under_fake_ip(self):
        # Fake-ip is not Bilibili-specific: every domain resolves there in TUN
        # mode, and the actual target is resolved by the proxy.
        with self._resolve_to("198.19.255.254"):
            net.assert_public_url("https://www.youtube.com/watch?v=abc")

    def test_real_private_address_still_blocked(self):
        with self._resolve_to("10.0.0.8"):
            with self.assertRaises(Video2AgentError):
                net.assert_public_url("https://example.com/video.mp4")

    def test_allow_private_keeps_metadata_protection(self):
        for url in (
            "http://169.254.169.254/latest/meta-data",
            "http://metadata.google.internal/computeMetadata/v1/",
        ):
            with self.assertRaises(Video2AgentError):
                net.assert_public_url(url, allow_private=True)
        with self._resolve_to("169.254.169.254"):
            with self.assertRaises(Video2AgentError):
                net.assert_public_url("https://example.com/redirect", allow_private=True)

    def test_link_local_blocked_even_with_allow_private(self):
        with self._resolve_to("169.254.1.1"):
            with self.assertRaises(Video2AgentError):
                net.assert_public_url("https://example.com/x", allow_private=True)


class NetTests(unittest.TestCase):
    def test_private_ipv4_blocked(self):
        with self.assertRaises(Video2AgentError) as ctx:
            assert_public_url("http://127.0.0.1/video.mp4")
        self.assertEqual(ctx.exception.code, "E_PRIVATE_URL")

    def test_private_ipv6_blocked(self):
        with self.assertRaises(Video2AgentError):
            assert_public_url("http://[::1]/video.mp4")

    def test_metadata_ip_blocked(self):
        with self.assertRaises(Video2AgentError):
            assert_public_url("http://169.254.169.254/latest/meta-data")

    def test_scheme_blocked(self):
        with self.assertRaises(Video2AgentError) as ctx:
            assert_public_url("file:///etc/passwd")
        self.assertEqual(ctx.exception.code, "E_URL_SCHEME")

    def test_allow_private_override(self):
        assert_public_url("http://127.0.0.1/video.mp4", allow_private=True)

    def test_path_allowlist(self):
        import tempfile
        from pathlib import Path
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp) / "videos"
            root.mkdir()
            inside = root / "a.mp4"
            inside.write_bytes(b"x")
            outside = Path(tmp) / "b.mp4"
            outside.write_bytes(b"x")
            self.assertTrue(path_allowed(inside, [str(root)]))
            self.assertFalse(path_allowed(outside, [str(root)]))
            self.assertTrue(path_allowed(outside, []))


if __name__ == "__main__":
    unittest.main()

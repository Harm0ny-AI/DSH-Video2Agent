import unittest

from video2agent.net import assert_public_url
from video2agent.sources import path_allowed
from video2agent.util import Video2AgentError


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

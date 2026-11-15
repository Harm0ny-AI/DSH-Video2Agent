import tempfile
import unittest
from pathlib import Path

from video2agent.captions import is_logged_in, load_netscape_cookies


class NetscapeCookieTest(unittest.TestCase):
    def test_httponly_prefix_keeps_sessdata(self):
        text = (
            "# Netscape HTTP Cookie File\n"
            "#HttpOnly_.bilibili.com\tTRUE\t/\tFALSE\t0\tSESSDATA\tsecret-token\n"
            ".bilibili.com\tTRUE\t/\tFALSE\t0\tbili_jct\tcsrf\n"
        )
        path = Path(tempfile.mkdtemp(prefix="vp-cookie-")) / "cookies.txt"
        path.write_text(text, encoding="utf-8")
        jar = load_netscape_cookies(path)
        self.assertEqual(jar.get("SESSDATA"), "secret-token")
        self.assertEqual(jar.get("bili_jct"), "csrf")
        self.assertTrue(is_logged_in(jar))

    def test_plain_comment_ignored(self):
        path = Path(tempfile.mkdtemp(prefix="vp-cookie-")) / "cookies.txt"
        path.write_text("# a comment\n", encoding="utf-8")
        self.assertEqual(load_netscape_cookies(path), {})

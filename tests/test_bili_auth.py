import base64
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from video2agent import bili_auth
from video2agent.config import load_config

REDIRECT = (
    "https://passport.bilibili.com/login/verify?SESSDATA=abc%2C123%2Cdef&bili_jct=csrf123"
    "&DedeUserID=424242&DedeUserID__ckMd5=zzz&sid=xyz&gourl=https%3A%2F%2Fwww.bilibili.com"
)


class RedirectParseTests(unittest.TestCase):
    def test_extracts_login_cookies_only(self):
        cookies = bili_auth.cookies_from_redirect(REDIRECT)
        self.assertEqual(cookies["SESSDATA"], "abc,123,def")
        self.assertEqual(cookies["bili_jct"], "csrf123")
        self.assertEqual(cookies["DedeUserID"], "424242")
        self.assertNotIn("gourl", cookies)

    def test_empty_or_foreign_url_is_safe(self):
        self.assertEqual(bili_auth.cookies_from_redirect(""), {})
        self.assertEqual(bili_auth.cookies_from_redirect("https://example.com/?a=1"), {})


class QrRenderTests(unittest.TestCase):
    def test_qr_png_decodes_back_to_the_url(self):
        import cv2
        import numpy as np

        url = "https://account.bilibili.com/h5/account-h5/auth/scan?qrcode_key=deadbeef"
        data = bili_auth.render_qr(url)
        self.assertTrue(data.startswith("data:image/png;base64,"))
        raw = base64.b64decode(data.split(",", 1)[1])
        self.assertEqual(raw[:8], b"\x89PNG\r\n\x1a\n")
        image = cv2.imdecode(np.frombuffer(raw, np.uint8), cv2.IMREAD_GRAYSCALE)
        decoded, _, _ = cv2.QRCodeDetector().detectAndDecode(image)
        self.assertEqual(decoded, url)


class PollTests(unittest.TestCase):
    def _poll(self, payload, jar=None):
        class FakeCookies(dict):
            def get(self, name, domain=None):
                return dict.get(self, name)

        class Fake:
            def get(self, *a, **k):
                return self._resp

        class Resp:
            def __init__(self, data):
                self._data = data

            def json(self):
                return self._data

        fake = Fake()
        fake._resp = Resp(payload)
        fake.cookies = FakeCookies(jar or {})
        with patch.object(bili_auth, "_session", return_value=fake):
            return bili_auth.poll_login("key123")

    def test_state_mapping(self):
        waiting = self._poll({"code": 0, "data": {"code": 86101}})
        self.assertEqual(waiting["state"], "pending")
        scanned = self._poll({"code": 0, "data": {"code": 86090}})
        self.assertEqual(scanned["state"], "scanned")
        expired = self._poll({"code": 0, "data": {"code": 86038}})
        self.assertEqual(expired["state"], "expired")

    def test_confirmed_returns_cookies_without_exposing_them(self):
        ok = self._poll({"code": 0, "data": {"code": 0, "url": REDIRECT}})
        self.assertEqual(ok["state"], "ok")
        self.assertTrue(ok["logged_in"])
        self.assertEqual(ok["cookies"]["SESSDATA"], "abc,123,def")
        self.assertEqual(ok["uid"], "424242")

    def test_confirmed_falls_back_to_session_cookies(self):
        """Some confirmations set cookies only via Set-Cookie, with no URL."""
        ok = self._poll({"code": 0, "data": {"code": 0, "url": ""}}, jar={"SESSDATA": "from-set-cookie", "DedeUserID": "9"})
        self.assertEqual(ok["state"], "ok")
        self.assertEqual(ok["cookies"]["SESSDATA"], "from-set-cookie")
        self.assertEqual(ok["uid"], "9")

    def test_confirmed_without_any_cookie_is_reported_as_failed(self):
        # A consumed QR answers code 0 but carries nothing; returning "ok" here
        # made the UI poll forever and then claim the QR had expired.
        failed = self._poll({"code": 0, "data": {"code": 0, "url": ""}})
        self.assertEqual(failed["state"], "failed")
        self.assertEqual(failed["reason"], "no_cookie")


class LoginStoreTests(unittest.TestCase):
    def setUp(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.cfg = load_config(Path(tmp.name))

    def test_save_status_clear_roundtrip(self):
        self.assertFalse(bili_auth.login_status(self.cfg)["logged_in"])
        saved = bili_auth.save_login(self.cfg, {"SESSDATA": "s", "DedeUserID": "777", "bili_jct": "j"})
        self.assertTrue(saved["ok"])
        self.assertEqual(saved["uid"], "777")
        status = bili_auth.login_status(self.cfg)
        self.assertTrue(status["logged_in"])
        self.assertEqual(status["uid"], "777")
        jar = Path(saved["path"]).read_text(encoding="utf-8")
        self.assertIn(".bilibili.com\tTRUE\t/\tFALSE\t", jar)
        self.assertIn("\tSESSDATA\ts", jar)
        cleared = bili_auth.clear_login(self.cfg)
        self.assertTrue(cleared["cleared"])
        self.assertFalse(bili_auth.login_status(self.cfg)["logged_in"])

    def test_save_without_sessdata_is_refused(self):
        from video2agent.util import Video2AgentError

        with self.assertRaises(Video2AgentError):
            bili_auth.save_login(self.cfg, {"bili_jct": "only-csrf"})

    def test_saved_login_is_preferred_over_the_anonymous_jar(self):
        from video2agent.captions import cookie_path

        anonymous = self.cfg.home / "cookies" / "bilibili.txt"
        anonymous.parent.mkdir(parents=True, exist_ok=True)
        anonymous.write_text("anon", encoding="utf-8")
        self.assertEqual(cookie_path(self.cfg), anonymous)
        bili_auth.save_login(self.cfg, {"SESSDATA": "s"})
        self.assertEqual(cookie_path(self.cfg), bili_auth.login_path(self.cfg))


if __name__ == "__main__":
    unittest.main()

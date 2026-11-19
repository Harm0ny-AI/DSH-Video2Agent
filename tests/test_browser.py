import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from video2agent import browser
from video2agent.util import Video2AgentError

FIXTURES = Path(__file__).resolve().parent / "fixtures"


class BrowserProfileParseTests(unittest.TestCase):
    def test_parse_public_profile_text(self):
        text = (FIXTURES / "douyin_profile.txt").read_text(encoding="utf-8")
        out = browser.parse_profile("anChaOs的抖音 - 抖音", text, "https://www.douyin.com/user/x")
        self.assertEqual(out["nickname"], "anChaOs")
        self.assertEqual(out["douyin_id"], "863866982")
        self.assertEqual(out["follows"], 107)
        self.assertEqual(out["fans"], 15)
        self.assertEqual(out["likes"], 101)
        self.assertEqual(out["works"], 17)
        self.assertEqual(out["ip_location"], "上海")
        self.assertTrue(out["ok"])

    def test_parse_counts_with_live_badge_between_them(self):
        # Live profile text puts "1人正在直播" between the follow and fan
        # counters; the old single regex made every count None.
        text = (
            "Harm0ny\n关注\n174\n1人正在直播\n粉丝\n127\n获赞\n0\n"
            "抖音号：dypahrrmracl\n26岁\n广东·佛山\n作品\n0\n推荐\n喜欢\n"
        )
        out = browser.parse_profile("Harm0ny的抖音 - 抖音", text, "https://www.douyin.com/user/self")
        self.assertEqual(out["nickname"], "Harm0ny")
        self.assertEqual(out["douyin_id"], "dypahrrmracl")
        self.assertEqual((out["follows"], out["fans"], out["likes"], out["works"]), (174, 127, 0, 0))

    def test_parse_missing_fields_is_empty(self):
        out = browser.parse_profile("", "nothing here", "https://example.com")
        self.assertEqual(out["nickname"], "")
        self.assertIsNone(out["fans"])

    def test_sec_uid_from_url_or_bare(self):
        sec = "MS4wLjABAAAAVrzMoIDUuKEjINFmMtB4YlgG2B5l4HaAsahmBxp1gUI"
        self.assertEqual(browser.sec_uid_of(f"https://www.douyin.com/user/{sec}?x=1"), sec)
        self.assertEqual(browser.sec_uid_of(sec), sec)
        with self.assertRaises(Video2AgentError):
            browser.sec_uid_of("https://www.douyin.com/")


class BrowserCookieStoreTests(unittest.TestCase):
    def test_netscape_roundtrip(self):
        cookies = [
            {"name": "sessionid", "value": "abc123", "domain": ".douyin.com",
             "path": "/", "expires": 1900000000, "secure": True, "httpOnly": True},
        ]
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "cookies" / "douyin.txt"
            browser._write_netscape(cookies, path)
            self.assertTrue(path.is_file())
            back = browser._read_netscape(path)
        self.assertEqual(back[0]["name"], "sessionid")
        self.assertEqual(back[0]["value"], "abc123")
        self.assertEqual(back[0]["domain"], ".douyin.com")


class BrowserOptionalDependencyTests(unittest.TestCase):
    def test_profile_explains_how_to_install_playwright(self):
        def missing():
            raise Video2AgentError("E_BROWSER", "浏览器自动化需要 playwright", "pip install video2agent[browser]")

        with patch.object(browser, "_playwright", side_effect=missing):
            with self.assertRaises(Video2AgentError) as ctx:
                browser.profile("MS4wLjABAAAAVrzMoIDUuKEjINFmMtB4YlgG2B5l4HaAsahmBxp1gUI")
        self.assertEqual(ctx.exception.code, "E_BROWSER")




class BrowserVideoTabTests(unittest.TestCase):
    """Tab aliases must map to the pane that belongs to that tab."""

    def test_tab_aliases(self):
        self.assertEqual(browser._tab_kind("favorites"), "favorites")
        self.assertEqual(browser._tab_kind("收藏"), "favorites")
        self.assertEqual(browser._tab_kind("collect"), "favorites")
        self.assertEqual(browser._tab_kind("likes"), "likes")
        self.assertEqual(browser._tab_kind("喜欢"), "likes")
        self.assertEqual(browser._tab_kind("works"), "works")
        self.assertEqual(browser._tab_kind("nonsense"), "works")
        self.assertIn("user-like-list", browser._VIDEO_TAB_LISTS["likes"])
        self.assertIn("user-favorite-list", browser._VIDEO_TAB_LISTS["favorites"])


class BrowserVideoCardTests(unittest.TestCase):
    """DOM cards get deduped and normalized without touching a browser."""

    def test_dedupe_invalid_and_limit(self):
        cards = [
            {"aweme_id": "7665930064613199114", "text": "  第一条\n描述  "},
            {"aweme_id": "7665930064613199114", "text": "重复"},
            {"aweme_id": "123", "text": "太短"},
            {"aweme_id": "7704519391488134410", "text": "第二条"},
        ]
        out = browser._normalize_video_cards(cards, 5)
        self.assertEqual([v["aweme_id"] for v in out], ["7665930064613199114", "7704519391488134410"])
        self.assertEqual(out[0]["title"], "第一条 描述")
        self.assertTrue(out[0]["url"].endswith("/video/7665930064613199114"))
        limited = browser._normalize_video_cards(cards, 1)
        self.assertEqual(len(limited), 1)




class BrowserTargetTests(unittest.TestCase):
    """Invalid profile targets and logged-out self pages must error clearly."""

    def test_profile_url_must_be_a_douyin_user_page(self):
        sec = "MS4wLjABAAAAVrzMoIDUuKEjINFmMtB4YlgG2B5l4HaAsahmBxp1gUI"
        url, is_self = browser._profile_target(f"https://www.douyin.com/user/{sec}")
        self.assertIn(sec, url)
        self.assertFalse(is_self)
        self.assertTrue(browser._profile_target("https://www.douyin.com/user/self")[1])
        for bad in ("https://example.com/x", "https://www.douyin.com/video/7665930064613199114"):
            with self.assertRaises(Video2AgentError) as ctx:
                browser._profile_target(bad)
            self.assertEqual(ctx.exception.code, "E_DOUYIN_USER")

    def test_empty_logged_out_self_is_an_error(self):
        empty = {"nickname": "", "fans": None, "works": None, "logged_in": False}
        with self.assertRaises(Video2AgentError) as ctx:
            browser._validate_profile(dict(empty), is_self=True)
        self.assertEqual(ctx.exception.code, "E_DOUYIN_LOGIN")
        with self.assertRaises(Video2AgentError) as ctx2:
            browser._validate_profile(dict(empty), is_self=False)
        self.assertEqual(ctx2.exception.code, "E_DOUYIN_USER")

    def test_public_profile_with_zero_counts_is_valid(self):
        data = {"nickname": "someone", "fans": 0, "works": 0, "logged_in": False}
        self.assertEqual(browser._validate_profile(dict(data), is_self=False)["nickname"], "someone")




class BrowserVerificationTests(unittest.TestCase):
    """Douyin's slider page must not be mistaken for the login QR."""

    def test_verification_markers(self):
        self.assertTrue(browser._looks_like_verification("请完成下列验证后继续"))
        self.assertTrue(browser._looks_like_verification("按住左边按钮拖动完成上方拼图"))
        self.assertTrue(browser._looks_like_verification("安全验证"))
        self.assertFalse(browser._looks_like_verification("用抖音 App 扫码登录"))
        self.assertFalse(browser._looks_like_verification("验证码登录"))
        self.assertFalse(browser._looks_like_verification(""))


if __name__ == "__main__":
    unittest.main()
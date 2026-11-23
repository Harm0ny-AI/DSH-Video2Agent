import io
import json
import re
import tempfile
import time
import unittest
from contextlib import redirect_stdout
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

from video2agent import browser, cli
from video2agent.util import Video2AgentError

ROOT = Path(__file__).resolve().parents[1]
PROMO = ROOT / ".promo"


def sec_uid(index: int) -> str:
    return f"MS4wLjABAAAAbatch{index:04d}xyz"


def profile_url(value: str) -> str:
    return f"https://www.douyin.com/user/{value}"


def profile_config(index: int, *, nickname: str | None = None,
                   fans_text: str | None = None, likes_text: str | None = None,
                   api: bool = True, api_after: int = 0, body_after: int = 0,
                   api_sec: str | None = None, api_query_sec: str | None = None,
                   exact_fans: int | None = None, exact_likes: int | None = None,
                   body: str | None = None, title: str | None = None,
                   fail_goto: bool = False, redirect_to: str | None = None,
                   url_unavailable: bool = False) -> dict:
    sec = sec_uid(index)
    name = nickname if nickname is not None else f"用户{index}"
    fans_text = fans_text or str(100 + index)
    likes_text = likes_text or str(200 + index)
    follows = 10 + index
    works = 7 + index
    cfg = {
        "nickname": name,
        "sec_uid": sec,
        "follows": follows,
        "works": works,
        "fans_text": fans_text,
        "likes_text": likes_text,
        "douyin_id": f"id{index}",
        "api": api,
        "api_after": api_after,
        "body_after": body_after,
        "fail_goto": fail_goto,
        "redirect_to": redirect_to,
        "url_unavailable": url_unavailable,
    }
    if body is not None:
        cfg["body"] = body
    if title is not None:
        cfg["title"] = title
    if api:
        user = {
            "sec_uid": api_sec or sec,
            "nickname": name,
            "following_count": follows,
            "follower_count": exact_fans if exact_fans is not None else int(fans_text),
            "total_favorited": exact_likes if exact_likes is not None else int(likes_text),
            "aweme_count": works,
        }
        cfg["api_user"] = user
        cfg["api_query_sec"] = api_query_sec or user["sec_uid"]
    return cfg


def default_body(cfg: dict) -> str:
    return (
        f"{cfg['nickname']}\n关注\n{cfg['follows']}\n粉丝\n{cfg['fans_text']}\n"
        f"获赞\n{cfg['likes_text']}\n抖音号：{cfg['douyin_id']}\n作品\n{cfg['works']}\n"
    )


class _FakeResponse:
    def __init__(self, url: str, payload: dict):
        self.url = url
        self._payload = payload

    def json(self):
        return self._payload


class _FakePage:
    def __init__(self, service: "FakeService"):
        self.service = service
        self._handlers = []
        self._url = ""
        self._sec = ""
        self._cfg = {}
        self._ticks = 0
        self._api_sent = False
        self._closed = False
        self.wait_calls: list[int] = []
        self.read_timeouts: list[int] = []
        self.goto_timeout = None

    @property
    def url(self):
        if self._cfg.get("url_unavailable"):
            raise RuntimeError("current URL unavailable")
        return self._url

    @property
    def closed(self):
        return self._closed

    def on(self, event: str, handler):
        if event == "response":
            self._handlers.append(handler)

    def goto(self, url: str, wait_until: str, timeout: int):
        self._url = url
        self.goto_timeout = timeout
        match = re.search(r"/user/([^/?#]+)", url)
        self._sec = match.group(1) if match else ""
        self._cfg = self.service.profiles.get(self._sec) or {
            "body": "", "title": "", "api": False,
        }
        if self._cfg.get("fail_goto"):
            raise RuntimeError("fake navigation failure")
        if self._cfg.get("redirect_to"):
            self._url = str(self._cfg["redirect_to"])
        self._emit_api()

    def _emit_api(self):
        if self._api_sent or self._ticks < int(self._cfg.get("api_after", 0)):
            return
        self._api_sent = True
        if not self._cfg.get("api"):
            return
        query_sec = self._cfg.get("api_query_sec") or self._cfg["api_user"]["sec_uid"]
        response = _FakeResponse(
            "https://www.douyin.com/aweme/v1/web/user/profile/other/?"
            f"sec_user_id={query_sec}",
            {"user": dict(self._cfg["api_user"])},
        )
        for handler in list(self._handlers):
            handler(response)

    def wait_for_timeout(self, ms: int):
        self.wait_calls.append(ms)
        self._ticks += 1
        self._emit_api()

    def title(self, timeout=None):
        if timeout is not None:
            self.read_timeouts.append(int(timeout))
        if self._ticks < int(self._cfg.get("body_after", 0)):
            return ""
        return self._cfg.get("title", f"{self._cfg.get('nickname', '')}的抖音 - 抖音")

    def inner_text(self, selector: str, timeout=None):
        if timeout is not None:
            self.read_timeouts.append(int(timeout))
        if self._ticks < int(self._cfg.get("body_after", 0)):
            return ""
        return self._cfg.get("body", default_body(self._cfg))

    def close(self):
        self._closed = True
        self.service.closed_pages += 1


class _FakeContext:
    def __init__(self, service: "FakeService"):
        self.service = service
        self.closed = False

    def new_page(self):
        page = _FakePage(self.service)
        self.service.pages.append(page)
        return page

    def cookies(self):
        return []

    def close(self):
        self.closed = True


class _FakeBrowser:
    def __init__(self, service: "FakeService"):
        self.service = service
        self.closed = False

    def new_context(self, **kwargs):
        self.service.context_calls += 1
        context = _FakeContext(self.service)
        self.service.context = context
        return context

    def close(self):
        self.closed = True


class _FakeSyncPlaywright:
    def __enter__(self):
        return self

    def __exit__(self, *args):
        return False


class FakeService:
    def __init__(self, profiles: dict[str, dict]):
        self.profiles = profiles
        self.context_calls = 0
        self.pages: list[_FakePage] = []
        self.closed_pages = 0
        self.context = None

    def browser(self):
        return _FakeBrowser(self)


class PromoTestBase(unittest.TestCase):
    def setUp(self):
        PROMO.mkdir(exist_ok=True)
        self.tmp = Path(tempfile.mkdtemp(prefix="douyin-profiles-", dir=str(PROMO)))
        self.home = self.tmp / "home"
        self.home.mkdir()

    def run_profiles(self, inputs, service: FakeService, **kwargs):
        fake_browser = service.browser()
        with patch.object(browser, "_playwright", return_value=lambda: _FakeSyncPlaywright()), \
                patch.object(browser, "_launch", return_value=fake_browser):
            out = browser.profiles(inputs, **kwargs)
        self.fake_browser = fake_browser
        return out


class BatchFixtureTests(PromoTestBase):
    def test_one_profile_uses_exact_counts_and_closes_page(self):
        service = FakeService({sec_uid(0): profile_config(
            0, fans_text="1.4万", likes_text="30.1万",
            exact_fans=14064, exact_likes=301208,
        )})
        out = self.run_profiles([profile_url(sec_uid(0))], service,
                                entry_timeout_s=0.5, api_grace_s=0)
        self.assertTrue(out["ok"], out)
        self.assertEqual((out["count"], out["succeeded"], out["failed"]), (1, 1, 0))
        row = out["results"][0]
        self.assertEqual(row["sec_uid"], sec_uid(0))
        self.assertEqual(row["nickname"], "用户0")
        self.assertEqual(row["fans"], 14064)
        self.assertEqual(row["displayed_counts"]["fans"], 14000)
        self.assertTrue(row["counts_exact"]["fans"])
        self.assertTrue(row["counts_exact"]["works"])
        self.assertEqual(row["displayed_counts"]["works"], 7)
        self.assertEqual(service.context_calls, 1)
        self.assertEqual(len(service.pages), 1)
        self.assertTrue(service.pages[0].closed)
        self.assertTrue(self.fake_browser.closed)

    def test_five_inputs_partial_error_dedup_and_stable_order(self):
        service = FakeService({
            sec_uid(0): profile_config(0),
            sec_uid(1): profile_config(1),
            sec_uid(2): profile_config(2),
        })
        bad = "https://example.com/not-douyin"
        inputs = [profile_url(sec_uid(0)), sec_uid(1), sec_uid(0), bad, sec_uid(2)]
        out = self.run_profiles(inputs, service, entry_timeout_s=0.5, api_grace_s=0)
        self.assertTrue(out["ok"], out)
        self.assertEqual(out["requested"], 5)
        self.assertEqual(out["count"], 4)
        self.assertEqual(out["duplicates"], 1)
        self.assertEqual((out["succeeded"], out["failed"]), (3, 1))
        self.assertEqual([r["input"] for r in out["results"]],
                         [profile_url(sec_uid(0)), sec_uid(1), bad, sec_uid(2)])
        self.assertFalse(out["results"][2]["ok"])
        self.assertEqual(out["results"][2]["error"]["code"], "E_DOUYIN_USER")
        self.assertEqual(len(service.pages), 3)
        self.assertTrue(all(page.closed for page in service.pages))
        self.assertEqual(service.context_calls, 1)

    def test_ten_profiles_one_context_ten_pages(self):
        profiles = {sec_uid(i): profile_config(i) for i in range(10)}
        service = FakeService(profiles)
        inputs = [profile_url(sec_uid(i)) for i in range(10)]
        out = self.run_profiles(inputs, service, entry_timeout_s=0.5, api_grace_s=0)
        self.assertTrue(out["ok"], out)
        self.assertEqual(out["count"], 10)
        self.assertEqual(out["succeeded"], 10)
        self.assertEqual([r["sec_uid"] for r in out["results"]],
                         [sec_uid(i) for i in range(10)])
        self.assertEqual(service.context_calls, 1)
        self.assertEqual(len(service.pages), 10)
        self.assertTrue(all(page.closed for page in service.pages))
        self.assertTrue(self.fake_browser.closed)


class BatchFailureTests(PromoTestBase):
    def test_all_failure_has_one_aggregate_error_and_entry_errors(self):
        service = FakeService({
            sec_uid(0): profile_config(0, body="", title="", api=False),
        })
        out = self.run_profiles(
            ["https://example.com/x", profile_url(sec_uid(0))], service,
            entry_timeout_s=0.05, api_grace_s=0,
        )
        self.assertFalse(out["ok"], out)
        self.assertEqual(out["error"]["code"], "E_DOUYIN_PROFILES")
        self.assertEqual((out["count"], out["succeeded"], out["failed"]), (2, 0, 2))
        self.assertEqual([r["error"]["code"] for r in out["results"]],
                         ["E_DOUYIN_USER", "E_DOUYIN_USER"])
        self.assertEqual(len(service.pages), 1)
        self.assertTrue(service.pages[0].closed)

    def test_invalid_only_does_not_launch_a_browser(self):
        service = FakeService({})
        with patch.object(browser, "_playwright", side_effect=AssertionError("no browser")):
            out = browser.profiles(["https://example.com/x", "not a sec uid"])
        self.assertFalse(out["ok"], out)
        self.assertEqual(out["error"]["code"], "E_DOUYIN_PROFILES")
        self.assertEqual(service.context_calls, 0)

    def test_per_entry_timeout_is_bounded_and_batch_continues(self):
        service = FakeService({
            sec_uid(0): profile_config(0, body="", title="", api=False),
            sec_uid(1): profile_config(1),
        })
        started = time.monotonic()
        out = self.run_profiles(
            [profile_url(sec_uid(0)), profile_url(sec_uid(1))], service,
            entry_timeout_s=0.05, api_grace_s=0,
        )
        elapsed = time.monotonic() - started
        self.assertLess(elapsed, 2.0)
        self.assertTrue(out["ok"], out)
        self.assertEqual((out["succeeded"], out["failed"]), (1, 1))
        self.assertEqual(out["results"][0]["error"]["code"], "E_DOUYIN_USER")
        self.assertEqual(len(service.pages), 2)
        self.assertTrue(all(page.closed for page in service.pages))

    def test_self_url_is_a_per_entry_error_not_a_batch_abort(self):
        service = FakeService({sec_uid(0): profile_config(0)})
        out = self.run_profiles(
            ["https://www.douyin.com/user/self", profile_url(sec_uid(0))], service,
            entry_timeout_s=0.5, api_grace_s=0,
        )
        self.assertTrue(out["ok"], out)
        self.assertEqual(out["results"][0]["error"]["code"], "E_DOUYIN_USER")
        self.assertTrue(out["results"][1]["ok"])
        self.assertEqual(len(service.pages), 1)


class BatchValidationTests(unittest.TestCase):
    def test_envelope_errors_are_rejected_before_browser(self):
        bad = [
            "not json",
            "{}",
            "[]",
            json.dumps([sec_uid(0)] * 11),
            "[1]",
            json.dumps([" "]),
        ]
        for raw in bad:
            with self.subTest(raw=raw):
                with self.assertRaises(Video2AgentError) as ctx:
                    browser.parse_profile_batch(raw)
                self.assertEqual(ctx.exception.code, "E_DOUYIN_ARGS")

    def test_accepts_one_and_ten_trimmed_strings(self):
        one = browser.parse_profile_batch(json.dumps([f" {sec_uid(0)} "]))
        self.assertEqual(one, [sec_uid(0)])
        ten = browser.parse_profile_batch(json.dumps([sec_uid(i) for i in range(10)]))
        self.assertEqual(len(ten), 10)

    def test_bare_sec_uid_must_match_whole_string(self):
        with self.assertRaises(Video2AgentError) as ctx:
            browser._canonical_profile_target("prefix " + sec_uid(0))
        self.assertEqual(ctx.exception.code, "E_DOUYIN_USER")
        sec, url = browser._canonical_profile_target(sec_uid(0))
        self.assertEqual(sec, sec_uid(0))
        self.assertEqual(url, profile_url(sec_uid(0)))

    def test_page_identity_is_an_exact_normalised_path(self):
        sec = sec_uid(0)
        self.assertEqual(browser._profile_page_sec(profile_url(sec)), sec)
        self.assertEqual(browser._profile_page_sec(profile_url(sec) + "?x=1"), sec)
        self.assertEqual(browser._profile_page_sec(profile_url(sec) + "/"), sec)
        self.assertEqual(browser._profile_page_sec(profile_url(sec) + "/video/123"), "")
        self.assertNotEqual(browser._profile_page_sec(profile_url(sec) + "extra"), sec)
        self.assertEqual(browser._profile_page_sec(f"https://evil.example/user/{sec}"), "")
        self.assertEqual(browser._profile_page_sec(f"ftp://www.douyin.com/user/{sec}"), "")
        self.assertEqual(browser._profile_page_sec(""), "")


class BatchReadinessTests(PromoTestBase):
    def test_waits_for_complete_counters_instead_of_fixed_nine_seconds(self):
        service = FakeService({
            sec_uid(0): profile_config(0, api=False, body_after=3),
        })
        out = self.run_profiles([profile_url(sec_uid(0))], service,
                                entry_timeout_s=0.5, api_grace_s=0)
        self.assertTrue(out["ok"], out)
        page = service.pages[0]
        self.assertGreaterEqual(len(page.wait_calls), 3)
        self.assertLess(len(page.wait_calls), 20)
        self.assertEqual(out["results"][0]["fans"], 100)
        self.assertFalse(out["results"][0]["counts_exact"]["fans"])

    def test_waits_for_exact_api_and_keeps_displayed_snapshot(self):
        service = FakeService({
            sec_uid(0): profile_config(
                0, fans_text="1.4万", api_after=2, exact_fans=14064,
            ),
        })
        out = self.run_profiles([profile_url(sec_uid(0))], service,
                                entry_timeout_s=0.5, api_grace_s=1.0)
        self.assertTrue(out["ok"], out)
        row = out["results"][0]
        self.assertEqual(row["fans"], 14064)
        self.assertEqual(row["displayed_counts"]["fans"], 14000)
        self.assertTrue(row["counts_exact"]["fans"])
        self.assertGreaterEqual(len(service.pages[0].wait_calls), 2)
        self.assertLess(len(service.pages[0].wait_calls), 10)

    def test_unrelated_api_response_cannot_overwrite_identity(self):
        wrong = sec_uid(9)
        cfg = profile_config(0, fans_text="1.4万", api_sec=wrong, exact_fans=999999)
        cfg["api_user"]["nickname"] = "错误身份"
        service = FakeService({sec_uid(0): cfg})
        out = self.run_profiles([profile_url(sec_uid(0))], service,
                                entry_timeout_s=0.5, api_grace_s=0)
        row = out["results"][0]
        self.assertTrue(row["ok"], out)
        self.assertEqual(row["nickname"], "用户0")
        self.assertEqual(row["fans"], 14000)
        self.assertFalse(row["counts_exact"]["fans"])

    def test_navigation_failure_is_a_per_entry_error(self):
        service = FakeService({
            sec_uid(0): profile_config(0, fail_goto=True),
            sec_uid(1): profile_config(1),
        })
        out = self.run_profiles(
            [profile_url(sec_uid(0)), profile_url(sec_uid(1))], service,
            entry_timeout_s=0.5, api_grace_s=0,
        )
        self.assertTrue(out["ok"], out)
        self.assertFalse(out["results"][0]["ok"])
        self.assertEqual(out["results"][0]["error"]["code"], "E_DOUYIN_USER")
        self.assertTrue(out["results"][1]["ok"])
        self.assertTrue(all(page.closed for page in service.pages))

    def test_redirect_with_matching_partial_api_is_rejected_and_not_mixed(self):
        cfg = profile_config(
            0, api=True, api_after=0, redirect_to=profile_url(sec_uid(1)),
            body="用户1\n关注\n10\n粉丝\n999\n获赞\n888\n作品\n7\n",
            title="用户1的抖音 - 抖音",
        )
        cfg["api_user"] = {
            "sec_uid": sec_uid(0), "nickname": "用户0", "follower_count": 54321,
        }
        service = FakeService({sec_uid(0): cfg})
        out = self.run_profiles([profile_url(sec_uid(0))], service,
                                entry_timeout_s=0.05, api_grace_s=0)
        self.assertFalse(out["ok"], out)
        self.assertFalse(out["results"][0]["ok"])
        self.assertEqual(out["results"][0]["error"]["code"], "E_DOUYIN_USER")
        self.assertIn("账号页", out["results"][0]["error"]["message"])
        page = service.pages[0]
        self.assertTrue(page.closed)
        self.assertTrue(page.read_timeouts)
        self.assertLessEqual(max(page.read_timeouts), 60)

        # The matching API identity must not be mixed into the redirected page's
        # DOM counters: the snapshot keeps the wrong page's displayed numbers only,
        # and the batch above refuses to use them at all.
        direct_page = service.browser().new_context().new_page()
        holder, capture = browser._profile_capture(sec_uid(0))
        direct_page.on("response", capture)
        direct_page.goto(profile_url(sec_uid(0)), wait_until="domcontentloaded", timeout=1000)
        snapshot = browser._profile_snapshot(
            direct_page, url=profile_url(sec_uid(0)), holder=holder,
            logged_in=False, deadline=time.monotonic() + 1,
            expected_sec=sec_uid(0),
        )
        self.assertEqual(snapshot["nickname"], "用户1")
        self.assertEqual(snapshot["fans"], 999)
        self.assertFalse(snapshot["counts_exact"]["fans"])

    def test_redirect_to_unrelated_host_with_same_path_is_rejected(self):
        service = FakeService({
            sec_uid(0): profile_config(
                0, api=False, redirect_to=f"https://evil.example/user/{sec_uid(0)}",
                body="用户0\n关注\n10\n粉丝\n100\n获赞\n200\n作品\n7\n",
                title="用户0的抖音 - 抖音",
            ),
        })
        out = self.run_profiles([profile_url(sec_uid(0))], service,
                                entry_timeout_s=0.05, api_grace_s=0)
        self.assertFalse(out["ok"], out)
        self.assertEqual(out["results"][0]["error"]["code"], "E_DOUYIN_USER")

    def test_unavailable_current_url_cannot_fall_back_to_requested_url(self):
        service = FakeService({
            sec_uid(0): profile_config(
                0, api=False, body="用户0\n粉丝\n100\n", title="用户0的抖音 - 抖音",
                url_unavailable=True,
            ),
        })
        out = self.run_profiles([profile_url(sec_uid(0))], service,
                                entry_timeout_s=0.05, api_grace_s=0)
        self.assertFalse(out["ok"], out)
        self.assertEqual(out["results"][0]["error"]["code"], "E_DOUYIN_USER")

    def test_self_profile_still_works_for_the_single_profile_operation(self):
        cfg = profile_config(0)
        service = FakeService({"self": cfg})
        fake_browser = service.browser()
        with patch.object(browser, "_playwright", return_value=lambda: _FakeSyncPlaywright()), \
                patch.object(browser, "_launch", return_value=fake_browser):
            out = browser.profile("https://www.douyin.com/user/self")
        self.assertEqual(out["nickname"], "用户0")
        self.assertEqual(out["fans"], 100)
        self.assertEqual(len(service.pages), 1)
        self.assertTrue(service.pages[0].closed)


class BatchCliTests(PromoTestBase):
    def test_parser_accepts_one_urls_argument(self):
        raw = json.dumps([profile_url(sec_uid(0)), sec_uid(1)])
        args = cli._make_parser().parse_args(["douyin", "profiles", "--urls", raw, "--json"])
        self.assertEqual(args.action, "profiles")
        self.assertEqual(args.urls, raw)
        self.assertEqual(args.entry_timeout, 12.0)

    def test_runner_passes_the_raw_json_array_once(self):
        raw = json.dumps([sec_uid(0)])
        args = cli._make_parser().parse_args(["douyin", "profiles", "--urls", raw, "--json"])
        payload = {"ok": True, "platform": "douyin", "results": []}
        with patch.object(browser, "profiles", return_value=payload) as fake:
            out = cli._run_douyin(args, SimpleNamespace(home=self.home))
        self.assertEqual(out, payload)
        fake.assert_called_once_with(raw, entry_timeout_s=12.0)

    def test_exit_code_zero_on_partial_and_one_on_all_failure(self):
        raw = json.dumps([sec_uid(0)])
        ok_payload = {"ok": True, "platform": "douyin", "results": []}
        fail_payload = {"ok": False, "platform": "douyin", "results": [],
                        "error": {"code": "E_DOUYIN_PROFILES", "message": "x"}}
        with patch.object(cli, "_require_deps"), \
                patch.object(browser, "profiles", return_value=ok_payload):
            with redirect_stdout(io.StringIO()):
                code = cli.main(["douyin", "profiles", "--urls", raw, "--json",
                                 "--home", str(self.home)])
        self.assertEqual(code, 0)
        with patch.object(cli, "_require_deps"), \
                patch.object(browser, "profiles", return_value=fail_payload):
            with redirect_stdout(io.StringIO()):
                code = cli.main(["douyin", "profiles", "--urls", raw, "--json",
                                 "--home", str(self.home)])
        self.assertEqual(code, 1)

    def test_missing_urls_is_a_clear_cli_error_without_a_browser(self):
        with patch.object(cli, "_require_deps"), \
                patch.object(browser, "profiles") as fake:
            with redirect_stdout(io.StringIO()) as out:
                code = cli.main(["douyin", "profiles", "--json", "--home", str(self.home)])
        self.assertEqual(code, 1)
        fake.assert_not_called()
        self.assertEqual(json.loads(out.getvalue())["error"]["code"], "E_DOUYIN_ARGS")


if __name__ == "__main__":
    unittest.main()

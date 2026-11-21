"""Optional browser-based Douyin account reads (public profile + QR login).

Douyin protects its JSON APIs with signatures (a_bogus / secsdk / uifid), so
account data cannot be read with plain HTTP. This module drives the user's own
installed Chrome/Edge through Playwright instead, which renders the same pages a
person would see. It is optional: install the extra with
`pip install "video2agent[browser]"`.
"""

from __future__ import annotations

import json
import random
import re
import time
from pathlib import Path
from typing import Any
from urllib.parse import quote

from .util import Video2AgentError

PROFILE_URL = "https://www.douyin.com/user/{sec_uid}"
HOME_URL = "https://www.douyin.com/"
_SEC_RE = re.compile(r"MS4wLjAB[A-Za-z0-9_-]{10,}")
# A live badge can sit between the counters ("关注\n174\n1人正在直播\n粉丝"),
# so each counter is matched on its own instead of one rigid block.
_FOLLOWS_RE = re.compile(r"关注\s*\n\s*(\d+)")
_FANS_RE = re.compile(r"粉丝\s*\n\s*(\d+)")
_LIKES_RE = re.compile(r"获赞\s*\n\s*(\d+)")
_DOUYIN_ID_RE = re.compile(r"抖音号[：:]\s*([0-9A-Za-z_-]+)")
_IP_RE = re.compile(r"IP属地[：:]\s*([^\n\s]+)")
_WORKS_RE = re.compile(r"作品\s*\n\s*(\d+)")
_LOGIN_COOKIES = ("sessionid", "sessionid_ss")

# The visible tabs are role=tab headers; the data-e2e="user-*-tab" nodes are
# hidden panes. Keep the alias map and the list selector in one place so a new
# tab cannot reuse the wrong pane again.
_VIDEO_TAB_ALIASES = {
    "works": "works", "work": "works", "作品": "works",
    "likes": "likes", "like": "likes", "喜欢": "likes",
    "favorites": "favorites", "favorite": "favorites", "favourite": "favorites",
    "collect": "favorites", "collection": "favorites", "收藏": "favorites",
}
_VIDEO_TAB_LABELS = {"works": "作品", "likes": "喜欢", "favorites": "收藏"}
_VIDEO_TAB_LISTS = {
    "works": '[data-e2e="user-post-list"]',
    "likes": '[data-e2e="user-like-list"]',
    "favorites": '[data-e2e="user-favorite-list"]',
}


def _tab_kind(value: str) -> str:
    """Map a CLI tab value (English or Chinese) to works/likes/favorites."""
    return _VIDEO_TAB_ALIASES.get(str(value or "").strip().lower(), "works")


def _playwright():
    try:
        from playwright.sync_api import sync_playwright
    except Exception as exc:  # noqa: BLE001 - optional dependency
        raise Video2AgentError(
            "E_BROWSER",
            "浏览器自动化需要 playwright",
            "pip install \"video2agent[browser]\" 后重试（需要本机安装 Chrome 或 Edge）。",
        ) from exc
    return sync_playwright


# A normal desktop Chrome UA: Playwright's default "HeadlessChrome" UA makes
# Douyin answer with a verification middle-page instead of the login QR.
_BROWSER_UA = ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
               "(KHTML, like Gecko) Chrome/143.0.0.0 Safari/537.36")
_AUTOMATION_ARGS = ["--disable-blink-features=AutomationControlled"]


def _launch(playwright, *, headless: bool = True, offscreen: bool = False):
    """Prefer the user's installed Chrome/Edge; fall back to bundled Chromium.

    Login uses a visible window: Douyin can answer a datacenter/automated IP with
    a slider verification, which only a person can pass. Everything else stays
    headless because it is background work.
    """
    args = list(_AUTOMATION_ARGS)
    if offscreen:
        # A real window (Douyin treats headless differently) placed far off-screen:
        # still a normal Chrome renderer, but no window covers the user's work.
        args += ["--window-position=-32000,-32000", "--window-size=1100,820"]
    last: Exception | None = None
    for channel in ("chrome", "msedge", None):
        try:
            # Playwright adds --enable-automation by default; drop that flag for
            # the user's real Chrome/Edge. We still do not bypass any challenge.
            launch_args = {
                "headless": headless,
                "args": list(args),
                "ignore_default_args": ["--enable-automation"],
            }
            if channel:
                return playwright.chromium.launch(channel=channel, **launch_args)
            return playwright.chromium.launch(**launch_args)
        except Exception as exc:  # noqa: BLE001 - try the next channel
            last = exc
    raise Video2AgentError(
        "E_BROWSER",
        "没有可用的 Chrome/Edge/Chromium",
        "安装 Chrome 或 Edge，或运行 playwright install chromium 后重试。",
    ) from last


def sec_uid_of(value: str) -> str:
    """"Accept a profile URL or a bare sec_uid."""
    match = _SEC_RE.search(str(value or ""))
    if not match:
        raise Video2AgentError(
            "E_DOUYIN_USER",
            "需要抖音主页 URL 或 sec_uid",
            "例如 https://www.douyin.com/user/MS4wLjABAAAA...，或登录后用 me。",
        )
    return match.group(0)


def parse_profile(title: str, text: str, url: str) -> dict[str, Any]:
    """Extract profile fields from the rendered page text (no JSON APIs)."""
    nickname = ""
    title = str(title or "")
    if "的抖音" in title:
        nickname = title.split("的抖音", 1)[0].strip()
    follows = _FOLLOWS_RE.search(text or "")
    fans = _FANS_RE.search(text or "")
    likes = _LIKES_RE.search(text or "")
    douyin_id = _DOUYIN_ID_RE.search(text or "")
    ip_location = _IP_RE.search(text or "")
    works = _WORKS_RE.search(text or "")
    return {
        "ok": True,
        "platform": "douyin",
        "url": url,
        "nickname": nickname,
        "douyin_id": douyin_id.group(1) if douyin_id else "",
        "follows": int(follows.group(1)) if follows else None,
        "fans": int(fans.group(1)) if fans else None,
        "likes": int(likes.group(1)) if likes else None,
        "works": int(works.group(1)) if works else None,
        "ip_location": ip_location.group(1) if ip_location else "",
    }


def _read_netscape(path: Path) -> list[dict[str, Any]]:
    cookies: list[dict[str, Any]] = []
    try:
        lines = path.read_text(encoding="utf-8").splitlines()
    except OSError:
        return cookies
    for line in lines:
        if not line or line.startswith("#") and not line.startswith("#HttpOnly_"):
            continue
        parts = line.split("\t")
        if len(parts) < 7:
            continue
        domain, _flag, pathv, secure, expires, name, value = parts[:7]
        cookies.append({
            "name": name, "value": value, "domain": domain.lstrip("#HttpOnly_"),
            "path": pathv or "/", "expires": float(expires or 0), "secure": secure.upper() == "TRUE",
        })
    return cookies


def _write_netscape(cookies: list[dict[str, Any]], path: Path) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    lines = ["# Netscape HTTP Cookie File", "# Generated by Video2Agent (Douyin browser login)", ""]
    for cookie in cookies:
        domain = str(cookie.get("domain") or "")
        if not domain:
            continue
        lines.append("\t".join([
            ("#HttpOnly_" if cookie.get("httpOnly") else "") + domain,
            "TRUE" if domain.startswith(".") else "FALSE",
            str(cookie.get("path") or "/"),
            "TRUE" if cookie.get("secure") else "FALSE",
            str(int(cookie.get("expires") or 0)),
            str(cookie.get("name") or ""),
            str(cookie.get("value") or ""),
        ]))
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")
    try:
        path.chmod(0o600)
    except OSError:
        pass
    return path


_PROFILE_HOSTS = ("douyin.com", "www.douyin.com", "m.douyin.com",
                   "iesdouyin.com", "www.iesdouyin.com")


def _profile_target(raw: str) -> tuple[str, bool]:
    """Return (url, is_self) for a profile URL or bare sec_uid."""
    value = str(raw or "").strip()
    if value.startswith(("http://", "https://")):
        from urllib.parse import urlparse

        parsed = urlparse(value)
        host = (parsed.hostname or "").lower()
        if host not in _PROFILE_HOSTS:
            raise Video2AgentError(
                "E_DOUYIN_USER",
                f"不是抖音主页链接：{host or value}",
                "使用 https://www.douyin.com/user/MS4wLjAB... 或直接传 sec_uid。",
            )
        path = parsed.path or ""
        if "/user/" not in path:
            raise Video2AgentError(
                "E_DOUYIN_USER",
                "这是抖音视频或其他页面，不是用户主页",
                "使用 douyin.com/user/<sec_uid> 主页链接，或先 douyin login 再用 me。",
            )
        return value, "/user/self" in path
    sec = sec_uid_of(value)
    return PROFILE_URL.format(sec_uid=sec), False


def _validate_profile(result: dict[str, Any], *, is_self: bool) -> dict[str, Any]:
    """Turn empty/logged-out pages into actionable errors instead of ok:true."""
    if is_self and not result.get("logged_in") and not result.get("nickname"):
        raise Video2AgentError(
            "E_DOUYIN_LOGIN",
            "抖音未登录或登录态已失效",
            "先运行 video2agent douyin login 扫码，再运行 douyin me。",
        )
    if (not result.get("nickname") and result.get("fans") is None
            and result.get("works") is None):
        raise Video2AgentError(
            "E_DOUYIN_USER",
            "主页没有读到公开资料（可能不存在、被删除或被风控）",
            "检查主页链接，或稍后重试；需要登录的页面请先 douyin login。",
        )
    return result


_SEARCH_CARD_RE = re.compile(r"^(?:(\d{1,2}):)?(\d{1,2}):(\d{2})$")


def _search_duration_ms(text: str) -> int | None:
    match = _SEARCH_CARD_RE.match(text.strip())
    if not match:
        return None
    hours = int(match.group(1) or 0)
    return ((hours * 60 + int(match.group(2))) * 60 + int(match.group(3))) * 1000


def _search_card(row: dict[str, Any]) -> dict[str, Any] | None:
    video_id = str(row.get("id") or "").strip()
    if not video_id.isdigit():
        return None
    lines = [line.strip() for line in str(row.get("cardText") or "").splitlines() if line.strip()]
    duration_ms = None
    for line in lines:
        duration_ms = _search_duration_ms(line)
        if duration_ms is not None:
            break
    uploader = ""
    uploader_index = -1
    for index, line in enumerate(lines):
        if line.startswith("@"):
            uploader = line[1:].strip()
            uploader_index = index
            break
    title = ""
    stop = uploader_index if uploader_index >= 0 else len(lines)
    for line in reversed(lines[:stop]):
        if _search_duration_ms(line) is not None:
            continue
        if line.isdigit() or line in ("合集", "图文") or line.endswith("前"):
            continue
        title = line
        break
    if not title:
        return None
    cover = str(row.get("img") or "").strip()
    return {
        "candidate_id": f"douyin_{video_id}",
        "platform": "douyin",
        "video_id": video_id,
        "url": f"https://www.douyin.com/video/{video_id}",
        "title": title[:200],
        "cover_url": cover,
        "duration_ms": duration_ms,
        "uploader": uploader,
        "uploader_id": None,
        "published_at": None,
        "published_ts": None,
        "description": title[:300],
        "tags": "",
        "stats": {},
    }


def _api_candidate(info: dict[str, Any]) -> dict[str, Any] | None:
    if not isinstance(info, dict):
        return None
    video_id = str(info.get("aweme_id") or "").strip()
    if not video_id.isdigit():
        return None
    author = info.get("author") or {}
    video = info.get("video") or {}
    stats = info.get("statistics") or {}
    title = str(info.get("desc") or "").strip() or f"抖音视频 {video_id}"
    cover = ""
    for key in ("cover", "origin_cover", "dynamic_cover"):
        block = video.get(key) or {}
        urls = block.get("url_list") or []
        if urls:
            cover = str(urls[0])
            if cover.startswith("//"):
                cover = "https:" + cover
            break
    return {
        "candidate_id": f"douyin_{video_id}",
        "platform": "douyin",
        "video_id": video_id,
        "url": f"https://www.douyin.com/video/{video_id}",
        "title": title[:200],
        "cover_url": cover,
        "duration_ms": int(video.get("duration") or 0) or None,
        "uploader": str(author.get("nickname") or ""),
        "uploader_id": str(author.get("uid") or author.get("sec_uid") or "") or None,
        "published_at": None,
        "published_ts": None,
        "description": title[:300],
        "tags": "",
        "stats": {
            key: stats.get(key)
            for key in ("play_count", "digg_count", "comment_count", "share_count")
            if stats.get(key) is not None
        },
    }


def _is_closed_browser_error(exc: Exception) -> bool:
    name = type(exc).__name__.lower()
    text = str(exc).lower()
    return "targetclosed" in name or "target page" in text or "has been closed" in text or "context or browser" in text


def _wait_for_handoff(page: Any, collect: Any, page_has_verify: Any, timeout_s: int) -> list[dict[str, Any]]:
    """Wait for a human to finish the browser check, then return parsed cards."""
    deadline = time.monotonic() + max(1, int(timeout_s))
    while time.monotonic() < deadline:
        try:
            page.wait_for_timeout(2000)
        except Exception as exc:
            if _is_closed_browser_error(exc):
                raise Video2AgentError(
                    "E_DOUYIN_VERIFY",
                    "验证窗口已关闭，这次搜索没有完成",
                    "重新发起搜索，并在打开的 Chrome 窗口完成验证。",
                ) from exc
            raise
        candidates = collect()
        if candidates:
            page.wait_for_timeout(1500)
            candidates = collect()
            return candidates
        if not page_has_verify():
            # The page may still be loading the post-verification response.
            page.wait_for_timeout(3000)
            candidates = collect()
            if candidates:
                return candidates
    raise Video2AgentError(
        "E_DOUYIN_VERIFY",
        "抖音搜索需要人机验证，但这次没有完成",
        "请在打开的 Chrome 窗口完成验证后重试；不会自动绕过验证。",
    )


def search_videos(query: str, *, cookie_path: str | Path | None = None,
                  limit: int = 8, wait_ms: int = 9000,
                  verify_timeout_s: int = 180) -> list[dict[str, Any]]:
    """Search Douyin with the logged-in real browser.

    This is used when the signed endpoint asks for verification. The browser is
    visible so a person can complete the check; the function waits for the page's
    own search response, then returns the cards. It never clicks or solves the
    slider itself. The caller must have a stored login cookie.
    """
    store = Path(cookie_path) if cookie_path else None
    if store is None or not store.is_file():
        raise Video2AgentError(
            "E_DOUYIN_LOGIN",
            "抖音搜索需要登录",
            "先在设置页扫码登录抖音，再重试。",
        )
    sync_playwright = _playwright()
    url = "https://www.douyin.com/search/" + quote(str(query)) + "?type=video"
    responses: list[Any] = []
    candidates: list[dict[str, Any]] = []
    seen: set[str] = set()
    verify_seen = False

    def collect() -> list[dict[str, Any]]:
        nonlocal verify_seen
        found: list[dict[str, Any]] = []
        for response in responses:
            try:
                if "/general/search/" not in response.url:
                    continue
                text = response.text()
            except Exception:
                continue
            start = text.find("{")
            if start < 0:
                continue
            try:
                data, _ = json.JSONDecoder().raw_decode(text[start:])
            except Exception:
                continue
            if not isinstance(data, dict):
                continue
            nil = data.get("search_nil_info") or {}
            if str(nil.get("search_nil_type") or nil.get("search_nil_item") or "") == "verify_check":
                verify_seen = True
            for item in data.get("data") or []:
                if not isinstance(item, dict):
                    continue
                candidate = _api_candidate(item.get("aweme_info") or item)
                if candidate and candidate["video_id"] not in seen:
                    seen.add(candidate["video_id"])
                    found.append(candidate)
        return found

    def page_has_verify() -> bool:
        try:
            body = page.inner_text("body")
            return any(marker in body for marker in _VERIFY_MARKERS) or "验证码中间页" in page.title()
        except Exception:
            return False

    with sync_playwright() as playwright:
        browser_instance = _launch(playwright, headless=False)
        try:
            context = browser_instance.new_context(
                viewport={"width": 1280, "height": 900}, locale="zh-CN",
            )
            cookies = _read_netscape(store)
            if cookies:
                context.add_cookies([{
                    "name": c["name"], "value": c["value"], "domain": c["domain"],
                    "path": c["path"], "expires": c["expires"] or -1, "secure": c["secure"],
                } for c in cookies])
            page = context.new_page()
            page.on("response", lambda response: responses.append(response) if "/general/search/" in response.url else None)
            # Use the main Douyin search route. Do not start from /jingxuan:
            # that is the "抖音精选" PC shell, not the main-site search the user asked for.
            page.goto(url, wait_until="domcontentloaded", timeout=45000)
            page.wait_for_timeout(wait_ms + random.randint(0, 700))
            candidates = collect()
            if not candidates and (verify_seen or page_has_verify()):
                # Hand the verification to the user in a normal, visible window.
                # No click, drag, OCR or solver code is used here.
                try:
                    page.bring_to_front()
                    cdp = context.new_cdp_session(page)
                    window = cdp.send("Browser.getWindowForTarget")
                    cdp.send("Browser.setWindowBounds", {
                        "windowId": window.get("windowId"),
                        "bounds": {"left": 120, "top": 90, "width": 1200, "height": 900, "windowState": "normal"},
                    })
                except Exception:
                    pass
                candidates = _wait_for_handoff(page, collect, page_has_verify, verify_timeout_s)
                if not candidates:
                    raise Video2AgentError(
                        "E_DOUYIN_VERIFY",
                        "抖音搜索需要人机验证，但这次没有完成",
                        "请在打开的 Chrome 窗口完成验证后重试；不会自动绕过验证。",
                    )
            if not candidates:
                # Last-resort DOM parse for pages that render links directly.
                rows = page.evaluate(r"""() => {
                  const rows = [];
                  const seen = new Set();
                  for (const a of document.querySelectorAll('a[href*="/video/"]')) {
                    const m = (a.href || '').match(/\/video\/(\d+)/);
                    if (!m || seen.has(m[1])) continue;
                    seen.add(m[1]);
                    const card = a.closest('li') || a.closest('div[data-e2e]') || a.parentElement;
                    rows.push({
                      id: m[1],
                      cardText: (card ? card.innerText : a.innerText || '').slice(0, 800),
                      img: (card && card.querySelector('img')) ? (card.querySelector('img').getAttribute('src') || '') : '',
                    });
                    if (rows.length >= 100) break;
                  }
                  return rows;
                }""")
                for row in rows if isinstance(rows, list) else []:
                    if not isinstance(row, dict):
                        continue
                    candidate = _search_card(row)
                    if candidate and candidate["video_id"] not in seen:
                        seen.add(candidate["video_id"])
                        candidates.append(candidate)
        finally:
            browser_instance.close()
    return candidates[:max(1, int(limit))]




def profile(sec_uid_or_url: str, *, cookie_path: str | Path | None = None,
            wait_ms: int = 9000) -> dict[str, Any]:
    """Read a Douyin profile page through the browser; no JSON/signature needed."""
    url, is_self = _profile_target(sec_uid_or_url)
    sync_playwright = _playwright()
    with sync_playwright() as playwright:
        browser = _launch(playwright)
        try:
            context = browser.new_context(
                viewport={"width": 1280, "height": 900}, locale="zh-CN",
            )
            store = Path(cookie_path) if cookie_path else None
            if store and store.is_file():
                cookies = _read_netscape(store)
                if cookies:
                    context.add_cookies([{
                        "name": c["name"], "value": c["value"], "domain": c["domain"],
                        "path": c["path"], "expires": c["expires"] or -1, "secure": c["secure"],
                    } for c in cookies])
            page = context.new_page()
            page.goto(url, wait_until="domcontentloaded", timeout=45000)
            page.wait_for_timeout(wait_ms)
            result = parse_profile(page.title(), page.inner_text("body"), url)
            result["logged_in"] = any(
                c.get("name") in _LOGIN_COOKIES for c in context.cookies()
            )
            return _validate_profile(result, is_self=is_self)
        finally:
            browser.close()


# Strong phrases only: the login modal also contains an SMS-login tab labelled
# "验证码登录", which a bare "验证码" marker mistook for a slider verification.
_VERIFY_MARKERS = (
    "请完成下列验证",
    "按住左边按钮",
    "拖动滑块",
    "完成下方拼图",
    "验证码中间页",
    "安全验证",
)
_VERIFY_SELECTORS = (
    "[class*='captcha']",
    "[id*='captcha']",
    "iframe[src*='captcha']",
    "iframe[src*='verify']",
)
_QR_SELECTORS = (
    "img[src*='qrcode']",
    "img[src*='QRCode']",
    "[class*='qrcode'] canvas",
    "[class*='qrcode'] img",
    "[class*='QRCode'] canvas",
    "[class*='QRCode'] img",
    "[data-e2e*='qrcode'] canvas",
    "[data-e2e*='qrcode'] img",
)
_LOGIN_CONTAINERS = ("[class*='login']", "[class*='Login']", "[class*='modal']")


def _looks_like_verification(text: str) -> bool:
    """True when Douyin is showing a human slider/captcha instead of the login QR."""
    return any(marker in str(text or "") for marker in _VERIFY_MARKERS)


def _page_frames(page: Any) -> list[Any]:
    try:
        frames = list(getattr(page, "frames", []) or [])
    except Exception:  # noqa: BLE001
        frames = []
    return [page] + [frame for frame in frames if frame is not page]


def _is_verification(page: Any) -> bool:
    """Detect the slider/captcha wall in page text, frames or the rendered DOM."""
    for frame in _page_frames(page):
        try:
            if _looks_like_verification(frame.inner_text("body")):
                return True
        except Exception:  # noqa: BLE001 - frame may be mid-navigation
            pass
        for selector in _VERIFY_SELECTORS:
            try:
                locator = frame.locator(selector).first
                if locator.count() and locator.is_visible():
                    return True
            except Exception:  # noqa: BLE001
                continue
    return False


def _square_qr_box(box: dict[str, Any] | None) -> bool:
    """A QR is square and 90-600px; login banners/video frames are wide."""
    if not box:
        return False
    width = float(box.get("width") or 0)
    height = float(box.get("height") or 0)
    if width < 90 or height < 90 or width > 600 or height > 600:
        return False
    return 0.72 <= width / height <= 1.38


def _capture_qr(page: Any, qr: Path) -> bool:
    """Screenshot only a real, square-ish QR element (never a banner or video)."""

    def shot(item: Any) -> bool:
        try:
            if not item.count() or not item.is_visible():
                return False
            if not _square_qr_box(item.bounding_box()):
                return False
            item.screenshot(path=str(qr))
            return True
        except Exception:  # noqa: BLE001
            return False

    for frame in _page_frames(page):
        for selector in _QR_SELECTORS:
            try:
                items = frame.locator(selector)
                count = min(items.count(), 8)
            except Exception:  # noqa: BLE001
                continue
            for index in range(count):
                if shot(items.nth(index)):
                    return True
        # The desktop login modal (class douyin_login_new_class) contains a banner
        # img before the 179x179 data-URL QR img, so scan every img/canvas in the
        # container instead of only the first one.
        for container in _LOGIN_CONTAINERS:
            try:
                box = frame.locator(container).first
                if not box.count() or not box.is_visible():
                    continue
                for inner in ("img", "canvas"):
                    items = box.locator(inner)
                    count = min(items.count(), 12)
                    for index in range(count):
                        if shot(items.nth(index)):
                            return True
            except Exception:  # noqa: BLE001
                continue
    return False


def _qr_signature(page: Any) -> str:
    """Cheap fingerprint of the visible QR element (no screenshot)."""
    try:
        return str(page.evaluate(r"""() => {
          const modal = document.querySelector('[class*=douyin_login]')
          if (!modal) return ''
          for (const el of modal.querySelectorAll('img,canvas')) {
            const r = el.getBoundingClientRect()
            const w = Math.round(r.width), h = Math.round(r.height)
            if (w < 90 || h < 90 || Math.abs(w - h) > 40) continue
            if (el.tagName === 'IMG') return 'img:' + (el.getAttribute('src') || '')
            return 'canvas:' + w + 'x' + h + ':' + (el.className || '')
          }
          return ''
        }"""))
    except Exception:  # noqa: BLE001
        return ""


def _page_text(page: Any) -> str:
    try:
        return str(page.inner_text("body"))
    except Exception:  # noqa: BLE001
        return ""


def _click_qr_refresh(page: Any) -> bool:
    try:
        modal = page.locator("[class*=douyin_login]").first
        root = modal if modal.count() else page
    except Exception:  # noqa: BLE001
        root = page
    for label in ("点击刷新", "刷新", "重新获取"):
        try:
            locator = root.get_by_text(label, exact=True).first
            if locator.count() and locator.is_visible():
                locator.click(timeout=2000)
                return True
        except Exception:  # noqa: BLE001
            continue
    return False


def _qr_login_attempt(store: Path, qr: Path, *, deadline: float, mode: str,
                      write_stage: Any, log: Any = None) -> dict[str, Any]:
    """One login attempt. mode = headless | offscreen | visible."""
    sync_playwright = _playwright()
    with sync_playwright() as playwright:
        browser = _launch(playwright, headless=(mode == "headless"), offscreen=(mode == "offscreen"))
        try:
            context = browser.new_context(
                viewport={"width": 1100, "height": 820}, locale="zh-CN",
                user_agent=_BROWSER_UA,
            )
            page = context.new_page()
            page.goto(HOME_URL, wait_until="domcontentloaded", timeout=45000)
            page.wait_for_timeout(2000)
            try:
                page.get_by_text("登录", exact=True).first.click(timeout=4000)
            except Exception:  # noqa: BLE001 - the modal may already be open
                pass
            page.wait_for_timeout(1500)
            qr_sig = ""
            qr_since = 0.0
            last_click = 0.0
            last_diag = 0.0
            while time.time() < deadline:
                cookies = context.cookies()
                if any(c.get("name") in _LOGIN_COOKIES for c in cookies):
                    _write_netscape(cookies, store)
                    write_stage("done")
                    if log is not None:
                        log("login cookie detected, saved %d cookies" % len(cookies))
                    return {"ok": True, "platform": "douyin", "cookie_path": str(store),
                            "qr_path": str(qr), "cookies": len(cookies)}
                text = _page_text(page)
                if log is not None and time.time() - last_diag > 5:
                    last_diag = time.time()
                    try:
                        url = str(page.url)[:120]
                    except Exception:  # noqa: BLE001
                        url = ""
                    names = sorted({str(c.get("name")) for c in cookies})[:12]
                    login_names = [str(c.get("name")) for c in cookies if str(c.get("name")) in _LOGIN_COOKIES]
                    log("diag mode=%s url=%s cookies=%d login=%s %s" % (
                        mode, url, len(cookies), ",".join(login_names) or "-", ",".join(names)))
                sig = _qr_signature(page)
                if sig and sig != qr_sig:
                    # A new QR appeared (first time or Douyin rotated it after expiry):
                    # screenshot once, never on every tick.
                    if _capture_qr(page, qr):
                        qr_sig = sig
                        qr_since = time.time()
                        write_stage("qr")
                        if log is not None:
                            log("qr captured (%s)" % sig[:24])
                elif sig and qr_sig:
                    if any(k in text for k in ("扫描成功", "扫码成功", "请在手机", "请在手机端确认")):
                        write_stage("scanned")
                    elif any(k in text for k in ("已失效", "已过期", "二维码失效", "点击刷新")):
                        write_stage("expired")
                        if time.time() - qr_since > 12 and time.time() - last_click > 5:
                            last_click = time.time()
                            _click_qr_refresh(page)
                            if log is not None:
                                log("qr expired, clicked refresh")
                        if time.time() - qr_since > 120:
                            raise Video2AgentError(
                                "E_DOUYIN_QR_EXPIRED",
                                "抖音登录二维码已失效且无法自动刷新",
                                "重新点一次扫码登录即可。",
                            )
                elif qr_sig and not sig:
                    # The modal vanished: either login succeeded (cookies may arrive a
                    # tick later) or the user closed it; keep checking cookies.
                    pass
                page.wait_for_timeout(2000)
            write_stage("timeout")
            raise Video2AgentError(
                "E_DOUYIN_LOGIN",
                "未在超时时间内检测到抖音登录完成",
                "重新运行 login，用抖音 App 扫描 " + str(qr) + " 并确认。",
            )
        finally:
            browser.close()

def qr_login(cookie_path: str | Path, qr_path: str | Path, *, timeout: float = 180.0,
             headless: bool = True, status_path: str | Path | None = None,
             fallback_headed: bool = True) -> dict[str, Any]:
    """Write the login QR screenshot and wait for the scan.

    A real Chrome window is used, placed fully off-screen (``offscreen``), because
    a headless session that shows the same QR did not receive the login cookies
    after a real scan — the visible-window flow is the one that was verified to
    work. The window stays off-screen, so nothing covers the user's work; only if
    Douyin demands a slider does a visible window open (``--headed`` forces that).
    """
    store = Path(cookie_path)
    qr = Path(qr_path)
    progress = Path(status_path) if status_path else None
    qr.parent.mkdir(parents=True, exist_ok=True)

    def write_stage(stage: str) -> None:
        if progress is None:
            return
        try:
            progress.parent.mkdir(parents=True, exist_ok=True)
            progress.write_text(json.dumps({"stage": stage, "at": time.time()}), encoding="utf-8")
        except OSError:
            pass

    log_file = Path(status_path).parent.parent / "logs" / "douyin-login.log" if status_path else None

    def write_log(message: str) -> None:
        if log_file is None:
            return
        try:
            log_file.parent.mkdir(parents=True, exist_ok=True)
            with log_file.open("a", encoding="utf-8") as handle:
                handle.write("%s %s\n" % (time.strftime("%Y-%m-%d %H:%M:%S"), message))
        except OSError:
            pass

    overall = time.time() + max(60.0, float(timeout))
    # A real, VISIBLE window is required: two live tests showed that a headless or
    # off-screen window shows the same QR, but after the phone confirms the scan the
    # desktop page never receives the session (url unchanged, no sessionid cookie).
    # The visible-window flow is the one that has logged in successfully. The window
    # closes automatically once the login lands, and the QR is also mirrored into the
    # settings card for scanning there.
    return _qr_login_attempt(store, qr, deadline=overall, mode="visible",
                             write_stage=write_stage, log=write_log)


def _normalize_video_cards(cards: list[dict[str, Any]], limit: int) -> list[dict[str, Any]]:
    """Filter/dedupe DOM cards into canonical Douyin video entries."""
    out: list[dict[str, Any]] = []
    seen: set[str] = set()
    for card in cards or []:
        aweme_id = str(card.get("aweme_id") or "").strip()
        if not re.fullmatch(r"\d{15,20}", aweme_id) or aweme_id in seen:
            continue
        seen.add(aweme_id)
        text = re.sub(r"\s+", " ", str(card.get("text") or "")).strip()
        out.append({
            "aweme_id": aweme_id,
            "url": f"https://www.douyin.com/video/{aweme_id}",
            "title": text[:200],
        })
        if len(out) >= max(1, int(limit)):
            break
    return out


def user_videos(profile: str, *, tab: str = "works", limit: int = 20,
                cookie_path: str | Path | None = None, wait_ms: int = 9000) -> dict[str, Any]:
    """List a profile's works, liked videos or favorites through the rendered page."""
    url, is_self = _profile_target(profile)
    tab_name = _tab_kind(tab)
    sync_playwright = _playwright()
    with sync_playwright() as playwright:
        browser = _launch(playwright)
        try:
            context = browser.new_context(viewport={"width": 1280, "height": 900}, locale="zh-CN")
            store = Path(cookie_path) if cookie_path else None
            if store and store.is_file():
                cookies = _read_netscape(store)
                if cookies:
                    context.add_cookies([{
                        "name": c["name"], "value": c["value"], "domain": c["domain"],
                        "path": c["path"], "expires": c["expires"] or -1, "secure": c["secure"],
                    } for c in cookies])
            logged_in = any(c.get("name") in _LOGIN_COOKIES for c in context.cookies())
            if is_self and not logged_in:
                raise Video2AgentError(
                    "E_DOUYIN_LOGIN",
                    "读取“我的作品/喜欢/收藏”需要登录",
                    "先运行 video2agent douyin login 扫码，再试一次。",
                )
            page = context.new_page()
            page.goto(url, wait_until="domcontentloaded", timeout=45000)
            page.wait_for_timeout(wait_ms)
            # The data-e2e="user-*-tab" nodes are hidden panes, not the clickable
            # headers: clicking one times out and a live read then returned the
            # works pane as an empty list. Click the role=tab header and require
            # it to become active; a failed switch is reported, never returned as
            # an empty list.
            tab_ready = True
            label = _VIDEO_TAB_LABELS[tab_name]
            if tab_name != "works":
                try:
                    page.get_by_role("tab", name=label).first.click(timeout=8000)
                    page.wait_for_timeout(4500)
                except Exception:  # noqa: BLE001 - report, do not fake a list
                    tab_ready = False
                if tab_ready:
                    tab_ready = bool(page.evaluate(r"""(label) => {
                      const tab = [...document.querySelectorAll('[role="tab"]')]
                        .find(t => (t.innerText || '').trim().startsWith(label))
                      return !!tab && (tab.getAttribute('aria-selected') === 'true' ||
                        String(tab.className).includes('semi-tabs-tab-active'))
                    }""", label))
            selector = _VIDEO_TAB_LISTS[tab_name]
            cards = page.evaluate(r"""(selector) => {
              const list = document.querySelector(selector)
              const anchors = list ? [...list.querySelectorAll('a[href*="/video/"]')] : []
              const out = []
              const seen = new Set()
              for (const a of anchors) {
                const m = String(a.getAttribute("href") || "").match(/video\/(\d{15,20})/)
                if (!m || seen.has(m[1])) continue
                seen.add(m[1])
                const img = a.querySelector("img")
                let text = (a.innerText || "").trim()
                if (!text && img) text = String(img.getAttribute("alt") || "").trim()
                if (!text) {
                  const card = a.closest("li") || a.parentElement
                  text = card ? (card.innerText || "").trim() : ""
                }
                out.push({ aweme_id: m[1], text })
              }
              return { cards: out, listText: list ? (list.innerText || "") : "", anchors: anchors.length }
            }""", selector)
        finally:
            browser.close()
    cards_map = cards if isinstance(cards, dict) else {}
    videos = _normalize_video_cards(cards_map.get("cards") or [], limit)
    payload: dict[str, Any] = {
        "ok": True,
        "platform": "douyin",
        "url": url,
        "tab": tab_name,
        "count": len(videos),
        "videos": videos,
    }
    if tab_name != "works" and not tab_ready:
        payload["unavailable"] = True
        payload["reason"] = f"抖音暂时没有返回「{label}」列表，稍后重试"
        return payload
    if not videos:
        list_text = str(cards_map.get("listText") or "")
        if any(marker in list_text for marker in ("服务异常", "拉取失败", "刷新")):
            payload["unavailable"] = True
            payload["reason"] = "抖音作品/喜欢/收藏列表被风控或服务异常，稍后重试（主页资料仍可读）"
    return payload
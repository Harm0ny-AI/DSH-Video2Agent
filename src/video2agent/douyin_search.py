from __future__ import annotations

import hashlib
import json
import os
import time
from datetime import datetime, timezone
from http.cookiejar import MozillaCookieJar
from pathlib import Path
from typing import Any
from urllib.parse import quote, urlencode

import requests

from ._abogus import ABogus
from .config import Config
from .discover import apply_filters
from .text import normalize_text
from .util import Video2AgentError

_UA = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/146.0.0.0 Safari/537.36"
)
_SEARCH_URL = "https://www.douyin.com/aweme/v1/web/general/search/single/"
_CACHE_TTL = 5 * 60
_MAX_PAGES = 3
_PAGE_SIZE = 20
_MAX_RESULTS = 50


_LOGIN_COOKIE_NAMES = ("sessionid", "sessionid_ss")


def login_status(cfg: Config) -> dict[str, Any]:
    """File + session-cookie presence + expiry; never a network call.

    The Host settings card uses the same rule, so a stale cookie cannot show
    green in the UI and red in the CLI.
    """
    path = Path(cfg.home) / "cookies" / "douyin.txt"
    if not path.is_file():
        return {"logged_in": False, "reason": "missing", "cookie_path": str(path)}
    jar = MozillaCookieJar(str(path))
    try:
        jar.load(ignore_discard=True, ignore_expires=True)
    except Exception:
        return {"logged_in": False, "reason": "unreadable", "cookie_path": str(path)}
    login = [c for c in jar if "douyin.com" in c.domain and c.name in _LOGIN_COOKIE_NAMES and c.value]
    if not login:
        return {"logged_in": False, "reason": "missing_session", "cookie_path": str(path)}
    now = time.time()
    if all(c.expires is not None and c.expires > 0 and c.expires <= now for c in login):
        return {"logged_in": False, "reason": "expired", "cookie_path": str(path)}
    return {"logged_in": True, "reason": "cookie", "cookie_path": str(path)}


def _cookies(cfg: Config) -> tuple[str, dict[str, str]]:
    path = Path(cfg.home) / "cookies" / "douyin.txt"
    if not path.is_file():
        raise Video2AgentError(
            "E_DOUYIN_LOGIN",
            "抖音搜索需要登录",
            "先在设置页扫码登录抖音，或运行 video2agent douyin login。",
        )
    jar = MozillaCookieJar(str(path))
    try:
        jar.load(ignore_discard=True, ignore_expires=True)
    except Exception as exc:  # noqa: BLE001 - a damaged jar is a login problem, not a crash
        raise Video2AgentError(
            "E_DOUYIN_LOGIN",
            f"抖音登录状态读取失败：{type(exc).__name__}",
            "重新运行 video2agent douyin login。",
        ) from exc
    values: dict[str, str] = {}
    for cookie in jar:
        if "douyin.com" in cookie.domain and cookie.value:
            values[cookie.name] = cookie.value
    state = login_status(cfg)
    if not state["logged_in"]:
        reason = state.get("reason")
        message = "抖音登录已过期" if reason == "expired" else "抖音登录状态为空"
        raise Video2AgentError(
            "E_DOUYIN_LOGIN",
            message,
            "重新运行 video2agent douyin login，或在设置页扫码登录抖音。",
        )
    return "; ".join(f"{key}={value}" for key, value in values.items()), values


def _read_json(path: Path) -> dict[str, Any]:
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
        return value if isinstance(value, dict) else {}
    except (OSError, ValueError):
        return {}


def _write_json(path: Path, value: dict[str, Any]) -> None:
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        tmp = path.with_name(path.name + f".tmp-{os.getpid()}")
        tmp.write_text(json.dumps(value, ensure_ascii=False), encoding="utf-8")
        os.replace(tmp, path)
    except OSError:
        # Search must still work when the cache directory is read-only.
        pass


def _cache_path(cfg: Config) -> Path:
    return Path(cfg.home) / "cache" / "douyin-search-cache.json"


def _cache_key(query: str, target: int, uploader: str | None, after: str | None, before: str | None) -> str:
    raw = json.dumps([query, target, uploader, after, before], ensure_ascii=False)
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()


def _cache_get(cfg: Config, key: str) -> dict[str, Any] | None:
    data = _read_json(_cache_path(cfg))
    entry = data.get(key)
    if not isinstance(entry, dict):
        return None
    try:
        age = time.time() - float(entry.get("at") or 0)
    except (TypeError, ValueError):
        return None
    result = entry.get("result")
    if age > _CACHE_TTL or not isinstance(result, dict):
        return None
    return result


def _cache_put(cfg: Config, key: str, result: dict[str, Any]) -> None:
    data = _read_json(_cache_path(cfg))
    now = time.time()
    clean: dict[str, Any] = {}
    for existing_key, entry in data.items():
        if not isinstance(entry, dict):
            continue
        try:
            age = now - float(entry.get("at") or 0)
        except (TypeError, ValueError):
            continue
        if age <= 24 * 60 * 60:
            clean[existing_key] = entry
    clean[key] = {"at": now, "result": result}
    if len(clean) > 50:
        ordered = sorted(clean.items(), key=lambda item: float(item[1].get("at") or 0), reverse=True)[:50]
        clean = dict(ordered)
    _write_json(_cache_path(cfg), clean)


def _cover(info: dict[str, Any]) -> str:
    video = info.get("video") or {}
    for key in ("cover", "origin_cover", "dynamic_cover"):
        block = video.get(key) or {}
        urls = block.get("url_list") or []
        if urls:
            url = str(urls[0])
            return "https:" + url if url.startswith("//") else url
    return ""


def _published(ts: Any) -> tuple[str | None, int | None]:
    try:
        value = int(ts)
    except (TypeError, ValueError):
        return None, None
    return datetime.fromtimestamp(value, tz=timezone.utc).strftime("%Y-%m-%d"), value


def _candidate(item: dict[str, Any]) -> dict[str, Any] | None:
    info = item.get("aweme_info") if isinstance(item.get("aweme_info"), dict) else item
    if not isinstance(info, dict):
        return None
    aweme_id = str(info.get("aweme_id") or "").strip()
    if not aweme_id.isdigit():
        return None
    author = info.get("author") or {}
    video = info.get("video") or {}
    stats = info.get("statistics") or {}
    published_at, published_ts = _published(info.get("create_time"))
    desc = normalize_text(info.get("desc") or "")
    if not desc:
        desc = f"抖音视频 {aweme_id}"
    return {
        "candidate_id": f"douyin_{aweme_id}",
        "platform": "douyin",
        "video_id": aweme_id,
        "url": f"https://www.douyin.com/video/{aweme_id}",
        "title": desc[:200],
        "cover_url": _cover(info),
        "duration_ms": int(video.get("duration") or 0) or None,
        "uploader": normalize_text(author.get("nickname") or ""),
        "uploader_id": str(author.get("uid") or author.get("sec_uid") or "") or None,
        "uploader_sec_uid": str(author.get("sec_uid") or "") or None,
        "published_at": published_at,
        "published_ts": published_ts,
        "description": desc[:300],
        "tags": "",
        "stats": {
            key: stats.get(key)
            for key in ("play_count", "digg_count", "comment_count", "share_count")
            if stats.get(key) is not None
        },
    }


def _fetch_page(
    query: str,
    cookie_header: str,
    cookies: dict[str, str],
    *,
    offset: str,
    search_id: str = "",
) -> dict[str, Any]:
    uifid = cookies.get("UIFID") or cookies.get("UIFID_TEMP") or ""
    params = {
        "device_platform": "webapp",
        "aid": "6383",
        "channel": "channel_pc_web",
        "update_version_code": "170400",
        "pc_client_type": "1",
        "pc_libra_divert": "Windows",
        "support_h265": "1",
        "support_dash": "1",
        "version_code": "190600",
        "version_name": "19.6.0",
        "cookie_enabled": "true",
        "screen_width": "1536",
        "screen_height": "864",
        "browser_language": "zh-CN",
        "browser_platform": "Win32",
        "browser_name": "Chrome",
        "browser_version": "146.0.0.0",
        "browser_online": "true",
        "engine_name": "Blink",
        "engine_version": "146.0.0.0",
        "os_name": "Windows",
        "os_version": "10",
        "cpu_core_num": "16",
        "device_memory": "8",
        "platform": "PC",
        "downlink": "10",
        "effective_type": "4g",
        "round_trip_time": "200",
        "uifid": uifid,
        "msToken": "",
        "pc_search_top_1_params": '{"enable_ai_search_top_1":1}',
        "search_channel": "aweme_general",
        "enable_history": "1",
        "keyword": query,
        "search_source": "switch_tab",
        "query_correct_type": "1",
        "is_filter_search": "0",
        "from_group_id": "",
        "disable_rs": "0",
        "offset": str(offset),
        "count": str(_PAGE_SIZE),
        "need_filter_settings": "0",
        "list_type": "single",
    }
    if search_id:
        params["search_id"] = search_id
    query_string = urlencode(params, quote_via=quote)
    try:
        a_bogus = ABogus(_UA).get_value(query_string)
    except Exception as exc:  # noqa: BLE001 - signing a malformed clock is a tool failure
        raise Video2AgentError(
            "E_DOUYIN_SIGN",
            f"抖音签名生成失败：{type(exc).__name__}",
            "检查系统时间，或更新 Video2Agent。",
        ) from exc
    url = _SEARCH_URL + "?" + query_string + "&a_bogus=" + quote(a_bogus, safe="")
    headers = {
        "User-Agent": _UA,
        "Referer": "https://www.douyin.com/search/" + quote(query) + "?type=general",
        "Accept": "application/json, text/plain, */*",
        "Cookie": cookie_header,
    }
    try:
        response = requests.get(url, headers=headers, timeout=25, allow_redirects=False)
    except requests.RequestException as exc:
        raise Video2AgentError(
            "E_DOUYIN_SEARCH",
            f"抖音搜索请求失败：{type(exc).__name__}",
            "检查网络或稍后重试。",
        ) from exc
    if response.status_code == 403:
        raise Video2AgentError(
            "E_DOUYIN_RISK",
            "抖音拒绝了这次搜索（可能触发了风控）",
            "稍后重试；如果持续失败，重新登录抖音或更新 Video2Agent。",
        )
    if response.status_code != 200:
        raise Video2AgentError(
            "E_DOUYIN_SEARCH",
            f"抖音搜索 HTTP {response.status_code}",
            "稍后重试；如果持续失败，重新登录抖音。",
        )
    try:
        data = response.json()
    except (ValueError, json.JSONDecodeError) as exc:
        raise Video2AgentError(
            "E_DOUYIN_RISK",
            "抖音返回了非 JSON 页面（可能需要验证）",
            "稍后重试；如果持续失败，重新登录抖音。",
        ) from exc
    status = data.get("status_code")
    if status not in (0, None):
        raise Video2AgentError(
            "E_DOUYIN_SEARCH",
            f"抖音搜索失败（status_code={status}）",
            "稍后重试；如果持续失败，重新登录抖音。",
        )
    return data


def _browser_result(
    query: str,
    cfg: Config,
    *,
    target: int,
    uploader: str | None,
    after: str | None,
    before: str | None,
    cache_key: str,
) -> dict[str, Any]:
    """Use the logged-in real browser when signed HTTP is challenged."""
    from .browser import search_videos

    candidates = search_videos(
        query,
        cookie_path=Path(cfg.home) / "cookies" / "douyin.txt",
        limit=target,
    )
    kept, report = apply_filters(candidates, uploader=uploader, after=after, before=before)
    warnings: list[dict[str, Any]] = [{
        "code": "DOUYIN_BROWSER_FALLBACK",
        "severity": "info",
        "message": "签名搜索被风控，已改用登录浏览器取结果。",
    }]
    result: dict[str, Any] = {
        "query": query,
        "platform": "douyin",
        "candidates": kept[:target],
        "cover_sheet": None,
        "filters": report,
        "warnings": warnings,
        "found": len(candidates),
        "returned": len(kept[:target]),
        "pages": 1,
        "has_more": False,
    }
    if len(candidates) < target:
        warnings.append({
            "code": "BROWSER_LIMIT_CAPPED",
            "message": f"浏览器只取到 {len(candidates)} 条（请求 {target} 条）",
            "remedy": "缩小关键词，或稍后用更具体的关键词再搜。",
        })
    if candidates and not kept:
        warnings.append({
            "code": "FILTER_EMPTY",
            "message": f"搜索到 {len(candidates)} 条，但没有一条满足 uploader/after/before 条件",
            "remedy": "放宽日期范围，或去掉 uploader。",
        })
    if not candidates:
        warnings.append({"code": "NO_RESULTS", "message": "No results"})
    _cache_put(cfg, cache_key, result)
    return result


def discover_douyin(
    query: str,
    cfg: Config,
    *,
    limit: int = 8,
    covers: bool = False,
    uploader: str | None = None,
    after: str | None = None,
    before: str | None = None,
) -> dict[str, Any]:
    """Search Douyin through the signed web API, without a browser.

    The search is paginated for up to three pages so filters are not limited to
    page one. A successful result is cached for five minutes. There is no forced
    cooldown: a verify/risk block is surfaced immediately so the user can finish
    the check or log in and retry. Douyin refuses keyword search to a guest, so
    the saved login cookie is required.
    """
    query = (query or "").strip()
    if not query:
        raise Video2AgentError("E_QUERY", "Search query is empty.", "Give a keyword or title.")
    try:
        requested = int(limit)
    except (TypeError, ValueError):
        requested = 8
    target = max(1, min(requested, _MAX_RESULTS))
    key = _cache_key(query, target, uploader, after, before)
    cached = _cache_get(cfg, key)
    if cached is not None:
        cached["cached"] = True
        return cached
    cookie_header, cookies = _cookies(cfg)
    candidates: list[dict[str, Any]] = []
    seen: set[str] = set()
    warnings: list[dict[str, Any]] = []
    offset = "0"
    search_id = ""
    pages = 0
    has_more = False
    interrupted = False
    for page in range(_MAX_PAGES):
        try:
            data = _fetch_page(query, cookie_header, cookies, offset=offset, search_id=search_id)
        except Video2AgentError as exc:
            if candidates and exc.code in ("E_DOUYIN_VERIFY", "E_DOUYIN_RISK"):
                warnings.append({
                    "code": "PAGINATION_INTERRUPTED",
                    "message": f"第 {pages + 1} 页被拦截，已返回前 {len(candidates)} 条",
                    "remedy": exc.remedy or "稍后再试。",
                })
                interrupted = True
                break
            if not candidates and exc.code in ("E_DOUYIN_VERIFY", "E_DOUYIN_RISK"):
                try:
                    return _browser_result(
                        query, cfg, target=target, uploader=uploader,
                        after=after, before=before, cache_key=key,
                    )
                except Video2AgentError:
                    raise exc
            raise
        pages += 1
        items = data.get("data") or []
        nil = data.get("search_nil_info") or {}
        nil_type = str(nil.get("search_nil_type") or nil.get("search_nil_item") or "")
        if not items and nil_type == "verify_check":
            if candidates:
                warnings.append({
                    "code": "PAGINATION_INTERRUPTED",
                    "message": f"第 {pages} 页要求人机验证，已返回前 {len(candidates)} 条",
                    "remedy": "在浏览器里完成一次抖音搜索验证后再试。",
                })
                interrupted = True
                break
            verify_error = Video2AgentError(
                "E_DOUYIN_VERIFY",
                "抖音搜索要求人机验证（滑块），这次搜索被风控拦截",
                "在浏览器里完成一次抖音搜索验证，或在设置页重新登录抖音，然后立即重试。",
            )
            try:
                return _browser_result(
                    query, cfg, target=target, uploader=uploader,
                    after=after, before=before, cache_key=key,
                )
            except Video2AgentError:
                raise verify_error
        for item in items:
            if not isinstance(item, dict):
                continue
            candidate = _candidate(item)
            if candidate and candidate["video_id"] not in seen:
                seen.add(candidate["video_id"])
                candidates.append(candidate)
        has_more = bool(data.get("has_more"))
        cursor = data.get("cursor")
        log_pb = data.get("log_pb") or {}
        search_id = str(log_pb.get("impr_id") or search_id or "")
        kept, _ = apply_filters(candidates, uploader=uploader, after=after, before=before)
        if len(kept) >= target:
            break
        if not has_more:
            break
        if page + 1 >= _MAX_PAGES:
            break
        offset = str(cursor) if cursor not in (None, "") else str(int(offset) + len(items))
    kept, report = apply_filters(candidates, uploader=uploader, after=after, before=before)
    result: dict[str, Any] = {
        "query": query,
        "platform": "douyin",
        "candidates": kept[:target],
        "cover_sheet": None,
        "filters": report,
        "warnings": warnings,
        "found": len(candidates),
        "returned": len(kept[:target]),
        "pages": pages,
        "has_more": has_more,
    }
    if requested > _MAX_RESULTS:
        result["warnings"].append({
            "code": "LIMIT_CAPPED",
            "message": f"抖音搜索最多返回 {_MAX_RESULTS} 条（请求 {requested} 条）",
            "remedy": "缩小关键词，或分多次搜索。",
        })
    if covers:
        result["warnings"].append({
            "code": "COVERS_UNSUPPORTED",
            "message": "抖音候选不下载封面 OCR；封面 URL 仍会返回。",
        })
    if has_more and len(kept) < target and not interrupted:
        result["warnings"].append({
            "code": "PAGES_CAPPED",
            "message": f"翻到第 {pages} 页仍未凑够 {target} 条，后面的结果没有继续请求",
            "remedy": "缩小关键词，或稍后用更具体的关键词再搜。",
        })
    if candidates and not kept:
        result["warnings"].append({
            "code": "FILTER_EMPTY",
            "message": f"搜索到 {len(candidates)} 条，但没有一条满足 uploader/after/before 条件",
            "remedy": "放宽日期范围，或去掉 uploader。",
        })
    elif not candidates and not interrupted:
        result["warnings"].append({"code": "NO_RESULTS", "message": "No results"})
    if not interrupted:
        _cache_put(cfg, key, result)
    return result

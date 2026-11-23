"""Douyin (抖音) video source: share-page metadata and direct mp4 download.

As of 2026-11 the canonical www.douyin.com page is a JS shell and the web JSON
API (aweme/v1/web/*) sits behind the Argus gateway (`a_bogus`, `uifid`,
`verifyFp`, `x-sec...` signatures), so neither yt-dlp nor plain requests can read
it without a browser session. The one JS-free path that still returns data is
the iesdouyin SSR share page (`window._ROUTER_DATA`), which is risk-gated: after
a burst of requests it degrades to a captcha/shell page. We therefore retry with
backoff and raise E_DOUYIN_RISK instead of returning a silent empty result.

The share payload has no `download_addr`, but `video.play_addr.uri` can be
turned into a no-watermark mp4 through the public play endpoint.
"""

from __future__ import annotations

import json
import random
import re
import time
from pathlib import Path
from typing import Any

from .text import normalize_text
from .util import Video2AgentError

CANONICAL = "https://www.douyin.com/video/{aweme_id}"
SHARE = "https://www.iesdouyin.com/share/video/{aweme_id}/"
PLAY = "https://aweme.snssdk.com/aweme/v1/play/?line=0&ratio={ratio}&video_id={uri}"
PLAY_FALLBACK = "https://www.iesdouyin.com/aweme/v1/play/?video_id={uri}"

_UAS = (
    "Mozilla/5.0 (iPhone; CPU iPhone OS 17_2 like Mac OS X) AppleWebKit/605.1.15 "
    "(KHTML, like Gecko) Version/17.2 Mobile/15E148 Safari/604.1",
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) "
    "Chrome/140.0.0.0 Safari/537.36",
    "Mozilla/5.0 (Linux; Android 14; Pixel 8) AppleWebKit/537.36 (KHTML, like Gecko) "
    "Chrome/140.0.0.0 Mobile Safari/537.36",
)

_RISK_MARKERS = ("验证码中间页", "captcha", "argus-csp-token", "middle_page_loading")
# Both hosts served the same SSR payload historically; try the canonical share
# host first, then www.douyin.com/share (which sometimes redirects to it).
_SHARE_ENDPOINTS = (
    "https://www.iesdouyin.com/share/video/{aweme_id}/",
    "https://www.douyin.com/share/video/{aweme_id}/",
)
_RETRYABLE = (0.8, 1.6, 3.2)


def canonical_url(aweme_id: str) -> str:
    return CANONICAL.format(aweme_id=str(aweme_id))


def _session():
    import requests

    session = requests.Session()
    session.headers.update({
        "User-Agent": _UAS[0],
        "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,image/avif,image/webp,*/*;q=0.8",
        "Accept-Language": "zh-CN,zh;q=0.9",
        "Cache-Control": "no-cache",
        "Pragma": "no-cache",
        "Referer": "https://www.douyin.com/",
        "Sec-Fetch-Dest": "document",
        "Sec-Fetch-Mode": "navigate",
        "Sec-Fetch-Site": "same-site",
        "Upgrade-Insecure-Requests": "1",
    })
    return session


def _as_int(value: Any) -> int | None:
    try:
        return int(float(value))
    except (TypeError, ValueError):
        return None


def _first_url(node: Any) -> str:
    if isinstance(node, dict):
        urls = node.get("url_list") or []
    elif isinstance(node, list):
        urls = node
    else:
        urls = []
    for value in urls:
        if isinstance(value, str) and value.startswith(('http://', 'https://')):
            return value
    return ""


def _extract_router_json(html: str) -> dict[str, Any] | None:
    """Pull the `window._ROUTER_DATA` object out of an SSR page.

    A plain regex stopped at the first `</script>`, which a video description
    could contain; this scans braces outside of JSON strings instead.
    """
    text = html or ""
    marker = text.find("window._ROUTER_DATA")
    if marker < 0:
        return None
    start = text.find("{", marker)
    if start < 0:
        return None
    depth = 0
    in_string = False
    escaped = False
    for index in range(start, len(text)):
        char = text[index]
        if in_string:
            if escaped:
                escaped = False
            elif char == "\\":
                escaped = True
            elif char == '"':
                in_string = False
            continue
        if char == '"':
            in_string = True
        elif char == "{":
            depth += 1
        elif char == "}":
            depth -= 1
            if depth == 0:
                try:
                    value = json.loads(text[start:index + 1])
                except json.JSONDecodeError:
                    return None
                return value if isinstance(value, dict) else None
    return None


def parse_share_html(html: str) -> dict[str, Any] | None:
    """Extract and normalize the item embedded in an iesdouyin share page."""
    data = _extract_router_json(html)
    if not data:
        return None
    page = (data.get("loaderData") or {}).get("video_(id)/page") or {}
    info = page.get("videoInfoRes") or {}
    items = info.get("item_list") or []
    if not items or not isinstance(items[0], dict):
        return None
    return normalize_item(items[0])


def is_image_post(item: dict[str, Any]) -> bool:
    """True for a 图文 (image carousel) aweme, which has no playable mp4."""
    if not isinstance(item, dict):
        return False
    if item.get("kind") == "image":
        return True
    if item.get("images"):
        return True
    if _as_int(item.get("aweme_type")) == 68:
        return True
    # A cache written before this guard has no images/kind, but its play uri is
    # the background-music file (ies-music/<id>.mp3) instead of a video id.
    play_uri = str(item.get("play_uri") or "").lower()
    return "ies-music" in play_uri or play_uri.endswith(".mp3")


def normalize_item(item: dict[str, Any]) -> dict[str, Any]:
    """Map one aweme JSON object onto the fields the source layer needs."""
    video = item.get("video") or {}
    images = item.get("images") or []
    author = item.get("author") or {}
    stats = item.get("statistics") or {}
    play = video.get("play_addr") or {}
    music = item.get("music") or {}
    desc = normalize_text(str(item.get("desc") or ""))
    aweme_id = str(item.get("aweme_id") or "")
    return {
        "aweme_id": aweme_id,
        "kind": "image" if is_image_post(item) else "video",
        "image_count": len(images) if isinstance(images, list) else 0,
        "title": desc,
        "description": desc,
        "author": {
            "nickname": normalize_text(str(author.get("nickname") or "")),
            "unique_id": str(author.get("unique_id") or ""),
            "sec_uid": str(author.get("sec_uid") or ""),
            "uid": str(author.get("uid") or ""),
        },
        "duration_ms": _as_int(video.get("duration")),
        "cover_url": _first_url(video.get("cover")) or _first_url(video.get("origin_cover"))
        or _first_url(video.get("dynamic_cover")),
        "play_uri": str(play.get("uri") or ""),
        "play_url": _first_url(play),
        "create_time": _as_int(item.get("create_time")),
        "stats": {
            "view": _as_int(stats.get("play_count")),
            "like": _as_int(stats.get("digg_count")),
            "comment": _as_int(stats.get("comment_count")),
            "share": _as_int(stats.get("share_count")),
            "collect": _as_int(stats.get("collect_count")),
        },
        "music": normalize_text(str(music.get("title") or "")),
    }


def _classify_html(html: str) -> str:
    """Name what a share-page response is: data / shell / captcha / blocked.

    Measured states (2026-11): full SSR 68.9-73.4 KB with ``videoInfoRes``;
    JS shell 65.5 KB with ``_ROUTER_DATA`` but no item; captcha middle page
    6,296 B with a ``验证码中间页`` title; hard-block bootstrap 2,492 B.
    """
    text = html or ""
    if "videoInfoRes" in text:
        return "data"
    title = ""
    if "<title>" in text:
        title = text.split("<title>", 1)[1].split("</title>", 1)[0]
    lowered = title.lower()
    if "验证码" in title or "captcha" in lowered or any(m in text for m in _RISK_MARKERS):
        return "captcha"
    if "_ROUTER_DATA" in text:
        return "shell"
    if len(text) < 4096:
        return "blocked"
    return "empty"


def _cache_path(cache_dir: str | Path | None, aweme_id: str) -> Path | None:
    if not cache_dir:
        return None
    return Path(cache_dir) / f"{aweme_id}.json"


def _read_cache(cache_dir: str | Path | None, aweme_id: str, max_age: float) -> dict[str, Any] | None:
    path = _cache_path(cache_dir, aweme_id)
    if path is None or not path.is_file():
        return None
    try:
        if max_age > 0 and time.time() - path.stat().st_mtime > max_age:
            return None
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return None
    if isinstance(data, dict) and data.get("aweme_id"):
        data["_cached"] = True
        return data
    return None


def _write_cache(cache_dir: str | Path | None, item: dict[str, Any]) -> None:
    path = _cache_path(cache_dir, str(item.get("aweme_id") or ""))
    if path is None:
        return
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(item, ensure_ascii=False), encoding="utf-8")
    except OSError:
        return


def _register_ttwid(session) -> None:
    """Best-effort anonymous ttwid cookie; a failure only loses a hint."""
    try:
        session.post(
            "https://ttwid.bytedance.com/ttwid/union/register/",
            json={
                "region": "cn", "aid": 1768, "needFid": False,
                "service": "www.douyin.com",
                "migrate_info": {"ticket": "", "source": "node"},
                "cbUrlProtocol": "https", "union": True,
            },
            timeout=10,
        )
    except Exception:  # noqa: BLE001 - optional hint
        return


def _bootstrap(session) -> None:
    """Warm a session like a browser: homepage (__ac_nonce) + anonymous ttwid."""
    try:
        session.get("https://www.douyin.com/", timeout=10)
    except Exception:  # noqa: BLE001 - best effort only
        pass
    _register_ttwid(session)


def get_item(
    aweme_id: str,
    *,
    timeout: float = 20.0,
    attempts: int = 4,
    cache_dir: str | Path | None = None,
    cache_max_age: float = 6 * 3600,
) -> dict[str, Any]:
    """Read one video through the SSR share page, retrying risk pages.

    Successes are cached (the page is risk-gated, so a repeated read is likely to
    hit a captcha); a stale cache is used when every retry is blocked, which also
    makes `resolve` then `ingest` work in sequence.
    """
    aweme_id = str(aweme_id or "").strip()
    if not re.fullmatch(r"\d{15,20}", aweme_id):
        raise Video2AgentError("E_DOUYIN_ID", f"Invalid Douyin aweme id: {aweme_id}", "Paste a douyin.com/video/<id> URL.")
    cached = _read_cache(cache_dir, aweme_id, cache_max_age)
    if cached is not None:
        return cached
    reason = ""
    seed = _session()
    try:
        _bootstrap(seed)
    except Exception:  # noqa: BLE001 - it is only a hint
        pass
    try:
        seed_cookies = dict(seed.cookies) if seed.cookies else {}
    except Exception:  # noqa: BLE001 - custom sessions in tests may lack cookies
        seed_cookies = {}
    for attempt in range(max(1, attempts)):
        session = _session()
        if seed_cookies:
            try:
                session.cookies.update(seed_cookies)
            except Exception:  # noqa: BLE001
                pass
        session.headers["User-Agent"] = _UAS[attempt % len(_UAS)]
        url = _SHARE_ENDPOINTS[attempt % len(_SHARE_ENDPOINTS)].format(aweme_id=aweme_id)
        try:
            response = session.get(url, timeout=timeout)
        except Exception as exc:  # noqa: BLE001 - reason is reported
            reason = f"{type(exc).__name__}: {exc}"
        else:
            body = response.text or ""
            state = _classify_html(body)
            if state == "data":
                item = parse_share_html(body)
                if item and item.get("aweme_id"):
                    _write_cache(cache_dir, item)
                    return item
                reason = "Douyin returned a JS shell (video may be deleted/unavailable, or the page is risk-gated)"
            elif state == "captcha":
                reason = "Douyin returned a verification page"
            elif state == "shell":
                reason = "Douyin returned a JS shell (video may be deleted/unavailable, or the page is risk-gated)"
            elif state == "blocked":
                reason = f"Douyin blocked the request (HTTP {response.status_code}, {len(body)} bytes)"
            else:
                reason = f"Douyin share page had no video data (HTTP {response.status_code}, {len(body)} bytes)"
        if attempt + 1 < attempts:
            time.sleep(_RETRYABLE[min(attempt, len(_RETRYABLE) - 1)] + random.uniform(0, 0.35))
    stale = _read_cache(cache_dir, aweme_id, 0)
    if stale is not None:
        return stale
    raise Video2AgentError(
        "E_DOUYIN_RISK",
        f"Could not read Douyin video {aweme_id}: {reason}",
        "Retry later (Douyin risk-gates anonymous share pages), or download the video another way and pass the local file.",
    )


def play_urls(item: dict[str, Any]) -> list[str]:
    """Candidate mp4 URLs, no-watermark first, watermarked last."""
    uri = str(item.get("play_uri") or "").strip()
    urls: list[str] = []
    if uri:
        urls.extend([
            PLAY.format(ratio="1080p", uri=uri),
            PLAY.format(ratio="720p", uri=uri),
            PLAY_FALLBACK.format(uri=uri),
        ])
    watermark = str(item.get("play_url") or "")
    if watermark:
        urls.append(watermark)
    seen: set[str] = set()
    return [u for u in urls if u and not (u in seen or seen.add(u))]


def download(item: dict[str, Any], dest: str | Path, *, timeout: float = 120.0) -> Path:
    """Stream the no-watermark mp4 to `dest`, trying each candidate URL."""
    import requests

    target = Path(dest)
    target.parent.mkdir(parents=True, exist_ok=True)
    urls = play_urls(item)
    if not urls:
        raise Video2AgentError("E_DOUYIN_DOWNLOAD", "Douyin payload has no play address.", "Retry later or pass a local file.")
    last = ""
    headers = {
        "User-Agent": _UAS[1],
        "Referer": "https://www.douyin.com/",
    }
    for url in urls:
        part = target.with_suffix(target.suffix + ".part")
        try:
            with requests.get(url, headers=headers, stream=True, timeout=(15, max(30.0, timeout))) as response:
                response.raise_for_status()
                content_type = str(response.headers.get("Content-Type") or "").lower()
                if content_type and "video" not in content_type and "octet-stream" not in content_type:
                    last = f"unexpected content type {content_type}"
                    continue
                size = 0
                with part.open("wb") as handle:
                    for chunk in response.iter_content(chunk_size=256 * 1024):
                        if not chunk:
                            continue
                        handle.write(chunk)
                        size += len(chunk)
                if size < 50_000:
                    last = f"downloaded only {size} bytes"
                    part.unlink(missing_ok=True)
                    continue
                part.replace(target)
                return target
        except Exception as exc:  # noqa: BLE001 - try the next mirror
            last = f"{type(exc).__name__}: {exc}"
            part.unlink(missing_ok=True)
    raise Video2AgentError(
        "E_DOUYIN_DOWNLOAD",
        f"Douyin video download failed: {last}",
        "Retry later, or download the video another way and pass the local file.",
    )
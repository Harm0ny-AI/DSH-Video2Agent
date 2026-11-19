from __future__ import annotations

import re
from datetime import datetime, timedelta, timezone
from typing import Any
from urllib.parse import urljoin

import requests

from .config import Config
from .media import contact_sheet, download_cover
from .text import normalize_text
from .util import Video2AgentError, stable_id
from .visual import ocr_image

_EM = re.compile(r"<[^>]+>")
_BV = re.compile(r"(BV[0-9A-Za-z]{6,})")
_UA = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36"


def _clean_title(value: str) -> str:
    return normalize_text(_EM.sub("", value or ""))


def _parse_duration(value: str | None) -> int | None:
    if not value:
        return None
    parts = value.strip().split(":")
    try:
        nums = [int(p) for p in parts]
    except Exception:
        return None
    if len(nums) == 2:
        return (nums[0] * 60 + nums[1]) * 1000
    if len(nums) == 3:
        return (nums[0] * 3600 + nums[1] * 60 + nums[2]) * 1000
    return None


def _cover_url(url: str) -> str:
    if not url:
        return ""
    if url.startswith("//"):
        return "https:" + url
    if url.startswith("http"):
        return url
    return urljoin("https://www.bilibili.com/", url.lstrip("/"))


def _api_candidates(query: str, limit: int, *, page: int = 1) -> list[dict[str, Any]]:
    session = requests.Session()
    session.headers.update({
        "User-Agent": _UA,
        "Referer": "https://search.bilibili.com/all?keyword=" + requests.utils.quote(query),
        "Accept": "application/json, text/plain, */*",
    })
    # The search endpoint accepts a normal session cookie; this is not an auth bypass.
    session.get("https://www.bilibili.com/", timeout=15)
    r = session.get(
        "https://api.bilibili.com/x/web-interface/search/type",
        params={"search_type": "video", "keyword": query, "page": max(1, int(page))},
        timeout=20,
    )
    if r.status_code != 200:
        raise Video2AgentError("E_SEARCH", f"Bilibili search HTTP {r.status_code}", "Try again or update yt-dlp.")
    data = r.json()
    if data.get("code") != 0:
        raise Video2AgentError("E_SEARCH", f"Bilibili search code {data.get('code')}: {data.get('message')}", "Try again later.")
    items = (data.get("data") or {}).get("result") or []
    out = []
    for item in items:
        bvid = item.get("bvid") or ""
        if not _BV.fullmatch(str(bvid)):
            continue
        title = _clean_title(item.get("title") or "")
        if not title:
            continue
        mid = item.get("mid")
        out.append({
            "candidate_id": f"bili_{bvid}",
            "platform": "bilibili",
            "video_id": bvid,
            "url": f"https://www.bilibili.com/video/{bvid}",
            "title": title,
            "cover_url": _cover_url(item.get("pic") or ""),
            "duration_ms": _parse_duration(item.get("duration")),
            "uploader": _clean_title(item.get("author") or ""),
            # Keeping the uid is what makes "this uploader's other videos" possible
            # later; the name alone is ambiguous.
            "uploader_id": str(mid) if mid else None,
            "published_at": _date(item.get("pubdate")),
            "published_ts": int(item["pubdate"]) if str(item.get("pubdate") or "").isdigit() else None,
            "description": normalize_text(item.get("description") or "")[:300],
            "tags": _clean_title(item.get("tag") or ""),
            "stats": {k: item.get(k) for k in ("play", "like", "review") if item.get(k) is not None},
        })
        if len(out) >= limit:
            break
    return out


def _date(ts: Any) -> str | None:
    try:
        return datetime.fromtimestamp(int(ts), tz=timezone.utc).strftime("%Y-%m-%d")
    except Exception:
        return None


_RELATIVE = re.compile(r"^(\d+)\s*([dwm])$", re.IGNORECASE)


def parse_date_bound(value: str | None, *, now: datetime | None = None) -> int | None:
    """`2026-10-01`, `2026/10/01`, or a relative `7d` / `2w` / `3m` -> unix ts.

    Filters have to be readable by a person typing them, so both forms are
    accepted; anything unparseable raises instead of silently ignoring the filter.
    """
    raw = str(value or "").strip()
    if not raw:
        return None
    match = _RELATIVE.match(raw)
    if match:
        amount, unit = int(match.group(1)), match.group(2).lower()
        days = amount * {"d": 1, "w": 7, "m": 30}[unit]
        base = now or datetime.now(tz=timezone.utc)
        return int((base - timedelta(days=days)).timestamp())
    for fmt in ("%Y-%m-%d", "%Y/%m/%d", "%Y.%m.%d"):
        try:
            parsed = datetime.strptime(raw, fmt).replace(tzinfo=timezone.utc)
            return int(parsed.timestamp())
        except ValueError:
            continue
    raise Video2AgentError(
        "E_DATE",
        f"无法解析日期：{value!r}",
        "用 2026-10-01 这样的日期，或 7d / 2w / 3m 这样的相对时间。",
    )


def apply_filters(candidates: list[dict[str, Any]], *, uploader: str | None = None,
                  after: str | None = None, before: str | None = None) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    """Filter by uploader and publication window; report what the filter did.

    A filter that silently matches nothing is worse than no filter, so the
    caller gets the applied values and how many were dropped.
    """
    after_ts = parse_date_bound(after)
    before_ts = parse_date_bound(before)
    if after_ts is not None and before_ts is not None and after_ts > before_ts:
        raise Video2AgentError("E_DATE", "after 比 before 还晚", "把范围改成 after <= before。")
    wanted = str(uploader or "").strip().lower()
    kept: list[dict[str, Any]] = []
    for c in candidates:
        if wanted:
            name = str(c.get("uploader") or "").lower()
            uid = str(c.get("uploader_id") or "")
            if not (name == wanted or wanted in name or (wanted.isdigit() and uid == wanted)):
                continue
        ts = c.get("published_ts")
        if after_ts is not None and (ts is None or int(ts) < after_ts):
            continue
        if before_ts is not None and (ts is None or int(ts) > before_ts):
            continue
        kept.append(c)
    filters = {
        "uploader": uploader or None,
        "after": _date(after_ts) if after_ts else None,
        "before": _date(before_ts) if before_ts else None,
        "matched": len(kept),
        "dropped": len(candidates) - len(kept),
    }
    return kept, filters


def _finalize(query: str, candidates: list[dict[str, Any]], cfg: Config, covers: bool) -> dict[str, Any]:
    # Keep the order Bilibili returned. The old lexical _score sort was a weak
    # second-guess of the platform algorithm; the model now reads the metadata and
    # decides which candidates matter.
    for c in candidates:
        if covers and c.get("cover_url"):
            cp = cfg.covers_dir / f"bili_{c['video_id']}.jpg"
            got = download_cover(c["cover_url"], cp, allow_private=bool(cfg.get("allow_private_urls")))
            if got:
                c["cover_path"] = str(got)
                if not c.get("cover_ocr"):
                    try:
                        boxes = ocr_image(got)
                        c["cover_ocr"] = " ".join(b.get("text", "") for b in boxes)[:300]
                    except Exception:  # noqa: BLE001 - cover text is best-effort
                        # A failed cover read is not "the cover has no text"; just
                        # leave it out of the candidate instead of claiming empty.
                        c["cover_ocr"] = ""
    cover_paths = [c["cover_path"] for c in candidates if c.get("cover_path")]
    sheet = None
    if covers and len(cover_paths) >= 2:
        sheet = contact_sheet(cover_paths[:6], cfg.covers_dir / f"sheet_{stable_id('q', query, length=8)}.jpg", cols=3)
    return {
        "query": query,
        "platform": "bilibili",
        "candidates": candidates,
        "cover_sheet": str(sheet) if sheet else None,
        "warnings": [],
    }


def discover_bilibili(query: str, cfg: Config, *, limit: int = 8, covers: bool = True,
                      uploader: str | None = None, after: str | None = None,
                      before: str | None = None) -> dict[str, Any]:
    query = (query or "").strip()
    if not query:
        raise Video2AgentError("E_QUERY", "Search query is empty.", "Give a keyword or title.")
    filtered = bool(uploader or after or before)
    try:
        # Filters shrink the result set, so pull more pages before giving up.
        want = max(1, min(limit, 50))
        candidates: list[dict[str, Any]] = []
        # The Bilibili API returns one page of 20. Fetch enough pages for the
        # requested total instead of silently truncating a collection search.
        # Filters can be sparse; page 1 alone produced a false FILTER_EMPTY for
        # an uploader that only appeared on page 2.
        pages = 5 if filtered else max(1, min(5, (want + 19) // 20))
        for page in range(1, pages + 1):
            batch = _api_candidates(query, 20, page=page)
            if not batch:
                break
            candidates.extend(batch)
            if not filtered and len(candidates) >= want:
                break
            if filtered:
                # The raw page is almost always >= want, so breaking on it made
                # pages=5 useless for the default limit=8. Stop only when the
                # *filtered* set has enough rows.
                kept, _ = apply_filters(candidates, uploader=uploader, after=after, before=before)
                if len(kept) >= want:
                    break
        if candidates:
            kept, report = apply_filters(candidates, uploader=uploader, after=after, before=before)
            result = _finalize(query, kept[:want], cfg, covers)
            result["filters"] = report
            if filtered and not kept:
                result["warnings"].append({
                    "code": "FILTER_EMPTY",
                    "message": f"搜索到 {len(candidates)} 条，但没有一条满足 uploader/after/before 条件",
                    "remedy": "放宽日期范围，或去掉 uploader（名字要对得上，也可以直接填 UID）。",
                })
            return result
    except Exception as e:
        # A bad date is the caller's mistake: report it instead of falling back.
        if isinstance(e, Video2AgentError) and e.code == "E_DATE":
            raise
        # Fall back to yt-dlp's BiliBiliSearch; never silently return empty.
        try:
            from .sources import discover_bilibili as ytdlp_discover
            result = ytdlp_discover(query, cfg, limit=limit, covers=covers)
            result.setdefault("warnings", []).append({"code": "SEARCH_FALLBACK", "message": f"API search failed: {e}"})
            if filtered:
                result.setdefault("warnings", []).append({
                    "code": "FILTERS_UNSUPPORTED",
                    "message": "fallback 搜索不支持 uploader/after/before 过滤",
                })
            return result
        except Exception as e2:
            raise Video2AgentError("E_SEARCH", f"Bilibili search failed: {e}; fallback failed: {e2}", "Check network or update yt-dlp.") from e2
    return {"query": query, "platform": "bilibili", "candidates": [], "cover_sheet": None,
            "filters": {"uploader": uploader, "after": after, "before": before, "matched": 0, "dropped": 0},
            "warnings": [{"code": "NO_RESULTS", "message": "No results"}]}

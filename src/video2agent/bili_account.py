"""Read and manage a user's Bilibili library.

The module is deliberately small and boring: it talks to the same web API the
Bilibili site uses, keeps cookies in the existing QR-login jar, and never returns
a cookie to the caller. It is the account counterpart to the evidence pipeline:

* read: account, favorites folders/content, watch history;
* plan: deterministic summaries and a classification plan;
* write: create/rename/delete folders, add/remove videos, apply a plan.

Writes are separate calls and require an explicit confirmation from the caller.
There is no background writer and no retry of a write: Bilibili rate limits and
CSRF failures must stop the batch, not silently replay it.
"""

from __future__ import annotations

import re
import time
from dataclasses import dataclass
from datetime import datetime, timezone
from http.cookiejar import MozillaCookieJar
from pathlib import Path
from typing import Any
from urllib.parse import parse_qs, urljoin, urlparse

import requests

from .captions import cookie_path
from .net import assert_public_url
from .util import Video2AgentError

API = "https://api.bilibili.com"
UA = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
    "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/126 Safari/537.36"
)
READ_DELAY = 0.28
WRITE_DELAY = 1.15
MAX_FAVORITES = 5000
MAX_HISTORY = 500
MAX_PLAN_FOLDERS = 20
MAX_PLAN_VIDEOS = 100
MAX_FOLDER_TITLE = 20
SYSTEMIC_WRITE_ERRORS = frozenset({
    "E_BILI_LOGIN_REQUIRED", "E_BILI_CSRF", "E_BILI_RATE_LIMIT",
    "E_BILI_NETWORK", "E_BILI_ACCOUNT",
})


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _duration(seconds: Any) -> str:
    try:
        total = max(0, int(seconds))
    except (TypeError, ValueError):
        return ""
    h, rem = divmod(total, 3600)
    m, s = divmod(rem, 60)
    return f"{h}:{m:02d}:{s:02d}" if h else f"{m}:{s:02d}"


def _int(value: Any, default: int = 0) -> int:
    try:
        return int(value)
    except (TypeError, ValueError):
        return default


def _privacy(value: Any, default: int = 1) -> int:
    """Normalize privacy from 0/1, bool, or the strings used by plans/tools."""
    if isinstance(value, bool):
        return 0 if value else 1
    if isinstance(value, str):
        text = value.strip().lower()
        if text in ("public", "0", "公开"):
            return 0
        if text in ("private", "1", "私密"):
            return 1
    return 1 if _int(value, default) else 0


def _b23_short_url(value: Any) -> str | None:
    """Return the URL only when it is really a b23.tv short link.

    A substring check (`"b23.tv" in value`) let `http://127.0.0.1:9/?b23.tv`
    reach requests.get. Parse the host and scheme before any network call.
    """
    raw = str(value or "").strip()
    try:
        parsed = urlparse(raw)
    except ValueError:
        return None
    if parsed.scheme not in ("http", "https"):
        return None
    if (parsed.hostname or "").lower() not in ("b23.tv", "www.b23.tv"):
        return None
    return raw


def _video_ref(value: Any) -> tuple[str, str]:
    """Return (kind, value) for a BV id, av id, aid, or Bilibili URL."""
    raw = str(value or "").strip()
    if not raw:
        return "", ""
    if re.fullmatch(r"\d+", raw):
        return "aid", raw
    m = re.search(r"(BV[0-9A-Za-z]{10})", raw)
    if m:
        return "bvid", m.group(1)
    if re.fullmatch(r"av\d+", raw, re.I):
        return "aid", raw[2:]
    try:
        parsed = urlparse(raw)
        bv = re.search(r"(BV[0-9A-Za-z]{10})", parsed.path)
        if bv:
            return "bvid", bv.group(1)
        av = re.search(r"/av(\d+)", parsed.path)
        if av:
            return "aid", av.group(1)
        aid = parse_qs(parsed.query).get("aid", [""])[0]
        if aid.isdigit():
            return "aid", aid
    except ValueError:
        pass
    return "", raw


def _normalize_fav(item: dict[str, Any]) -> dict[str, Any]:
    upper = item.get("upper") or {}
    count = item.get("cnt_info") or {}
    return {
        "id": _int(item.get("id")),
        "bvid": str(item.get("bvid") or item.get("bv_id") or ""),
        "title": str(item.get("title") or ""),
        "duration_s": _int(item.get("duration")),
        "duration": _duration(item.get("duration")),
        "uploader": str(upper.get("name") or ""),
        "uploader_mid": _int(upper.get("mid")),
        "cover": str(item.get("cover") or ""),
        "intro": str(item.get("intro") or "")[:200],
        "fav_time": _int(item.get("fav_time")),
        "pub_time": _int(item.get("pubtime") or item.get("ctime")),
        "play": _int(count.get("play")),
        "invalid": bool(_int(item.get("attr")) & 1),
        "type": _int(item.get("type")),
    }


def _normalize_history(item: dict[str, Any]) -> dict[str, Any]:
    hist = item.get("history") or {}
    duration = _int(item.get("duration"))
    progress = _int(item.get("progress"))
    completed = bool(_int(item.get("is_finish")))
    # Regular archive history often leaves is_finish=0 even when the progress
    # bar is at the end; a near-complete progress is a better signal.
    if not completed and duration > 0 and progress >= 0 and progress >= duration * 0.95:
        completed = True
    return {
        "bvid": str(hist.get("bvid") or ""),
        "aid": _int(hist.get("oid")),
        "title": str(item.get("title") or ""),
        "part": str(hist.get("part") or ""),
        "uploader": str(item.get("author_name") or ""),
        "uploader_mid": _int(item.get("author_mid")),
        "duration_s": duration,
        "duration": _duration(duration),
        "progress_s": progress,
        "view_at": _int(item.get("view_at")),
        "finished": completed,
        "completed": completed,
        "fav": bool(_int(item.get("is_fav"))),
        "tag": str(item.get("tag_name") or ""),
    }


def _dedupe(items: list[dict[str, Any]], key: str = "bvid") -> list[dict[str, Any]]:
    seen: set[str] = set()
    out: list[dict[str, Any]] = []
    for item in items:
        k = str(item.get(key) or "")
        if not k or k in seen:
            continue
        seen.add(k)
        out.append(item)
    return out


def _top_uploaders(items: list[dict[str, Any]], limit: int = 10) -> list[dict[str, Any]]:
    counts: dict[str, int] = {}
    for item in items:
        name = str(item.get("uploader") or "").strip()
        if name:
            counts[name] = counts.get(name, 0) + 1
    return [
        {"name": name, "count": count}
        for name, count in sorted(counts.items(), key=lambda kv: (-kv[1], kv[0]))[:limit]
    ]


def _folder_titles(items: list[dict[str, Any]]) -> dict[str, list[str]]:
    groups: dict[str, list[str]] = {}
    for item in items:
        upper = str(item.get("uploader") or "").strip()
        bvid = str(item.get("bvid") or "")
        if upper and bvid:
            groups.setdefault(upper, []).append(bvid)
    return groups


@dataclass
class AccountClient:
    """A cookie-backed client for the user's own Bilibili library."""

    cfg: Any
    cookie_file: str | None = None
    delay_read: float = READ_DELAY
    delay_write: float = WRITE_DELAY
    _session: requests.Session | None = None

    def _err(self, code: str, message: str, remedy: str | None = None) -> Video2AgentError:
        return Video2AgentError(code, message, remedy)

    def _load(self) -> requests.Session:
        if self._session is not None:
            return self._session
        path = Path(self.cookie_file) if self.cookie_file else cookie_path(self.cfg)
        if not path or not path.is_file():
            raise self._err(
                "E_BILI_LOGIN_REQUIRED",
                "需要先登录 B 站，才能读取收藏夹或历史记录。",
                "在 Video2Agent 设置页扫码登录，或运行 video2agent biliauth --start。",
            )
        jar = MozillaCookieJar(str(path))
        try:
            jar.load(ignore_discard=True, ignore_expires=True)
        except Exception as exc:
            raise self._err(
                "E_BILI_COOKIES",
                "Cookie 文件无法读取。",
                "重新扫码登录，或导出一个 Netscape 格式的 cookie 文件。",
            ) from exc
        session = requests.Session()
        session.cookies.update(jar)
        if not session.cookies.get("SESSDATA"):
            raise self._err(
                "E_BILI_LOGIN_REQUIRED",
                "B 站登录已失效，Cookie 中没有 SESSDATA。",
                "重新扫码登录后再试。",
            )
        session.headers.update({
            "User-Agent": UA,
            "Referer": "https://www.bilibili.com/",
            "Accept": "application/json, text/plain, */*",
        })
        self._session = session
        return session

    def _request(
        self,
        path: str,
        *,
        params: dict[str, Any] | None = None,
        data: dict[str, Any] | None = None,
        write: bool = False,
        allow_already: bool = False,
    ) -> Any:
        session = self._load()
        url = API + path
        try:
            response = session.request(
                "POST" if write else "GET",
                url,
                params=params,
                data=data,
                timeout=25,
            )
        except requests.RequestException as exc:
            raise self._err(
                "E_BILI_NETWORK",
                "无法确认 B 站接口结果。" if write else "无法连接 B 站接口。",
                "先看账号里是否已经生效，不要直接重复写。" if write else "检查网络后重试。",
            ) from exc
        if response.status_code in (412, 429):
            raise self._err(
                "E_BILI_RATE_LIMIT",
                "B 站接口返回限流或风控。",
                "等几分钟再试；写操作不要重试，先看账号里是否已经生效。",
            )
        if response.status_code >= 500:
            raise self._err(
                "E_BILI_API",
                f"B 站接口返回 HTTP {response.status_code}。",
                "先看账号里是否已经生效，不要直接重复写。" if write else "稍后重试。",
            )
        try:
            payload = response.json()
        except ValueError as exc:
            raise self._err(
                "E_BILI_API",
                "B 站接口返回了非 JSON 内容。",
                "先看账号里是否已经生效，不要直接重复写。" if write else "检查登录状态或稍后重试。",
            ) from exc
        code = payload.get("code")
        if code == 0:
            return payload.get("data")
        message = str(payload.get("message") or f"B 站错误 {code}")
        if code in (-101, -4009):
            raise self._err("E_BILI_LOGIN_REQUIRED", f"B 站登录已失效：{message}", "重新扫码登录。")
        if code == -111:
            raise self._err("E_BILI_CSRF", "B 站 CSRF 校验失败。", "重新登录后再试；写操作没有重试。")
        if code == -102:
            raise self._err("E_BILI_ACCOUNT", "B 站账号当前不可操作。", "先在 B 站网页确认账号状态。")
        if code in (-352, -412, -509):
            raise self._err("E_BILI_RATE_LIMIT", f"B 站风控拒绝：{message}", "等几分钟再试；写操作先确认是否生效。")
        if code == 11001:
            raise self._err("E_ACCOUNT_ARGS", f"收藏夹名称无效或已存在：{message}", "换一个 20 字以内的标题。")
        if code == 11201 and allow_already:
            return {"already": True}
        raise self._err(
            "E_BILI_API",
            f"B 站接口失败：{message}（{code}）",
            "先看账号里是否已经生效，不要直接重复写。" if write else "确认登录状态和权限后重试。",
        )

    def _csrf(self) -> str:
        session = self._load()
        token = session.cookies.get("bili_jct")
        if not token:
            raise self._err(
                "E_BILI_CSRF",
                "Cookie 中没有 bili_jct，无法执行写操作。",
                "重新扫码登录，让登录 jar 包含 bili_jct。",
            )
        return str(token)

    def _wait(self, write: bool) -> None:
        time.sleep(self.delay_write if write else self.delay_read)

    def info(self) -> dict[str, Any]:
        data = self._request("/x/web-interface/nav") or {}
        if not data.get("isLogin"):
            raise self._err("E_BILI_LOGIN_REQUIRED", "B 站登录已失效。", "重新扫码登录。")
        return {
            "ok": True,
            "mid": _int(data.get("mid")),
            "uname": str(data.get("uname") or ""),
            "avatar": str(data.get("face") or ""),
            "vip": bool(_int(data.get("vipStatus"))),
            "logged_in": True,
        }

    def folders(self) -> dict[str, Any]:
        info = self.info()
        data = self._request(
            "/x/v3/fav/folder/created/list-all",
            params={"up_mid": info["mid"]},
        ) or {}
        raw = data.get("list") if isinstance(data, dict) else data
        folders = []
        for item in raw or []:
            if not isinstance(item, dict):
                continue
            attr = item.get("attr")
            folders.append({
                "id": _int(item.get("id")),
                "title": str(item.get("title") or ""),
                "count": _int(item.get("media_count")),
                "privacy": (
                    "unknown" if attr is None
                    else ("private" if _int(attr) & 1 else "public")
                ),
            })
        return {"ok": True, "mid": info["mid"], "uname": info["uname"], "folders": folders}

    def favorites(self, folder_id: int | str, limit: int = 200) -> dict[str, Any]:
        fid = _int(folder_id)
        if fid <= 0:
            raise self._err("E_ACCOUNT_ARGS", "收藏夹 id 无效。", "先用 account folders 列出收藏夹。")
        limit = max(1, min(MAX_FAVORITES, _int(limit, 200)))
        items: list[dict[str, Any]] = []
        page = 1
        folder: dict[str, Any] = {"id": fid, "title": "", "count": 0}
        while len(items) < limit:
            data = self._request(
                "/x/v3/fav/resource/list",
                params={"media_id": fid, "pn": page, "ps": 20, "platform": "web"},
            ) or {}
            info = data.get("info") or {}
            if page == 1:
                folder = {
                    "id": _int(info.get("id")) or fid,
                    "title": str(info.get("title") or ""),
                    "count": _int(info.get("media_count")),
                    "privacy": "private" if _int(info.get("attr")) & 1 else "public",
                }
            medias = data.get("medias") or []
            for item in medias:
                if isinstance(item, dict) and _int(item.get("type")) == 2:
                    items.append(_normalize_fav(item))
                    if len(items) >= limit:
                        break
            if not data.get("has_more") or not medias:
                break
            page += 1
            self._wait(False)
        return {
            "ok": True,
            "folder": folder,
            "items": items[:limit],
            "returned": len(items[:limit]),
            "truncated": len(items) >= limit and bool(data.get("has_more")) if "data" in locals() else False,
        }

    def history(self, days: int = 30, limit: int = 100) -> dict[str, Any]:
        days = max(1, min(365, _int(days, 30)))
        limit = max(1, min(MAX_HISTORY, _int(limit, 100)))
        cutoff = int(_now().timestamp()) - days * 86400
        items: list[dict[str, Any]] = []
        cursor: dict[str, Any] = {"max": 0, "view_at": 0, "business": ""}
        truncated = False
        while len(items) < limit:
            data = self._request("/x/web-interface/history/cursor", params=cursor) or {}
            batch = data.get("list") or []
            if not batch:
                break
            old_hit = False
            for index, item in enumerate(batch):
                if not isinstance(item, dict):
                    continue
                row = _normalize_history(item)
                if row["view_at"] <= 0:
                    continue
                if row["view_at"] < cutoff:
                    old_hit = True
                    break
                items.append(row)
                if len(items) >= limit:
                    truncated = index < len(batch) - 1 or bool((data.get("cursor") or {}).get("max"))
                    break
            if old_hit or len(items) >= limit:
                break
            nxt = data.get("cursor") or {}
            if not nxt.get("max"):
                break
            cursor = {
                "max": nxt.get("max") or 0,
                "view_at": nxt.get("view_at") or 0,
                "business": nxt.get("business") or "",
            }
            self._wait(False)
        return {"ok": True, "days": days, "items": items, "returned": len(items), "truncated": truncated}

    def _resolve_aid(self, video: Any) -> tuple[int, str]:
        kind, value = _video_ref(video)
        if kind == "aid":
            aid = _int(value)
            if aid <= 0:
                raise self._err("E_ACCOUNT_ARGS", f"无效的 aid：{video}", "传 BV 号或 av 号。")
            return aid, ""
        short = _b23_short_url(video)
        if kind != "bvid" and short:
            current = short
            moved = None
            for _ in range(6):
                try:
                    assert_public_url(current)
                    moved = requests.get(
                        current, headers={"User-Agent": UA, "Referer": "https://www.bilibili.com/"},
                        timeout=15, allow_redirects=False,
                    )
                except Video2AgentError as exc:
                    raise self._err("E_ACCOUNT_ARGS", f"短链目标不可访问：{current}", exc.remedy) from exc
                except requests.RequestException as exc:
                    raise self._err("E_ACCOUNT_ARGS", f"短链无法解析：{video}", "展开成 bilibili.com/video/BV… 再试。") from exc
                if moved.status_code in (301, 302, 303, 307, 308) and moved.headers.get("location"):
                    current = urljoin(current, moved.headers["location"])
                    continue
                if moved.status_code >= 400:
                    raise self._err("E_ACCOUNT_ARGS", f"短链返回 HTTP {moved.status_code}", "展开成 bilibili.com/video/BV… 再试。")
                break
            if moved is None or moved.status_code in (301, 302, 303, 307, 308):
                raise self._err("E_ACCOUNT_ARGS", "短链跳转次数过多", "展开成 bilibili.com/video/BV… 再试。")
            kind, value = _video_ref(current)
        elif kind != "bvid" and "b23.tv" in str(video):
            raise self._err("E_ACCOUNT_ARGS", f"不是有效的 b23.tv 链接：{video}", "传 https://b23.tv/… 或 bilibili.com/video/BV…。")
        if kind != "bvid":
            raise self._err("E_ACCOUNT_ARGS", f"无法识别视频：{video}", "传 BV 号、av 号或视频 URL。")
        data = self._request("/x/web-interface/view", params={"bvid": value}) or {}
        aid = _int(data.get("aid"))
        if aid <= 0:
            raise self._err("E_ACCOUNT_ARGS", f"找不到视频：{value}", "确认 BV 号有效。")
        return aid, str(data.get("bvid") or value)

    def add_videos(self, folder_id: int | str, videos: list[Any]) -> dict[str, Any]:
        fid = _int(folder_id)
        if fid <= 0:
            raise self._err("E_ACCOUNT_ARGS", "收藏夹 id 无效。", "先用 account folders 列出收藏夹。")
        videos = [v for v in videos if str(v).strip()]
        if not videos:
            raise self._err("E_ACCOUNT_ARGS", "没有要加入的视频。", "传至少一个 BV 号或 URL。")
        if len(videos) > MAX_PLAN_VIDEOS:
            raise self._err("E_ACCOUNT_ARGS", f"一次最多加入 {MAX_PLAN_VIDEOS} 个视频。", "拆成几批再操作。")
        csrf = self._csrf()
        results = []
        fatal: Video2AgentError | None = None
        for video in videos:
            try:
                aid, bvid = self._resolve_aid(video)
                data = self._request(
                    "/x/v3/fav/resource/deal",
                    data={
                        "rid": aid,
                        "type": 2,
                        "add_media_ids": str(fid),
                        "del_media_ids": "",
                        "csrf": csrf,
                        "platform": "web",
                    },
                    write=True,
                    allow_already=True,
                )
                results.append({
                    "video": str(video),
                    "bvid": bvid,
                    "aid": aid,
                    "ok": True,
                    "already": bool(isinstance(data, dict) and data.get("already")),
                })
            except Video2AgentError as exc:
                results.append({
                    "video": str(video),
                    "ok": False,
                    "error": exc.as_dict(),
                })
                if exc.code in SYSTEMIC_WRITE_ERRORS:
                    fatal = exc
                    break
            self._wait(True)
        failed = [r for r in results if not r.get("ok")]
        added = sum(1 for r in results if r.get("ok") and not r.get("already"))
        already = sum(1 for r in results if r.get("ok") and r.get("already"))
        payload = {
            "ok": not failed,
            "folder_id": fid,
            "results": results,
            "added": added,
            "already": already,
            "failed": len(failed),
            "not_attempted": len(videos) - len(results),
        }
        if failed:
            payload["error"] = {
                "code": "E_ACCOUNT_PARTIAL",
                "message": f"{len(failed)} 个视频加入失败" + ("，批次已停止。" if fatal else "。"),
                "remedy": "检查登录、视频是否有效或账号风控；不要重复提交成功的视频。",
            }
        if fatal:
            payload["stopped"] = fatal.as_dict()
        return payload

    def remove_videos(self, folder_id: int | str, videos: list[Any]) -> dict[str, Any]:
        fid = _int(folder_id)
        if fid <= 0:
            raise self._err("E_ACCOUNT_ARGS", "收藏夹 id 无效。", "先用 account folders 列出收藏夹。")
        videos = [v for v in videos if str(v).strip()]
        if not videos:
            raise self._err("E_ACCOUNT_ARGS", "没有要移除的视频。", "传至少一个 BV 号或 URL。")
        if len(videos) > MAX_PLAN_VIDEOS:
            raise self._err("E_ACCOUNT_ARGS", f"一次最多移除 {MAX_PLAN_VIDEOS} 个视频。", "拆成几批再操作。")
        csrf = self._csrf()
        results = []
        fatal: Video2AgentError | None = None
        for video in videos:
            try:
                aid, bvid = self._resolve_aid(video)
                self._request(
                    "/x/v3/fav/resource/batch-del",
                    data={"resources": f"{aid}:2", "media_id": fid, "csrf": csrf, "platform": "web"},
                    write=True,
                )
                results.append({"video": str(video), "bvid": bvid, "aid": aid, "ok": True})
            except Video2AgentError as exc:
                results.append({"video": str(video), "ok": False, "error": exc.as_dict()})
                if exc.code in SYSTEMIC_WRITE_ERRORS:
                    fatal = exc
                    break
            self._wait(True)
        failed = [r for r in results if not r.get("ok")]
        payload = {
            "ok": not failed,
            "folder_id": fid,
            "results": results,
            "removed": len(results) - len(failed),
            "failed": len(failed),
            "not_attempted": len(videos) - len(results),
        }
        if failed:
            payload["error"] = {
                "code": "E_ACCOUNT_PARTIAL",
                "message": f"{len(failed)} 个视频移除失败" + ("，批次已停止。" if fatal else "。"),
                "remedy": "检查登录、视频是否仍在收藏夹或账号风控；不要重复提交成功的视频。",
            }
        if fatal:
            payload["stopped"] = fatal.as_dict()
        return payload

    def create_folder(self, title: str, intro: str = "", privacy: int = 1) -> dict[str, Any]:
        title = str(title or "").strip()
        if not 1 <= len(title) <= MAX_FOLDER_TITLE:
            raise self._err("E_ACCOUNT_ARGS", f"收藏夹标题需要 1–{MAX_FOLDER_TITLE} 个字符。", "换一个短标题。")
        if any(ord(c) < 32 for c in title):
            raise self._err("E_ACCOUNT_ARGS", "收藏夹标题包含控制字符。", "换一个普通标题。")
        existing = {f["title"]: f for f in self.folders()["folders"]}
        if title in existing:
            raise self._err(
                "E_ACCOUNT_EXISTS",
                f"收藏夹「{title}」已存在（id={existing[title]['id']}）。",
                "把视频加入这个 id，或换一个标题。",
            )
        data = self._request(
            "/x/v3/fav/folder/add",
            data={
                "title": title,
                "intro": str(intro or "")[:200],
                "privacy": _privacy(privacy, 1),
                "csrf": self._csrf(),
            },
            write=True,
        ) or {}
        self._wait(True)
        folder_id = _int(data.get("id"))
        if folder_id <= 0:
            raise self._err("E_BILI_API", "B 站没有返回新收藏夹 id，写入结果不确定。", "先运行 account folders 确认是否已创建，再决定是否重试。")
        actual_private = bool(_int(data.get("attr")) & 1) if "attr" in data else bool(_int(privacy, 1))
        return {
            "ok": True,
            "folder": {
                "id": folder_id,
                "title": str(data.get("title") or title),
                "privacy": "private" if actual_private else "public",
            },
        }

    def rename_folder(self, folder_id: int | str, title: str, privacy: int | None = None) -> dict[str, Any]:
        fid = _int(folder_id)
        title = str(title or "").strip()
        if fid <= 0 or not 1 <= len(title) <= MAX_FOLDER_TITLE:
            raise self._err("E_ACCOUNT_ARGS", "收藏夹 id/标题无效。", f"id 必须是数字，标题 1–{MAX_FOLDER_TITLE} 字符。")
        if any(ord(c) < 32 for c in title):
            raise self._err("E_ACCOUNT_ARGS", "收藏夹标题包含控制字符。", "换一个普通标题。")
        if privacy is None:
            existing = {f["id"]: f for f in self.folders()["folders"]}
            if fid not in existing:
                raise self._err("E_ACCOUNT_ARGS", f"收藏夹不存在：{fid}", "先用 account folders 确认 id。")
            privacy = 1 if existing[fid].get("privacy") != "public" else 0
        data = self._request(
            "/x/v3/fav/folder/edit",
            data={"media_id": fid, "title": title, "privacy": _privacy(privacy, 1), "csrf": self._csrf()},
            write=True,
        ) or {}
        self._wait(True)
        return {
            "ok": True,
            "folder": {
                "id": fid,
                "title": str(data.get("title") or title),
                "privacy": "private" if _int(privacy, 1) else "public",
            },
        }

    def delete_folder(self, folder_id: int | str, expected_title: str | None = None) -> dict[str, Any]:
        fid = _int(folder_id)
        if fid <= 0:
            raise self._err("E_ACCOUNT_ARGS", "收藏夹 id 无效。", "先用 account folders 列出收藏夹。")
        target = next((f for f in self.folders()["folders"] if f["id"] == fid), None)
        if target is None:
            raise self._err("E_ACCOUNT_ARGS", f"收藏夹不存在：{fid}", "先用 account folders 确认 id。")
        if expected_title and str(expected_title).strip() != target["title"]:
            raise self._err(
                "E_ACCOUNT_TARGET",
                f"目标标题不匹配：id={fid} 实际是「{target['title']}」。",
                "重新确认收藏夹 id 和标题，未删除任何内容。",
            )
        self._request(
            "/x/v3/fav/folder/del",
            data={"media_ids": str(fid), "csrf": self._csrf()},
            write=True,
        )
        self._wait(True)
        return {"ok": True, "deleted_folder_id": fid, "deleted": target}

    def analyze(self, source: str = "favorites", folder_id: int | str | None = None, days: int = 30,
                limit: int = MAX_HISTORY) -> dict[str, Any]:
        source = str(source or "favorites").lower()
        if source == "history":
            payload = self.history(days=days, limit=limit)
            items = payload["items"]
            unique = _dedupe(items)
            finished = sum(1 for item in items if item.get("finished"))
            watched = sum(max(0, _int(item.get("progress_s"))) for item in items)
            return {
                "ok": True,
                "source": "history",
                "days": days,
                "count": len(items),
                "limit": limit,
                "truncated": bool(payload.get("truncated")),
                "complete": not bool(payload.get("truncated")),
                "unique": len(unique),
                "finished": finished,
                "unfinished": len(items) - finished,
                "total_duration_s": sum(item.get("duration_s", 0) for item in items),
                "watched_s": watched,
                "progress_seconds": watched,
                "top_uploaders": _top_uploaders(items),
                "unfinished_items": [
                    {
                        "bvid": item.get("bvid"),
                        "title": item.get("title"),
                        "uploader": item.get("uploader"),
                        "duration": item.get("duration"),
                        "progress_s": item.get("progress_s"),
                        "view_at": item.get("view_at"),
                    }
                    for item in items if not item.get("finished")
                ][:10],
            }
        if source != "favorites":
            raise self._err("E_ACCOUNT_ARGS", "source 只能是 favorites 或 history。")
        if folder_id is None:
            raise self._err("E_ACCOUNT_ARGS", "分析收藏夹需要 --folder。", "先用 account folders 查看 id。")
        payload = self.favorites(folder_id, limit=MAX_FAVORITES)
        items = payload["items"]
        valid = [item for item in items if not item.get("invalid")]
        durations = [_int(item.get("duration_s")) for item in valid]
        duplicate = len(items) - len({item.get("bvid") for item in items})
        return {
            "ok": True,
            "source": "favorites",
            "folder": payload["folder"],
            "count": len(items),
            "valid": len(valid),
            "invalid": len(items) - len(valid),
            "duplicates": duplicate,
            "total_duration_s": sum(durations),
            "total_duration": _duration(sum(durations)),
            "long_videos": sum(1 for d in durations if d >= 1800),
            "short_videos": sum(1 for d in durations if d and d < 600),
            "top_uploaders": _top_uploaders(valid),
        }

    def classify_plan(self, source: str = "favorites", folder_id: int | str | None = None, days: int = 30) -> dict[str, Any]:
        source = str(source or "favorites").lower()
        if source == "history":
            items = self.history(days=days, limit=MAX_HISTORY)["items"]
        elif source == "favorites":
            if folder_id is None:
                raise self._err("E_ACCOUNT_ARGS", "收藏夹分类计划需要 --folder。")
            items = self.favorites(folder_id, limit=MAX_FAVORITES)["items"]
        else:
            raise self._err("E_ACCOUNT_ARGS", "source 只能是 favorites 或 history。")
        groups = []
        used_titles: set[str] = set()
        for uploader, videos in sorted(_folder_titles(items).items(), key=lambda kv: (-len(kv[1]), kv[0])):
            if len(videos) < 2:
                continue
            title = uploader[:MAX_FOLDER_TITLE] or "未命名"
            if title in used_titles:
                for n in range(2, 100):
                    suffix = f" {n}"
                    candidate = (uploader[:MAX_FOLDER_TITLE - len(suffix)] + suffix).strip()
                    if candidate not in used_titles:
                        title = candidate
                        break
            used_titles.add(title)
            groups.append({
                "title": title,
                "reason": f"同一 UP 主，{len(videos)} 个视频",
                "videos": videos,
            })
        # Reserve the catch-all slot before computing what is left, otherwise
        # videos from trimmed uploader groups are neither planned nor counted.
        if len(groups) >= MAX_PLAN_FOLDERS:
            groups = groups[:MAX_PLAN_FOLDERS - 1]
        remaining = [item for item in items if item.get("bvid") and item.get("bvid") not in {
            bvid for group in groups for bvid in group["videos"]
        }]
        if remaining:
            groups.append({
                "title": "待分类",
                "reason": "未形成稳定 UP 主分组",
                "videos": [item["bvid"] for item in remaining if item.get("bvid")],
            })
        groups = groups[:MAX_PLAN_FOLDERS]
        by_bvid = {str(item.get("bvid")): item for item in items if item.get("bvid")}
        plan_folders = []
        used = 0
        for group in groups:
            if used >= MAX_PLAN_VIDEOS:
                break
            videos = group["videos"][:MAX_PLAN_VIDEOS - used]
            if not videos:
                continue
            plan_folders.append({
                "title": group["title"],
                "reason": group["reason"],
                "videos": videos,
                "sample_titles": [
                    str(by_bvid[bvid].get("title") or "")
                    for bvid in videos[:3] if bvid in by_bvid
                ],
                "privacy": 1,
            })
            used += len(videos)
        total_group_videos = sum(len(group["videos"]) for group in groups)
        if not plan_folders:
            return {
                "ok": True,
                "source": source,
                "count": len(items),
                "empty": True,
                "groups": [],
                "plan": {"folders": [], "video_count": 0, "truncated": False},
                "note": "没有可分类的视频。",
            }
        return {
            "ok": True,
            "source": source,
            "count": len(items),
            # Keep the display summary small; the full video lists live once in
            # `plan`, which is the object the user can apply.
            "groups": [
                {"title": folder["title"], "count": len(folder["videos"]), "reason": folder["reason"]}
                for folder in plan_folders
            ],
            "plan": {
                "folders": plan_folders,
                "video_count": used,
                "truncated": used < total_group_videos,
            },
            "note": "这是按 UP 主/数量生成的保守草案；可在 DSH 里再按主题调整后再 apply。",
        }

    def apply_plan(self, plan: dict[str, Any], confirm: bool = False, default_privacy: int = 1) -> dict[str, Any]:
        if not isinstance(plan, dict) or not isinstance(plan.get("folders"), list):
            raise self._err("E_ACCOUNT_PLAN", "计划格式应为 {folders:[{title,videos}]}。")
        folders = plan["folders"]
        if not folders:
            raise self._err("E_ACCOUNT_PLAN", "计划里没有收藏夹。", "先运行 classify-plan，或提供至少一个 folders 项。")
        if not 1 <= len(folders) <= MAX_PLAN_FOLDERS:
            raise self._err("E_ACCOUNT_PLAN", f"一次最多处理 {MAX_PLAN_FOLDERS} 个收藏夹。")
        normalized: list[dict[str, Any]] = []
        seen_titles: set[str] = set()
        total_videos = 0
        for item in folders:
            if not isinstance(item, dict):
                raise self._err("E_ACCOUNT_PLAN", "每个收藏夹必须是对象。")
            title = str(item.get("title") or "").strip()
            if not title or title in seen_titles:
                raise self._err("E_ACCOUNT_PLAN", f"收藏夹标题为空或重复：{title!r}。")
            if len(title) > MAX_FOLDER_TITLE:
                raise self._err("E_ACCOUNT_PLAN", f"收藏夹标题超过 {MAX_FOLDER_TITLE} 个字符：{title}")
            if any(ord(c) < 32 for c in title):
                raise self._err("E_ACCOUNT_PLAN", f"收藏夹标题包含控制字符：{title!r}")
            seen_titles.add(title)
            videos = item.get("videos") or []
            if not isinstance(videos, list):
                raise self._err("E_ACCOUNT_PLAN", f"{title} 的 videos 必须是数组。")
            clean_videos = [str(v).strip() for v in videos if str(v).strip()]
            total_videos += len(clean_videos)
            normalized.append({
                "title": title,
                "intro": str(item.get("intro") or "")[:200],
                "privacy": _privacy(item.get("privacy"), default_privacy),
                "videos": clean_videos,
            })
        if total_videos > MAX_PLAN_VIDEOS:
            raise self._err("E_ACCOUNT_PLAN", f"一次最多处理 {MAX_PLAN_VIDEOS} 个视频。")
        existing = {f["title"]: f for f in self.folders()["folders"]}
        if not confirm:
            reused_preview = []
            privacy_warnings = []
            would_create = []
            for item in normalized:
                hit = existing.get(item["title"])
                if hit:
                    reused_preview.append({
                        "title": item["title"], "id": hit["id"], "privacy": hit.get("privacy"),
                    })
                    if hit.get("privacy") != ("private" if item["privacy"] else "public"):
                        privacy_warnings.append({
                            "title": item["title"],
                            "current": hit.get("privacy"),
                            "requested": "private" if item["privacy"] else "public",
                            "note": "复用现有收藏夹时不会改变它的公开状态。",
                        })
                else:
                    would_create.append({
                        "title": item["title"], "privacy": "private" if item["privacy"] else "public",
                    })
            return {
                "ok": True,
                "dry_run": True,
                "folders": normalized,
                "video_count": total_videos,
                "reused": reused_preview,
                "would_create": would_create,
                "privacy_warnings": privacy_warnings,
            }
        created = []
        reused = []
        folder_failures = []
        valid_items = []
        for item in normalized:
            if item["title"] in existing:
                item["id"] = existing[item["title"]]["id"]
                reused.append({
                    "title": item["title"],
                    "id": item["id"],
                    "privacy": existing[item["title"]].get("privacy"),
                })
                valid_items.append(item)
            else:
                try:
                    made = self.create_folder(item["title"], item["intro"], item["privacy"])
                except Video2AgentError as exc:
                    folder_failures.append({"title": item["title"], "error": exc.as_dict()})
                    continue
                item["id"] = made["folder"]["id"]
                created.append(made["folder"])
                valid_items.append(item)
        by_video: dict[str, list[int]] = {}
        for item in valid_items:
            for video in item["videos"]:
                by_video.setdefault(video, []).append(item["id"])
        results = []
        fatal: Video2AgentError | None = None
        for video, folder_ids in by_video.items():
            try:
                aid, bvid = self._resolve_aid(video)
                data = self._request(
                    "/x/v3/fav/resource/deal",
                    data={
                        "rid": aid,
                        "type": 2,
                        "add_media_ids": ",".join(str(x) for x in folder_ids),
                        "del_media_ids": "",
                        "csrf": self._csrf(),
                        "platform": "web",
                    },
                    write=True,
                    allow_already=True,
                )
                results.append({
                    "video": video, "bvid": bvid, "folder_ids": folder_ids,
                    "ok": True, "already": bool(isinstance(data, dict) and data.get("already")),
                })
            except Video2AgentError as exc:
                results.append({"video": video, "folder_ids": folder_ids, "ok": False, "error": exc.as_dict()})
                if exc.code in SYSTEMIC_WRITE_ERRORS:
                    fatal = exc
                    break
            self._wait(True)
        failed = [r for r in results if not r.get("ok")]
        added = sum(1 for r in results if r.get("ok") and not r.get("already"))
        already = sum(1 for r in results if r.get("ok") and r.get("already"))
        payload = {
            "ok": not failed and not folder_failures,
            "dry_run": False,
            "created": created,
            "reused": reused,
            "folder_failures": folder_failures,
            "added": added,
            "already": already,
            "failed": len(failed),
            "not_attempted": len(by_video) - len(results),
            "results": results,
        }
        if failed or folder_failures:
            payload["error"] = {
                "code": "E_ACCOUNT_PARTIAL",
                "message": f"{len(failed)} 个视频加入失败"
                           + (f"，{len(folder_failures)} 个收藏夹创建失败" if folder_failures else "")
                           + ("，批次已停止。" if fatal else "。"),
                "remedy": "检查登录/标题/风控；成功的结果不要重复提交。",
            }
        if fatal:
            payload["stopped"] = fatal.as_dict()
        return payload


def account_client(cfg: Any, cookie_file: str | None = None) -> AccountClient:
    return AccountClient(cfg=cfg, cookie_file=cookie_file)

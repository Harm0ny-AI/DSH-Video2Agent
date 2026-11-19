from __future__ import annotations

import json
import os
import re
import sys
import time
from pathlib import Path
from typing import Any

import requests

from .config import Config
from .links import normalize_video_ref
from .media import contact_sheet, download_cover, probe
from .net import assert_public_url
from .text import language_hint, normalize_text
from .util import Video2AgentError, ensure_dir, iter_json_lines, run, sha256_file, stable_id, which

_BV = re.compile(r"(BV[0-9A-Za-z]{6,})")


def _ytdlp() -> list[str]:
    p = which("yt-dlp")
    if p:
        return [p]
    try:
        import yt_dlp  # noqa: F401
        return [sys.executable, "-m", "yt_dlp"]
    except Exception as e:
        raise Video2AgentError("E_YTDLP", "yt-dlp is not installed.", "pip install yt-dlp") from e


def _bilibili_cookies(cfg: Config) -> Path | None:
    """Anonymous cookies fix Bilibili's 412 on metadata/download; no login."""
    path = cfg.home / "cookies" / "bilibili.txt"
    if path.exists() and time.time() - path.stat().st_mtime < 3600:
        return path
    try:
        s = requests.Session()
        s.headers.update({"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 Chrome/131 Safari/537.36"})
        s.get("https://www.bilibili.com/", timeout=15)
        if not s.cookies:
            return path if path.exists() else None
        path.parent.mkdir(parents=True, exist_ok=True)
        lines = ["# Netscape HTTP Cookie File"]
        for c in s.cookies:
            domain = c.domain or ".bilibili.com"
            if not domain.startswith("."):
                domain = "." + domain
            expires = int(c.expires) if c.expires else int(time.time()) + 86400
            lines.append("\t".join([domain, "TRUE", c.path or "/", "FALSE", str(expires), c.name, c.value]))
        path.write_text("\n".join(lines) + "\n", encoding="utf-8")
        try:
            os.chmod(path, 0o600)
        except Exception:
            pass
        return path
    except Exception:
        return path if path.exists() else None


def _common_args(cfg: Config, url: str = "") -> list[str]:
    args = ["--no-warnings", "--no-playlist", "--no-progress"]
    cookies = cfg.get("cookies_file")
    lowered = url.lower()
    if "bilibili.com" in lowered or "b23.tv" in lowered:
        # A saved QR login wins: it unlocks CC/AI subtitles and higher qualities.
        login = cfg.home / "cookies" / "bilibili-login.txt"
        if login.is_file():
            cookies = str(login)
        elif not cookies:
            cookies = _bilibili_cookies(cfg)
    if cookies:
        args += ["--cookies", str(cookies)]
    return args


def bilibili_view_metadata(ref: dict[str, Any], cfg: Config, *, timeout: float = 2.0) -> dict[str, Any] | None:
    """Fast Bilibili metadata for the composer preview.

    The public view endpoint returns title/cover/duration/uploader in one
    request; yt-dlp spends seconds extracting the same fields. Any failure
    returns None so resolve_info can fall back to the existing path.
    """
    bvid = str(ref.get("bvid") or "").strip()
    aid = ref.get("av_id")
    if not bvid and not aid:
        return None
    params = {"bvid": bvid} if bvid else {"aid": aid}
    try:
        response = requests.get(
            "https://api.bilibili.com/x/web-interface/view",
            params=params,
            headers={"User-Agent": "Mozilla/5.0", "Referer": "https://www.bilibili.com/"},
            timeout=timeout,
        )
        payload = response.json()
        data = payload.get("data") if isinstance(payload, dict) else None
        if not isinstance(data, dict) or not data.get("title"):
            return None
        return {
            "title": data.get("title"),
            "uploader": (data.get("owner") or {}).get("name"),
            "duration": data.get("duration"),
            "thumbnail": data.get("pic"),
            "description": data.get("desc") or "",
            "webpage_url": "https://www.bilibili.com/video/" + (bvid or "av" + str(aid)),
            "extractor_key": "BiliBili",
            "id": bvid or str(aid),
            "pubdate": data.get("pubdate"),
        }
    except Exception:
        return None


def fetch_metadata(url: str, cfg: Config, *, timeout: float = 45) -> dict[str, Any]:
    cmd = _ytdlp() + ["--dump-single-json", "--skip-download"] + _common_args(cfg, url) + [url]
    res = run(cmd, timeout=timeout)
    if not res.ok:
        detail = (res.stderr or res.stdout).strip()[-1200:]
        raise Video2AgentError("E_METADATA", f"Could not read metadata: {url}\n{detail}", "Check the URL, cookies, or platform support.")
    for line in res.stdout.splitlines():
        line = line.strip()
        if line.startswith("{"):
            try:
                return json.loads(line)
            except json.JSONDecodeError:
                continue
    raise Video2AgentError("E_METADATA", "yt-dlp returned no JSON metadata.", "Try updating yt-dlp.")


def _safe_filename(name: str) -> str:
    name = re.sub(r"[^\w.\- ]+", "_", name, flags=re.UNICODE).strip()
    return name[:80] or "video"


def download_video(url: str, cfg: Config, *, video_id: str, timeout: float = 3600) -> tuple[Path, dict[str, Any]]:
    meta = fetch_metadata(url, cfg)
    out_dir = ensure_dir(cfg.media_dir / video_id)
    template = str(out_dir / "source.%(ext)s")
    cmd = _ytdlp() + [
        "-f", str(cfg.get("ytdlp_format")),
        "--merge-output-format", "mp4",
        # Three videos once burned ~20 minutes on a stalled Bilibili CDN before
        # failing with E_DOWNLOAD: yt-dlp's default is ten retries per download and
        # ten per fragment, so one dead mirror multiplied the wait. Three of each
        # bounds a dead mirror to about a minute (measured 81s against a server
        # that sends headers then stalls). --socket-timeout is deliberately not
        # set: yt-dlp already defaults to 20s, and passing it would override a
        # user's own yt-dlp configuration.
        "--retries", "3",
        "--fragment-retries", "3",
        "--write-subs", "--write-auto-subs",
        "--sub-langs", "zh.*,en.*",
        "--convert-subs", "vtt",
        "--print", "after_move:filepath",
        "-o", template,
    ] + _common_args(cfg, url) + [url]
    res = run(cmd, timeout=timeout)
    if not res.ok:
        detail = (res.stderr or res.stdout).strip()[-1600:]
        raise Video2AgentError("E_DOWNLOAD", f"Download failed: {url}\n{detail}", "Check cookies/network or try a direct URL.")
    candidates: list[Path] = []
    for line in reversed(res.stdout.splitlines()):
        p = Path(line.strip())
        if line.strip() and p.exists():
            candidates.append(p)
    if not candidates:
        candidates = sorted(out_dir.glob("source.*"))
        candidates = [p for p in candidates if p.suffix.lower() not in (".vtt", ".srt", ".json")]
    if not candidates:
        raise Video2AgentError("E_DOWNLOAD", "Download finished but no media file was found.", "Check the output directory.")
    return candidates[0], meta


def path_allowed(path: str | Path, roots: list[str] | str | None) -> bool:
    if isinstance(roots, str):
        roots = [roots]
    if not roots:
        return True
    try:
        target = Path(path).expanduser().resolve()
    except OSError:
        return False
    for root in roots:
        try:
            base = Path(root).expanduser().resolve()
            if target == base or base in target.parents:
                return True
        except OSError:
            continue
    return False


def find_downloaded_subtitles(directory: str | Path) -> list[Path]:
    d = Path(directory)
    if not d.exists():
        return []
    return sorted([*d.glob("*.vtt"), *d.glob("*.srt")])


def _douyin_source(ref: dict[str, Any], cfg: Config) -> dict[str, Any]:
    """Build an ingest source from one Douyin video (SSR metadata + direct mp4)."""
    from .douyin import download, get_item

    item = get_item(
        str(ref["aweme_id"]),
        attempts=6,
        cache_dir=cfg.home / "cache" / "douyin",
    )
    canonical = str(ref["url"])
    vid = stable_id("vid", canonical)
    out_dir = ensure_dir(cfg.media_dir / vid)
    target = out_dir / "source.mp4"
    if not (target.is_file() and target.stat().st_size > 50_000):
        download(item, target)
    info = probe(target)
    title = normalize_text(item.get("title") or info.get("title") or target.stem)
    author = item.get("author") or {}
    stats = item.get("stats") or {}
    cover = str(item.get("cover_url") or "")
    cover_path = ""
    if cover:
        cp = cfg.covers_dir / f"douyin_{item.get('aweme_id')}.jpg"
        got = download_cover(cover, cp, allow_private=bool(cfg.get("allow_private_urls")))
        if got:
            cover_path = str(got)
    digest = sha256_file(target)
    duration_ms = item.get("duration_ms") or 0
    duration_s = round(float(duration_ms) / 1000.0, 3) if duration_ms else (info.get("duration") or None)
    created = item.get("create_time")
    upload_date = time.strftime("%Y%m%d", time.localtime(int(created))) if created else None
    meta = {
        "id": str(item.get("aweme_id") or ""),
        "title": title,
        "uploader": author.get("nickname") or author.get("unique_id") or "",
        "uploader_id": author.get("unique_id") or author.get("uid") or "",
        "channel": author.get("nickname") or "",
        "channel_id": author.get("sec_uid") or "",
        "duration": duration_s,
        "thumbnail": cover,
        "cover_path": cover_path or None,
        "webpage_url": canonical,
        "description": str(item.get("description") or title),
        "upload_date": upload_date,
        "view_count": stats.get("view"),
        "like_count": stats.get("like"),
        "comment_count": stats.get("comment"),
        "repost_count": stats.get("share"),
        "collect_count": stats.get("collect"),
        "music": item.get("music") or "",
        "platform": "douyin",
    }
    return {
        "id": vid,
        "kind": "url",
        "uri": canonical,
        "path": str(target.resolve()),
        "sha256": digest,
        "platform": "douyin",
        "title": title,
        "language": language_hint(title) or "zh",
        "probe": info,
        "meta": {k: v for k, v in meta.items() if v is not None},
        "subtitles": [],
    }


def resolve_source(source: str, cfg: Config) -> dict[str, Any]:
    text = str(source).strip()
    p = Path(text).expanduser()
    if p.exists() and p.is_file():
        if not path_allowed(p, cfg.get("allowed_roots")):
            raise Video2AgentError("E_PATH_DENIED", f"Path is outside allowed_roots: {p}", "Add the directory to allowed_roots or pass an allowed file.")
        info = probe(p)
        digest = sha256_file(p)
        vid = stable_id("vid", str(p.resolve()), digest)
        return {
            "id": vid,
            "kind": "local",
            "uri": str(p.resolve()),
            "path": str(p.resolve()),
            "sha256": digest,
            "platform": "local",
            "title": info.get("title") or p.stem,
            "language": language_hint(info.get("title") or ""),
            "probe": info,
            "meta": {"source": "local"},
            "subtitles": [str(find_sidecar_for(p))] if find_sidecar_for(p) else [],
        }
    ref = normalize_video_ref(text, timeout=8.0, allow_private=bool(cfg.get("allow_private_urls")))
    if ref:
        text = ref["url"]
    if ref and ref.get("platform") == "douyin":
        return _douyin_source(ref, cfg)
    if ref is None and re.match(r"https?://", text, re.I) and re.search(
        r"^https?://(?:www\.|m\.)?(?:ies)?douyin\.com/(?:share/)?user/", text, re.I
    ):
        raise Video2AgentError(
            "E_SOURCE",
            "这是抖音用户主页，不是视频",
            "贴视频链接（douyin.com/video/<数字id> 或 v.douyin.com 短链）；账户资料用 video2agent douyin profile。",
        )
    if re.match(r"https?://", text, re.I):
        assert_public_url(text, allow_private=bool(cfg.get("allow_private_urls")))
        meta = fetch_metadata(text, cfg)
        vid = stable_id("vid", text)
        out_dir = ensure_dir(cfg.media_dir / vid)
        path, meta2 = download_video(text, cfg, video_id=vid)
        meta = {**meta, **meta2}
        info = probe(path)
        digest = sha256_file(path)
        # Make the final ID content-addressed but keep the directory stable.
        title = normalize_text(meta.get("title") or info.get("title") or path.stem)
        return {
            "id": vid,
            "kind": "url",
            "uri": text,
            "path": str(path.resolve()),
            "sha256": digest,
            "platform": meta.get("extractor_key") or meta.get("extractor") or "url",
            "title": title,
            "language": language_hint(title),
            "probe": info,
            # Keep the identity fields: `uploader_id` is what lets a later
            # "this creator's other videos" query work, and `is_upower_exclusive`
            # plus the declared duration explain a truncated download.
            "meta": {k: meta.get(k) for k in (
                "id", "title", "uploader", "uploader_id", "channel", "channel_id",
                "duration", "thumbnail", "webpage_url", "description", "tags",
                "upload_date", "view_count", "is_upower_exclusive", "availability",
            ) if meta.get(k) is not None},
            "subtitles": [str(x) for x in find_downloaded_subtitles(out_dir)],
        }
    raise Video2AgentError("E_SOURCE", f"Not a local file or http(s) URL: {source}", "Pass an existing video path or a platform URL.")


def find_sidecar_for(p: Path) -> Path | None:
    from .text import find_sidecar
    return find_sidecar(p)


def discover_bilibili(query: str, cfg: Config, *, limit: int = 8, covers: bool = True) -> dict[str, Any]:
    query = query.strip()
    if not query:
        raise Video2AgentError("E_QUERY", "Search query is empty.", "Give a keyword or title.")
    search = _ytdlp() + [
        f"bilisearch:{query}", "--flat-playlist", "--playlist-end", str(max(1, min(limit, 50))),
        "--dump-json", "--no-warnings", "--no-progress",
    ]
    res = run(search, timeout=90)
    if not res.ok:
        detail = (res.stderr or res.stdout).strip()[-1200:]
        raise Video2AgentError("E_SEARCH", f"Bilibili search failed.\n{detail}", "Try again, update yt-dlp, or provide a video URL directly.")
    entries = list(iter_json_lines(res.stdout))
    if not entries:
        return {"query": query, "platform": "bilibili", "candidates": [], "warnings": [{"code": "NO_RESULTS", "message": "No results"}]}
    candidates: list[dict[str, Any]] = []
    cover_paths: list[Path] = []
    for idx, entry in enumerate(entries[:limit], start=1):
        url = entry.get("webpage_url") or entry.get("url") or ""
        if url.startswith("http://"):
            url = "https://" + url[len("http://"):]
        bvid = entry.get("id") or ""
        if not _BV.search(str(bvid) + " " + str(url)):
            m = _BV.search(str(url))
            bvid = m.group(1) if m else str(bvid)
        title = normalize_text(entry.get("title") or "")
        meta: dict[str, Any] = entry
        if not title and url:
            try:
                meta = fetch_metadata(url, cfg, timeout=30)
                title = normalize_text(meta.get("title") or "")
            except Exception:
                title = ""
        title = title or f"Bilibili {bvid or idx}"
        desc = normalize_text(meta.get("description") or "")
        cover = meta.get("thumbnail") or ""
        cover_path = None
        cover_text = ""
        if covers and cover:
            cp = cfg.covers_dir / f"bili_{bvid or idx}.jpg"
            got = download_cover(cover, cp, allow_private=bool(cfg.get("allow_private_urls")))
            if got:
                cover_path = str(got)
                cover_paths.append(got)
        candidates.append({
            "candidate_id": f"bili_{bvid or idx}",
            "platform": "bilibili",
            "video_id": bvid,
            "url": url,
            "title": title,
            "cover_url": cover,
            "cover_path": cover_path,
            "cover_ocr": cover_text,
            "duration_ms": int(float(meta.get("duration") or 0) * 1000) if meta.get("duration") else None,
            "uploader": meta.get("uploader") or meta.get("channel"),
            "published_at": meta.get("upload_date"),
            "description": desc[:300],
            "stats": {k: meta.get(k) for k in ("view_count", "like_count", "comment_count") if meta.get(k) is not None},
        })
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

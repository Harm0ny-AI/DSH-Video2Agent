"""Bilibili CC subtitles.

Why this module exists: Bilibili only returns a video's subtitle list to a
request that carries a viewer session. Anonymous requests (the pipeline's
default anonymous cookie jar) get `subtitle.subtitles == []`, so a URL ingest
silently fell back to local ASR even when the uploader had published verified
subtitles. yt-dlp's Bilibili extractor only surfaces `danmaku` here, so the
signed player API is the reliable path.

The legacy `/x/player/v2` endpoint is not reliable any more: on 2026-10-31 a
46s DSH video received another video's 160-line AI subtitle (298s), and a 26m
attention lecture received a 93-line fairy-tale track. The WBI-signed
`/x/player/wbi/v2` returned the correct 18-line track for the 46s cid. This
module therefore signs with the nav WBI keys and never silently falls back to
the legacy endpoint when WBI returns no track; ASR is the fallback.

The flow is deliberately split into pure functions plus two thin HTTP calls so
the parsing and track-preference rules are testable offline:

    video_cid()        -> cid for the first page
    subtitle_tracks()  -> [{lan, lan_doc, ai, url}] (only entries with a URL)
    rank_tracks()      -> order candidates; the caller keeps the one with most text
    fetch_track()      -> segments in Video2Agent's {start_ms, end_ms, text, source}

Everything is opt-in: without a logged-in cookie file the API still answers and
the caller gets an empty result plus `logged_in=False`, which the pipeline turns
into an explicit warning instead of a silent ASR fallback.
"""

from __future__ import annotations

import hashlib
import time
from pathlib import Path
from typing import Any
from urllib.parse import urlencode

import requests

from .config import Config
from .text import normalize_text, query_units
from .util import Video2AgentError

_UA = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/131 Safari/537.36"
)
_REFERER = "https://www.bilibili.com/"
_API = "https://api.bilibili.com"

# Language preference: the content is Chinese-first, so a Chinese track wins over
# an English one even if the English one is human-made.
_ZH_EXACT = {"zh-hans", "zh-cn", "zh", "zh-hant", "zh-tw", "ai-zh"}


def cookie_path(cfg: Config) -> Path | None:
    """Cookie file to use: a saved QR login first, then explicit config, then the jar.

    The QR login writes `cookies/bilibili-login.txt`; the anonymous 412-fixup jar
    lives at `cookies/bilibili.txt` and must never overwrite a real login.
    """
    login = cfg.home / "cookies" / "bilibili-login.txt"
    if login.is_file():
        return login
    raw = cfg.get("cookies_file")
    if raw:
        return Path(str(raw)).expanduser()
    return cfg.home / "cookies" / "bilibili.txt"


def load_netscape_cookies(path: str | Path | None) -> dict[str, str]:
    """Read a Netscape cookie file into a plain dict (best effort, never raises)."""
    jar: dict[str, str] = {}
    if not path:
        return jar
    p = Path(path)
    if not p.is_file():
        return jar
    try:
        for line in p.read_text(encoding="utf-8", errors="replace").splitlines():
            if not line:
                continue
            # Chrome/Firefox export HttpOnly cookies with a "#HttpOnly_" prefix;
            # skipping every "#" line silently drops SESSDATA.
            if line.startswith("#HttpOnly_"):
                line = line[len("#HttpOnly_"):]
            elif line.startswith("#"):
                continue
            parts = line.split("\t")
            if len(parts) >= 7 and parts[5]:
                jar[parts[5]] = parts[6]
    except OSError:
        return {}
    return jar


def is_logged_in(cookies: dict[str, str]) -> bool:
    """Bilibili keeps the session in SESSDATA; without it subtitles are hidden."""
    return bool(cookies.get("SESSDATA"))


def parse_caption_json(payload: Any) -> list[dict[str, Any]]:
    """Convert Bilibili's subtitle JSON ({body:[{from,to,content}]}) to segments."""
    body = payload.get("body") if isinstance(payload, dict) else None
    if not isinstance(body, list):
        return []
    segments: list[dict[str, Any]] = []
    for item in body:
        if not isinstance(item, dict):
            continue
        text = normalize_text(str(item.get("content") or ""))
        if not text:
            continue
        try:
            start_ms = int(round(float(item.get("from") or 0) * 1000))
        except (TypeError, ValueError):
            continue
        try:
            end_ms = int(round(float(item.get("to") or 0) * 1000))
        except (TypeError, ValueError):
            end_ms = 0
        if end_ms <= start_ms:
            end_ms = start_ms + 1500
        segments.append({"start_ms": start_ms, "end_ms": end_ms, "text": text, "source": "caption"})
    segments.sort(key=lambda s: s["start_ms"])
    return segments


def _lang_rank(lan: str) -> int:
    key = (lan or "").lower()
    if key in _ZH_EXACT:
        return 0
    if key.startswith("zh"):
        return 1
    if key.startswith("en"):
        return 3
    return 4


def _lang_base(lan: str) -> str:
    """`zh-Hans`/`ai-zh` -> `zh`; used to keep an AI fallback in the same language."""
    parts = [part for part in str(lan or "").lower().split("-") if part]
    if parts and parts[0] == "ai" and len(parts) > 1:
        return parts[1]
    return parts[0] if parts else ""


def rank_tracks(tracks: list[dict[str, Any]], limit: int = 3) -> list[dict[str, Any]]:
    """Ordered candidates, so the caller can compare how much text each one has.

    A human-translated track is normally best, but a stub with one line loses to a
    full AI transcript; ranking alone cannot see that, so the order is only a
    suggestion and the pipeline fetches a couple of candidates to compare sizes.
    """
    ranked = sorted(
        tracks,
        key=lambda t: (_lang_rank(str(t.get("lan") or "")), 1 if t.get("ai") else 0),
    )
    return ranked[:max(1, limit)]


def _session(cfg: Config) -> tuple[requests.Session, bool]:
    session = requests.Session()
    session.headers.update({"User-Agent": _UA, "Referer": _REFERER})
    cookies = load_netscape_cookies(cookie_path(cfg))
    if cookies:
        session.cookies.update(cookies)
    return session, is_logged_in(cookies)


def _get_json(session: requests.Session, url: str, params: dict[str, Any] | None = None, timeout: float = 15.0) -> Any:
    try:
        response = session.get(url, params=params, timeout=timeout)
        return response.json()
    except Exception as e:  # noqa: BLE001 - network/JSON failures share one remedy
        raise Video2AgentError("E_CAPTION_API", f"Bilibili subtitle API failed: {e}", "Retry, or ignore subtitles.") from e


def video_cid(bvid: str, session: requests.Session, page: int = 1) -> int | None:
    payload = _get_json(session, _API + "/x/web-interface/view", {"bvid": bvid})
    data = (payload or {}).get("data") or {}
    pages = data.get("pages") or []
    if pages:
        index = max(0, int(page) - 1)
        if index >= len(pages):
            index = 0
        try:
            return int(pages[index].get("cid"))
        except (TypeError, ValueError):
            return None
    try:
        return int(data["cid"]) if data.get("cid") else None
    except (TypeError, ValueError):
        return None


# Bilibili's legacy /x/player/v2 is currently returning another video's AI
# subtitle on real requests (observed: a 46s DSH video got 160 parenting lines,
# 298s; a 26m attention lecture got a 93-line fairy-tale track). The WBI-signed
# /x/player/wbi/v2 returned the correct 18-line track for the same 46s cid.
# Prefer the signed endpoint; do not silently fall back to the buggy one.
_WBI_TAB = [
    46, 47, 18, 2, 53, 8, 23, 32, 15, 50, 10, 31, 58, 3, 45, 35,
    27, 43, 5, 49, 33, 9, 42, 19, 29, 28, 14, 39, 12, 38, 41, 13,
    37, 48, 7, 16, 24, 55, 40, 61, 26, 17, 0, 1, 60, 51, 30, 4,
    22, 25, 54, 21, 56, 59, 6, 63, 57, 62, 11, 36, 20, 34, 44, 52,
]
_WBI_CACHE: tuple[str, float] | None = None


def _wbi_key(session: requests.Session) -> str:
    """Derive Bilibili's current WBI mixin key from the nav image/sub keys."""
    global _WBI_CACHE
    now = time.time()
    if _WBI_CACHE and _WBI_CACHE[1] > now:
        return _WBI_CACHE[0]
    nav = _get_json(session, _API + "/x/web-interface/nav", {})
    wbi = ((nav or {}).get("data") or {}).get("wbi_img") or {}
    img = str(wbi.get("img_url") or "").rsplit("/", 1)[-1].split(".")[0]
    sub = str(wbi.get("sub_url") or "").rsplit("/", 1)[-1].split(".")[0]
    orig = img + sub
    if len(orig) < 64:
        return ""
    key = "".join(orig[i] for i in _WBI_TAB)[:32]
    _WBI_CACHE = (key, now + 300)
    return key


def _wbi_params(session: requests.Session, params: dict[str, Any]) -> dict[str, Any]:
    key = _wbi_key(session)
    signed = dict(params)
    signed["wts"] = int(time.time())
    if not key:
        return signed
    query = urlencode(sorted(signed.items()))
    signed["w_rid"] = hashlib.md5((key + query).encode()).hexdigest()
    return signed


def subtitle_tracks(bvid: str, cid: int, session: requests.Session) -> list[dict[str, Any]]:
    payload = _get_json(session, _API + "/x/player/wbi/v2", _wbi_params(session, {"bvid": bvid, "cid": cid}))
    data = (payload or {}).get("data") or {}
    raw = ((data.get("subtitle") or {}).get("subtitles")) or []
    tracks: list[dict[str, Any]] = []
    for item in raw:
        if not isinstance(item, dict):
            continue
        url = str(item.get("subtitle_url") or "")
        if url.startswith("//"):
            url = "https:" + url
        if not url:
            # A rate-limited response lists the track with an empty URL; the
            # caller re-requests the whole list to get a fresh auth_key URL.
            continue
        lan = str(item.get("lan") or "")
        ai_flag = str(item.get("ai_type") or "0") not in ("0", "") or lan.startswith("ai-")
        tracks.append({
            "lan": lan,
            "lan_doc": str(item.get("lan_doc") or ""),
            "ai": ai_flag,
            "kind": "ai" if ai_flag else "human",
            # The signed WBI endpoint is the trusted source; the legacy
            # /x/player/v2 endpoint returned another video's track in testing.
            "endpoint": "wbi",
            "url": url,
        })
    return tracks


def summarize_tracks(tracks: list[dict[str, Any]], limit: int = 12) -> list[dict[str, Any]]:
    """Compact list for metrics: which languages/AI variants this video offers."""
    return [
        {"lan": t.get("lan"), "lan_doc": t.get("lan_doc"), "kind": t.get("kind")}
        for t in tracks[:limit]
    ]


def fetch_track(track: dict[str, Any], session: requests.Session) -> list[dict[str, Any]]:
    payload = _get_json(session, str(track["url"]), timeout=20.0)
    return parse_caption_json(payload)


def caption_track_mismatch(segments: list[dict[str, Any]], duration_ms: int | None) -> bool:
    """A track that runs far past the media is usually another video's captions.

    This is deliberately conservative: a few seconds of outro overrun is normal,
    but a large share ending past 1.5x the media means the track cannot be trusted
    as this video's words.
    """
    if not duration_ms or duration_ms <= 0 or not segments:
        return False
    far = [s for s in segments if int(s.get("end_ms") or 0) > duration_ms * 1.5]
    return len(far) >= max(3, len(segments) // 10)


def caption_track_trusted(track: dict[str, Any] | None) -> bool:
    """A WBI-signed track list is authoritative for a track's identity.

    The signed endpoint returned the correct 18-line track for a 46s video where
    the legacy /player/v2 list pointed at another video's 160-line track. The
    text gate stays for untrusted sources (local sidecars, old cached captions),
    but applying it to a WBI track produced false alarms: speech rarely repeats a
    clickbait title's words ("双十一半价老旗舰…" vs "今年想换个新机…"), and a
    Bilibili AI translation (ai-en/ai-ja) shares no units with a Chinese title by
    design. Re-ingesting cannot fix either case — the same WBI track comes back.
    """
    return bool(track) and (track.get("endpoint") == "wbi")


def caption_content_mismatch(
    segments: list[dict[str, Any]],
    title: str | None,
    description: str | None = None,
    tags: list[str] | tuple[str, ...] | None = None,
) -> bool:
    """Catch a track whose words have nothing to do with the video's metadata.

    Duration validation catches a different video when the track overruns. A
    same-duration wrong track (observed: a 26-minute attention lecture carrying
    iPhone-lens captions) needs a second signal. Use distinctive title/description/
    tag units; skip when metadata is too thin, so a generic filename does not
    discard a valid local subtitle.
    """
    # The title is the strongest identity signal; descriptions/tags often contain
    # generic words ("视频", "内容") that can overlap unrelated captions. Use them
    # only when the title itself is too thin to judge.
    title_units = set(query_units(str(title or ""), max_units=64))
    if len(title_units) >= 3:
        context_units = title_units
    else:
        context = " ".join([str(title or ""), str(description or ""), " ".join(tags or [])])
        context_units = set(query_units(context, max_units=64))
    if len(context_units) < 3 or not segments:
        return False
    caption_text = " ".join(str(s.get("text") or "") for s in segments[:120])
    caption_units = set(query_units(caption_text, max_units=96))
    if len(caption_units) < 8:
        return False
    return not (context_units & caption_units)


def bilibili_captions(
    bvid: str,
    cfg: Config,
    *,
    attempts: int = 3,
    duration_ms: int | None = None,
    page: int = 1,
    title: str | None = None,
    description: str | None = None,
    tags: list[str] | tuple[str, ...] | None = None,
) -> dict[str, Any]:
    """Try to read the uploader/AI subtitles for a Bilibili video.

    Bilibili hides the subtitle list from anonymous requests, so without a
    logged-in cookie this returns ``reason="no_tracks"`` and ``logged_in=False``
    (the caller then falls back to ASR and says so). Under rate limiting the list
    arrives with empty ``subtitle_url`` entries or the subtitle JSON comes back
    without a body; the subtitle URL also carries a time-limited ``auth_key``, so
    each retry re-requests the track list instead of reusing the old URL.

    Returns ``{"segments", "track", "tracks", "logged_in", "reason"}``; failure
    modes are reported instead of raised because the caller falls back to ASR.
    """
    session, logged_in = _session(cfg)
    result: dict[str, Any] = {
        "segments": [],
        "track": None,
        "tracks": [],
        "logged_in": logged_in,
        "reason": "no_cid",
    }
    cid = video_cid(bvid, session, page=page)
    if not cid:
        return result
    reason = "no_tracks"
    for attempt in range(max(1, attempts)):
        tracks = subtitle_tracks(bvid, cid, session)
        if tracks:
            result["tracks"] = summarize_tracks(tracks)
            # A "human" track can be a one-line stub while the AI transcript is
            # complete, so compare every advertised track by length and keep the
            # longest valid one. The old cap of three was an arbitrary request
            # budget; it could hide the only valid track behind translations.
            # Only a clearly larger track (20%) replaces the current best, so the
            # rank-preferred human track still wins a close call.
            best: tuple[int, dict[str, Any], list[dict[str, Any]]] | None = None
            ai_fallbacks: dict[str, dict[str, Any]] = {}
            saw_mismatch = False
            saw_content_mismatch = False
            for candidate in rank_tracks(tracks, limit=len(tracks)):
                # One broken/empty candidate must not throw away a good one: a rate
                # limited later track used to take the whole subtitle path down and
                # fall back to ASR even when the first track was complete.
                try:
                    segments = fetch_track(candidate, session)
                except Exception:  # noqa: BLE001 - try the next candidate
                    continue
                if not segments:
                    continue
                if caption_track_mismatch(segments, duration_ms):
                    # Do not let a long wrong track beat a shorter valid one; the
                    # pipeline used to fall back to ASR only after accepting it.
                    saw_mismatch = True
                    continue
                if not caption_track_trusted(candidate) and caption_content_mismatch(segments, title, description, tags):
                    saw_content_mismatch = True
                    continue
                if candidate.get("ai"):
                    base = _lang_base(candidate.get("lan"))
                    current = ai_fallbacks.get(base)
                    if current is None or len(segments) > len(current["segments"]):
                        ai_fallbacks[base] = {
                            "segments": segments,
                            "track": {
                                "lan": candidate["lan"],
                                "lan_doc": candidate["lan_doc"],
                                "ai": True,
                                "kind": candidate.get("kind") or "ai",
                                "endpoint": candidate.get("endpoint") or "wbi",
                            },
                        }
                if best is None or len(segments) > best[0] * 1.2:
                    best = (len(segments), candidate, segments)
            if best is not None:
                _count, track, segments = best
                result.update({
                    "segments": segments,
                    "track": {
                        "lan": track["lan"],
                        "lan_doc": track["lan_doc"],
                        "ai": bool(track["ai"]),
                        "kind": track.get("kind") or ("ai" if track.get("ai") else "human"),
                        "endpoint": track.get("endpoint") or "wbi",
                    },
                    "reason": "ok",
                })
                if not bool(track.get("ai")):
                    base = _lang_base(track.get("lan"))
                    if ai_fallbacks.get(base):
                        result["ai_fallback"] = ai_fallbacks[base]
                return result
            if saw_mismatch or saw_content_mismatch:
                reason = "mismatch"
            else:
                reason = "empty"
        # Back off and ask again for a fresh URL (rate limiting is the usual cause).
        if attempt + 1 < attempts:
            time.sleep(2.0 + attempt * 2.0)
    result["reason"] = reason
    return result

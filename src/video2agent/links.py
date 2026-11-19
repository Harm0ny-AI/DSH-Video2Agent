"""Bilibili and Douyin link/ID normalization.

Bilibili accepted inputs:

* ``BV1xx411c7mD`` (pasted bare)
* ``av170001`` (bare numeric id)
* ``https://www.bilibili.com/video/BV1xx411c7mD/``
* ``https://www.bilibili.com/video/av170001``
* ``https://b23.tv/AbCdEf`` (short link; resolved over the network)

Douyin accepted inputs:

* ``https://www.douyin.com/video/<aweme_id>``
* ``https://www.iesdouyin.com/share/video/<aweme_id>/``
* ``https://www.douyin.com/discover?modal_id=<aweme_id>``
* ``https://v.douyin.com/<code>/`` (short link; one redirect, no cookies)
* the whole "复制打开抖音…" share text containing one of those URLs

Everything is reduced to ``{"kind", "platform", "url", ...}`` with a canonical URL.
Pure string handling is separate from the network calls so it is testable offline.
"""

from __future__ import annotations

import re
from urllib.parse import parse_qs, urljoin, urlparse

from .util import Video2AgentError

_BV_RE = re.compile(r"(?<![0-9A-Za-z])BV[0-9A-Za-z]{10}(?![0-9A-Za-z])")
_BV_FULL = re.compile(r"^BV[0-9A-Za-z]{10}$")
_AV_RE = re.compile(r"(?<![0-9A-Za-z])av(\d+)(?![0-9A-Za-z])", re.I)
_AV_FULL = re.compile(r"^av(\d+)$", re.I)
_SHORT_HOSTS = {"b23.tv", "www.b23.tv"}
_BILI_HOSTS = {
    "bilibili.com", "www.bilibili.com", "m.bilibili.com", "b23.tv", "www.b23.tv",
}
_DOUYIN_HOSTS = {
    "douyin.com", "www.douyin.com", "m.douyin.com", "v.douyin.com",
    "iesdouyin.com", "www.iesdouyin.com",
}
_DOUYIN_SHORT_HOSTS = {"v.douyin.com"}
_DOUYIN_PATH_ID = re.compile(r"(?:/video/|/share/video/)(\d{15,20})(?:/|$)")
_DOUYIN_QUERY_ID = re.compile(r"(?:modal_id|aweme_id|item_ids)=(\d{15,20})")
_DOUYIN_URL_IN_TEXT = re.compile(
    r"https?://(?:v\.douyin\.com/[A-Za-z0-9_-]+|"
    r"(?:www\.)?(?:ies)?douyin\.com/(?:share/)?video/\d{15,20})[^\s，。！？、]*"
)
_DOUYIN_UA = (
    "Mozilla/5.0 (iPhone; CPU iPhone OS 17_2 like Mac OS X) AppleWebKit/605.1.15 "
    "(KHTML, like Gecko) Version/17.2 Mobile/15E148 Safari/604.1"
)
_USER_AGENT = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/131 Safari/537.36"
)

# Bilibili's public av <-> BV permutation.
_TABLE = "FcwAPNKTMug3GV5Lj7EJnHpWsx4tb8haYeviqBz6rkCy12mUSDQX9RdoZf"
_XOR = 23442827791579
_MASK = (1 << 51) - 1
_MAX_AID = 1 << 51
_BASE = 58


def av_to_bv(av_id: int) -> str:
    """Convert a numeric aid to its BV id (deterministic, no network)."""
    if not isinstance(av_id, int) or not 0 <= av_id < _MAX_AID:
        raise Video2AgentError("E_BAD_AV", f"av 号超出范围: {av_id}", "Use a valid numeric av id.")
    chars = list("BV1" + "0" * 9)
    idx = len(chars) - 1
    tmp = (_MAX_AID | int(av_id)) ^ _XOR
    while tmp > 0:
        chars[idx] = _TABLE[tmp % _BASE]
        tmp //= _BASE
        idx -= 1
    chars[3], chars[9] = chars[9], chars[3]
    chars[4], chars[7] = chars[7], chars[4]
    return "".join(chars)


def bv_to_av(bvid: str) -> int | None:
    """Inverse of :func:`av_to_bv`; None when the id is not a BV id."""
    if not _BV_FULL.fullmatch(bvid or ""):
        return None
    chars = list(bvid)
    chars[3], chars[9] = chars[9], chars[3]
    chars[4], chars[7] = chars[7], chars[4]
    tmp = 0
    for ch in chars[3:]:
        idx = _TABLE.find(ch)
        if idx < 0:
            return None
        tmp = tmp * _BASE + idx
    return (tmp & _MASK) ^ _XOR


def extract_bvid(text: str) -> str | None:
    """First BV id inside an arbitrary string (URL, id, log line)."""
    m = _BV_RE.search(text or "")
    return m.group(0) if m else None


def canonical_douyin_url(aweme_id: str) -> str:
    return f"https://www.douyin.com/video/{aweme_id}"


def _douyin_ref(raw: str, parsed) -> dict | None:
    host = (parsed.hostname or "").lower()
    path = parsed.path or ""
    if host in _DOUYIN_SHORT_HOSTS:
        token = path.strip("/").split("/")[0]
        if re.fullmatch(r"[A-Za-z0-9_-]{4,}", token):
            return {
                "kind": "douyin_shortlink", "platform": "douyin", "aweme_id": None,
                "url": f"https://v.douyin.com/{token}/", "input_kind": "shortlink", "token": token,
            }
        return None
    match = _DOUYIN_PATH_ID.search(path) or _DOUYIN_QUERY_ID.search(parsed.query or "")
    if match:
        aweme_id = match.group(1)
        return {
            "kind": "douyin", "platform": "douyin", "aweme_id": aweme_id,
            "url": canonical_douyin_url(aweme_id), "input_kind": "url",
        }
    return None


def canonical_video_url(bvid: str, *, page: int | None = None) -> str:
    url = f"https://www.bilibili.com/video/{bvid}/"
    if page and page > 1:
        url += f"?p={page}"
    return url


def _page_of(parsed) -> int | None:
    try:
        raw = (parse_qs(parsed.query).get("p") or [""])[0]
        page = int(raw)
        return page if page > 1 else None
    except Exception:
        return None


def extract_ref(text: str) -> dict | None:
    """Classify an input string without any network access.

    Returns ``{"kind", "bvid", "av_id", "url", "input_kind"}`` or None. For a
    b23.tv short token the returned ref has ``kind == "shortlink"`` and no bvid;
    :func:`normalize_video_ref` resolves it.
    """
    raw = (text or "").strip()
    if not raw:
        return None
    if _BV_FULL.fullmatch(raw):
        return {"kind": "bv", "bvid": raw, "av_id": bv_to_av(raw),
                "url": canonical_video_url(raw), "input_kind": "bv"}
    m = _AV_FULL.fullmatch(raw)
    if m:
        aid = int(m.group(1))
        bvid = av_to_bv(aid)
        return {"kind": "bv", "bvid": bvid, "av_id": aid,
                "url": canonical_video_url(bvid), "input_kind": "av"}
    if not re.match(r"https?://", raw, re.I):
        # "7.85 复制打开抖音… https://v.douyin.com/xxx/" — pull the URL out of the
        # share text instead of demanding the user trim it.
        share = _DOUYIN_URL_IN_TEXT.search(raw)
        if share:
            return extract_ref(share.group(0))
        return None
    parsed = urlparse(raw)
    host = (parsed.hostname or "").lower()
    if host in _DOUYIN_HOSTS:
        return _douyin_ref(raw, parsed)
    if host not in _BILI_HOSTS:
        return None
    page = _page_of(parsed)
    if host in _SHORT_HOSTS:
        m = _BV_RE.search(parsed.path or "")
        if m:
            bvid = m.group(0)
            return {"kind": "bv", "bvid": bvid, "av_id": bv_to_av(bvid),
                    "url": canonical_video_url(bvid, page=page), "input_kind": "shortlink"}
        m = _AV_RE.search(parsed.path or "")
        if m:
            aid = int(m.group(1))
            bvid = av_to_bv(aid)
            return {"kind": "bv", "bvid": bvid, "av_id": aid,
                    "url": canonical_video_url(bvid, page=page), "input_kind": "shortlink"}
        token = (parsed.path or "").strip("/")
        if token:
            return {"kind": "shortlink", "bvid": None, "av_id": None,
                    "url": raw, "input_kind": "shortlink", "token": token}
        return None
    path = parsed.path or ""
    m = _BV_RE.search(path)
    if m:
        bvid = m.group(0)
        return {"kind": "bv", "bvid": bvid, "av_id": bv_to_av(bvid),
                "url": canonical_video_url(bvid, page=page), "input_kind": "url"}
    m = _AV_RE.search(path)
    if m:
        aid = int(m.group(1))
        bvid = av_to_bv(aid)
        return {"kind": "bv", "bvid": bvid, "av_id": aid,
                "url": canonical_video_url(bvid, page=page), "input_kind": "url"}
    return None


def _resolve_shortlink(url: str, *, timeout: float = 8.0, allow_private: bool = False) -> str:
    """Follow a b23.tv redirect and return the final URL."""
    try:
        import requests
    except Exception as e:  # pragma: no cover - requests is a hard dependency
        raise Video2AgentError("E_SHORTLINK", f"Cannot resolve short link: {url}",
                            "Install requests, or paste the full bilibili.com URL.") from e
    from .net import assert_public_url

    # The first hop is checked too: a caller passing a private URL must not make
    # this helper issue the request at all.
    assert_public_url(url, allow_private=allow_private)

    # Follow redirects by hand so every hop is checked: allow_redirects=True
    # fetched an internal 302 target before the final-host check ran.
    final = url
    try:
        for _ in range(6):
            resp = requests.get(final, timeout=timeout, allow_redirects=False, stream=True,
                                headers={"User-Agent": _USER_AGENT})
            location = resp.headers.get("Location") if resp.is_redirect else None
            if location:
                resp.close()
                nxt = urljoin(final, location)
                assert_public_url(nxt, allow_private=allow_private)
                final = nxt
                continue
            resp.close()
            break
        else:
            raise Video2AgentError("E_SHORTLINK", f"Too many redirects: {url}",
                                   "Paste the canonical bilibili.com video URL instead.")
    except Video2AgentError:
        raise
    except Exception as e:
        raise Video2AgentError(
            "E_SHORTLINK",
            f"Short link could not be resolved within {timeout:g}s: {url}",
            "Open the link in a browser and paste the full bilibili.com URL, or retry when the network is up.",
        ) from e
    host = (urlparse(final).hostname or "").lower()
    if host not in _BILI_HOSTS - _SHORT_HOSTS:
        raise Video2AgentError(
            "E_SHORTLINK",
            f"Short link redirected outside Bilibili: {final}",
            "Paste the canonical bilibili.com video URL instead.",
        )
    return final


def resolve_douyin_shortlink(token: str, *, timeout: float = 8.0) -> str:
    """Resolve v.douyin.com/<token> to an aweme id (one 302, no cookies).

    Verified 2026-11: the short host answers 302 with an iesdouyin share URL that
    contains '/share/video/<aweme_id>/'. Invalid codes redirect to the Douyin
    homepage, so the Location is validated rather than trusted.
    """
    try:
        import requests
    except Exception as e:  # pragma: no cover - requests is a hard dependency
        raise Video2AgentError("E_DOUYIN_SHORTLINK", f"Cannot resolve Douyin short link: {token}",
                               "Install requests, or paste the full douyin.com video URL.") from e
    from .net import assert_public_url

    url = f"https://v.douyin.com/{token}/"
    assert_public_url(url)
    try:
        resp = requests.get(url, timeout=timeout, allow_redirects=False,
                            headers={"User-Agent": _DOUYIN_UA})
        location = resp.headers.get("Location") or ""
        status = resp.status_code
        text = ""
        if status == 200:
            text = resp.text[:200_000]
        resp.close()
    except Video2AgentError:
        raise
    except Exception as e:
        raise Video2AgentError(
            "E_DOUYIN_SHORTLINK",
            f"Douyin short link could not be resolved: {token}",
            "Open the link in a browser and paste the douyin.com/video/<id> URL.",
        ) from e
    match = re.search(r"/share/video/(\d{15,20})", location) or re.search(
        r"https?://(?:www\.)?douyin\.com/video/(\d{15,20})", location
    )
    if match:
        return match.group(1)
    if text:
        match = re.search(r"(?:/share/video/|/video/)(\d{15,20})", text)
        if match:
            return match.group(1)
    raise Video2AgentError(
        "E_DOUYIN_SHORTLINK",
        f"Douyin short link did not point at a video: {token}",
        "Open the link in a browser and paste the douyin.com/video/<id> URL.",
    )


def normalize_video_ref(text: str, *, timeout: float = 8.0, allow_private: bool = False) -> dict | None:
    """Normalize any accepted reference to a canonical BV URL ref.

    Raises ``Video2AgentError("E_SHORTLINK", ...)`` when a b23.tv short link cannot
    be resolved; returns None when the input is not a Bilibili reference at all
    (callers keep their existing local-path / generic-URL handling).
    """
    ref = extract_ref(text)
    if ref is None:
        return None
    if ref.get("platform") == "douyin":
        if ref.get("kind") == "douyin_shortlink":
            aweme_id = resolve_douyin_shortlink(ref["token"], timeout=timeout)
            return {
                "kind": "douyin", "platform": "douyin", "aweme_id": aweme_id,
                "url": canonical_douyin_url(aweme_id), "input_kind": "shortlink",
                "resolved_from": ref["url"],
            }
        return ref
    if ref.get("kind") != "shortlink":
        return ref
    final = _resolve_shortlink(ref["url"], timeout=timeout, allow_private=allow_private)
    resolved = extract_ref(final)
    if not resolved or not resolved.get("bvid"):
        raise Video2AgentError(
            "E_SHORTLINK",
            f"Short link resolved to a page without a BV id: {final}",
            "Paste the full bilibili.com video URL.",
        )
    resolved["resolved_from"] = ref["url"]
    resolved["input_kind"] = "shortlink"
    return resolved

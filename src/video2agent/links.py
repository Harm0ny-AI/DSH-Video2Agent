"""Bilibili link/ID normalization.

Accepted inputs:

* ``BV1xx411c7mD`` (pasted bare)
* ``av170001`` (bare numeric id)
* ``https://www.bilibili.com/video/BV1xx411c7mD/``
* ``https://www.bilibili.com/video/av170001``
* ``https://b23.tv/AbCdEf`` (short link; resolved over the network)

Everything is reduced to ``{"kind", "bvid", "url", ...}`` where ``url`` is the
canonical ``https://www.bilibili.com/video/<BV>/`` URL. Pure string handling is
separate from the one network call so the normalization is testable offline.
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
        return None
    parsed = urlparse(raw)
    host = (parsed.hostname or "").lower()
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


def _resolve_shortlink(url: str, *, timeout: float = 8.0) -> str:
    """Follow a b23.tv redirect and return the final URL."""
    try:
        import requests
    except Exception as e:  # pragma: no cover - requests is a hard dependency
        raise Video2AgentError("E_SHORTLINK", f"Cannot resolve short link: {url}",
                            "Install requests, or paste the full bilibili.com URL.") from e
    from .net import assert_public_url

    # The first hop is checked too: a caller passing a private URL must not make
    # this helper issue the request at all.
    assert_public_url(url)

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
                assert_public_url(nxt)
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


def normalize_video_ref(text: str, *, timeout: float = 8.0) -> dict | None:
    """Normalize any accepted reference to a canonical BV URL ref.

    Raises ``Video2AgentError("E_SHORTLINK", ...)`` when a b23.tv short link cannot
    be resolved; returns None when the input is not a Bilibili reference at all
    (callers keep their existing local-path / generic-URL handling).
    """
    ref = extract_ref(text)
    if ref is None:
        return None
    if ref.get("kind") != "shortlink":
        return ref
    final = _resolve_shortlink(ref["url"], timeout=timeout)
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

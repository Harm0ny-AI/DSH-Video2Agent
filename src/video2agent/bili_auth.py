"""Bilibili QR login, so a user never has to export a cookie file by hand.

Flow (same as the Bilibili app):
    start_login()  -> official qrcode generate -> url + qrcode_key
    render_qr()    -> the url as a PNG data URL (OpenCV's encoder, no new deps)
    poll_login()   -> 86101 waiting / 86090 scanned / 0 confirmed (cookies come
                      back in the redirect URL's query string) / 86038 expired
    save_login()   -> write a Netscape cookie jar under $VIDEO2AGENT_HOME/cookies

Only the jar is persisted; nothing here logs or returns a cookie value.
"""

from __future__ import annotations

import base64
import time
from pathlib import Path
from typing import Any
from urllib.parse import parse_qs, urlparse

import requests

from .config import Config
from .util import Video2AgentError

_UA = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/131 Safari/537.36"
)
_GENERATE = "https://passport.bilibili.com/x/passport-login/web/qrcode/generate"
_POLL = "https://passport.bilibili.com/x/passport-login/web/qrcode/poll"
_LOGIN_FILE = "bilibili-login.txt"

# 86101 waiting, 86090 scanned-not-confirmed, 86038 expired, 0 confirmed.
STATE_BY_CODE = {
    86101: "pending",
    86090: "scanned",
    86038: "expired",
    0: "ok",
}

# Cookies worth keeping from the confirmed redirect.
_KEEP = ("SESSDATA", "bili_jct", "DedeUserID", "DedeUserID__ckMd5", "sid", "buvid3", "buvid4")


def login_path(cfg: Config) -> Path:
    return cfg.home / "cookies" / _LOGIN_FILE


def _session() -> requests.Session:
    s = requests.Session()
    s.headers.update({"User-Agent": _UA, "Referer": "https://www.bilibili.com/"})
    return s


def start_login(session: requests.Session | None = None) -> dict[str, Any]:
    s = session or _session()
    try:
        payload = s.get(_GENERATE, timeout=15).json()
    except Exception as e:  # noqa: BLE001
        raise Video2AgentError("E_BILI_QR", f"Bilibili QR generate failed: {e}", "Check the network and retry.") from e
    data = payload.get("data") or {}
    url = str(data.get("url") or "")
    key = str(data.get("qrcode_key") or "")
    if payload.get("code") != 0 or not url or not key:
        raise Video2AgentError(
            "E_BILI_QR",
            f"Bilibili refused to create a login QR (code={payload.get('code')}).",
            "Retry later.",
        )
    return {"url": url, "key": key}


def render_qr(url: str, *, scale_px: int = 320, quiet: int = 4) -> str:
    """Render a QR code as a PNG data URL using OpenCV (no extra dependency)."""
    try:
        import cv2
        import numpy as np
    except Exception as e:  # noqa: BLE001
        raise Video2AgentError("E_QR_LIB", "OpenCV is required to draw the login QR.", "pip install opencv-python-headless") from e
    try:
        encoder = cv2.QRCodeEncoder_create()
        matrix = encoder.encode(str(url))
    except Exception as e:  # noqa: BLE001
        raise Video2AgentError("E_QR_LIB", f"Could not encode the login QR: {e}", "Update opencv-python-headless.") from e
    modules = (np.asarray(matrix) > 0).astype(np.uint8) * 255
    if quiet:
        modules = np.pad(modules, quiet, constant_values=255)
    size = max(120, int(scale_px))
    image = cv2.resize(modules, (size, size), interpolation=cv2.INTER_NEAREST)
    ok, buf = cv2.imencode(".png", image)
    if not ok:
        raise Video2AgentError("E_QR_LIB", "Could not encode the QR PNG.", "Retry.")
    return "data:image/png;base64," + base64.b64encode(buf.tobytes()).decode("ascii")


def cookies_from_redirect(url: str) -> dict[str, str]:
    """The confirmed login returns its cookies in the redirect URL's query string."""
    if not url:
        return {}
    query = parse_qs(urlparse(url).query)
    out: dict[str, str] = {}
    for name in _KEEP:
        values = query.get(name)
        if values and values[0]:
            out[name] = values[0]
    return out


def cookies_from_session(session: requests.Session) -> dict[str, str]:
    """Cookies Bilibili set on the poll response itself (when no redirect URL)."""
    out: dict[str, str] = {}
    jar = getattr(session, "cookies", None)
    if jar is None:
        return out
    for name in _KEEP:
        value = None
        try:
            value = jar.get(name, domain=".bilibili.com")
        except Exception:  # noqa: BLE001 - a plain dict has no domain argument
            try:
                value = jar.get(name)
            except Exception:  # noqa: BLE001
                value = None
        if value:
            out[name] = value
    return out


def poll_login(key: str, session: requests.Session | None = None) -> dict[str, Any]:
    s = session or _session()
    try:
        payload = s.get(_POLL, params={"qrcode_key": key}, timeout=15).json()
    except Exception as e:  # noqa: BLE001
        raise Video2AgentError("E_BILI_QR", f"Bilibili QR poll failed: {e}", "Retry.") from e
    data = payload.get("data") or {}
    code = data.get("code")
    state = STATE_BY_CODE.get(code if isinstance(code, int) else -1, "pending" if payload.get("code") == 0 else "error")
    result: dict[str, Any] = {"state": state, "code": code}
    if state == "ok":
        # Confirmed logins put their cookies in the redirect URL's query string, but
        # some responses carry them as Set-Cookie instead; take whatever exists.
        cookies = cookies_from_redirect(str(data.get("url") or ""))
        for name, value in cookies_from_session(s).items():
            cookies.setdefault(name, value)
        if not cookies.get("SESSDATA"):
            # Consumed QR: the scan worked, but there is nothing to persist.
            return {"state": "failed", "code": code, "reason": "no_cookie"}
        result["cookies"] = cookies
        result["logged_in"] = True
        result["uid"] = cookies.get("DedeUserID") or ""
    return result


def _netscape(cookies: dict[str, str], ttl_days: int = 30) -> str:
    expires = int(time.time()) + ttl_days * 86400
    lines = ["# Netscape HTTP Cookie File", "# generated by video2agent biliauth"]
    for name, value in cookies.items():
        lines.append("\t".join([".bilibili.com", "TRUE", "/", "FALSE", str(expires), name, value]))
    return "\n".join(lines) + "\n"


def save_login(cfg: Config, cookies: dict[str, str]) -> dict[str, Any]:
    if not cookies.get("SESSDATA"):
        raise Video2AgentError("E_BILI_LOGIN", "The login did not return SESSDATA.", "Scan the QR with the Bilibili app and retry.")
    path = login_path(cfg)
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(".tmp")
    tmp.write_text(_netscape(cookies), encoding="utf-8")
    try:
        import os

        os.chmod(tmp, 0o600)
    except Exception:  # noqa: BLE001 - Windows has no POSIX mode
        pass
    tmp.replace(path)
    return {"ok": True, "uid": cookies.get("DedeUserID") or "", "path": str(path)}


def login_status(cfg: Config) -> dict[str, Any]:
    path = login_path(cfg)
    if not path.is_file():
        return {"logged_in": False, "uid": ""}
    uid = ""
    try:
        for line in path.read_text(encoding="utf-8", errors="replace").splitlines():
            if line.startswith("#") or not line.strip():
                continue
            parts = line.split("\t")
            if len(parts) >= 7 and parts[5] == "DedeUserID":
                uid = parts[6]
    except OSError:
        return {"logged_in": False, "uid": ""}
    return {"logged_in": True, "uid": uid}


def clear_login(cfg: Config) -> dict[str, Any]:
    path = login_path(cfg)
    removed = False
    try:
        if path.is_file():
            path.unlink()
            removed = True
    except OSError:
        removed = False
    return {"ok": True, "cleared": removed}

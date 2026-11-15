from __future__ import annotations

import ipaddress
import socket
import urllib.request
from urllib.parse import urlparse

from .util import Video2AgentError

_BLOCKED_HOSTS = {
    "metadata.google.internal",
    "metadata",
    "instance-data",
}

_BLOCKED_IPS = {
    "169.254.169.254",
    "100.100.100.200",
}


def assert_public_url(url: str, *, allow_private: bool = False) -> None:
    parsed = urlparse(url)
    if parsed.scheme not in ("http", "https"):
        raise Video2AgentError("E_URL_SCHEME", f"Only http(s) URLs are allowed: {url}", "Pass a local file or an http(s) URL.")
    host = (parsed.hostname or "").strip().lower()
    if not host:
        raise Video2AgentError("E_URL_HOST", f"URL has no host: {url}", "Check the URL.")
    if allow_private:
        return
    if host in _BLOCKED_HOSTS:
        raise Video2AgentError("E_PRIVATE_URL", f"Blocked metadata host: {host}", "Use a public video URL.")
    try:
        infos = socket.getaddrinfo(host, None)
    except OSError as e:
        raise Video2AgentError("E_DNS", f"Cannot resolve {host}: {e}", "Check the URL/network or use a local file.") from e
    for info in infos:
        ip_text = info[4][0]
        if ip_text in _BLOCKED_IPS:
            raise Video2AgentError("E_PRIVATE_URL", f"Blocked metadata IP: {ip_text}", "Use a public video URL.")
        try:
            ip = ipaddress.ip_address(ip_text)
        except ValueError:
            continue
        if not ip.is_global:
            raise Video2AgentError("E_PRIVATE_URL", f"Blocked private/reserved address: {ip_text}", "Use a public URL or set allow_private_urls=true for local testing.")


class _PublicOnlyRedirect(urllib.request.HTTPRedirectHandler):
    """Validate every redirect hop, not just the first URL (SSRF via 302)."""

    def redirect_request(self, req, fp, code, msg, headers, newurl):
        assert_public_url(newurl)
        return super().redirect_request(req, fp, code, msg, headers, newurl)


def safe_urlopen(req, *, timeout: float = 20):
    """urllib.request.urlopen that refuses redirects into private/metadata hosts."""
    opener = urllib.request.build_opener(_PublicOnlyRedirect)
    return opener.open(req, timeout=timeout)

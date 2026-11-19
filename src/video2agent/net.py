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

# Cloud metadata endpoints: blocked in every mode, including allow_private.
# 169.254.169.254 (AWS/GCP/Azure/OpenStack), 100.100.100.200 (Alibaba Cloud),
# fd00:ec2::254 (AWS IPv6 IMDS).
_BLOCKED_IPS = {
    "169.254.169.254",
    "100.100.100.200",
    "fd00:ec2::254",
}

# RFC 2544 benchmarking range. Clash Verge / mihomo and other TUN proxies in
# fake-ip mode answer *every* DNS query with an address in 198.18.0.0/15; the
# real outbound connection is made and resolved by the proxy, so such an answer
# is not evidence of a private-network target. Treating it as private broke every
# remote ingest for the (very common) TUN + fake-ip setup.
_PROXY_FAKE_IP_NET = ipaddress.ip_network("198.18.0.0/15")


def _iter_ips(host: str):
    try:
        infos = socket.getaddrinfo(host, None)
    except OSError as e:
        raise Video2AgentError("E_DNS", f"Cannot resolve {host}: {e}", "Check the URL/network or use a local file.") from e
    for info in infos:
        ip_text = str(info[4][0])
        try:
            ip = ipaddress.ip_address(ip_text)
        except ValueError:
            continue
        # A v4-mapped IPv6 literal must be checked as the IPv4 address it names.
        if isinstance(ip, ipaddress.IPv6Address) and ip.ipv4_mapped is not None:
            ip = ip.ipv4_mapped
        yield ip_text, ip


def assert_public_url(url: str, *, allow_private: bool = False) -> None:
    """Refuse URLs that point at loopback/private/metadata targets.

    allow_private skips only the public-address requirement (for local testing);
    metadata and link-local targets stay blocked so the escape hatch cannot be
    used to read a cloud instance's credentials.
    """
    parsed = urlparse(url)
    if parsed.scheme not in ("http", "https"):
        raise Video2AgentError("E_URL_SCHEME", f"Only http(s) URLs are allowed: {url}", "Pass a local file or an http(s) URL.")
    host = (parsed.hostname or "").strip().lower()
    if not host:
        raise Video2AgentError("E_URL_HOST", f"URL has no host: {url}", "Check the URL.")
    # Metadata host names are blocked before DNS: allow_private must not unlock
    # them, and a fake-ip proxy would answer for them too.
    if host in _BLOCKED_HOSTS:
        raise Video2AgentError("E_PRIVATE_URL", f"Blocked metadata host: {host}", "Use a public video URL.")
    for ip_text, ip in _iter_ips(host):
        if ip_text in _BLOCKED_IPS or str(ip) in _BLOCKED_IPS:
            raise Video2AgentError("E_PRIVATE_URL", f"Blocked metadata IP: {ip_text}", "Use a public video URL.")
        # Link-local is never a video host, and it is how metadata services are
        # reached (169.254.x); keep it blocked even with allow_private.
        if ip.is_link_local:
            raise Video2AgentError("E_PRIVATE_URL", f"Blocked link-local address: {ip_text}", "Use a public video URL.")
        if ip.is_global:
            continue
        if ip in _PROXY_FAKE_IP_NET:
            # TUN fake-ip: the request leaves through the proxy, which resolves
            # the name remotely. Not a private-network access.
            continue
        if allow_private:
            continue
        raise Video2AgentError(
            "E_PRIVATE_URL",
            f"Blocked private/reserved address: {ip_text}",
            "Use a public URL or set allow_private_urls=true for local testing.",
        )


class _PublicOnlyRedirect(urllib.request.HTTPRedirectHandler):
    """Validate every redirect hop, not just the first URL (SSRF via 302)."""

    def __init__(self, allow_private: bool = False):
        super().__init__()
        self._allow_private = bool(allow_private)

    def redirect_request(self, req, fp, code, msg, headers, newurl):
        # The escape hatch has to reach redirects too: Bilibili answers with many
        # 302s, and the old call dropped allow_private and blocked every hop.
        assert_public_url(newurl, allow_private=self._allow_private)
        return super().redirect_request(req, fp, code, msg, headers, newurl)


def safe_urlopen(req, *, timeout: float = 20, allow_private: bool = False):
    """urllib.request.urlopen that refuses redirects into private/metadata hosts."""
    opener = urllib.request.build_opener(_PublicOnlyRedirect(allow_private=allow_private))
    return opener.open(req, timeout=timeout)

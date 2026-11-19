import http.server
import unittest
from unittest.mock import patch

from video2agent import net
from video2agent.util import Video2AgentError


class _RedirectHandler(http.server.BaseHTTPRequestHandler):
    target = ""

    def do_GET(self):  # noqa: N802
        self.send_response(302)
        self.send_header("Location", _RedirectHandler.target)
        self.end_headers()

    def log_message(self, *args):
        return


class SsrfRedirectTest(unittest.TestCase):
    def test_redirect_to_loopback_is_blocked(self):
        # A public-looking initial host that actually points at loopback would be
        # blocked earlier, so drive redirect_request directly with a private target.
        handler = net._PublicOnlyRedirect()
        req = net.urllib.request.Request("http://example.com/a.jpg")
        with self.assertRaises(Video2AgentError) as ctx:
            handler.redirect_request(req, None, 302, "Found", {}, "http://127.0.0.1:9/secret")
        self.assertEqual(ctx.exception.code, "E_PRIVATE_URL")

    def test_allow_private_reaches_redirect_hops(self):
        # Bilibili 302s: the escape hatch used to be dropped in this branch, so a
        # local proxy/CDN test URL could not follow redirects at all.
        handler = net._PublicOnlyRedirect(allow_private=True)
        req = net.urllib.request.Request("http://example.com/a.jpg")
        out = handler.redirect_request(req, None, 302, "Found", {}, "http://127.0.0.1:9/secret")
        self.assertIsNotNone(out)

    def test_safe_urlopen_forwards_allow_private(self):
        req = net.urllib.request.Request("http://example.com/x")
        with patch.object(net.urllib.request, "build_opener") as build:
            net.safe_urlopen(req, allow_private=True)
        handler = build.call_args.args[0]
        self.assertTrue(handler._allow_private)
        with patch.object(net.urllib.request, "build_opener") as build:
            net.safe_urlopen(req)
        self.assertFalse(build.call_args.args[0]._allow_private)

    def test_redirect_to_public_host_allowed(self):
        handler = net._PublicOnlyRedirect()
        req = net.urllib.request.Request("http://example.com/a.jpg")
        with patch.object(net, "assert_public_url", lambda url, **kwargs: None):
            out = handler.redirect_request(req, None, 302, "Found", {}, "https://cdn.example.com/b.jpg")
        self.assertIsNotNone(out)

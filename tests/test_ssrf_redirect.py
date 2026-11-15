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

    def test_redirect_to_public_host_allowed(self):
        handler = net._PublicOnlyRedirect()
        req = net.urllib.request.Request("http://example.com/a.jpg")
        with patch.object(net, "assert_public_url", lambda url: None):
            out = handler.redirect_request(req, None, 302, "Found", {}, "https://cdn.example.com/b.jpg")
        self.assertIsNotNone(out)

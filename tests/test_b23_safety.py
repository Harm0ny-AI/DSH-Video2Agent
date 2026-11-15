"""Bilibili short links must be real b23.tv URLs and every hop must be public."""

import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from video2agent.bili_account import AccountClient, _b23_short_url
from video2agent.config import load_config
from video2agent.util import Video2AgentError


class B23SafetyTests(unittest.TestCase):
    def test_only_real_b23_hosts_are_short_links(self):
        self.assertEqual(_b23_short_url("https://b23.tv/abc"), "https://b23.tv/abc")
        self.assertIsNone(_b23_short_url("https://evil.example/?b23.tv"))
        self.assertIsNone(_b23_short_url("http://127.0.0.1:9/?b23.tv"))
        self.assertIsNone(_b23_short_url("file:///b23.tv/x"))

    def test_a_fake_b23_substring_never_reaches_requests(self):
        with tempfile.TemporaryDirectory() as tmp:
            client = AccountClient(cfg=load_config(Path(tmp)))
            with patch("video2agent.bili_account.requests.get") as get:
                with self.assertRaises(Video2AgentError) as ctx:
                    client._resolve_aid("http://127.0.0.1:9/?b23.tv")
        self.assertEqual(ctx.exception.code, "E_ACCOUNT_ARGS")
        get.assert_not_called()

    def test_a_private_redirect_is_refused_before_the_second_request(self):
        with tempfile.TemporaryDirectory() as tmp:
            client = AccountClient(cfg=load_config(Path(tmp)))
            redirect = type("R", (), {
                "status_code": 302,
                "headers": {"location": "http://127.0.0.1:9/x"},
                "url": "https://b23.tv/abc",
            })()
            with patch("video2agent.bili_account.requests.get", return_value=redirect) as get:
                with self.assertRaises(Video2AgentError) as ctx:
                    client._resolve_aid("https://b23.tv/abc")
        self.assertEqual(ctx.exception.code, "E_ACCOUNT_ARGS")
        self.assertEqual(get.call_count, 1)


if __name__ == "__main__":
    unittest.main()

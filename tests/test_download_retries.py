import tempfile
import unittest
from pathlib import Path
from unittest import mock

from video2agent import sources
from video2agent.config import Config
from video2agent.util import Video2AgentError


class DownloadRetryBounds(unittest.TestCase):
    """A stalled Bilibili CDN node must not cost ten minutes per video."""

    def test_retries_and_socket_timeout_are_bounded(self):
        cfg = Config(Path(tempfile.mkdtemp(prefix="vp-dl-")))
        captured = {}

        class Result:
            ok = False
            stdout = ""
            stderr = "[download] Got error: SSL EOF"

        def fake_run(cmd, timeout=None):
            captured["cmd"] = list(cmd)
            captured["timeout"] = timeout
            return Result()

        with mock.patch.object(sources, "fetch_metadata", return_value={}), \
             mock.patch.object(sources, "run", side_effect=fake_run):
            with self.assertRaises(Video2AgentError):
                sources.download_video(
                    "https://www.bilibili.com/video/BV1xx411c7mD",
                    cfg,
                    video_id="vid_dl",
                )

        cmd = captured["cmd"]
        for flag, value in (("--retries", "3"), ("--fragment-retries", "3")):
            self.assertIn(flag, cmd, flag)
            self.assertEqual(cmd[cmd.index(flag) + 1], value, flag)
        # No --retry-sleep: a malformed expression makes every download fail
        # (measured: 'linear:1:1' is rejected by yt-dlp).
        self.assertNotIn("--retry-sleep", cmd)
        # yt-dlp already defaults to a 20s socket timeout; passing it would
        # override the user's own configuration.
        self.assertNotIn("--socket-timeout", cmd)

        # String assertions alone missed an invalid value once ('linear:1:1'
        # passed this test and broke every download). Ask the real yt-dlp to
        # parse the same flags.
        import subprocess
        import sys
        parsed = subprocess.run(
            [sys.executable, "-m", "yt_dlp", "--retries", "3", "--fragment-retries", "3",
             "--version"],
            capture_output=True, text=True, timeout=120,
        )
        self.assertEqual(parsed.returncode, 0, parsed.stderr[-400:])


if __name__ == "__main__":
    unittest.main()
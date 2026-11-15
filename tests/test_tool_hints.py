import os
import unittest
from unittest.mock import patch

from video2agent import media
from video2agent.util import Video2AgentError, install_hint, require_tool, run


class InstallHintTests(unittest.TestCase):
    """The missing-FFmpeg error is what a user hands to their agent to fix.

    A vague "install FFmpeg and make sure it is on PATH" makes the assistant
    guess; the remedy must be a command it can run on this platform.
    """

    def test_ffmpeg_hint_is_platform_specific(self):
        with patch("video2agent.util.sys.platform", "win32"):
            hint = install_hint("ffmpeg")
            self.assertIn("winget install Gyan.FFmpeg", hint)
            self.assertIn("FFMPEG_BIN", hint)
        with patch("video2agent.util.sys.platform", "darwin"):
            self.assertIn("brew install ffmpeg", install_hint("ffprobe"))
        with patch("video2agent.util.sys.platform", "linux"):
            self.assertIn("apt install ffmpeg", install_hint("ffmpeg"))

    def test_other_tools_keep_the_generic_hint(self):
        self.assertIn("on PATH", install_hint("git"))

    def test_a_missing_ffmpeg_is_reported_as_ffmpeg_not_a_generic_command(self):
        with patch("video2agent.util.subprocess.run", side_effect=FileNotFoundError("ffmpeg")):
            with self.assertRaises(Video2AgentError) as ctx:
                run(["ffmpeg", "-version"])
        self.assertEqual(ctx.exception.code, "E_FFMPEG")
        remedy = ctx.exception.remedy or ""
        self.assertIn("FFMPEG_BIN", remedy)
        self.assertTrue(
            any(cmd in remedy for cmd in ("winget install Gyan.FFmpeg", "brew install ffmpeg", "apt install ffmpeg")),
            remedy,
        )

    def test_a_missing_other_tool_stays_e_tool_missing(self):
        with patch("video2agent.util.subprocess.run", side_effect=FileNotFoundError("git")):
            with self.assertRaises(Video2AgentError) as ctx:
                run(["git", "--version"])
        self.assertEqual(ctx.exception.code, "E_TOOL_MISSING")

    def test_require_tool_names_the_ffmpeg_install_command(self):
        with patch("video2agent.util.shutil.which", return_value=None):
            with patch("video2agent.util.sys.platform", "win32"):
                with self.assertRaises(Video2AgentError) as ctx:
                    require_tool("ffmpeg")
            self.assertEqual(ctx.exception.code, "E_FFMPEG")
            self.assertIn("winget", ctx.exception.remedy or "")


class FfmpegPathTests(unittest.TestCase):
    """A bundled/portable FFmpeg is addressed through FFMPEG_BIN/FFPROBE_BIN."""

    def test_env_override_wins_over_path(self):
        with patch.dict(os.environ, {"FFMPEG_BIN": r"C:\tools\ffmpeg.exe", "FFPROBE_BIN": r"C:\tools\ffprobe.exe"}):
            self.assertEqual(media._ffmpeg(), r"C:\tools\ffmpeg.exe")
            self.assertEqual(media._ffprobe(), r"C:\tools\ffprobe.exe")

    def test_path_is_used_without_an_override(self):
        with patch.dict(os.environ, {}, clear=False):
            os.environ.pop("FFMPEG_BIN", None)
            with patch("video2agent.media.which", return_value="/usr/bin/ffmpeg"):
                self.assertEqual(media._ffmpeg(), "/usr/bin/ffmpeg")


if __name__ == "__main__":
    unittest.main()

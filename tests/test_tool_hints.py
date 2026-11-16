import os
import shutil
import tempfile
import unittest
from unittest.mock import patch

from video2agent import media, perception
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


class MissingFfmpegPathTests(unittest.TestCase):
    """A missing Windows .exe must still be reported as an FFmpeg problem.

    The docs tell users to point FFMPEG_BIN at ffmpeg.exe; Path(...).name keeps
    ".exe" and fell out of the FFmpeg family, so the error became a generic
    "Command not found" with no install command.
    """

    def test_exe_path_is_still_ffmpeg(self):
        with patch("video2agent.util.subprocess.run", side_effect=FileNotFoundError("ffmpeg.exe")):
            with self.assertRaises(Video2AgentError) as ctx:
                run([r"C:\nope\ffmpeg.exe", "-version"])
        self.assertEqual(ctx.exception.code, "E_FFMPEG")
        self.assertIn("FFMPEG_BIN", ctx.exception.remedy or "")

    def test_bad_override_is_named(self):
        bad = r"C:\nope\ffmpeg.exe"
        with patch.dict(os.environ, {"FFMPEG_BIN": bad}):
            with patch("video2agent.util.subprocess.run", side_effect=FileNotFoundError(bad)):
                with self.assertRaises(Video2AgentError) as ctx:
                    run([bad, "-version"])
        self.assertEqual(ctx.exception.code, "E_FFMPEG")
        self.assertIn("不存在", ctx.exception.message)

    def test_require_tool_uses_the_override(self):
        handle, path = tempfile.mkstemp(suffix=".exe")
        os.close(handle)
        try:
            with patch.dict(os.environ, {"FFMPEG_BIN": path}):
                self.assertEqual(require_tool("ffmpeg"), path)
        finally:
            os.unlink(path)

    def test_require_tool_rejects_a_missing_override(self):
        bad = r"C:\nope\ffprobe.exe"
        with patch.dict(os.environ, {"FFPROBE_BIN": bad}):
            with self.assertRaises(Video2AgentError) as ctx:
                require_tool("ffprobe")
        self.assertEqual(ctx.exception.code, "E_FFMPEG")
        self.assertIn("不存在", ctx.exception.message)

    def test_perception_uses_the_override_and_rejects_a_bad_one(self):
        handle, path = tempfile.mkstemp(suffix=".exe")
        os.close(handle)
        try:
            with patch.dict(os.environ, {"FFMPEG_BIN": path}):
                self.assertEqual(perception._require_tool("ffmpeg"), path)
        finally:
            os.unlink(path)
        with patch.dict(os.environ, {"FFMPEG_BIN": r"C:\nope\ffmpeg.exe"}):
            with self.assertRaises(Video2AgentError) as ctx:
                perception._require_tool("ffmpeg")
        self.assertEqual(ctx.exception.code, "E_FFMPEG")
        self.assertIn("不存在", ctx.exception.message)

    def test_doctor_reports_the_override(self):
        from video2agent import config
        handle, path = tempfile.mkstemp(suffix=".exe")
        os.close(handle)
        home = tempfile.mkdtemp(prefix="vp-doctor-")
        try:
            with patch.dict(os.environ, {"VIDEO2AGENT_HOME": home, "FFMPEG_BIN": path, "FFPROBE_BIN": path}):
                checks = {check["name"]: check for check in config.doctor()["checks"]}
            self.assertTrue(checks["ffmpeg"]["ok"])
            self.assertEqual(checks["ffmpeg"]["detail"], path)
            self.assertTrue(checks["ffprobe"]["ok"])
        finally:
            os.unlink(path)
            shutil.rmtree(home, ignore_errors=True)

    def test_doctor_names_a_bad_override(self):
        from video2agent import config
        home = tempfile.mkdtemp(prefix="vp-doctor-")
        bad = r"C:\nope\ffmpeg.exe"
        try:
            with patch.dict(os.environ, {"VIDEO2AGENT_HOME": home, "FFMPEG_BIN": bad}):
                checks = {check["name"]: check for check in config.doctor()["checks"]}
            self.assertFalse(checks["ffmpeg"]["ok"])
            self.assertIn("不存在", checks["ffmpeg"]["detail"])
        finally:
            shutil.rmtree(home, ignore_errors=True)

    def test_cloud_duration_maps_a_missing_ffprobe(self):
        from video2agent import cloud
        empty = tempfile.mkdtemp(prefix="vp-empty-path-")
        try:
            with patch.dict(os.environ, {"PATH": empty}, clear=False):
                with patch.dict(os.environ, {}, clear=False):
                    os.environ.pop("FFPROBE_BIN", None)
                    with self.assertRaises(Video2AgentError) as ctx:
                        cloud._duration(__import__("pathlib").Path("whatever.mp3"))
            self.assertEqual(ctx.exception.code, "E_FFMPEG")
        finally:
            shutil.rmtree(empty, ignore_errors=True)


if __name__ == "__main__":
    unittest.main()
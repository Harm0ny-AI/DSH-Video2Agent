import json
import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from video2agent import util


class ManagedToolPathTest(unittest.TestCase):
    def test_managed_ffmpeg_is_used_when_path_is_stale(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            bin_dir = root / "bin"
            bin_dir.mkdir()
            ffmpeg = bin_dir / "ffmpeg.exe"
            ffprobe = bin_dir / "ffprobe.exe"
            ffmpeg.write_bytes(b"")
            ffprobe.write_bytes(b"")
            tools = root / "tools" / "ffmpeg.json"
            tools.parent.mkdir()
            tools.write_text(json.dumps({"ffmpeg": str(ffmpeg), "ffprobe": str(ffprobe)}), encoding="utf-8")
            with patch.dict(os.environ, {"VIDEO2AGENT_HOME": td}):
                self.assertEqual(util.which("ffmpeg"), str(ffmpeg))
                self.assertEqual(util.which("ffprobe"), str(ffprobe))

    def test_unknown_tool_still_uses_path_lookup(self):
        self.assertEqual(util.which("definitely-not-a-real-tool-xyz"), None)


if __name__ == "__main__":
    unittest.main()

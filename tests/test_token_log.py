"""Opt-in tool-result measurement must be off unless the flag file exists."""

import tempfile
import unittest
from pathlib import Path

from video2agent import cli


class TokenLogTests(unittest.TestCase):
    def test_log_only_written_with_the_flag(self):
        with tempfile.TemporaryDirectory() as tmp:
            cli._TOKEN_LOG_DIR = Path(tmp)
            cli._TOKEN_LOG_COMMAND = "search"
            try:
                cli._log_tool_result({"ok": True, "video_id": "v", "images": ["a.jpg"]})
                self.assertFalse((Path(tmp) / "token-log.jsonl").exists())
                (Path(tmp) / "token-log.on").write_text("1", encoding="utf-8")
                cli._log_tool_result({"ok": True, "video_id": "v", "images": ["a.jpg"]})
                lines = (Path(tmp) / "token-log.jsonl").read_text(encoding="utf-8").splitlines()
            finally:
                cli._TOKEN_LOG_DIR = None
                cli._TOKEN_LOG_COMMAND = ""
        self.assertEqual(len(lines), 1)
        self.assertIn('"images": 1', lines[0])
        self.assertIn('"cmd": "search"', lines[0])


if __name__ == "__main__":
    unittest.main()

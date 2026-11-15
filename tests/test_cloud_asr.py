"""Cloud ASR format/chunking: Qwen3-ASR rejects verbose_json, json works."""

import tempfile
import unittest
from pathlib import Path
from unittest.mock import MagicMock, patch

from video2agent import cloud
from video2agent.util import Video2AgentError


class CloudAsrFormatTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.wav = Path(self.tmp.name) / "a.wav"
        self.wav.write_bytes(b"RIFF")

    def _run(self, responses, model="Qwen/Qwen3-ASR-1.7B"):
        with patch("video2agent.cloud.load_key", return_value="k"), \
                patch("video2agent.cloud._read_config", return_value={"base_url": "https://x", "asr_model": model}), \
                patch("video2agent.cloud._chunks", return_value=[(self.wav, 0.0)]) as chunks, \
                patch("video2agent.cloud.requests.post", side_effect=responses) as post:
            result = cloud.transcribe(MagicMock(), self.wav)
        return result, post, chunks

    def test_qwen_uses_json_and_two_minute_chunks(self):
        ok = MagicMock(status_code=200)
        ok.json.return_value = {"text": "привет", "language": "Russian", "usage": {"duration": 60}}
        result, post, chunks = self._run([ok])
        self.assertEqual(post.call_count, 1)
        self.assertEqual(post.call_args.kwargs["data"]["response_format"], "json")
        self.assertEqual(chunks.call_args.kwargs["seconds"], 120, "Qwen has no segment timestamps")
        self.assertEqual(result["segments"], [{"start_ms": 0, "end_ms": 60000, "text": "привет"}])
        self.assertEqual(result["language"], "Russian")

    def test_verbose_json_rejected_retries_with_json(self):
        rejected = MagicMock(status_code=400, text="")
        ok = MagicMock(status_code=200)
        ok.json.return_value = {"text": "hello", "language": "English", "usage": {"duration": 30}}
        result, post, chunks = self._run([rejected, ok], model="whisper-1")
        self.assertEqual(post.call_count, 2)
        self.assertEqual(post.call_args_list[0].kwargs["data"]["response_format"], "verbose_json")
        self.assertEqual(post.call_args_list[1].kwargs["data"]["response_format"], "json")
        self.assertEqual(chunks.call_args.kwargs["seconds"], 1800)
        self.assertEqual(result["segments"], [{"start_ms": 0, "end_ms": 30000, "text": "hello"}])

    def test_verbose_json_segments_are_kept(self):
        ok = MagicMock(status_code=200)
        ok.json.return_value = {"segments": [{"start": 1.5, "end": 3.0, "text": "hello"}], "language": "English"}
        result, post, _chunks = self._run([ok], model="whisper-1")
        self.assertEqual(post.call_count, 1)
        self.assertEqual(result["segments"][0]["start_ms"], 1500)
        self.assertEqual(result["language"], "English")

    def test_empty_cloud_transcript_is_an_error(self):
        ok = MagicMock(status_code=200)
        ok.json.return_value = {"text": ""}
        with self.assertRaises(Video2AgentError) as ctx:
            self._run([ok])
        self.assertEqual(ctx.exception.code, "E_CLOUD_ASR_EMPTY")


if __name__ == "__main__":
    unittest.main()

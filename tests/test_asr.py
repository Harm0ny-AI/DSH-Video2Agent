import unittest
from pathlib import Path

from video2agent.text import transcribe_with_faster_whisper

ROOT = Path(__file__).resolve().parents[1]
MODEL = ROOT / ".models" / "faster-whisper-tiny"
AUDIO = ROOT / "tests" / "fixtures" / "speech.wav"


class AsrTests(unittest.TestCase):
    @unittest.skipUnless(MODEL.exists() and AUDIO.exists(), "local tiny model/audio not available")
    def test_local_asr(self):
        segments, lang = transcribe_with_faster_whisper(
            AUDIO, model_size=str(MODEL), device="cpu", compute_type="int8",
        )
        self.assertTrue(segments)
        self.assertIn("test", " ".join(s["text"] for s in segments).lower())
        self.assertTrue(lang)


if __name__ == "__main__":
    unittest.main()

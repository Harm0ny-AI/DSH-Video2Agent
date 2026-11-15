import unittest
from pathlib import Path

from video2agent.pipeline import _asr_language_hint
from video2agent.text import has_kana, transcribe_with_faster_whisper

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


class AsrLanguageHintTests(unittest.TestCase):
    """A Chinese Bilibili video was transcribed as Japanese on 2026-11-15.

    With no language, faster-whisper guesses from 30s of audio and loud background
    music beat the speech. The title is a better prior, but only where it is
    trustworthy: a Bilibili video with a Chinese title and no kana.
    """

    def test_explicit_language_wins(self):
        self.assertEqual(_asr_language_hint("ja", {"language": "zh", "platform": "bilibili", "title": "中文标题"}), "ja")

    def test_bilibili_chinese_title_forces_zh(self):
        self.assertEqual(_asr_language_hint(None, {"language": "zh", "platform": "BiliBili", "title": "双11手机推荐"}), "zh")

    def test_japanese_title_keeps_auto_detection(self):
        self.assertIsNone(_asr_language_hint(None, {"language": "zh", "platform": "bilibili", "title": "【作業用】テスト動画"}))

    def test_other_platforms_keep_auto_detection(self):
        self.assertIsNone(_asr_language_hint(None, {"language": "zh", "platform": "youtube", "title": "中文标题的视频"}))

    def test_english_and_unknown_hints_do_not_force(self):
        self.assertIsNone(_asr_language_hint(None, {"language": "en", "platform": "bilibili", "title": "English title"}))
        self.assertIsNone(_asr_language_hint(None, {"language": "unknown", "platform": "bilibili", "title": "标题"}))

    def test_has_kana(self):
        self.assertTrue(has_kana("これ、テスト"))
        self.assertFalse(has_kana("双11手机推荐"))
        self.assertFalse(has_kana(""))


if __name__ == "__main__":
    unittest.main()

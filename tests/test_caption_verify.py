from __future__ import annotations

import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from video2agent.caption_verify import _cached_model, text_similarity, verify_caption_audio


class _Cfg(dict):
    def __init__(self, derived_dir: Path):
        super().__init__(asr_device="cpu", asr_compute_type="int8", asr_cpu_threads=0)
        self.derived_dir = derived_dir


def _segments(text: str) -> list[dict]:
    return [{"start_ms": 0, "end_ms": 70_000, "text": text}]


class CaptionAudioVerifyTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.dir = Path(self.tmp.name)
        self.cfg = _Cfg(self.dir)
        self.video = self.dir / "video.mp4"
        self.video.write_bytes(b"not a real video")

    def tearDown(self):
        self.tmp.cleanup()

    def _run(self, caption: str, heard: str, *, lang: str = "zh-CN", cached: bool = True,
             one_window: bool = False):
        def fake_extract(_video, out, _windows, **_kwargs):
            Path(out).parent.mkdir(parents=True, exist_ok=True)
            Path(out).write_bytes(b"RIFF")
            return Path(out)

        asr_segments = [{"text": heard, "start_ms": 0}]
        if not one_window:
            # The two 7s windows of a 70s video start at 0 and 7s in the
            # concatenated sample; give each window its own ASR segment.
            asr_segments.append({"text": heard, "start_ms": 7_000})
        with patch("video2agent.caption_verify.whisper_cache_state", return_value={"cached": cached}), \
             patch("video2agent.caption_verify.extract_audio_windows", side_effect=fake_extract), \
             patch("video2agent.caption_verify.transcribe_with_faster_whisper",
                   return_value=(asr_segments, "zh")):
            return verify_caption_audio(
                self.video,
                _segments(caption),
                self.cfg,
                70_000,
                caption_lang=lang,
                temp_dir=self.dir,
            )

    def test_matching_caption_is_verified(self):
        caption = "今天我们讲量化交易的基础知识，包括常见因子、回测方法和风险控制"
        result = self._run(caption, caption)
        self.assertEqual(result["verdict"], "verified")
        self.assertGreaterEqual(result["score"], 0.18)
        self.assertEqual(result["model"], "tiny")
        self.assertGreaterEqual(result["seconds"], 0.0)

    def test_joke_caption_is_rejected(self):
        result = self._run(
            "今天我们去吃火锅吧，顺便聊聊最近看的电影和旅行计划",
            "现在我们讲量化因子、回测方法和风险控制的具体实现",
        )
        self.assertEqual(result["verdict"], "mismatch")
        self.assertLess(result["score"], 0.18)

    def test_gray_zone_is_unverified_not_verified(self):
        # Partial topical overlap (0.25) is not enough to claim verification, and
        # not low enough to throw away a possibly paraphrased caption. It shares
        # only filler bigrams (今天/我们/聊聊).
        result = self._run(
            "我们今天就随便聊聊最近的生活吧啊",
            "今天我们来聊聊这个量化因子和回测",
        )
        self.assertEqual(result["verdict"], "unknown")
        self.assertEqual(result["reason"], "low_confidence")
        self.assertGreater(result["score"], 0.18)
        self.assertLess(result["score"], 0.5)

    def test_one_scorable_window_is_not_enough_to_reject(self):
        result = self._run(
            "今天我们去吃火锅吧，顺便聊聊最近看的电影和旅行计划",
            "现在我们讲量化因子、回测方法和风险控制的具体实现",
            one_window=True,
        )
        self.assertEqual(result["verdict"], "unknown")
        self.assertEqual(result["reason"], "low_confidence")
        self.assertEqual(len(result["window_scores"]), 1)

    def test_one_scorable_window_is_not_enough_to_verify(self):
        result = self._run(
            "现在我们讲量化因子和回测方法的具体实现",
            "现在我们讲量化因子和回测方法的具体实现",
            one_window=True,
        )
        self.assertEqual(result["verdict"], "unknown")
        self.assertEqual(result["reason"], "low_confidence")

    def test_english_filler_is_not_verified(self):
        # "we are going to …" is not evidence; content words must overlap.
        result = self._run(
            "we are going to eat hotpot and chat about movies",
            "we are going to explain quant factors and backtesting",
            lang="en-US",
        )
        self.assertNotEqual(result["verdict"], "verified")
        self.assertLess(result["score"], 0.5)

    def test_script_mismatch_is_not_rejected(self):
        # A bilingual/translated track can be correct even when the sampled
        # window is English and the ASR language is Chinese. It is unknown, not a
        # mismatch, and must not trigger a full ASR pass.
        result = self._run(
            "This is a caption about quantitative factors and backtesting",
            "现在我们讲量化因子和回测方法",
        )
        self.assertEqual(result["verdict"], "unknown")
        self.assertEqual(result["reason"], "script_differs")

    def test_medium_is_not_loaded_for_a_16s_check(self):
        with patch("video2agent.caption_verify.whisper_cache_state",
                   side_effect=lambda model: {"cached": model == "medium"}):
            self.assertIsNone(_cached_model(self.cfg))

    def test_configured_cached_model_is_preferred(self):
        self.cfg["asr_model"] = "small"
        with patch("video2agent.caption_verify.whisper_cache_state",
                   side_effect=lambda model: {"cached": model in {"tiny", "small"}}):
            self.assertEqual(_cached_model(self.cfg), "small")

    def test_no_cached_model_keeps_caption(self):
        result = self._run(
            "今天我们讲量化交易的基础知识，包括常见因子、回测方法和风险控制",
            "今天我们讲量化交易的基础知识，包括常见因子、回测方法和风险控制",
            cached=False,
        )
        self.assertEqual(result["verdict"], "unknown")
        self.assertEqual(result["reason"], "no_cached_asr_model")

    def test_translated_track_is_not_rejected(self):
        result = self._run(
            "Today we discuss the basics of quantitative trading, factors and backtesting",
            "今天我们讲量化交易的基础知识，包括常见因子、回测方法和风险控制",
            lang="en-US",
        )
        self.assertEqual(result["verdict"], "unknown")
        self.assertEqual(result["reason"], "caption_language_differs")

    def test_short_video_is_not_checked(self):
        with patch("video2agent.caption_verify.extract_audio_windows") as extract:
            result = verify_caption_audio(self.video, _segments("短"), self.cfg, 30_000)
        self.assertEqual(result["verdict"], "unknown")
        self.assertEqual(result["reason"], "video_too_short")
        extract.assert_not_called()

    def test_similarity_is_language_aware(self):
        self.assertGreater(text_similarity("量化因子和回测", "量化因子与回测"), 0.3)
        self.assertLess(text_similarity("今天吃火锅", "量化因子和回测"), 0.18)

    def test_traditional_asr_matches_simplified_caption(self):
        # Whisper often emits Traditional Chinese; a valid Simplified caption
        # must not be rejected just because the character forms differ.
        self.assertGreater(
            text_similarity("太多东西把电脑跑崩了，中断了一次", "太多東西把電腦跑崩了 中斷了一次"),
            0.4,
        )


if __name__ == "__main__":
    unittest.main()

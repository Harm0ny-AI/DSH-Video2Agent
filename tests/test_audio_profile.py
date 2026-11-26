"""Audio hints for digest: loudness, speech ratio and no-speech gaps."""

import shutil
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from video2agent import media
from video2agent.media import audio_profile, speech_profile

FIXTURES = Path(__file__).parent / "fixtures"


def _ffmpeg() -> str | None:
    return shutil.which("ffmpeg")


def _have_vad() -> bool:
    try:
        import faster_whisper.vad  # noqa: F401
    except Exception:
        return False
    return True


def _make_wav(tmp: str) -> Path:
    from video2agent.util import run

    wav = Path(tmp) / "tone_silence.wav"
    # 1s tone, 2s silence, 1s tone (16000 Hz mono).
    res = run([
        _ffmpeg(), "-y", "-v", "error",
        "-f", "lavfi", "-i", "sine=frequency=440:duration=1",
        "-f", "lavfi", "-i", "anullsrc=r=16000:cl=mono:d=2",
        "-f", "lavfi", "-i", "sine=frequency=660:duration=1",
        "-filter_complex", "[0:a][1:a][2:a]concat=n=3:v=0:a=1", str(wav),
    ], timeout=60)
    assert res.ok and wav.exists(), res.stderr[-300:]
    return wav


@unittest.skipUnless(_ffmpeg(), "ffmpeg not on PATH")
class AudioProfileTests(unittest.TestCase):
    def test_loudness_and_silence(self):
        with tempfile.TemporaryDirectory() as tmp:
            profile = audio_profile(_make_wav(tmp))
            self.assertTrue(profile["has_audio"])
            self.assertIsNotNone(profile["mean_dbfs"])
            self.assertIsNotNone(profile["max_dbfs"])
            self.assertGreater(profile["silence_ratio"], 0.2)
            self.assertIn(profile["source"], ("silero", "silence"))
            self.assertTrue(profile["no_speech_ms"], "the 2s gap is a hint")

    @unittest.skipUnless(_have_vad(), "faster-whisper's Silero VAD is not installed")
    def test_a_music_track_is_not_speech(self):
        # A tone has audio but no speech: volume-based silence would call it
        # "not silent", while the VAD path must report (almost) no speech.
        with tempfile.TemporaryDirectory() as tmp:
            profile = audio_profile(_make_wav(tmp))
            self.assertEqual(profile["source"], "silero")
            self.assertLess(profile["speech_ratio"], 0.1)
            self.assertEqual(len(profile["no_speech_ms"]), 1)

    @unittest.skipUnless(_have_vad() and (FIXTURES / "speech.mp4").exists(),
                         "no speech fixture or VAD")
    def test_real_speech_is_detected(self):
        with patch.object(media, "run", wraps=media.run) as ffmpeg:
            profile = audio_profile(FIXTURES / "speech.mp4")
        stats_command = next(call.args[0] for call in ffmpeg.call_args_list if "-af" in call.args[0])
        self.assertIn("-vn", stats_command)
        self.assertEqual(profile["source"], "silero")
        self.assertGreater(profile["speech_ratio"], 0.3)
        self.assertIsNotNone(profile["first_speech_ms"])

    def test_no_audio_track_is_not_reported_as_quiet(self):
        with tempfile.TemporaryDirectory() as tmp:
            video = Path(tmp) / "silent.mp4"
            from video2agent.util import run

            res = run([
                _ffmpeg(), "-y", "-v", "error", "-f", "lavfi",
                "-i", "color=c=black:s=64x36:d=1", "-an", str(video),
            ], timeout=60)
            self.assertTrue(res.ok and video.exists(), res.stderr[-300:])
            profile = audio_profile(video)
            self.assertFalse(profile["has_audio"])
            self.assertIsNone(profile["speech_ratio"])
            self.assertEqual(profile["no_speech_ms"], [])

    def test_missing_file_is_unmeasured_not_silent(self):
        profile = audio_profile(r"C:\definitely\missing.mp4")
        self.assertFalse(profile["has_audio"])
        self.assertIsNone(profile["silence_ratio"])
        self.assertIsNone(speech_profile(r"C:\definitely\missing.mp4"))


if __name__ == "__main__":
    unittest.main()

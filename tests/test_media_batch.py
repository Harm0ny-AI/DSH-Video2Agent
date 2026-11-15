"""Batch extraction must match the per-frame path exactly."""

import shutil
import tempfile
import unittest
from pathlib import Path

from PIL import Image, ImageChops, ImageStat

from video2agent.media import extract_frame, extract_frames_batch

FIXTURE = Path(__file__).parent / "fixtures" / "slides.mp4"


@unittest.skipUnless(FIXTURE.exists() and shutil.which("ffmpeg"), "needs slides fixture and ffmpeg")
class BatchFrameTests(unittest.TestCase):
    def test_batch_frames_match_the_per_frame_path(self):
        with tempfile.TemporaryDirectory() as tmp:
            batch = extract_frames_batch(FIXTURE, [500, 1_000, 1_500], tmp, width=320, prefix="t")
            self.assertEqual(sorted(batch), [500, 1_000, 1_500])
            one = Path(tmp) / "one.jpg"
            extract_frame(FIXTURE, 1_000, one, width=320)
            diff = ImageStat.Stat(
                ImageChops.difference(Image.open(batch[1_000]).convert("RGB"), Image.open(one).convert("RGB"))
            ).mean
            self.assertLess(sum(diff), 5.0, "batch frame must be the same picture")

    def test_non_uniform_times_are_supported(self):
        with tempfile.TemporaryDirectory() as tmp:
            batch = extract_frames_batch(FIXTURE, [500, 1_100, 1_900], tmp, width=160, prefix="n")
            self.assertEqual(sorted(batch), [500, 1_100, 1_900])

    def test_single_time_returns_empty(self):
        with tempfile.TemporaryDirectory() as tmp:
            self.assertEqual(extract_frames_batch(FIXTURE, [1_000], tmp), {})


if __name__ == "__main__":
    unittest.main()

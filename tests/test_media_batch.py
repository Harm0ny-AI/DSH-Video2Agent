"""Batch extraction must match the per-frame path exactly."""

import shutil
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

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


class BatchSeekTests(unittest.TestCase):
    def test_partial_shared_output_retries_with_independent_seeks(self):
        with tempfile.TemporaryDirectory() as tmp:
            outputs = [Path(tmp) / f"near_3000_{i:04d}.jpg" for i in (1, 2)]
            inputs = []

            def run(cmd, **_kwargs):
                inputs.append(cmd.count("-i"))
                if len(inputs) == 1:
                    outputs[0].write_bytes(b"partial")
                else:
                    self.assertFalse(outputs[0].exists())
                    for path in outputs:
                        path.write_bytes(b"complete")
                return SimpleNamespace(ok=True)

            with patch("video2agent.media.run", side_effect=run):
                result = extract_frames_batch(FIXTURE, [3000, 4250], tmp, prefix="near")
        self.assertEqual(inputs, [1, 2])
        self.assertEqual(list(result), [3000, 4250])

    def test_zero_byte_shared_output_cleans_up_and_retries(self):
        with tempfile.TemporaryDirectory() as tmp:
            outputs = [Path(tmp) / f"zero_3000_{i:04d}.jpg" for i in (1, 2)]
            inputs = []

            def run(cmd, **_kwargs):
                inputs.append(cmd.count("-i"))
                if len(inputs) == 1:
                    outputs[0].write_bytes(b"ok")
                    outputs[1].write_bytes(b"")
                else:
                    self.assertFalse(outputs[0].exists())
                    self.assertFalse(outputs[1].exists())
                    for path in outputs:
                        path.write_bytes(b"complete")
                return SimpleNamespace(ok=True)

            with patch("video2agent.media.run", side_effect=run):
                result = extract_frames_batch(FIXTURE, [3000, 4500], tmp, prefix="zero")
        self.assertEqual(inputs, [1, 2])
        self.assertEqual(list(result), [3000, 4500])

    def test_spread_out_times_use_independent_seeks_directly(self):
        with tempfile.TemporaryDirectory() as tmp:
            outputs = [Path(tmp) / f"wide_1000_{i:04d}.jpg" for i in (1, 2)]
            inputs = []

            def run(cmd, **_kwargs):
                inputs.append(cmd.count("-i"))
                for path in outputs:
                    path.write_bytes(b"complete")
                return SimpleNamespace(ok=True)

            with patch("video2agent.media.run", side_effect=run):
                result = extract_frames_batch(FIXTURE, [1000, 4000], tmp, prefix="wide")
        self.assertEqual(inputs, [2])
        self.assertEqual(list(result), [1000, 4000])


if __name__ == "__main__":
    unittest.main()

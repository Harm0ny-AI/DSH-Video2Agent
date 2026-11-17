import tempfile
import unittest
from pathlib import Path

import numpy as np
from PIL import Image

from video2agent.media import _phash, _sharpness, frame_features, hamming_distance


def write_image(path: Path, array: np.ndarray) -> Path:
    Image.fromarray(array.astype(np.uint8)).save(path)
    return path


class SharpnessTests(unittest.TestCase):
    """The old min(1, var/900) pinned 62-71% of real frames at exactly 1.0."""

    def test_flat_image_is_not_sharp(self):
        flat = np.full((90, 160), 128, dtype=np.uint8)
        self.assertLess(_sharpness(flat), 0.05)

    def test_textured_image_is_sharper_than_flat(self):
        rng = np.random.default_rng(7)
        noise = rng.integers(0, 255, size=(90, 160)).astype(np.uint8)
        self.assertGreater(_sharpness(noise), 0.8)

    def test_values_stay_inside_the_unit_interval(self):
        rng = np.random.default_rng(11)
        for _ in range(20):
            img = rng.integers(0, 255, size=(90, 160)).astype(np.uint8)
            value = _sharpness(img)
            self.assertGreaterEqual(value, 0.0)
            self.assertLessEqual(value, 1.0)


class PHashTests(unittest.TestCase):
    """A real DCT pHash, and it must actually distinguish frames."""

    def _frame(self, seed: int) -> np.ndarray:
        rng = np.random.default_rng(seed)
        base = np.full((72, 128), 40, dtype=np.uint8)
        base[10:30, 10:60] = rng.integers(120, 255, size=(20, 50))
        return base

    def test_identical_frames_have_distance_zero(self):
        img = self._frame(1)
        self.assertEqual(hamming_distance(_phash(img), _phash(img)), 0)

    def test_brightness_shift_barely_moves_the_hash(self):
        img = self._frame(2)
        brighter = np.clip(img.astype(np.int16) + 30, 0, 255).astype(np.uint8)
        self.assertLessEqual(hamming_distance(_phash(img), _phash(brighter)), 8)

    def test_different_layouts_are_far_apart(self):
        a = self._frame(3)
        b = np.roll(self._frame(4), 40, axis=1)
        self.assertGreater(hamming_distance(_phash(a), _phash(b)), 8)

    def test_hash_format_is_stable(self):
        value = _phash(self._frame(5))
        self.assertEqual(len(value), 16)
        int(value, 16)  # parses as hex


class DedupeTests(unittest.TestCase):
    """Hash-based dedupe deleted real slides; the signature must be a pixel diff."""

    def _frame(self, pts, thumb_value, sharpness=0.5, path=None):
        thumb = bytes([thumb_value]) * (32 * 32)
        return {"pts_ms": pts, "path": path or f"{pts}.jpg", "_thumb": thumb, "sharpness": sharpness}

    def test_distinct_slides_in_one_scene_are_all_kept(self):
        from video2agent.pipeline import _dedupe_frames

        scenes = [{"start_ms": 0, "end_ms": 60_000}]
        # Pixel values 20 apart: a real slide change is far bigger than the 8 allowed.
        frames = [self._frame(1000, 0), self._frame(20_000, 20), self._frame(40_000, 40)]
        kept, dropped = _dedupe_frames(frames, scenes)
        self.assertEqual(len(kept), 3)
        self.assertEqual(dropped, [])

    def test_a_small_edit_is_not_a_duplicate(self):
        from video2agent.pipeline import _dedupe_frames

        scenes = [{"start_ms": 0, "end_ms": 60_000}]
        base = bytearray([10]) * (32 * 32)
        edited = bytearray(base)
        for i in range(32, 64):  # one changed line of the thumbnail
            edited[i] = 90
        frames = [
            {"pts_ms": 1000, "path": "a.jpg", "sharpness": 0.5, "_thumb": bytes(base)},
            {"pts_ms": 2000, "path": "b.jpg", "sharpness": 0.9, "_thumb": bytes(edited)},
        ]
        kept, dropped = _dedupe_frames(frames, scenes)
        self.assertEqual(len(kept), 2, "a slide with a new line is a different slide")

    def test_identical_frames_collapse_and_keep_the_sharper(self):
        from video2agent.pipeline import _dedupe_frames

        scenes = [{"start_ms": 0, "end_ms": 60_000}]
        # A re-encode moves pixels by ~2, so a 3-level difference is still a duplicate.
        frames = [self._frame(1000, 7, sharpness=0.3), self._frame(1500, 9, sharpness=0.9)]
        kept, dropped = _dedupe_frames(frames, scenes)
        self.assertEqual(len(kept), 1)
        self.assertEqual(len(dropped), 1)
        self.assertAlmostEqual(kept[0]["sharpness"], 0.9, msg="the sharper frame must survive")

    def test_one_frame_per_scene_even_when_identical(self):
        from video2agent.pipeline import _dedupe_frames

        scenes = [{"start_ms": 0, "end_ms": 10_000}, {"start_ms": 10_000, "end_ms": 20_000}]
        frames = [self._frame(1000, 3), self._frame(11_000, 3)]
        kept, dropped = _dedupe_frames(frames, scenes)
        self.assertEqual(len(kept), 2, "two scenes keep two representatives")
        self.assertEqual(dropped, [])


class FrameFeatureTests(unittest.TestCase):
    def test_unread_frame_reports_text_as_unknown_not_zero(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = write_image(Path(tmp) / "f.png", np.full((90, 160), 128, dtype=np.uint8))
            feats, _ = frame_features(path)
        self.assertIsNone(feats["text_coverage"], "an unread frame must not claim 'no text'")
        self.assertEqual(feats["ocr_status"], "unmeasured")
        self.assertIn("phash", feats)


class HoughLinesShapeTests(unittest.TestCase):
    """opencv 5 changed HoughLinesP's result shape; both must work."""

    def test_both_result_shapes_are_scored(self):
        from unittest.mock import patch

        import numpy as np

        try:
            from video2agent import media
        except Exception:  # pragma: no cover - numpy always present here
            self.skipTest("media stack unavailable")
        if media.cv2 is None:  # pragma: no cover
            self.skipTest("opencv unavailable")
        gray = np.zeros((100, 200), dtype=np.uint8)
        rows_v4 = np.array([[[0, 50, 180, 50]], [[10, 60, 190, 60]]], dtype=np.int32)
        rows_v5 = rows_v4.reshape(-1, 4)
        with patch.object(media.cv2, "HoughLinesP", return_value=rows_v4):
            old = media._line_score(gray)
        with patch.object(media.cv2, "HoughLinesP", return_value=rows_v5):
            new = media._line_score(gray)
        self.assertGreater(old, 0.0)
        self.assertEqual(old, new)


if __name__ == "__main__":
    unittest.main()

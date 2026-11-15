import unittest

from video2agent.pipeline import _evenly_spaced, _ocr_reliable


class OcrReliabilityTests(unittest.TestCase):
    def test_threshold(self):
        self.assertIsNone(_ocr_reliable(None))
        self.assertFalse(_ocr_reliable(0.0))
        self.assertFalse(_ocr_reliable(0.49))
        self.assertTrue(_ocr_reliable(0.5))
        self.assertTrue(_ocr_reliable(0.91))
        self.assertIsNone(_ocr_reliable("bad"))

    def test_evenly_spaced_range(self):
        frames = [{"pts_ms": i * 1000} for i in range(11)]
        picked = _evenly_spaced(frames, 3)
        self.assertEqual([f["pts_ms"] for f in picked], [0, 5000, 10000])
        self.assertEqual(_evenly_spaced(frames, 1)[0]["pts_ms"], 0)
        self.assertEqual(len(_evenly_spaced(frames, 20)), 11)

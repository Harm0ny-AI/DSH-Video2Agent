import unittest

from video2agent.pipeline import _dense_times, _validate_change_budget
from video2agent.util import Video2AgentError


class DenseWindowTests(unittest.TestCase):
    def test_window_covers_the_end_and_cap(self):
        times, warnings, end = _dense_times(0, 5000, 5, 12)
        self.assertEqual(times[0], 0)
        self.assertEqual(times[-1], 5000)
        self.assertEqual(end, 5000)
        self.assertLessEqual(len(times), 12)
        self.assertTrue(all(b > a for a, b in zip(times, times[1:])))
        self.assertIn("DENSE_REDISTRIBUTED", [w["code"] for w in warnings])

    def test_window_is_clamped_to_five_seconds(self):
        times, warnings, end = _dense_times(0, 20_000, 5, 12)
        self.assertEqual(times[-1], 5000)
        self.assertEqual(end, 5000)
        self.assertEqual(warnings[0]["code"], "DENSE_WINDOW_CLAMPED")

    def test_frame_cap_one_keeps_end(self):
        times, _, end = _dense_times(1000, 3000, 8, 1)
        self.assertEqual(times, [3000])
        self.assertEqual(end, 3000)

    def test_change_mode_requires_three_frames(self):
        for cap in (0, 1, 2):
            with self.assertRaises(Video2AgentError):
                _validate_change_budget("change", cap)
        _validate_change_budget("change", 3)
        _validate_change_budget("uniform", 1)

    def test_negative_window_is_rejected_by_api(self):
        with self.assertRaises(Video2AgentError):
            _dense_times(-2000, 2000, 5, 12)

    def test_hard_cap_is_fifteen_even_when_asked_for_more(self):
        times, _, end = _dense_times(0, 5000, 8, 30)
        self.assertEqual(end, 5000)
        self.assertLessEqual(len(times), 15)
        self.assertEqual(times[-1], 5000)

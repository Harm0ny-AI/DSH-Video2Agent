import unittest

from video2agent.links import av_to_bv, bv_to_av
from video2agent.util import Video2AgentError


class BvParsingTest(unittest.TestCase):
    def test_short_bv_returns_none_instead_of_index_error(self):
        self.assertIsNone(bv_to_av("BV123456"))
        self.assertIsNone(bv_to_av("BV1"))
        self.assertIsNone(bv_to_av(""))

    def test_real_bv_round_trips(self):
        bvid = av_to_bv(170001)
        self.assertEqual(bv_to_av(bvid), 170001)

    def test_absurd_av_rejected(self):
        with self.assertRaises(Video2AgentError):
            av_to_bv(1 << 60)
        with self.assertRaises(Video2AgentError):
            av_to_bv(-1)

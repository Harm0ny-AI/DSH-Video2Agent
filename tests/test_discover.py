import unittest

from video2agent.discover import _cover_url, _parse_duration


class DiscoverTests(unittest.TestCase):
    def test_duration(self):
        self.assertEqual(_parse_duration("17:03"), 1_023_000)
        self.assertEqual(_parse_duration("1:02:03"), 3_723_000)
        self.assertIsNone(_parse_duration(""))

    def test_cover_url(self):
        self.assertEqual(_cover_url("//i0.hdslb.com/a.jpg"), "https://i0.hdslb.com/a.jpg")
        self.assertEqual(_cover_url("https://x/a.jpg"), "https://x/a.jpg")

if __name__ == "__main__":
    unittest.main()

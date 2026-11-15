import unittest

from video2agent.pipeline import _literal_all


class LiteralMatchTest(unittest.TestCase):
    def test_decimal_and_percent_match(self):
        self.assertTrue(_literal_all("版本 3.5 的准确率 85%", ["3.5"]))
        self.assertTrue(_literal_all("版本 3.5 的准确率 85%", ["85%"]))

    def test_boundaries_still_hold(self):
        self.assertFalse(_literal_all("版本 3.55", ["3.5"]))
        self.assertTrue(_literal_all("使用 gpt-4o", ["gpt-4o"]))

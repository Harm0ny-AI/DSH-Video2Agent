import unittest

from video2agent.pipeline import _literal_all


class LiteralVersionTest(unittest.TestCase):
    def test_version_prefix_matches(self):
        self.assertTrue(_literal_all("v3.5 版本", ["3.5"]))

    def test_patch_version_does_not_match_minor(self):
        self.assertFalse(_literal_all("版本 3.5.1", ["3.5"]))

    def test_percent_still_matches(self):
        self.assertTrue(_literal_all("准确率 85%", ["85%"]))

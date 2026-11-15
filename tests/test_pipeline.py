import unittest

from video2agent.pipeline import _expand_query, _fuzzy_score, _wanted_visual


class SearchLogicTests(unittest.TestCase):
    def test_expand_visual_terms(self):
        q = _expand_query("表格 第三行")
        self.assertIn("表", q)

    def test_wanted_visual(self):
        self.assertIn("table_like", _wanted_visual("这张表格"))
        self.assertIn("animation", _wanted_visual("这段动画"))

    def test_fuzzy_typo(self):
        self.assertGreater(_fuzzy_score("注意力机治", "注意力机制"), 0.45)


if __name__ == "__main__":
    unittest.main()

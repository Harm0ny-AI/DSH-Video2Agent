import unittest

from video2agent.text import (
    chinese_to_int,
    coverage_score,
    format_timestamp,
    fts_match_query,
    leading_timecode,
    literal_terms,
    number_tokens,
    numeric_overlap,
    parse_subtitle_text,
    query_units,
    tokens_for_search,
)
from video2agent.util import format_timecode, parse_time_ms


class TextTests(unittest.TestCase):
    def test_parse_time(self):
        self.assertEqual(parse_time_ms("1:30"), 90_000)
        self.assertEqual(parse_time_ms("01:02:03.500"), 3_723_500)
        self.assertEqual(parse_time_ms("1m30s"), 90_000)
        self.assertEqual(parse_time_ms(2.5), 2500)

    def test_timecode(self):
        self.assertEqual(format_timecode(3_723_500), "01:02:03.500")
        self.assertEqual(format_timecode(3_723_500, millis=False), "01:02:03")

    def test_srt_keeps_cue_boundaries(self):
        text = """1
00:00:00,000 --> 00:00:02,000
第一句。

2
00:00:02,000 --> 00:00:04,000
第二句。
"""
        segs = parse_subtitle_text(text)
        self.assertEqual(len(segs), 2)
        self.assertEqual(segs[0]["start_ms"], 0)
        self.assertEqual(segs[1]["start_ms"], 2000)
        self.assertEqual(segs[1]["text"], "第二句。")

    def test_cjk_tokens(self):
        toks = tokens_for_search("注意力机制").split()
        self.assertIn("注意", toks)
        self.assertIn("机制", toks)
        q = fts_match_query("注意力机制")
        self.assertIn("OR", q)

    def test_timestamp(self):
        self.assertEqual(format_timestamp(65_000), "01:05.000")

    def test_chinese_numerals(self):
        self.assertEqual(chinese_to_int("三十五"), 35)
        self.assertEqual(chinese_to_int("八十五"), 85)
        self.assertEqual(chinese_to_int("一百二十"), 120)
        self.assertEqual(chinese_to_int("十"), 10)
        self.assertIsNone(chinese_to_int("注意力"))

    def test_decimal_comma_normalized(self):
        self.assertEqual(number_tokens("3.5"), ["3.5"])
        self.assertEqual(number_tokens("3,5"), ["3.5"])
        self.assertIn("3.5", tokens_for_search("公式 3,5 是缩放因子").split())

    def test_percent_cross_form(self):
        self.assertIn("pct85", number_tokens("准确率 85%"))
        self.assertIn("pct85", number_tokens("百分之八十五"))
        self.assertIn("pct85", tokens_for_search("百分之八十五").split())
        self.assertEqual(numeric_overlap("百分之八十五", "Transformer 的准确率是 85%"), 1.0)
        self.assertEqual(numeric_overlap("百分之八十五", "百分之三十五的样本"), 0.0)

    def test_plural_folding(self):
        self.assertIn("timestamp", tokens_for_search("timestamps").split())
        self.assertIn("model", tokens_for_search("models").split())
        self.assertIn("process", tokens_for_search("process").split())

    def test_traditional_folded_to_simplified(self):
        from video2agent.text import to_simplified
        self.assertEqual(to_simplified("還沒到底"), "还没到底")
        self.assertEqual(to_simplified("權重與點積，隨後矩陣"), "权重与点积，随后矩阵")
        self.assertIn("点积", tokens_for_search("點積").split())
        self.assertIn("矩阵", tokens_for_search("矩陣").split())

    def test_leading_timecode(self):
        self.assertEqual(leading_timecode("00:00:12 说了什么"), (12_000, "说了什么"))
        self.assertEqual(leading_timecode("1:30"), (90_000, ""))
        self.assertEqual(leading_timecode("00:06:12"), (372_000, ""))
        self.assertEqual(leading_timecode("第42段"), (None, "第42段"))

    def test_query_units_and_coverage(self):
        units = query_units("表格里 Transformer 的准确率是多少")
        self.assertIn("transformer", units)
        self.assertIn("准确率", units)
        good = "这张表是三种模型的准确率对比,Transformer 是 85%。"
        bad = "Transformer用注意力直接建模长距离依赖。"
        self.assertGreater(coverage_score(good, units), coverage_score(bad, units))
        self.assertEqual(coverage_score("TAG-63 · Q1", query_units("TAG-63")), 1.0)

    def test_non_latin_scripts_become_tokens(self):
        # Cyrillic/kana/Hangul/Arabic used to tokenise to nothing, so a Russian
        # video was unsearchable by its own words.
        for text, expected in (
            ("промокод скидка", "промокод"),
            ("おすすめ クーポン", "クーポン"),
            ("할인 쿠폰", "쿠폰"),
            ("خصم كوبون", "كوبون"),
        ):
            tokens = tokens_for_search(text).split()
            self.assertIn(expected, tokens, text)
            self.assertIn(expected, query_units(text), text)
            self.assertIn(expected, fts_match_query(text), text)
            self.assertIn(expected, literal_terms(text), text)

    def test_other_scripts_match_their_inflections(self):
        # Russian "промокод" vs "промокоду": the FTS query is a prefix query for
        # non-Latin scripts, so the inflected form is still reachable.
        self.assertIn('"промокод"*', fts_match_query("промокод"))
        self.assertNotIn('*', fts_match_query("attention"))
        self.assertNotIn('*', fts_match_query("注意力机制"))

    def test_latin_and_cjk_stay_unchanged_next_to_other_scripts(self):
        tokens = tokens_for_search("промокод 优惠码 discount").split()
        self.assertIn("промокод", tokens)
        self.assertIn("discount", tokens)
        self.assertIn("优惠", tokens)
        self.assertIn("优惠码", tokens)


if __name__ == "__main__":
    unittest.main()

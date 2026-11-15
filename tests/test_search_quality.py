import tempfile
import unittest
from pathlib import Path

from video2agent.config import load_config
from video2agent.db import Database
from video2agent.pipeline import (
    _coverage_units,
    _expand_terms,
    _has_keyword,
    _rerank,
    _wanted_visual,
    evidence,
    search,
)
from video2agent.text import tokens_for_search

VID = "vid_quality"
DURATION = 700_000

SEGMENTS = [
    (0, 10_000, "第0节开始，我们讲注意力机制的直觉。"),
    (10_000, 20_000, "这一页给出 Transformer 的准确率是 85%，比 RNN 高很多。"),
    (20_000, 30_000, "公式 3.5 是缩放因子，用来控制点积的大小。"),
    (30_000, 40_000, "数据质量决定结论，时间戳会影响证据定位。"),
    (70_000, 80_000, "百分之三十五的样本来自 LongVideoBench 子集。"),
]

OCR = [
    (1_000, 2_000, "考点:画面文字·表格·时间戳"),
    (4_000, 5_000, "TAG-04 · Q1"),
    (5_000, 6_000, "Q · K · V 三组向量"),
    (8_000, 9_000, "還沒到底，權重與點積，隨後矩陣"),
    (63_000, 64_000, "TAG-63 · Q1"),
]

VISUAL = [
    (0, 10_000, "slide_like", 0.7),
    (10_000, 20_000, "table_like", 0.6),
]


def _insert_analysis(db, vid):
    segs = [
        {"start_ms": start, "end_ms": end, "text": text, "source": "caption",
         "confidence": 1.0, "tokens": tokens_for_search(text)}
        for start, end, text in SEGMENTS
    ]
    db.insert_segments(vid, segs)
    tracks = [
        {"start_ms": start, "end_ms": end, "text": text, "confidence": 0.9,
         "tokens": tokens_for_search(text)}
        for start, end, text in OCR
    ]
    db.insert_ocr_tracks(vid, tracks)
    db.insert_visual_segments(vid, [
        {"start_ms": start, "end_ms": end, "label": label, "score": score, "signals": {}}
        for start, end, label, score in VISUAL
    ])


def _cost_library(texts, vid="vid_cost"):
    """A library about cost that never says 计费, only its aliases."""
    tmp = tempfile.TemporaryDirectory()
    cfg = load_config(Path(tmp.name))
    db = Database(cfg.db_path)
    try:
        db.upsert_video({
            "id": vid, "source_kind": "local", "source_uri": "cost.mp4",
            "source_path": "cost.mp4", "title": "cost", "duration_ms": 60_000,
            "status": "ready",
        })
        db.insert_segments(vid, [
            {"start_ms": i * 5000, "end_ms": i * 5000 + 4000, "text": text,
             "source": "caption", "confidence": 1.0, "tokens": tokens_for_search(text)}
            for i, text in enumerate(texts)
        ])
    finally:
        db.close()
    return tmp, cfg


class SearchQualityTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.tmp = tempfile.TemporaryDirectory()
        cls.cfg = load_config(Path(cls.tmp.name))
        db = Database(cls.cfg.db_path)
        try:
            db.upsert_video({
                "id": VID, "source_kind": "local", "source_uri": "qa.mp4",
                "source_path": "qa.mp4", "title": "qa", "duration_ms": DURATION,
                "status": "ready",
            })
            _insert_analysis(db, VID)
        finally:
            db.close()

    @classmethod
    def tearDownClass(cls):
        cls.tmp.cleanup()

    # -- empty results -------------------------------------------------
    def test_nonsense_query_returns_explicit_empty(self):
        # Regression: "zzzznotaslideword" used to match the visual keyword
        # "slide" inside the word and return a confident-looking visual hit.
        result = search(self.cfg, "zzzznotaslideword", video_id=VID)
        self.assertEqual(result["results"], [])
        self.assertTrue(result["empty"])
        self.assertIn("NO_MATCH", [w["code"] for w in result["warnings"]])

    def test_nonsense_query_without_visual_segments(self):
        with tempfile.TemporaryDirectory() as tmp:
            cfg = load_config(Path(tmp))
            db = Database(cfg.db_path)
            try:
                db.upsert_video({"id": "vid_plain", "source_kind": "local",
                                 "source_uri": "plain.mp4", "source_path": "plain.mp4",
                                 "title": "plain", "duration_ms": 6000, "status": "ready"})
                text = "这是一个测试视频,讲注意力机制。"
                db.insert_segments("vid_plain", [{
                    "start_ms": 0, "end_ms": 6000, "text": text,
                    "source": "caption", "confidence": 1.0,
                    "tokens": tokens_for_search(text),
                }])
            finally:
                db.close()
            result = search(cfg, "zzzznotaslideword", video_id="vid_plain")
            self.assertEqual(result["results"], [])
            self.assertTrue(result["empty"])

    def test_query_without_tokens_is_empty_query(self):
        result = search(self.cfg, "?!", video_id=VID)
        self.assertEqual(result["results"], [])
        self.assertTrue(result["empty"])
        self.assertIn("EMPTY_QUERY", [w["code"] for w in result["warnings"]])

    # -- visual gating --------------------------------------------------
    def test_visual_keyword_needs_word_boundary(self):
        self.assertFalse(_has_keyword("zzzznotaslideword", "slide"))
        self.assertEqual(_wanted_visual("zzzznotaslideword"), [])
        self.assertEqual(_wanted_visual("point me at the slide"), ["slide_like"])
        self.assertEqual(_wanted_visual("这张表格里有什么"), ["table_like"])
        self.assertTrue(_has_keyword("这张表格", "表格"))

    def test_visual_query_returns_honest_visual_hit(self):
        result = search(self.cfg, "table", video_id=VID)
        visual = [r for r in result["results"] if "visual" in (r.get("modalities") or [])]
        self.assertTrue(visual)
        self.assertNotIn("关键词", visual[0]["why"])
        self.assertIn("视觉结构匹配", visual[0]["why"])
        self.assertIn("table_like", visual[0]["visual_types"])

    # -- timestamp queries ---------------------------------------------
    def test_timestamp_query_returns_segment_at_that_time(self):
        result = search(self.cfg, "00:00:12 说了什么", video_id=VID)
        self.assertTrue(result["results"])
        top = result["results"][0]
        self.assertEqual(top["start_ms"], 10_000)
        self.assertIn("时间戳", top["why"])

    def test_timestamp_only_query(self):
        result = search(self.cfg, "00:00:35", video_id=VID)
        self.assertEqual(result["results"][0]["start_ms"], 30_000)
        self.assertEqual(result["results"][0]["score"], 0.99)

    def test_timestamp_beyond_duration_is_not_faked(self):
        result = search(self.cfg, "00:59:00 说了什么", video_id=VID)
        codes = [w["code"] for w in result["warnings"]]
        self.assertIn("TIMESTAMP_NOT_FOUND", codes)
        self.assertTrue(result["empty"])

    # -- numeric / phrase ----------------------------------------------
    def test_decimal_query_with_dot_and_comma(self):
        for query in ("3.5", "3,5"):
            result = search(self.cfg, query, video_id=VID)
            self.assertTrue(result["results"], query)
            self.assertEqual(result["results"][0]["start_ms"], 20_000, query)

    def test_percent_query_matches_chinese_numeral(self):
        for query in ("85%", "百分之八十五"):
            result = search(self.cfg, query, video_id=VID)
            self.assertTrue(result["results"], query)
            self.assertEqual(result["results"][0]["start_ms"], 10_000, query)
            self.assertIn("85", result["results"][0]["snippet"])

    def test_ocr_tag_query_ranks_exact_tag_first(self):
        result = search(self.cfg, "TAG-63", video_id=VID)
        self.assertEqual(result["results"][0]["start_ms"], 63_000)
        self.assertIn("TAG-63", result["results"][0]["snippet"])

    def test_plural_query_matches_singular(self):
        with tempfile.TemporaryDirectory() as tmp:
            cfg = load_config(Path(tmp))
            db = Database(cfg.db_path)
            text = "It should produce timestamps."
            try:
                db.upsert_video({"id": "vid_en", "source_kind": "local",
                                 "source_uri": "en.mp4", "source_path": "en.mp4",
                                 "title": "en", "duration_ms": 7000, "status": "ready"})
                db.insert_segments("vid_en", [{
                    "start_ms": 4000, "end_ms": 7000, "text": text,
                    "source": "asr", "confidence": 0.9,
                    "tokens": tokens_for_search(text),
                }])
            finally:
                db.close()
            result = search(cfg, "timestamp", video_id="vid_en")
            self.assertTrue(result["results"])
            self.assertEqual(result["results"][0]["start_ms"], 4000)

    # -- coverage reranking --------------------------------------------
    def test_rerank_prefers_more_query_units(self):
        from video2agent.text import query_units
        units = query_units("表格里 Transformer 的准确率是多少")
        good = "这张表是三种模型的准确率对比,Transformer 是 85%。"
        bad = "Transformer用注意力直接建模长距离依赖。"
        self.assertGreater(_rerank(0.4, good, query="表格里 Transformer 的准确率是多少", units=units),
                           _rerank(0.4, bad, query="表格里 Transformer 的准确率是多少", units=units))

    def test_english_query_finds_chinese_content(self):
        result = search(self.cfg, "attention mechanism", video_id=VID)
        self.assertTrue(result["results"])
        self.assertEqual(result["results"][0]["start_ms"], 0)

    def test_single_char_cjk_query_falls_back_to_literal(self):
        # FTS indexes bigrams/trigrams only, so "表" used to return nothing.
        result = search(self.cfg, "表", video_id=VID)
        self.assertTrue(result["results"])
        self.assertIn("表", result["results"][0]["snippet"])
        self.assertIn("LITERAL_FALLBACK", [w["code"] for w in result["warnings"]])

    def test_short_token_shorthand_query(self):
        # "Q K V" tokens are single letters and are dropped by the tokenizer;
        # the literal all-terms fallback must still find "Q · K · V".
        result = search(self.cfg, "Q K V", video_id=VID)
        self.assertTrue(result["results"])
        self.assertEqual(result["results"][0]["start_ms"], 5000)

    def test_traditional_and_simplified_find_each_other(self):
        for query in ("点积", "點積"):
            result = search(self.cfg, query, video_id=VID)
            self.assertTrue(result["results"], query)
            snippets = " ".join(r["snippet"] for r in result["results"])
            self.assertIn("点积", snippets, query)
            self.assertIn(result["results"][0]["start_ms"], (8000, 20000), query)

    # -- synonyms -------------------------------------------------------
    def test_a_synonym_query_finds_alias_only_hits(self):
        # 计费 never appears in the transcript; only the curated aliases do. The
        # coverage guard used to tokenise the expanded query as one CJK run
        # ("计费价", "费价格"), so every real cost line was deleted and 计费
        # returned 0 results (live library: 17 FTS hits, 0 returned).
        tmp, cfg = _cost_library(["这是混元四的价格", "比如处理账单数据", "迁移成本几乎为零"])
        self.addCleanup(tmp.cleanup)
        result = search(cfg, "计费")
        self.assertFalse(result["empty"])
        self.assertEqual(len(result["results"]), 3)
        for hit in result["results"]:
            self.assertNotIn("关键词", hit["why"])
            self.assertIn("同义词", hit["why"])
            self.assertTrue(hit["matched_terms"])
            self.assertIn(hit["matched_terms"][0], hit["snippet"])

    def test_an_alias_hit_names_the_term_that_matched(self):
        # Before: "transcript 命中；关键词「价格」" on a line that never says 价格.
        tmp, cfg = _cost_library(["一共花了多少钱"])
        self.addCleanup(tmp.cleanup)
        top = search(cfg, "价格")["results"][0]
        self.assertEqual(top["matched_terms"], ["多少钱"])
        self.assertIn("同义词「多少钱」", top["why"])
        self.assertNotIn("关键词", top["why"])

    def test_a_keyword_hit_still_names_the_keyword(self):
        tmp, cfg = _cost_library(["这是混元四的价格"])
        self.addCleanup(tmp.cleanup)
        top = search(cfg, "价格")["results"][0]
        self.assertIn("关键词「价格」", top["why"])
        self.assertNotIn("同义词", top["why"])

    def test_a_literal_hit_outranks_a_synonym_only_hit(self):
        # Synonym recall must not flatten the ranking: the line that says the
        # query wins, the alias-only line comes back behind it with a real score,
        # and both are labelled by the term that matched. A filler line keeps the
        # FTS IDF positive; in a two-line library BM25 is ~0 and every rank-based
        # score collapses, which would make the gap an artefact.
        tmp, cfg = _cost_library(["这是混元四的价格", "迁移成本几乎为零", "今天天气不错"])
        self.addCleanup(tmp.cleanup)
        results = search(cfg, "价格", limit=8)["results"]
        literal = next(r for r in results if "价格" in r["snippet"])
        alias = next(r for r in results if "成本" in r["snippet"])
        self.assertEqual(results[0]["snippet"], literal["snippet"])
        self.assertGreater(literal["score"], alias["score"])
        self.assertGreaterEqual(literal["score"] - alias["score"], 0.05)
        self.assertGreater(alias["score"], 0.0)
        self.assertIn("关键词「价格」", literal["why"])
        self.assertIn("同义词「成本」", alias["why"])
        self.assertEqual(alias["matched_terms"], ["成本"])

    def test_a_synonym_hit_is_not_scored_zero_in_a_tiny_library(self):
        # Two lines mean FTS5 IDF is 0, so BM25 is ~0 and a synonym-only hit used
        # to come back at 0.0 — "no match" on a row that was returned.
        tmp, cfg = _cost_library(["迁移成本几乎为零", "今天天气不错"])
        self.addCleanup(tmp.cleanup)
        hit = search(cfg, "计费")["results"][0]
        self.assertEqual(hit["matched_terms"], ["成本"])
        # Alias hits now count the alias' own units instead of the 0.05 floor.
        self.assertAlmostEqual(hit["score"], 0.175, places=4)
        self.assertLess(hit["score"], 0.2, "must stay below the fuzzy fallback")
        self.assertIn("同义词「成本」", hit["why"])

    def test_an_alias_only_video_row_does_not_outrank_a_moment(self):
        # A description that says 价格 puts a whole-video row into a 计费 result
        # at 0.32 — above every real moment at 0.3193 on the live library. A row
        # that lacks the typed query is discovery, so it goes below the moments.
        with tempfile.TemporaryDirectory() as tmp:
            cfg = load_config(Path(tmp))
            db = Database(cfg.db_path)
            try:
                db.upsert_video({
                    "id": "vid_meta", "source_kind": "local", "source_uri": "m.mp4",
                    "source_path": "m.mp4", "title": "价格与成本",
                    "duration_ms": 60_000, "status": "ready",
                    "meta_json": '{"description": "本期讨论价格"}',
                })
                text = "迁移成本几乎为零"
                db.insert_segments("vid_meta", [{
                    "start_ms": 5000, "end_ms": 9000, "text": text,
                    "source": "caption", "confidence": 1.0,
                    "tokens": tokens_for_search(text),
                }])
            finally:
                db.close()
            result = search(cfg, "计费")
            self.assertTrue(result["results"])
            self.assertNotEqual(result["results"][0]["source"], "video_meta",
                                "a row without the typed query must not lead")
            meta = next(r for r in result["results"] if r["source"] == "video_meta")
            self.assertIn("价格", meta["matched_terms"])
            self.assertNotIn("计费", meta["matched_terms"])
            self.assertIn("标题/简介匹配", meta["why"])
            self.assertIn("同义词「价格」", meta["why"])

    def test_a_video_row_names_the_keyword_when_it_contains_the_query(self):
        with tempfile.TemporaryDirectory() as tmp:
            cfg = load_config(Path(tmp))
            db = Database(cfg.db_path)
            try:
                db.upsert_video({
                    "id": "vid_meta", "source_kind": "local", "source_uri": "m.mp4",
                    "source_path": "m.mp4", "title": "价格与成本",
                    "duration_ms": 60_000, "status": "ready",
                })
            finally:
                db.close()
            top = search(cfg, "价格")["results"][0]
            self.assertEqual(top["source"], "video_meta")
            self.assertIn("关键词「价格」", top["why"])

    def test_coverage_units_do_not_span_synonym_words(self):
        units = _coverage_units("计费", _expand_terms("计费"))
        self.assertIn("计费", units)
        self.assertIn("价格", units)
        self.assertIn("账单", units)
        self.assertNotIn("计费价", units, "cross-word trigrams match no transcript")
        self.assertNotIn("费价格", units)

    def test_a_query_whose_units_appear_nowhere_is_still_a_miss(self):
        # The guard's original job: 量子纠缠 shares 量子 with 量子力学 lines, which
        # is not a match. This had no test before the synonym fix widened coverage.
        tmp, cfg = _cost_library(["量子力学的基本假设", "贝尔不等式讨论的是量子力学"],
                                 vid="vid_quantum")
        self.addCleanup(tmp.cleanup)
        result = search(cfg, "量子纠缠")
        self.assertEqual(result["results"], [])
        self.assertTrue(result["empty"])
        self.assertIn("NO_MATCH", [w["code"] for w in result["warnings"]])

    def test_non_latin_transcript_is_searchable(self):
        # A Russian video used to index zero tokens: the transcript was there but
        # "промокод" returned EMPTY_QUERY because the tokenizer only kept
        # Latin/CJK. The transcript is now tokenised by script.
        tmp, cfg = _cost_library(["промокод на скидку в этом видео",
                                  "сегодня хорошая погода"], vid="vid_ru")
        self.addCleanup(tmp.cleanup)
        for query in ("промокод", "скидку"):
            result = search(cfg, query)
            self.assertTrue(result["results"], query)
            self.assertIn("промокод", result["results"][0]["snippet"].lower())
            self.assertEqual(result["results"][0]["start_ms"], 0, query)
        self.assertTrue(search(cfg, "абракадабра")["empty"],
                        "a nonsense Cyrillic word is still a miss")

    # -- evidence window -----------------------------------------------
    def test_evidence_window_contains_hit(self):
        result = search(self.cfg, "85%", video_id=VID)
        hit = result["results"][0]
        bundle = evidence(self.cfg, video_id=VID, at_ms=hit["start_ms"], image_budget=0)
        rng = bundle["range"]
        self.assertLessEqual(rng["start_ms"], hit["start_ms"])
        self.assertGreaterEqual(rng["end_ms"], hit["start_ms"])
        self.assertTrue(any("85" in s["text"] for s in bundle["transcript"]))


if __name__ == "__main__":
    unittest.main()

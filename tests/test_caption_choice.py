"""Which track wins when a short human track competes with a longer AI transcript?"""
import tempfile
import unittest
from pathlib import Path
from unittest.mock import MagicMock, patch

from video2agent import captions
from video2agent.config import load_config

TRACKS = [
    {"lan": "zh-Hans", "lan_doc": "中文（人工）", "ai": False, "kind": "human", "url": "human.json"},
    {"lan": "ai-zh", "lan_doc": "中文（AI）", "ai": True, "kind": "ai", "url": "ai.json"},
    {"lan": "ai-en", "lan_doc": "English", "ai": True, "kind": "ai", "url": "en.json"},
]


def _segments(n: int, prefix: str = "句") -> list[dict]:
    return [{"start_ms": i * 1000, "end_ms": i * 1000 + 900, "text": f"{prefix}{i}", "source": "caption"}
            for i in range(n)]


def _text_segments(n: int, text: str) -> list[dict]:
    return [{"start_ms": i * 1000, "end_ms": i * 1000 + 900, "text": text, "source": "caption"}
            for i in range(n)]


class TrackChoiceTests(unittest.TestCase):
    def _run(self, payloads, tracks=None, duration_ms=None, title=None, description=None, tags=None):
        def fake_fetch(track, session):
            return payloads.get(track["url"], [])

        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        cfg = load_config(Path(tmp.name))
        with patch.object(captions, "_session", return_value=(MagicMock(), True)), \
                patch.object(captions, "video_cid", return_value=1), \
                patch.object(captions, "subtitle_tracks", return_value=tracks or TRACKS), \
                patch.object(captions, "fetch_track", side_effect=fake_fetch), \
                patch.object(captions.time, "sleep", return_value=None):
            return captions.bilibili_captions(
                "BV1xx411c7mD", cfg,
                duration_ms=duration_ms,
                title=title, description=description, tags=tags,
            )

    def test_a_human_stub_loses_to_a_full_ai_transcript(self):
        # The real incident: zh-Hans had 1 segment, ai-zh had 141.
        result = self._run({"human.json": _segments(1), "ai.json": _segments(141)})
        self.assertEqual(result["reason"], "ok")
        self.assertEqual(result["track"]["lan"], "ai-zh")
        self.assertGreater(len(result["segments"]), 100)

    def test_a_short_but_real_human_track_loses_too(self):
        # The reviewer's case: a partial human track with 21+ segments must not win
        # merely because it arrives first.
        result = self._run({"human.json": _segments(21), "ai.json": _segments(141)})
        self.assertEqual(result["track"]["lan"], "ai-zh")

    def test_a_comparable_human_track_wins(self):
        result = self._run({"human.json": _segments(140), "ai.json": _segments(141)})
        self.assertEqual(result["track"]["lan"], "zh-Hans", "rank still breaks a close call")

    def test_a_larger_human_track_keeps_ai_fallback(self):
        result = self._run({"human.json": _segments(300), "ai.json": _segments(141)})
        self.assertEqual(result["track"]["lan"], "zh-Hans")
        self.assertEqual(result["ai_fallback"]["track"]["lan"], "ai-zh")
        self.assertEqual(len(result["ai_fallback"]["segments"]), 141)

    def test_same_duration_unrelated_caption_is_rejected(self):
        # The 26-minute attention lecture carried iPhone-lens captions; timing
        # looked valid, so title/topic units must catch it.
        result = self._run(
            {"human.json": _text_segments(80, "手机镜头膜到底有没有必要贴")},
            duration_ms=200_000,
            title="直观解释注意力机制 Transformer 深度学习",
        )
        self.assertEqual(result["reason"], "mismatch")
        self.assertEqual(result["segments"], [])

    def test_title_first_ignores_generic_description(self):
        result = self._run(
            {"human.json": _text_segments(80, "手机镜头膜到底有没有必要贴")},
            duration_ms=200_000,
            title="直观解释注意力机制 Transformer 深度学习",
            description="视频内容分享，欢迎讨论",
            tags=["视频", "内容", "分享"],
        )
        self.assertEqual(result["reason"], "mismatch")
        self.assertEqual(result["segments"], [])

    def test_stored_caption_is_detected_without_reingest(self):
        from video2agent.pipeline import _stored_caption_mismatch

        class FakeDB:
            def get_segments(self, video_id, limit=120):
                return _text_segments(80, "手机镜头膜到底有没有必要贴")

        video = {
            "id": "vid_bad",
            "title": "直观解释注意力机制 Transformer 深度学习",
            "meta": {"analysis_metrics": {"transcript_source": "caption"}},
        }
        self.assertTrue(_stored_caption_mismatch(FakeDB(), video))

    def test_a_wbi_track_is_trusted_for_identity(self):
        # A signed WBI track is authoritative even when its words share nothing with
        # the title: clickbait titles and AI translation tracks (ai-en/ai-ja) never
        # repeat the spoken text, and re-ingest returns the same track.
        from video2agent.pipeline import _stored_caption_mismatch

        class FakeDB:
            def get_segments(self, video_id, limit=120):
                return _text_segments(80, "手机镜头膜到底有没有必要贴")

        video = {
            "id": "vid_wbi",
            "title": "直观解释注意力机制 Transformer 深度学习",
            "meta": {"analysis_metrics": {
                "transcript_source": "caption",
                "caption_track": {"endpoint": "wbi", "lan": "ai-zh"},
            }},
        }
        self.assertFalse(_stored_caption_mismatch(FakeDB(), video))

    def test_stored_asr_is_not_rechecked_as_caption(self):
        from video2agent.pipeline import _stored_caption_mismatch

        class FakeDB:
            def get_segments(self, video_id, limit=120):
                return _text_segments(80, "手机镜头膜到底有没有必要贴")

        video = {
            "id": "vid_asr",
            "title": "直观解释注意力机制 Transformer 深度学习",
            "meta": {"analysis_metrics": {"transcript_source": "asr"}},
        }
        self.assertFalse(_stored_caption_mismatch(FakeDB(), video))

    def test_same_duration_related_caption_is_kept(self):
        result = self._run(
            {"human.json": _text_segments(80, "注意力机制 Transformer 深度学习")},
            duration_ms=200_000,
            title="直观解释注意力机制 Transformer 深度学习",
        )
        self.assertEqual(result["reason"], "ok")
        self.assertEqual(len(result["segments"]), 80)

    def test_a_wrong_long_track_does_not_beat_a_valid_shorter_one(self):
        # Real incident: a 46s video exposed a 772-line track ending at 800s.
        # A shorter but duration-valid human track must win instead of ASR.
        result = self._run(
            {"human.json": _segments(140), "ai.json": _segments(500)},
            duration_ms=200_000,
        )
        self.assertEqual(result["reason"], "ok")
        self.assertEqual(result["track"]["lan"], "zh-Hans")
        self.assertEqual(len(result["segments"]), 140)

    def test_all_mismatched_tracks_are_reported_without_using_them(self):
        result = self._run(
            {"human.json": _segments(500), "ai.json": _segments(700)},
            duration_ms=200_000,
        )
        self.assertEqual(result["reason"], "mismatch")
        self.assertEqual(result["segments"], [])

    def test_all_advertised_tracks_are_considered(self):
        calls = []

        def fake_fetch(track, session):
            calls.append(track["url"])
            return _segments(5)

        many = [{"lan": "ja", "lan_doc": "日本語", "ai": False, "kind": "human", "url": f"ja{i}.json"} for i in range(5)]
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        cfg = load_config(Path(tmp.name))
        with patch.object(captions, "_session", return_value=(MagicMock(), True)), \
                patch.object(captions, "video_cid", return_value=1), \
                patch.object(captions, "subtitle_tracks", return_value=many), \
                patch.object(captions, "fetch_track", side_effect=fake_fetch):
            captions.bilibili_captions("BV1xx411c7mD", cfg)
        self.assertEqual(len(calls), 5, "the old three-track cap must not hide a fifth track")
        self.assertEqual(sorted(calls), [f"ja{i}.json" for i in range(5)])

    def test_a_valid_fifth_track_is_not_hidden(self):
        many = [{"lan": "ja", "lan_doc": "日本語", "ai": False, "kind": "human", "url": f"ja{i}.json"} for i in range(5)]
        result = self._run(
            {f"ja{i}.json": ([] if i < 4 else _segments(140)) for i in range(5)},
            tracks=many,
            duration_ms=200_000,
        )
        self.assertEqual(result["reason"], "ok")
        self.assertEqual(len(result["segments"]), 140)

    def test_a_broken_candidate_does_not_discard_a_good_one(self):
        # Comparing three candidates must not make subtitle discovery more fragile
        # than the old single-track fetch: a rate-limited later track used to raise
        # and fall back to ASR even though the first track was complete.
        def fake_fetch(track, session):
            if track["lan"] == "ai-zh":
                raise RuntimeError("rate limited")
            return _segments(140)

        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        cfg = load_config(Path(tmp.name))
        with patch.object(captions, "_session", return_value=(MagicMock(), True)), \
                patch.object(captions, "video_cid", return_value=1), \
                patch.object(captions, "subtitle_tracks", return_value=TRACKS), \
                patch.object(captions, "fetch_track", side_effect=fake_fetch):
            result = captions.bilibili_captions("BV1xx411c7mD", cfg)
        self.assertEqual(result["reason"], "ok")
        self.assertEqual(result["track"]["lan"], "zh-Hans")
        self.assertGreater(len(result["segments"]), 100)


if __name__ == "__main__":
    unittest.main()

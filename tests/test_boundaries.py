import io
import json
import tempfile
import unittest
from contextlib import redirect_stdout
from pathlib import Path

from video2agent import cli
from video2agent.config import load_config
from video2agent.db import Database
from video2agent.pipeline import _clip, _require_in_range, evidence, overview, search, visual_map
from video2agent.util import Video2AgentError

VID = "vid_boundary"
MEDIA_MS = 10_000
DECLARED_S = 60.0


class ClipTests(unittest.TestCase):
    """Snippets must show the match instead of 500 characters of noise."""

    def test_short_text_is_unchanged(self):
        self.assertEqual(_clip("  一句话  ", "一句话"), "一句话")

    def test_match_at_the_end_is_still_visible(self):
        out = _clip("噪" * 200 + "高效注意力", "高效注意力")
        self.assertIn("高效注意力", out)
        self.assertLessEqual(len(out), 60, "a tail match must produce a short snippet")

    def test_middle_match_sits_near_the_front(self):
        out = _clip("一" * 120 + "高效注意力" + "二" * 120, "高效注意力")
        self.assertLessEqual(out.index("高效注意力"), 40)
        self.assertLessEqual(len(out), 165)

    def test_missing_needle_falls_back_to_the_head(self):
        out = _clip("x" * 300, "不存在的词")
        self.assertTrue(out.endswith("…"))
        self.assertLessEqual(len(out), 161)

    def test_long_text_without_needle_is_windowed(self):
        out = _clip("y" * 300)
        self.assertLessEqual(len(out), 161)


class BoundaryTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.tmp = tempfile.TemporaryDirectory()
        cls.cfg = load_config(Path(cls.tmp.name))
        db = Database(cls.cfg.db_path)
        try:
            db.upsert_video({
                "id": VID, "source_kind": "url", "source_uri": "https://example.com/v",
                "source_path": str(Path(cls.tmp.name) / "missing.mp4"), "title": "truncated",
                "duration_ms": MEDIA_MS, "status": "ready",
                "meta_json": '{"duration": %s, "is_upower_exclusive": true}' % DECLARED_S,
            })
        finally:
            db.close()

    @classmethod
    def tearDownClass(cls):
        cls.tmp.cleanup()

    def test_overview_declares_the_platform_duration(self):
        data = overview(self.cfg, VID)
        self.assertEqual(data["declared_duration_ms"], 60_000)
        self.assertEqual(data["declared_duration"], "1m00s")
        self.assertTrue(data["exclusive"])
        codes = [w["code"] for w in data["warnings"]]
        self.assertIn("MEDIA_TRUNCATED", codes, "a truncated download must not look normal")

    def test_require_in_range_allows_a_request_inside(self):
        video = {"duration_ms": MEDIA_MS}
        self.assertEqual(_require_in_range(video, at_ms=9_000), MEDIA_MS)

    def test_evidence_past_the_end_is_an_error(self):
        with self.assertRaises(Video2AgentError) as ctx:
            evidence(self.cfg, video_id=VID, at_ms=20_000, image_budget=0)
        self.assertEqual(ctx.exception.code, "E_OUT_OF_RANGE")
        self.assertIn("00:00:10", ctx.exception.message + ctx.exception.remedy)

    def test_evidence_at_the_exact_end_is_rejected(self):
        # 10.0s is not addressable: the last frame starts at 9.96s.
        with self.assertRaises(Video2AgentError) as ctx:
            evidence(self.cfg, video_id=VID, at_ms=MEDIA_MS, image_budget=0)
        self.assertEqual(ctx.exception.code, "E_OUT_OF_RANGE")

    def test_evidence_inside_reports_request_and_media_end(self):
        data = evidence(self.cfg, video_id=VID, at_ms=8_000, image_budget=0)
        self.assertTrue(data["ok"])
        self.assertEqual(data["requested_ms"], 8_000)
        self.assertEqual(data["media_end_ms"], MEDIA_MS)
        self.assertIn("snapped", data)

    def test_an_end_past_the_media_is_rejected(self):
        with self.assertRaises(Video2AgentError) as ctx:
            evidence(self.cfg, video_id=VID, start_ms=0, end_ms=99_000, image_budget=0)
        self.assertEqual(ctx.exception.code, "E_OUT_OF_RANGE")
        self.assertIn("结尾", ctx.exception.message)

    def test_a_millisecond_value_names_the_unit_slip(self):
        # Real log 2026-11-14: read with start=548000 answered "152 小时" and the
        # model retried blindly. The remedy must name the likely unit mistake.
        # "548000" read as seconds = 152 hours; the same number as milliseconds is
        # 9:08, inside a 57-minute video. The remedy must say so.
        with self.assertRaises(Video2AgentError) as ctx:
            _require_in_range({"duration_ms": 3_420_000}, start_ms=548_000_000)
        self.assertIn("毫秒当成了秒", ctx.exception.remedy)
        self.assertIn("548", ctx.exception.remedy)

    def test_an_empty_range_is_rejected_instead_of_inverting(self):
        with self.assertRaises(Video2AgentError) as ctx:
            evidence(self.cfg, video_id=VID, start_ms=8_000, end_ms=2_000, image_budget=0)
        self.assertEqual(ctx.exception.code, "E_OUT_OF_RANGE")
        self.assertIn("为空", ctx.exception.message)

    def test_frames_near_the_end_clamp_and_do_not_duplicate(self):
        from unittest.mock import patch

        from video2agent import pipeline

        # `frames()` now refuses before extraction when the source file is gone.
        (Path(self.tmp.name) / "media.mp4").write_bytes(b"stub")
        with Database(self.cfg.db_path) as db:
            db.update_video(VID, source_path=str(Path(self.tmp.name) / "media.mp4"))
        seen: list[int] = []

        def fake_extract(_src, t, _out, **_kwargs):
            seen.append(int(t))

        # 9.5s of a 10s video with --count 8: no request may pass the media end and
        # the same moment must not be extracted twice.
        with patch.object(pipeline, "extract_frame", side_effect=fake_extract):
            data = pipeline.frames(self.cfg, VID, at_ms=9_500, count=8)
        self.assertTrue(data["ok"])
        self.assertTrue(seen, "at least one frame should be attempted")
        self.assertLess(max(seen), MEDIA_MS, "no frame may be requested past the end")
        self.assertEqual(len(seen), len(set(seen)), "frames must not be duplicated")

    def test_a_frame_failure_is_reported_not_swallowed(self):
        from unittest.mock import patch

        from video2agent import pipeline

        (Path(self.tmp.name) / "media.mp4").write_bytes(b"stub")
        with Database(self.cfg.db_path) as db:
            db.update_video(VID, source_path=str(Path(self.tmp.name) / "media.mp4"))
        with patch.object(pipeline, "extract_frame", side_effect=RuntimeError("boom")):
            data = pipeline.frames(self.cfg, VID, at_ms=1_000, count=1)
        self.assertFalse(data["ok"])
        self.assertEqual(data["error"]["code"], "E_FRAME")
        self.assertTrue(data["error"]["remedy"])

    def test_missing_media_is_named_not_blamed_on_the_time(self):
        from video2agent import pipeline
        from video2agent.util import Video2AgentError

        with Database(self.cfg.db_path) as db:
            db.update_video(VID, source_path=str(Path(self.tmp.name) / "gone.mp4"))
        with self.assertRaises(Video2AgentError) as caught:
            pipeline.frames(self.cfg, VID, at_ms=1_000, count=1)
        self.assertEqual(caught.exception.code, "E_MEDIA_MISSING")
        self.assertIn("ingest", caught.exception.remedy)

    def test_an_unread_moment_is_ocred_on_demand_and_remembered(self):
        # Lazy ingest means nothing was OCR'd up front. Asking for a moment must read
        # that frame then, return its text, and keep the read as an anchor so a second
        # question about the same moment is free.
        from unittest.mock import patch

        from video2agent import pipeline

        calls: list[str] = []

        def fake_extract(_src, t, out, **_kwargs):
            Path(out).parent.mkdir(parents=True, exist_ok=True)
            Path(out).write_bytes(b"\xff\xd8\xff\xd9")
            calls.append(str(t))

        boxes = [
            {"text": "注意力分数矩阵", "confidence": 0.93, "bbox": [10, 10, 200, 40]},
            {"text": "Q K V", "confidence": 0.90, "bbox": [10, 60, 120, 90]},
            {"text": "softmax", "confidence": 0.88, "bbox": [10, 110, 160, 140]},
        ]
        with patch.object(pipeline, "extract_frame", side_effect=fake_extract), \
                patch.object(pipeline, "ocr_available", return_value=True), \
                patch.object(pipeline, "ocr_image", return_value=boxes) as read:
            data = pipeline.evidence(self.cfg, video_id=VID, at_ms=4_000, image_budget=1)
        self.assertTrue(data["ok"])
        self.assertEqual(read.call_count, 1, "the requested frame must be read exactly once")
        self.assertIn("OCR_ON_DEMAND", [w["code"] for w in data.get("warnings") or []])
        self.assertTrue(data.get("ocr"), "the on-demand text must be part of the answer")
        self.assertIn("注意力分数矩阵", " ".join(o.get("text", "") for o in data["ocr"]))
        with Database(self.cfg.db_path) as db:
            self.assertIn(4_000, db.get_ocr_anchors(VID), "the read must be remembered")
        # Second time: the stored anchor answers, no second OCR run.
        with patch.object(pipeline, "ocr_available", return_value=True), \
                patch.object(pipeline, "ocr_image") as read2:
            again = pipeline.evidence(self.cfg, video_id=VID, at_ms=4_000, image_budget=0)
        self.assertEqual(read2.call_count, 0, "a remembered moment must not be OCR\'d twice")
        self.assertTrue(again.get("ocr"))


class ReadinessTests(unittest.TestCase):
    """A missing or unfinished video is an error, not an empty answer."""

    @classmethod
    def setUpClass(cls):
        cls.tmp = tempfile.TemporaryDirectory()
        cls.cfg = load_config(Path(cls.tmp.name) / "home")
        db = Database(cls.cfg.db_path)
        try:
            for vid, status in (("vid_ready", "ready"), ("vid_busy", "analyzing")):
                db.upsert_video({
                    "id": vid, "source_kind": "local", "source_uri": "clip.mp4",
                    "source_path": "clip.mp4", "title": vid,
                    "duration_ms": MEDIA_MS, "status": status,
                })
        finally:
            db.close()

    @classmethod
    def tearDownClass(cls):
        cls.tmp.cleanup()

    def test_search_unknown_video_is_not_found(self):
        with self.assertRaises(Video2AgentError) as ctx:
            search(self.cfg, "x", video_id="vid_nope")
        self.assertEqual(ctx.exception.code, "E_NOT_FOUND")

    def test_search_unfinished_video_is_not_ready(self):
        with self.assertRaises(Video2AgentError) as ctx:
            search(self.cfg, "x", video_id="vid_busy")
        self.assertEqual(ctx.exception.code, "E_NOT_READY")

    def test_map_unknown_video_is_not_found(self):
        with self.assertRaises(Video2AgentError) as ctx:
            visual_map(self.cfg, "vid_nope")
        self.assertEqual(ctx.exception.code, "E_NOT_FOUND")

    def test_map_unfinished_video_is_not_ready(self):
        with self.assertRaises(Video2AgentError) as ctx:
            visual_map(self.cfg, "vid_busy")
        self.assertEqual(ctx.exception.code, "E_NOT_READY")

    def test_cli_transcript_keeps_the_error_code(self):
        buf = io.StringIO()
        with redirect_stdout(buf):
            code = cli.main(["transcript", "vid_nope", "--json", "--home", str(self.cfg.home)])
        self.assertEqual(code, 1)
        payload = json.loads(buf.getvalue())
        self.assertFalse(payload["ok"])
        self.assertEqual(payload["error"]["code"], "E_NOT_FOUND")

    def test_cli_transcript_unfinished_is_not_ready(self):
        buf = io.StringIO()
        with redirect_stdout(buf):
            code = cli.main(["transcript", "vid_busy", "--json", "--home", str(self.cfg.home)])
        self.assertEqual(code, 1)
        payload = json.loads(buf.getvalue())
        self.assertEqual(payload["error"]["code"], "E_NOT_READY")


if __name__ == "__main__":
    unittest.main()

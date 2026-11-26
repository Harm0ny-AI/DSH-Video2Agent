"""A failed OCR read, an unread frame and an empty frame must not look the same.

These tests lock the three-state contract: unknown/unread, read-but-empty, and
failed. They also cover the two "empty success" traps around them: searching a
library with no videos, and an ingest whose transcript never ran.
"""
import importlib.util
import io
import json
import os
import tempfile
import threading
import time
import unittest
from contextlib import redirect_stdout
from pathlib import Path
from unittest.mock import patch

from video2agent import cli, pipeline
from video2agent.config import doctor, load_config
from video2agent.db import Database
from video2agent.text import tokens_for_search
from video2agent.util import Video2AgentError
from video2agent.visual import (
    OcrFailed,
    _aggregate,
    attach_ocr,
    ocr_state,
    ocr_summary,
    select_ocr_frames,
    visual_segments,
)


def _frames(*statuses):
    out = []
    for i, status in enumerate(statuses):
        out.append({
            "pts_ms": i * 1000,
            "path": f"frame_{i}.jpg",
            "line_score": 0.4,
            "edge_density": 0.2,
            "sharpness": 0.8,
            "motion": 0.0,
            "ocr_status": status,
            "text_coverage": 0.12 if status == "ok" else None,
        })
    return out


class OcrReadStateTests(unittest.TestCase):
    def test_failed_read_is_marked_failed_not_empty(self):
        def boom(_path):
            raise OcrFailed("engine crashed")

        frames = _frames("pending", "pending")
        attach_ocr(frames, max_frames=2, ocr_fn=boom)
        for frame in frames:
            self.assertEqual(frame["ocr_status"], "failed")
            self.assertIsNone(frame["text_coverage"], "a failed read must not claim 0 text")
            self.assertIn("engine crashed", frame["ocr_error"])
            self.assertEqual(frame["ocr"], [])

    def test_unexpected_exception_is_also_a_failed_read(self):
        def boom(_path):
            raise RuntimeError("decoder exploded")

        frames = _frames("pending")
        attach_ocr(frames, max_frames=1, ocr_fn=boom)
        self.assertEqual(frames[0]["ocr_status"], "failed")
        self.assertIsNone(frames[0]["text_coverage"])

    def test_empty_read_is_still_empty(self):
        frames = _frames("pending")
        attach_ocr(frames, max_frames=1, ocr_fn=lambda _p: [])
        self.assertEqual(frames[0]["ocr_status"], "empty")
        self.assertEqual(frames[0]["text_coverage"], 0.0, "a real empty read is a measured zero")

    def test_unavailable_ocr_never_writes_zero(self):
        frames = _frames("pending")
        with patch("video2agent.visual.ocr_available", return_value=False):
            attach_ocr(frames)
        self.assertEqual(frames[0]["ocr_status"], "unavailable")
        self.assertIsNone(frames[0]["text_coverage"])

    def test_failed_frames_do_not_produce_a_label(self):
        frames = _frames("failed", "failed")
        sig = _aggregate(frames)
        self.assertIsNone(sig["text_coverage"], "failed frames are not a measured zero")
        scenes = [{"start_ms": 0, "end_ms": 3000, "keyframe_ms": 0}]
        segments = visual_segments(scenes, frames)
        self.assertEqual(segments[0]["label"], "unknown")
        self.assertEqual(segments[0]["reason"], "text_unmeasured")

    def test_summary_and_state_words(self):
        self.assertEqual(ocr_state(ocr_summary(_frames("ok", "empty")), on_demand=False), "indexed")
        self.assertEqual(ocr_state(ocr_summary(_frames("failed")), on_demand=False), "failed")
        self.assertEqual(ocr_state(ocr_summary(_frames("ok", "failed")), on_demand=False), "partial")
        self.assertEqual(ocr_state(ocr_summary(_frames("pending")), on_demand=True), "on_demand")
        self.assertEqual(ocr_state(ocr_summary(_frames("unavailable")), on_demand=False), "unavailable")
        summary = ocr_summary(_frames("ok", "failed", "pending"))
        self.assertEqual((summary["read"], summary["failed"], summary["unmeasured"]), (1, 1, 1))


class _HomeCase(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.home = Path(self._tmp.name) / "home"
        self.cfg = load_config(self.home)
        self.addCleanup(self._tmp.cleanup)

    def add_video(self, vid="vid_ocr", *, metrics=None, frames=(), tracks=(), segments=(), anchors=(),
                  title="clip", duration_ms=10_000):
        db = Database(self.cfg.db_path)
        try:
            db.upsert_video({
                "id": vid,
                "source_kind": "local",
                "source_uri": "clip.mp4",
                "source_path": "clip.mp4",
                "title": title,
                "duration_ms": duration_ms,
                "status": "ready",
                "analysis_version": pipeline.ANALYSIS_VERSION,
                "meta_json": json.dumps({"analysis_metrics": metrics or {}}),
            })
            if frames:
                db.insert_frames(vid, list(frames))
            if tracks:
                db.insert_ocr_tracks(vid, list(tracks))
            if segments:
                db.insert_segments(vid, list(segments))
            if anchors:
                db.set_ocr_anchors(vid, list(anchors))
        finally:
            db.close()


class OverviewOcrStateTests(_HomeCase):
    def test_failed_frames_are_reported_as_failed(self):
        self.add_video(frames=[{"pts_ms": 1000, "path": "f.jpg", "ocr_status": "failed", "text_coverage": None}])
        data = pipeline.overview(self.cfg, "vid_ocr")
        self.assertEqual(data["capabilities"]["ocr_state"], "failed")
        self.assertFalse(data["capabilities"]["ocr"])
        self.assertEqual(data["capabilities"]["ocr_failed_frames"], 1)
        self.assertEqual(data["visual"]["ocr"]["state"], "failed")
        codes = [w["code"] for w in data["warnings"]]
        self.assertIn("OCR_FAILED", codes)
        failed = next(w for w in data["warnings"] if w["code"] == "OCR_FAILED")
        self.assertIn("不是", failed["message"])

    def test_lazy_mode_says_not_indexed_not_no_text(self):
        self.add_video(frames=[{"pts_ms": 1000, "path": "f.jpg", "ocr_status": "pending"}],
                       metrics={"profile": "auto", "ocr_budget": 0})
        data = pipeline.overview(self.cfg, "vid_ocr")
        self.assertEqual(data["capabilities"]["ocr_state"], "on_demand")
        codes = [w["code"] for w in data["warnings"]]
        self.assertIn("OCR_NOT_INDEXED", codes)
        self.assertNotIn("OCR_FAILED", codes)

    def test_indexed_frames_have_no_failure_warning(self):
        tracks = [{"start_ms": 1000, "end_ms": 1000, "text": "画面标题", "confidence": 0.9, "bbox": [0, 0, 10, 10]}]
        self.add_video(frames=[{"pts_ms": 1000, "path": "f.jpg", "ocr_status": "ok", "text_coverage": 0.2}],
                       tracks=tracks, metrics={"profile": "fast", "ocr_budget": 6})
        data = pipeline.overview(self.cfg, "vid_ocr")
        self.assertEqual(data["capabilities"]["ocr_state"], "indexed")
        codes = [w["code"] for w in data["warnings"]]
        self.assertNotIn("OCR_FAILED", codes)
        self.assertNotIn("OCR_NOT_INDEXED", codes)


class SearchEmptyHonestyTests(_HomeCase):
    def test_empty_library_is_an_error_not_an_empty_success(self):
        with self.assertRaises(Video2AgentError) as ctx:
            pipeline.search(self.cfg, "矩阵")
        self.assertEqual(ctx.exception.code, "E_EMPTY_LIBRARY")
        self.assertIn("ingest", ctx.exception.remedy)

    def test_zero_hits_say_the_visual_index_was_never_built(self):
        self.add_video(frames=[{"pts_ms": 1000, "path": "f.jpg", "ocr_status": "pending"}],
                       metrics={"profile": "auto", "ocr_budget": 0})
        data = pipeline.search(self.cfg, "zzzznotaslideword", video_id="vid_ocr")
        self.assertTrue(data["empty"])
        codes = [w["code"] for w in data["warnings"]]
        self.assertIn("NO_MATCH", codes)
        self.assertIn("OCR_NOT_INDEXED", codes)
        note = next(w for w in data["warnings"] if w["code"] == "OCR_NOT_INDEXED")
        self.assertIn("video2agent ocr-index", note["remedy"])

    def test_zero_hits_name_a_failed_read(self):
        self.add_video(frames=[{"pts_ms": 1000, "path": "f.jpg", "ocr_status": "failed", "text_coverage": None}],
                       metrics={"profile": "fast", "ocr_budget": 6})
        data = pipeline.search(self.cfg, "zzzznotaslideword", video_id="vid_ocr")
        codes = [w["code"] for w in data["warnings"]]
        self.assertIn("OCR_FAILED", codes)
        note = next(w for w in data["warnings"] if w["code"] == "OCR_FAILED")
        self.assertIn("不能说明", note["message"])


class TranscriptHonestyTests(unittest.TestCase):
    def test_missing_model_blocks_a_ready_empty_transcript(self):
        failure = Video2AgentError("E_ASR_NOT_CONFIGURED", "没有模型。", "运行 video2agent models download --model small。")
        blocked = pipeline._asr_blocked_error(has_audio=True, segments=[], failure=failure)
        self.assertIsNotNone(blocked)
        self.assertEqual(blocked.code, "E_ASR_NOT_CONFIGURED")
        self.assertIn("没有生成转写", blocked.message)
        self.assertIn("models download", blocked.remedy)

    def test_audio_less_video_is_not_an_error(self):
        failure = Video2AgentError("E_ASR_NOT_CONFIGURED", "没有模型。", "下载模型。")
        self.assertIsNone(pipeline._asr_blocked_error(has_audio=False, segments=[], failure=failure))

    def test_a_real_transcript_is_not_an_error(self):
        failure = Video2AgentError("E_ASR_NOT_CONFIGURED", "没有模型。", "下载模型。")
        self.assertIsNone(pipeline._asr_blocked_error(
            has_audio=True, segments=[{"text": "你好"}], failure=failure))


class EvidenceSameFrameTests(_HomeCase):
    """A picture and its text must describe the same frame."""

    def setUp(self):
        super().setUp()
        self.frame_dir = Path(self._tmp.name) / "frames"
        self.frame_dir.mkdir()
        self.sample = self.frame_dir / "f1000.jpg"
        self.sample.write_bytes(b"\xff\xd8\xff\xd9")
        self.add_video(
            frames=[{"pts_ms": 1000, "path": str(self.sample)}],
            tracks=[{"start_ms": 2500, "end_ms": 2500, "text": "第二页文字",
                     "confidence": 0.95, "tokens": tokens_for_search("第二页文字")}],
            anchors=[2500],
        )

    def _fake_extract(self, _src, _at, out, **_kwargs):
        Path(out).parent.mkdir(parents=True, exist_ok=True)
        Path(out).write_bytes(b"\xff\xd8\xff\xd9")

    def test_the_picture_and_its_text_share_a_frame(self):
        boxes = [{"text": "第一页标题", "confidence": 0.96, "bbox": [10, 10, 300, 40]}]
        with patch("video2agent.pipeline.extract_frame", side_effect=self._fake_extract), \
                patch("video2agent.pipeline.ocr_available", return_value=True), \
                patch("video2agent.pipeline.ocr_image", return_value=boxes) as read:
            data = pipeline.evidence(self.cfg, video_id="vid_ocr", at_ms=1500, image_budget=1)
        self.assertEqual(data["frame_ms"], 1500)
        self.assertEqual(data["ocr_frame_ms"], 1500)
        self.assertEqual([o["text"] for o in data["ocr"]], ["第一页标题"])
        self.assertNotIn("OCR_WINDOW_EMPTY", [w["code"] for w in data["warnings"]])
        self.assertEqual(read.call_count, 1)

    def test_a_failed_read_does_not_ship_the_other_frame_text(self):
        def boom(*_a, **_k):
            raise OcrFailed("engine down")

        with patch("video2agent.pipeline.extract_frame", side_effect=self._fake_extract), \
                patch("video2agent.pipeline.ocr_available", return_value=True), \
                patch("video2agent.pipeline.ocr_image", side_effect=boom):
            data = pipeline.evidence(self.cfg, video_id="vid_ocr", at_ms=1500, image_budget=1)
        self.assertEqual(data["ocr"], [])
        codes = [w["code"] for w in data["warnings"]]
        self.assertIn("OCR_FAILED", codes)
        self.assertNotIn("OCR_WINDOW_EMPTY", codes)
        self.assertEqual(data["ocr_state"], "failed")

    def test_an_extract_failure_is_named_not_swallowed(self):
        boxes = [{"text": "采样帧文字", "confidence": 0.9, "bbox": [1, 1, 60, 20]}]
        with patch("video2agent.pipeline.extract_frame", side_effect=RuntimeError("no decoder")), \
                patch("video2agent.pipeline.ocr_available", return_value=True), \
                patch("video2agent.pipeline.ocr_image", return_value=boxes):
            data = pipeline.evidence(self.cfg, video_id="vid_ocr", at_ms=1500, image_budget=1)
        codes = [w["code"] for w in data["warnings"]]
        self.assertIn("FRAME_EXTRACT_FAILED", codes)
        # It still answers from the nearest sampled frame, and says which frame.
        self.assertEqual(data["ocr_frame_ms"], 1000)
        self.assertTrue(data["ocr"])

    def test_nearby_legacy_ocr_is_not_used_for_the_picture(self):
        boxes = [{"text": "当前画面 10 元", "confidence": 0.96, "bbox": [10, 10, 300, 40]}]
        with Database(self.cfg.db_path) as db:
            db.insert_ocr_tracks("vid_ocr", [{"start_ms": 1200, "end_ms": 1200, "text": "下一帧 99 元"}])
            db.set_ocr_anchors("vid_ocr", [1000, 1200, 2500])
        with patch("video2agent.pipeline.ocr_available", return_value=True), \
                patch("video2agent.pipeline._local_ocr_boxes", return_value=boxes) as read:
            data = pipeline.evidence(self.cfg, video_id="vid_ocr", at_ms=1000, image_budget=1)
        read.assert_called_once_with(str(self.sample), None, False)
        self.assertEqual(data["frame_ms"], 1000)
        self.assertEqual(data["ocr_frame_ms"], 1000)
        self.assertEqual([row["text"] for row in data["ocr"]], ["当前画面 10 元"])

    def test_first_surviving_frame_is_the_one_read(self):
        boxes = [{"text": "返回的画面", "confidence": 0.96, "bbox": [10, 10, 300, 40]}]
        with Database(self.cfg.db_path) as db:
            db.insert_frames("vid_ocr", [{"pts_ms": 1200, "path": str(self.frame_dir / "missing.jpg")}])
            db.insert_ocr_tracks("vid_ocr", [{"start_ms": 1200, "end_ms": 1200, "text": "已清理的画面"}])
        with patch("video2agent.pipeline.ocr_available", return_value=True), \
                patch("video2agent.pipeline._local_ocr_boxes", return_value=boxes) as read:
            data = pipeline.evidence(self.cfg, video_id="vid_ocr", at_ms=1200, image_budget=2)
        read.assert_called_once_with(str(self.sample), None, False)
        self.assertEqual(data["images"], [str(self.sample)])
        self.assertEqual(data["frame_ms"], 1000)
        self.assertEqual(data["ocr_frame_ms"], 1000)
        self.assertEqual([row["text"] for row in data["ocr"]], ["返回的画面"])

    def test_no_engine_preserves_unread_state_and_text_only_lookup(self):
        with patch("video2agent.pipeline.ocr_available", return_value=False), \
                patch("video2agent.pipeline.cloud.configured", return_value=False):
            image = pipeline.evidence(self.cfg, video_id="vid_ocr", at_ms=1000, image_budget=1)
            text = pipeline.evidence(self.cfg, video_id="vid_ocr", at_ms=1000, image_budget=0)
        self.assertEqual(image["ocr"], [])
        self.assertEqual(image["ocr_state"], "unread")
        self.assertIsNone(image["ocr_frame_ms"])
        self.assertIn("OCR_UNAVAILABLE", [warning["code"] for warning in image["warnings"]])
        self.assertEqual([row["text"] for row in text["ocr"]], ["第二页文字"])
        self.assertEqual(text["ocr_frame_ms"], 2500)

    def test_a_successful_empty_read_is_reused_without_an_engine(self):
        with patch("video2agent.pipeline.ocr_available", return_value=True), \
                patch("video2agent.pipeline._local_ocr_boxes", return_value=[]) as read:
            first = pipeline.evidence(self.cfg, video_id="vid_ocr", at_ms=1000, image_budget=1)
        read.assert_called_once()
        with patch("video2agent.pipeline.ocr_available", return_value=False), \
                patch("video2agent.pipeline._local_ocr_boxes") as read:
            second = pipeline.evidence(self.cfg, video_id="vid_ocr", at_ms=1000, image_budget=1)
        read.assert_not_called()
        self.assertEqual(second["ocr"], [])
        self.assertEqual(second["ocr_state"], "read")
        self.assertEqual(second["ocr_frame_ms"], 1000)
        self.assertEqual(second["evidence_id"], first["evidence_id"])
        codes = [warning["code"] for warning in second["warnings"]]
        self.assertIn("OCR_EMPTY_FRAME", codes)
        self.assertNotIn("OCR_UNAVAILABLE", codes)

    def test_replaced_primary_frame_never_reuses_its_previous_ocr_or_citation(self):
        companion = self.frame_dir / "f1300.jpg"
        companion.write_bytes(b"companion frame")
        with Database(self.cfg.db_path) as db:
            db.insert_frames("vid_ocr", [{"pts_ms": 1300, "path": str(companion)}])
        old_boxes = [{"text": "原始引用", "confidence": 0.96, "bbox": [10, 10, 300, 40]}]
        new_boxes = [{"text": "新截图", "confidence": 0.96, "bbox": [10, 10, 300, 40]}]
        with patch("video2agent.pipeline.ocr_available", return_value=True), \
                patch("video2agent.pipeline._local_ocr_boxes", side_effect=[old_boxes, new_boxes]) as read:
            original = pipeline.evidence(self.cfg, video_id="vid_ocr", at_ms=1000, image_budget=2)
            self.sample.write_bytes(b"replacement frame")
            fresh = pipeline.evidence(self.cfg, video_id="vid_ocr", at_ms=1000, image_budget=2)
            replay = pipeline.evidence(self.cfg, video_id="vid_ocr", evidence_id=original["evidence_id"])
        self.assertEqual(read.call_count, 2)
        self.assertEqual(original["images"], [str(self.sample), str(companion)])
        self.assertNotEqual(fresh["evidence_id"], original["evidence_id"])
        self.assertEqual([row["text"] for row in fresh["ocr"]], ["新截图"])
        self.assertEqual([row["text"] for row in replay["ocr"]], ["原始引用"])
        self.assertEqual(replay["ocr_frame_ms"], 1000)
        self.assertEqual(replay["images"], [])
        self.assertIsNone(replay["frame_ms"])
        self.assertNotIn("_image_hashes", replay)


class EvidenceListAlignmentTests(_HomeCase):
    """frames and images must be the same list, even when a frame file is gone."""

    def test_a_missing_frame_is_removed_from_both_lists(self):
        from PIL import Image
        frame_dir = Path(self._tmp.name) / "frames"
        frame_dir.mkdir()
        paths = []
        for index in range(3):
            path = frame_dir / f"f{index}.jpg"
            Image.new("RGB", (64, 36), "white").save(path)
            paths.append(str(path))
        self.add_video(frames=[
            {"pts_ms": (index + 1) * 1000, "path": path, "ocr_status": "ok", "text_coverage": 0.1}
            for index, path in enumerate(paths)
        ])
        Path(paths[1]).unlink()
        data = pipeline.evidence(self.cfg, video_id="vid_ocr", at_ms=2000, image_budget=3)
        self.assertEqual(len(data["images"]), len(data["frames"]))
        self.assertEqual(len(data["frames"]), len(data["image_frame_ms"]))
        self.assertEqual([f["t_ms"] for f in data["frames"]], data["image_frame_ms"])
        self.assertEqual(len(data["images"]), 2)
        self.assertIn("FRAME_MISSING", [w["code"] for w in data["warnings"]])


class OcrResultShapeTests(unittest.TestCase):
    """The adapter must accept both engines' result shapes."""

    def test_legacy_items_pass_through(self):
        from video2agent.visual import _ocr_items
        items = [([[0, 0], [1, 0], [1, 1], [0, 1]], "hello", 0.9)]
        self.assertEqual(_ocr_items(items, "legacy"), items)

    def test_rapidocr_output_object_is_normalized(self):
        from types import SimpleNamespace

        from video2agent.visual import _ocr_items

        raw = SimpleNamespace(
            txts=("hello", "world"),
            scores=(0.9, 0.8),
            boxes=[[[0, 0], [1, 0], [1, 1], [0, 1]], [[2, 2], [3, 2], [3, 3], [2, 3]]],
        )
        items = _ocr_items(raw, "rapidocr")
        self.assertEqual(len(items), 2)
        self.assertEqual(items[0][1], "hello")
        self.assertAlmostEqual(items[1][2], 0.8)

    def test_missing_fields_are_empty_not_crash(self):
        from types import SimpleNamespace

        from video2agent.visual import _ocr_items

        self.assertEqual(_ocr_items(SimpleNamespace(txts=None, boxes=None, scores=None), "rapidocr"), [])


class OcrRuntimeCacheTests(unittest.TestCase):
    """A fixed or moved OCR environment must not stay broken for the process."""

    @unittest.skipUnless(
        importlib.util.find_spec("rapidocr") or importlib.util.find_spec("rapidocr_onnxruntime"),
        "neither OCR engine is installed",
    )
    def test_a_failed_availability_probe_is_retried(self):
        import video2agent.visual as visual
        with patch.object(visual, "_OCR_TRIED", True), \
                patch.object(visual, "_OCR_AVAILABLE", False), \
                patch.object(visual, "_OCR_TRIED_AT", time.monotonic() - visual._OCR_RETRY_SECONDS - 1):
            self.assertTrue(visual.ocr_available())

    def test_a_recent_failure_stays_cached(self):
        import video2agent.visual as visual
        with patch.object(visual, "_OCR_TRIED", True), \
                patch.object(visual, "_OCR_AVAILABLE", False), \
                patch.object(visual, "_OCR_TRIED_AT", time.monotonic()):
            self.assertFalse(visual.ocr_available())

    def test_builtin_rapidocr_bounds_thread_pools_without_overriding_custom_config(self):
        import video2agent.visual as visual
        made = []

        def fake_engine(**kwargs):
            made.append(kwargs)
            return object()

        with patch.object(visual, "_OCR_LOCAL", threading.local()), \
                patch.object(visual, "ocr_engine", return_value=("rapidocr", fake_engine)), \
                patch.object(visual.os, "process_cpu_count", return_value=4, create=True):
            first = visual._engine_for_thread()
            self.assertIs(first, visual._engine_for_thread())
            visual._engine_for_thread("custom-ocr.yaml")
        self.assertEqual(made, [
            {"params": {
                "EngineConfig.onnxruntime.intra_op_num_threads": 2,
                "EngineConfig.onnxruntime.inter_op_num_threads": 1,
            }},
            {"config_path": "custom-ocr.yaml"},
        ])

    def test_the_engine_is_rebuilt_when_the_config_file_changes(self):
        import video2agent.visual as visual
        with tempfile.TemporaryDirectory() as tmp:
            config = Path(tmp) / "ocr.yaml"
            config.write_text("model: v1", encoding="utf-8")
            made = []

            class FakeEngine:
                def __init__(self, config_path=None):
                    made.append(config_path)

            with patch.object(visual, "_OCR_LOCAL", threading.local()), \
                    patch.object(visual, "ocr_engine", return_value=("legacy", FakeEngine)):
                visual._engine_for_thread(str(config))
                visual._engine_for_thread(str(config))
                self.assertEqual(len(made), 1, "the same config must reuse its engine")
                stat = config.stat()
                os.utime(config, (stat.st_atime + 10, stat.st_mtime + 10))
                visual._engine_for_thread(str(config))
                self.assertEqual(len(made), 2, "a changed config must build a new engine")


class OcrPrefilterTests(unittest.TestCase):
    """The cheap text signal must actually separate text from blank frames."""

    def test_a_blank_first_deck_still_selects_text_frames(self):
        from PIL import Image, ImageDraw

        from video2agent.media import frame_features

        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            paths = []
            for i in range(6):
                blank = Image.new("RGB", (640, 360), (24, 28, 36))
                blank_path = root / f"blank{i}.png"
                blank.save(blank_path)
                paths.append(blank_path)
                text = Image.new("RGB", (640, 360), (24, 28, 36))
                draw = ImageDraw.Draw(text)
                for k in range(4):
                    draw.text((40, 40 + k * 40), f"SLIDE {i} line {k} price 12.99", fill=(240, 240, 240))
                text_path = root / f"text{i}.png"
                text.save(text_path)
                paths.append(text_path)
            frames = []
            prev = None
            for i, path in enumerate(paths):
                features, prev = frame_features(str(path), prev)
                frames.append({"pts_ms": i * 1000, "path": str(path), **features})
            chosen = select_ocr_frames(frames, 6)
            self.assertTrue(chosen)
            self.assertTrue(all("text" in Path(f["path"]).name for f in chosen),
                            f"blank-first deck chose {[Path(f['path']).name for f in chosen]}")


class OcrTextClipTests(unittest.TestCase):
    """A misread overlay must not turn the evidence receipt into a paragraph."""

    def test_a_repeated_glyph_blob_is_capped(self):
        text, truncated = pipeline._clip_ocr_text("图 " * 500)
        self.assertTrue(truncated)
        self.assertLessEqual(len(text), 401)
        self.assertTrue(text.endswith("…"))

    def test_short_text_is_unchanged(self):
        text, truncated = pipeline._clip_ocr_text("短文本")
        self.assertFalse(truncated)
        self.assertEqual(text, "短文本")


class VisualIndexTests(_HomeCase):
    """The explicit on-screen text index: measure, then read; never silent."""

    def setUp(self):
        super().setUp()
        from PIL import Image
        self.frame_dir = Path(self._tmp.name) / "frames"
        self.frame_dir.mkdir()
        self.frames = []
        for index, pts in enumerate((1000, 2000, 3000)):
            path = self.frame_dir / f"f{index}.jpg"
            Image.new("RGB", (64, 36), "white").save(path)
            self.frames.append({"pts_ms": pts, "path": str(path), "line_score": 0.3,
                                "edge_density": 0.2, "sharpness": 0.8, "motion": 0.0})
        self.add_video(frames=self.frames)

    def test_dry_run_measures_but_writes_nothing(self):
        boxes = [{"text": "标题", "confidence": 0.9, "bbox": [2, 2, 20, 10]}]
        with patch("video2agent.pipeline.ocr_available", return_value=True), \
                patch("video2agent.pipeline.ocr_image", return_value=boxes) as read:
            data = pipeline.ocr_index(self.cfg, "vid_ocr", dry_run=True)
        self.assertTrue(data["dry_run"])
        self.assertEqual(data["to_read"], 3)
        self.assertGreater(data["per_frame_ms"], 0)
        self.assertEqual(data["measured_by"], "probe")
        self.assertEqual(read.call_count, 1, "a dry run probes one frame, not all")
        with Database(self.cfg.db_path) as db:
            self.assertEqual(db.frame_ocr_counts("vid_ocr").get("ok", 0), 0)
            self.assertEqual(db.get_ocr_anchors("vid_ocr"), [])
            self.assertEqual(db.counts("vid_ocr")["ocr_tracks"], 0)

    def test_the_index_makes_visual_text_searchable(self):
        boxes = [{"text": "注意力机制", "confidence": 0.9, "bbox": [2, 2, 40, 10]},
                 {"text": "表格与结论", "confidence": 0.9, "bbox": [2, 14, 40, 10]}]
        with patch("video2agent.pipeline.ocr_available", return_value=True), \
                patch("video2agent.pipeline.ocr_image", return_value=boxes):
            data = pipeline.ocr_index(self.cfg, "vid_ocr")
        self.assertEqual(data["indexed"], 3)
        self.assertTrue(data["visual_indexed"])
        self.assertEqual(data["visual_index"]["state"], "complete")
        hits = pipeline.search(self.cfg, "注意力机制", video_id="vid_ocr")
        self.assertTrue(hits["results"])
        self.assertTrue(hits["visual_indexed"])
        with Database(self.cfg.db_path) as db:
            self.assertEqual(db.frame_ocr_counts("vid_ocr").get("ok"), 3)
            self.assertEqual(sorted(db.get_ocr_anchors("vid_ocr")), [1000, 2000, 3000])

    def test_limit_caps_the_frames_read(self):
        boxes = [{"text": "标题", "confidence": 0.9, "bbox": [2, 2, 20, 10]}]
        with patch("video2agent.pipeline.ocr_available", return_value=True), \
                patch("video2agent.pipeline.ocr_image", return_value=boxes) as read:
            data = pipeline.ocr_index(self.cfg, "vid_ocr", limit=2)
        self.assertEqual(read.call_count, 2)
        self.assertEqual(data["indexed"], 2)

    def test_the_default_budget_covers_a_hundred_frames(self):
        # The default cap used to be 60, so a 120-frame record could never be
        # fully indexed by one call; a text-heavy video stayed half-read.
        from PIL import Image

        frames = []
        for i in range(100):
            path = self.frame_dir / f"d{i}.jpg"
            Image.new("RGB", (32, 18), "white").save(path)
            frames.append({"pts_ms": i * 1000, "path": str(path), "line_score": 0.3,
                           "edge_density": 0.2, "sharpness": 0.8, "motion": 0.0})
        self.add_video(vid="vid_big", frames=frames)
        boxes = [{"text": "标题", "confidence": 0.9, "bbox": [2, 2, 20, 10]}]
        with patch("video2agent.pipeline.ocr_available", return_value=True), \
                patch("video2agent.pipeline.ocr_image", return_value=boxes):
            data = pipeline.ocr_index(self.cfg, "vid_big")
        self.assertEqual(data["indexed"], 100)

    def test_a_failed_read_is_counted_not_hidden(self):
        with patch("video2agent.pipeline.ocr_available", return_value=True), \
                patch("video2agent.pipeline.ocr_image", side_effect=OcrFailed("engine down")):
            data = pipeline.ocr_index(self.cfg, "vid_ocr")
        self.assertEqual(data["failed"], 3)
        self.assertFalse(data["visual_indexed"])
        self.assertEqual(data["visual_index"]["state"], "failed")
        overview = pipeline.overview(self.cfg, "vid_ocr")
        self.assertEqual(overview["visual_index"]["state"], "failed")

    def test_a_capped_pass_is_partial_not_complete(self):
        boxes = [{"text": "标题", "confidence": 0.9, "bbox": [2, 2, 20, 10]}]
        with patch("video2agent.pipeline.ocr_available", return_value=True), \
                patch("video2agent.pipeline.ocr_image", return_value=boxes):
            data = pipeline.ocr_index(self.cfg, "vid_ocr", limit=1)
        self.assertEqual(data["indexed"], 1)
        self.assertEqual(data["remaining"], 2)
        self.assertEqual(data["visual_index"]["state"], "partial")
        overview = pipeline.overview(self.cfg, "vid_ocr")
        self.assertEqual(overview["visual_index"]["state"], "partial")
        self.assertIn("待读", overview["visual_index"]["reason"])

    def test_a_partial_index_marks_ocr_state_partial(self):
        boxes = [{"text": "标题", "confidence": 0.9, "bbox": [2, 2, 20, 10]}]
        with patch("video2agent.pipeline.ocr_available", return_value=True), \
                patch("video2agent.pipeline.ocr_image", return_value=boxes):
            pipeline.ocr_index(self.cfg, "vid_ocr", limit=1)
        overview = pipeline.overview(self.cfg, "vid_ocr")
        self.assertEqual(overview["visual_index"]["state"], "partial")
        self.assertEqual(overview["capabilities"]["ocr_state"], "partial")

    def test_a_partial_index_zero_hit_says_so(self):
        boxes = [{"text": "标题", "confidence": 0.9, "bbox": [2, 2, 20, 10]}]
        with patch("video2agent.pipeline.ocr_available", return_value=True), \
                patch("video2agent.pipeline.ocr_image", return_value=boxes):
            pipeline.ocr_index(self.cfg, "vid_ocr", limit=1)
        hits = pipeline.search(self.cfg, "zzzznotaslideword", video_id="vid_ocr")
        codes = [w["code"] for w in hits["warnings"]]
        self.assertIn("OCR_INDEX_PARTIAL", codes)
        note = next(w for w in hits["warnings"] if w["code"] == "OCR_INDEX_PARTIAL")
        self.assertIn("ocr-index", note["remedy"])

    def test_library_search_reports_each_videos_state(self):
        boxes = [{"text": "标题", "confidence": 0.9, "bbox": [2, 2, 20, 10]}]
        with patch("video2agent.pipeline.ocr_available", return_value=True), \
                patch("video2agent.pipeline.ocr_image", return_value=boxes):
            pipeline.ocr_index(self.cfg, "vid_ocr")
        self.add_video(vid="vid_lazy", frames=[{"pts_ms": 1000, "path": "f.jpg",
                                               "ocr_status": "pending"}],
                       metrics={"profile": "auto", "ocr_budget": 0})
        complete = pipeline.search(self.cfg, "zzzznotaslideword", video_id="vid_ocr")
        lazy = pipeline.search(self.cfg, "zzzznotaslideword", video_id="vid_lazy")
        library = pipeline.search(self.cfg, "zzzznotaslideword")
        self.assertEqual(complete["visual_index"]["state"], "complete")
        self.assertEqual(lazy["visual_index"]["state"], "on_demand")
        self.assertEqual(library["visual_index"]["state"], "partial")
        self.assertEqual(complete["visual_index"]["state"],
                         pipeline.overview(self.cfg, "vid_ocr")["visual_index"]["state"])

    def test_old_records_derive_the_state_from_frames(self):
        # No analysis_metrics at all: the stored frame statuses are the evidence.
        self.add_video(vid="vid_old", frames=[{"pts_ms": 1000, "path": "f.jpg",
                                               "ocr_status": "ok", "text_coverage": 0.2}])
        data = pipeline.overview(self.cfg, "vid_old")
        self.assertTrue(data["visual_indexed"])
        self.assertEqual(data["visual_index"]["state"], "partial")

    def test_old_records_report_frames_still_to_read(self):
        # No recorded pass, but the frame statuses already say how many are unread;
        # "partial" with no number read as "we do not know how much is left".
        self.add_video(vid="vid_old", frames=_frames("ok", "pending"), metrics={})
        info = pipeline.overview(self.cfg, "vid_old")["visual_index"]
        self.assertEqual(info["state"], "partial")
        self.assertEqual(info["read_frames"], 1)
        self.assertEqual(info["total_frames"], 2)
        self.assertEqual(info["remaining_frames"], 1)
        self.assertIn("待读", info["reason"])


class JobErrorHonestyTests(unittest.TestCase):
    def test_a_failed_job_keeps_its_runnable_remedy(self):
        with tempfile.TemporaryDirectory() as tmp:
            home = Path(tmp) / "home"
            cfg = load_config(home)
            db = Database(cfg.db_path)
            try:
                job_id = db.create_job("ingest", "clip.mp4", options={})
                db.update_job(
                    job_id, state="failed", error_code="E_ASR_NOT_CONFIGURED",
                    error_message="没有可用的语音识别模型。",
                    remedy="运行 video2agent models download --model small（约 464MB）。",
                )
            finally:
                db.close()
            buf = io.StringIO()
            with redirect_stdout(buf):
                code = cli.main(["jobs", "--id", job_id, "--json", "--home", str(home)])
            self.assertEqual(code, 1)
            data = json.loads(buf.getvalue())
            self.assertFalse(data["ok"])
            self.assertEqual(data["error"]["code"], "E_ASR_NOT_CONFIGURED")
            self.assertIn("models download", data["error"]["remedy"])


class DoctorHonestyTests(unittest.TestCase):
    def test_an_uncached_model_is_not_a_green_check(self):
        with tempfile.TemporaryDirectory() as tmp:
            cfg = load_config(Path(tmp) / "home")
            missing = {"cached": False, "model": "small", "bytes": 0, "path": str(Path(tmp) / "models")}
            with patch("video2agent.text.whisper_cache_state", return_value=missing):
                result = doctor(cfg)
            check = next(c for c in result["checks"] if c["name"] == "asr_model_cached")
            self.assertFalse(check["ok"], "a configured but missing model is not ready")
            self.assertIn("video2agent models download", check["remedy"])
    def test_doctor_prints_a_next_step(self):
        with tempfile.TemporaryDirectory() as tmp:
            home = Path(tmp) / "home"
            missing = {"cached": False, "model": "small", "bytes": 0, "path": str(Path(tmp) / "models")}
            buf = io.StringIO()
            with patch("video2agent.text.whisper_cache_state", return_value=missing), redirect_stdout(buf):
                cli.main(["doctor", "--home", str(home), "--json"])
            data = json.loads(buf.getvalue())
            self.assertIn("next_step", data)
            if data.get("required_ok"):
                self.assertIn("video2agent models download", data["next_step"])


class DoctorAlignmentTests(_HomeCase):
    def _alignment(self):
        return next(c for c in doctor(self.cfg)["checks"] if c["name"] == "transcript_alignment")

    def test_doctor_accepts_a_signed_wbi_caption_track(self):
        # Real library: all 15 flagged records were WBI tracks, 13 of them perfectly
        # valid Chinese transcripts whose clickbait titles simply never get spoken.
        # Re-ingest cannot change them, so the doctor told users to chase a dead end.
        self.add_video(
            title="双十一半价老旗舰香爆了",
            duration_ms=200_000,
            metrics={"transcript_source": "caption", "caption_track": {"endpoint": "wbi", "lan": "ai-zh"}},
            segments=[{"start_ms": i * 1000, "end_ms": i * 1000 + 900, "text": f"今年想换个新机真是太难了{i}"}
                      for i in range(80)],
        )
        check = self._alignment()
        self.assertTrue(check["ok"], check["detail"])

    def test_doctor_still_flags_an_untrusted_mismatched_caption(self):
        self.add_video(
            title="直观解释注意力机制 Transformer 深度学习",
            duration_ms=200_000,
            metrics={"transcript_source": "caption", "caption_track": {"endpoint": "player-v2"}},
            segments=[{"start_ms": i * 1000, "end_ms": i * 1000 + 900, "text": f"手机镜头膜到底有没有必要贴{i}"}
                      for i in range(80)],
        )
        check = self._alignment()
        self.assertFalse(check["ok"])
        self.assertIn("不匹配", check["detail"])


if __name__ == "__main__":
    unittest.main()

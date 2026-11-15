import os
import tempfile
import types
import unittest
from pathlib import Path
from unittest.mock import patch

from video2agent import text as text_mod
from video2agent.config import load_config
from video2agent.db import Database
from video2agent.pipeline import _chapter_title, _chapters, evidence
from video2agent.text import tokens_for_search, whisper_cache_state
from video2agent.visual import _frames_at_times

VID = "vid_anchor"
MEDIA_MS = 200_000


class AnchorStoreTests(unittest.TestCase):
    def test_anchors_round_trip(self):
        with tempfile.TemporaryDirectory() as tmp:
            cfg = load_config(Path(tmp))
            db = Database(cfg.db_path)
            try:
                self.assertEqual(db.get_ocr_anchors(VID), [])
                db.set_ocr_anchors(VID, [9000, 3000, 9000, -5])
                self.assertEqual(db.get_ocr_anchors(VID), [3000, 9000])
            finally:
                db.close()

    def test_frames_at_times_picks_the_nearest_sample(self):
        frames = [{"pts_ms": t} for t in (0, 5000, 10_000, 15_000)]
        chosen = _frames_at_times(frames, [4_800, 10_400])
        self.assertEqual([f["pts_ms"] for f in chosen], [5000, 10_000])

    def test_frames_at_times_skips_far_away_anchors(self):
        frames = [{"pts_ms": 0}, {"pts_ms": 1000}]
        self.assertEqual(_frames_at_times(frames, [10_000]), [])


class EvidenceFallbackTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.tmp = tempfile.TemporaryDirectory()
        cls.cfg = load_config(Path(cls.tmp.name))
        db = Database(cls.cfg.db_path)
        try:
            db.upsert_video({
                "id": VID, "source_kind": "local", "source_uri": "x.mp4", "source_path": "x.mp4",
                "title": "anchor", "duration_ms": MEDIA_MS, "status": "ready", "analysis_version": "0.2",
            })
            db.insert_ocr_tracks(VID, [{
                "start_ms": 30_000, "end_ms": 31_000, "text": "这是锚点上的文字",
                "confidence": 0.9, "tokens": tokens_for_search("这是锚点上的文字"),
            }])
            db.set_ocr_anchors(VID, [30_000])
        finally:
            db.close()

    @classmethod
    def tearDownClass(cls):
        cls.tmp.cleanup()

    def test_empty_window_falls_back_to_the_nearest_anchor(self):
        # Only a *nearby* anchor may answer this moment. 120s vs a 30s anchor is 90s
        # away, so the honest answer is "not read", not the other moment's text.
        payload = evidence(self.cfg, video_id=VID, at_ms=120_000, image_budget=0)
        self.assertIsNone(payload["nearest_ocr_ms"])
        self.assertFalse(payload["ocr"], "a far anchor must not be presented as this moment")

    def test_a_nearby_anchor_is_still_used(self):
        # 26.5s vs a 30s anchor: outside the window, but only 3.5s away, so the anchor
        # may answer — with the distance spelled out.
        payload = evidence(self.cfg, video_id=VID, at_ms=26_500, image_budget=0)
        self.assertEqual(payload["nearest_ocr_ms"], 30_000)
        codes = [w["code"] for w in payload["warnings"]]
        self.assertIn("OCR_WINDOW_EMPTY", codes)
        self.assertTrue(payload["ocr"], "the fallback must actually return the anchor text")

    def test_window_with_text_does_not_fall_back(self):
        payload = evidence(self.cfg, video_id=VID, at_ms=30_400, image_budget=0)
        self.assertIsNone(payload["nearest_ocr_ms"])
        # The fixture has OCR rows but no segmentation, so EMPTY_ANALYSIS is correct;
        # what must not appear is a stale-analysis or OCR warning.
        codes = [w["code"] for w in payload["warnings"]]
        self.assertNotIn("STALE_ANALYSIS", codes)
        self.assertEqual([c for c in codes if c.startswith("OCR")], [])


class OnDemandStampTests(unittest.TestCase):
    """Text read on demand must carry the time of the frame that was read."""

    def setUp(self):
        # Fresh database per test: an anchor written by one test would make the next
        # one skip its OCR read (the "already read" shortcut), which is correct
        # behaviour but makes shared state confusing.
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.cfg = load_config(Path(self.tmp.name))
        self.frame_path = str(Path(self.tmp.name) / "frame_100s.jpg")
        Path(self.frame_path).write_bytes(b"\xff\xd8\xff\xd9")
        db = Database(self.cfg.db_path)
        try:
            db.upsert_video({
                "id": VID, "source_kind": "local", "source_uri": "x.mp4", "source_path": "x.mp4",
                "title": "stamp", "duration_ms": MEDIA_MS, "status": "ready", "analysis_version": "0.2",
            })
            db.insert_frames(VID, [{"pts_ms": 100_000, "path": self.frame_path, "width": 1280, "height": 720}])
        finally:
            db.close()

    def test_on_demand_text_is_stamped_with_the_frame_time(self):
        boxes = [
            {"text": "注意力分数矩阵", "confidence": 0.9, "bbox": [10, 10, 200, 40]},
            {"text": "Q K V", "confidence": 0.9, "bbox": [10, 60, 120, 90]},
            {"text": "softmax", "confidence": 0.9, "bbox": [10, 110, 160, 140]},
        ]
        with patch("video2agent.pipeline.ocr_available", return_value=True), \
                patch("video2agent.pipeline.ocr_image", return_value=boxes) as read:
            # --images 0 means no exact frame, so the nearest sample (100s) is read.
            payload = evidence(self.cfg, video_id=VID, at_ms=108_000, image_budget=0)
        self.assertTrue(payload["ocr"])
        starts = {int(o["start_ms"]) for o in payload["ocr"]}
        self.assertEqual(starts, {100_000}, "text must be stamped with the frame it came from")
        self.assertNotIn(108_000, starts, "never stamp text with the requested time")
        on_demand = [w for w in payload["warnings"] if w["code"] == "OCR_ON_DEMAND"]
        self.assertTrue(on_demand, "the read must be reported")
        # With no image returned, frame_ms is null and ocr_frame_ms describes the read.
        self.assertIsNone(payload["frame_ms"])
        self.assertEqual(payload["ocr_frame_ms"], 100_000)
        self.assertEqual(read.call_count, 1)
        with Database(self.cfg.db_path) as db:
            anchors = db.get_ocr_anchors(VID)
        self.assertEqual(anchors, [100_000], "the anchor is the frame that was read")
        # Second call: the anchor answers, OCR is not run again.
        with patch("video2agent.pipeline.ocr_available", return_value=True), \
                patch("video2agent.pipeline.ocr_image") as read2:
            again = evidence(self.cfg, video_id=VID, at_ms=108_000, image_budget=0)
        self.assertEqual(read2.call_count, 0, "a remembered frame must not be re-read")
        self.assertTrue(again["ocr"])

    def test_an_empty_frame_is_remembered_too(self):
        with patch("video2agent.pipeline.ocr_available", return_value=True), \
                patch("video2agent.pipeline.ocr_image", return_value=[]) as read:
            payload = evidence(self.cfg, video_id=VID, at_ms=108_000, image_budget=0)
        self.assertEqual(read.call_count, 1)
        empty = [w for w in payload["warnings"] if w["code"] == "OCR_EMPTY_FRAME"]
        self.assertTrue(empty)
        self.assertIn("100000", str(empty[0]["message"]) + str(payload.get("ocr_frame_ms")))
        with patch("video2agent.pipeline.ocr_available", return_value=True), \
                patch("video2agent.pipeline.ocr_image") as read2:
            evidence(self.cfg, video_id=VID, at_ms=108_000, image_budget=0)
        self.assertEqual(read2.call_count, 0, "an empty read must not be repeated forever")


class ChapterTitleTests(unittest.TestCase):
    def test_prefers_a_short_slide_heading(self):
        segments = [{"start_ms": 1000, "text": "嗯那个我们这一页讲的是注意力机制的一些细节和实现"}]
        ocr = [{"start_ms": 1200, "text": "注意力机制"}, {"start_ms": 1300, "text": "这是一整段很长的幻灯片正文，包含了很多解释性的句子。"}]
        title, source = _chapter_title(0, 60_000, segments, ocr, 1)
        self.assertEqual(source, "ocr")
        self.assertEqual(title, "注意力机制")

    def test_falls_back_to_the_transcript(self):
        segments = [{"start_ms": 1000, "text": "我们把十年的注意力方法统一成一张表"}]
        title, source = _chapter_title(0, 60_000, segments, [], 1)
        self.assertEqual(source, "transcript")
        self.assertIn("统一成一张表", title)

    def test_timecode_noise_is_not_a_title(self):
        segments = [{"start_ms": 1000, "text": "5m06s"}, {"start_ms": 2000, "text": "嗯"}]
        title, source = _chapter_title(0, 60_000, segments, [], 3)
        self.assertEqual(source, "timecode")
        self.assertEqual(title, "第 3 段")

    def test_chapters_carry_their_source(self):
        scenes = [{"start_ms": 0, "end_ms": 60_000}, {"start_ms": 60_000, "end_ms": 120_000}]
        chapters = _chapters(scenes, [], [], )
        self.assertTrue(chapters)
        self.assertIn("title_source", chapters[0])
        self.assertIn("fallback_timecode", chapters[0])

    def test_long_sparse_scenes_use_a_five_minute_grid(self):
        # One 22-minute scene used to stay one 22-minute chapter. The outline must
        # keep a navigable 5-minute grid even when scene detection is sparse.
        scenes = [{"start_ms": 0, "end_ms": 1_320_000}]
        chapters = _chapters(scenes, [], [])
        self.assertGreaterEqual(len(chapters), 4)
        self.assertEqual(chapters[0]["start_ms"], 0)
        self.assertEqual(chapters[0]["end_ms"], 300_000)
        self.assertEqual(chapters[-1]["end_ms"], 1_320_000)
        self.assertLessEqual(max(c["end_ms"] - c["start_ms"] for c in chapters), 300_000)


class WhisperCacheTests(unittest.TestCase):
    def test_reports_missing_and_present_models(self):
        with tempfile.TemporaryDirectory() as tmp:
            with patch.dict(os.environ, {"HF_HOME": tmp}):
                missing = whisper_cache_state("small")
                self.assertFalse(missing["cached"])
                self.assertEqual(missing["bytes"], 0)
                target = Path(missing["path"]) / "snapshots" / "abc"
                target.mkdir(parents=True)
                (target / "model.bin").write_bytes(b"x" * (2 * 1024 * 1024))
                (target / "config.json").write_bytes(b"{}")
                present = whisper_cache_state("small")
                self.assertTrue(present["cached"])
                self.assertEqual(present["bytes"], 2 * 1024 * 1024 + 2)

    def test_stage_is_announced_before_a_cold_load(self):
        calls = []

        def fake_stage(message):
            calls.append(message)

        # Without this stub the test constructs a real WhisperModel and downloads
        # ~500MB from Hugging Face: it once took 219s and needed the network.
        class Boom(Exception):
            pass

        def refuse(*_args, **_kwargs):
            raise Boom("no download in tests")

        with tempfile.TemporaryDirectory() as tmp:
            with patch.dict(os.environ, {"HF_HOME": tmp}), \
                    patch.dict("sys.modules", {"faster_whisper": types.SimpleNamespace(WhisperModel=refuse)}):
                try:
                    text_mod.transcribe_with_faster_whisper(
                        Path(tmp) / "missing.wav", model_size="small", stage=fake_stage)
                except Exception:
                    pass
        self.assertTrue(any("下载语音模型" in c for c in calls), calls)

    def test_the_download_watcher_reports_bytes_and_stops(self):
        calls = []
        seen = {"bytes": 0}

        def fake_stage(message):
            calls.append(message)

        class Boom(Exception):
            pass

        def slow_load(*_args, **_kwargs):
            # Two watcher ticks with growing cache size, then fail the load.
            import time as _time
            for size in (1024, 4096):
                seen["bytes"] = size
                _time.sleep(0.05)
            raise Boom("no model")

        with tempfile.TemporaryDirectory() as tmp:
            with patch.dict(os.environ, {"HF_HOME": tmp}), \
                    patch.dict("sys.modules", {"faster_whisper": types.SimpleNamespace(WhisperModel=slow_load)}), \
                    patch.object(text_mod, "whisper_cache_state",
                                 side_effect=lambda model: {"model": model, "cached": seen["bytes"] > 0,
                                                            "path": str(Path(tmp) / "models"), "bytes": seen["bytes"]}), \
                    patch.object(text_mod, "human_bytes", side_effect=lambda n: f"{n}B"), \
                    patch.object(text_mod, "_DOWNLOAD_WATCH_INTERVAL_S", 0.01):
                try:
                    text_mod.transcribe_with_faster_whisper(
                        Path(tmp) / "missing.wav", model_size="small", stage=fake_stage)
                except Exception:
                    pass
            before = len(calls)
            import time as _time
            _time.sleep(2.0)
            self.assertEqual(len(calls), before, "the watcher must stop once the load returns")
        self.assertTrue(any("已下载" in c for c in calls), calls)


if __name__ == "__main__":
    unittest.main()

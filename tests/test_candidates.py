"""Candidate shots: scene-based shots with text, honest fallback when no match."""

import tempfile
import unittest
from pathlib import Path

from video2agent.config import load_config
from video2agent.db import Database
from video2agent.pipeline import _sheet_layout, candidates
from video2agent.text import tokens_for_search

VID = "vid_candidates"


class CandidateTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.cfg = load_config(Path(self.tmp.name))
        db = Database(self.cfg.db_path)
        try:
            db.upsert_video({
                "id": VID, "source_kind": "local", "source_uri": "x.mp4",
                "source_path": "x.mp4", "title": "cand", "duration_ms": 60_000,
                "status": "ready", "analysis_version": "0.2",
            })
            db.insert_scenes(VID, [
                {"start_ms": i * 10_000, "end_ms": (i + 1) * 10_000, "cut_score": 0.2}
                for i in range(6)
            ])
            db.insert_segments(VID, [
                {"start_ms": 1000, "end_ms": 5000, "text": "промокод на скидку",
                 "source": "caption", "confidence": 1.0,
                 "tokens": tokens_for_search("промокод на скидку")},
                {"start_ms": 21_000, "end_ms": 25_000, "text": "просто музыка играет",
                 "source": "caption", "confidence": 1.0,
                 "tokens": tokens_for_search("просто музыка играет")},
            ])
            db.insert_frames(VID, [
                {"pts_ms": 5000, "path": "f0.jpg"},
                {"pts_ms": 25_000, "path": "f1.jpg"},
            ])
        finally:
            db.close()

    def test_query_picks_the_shot_with_the_text(self):
        data = candidates(self.cfg, VID, query="промокод", limit=3)
        self.assertEqual(data["shots"], 6)
        top = data["candidates"][0]
        self.assertEqual(top["start_ms"], 0)
        self.assertGreater(top["matched_units"], 0)
        self.assertIn("промокод", top["text"].lower())
        self.assertEqual(top["keyframe_ms"], 5000, "nearest sampled frame")

    def test_no_text_match_is_explicit_and_spread_in_time(self):
        data = candidates(self.cfg, VID, query="абракадабра", limit=3)
        codes = [w["code"] for w in data["warnings"]]
        self.assertIn("NO_TEXT_MATCH", codes)
        starts = [c["start_ms"] for c in data["candidates"]]
        self.assertEqual(len(starts), 3)
        self.assertEqual(starts[0], 0)
        self.assertGreater(starts[-1], starts[0])

    def test_long_shot_candidates_show_the_matching_moment(self):
        with Database(self.cfg.db_path) as db:
            db.upsert_video({
                "id": "vid_long_shot", "source_kind": "local", "source_uri": "long.mp4",
                "source_path": "long.mp4", "title": "long", "duration_ms": 90_000,
                "status": "ready", "analysis_version": "0.3.8",
            })
            db.insert_scenes("vid_long_shot", [{"start_ms": 0, "end_ms": 90_000, "cut_score": 0.2}])
            db.insert_segments("vid_long_shot", [
                {"start_ms": 81_000, "end_ms": 82_000, "text": "calibration finished",
                 "source": "caption", "confidence": 1.0, "tokens": tokens_for_search("calibration finished")},
            ])
            db.insert_frames("vid_long_shot", [
                {"pts_ms": 15_000, "path": "start.jpg"},
                {"pts_ms": 45_000, "path": "middle.jpg"},
                {"pts_ms": 74_000, "path": "before.jpg"},
                {"pts_ms": 81_600, "path": "match.jpg"},
            ])
        result = candidates(self.cfg, "vid_long_shot", query="calibration finished", limit=1)
        pick = result["candidates"][0]
        self.assertEqual((pick["start_ms"], pick["end_ms"]), (60_000, 90_000))
        self.assertEqual(pick["keyframe_ms"], 81_600)
        self.assertEqual(pick["text"], "calibration finished")
        fallback = candidates(self.cfg, "vid_long_shot", query="unknown", limit=3)
        self.assertEqual([row["keyframe_ms"] for row in fallback["candidates"]], [15_000, 45_000, 74_000])

    def test_long_shot_candidates_target_matching_ocr_cue(self):
        with Database(self.cfg.db_path) as db:
            db.upsert_video({
                "id": "vid_long_ocr", "source_kind": "local", "source_uri": "ocr.mp4",
                "source_path": "ocr.mp4", "title": "ocr", "duration_ms": 90_000,
                "status": "ready", "analysis_version": "0.3.8",
            })
            db.insert_scenes("vid_long_ocr", [{"start_ms": 0, "end_ms": 90_000, "cut_score": 0.2}])
            db.insert_ocr_tracks("vid_long_ocr", [
                {"start_ms": 48_000, "end_ms": 50_000, "text": "Export SRT Subtitles",
                 "confidence": 0.95, "tokens": tokens_for_search("Export SRT Subtitles")},
            ])
            db.insert_frames("vid_long_ocr", [
                {"pts_ms": 34_000, "path": "early.jpg"},
                {"pts_ms": 49_200, "path": "ocr_hit.jpg"},
            ])
        result = candidates(self.cfg, "vid_long_ocr", query="Export SRT", limit=1)
        pick = result["candidates"][0]
        self.assertEqual((pick["start_ms"], pick["end_ms"]), (30_000, 60_000))
        self.assertEqual(pick["keyframe_ms"], 49_200)
        self.assertEqual(pick["text"], "Export SRT Subtitles")

    def test_no_saved_frame_does_not_point_at_the_next_shot(self):
        result = candidates(self.cfg, VID, limit=6, images=True)
        for row in result["candidates"]:
            self.assertLessEqual(row["start_ms"], row["keyframe_ms"])
            self.assertLess(row["keyframe_ms"], row["end_ms"])
        self.assertEqual(result["candidates"][1]["keyframe_ms"], 15_000)

    def test_without_a_query_shots_are_evenly_spaced(self):
        data = candidates(self.cfg, VID, limit=3)
        starts = [c["start_ms"] for c in data["candidates"]]
        self.assertEqual(len(starts), 3)
        self.assertGreater(starts[-1], 40_000)

    def test_no_scenes_falls_back_to_windows(self):
        with tempfile.TemporaryDirectory() as tmp:
            cfg = load_config(Path(tmp))
            db = Database(cfg.db_path)
            try:
                db.upsert_video({
                    "id": "vid_noscene", "source_kind": "local", "source_uri": "y.mp4",
                    "source_path": "y.mp4", "title": "noscene", "duration_ms": 60_000,
                    "status": "ready", "analysis_version": "0.2",
                })
            finally:
                db.close()
            data = candidates(cfg, "vid_noscene", limit=10)
            self.assertEqual(data["shots"], 4, "60s / 15s windows")
            self.assertEqual(data["candidates"][0]["start_ms"], 0)

    def test_missing_video_is_an_error_not_an_empty_list(self):
        with self.assertRaises(Exception):
            candidates(self.cfg, "vid_missing")

    def test_images_render_one_montage_of_the_candidates(self):
        from PIL import Image

        with tempfile.TemporaryDirectory() as tmp:
            cfg = load_config(Path(tmp))
            db = Database(cfg.db_path)
            try:
                db.upsert_video({
                    "id": "vid_sheet", "source_kind": "local", "source_uri": "s.mp4",
                    "source_path": "s.mp4", "title": "sheet", "duration_ms": 30_000,
                    "status": "ready", "analysis_version": "0.2",
                })
                db.insert_scenes("vid_sheet", [
                    {"start_ms": i * 10_000, "end_ms": (i + 1) * 10_000, "cut_score": 0.2}
                    for i in range(3)
                ])
                frames = []
                for i in range(3):
                    path = Path(tmp) / f"sheet{i}.jpg"
                    Image.new("RGB", (640, 360), (20 * i, 40, 80)).save(path)
                    frames.append({"pts_ms": i * 10_000 + 5000, "path": str(path)})
                db.insert_frames("vid_sheet", frames)
            finally:
                db.close()
            data = candidates(cfg, "vid_sheet", limit=3, images=True)
            self.assertTrue(data["sheet"])
            self.assertTrue(Path(data["sheet"]).exists())
            self.assertEqual(data["images"], [data["sheet"]])
            self.assertEqual(len(data["sheet_tiles"]), 3)
            from PIL import Image as PILImage
            with PILImage.open(data["sheet"]) as sheet:
                self.assertEqual(sheet.size, (960, 202), "3 tiles in one row, 320x180 + label")

    def test_without_images_no_sheet_is_built(self):
        data = candidates(self.cfg, VID, limit=3)
        self.assertNotIn("sheet", data)
        self.assertNotIn("images", data)

    def test_layout_never_leaves_blank_cells(self):
        # Fewer candidates than nine must re-flow, not leave a 3-column hole.
        self.assertEqual(_sheet_layout(1), (1, 1))
        self.assertEqual(_sheet_layout(2), (2, 1))
        self.assertEqual(_sheet_layout(3), (3, 1))
        self.assertEqual(_sheet_layout(4), (2, 2))
        self.assertEqual(_sheet_layout(5), (3, 2))
        self.assertEqual(_sheet_layout(6), (3, 2))
        self.assertEqual(_sheet_layout(7), (4, 2))
        self.assertEqual(_sheet_layout(8), (4, 2))
        self.assertEqual(_sheet_layout(9), (3, 3))

    def test_four_candidates_fill_a_2x2_sheet(self):
        from PIL import Image

        with tempfile.TemporaryDirectory() as tmp:
            cfg = load_config(Path(tmp))
            db = Database(cfg.db_path)
            try:
                db.upsert_video({
                    "id": "vid_four", "source_kind": "local", "source_uri": "f.mp4",
                    "source_path": "f.mp4", "title": "four", "duration_ms": 40_000,
                    "status": "ready", "analysis_version": "0.2",
                })
                db.insert_scenes("vid_four", [
                    {"start_ms": i * 10_000, "end_ms": (i + 1) * 10_000, "cut_score": 0.2}
                    for i in range(4)
                ])
                frames = []
                for i in range(4):
                    path = Path(tmp) / f"f{i}.jpg"
                    Image.new("RGB", (640, 360), (20 * i, 40, 80)).save(path)
                    frames.append({"pts_ms": i * 10_000 + 5000, "path": str(path)})
                db.insert_frames("vid_four", frames)
            finally:
                db.close()
            data = candidates(cfg, "vid_four", limit=9, images=True)
            from PIL import Image as PILImage
            with PILImage.open(data["sheet"]) as sheet:
                self.assertEqual(sheet.size, (640, 404), "2x2 tiles, no blank cells")


if __name__ == "__main__":
    unittest.main()

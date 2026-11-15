import unittest
from unittest.mock import patch

from video2agent.visual import (
    _is_ocr_noise,
    attach_ocr,
    build_ocr_tracks,
    label_scores,
    plan_ocr_budget,
    select_ocr_frames,
)


class VisualTests(unittest.TestCase):
    def test_unmeasured_text_returns_no_label(self):
        # `auto` ingest never OCRs, so text_coverage is unknown, not zero. Claiming a
        # label from an unmeasured field is how 91% of segments became `animation`.
        unmeasured = {"motion": 0.0055, "text_coverage": None, "edge_density": 0.173,
                      "line_score": 0.225, "color_entropy": 0.20, "static_ratio": 0.954, "grid_score": 0.0}
        self.assertEqual(label_scores(unmeasured), {})

    def test_a_scene_without_frames_is_unknown_not_missing(self):
        from video2agent.visual import visual_segments

        scenes = [{"start_ms": 0, "end_ms": 10_000, "keyframe_ms": 0},
                  {"start_ms": 10_000, "end_ms": 20_000, "keyframe_ms": 10_000}]
        frames = [{"pts_ms": 5_000, "motion": 0.0, "text_coverage": None, "edge_density": 0.1,
                   "line_score": 0.0, "sharpness": 0.5, "color_entropy": 0.1, "ocr_status": "unmeasured"}]
        segs = visual_segments(scenes, frames)
        self.assertEqual(len(segs), 2, "a scene without a frame must still be reported")
        self.assertEqual([s["label"] for s in segs], ["unknown", "unknown"])
        self.assertEqual(segs[0]["reason"], "text_unmeasured")
        self.assertEqual(segs[1]["reason"], "no_frame")

    def test_measured_text_still_labels_a_slide(self):
        from video2agent.visual import visual_segments

        scenes = [{"start_ms": 0, "end_ms": 10_000, "keyframe_ms": 0}]
        frames = [{"pts_ms": 5_000, "motion": 0.004, "text_coverage": 0.19, "edge_density": 0.12,
                   "line_score": 0.02, "sharpness": 0.9, "color_entropy": 0.10, "ocr_status": "ok"}]
        segs = visual_segments(scenes, frames)
        self.assertEqual(segs[0]["label"], "slide_like")
        self.assertGreater(segs[0]["score"], 0.5)

    def test_skipped_frames_do_not_dilute_the_measured_text(self):
        # One frame was read (0.19), five were skipped. Averaging their 0.0 in made the
        # value 0.0317 and flipped slide_like to talking_head on 18 live segments.
        from video2agent.visual import _aggregate

        frames = [{"pts_ms": 0, "ocr_status": "ok", "text_coverage": 0.19, "motion": 0.0,
                   "edge_density": 0.1, "line_score": 0.0, "sharpness": 0.5, "color_entropy": 0.1}]
        frames += [{"pts_ms": 1000 * i, "ocr_status": "skipped", "text_coverage": 0.0, "motion": 0.0,
                    "edge_density": 0.1, "line_score": 0.0, "sharpness": 0.5, "color_entropy": 0.1}
                   for i in range(1, 6)]
        sig = _aggregate(frames)
        self.assertEqual(sig["text_coverage"], 0.19)

    def test_table_needs_structure(self):
        table = {"motion": 0.008, "text_coverage": 0.098, "edge_density": 0.054,
                 "line_score": 0.05, "color_entropy": 0.123, "static_ratio": 0.933, "grid_score": 1.0}
        scores = label_scores(table)
        self.assertEqual(max(scores, key=scores.get), "table_like")

    def test_animation_beats_scattered_table_text(self):
        anim = {"motion": 0.024, "text_coverage": 0.031, "edge_density": 0.079,
                "line_score": 0.055, "color_entropy": 0.173, "static_ratio": 0.80, "grid_score": 1.0}
        scores = label_scores(anim)
        self.assertEqual(max(scores, key=scores.get), "animation")

    def test_ocr_noise(self):
        self.assertTrue(_is_ocr_noise("bilibili"))
        self.assertTrue(_is_ocr_noise("?"))
        self.assertFalse(_is_ocr_noise("注意力机制"))

    def test_ocr_prefilter_is_sparse_and_spread(self):
        frames = []
        for i in range(100):
            frames.append({
                "pts_ms": i * 1000,
                "line_score": 0.30 if i % 10 == 0 else 0.02,
                "edge_density": 0.12 if i % 10 == 0 else 0.01,
                "sharpness": 0.8,
                "motion": 0.0,
            })
        chosen = select_ocr_frames(frames, 10)
        self.assertLessEqual(len(chosen), 10)
        self.assertGreater(len(chosen), 0)
        self.assertEqual(len({id(f) for f in chosen}), len(chosen))
        self.assertTrue(all(f["line_score"] >= 0.30 for f in chosen))

    def test_ocr_reports_frame_progress(self):
        frames = [{
            "pts_ms": i * 1000,
            "path": f"frame_{i}.jpg",
            "line_score": 0.4,
            "edge_density": 0.2,
            "sharpness": 0.8,
            "motion": 0.0,
        } for i in range(3)]
        calls = []
        with patch("video2agent.visual.ocr_available", return_value=True), \
             patch("video2agent.visual.ocr_image", return_value=[]):
            attach_ocr(frames, max_frames=2, progress=lambda done, total, pts: calls.append((done, total, pts)))
        self.assertEqual(len(calls), 2)
        self.assertTrue(all(f.get("ocr_status") in ("ok", "empty") for f in frames if f.get("ocr_status") != "skipped"))
        self.assertTrue(all(total == len(calls) for _, total, _ in calls))
        self.assertTrue(all(pts % 1000 == 0 for _, _, pts in calls))

    def test_slide_is_not_animation(self):
        slide = {"motion": 0.0, "text_coverage": 0.089, "edge_density": 0.059,
                 "line_score": 0.05, "color_entropy": 0.109, "static_ratio": 1.0, "grid_score": 0.0}
        scores = label_scores(slide)
        self.assertEqual(max(scores, key=scores.get), "slide_like")

    def test_frame_text_track_keeps_table_together(self):
        boxes = [
            {"text": "方法", "confidence": 0.9, "bbox": [74, 330, 60, 20]},
            {"text": "准确率", "confidence": 0.9, "bbox": [374, 330, 60, 20]},
            {"text": "Transformer", "confidence": 0.9, "bbox": [74, 458, 120, 20]},
            {"text": "85%", "confidence": 0.9, "bbox": [374, 458, 50, 20]},
        ]
        frames = [{"pts_ms": 3000, "ocr": boxes}]
        tracks = build_ocr_tracks(frames)
        joined = [t for t in tracks if t.get("change_type") == "frame_text"]
        self.assertEqual(len(joined), 1)
        self.assertIn("准确率", joined[0]["text"])
        self.assertIn("85%", joined[0]["text"])
        self.assertIn(" | ", joined[0]["text"])
        # The row order follows the boxes' vertical position (330 before 458).
        self.assertLess(joined[0]["text"].index("方法"), joined[0]["text"].index("Transformer"))

    def test_frame_text_track_requires_three_boxes(self):
        frames = [{"pts_ms": 1000, "ocr": [
            {"text": "标题", "confidence": 0.9, "bbox": [10, 10, 40, 20]},
            {"text": "正文", "confidence": 0.9, "bbox": [10, 60, 40, 20]},
        ]}]
        tracks = build_ocr_tracks(frames)
        self.assertFalse([t for t in tracks if t.get("change_type") == "frame_text"])

    def test_ocr_budget_grows_with_scene_density(self):
        # 12-minute slide deck: 12 duration-rate frames, raised to the cap of 20.
        self.assertEqual(plan_ocr_budget(720_000, rate=1, cap=20, n_scenes=72), 20)
        # Static/talking-head video (one scene): keep the old duration rate.
        self.assertEqual(plan_ocr_budget(720_000, rate=1, cap=20, n_scenes=1), 12)
        # Short clip keeps the floor of 6.
        self.assertEqual(plan_ocr_budget(6_000, rate=1, cap=60, n_scenes=3), 6)
        # Deep profile may spend the full cap on dense slides.
        self.assertEqual(plan_ocr_budget(720_000, rate=4, cap=60, n_scenes=72), 60)


if __name__ == "__main__":
    unittest.main()

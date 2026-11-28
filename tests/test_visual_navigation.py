"""Zero-overhead visual navigation: long-range sheets, diverse picks, highlights, visual map."""
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from PIL import Image

from video2agent import cli, pipeline
from video2agent.config import load_config
from video2agent.db import Database
from video2agent.digest import _cached_audio_profile, _contact_sheet, digest
from video2agent.pipeline import candidates, visual_map
from video2agent.text import to_simplified, tokens_for_search
from video2agent.util import parse_time_ms
from video2agent.visual import pick_diverse_frames, visual_frame_highlights

VID = "vid_nav"


def fake_extract(_src, t, out, **_kwargs):
    Image.new("RGB", (320, 180), (int(t) % 255, 40, 80)).save(out)


def _gray_frames(root: Path, count: int, odd: dict[int, tuple[int, int, int]] | None = None):
    frames = []
    for i in range(count):
        path = root / f"g{i}.jpg"
        im = Image.new("RGB", (320, 180), (200, 200, 200))
        if odd and i in odd:
            im.paste(odd[i], (40, 40, 280, 140))
        im.save(path)
        frames.append({"pts_ms": i * 10_000, "path": str(path), "motion": 0.0})
    return frames


class LongRangeSheetTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.cfg = load_config(Path(self.tmp.name))
        media = Path(self.tmp.name) / "media.mp4"
        media.write_bytes(b"stub")
        with Database(self.cfg.db_path) as db:
            db.upsert_video({
                "id": VID, "source_kind": "local", "source_uri": str(media),
                "source_path": str(media), "title": "nav", "duration_ms": 60_000,
                "status": "ready", "analysis_version": "0.2",
            })

    def test_long_range_sheet_covers_the_whole_range(self):
        with patch.object(pipeline, "extract_frame", side_effect=fake_extract):
            data = pipeline.frames(self.cfg, VID, start_ms=0, end_ms=60_000, max_frames=12, sheet=True)
        codes = [w["code"] for w in data["warnings"]]
        self.assertIn("RANGE_SHEET_AUTO_COVERED", codes)
        self.assertNotIn("DENSE_WINDOW_TRUNCATED", codes)
        self.assertNotIn("DENSE_WINDOW_CLAMPED", codes)
        self.assertEqual(data["covered_ms"], 60_000)
        self.assertEqual(len(data["sheet_tiles"]), 12)
        self.assertEqual(data["images"], [data["sheet"]])
        times = [t["t_ms"] for t in data["sheet_tiles"]]
        self.assertGreater(times[-1], 50_000, "tiles must reach the end of the range")
        with Image.open(data["sheet"]) as sheet:
            self.assertEqual(sheet.size, (1280, 606), "12 tiles flow into a 4x3 sheet")

    def test_short_range_sheet_keeps_the_dense_window(self):
        with patch.object(pipeline, "extract_frame", side_effect=fake_extract):
            data = pipeline.frames(self.cfg, VID, start_ms=1_000, end_ms=4_000, fps=2, max_frames=6, sheet=True)
        self.assertNotIn("RANGE_SHEET_AUTO_COVERED", [w["code"] for w in data["warnings"]])

    def test_windows_allow_sixteen_tiles(self):
        with patch.object(pipeline, "extract_frame", side_effect=fake_extract):
            data = pipeline.frames(self.cfg, VID, start_ms=0, end_ms=60_000, windows=16)
        self.assertEqual(data["window_count"], 16)
        self.assertEqual(len(data["sheet_tiles"]), 16)

    def test_multi_at_sheet_packs_requested_timestamps(self):
        with patch.object(pipeline, "extract_frame", side_effect=fake_extract):
            data = pipeline.frames(self.cfg, VID, at_list_ms=[5_000, 22_500, 55_000], sheet=True)
        self.assertEqual([t["t_ms"] for t in data["sheet_tiles"]], [5_000, 22_500, 55_000])
        self.assertEqual(data["images"], [data["sheet"]])
        self.assertIn("moments_sheet_", Path(data["sheet"]).name)

    def test_cli_frames_accepts_comma_at_with_sheet(self):
        import io
        import json
        import os
        from contextlib import redirect_stdout

        buf = io.StringIO()
        with patch.dict(os.environ, {"VIDEO2AGENT_HOME": self.tmp.name}), \
             patch.object(pipeline, "extract_frame", side_effect=fake_extract):
            with redirect_stdout(buf):
                rc = cli.main(["frames", VID, "--at", "5.0s,22.5s,55s", "--sheet", "--json"])
        self.assertEqual(rc, 0)
        payload = json.loads(buf.getvalue())
        self.assertEqual([t["t_ms"] for t in payload["sheet_tiles"]], [5_000, 22_500, 55_000])
        self.assertEqual(payload["images"], [payload["sheet"]])


class DiversePickTests(unittest.TestCase):
    def test_picker_surfaces_a_brief_visual_change(self):
        with tempfile.TemporaryDirectory() as tmp:
            frames = _gray_frames(Path(tmp), 12, {7: (20, 20, 20)})
            picked = pick_diverse_frames(frames, 4)
            self.assertEqual(len(picked), 4)
            self.assertIn(70_000, [f["pts_ms"] for f in picked])
            times = [f["pts_ms"] for f in picked]
            self.assertEqual(times, sorted(times))
            self.assertLess(times[0], 30_000, "the start of the video stays covered")

    def test_uniform_frames_keep_the_earliest_per_stratum(self):
        with tempfile.TemporaryDirectory() as tmp:
            frames = _gray_frames(Path(tmp), 12)
            picked = pick_diverse_frames(frames, 4)
            self.assertEqual([f["pts_ms"] for f in picked], [0, 30_000, 60_000, 90_000])

    def test_contact_sheet_takes_nine_and_twelve_tiles(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            frames = _gray_frames(root, 12, {7: (20, 20, 20)})
            sheet9, _keys9, placed9 = _contact_sheet(frames, root / "out9", max_frames=9)
            self.assertEqual(placed9, 9)
            with Image.open(sheet9) as im9:
                self.assertEqual(im9.size, (960, 612), "9 tiles pack into a 3x3 grid")
            sheet, keys, placed = _contact_sheet(frames, root / "out", max_frames=12)
            self.assertEqual(placed, 12)
            with Image.open(sheet) as im:
                self.assertEqual(im.size, (1280, 612))

    def test_portrait_and_square_digest_sheets_keep_both_edges(self):
        for size, expected in (((180, 320), (540, 344)), ((300, 300), (720, 264))):
            with tempfile.TemporaryDirectory() as tmp:
                root = Path(tmp)
                frames = []
                for i in range(3):
                    path = root / f"p{i}.jpg"
                    im = Image.new("RGB", size, (40, 40, 40))
                    w, h = size
                    im.paste((230, 30, 30), (0, 0, w, h // 8))
                    im.paste((30, 210, 30), (0, h - h // 8, w, h))
                    im.save(path)
                    frames.append({"pts_ms": i * 1000, "path": str(path)})
                sheet, _keys, placed = _contact_sheet(frames, root / "out")
                self.assertEqual(placed, 3)
                with Image.open(sheet) as im:
                    self.assertEqual(im.size, expected)
                    tw = expected[0] // 3
                    th = expected[1] - 24
                    self.assertGreater(im.getpixel((tw // 2, 6))[0], 180, "top edge kept")
                    self.assertGreater(im.getpixel((tw // 2, th - 6))[1], 160, "bottom edge kept")


class AudioCacheTests(unittest.TestCase):
    def test_second_digest_reuses_the_audio_scan(self):
        with tempfile.TemporaryDirectory() as tmp:
            media = Path(tmp) / "clip.mp4"
            media.write_bytes(b"x" * 10)
            calls = []

            def fake(path, max_gaps=4):
                calls.append(path)
                return {"has_audio": True, "mean_dbfs": -20.0}

            with patch("video2agent.digest.audio_profile", side_effect=fake):
                first = _cached_audio_profile(str(media), Path(tmp) / "cache")
                second = _cached_audio_profile(str(media), Path(tmp) / "cache")
                media.write_bytes(b"y" * 20)
                third = _cached_audio_profile(str(media), Path(tmp) / "cache")
            self.assertEqual(first, second)
            self.assertEqual(len(calls), 2, "a changed file is scanned again, an unchanged one is not")
            self.assertEqual(third["has_audio"], True)


class HighlightTests(unittest.TestCase):
    def test_highlights_find_the_outlier_and_the_jump(self):
        with tempfile.TemporaryDirectory() as tmp:
            frames = _gray_frames(Path(tmp), 12, {7: (20, 20, 20)})
            result = visual_frame_highlights(frames, top_k=4)
            self.assertIn(70_000, [m["t_ms"] for m in result["novel_moments"]])
            self.assertIn(70_000, [m["t_ms"] for m in result["visual_jumps"]])

    def test_too_few_frames_return_nothing(self):
        with tempfile.TemporaryDirectory() as tmp:
            result = visual_frame_highlights(_gray_frames(Path(tmp), 2))
            self.assertEqual(result, {"novel_moments": [], "visual_jumps": []})


class _DbCase(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.cfg = load_config(Path(self.tmp.name))

    def add_video(self, vid, duration_ms=120_000):
        with Database(self.cfg.db_path) as db:
            db.upsert_video({
                "id": vid, "source_kind": "local", "source_uri": "x.mp4", "source_path": "x.mp4",
                "title": vid, "duration_ms": duration_ms, "status": "ready", "analysis_version": "0.2",
            })


class VisualMapTests(_DbCase):
    def test_unmeasured_map_keeps_unknown_labels_but_points_at_changes(self):
        self.add_video("vid_map")
        frames = _gray_frames(Path(self.tmp.name), 12, {7: (20, 20, 20)})
        for i, frame in enumerate(frames):
            frame["motion"] = 0.2 if i == 7 else 0.01
        with Database(self.cfg.db_path) as db:
            db.insert_frames("vid_map", frames)
            db.insert_visual_segments("vid_map", [
                {"start_ms": 0, "end_ms": 60_000, "label": "unknown", "score": 0.0,
                 "signals": {"motion": 0.2}, "scores": {}, "keyframe_ms": 0, "reason": "text_unmeasured"},
                {"start_ms": 60_000, "end_ms": 120_000, "label": "unknown", "score": 0.0,
                 "signals": {"motion": 0.01}, "scores": {}, "keyframe_ms": 60_000, "reason": "text_unmeasured"},
            ])
        data = visual_map(self.cfg, "vid_map")
        self.assertEqual([s["label"] for s in data["segments"]], ["unknown", "unknown"])
        self.assertEqual([s["activity"] for s in data["segments"]], ["high_motion", "static"])
        self.assertTrue(all("scores" not in s for s in data["segments"]))
        self.assertIn("note", data)
        highlights = data["visual_highlights"]
        self.assertIn(70_000, [m["t_ms"] for m in highlights["novel_moments"]])
        self.assertIn(70_000, [m["t_ms"] for m in highlights["motion_peaks"]])
        self.assertIn("timecode", highlights["novel_moments"][0])
        self.assertIn("timecode", highlights["motion_peaks"][0])
        self.assertIn("70.0s", highlights["inspect_at"].split(","))
        self.assertIn(highlights["inspect_at"], data["note"])
        self.assertTrue(all(parse_time_ms(p) >= 0 for p in highlights["inspect_at"].split(",")))

    def test_digest_highlights_gate_imperative_hint_on_transcript(self):
        self.add_video("vid_dig")
        frames = _gray_frames(Path(self.tmp.name), 12, {7: (20, 20, 20)})
        with Database(self.cfg.db_path) as db:
            db.insert_frames("vid_dig", frames)
        with patch("video2agent.digest._cached_audio_profile", return_value=None):
            no_text = digest(self.cfg, "vid_dig", max_frames=6)
        vh = no_text["visual_highlights"]
        self.assertIn("70.0s", vh["inspect_at"].split(","))
        self.assertIn(vh["inspect_at"], vh["hint"])
        self.assertNotIn("note", vh)

        self.add_video("vid_sub")
        long_text = "我们来看一下这个教程里怎么设置参数和面板，然后对照演示流程继续往下走。" * 6
        with Database(self.cfg.db_path) as db:
            db.insert_frames("vid_sub", frames)
            db.insert_segments("vid_sub", [{"start_ms": 0, "end_ms": 5000, "text": long_text,
                                            "source": "asr", "confidence": 1.0,
                                            "tokens": tokens_for_search(long_text)}])
        with patch("video2agent.digest._cached_audio_profile", return_value=None):
            with_text = digest(self.cfg, "vid_sub", max_frames=9)
        vh_sub = with_text["visual_highlights"]
        self.assertIn("inspect_at", vh_sub)
        self.assertNotIn("hint", vh_sub)
        self.assertIn("note", vh_sub)


class TraditionalQueryTests(_DbCase):
    def test_traditional_knob_matches_a_simplified_query(self):
        self.assertEqual(to_simplified("小旋鈕"), "小旋钮")
        self.add_video("vid_t2s", 90_000)
        text = "點位你看其實後面這個小旋鈕的"
        with Database(self.cfg.db_path) as db:
            db.insert_scenes("vid_t2s", [{"start_ms": 0, "end_ms": 20_000, "cut_score": 0.2},
                                          {"start_ms": 20_000, "end_ms": 40_000, "cut_score": 0.2}])
            db.insert_segments("vid_t2s", [{"start_ms": 25_000, "end_ms": 28_000, "text": text,
                                            "source": "asr", "confidence": 1.0,
                                            "tokens": tokens_for_search(text)}])
        result = candidates(self.cfg, "vid_t2s", query="小旋钮", limit=2)
        self.assertEqual(result["candidates"][0]["start_ms"], 20_000)
        self.assertGreater(result["candidates"][0]["matched_units"], 0)


class NoMatchPickTests(_DbCase):
    def test_no_match_candidates_favour_a_distinct_shot(self):
        self.add_video("vid_nm", 120_000)
        frames = _gray_frames(Path(self.tmp.name), 12, {7: (20, 20, 20)})
        with Database(self.cfg.db_path) as db:
            db.insert_scenes("vid_nm", [{"start_ms": i * 10_000, "end_ms": (i + 1) * 10_000, "cut_score": 0.2}
                                        for i in range(12)])
            db.insert_frames("vid_nm", frames)
        result = candidates(self.cfg, "vid_nm", limit=4)
        self.assertEqual(len(result["candidates"]), 4)
        self.assertIn(70_000, [c["keyframe_ms"] for c in result["candidates"]])


if __name__ == "__main__":
    unittest.main()

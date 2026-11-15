"""frames --sheet / --windows: one labelled image and an honest coverage report."""

import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from PIL import Image

from video2agent import pipeline
from video2agent.config import load_config
from video2agent.db import Database
from video2agent.util import Video2AgentError

VID = "vid_sheet_frames"


def fake_extract(_src, t, out, **_kwargs):
    Image.new("RGB", (320, 180), (int(t) % 255, 40, 80)).save(out)


class FramesSheetTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.cfg = load_config(Path(self.tmp.name))
        self.media = Path(self.tmp.name) / "media.mp4"
        self.media.write_bytes(b"stub")
        db = Database(self.cfg.db_path)
        try:
            db.upsert_video({
                "id": VID, "source_kind": "local", "source_uri": str(self.media),
                "source_path": str(self.media), "title": "sheet", "duration_ms": 60_000,
                "status": "ready", "analysis_version": "0.2",
            })
        finally:
            db.close()

    def test_window_sheet_is_one_image_with_a_tile_per_frame(self):
        with patch.object(pipeline, "extract_frame", side_effect=fake_extract):
            data = pipeline.frames(self.cfg, VID, start_ms=1_000, end_ms=4_000,
                                   fps=2, max_frames=6, sheet=True)
        self.assertTrue(data["ok"])
        self.assertTrue(Path(data["sheet"]).exists())
        self.assertEqual(data["images"], [data["sheet"]], "one image, not six")
        self.assertGreaterEqual(len(data["frames"]), 2)
        self.assertEqual(len(data["sheet_tiles"]), len(data["frames"]), "one tile per returned frame")
        # 6 frames is 3x2; a 3x2 sheet is 960x404.
        with Image.open(data["sheet"]) as sheet:
            self.assertEqual(sheet.size, (960, 404))
        self.assertTrue(all("path" not in row for row in data["frames"]), "no paths in the text payload")

    def test_sheet_without_a_window_is_not_forced(self):
        with patch.object(pipeline, "extract_frame", side_effect=fake_extract):
            data = pipeline.frames(self.cfg, VID, at_ms=1_000, count=1, sheet=True)
        self.assertNotIn("sheet", data)
        self.assertEqual(len(data["images"]), 1)

    def test_windows_cover_the_range_without_reading_it_all(self):
        with patch.object(pipeline, "extract_frame", side_effect=fake_extract):
            data = pipeline.frames(self.cfg, VID, start_ms=0, end_ms=60_000, windows=6)
        self.assertTrue(data["ok"])
        self.assertEqual(data["window_count"], 6)
        self.assertEqual(data["covered_ms"], 60_000)
        self.assertEqual(data["missing_ms"], 0)
        self.assertEqual(len(data["windows"]), 6)
        self.assertEqual(data["images"], [data["sheet"]])
        starts = [w["start_ms"] for w in data["windows"]]
        self.assertEqual(starts, [0, 10_000, 20_000, 30_000, 40_000, 50_000])
        # Midpoint sampling: one frame per window, not 60 seconds of frames.
        self.assertEqual(len(data["frames"]), 6)

    def test_windows_need_both_edges(self):
        with self.assertRaises(Video2AgentError) as ctx:
            pipeline.frames(self.cfg, VID, start_ms=0, windows=6)
        self.assertEqual(ctx.exception.code, "E_ARGS")
        self.assertTrue(ctx.exception.remedy)

    def test_two_ranges_do_not_share_a_sheet_file(self):
        # A fixed filename let a concurrent call overwrite the file another
        # caller was about to read: the image then showed a different range
        # than its own labels/timecodes.
        with patch.object(pipeline, "extract_frame", side_effect=fake_extract):
            first = pipeline.frames(self.cfg, VID, start_ms=1_000, end_ms=4_000,
                                    fps=2, max_frames=6, sheet=True)
            second = pipeline.frames(self.cfg, VID, start_ms=10_000, end_ms=14_000,
                                     fps=2, max_frames=6, sheet=True)
        self.assertNotEqual(first["sheet"], second["sheet"])
        self.assertTrue(Path(first["sheet"]).exists())
        self.assertTrue(Path(second["sheet"]).exists())


if __name__ == "__main__":
    unittest.main()

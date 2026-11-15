import tempfile
import unittest
from pathlib import Path

from PIL import Image

from video2agent.digest import _contact_sheet, _score_cues


class DigestSheetTests(unittest.TestCase):
    def test_sheet_has_six_tiles_and_labels(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            frames = []
            for i in range(6):
                path = root / f"f{i}.jpg"
                Image.new("RGB", (320, 180), (i * 30, 80, 120)).save(path)
                frames.append({"pts_ms": i * 1000, "path": str(path)})
            sheet, keys, placed = _contact_sheet(frames, root / "out")
            self.assertTrue(Path(sheet).exists())
            with Image.open(sheet) as im:
                self.assertEqual(im.size, (960, 408))
            self.assertEqual(placed, 6)
            self.assertEqual(len(keys), 6)
            self.assertEqual(keys[0]["timecode"], "00:00:00")
            self.assertEqual(keys[-1]["timecode"], "00:00:05")

    def test_frame_budget_is_honoured(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            frames = []
            for i in range(6):
                path = root / f"f{i}.jpg"
                Image.new("RGB", (320, 180), (i, i, i)).save(path)
                frames.append({"pts_ms": i * 1000, "path": str(path)})
            sheet, keys, placed = _contact_sheet(frames, root / "out", max_frames=2)
            self.assertEqual(placed, 2)
            self.assertEqual(len(keys), 2)
            with Image.open(sheet) as im:
                self.assertEqual(im.size, (640, 204))


class ScoreCueTests(unittest.TestCase):
    def test_score_like_lines_are_timestamped_once(self):
        cues = _score_cues([
            {"start_ms": 1000, "text": "Score 9 - 7"},
            {"start_ms": 2000, "text": "Score 9 - 7"},
            {"start_ms": 3000, "text": "2:1"},
        ])
        self.assertEqual([c["timecode"] for c in cues], ["00:00:01", "00:00:03"])
        self.assertEqual(cues[0]["text"], "Score 9 - 7")

    def test_dates_and_prose_are_not_scores(self):
        self.assertEqual(_score_cues([
            {"start_ms": 0, "text": "2024-01-01 release"},
            {"start_ms": 0, "text": "24-01-01"},
            {"start_ms": 0, "text": "2024 - 01 - 01"},
            {"start_ms": 0, "text": "chapter 3"},
            {"start_ms": 0, "text": "no digits here"},
        ]), [])

    def test_cues_are_bounded(self):
        tracks = [{"start_ms": i * 1000, "text": f"{i}-{i + 1}"} for i in range(1, 20)]
        self.assertEqual(len(_score_cues(tracks)), 8)

    def test_mixed_corrupt_frames_are_compacted(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            good1 = root / "good1.jpg"
            bad = root / "bad.jpg"
            good2 = root / "good2.jpg"
            Image.new("RGB", (320, 180), (10, 20, 30)).save(good1)
            bad.write_text("not an image", encoding="utf-8")
            Image.new("RGB", (320, 180), (40, 50, 60)).save(good2)
            frames = [{"pts_ms": 0, "path": str(good1)}, {"pts_ms": 1000, "path": str(bad)}, {"pts_ms": 2000, "path": str(good2)}]
            sheet, keys, placed = _contact_sheet(frames, root / "out")
            self.assertEqual(placed, 2)
            self.assertEqual([k["index"] for k in keys], [0, 1])
            with Image.open(sheet) as im:
                self.assertEqual(im.size, (640, 204))

    def test_corrupt_frames_do_not_make_a_blank_sheet(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            frames = []
            for i in range(3):
                path = root / f"bad{i}.jpg"
                path.write_text("not an image", encoding="utf-8")
                frames.append({"pts_ms": i * 1000, "path": str(path)})
            self.assertEqual(_contact_sheet(frames, root / "out"), (None, [], 0))

    def test_missing_files_do_not_make_a_sheet(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            frames = [{"pts_ms": 0, "path": str(root / "gone.jpg")}]
            self.assertEqual(_contact_sheet(frames, root / "out"), (None, [], 0))

    def test_empty_frames(self):
        self.assertEqual(_contact_sheet([], Path(tempfile.gettempdir())), (None, [], 0))

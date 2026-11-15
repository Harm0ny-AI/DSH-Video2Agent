import json
import shutil
import tempfile
import unittest
from pathlib import Path

from PIL import Image

from video2agent.config import load_config
from video2agent.db import Database
from video2agent.digest import digest

VID = "vid_digest_test"


class DigestIntegrationTests(unittest.TestCase):
    def test_budget_and_corrupt_frames(self):
        with tempfile.TemporaryDirectory() as tmp:
            cfg = load_config(Path(tmp))
            db = Database(cfg.db_path)
            try:
                db.upsert_video({
                    "id": VID, "source_kind": "local", "source_uri": "x.mp4", "source_path": "x.mp4",
                    "title": "digest", "duration_ms": 6000, "status": "ready", "analysis_version": "0.2",
                })
                frames = []
                for i in range(6):
                    path = Path(tmp) / f"f{i}.jpg"
                    Image.new("RGB", (320, 180), (i, 20, 30)).save(path)
                    frames.append({"pts_ms": i * 1000, "path": str(path)})
                db.insert_frames(VID, frames)
            finally:
                db.close()
            data = digest(cfg, VID, max_frames=2)
            self.assertEqual(len(data["keyframes"]), 2)
            self.assertTrue(Path(data["contact_sheet"]).exists())
            self.assertEqual(data["keyframes"][0]["timecode"], "00:00:00")

    def test_ocr_total_is_the_real_count(self):
        with tempfile.TemporaryDirectory() as tmp:
            cfg = load_config(Path(tmp))
            db = Database(cfg.db_path)
            try:
                db.upsert_video({
                    "id": VID + "_ocr", "source_kind": "local", "source_uri": "x.mp4",
                    "source_path": "x.mp4", "title": "ocr", "duration_ms": 60_000,
                    "status": "ready", "analysis_version": "0.2",
                })
                db.insert_ocr_tracks(VID + "_ocr", [
                    {"start_ms": i * 100, "end_ms": i * 100 + 90, "text": f"line {i}", "confidence": 0.9}
                    for i in range(90)
                ])
            finally:
                db.close()
            data = digest(cfg, VID + "_ocr")
            self.assertEqual(data["ocr_total"], 90, "the total must be the stored count, not the fetch cap")
            self.assertTrue(data["ocr_truncated"])
            self.assertEqual(len(data["ocr"]), 80)
            message = [w["message"] for w in data["warnings"] if w["code"] == "OCR_TRUNCATED"][0]
            self.assertIn("90", message)

    def test_truncated_transcript_is_marked_as_a_sample(self):
        with tempfile.TemporaryDirectory() as tmp:
            cfg = load_config(Path(tmp))
            db = Database(cfg.db_path)
            try:
                db.upsert_video({
                    "id": VID + "_sample", "source_kind": "local", "source_uri": "x.mp4",
                    "source_path": "x.mp4", "title": "sample", "duration_ms": 60_000,
                    "status": "ready", "analysis_version": "0.2",
                })
                db.insert_segments(VID + "_sample", [
                    {"start_ms": i * 1000, "end_ms": (i + 1) * 1000, "text": "x" * 300}
                    for i in range(10)
                ])
            finally:
                db.close()
            data = digest(cfg, VID + "_sample", max_chars=600)
            self.assertTrue(data["transcript_truncated"])
            self.assertGreater(data["next_start_ms"], 0)
            self.assertIn("DIGEST_SAMPLED", [w["code"] for w in data["warnings"]])

    def test_compact_uses_lines_and_is_smaller(self):
        with tempfile.TemporaryDirectory() as tmp:
            cfg = load_config(Path(tmp))
            db = Database(cfg.db_path)
            try:
                db.upsert_video({
                    "id": VID + "_compact", "source_kind": "local", "source_uri": "x.mp4",
                    "source_path": "x.mp4", "title": "compact", "duration_ms": 60_000,
                    "status": "ready", "analysis_version": "0.2",
                })
                db.insert_segments(VID + "_compact", [
                    {"start_ms": i * 1000, "end_ms": (i + 1) * 1000, "text": f"line {i}"}
                    for i in range(10)
                ])
            finally:
                db.close()
            verbose = digest(cfg, VID + "_compact")
            compact = digest(cfg, VID + "_compact", compact=True)
            self.assertEqual(compact["transcript_format"], "lines")
            self.assertIsInstance(compact["transcript"][0], str)
            self.assertIn("line 0", compact["transcript"][0])
            self.assertLess(len(json.dumps(compact)), len(json.dumps(verbose)))

    def test_corrupt_frames_get_a_warning_not_a_blank_sheet(self):
        with tempfile.TemporaryDirectory() as tmp:
            cfg = load_config(Path(tmp))
            db = Database(cfg.db_path)
            try:
                db.upsert_video({
                    "id": VID + "_bad", "source_kind": "local", "source_uri": "x.mp4", "source_path": "x.mp4",
                    "title": "digest", "duration_ms": 6000, "status": "ready", "analysis_version": "0.2",
                })
                bad = []
                for i in range(3):
                    path = Path(tmp) / f"bad{i}.jpg"
                    path.write_text("not a jpeg", encoding="utf-8")
                    bad.append({"pts_ms": i * 1000, "path": str(path)})
                db.insert_frames(VID + "_bad", bad)
            finally:
                db.close()
            data = digest(cfg, VID + "_bad")
            self.assertIsNone(data["contact_sheet"])
            self.assertEqual(data["keyframes"], [])
            codes = {w["code"] for w in data["warnings"]}
            self.assertIn("FRAMES_UNREADABLE", codes)

    def test_scene_cuts_ride_along_and_are_bounded(self):
        with tempfile.TemporaryDirectory() as tmp:
            cfg = load_config(Path(tmp))
            db = Database(cfg.db_path)
            try:
                db.upsert_video({
                    "id": VID + "_cuts", "source_kind": "local", "source_uri": "x.mp4",
                    "source_path": "x.mp4", "title": "cuts", "duration_ms": 40_000,
                    "status": "ready", "analysis_version": "0.2",
                })
                db.insert_scenes(VID + "_cuts", [
                    {"start_ms": i * 2000, "end_ms": (i + 1) * 2000, "cut_score": 0.2}
                    for i in range(20)
                ])
            finally:
                db.close()
            data = digest(cfg, VID + "_cuts")
            cuts = data["scene_cuts"]
            self.assertEqual(cuts["count"], 19, "20 scenes = 19 boundaries")
            self.assertEqual(len(cuts["cuts_ms"]), 16, "the hint budget is 16 cuts")
            self.assertTrue(cuts["truncated"])
            self.assertEqual(cuts["cuts_ms"][0], 2000, "first cut is the first boundary")
            # No media file on this record: unmeasured, not "silent".
            self.assertIsNone(data["audio"])

    @unittest.skipUnless(shutil.which("ffmpeg"), "ffmpeg not on PATH")
    def test_digest_reports_audio_loudness_and_silence(self):
        from video2agent.util import run

        with tempfile.TemporaryDirectory() as tmp:
            media = Path(tmp) / "clip.mp4"
            res = run([
                shutil.which("ffmpeg"), "-y", "-v", "error",
                "-f", "lavfi", "-i", "color=c=black:s=64x36:d=3",
                "-f", "lavfi", "-i", "sine=frequency=440:duration=3",
                "-shortest", "-c:v", "libx264", "-c:a", "aac", str(media),
            ], timeout=120)
            self.assertTrue(res.ok and media.exists(), res.stderr[-300:])
            cfg = load_config(Path(tmp))
            db = Database(cfg.db_path)
            try:
                db.upsert_video({
                    "id": VID + "_audio", "source_kind": "local", "source_uri": str(media),
                    "source_path": str(media), "title": "audio", "duration_ms": 3000,
                    "status": "ready", "analysis_version": "0.2",
                })
            finally:
                db.close()
            data = digest(cfg, VID + "_audio")
            audio = data["audio"]
            self.assertTrue(audio["has_audio"])
            self.assertIsNotNone(audio["mean_dbfs"])
            self.assertIsNotNone(audio["max_dbfs"])
            self.assertEqual(audio["silence_ratio"], 0.0, "a tone is scanned, not unknown")

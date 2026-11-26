import shutil
import subprocess
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from video2agent import cli, pipeline
from video2agent.config import Config
from video2agent.db import Database
from video2agent.links import canonical_video_url
from video2agent.util import Video2AgentError, sha256_file, stable_id


@unittest.skipUnless(shutil.which("ffmpeg") and shutil.which("ffprobe"), "FFmpeg required")
class CaptionReadinessTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.cfg = Config(Path(self.tmp.name))
        self.source = self.cfg.home / "salmon.mp4"
        subprocess.run(
            ["ffmpeg", "-loglevel", "error", "-f", "lavfi", "-i", "color=c=blue:s=160x120:d=4",
             "-c:v", "mpeg4", "-pix_fmt", "yuv420p", str(self.source)], check=True,
        )
        self.write_caption("original salmon transcript")

    def write_caption(self, text):
        self.source.with_suffix(".srt").write_text(
            f"1\n00:00:00,200 --> 00:00:03,800\n{text}\n", encoding="utf-8",
        )

    def new_job(self):
        with Database(self.cfg.db_path) as db:
            return db.create_job("ingest", str(self.source), options={"profile": "auto"})

    def test_caption_wait_and_point_evidence_work_while_visuals_are_pending(self):
        job_id = self.new_job()
        sample_times = pipeline._sample_times
        observed = {}

        def during_visuals(*args):
            job = cli._wait_job(self.cfg, job_id, timeout=0.1, wait_for="transcript")
            vid = job["video_id"]
            self.assertEqual(job["state"], "running")
            self.assertTrue(job["transcript_ready"])
            with self.assertRaisesRegex(Video2AgentError, "Job still running"):
                cli._wait_job(self.cfg, job_id, timeout=0.01)
            with self.assertRaises(Video2AgentError) as missing:
                pipeline.search(self.cfg, "salmon")
            self.assertEqual(missing.exception.code, "E_NO_READY_VIDEO")
            with self.assertRaises(Video2AgentError) as visual_only:
                pipeline.search(self.cfg, "salmon", video_id=vid, modalities=["ocr"])
            self.assertEqual(visual_only.exception.code, "E_NOT_READY")
            result = pipeline.search(self.cfg, "salmon", video_id=vid)
            self.assertEqual(result["results"][0]["start_ms"], 200)
            self.assertIn("VISUAL_ANALYSIS_PENDING", [w["code"] for w in result["warnings"]])
            with patch.object(pipeline, "ocr_available", return_value=False):
                point = pipeline.evidence(self.cfg, video_id=vid, at_ms=1000, image_budget=1)
            self.assertEqual(point["image_frame_ms"], [1000])
            self.assertTrue(point["transcript"])
            observed["evidence_id"] = point["evidence_id"]
            return sample_times(*args)

        with patch.object(pipeline, "_sample_times", side_effect=during_visuals):
            done = cli._run_job(job_id, self.cfg)
        vid = done["video_id"]
        with Database(self.cfg.db_path) as db:
            self.assertEqual(db.get_video(vid)["status"], "ready")
            self.assertIsNone(db.active_caption_job(db.get_video(vid)))
            self.assertEqual(len(db.get_segments(vid)), 1)
        replay = pipeline.evidence(self.cfg, video_id=vid, evidence_id=observed["evidence_id"])
        self.assertEqual(replay["image_frame_ms"], [1000])
        self.assertEqual(pipeline.search(self.cfg, "salmon")["results"][0]["video_id"], vid)

    def test_canceled_caption_is_hidden_and_retry_replaces_it(self):
        job_id = self.new_job()
        with patch.object(pipeline, "_sample_times", side_effect=Video2AgentError("E_CANCELED", "test cancel")):
            with self.assertRaises(Video2AgentError):
                cli._run_job(job_id, self.cfg)
        job = cli._wait_job(self.cfg, job_id, wait_for="transcript")
        self.assertEqual(job["state"], "canceled")
        self.assertNotIn("transcript_ready", job)
        with self.assertRaises(Video2AgentError):
            pipeline.search(self.cfg, "original", video_id=job["video_id"])
        self.write_caption("new salmon transcript")
        done = cli._run_job(self.new_job(), self.cfg)
        with Database(self.cfg.db_path) as db:
            self.assertEqual([s["text"] for s in db.get_segments(done["video_id"])], ["new salmon transcript"])


class AnalyzeFailureStatusTest(unittest.TestCase):
    def test_failed_analyze_marks_video_failed(self):
        home = tempfile.mkdtemp(prefix="vp-analyze-fail-")
        cfg = Config(Path(home))
        from video2agent import cli as cli_module

        with Database(cfg.db_path) as db:
            job_id = db.create_job("ingest", "local:x", video_id="vid_t1", options={})
            db.update_job(job_id, state="running", stage="transcribing", progress=0.1, message="running")
            db.upsert_video({
                "id": "vid_t1", "source_kind": "local", "source_uri": "local:x",
                "source_path": "x", "sha256": None, "title": "t", "duration_ms": 1000,
                "width": None, "height": None, "fps": None, "language": None,
                "platform": "local", "status": "analyzing", "analysis_version": "1",
                "meta_json": "{}", "warnings_json": "[]",
                "created_at": "2026-11-14T00:00:00+00:00", "updated_at": "2026-11-14T00:00:00+00:00",
            })

        def boom(*args, **kwargs):
            raise Video2AgentError("E_ASR_NOT_CONFIGURED", "no model", "install one")

        with patch.object(cli_module, "analyze", boom):
            with self.assertRaises(Video2AgentError):
                cli_module._run_job(job_id, cfg)

        with Database(cfg.db_path) as db:
            video = db.get_video("vid_t1")
        self.assertEqual(video.get("status"), "failed")

    def test_waiting_reconciles_a_worker_that_has_already_exited(self):
        cfg = Config(Path(tempfile.mkdtemp(prefix="vp-analyze-wait-")))
        with Database(cfg.db_path) as db:
            job_id = db.create_job("ingest", "local:x")
            db.update_job(job_id, state="running", pid=12345)
        with patch("video2agent.db.pid_alive", return_value=False):
            result = cli._wait_job(cfg, job_id, timeout=1)
        self.assertEqual(result["state"], "failed")
        self.assertEqual(result["error_code"], "E_WORKER_LOST")

    @unittest.skipUnless(shutil.which("ffmpeg") and shutil.which("ffprobe"), "FFmpeg required")
    def test_rebuild_failure_rolls_back_and_success_keeps_old_evidence(self):
        cfg = Config(Path(tempfile.mkdtemp(prefix="vp-rebuild-")))
        source = cfg.home / "sample.mp4"
        subprocess.run(
            ["ffmpeg", "-loglevel", "error", "-f", "lavfi", "-i", "color=c=blue:s=160x120:d=4",
             "-c:v", "libx264", "-pix_fmt", "yuv420p", str(source)], check=True,
        )
        source.with_suffix(".srt").write_text(
            "1\n00:00:00,200 --> 00:00:03,800\noriginal salmon transcript\n", encoding="utf-8",
        )
        video_id = pipeline.analyze(cfg, str(source), profile="auto")["video_id"]
        with patch.object(pipeline, "ocr_available", return_value=False):
            original = pipeline.evidence(cfg, video_id=video_id, at_ms=900, image_budget=1)
        old_image = Path(original["images"][0])
        old_bytes = old_image.read_bytes()
        source.with_suffix(".srt").write_text(
            "1\n00:00:00,200 --> 00:00:03,800\nreplacement marlin transcript\n", encoding="utf-8",
        )
        with Database(cfg.db_path) as db:
            job_id = db.create_job("ingest", str(source), options={"force": True, "profile": "auto"})

        def fail_write(*args, **kwargs):
            # A separate reader must still see the previous committed index while the
            # writer is in the middle of replacing it.
            self.assertTrue(pipeline.search(cfg, "salmon")["results"])
            raise Video2AgentError("E_TEST_FAULT", "interrupted index write")

        with patch.object(Database, "insert_frames", side_effect=fail_write), self.assertRaises(Video2AgentError) as error:
            cli._run_job(job_id, cfg)
        self.assertEqual(error.exception.code, "E_TEST_FAULT")
        self.assertTrue(pipeline.search(cfg, "salmon")["results"])
        with Database(cfg.db_path) as db:
            self.assertEqual(db.get_job(job_id)["state"], "failed")
            self.assertEqual(db.get_video(video_id)["status"], "ready")

        with Database(cfg.db_path) as db:
            canceled = db.create_job("ingest", str(source), options={"force": True, "profile": "auto"})
        build_visual = pipeline.visual_segments

        def cancel_before_publish(*args, **kwargs):
            cli._cancel_marker(cfg, canceled).touch()
            return build_visual(*args, **kwargs)

        with patch.object(pipeline, "visual_segments", side_effect=cancel_before_publish):
            with self.assertRaises(Video2AgentError) as error:
                cli._run_job(canceled, cfg)
        self.assertEqual(error.exception.code, "E_CANCELED")
        with Database(cfg.db_path) as db:
            self.assertEqual(db.get_job(canceled)["state"], "canceled")
        self.assertTrue(pipeline.search(cfg, "salmon")["results"])

        pipeline.analyze(cfg, str(source), profile="auto", force=True)
        self.assertTrue(pipeline.search(cfg, "marlin")["results"])
        self.assertFalse(pipeline.search(cfg, "salmon")["results"])
        replay = pipeline.evidence(cfg, video_id=video_id, evidence_id=original["evidence_id"])
        self.assertEqual(replay["images"], original["images"])
        self.assertEqual(old_image.read_bytes(), old_bytes)
        self.assertEqual(replay["transcript"], original["transcript"])

    def test_reingest_of_released_media_checks_bytes_and_preserves_index(self):
        cfg = Config(Path(tempfile.mkdtemp(prefix="vp-restore-media-")))
        url = canonical_video_url("BV1test00001")
        video_id = stable_id("vid", url)
        fetched = cfg.home / "fetched.mp4"
        fetched.write_bytes(b"matching sample bytes")
        original_path = cfg.media_dir / video_id / "source.mp4"
        with Database(cfg.db_path) as db:
            db.upsert_video({
                "id": video_id, "source_kind": "url", "source_uri": url, "source_path": str(original_path),
                "title": "sample", "duration_ms": 4000, "status": "ready", "sha256": sha256_file(fetched),
                "media_released_at": "2026-11-24T00:00:00+00:00",
            })
            db.insert_segments(video_id, [{"start_ms": 0, "end_ms": 1000, "text": "prior", "tokens": "prior"}])
        resolved = {
            "id": video_id, "kind": "url", "uri": url, "path": str(fetched),
            "probe": {"duration_ms": 4000},
        }
        with patch.object(pipeline, "resolve_source", return_value={**resolved, "sha256": "different"}):
            with self.assertRaises(Video2AgentError) as failure:
                pipeline.analyze(cfg, url)
        self.assertEqual(failure.exception.code, "E_SOURCE_CHANGED")
        with Database(cfg.db_path) as db:
            self.assertEqual(db.get_video(video_id)["source_path"], str(original_path))
        self.assertTrue(pipeline.search(cfg, "prior")["results"])

        with patch.object(pipeline, "resolve_source", return_value={**resolved, "sha256": sha256_file(fetched)}) as download:
            self.assertEqual(pipeline.analyze(cfg, url)["video_id"], video_id)
            self.assertIn("cache_slot", download.call_args.kwargs)
        with Database(cfg.db_path) as db:
            video = db.get_video(video_id)
            self.assertEqual(video["source_path"], str(fetched))
            self.assertIsNone(video["media_released_at"])
            self.assertEqual(db.get_segments(video_id)[0]["text"], "prior")

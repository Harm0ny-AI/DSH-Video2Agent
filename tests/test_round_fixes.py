import tempfile
import unittest
from pathlib import Path

from video2agent.config import load_config
from video2agent.db import Database
from video2agent.pipeline import evidence, search
from video2agent.util import stable_id

VID = "vid_roundfix000001"


class RoundFixTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.cfg = load_config(Path(self.tmp.name))
        with Database(self.cfg.db_path) as db:
            db.upsert_video({
                "id": VID, "source_kind": "local", "source_uri": "x.mp4", "source_path": "x.mp4",
                "title": "Q K V 原理", "duration_ms": 60_000, "status": "ready",
                "analysis_version": "0.1",
            })
            db.insert_segments(VID, [{
                "id": stable_id("seg", VID, 1000), "start_ms": 1000, "end_ms": 3000,
                "text": "matrix multiplication of attention", "source": "asr",
            }])
            db.insert_ocr_tracks(VID, [{
                "id": stable_id("ocr", VID, 1000), "text": "注意力 Q K V", "start_ms": 1000, "end_ms": 1000,
                "confidence": 0.9, "bbox": [0, 0, 10, 10], "stability": None, "change_type": "appear",
            }])

    def test_modalities_filter_applies_to_every_source(self):
        only_text = search(self.cfg, "matrix multiplication", limit=20, modalities=["transcript"])
        tags = [tuple(r.get("modalities") or []) for r in only_text["results"]]
        self.assertTrue(tags, "the transcript row should match")
        for tag in tags:
            self.assertTrue({"transcript", "caption", "asr", "segment"} & set(tag), tag)
        only_ocr = search(self.cfg, "注意力", limit=20, modalities=["ocr"])
        for row in only_ocr["results"]:
            self.assertIn("ocr", row.get("modalities") or [])

    def test_old_analysis_is_declared_in_evidence(self):
        payload = evidence(self.cfg, video_id=VID, at_ms=1000, image_budget=0)
        codes = [w["code"] for w in payload["warnings"]]
        self.assertIn("STALE_ANALYSIS", codes)

    def test_a_dead_worker_is_not_reported_as_running(self):
        import os

        with Database(self.cfg.db_path) as db:
            job_id = db.create_job("ingest", "x.mp4")
            db.update_job(job_id, state="running", pid=999_999)
            # Reading alone must not write (a UI poll would fail a live job).
            self.assertEqual(db.get_job(job_id)["state"], "running")
            job = db.reconcile_job(job_id)
            self.assertEqual(job["state"], "failed")
            self.assertEqual(job["error_code"], "E_WORKER_LOST")
            live_id = db.create_job("ingest", "y.mp4")
            db.update_job(live_id, state="running", pid=os.getpid())
            self.assertEqual(db.reconcile_job(live_id)["state"], "running")

    def test_modalities_filter_applies_to_the_literal_fallback_too(self):
        # The earliest return (literal fallback) used to bypass the filter: asking for
        # transcript returned the OCR row.
        only_text = search(self.cfg, "Q K V", limit=10, modalities=["transcript"])
        self.assertEqual(only_text["results"], [])
        only_ocr = search(self.cfg, "Q K V", limit=10, modalities=["ocr"])
        self.assertTrue(only_ocr["results"])
        for row in only_ocr["results"]:
            self.assertIn("ocr", row.get("modalities") or [])

    def test_a_single_letter_is_not_a_search_term(self):
        # "C++" used to become the term "c" and match every "C 语言教程" title.
        from video2agent.text import literal_terms

        self.assertNotIn("c", literal_terms("C++"))
        # Shorthand letters are still legitimate when the whole query is letters.
        self.assertIn("q", literal_terms("Q K V"))

    def test_a_finished_job_is_not_overwritten_by_reconciliation(self):
        with Database(self.cfg.db_path) as db:
            job_id = db.create_job("ingest", "x.mp4")
            db.update_job(job_id, state="running", pid=999_999)
            db.update_job(job_id, state="ready")  # worker finishes first
            self.assertEqual(db.reconcile_job(job_id)["state"], "ready")


if __name__ == "__main__":
    unittest.main()

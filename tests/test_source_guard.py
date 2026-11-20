import tempfile
import unittest
from pathlib import Path

from video2agent import cli, pipeline
from video2agent.config import load_config
from video2agent.util import Video2AgentError


def _video(path, *, size, mtime_ns, sha=None, released=None):
    return {
        "id": "vid_test", "source_path": str(path), "sha256": sha,
        "source_size": size, "source_mtime_ns": mtime_ns,
        "media_released_at": released,
    }


class SourceGuardTest(unittest.TestCase):
    def setUp(self):
        self.dir = Path(tempfile.mkdtemp(prefix="vp-src-"))
        self.file = self.dir / "video.mp4"
        self.file.write_bytes(b"abc" * 10)
        stat = self.file.stat()
        self.size, self.mtime = int(stat.st_size), int(stat.st_mtime_ns)

    def test_unchanged_source_passes(self):
        pipeline._require_media(_video(self.file, size=self.size, mtime_ns=self.mtime))

    def test_size_change_is_refused(self):
        with self.assertRaises(Video2AgentError) as ctx:
            pipeline._require_media(_video(self.file, size=self.size - 1, mtime_ns=self.mtime))
        self.assertEqual(ctx.exception.code, "E_SOURCE_CHANGED")

    def test_same_size_new_content_is_refused_after_touch(self):
        import hashlib
        import os
        original = self.file.read_bytes()
        old_hash = hashlib.sha256(original).hexdigest()
        self.file.write_bytes(b"xyz" * (len(original) // 3))
        os.utime(self.file, ns=(self.mtime, self.mtime + 1_000_000))
        with self.assertRaises(Video2AgentError) as ctx:
            pipeline._require_media(_video(self.file, size=self.size, mtime_ns=self.mtime,
                                           sha=old_hash))
        self.assertEqual(ctx.exception.code, "E_SOURCE_CHANGED")

    def test_missing_media_says_why(self):
        self.file.unlink()
        with self.assertRaises(Video2AgentError) as ctx:
            pipeline._require_media(_video(self.file, size=self.size, mtime_ns=self.mtime,
                                           released="2026-11-20T00:00:00+00:00"))
        self.assertEqual(ctx.exception.code, "E_MEDIA_MISSING")
        self.assertIn("缓存策略", ctx.exception.message)


class EvidenceSnapshotTest(unittest.TestCase):
    def _payload(self, text):
        return {"image_frame_ms": [1000], "ocr": [{"start_ms": 1000, "text": text}],
                "transcript": [], "visual": []}

    def test_same_question_same_content_is_stable(self):
        video = {"sha256": "a" * 64}
        one = pipeline._evidence_snapshot_id(video, "vid", at_ms=1000, start=0, end=2000,
                                            payload=self._payload("蓝莓"))
        two = pipeline._evidence_snapshot_id(video, "vid", at_ms=1000, start=0, end=2000,
                                            payload=self._payload("蓝莓"))
        self.assertEqual(one, two)
        self.assertTrue(one.startswith("ev_"))

    def test_new_source_version_is_a_new_snapshot(self):
        old = pipeline._evidence_snapshot_id({"sha256": "a" * 64}, "vid", at_ms=1000, start=0,
                                            end=2000, payload=self._payload("蓝莓"))
        new = pipeline._evidence_snapshot_id({"sha256": "b" * 64}, "vid", at_ms=1000, start=0,
                                            end=2000, payload=self._payload("蓝莓"))
        self.assertNotEqual(old, new, "a citation must not be overwritten after the source changed")

    def test_new_content_is_a_new_snapshot(self):
        one = pipeline._evidence_snapshot_id({"sha256": "a" * 64}, "vid", at_ms=1000, start=0,
                                            end=2000, payload=self._payload("蓝莓"))
        two = pipeline._evidence_snapshot_id({"sha256": "a" * 64}, "vid", at_ms=1000, start=0,
                                            end=2000, payload=self._payload("草莓"))
        self.assertNotEqual(one, two)


class IngestCancelLockTest(unittest.TestCase):
    def test_cancel_after_acquiring_releases_the_lock(self):
        with tempfile.TemporaryDirectory() as td:
            cfg = load_config(Path(td))
            (cfg.home / "jobs").mkdir(parents=True, exist_ok=True)
            lock = cfg.home / "jobs" / ".ingest.lock"
            calls = {"n": 0}

            class _Marker:
                def __init__(self, flag):
                    self.flag = flag

                def exists(self):
                    return self.flag

            def fake_marker(_cfg, _job_id):
                calls["n"] += 1
                return _Marker(calls["n"] > 1)

            original = cli._cancel_marker
            cli._cancel_marker = fake_marker
            try:
                with self.assertRaises(Video2AgentError) as ctx:
                    with cli._ingest_slot(cfg, "job_test"):
                        pass
            finally:
                cli._cancel_marker = original
            self.assertEqual(ctx.exception.code, "E_CANCELED")
            self.assertFalse(lock.exists(), "a cancelled ingest left the queue lock behind")


if __name__ == "__main__":
    unittest.main()

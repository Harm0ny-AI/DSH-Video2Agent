import json
import os
import subprocess
import sys
import tempfile
import time
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / "src"
FIXTURE = ROOT / "tests" / "fixtures" / "demo.mp4"


def run_cli(args, home):
    env = os.environ.copy()
    env["PYTHONPATH"] = str(SRC)
    env["PYTHONIOENCODING"] = "utf-8"
    return subprocess.run(
        [sys.executable, "-m", "video2agent", *args, "--home", str(home)],
        capture_output=True, text=True, encoding="utf-8", errors="replace", env=env, cwd=str(ROOT),
    )


class CliTests(unittest.TestCase):
    @unittest.skipUnless(FIXTURE.exists(), "fixture missing")
    def test_ingest_search_evidence_export(self):
        with tempfile.TemporaryDirectory() as tmp:
            home = Path(tmp) / "home"
            p = run_cli(["ingest", str(FIXTURE), "--profile", "fast", "--json"], home)
            self.assertEqual(p.returncode, 0, p.stderr)
            data = json.loads(p.stdout)
            self.assertTrue(data["ok"], data)
            vid = data["video_id"]
            p = run_cli(["search", "表格", "--video", vid, "--json"], home)
            self.assertEqual(p.returncode, 0, p.stderr)
            results = json.loads(p.stdout)["results"]
            self.assertTrue(results)
            self.assertGreaterEqual(results[0]["start_ms"], 0)
            p = run_cli(["evidence", vid, "--at", "2.5", "--images", "2", "--json"], home)
            self.assertEqual(p.returncode, 0, p.stderr)
            ev = json.loads(p.stdout)
            self.assertTrue(ev["ok"])
            self.assertTrue(ev["images"])
            p = run_cli(["export", vid, "--format", "html", "--out", str(Path(tmp) / "report.html"), "--json"], home)
            self.assertEqual(p.returncode, 0, p.stderr)
            self.assertTrue(Path(json.loads(p.stdout)["path"]).exists())
            p = run_cli(["bench", vid, "--queries", "表格", "--json"], home)
            self.assertEqual(p.returncode, 0, p.stderr)
            bench = json.loads(p.stdout)
            self.assertTrue(bench["ok"])
            self.assertGreater(bench["queries"][0]["search_ms"], 0)
            self.assertGreaterEqual(bench["latency_ms"]["search_p95"], bench["latency_ms"]["search_p50"])

            p = run_cli(["overview", vid, "--json"], home)
            self.assertEqual(p.returncode, 0, p.stderr)
            overview = json.loads(p.stdout)
            self.assertIn("n_frames", overview["metrics"])
            self.assertEqual(overview["metrics"]["n_frames"], overview["counts"]["frames"])

            p = run_cli(["transcript", vid, "--json"], home)
            self.assertEqual(p.returncode, 0, p.stderr)
            self.assertTrue(json.loads(p.stdout)["lines"])

            p = run_cli(["transcript", vid, "--json", "--full"], home)
            self.assertEqual(p.returncode, 0, p.stderr)
            self.assertTrue(json.loads(p.stdout)["segments"])

            p = run_cli(["map", vid, "--json"], home)
            self.assertEqual(p.returncode, 0, p.stderr)
            self.assertTrue(json.loads(p.stdout)["segments"])

            out_dir = Path(tmp) / "frames"
            p = run_cli(["frames", vid, "--at", "2.5", "--count", "2", "--out", str(out_dir), "--json"], home)
            self.assertEqual(p.returncode, 0, p.stderr)
            self.assertEqual(len(json.loads(p.stdout)["images"]), 2)

            p = run_cli(["stats", "--json"], home)
            self.assertEqual(p.returncode, 0, p.stderr)
            stats = json.loads(p.stdout)
            from video2agent.db import SCHEMA_VERSION

            self.assertEqual(stats["db"]["schema_version"], SCHEMA_VERSION)

            p = run_cli(["gc", "--dry-run", "--json"], home)
            self.assertEqual(p.returncode, 0, p.stderr)
            self.assertTrue(json.loads(p.stdout)["ok"])

            # Past-the-end requests must be one consistent error, not three
            # different behaviours (inverted range / empty success / bare E_FRAME).
            for args in (
                ["evidence", vid, "--at", "99", "--images", "0", "--json"],
                ["transcript", vid, "--start", "99", "--json"],
                ["frames", vid, "--at", "99", "--count", "1", "--json"],
            ):
                p = run_cli(args, home)
                self.assertNotEqual(p.returncode, 0, f"{args[0]} should reject a time past the end")
                err = json.loads(p.stdout)["error"]
                self.assertEqual(err["code"], "E_OUT_OF_RANGE", f"{args[0]}: {err}")
                self.assertTrue(err.get("remedy"), f"{args[0]} error needs a remedy")

            # An in-range request says what it was asked for versus what the media has.
            p = run_cli(["evidence", vid, "--at", "2.0", "--images", "0", "--json"], home)
            self.assertEqual(p.returncode, 0, p.stderr)
            ev = json.loads(p.stdout)
            self.assertEqual(ev["requested_ms"], 2000)
            self.assertEqual(ev["media_end_ms"], overview["duration_ms"])
            self.assertLessEqual(ev["range"]["start_ms"], ev["range"]["end_ms"], "range must not invert")

            # Cache expiry frees media but must not empty the library. Age the
            # record, let the auto policy run, then prove the text is still here
            # and the media claim is honest.
            from video2agent.db import Database

            with Database(home / "library.db") as db:
                db.conn.execute("UPDATE videos SET updated_at=?, created_at=? WHERE id=?",
                                ["2026-01-01T00:00:00+00:00", "2026-01-01T00:00:00+00:00", vid])
                db.conn.commit()
            (home / "ui-settings.json").parent.mkdir(parents=True, exist_ok=True)
            (home / "ui-settings.json").write_text(
                json.dumps({"cacheExpire": True, "cacheDays": 1, "cacheLimitEnabled": False}),
                encoding="utf-8")
            p = run_cli(["gc", "--auto", "--json"], home)
            self.assertEqual(p.returncode, 0, p.stderr)
            released = [e for e in json.loads(p.stdout)["evicted"] if e.get("video_id") == vid]
            self.assertTrue(released, "the aged media must be released")
            p = run_cli(["list", "--json"], home)
            self.assertEqual(p.returncode, 0, p.stderr)
            self.assertIn(vid, [v["id"] for v in json.loads(p.stdout)["videos"]],
                          "cache expiry deleted the library record")
            p = run_cli(["search", "表格", "--video", vid, "--json"], home)
            self.assertEqual(p.returncode, 0, p.stderr)
            self.assertTrue(json.loads(p.stdout)["results"], "released media lost the searchable text")
            p = run_cli(["overview", vid, "--json"], home)
            self.assertEqual(p.returncode, 0, p.stderr)
            released_overview = json.loads(p.stdout)
            caps = released_overview["capabilities"]
            self.assertTrue(caps["media"], "a local file is the user's own and must stay put")
            self.assertFalse(caps.get("media_released"))
            self.assertFalse((home / "derived" / vid).exists(), "frame cache must be freed")
            # Frames can still be cut from the user's own source on demand.
            p = run_cli(["evidence", vid, "--at", "2.5", "--images", "1", "--json"], home)
            self.assertEqual(p.returncode, 0, p.stderr)
            self.assertTrue(json.loads(p.stdout)["images"])
            # Deleting knowledge is a separate, explicit act: --purge removes the
            # record that a release deliberately kept.
            p = run_cli(["gc", "--auto", "--purge", "--json"], home)
            self.assertEqual(p.returncode, 0, p.stderr)
            purged = [e for e in json.loads(p.stdout)["evicted"] if e.get("video_id") == vid]
            self.assertTrue(purged, "an explicit purge must delete the released record")
            p = run_cli(["list", "--json"], home)
            self.assertEqual(p.returncode, 0, p.stderr)
            self.assertNotIn(vid, [v["id"] for v in json.loads(p.stdout)["videos"]])


class GcCacheDefaultsTests(unittest.TestCase):
    """The Host's gc --auto applies the same cache policy the settings page shows."""

    def _seed(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        home = Path(tmp.name) / "home"
        from video2agent.config import load_config
        from video2agent.db import Database

        cfg = load_config(home)
        vid = "vid_gc_row"
        (cfg.media_dir / vid).mkdir(parents=True)
        (cfg.derived_dir / vid / "frames").mkdir(parents=True)
        (cfg.media_dir / vid / "source.mp4").write_bytes(b"x" * 1024)
        (cfg.derived_dir / vid / "frames" / "f.jpg").write_bytes(b"y" * 512)
        old = "2026-01-01T00:00:00+00:00"
        with Database(cfg.db_path) as db:
            db.upsert_video({
                "id": vid, "source_kind": "url", "source_uri": "test://" + vid,
                "source_path": str(cfg.media_dir / vid / "source.mp4"),
                "title": "aged", "duration_ms": 1000, "status": "ready",
                "created_at": old,
            })
            db.conn.execute("UPDATE videos SET created_at=?, updated_at=? WHERE id=?", [old, old, vid])
            db.conn.commit()
        return home, vid, cfg

    def _gc(self, home, defaults):
        p = run_cli(["gc", "--auto", "--json", "--cache-defaults", json.dumps(defaults)], home)
        self.assertEqual(p.returncode, 0, p.stderr)
        return json.loads(p.stdout)

    def test_row_config_off_keeps_the_cache_without_a_settings_file(self):
        home, vid, cfg = self._seed()
        data = self._gc(home, {"cacheExpire": False, "cacheDays": 1,
                               "cacheLimitEnabled": False, "cacheLimitGb": 20})
        self.assertFalse(data["policy"]["expire"])
        self.assertFalse(data["policy"].get("corrupt"))
        self.assertEqual(data["evicted"], [])
        self.assertTrue((cfg.media_dir / vid / "source.mp4").exists())

    def test_settings_file_wins_over_row_config(self):
        home, vid, cfg = self._seed()
        (home / "ui-settings.json").write_text(
            json.dumps({"cacheExpire": True, "cacheDays": 1}), encoding="utf-8")
        data = self._gc(home, {"cacheExpire": False, "cacheDays": 30,
                               "cacheLimitEnabled": False, "cacheLimitGb": 20})
        self.assertTrue(data["policy"]["expire"])
        self.assertIn(vid, [e.get("video_id") for e in data["evicted"]])

    def test_corrupt_settings_file_fails_closed_despite_row_config(self):
        home, vid, cfg = self._seed()
        (home / "ui-settings.json").write_text("{not json", encoding="utf-8")
        data = self._gc(home, {"cacheExpire": True, "cacheDays": 1,
                               "cacheLimitEnabled": False, "cacheLimitGb": 20})
        self.assertFalse(data["policy"]["expire"])
        self.assertTrue(data["policy"].get("corrupt"))
        self.assertEqual(data["evicted"], [])
        self.assertTrue((cfg.media_dir / vid / "source.mp4").exists())

    def test_invalid_cache_defaults_are_rejected_before_any_deletion(self):
        home, vid, cfg = self._seed()
        stale_tmp = cfg.derived_dir / "stale.tmp"
        stale_cover = cfg.covers_dir / "bili_old.jpg"
        stale_log = cfg.logs_dir / "job_old.log"
        stale_tmp.write_bytes(b"tmp")
        stale_cover.write_bytes(b"jpg")
        stale_log.write_text("old log", encoding="utf-8")
        old = time.time() - 8 * 86400
        for stale in (stale_tmp, stale_cover, stale_log):
            os.utime(stale, (old, old))
        p = run_cli(["gc", "--auto", "--json", "--cache-defaults", "{not json"], home)
        self.assertNotEqual(p.returncode, 0)
        self.assertEqual(json.loads(p.stdout)["error"]["code"], "E_CACHE_DEFAULTS")
        self.assertTrue(stale_tmp.exists(), "validation must run before the temp sweep")
        self.assertTrue(stale_cover.exists(), "validation must run before the cover sweep")
        self.assertTrue(stale_log.exists(), "validation must run before the log sweep")
        self.assertTrue((cfg.media_dir / vid / "source.mp4").exists())


if __name__ == "__main__":
    unittest.main()

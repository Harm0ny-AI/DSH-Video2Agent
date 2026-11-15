import json
import os
import subprocess
import sys
import tempfile
import unittest
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

from video2agent.cli import clear_offers, issue_confirm_token, remember_offered, unconfirmed_offer
from video2agent.config import load_config

ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / "src"

A = "BV1aaaaaaaa1"
B = "BV1bbbbbbbb1"
C = "BV1cccccccc1"


def run_cli(args, home):
    env = {
        **dict(os.environ),
        "PYTHONPATH": str(SRC),
        "PYTHONIOENCODING": "utf-8",
        "VIDEO2AGENT_HOME": str(home),
    }
    return subprocess.run(
        [sys.executable, "-m", "video2agent", *args],
        capture_output=True, text=True, encoding="utf-8", errors="replace", env=env, cwd=str(ROOT),
    )


class OfferedGuardTests(unittest.TestCase):
    """A discover is a question: indexing one of its candidates needs a user token."""

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.cfg = load_config(Path(self.tmp.name))

    def test_offered_ids_accumulate_and_match(self):
        remember_offered(self.cfg, [{"video_id": A}, {"video_id": B}])
        remember_offered(self.cfg, [{"video_id": B}, {"video_id": C}])
        self.assertEqual(unconfirmed_offer(self.cfg, f"https://x/{A}"), A)
        self.assertEqual(unconfirmed_offer(self.cfg, f"https://x/{C}"), C)
        self.assertIsNone(unconfirmed_offer(self.cfg, "https://x/BV1zzzzzzzz1"))

    def test_identity_is_normalised_not_a_substring(self):
        # An `av` reference and its BV id are the same video. The first guard compared
        # raw substrings, so an av link walked past it (reproduced in review).
        remember_offered(self.cfg, [{"video_id": "BV1xx411c7mD"}])
        self.assertEqual(unconfirmed_offer(self.cfg, "https://www.bilibili.com/video/av2"), "BV1xx411c7mD")
        # A local file whose *name* contains a BV id is not that video.
        self.assertIsNone(unconfirmed_offer(self.cfg, r"D:\videos\BV1xx411c7mD.mp4"))

    def test_a_bare_flag_is_not_a_confirmation(self):
        source = str(Path(self.tmp.name) / "clip.mp4")
        remember_offered(self.cfg, [{"video_id": source}])
        blocked = run_cli(["ingest", source, "--json"], Path(self.tmp.name))
        self.assertNotEqual(blocked.returncode, 0)
        payload = json.loads(blocked.stdout[blocked.stdout.index("{"):])
        self.assertEqual(payload["error"]["code"], "E_CONFIRM_FIRST")
        self.assertIn("shortlist", payload["error"]["remedy"])
        flag_only = run_cli(["ingest", source, "--confirm", "--json"], Path(self.tmp.name))
        self.assertIn("E_CONFIRM_FIRST", flag_only.stdout + flag_only.stderr)

    def test_a_token_issued_for_this_id_gets_through_once(self):
        source = str(Path(self.tmp.name) / "clip.mp4")
        remember_offered(self.cfg, [{"video_id": source}])
        token = issue_confirm_token(self.cfg, [source])
        allowed = run_cli(["ingest", source, "--confirm-token", token, "--json"], Path(self.tmp.name))
        out = allowed.stdout + allowed.stderr
        self.assertNotIn("E_CONFIRM_FIRST", out)
        self.assertNotEqual(allowed.returncode, 0, "a missing file must still fail")
        again = run_cli(["ingest", source, "--confirm-token", token, "--json"], Path(self.tmp.name))
        self.assertIn("E_CONFIRM_FIRST", again.stdout + again.stderr)

    def test_a_token_for_other_ids_does_not_authorise_this_source(self):
        a = str(Path(self.tmp.name) / "a.mp4")
        b = str(Path(self.tmp.name) / "b.mp4")
        remember_offered(self.cfg, [{"video_id": a}, {"video_id": b}])
        token = issue_confirm_token(self.cfg, [a])
        run = run_cli(["ingest", b, "--confirm-token", token, "--json"], Path(self.tmp.name))
        self.assertIn("E_CONFIRM_FIRST", run.stdout + run.stderr)

    def test_an_expired_token_does_not_authorise(self):
        source = str(Path(self.tmp.name) / "clip.mp4")
        remember_offered(self.cfg, [{"video_id": source}])
        token = issue_confirm_token(self.cfg, [source], ttl_s=-1)
        run = run_cli(["ingest", source, "--confirm-token", token, "--json"], Path(self.tmp.name))
        self.assertIn("E_CONFIRM_FIRST", run.stdout + run.stderr)

    def test_parallel_writers_do_not_drop_offers(self):
        # The decision guard is a read-modify-write on offered.json. Six parallel
        # discovers in the real draft session raced, and one candidate that had
        # been offered looked unoffered to ingest. Every id must survive.
        # A real BV id is BV + exactly 10 characters; the strict extractor now
        # rejects longer fakes like BV1parallel00 (13 chars).
        ids = [f"BV{i:010d}" for i in range(16)]
        with ThreadPoolExecutor(max_workers=8) as pool:
            list(pool.map(lambda vid: remember_offered(self.cfg, [{"video_id": vid}]), ids))
        for vid in ids:
            self.assertEqual(unconfirmed_offer(self.cfg, f"https://x/{vid}"), vid)
        state = json.loads((Path(self.cfg.home) / "discovery" / "offered.json").read_text(encoding="utf-8"))
        self.assertEqual(sorted(state["video_ids"]), sorted(ids))

    def test_clearing_one_offer_keeps_the_others(self):
        remember_offered(self.cfg, [{"video_id": A}, {"video_id": B}])
        clear_offers(self.cfg, [A])
        self.assertIsNone(unconfirmed_offer(self.cfg, f"https://x/{A}"))
        self.assertEqual(unconfirmed_offer(self.cfg, f"https://x/{B}"), B)

    def test_broken_state_fails_open_not_closed(self):
        # A corrupt offered.json must not crash, and must not block forever.
        target = Path(self.cfg.home) / "discovery" / "offered.json"
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text('{"video_ids": "BV1aaa", "updated_ms": "soon"}', encoding="utf-8")
        self.assertIsNone(unconfirmed_offer(self.cfg, "https://x/BV1aaaaaaaa1"))


if __name__ == "__main__":
    unittest.main()

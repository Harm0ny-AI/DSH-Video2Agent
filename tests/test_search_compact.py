"""Compact search hits keep only what evidence/timecode lookups need."""

import unittest

from video2agent import cli
from video2agent.util import parse_time_ms


class CompactSearchTests(unittest.TestCase):
    def test_drops_repeated_fields_and_keeps_evidence_fields(self):
        data = {
            "ok": True,
            "results": [{
                "evidence_id": "ev_1", "video_id": "v", "title": "t", "timecode": "00:00:01",
                "snippet": "text", "modalities": ["transcript"], "score": 0.5,
                "start_ms": 1000, "end_ms": 2000, "citation": "t 00:00:01", "why": "keyword",
            }],
        }
        out = cli._compact_search(data)
        row = out["results"][0]
        self.assertEqual(set(row), {"evidence_id", "video_id", "title", "timecode", "snippet",
                                    "modalities", "score"})
        self.assertEqual(parse_time_ms(row["timecode"]), 1000, "timecode still drives frames/evidence")
        self.assertTrue(row["evidence_id"], "evidence --evidence-id still works")
        self.assertTrue(out["compact"])

    def test_multi_query_payloads_are_compacted_too(self):
        data = {"queries": [{"query": "a", "results": [{"evidence_id": "e", "start_ms": 1}]}]}
        out = cli._compact_search(data)
        self.assertEqual(out["queries"][0]["results"][0], {"evidence_id": "e"})


if __name__ == "__main__":
    unittest.main()

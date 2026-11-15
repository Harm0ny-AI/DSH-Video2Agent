import unittest

from video2agent.cli import _merge_evidence_results, _parse_at_list


class EvidenceBatchParsingTests(unittest.TestCase):
    def test_comma_and_json_lists(self):
        self.assertEqual(_parse_at_list("00:00:06,00:00:10"), [6000, 10000])
        self.assertEqual(_parse_at_list("[1, 2.5]"), [1000, 2500])
        self.assertEqual(_parse_at_list('["00:00:01"]'), [1000])
        self.assertEqual(_parse_at_list(""), [])
        with self.assertRaises(Exception) as ctx:
            _parse_at_list("[not-json]")
        self.assertEqual(getattr(ctx.exception, "code", ""), "E_BAD_TIME")

    def test_merge_keeps_moments_text_and_dedupes_images(self):
        results = [
            {
                "ok": True, "video_id": "vid", "evidence_id": "ev1",
                "requested_ms": 1000, "range": {"start_ms": 1000, "end_ms": 2000},
                "images": [{"path": "a.jpg"}], "image_frame_ms": [1000],
                "ocr": [{"text": "one"}], "transcript": [{"text": "t1"}],
                "warnings": [{"code": "W1"}],
            },
            {
                "ok": True, "video_id": "vid", "evidence_id": "ev2",
                "requested_ms": 4000, "range": {"start_ms": 4000, "end_ms": 5000},
                "images": [{"path": "a.jpg"}, {"path": "b.jpg"}], "image_frame_ms": [4000],
                "ocr": [{"text": "two"}], "transcript": [{"text": "t2"}],
                "warnings": [{"code": "W2"}],
            },
        ]
        merged = _merge_evidence_results(results)
        self.assertTrue(merged["multi_moment"])
        self.assertEqual(len(merged["moments"]), 2)
        self.assertEqual([m["at_ms"] for m in merged["moments"]], [1000, 4000])
        self.assertEqual([i["path"] for i in merged["images"]], ["a.jpg", "b.jpg"])
        self.assertEqual([o["text"] for o in merged["ocr"]], ["one", "two"])
        self.assertEqual([t["text"] for t in merged["transcript"]], ["t1", "t2"])
        self.assertEqual(len(merged["images"]), len(merged["frames"]))
        self.assertEqual(len(merged["images"]), len(merged["image_frame_ms"]))
        self.assertEqual(merged["citation"], "multiple")
        self.assertIsNone(merged["evidence_id"])
        for moment in merged["moments"]:
            self.assertNotIn("images", moment, "batch moments must not leak frame paths")
        self.assertTrue(all("path" not in frame for frame in merged["frames"]))


if __name__ == "__main__":
    unittest.main()

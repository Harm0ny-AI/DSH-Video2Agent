import json
import tempfile
import unittest
from pathlib import Path

from video2agent import storage
from video2agent.config import Config


class CachePolicyCorruptTest(unittest.TestCase):
    """A corrupt ui-settings.json must not apply the 7-day default policy."""

    def setUp(self):
        self.cfg = Config(Path(tempfile.mkdtemp(prefix="vp-policy-")))

    def test_missing_file_uses_defaults(self):
        policy = storage.cache_policy(self.cfg)
        self.assertTrue(policy["expire"])
        self.assertEqual(policy["days"], 7)

    def test_corrupt_file_disables_expiry(self):
        (self.cfg.home / "ui-settings.json").write_text("{not json", encoding="utf-8")
        policy = storage.cache_policy(self.cfg)
        self.assertFalse(policy["expire"], "a corrupt file must not expire the cache")
        self.assertTrue(policy.get("corrupt"))

    def test_non_object_disables_expiry(self):
        (self.cfg.home / "ui-settings.json").write_text("[1,2]", encoding="utf-8")
        policy = storage.cache_policy(self.cfg)
        self.assertFalse(policy["expire"])

    def test_valid_file_is_respected(self):
        (self.cfg.home / "ui-settings.json").write_text(
            json.dumps({"cacheExpire": False, "cacheDays": 30}), encoding="utf-8")
        policy = storage.cache_policy(self.cfg)
        self.assertFalse(policy["expire"])
        self.assertEqual(policy["days"], 30)

    def test_infinity_limit_falls_back(self):
        (self.cfg.home / "ui-settings.json").write_text(
            '{"cacheLimitEnabled": true, "cacheLimitGb": Infinity}', encoding="utf-8")
        policy = storage.cache_policy(self.cfg)
        self.assertEqual(policy["limit_gb"], 20)


if __name__ == "__main__":
    unittest.main()

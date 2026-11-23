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


class CachePolicyRowConfigTest(unittest.TestCase):
    """The plugin-row Config is the layer below ui-settings.json.

    The DSH Host passes it to `gc --auto` so the background sweep applies the
    policy the settings page shows instead of falling back to defaults.
    """

    def setUp(self):
        self.cfg = Config(Path(tempfile.mkdtemp(prefix="vp-policy-row-")))
        self.row = {"cacheExpire": False, "cacheDays": 30,
                    "cacheLimitEnabled": True, "cacheLimitGb": 5}

    def test_row_config_applies_when_file_is_missing(self):
        policy = storage.cache_policy(self.cfg, self.row)
        self.assertEqual(policy, {"expire": False, "days": 30,
                                  "limit_enabled": True, "limit_gb": 5})

    def test_file_value_wins_over_row_config(self):
        (self.cfg.home / "ui-settings.json").write_text(
            json.dumps({"cacheExpire": True, "cacheDays": 2}), encoding="utf-8")
        policy = storage.cache_policy(self.cfg, self.row)
        self.assertTrue(policy["expire"], "the settings file is the top layer")
        self.assertEqual(policy["days"], 2)
        # A key the file does not repeat still comes from the row Config.
        self.assertTrue(policy["limit_enabled"])
        self.assertEqual(policy["limit_gb"], 5)

    def test_row_config_only_accepts_cache_keys(self):
        policy = storage.cache_policy(self.cfg, {
            "cacheExpire": False, "cacheDays": 30,
            "cacheLimitEnabled": False, "cacheLimitGb": 5,
            # Internal/Python-shaped names must not smuggle a policy field in.
            "days": 1, "expire": True, "limit_gb": 1, "limit_enabled": True,
            "purge": True, "unknown": "x",
        })
        self.assertEqual(policy, {"expire": False, "days": 30,
                                  "limit_enabled": False, "limit_gb": 5})

    def test_corrupt_file_fails_closed_despite_row_config(self):
        (self.cfg.home / "ui-settings.json").write_text("{not json", encoding="utf-8")
        policy = storage.cache_policy(self.cfg, {**self.row, "cacheExpire": True})
        self.assertFalse(policy["expire"], "a corrupt file must not expire the cache")
        self.assertTrue(policy.get("corrupt"))


if __name__ == "__main__":
    unittest.main()

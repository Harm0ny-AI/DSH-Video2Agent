import json
import tempfile
import unittest
from pathlib import Path

from video2agent.config import load_config, save_config


class ConfigPersistenceTest(unittest.TestCase):
    def test_corrupt_config_is_backed_up_not_lost(self):
        home = Path(tempfile.mkdtemp(prefix="vp-config-"))
        (home / "config.json").write_text("{ not json", encoding="utf-8")
        cfg = load_config(home)
        backups = list(home.glob("config.json.corrupt-*"))
        self.assertEqual(len(backups), 1)
        self.assertEqual(backups[0].read_text(encoding="utf-8"), "{ not json")
        self.assertEqual(cfg.data, {})

    def test_save_is_atomic_and_readable(self):
        home = Path(tempfile.mkdtemp(prefix="vp-config-"))
        cfg = load_config(home)
        cfg.data["asr_model"] = "small"
        save_config(cfg)
        payload = json.loads((home / "config.json").read_text(encoding="utf-8"))
        self.assertEqual(payload.get("asr_model"), "small")
        self.assertEqual(list(home.glob("config.json.tmp-*")), [])

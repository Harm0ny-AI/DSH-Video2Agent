import tempfile
import unittest
from pathlib import Path

from video2agent import cloud
from video2agent.config import Config
from video2agent.util import Video2AgentError


class CloudCorruptConfigTest(unittest.TestCase):
    """A corrupt cloud.json must never retarget a stored key at a default endpoint."""

    def setUp(self):
        self.cfg = Config(Path(tempfile.mkdtemp(prefix="vp-cloud-")))
        self.path = self.cfg.home / "cloud.json"

    def test_status_reports_corrupt_and_not_configured(self):
        self.path.write_text("{not json", encoding="utf-8")
        data = cloud.status(self.cfg)
        self.assertTrue(data.get("corrupt"))
        self.assertFalse(data["configured"])

    def test_configured_is_false_when_corrupt(self):
        self.path.write_text("{not json", encoding="utf-8")
        self.assertFalse(cloud.configured(self.cfg))

    def test_toggle_is_refused_when_corrupt(self):
        self.path.write_text("{not json", encoding="utf-8")
        with self.assertRaises(Video2AgentError) as ctx:
            cloud.set_asr_enabled(self.cfg, False)
        self.assertEqual(ctx.exception.as_dict()["code"], "E_CLOUD_CONFIG")
        # The corrupt file is left for an explicit provider reset.
        self.assertEqual(self.path.read_text(encoding="utf-8"), "{not json")

    def test_full_reset_repairs_the_file(self):
        self.path.write_text("{not json", encoding="utf-8")
        data = cloud.set_config(self.cfg, {
            "provider": "custom", "base_url": "https://api.example.com/v1",
        })
        self.assertEqual(data["base_url"], "https://api.example.com/v1")
        self.assertEqual(cloud.status(self.cfg).get("corrupt"), False)


if __name__ == "__main__":
    unittest.main()

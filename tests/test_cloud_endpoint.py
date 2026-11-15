import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from video2agent import cloud
from video2agent.config import Config
from video2agent.util import Video2AgentError


class CloudEndpointSwitchTest(unittest.TestCase):
    """Switching endpoints must never leave the old key pointing at the new host."""

    def setUp(self):
        self.cfg = Config(Path(tempfile.mkdtemp(prefix="vp-cloud-ep-")))
        cloud._write_config(self.cfg, {
            "provider": "custom", "base_url": "https://a.example.com/v1",
        })

    def test_endpoint_is_not_switched_when_the_key_cannot_be_cleared(self):
        with patch.object(cloud, "clear_key",
                          side_effect=Video2AgentError("E_CLOUD_CLEAR", "busy", "retry")):
            with self.assertRaises(Video2AgentError):
                cloud.set_config(self.cfg, {
                    "provider": "siliconflow",
                    "base_url": "https://api.siliconflow.cn/v1",
                })
        data = cloud._read_config(self.cfg)
        self.assertEqual(data["base_url"], "https://a.example.com/v1",
                         "the endpoint changed even though the old key survived")

    def test_switch_succeeds_when_the_key_is_cleared(self):
        with patch.object(cloud, "clear_key") as cleared:
            data = cloud.set_config(self.cfg, {
                "provider": "siliconflow",
                "base_url": "https://api.siliconflow.cn/v1",
            })
            cleared.assert_called_once()
        self.assertEqual(data["base_url"], "https://api.siliconflow.cn/v1")



    def test_an_environment_key_is_reported_instead_of_claiming_cleared(self):
        # load_key() falls back to the environment when secrets/cloud.bin is gone,
        # so an endpoint switch cannot honestly say "key cleared": cloud is still
        # configured and the pipeline would send audio with that env key.
        with patch.dict("os.environ", {"SILICONFLOW_API_KEY": "sk-env-test-123456"}, clear=False):
            data = cloud.set_config(self.cfg, {
                "provider": "siliconflow",
                "base_url": "https://api.siliconflow.cn/v1",
            })
        self.assertFalse(data["key_cleared"], "an env key cannot be cleared")
        self.assertTrue(data["configured"], "the env key still makes cloud usable")
        self.assertEqual(data["source"], "env")

    def test_a_saved_key_is_reported_as_cleared(self):
        import os
        for name in ("SILICONFLOW_API_KEY", "VIDEO2AGENT_CLOUD_API_KEY"):
            os.environ.pop(name, None)
        data = cloud.set_config(self.cfg, {
            "provider": "siliconflow",
            "base_url": "https://api.siliconflow.cn/v1",
        })
        self.assertTrue(data["key_cleared"])
        self.assertFalse(data["configured"])
        self.assertIsNone(data["source"])
if __name__ == "__main__":
    unittest.main()

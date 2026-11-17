from __future__ import annotations

import json
import os
import stat
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from video2agent import cloud
from video2agent.config import load_config
from video2agent.util import Video2AgentError


class CloudTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory(prefix="vp-cloud-")
        self.cfg = load_config(self.tmp.name)

    def tearDown(self):
        self.tmp.cleanup()

    @unittest.skipUnless(os.name == "nt", "requires the Windows DPAPI secret store")
    def test_key_is_encrypted_and_status_hides_it(self):
        key = "sk-" + "test" * 10
        result = cloud.save_key(self.cfg, key)
        self.assertTrue(result["configured"])
        self.assertEqual(result["last4"], "test")
        raw = (Path(self.tmp.name) / "secrets" / "cloud.bin").read_bytes()
        self.assertNotIn(key.encode(), raw)
        status = cloud.status(self.cfg)
        self.assertTrue(status["configured"])
        self.assertEqual(status["last4"], "test")
        self.assertNotIn(key, json.dumps(status))
        self.assertEqual(cloud.load_key(self.cfg), key)
        cloud.clear_key(self.cfg)
        self.assertFalse(cloud.status(self.cfg)["configured"])

    def test_invalid_key_rejected(self):
        with self.assertRaises(Video2AgentError) as ctx:
            cloud.save_key(self.cfg, "bad key")
        self.assertEqual(ctx.exception.code, "E_CLOUD_KEY")

    @unittest.skipUnless(os.name == "nt", "requires the Windows DPAPI secret store")
    def test_custom_provider_models_and_switch_clears_key(self):
        key = "custom-provider-key-1234567890"
        cloud.save_key(self.cfg, key)  # custom providers need not use sk-
        result = cloud.set_config(self.cfg, {
            "provider": "custom",
            "base_url": "https://api.example.com/v1/",
            "asr_model": "my-asr",
            "ocr_model": "my-ocr",
            "asr_enabled": False,
        })
        self.assertEqual(result["base_url"], "https://api.example.com/v1")
        self.assertEqual(result["asr_model"], "my-asr")
        self.assertTrue(result["key_cleared"])
        status = cloud.status(self.cfg)
        self.assertEqual(status["provider"], "custom")
        self.assertFalse(status["asr_enabled"])
        self.assertFalse(status["configured"])
        # Changing the endpoint must not silently reuse a key.
        cloud.save_key(self.cfg, key)
        self.assertTrue(cloud.status(self.cfg)["configured"])
        result = cloud.set_config(self.cfg, {"provider": "siliconflow", "base_url": cloud.BASE_URL})
        self.assertTrue(result["key_cleared"])
        self.assertFalse(cloud.status(self.cfg)["configured"])

    def test_remote_http_provider_is_rejected(self):
        with self.assertRaises(Video2AgentError) as ctx:
            cloud.set_config(self.cfg, {
                "provider": "custom",
                "base_url": "http://api.example.com/v1",
                "asr_model": "a",
                "ocr_model": "b",
            })
        self.assertEqual(ctx.exception.code, "E_CLOUD_CONFIG")

    def test_clear_failure_is_reported(self):
        with patch("video2agent.cloud.Path.unlink", side_effect=PermissionError("busy")):
            with self.assertRaises(Video2AgentError) as ctx:
                cloud.clear_key(self.cfg)
        self.assertEqual(ctx.exception.code, "E_CLOUD_CLEAR")

    def test_402_maps_to_balance(self):
        response = type("R", (), {
            "status_code": 402,
            "json": lambda self: {"code": 30001, "message": "balance"},
            "text": "balance",
        })()
        error = cloud._cloud_error(response, "test")
        self.assertEqual(error.code, "E_CLOUD_BALANCE")

    @unittest.skipUnless(os.name == "nt", "requires the Windows DPAPI secret store")
    def test_transcribe_offsets_chunks(self):
        key = "sk-" + "test" * 10
        cloud.save_key(self.cfg, key)
        response = type("R", (), {
            "status_code": 200,
            "json": lambda self: {
                "segments": [{"start": 1.0, "end": 2.5, "text": "hello"}],
                "duration": 30,
            },
        })()
        chunk = Path(self.tmp.name) / "chunk.wav"
        chunk.write_bytes(b"fake-audio")
        with patch("video2agent.cloud._chunks", return_value=[(chunk, 60.0)]):
            with patch("video2agent.cloud.requests.post", return_value=response) as post:
                result = cloud.transcribe(self.cfg, "audio.wav")
        self.assertEqual(result["segments"][0]["start_ms"], 61000)
        self.assertEqual(result["segments"][0]["end_ms"], 62500)
        self.assertEqual(post.call_args.kwargs["data"]["response_format"], "verbose_json")
        self.assertEqual(post.call_args.kwargs["files"]["file"][2], "audio/wav")

    @unittest.skipUnless(os.name == "nt", "requires the Windows DPAPI secret store")
    def test_ocr_returns_text(self):
        key = "sk-" + "test" * 10
        cloud.save_key(self.cfg, key)
        image = Path(self.tmp.name) / "frame.jpg"
        image.write_bytes(b"fake-jpeg")
        response = type("R", (), {
            "status_code": 200,
            "json": lambda self: {"choices": [{"message": {"content": "# slide\ntext"}}]},
        })()
        with patch("video2agent.cloud.requests.post", return_value=response):
            result = cloud.ocr(self.cfg, image)
        self.assertIn("slide", result["text"])


class SecretBackendTest(unittest.TestCase):
    """The key store must work on macOS/Linux, not only Windows DPAPI.

    macOS uses the login Keychain through the security CLI; other platforms use a
    0600 file. Both paths run against a fake security/FS so every CI runner covers
    them (the Windows DPAPI path has its own tests above).
    """

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory(prefix="vp-secret-")
        self.cfg = load_config(self.tmp.name)

    def tearDown(self):
        self.tmp.cleanup()

    @staticmethod
    def _fake_security():
        state = {"key": None}
        calls = []

        class Proc:
            def __init__(self, code=0, out="", err=""):
                self.returncode = code
                self.stdout = out
                self.stderr = err

        def fake_run(argv, **kwargs):
            calls.append(argv)
            assert argv[0] == "security", argv
            cmd = argv[1]
            if cmd == "find-generic-password":
                if state["key"] is None:
                    return Proc(44, "", "The specified item could not be found in the keychain.")
                return Proc(0, state["key"] + "\n", "")
            if cmd == "add-generic-password":
                state["key"] = argv[argv.index("-w") + 1]
                return Proc()
            if cmd == "delete-generic-password":
                if state["key"] is None:
                    return Proc(44, "", "The specified item could not be found in the keychain.")
                state["key"] = None
                return Proc()
            raise AssertionError(argv)

        return fake_run, calls, state

    def test_macos_keychain_roundtrip_and_clear(self):
        fake_run, calls, state = self._fake_security()
        key = "sk-keychain-test-123456"
        with patch("video2agent.cloud._secret_backend", return_value="keychain"), patch(
            "video2agent.cloud.subprocess.run", side_effect=fake_run
        ):
            self.assertIsNone(cloud.load_key(self.cfg))
            result = cloud.save_key(self.cfg, key)
            self.assertEqual(result["backend"], "keychain")
            self.assertEqual(cloud.load_key(self.cfg), key)
            status = cloud.status(self.cfg)
            self.assertTrue(status["configured"])
            self.assertEqual(status["source"], "keychain")
            self.assertEqual(status["backend"], "keychain")
            cloud.clear_key(self.cfg)
            self.assertIsNone(cloud.load_key(self.cfg))
            self.assertFalse(cloud.status(self.cfg)["configured"])
            self.assertFalse((Path(self.tmp.name) / "secrets" / "cloud.bin").exists())
            self.assertFalse((Path(self.tmp.name) / "secrets" / "cloud.key").exists())
        self.assertIn("add-generic-password", [argv[1] for argv in calls])
        self.assertNotIn(key, json.dumps(cloud.status(self.cfg)))

    def test_linux_file_backend_roundtrip_and_clear(self):
        key = "sk-file-backend-123456"
        with patch("video2agent.cloud._secret_backend", return_value="file"):
            cloud.save_key(self.cfg, key)
            path = Path(self.tmp.name) / "secrets" / "cloud.key"
            self.assertTrue(path.is_file())
            self.assertEqual(path.read_text(encoding="utf-8"), key)
            if os.name != "nt":
                self.assertEqual(stat.S_IMODE(path.stat().st_mode), 0o600)
            self.assertEqual(cloud.load_key(self.cfg), key)
            self.assertEqual(cloud.status(self.cfg)["source"], "file")
            cloud.clear_key(self.cfg)
            self.assertFalse(path.exists())
            self.assertIsNone(cloud.load_key(self.cfg))

    def test_env_key_is_used_when_nothing_is_stored(self):
        with patch("video2agent.cloud._secret_backend", return_value="file"), patch.dict(
            os.environ, {"VIDEO2AGENT_CLOUD_API_KEY": "sk-env-only-123456"}, clear=False
        ):
            self.assertEqual(cloud.load_key(self.cfg), "sk-env-only-123456")
            self.assertEqual(cloud.status(self.cfg)["source"], "env")


if __name__ == "__main__":
    unittest.main()

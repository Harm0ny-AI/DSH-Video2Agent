from __future__ import annotations

import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from video2agent import local_models
from video2agent.config import load_config
from video2agent.util import Video2AgentError


class LocalModelTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory(prefix="vp-model-")
        self.cfg = load_config(self.tmp.name)

    def tearDown(self):
        self.tmp.cleanup()

    def test_tiers_cover_low_to_enterprise(self):
        status = local_models.status(self.cfg)
        models = [p["model"] for p in status["tiers"]]
        self.assertEqual(models, ["base", "small", "medium", "large-v3"])
        self.assertIn("Ryzen", " ".join(p["cpu"] for p in status["tiers"]))
        self.assertIn("Intel", " ".join(p["cpu"] for p in status["tiers"]))

    def test_ocr_status_explains_extra_availability(self):
        # The settings page must be able to say why local OCR is missing: the
        # extra has no wheel on Python 3.13, so a dead "内置" dropdown would lie.
        import sys
        status = local_models.status(self.cfg)
        ocr = status["ocr"]
        self.assertIn("python", ocr)
        self.assertEqual(ocr["python"], "%d.%d" % sys.version_info[:2])
        self.assertEqual(ocr["extra_available"], sys.version_info[:2] < (3, 13))
        self.assertIsInstance(ocr["extra_available"], bool)

    def test_custom_local_ct2_path_is_recognized_and_selected(self):
        model = Path(self.tmp.name) / "my-ct2"
        model.mkdir()
        (model / "model.bin").write_bytes(b"x" * (2 * 1024 * 1024))
        (model / "config.json").write_text("{}", encoding="utf-8")
        state = local_models.status(self.cfg, str(model))
        self.assertTrue(state["asr"]["cached"])
        self.assertTrue(state["custom"])
        selected = local_models.select(self.cfg, str(model))
        self.assertEqual(selected["asr"]["selected"], str(model))
        self.assertTrue(selected["asr"]["cached"])

    def test_hf_cache_model_can_be_uninstalled(self):
        with patch.dict(os.environ, {"HF_HOME": self.tmp.name}):
            model = Path(self.tmp.name) / "hub" / "models--Systran--faster-whisper-base"
            snap = model / "snapshots" / "abc"
            snap.mkdir(parents=True)
            (snap / "model.bin").write_bytes(b"x" * (2 * 1024 * 1024))
            (snap / "config.json").write_text("{}", encoding="utf-8")
            self.assertTrue(local_models.status(self.cfg, "base")["asr"]["cached"])
            result = local_models.uninstall(self.cfg, "base")
            self.assertTrue(result["removed"])
            self.assertFalse(result["asr"]["cached"])
            self.assertFalse(model.exists())

    def test_custom_local_path_is_never_deleted(self):
        model = Path(self.tmp.name) / "my-keep"
        model.mkdir()
        (model / "model.bin").write_bytes(b"x" * (2 * 1024 * 1024))
        (model / "config.json").write_text("{}", encoding="utf-8")
        with self.assertRaises(Video2AgentError) as ctx:
            local_models.uninstall(self.cfg, str(model))
        self.assertEqual(ctx.exception.code, "E_MODEL_UNINSTALL")
        self.assertTrue(model.exists())

    def test_local_ocr_model_selection(self):
        config = Path(self.tmp.name) / "ocr.yaml"
        config.write_text("Global: {}\n", encoding="utf-8")
        selected = local_models.select_ocr(self.cfg, str(config))
        self.assertEqual(selected["ocr"]["selected"], "custom")
        self.assertEqual(selected["ocr"]["config_path"], str(config.resolve()))
        builtin = local_models.select_ocr(self.cfg, "")
        self.assertEqual(builtin["ocr"]["selected"], "builtin")
        with self.assertRaises(Video2AgentError) as ctx:
            local_models.select_ocr(self.cfg, str(Path(self.tmp.name) / "missing.yaml"))
        self.assertEqual(ctx.exception.code, "E_OCR_MODEL")

    def test_huggingface_ocr_repo_uses_its_rapidocr_config(self):
        repo = Path(self.tmp.name) / "hf-repo"
        repo.mkdir()
        config = repo / "config.yaml"
        config.write_text("Global: {}\n", encoding="utf-8")
        with patch("huggingface_hub.snapshot_download", return_value=str(repo)):
            selected = local_models.select_ocr(self.cfg, "example/rapidocr-model")
        self.assertEqual(selected["ocr"]["selected"], "custom")
        self.assertEqual(selected["ocr"]["config_path"], str(config.resolve()))

    def test_huggingface_ocr_onnx_repo_generates_config(self):
        repo = Path(self.tmp.name) / "hf-onnx"
        for rel in ("PP-OCRv4/ch_PP-OCRv4_det_infer.onnx", "PP-OCRv4/ch_PP-OCRv4_rec_infer.onnx", "PP-OCRv1/ch_ppocr_mobile_v2.0_cls_infer.onnx"):
            path = repo / rel
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_bytes(b"fake")
        with patch("huggingface_hub.snapshot_download", return_value=str(repo)):
            selected = local_models.select_ocr(self.cfg, "example/onnx-ocr")
        generated = Path(selected["ocr"]["config_path"])
        self.assertTrue(generated.is_file())
        text = generated.read_text(encoding="utf-8")
        self.assertIn("ch_PP-OCRv4_det_infer.onnx", text)
        self.assertIn("ch_PP-OCRv4_rec_infer.onnx", text)


if __name__ == "__main__":
    unittest.main()

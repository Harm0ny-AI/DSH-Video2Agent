import os
import subprocess
import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


class LazyImportTests(unittest.TestCase):
    def test_read_cli_does_not_import_media_stack(self):
        env = os.environ.copy()
        env["PYTHONPATH"] = str(ROOT / "src")
        code = (
            "import sys; import video2agent.cli; "
            "heavy=[n for n in ('numpy','PIL','requests','cv2','faster_whisper','rapidocr','rapidocr_onnxruntime') if n in sys.modules]; "
            "print(','.join(heavy))"
        )
        out = subprocess.check_output([sys.executable, "-c", code], env=env, text=True)
        self.assertEqual(out.strip(), "", out)


if __name__ == "__main__":
    unittest.main()

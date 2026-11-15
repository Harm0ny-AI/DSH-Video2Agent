"""Create the tiny caption fixture used by the CLI smoke test in CI.

No fonts, no speech, no network: a 4-second colour video plus a sidecar SRT.
The sidecar is what makes `ingest` work without downloading an ASR model, and
the words in it are what `search 表格` must find. Run before the test suite:

    python tests/fixtures/make_ci_fixture.py
"""
from __future__ import annotations

import shutil
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).parent
VIDEO = ROOT / "demo.mp4"
SRT = ROOT / "demo.srt"


def main() -> int:
    if VIDEO.exists() and SRT.exists():
        print("fixture already present:", VIDEO)
        return 0
    if not shutil.which("ffmpeg"):
        print("ffmpeg is required to generate the CI fixture", file=sys.stderr)
        return 1
    subprocess.run(
        [
            "ffmpeg", "-y", "-loglevel", "error",
            "-f", "lavfi", "-i", "color=c=0xF6F2E8:s=640x360:d=4",
            "-c:v", "libx264", "-pix_fmt", "yuv420p", str(VIDEO),
        ],
        check=True,
    )
    SRT.write_text(
        "1\n00:00:00,200 --> 00:00:03,800\n表格与结论在画面上\n",
        encoding="utf-8",
    )
    print("wrote", VIDEO)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

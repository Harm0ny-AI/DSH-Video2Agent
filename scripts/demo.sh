#!/usr/bin/env bash
# Video2Agent demo: one local video -> transcript/OCR -> a timestamped search hit -> a frame.
# Every command below is the public CLI; the video is real, the output is not edited.
#
#   scripts/demo.sh                    # uses tests/fixtures/slides.mp4 when present
#   scripts/demo.sh /path/to/clip.mp4  # or any local video
#   VIDEO2AGENT_HOME=/tmp/vp-demo scripts/demo.sh ./clip.mp4
set -euo pipefail
ROOT="$(cd "$(dirname "$0")/.." && pwd)"
VIDEO="${1:-$ROOT/tests/fixtures/slides.mp4}"
if [ ! -f "$VIDEO" ]; then
  echo "No video at $VIDEO -- pass one: scripts/demo.sh <video>" >&2
  exit 1
fi
export VIDEO2AGENT_HOME="${VIDEO2AGENT_HOME:-$(mktemp -d)}"
echo "# Video2Agent demo"
echo "# home: $VIDEO2AGENT_HOME"
echo
echo "\$ video2agent ingest \"$VIDEO\""
video2agent ingest "$VIDEO"
VIDEO_ID="$(video2agent list --json | python -c 'import json,sys; print(json.load(sys.stdin)["videos"][0]["id"])')"
echo
echo "\$ video2agent ocr-index $VIDEO_ID"
video2agent ocr-index "$VIDEO_ID"
echo
echo "\$ video2agent search 注意力 --video $VIDEO_ID"
video2agent search 注意力 --video "$VIDEO_ID"
echo
echo "\$ video2agent evidence $VIDEO_ID --at 1.5 --images 1"
video2agent evidence "$VIDEO_ID" --at 1.5 --images 1
echo
echo "# Done. Library: video2agent list --json   Frame: the path printed above."

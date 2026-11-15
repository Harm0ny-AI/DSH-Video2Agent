# Third-party licenses and models

DSH-Video2Agent's own code is Apache-2.0. It depends on third-party projects; their
licenses remain in force.

| Component | License | Notes |
|---|---|---|
| yt-dlp | Unlicense | Download/search adapter |
| faster-whisper | MIT | ASR runtime |
| CTranslate2 | MIT | ASR runtime |
| OpenAI Whisper weights | MIT | Downloaded at runtime |
| RapidOCR | Apache-2.0 | OCR runtime |
| PP-OCR models | Apache-2.0 | Downloaded with RapidOCR |
| OpenCV | Apache-2.0 | Frame signals / lines |
| NumPy | BSD-3-Clause | Numeric arrays |
| Pillow | HPND | Frames / contact sheets |
| requests | Apache-2.0 | Bilibili API |
| onnxruntime | MIT | RapidOCR inference |
| huggingface-hub | Apache-2.0 | Model download helper |
| FFmpeg | LGPL/GPL depending on build | Not bundled by default |

## Distribution rules

- Do not bundle non-commercial models (for example ImageBind) in the default
  package.
- Do not bundle a GPL FFmpeg build unless the distribution complies with GPL.
  Prefer a system FFmpeg or an LGPL build.
- Downloaded ASR/OCR model weights are not part of this repository.
- Bilibili covers, videos, subtitles, and comments remain the property of their
  owners. DSH-Video2Agent caches them locally for the user's analysis; it does not
  redistribute them.

This file is informational, not legal advice. Run a license audit before a
public release.

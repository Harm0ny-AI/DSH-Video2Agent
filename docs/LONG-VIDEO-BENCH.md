# Long-video benchmark (2026-11-01)

Purpose: measure a real 1–2 hour Bilibili video end to end, not a 90-second clip.
All runs used an isolated `VIDEO2AGENT_HOME` under `%TEMP%`, the packaged Bilibili
login cookie, the default `auto` profile (120 frames max), and the CLI:

```powershell
$env:VIDEO2AGENT_HOME = "$env:TEMP\vp-longbench-run"
video2agent ingest "<url>" --json --force
```

Wall time is the PowerShell `Measure-Command` span around the CLI; the detailed
breakdown comes from `overview.metrics` in the JSON.

## 一数 — 高一三角函数（67 min）

- Title: 【高一】三角函数+诱导公式!保姆级零基础讲解!
- URL: https://www.bilibili.com/video/BV1EZ2QBtERw
- Duration: 4,006,510 ms (1 h 06 m 46 s)
- Video: 145.6 MB source; AI Chinese subtitle track (WBI, `ai-zh`) + five
  translated AI tracks.

| Metric | Value |
|---|---:|
| Wall time | **61.2 s** |
| `resolve` | 8.8 s |
| `transcript` (captions) | 0.9 s |
| `scenes` | 42.3 s |
| `frames` | 8.9 s |
| `ocr` | 0.16 s (0 frames; on-demand mode) |
| Segments | 1,976 |
| Scenes | 23 |
| Frames | 114 (120 sampled, 6 near-duplicates removed) |
| Transcript coverage | **0.995** (`capabilities.transcript_coverage`) |
| Peak RSS | **875.7 MB** |
| Avg RSS | 243.1 MB |
| Failure | exit 0; no blocking warning |
| OCR tracks | 0 (on-demand; no upfront OCR) |
| Visual coverage | 0.0 known (labels `unknown` until a frame is read) |
| Transcript source | `caption` (AI/WBI) |
| `caption_check` | `null` — AI tracks are generated from the audio, so the audio check is skipped |
| Warnings | `FRAMES_DEDUPED`, `OCR_ON_DEMAND_MODE` |

Observations:
- With a usable AI caption, a 67-minute video is ~1 minute end to end; scene
  detection dominates, not transcription.
- OCR is deliberately lazy: 0 OCR tracks up front, so the long-video cost stays
  bounded. A specific question that needs on-screen text pays for that one frame.
- Visual coverage is 0 until a frame is read; `visual_map=false` is the honest
  answer, not "no visuals".

## 72-minute Chinese lecture

- A public Bilibili lecture with an AI Chinese subtitle track. Title and URL are omitted here because
  this benchmark measures runtime, not the topic.
- Duration: 4,327,274 ms (1 h 12 m 07 s)
- Video: 236.3 MB source; AI Chinese subtitle track (WBI, `ai-zh`).

| Metric | Value |
|---|---:|
| Wall time | **75.6 s** |
| `resolve` | 33.8 s |
| `transcript` (captions) | 0.34 s |
| `scenes` | 31.5 s |
| `frames` | 9.0 s |
| `ocr` | 0.17 s (0 frames; on-demand) |
| Segments | 1,668 |
| Scenes | 150 |
| Frames | 116 (120 sampled, 4 duplicates removed) |
| Transcript coverage | **0.842** (`capabilities.transcript_coverage`) |
| Peak RSS | **1,077.1 MB** |
| Avg RSS | 273.7 MB |
| Failure | exit 0; no blocking warning |
| OCR tracks | 0 (on-demand) |
| Transcript source | `caption` (AI/WBI) |
| `caption_check` | `null` — AI track |
| Warnings | `FRAMES_DEDUPED`, `OCR_ON_DEMAND_MODE` |

Both long videos were AI-caption videos, so the new audio check did not run on
them (by design). The check was exercised separately against real audio, below.

## Caption audio verification (separate, 2026-11-01)

The 一数 video uses an AI track, so it does not exercise the new audio check.
The check was measured directly on a 103 s local video with real speech:

| Case | Result |
|---|---|
| Joke/wrong caption over the real audio | `mismatch`, score **0.048** (both windows; max common run 1) |
| Same speech, correct caption (Traditional ASR vs Simplified caption) | `verified`, score **0.667** per-window average |
| Sample | two 8 s windows concatenated (16 s total); per-window scores |
| Model | cached light model (configured ASR when present; `small` on the test machine); no download |
| Cost | **~4.1–4.4 s** for the 16 s sample with the cached small model |
| Path | `src/video2agent/caption_verify.py`; unit tests `tests/test_caption_verify.py` |

It only runs for non-AI Bilibili human tracks (video ≥60 s, Chinese/English, with
audio). AI tracks skip it because they are generated from the audio; local
sidecars skip it because they are the user's own input. A track is rejected only
when **both** scored windows are <0.18 similar and have no common run longer than
two characters; the fallback is a same-video AI track if one was fetched, otherwise
full ASR (if the configured model is cached). If neither is available, ingest keeps the caption
and marks it untrusted. The gray zone (0.18–0.5, mixed windows, or only one
scorable window) keeps the caption and records `CAPTION_AUDIO_UNVERIFIED`.

## Reproduce

- Date 2026-11-01; commit `18454ed`; Windows 11 10.0.26200; Python 3.12.3;
  isolated `VIDEO2AGENT_HOME`; Bilibili login cookie; cached faster-whisper `small`.
- Time: `Measure-Command { video2agent ingest "<url>" --json --force }` in PowerShell,
  plus `overview.metrics` from the same JSON.
- Memory: a Python wrapper started `python -m video2agent ingest "<url>" --force
  --json`, then every 0.2 s summed RSS (`psutil`) for the Python process and all
  descendants (including ffmpeg). Peak/avg are over those samples. A 0.2 s sample
  is a lower bound on a very short spike.
- Verify: `video2agent overview <video_id> --json`, `video2agent map <video_id>
  --limit 50 --json`, and `video2agent evidence <video_id> --at 01:06:46.4 --images 1
  --json`.
- The memory run was a second, warm-cache/network run: its wall times (56.2 s and
  40.3 s) are not the table's first-run wall times.

## Caveats

- Two videos (67 min + 72 min) are not a statistical claim; both happened to use
  AI captions, so they measure the long-video sampling cost, not full ASR cost.
- RSS includes shared DLL pages and Python/ffmpeg children; it is a working-set
  measure for the test machine, not a hard memory limit. Peak was 875.7 MB / 1,077.1 MB.
- Network/download speed affects wall time; `resolve` is the noisiest component
  (8.8 s vs 33.8 s for the two videos).
- Very large compilations (30 h / 113 h) were deliberately not downloaded; they
  are playlists, not single videos.
- For a long video without usable captions, full ASR time scales with audio
  length; this benchmark does not claim that path. The card shows one plain stage
  and a progress ring; there is no ETA by design.

## Full-ASR path (2026-11-01)

A local 3 m 56 s video with no captions, indexed with `--profile fast` in a fresh
home, completed **full local ASR**:

| Metric | Value |
|---|---|
| `transcript_source` | `asr` |
| Segments | 49 |
| Transcript coverage | 0.984 |
| Transcript step | 59.8 s |
| Total ingest | 100.5 s |
| Working set peak / avg | 1,031.8 MB / 926.9 MB |
| Model | cached `small`; configured `tiny` was absent, so the fallback used `small` and warned `ASR_MODEL_FALLBACK` |

The 67-minute local video (no captions, 4,006.5 s) also completed full ASR:

| Metric | Value |
|---|---|
| `transcript_source` | `asr` |
| Segments | 2,132 |
| Transcript coverage | 0.981 |
| Transcript step | 372.4 s |
| OCR step | 156.7 s |
| Total ingest | 532.4 s (8 m 52 s) |
| Working set peak / avg | 2,455.9 MB / 918.0 MB |
| Model | cached `small` via `ASR_MODEL_FALLBACK` |

The peak includes model load; the steady transcription working set was ~944 MB.
The caption path remains the fast path; full ASR is for videos without usable
captions.

## Cloud ASR path (2026-11-02)

The same 67-minute audio was sent to SiliconFlow
`XingChenAGI/XingChenASR-V3.2-Ultra` through the chunked path (3 × 30-minute
chunks, timestamps offset):

| Metric | Cloud |
|---|---|
| Wall time | 499.6 s (8 m 20 s) |
| Segments | 236 |
| First / last timestamp | 2.68 s / 4,006.5 s |
| Request limit handling | 3 chunks, each under 1 h / 50 MB |

Cloud avoids the 464MB local model download but is **not faster** than the local
GPU path on the test machine, and its segment timestamps are much coarser than local
whisper (236 vs 2,132 segments). This is acceptable for transcript search and
coarse citations, not for second-level quote alignment. Cloud OCR was measured
separately at ~2.1–2.7 s per real frame; it is only used for frames the model
explicitly asks to read.

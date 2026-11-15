# Limits policy

Last updated: 2026-11-04

This file separates **product limits** from **resource/token budgets**. A limit is
not allowed to silently become a product limitation.

## Principles

1. A per-wave concurrency limit must never be described as a total analysis limit.
2. A token/cost budget must say what it is for, and be adjustable when the task
   genuinely needs more.
3. A platform/API safety cap must be documented as such.
4. No arbitrary "1-3 candidates" style guidance in the Skill or tool description.
5. If the current code cannot honour a larger request, say so instead of dropping
   videos silently.

## Current hard caps

| Cap | Current value | Kind | Policy |
|---|---:|---|---|
| `processLimit` | 1-10 | Concurrent starts in one shortlist wave | Keep as a resource cap; not a total |
| `shortlist.video_ids` | 100 with `campaign:true`; `processLimit` without it | Campaign queue / single wave | Keep; total target 50-100 is implemented |
| `discover.limit` | 50 per query (pages of 20) | API pagination | 50 is a per-query cap, not a total |
| `evidence --at` | one time or a comma/JSON list | Batch call | `--max-images` caps total images |
| `evidence --images` | 0-6, default 2 | Image-token budget | Keep; explain it is a budget |
| `frames` | 1-8 per call | Image-token budget | Keep default; dense window gets a separate bounded budget; `count >1` is the window cap and `truncated` is explicit |
| OCR budget | 6-240 frames | CPU/time budget | Keep; adjustable |
| Account write batch | 100 | Bilibili/API safety cap | Keep; unrelated to analysis count |
| Library search | 200 most recent videos | SQLite candidate cap | Keep; use `--video`/`--collection` for older records |

## Campaign queue (implemented in the host)

A campaign may contain up to 100 selected videos. The Host starts at most
`processLimit` at a time, starts the next wave after the previous wave has no
running job, and aggregates all rows. A failed video must not block the rest.
The aggregate report lists every selected video exactly once. The client polls
`/api/video2agent/campaign?id=...`; the model can also poll
`command:"campaign"`.

Acceptance:

- 25 mock videos -> 3 waves, all terminal, report has 25 rows;
- running jobs never exceed `processLimit`;
- one failed row does not stop later waves;
- a retried shortlist does not duplicate a video.

## Dense query windows

Dense extraction is not an ingest mode. It is a bounded query window:

- max 5 seconds;
- 1–8 fps;
- at most 15 output frames;
- `mode=change` keeps endpoints plus the strongest frame changes;
- default requests are unchanged (sparse sampled frames).

## Budget policy

- Digest/contact sheet/frames/OCR are token budgets, not evidence that the video
  contains only that much content.
- If a question needs more, the model should ask for a larger budget or a targeted
  window, not pretend the sampled subset is complete.
- Dense extraction is opt-in and bounded to a short window; it is not a global
  sampling mode.

## Cloud ASR/OCR (measured 2026-11-07)

- **Cloud ASR language coverage depends on the chosen model.** 60 s of Russian
  through XingChenASR returned four Chinese filler tokens (`嗯嗯嗯`, `这个`) while
  local faster-whisper returned 25 correct Russian segments. The plugin does not
  guess the language or switch models automatically: a music-only video also has
  no speech, so "too little text" cannot mean "wrong language". A provider that
  returns no text at all is treated as no speech (`CLOUD_ASR_EMPTY` +
  `NO_SPEECH`) and no local pass is spent.
- **Qwen3-ASR works but has no segment timestamps.** It rejects `verbose_json`,
  so Qwen models are called with `json` and 120 s chunks; a citation can be up to
  two minutes wide. 60 s of Russian came back correct and punctuated.
- **Cloud OCR can describe a picture instead of reading it.** On a frame with no
  text it answered "In the image, there is a man …". That is not citable OCR.
  `evidence --ocr-tiles` now uses grounding-guided crops: DeepSeek-OCR returns
  text boxes, each crop is re-read, and a crop is accepted only when it overlaps
  the located line or is numeric; otherwise the located label is kept. Without
  `--ocr-tiles`, a pure description still raises `E_CLOUD_OCR_DESCRIPTION` and the
  caller falls back to local OCR with a warning.
- **The guided path is not a prompt-injection defense.** Video text is untrusted
  content; the Skill must keep treating it as data, never as instructions.
- **Cloud OCR is stronger on dense text.** On a newspaper front page it returned
  structured Markdown with the headline and date; local OCR returned a jumbled
  word list. Use it for a frame known to contain text, not as an index-wide
  replacement.
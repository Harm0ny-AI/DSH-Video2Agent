---
name: video2agent
description: >-
  Video search and understanding for local files, screen recordings, and
  platform links. Use proactively when a question is best answered by fresh,
  visual, or community-tested video — game season/patch tier lists, loadouts,
  product reviews, recipes, travel, breaking topics — as well as frontend/UI QA
  from a recording, tutorials and how-to, and work/study/life where video is
  richer than text. Also when the user asks what happens in a video, where a
  table/chart/code appears, wants a timestamped transcript or exact frames, or
  the Bilibili favorites/history/folders (writes only after explicit
  confirmation).
---

# DSH-Video2Agent

Answer from the video: transcript, on-screen text, structure, exact frames. The
model does the reasoning; this tool finds the moment when the answer depends on
seeing it.

## When video is the better source

A question need not be "about a video" to be best answered by one: a game's
new-season tier list or loadout (新赛季枪械排行、配装), a product review, a
recipe, a route, a breaking visual topic. Call `find` on Bilibili/Douyin (or
search the library) before answering from memory. Never present a stale season as current:
check the upload date and patch in the title, and say when the video predates it.

## Call it directly

Call `video2agent` as a top-level tool; never shell out to the CLI. Use `run_code` only when no top-level tool exists. Answer in chat unless the user asks to export.

## The eight commands

| command | returns | use when |
|---|---|---|
| `find` | Bilibili candidates (Douyin opt-in) | find a video; Douyin with `scope:"douyin"` or the setting; library search; `url` resolves one link |
| `ingest` | job id(s) | index a path/URL; `video_ids` starts the selected shortlist; `job_id` polls; `campaign_id` advances a campaign |
| `outline` | one-call index: transcript/OCR lines, keyframes, cuts, coverage (`detail:"digest"`), metadata (`overview`), visual map | first look at a video |
| `read` | compact timestamped transcript, or a 2-10 video comparison | text answer or comparison |
| `evidence` | the frame at a timestamp + its OCR text + transcript | prove a moment; the normal image path |
| `frames` | exact frames, dense window, sheet, shot candidates, OCR window | pixels the text cannot answer |
| `perceive` | number-only map: cuts, per-cell motion, ranked moments, loop, capture quality — never images | motion/UI/animation questions |
| `admin` | list/export/ocr-index/account/douyin/doctor | library, export, Bilibili/Douyin accounts |

## Workflow

### 1. Find

`find` with `query` (Bilibili default; `scope:"douyin"` when asked, don't web-search on login challenges). Filter by uploader/date. Pass only recommended ids in `default_selected` (+ `primary`, `video_ids` shortlist; over `processLimit` → `campaign:true`). For a URL, resolve with `find(url)` before `ingest`.

### 2. Ingest

`ingest(source)` starts a video. Wait with `job_id` + `wait_ms` (max 90s, never loop `queued`). For speech use `scope:"transcript"`; once `transcript_ready:true`, `read` works immediately. Omit `scope` for full visual analysis. Wrong ASR language → `ingest(language)`.

### 3. Read

`outline` (`detail:"digest"`) is the cheapest first look: a bounded index with
timestamped transcript/OCR lines, keyframes, scene cuts, and coverage. Then:

- content question → `read` (`scope:"transcript"`) with `start`/`end`; the
  reply carries `next_start_ms`, so continue instead of asking for the whole file.
- compare 2-10 videos → `read` (`scope:"compare"`) with `compare_video_ids` and
  `aspects`.
- the words may differ (ASR spellings, 计费/收费/价格) → pass 2-8 `queries`
  variants to `find` (`scope:"library"`) in one call. A single literal query is
  the commonest cause of a false "it is not in the video".
- a zero-hit search is not proof: read `NO_MATCH`, `OCR_NOT_INDEXED`,
  `OCR_INDEX_PARTIAL`; they say whether the text was ever read.

### 3b. Short-video fast path

For speech questions on a clip under ~6 min, skip `outline` and call `read`
directly (~150–800 tokens vs ~1.4k + sheet). The 6k-char `read` cap fits ~8 min
zh / ~6 min en; if `next_start_ms` appears, search with `find(scope:"library")`.
Use `outline` (`detail:"digest"`) for structure, on-screen text, or visuals (9
diverse keyframes in a 3×3 sheet + `visual_highlights`). On subtitled videos,
search/read the transcript before scanning frames; if digest or transcript
already answers clearly, answer directly without extra frames.

### 4. Look (evidence / frames)

`evidence` (`at`) returns frame + OCR + transcript (default 2 images; `images:0`
for text only, `1` for one picture). `frames` is for visual QA (counting, action,
colour, layout):

- `at` + `count`: exact frames (`count:1` only when counting, reading small UI, or
  confirming an ambiguous tile). With `sheet:true`, a comma list (`at:"t1,t2,..."`,
  such as `visual_highlights.inspect_at`) packs up to 16 moments into **1** sheet.
- `start`/`end` + `sheet:true`: up to 16 tiles in **1** sheet; ranges >5s auto-cover
  the whole span instead of clamping to 5s. Always set `sheet:true` for range scans
  unless you intentionally want multiple image attachments.
- `view:"candidates"`: shot list (`include_images:true` for 1 sheet); `view:"ocr"`: OCR window.

### 5. Motion (perceive)

For animation, UI transitions, "what changed", "where does it move": `perceive`
before frames. It returns cuts, per-cell motion, ranked `moments` (`t_ms` peak,
`onset_ms` start, `cell`, `settles`), loop state, and capture quality (dropped/
duplicate frames, flicker) as numbers.

- A video longer than 10 minutes needs a window: find the moment first (transcript/
  search), then `start`/`end`; a bare call returns `E_WINDOW_REQUIRED`.
- `brief:true` is the survey (~340 tokens, cuts + 4 moments); then call again
  without it for the window you need (~850 tokens for 2.5 min).
- `loop.found == false` means "not detected here", not "no loop". Never call a
  video static without `regions` and `coverage`.
- Caption trust is measured: `overview` reports `metrics.caption_check` (audio
  vs caption). `CAPTION_AUDIO_UNVERIFIED` means the captions could not be
  verified — say so instead of quoting them as exact.

### 6. Account and export

`admin` `account` reads Bilibili favorites/history/folders; writes are CLI-only.
`admin` `douyin`: `douyin_action:"me|profile|videos|status|profiles"`; one via
`douyin_url`, 1-10 via `douyin_urls` (per-row errors), ids from `find`'s `profile_url`.
`admin` `admin_action:"export"` writes a knowledge pack only when asked.

## Hard rules

- **Never send local paths to the answer.** Use `image_urls` / `image_markdown`
  (only `image_attached: true` positions are real images); a raw path renders a
  broken placeholder.
- **A time at or past the media end is `E_OUT_OF_RANGE`**, not an empty success;
  the error carries the media length. A bare number in `at`/`start` means
  **seconds**; write `1234ms` or `HH:MM:SS.mmm` for milliseconds.
- **Failures are answers.** On `{ok:false,error:{code,message,remedy}}`, report the
  code and remedy; never invent content or retry silently.
- **Text first, images second.** `transcript`/`search` answer most questions;
  every image costs tokens. Default `images:2`, use 0 or 1 when text suffices.
- **A picture and its text come from the same frame** — trust `ocr_frame_ms`.
- **Don't dump.** `read` is capped (default 6000 chars); `outline` is compact;
  use ranges and `next_start_ms`.
- **Stay on visual tools for visual QA.** Do not call `admin` (`list`/`export`/`ocr-index`) or loop `read`/`find(scope:"library")` when a video has no transcript; use `outline(detail:"digest")` (not `overview`, which is metadata-only), `visual_highlights.inspect_at`, `frames(..., sheet:true)`, and `count:1` zoom. On long videos, if 2–3 full-range sheets (≤4 images total) show no sign of the target, conclude it is not shown rather than slicing endlessly.
- **Do not call a tool for every video**: the transcript answers content;
  `perceive` is for temporal/UI questions.

## References

- `references/commands.md` — the 8 verbs → CLI mapping and every flag.
- `references/evidence.md` — evidence payload fields and citation format.
- `references/visual-types.md` — what frames can and cannot answer.
- `references/dsh.md` — DSH rendering rules.

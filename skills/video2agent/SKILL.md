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

Call the `video2agent` tool as a top-level tool whenever the harness allows it.
Never shell out to the CLI for a tool action. A nested `run_code` call bypasses
the plugin's dock rendering, so use it only when the harness exposes no other way
to reach the tool; the card may stay blank.

## Answer in chat; export only when asked

A video answer belongs in chat. Do not create or export a file unless the user
asks for it.

## The eight commands

| command | returns | use when |
|---|---|---|
| `find` | Bilibili + Douyin candidates | find a video; both by default, `scope:"bilibili"`/`"douyin"` restrict, library search; `url` resolves one link |
| `ingest` | job id(s) | index a path/URL; `video_ids` starts the selected shortlist; `job_id` polls; `campaign_id` advances a campaign |
| `outline` | one-call index: transcript/OCR lines, keyframes, cuts, coverage (`detail:"digest"`), metadata (`overview`), visual map | first look at a video |
| `read` | compact timestamped transcript, or a 2-10 video comparison | text answer or comparison |
| `evidence` | the frame at a timestamp + its OCR text + transcript | prove a moment; the normal image path |
| `frames` | exact frames, dense window, sheet, shot candidates, OCR window | pixels the text cannot answer |
| `perceive` | number-only map: cuts, per-cell motion, ranked moments, loop, capture quality — never images | motion/UI/animation questions |
| `admin` | list/export/ocr-index/account/douyin/doctor | library, export, Bilibili/Douyin accounts |

## Workflow

### 1. Find

`find` with `query`; Bilibili + Douyin by default, `scope:"bilibili"`/`"douyin"` to restrict
(Douyin needs login). Filter with `uploader`, `after`, `before`.
The reply is for you, not a table: read the metadata and call `ingest` with the ids you actually
recommend; everything you will analyze goes in `default_selected` (only those
start, `video_ids` merely lists candidates) plus `primary`. Over `processLimit`
→ `campaign:true`.

A pasted URL → `find` with `url` (title/cover/duration, no download), then
`ingest` once the user wants it.

### 2. Ingest

`ingest` with `source` (local path or URL) returns a job id. Never ingest a
`find` candidate by URL again; the shortlist already started it. Must wait?
`ingest` with `job_id` and `wait_ms` — once, one job (clamped to 90s; a program
dies near 120s: no loops over several jobs). `queued` = the ingest slot is busy
and the job has not started; do not poll it again. Wrong transcript language →
`ingest` with `language`.

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

For a clip under ~6 minutes where the question is about **what was said** (not
what was on screen), skip `outline` and call `read` directly: the whole
transcript usually fits one reply (~150–800 tokens) versus ~1.4k tokens plus a
contact-sheet image for `outline`. Measured: the 6,000-character `read` cap
covers ~8 min of fast Chinese commentary and ~5.5–7 min of English. If the
reply carries `next_start_ms`, it was cut — switch to `search`/`outline` for
the rest instead of paging. Use `outline` when you need structure, on-screen
text, or visuals; use `perceive` for motion. If the user pastes the
transcript/subtitles themselves, answer from that text and use the video only
for the moments that need a picture.

### 4. Look (evidence / frames)

`evidence` with `at` returns the frame plus its on-screen text and transcript.
Default 2 images; `images:0` for text only, `images:1` for one picture.

`frames` is for what text cannot answer (counting, action, colour, layout):

- `at` + `count`: exact frames.
- `start`/`end`: a dense window (≤5 s); `sheet:true` tiles up to 9 frames into
  one labelled image; `windows:N` samples a named range into one coverage image
  and reports covered/missing.
- `view:"candidates"`: shot list (timecodes + keyframes) for "find one segment".
- `view:"ocr"`: OCR every frame of a short window when an on-screen line changes.

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

`admin` `account` reads Bilibili favorites/history/folders; writes are CLI-only
(`--confirm`; folders ≤20 chars, ≤100 videos per write).

`admin` with `admin_action:"export"` writes a knowledge pack only when asked.

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
- **Do not call a tool for every video**: the transcript answers content;
  `perceive` is for temporal/UI questions.

## References

- `references/commands.md` — the 8 verbs → CLI mapping and every flag.
- `references/evidence.md` — evidence payload fields and citation format.
- `references/visual-types.md` — what frames can and cannot answer.
- `references/dsh.md` — DSH rendering rules.
# Architecture

Short map of the pieces and the invariants between them. Read this before
changing a boundary; the tests and inline comments carry the detailed rationale.

## Layers

```
┌─────────────────────────────┐
│ DSH plugin (packages/)      │  host routes + dock cards, no video work
│  index.js / client.js       │
└─────────────┬───────────────┘
              │ spawns the installed CLI (`video2agent …`), never imports src/
┌─────────────▼───────────────┐
│ CLI (src/video2agent/cli.py)   │  argument parsing, JSON envelope, exit codes
└─────────────┬───────────────┘
              │
┌─────────────▼───────────────┐
│ Pipeline (pipeline.py)      │  ingest, evidence, search, overview, chapters
│  media.py  captions.py      │  probe/frames/scenes · Bilibili subtitles
│  bili_account.py            │  account library: read, plan, confirmed writes
│  cloud.py local_models.py   │  OpenAI-compatible cloud ASR/OCR · local model presets/custom
│  visual.py ocr.py text.py   │  OCR + labels · tokens/FTS · segmentation
│  db.py     sources.py       │  SQLite (FTS5) · resolve/download
└─────────────┬───────────────┘
              │
        $VIDEO2AGENT_HOME
        library.db · media/ · derived/ · cookies/ · logs/
```

## Data flow

- **Ingest** (`analyze`): probe → transcript (uploader/AI caption, else ASR) →
  scene cuts → sampled frames (per profile: fast 40 / standard 120 / deep 240,
  `auto` = 120) → OCR only if the profile asks for it (`auto` reads **zero**
  frames up front) → visual segments → one transaction per stage → `ready`.
- **Evidence** (`evidence`): locate the moment, pull the nearest/frames exactly,
  read OCR on demand (stamp with the frame's own time), return text + image
  paths (+ image blocks in DSH) + `frame_ms` / `ocr_frame_ms` / drift.
- **Search**: FTS5 over transcript and OCR tokens plus a `video_fts` title index;
  filters by target set computed **once**, so `--video` cannot change what the
  content query matches.
- **Account library**: `bili_account.py` uses the QR-login jar to read folders,
  paginated favorites, and recent history; `analyze`/`classify-plan` summarize
  locally and return a plan. Writes (create/rename/delete folder, add/remove,
  apply plan) are separate calls, default new folders to private, and are never
  retried automatically. Cookies never leave the process.

## Invariants (each has a test or a check)

1. **A timecode describes the frame that was read**, never the question:
   `frame_ms` = returned image, `ocr_frame_ms` = OCR source, drift reported.
2. **Unmeasured is not zero**: unread text coverage is `NULL`; labels become
   `unknown` with a `reason`; `overview` reports `visual.known` / `coverage`.
3. **Failures never become empty successes**: every error is
   `{ok:false,error:{code,message,remedy}}`; nonsense queries return 0 hits.
4. **Boundary**: times at/after media end are `E_OUT_OF_RANGE` (never clamped to
   an empty success).
5. **Dedupe compares pixels** (32×32 max block diff ≤ 8), per scene, and deletes
   duplicate files only after the DB rows are rewritten.
6. **The user chooses**: a `discover` records what it offered; `ingest` refuses
   those ids unless it receives a single-use token that names them. Only the card
   route (a real click) issues that token; a bare `--confirm` is rejected. The token
   file lives in the user's own home, so this stops a caller from silently skipping
   the card — it is not a defence against a same-user attacker, and does not claim
   to be.
7. **Account writes are planned, explicit, and never retried.** Read actions
   return summaries, not cookie material; `classify-apply` without `confirm` is a
   dry run; every write names its target and reports a partial failure as a
   failure, not an empty success.
8. **The live DSH home is read-only to this repo.** Tests use `DSH_HOME` /
   `VIDEO2AGENT_HOME` copies; `scripts/check-live-home.ps1` fails the build if a
   script gains a destructive command against `~/.dsh` or `~/.video2agent`.

## Storage

`library.db` tables: `videos`, `segments`, `scenes`, `frames`, `ocr_tracks`,
`visual_segments`, `evidence`, `jobs`, `collections`, `ocr_anchors`,
`collection_videos` + FTS5 tables `segment_fts`,
`ocr_fts`, `video_fts`. Derived media lives under
`$VIDEO2AGENT_HOME/derived/<video_id>/` (frames, audio). Session/workspace state is
DSH's, not ours.

## What this is not

Not an editor, not a note template, not a summarizer. No MCP server by design.
The product is the evidence: exact time, exact frame, exact text, plus the
honest note when any of those could not be measured.

# Commands: the eight tool verbs → CLI

The tool exposes eight verbs. The CLI keeps the full names; the Host maps the
verbs onto them, so a script can use either.

| verb | key params | CLI |
|---|---|---|
| `find` | `query`, `uploader`, `after`, `before`, `covers`, `limit`; `scope:"library"`; `url` | `discover` / `search` / `resolve` |
| `ingest` | `source`; `video_ids` + `default_selected` + `primary`; `job_id` + `wait_ms`; `campaign_id` | `ingest` / `shortlist` / `jobs` / `campaign` |
| `outline` | `video_id`, `detail` (`digest` \| `overview` \| `map`), `count`, `max_chars`, `start`, `end` | `digest` / `overview` / `map` |
| `read` | `video_id`, `scope` (`transcript` \| `compare`), `start`, `end`, `max_chars`, `aspects` | `transcript` / `compare` |
| `evidence` | `video_id`, `at`, `images`, `max_images`, `ocr_tiles` | `evidence` |
| `frames` | `video_id`, `at` / `start`+`end`, `count`, `fps`, `max`, `mode`, `sheet`, `windows`, `crop`, `scale`; `view:"candidates"` / `"ocr"` | `frames` / `candidates` / `ocr-window` |
| `perceive` | `video_id`, `start`, `end`, `fps`, `max_frames`, `brief` | `perceive` |
| `admin` | `admin_action` (`list` \| `export` \| `ocr-index` \| `account` \| `doctor`), `video_id`, `format`, `account_action`, `folder_id`, `days` | `list` / `export` / `ocr-index` / `account` / `doctor` |

## Flags worth remembering

- `at`/`start`/`end`: a bare number is **seconds**; `1234ms` or `HH:MM:SS.mmm`
  is milliseconds. A time at/past the media end is `E_OUT_OF_RANGE`.
- `frames` dense windows are capped at 5 s; `windows:N` needs both edges.
- `evidence` defaults to 2 images; `images:0` is text-only.
- `perceive`: `brief` ≈ 340 tokens; a full 2.5 min map ≈ 850; >10 min needs a
  window unless `start`/`end` is explicit.
- `admin account` is read-only in the tool; writes are CLI-only (`--confirm`).
- `export`: `format` = `md` / `html` / `json` / `knowledge`; redacts paths unless
  `--include-paths` (CLI).

# Video-MME benchmark — chunk 01, 90 questions

This is a small, honest measurement of agent answers through the real
`video2agent` CLI. It is not a leaderboard: 90 questions from one Video-MME
chunk give a 95% confidence interval of roughly ±8–9 percentage points, and the
runs differ in how much effort the agent was allowed to spend.

## What was answered

- 30 videos from Video-MME `test` chunk 01 (short/medium/long).
- 90 questions: 15 per run group × 6 groups, 66 questions with captions, 15 that
  need ASR, 9 with no transcript (music/ambience).
- Answer key stayed in a parquet file the answering agents never read; each
  answer records `calls` and the images actually viewed.

## Runs

| Run | Protocol | Accuracy | CLI calls | Images | Guesses |
|---|---|---:|---:|---:|---:|
| Baseline (before the five upgrades) | real CLI, no per-question budget stated | **73/90 = 81.1%** | 526 | 355 | 30 |
| Upgrades + 12 calls / 25 images budget | real CLI, agent told to stay within the budget | **74/90 = 82.2%** | 465 | 347 | 7 |
| Upgrades, no budget | real CLI, agent records its own effort | **78/90 = 86.7%** (95% CI 79.7–93.7) | 993 | 801 | 1 |
| Final (`ocr-window` shipped) | real CLI, no budget, new tools available | **79/90 = 87.8%** (95% CI 81.0–94.6) | 537 | 241 | 0 |
| Cloud ASR + guided OCR | Qwen3-ASR (26) + XingChen (4), DeepSeek-OCR grounding → crop → cloud OCR | **76/90 = 84.4%** (95% CI 75.6–90.5) | 550 | 276 | 5 |

The cloud run is a separate configuration: 30 videos were re-ingested with cloud ASR and on-screen
text used the grounding-guided cloud OCR path. Six questions improved over the earlier cloud run and
four regressed; the difference is inside the confidence interval. It remains below the local-caption
run (87.8%).

The final run adds one question: the OCR question whose phone banner changed
mid-window is now answerable, and the OCR task is 5/5. It also uses 46% fewer
calls and 70% fewer images than the previous uncapped run, because the agents
used `digest`/`candidates`/`frames --sheet` instead of blind scans. That is one
question, inside the confidence interval; the honest claim is "no regression,
cheaper and better on OCR", not a new level.

Read these as three different protocols, not as a feature-only comparison: the
uncapped run spends 2.1× the calls and 2.3× the images of the capped one. The
capped run is the realistic default; the uncapped run is the ceiling when the
agent may keep looking.

## By task type (capped → uncapped)

| Task | n | Capped | Uncapped |
|---|---:|---:|---:|
| Action Reasoning | 9 | 77.8% | 77.8% |
| Action Recognition | 10 | 80.0% | **100%** |
| Attribute Perception | 5 | 40.0% | 60.0% |
| Counting Problem | 7 | 71.4% | 42.9% |
| Information Synopsis | 10 | 100% | 100% |
| OCR Problems | 5 | 80.0% | 80.0% |
| Object Reasoning | 13 | 100% | 92.3% |
| Object Recognition | 12 | 91.7% | **100%** |
| Spatial Perception | 4 | 50.0% | 75.0% |
| Spatial Reasoning | 1 | 100% | 100% |
| Temporal Perception | 3 | 66.7% | **100%** |
| Temporal Reasoning | 11 | 81.8% | **90.9%** |

By duration: short 90.5% → 95.2%, medium 74.1% → 81.5%, long 83.3% → 85.7%.

## Counting subtest (7 questions)

The seven `Counting Problem` questions were rerun twice with the counting tools
(`frames --windows`, `frames --sheet`) and compared with the earlier runs:

| Run | Correct |
|---|---:|
| Baseline | 3/7 |
| Upgrades, 12/25 budget | 5/7 |
| Upgrades, no budget | 3/7 |
| Counting tools, agent A | 6/7 |
| Counting tools, agent B | 4/7 |

The two new runs disagree (6/7 vs 4/7), so the tools are not proven to raise
counting accuracy at this sample size. What is measurable is cost: the
`792-1` "how many magic shows" question fell from 53 calls (uncapped, no sheet)
to 17 and 9 calls with `--windows`/`--sheet`.

## What the misses are

- `445-3` ("how many points does a three-pointer count") expects 2, while
  basketball rules say 3. Three agents answered 1, 2 and 3. This is a dataset
  annotation quirk, not a tool defect.
- `314-1` ("donations before she started playing") — frame 0 already shows her
  playing, and no donation appears in the first seconds; the event is outside the
  clip. No retrieval tool can recover it from this file.
- `884-1` ("goals of the interviewed player") — there is no on-screen scoreboard
  (checked at 0:20 and 1:52); the count exists only in commentary ("one nil").
  Scoreboard OCR would not help.

## Latency (17-step CLI bench, same fixture)

- Read paths unchanged versus pre-P2: search 333–337 ms (329–335), overview
  446–453 ms (447), evidence with 4 images 2938–3037 ms (3030), polls 151–162 ms
  (152–160). No read-path regression.
- `ingest-sync` shows 6.3 s cold versus 0.65 s warm: the bench reuses a ready
  fixture, so a dropped dedupe is not a slowdown.
- `ocr-window` was 69 s for a 7 s window when every frame used 3×3 tiles
  (135 OCR passes). It is now 15.5 s with the default full-frame pass and skips
  unchanged frames; `--tiles` stays available for one small-text frame via
  `evidence --ocr-tiles`.

## Reproduce

The answer files (`answers/real_*.json`, `real2_*.json`, `real3_*.json`,
`count_*.json`), the question key and the analysis scripts are benchmark
artifacts kept outside this repository; the numbers below are reproduced from
real CLI runs on the same 90-question subset.
They are not published, so the exact numbers cannot be recomputed from a clean
checkout; the protocol above is what a rerun must follow.

The answering model/provider version and the exact agent prompts were **not
recorded** in these runs. Treat 84.4/87.8 as protocol-level measurements, not a
bit-for-bit reproducible benchmark; a rerun with a different model can move the
score by several questions.

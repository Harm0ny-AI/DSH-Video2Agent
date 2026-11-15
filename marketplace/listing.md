# Marketplace listing copy

Prepared for **awesome-dsh-plugin** and DSH storefronts. Nothing here is published.
Claims are limited to what the repository and benchmark docs measure.

## Name

Video2Agent

## One line (EN)

Video search and understanding for DSH: one library for local files and Bilibili, cross-video search, timestamped evidence, and batch analysis.

## One line (ZH)

让 DSH 获得视频检索与理解能力：本地文件与 B 站视频合成一个库，跨视频搜索、时间码证据、批量分析。

## Short card

**EN:** Ask across a library of local files and Bilibili links; get the clip, the video and the timecode. Read 1–10 videos together and let the agent compare what they agree and disagree on. Local-first; cloud ASR/OCR is optional.

**ZH:** 在本地或 B 站视频库里跨视频找信息，返回片段、视频和时间码；一次读 1–10 个视频，让 Agent 读完再比较重点异同。本地优先，云端 ASR/OCR 可选。

## Long description

Video2Agent gives an agent a searchable video library instead of one prompt attachment.

- **Cross-video search:** transcript, scenes, on-screen text (OCR) and sampled frames are indexed in SQLite FTS5. Search returns text and timecodes; `evidence` returns the frame when a quote needs checking.
- **Batch analysis:** ingest 1–10 videos per run, then let the agent read each video before comparing consensus, disagreement and emphasis.
- **Evidence, not vibes:** a hit carries an `evidence_id`; the frame, transcript and OCR text come from the same moment. Missing or unread data is reported as `pending`/`partial`/`failed`, never as a fake zero.
- **Local ASR/OCR by default:** local ASR/OCR runs on this machine; evidence frames/text go to the host model, so a cloud host model sees them. Cloud ASR/OCR is opt-in per section and uses the provider key you configure; keys are stored locally.
- **Bilibili account (optional):** QR login adds keyword discovery, favorites/history/folders and CC/AI subtitles. The DSH account tool is read-only (status/folders/favorites/history/analyze/classify-plan); folder writes are CLI-only with `--confirm`.
- **Expected interfaces:** a `video2agent` tool and `/video` command inside DSH; the same Python CLI works headless.

## Category

`vision`

## Topics

`dsh-plugin`, `dsh`, `deepseek-harness`, `video`, `bilibili`, `retrieval`, `transcript`, `ocr`, `asr`, `timestamp`, `search`, `local-first`

## Install (release candidate)

Until the PyPI/npm release is published, install from the repository:

```bash
git clone https://github.com/Harm0ny-AI/DSH-Video2Agent.git
cd DSH-Video2Agent
python -m venv .venv && source .venv/bin/activate   # Windows: .venv\Scripts\activate
pip install -e .
video2agent setup
video2agent doctor
dsh plugin --profile web add ./packages/dsh-video2agent
```

## Media

- Card: `docs/assets/marketplace-card.png` (1200×630)
- Social preview: `docs/assets/social-preview.png` (1280×640)
- Storefront screenshots: `packages/dsh-video2agent/assets/screenshot-1..5.png`, declared in `packages/dsh-video2agent/screenshots.json`
- Icon: `packages/dsh-video2agent/assets/icon-180.png` (1:1, GitHub-hosted raw URL)

## What not to claim

Do not say “SOTA”, “best video understanding”, “full Video-MME score”, “200+ videos in production”, or “zero setup”. The measured 90-question subset, its configuration and its confidence interval are in `docs/BENCH-VIDEOMME.md`; the plugin is a release candidate, not market-tested.

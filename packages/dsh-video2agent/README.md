# dsh-video2agent

<h3 align="center">B站/抖音收藏夹吃灰？<br>让 Agent 拥有视频检索和理解能力。</h3>

<p align="center">B站/抖音收藏夹吃灰？想要Agent获得视频检索和理解能力？欢迎选择Video2Agent！一键安装，让Agent获取顶尖视频理解能力，并获取网络视频作为信息源。无论你是想调研社会趋势，还是自媒体工作者，只要需要你看视频完成的工作，现在统统交给Video2Agent即可！本地优先，云端 ASR/OCR 可选；B 站/抖音登录可选，解锁收藏夹/历史与 CC/AI 字幕。</p>

<p align="center">
  <img src="assets/screenshot-1.png" alt="Detailed video analysis with keyframes and source-frame evidence">
</p>

Bilibili/Douyin favorites gathering dust? Want your agent to gain video retrieval and understanding? Choose Video2Agent! One-click install gives your agent top-tier video understanding and turns online video into an information source. Whether you are researching social trends or working in media, any task that requires watching videos can now be handed to Video2Agent. Local-first; optional cloud ASR/OCR; optional Bilibili/Douyin login to unlock favorites/history and CC/AI subtitles.

## What you can ask

- 「我收藏夹里这几条，哪条最值得看？」→ 1–10 条批量读完后对比共识与分歧；
- 「这条 40 分钟的视频到底讲了什么？」→ 几分钟读完，带时间码；
- 「第 12 分钟那张表写了什么？」→ 按时间码取同一帧，配同一帧上的文字作证据；
- 「这个视频值不值得看？」→ 用转写、画面上的字（OCR）和关键帧回答，不靠标题。

## Install

```bash
# 1. The Python CLI (the plugin calls this executable)
pip install video2agent          # PyPI; pipx install video2agent also works
video2agent setup                # install the Skill into ~/.dsh/skills
video2agent doctor               # checks Python, FFmpeg and the Python packages

# 2. This plugin
dsh plugin --profile web add dsh-video2agent   # npm
```

Requires Python 3.11+ and FFmpeg. The plugin settings page has an **环境检查**
card that reports what is missing, installs each item, and offers one
**一键安装缺少项** action for CLI, FFmpeg, the optional browser component
(Douyin login) and OCR.

Local on-screen-text OCR is an optional extra (Python 3.11/3.12 —
`rapidocr-onnxruntime` has no 3.13 wheel yet). Core search, transcription and
evidence work without it; cloud OCR does not need it. The browser component is
also optional: it is only needed for Douyin login/account reads.

The cloud API key is stored per platform: DPAPI on Windows, the login Keychain
on macOS, and a 0600 file under `$VIDEO2AGENT_HOME/secrets/` on Linux. A
`SILICONFLOW_API_KEY` environment variable works everywhere. Any DSH 0.2.1 / 0.2.2 profile works; the host
command is optional, so terminal-only setups still get the tool and `/video`.

- PyPI: <https://pypi.org/project/video2agent/>
- npm: <https://www.npmjs.com/package/dsh-video2agent>
- Releases: <https://github.com/Harm0ny-AI/DSH-Video2Agent/releases>

## Screenshots

**详细分析：关键帧、时间码，以及同一帧上的文字证据**

![Keyframes and source-frame evidence](assets/screenshot-2.png)

**设置：环境检查**

![Settings environment check](assets/screenshot-3.png)

**本地 ASR / OCR**

![Local ASR and OCR](assets/screenshot-4.png)

**B 站 / 抖音登录**

![Bilibili and Douyin login cards](assets/screenshot-5.png)

## What it adds

- `video2agent` tool and `/video` command.
- Composer preview for `bilibili.com/video/BV…`, `av` numbers, `b23.tv` links and bare BV ids, plus Douyin video/share/`v.douyin.com` links and the whole share text.
- A session-scoped selected-video table above the composer: cover, title, one plain-language status and stop.
- **Search across videos** (the default scope), **batch analysis** of 1–10 videos, and **evidence** frames with transcript/OCR from the same moment.
- Optional Bilibili QR login for discovery, favorites/history/folders and CC/AI subtitles. The DSH account tool is read-only; folder writes are CLI-only with `--confirm`.
- Optional Douyin login for your own profile and works/favorites/liked lists; the same read is exposed to any session as `admin_action:"douyin"`, and a risk-blocked list reports `unavailable` with a reason.
- Local ASR/OCR runs on this machine; only the frames/text you ask for reach the host model. Cloud ASR/OCR is opt-in per section and uses the provider key you configure.

## Manifest

`package.json` declares:

```json
"dsh": { "bundle": { "patch": "./cordis.patch.yml" }, "client": { "platform": "web" } }
```

The host command is optional (`webServer` is injected, not required), so terminal-only setups still get the tool and `/video`.

## Documentation

- [Repository README](https://github.com/Harm0ny-AI/DSH-Video2Agent#readme)
- [Architecture](https://github.com/Harm0ny-AI/DSH-Video2Agent/blob/main/docs/ARCHITECTURE.md)
- [Benchmark and limits](https://github.com/Harm0ny-AI/DSH-Video2Agent/blob/main/docs/BENCH-VIDEOMME.md)
- [Security](https://github.com/Harm0ny-AI/DSH-Video2Agent/blob/main/SECURITY.md)

Apache-2.0.
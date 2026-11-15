# B 站字幕调研（2026-10-26）

目的：搞清楚 B 站视频的字幕到底有哪几种、怎么取、为什么之前一直回退到 ASR，
以及哪些情况我们取不到、只能 OCR。

结论先行：**B 站字幕（含 AI 字幕、双语/多语言）必须带登录 cookie 才能读到**；
匿名请求 `player/v2` 返回空字幕列表。硬字幕（烧进画面）API 永远拿不到，只能 OCR。

## 1. 三种“字幕”

| 类型 | 来源 | 能否经 API 取到 | 说明 |
| --- | --- | --- | --- |
| 软字幕（UP/社区上传） | `subtitles[]` 里 `kind=human` | 能，**需登录** | 可多语言，质量最高（UP 校验过） |
| AI 字幕 | `subtitles[]` 里 `lan=ai-zh` 等，`kind=ai` | 能，**需登录** | B 站自动语音识别，通常单语中文，部分双语 |
| 硬字幕 | 画面像素 | **不能** | 只能 OCR；卡在视频里，无法切语言 |

## 2. 取字幕的链路

```text
x/web-interface/view?bvid=…        -> data.pages[0].cid / data.aid
x/player/v2?bvid=…&cid=…           -> data.subtitle.subtitles[]   # 需登录
  {lan: "ai-zh"|"zh-Hans"|"en-US", lan_doc, ai_type, subtitle_url}
GET subtitle_url                   -> {"body":[{"from":1.2,"to":3.4,"content":"…"}]}
```

`subtitle_url` 带有时效 `auth_key`，不能长期缓存；每次重试都要重新请求列表。

## 3. 实测与资料

- 本机匿名实测：**21 个视频（含 6 个热门 UP、12 个跨领域）全部 `subtitles: []`**，
  `bvid` / `aid` / `wbi` 签名三种调用方式结果一致；yt-dlp（自带 WBI 签名）也只列出
  `danmaku`（弹幕），没有 `zh-*` / `ai-zh`。
- 独立资料一致：
  - 「必须带登录 cookie（SESSDATA）：匿名请求 `player/v2` 返回的字幕列表为空」；
    批量场景还会出现「假残缺」——URL 或 body 为空、或只回一部分，需要递增重试并重新取 URL。
    —— [批量下载 B站字幕：限流排查与「假残缺」识别实战](https://www.cnblogs.com/ljn233/p/22489804)（2026-08-15）
  - 「下载字幕需要登录；没字幕可选时，要么视频没有字幕，要么你没登录」；
    字幕支持最多 15 种语言 + AI 字幕，分软字幕/硬字幕两种。 ——
    [How to Download Bilibili Videos with Subtitles](https://j4rviscmd.github.io/bilibili-downloader-gui/guides/download-with-subtitles/)（2026-10-07）

两者均于 2026-10-26 访问。

## 4. 我们的实现

### 4.1 扫码登录（推荐，不需要导文件）

`src/video2agent/bili_auth.py` + 插件设置页：

- `video2agent biliauth --start` 调 B 站官方二维码接口拿 `url` + `qrcode_key`，用
  OpenCV 的 `QRCodeEncoder` 画成 320px PNG（**零新依赖**，自检：再用
  `QRCodeDetector` 解回来必须等于原 URL，测试里有这一条）。
- 插件设置页点「扫码登录」→ 显示二维码 → 每 2 秒轮询 `--poll`；
  状态 `pending`（未扫）/ `scanned`（已扫待确认）/ `ok` / `expired`。
- 确认后，B 站把 cookie 放在回调 URL 的查询串里，Python 侧直接解析并写入
  `$VIDEO2AGENT_HOME/cookies/bilibili-login.txt`（Netscape 格式，0600）。
  **cookie 不经过任何 HTTP 路由**，插件只能看到 `{state, uid}`。
- 这个文件与匿名 412 修复用的 `cookies/bilibili.txt` **分开**，后者不会覆盖它；
  `captions.cookie_path()` 与 yt-dlp 的 `--cookies` 都优先用登录文件。
- 设置页还有「退出登录」；CLI 是 `biliauth --clear`。

### 4.2 取字幕轨

`src/video2agent/captions.py`：

- `video_cid` → `subtitle_tracks`（丢弃 `subtitle_url` 为空的项，那是限流特征）→
  `rank_tracks`（最多 3 个候选）→ 逐个 `fetch_track`，**取段数最多的那条**
  （人工轨只在一个 20% 的差距内才靠排序胜出）。
- 轨道优先级：**中文人工 > 中文 AI > 其他中文 > 英文人工 > 英文 AI > 其他**，
  但"够长的"优先于"更官方的"。
- 限流处理：最多 3 次，退避 2s / 4s，**每次重新取列表**（拿新的 `auth_key`）；
  body 为空同样重试，最后如实报 `reason=empty`。
- 结果带 `track`（`lan`、`lan_doc`、`ai`、`kind`）和 `tracks`（该视频可用的语言列表），
  所以报告里能写清“用的是 AI 字幕还是 UP 字幕”。

`pipeline.py`：

- 顺序：本地 sidecar → 内嵌字幕 → 下载的字幕文件 → **B 站字幕轨** → ASR。
- 用了字幕 → `metrics.transcript_source="caption"`；用了 ASR → `"asr"`；
  `metrics.caption_track` / `metrics.caption_tracks` 记录具体轨道。
- 未登录 → 警告 `CAPTION_LOGIN_REQUIRED`（说明需要 cookie 及怎么给）；
  已登录但仍取不到 → 警告 `CAPTION_UNAVAILABLE`（可能视频真没字幕轨，或限流）。

DSH 插件：

- 设置页新增 **“B 站 Cookie 文件”**，填导出文件的路径即可；`ingest` 和失败重试都会自动
  带 `--cookies <路径>`（只存路径，不存 cookie 内容）。
- 完成态卡片会标出来源：`已完成 · 字幕/AI 字幕/语音识别 · 总长 … · 证据索引可用`。

CLI：

```powershell
video2agent biliauth --status         # 是否已登录
video2agent biliauth --start --json   # 拿 key + 二维码（data URL）
video2agent biliauth --poll <key>     # 扫码确认后自动保存登录
video2agent ingest "https://www.bilibili.com/video/BV..." --force   # 重灌已有视频
video2agent doctor --json             # bilibili_login
```

## 5. 已知限制

- **没有登录就永远只有 ASR**：这不是 bug，是 B 站的服务端行为。
- **硬字幕只能用 OCR**：当前 OCR 是稀疏采样，只抓零散几行；密集 OCR 字幕轨
  按用户决定**不做**（算力开销太大）。
- **双语**：目前只取一条轨道（中文优先）。`metrics.caption_tracks` 已记录可用语言列表，
  但还没有“同时产出中英双语”的输出格式。
- **登录过期**：`SESSDATA` 会过期；过期后表现为 `CAPTION_UNAVAILABLE`，重新扫码即可。
- 未验证：真实扫码确认后的端到端取字幕（本机没有 B 站手机端可扫）。
  二维码生成/解析、cookie 解析、保存与优先级、轮询状态映射都有离线测试
  （`tests/test_bili_auth.py`）。

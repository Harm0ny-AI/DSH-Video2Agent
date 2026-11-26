# Changelog

## 0.3.8 (2026-11-26)

- **Ask about the subtitles while visual analysis continues.** Once subtitles
  are ready, the agent can read them and check known moments in the video.

- **Reopening a conversation verifies saved video jobs before showing progress.**
  Missing or temporarily unavailable status no longer revives old running cards.

- **Bilibili fallback search honors creator and date filters.** Results with
  dates that cannot be verified are excluded when a date filter is in use.
- **The Douyin search setting explains when Douyin search is used and when
  manual verification is required.**
- **Background video jobs stay windowless on Windows.**

- **Search covers the full ready library.** Older videos can match via
  subtitles, speech transcripts, on-screen text, titles and descriptions, even
  in libraries with more than 200 videos. Expensive per-video fallbacks are
  still bounded and report their coverage.
- **Local on-screen text reads use fewer CPU resources.** Default RapidOCR
  sessions have bounded CPU thread pools, improving single-frame reads and
  short-window OCR without changing the models, input frames or output format.
- **Video outlines scan only audio for speech and loudness hints.** Picture
  decoding is no longer repeated for this step.

- **Settings no longer offer a redundant engine update.** While the plugin is
  waiting for DSH to reopen, the update row only prompts for that restart. If
  the video engine is already up to date, stale update and retry buttons stay
  hidden.

- **Re-analysis preserves the previous result until the new analysis succeeds.**
  Earlier evidence remains available, and reprocessing a link after media
  cleanup restores the source without rebuilding the index when the bytes match.
- **Evidence text matches the returned frame.** Library searches honor the
  requested time range, and saved evidence can be reopened from the plugin tool.
- **Video tasks recover more reliably.** A failed first wave can leave later
  videos queued for processing. Search progress stays with its conversation,
  retry keeps the original analysis options, and a stopped worker is reported
  while waiting.
- **The existing 20 GB media cache limit is enabled by default.** Explicit
  cache settings still apply, and automatic cleanup preserves the searchable
  library.

- **Updated download security dependencies.** Requires yt-dlp 2026.10.26 or
  later and certifi 2026.10.19 or later.

## 0.3.7 (2026-11-24)

- **Older engines move into a versioned private environment on startup.** An
  install whose record has no provenance, or that only exists as a
  `video2agent` command on PATH, is now adopted automatically when the 0.3.7
  plugin loads. The plugin builds a fresh venv under
  `<home>/engines/0.3.7/venv-*` from the interpreter that really runs the old
  CLI (the CLI's own `doctor` for a pipx/venv wrapper, otherwise every Python
  candidate rather than the first one on PATH), installs the exact plugin
  version there, and switches the record in one atomic rename only after the
  new engine and the components the old one had (browser/OCR) are verified.
  The old environment is never modified or deleted, so a failed attempt simply
  keeps it in use. Explicit `VIDEO2AGENT_BIN`/`VIDEO2AGENT_PYTHON` pins, an
  editable checkout and a direct-URL install stay on the manual update path.
- **OCR and browser components install into the engine's own environment.**
  The card used to pip-install into whichever `python` came first on PATH, so
  it could say "已安装" while `models status` still reported OCR missing. The
  install now runs in the interpreter the managed record names, or the one the
  CLI's own `doctor` reports for a PATH/pipx engine, and refuses with an
  actionable message when no trustworthy interpreter can be identified. It
  pins `video2agent[ocr]==<installed version>` instead of `--upgrade`, so
  satisfying the extra cannot backtrack or replace the core engine.
- **Link previews follow the settings TTL.** The Host's resolve cache used a
  hard-coded 24 hours, so a cached preview kept resolving long after the page
  would have refreshed it (or the reverse). It now judges entries against the
  same `cacheTtlMs` the composer persists.
- **Cards stop contradicting their own state.** A failed manual engine update
  that was followed by a running update no longer shows "更新失败" plus a retry
  button under "正在更新"; a busy lock keeps following the run, so
  "有安装任务正在进行" clears when the update settles; the queue poll's first
  tick uses the same guard as its interval, so a slow read no longer starts a
  second `/job` (each spawns Python); a Douyin link card is labelled
  "抖音视频" instead of Bilibili.
- **Douyin creator batches and homepage links.** `admin douyin` gains a
  `profiles` action: 1-10 homepage URLs or sec_uids in one browser session
  (`douyin profiles --urls` from the CLI), one page per person (~12s each,
  bounded), deduped by sec_uid, with a per-row error so one bad link does not
  abort the batch. A partial batch keeps its successes; an all-failed batch
  answers `E_DOUYIN_PROFILES` and still lists every row. `find` Douyin
  candidates now carry a verified `profile_url` built from `uploader_sec_uid`,
  so find → profiles needs no URL rebuilding. Each page is confirmed to be the
  requested `/user/<sec_uid>` and its counters wait for the profile JSON's
  exact numbers (14064/301208) instead of a fixed 9s sleep, so a redirect or
  another person's cached response cannot be returned as the target.
- **Windowed `perceive` timestamps are source time.** A windowed scan mixed
  two clocks: cut and moment timestamps were window-local while shot rows used
  source time, so every windowed cut and moment was shifted by the window
  start, attributed to the wrong shot, and the loop analysis compared frames
  from the wrong part of the window. The offset is now applied exactly once,
  when a window-local frame index becomes a timestamp; `perceive` with
  `start`/`end` reports the same coordinates as a full scan.

## 0.3.6 (2026-11-23)

- **A plugin-managed video engine follows the loaded plugin.** After the 0.3.6
  plugin loads, the environment card reports "视频引擎可更新：0.3.5 → 0.3.6" and
  updates the engine in the background; the next tool call uses it, with no
  further DSH restart (the marketplace plugin update itself still takes effect
  on a restart). Only a record that says this plugin installed the engine is
  followed automatically: a record written before provenance existed is never
  auto-updated — one explicit 更新引擎 click performs that update and records the
  authorization — and an engine behind an explicit path/Python pin, an editable
  checkout, a direct-URL install or pipx is reported for manual update instead
  of being overwritten. One install or update runs at a time; an automatic
  update waits for in-flight worker calls and is skipped for that start while
  one is still running, instead of killing the call.
- **The background cache sweep applies the settings page's policy.** The plugin
  row's cache values are the default layer below `ui-settings.json` for
  `gc --auto`, so a page showing 关闭 no longer falls back to the 7-day default
  and frees a cache the user kept. A corrupt settings file still fails closed,
  and a malformed host value is rejected before anything is deleted.
- **Search status lines expire with their phase.** Searching, curating, no-result
  and error lines each have their own budget and timer, so a line no longer stays
  above the composer while the model keeps thinking or the poll is throttled. A
  conversation switch, the end of the turn, or disabling the plugin clears it; a
  shortlist still holds its busy line briefly so it does not blink out before the
  table paints.
- **Douyin 图文 posts are no longer offered as video candidates.** Keyword search
  mixes image carousels into its results (`images` / `aweme_type` 68, no
  duration); their play address is the background music, so ingesting one failed
  with an opaque 404 on an mp3 URL (live 2026-11-23: the first 蓝莓 result was a
  图文 post). Search now skips them and reports `IMAGE_POSTS_SKIPPED` with the
  count, and a pasted 图文 URL returns `E_DOUYIN_IMAGE` before any download.
  Live: 蓝莓 returned 5 videos after skipping 3 图文 posts; the same post now says
  "这是抖音图文作品（图片合集），没有可分析的视频".

## 0.3.5 (2026-11-22)

- **Douyin account timelines are complete.** `douyin videos` now scrolls the
  lazily loaded works list until the requested limit, so a 27-work profile returns
  27 rows (live: 15s) and every row carries `published_at`/`published_ts` from the
  page's own `aweme/post` response. That is enough to answer "when did this creator
  last post" without CDP or a search engine.
- **Failed queue rows say 失败 and show the error.** They no longer show raw
  sec_uid/profile URLs as a title or a misleading "未完成" label.
- **Long-running search cards expire.** A `curating` line no longer stays
  forever while the model thinks; busy search lines now go stale after their
  phase budget, clear the Host status, and a newer search still shows. This
  fixes the card that remained until the next tool call or turn end.
- **Profile URLs are not video sources.** Passing a `/user/...` URL or bare
  `MS4wLjAB...` sec_uid to `ingest` now returns a clear E_DOUYIN_USER before a
  failed job row can become the confusing "未完成" batch card.

## 0.3.4 (2026-11-22)

- **Douyin profile uses exact counters, not rounded text.** The page displays
  `1.4万`/`30.1万`, but its own `/user/profile/other/` response carries
  `14064`/`301208`. The profile reader now captures that response and merges
  exact follows/fans/likes/works plus favorites, mixes and signature.
- **Douyin profile counters keep their units.** `粉丝 1.4万` and `获赞 30.1万`
  used to be parsed as 1 and 30 because the regex stopped at digits. Counters now
  convert 万/亿/w, so the card matches the page.
- **Douyin profile reads use the right identifier.** `find` candidates now include
  `uploader_sec_uid`; `douyin profile`/`videos` need that `MS4wLjAB...` sec_uid,
  not the numeric uid. A numeric `/user/<uid>` URL now says so instead of
  returning an empty page. `admin` also accepts `action` as a defensive alias for
  `admin_action`, so a model using the wrong field no longer silently falls back
  to the local library list.
- **Search status cards are turn-scoped.** The "没有找到候选" / "搜索失败"
  card used to remain for ten minutes and could reappear when a later turn
  mounted the composer. Empty/error lines now hide and clear at turn end, with a
  short stale-status fallback in the Host; a genuinely newer search still shows.

## 0.3.3 (2026-11-21)

- **Environment status is a capability check, not a file check.** Playwright now
  only reads green when Chrome/Edge or a Playwright Chromium is actually
  available; a signed-in Douyin card now requires a live `sessionid` cookie, not
  just the cookie file; direct CLI and `doctor` resolve FFmpeg through the
  managed path or the current WinGet package when PATH is stale.
- **FFmpeg detection follows WinGet updates.** When PATH still points at an old
  `ffmpeg-8.x` directory after a WinGet package update, the environment card now
  locates `Gyan.FFmpeg` under the WinGet package directory, verifies ffprobe, and
  records the path for the CLI. This prevents a false red "FFmpeg 未安装" while
  ffmpeg 9.0.2 is installed.
- **Douyin search is opt-in.** `find` now searches Bilibili only by default.
  Douyin is searched only when the user explicitly names the Douyin platform
  (`scope:"douyin"`) or enables the new **抖音搜索** setting. The setting is off
  by default; the helper text warns that Douyin search is strictly risk-controlled
  and that a verification must be completed in the Chrome window.

## 0.3.2 (2026-11-21)

- **No forced Douyin cooldown.** The client no longer writes a ten-minute local
  lock after a verify/risk block. Verification is surfaced immediately; after the
  user completes the check or logs in, they can retry at once. This does not
  bypass Douyin's risk control; it stops the client from hiding the real state.
- **Douyin signed-search fallback with human verification handoff.** When the
  signed endpoint asks for verification, the client opens the logged-in Chrome/Edge
  window on the main `www.douyin.com/search` route (not the 抖音精选 /jingxuan
  shell), brings it to the front, and waits up to three minutes for the user to
  complete the check. It reads the page's own search responses and continues
  automatically; it never clicks or solves the slider. A timeout returns a clear
  E_DOUYIN_VERIFY instead of a raw risk error.
- **One-click environment setup, including the browser.** The settings
  environment card now reports the optional Playwright extra and can install it with the CLI, FFmpeg and OCR from one **一键安装缺少项** action. The
  Playwright install uses the interpreter that runs the CLI, prefers the installed
  Chrome/Edge, and only downloads Chromium when neither is present. The Douyin
  login failure now points at the environment card instead of exposing the raw
  Playwright import error.

## 0.3.1 (2026-11-20)

- **Cache expiry frees media; it no longer deletes knowledge.** The default
  policy (7 days) used to purge the whole record: transcript, OCR index, evidence
  and collection membership included, so a cache setting silently emptied the
  library. Expiry now deletes only the downloaded media and cached frames; text
  search keeps working, `overview` reports `media_released`, and anything that
  needs pixels says the media must be fetched again (a local file is the user's
  own and is never touched). Deleting the record itself is the separate, explicit
  `gc --auto --purge`.
- **A replaced source file is refused, and evidence is snapshotted.** The record
  now stores the source size/mtime/hash at ingest; if the file changed, evidence
  and windowed OCR raise E_SOURCE_CHANGED instead of cutting frames out of a file
  the analysis never saw. Evidence bundle ids are content-addressed, so a later
  read of the same range can no longer overwrite an older citation.
- **Time-window search filters before ranking.** `start_ms`/`end_ms` used to be
  applied to the top result pool; a window hit ranked just below the pool was
  reported as a miss. Segments and OCR rows now filter by the window in SQL,
  before the limit, including the literal fallback.
- **OCR index writes are atomic.** A frame status and its OCR tracks now commit
  in one transaction. An interrupted pass no longer leaves a frame marked read
  with no searchable text; a failure leaves it unread so a retry can redo it.
- **Cancelling an ingest no longer leaves the queue lock behind.** A cancel that
  arrived right after the lock was acquired raised before the cleanup block, so
  the next ingest waited the full 180-second stale window.
- **The pip mirror keeps TLS verification.** The fallback to the Tsinghua mirror
  passed `--trusted-host`, which turned a certificate problem into a silent
  downgrade to unauthenticated package downloads.

- **Douyin keyword search, without a browser.** `find` now searches Bilibili and
  Douyin by default; `scope:"bilibili"` / `scope:"douyin"` restrict it
  (CLI: `discover --platform all|bilibili|douyin`). Results are paginated up to
  three pages / 50 items, and filters keep fetching until they have enough or run
  out. Successful searches are cached for five minutes; a verify/risk block sets
  a ten-minute cooldown instead of hammering Douyin. It uses the saved Douyin login cookie and a
  vendored Apache-2.0 a_bogus signer to call Douyin's signed web search endpoint,
  then returns the same candidate shape as Bilibili. No Playwright, no TikHub, no
  third-party search key. Missing login, risk pages and non-zero status codes are
  reported explicitly instead of returning a fake empty result.
- **A Douyin risk check is no longer shown as "no results".** When Douyin wants a
  slider check it answers HTTP 200 with status_code 0, an empty data list and
  `search_nil_info.search_nil_type="verify_check"`; that was classified as
  NO_RESULTS (seen live on 2026-11-20 after a burst of searches), so a blocked
  search looked like a harmless empty one. It now raises E_DOUYIN_VERIFY with a
  verify/re-login remedy; a genuinely empty search still reports NO_RESULTS, and
  real results still win over a stray nil marker.

## 0.3.0 (2026-11-18)

- **TUN + fake-ip proxies no longer break remote ingest.** Clash Verge/mihomo TUN
  mode resolves every domain into 198.18.0.0/15 (RFC 2544, is_global=False), and
  the URL guard read that as a private-network target: every remote ingest failed
  with E_PRIVATE_URL even though the proxy resolves the name remotely and the real
  stream is pulled by yt-dlp. 198.18.0.0/15 is now treated as a proxy marker for
  any host; a literal private address still resolves to itself and is rejected.
- **allow_private_urls now survives redirects.** safe_urlopen's redirect handler
  dropped the flag (Bilibili answers with many 302s), so the documented escape
  hatch never worked there. It is propagated now; cover downloads and b23.tv
  short-link resolution pass it through too.
- **allow_private only skips the public-address requirement.** Cloud metadata
  endpoints (169.254.169.254, 100.100.100.200, fd00:ec2::254, metadata host
  names) and link-local addresses stay blocked in every mode.

- **Douyin (抖音) video source (experimental).** URL recognition covers
  douyin.com/video/<id>, iesdouyin share pages, discover?modal_id and
  v.douyin.com short links (the whole share text works too); the short link is
  resolved with one 302 request. Metadata comes from the iesdouyin SSR share page
  (_ROUTER_DATA) with 4 backoff retries and explicit state classification (full
  SSR / JS shell / captcha middle page / hard block); a blocked read reports
  E_DOUYIN_RISK instead of pretending the video is empty. Download uses the
  play_addr.uri to build the no-watermark mp4 URLs (1080p/720p/fallback domain,
  watermarked last resort) and reuses the whole ingest pipeline (ASR, OCR,
  scenes, frames, retrieval). The plugin composer recognizes Douyin links and
  the cover proxy serves Douyin CDN images. Metadata reads use browser-like sessions (homepage warm-up, anonymous
  ttwid, rotating UA) plus a 6h metadata cache, so a resolve followed by an ingest
  survives Douyin's intermittent captcha. Douyin search is not supported (`find`
  stays Bilibili-only).
- **Optional Douyin account reads (experimental).** With
  `pip install "video2agent[browser]"`, `video2agent douyin profile` / `me` read a
  profile through the installed Chrome or Edge via Playwright, and
  `video2agent douyin login` saves a QR screenshot, waits for the scan and stores
  a cookie jar. Douyin's JSON APIs need the a_bogus/secsdk/uifid signature stack,
  so plain requests cannot read them; the browser extra is optional and no
  browser is bundled.
- **Douyin account reads are honest about failures.** `video2agent douyin videos`
  lists works/liked videos; a risk-gated list reports unavailable (with a reason)
  instead of pretending it is empty. Invalid targets, a logged-out `me`/`videos`,
  Douyin user-page ingestion and invalid ids return clear E_DOUYIN_USER /
  E_DOUYIN_LOGIN / E_SOURCE / E_DOUYIN_ID errors instead of empty success; the
  composer preview labels Douyin links 抖音视频, and the host retry route accepts
  platform URLs so a failed Douyin start can be retried.
- **Douyin liked and saved videos are read from their real tabs.** The old flow
  clicked the tab pane (user-like-tab), not the clickable "喜欢" header; the click
  timed out, the error was swallowed, and the empty works pane came back as ok:true
  / 0 videos. It now clicks the real role=tab, verifies that it became active, reads
  the matching pane (user-like-list / user-favorite-list), and reports unavailable
  (with a reason) when the switch fails. New tab: `douyin videos --tab favorites`
  (收藏). Verified live: 5 liked videos in 15.9s and 5 favorites in 16.3s from the
  logged-in account. Profile counters also survive the live badge now sitting
  between them (关注 174 / 粉丝 127 / 获赞 0) instead of returning null.
- **Any DSH session can read a logged-in Douyin account.** The tool's admin
  action `douyin` maps to `me` / `profile` / `videos` / `status` (works,
  favorites, likes), so a session that is not the CLI can answer "read my Douyin
  account" instead of falling back to the Bilibili-only `admin account`. Read-only;
  login stays in the settings card / CLI. Verified: `admin douyin status` through
  the host harness.
- **The environment card asks the CLI for the OCR state.** It used its own
  `py -3` probe, which on Windows can resolve a different Python than the CLI runs
  (measured: the card said "OCR 未安装" while the CLI had rapidocr installed). It
  now reads `video2agent models status` first and only falls back to a Python
  import probe, so the chip reflects the interpreter that actually runs OCR.
- **Douyin QR login is in the settings page.** The 0.3.0 environment card gained a 抖音登录 block next to the Bilibili one: the Host tracks one `douyin login` child, serves its QR screenshot, and polls until the scan lands, then stores the cookie jar and account cache. CLI-only before this; the QR/clear flow was end-to-end tested through the Host routes.
- **Fix: the Douyin login card stopped polling after its first tick.** The effect was keyed on `[state, qr]`, so a first poll without a QR left both values unchanged and never polled again — the backend had the QR image ~11s after the click while the card sat on "等待扫码" forever. It now polls on a fixed interval and shows a "generating QR" hint; verified in the real settings UI (QR image rendered at t=12s).
- **Fix: the Douyin login view no longer shows the slider verification as if it were the QR.** `douyin login` now opens a visible Chrome/Edge window (complete the slider there), screenshots only a real QR element (login-modal QR) and reports `E_DOUYIN_VERIFY`/`stage=verifying` in headless mode instead of saving the captcha page as the QR; the settings card explains the verification step and updates to the QR once it is passed.
- **The Douyin login card only shows a real QR.** Page screenshots (captcha or video frames) are no longer written into the QR slot, so the card cannot show a stretched, constantly-changing screenshot: before the QR exists it shows a text hint, then the login-modal QR element, then `已登录` after the scan; the image keeps its aspect ratio instead of being forced into a 180x180 box.
- **The login card captures the real QR once.** The previous flow screenshotted a wide login banner (measured 813x261) every 1.5s into the QR slot, so it looked stretched and made the visible Chrome window flash. Login now scans every img/canvas inside the login modal, accepts only a 90-600px square candidate (the real desktop QR is 179x179), screenshots it exactly once, and stops capturing while waiting for the scan; page screenshots are never written to the QR slot.
- **The login QR is generated in the background.** `douyin login` is headless by default (normal Chrome UA + no automation flag), so the settings page gets the QR without a browser window popping up; a captcha falls back to an off-screen window, and only a real slider opens a visible window (`--headed` forces it). Verification detection now matches the strong slider phrases only ("验证码登录" is an SMS-login tab, not a captcha). Verified: QR captured at ~16s with no visible window.

## 0.2.0 (2026-11-17)

- **Local OCR now installs on Python 3.13 with one click.** The OCR extra installs
  rapidocr 3.x (pure-Python wheel, bundled PP-OCRv6 models) instead of
  rapidocr-onnxruntime, which has no 3.13 wheel. Both engines are supported at
  runtime (3.x preferred, legacy fallback), so existing installs keep working and
  the environment card's 安装 OCR button works on Python 3.11-3.13.
- **An outdated CLI can be updated from the card.** When the installed Python CLI
  is older than the npm build, the card shows CLI 可更新 (e.g. 0.1.8 -> 0.2.0) with
  a one-click 更新 CLI button. Without it a 0.1.8 CLI could not save the API key
  on macOS while the page looked healthy and offered no fix.
- Settings page: the local-OCR option names the actual model (PP-OCRv6 / PP-OCRv4),
  and the same Key-store error is no longer rendered twice.
- doctor reports rapidocr 3.x as the OCR package; CI still tests the legacy
  rapidocr-onnxruntime engine on Python 3.11/3.12.

## 0.1.9 (2026-11-17)

- **macOS/Linux can save the cloud API key now.** The settings page used to
  write the key through Windows DPAPI only, so on macOS saving failed with
  "当前系统没有可用的 Windows DPAPI 密钥存储" and cloud ASR/OCR was unusable.
  macOS now uses the login Keychain (security CLI), Linux/other use a 0600 file
  under secrets/, Windows keeps DPAPI; SILICONFLOW_API_KEY still wins everywhere.
  Status reports the backend (source: dpapi/keychain/file/env).
- **Local OCR is honest on Python 3.13.** When the optional OCR extra is missing
  the settings page says 本地 OCR 未安装, explains it needs Python 3.11/3.12 (no
  rapidocr wheel on 3.13) or cloud OCR, and disables the dead 内置 model dropdown
  instead of showing a built-in model that cannot run.
- **Bilibili QR image failures are visible.** A QR data URL that fails to decode
  now shows a retry hint instead of a blank white box.
- README: per-platform key storage documented.

## 0.1.8 (2026-11-17)

- **A marketplace install on a fresh Python 3.13 machine now works.** Root cause
  of "一键安装 CLI 失败 / 之后几乎每个设置都读取失败": rapidocr-onnxruntime was a
  required dependency and has no Python 3.13 wheel, so pip install video2agent
  failed with No matching distribution found on 3.13. Local OCR is now an
  optional extra (pip install "video2agent[ocr]", Python 3.11/3.12); the core
  install works on Python 3.11-3.13 (faster-whisper/ctranslate2, opencv, numpy
  and pillow all ship 3.13 wheels). The environment card shows an optional OCR
  row with its own install button and skips it on 3.13.
- **One-click install is resilient.** The CLI install is core-only (the slow OCR
  resolver no longer makes the button look stuck), retries once through the
  Tsinghua PyPI mirror when the default source fails, shows "正在安装…" while it
  runs, and pip-failure remedies mention mirrors and the Python version. Verified
  on a fresh CLI-free venv: install -> CLI usable -> Bilibili QR renders.
- Doctor/OCR error remedies point at the optional extra now.

## 0.1.7 (2026-11-17)

- **Every plugin HTTP route now goes through DSH's Connection admission.** Routes
  registered with webServer.register first call
  ctx.connection.requestRejection(req) (the service is optional; the plugin's own
  Host/Origin guards stay). A page in the user's browser can no longer reach them
  even when it finds the loopback port. The one cross-site read kept is the
  evidence-image GET (opaque id + image destination) that the desktop shell needs.
  Verified in a real DSH instance: an unauthenticated request now gets 401 while
  the settings page keeps working.
- The marketplace entry drops the "HTTP routes have no DSH access check" caveat the
  maintainer added when merging the listing (entry-update PR).

## 0.1.6 (2026-11-16)

- **New storefront.** The marketplace/social card now uses the hero art and the
  "你的 Agent 浏览了无数网页 —— 现在该让它看视频了" copy; the README screenshots were
  re-captured on the current build (composer preview, batch table, and the settings
  page with the 环境检查 card). README images now use absolute raw URLs so the
  marketplace detail page can render them.
- **Marketplace entry copy** is the same hook plus what the plugin actually does:
  cross-video search with video + timecode, exact-frame evidence, 1–10 video batch
  analysis, local-first with optional cloud ASR/OCR and Bilibili login, and the
  Python 3.11+/FFmpeg prereqs the settings page can install.
- Package README restructured: what you can ask, install (PyPI + npm), screenshots,
  manifest.

## 0.1.5 (2026-11-16)

- **An explicit `VIDEO2AGENT_PYTHON` is now a pin.** When set, the setup card uses
  exactly that interpreter instead of falling through to another `py`/`python` on
  PATH, so "which interpreter will it use" is deterministic (and the Linux CI's
  missing-CLI test is stable again; it was the red job on the 0.1.3/0.1.4 tags).
- No user-visible behaviour change when the variable is unset (the normal case);
  CI is green again on the tag.

## 0.1.4 (2026-11-16)

- **Cross-platform error mapping fix.** A missing `ffmpeg.exe` given as a Windows
  path is now classified as `E_FFMPEG` with the install command on every platform.
  `Path(...).stem` keeps the backslashes on POSIX, so the previous code fell back to
  a generic "missing command" and failed the new tests on the Linux CI runners. The
  Windows runtime behaviour is unchanged; this release exists to make the Linux CI
  job (and the 0.1.3 tag) green.
- Regression coverage: the dependency tests run on Windows, Linux and macOS in CI.

## 0.1.3 (2026-11-16)

- **The environment check is one compact line.** Python, the `video2agent` CLI and
  FFmpeg are three status chips on one row (full version/path on hover); install
  buttons appear only for what is missing, and the card reuses the blue
  settings-card shell instead of a bare section.
- **The dependency overrides now reach every tool call.** `perceive` and
  `video2agent doctor` honour `FFMPEG_BIN` / `FFPROBE_BIN` like the media paths, so
  "install FFmpeg with one click" leaves the whole plugin working even when FFmpeg
  is not on the app's PATH (before: `perceive` failed and `doctor` reported FFmpeg
  missing). A `FFMPEG_BIN` pointing at a missing file is named in the error, a
  missing Windows `.exe` is classified as `E_FFMPEG` instead of a generic missing
  command, and the cloud-ASR chunker uses the same mapping.
- **A pip install the app cannot see still works.** If the console script lands in a
  Scripts directory missing from DSH's PATH, the setup card now falls back to
  `python -m video2agent`, records that interpreter, and every tool/worker spawn uses
  it — before, "一键安装 CLI" succeeded but the card kept saying the CLI was missing.
- **Installs tell the truth and cannot race.** `install-cli` now returns `ok:false`
  (`E_CLI_NOT_ON_PATH`) when pip succeeds but the CLI still cannot start; a second
  click while an install runs gets `E_BUSY` instead of a parallel pip/winget;
  adopting an existing winget FFmpeg prefers `Gyan.FFmpeg`, requires `ffprobe`,
  validates `ffmpeg -version` first, and every successful install restarts the warm
  worker so new tool calls see the new environment; a missing `brew` and PEP 668
  externally-managed Pythons get their own remedies; Linux no longer shows an
  FFmpeg install button that would always fail.
- **The settings card shows route failures.** A 403/413/500 from `/setup`
  (instead of a JSON `{ok:false}`) is now visible in the card log, the refresh no
  longer fires a second probe while one is running, and a successful refresh clears
  the stale error log. `POST /setup` is in the same cross-site guard allowlist as
  `/settings`, so a desktop write cannot be refused as a cross-site read.
- **The plugin page ships the real install steps.** 0.1.2's bundled README still
  said "not published yet" and showed the pre-release git instructions; it is now
  `pip install video2agent` + `dsh plugin add dsh-video2agent`, with PyPI/npm links.
- **Regression tests** for `doctor`, `perception`, `.exe` paths and the cloud
  duration probe with `FFMPEG_BIN`/`FFPROBE_BIN` set and no FFmpeg on PATH
  (512 Python tests now).

## 0.1.2 (2026-11-16)

- **Environment check with one-click installs.** The plugin settings page now
  shows Python 3.11+, the `video2agent` CLI and FFmpeg/ffprobe with their real
  versions; missing pieces can be installed from the page (CLI via
  `pip install video2agent`, FFmpeg via `winget`/`brew`). An FFmpeg that is
  installed but missing from the app's PATH is adopted instead of installed again,
  and every CLI spawn gets `FFMPEG_BIN`/`FFPROBE_BIN`, so it works without an app
  restart. Installs are triggered only by the page (loopback JSON POST).
- **Errors name the real install command.** A missing FFmpeg is now `E_FFMPEG`
  with `winget install Gyan.FFmpeg` / `brew install ffmpeg` /
  `sudo apt install ffmpeg` and the `FFMPEG_BIN` hint; the missing-CLI remedy is
  the PyPI `pip install video2agent`. README and the marketplace entry state the
  prerequisites.

## 0.1.1 (2026-11-15)

- **Reading to the end works.** A `read`/`evidence` end time within 2% (or 2s) of
  the media end is now clamped to the last moment with a `RANGE_CLAMPED` note
  instead of `E_OUT_OF_RANGE`; a bare number whose second reading is absurd but
  whose millisecond reading fits is read as milliseconds (`TIME_UNIT_FIXED`).
  Genuinely out-of-range requests still fail.
- **Chinese audio stays Chinese.** Local ASR passes `zh` for a Bilibili video with
  a Chinese title (titles with kana keep auto-detection); `ingest` accepts an
  explicit `language`, and `overview` records the language that was used.
- **The batch progress ring follows the running row.** It used to sit on the first
  queued row while another row said 正在处理.
- **A single wait can no longer kill the call.** One `wait_ms` is clamped to 90s
  (a `run_code` program dies near 120s), and a timed-out wait reports the worker's
  real `state`/`stage`: a queued job says 排队中 instead of looking like it is
  running. The Skill tells the model to wait once, for one job.

## 0.1.0 (2026-11-15)

The first public release is built from this state; nothing is published yet.

- **Release-hardening fixes.** Bilibili short links are limited to real `b23.tv`
  hosts and every redirect is checked with the public-URL guard, so a URL such as
  `http://127.0.0.1:9/?b23.tv` no longer reaches `requests.get`. Tool text now
  redacts absolute paths embedded mid-sentence (e.g. a `doctor` detail), not only
  values that start with a path. Install docs now include `video2agent setup`;
  local-first wording says evidence frames/text go to the host model.
- **Account writes are CLI-only.** The DSH `account` tool is read-only
  (`status`/`folders`/`favorites`/`history`/`analyze`/`classify-plan`); a model
  `confirm: true` is ignored. `create-folder`, `rename-folder`, `add`,
  `classify-apply`, `delete-folder` and `remove` require the user to run the CLI
  with `--confirm`.
- **Batch evidence + clearer dense windows.** `evidence --at` accepts a comma/JSON
  list and `--max-images`, returning all moments in one call. Dense `frames`
  treats `--count >1` as the frame cap, reports `window.truncated` /
  `covered_end_ms`, and keeps the 5s cap explicit. The Skill now says to read
  on-screen text with `evidence --images 0` before pulling pixels, and to use
  `wait_ms`/`--wait-timeout` for a real blocking wait.
- **Perception fixes from a real recording.** A real Chrome recording (button colour at 1.52 s, toast, card slide, 1 s loader loop, 24 px dot) exposed three gaps: a shot-wide baseline hid a small colour change (now a ±1 s local baseline), a burst reported only its peak (now `onset_ms`), and a missing loop was reported as `null`, which a blind analyst read as "no loop" (now `found:false, reason:"not_detected"`). Blind A/B on that clip: digest's contact sheet answered 2/6 questions, nine uniform frames 3/6, the map 4/6 (5/6 after the onset fix) with 3 images instead of 9. The loop detector still misses loops that start mid-shot; the map now says so instead of inventing a period.
- **Eight tool verbs instead of 22.** The model now picks from `find` / `ingest` / `outline` / `read` / `evidence` / `frames` / `perceive` / `admin`; the CLI keeps its full names and every verb maps to byte-identical argv (asserted with `deepEqual` in the harness, so behaviour is the same command). The tool description dropped from 3.5k to 1.2k characters and `SKILL.md` from 36k to 6.8k: fixed cost ~11.8k → ~3.7k tokens (schema ~2.0k + skill ~1.7k). Measured task cost on a 161 s clip: `outline` 942, `read` (30 s) 163, `evidence` (1 image) 1,017 text, `perceive --brief` 292. Nothing was removed: evidence, perceive, long-video windows and the brief survey behave as before.
- **Fast-cut videos keep the cuts the map can show.** The shot rows cap at 20, so a 180-cut anime montage reported 12 boundaries and a model asking "where are the cuts" got a fraction. When rows merge, the map now also carries `cuts_ms` (≤40, `cuts_truncated`); the 88-cut game clip returns 40 cuts in a 2.3 KB map. Validated on five real Bilibili clips against ffmpeg scene (precision 0.52–0.95, recall 0.45–0.96); the threshold sweep kept 0.35/0.5/0.25.
- **OCR prefilter threshold was wrong.** Measured on text vs blank frames: a text slide scores 0.017–0.018, a blank one 0.000, but `select_ocr_frames` required 0.04 — every text frame failed and the fallback selected by position, so a blank-first deck read only blanks. The cut is now 0.004 (between the measured populations) and a blank-first regression test locks it. The thresholds that were swept and left alone (cuts, moments, digest budget, 750 ms sampling) are recorded with their numbers in the changelog entry above.
- **Digest says it is a sample.** A truncated transcript now carries `DIGEST_SAMPLED` (it names the cutoff and `next_start_ms`), and `ocr_total` uses the stored row count instead of the 1,500-row fetch cap, so a long video no longer reports a fake total. The Skill also routes short content questions straight to `read` instead of `outline`.
- **Evidence text is capped.** A misread overlay can emit hundreds of repeated glyphs; one real frame returned a 3.8k-character receipt (~950 tokens) for a single OCR track. Each returned OCR track is now collapsed and capped at 400 characters with `text_truncated: true` (the stored track keeps its full text for search). That frame's receipt dropped to 2.3k characters, and the `OCR_LOW_CONFIDENCE` warning is unchanged.
- **Perception budget.** The map is bounded regardless of duration: shots cap at 20 (adjacent merge, timeline coverage kept), moments at 12, and `--brief` returns a ~340-token survey (cuts + 4 moments, no shot rows). Videos over 10 minutes require a window (`E_WINDOW_REQUIRED`) because a full decode is slow and 4 fps is coarse; pass `--start 0 --end <duration>` to ask for the whole scan explicitly. Measured: 8 s → 343 tokens, 161 s → 855 full / 339 brief.
- **Perception layer (`perceive`).** A number-only map for motion and UI work: hard cuts (structure **and** colour, so a cut between two flat scenes is visible), per-cell motion/colour change on an 8×5 grid, ranked moments with a cell and a "settles" flag, loop period, and capture quality (PTS gaps, duplicate/frozen frames, brightness flicker). Every reply states its coverage: decode fps (Nyquist for flicker), minimum change in source pixels, hard cuts only. Measured: 7.0 s decode + 0.26 s metrics for a 161 s 1080p clip; the map is ~290 tokens for 6 s and ~830 for 161 s. No images and no model download.
- **Clearing a finished batch stays cleared.** 清除 used to remove the table and let the single-job card for the same completion take its place until that card's own 8s hold ended. Clearing now retires the batch's live entry in the same step; the 8s auto-clear uses the same path. A canceled batch is labelled 已取消 instead of 已完成 in the table header and the collapsed pill. Settings autosave now posts every pending change (two controls moved inside the same 300ms window used to save only the last one), and the cloud capsule is disabled until an API key is saved.
- **Batch receipt fixes.** A cleared or auto-faded batch is latched so a historical ingest/shortlist card cannot recreate it on conversation switch. Cover backfill now resolves Bilibili `source` URLs even when the row uses a `vid_...` id, so completed rows do not lose their cover. Only one batch surface renders.
- **Plugin control-loop fixes.** The batch table now renders a real stop button
  wired to `cancel()`; `/campaign` GET is read-only and POST advances a wave; the
  settings client posts only changed keys so Config no longer freezes; a running
  batch stays visible after the turn ends; canceled jobs no longer look running;
  a historical result can no longer rewrite a completed live card. The single
  LiveStrip is suppressed whenever a batch row exists, so cancel/finish cannot
  alternate between two surfaces. Discovery/activity records now carry
  `exec.agent.session.id` when the Host supplies it, instead of relying only on
  the first poller's claim. The Skill forbids re-ingesting after a user cancel.
  The worker resets on a closed stdin, `guardRead` covers every method, aborted
  bodies and oversized covers settle, the watchdog sends `overview=0` and checks
  cards in parallel, cache cleanup repeats, idle polling is gated, and
  SHORTLIST_STARTS is pruned. Account write-only schema parameters were removed.
- **Cloud OCR can now use grounding-guided crops.** With cloud OCR enabled,
  `evidence --ocr-tiles` asks DeepSeek-OCR for text plus boxes, crops/upscales
  each located line and re-reads it with cloud OCR; blind tiles are gone. A crop
  is accepted only when it agrees with the located line or is numeric, so a green
  wall cannot become a "paper screenshot". This is pure cloud (no local OCR).
  Measured on the 90-question subset: **76/90 = 84.4%** (550 calls, 276 images),
  versus 74/90 = 82.2% without guided OCR; local captions + local OCR remains
  the best at 79/90 = 87.8%.
- **`search --compact` is opt-in, not the plugin default.** It trims repeated hit
  fields (keeps `evidence_id`/`timecode`/`snippet`/`modalities`/`score`; measured
  -46% characters), but a same-question A/B (604/314/445) matched on only one of
  three questions (314 C vs A, 445 B vs C). Those two are ambiguous questions and
  the difference may be frame-sampling variance rather than the dropped fields,
  but the evidence is not clean enough to make it the default. The plugin keeps
  the full hit fields; `--compact` remains available for callers that want it.
- **`transcript --json` is compact by default.** One `"HH:MM:SS text"` line per
  segment instead of per-segment objects: 88.7k → 14.0k characters on a
  30-minute talk (-84%); `--full` restores the objects. The DSH plugin already
  requested compact output, so plugin behaviour is unchanged.
- **`digest` costs ~60–70% fewer characters by default.** Transcript and OCR
  rows are now one `"HH:MM:SS text"` line each instead of five-key objects; the
  content and timecodes are unchanged. Measured: 44.8k → 12.6k characters on a
  42-minute video, 31.8k → 13.1k on a 30-minute one (plugin budget 2000 chars:
  19.0k → 5.7k). `--full` restores the old objects. A same-question A/B (007-3,
  884-2, 604-2) kept every answer unchanged. An opt-in `token-log.on` flag in the
  video home now records per-call text chars / images / estimated tokens.
- **Read-path speedups for `ocr-window` and `frames`.** `ocr-window` results are
  cached per source/config (repeat calls 38.6 s → 0.17 s) and the command runs in
  the warm worker; window OCR uses two workers (38.2 s → 17.0 s for 15 frames;
  four workers were slower). A partial read is never cached. `frames` now extracts
  a run of frames in one ffmpeg process (one exact seek per frame; 9-frame sheet
  1.5 s → 0.84 s, pixel diff 0.0 against the per-frame path). A `select`-based
  pass was rejected: at 30 fps a 40 ms window catches two frames and shifts every
  later output.
- **`ocr-window` tells the truth about coverage and cleans up.** A window longer
  than the frame cap is now flagged (`OCR_WINDOW_SAMPLED`, with planned vs read
  frames) instead of looking complete; missing frames add `OCR_WINDOW_GAPS`; the
  unchanged-frame skip only fires when the picture is effectively identical
  (difference <=2, not <=8), so a small text change on a static screen is not
  missed; the temporary `ocrwin_*.jpg` frames are deleted after the call (and
  stale ones older than an hour are swept).
- **`ocr-window` reads text that changes inside a short window.** A phone banner
  showed "Dude! You gotta come to BigStuf Camps!" at 0:59 and switched to
  "BTW...you got something in your teeth!" at 1:02; a single `evidence --at`
  returned only the first line, and the OCR question was answered wrong.
  `ocr-window --start --end --fps 2` reads every frame of the window and
  returns each distinct line with its timecode; one agent then answered the
  question correctly with one call and no images. `evidence --ocr-tiles` reads a
  single frame as 3×3 overlapping tiles, which measurably raised text recall on
  phone and slide frames. A 7-second tiled window first cost 69 s; the default
  full-frame pass costs 15.5 s, and unchanged frames are skipped by a 32×32
  pixel check.

- **A Video-MME measurement now lives in the repo.** `docs/BENCH-VIDEOMME.md`
  records 90 real-tool questions in three effort protocols: 81.1% before the five
  upgrades, 82.2% when the agent was held to 12 calls/25 images, 86.7% with no
  budget (2.1× the calls). It also documents the 7-question counting subtest
  (6/7 and 4/7, not a proven gain) and three dataset quirks (`445-3`, `314-1`,
  `884-1`) so the number is not read as a leaderboard claim.

- **Cloud ASR supports Qwen3-ASR.** It rejects `verbose_json`, so Qwen models are
  requested with `json` and 120-second chunks (long enough to keep a citation
  inside two minutes, short enough not to lose timing); other models keep
  `verbose_json` and 30-minute chunks. Measured: 60 s of Russian came back
  correct and punctuated, including "скидка 70%" and "4950 рублей", where
  XingChenASR had returned Chinese filler. A provider that returns no text at all
  is treated as no speech (music/ambience): the run warns `CLOUD_ASR_EMPTY` +
  `NO_SPEECH` and does not spend a local ASR pass.
- **Cloud OCR no longer stores a picture description as on-screen text.**
  Measured 2026-11-07: on a textless interview frame the configured cloud OCR
  answered "In the image, there is a man …". That description raises
  `E_CLOUD_OCR_DESCRIPTION` and the evidence path falls back to local OCR with
  an info warning. On a dense page cloud OCR still wins (structured Markdown vs
  a word jumble), so it stays available for frames known to contain text.
  Cloud ASR language coverage depends on the chosen model (XingChenASR returned
  Chinese filler for Russian); the plugin does not guess the language or switch
  models automatically, because a music-only video has no speech either.
- **One image for a window: `frames --sheet`, and `--windows N` for a named
  range.** `--sheet` tiles the frames a dense window already extracted into one
  labelled image (max 9, adaptive grid: 4 → 2×2, 5–6 → 3×2, 9 → 3×3), so a
  counting question costs one image instead of nine. `--windows N` samples one
  frame per window across an explicit `--start/--end`, returns one coverage
  image plus `covered_ms`/`missing_ms`, and never scans the whole video by
  itself. Tiles stay 320×180; small text still goes through `--crop --scale`.
- **`digest` carries score-like OCR lines.** When the OCR actually read
  something like `9-7` or `2:1`, digest lists up to eight timestamped lines;
  dates (`2024-01-01`), chains (`1-9-7`) and label prefixes (`Q1: 9-7`) are
  filtered out, and the field is absent when nothing matched.
- **Search reads non-Latin scripts.** Cyrillic, Greek, Arabic, kana and Hangul
  tokenise as whole words now, and their FTS queries are prefix queries so
  inflections match (`промокод` finds «промокоду»). A Russian video whose
  transcript carried 4,751 Cyrillic characters used to index zero tokens and
  answered its own queries with `EMPTY_QUERY`; it is searchable and cites the
  line at 00:08:38.520. Latin and CJK tokens are byte-identical to before.
- **`candidates`: candidate shots for visual questions.** New command and tool
  action. It lists shots from the stored scene cuts (or 15s windows when a
  record has none) with start/end, timecode, keyframe and the overlapping
  transcript/OCR text; with `query` it ranks by lexical overlap, and when no
  shot matches it returns `NO_TEXT_MATCH` and spreads candidates in time instead
  of pretending the video has nothing. For a 9-minute, 64-shot compilation this
  replaces scanning with frames: eight timecodes in one call.
- **OCR index budget 60 → 120.** One `ocr-index` call can now cover a 120-frame
  record (cap stays 240), which is what text-heavy videos need; `--ocr-budget`
  on the `deep` profile follows the same default.
- **A music-only video no longer tells you to install ASR.** Ingest records
  `metrics.asr` (`ran`, `model`, `seconds`, `segments`, `no_speech`) and warns
  `NO_SPEECH` ("ASR ran, no voice detected; rely on frames/OCR") instead of
  `NO_TRANSCRIPT` with a remedy that points at an already-installed model.
- **Smaller DX fixes.** `digest --count` is accepted as the tool-level name,
  the 5s dense-window cap is in `frames --help`, and an out-of-range error now
  names the last usable timecode and `media_end_ms` so a rounded duration can be
  fixed without another probe.
- **Skill hard rules.** The skill now says: variants first for vocabulary
  mismatches; counting/action/spatial questions need frames, not text;
  compilations go through `candidates`; a zero-hit search is not proof.

- **`digest` now carries scene cuts and audio hints, without new images.** Every
  digest adds `scene_cuts.cuts_ms` (up to 16 stored scene boundaries, in
  milliseconds) and an `audio` block: mean/max dBFS, volume-based
  `silence_ratio`, and — when faster-whisper is installed — `speech_ratio`,
  `first_speech_ms` and up to 4 `no_speech_ms` gaps from the Silero VAD model
  that faster-whisper already ships (`source: "silero"`; otherwise the
  volume-based silence is reported with `source: "silence"`). Both hints are
  digits-only and cost roughly 100–130 tokens together; `audio: null` means the
  media file is missing (unmeasured, not silent). Measured on three videos,
  cut-adjacent frames differ 2–5× more than random frame pairs, and a music
  track reports `speech_ratio 0.03` against `0.89` for an interview. The skill
  now tells the agent to look at a cut or right after a long no-speech gap
  before scanning a long video. Cost: digest gains about 1–5 s per call for the
  VAD pass; no new dependency or image.

- **Bounded read worker.** A single JSON-lines Python worker is started on
  demand for read commands and stopped after 10 idle minutes. It holds only the
  interpreter/read path; ASR is never preloaded and OCR loads on demand. First
  search 158 ms, warm search 16 ms, warm transcript 6 ms, compare 3 186 ms,
  compare 10×5 521 ms, digest 186 ms. Worker failure falls back to the CLI.

- **Read commands no longer pay for the media/OCR stack at startup.** Search,
  overview, transcript, map and compare used to import numpy, Pillow, requests,
  opencv and the OCR modules on every CLI process. Those imports are now lazy;
  media/ASR/OCR/resolve load only when their command needs them. Measured on the
  live 14-video library: CLI `--version` 478 → 130 ms, search 503 → 166 ms,
  overview 522 → 282 ms, transcript 503 → 142 ms, map 493 → 139 ms, digest
  573 → 324 ms, warm evidence 487 → 147 ms. Compare now emits compact JSON with
  only the aspect-hit evidence fields, and the Host rejects a >60k payload with
  `E_OUTPUT_TRUNCATED` instead of returning invalid JSON. 345 tests.

- **A synonym query no longer comes back empty, and an alias hit no longer claims
  the typed word.** `计费` returned 0 results on a real library whose lines say
  价格/成本/账单, even though the FTS matcher returned 17 of them: the coverage
  guard tokenised the expanded query (`计费 价格 成本`) as one CJK run, so it
  looked for cross-word trigrams (`计费价`, `费价格`) that occur nowhere and
  deleted every hit. Coverage units are now built per term (the query plus each
  alias), so `计费` returns 5 hits at `--limit 5`; 收费/定价/账单/付费 were added
  to the same table. A transcript or OCR hit that matched an alias now carries
  `matched_terms` and says `同义词「价格」` instead of claiming `关键词「计费」` —
  `价格` hits on "一共花了多少钱" used to say the keyword matched. The snippet is
  centred on the term that really matched. A query whose units appear nowhere is
  still an explicit miss (`量子纠缠` vs 量子力学 stays 0), and a zero-hit query
  keeps `NO_MATCH`. Old records without a stored index count now report
  `remaining_frames` from their frame statuses instead of `null`. A whole-video
  row now names the term it matched (`标题/简介匹配…；同义词「价格」`), and a row
  that does not contain the typed query ranks below every real moment instead of
  leading the list. A hit that survived only on a curated synonym reports a
  floor score of 0.05 instead of 0.0 — in a one- or two-video library FTS5 IDF is
  0, so BM25 was ~0 and the row read as "no match" while still being returned.
- **One activity card for OCR, export and account writes.** These actions
  publish a start/finish status (no counts, stages, error reasons or 30s error
  dwell), polled every 2.5s; discover/evidence/frames keep their existing
  surfaces. Processing cards now show only 正在处理 / 已完成 / 未完成.
- **Renamed to DSH-Video2Agent before launch.** Product `DSH-Video2Agent`, plugin
  `dsh-video2agent`, CLI `video2agent` / `v2a`, environment `VIDEO2AGENT_HOME`,
  routes `/api/video2agent/*`, repo `Harm0ny-AI/DSH-Video2Agent`. The old
  `VidProof` / `vidproof` / `v2k` names are gone; nothing was published under
  them, so there is no compatibility alias. Copy now leads with video search and
  understanding; evidence is the verification step, not the headline.
- **Public copy and install paths are ready.** The package metadata, release
  notes, screenshots and install commands are prepared. The install docs say the
  true route (repository or Release wheel, then the plugin tarball); PyPI/npm are
  still pending. Personal paths were removed from the tracked tree before going
  public.
- **A partial index no longer calls itself complete.** `visual_index` gained
  `remaining_frames`, and `complete` now requires every candidate frame to be read
  with no failures. A capped `ocr-index` run reports `partial` with the frames still
  to read, and a zero-hit search on that state adds `OCR_INDEX_PARTIAL` ("0 条不代表
  视频里没有这些字"). Library-wide search derives each video's state from its own
  metrics, so it cannot disagree with that video's overview. Both zero-hit
  explanations now point at `video2agent ocr-index` instead of suggesting a re-ingest.
  The Windows live-home guard exits cleanly on a runner with no live home, and the
  README no longer tells anyone to clone a repository that is not public.
- **Public copy now leads with real requests.** The listing opens with
  cross-library search (e.g. Tencent PM interview notes) and batch analysis of
  3–10 exam-prep videos, with the Bilibili account as an optional third module.
  The 200-video search target limit is stated in the card and limitations.

- **Batch rows have a fixed cover and no oversized ring.** Every row uses the same
  72×40 cover; a failed cover gets an inline placeholder instead of a blank box;
  a terminal queue restored from storage renders nothing. This removes the cover
  jump, the blank cover and the historical completion replay.

- **A stored queue is not painted until the first poll proves a job is running.**
  Switching back to an old conversation no longer flashes a processing card; a
  terminal queue is cleared without rendering. Every stored queue now waits for
  the first poll, including one created seconds ago; a fresh batch appears after
  the immediate poll. The same guard covers a session change, where the component
  used to render once with the previous session's hydrated state.

- **Historical tool cards no longer recreate a batch.** Opening an old
  conversation that contains a shortlist or direct-ingest result now ignores it
  when no live queue exists and its timestamp is older than five minutes. This
  was the remaining source of the card replay on old conversations.

- **Batch card layout:** no stop button, no top-level “正在处理” header while
  running, status stays on each row; the cover is 96×54 inside a 104px progress
  ring; a failed cover request uses a 96×54 placeholder. Verified: header text
  is only 收起, row says 正在处理, cover 96×54, ring 104, stop button absent.

- **Search card shows candidates, not IDs.** While searching/screening it lists
  up to four covers + titles (no BV numbers), keeps the dots animation, holds
  through a shortlist status clear instead of blinking out, and suppresses the
  old start/selection failure cards. A batch table takes over once jobs exist.

- **BV-only batch rows resolve their title and cover.** A queued row that only
  has a BVID asks `/api/video2agent/resolve` for the title/cover/uploader and
  updates in place; if the lookup fails it shows `视频`, never a raw BV id. The
  shortlist-start failure card (`视频没有开始`) is suppressed; the answer reports it.

- **A new batch is a clean table.** Shortlist and direct ingest no longer carry
  still-running rows from an older turn; switching to an idle conversation hides
  the table entirely, a new turn clears an old queue, and the row list no longer
  scrolls/clips. This removes the stale videos and broken layout after a switch.

- **The batch progress ring now wraps the cover as a rounded rectangle.** It no
  longer uses a circle that gets hidden behind a 96×54 cover or inherits the old
  client's 90° rotation. A clean single-plugin profile (old `dsh-vidproof`
  removed) was used for the recorded full-flow browser test.

- **Settings writes accept a loopback hostname mismatch.** DSH desktop can load
  the page from `localhost` while the request Host is `127.0.0.1`; the old exact
  match returned 403 for every save (API key, theme, Bilibili QR). Both sides now
  only have to be loopback. The compatibility host also pins the renamed CLI to
  `.vidproof`, so the existing key and Bilibili login are visible again.

- **The cloud/local source toggle is clickable without a saved key.** The old
  disabled condition made the ASR/OCR 云端 button inert until the page saw a key.
  Isolated old-host verification: 云端 ASR switches to 云端, 扫码登录 renders a QR
  (`data-vp-bili-qr` = 1), and settings/QR POSTs from a localhost Origin to a
  127.0.0.1 Host return 200 after the loopback guard fix.

- **The single-video card ring is visible.** A 72px cover inside an 84px ring
  left only 2px of track, which looked like no progress ring. The cover is now
  64px, leaving a readable ring. Real 8s local-video job recorded: title `cloud8`,
  status `正在处理`, ring visible; the job itself completed in the same backend.

- **Cards now carry the video's identity, not just its title.** Shortlist rows
  pass `uploader` and `stats.play` into the queue and live card; the card shows
  `UP 主 · 3.1万播放` on a second line. Direct ingests show the uploader when the
  resolve/overview has it; no fabricated view count when the platform did not
  provide one.

- **The Skill and tool description now push video-first use.** They explicitly
  cover screen-recorded frontend/UI QA (record, ingest, inspect frames at state
  changes) and tutorials/how-to/work/study/life experience where video is richer
  than text, with discover → shortlist → transcript/search/evidence.

- **Play counts follow Bilibili formatting.** Under 10,000 shows the full number
  (`9,999` without a thousands separator in the card); 10,000 and above keeps one
  decimal + 万 (`1.0万`, `3.1万`); 100,000,000 and above keeps one decimal + 亿
  (`1.0亿`).

- **Shortlist guidance no longer says 1–3.** The 10-video limit is a per-wave
  concurrency/start limit, not a product limit; Skill and tool description now
  tell the model to use as many as the task needs up to the per-wave limit and
  to split dozens into waves.

- **Campaign queue for more than one wave.** `shortlist` accepts `campaign:true`
  with up to 100 ids. The Host starts `processLimit` at a time, starts the next
  wave when the previous one has no running job, keeps a failed row from
  blocking the rest, and exposes `command:"campaign"` plus
  `/api/video2agent/campaign?id=...` for the aggregate state. The client polls
  that route and shows queued rows as `排队中` instead of pretending they are
  running. Verified with 25 mock videos (3 waves, max 10) and a failed-row
  case (11 ready + 1 failed; wave 2 still ran).

- **Low-confidence OCR is no longer presented as usable text.** OCR search and
  evidence rows carry `ocr_reliable` (false below 0.5, null when the engine
  provides no score); a low-confidence frame adds `OCR_LOW_CONFIDENCE` and the
  Skill says to treat it as a search lead, not a quote.

- **Evidence ranges are spread across the range.** `evidence --start/--end`
  without `--at` now samples evenly instead of clustering at the range start;
  `range_requested`/`requested_ms` make the semantics explicit. Verified on a
  generated 6s video: requested 0–5s, images at 25ms and 4525ms.

- **Discover can return up to 50 candidates per query.** The host clamp and the
  Bilibili search now fetch pages of 20 instead of truncating at one page; 50
  remains a per-query cap, not a library limit.

- **Campaign review fixes.** `command:"campaign"` now exists (the previous
  schema/next_step pointed at a missing function), terminal job sidecars stay
  readable after 15s so later waves can advance, a fully failed first wave is
  `E_START` instead of `ok:true`, 11–100 ids without `campaign:true` are
  rejected rather than silently dropping the tail, and CI now runs the campaign
  test and asserts `campaign.js` in the tarball.

- **Campaign review residuals.** The per-wave error now shows the configured
  `processLimit` instead of a hardcoded 10, and an `E_START` campaign is marked
  `failed` instead of being left running with no id returned.

- **Digest is a one-call index, not a generated summary.** `video2agent digest`
  returns timestamped transcript and OCR rows, keyframes and a 3×2 contact sheet;
  the Host attaches the sheet and strips its path. The sheet is navigation only, so
  a detail can be requested with `frames --at ... --crop x,y,w,h --scale 2`.
  Verified on a 6s video (6 tiles at two rows) and a real crop (0,0,0.5,0.5 →
  320×240 at scale 2).

- **Digest review fixes.** `digest` image_urls are no longer redacted into a
  broken relative URL; `--frames`/tool `count` actually controls the sheet size;
  corrupt or missing frames return no sheet plus `FRAMES_UNREADABLE`/
  `CONTACT_SHEET_PARTIAL` instead of a blank JPEG; crop decodes at source width
  (1920×1080 test: half-frame crop = 960×540, scale 2 = 1920×1080); OCR
  truncation is declared with `ocr_total`/`ocr_truncated`.

- **Contact sheet compacts corrupt tiles.** A corrupt frame no longer leaves an
  unlabeled blank slot; the canvas is sized from usable tiles, and keyframe index
  matches tile position.

- **Bounded dense/change extraction.** `frames --start/--end` samples a query
  window (≤5s, 1–8fps, ≤15 frames); `--mode change` keeps endpoints plus the
  strongest frame differences. Default ingest sampling is unchanged. On a 4s
  red→blue fixture, the change window selected the 2.0s boundary with a 47.0
  difference score; the default path remains sparse.

- **Dense windows cover the whole request.** Sampling is redistributed when the
  frame cap would otherwise clip the tail, always includes the effective end,
  and reports the clamped end in `window.end_ms`. The uniform path is hard-capped
  at 15 frames too, not only `mode=change`.

- **Change mode needs three frames.** `mode=change` with `--max 1/2` now returns
  `E_ARGS` instead of silently dropping the end or the change point; the pipeline
  API also rejects negative dense windows. `--max 0` is included in that guard;
  `--max 3` and up retain endpoints.

- **Guidance now targets coding and frontend work, not just video questions.**
  The tool opens as video perception/retrieval and the Skill says to record →
  ingest → digest before building UI from a visual reference, to use one
  discover for a how-to before guessing, and to stop searching instead of
  looping. Pure API/algorithm questions stay text-first.

- **Final audit fixes.** Dense window attachments now use the `--max` budget
  (12 frames reached the model, not 1); discovery keeps up to 100 candidates
  so a 50-candidate discover can be shortlisted; filtered discovery scans all
  5 pages before declaring FILTER_EMPTY; CLI help is video-first again; stale
  reference docs and a tracked absolute path were removed.

- **Filtered discover scans past a full first page.** The raw candidate count
  no longer stops pagination before uploader/date filters run, so a match on
  page 2 is found at the default limit=8.

- **Settings no longer flashes defaults on every tab switch.** The settings
  section caches the last cloud/model/Bilibili read and shows one `读取配置…`
  placeholder until the first reads finish, instead of painting local ASR,
  `未配置`, and `未登录` first. Tab switches render the cached values instantly.

- **Settings cache survives an app restart.** The cloud/model/Bilibili snapshot
  is persisted in localStorage (no key, no QR), so the first VidProof click after
  launch can render the last configuration instead of a blank loading panel.
  While the first-ever read runs, the blue cards stay in place and their contents
  are hidden, rather than disappearing.

- **No settings loading animation.** The `读取配置…` opening state was removed.
  Cloud/model/Bilibili reads are prefetched when the client loads and persisted
  in localStorage, so the VidProof tab opens with the last configuration; the
  blue card shells stay in place until the first read fills them.

- **OCR evidence no longer repeats one subtitle.** Duplicate detections on the
  same row are dropped, and an engine-repeated line is collapsed before it is
  stored; low-confidence text remains marked unreliable. A real 03:45 frame had
  3,641 repeated characters; the new regression test covers the collapse.

- **Tool errors are JSON and search meta ranks below content.** Invalid/absent
  campaign ids and missing arguments now return a JSON envelope, and a whole-
  video meta row no longer outranks real transcript moments when content hits
  exist.

- **Cost/size search aliases.** A query for 价格/成本/费用/计费 no longer dies
  because only the alias appears in the transcript; alias hits count as
  coverage when the original term is absent. `价格` on the 55-minute sample now
  returns the real cost lines at 16s and 53min.

- **Faster link preview.** Bilibili BV/av links use the public view endpoint for
  title/cover/duration before falling back to yt-dlp; the Host caches resolve
  results for 24h, the client persists its cache across refreshes, aborts stale
  requests and starts after 220ms instead of 450ms. Measured resolve on the Hy4
  sample dropped from 1.93s to 0.59–0.68s before caching.

- **Model-supplied query variants.** `search` accepts 2–8 `queries` (synonyms or
  likely ASR spellings), merges hits, records `matched_queries`, and keeps each
  variant's empty/warnings state. No model is called inside the search process.

- **Multi-video compare.** `video2agent compare` packs one transcript window per
  video (full when it fits, evenly sampled across the timeline when it does not)
  plus per-video aspect hits with explicit `hit`/`no_hit`, so one long video cannot
  fill a global top-k. A total character budget prevents a 10-video comparison
  from blowing the model context.

- **Cache policy in Settings.** Cache keeps the whole entry (media, frames,
  transcript, index). Expiry is on by default at 7 days and deletes the complete
  entry; an optional capacity cap is off by default, max 20 GB, and evicts the
  oldest entries. `video2agent gc --auto` applies the policy and the Host runs it
  after a settings save and every six hours. The expiry and capacity toggles sit
  inline with their value selects.

- **Settings write hardening.** The settings POST no longer schedules cache
  cleanup inline, and the host write falls back to a direct write if an atomic
  replace is rejected; cleanup is one delayed run per host load. The desktop
  shell's custom-scheme Origin is accepted for loopback JSON writes, so settings
  saves no longer fail with 403 in that shell; a non-loopback write still fails
  closed. The client merges each save over the current settings and applies the
  Host response, so changing the 5 GB cap no longer resets the enable checkbox
  to off/20 GB.

- **Release artefacts rebuilt and verified.** Wheel 197,390 B and plugin tarball
  219,974 B; the wheel installs into a clean venv (`--no-deps`, `--version`/
  `--help`) and into a full venv (`doctor` ends with a runnable next step); the
  tarball installs into an isolated DSH profile whose files hash-match the
  checkout. A real ingest → ocr-index → search → evidence run in that isolated
  home returned three hits and a 00:00:01.575 citation whose image loaded in a
  browser through the opaque frame id. Nothing is published; checks that cannot
  run locally are documented in the release notes.
- **A reliability pass after the full review.** A missing/unfinished video now
  returns `E_NOT_FOUND`/`E_NOT_READY` from search, map and transcript instead of
  an empty success; evidence frames and images are the same list; a failed ASR
  mode save no longer flips the capsule or the upload notice; a failed settings
  read blocks auto-save instead of writing four defaults; `保存配置` is disabled
  when the cloud config is unreadable; the collapsed receipt is not auto-deleted;
  local paths never appear as row titles; the completed card says how much
  on-screen text was indexed; GET routes reject a foreign Host; frame paths are
  contained before `realpath` (no UNC probe) and directories cannot be streamed;
  `frames` keeps its timestamps, `jobs` keeps the real failure reason, `doctor`
  returns the failing check instead of a JSON wall, and resolve/shortlist errors
  keep their codes. CI generates its own caption fixture, requires the Config
  peer, and no longer depends on b23.tv.
- **A five-step quick start and a 19-second demo.** The README now goes from
  installing FFmpeg and the package through the 464MB model, the first `ingest`,
  and `video2agent list` for the VIDEO_ID; `docs/demo.mp4` shows a real ingest →
  on-screen index → two timestamped hits → the frame, and
  `scripts/demo.sh` / `scripts/demo.ps1` reproduce it (`scripts/render-demo.py`
  re-renders the video from a fresh run). Stale doc claims were corrected: the
  settings page no longer claims an environment check, Whisper weights are not
  downloaded implicitly, the long-video card has no ETA, MCP is not implemented,
  and `docs/COST.md` reflects the current defaults and test count.
- **CI covers both operating systems.** `.github/workflows/ci.yml` runs ruff,
  the Python suite and the three Node harnesses on ubuntu and windows for Python
  3.11/3.12, runs the two safety guards on Windows, and builds the wheel + plugin
  tarball in a package job that also installs the wheel into a clean venv. DPAPI
  tests skip off Windows with a reason; CI does not download the ASR model and
  does not claim real-ASR coverage. The running job poll moved from 1.2s to 2.5s
  (measured: one poll costs ~0.5s of Python start, so this halves idle CPU).
- **Paths stay on this machine unless you ask for them.** Evidence frame links
  now use an opaque `<video_id>/<file>` id instead of an absolute path, exports
  redact local paths to file names by default (`--include-paths` opts out, and the
  JSON says `paths_redacted`), and `video2agent gc` prunes `logs/job_*.log` older
  than 7 days (`--keep-logs-days`). Write routes now also reject a request with no
  `Origin` header, not just a foreign one.
- **On-screen text can be indexed explicitly, and the result is visible.**
  `overview` and `search` return `visual_indexed` plus `visual_index`
  (`on_demand` / `partial` / `complete` / `failed` / `unavailable` and a
  plain-language reason), so an empty visual-text search says whether the index
  was never built instead of implying the video has no such text. New
  `video2agent ocr-index VIDEO_ID`: `--dry-run` reports the real frame count and a
  per-frame time measured on a probe frame, then the run reads only likely-text
  frames (capped) and makes them searchable. The default `auto` profile stays
  lazy; the settings page says so in one line.
- **A picture and its text now come from the same frame.** `evidence --images 1`
  used to return the requested screenshot together with OCR text read from
  another frame (reproduced: image at 1.5s, text from 2.275s, no warning). The
  bundle now keeps only tracks from the returned frame (`OCR_SAME_FRAME_MS`),
  reads that frame on demand when the window only had another frame's text, and
  never falls back to another frame's text when the read fails. With
  `--images 0` a nearby anchor may still answer, labelled with its own time.
- **OCR runtime fixes.** The engine cache is keyed by the config file's mtime and
  size, so a regenerated YAML or a newly selected local model is picked up
  without restarting; a failed availability check is retried after 30s instead
  of marking OCR broken for the whole process. A failed exact-frame extraction
  is reported as `FRAME_EXTRACT_FAILED` instead of being swallowed.
- **A failed OCR read no longer looks like "this frame has no text".** Frames now
  carry `ocr_status` = read / empty / failed / unread, `text_coverage` stays
  `None` when the read failed, and `overview` reports
  `capabilities.ocr_state` (`indexed` / `partial` / `failed` / `on_demand` /
  `unavailable` / `unmeasured`) instead of only `ocr: false`. A zero-hit search
  now says whether the visual index was never built, whether frames failed to
  read, or whether the text is genuinely absent.
- **An ingest that cannot produce a transcript fails instead of returning
  `ready` with nothing.** A video with speech, no captions and no usable ASR
  model now returns `ok:false` with `E_ASR_NOT_CONFIGURED` and the exact command
  (`video2agent models download --model small`, about 464MB). `doctor` reports an
  uncached model as not-ok and ends with a plain-language next step. Searching
  an empty library returns `E_EMPTY_LIBRARY` instead of an empty success.
- **The settings page cannot pretend a save happened.** A rejected save shows a
  red line that stays until the next successful save; a failed settings read
  says `读取失败` instead of showing defaults as saved; a failed model read says
  `当前：读取失败` instead of `small · 未下载`. The cloud switch explains
  `先粘贴 API Key` when disabled, and switching a section to the cloud shows
  `音频/画面会发送给你配置的服务商`; `SECURITY.md` and the README say the same.
- **Cloud ASR/OCR without downloading the local model.** Settings defaults to
  SiliconFlow but accepts any OpenAI-compatible provider and any ASR/OCR model
  ID. The defaults `XingChenAGI/XingChenASR-V3.2-Ultra` (`verbose_json` segments)
  and `deepseek-ai/DeepSeek-OCR` are pre-filled; a bottom line says the default
  models are free. The top API-key card carries the referral note, key row and
  domestic invitation / international links; the domestic button is filled and
  the international button is neutral so the choice is visually distinct. The
  key is encrypted with Windows DPAPI and never appears in argv, logs,
  `ui-settings.json`, or route responses. Cloud OCR is opt-in and only reads
  frames the model asks for; local OCR stays built in.
- **Local ASR is not a whitelist.** Four hardware tiers with short CPU hints:
  入门→base, 中端→small, 高端→medium, 企业级→large-v3. Any HuggingFace
  faster-whisper model ID / local CTranslate2 directory remains available under
  Advanced. Cached HuggingFace models can be uninstalled (custom paths are never
  deleted); RapidOCR PP-OCRv4 is the built-in local OCR; a HuggingFace ONNX repo (det/rec models, config generated automatically), a local YAML config, or a directory containing config.yaml can be selected as the local OCR model. A missing model now
  returns a setup reminder instead of downloading silently; downloads are
  explicit, the download button is disabled once cached, and “只用本地模型”
  ignores a saved cloud key.
- **Your Bilibili library is now a tool.** `account` reads folders, paginated
  favorites, and recent history; `analyze` and `classify-plan` produce compact
  summaries and a classification draft. The DSH tool can create/rename folders
  and batch add videos after explicit `confirm`; delete/remove are CLI-only.
  New folders are private by default. Cookies stay local and never reach the model.
- **The batch surface now shows only what a user acts on, once.** The glass table
  keeps the cover, title, UP 主/时长, one coarse stage and the stop action; the
  active video's cover carries the progress ring, so there is no second
  cover/title card. The primary chip, selection reason, evidence chip, failure
  reason and retry button are gone; a failed row is a neutral `未完成`. The
  completed table holds ~2.6s then clears, so the answer is the lasting record.
  The ring, cover and ready/check animation are unchanged, and the answer carries
  the screenshot/timestamp.
- **Evidence frames no longer turn into `图片无法预览`.** The Host removes absolute
  `images`/`frames[].path` values before the model sees them and exposes
  `image_urls`/`image_markdown`; the Skill says never to write a local path in the
  answer. A real direct-link turn now delivers the requested screenshot without a
  broken workspace image.
- **A failed stop is no longer silent.** The table shows one short `停止失败`
  line for 2.2s; the normal row stays free of error detail.
- **ASR falls back to a cached model instead of failing offline.** `--profile fast`
  prefers `tiny`; if only `small`/`base` is cached, it uses that and reports
  `ASR_MODEL_FALLBACK` instead of trying a network download. A 4-minute
  no-caption video completed full ASR (49 segments, coverage 0.984, peak
  1,031.8 MB), and a 67-minute local no-caption video completed in 8m52s
  (2,132 segments, coverage 0.981, peak 2,455.9 MB).
- **Caption trust is checked against the actual audio, with a gray zone.** Duration
  and title/metadata checks catch another video's track, but not a same-video track
  whose lines are a joke. For non-AI Bilibili tracks (video ≥60s, Chinese/English,
  with audio), ingest samples up to two 8s windows (60–80s videos get 6–8s; 16s
  max) and transcribes them with a cached light model (configured ASR model when
  present, else tiny/base/small). A
  track is rejected only when **both sampled windows** are <0.18 similar **and**
  share no run longer than two characters; `CAPTION_AUDIO_MISMATCH` is recorded
  and a same-video AI track is preferred, otherwise full ASR re-listens (a full
  ASR pass, expensive on a long video); with neither available the caption is kept
  and marked untrusted. 0.18–0.5, a longer shared run, or only one scorable
  window is a gray zone: keep the caption, record `CAPTION_AUDIO_UNVERIFIED`; ≥0.5
  in every scored window is `verified`. AI tracks
  skip this because they are generated from the audio; local sidecars are user
  input and are not audio-checked. `unknown`/`null` must not be read as a zero
  score. `overview.metrics.caption_check` exposes verdict/score/per-window
  scores/model/seconds; the 16s sample took ~4.1–4.4s with the cached small model. No
  model is downloaded just for this check.
- **Long-video completeness is visible.** `overview.capabilities.transcript_coverage`
  was always 0.0 on stored videos because it read a closed database after the
  connection closed; it now reports real coverage (0.995 / 0.842 on the two 1-hour
  benchmarks) and checks frame files. `map` now returns `returned`, `total`,
  `truncated` and `next_start_ms`, so a 50-row default on a 1-hour video no longer
  looks complete. Chapters use a real 5-minute grid even when scene detection is
  sparse (the 67-minute one had 5 chapters, one 22 minutes long; now 14).
- **The completed table clears by design.** The glass table holds the live batch;
  when every row is terminal it holds ~2.6s and fades, leaving the answer as the
  record. The cover/ring and ready state are unchanged; there is no evidence chip.
- **Old wrong transcripts are repaired, not trusted.** An already-ready video
  used to bypass the new caption content gate; the early URL cache returned its
  overview before the check ran. Both dedupe paths now detect a stored caption
  track that does not match the title and re-analyze that video once. overview
  marks the old transcript unavailable, and transcript/search refuse the bad
  rows with E_CAPTION_CONTENT_MISMATCH and a repair command.
- **Smaller default context.** The agent tool now asks for at most 6,000
  transcript characters by default (the CLI keeps 12,000), and the Skill caps
  discovery at two searches per turn. Both were the largest avoidable context
  costs; continuation still uses next_start_ms.
- **Doctor now checks caption ownership.** `video2agent doctor` is the single
  environment check (Python, FFmpeg, ASR/OCR, disk, login, transcript alignment);
  the settings page no longer duplicates it. Doctor also compares stored caption
  text with the video title, so a silently wrong track is visible before it
  becomes evidence.
- **One search, one shortlist, Host-start.** Raw `discover` results do not render
  in chat (a turn with ten searches used to stack ten eight-item cards). The model
  filters them and calls `shortlist` with 1–10 videos; the Host validates them,
  starts the selected ingests itself, and returns the job rows. There is no
  pending card, confirm route, countdown or auto-pick setting; closing the tab can
  neither block nor duplicate the batch.
- **The composer shows a batch table, not a picker.** One row per selected job:
  cover, title, uploader, duration, plain-language stage and a stop action. When
  every row is terminal the full table holds ~2.6s, then clears; only a manual
  collapse becomes the 44px pill. There is no primary chip, reason, retry,
  evidence chip, checkbox, start button, countdown or confirmation question.
  A direct link uses the same table, with title/cover backfilled from
  `resolve`/`overview` instead of the placeholder "视频".
- **Search progress is one glass line.** `discover`/curating appears above the
  composer as a status line only; it never shows candidates or controls, and it
  clears when the batch starts.
- **Overview carries a short transcript preview.** Up to 1,600 characters are
  returned with overview so a simple content question can skip a separate
  transcript call; a truncated preview reports the next start. Measured direct
  task dropped from 55s to 38s, while token use stayed model/context-bound.
- **No-speech videos get an OCR preview in overview.** When there is no
  readable speech, overview carries up to 1,600 characters of slide/screen text,
  so the model can answer a text-heavy video without opening frame after frame.
  Normal transcript videos do not pay this extra context.
- **No false "语音识别" label on speechless videos.** A zero-segment record now
  reports transcript_source=none, and the live card says 无可用转写 when
  capabilities.transcript is false. It no longer presents an empty ASR result
  as a successful transcript.
- **Speechless summaries use the OCR preview.** The Skill now says to answer a
  general summary from ocr_preview + chapters, and only open frames for a
  specific visual detail. This targets the 1:53 slide video that previously took
  ~3 minutes by walking frames.
- **Bilibili captions use the WBI-signed endpoint.** The legacy /x/player/v2
  was returning another video's AI track: a 46s DSH video got 160 parenting
  lines ending at 298s, while /x/player/wbi/v2 returned the correct 18 lines
  ending at 39.9s. The 26m attention video's WBI response has no usable track
  and now falls back to ASR. The old trigram gate no longer false-rejects a WBI
  track (it rejected "deep sick" for the title's "dsh").
- **The plugin no longer enforces a model policy.** The Host-side
  E_SPEECHLESS_EVIDENCE_LIMIT cap and overview's answer_guidance field were
  removed: run_code, stop, and token/step budgets are DSH/Agent configuration,
  not a video plugin's job. The Skill still tells the model to answer a
  speechless video from ocr_preview and to open frames only for a specific
  visual detail.
- **Evidence frames stop producing broken image previews.** The CLI's JSON
  absolute frame paths were copied by the model into answers, and DSH tried to
  preview them as workspace file images ("图片无法预览"). The Host now removes
  the paths from the model-visible text (keeping an image_count) and supplies
  the actual frames only as attachment blocks.
- **Only the composer surface is rendered.** The user never asked for DSH-Video2Agent
  tool cards in the chat transcript. All `data-vp-card` result cards are hidden;
  the processing card and the selected-video table remain above the composer.
  The transcript-overview attachment and the 15s completion hold were withdrawn;
  the dock hold is back to 2.6s.
- **Do not blame a missing dependency without evidence.** When a transcript is
  empty, the Skill now distinguishes NO_AUDIO / ASR_FAILED / NO_TRANSCRIPT and
  requires doctor before saying Whisper is missing. A slide video can legitimately
  have zero speech while ASR is installed.
- **No unrequested edits or deletions.** The no-file rule now also forbids
  editing/deleting existing files or "cleaning" temp files unless asked. A live
  run removed two .tmp_*.py files on its own; that is still a workspace write.
- **No unrequested files.** A content answer stays in chat; the Skill now
  forbids creating/exporting a note, Markdown file or knowledge pack unless the
  user explicitly asks. The latest search run had added a 31-line note nobody
  requested, costing steps and tokens.
- **Bad transcripts cannot leak through chapters.** When overview marks a
  stored caption invalid, chapter titles now fall back to scenes/OCR/timecodes
  instead of the wrong words, so a phone-lens track cannot label an attention
  lecture.
- **Both visible surfaces share one shell.** The processing card and the
  selected-video table use the same 748px max width, glass surface, 20px radius
  and 0.32s entrance. The processing card drops technical source/duration/warning
  clutter; title, stage, ETA and the green completion line stay prominent.
- **Unrelated Bilibili caption tracks are rejected before selection.** Every
  advertised track is now compared (the old three-track cap could hide the only
  valid one). Tracks are checked against the video duration while candidates are
  still being compared, so a long wrong track cannot beat a shorter valid one;
  if every track is unrelated, the pipeline falls back to ASR with
  `CAPTION_TRACK_MISMATCH`. A same-duration wrong track is caught by
  title/description/tag content units and rejected with
  `CAPTION_CONTENT_MISMATCH`. Multi-P Bilibili links pass their `?p=N`
  page to the subtitle cid lookup. When captions are rejected and ASR is
  unavailable, the Skill now stops re-ingest loops and reports the limitation.
- **The model must call `video2agent` directly, not through `run_code`.** Nested
  `tools.video2agent` calls bypass the plugin card and appear as a generic
  run_code animation in the draft panel; the Skill and tool description now
  forbid that wrapping, and `doctor`/`list` are direct tool commands.
- **Process calls add no chat cards.** `ingest`/job polling drives the dock
  through a headless bridge; the batch table (with the card's green completion
  ring) is the only process surface, and the answer carries the result. The old
  in-chat completion card is hidden.
- **A card click continues the original task.** If the search request was a
  content task ("看完告诉我/分析这期"), the model now waits for the started job
  with `jobs --wait`, then calls overview/transcript/search/evidence and answers
  with timecodes. It no longer stops at "已启动". A bare video URL is analyzed
  directly; only a find/recommend-only search ends after the card.
- **Bilibili's order is the order.** Python no longer re-sorts discover results
  with a lexical `match.score` and no longer emits `recommended` /
  `needs_confirmation`. The model reads the metadata and names a
  `default_selected` subset; the card ticks only that subset.
- **The process limit is yours.** Settings now has a horizontal 1–10 slider
  with the number shown next to it (`processLimit`, default 10) for the most
  videos one run may process. The model's `default_selected` cannot exceed it;
  the confirm route enforces it too. The auto-processing note sits directly
  under its switch, and the long explanatory paragraphs were cut.
### Historical iterations (removed before release)

> The candidate card/picker, countdown, auto-pick and takeover described below
> were built during this unreleased RC and removed on 2026-11-01 in favour of the
> Host-start batch table. Kept as the development record; not part of the 0.1.0
> surface.

- **Search is fast by default.** Cover OCR is opt-in: 8 results took 13.8s with
  covers and 0.9s without them on this machine. The candidate card still shows
  cover images through the host proxy; `covers: true` is for ambiguous
  slide/table searches only. Candidate covers load lazily, and Escape closes
  the card like ×.
- **The shortlist matches the processing card's width.** It uses 712px, with
  16:6.5 covers (28% less cover height) and tighter rows, an adaptive 1–10 grid
  with no horizontal scrolling, the completed card's SVG check, and a `首选`
  badge. One candidate is valid; there is no fixed target count. The footer has
  one right-aligned 开始处理 button; × closes the card. There is no 取消 button
  and no `（n）` suffix. Only the model's `default_selected` candidates are
  ticked; the user can tick more up to the process limit. Closing/starting also
  clears the old raw-discover picker that used to reappear underneath. Escape
  closes the card,
  focused tiles get a visible ring, errors are announced and stay for 30s.
- **Cancel is validated against a real job.** An unknown job id now returns
  404 instead of creating a stray cancel marker; the worker still turns a real
  canceled job into a terminal canceled state.
- **Multiple selected videos are no longer silent.** After a multi-select
  start, a compact queue strip shows every job with its state and a 停止 button;
  the first job still has the full live card. 停止 writes a cancel marker and
  the worker turns the job `canceled` at its next stage boundary, instead of
  pretending that hiding the card stopped it.
- **The real model path and a real click were exercised, not only Host mocks.**
  In isolated DSH, DeepSeek V4.1-Flash ran discover → shortlist → the card → the
  visible countdown → one confirm, with no `E_SHORTLIST_DEFAULT`. A separate
  click on 开始处理 ran the real Host/CLI and reached a green ready card in 26s
  for the 46s video.
- **Old Skills still open a usable card.** If `default_selected` is absent
  (an older Skill), the Host ticks only the primary and puts a visible
  compatibility warning on the card instead of failing with
  `E_SHORTLIST_DEFAULT`; the current Skill still supplies the model's subset.
- **UI settings no longer freeze plugin Config.** A save patches only the raw
  `ui-settings.json`, so a later Config edit is not overwritten by merged
  defaults. Empty/error search cards now live 10 minutes instead of 2.
- **The card is now single-use and session-scoped.** Manual confirm requires
  the current `card_id`; a stale/double-clicked card returns 409 instead of
  starting another job. The pending card is claimed by the first conversation
  that sees it and hidden from other conversations; manual cards expire after
  10 minutes.
- **Wrong Bilibili subtitle tracks are rejected.** A 46s real video returned a
  caption track with 772 lines running past 1.5× its duration. The pipeline now
  discards that track and falls back to ASR instead of trimming wrong words and
  presenting them as evidence.
- **Windows ingest lock is hardened.** `_ingest_slot` treats `PermissionError`
  as lock contention, and a worker that dies before writing a terminal state is
  marked failed instead of staying `running` forever.
- **Parallel discover cannot drop the guard.** `offered.json` is now locked and
  written atomically, and the Host remembers the union of every offered candidate.
  In the 2026-10-28 draft session a parallel search race let one candidate through
  the confirmation guard; this closes it.

- **A video's own title is searchable.** Searching a word that only appears in the
  title used to return nothing (`NeurIPS` → 0 hits). Titles now have their own FTS
  index, so a search finds the video itself before its transcript lines.
- **Decimal numbers stay whole.** `3.5` was tokenised as `3` and `5` and matched
  unrelated pages ("3项(2025", "85%"); a lone digit is no longer a search term.
- **The decision is enforced, not requested.** `discover` records the ids it offered
  and `ingest` refuses them unless it gets a single-use token naming those ids. Only a
  user action (the card button, or a manual retry) issues one; a bare flag is refused
  outright. Previously an agent could skip the card and index the top hit on its own.
- **Searching several times in one turn no longer flashes the card.** The candidate
  list merges (newest first, de-duplicated, max 8) instead of being replaced — and a
  job starting no longer discards a list you opened *after* it started.
- **An answer you can check.** Evidence now says when the analysis behind it is old
  (`STALE_ANALYSIS`) or when a `ready` record has no transcript and no frames
  (`EMPTY_ANALYSIS`), and a deleted frame is reported instead of cited.
- **A dead worker is not a running job.** Jobs whose process is gone report
  `E_WORKER_LOST` instead of blocking the queue behind a ghost; listing jobs now
  reconciles them, and a worker that finished first is never rewritten to failed.
- **A replayed citation names a picture you receive.** If a frame file disappeared,
  the bundle now says `FRAME_MISSING` and moves the citation to the image that exists.
- **Unknown modality names are an error, not a silent zero.**
  `--modalities bogus` answers `E_BAD_MODALITY` with the accepted list.
- **Ingest does the minimum, and asks for more only when needed.** It takes the
  uploader/AI subtitle when one is readable, otherwise runs ASR, samples frames for
  the timeline, and **does not OCR anything up front**. Text inside a frame is read
  the first time that moment is asked for (`evidence --at`), stored as an anchor, and
  reused; a second question about the same moment is free. The frames themselves are
  returned to the model as images, because OCR cannot read handwriting, charts,
  actions or a UI — it is a search aid, not a description.
- **Timecodes describe the frame that was read, never the question.** With
  `--images 0` the text now carries the frame's own time (`ocr_frame_ms`), the
  payload reports `frame_ms` for the returned picture, and a frame more than a second
  away is replaced by an exact one. A stored anchor more than 5s away is no longer
  answered as if it belonged to this moment.
- **"Unmeasured" is not "zero".** Frames nobody read leave `text_coverage` empty
  instead of 0.0, so visual labels stop collapsing: before this, 610 of 667 segments
  in the local library were labelled `animation` (10/10 of them were really slides
  once read). Segments without a sampled frame are reported as `unknown` with a
  reason instead of disappearing, and `overview` exposes `visual.known` / `coverage`.
- **Frame dedupe compares pixels.** Per scene, the largest per-pixel difference of a
  32×32 thumbnail (≤8) decides duplicates; a perceptual hash had put six visually
  different slides within 2–4 bits of each other. On a 20-minute lecture this keeps
  91 of 120 frames with unchanged scene coverage.
- **Sharpness never saturates.** `min(1, var/900)` pinned 70% of real frames at 1.0;
  `1-exp(-var/1500)` gives p50 0.53, p90 0.88 on the same frames.
- **Old analyses say they are old.** Records written before `analysis_version 0.2`
  report `STALE_ANALYSIS` with a `--force` remedy instead of passing old labels off as
  current.
- **The shortlist is visible without opening a tool call.** Discovery results used
  to live only inside the tool card, which collapsed tool calls (PTC) hide
  completely — so the user was asked to choose from something they could not see.
  The candidates now also appear in the input dock above the composer as a 16:9 cover
  grid with checkboxes (the model's pick is pre-ticked) and one 开始处理 button that
  starts the ingest itself — no copy-and-paste, and a list you closed never returns.
- **A shortlist starts as a choice, not a bulk action.** The in-chat card used to
  pre-tick every hit, so a ten-result search offered "开始处理（10）"; it now starts
  with exactly one recommendation ticked. An unchosen list also disappears when the
  turn ends instead of staying clickable with no model turn behind it.
- **A crashed job shows its error on the first poll.** The jobs command returns a
  failed row inside a `{ok:false, job, error}` envelope; the Host now unwraps it, so
  the card reports `E_WORKER_LOST` and its remedy instead of a 404. A running job
  mirror older than 15s is reconciled through the CLI rather than shown as running
  for two minutes.
- **Auto-pick with a visible countdown.** A settings switch (default off) makes a
  search decide on its own: the dock plays a short progress bar and then starts
  processing without asking. Hovering the bar pauses the window (the Host pauses
  too, so the clock never runs out while you are deciding); clicking it takes over
  and unlocks the candidate checkboxes with the AI's choice already ticked. The
  window is 2.6 s (a fixed hold; hover pauses it, click takes over).
- **The choice is a question — asked every time — with an "AI picks" option.** The
  `discover` result carries a ready `next_step.request` (question, header,
  multi-select options) so the model asks through `ask_user_question`, which the
  shell renders as a real prompt above the composer. The option list ends with
  **「让 AI 自己选（推荐：…）」**: picking it makes the model take
  `next_step.recommended` and explain why, without asking again. The Skill carries
  the same rule (and why a collapsed card can never do this job).
- **Transcripts are compact and honest.** `transcript --compact` emits one
  `m:ss text` line per segment instead of a JSON object with five fields, and
  `--max-chars` now budgets the emitted text (timecodes included): an 11-minute
  talk went from 118,080 characters to 11,803, and a cut reply reports
  `truncated: true` plus `next_start_ms` instead of claiming to be complete. The
  agent tool always uses the compact form.
- **Progress no longer spawns a process per poll.** The worker mirrors each job
  update into `$VIDEO2AGENT_HOME/jobs/<id>.json` and the Host reads that file
  (~1ms), falling back to the CLI only when the mirror is missing or stale.
  Measured under a running ingest: 3,480ms per CLI poll vs ~1ms for the file.
- **Ingests queue instead of fighting.** One ingest at a time, and a waiting job
  reports `排队中` instead of sitting at 0% (three at once was 4.3x slower than
  one alone).
- **A repeat ingest of an indexed URL returns immediately** (742ms instead of
  5–44s): the id is derived from the URL before any download.
- **`fast` skips full shot detection** (fixed 60s grid), removing ~27s from a
  warm ingest; chapters degrade to time buckets.
- **First-run model download reports bytes** ("已下载 180.4MB") while the weights
  land, instead of one frozen percentage.
- **The default profile is `auto`** (lazy OCR: captions or ASR, frames sampled, no
  bulk OCR). `standard`/`deep` still exist for CLI users who want an eager index — the Skill, the plugin config
  and the settings form used to disagree.
- **Settings are visible to DSH.** The plugin exports a `Config` schema, so its
  settings appear in DSH's own config editor and are validated there. Precedence:
  the settings form's `ui-settings.json` wins over the plugin-row config, which
  wins over built-in defaults.
- **The best subtitle track wins, not the most “official” one.** A one-line
  “human” Chinese track used to beat a complete AI transcript; the fetcher now
  compares up to three candidates and keeps the longest (measured: 1 segment ->
  141 on `vid_f4936940aa5371bf`, transcription 25s -> 2.3s).
- **Discovery can be narrowed** — `discover --uploader <name|uid> --after 2026-10-01
  --before 30d`, and the agent tool gained `uploader` / `after` / `before`. The
  payload reports `filters` (`matched` / `dropped`), so a filter that matches
  nothing says so (`FILTER_EMPTY`) instead of looking like "no results". Dates
  accept `2026-10-01`, `2026/10/01`, or relative `7d` / `2w` / `3m`; a nonsense
  date is `E_DATE`, not a silent ignore. Candidates carry `uploader_id` (numeric
  uid) — that is what makes "this creator's other videos" unambiguous — and
  ingest keeps `uploader_id` / `upload_date` / `is_upower_exclusive` in metadata.

- **Boundaries are honest now.** `evidence`, `transcript`, and `frames` share one
  range check: a timestamp at or past the media end is `E_OUT_OF_RANGE` with a
  remedy, instead of an inverted range, an empty success, or a bare `E_FRAME`.
  `evidence` also reports `requested_ms`, `media_end_ms`, and `snapped`.
- **Truncated downloads are labelled.** When the platform advertises more video
  than the media actually contains (paywalled/preview/truncated), ingest adds a
  `MEDIA_TRUNCATED` warning and `overview` exposes `declared_duration_ms` /
  `declared_duration` / `exclusive`. Existing records get the warning derived at
  read time, so old libraries benefit without re-ingesting.
- **CLI failures keep their code and remedy** through the plugin: the host parses
  the CLI's `{ok:false,error:{code,message,remedy}}` envelope instead of wrapping
  the JSON into an `E_CLI` message, so the error card shows the real reason.
- **Search snippets centre on the match** (≤160 chars, hit within the first ~32)
  instead of `text[:500]`, where a keyword could sit in the last few characters.
- The `video2agent` tool exposes `wait_ms` for `jobs`, so a caller can block instead
  of polling.
- Plugin now loads **outside the web profile**: `webServer` is an optional
  dependency (deferred `ctx.inject`), so headless/TUI profiles still get the
  tool and `/video` command.
- Live card state is keyed **per session**: a job in another conversation can
  neither paint into nor hide this conversation's card.
- Failed tool calls render a structured error card with `code` and `remedy`
  instead of a permanent "waiting for result"; a raw CLI failure still renders
  an error card.
- Settings Save is honest: it awaits the Host POST and shows a failure state
  when persistence fails (previously it always said saved).
- Job polling backs off (1.2s → 15s) after failures, shows an interruption
  notice, and offers a retry button instead of stalling silently.
- Composer accepts `bilibili.com/video/BV…`, `av` numbers, `b23.tv` short
  links, and a bare BV id.
- Both composer cards share one glass material (same background, border, radius,
  blur and gap) and one accent colour.
- **Completion now reads like a finished build**: a job that really finished
  shows a filled **green** ring, a green check badge and "已完成 · 总长 … ·
  画面文字按需识别". Green is a semantic success colour (`--vp-ok`), not the theme
  accent, so it stays green whatever theme is picked. A turn that ends before the
  job does still shows the neutral "本轮结束 · 后台继续处理" wrap-up instead,
  because that is not a completion.
- **Bilibili QR login** (`video2agent biliauth`, and a 扫码登录 block on the plugin
  settings page): scan with the Bilibili mobile app and the session is stored at
  `$VIDEO2AGENT_HOME/cookies/bilibili-login.txt` — no cookie file to export, and the
  cookie never travels through an HTTP route. Login state, expiry, and sign-out
  are handled in the UI; a cookie file path remains as an advanced option.
- The `video2agent` tool gained `force`, so an already-indexed video can be
  re-ingested to pick up subtitles after logging in.
- **The card wraps up when the turn ends.** The dock slot's session object
  carries `running` (verified in a real profile), so when the assistant turn
  finishes the card switches to a closing state — "本轮结束 · 后台继续处理" (or
  "已完成"), frozen ring in grey, no pulsing dot, `aria-label` updated — and fades
  after 1.5s instead of hanging. A background job keeps running and its in-chat
  card stays as the record; landing on an idle session does not close a card that
  was never seen running.
- **The processing card no longer hangs after a finished task.** The strip only
  rendered what the in-chat job card pushed; when that card unmounted (a new turn
  started), polling stopped and a "running" card stayed on screen forever. A
  watchdog now re-checks only cards that stopped being refreshed (>5s), so a
  finished job clears itself in ~9s and a job that no longer exists clears in
  ~7s; a genuinely long background job keeps updating its progress.
- Live focus timecodes drop milliseconds (`00:02:56.720` → `00:02:56`); the exact
  value stays in the evidence payload.
- **Bilibili CC subtitles** are now reachable: the player API hides them from
  anonymous requests (verified on nine videos), so a logged-in cookie export
  (`--cookies <file>` or `cookies_file`) lets an uploader/AI subtitle become the
  transcript and ASR is skipped. Track preference is human Chinese → AI Chinese →
  English. `overview.metrics.transcript_source` (`caption` / `asr` / `none`) and
  optional `caption_track` record the provenance, and an anonymous URL ingest
  reports `CAPTION_LOGIN_REQUIRED` instead of silently paying for ASR.
- `video2agent doctor` reports `bilibili_login`, so a configured cookie file is
  visible instead of implied.
- ASR now retries from the local model cache (`local_files_only`) when the model
  host is unreachable, so a cached model still transcribes offline.
- New **theme colour** setting (5 presets + custom picker, default DSH blue),
  persisted on the Host and applied to every DSH-Video2Agent surface through a single
  `--vp-accent` token. Settings POSTs now patch instead of replacing, so a client
  that sends one field no longer resets the others.
- The in-chat job card is compact (title, one status line, stage rail, error,
  copy video_id); job ids, per-source counts, and a duplicate progress bar are
  gone.
- CLI timeouts kill the whole process tree on Windows and captured output is
  capped at 2 MiB.
- Public measurement docs: `docs/PLUGIN-BENCH.md`, `docs/COST.md`,
  `docs/INDEX-QUALITY.md`, plus real-UI screenshots in `docs/`.
- `scripts/dsh-isolated.ps1` (scratch `DSH_HOME` + scratch `VIDEO2AGENT_HOME`) and
  `scripts/bench-cli.mjs` for reproducible verification.
- Real isolated DSH 0.2.1-rc.3 verification: composer preview (real Bilibili
  title), processing card, per-session isolation, settings save and forced
  failure, retry validation, 420px layout, zero DSH-Video2Agent console errors.

## Previous work (same RC, earlier sessions)

- DSH processing card polished: App Store-style icon ring, Lucide check,
  session-isolated live ownership, 2.6s hold + 180ms fade, error close.
- Real error retry from the card through `POST /api/video2agent/retry`.
- Host-persisted settings (`$VIDEO2AGENT_HOME/ui-settings.json`) with default
  profile and OCR frame budget; Configure page under Plugins.
- Structured job `duration_ms` / `position_ms` / `updated_at`.
- Zero-position focus no longer renders a fake current frame.

## 0.1.0 (MVP, never published)

- Local-first CLI: doctor, setup, discover, ingest, jobs, overview, transcript,
  search, evidence, frames, map, bench, export, stats, gc, list.
- Bilibili keyword discovery with covers, cover OCR, match reasons, cover sheet.
- Bilibili public download with anonymous cookies and updated yt-dlp.
- Subtitle-first transcript, faster-whisper ASR fallback, timestamps.
- Scene detection, parallel frame extraction, sparse sequential OCR tracks.
- Visual structure labels: slide/table/chart/screencast/talking-head/animation.
- SQLite FTS5 search with visual terms, typo fuzzy fallback, evidence bundles.
- Knowledge JSON, Markdown, JSON, and offline HTML export.
- DSH/Claude/Codex Skill with citation and budget rules.
- Experimental DSH plugin: cached composer link preview above the input,
  one session-scoped glass processing card with cover/title, plain-language
  stage, AI focus, animated progress ring, terminal fade, /video command,
  video2agent tool, link/discovery/progress/evidence cards, and a local settings
  section for card/cache preferences.
- Storage retention/quota eviction for cached URL media.
- Additive SQLite migrations for older libraries.
- SSRF preflight for direct http(s) ingestion (private/metadata IP rejection).
- Optional local path allowlist (allowed_roots).
- Fast profile: tiny ASR + sparse OCR; 18:38 lecture dropped from about 459s to 138.7s.
- Cheap line/edge OCR prefilter; OCR is sequential because RapidOCR is not thread-safe.
- Exact-substring ranking for numeric/phrase queries (e.g. 第42段).
- 35 Python tests plus DSH card and manifest harnesses.
- Apache-2.0.

### Known limitations

- The DSH plugin is not market-tested or published.
- Card selection does not inject a message yet; use the host question tool or
  copy the selection.
- No MCP adapter (deliberately optional).
- ASR accuracy depends on model/audio; OCR is the largest CPU stage.
- No official 1-hour benchmark on varied real content.

import fs from 'node:fs'
import path from 'node:path'
import vm from 'node:vm'
import { fileURLToPath } from 'node:url'

const root = path.resolve(path.dirname(fileURLToPath(import.meta.url)), '..')
const clientPath = path.join(root, 'packages/dsh-video2agent/client.js')

let loaded = null
const pendingTimers = []
// localStorage is where the selected-video table lives; the direct-link path has
// no picker, so this is the only record of the job the client started.
const storage = new Map()
const context = {
  window: {
    __VIDEO2AGENT_DEBUG__: true,
    __ModuleLoader__: {
      load: (mod) => { loaded = mod },
    },
  },
  localStorage: {
    getItem: (key) => (storage.has(key) ? storage.get(key) : null),
    setItem: (key, value) => { storage.set(key, String(value)) },
    removeItem: (key) => { storage.delete(key) },
  },
  document: {
    createElement: () => ({ setAttribute() {}, remove() {}, textContent: '' }),
    head: { appendChild() {} },
  },
  console,
  // Polling must not schedule real timers inside the test process.
  setTimeout: (fn) => { pendingTimers.push(fn); return pendingTimers.length },
  clearTimeout: () => {},
  fetch: async () => ({ json: async () => ({}) }),
  navigator: { clipboard: { writeText: async () => {} } },
  URL,
}
vm.createContext(context)
vm.runInContext(fs.readFileSync(clientPath, 'utf8'), context, { filename: clientPath })
if (!loaded) throw new Error('module loader was not called')

const React = {
  createElement: (type, props, ...children) => ({ type, props: props || {}, children }),
  useState: (init) => [typeof init === 'function' ? init() : init, () => {}],
  useEffect: (fn) => { fn() },
  useRef: (init) => ({ current: init }),
}
const fakeRequire = (name) => {
  if (name === 'react') return React
  throw new Error('unexpected require: ' + name)
}

const mod = loaded.factory(fakeRequire)
let captured = null
const capturedSlots = {}
const slots = {
  inject: (name, fn) => fn(),
  register: (spec, component) => {
    if (!capturedSlots[spec.name]) capturedSlots[spec.name] = []
    capturedSlots[spec.name].push({ spec, component })
    if (spec.name === 'tool.call.toolview') captured = { spec, component }
    return () => {}
  },
}
mod.apply({
  get: (name) => (name === 'slots' ? slots : undefined),
  effect: () => {},
})

if (!captured) throw new Error('tool card was not registered')
if (captured.spec.key !== 'video2agent') throw new Error('wrong slot key: ' + captured.spec.key)

// The floating fixed-position HUD is gone on purpose: progress lives inline.
if ((capturedSlots['conversation.input.overlay'] || []).length) {
  throw new Error('floating status overlay must not be registered')
}
const dockEntries = capturedSlots['conversation.input.dock'] || []
if (dockEntries.some((e) => e.spec.id === 'video2agent-scope')) throw new Error('session scope bridge is obsolete')
const previewEntry = dockEntries.find((e) => e.spec.id === 'video2agent-link-preview')
if (!previewEntry) throw new Error('composer preview was not registered')
const statusEntry = dockEntries.find((e) => e.spec.id === 'video2agent-status')
if (!statusEntry) throw new Error('processing window was not registered')
statusEntry.component({ session: { id: 'session-a', running: true } })
// A session switch must not create a LIVE shell that lets history cards appear.
const emptyHistory = captured.component({
  block: {
    call: { argsRaw: JSON.stringify({ command: 'overview' }) },
    content: [{ type: 'text', text: JSON.stringify({ title: 'QA 历史总览卡片', counts: { segments: 3 } }) }],
    isError: false,
  },
})
emptyHistory.type(emptyHistory.props)
if (statusEntry.component({ session: { id: 'session-empty', running: false } })) throw new Error('historical overview created a live card')
statusEntry.component({ session: { id: 'session-a', running: true } })
const publish = context.window.__video2agentPublishLive
if (typeof publish !== 'function') throw new Error('debug publish missing')
const canPublishJob = context.window.__video2agentCanPublishJob
if (typeof canPublishJob !== 'function') throw new Error('session publish guard missing')
if (canPublishJob('session-b', 'session-a', { sessionId: 'session-a' })) throw new Error('cross-session job publish allowed')
if (canPublishJob('session-b', 'session-b', { sessionId: 'session-a' })) throw new Error('job leaked into another session')
if (!canPublishJob('session-a', 'session-a', { sessionId: 'session-a' })) throw new Error('owner session publish blocked')

// Composer link forms: BV / av / b23 short / bare BV id all reach the preview,
// and the canonical URL the Host receives is normalised.
const detectVideoLink = context.window.__video2agentDetectVideoLink
if (typeof detectVideoLink !== 'function') throw new Error('link detector missing')
const linkCases = [
  ['https://www.bilibili.com/video/BV1GJ411x7h7', 'https://www.bilibili.com/video/BV1GJ411x7h7'],
  ['看这个 https://bilibili.com/video/av170001 讲得不错', 'https://www.bilibili.com/video/av170001'],
  ['https://b23.tv/AbCd123', 'https://b23.tv/AbCd123'],
  ['分享 BV1GJ411x7h7 这个视频', 'https://www.bilibili.com/video/BV1GJ411x7h7'],
  // Douyin: canonical, share page and short link all normalise to a video URL.
  ['https://www.douyin.com/video/7665930064613199114', 'https://www.douyin.com/video/7665930064613199114'],
  ['https://www.iesdouyin.com/share/video/7665930064613199114/', 'https://www.douyin.com/video/7665930064613199114'],
  ['7.85 复制打开抖音 https://v.douyin.com/s-GVFhZGxtk/ 看看', 'https://v.douyin.com/s-GVFhZGxtk/'],
]
for (const [input, expected] of linkCases) {
  const got = detectVideoLink(input)
  if (!got || got.url !== expected) throw new Error('link detect failed for ' + input + ' -> ' + JSON.stringify(got))
}
if (detectVideoLink('https://example.com/watch?v=1') !== null) throw new Error('non-Bilibili link must not trigger the preview')
const shortPreview = previewEntry.component({ input: { draft: '看看 https://b23.tv/AbCd123' } })
if (!shortPreview || !JSON.stringify(shortPreview).includes('正在读取视频信息')) throw new Error('b23 short link preview did not render')
// Douyin links go through the same preview, but must be labelled 抖音视频.
const douyinPreview = previewEntry.component({ input: { draft: 'https://www.douyin.com/video/7665930064613199114' } })
const douyinJson = JSON.stringify(douyinPreview)
if (!douyinJson.includes('抖音视频')) throw new Error('Douyin preview must be labelled 抖音视频')
if (douyinJson.includes('B 站视频')) throw new Error('Douyin preview must not be labelled B 站视频')
const preview = previewEntry.component({ input: { draft: 'https://www.bilibili.com/video/BV1test12345' } })
if (!preview || !JSON.stringify(preview).includes('正在读取视频信息')) throw new Error('composer preview did not render')

const discovery = {
  query: 'Transformer 注意力机制',
  needs_confirmation: false,
  candidates: [{
    candidate_id: 'bili_BV1test',
    title: 'Transformer 注意力机制',
    uploader: 'tester',
    duration_ms: 90000,
    match: { score: 0.84, reasons: ['标题命中'] },
  }, {
    candidate_id: 'bili_BV1other',
    title: '另一期注意力机制',
    uploader: 'tester2',
    duration_ms: 120000,
    match: { score: 0.51, reasons: ['标题命中'] },
  }],
}
const discoveryCard = captured.component({
  block: {
    call: { argsRaw: JSON.stringify({ command: 'discover' }) },
    content: [{ type: 'text', text: JSON.stringify(discovery) }],
    isError: false,
  },
})
// Raw discover results are model input, not chat UI. The single candidate card
// is the dock entry published after shortlist; ten searches used to render ten
// eight-item cards in the 2026-10-28 draft session.
if (discoveryCard !== null) throw new Error('raw discover result must not render a chat card')

const link = captured.component({
  block: {
    call: { argsRaw: JSON.stringify({ command: 'resolve', url: 'https://www.bilibili.com/video/BV1test' }) },
    content: [{ type: 'text', text: JSON.stringify({ ok: true, kind: 'video-link', title: 'Transformer 链接', uploader: 'tester', duration: '18m38s', cover_url: 'https://example.com/cover.jpg', url: 'https://www.bilibili.com/video/BV1test', platform: 'bilibili' }) }],
    isError: false,
  },
})
if (link.type.name !== 'LinkCard') throw new Error('expected LinkCard, got ' + link.type.name)
const linkRendered = link.type(link.props)
if (!JSON.stringify(linkRendered).includes('Transformer 链接')) throw new Error('link card title missing')

// A Douyin resolve is still a video-link payload, but its card must name the
// actual platform instead of the hard-coded Bilibili kicker.
const douyinLink = captured.component({
  block: {
    call: { argsRaw: JSON.stringify({ command: 'resolve', url: 'https://www.douyin.com/video/7665930064613199114' }) },
    content: [{ type: 'text', text: JSON.stringify({ ok: true, kind: 'video-link', platform: 'douyin', title: '抖音链接', url: 'https://www.douyin.com/video/7665930064613199114', uploader: 'tester' }) }],
    isError: false,
  },
})
if (douyinLink.type.name !== 'LinkCard') throw new Error('expected LinkCard for a Douyin link')
const douyinLinkJson = JSON.stringify(douyinLink.type(douyinLink.props))
if (!douyinLinkJson.includes('抖音视频')) throw new Error('Douyin link card is not labelled 抖音视频')
if (douyinLinkJson.includes('Bilibili')) throw new Error('Douyin link card still claims Bilibili')

// Inline job card: same information the old floating HUD had, in place.
const progress = captured.component({
  block: {
    call: { argsRaw: JSON.stringify({ command: 'ingest', profile: 'standard' }) },
    content: [{ type: 'text', text: JSON.stringify({ ok: true, job_id: 'job_test123', state: 'running', stage: 'ocr', progress: 0.6, message: '识别画面文字' }) }],
    isError: false,
  },
})
if (!progress || progress.type.name !== 'JobCard') throw new Error('job bridge missing')
if (progress.type(progress.props) !== null) throw new Error('process tool cards must not render in chat')
function deep(node) {
  if (node === null || node === undefined || node === false) return ''
  if (Array.isArray(node)) return node.map(deep).join('')
  if (typeof node !== 'object') return String(node)
  const name = typeof node.type === 'string' ? node.type : (node.type && node.type.name) || 'component'
  let out = name + JSON.stringify(node.props || {})
  if (typeof node.type === 'function') out += deep(node.type(node.props))
  else out += (node.children || []).map(deep).join('')
  return out
}
const doneCard = captured.component({
  block: {
    call: { argsRaw: JSON.stringify({ command: 'overview' }) },
    content: [{ type: 'text', text: JSON.stringify({ ok: true, title: '完成后视频', duration: '03:00', video_id: 'vid_done', counts: { segments: 12, frames: 3 }, capabilities: { transcript: true, frames: true } }) }],
    isError: false,
  },
})
if (!doneCard || doneCard.type.name !== 'OverviewCard') throw new Error('completion card did not render')
const doneText = deep(doneCard.type(doneCard.props))
for (const needle of ['完成后视频', '已完成', '证据索引可用']) {
  if (!doneText.includes(needle)) throw new Error('completion card missing: ' + needle)
}
if (!doneText.includes('data-vp-done')) throw new Error('completion card must use the dock-like done style')

const rawFailure = captured.component({
  block: {
    call: { argsRaw: JSON.stringify({ command: 'overview' }) },
    content: [{ type: 'text', text: 'Timed out. Try --detach and poll jobs.' }],
    isError: false,
  },
})
if (rawFailure.type.name !== 'ErrorCard') throw new Error('raw CLI failure should render ErrorCard')

const structuredFailure = captured.component({
  block: {
    call: { argsRaw: JSON.stringify({ command: 'overview' }) },
    content: [{ type: 'text', text: JSON.stringify({ ok: false, text: 'failed', error: { code: 'E_SPAWN', message: 'video2agent not found', remedy: 'Install video2agent' } }) }],
    isError: false,
  },
})
if (structuredFailure.type.name !== 'ErrorCard') throw new Error('structured CLI failure should render ErrorCard')
const structuredText = deep(structuredFailure.type(structuredFailure.props))
if (!structuredText.includes('E_SPAWN')) throw new Error('structured error code missing')
if (!structuredText.includes('video2agent not found')) throw new Error('structured error message missing')
if (!structuredText.includes('Install video2agent')) throw new Error('structured error remedy missing')

const evidence = captured.component({
  block: {
    call: { argsRaw: JSON.stringify({ command: 'evidence' }) },
    content: [{ type: 'text', text: JSON.stringify({ title: 'demo', citation: '《demo》 00:00:02', range: { timecode: '00:00:02' }, transcript: [{ start_ms: 2000, text: '表格', source: 'caption' }], ocr: [], images: ['C:/x/derived/v/frames/a.jpg'] }) }],
    isError: false,
  },
})
if (!evidence || evidence.type.name !== 'EvidenceCard') throw new Error('evidence card did not render')
const evidenceText = deep(evidence.type(evidence.props))
if (!evidenceText.includes('复制引用')) throw new Error('evidence card missing citation action')
if (!evidenceText.includes('/api/video2agent/frame?path=')) throw new Error('evidence card should show frame thumbnails')

publish({ title: 'demo', videoId: 'vid_demo', jobId: 'job_demo', phase: 'running', pct: 60, stage: '正在读画面上的文字', createdAt: new Date().toISOString() })
const search = captured.component({
  block: {
    call: { argsRaw: JSON.stringify({ command: 'search' }) },
    content: [{ type: 'text', text: JSON.stringify({ ok: true, query: '动画', results: [{ timecode: '00:01:09.900', snippet: 'taunt_2', source: 'ocr_track', confidence: 0.99 }] }) }],
    isError: false,
  },
})
if (!search || search.type.name !== 'SearchCard') throw new Error('search card did not render')
const searchText = deep(search.type(search.props))
if (!searchText.includes('画面文字')) throw new Error('search card should label the modality in chinese')

const live = statusEntry.component({ session: { id: 'session-a', running: true } })
const liveText = deep(live)
for (const needle of ['data-vp-live', 'role', '正在处理']) {
  if (!liveText.includes(needle)) throw new Error('processing window missing: ' + needle)
}
// The live card keeps the ring/cover/stage but no longer mirrors the model's
// evidence timecode as an "AI focus"; that was implementation detail.
if (liveText.includes('00:01:09')) throw new Error('live card should not show the evidence focus timecode')
const otherLive = statusEntry.component({ session: { id: 'session-b', running: false } })
if (otherLive !== null) throw new Error('processing window leaked into another session')

// A historical result card in B must not hijack A's running card.
const historicalResolve = captured.component({
  block: {
    call: { argsRaw: JSON.stringify({ command: 'resolve' }) },
    content: [{ type: 'text', text: JSON.stringify({ ok: true, kind: 'video-link', title: 'QA 历史链接卡片', url: 'https://www.bilibili.com/video/BV1test12345' }) }],
    isError: false,
  },
})
deep(historicalResolve.type(historicalResolve.props))
if (statusEntry.component({ session: { id: 'session-b', running: false } })) throw new Error('historical card hijacked the other session')
const ownerLive = statusEntry.component({ session: { id: 'session-a', running: true } })
if (!ownerLive || !deep(ownerLive).includes('demo')) throw new Error('running card lost its owning session')

// A background job from session A polls while B is active; it must stay owned by A.
statusEntry.component({ session: { id: 'session-b', running: true } })
progress.type(progress.props)
const backInA = statusEntry.component({ session: { id: 'session-a', running: true } })
if (!backInA) throw new Error('background job lost its owning session')

statusEntry.component({ session: { id: 'session-a', running: false } })
const failed = captured.component({
  block: {
    call: { argsRaw: JSON.stringify({ command: 'ingest' }) },
    content: [{ type: 'text', text: JSON.stringify({ job_id: 'job_failed', state: 'failed', stage: 'failed', progress: 1, error_code: 'E_TEST', error_message: '视频处理失败' }) }],
    isError: false,
  },
})
deep(failed.type(failed.props))
publish({ title: 'failed demo', jobId: 'job_failed', phase: 'error', pct: 0, errorMessage: '视频处理失败', createdAt: new Date().toISOString() })
const errorLive = statusEntry.component({ session: { id: 'session-a', running: false } })
const errorText = deep(errorLive)
for (const needle of ['data-vp-live', '未完成']) {
  if (!errorText.includes(needle)) throw new Error('error window missing: ' + needle)
}
// Failure reasons / retry / close are no longer part of the process card; the
// assistant explains the failure in the answer instead.
for (const stale of ['遇到问题', '视频处理失败', '重试', '关闭']) {
  if (errorText.includes(stale)) throw new Error('process card still exposes failure detail: ' + stale)
}

const sameVideoBlock = {
  block: {
    call: { argsRaw: JSON.stringify({ command: 'resolve' }) },
    content: [{ type: 'text', text: JSON.stringify({ ok: true, kind: 'video-link', title: 'same video', video_id: 'vid_same', url: 'https://www.bilibili.com/video/BV1test12345' }) }],
    isError: false,
  },
}
statusEntry.component({ session: { id: 'session-b', running: false } })
deep(captured.component(sameVideoBlock).type(captured.component(sameVideoBlock).props))
statusEntry.component({ session: { id: 'session-a', running: false } })
const sameCard = captured.component(sameVideoBlock)
deep(sameCard.type(sameCard.props))
if (!statusEntry.component({ session: { id: 'session-a', running: false } })) throw new Error('same-video card was attributed to the wrong session')

// Once the card is dismissed, switching sessions or replaying the same job must not revive it.
statusEntry.component({ session: { id: 'session-a', running: false } })
publish({ title: 'hidden job', jobId: 'job_hide', videoId: 'vid_hide', phase: 'running', pct: 42, stage: '正在读画面上的文字' })
statusEntry.component({ session: { id: 'session-a', running: false } })
publish({ title: 'hidden job', jobId: 'job_hide', videoId: 'vid_hide', phase: 'ready', pct: 100, stage: '已完成' })
statusEntry.component({ session: { id: 'session-a', running: false } })
const hideTimer = [...pendingTimers].reverse().find((fn) => String(fn).includes('setDismissed'))
if (!hideTimer) throw new Error('auto-dismiss timer was not scheduled')
const seenTimers = new Set()
for (;;) {
  const timer = [...pendingTimers].reverse().find((fn) => String(fn).includes('setDismissed') && !seenTimers.has(fn))
  if (!timer) break
  seenTimers.add(timer)
  timer()
}
if (statusEntry.component({ session: { id: 'session-a', running: false } })) throw new Error('dismissed card came back in its own session')
// A stored same-job result still says running. Replaying it must not unhide.
publish({ title: 'hidden job', jobId: 'job_hide', videoId: 'vid_hide', phase: 'running', pct: 50, stage: '正在读画面上的文字' })
if (statusEntry.component({ session: { id: 'session-a', running: true } })) throw new Error('same-job history revived the dismissed card')
statusEntry.component({ session: { id: 'session-b', running: false } })
if (statusEntry.component({ session: { id: 'session-a', running: false } })) throw new Error('dismissed card came back after a session switch')
// A genuinely new task must show again.
publish({ title: 'new job', jobId: 'job_new', videoId: 'vid_new', phase: 'running', pct: 5, stage: '正在准备视频', createdAt: new Date(Date.now() + 5000).toISOString() })
if (!statusEntry.component({ session: { id: 'session-a', running: true } })) throw new Error('new task did not revive the card')

const settingsEntry = (capturedSlots['settings.section'] || []).find((e) => e.spec.id === 'video2agent')
if (!settingsEntry) throw new Error('settings section was not registered')
const settingsText = deep(settingsEntry.component({}))
for (const needle of ['Video2Agent', '单次处理上限', '链接预览缓存', '缓存到期删除', '缓存保留天数', '限制缓存容量', '缓存容量上限']) {
  if (!settingsText.includes(needle)) throw new Error('settings section missing: ' + needle)
}
// Retired: the cookie-file row (QR login replaced it), the finished-card hold knob,
// the auto-pick countdown, and every "how much work" preference — that is the
// model's call per request, and the card starts the model's selection itself.
for (const gone of ['高级：Cookie 文件', '完成后停留', 'data-vp-cookies', '自动选择等待', '处理强度', '画面文字识别帧数', 'OCR 帧预算', 'AI 自动处理', '开始处理', '倒计时']) {
  if (settingsText.includes(gone)) throw new Error('retired setting still rendered: ' + gone)
}
if (!settingsText.includes('自动保存')) throw new Error('UI settings must be auto-saved')
const bundleSettings = (capturedSlots['plugins.bundle.config'] || []).find((e) => e.spec.key === 'dsh-video2agent')
if (!bundleSettings) throw new Error('plugin manager config page was not registered')
if (!deep(bundleSettings.component({ view: 'summary' })).includes('云端 ASR/OCR')) throw new Error('plugin config summary missing')
if (!deep(bundleSettings.component({ view: 'page' })).includes('单次处理上限')) throw new Error('plugin config page missing')

// --- Session-keyed live state -------------------------------------------------
// A single module-global live slot used to be shared by every conversation, so
// a publisher that declared another session was re-labelled into the active one
// and painted there (observed live in an isolated DSH 0.2 browser session).
{
  const state = context.window.__video2agentLiveState
  if (typeof state !== 'function') throw new Error('live state debug hook missing')

  // A publishes; B publishes; both entries must exist independently.
  publish({ sessionId: 'sess-a', jobId: 'job_a', title: '会话 A 的视频', phase: 'running', pct: 10, stage: '正在听语音', createdAt: new Date().toISOString() })
  publish({ sessionId: 'sess-b', jobId: 'job_b', title: '会话 B 的视频', phase: 'running', pct: 80, stage: '正在读画面上的文字', createdAt: new Date().toISOString() })
  const snap = state()
  const a = snap.sessions.find(([id]) => id === 'sess-a')
  const b = snap.sessions.find(([id]) => id === 'sess-b')
  if (!a || !b) throw new Error('per-session live entries missing: ' + JSON.stringify(snap.sessions.map(([id]) => id)))
  if (a[1].sessionId !== 'sess-a' || a[1].pct !== 10) throw new Error('session A entry was overwritten: ' + JSON.stringify(a[1]))
  if (b[1].sessionId !== 'sess-b' || b[1].pct !== 80) throw new Error('session B entry is wrong: ' + JSON.stringify(b[1]))

  // Rendering A shows A's own job, not B's.
  const stripA = statusEntry.component({ session: { id: 'sess-a', running: true } })
  const stripAText = deep(stripA)
  if (!stripAText.includes('会话 A 的视频')) throw new Error('session A lost its own live status')
  if (stripAText.includes('会话 B 的视频')) throw new Error('session B state painted into session A')

  // B's terminal state must not hide or replace A's entry.
  publish({ sessionId: 'sess-b', jobId: 'job_b', phase: 'error', errorMessage: 'B 失败' })
  const afterB = state().sessions.find(([id]) => id === 'sess-b')
  if (!afterB || afterB[1].phase !== 'error') throw new Error('session B error was not stored on B')
  const stripA2 = deep(statusEntry.component({ session: { id: 'sess-a', running: true } }))
  if (!stripA2.includes('会话 A 的视频')) throw new Error('session A status lost after B failed')

  // A publisher that declares nothing still targets the active conversation, so
  // the debug hook and legacy call sites keep working.
  const active = state().activeSession
  if (!active) throw new Error('active session was not tracked')
  publish({ jobId: 'job_implicit', title: '隐式会话状态', phase: 'running', pct: 33, stage: '正在整理内容', createdAt: new Date().toISOString() })
  const implicit = state().sessions.find(([id]) => id === active)
  if (!implicit || implicit[1].jobId !== 'job_implicit') throw new Error('implicit publish did not target the active session')
}

// --- Theme colour -------------------------------------------------------------
// The accent is a user setting, so the client derives one palette from one hex
// and the settings page exposes presets + a custom picker.
{
  const palette = context.window.__video2agentAccentPalette
  if (typeof palette !== 'function') throw new Error('accent palette hook missing')
  const blue = palette('#0a84ff')
  if (blue.accent !== '#0a84ff') throw new Error('default accent changed: ' + blue.accent)
  if (blue.soft !== 'rgba(10,132,255,.10)') throw new Error('soft token wrong: ' + blue.soft)
  if (!/^#[0-9a-f]{6}$/.test(blue.strong) || !/^#[0-9a-f]{6}$/.test(blue.tint)) throw new Error('derived tokens must be hex')
  const purple = palette('#6B5CFF')
  if (purple.accent !== '#6b5cff') throw new Error('accent must be lowercased: ' + purple.accent)
  if (purple.soft !== 'rgba(107,92,255,.10)') throw new Error('custom accent soft token wrong: ' + purple.soft)
  if (palette('not-a-colour').accent !== '#0a84ff') throw new Error('invalid accent must fall back to the default')
  const css = context.window.__video2agentAccentCss('#6b5cff')
  for (const needle of ['--vp-accent:#6b5cff', '--vp-accent-soft:rgba(107,92,255,.10)', '[data-vp-live]']) {
    if (!css.includes(needle)) throw new Error('accent css missing: ' + needle)
  }
  const settingsText = deep(settingsEntry.component({}))
  if (!settingsText.includes('主题色')) throw new Error('settings page missing the theme colour row')
  const swatches = (settingsText.match(/data-vp-swatch/g) || []).length
  if (swatches < 5) throw new Error('theme colour presets missing: ' + swatches)
  if (!(settingsText.match(/data-vp-color/g) || []).length) throw new Error('custom colour picker missing')
  if (!settingsText.includes('B 站登录')) throw new Error('settings page missing the Bilibili login block')
  if (!(settingsText.match(/data-vp-bili/g) || []).length) throw new Error('Bilibili login block markup missing')
  if (!settingsText.includes('抖音登录')) throw new Error('settings page missing the Douyin login block')
  if (!(settingsText.match(/data-vp-douyin/g) || []).length) throw new Error('Douyin login block markup missing')
  if (!settingsText.includes('抖音搜索')) throw new Error('Douyin search toggle missing')
  if (!(settingsText.match(/data-vp-douyin-search/g) || []).length) throw new Error('Douyin search toggle markup missing')
  if (!settingsText.includes('风控严格') || !settingsText.includes('完成')) throw new Error('Douyin search risk helper text missing')
  if (!settingsText.includes('单次处理上限')) throw new Error('process limit setting missing')
  if (!(settingsText.match(/data-vp-process-limit/g) || []).length) throw new Error('process limit input missing')
}

// --- Stale live card watchdog -------------------------------------------------
// The strip never polls; it only renders what the JobCard pushed. When the card
// unmounts (turn ends) a running entry used to stay on screen forever. The
// watchdog re-checks only entries that stopped being refreshed.
{
  const state = context.window.__video2agentLiveState
  const tick = context.window.__video2agentWatchdogTick
  const shortTimecode = context.window.__video2agentShortTimecode
  if (typeof tick !== 'function') throw new Error('watchdog hook missing')
  if (typeof shortTimecode !== 'function') throw new Error('timecode helper missing')

  if (shortTimecode('00:02:56.720') !== '00:02:56') throw new Error('milliseconds not trimmed: ' + shortTimecode('00:02:56.720'))
  if (shortTimecode('01:12:34') !== '01:12:34') throw new Error('timecode without ms changed')
  if (shortTimecode(null) !== '') throw new Error('null timecode should be empty')

  const entryFor = (id) => {
    const found = state().sessions.find(([sid]) => sid === id)
    return found ? found[1] : null
  }
  const originalFetch = context.fetch
  let fetchCalls = 0

  // 1) A finished job must become terminal instead of hanging on "running".
  publish({ sessionId: 'wd-a', jobId: 'job_wd_a', phase: 'running', pct: 30, stage: '正在找关键画面', createdAt: new Date().toISOString() })
  const staleA = entryFor('wd-a')
  staleA.updatedAt = 0
  context.fetch = async () => {
    fetchCalls += 1
    return { status: 200, ok: true, json: async () => ({ job: { id: 'job_wd_a', state: 'ready', progress: 1, stage: 'done' }, overview: { warnings: [] } }) }
  }
  await tick()
  if (fetchCalls !== 1) throw new Error('watchdog should fetch a stale entry once, got ' + fetchCalls)
  if (entryFor('wd-a').phase !== 'ready') throw new Error('stale running entry did not become ready: ' + entryFor('wd-a').phase)

  // 2) A fresh entry must not be polled again (the JobCard owns it).
  publish({ sessionId: 'wd-b', jobId: 'job_wd_b', phase: 'running', pct: 40, stage: '正在听语音', createdAt: new Date().toISOString() })
  fetchCalls = 0
  await tick()
  if (fetchCalls !== 0) throw new Error('watchdog polls entries that are still fresh: ' + fetchCalls)

  // 3) A job that no longer exists must hide the card, not keep lying.
  publish({ sessionId: 'wd-c', jobId: 'job_wd_c', phase: 'running', pct: 55, stage: '正在整理内容', createdAt: new Date().toISOString() })
  const staleC = entryFor('wd-c')
  staleC.updatedAt = 0
  context.fetch = async () => ({ status: 404, ok: false, json: async () => ({ error: 'not found' }) })
  await tick()
  if (entryFor('wd-c').hidden !== true) throw new Error('missing job did not hide the stale card')

  context.fetch = originalFetch
}

// --- Turn end closes the card with a wrap-up state -----------------------------
// Product decision: when the assistant turn ends, the work is done as far as the
// card is concerned, so it wraps up ("本轮结束") and fades instead of hanging.
{
  const state = context.window.__video2agentLiveState
  const entryFor = (id) => {
    const found = state().sessions.find(([sid]) => sid === id)
    return found ? found[1] : null
  }

  // A card that was running during the turn closes when the turn ends. The first
  // render observes the transition and publishes the wrap-up; the next render
  // shows it (same as a real re-render after the state change).
  publish({ sessionId: 'close-a', jobId: 'job_close_a', phase: 'running', pct: 42, stage: '正在找关键画面', duration: '08:32', createdAt: new Date().toISOString() })
  statusEntry.component({ session: { id: 'close-a', running: true } })
  statusEntry.component({ session: { id: 'close-a', running: false } })
  const rendered = deep(statusEntry.component({ session: { id: 'close-a', running: false } }))
  const closed = entryFor('close-a')
  if (closed.phase !== 'closing') throw new Error('turn end did not close the card: ' + closed.phase)
  if (!rendered.includes('本轮结束')) throw new Error('closing card missing 本轮结束')
  if (rendered.includes('后台继续处理')) throw new Error('closing card should use the short status only')
  if (!rendered.includes('已收尾')) throw new Error('closing aria label missing')
  if (closed.etaMs !== 0) throw new Error('closing card must drop the ETA')

  // Closing is a terminal phase: the normal dismiss path hides it. The hold and
  // the fade are two nested timers, so drain both.
  const seenClosing = new Set()
  let firedClosing = 0
  for (;;) {
    const timer = [...pendingTimers].reverse().find((fn) => String(fn).includes('setDismissed') && !seenClosing.has(fn))
    if (!timer) break
    seenClosing.add(timer)
    timer()
    firedClosing += 1
  }
  if (!firedClosing) throw new Error('closing card scheduled no dismiss')
  if (entryFor('close-a').hidden !== true) throw new Error('closing card was not hidden after the hold')

  // Merely landing on an idle session must NOT kill a background card.
  publish({ sessionId: 'close-b', jobId: 'job_close_b', phase: 'running', pct: 60, stage: '正在听语音', createdAt: new Date().toISOString() })
  statusEntry.component({ session: { id: 'close-b', running: false } })
  if (entryFor('close-b').phase !== 'running') throw new Error('idle mount closed a background card it never saw running')
}

// --- A historical shortlist card must not recreate its batch ------------------
// Opening an old conversation remounts its tool cards. A shortlist that started
// minutes ago is history: it must not create a queue or a live card again.
{
  const oldAt = Date.now() - 10 * 60 * 1000
  const view = captured.component({
    sessionId: 'sess-shortlist-history',
    block: {
      call: { argsRaw: JSON.stringify({ command: 'shortlist', video_ids: ['BV1old'] }) },
      content: [{ type: 'text', text: JSON.stringify({ ok: true, state: 'started', started_at: oldAt, jobs: [{ video_id: 'BV1old', job_id: 'job_old', title: '旧批次', state: 'ready', origin: 'shortlist' }] }) }],
      isError: false,
    },
  })
  if (view !== null) throw new Error('historical shortlist must not render a chat card')
  if (storage.get('video2agent.queue.sess-shortlist-history')) throw new Error('historical shortlist recreated the queue')
  const live = context.window.__video2agentLiveState().sessions.find(([sid]) => sid === 'sess-shortlist-history')
  if (live) throw new Error('historical shortlist published a live card: ' + JSON.stringify(live))
}

// --- Discover no longer publishes a picker -----------------------------------
// The retired candidate panel is gone for good: a discover result is model input
// only, and it must not create a queue or a live card either.
{
  if (context.window.__video2agentPublishPicker !== undefined) throw new Error('legacy picker hook still exposed')
  const beforeLive = JSON.stringify(context.window.__video2agentLiveState().sessions)
  const view = captured.component({
    sessionId: 'sess-discover',
    block: {
      call: { argsRaw: JSON.stringify({ command: 'discover', query: 'Transformer' }) },
      content: [{ type: 'text', text: JSON.stringify({ ok: true, query: 'Transformer', candidates: [{ candidate_id: 'bili_A', video_id: 'BV1aaaaaaaa1', title: '甲' }], next_step: { action: 'shortlist', ts: Date.now() } }) }],
      isError: false,
    },
  })
  if (view !== null) throw new Error('discover must not render a chat card')
  if (context.window.__video2agentQueueState('sess-discover')) throw new Error('discover must not create a selected-video table')
  if (JSON.stringify(context.window.__video2agentLiveState().sessions) !== beforeLive) throw new Error('discover must not publish live state')
}

// --- Shortlist result creates the batch table and the live card --------------
// The Host starts the jobs inline and returns their rows; this tool result is the
// only source of the table. There is no confirm POST to wait for.
{
  const jobs = [
    { video_id: 'BV1s1', job_id: 'job_s1', title: '短名单视频一', uploader: 'UP1', duration_ms: 61000, cover_url: 'https://example.com/s1.jpg', origin: 'shortlist', primary: true, reason: '最相关' },
    { video_id: 'BV1s2', job_id: 'job_s2', title: '短名单视频二', uploader: 'UP2', duration_ms: 120000, cover_url: '', origin: 'shortlist' },
  ]
  const view = captured.component({
    sessionId: 'sess-shortlist',
    block: {
      call: { argsRaw: JSON.stringify({ command: 'shortlist', video_ids: ['BV1s1', 'BV1s2'] }) },
      content: [{ type: 'text', text: JSON.stringify({ ok: true, state: 'started', started_at: Date.now(), jobs, failed: [{ video_id: 'BV1s3', job_id: null, title: '失败视频', state: 'failed', error_message: 'spawn failed', origin: 'shortlist' }] }) }],
      isError: false,
    },
  })
  if (view !== null) throw new Error('shortlist must not render a chat card')
  const raw = storage.get('video2agent.queue.sess-shortlist')
  if (!raw) throw new Error('shortlist did not create a selected-video table')
  const queue = JSON.parse(raw)
  if (!queue || !Array.isArray(queue.jobs) || queue.jobs.length !== 3) throw new Error('shortlist did not create 3 rows: ' + raw)
  if (queue.jobs[0].origin !== 'shortlist' || queue.jobs[0].title !== '短名单视频一') throw new Error('shortlist row metadata missing: ' + JSON.stringify(queue.jobs[0]))
  if (queue.jobs[0].primary !== true) throw new Error('shortlist primary marker missing')
  if (queue.jobs[2].state !== 'failed' || queue.jobs[2].error_message !== 'spawn failed') throw new Error('failed start row missing: ' + JSON.stringify(queue.jobs[2]))
  const live = context.window.__video2agentLiveState().sessions.find(([sid]) => sid === 'sess-shortlist')
  if (!live || live[1].jobId !== 'job_s1' || live[1].phase !== 'running') throw new Error('shortlist did not publish the first live job: ' + JSON.stringify(live))

  // A `jobs --wait` result is job-shaped too. It must not replace the shortlist
  // row with a direct-link row (which would fall back to the vid_… title).
  const jobsView = captured.component({
    sessionId: 'sess-shortlist',
    block: {
      call: { argsRaw: JSON.stringify({ command: 'jobs', job_id: 'job_s1', wait_ms: 60000 }) },
      content: [{ type: 'text', text: JSON.stringify({ id: 'job_s1', state: 'ready', video_id: 'vid_s1', source: 'https://www.bilibili.com/video/BV1s1' }) }],
      isError: false,
    },
  })
  deep(jobsView)
  const afterJobs = JSON.parse(storage.get('video2agent.queue.sess-shortlist'))
  const sameRow = afterJobs.jobs.find((job) => job.job_id === 'job_s1')
  if (!sameRow || sameRow.title !== '短名单视频一' || sameRow.origin !== 'shortlist') {
    throw new Error('jobs --wait replaced the shortlist row: ' + JSON.stringify(sameRow))
  }
  if (afterJobs.jobs.length !== 3) throw new Error('jobs --wait changed the row count')
}

// The model normally calls ingest with video_ids; that is the shortlist form.
// It must create the same batch table as the legacy shortlist command.
{
  const jobs = [
    { video_id: 'BV1ing1', job_id: 'job_ing1', title: '批量视频一', origin: 'shortlist', primary: true },
    { video_id: 'BV1ing2', job_id: 'job_ing2', title: '', origin: 'shortlist' },
  ]
  const view = captured.component({
    sessionId: 'sess-ingest-batch',
    block: {
      call: { argsRaw: JSON.stringify({ command: 'ingest', video_ids: ['BV1ing1', 'BV1ing2'] }) },
      content: [{ type: 'text', text: JSON.stringify({ ok: true, state: 'started', started_at: Date.now(), jobs }) }],
      isError: false,
    },
  })
  if (view !== null) throw new Error('ingest shortlist must not render a chat card')
  const raw = storage.get('video2agent.queue.sess-ingest-batch')
  if (!raw) throw new Error('ingest with video_ids did not create a batch table')
  const queue = JSON.parse(raw)
  if (!queue.jobs || queue.jobs.length !== 2) throw new Error('ingest batch rows missing: ' + raw)
  if (queue.jobs[0].job_id !== 'job_ing1') throw new Error('ingest batch first row missing')
  const live = context.window.__video2agentLiveState().sessions.find(([sid]) => sid === 'sess-ingest-batch')
  if (!live || live[1].jobId !== 'job_ing1') throw new Error('ingest batch did not publish a live job')
}

// A jobs --wait / job_id poll is command 'ingest' too. Its card must not replace
// the two-row batch table with a one-row direct row (the live table lost row 2
// as soon as the first wait returned).
{
  const before = JSON.parse(storage.get('video2agent.queue.sess-ingest-batch'))
  captured.component({
    sessionId: 'sess-ingest-batch',
    block: {
      call: { argsRaw: JSON.stringify({ command: 'ingest', job_id: 'job_ing1', wait_ms: 60000 }) },
      content: [{ type: 'text', text: JSON.stringify({ ok: true, id: 'job_ing1', state: 'ready', video_id: 'vid_ing1', source: 'https://www.bilibili.com/video/BV1ing1' }) }],
      isError: false,
    },
  })
  const after = JSON.parse(storage.get('video2agent.queue.sess-ingest-batch'))
  if (!after || !Array.isArray(after.jobs) || after.jobs.length !== 2) {
    throw new Error('a jobs --wait card replaced the batch table: ' + JSON.stringify(after))
  }
  if (after.jobs[0].title !== before.jobs[0].title) throw new Error('a jobs --wait card dropped the batch row title')
}

// An HTTP Bilibili cover must be upgraded before the HTTPS-only proxy; a BV id
// must never be used as the row title while resolve is in flight.
{
  const coverThrough = context.window.__video2agentCoverThrough
  const displayTitle = context.window.__video2agentDisplayTitle
  const proxied = coverThrough('http://i0.hdslb.com/bfs/archive/a.jpg')
  if (!proxied.startsWith('/api/video2agent/cover?u=')) throw new Error('Bilibili cover was not proxied: ' + proxied)
  if (!decodeURIComponent(proxied.split('u=')[1]).startsWith('https://i0.hdslb.com/')) throw new Error('HTTP cover was not upgraded: ' + proxied)
  if (displayTitle({ title: 'BV1aaaaaaaa1', video_id: 'BV1aaaaaaaa1' }) !== '视频') throw new Error('BV id leaked into the row title')
  if (displayTitle({ title: '', video_id: 'BV1aaaaaaaa1' }) !== '视频') throw new Error('missing title must render 视频')
  if (displayTitle({ title: '真正的标题' }) !== '真正的标题') throw new Error('real title was replaced')
}

// --- Success reads like a finished build --------------------------------------
// A completed job must state the outcome in words, not just fade: green ring +
// check + "已完成 · 总长 …" (colour is CSS, the text is asserted here).
{
  publish({ sessionId: 'done-a', jobId: 'job_done_a', phase: 'ready', pct: 100, stage: '已完成', duration: '08:32', createdAt: new Date().toISOString() })
  const doneText = deep(statusEntry.component({ session: { id: 'done-a', running: true } }))
  if (!doneText.includes('已完成')) throw new Error('success card missing 已完成')
  if (doneText.includes('总长') || doneText.includes('08:32')) throw new Error('success card still shows a technical duration')
  if (doneText.includes('证据索引可用')) throw new Error('success card still advertises the internal evidence index')
  if (!doneText.includes('data-vp-live-badge')) throw new Error('success card missing the check badge')

  // The card no longer reports where the words came from; the answer does.
  publish({ sessionId: 'done-b', jobId: 'job_done_b', phase: 'ready', pct: 100, stage: '已完成', duration: '08:32', transcript: 'asr', createdAt: new Date().toISOString() })
  const asrText = deep(statusEntry.component({ session: { id: 'done-b', running: true } }))
  if (asrText.includes('语音识别')) throw new Error('card should not show transcript source labels')
}

// --- Direct-link status row backfills from resolve + sidecar -------------------
// A direct ingest has no shortlist candidate: the row's title/cover/uploader come
// from the resolve result cached by URL/video id, and the row must update as soon
// as the job sidecar fills `source`/`video_id` (the first ingest payload only has
// the job id). This path used to stay "视频" until the job was ready — and by then
// the table has already hidden itself.
{
  const active = context.window.__video2agentLiveState().activeSession
  if (!active) throw new Error('no active session for the direct-link case')
  const resolveView = captured.component({
    sessionId: active,
    block: {
      call: { argsRaw: JSON.stringify({ command: 'resolve', url: 'https://www.bilibili.com/video/BV1direct01' }) },
      content: [{ type: 'text', text: JSON.stringify({ ok: true, kind: 'video-link', title: '直链视频标题', uploader: '直链UP', duration: '03:20', duration_ms: 200000, cover_url: 'https://example.com/direct.jpg', url: 'https://www.bilibili.com/video/BV1direct01/', bvid: 'BV1direct01' }) }],
      isError: false,
    },
  })
  deep(resolveView.type(resolveView.props))
  const resolveCache = context.window.__video2agentResolveState()
  if (!resolveCache.some(([, item]) => item && item.bvid === 'BV1direct01')) {
    throw new Error('resolve result was not cached for the direct-link row: ' + JSON.stringify(resolveCache))
  }
  const ingestView = captured.component({
    sessionId: active,
    block: {
      call: { argsRaw: JSON.stringify({ command: 'ingest', source: 'https://www.bilibili.com/video/BV1direct01/' }) },
      // The real detached-ingest payload has only these fields; the URL must come
      // from the call arguments and the title/cover from the resolve cache.
      content: [{ type: 'text', text: JSON.stringify({ ok: true, job_id: 'job_direct', state: 'running' }) }],
      isError: false,
    },
  })
  deep(ingestView.type(ingestView.props))
  const raw = storage.get('video2agent.queue.' + active)
  if (!raw) throw new Error('direct ingest did not create a status row')
  const queue = JSON.parse(raw)
  const row = queue.jobs && queue.jobs[0]
  if (!row || row.job_id !== 'job_direct') throw new Error('direct ingest row is wrong: ' + raw)
  if (row.title !== '直链视频标题') throw new Error('direct row lost the resolve title: ' + row.title)
  if (row.cover_url !== 'https://example.com/direct.jpg') throw new Error('direct row lost the resolve cover')
  if (row.uploader !== '直链UP') throw new Error('direct row lost the resolve uploader')
  if (row.duration_ms !== 200000) throw new Error('direct row lost the resolve duration')
}

// H1: after a real clear, a *fresh* direct ingest must still create its row.
// The detached payload has no created_at, so the "cleared" latch may only
// reject a trustworthy timestamp older than the clear.
{
  const active = context.window.__video2agentLiveState().activeSession
  if (!active) throw new Error('no active session for the cleared-direct case')
  context.window.__video2agentClearQueue(active)
  if (context.window.__video2agentQueueState(active)) {
    throw new Error('the clear did not clear the in-memory queue')
  }
  const view = captured.component({
    sessionId: active,
    block: {
      call: { argsRaw: JSON.stringify({ command: 'ingest', source: 'https://www.bilibili.com/video/BV1direct02/' }) },
      content: [{ type: 'text', text: JSON.stringify({ ok: true, job_id: 'job_direct2', state: 'running' }) }],
      isError: false,
    },
  })
  deep(view.type(view.props))
  const queue = context.window.__video2agentQueueState(active)
  if (!queue || !queue.jobs || queue.jobs[0].job_id !== 'job_direct2') {
    throw new Error('a fresh direct ingest after a clear did not create its row: ' + JSON.stringify(queue))
  }
  context.window.__video2agentClearQueue(active)
}



// A retry of the same video must replace its row, not add a twin: three failed
// downloads came back as six rows for three videos.
{
  const active = context.window.__video2agentLiveState().activeSession
  if (!active) throw new Error('no active session for the retry dedupe case')
  context.window.__video2agentClearQueue(active)
  const first = captured.component({
    sessionId: active,
    block: {
      call: { argsRaw: JSON.stringify({ command: 'ingest', source: 'https://www.bilibili.com/video/BV1retry01/' }) },
      content: [{ type: 'text', text: JSON.stringify({ ok: true, job_id: 'job_retry_a', state: 'running' }) }],
      isError: false,
    },
  })
  deep(first.type(first.props))
  const failed = context.window.__video2agentQueueState(active)
  if (!failed || failed.jobs.length !== 1) throw new Error('the retry case did not start with one row')
  // The row settles as failed; the model retries the same URL with a new job id.
  context.window.__video2agentSetQueue(active, {
    ...failed,
    jobs: [{ ...failed.jobs[0], state: 'failed', error_message: 'E_DOWNLOAD', title: '重试前的标题', cover_url: 'https://i0.hdslb.com/bfs/archive/keep.jpg' }],
  })
  const second = captured.component({
    sessionId: active,
    block: {
      call: { argsRaw: JSON.stringify({ command: 'ingest', source: 'https://www.bilibili.com/video/BV1retry01' }) },
      content: [{ type: 'text', text: JSON.stringify({ ok: true, job_id: 'job_retry_b', state: 'running' }) }],
      isError: false,
    },
  })
  deep(second.type(second.props))
  const after = context.window.__video2agentQueueState(active)
  const ids = (after && after.jobs ? after.jobs : []).map((r) => r.job_id)
  if (ids.length !== 1 || ids[0] !== 'job_retry_b') {
    throw new Error('a retry of the same video added a duplicate row: ' + JSON.stringify(ids))
  }
  const keptRow = after.jobs[0]
  if (keptRow.title !== '重试前的标题') {
    throw new Error('the retry blanked the row title: ' + JSON.stringify(keptRow.title))
  }
  if (!String(keptRow.cover_url || '').includes('keep.jpg')) {
    throw new Error('the retry blanked the row cover: ' + JSON.stringify(keptRow.cover_url))
  }
  context.window.__video2agentClearQueue(active)
}

// A row that carries only a video_id (no source) must still absorb its retry,
// which carries only a source URL for the same BV id.
{
  const active = context.window.__video2agentLiveState().activeSession
  if (!active) throw new Error('no active session for the BV-only dedupe case')
  context.window.__video2agentClearQueue(active)
  context.window.__video2agentSetQueue(active, {
    createdAt: Date.now() - 60000,
    collapsed: false,
    jobs: [{ job_id: 'job_bv_old', video_id: 'BV1bvonly001', title: '只有视频号的行', cover_url: 'https://i0.hdslb.com/bfs/archive/bv.jpg', state: 'failed', error_message: 'E_DOWNLOAD' }],
    evidence: null,
  })
  const retry = captured.component({
    sessionId: active,
    block: {
      call: { argsRaw: JSON.stringify({ command: 'ingest', source: 'https://www.bilibili.com/video/BV1bvonly001/' }) },
      content: [{ type: 'text', text: JSON.stringify({ ok: true, job_id: 'job_bv_new', state: 'running' }) }],
      isError: false,
    },
  })
  deep(retry.type(retry.props))
  const after = context.window.__video2agentQueueState(active)
  const ids = (after && after.jobs ? after.jobs : []).map((r) => r.job_id)
  if (ids.length !== 1 || ids[0] !== 'job_bv_new') {
    throw new Error('a BV-only row did not absorb its retry: ' + JSON.stringify(ids))
  }
  if (after.jobs[0].title !== '只有视频号的行') {
    throw new Error('the BV-only retry blanked the title')
  }
  context.window.__video2agentClearQueue(active)
}

// A historical card remount must not push a live retry back to failed: the old
// job failed, the model retried the same video, and the old card comes back.
{
  const active = context.window.__video2agentLiveState().activeSession
  if (!active) throw new Error('no active session for the stale-card case')
  context.window.__video2agentClearQueue(active)
  context.window.__video2agentSetQueue(active, {
    createdAt: Date.now() - 30000,
    collapsed: false,
    jobs: [{
      job_id: 'job_retry_live',
      video_id: 'BV1stale0001',
      title: '重试中的视频',
      cover_url: 'https://i0.hdslb.com/bfs/archive/live.jpg',
      source: 'https://www.bilibili.com/video/BV1stale0001',
      state: 'running',
    }],
    evidence: null,
  })
  const stale = captured.component({
    sessionId: active,
    block: {
      call: { argsRaw: JSON.stringify({ command: 'ingest', source: 'https://www.bilibili.com/video/BV1stale0001/' }) },
      content: [{ type: 'text', text: JSON.stringify({ ok: false, job_id: 'job_old_failed', state: 'failed' }) }],
      isError: false,
    },
  })
  deep(stale.type(stale.props))
  const after = context.window.__video2agentQueueState(active)
  const row = after && after.jobs ? after.jobs[0] : null
  if (!row || row.job_id !== 'job_retry_live' || row.state !== 'running') {
    throw new Error('a stale failed card overwrote the live retry: ' + JSON.stringify(row))
  }
  context.window.__video2agentClearQueue(active)
}

// Part 1 and part 2 of a multi-P video share a BV id but are different videos:
// the retry dedupe must not merge them.
{
  const active = context.window.__video2agentLiveState().activeSession
  if (!active) throw new Error('no active session for the multi-P case')
  context.window.__video2agentClearQueue(active)
  context.window.__video2agentSetQueue(active, {
    createdAt: Date.now() - 60000,
    collapsed: false,
    jobs: [{ job_id: 'job_p1', video_id: 'BV1parts0001', title: '第 1 P', source: 'https://www.bilibili.com/video/BV1parts0001', state: 'ready' }],
    evidence: null,
  })
  const p2 = captured.component({
    sessionId: active,
    block: {
      call: { argsRaw: JSON.stringify({ command: 'ingest', source: 'https://www.bilibili.com/video/BV1parts0001?p=2' }) },
      content: [{ type: 'text', text: JSON.stringify({ ok: true, job_id: 'job_p2', state: 'running' }) }],
      isError: false,
    },
  })
  deep(p2.type(p2.props))
  const after = context.window.__video2agentQueueState(active)
  const ids = (after && after.jobs ? after.jobs : []).map((r) => r.job_id)
  if (ids.length !== 2 || !ids.includes('job_p1') || !ids.includes('job_p2')) {
    throw new Error('a different part was merged into the first part: ' + JSON.stringify(ids))
  }
  context.window.__video2agentClearQueue(active)
}

// A historical ingest card always reports state "running" on mount; it must not
// demote a completed row of the same video back to running.
{
  const active = context.window.__video2agentLiveState().activeSession
  if (!active) throw new Error('no active session for the finished-row case')
  context.window.__video2agentClearQueue(active)
  context.window.__video2agentSetQueue(active, {
    createdAt: Date.now() - 60000,
    collapsed: false,
    jobs: [{ job_id: 'job_done_row', video_id: 'BV1finished01', title: '已完成行', source: 'https://www.bilibili.com/video/BV1finished01', state: 'ready' }],
    evidence: null,
  })
  const hist = captured.component({
    sessionId: active,
    block: {
      call: { argsRaw: JSON.stringify({ command: 'ingest', source: 'https://www.bilibili.com/video/BV1finished01/' }) },
      content: [{ type: 'text', text: JSON.stringify({ ok: true, job_id: 'job_hist_row', state: 'running' }) }],
      isError: false,
    },
  })
  deep(hist.type(hist.props))
  const after = context.window.__video2agentQueueState(active)
  const row = after && after.jobs ? after.jobs[0] : null
  if (!row || row.job_id !== 'job_done_row' || row.state !== 'ready') {
    throw new Error('a historical card demoted a finished row: ' + JSON.stringify(row))
  }
  context.window.__video2agentClearQueue(active)
}

// A retry must drop the replaced job's runtime flags, or the new row is skipped
// as a lost job while it is running.
{
  const active = context.window.__video2agentLiveState().activeSession
  if (!active) throw new Error('no active session for the lost-flag case')
  context.window.__video2agentClearQueue(active)
  context.window.__video2agentSetQueue(active, {
    createdAt: Date.now() - 60000,
    collapsed: false,
    jobs: [{ job_id: 'job_lost_old', video_id: 'BV1lost00001', title: '丢了任务的行', source: 'https://www.bilibili.com/video/BV1lost00001', state: 'failed', lost: true }],
    evidence: null,
  })
  const retry = captured.component({
    sessionId: active,
    block: {
      call: { argsRaw: JSON.stringify({ command: 'ingest', source: 'https://www.bilibili.com/video/BV1lost00001/' }) },
      content: [{ type: 'text', text: JSON.stringify({ ok: true, job_id: 'job_lost_new', state: 'running' }) }],
      isError: false,
    },
  })
  deep(retry.type(retry.props))
  const after = context.window.__video2agentQueueState(active)
  const row = after && after.jobs ? after.jobs[0] : null
  if (!row || row.job_id !== 'job_lost_new') throw new Error('the retry did not replace the lost row')
  if (row.lost === true) throw new Error('the retry inherited the lost flag: ' + JSON.stringify(row))
  context.window.__video2agentClearQueue(active)
}

// Bilibili BV ids are mixed case: two ids that differ only by case are two
// different videos and must never be merged.
{
  const active = context.window.__video2agentLiveState().activeSession
  if (!active) throw new Error('no active session for the case-sensitivity case')
  context.window.__video2agentClearQueue(active)
  context.window.__video2agentSetQueue(active, {
    createdAt: Date.now() - 60000,
    collapsed: false,
    jobs: [{ job_id: 'job_case_a', video_id: 'BV1caseAA001', title: '大写版', source: 'https://www.bilibili.com/video/BV1caseAA001', state: 'ready' }],
    evidence: null,
  })
  const lower = captured.component({
    sessionId: active,
    block: {
      call: { argsRaw: JSON.stringify({ command: 'ingest', source: 'https://www.bilibili.com/video/BV1caseaa001' }) },
      content: [{ type: 'text', text: JSON.stringify({ ok: true, job_id: 'job_case_b', state: 'running' }) }],
      isError: false,
    },
  })
  deep(lower.type(lower.props))
  const after = context.window.__video2agentQueueState(active)
  const ids = (after && after.jobs ? after.jobs : []).map((r) => r.job_id)
  if (ids.length !== 2) {
    throw new Error('two ids differing only by case were merged: ' + JSON.stringify(ids))
  }
  context.window.__video2agentClearQueue(active)
}

// A genuinely new direct ingest during a running batch must appear as a second
// row (it used to be dropped silently because the batch was still live).
{
  const active = context.window.__video2agentLiveState().activeSession
  if (!active) throw new Error('no active session for the live-batch append case')
  context.window.__video2agentClearQueue(active)
  context.window.__video2agentSetQueue(active, {
    createdAt: Date.now() - 60000,
    collapsed: false,
    jobs: [{ job_id: 'job_batch_live', video_id: 'BV1batchlive1', title: '批量中', state: 'running' }],
    seenJobIds: ['job_batch_live'],
    evidence: null,
  })
  const fresh = captured.component({
    sessionId: active,
    block: {
      call: { argsRaw: JSON.stringify({ command: 'ingest', source: 'https://www.bilibili.com/video/BV1freshnew01/' }) },
      content: [{ type: 'text', text: JSON.stringify({ ok: true, job_id: 'job_fresh_new', state: 'running' }) }],
      isError: false,
    },
  })
  deep(fresh.type(fresh.props))
  const after = context.window.__video2agentQueueState(active)
  const ids = (after && after.jobs ? after.jobs : []).map((r) => r.job_id)
  if (ids.length !== 2 || !ids.includes('job_batch_live') || !ids.includes('job_fresh_new')) {
    throw new Error('a new ingest during a live batch was dropped: ' + JSON.stringify(ids))
  }
  if (!(after.seenJobIds || []).includes('job_fresh_new')) {
    throw new Error('the new job id was not remembered')
  }
  context.window.__video2agentClearQueue(active)
}

// The same card mounting again is history: it must not append a twin row.
{
  const active = context.window.__video2agentLiveState().activeSession
  if (!active) throw new Error('no active session for the replay case')
  context.window.__video2agentClearQueue(active)
  context.window.__video2agentSetQueue(active, {
    createdAt: Date.now() - 60000,
    collapsed: false,
    jobs: [{ job_id: 'job_batch_live2', video_id: 'BV1batchlive2', title: '批量中', state: 'running' }],
    seenJobIds: ['job_batch_live2', 'job_replayed'],
    evidence: null,
  })
  const replay = captured.component({
    sessionId: active,
    block: {
      call: { argsRaw: JSON.stringify({ command: 'ingest', source: 'https://www.bilibili.com/video/BV1replay0001/' }) },
      content: [{ type: 'text', text: JSON.stringify({ ok: true, job_id: 'job_replayed', state: 'running' }) }],
      isError: false,
    },
  })
  deep(replay.type(replay.props))
  const after = context.window.__video2agentQueueState(active)
  const ids = (after && after.jobs ? after.jobs : []).map((r) => r.job_id)
  if (ids.length !== 1 || ids[0] !== 'job_batch_live2') {
    throw new Error('a replayed card appended a ghost row: ' + JSON.stringify(ids))
  }
  context.window.__video2agentClearQueue(active)
}

// The replay guard must also hold on an all-terminal table, where the old code
// appended a second row for the same finished job.
{
  const active = context.window.__video2agentLiveState().activeSession
  if (!active) throw new Error('no active session for the terminal replay case')
  context.window.__video2agentClearQueue(active)
  context.window.__video2agentSetQueue(active, {
    createdAt: Date.now() - 60000,
    collapsed: false,
    jobs: [{ job_id: 'job_done_replay', video_id: 'BV1replay0002', title: '已完成', state: 'ready' }],
    seenJobIds: ['job_done_replay', 'job_replayed_term'],
    evidence: null,
  })
  const replay = captured.component({
    sessionId: active,
    block: {
      call: { argsRaw: JSON.stringify({ command: 'ingest', source: 'https://www.bilibili.com/video/BV1replay0002/' }) },
      content: [{ type: 'text', text: JSON.stringify({ ok: true, job_id: 'job_replayed_term', state: 'running' }) }],
      isError: false,
    },
  })
  deep(replay.type(replay.props))
  const after = context.window.__video2agentQueueState(active)
  const ids = (after && after.jobs ? after.jobs : []).map((r) => r.job_id)
  if (ids.length !== 1 || ids[0] !== 'job_done_replay') {
    throw new Error('a replayed card added a row to a finished table: ' + JSON.stringify(ids))
  }
  context.window.__video2agentClearQueue(active)
}
// A folded, finished table must not permanently block the next direct ingest:
// only a historical (terminal) card is refused, a new running job replaces it
// and expands the table.
{
  const active = context.window.__video2agentLiveState().activeSession
  if (!active) throw new Error('no active session for the folded-table case')
  context.window.__video2agentSetQueue(active, {
    createdAt: Date.now() - 60000,
    collapsed: true,
    jobs: [{ job_id: 'job_old', state: 'ready', title: '旧批次', origin: 'shortlist' }],
    evidence: null,
  })
  const view = captured.component({
    sessionId: active,
    block: {
      call: { argsRaw: JSON.stringify({ command: 'ingest', source: 'https://www.bilibili.com/video/BV1direct03/' }) },
      content: [{ type: 'text', text: JSON.stringify({ ok: true, job_id: 'job_new3', state: 'running' }) }],
      isError: false,
    },
  })
  deep(view.type(view.props))
  // A folded table is user-authored state: a card mount must not rewrite it.
  // (A historical ingest card also reports state "running", so it cannot be
  // told apart from a new one; the job shows as a single card instead.)
  const queue = context.window.__video2agentQueueState(active)
  if (!queue || !Array.isArray(queue.jobs) || queue.jobs[0].job_id !== 'job_old') {
    throw new Error('a card mount rewrote a folded table: ' + JSON.stringify(queue))
  }
  if (queue.collapsed !== true) throw new Error('a folded table was expanded by a card mount')
  // A historical (ready) card must still be refused.
  context.window.__video2agentSetQueue(active, {
    createdAt: Date.now() - 60000,
    collapsed: false,
    jobs: [{ job_id: 'job_keep', state: 'ready', title: '保留', origin: 'shortlist' }],
    evidence: null,
  })
  const hist = captured.component({
    sessionId: active,
    block: {
      call: { argsRaw: JSON.stringify({ command: 'ingest', source: 'https://www.bilibili.com/video/BV1direct04/' }) },
      content: [{ type: 'text', text: JSON.stringify({ ok: true, job_id: 'job_hist', state: 'ready' }) }],
      isError: false,
    },
  })
  deep(hist.type(hist.props))
  const after = context.window.__video2agentQueueState(active)
  if (!after || !after.jobs || after.jobs[0].job_id !== 'job_keep') {
    throw new Error('a historical card replaced a finished table: ' + JSON.stringify(after))
  }
  context.window.__video2agentClearQueue(active)
}


// A terminal row with no job_id (a shortlist row that failed before it started)
// must not count as a live batch: it used to block every later ingest invisibly.
{
  const active = context.window.__video2agentLiveState().activeSession
  if (!active) throw new Error('no active session for the failed-row case')
  context.window.__video2agentSetQueue(active, {
    createdAt: Date.now() - 60000,
    collapsed: false,
    jobs: [{ job_id: null, state: 'failed', title: '启动失败', origin: 'shortlist' }],
    evidence: null,
  })
  const view = captured.component({
    sessionId: active,
    block: {
      call: { argsRaw: JSON.stringify({ command: 'ingest', source: 'https://www.bilibili.com/video/BV1direct05/' }) },
      content: [{ type: 'text', text: JSON.stringify({ ok: true, job_id: 'job_after_failed', state: 'running' }) }],
      isError: false,
    },
  })
  deep(view.type(view.props))
  const queue = context.window.__video2agentQueueState(active)
  const hasNew = !!(queue && Array.isArray(queue.jobs)
    && queue.jobs.some((r) => r && r.job_id === 'job_after_failed'))
  if (!hasNew) {
    throw new Error('a failed row without a job_id blocked the new ingest: ' + JSON.stringify(queue))
  }
  // The failed row stays in the table: the new job joins it, it does not wipe it.
  if (!queue.jobs.some((r) => r && r.state === 'failed' && !r.job_id)) {
    throw new Error('the finished row was dropped when a new ingest joined: ' + JSON.stringify(queue))
  }
  context.window.__video2agentClearQueue(active)
}

// Resolve answers with the canonical URL (trailing slash) while an ingest source
// may omit it. Raw string comparison left the row as a bare "视频" with no cover.
{
  const active = context.window.__video2agentLiveState().activeSession
  if (!active) throw new Error('no active session for the trailing-slash case')
  context.window.__video2agentClearQueue(active)
  const resolveView = captured.component({
    sessionId: active,
    block: {
      call: { argsRaw: JSON.stringify({ command: 'resolve', url: 'https://www.bilibili.com/video/BV1trail01' }) },
      content: [{ type: 'text', text: JSON.stringify({ ok: true, kind: 'video-link', title: '斜杠视频', uploader: '斜杠UP', duration_ms: 120000, cover_url: 'https://example.com/trail.jpg', url: 'https://www.bilibili.com/video/BV1trail01/', bvid: 'BV1trail01' }) }],
      isError: false,
    },
  })
  deep(resolveView.type(resolveView.props))
  const ingestView = captured.component({
    sessionId: active,
    block: {
      call: { argsRaw: JSON.stringify({ command: 'ingest', source: 'https://www.bilibili.com/video/BV1trail01' }) },
      content: [{ type: 'text', text: JSON.stringify({ ok: true, job_id: 'job_trail', state: 'running' }) }],
      isError: false,
    },
  })
  deep(ingestView.type(ingestView.props))
  const queue = context.window.__video2agentQueueState(active)
  const row = queue && queue.jobs && queue.jobs[0]
  if (!row || row.job_id !== 'job_trail') throw new Error('the trailing-slash ingest did not create its row')
  if (row.title !== '斜杠视频') throw new Error('a trailing-slash resolve miss dropped the title: ' + JSON.stringify(row.title))
  if (row.cover_url !== 'https://example.com/trail.jpg') throw new Error('a trailing-slash resolve miss dropped the cover')
  context.window.__video2agentClearQueue(active)
}

// The reported case: a finished 2-video batch must not collapse into one card
// when the model later ingests a third video directly.
{
  const active = context.window.__video2agentLiveState().activeSession
  if (!active) throw new Error('no active session for the batch-then-direct case')
  context.window.__video2agentSetQueue(active, {
    createdAt: Date.now() - 60000,
    collapsed: false,
    jobs: [
      { job_id: 'job_b1', state: 'ready', title: '批量一', origin: 'shortlist' },
      { job_id: 'job_b2', state: 'ready', title: '批量二', origin: 'shortlist' },
    ],
    evidence: null,
  })
  const view = captured.component({
    sessionId: active,
    block: {
      call: { argsRaw: JSON.stringify({ command: 'ingest', source: 'https://www.bilibili.com/video/BV1third01/' }) },
      content: [{ type: 'text', text: JSON.stringify({ ok: true, job_id: 'job_third', state: 'running' }) }],
      isError: false,
    },
  })
  deep(view.type(view.props))
  const queue = context.window.__video2agentQueueState(active)
  const ids = (queue && queue.jobs ? queue.jobs : []).map((r) => r.job_id)
  if (ids.length !== 3 || !ids.includes('job_b1') || !ids.includes('job_b2') || !ids.includes('job_third')) {
    throw new Error('a finished batch collapsed when a direct ingest joined: ' + JSON.stringify(ids))
  }
  context.window.__video2agentClearQueue(active)
}
// Regression guards for fixes that are hard to exercise in the vm shim: the
// queue stop control, patch-only settings POST, POST campaign advance, bounded
// watchdog polling, worker reset, and body-abort handling.
const clientSource = fs.readFileSync(clientPath, 'utf8')
const indexSource = fs.readFileSync(path.join(root, 'packages/dsh-video2agent/index.js'), 'utf8')
for (const [label, source, pattern] of [
  ['queue stop button', clientSource, /data-vp-queue-cancel/],
  ['queue cancel call', clientSource, /onClick: \(\) => cancel\(job\)/],
  ['settings patch POST', clientSource, /JSON\.stringify\(patch\)/],
  ['campaign POST poll', clientSource, /campaign\?id=' \+ encodeURIComponent\(campaignId\), \{\s*method: 'POST'/],
  ['watchdog overview=0', clientSource, /overview=0/],
  ['watchdog parallel', clientSource, /Promise\.all\(watchdogEntries\(\)\.map/],
  ['single surface', clientSource, /if \(queueJobs\.length && !foldedForeignJob\) return null/],
  ['queue clear latch', clientSource, /queueClearedKey/],
  ['cover source backfill', clientSource, /\(\/\^https\?:\/i\.test\(String\(job\.source/],
  ['evidence attach budget', indexSource, /attachedImagePaths\.length/],
  ['dense count alias', indexSource, /Number\(args\.count\) > 1/],
  ['batch moments no paths', indexSource, /delete copy\.images/],
  ['shortlist cache prune', indexSource, /pruneShortlistStarts\(\)/],
  ['worker reset', indexSource, /_workerFail\(worker, 'worker stdin is closed'\)/],
  ['body abort', indexSource, /req\.on\('aborted'/],
  ['guardRead all methods', indexSource, /if \(!guardRead\(req, res\)\) return/],
  ['tool session ownership', indexSource, /exec\?\.agent\?\.session\?\.id/],
  ['status session write', indexSource, /}, sessionId\)/],
]) {
  if (!pattern.test(source)) throw new Error('missing regression guard: ' + label)
}

console.log('card ok: composer-preview, link, douyin-link-label, discovery, inline-job, evidence, search, live-window, error-window, same-video-session, dismiss-persistence, settings, per-session-live, theme-colour, stale-watchdog, turn-end-close, success-state, direct-link-row, cleared-direct-row, folded-preserved, failed-row-unblocked, trailing-slash-resolve, batch-kept-on-direct, retry-dedupe, bv-only-dedupe, stale-card-keeps-retry, parts-stay-separate, case-sensitive-ids, finished-row-not-demoted, retry-clears-lost, live-batch-append, replayed-card-no-row, terminal-replay-no-row, history-blocked, no-picker, host-shortlist-table, jobs-row-guard')

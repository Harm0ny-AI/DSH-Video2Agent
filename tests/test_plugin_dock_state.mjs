// Dock-state harness: renders the real dock components with a small hook runtime.
//
// The card harness (test_plugin_card.mjs) stubs React with no-op state, so it can
// only render one snapshot. These regressions need click -> re-render -> timer:
//   1. 清除 on a completed batch revealed the same completion as a LiveStrip card
//      for the rest of its 8s hold (the table vanished, the card came back);
//   2. a canceled batch was labelled 已完成 in the table header and the collapsed
//      pill said "已完成" next to a 已取消 row;
//   3. a failed settings save was cleared 1.2s later by the previous save's timer,
//      so the page said 自动保存 while the server still had the old value;
//   4. the cloud capsule was clickable without a key (AGENTS says it is disabled);
//   5. two controls changed inside the 300ms autosave window posted only the last
//      key, so the first change looked saved and reverted on reload.
//
// Run: node tests/test_plugin_dock_state.mjs
import fs from 'node:fs'
import path from 'node:path'
import vm from 'node:vm'
import { fileURLToPath } from 'node:url'

const root = path.resolve(path.dirname(fileURLToPath(import.meta.url)), '..')
const clientPath = path.join(root, 'packages/dsh-video2agent/client.js')

// ---- deterministic environment ------------------------------------------------
const storage = new Map()
const timers = new Map()
let timerSeq = 0
const clock = { t: 1_700_000_000_000 }
function schedule(fn, ms, repeat) {
  const id = ++timerSeq
  const delay = Math.max(0, Number(ms) || 0)
  timers.set(id, { fn, at: clock.t + delay, repeat: repeat ? Math.max(1, delay) : 0 })
  return id
}
let fetchImpl = async () => ({ ok: true, status: 200, json: async () => ({}) })
// The plugin injects one <style>; the harness keeps its text so layout rules
// like the batch table's height cap cannot silently disappear.
let capturedCss = ''

const context = {
  window: { __VIDEO2AGENT_DEBUG__: true, __ModuleLoader__: { load: (m) => { context.__loaded = m } } },
  localStorage: {
    getItem: (k) => (storage.has(k) ? storage.get(k) : null),
    setItem: (k, v) => { storage.set(k, String(v)) },
    removeItem: (k) => { storage.delete(k) },
  },
  document: {
    createElement: () => ({
      setAttribute() {},
      remove() {},
      set textContent(value) { capturedCss += String(value) },
      get textContent() { return capturedCss },
    }),
    head: { appendChild() {} },
    hidden: false,
    visibilityState: 'visible',
    addEventListener() {},
    removeEventListener() {},
  },
  console,
  setTimeout: (fn, ms) => schedule(fn, ms, false),
  clearTimeout: (id) => { timers.delete(id) },
  setInterval: (fn, ms) => schedule(fn, ms, true),
  clearInterval: (id) => { timers.delete(id) },
  fetch: (url, opts) => fetchImpl(String(url), opts),
  navigator: { clipboard: { writeText: async () => {} } },
  Date: class extends Date {
    constructor(...args) { if (args.length) super(...args); else super(clock.t) }
    static now() { return clock.t }
  },
}
vm.createContext(context)
vm.runInContext(fs.readFileSync(clientPath, 'utf8'), context, { filename: clientPath })
const loaded = context.__loaded
if (!loaded) throw new Error('module loader was not called')

// ---- minimal hooks ------------------------------------------------------------
let current = null
const instances = []
const React = {
  createElement: (type, props, ...children) => ({ type, props: props || {}, children }),
  useState(init) {
    const inst = current
    const i = inst.hookIndex++
    if (!(i in inst.hooks)) inst.hooks[i] = typeof init === 'function' ? init() : init
    const set = (value) => {
      const next = typeof value === 'function' ? value(inst.hooks[i]) : value
      if (Object.is(next, inst.hooks[i])) return
      inst.hooks[i] = next
      inst.dirty = true
    }
    return [inst.hooks[i], set]
  },
  useEffect(fn, deps) {
    const inst = current
    inst.effects.push({ i: inst.hookIndex++, fn, deps })
  },
  useRef(init) {
    const inst = current
    const i = inst.hookIndex++
    if (!(i in inst.refs)) inst.refs[i] = { current: init }
    return inst.refs[i]
  },
}
const mod = loaded.factory((name) => {
  if (name === 'react') return React
  throw new Error('unexpected require: ' + name)
})
const sameDeps = (a, b) => Array.isArray(a) && Array.isArray(b)
  && a.length === b.length && a.every((v, i) => Object.is(v, b[i]))

function renderInstance(inst) {
  const previous = current
  current = inst
  inst.hookIndex = 0
  inst.effects = []
  inst.tree = inst.component(inst.props)
  current = previous
  inst.dirty = false
  const pending = inst.effects
  inst.effects = []
  for (const effect of pending) {
    const prev = inst.effectState[effect.i]
    if (prev && sameDeps(prev.deps, effect.deps)) continue
    if (prev && typeof prev.cleanup === 'function') prev.cleanup()
    const cleanup = effect.fn()
    inst.effectState[effect.i] = { deps: effect.deps, cleanup: typeof cleanup === 'function' ? cleanup : null }
  }
}
function mount(component, props) {
  const inst = {
    component, props, hooks: {}, refs: {}, effects: [], effectState: {},
    hookIndex: 0, dirty: false, mounted: true, tree: null,
  }
  instances.push(inst)
  renderInstance(inst)
  return inst
}
async function flush(rounds = 40) {
  for (let round = 0; round < rounds; round += 1) {
    // Real macrotask: every pending microtask (fetch -> json -> tick) settles
    // before the next render. Three awaits were not enough and the assertion saw
    // the pre-tick tree while the queue had already advanced.
    await new Promise((resolve) => setImmediate(resolve))
    const dirty = instances.filter((inst) => inst.mounted && inst.dirty)
    if (!dirty.length) return
    for (const inst of dirty) inst.dirty = false
    for (const inst of dirty) renderInstance(inst)
  }
}
async function advance(ms) {
  const target = clock.t + ms
  for (;;) {
    const due = [...timers.entries()].filter(([, timer]) => timer.at <= target)
      .sort((a, b) => a[1].at - b[1].at || a[0] - b[0])[0]
    if (!due) break
    const [id, timer] = due
    clock.t = timer.at
    if (timer.repeat) timer.at = clock.t + timer.repeat
    else timers.delete(id)
    timer.fn()
    await flush()
  }
  clock.t = target
  await flush()
}
function unmount(inst) {
  inst.mounted = false
  for (const state of Object.values(inst.effectState)) {
    if (state && typeof state.cleanup === 'function') state.cleanup()
  }
}

// ---- tree helpers -------------------------------------------------------------
function findByAttr(node, attr) {
  if (!node) return null
  if (Array.isArray(node)) {
    for (const child of node) {
      const hit = findByAttr(child, attr)
      if (hit) return hit
    }
    return null
  }
  if (typeof node !== 'object') return null
  if (node.props && node.props[attr] !== undefined) return node
  const nested = findByAttr(node.children || [], attr)
  if (nested) return nested
  if (typeof node.type === 'function') return findByAttr(node.type(node.props), attr)
  return null
}
function collectByAttr(node, attr) {
  if (!node) return []
  if (Array.isArray(node)) return node.flatMap((child) => collectByAttr(child, attr))
  if (typeof node !== 'object') return []
  if (typeof node.type === 'function') return collectByAttr(node.type(node.props), attr)
  const self = node.props && node.props[attr] !== undefined ? [node] : []
  return self.concat(collectByAttr(node.children || [], attr))
}
function findByChildText(node, needle) {
  if (!node) return null
  if (Array.isArray(node)) {
    for (const child of node) {
      const hit = findByChildText(child, needle)
      if (hit) return hit
    }
    return null
  }
  if (typeof node !== 'object') return null
  if (node.type === 'button' && (node.children || []).some((child) => child === needle)) return node
  const nested = findByChildText(node.children || [], needle)
  if (nested) return nested
  return null
}
function textOf(node) {
  if (node === null || node === undefined || node === false) return ''
  if (Array.isArray(node)) return node.map(textOf).join('')
  if (typeof node !== 'object') return String(node)
  if (typeof node.type === 'function') return textOf(node.type(node.props))
  return (node.children || []).map(textOf).join('')
}
function expect(condition, message) {
  if (!condition) throw new Error(message)
}

// ---- register the plugin ------------------------------------------------------
const slots = {
  inject: (name, fn) => fn(),
  register: (spec, component) => {
    context.__slots ||= {}
    context.__slots[spec.name] ||= []
    context.__slots[spec.name].push({ spec, component })
    return () => {}
  },
}
mod.apply({ get: (name) => (name === 'slots' ? slots : undefined), effect: () => {} })
const dock = Object.fromEntries((context.__slots['conversation.input.dock'] || []).map((e) => [e.spec.id, e.component]))
const table = dock['video2agent-queue']
const strip = dock['video2agent-status']
const searchStatus = dock['video2agent-search']
const settingsPage = (context.__slots['settings.section'] || []).find((e) => e.spec.id === 'video2agent')?.component
for (const [name, value] of Object.entries({ table, strip, searchStatus, settingsPage })) {
  if (!value) throw new Error('dock component missing: ' + name)
}
const debug = context.window
const jobPayload = (jobId, state) => ({
  ok: true,
  status: 200,
  json: async () => ({
    ok: true,
    job: {
      id: jobId,
      state,
      stage: state === 'running' ? 'ocr' : 'done',
      progress: state === 'running' ? 0.4 : 1,
      video_id: 'BV1xx411c7mD',
      source: 'https://www.bilibili.com/video/BV1xx411c7mD',
      created_at: new Date().toISOString(),
      duration_ms: 60000,
      position_ms: 60000,
    },
    overview: null,
  }),
})

// One job that starts running, then settles in the terminal state on the next poll.
async function runBatch(sessionId, jobId, terminalState) {
  debug.__video2agentPublishBatch(sessionId, [{
    job_id: jobId, video_id: 'BV1xx411c7mD', title: '测试视频', cover_url: '',
    uploader: 'up', duration_ms: 60000, state: 'running',
  }])
  let jobCalls = 0
  fetchImpl = async (url) => {
    if (url.includes('/api/video2agent/job?')) {
      jobCalls += 1
      return jobPayload(jobId, jobCalls === 1 ? 'running' : terminalState)
    }
    if (url.includes('/api/video2agent/resolve')) {
      return { ok: true, status: 200, json: async () => ({ ok: true, title: '测试视频', cover_url: '', uploader: 'up', duration_ms: 60000 }) }
    }
    return { ok: true, status: 200, json: async () => ({ ok: true }) }
  }
  const inst = mount(table, { session: { id: sessionId, running: true } })
  await flush()
  await advance(2600)
  return inst
}

// A slow first /job read must not be joined by the 2.5s interval. Both reads
// spawn their own Python probe, and the older answer can land after the newer
// one. The initial read used to bypass the interval's ticking guard.
{
  const sid = 'slow-first-tick'
  let calls = 0
  let release = null
  const pending = new Promise((resolve) => { release = resolve })
  debug.__video2agentSetQueue(sid, {
    createdAt: Date.now(),
    collapsed: false,
    jobs: [{ job_id: 'job_slowtick', video_id: 'BV1slowtick', title: '慢任务', state: 'running' }],
    evidence: null,
  })
  fetchImpl = async (url) => {
    if (url.includes('/api/video2agent/queue')) return { ok: true, status: 200, json: async () => ({ ok: true }) }
    if (url.includes('/api/video2agent/job?')) {
      calls += 1
      await pending
      return jobPayload('job_slowtick', 'running')
    }
    return { ok: true, status: 200, json: async () => ({ ok: true }) }
  }
  const inst = mount(table, { session: { id: sid, running: true } })
  await flush()
  await advance(2700)
  expect(calls === 1, 'a slow first job read was duplicated by the interval: ' + calls)
  release()
  await flush()
  await advance(2700)
  expect(calls === 2, 'the next job read did not follow the released one: ' + calls)
  unmount(inst)
  debug.__video2agentClearQueue(sid)
}

// Opening an old chat restores the original "running" rows. Neither a failed
// status read nor an old Host snapshot proves that any work is still active.
{
  for (const fromHost of [false, true]) {
    const sid = 'restored-unverified-' + fromHost
    const createdAt = clock.t - 16 * 86400000
    const jobs = [{ job_id: 'job_stale_' + fromHost, title: '历史视频', state: 'running' }]
    if (!fromHost) storage.set('video2agent.queue.' + sid, JSON.stringify({ createdAt, jobs }))
    fetchImpl = async (url) => {
      if (url.includes('/api/video2agent/queue') && fromHost) {
        return { ok: true, status: 200, json: async () => ({ ok: true, queue: { started_at: createdAt, jobs } }) }
      }
      if (url.includes('/api/video2agent/job?')) return { ok: false, status: fromHost ? 404 : 503 }
      return { ok: true, status: 200, json: async () => ({ ok: true }) }
    }
    const inst = mount(table, { session: { id: sid, running: false } })
    await flush()
    expect(textOf(inst.tree) === '', 'an unverified historical queue rendered: ' + textOf(inst.tree))
    expect(!debug.__video2agentLiveState().sessions.some(([id]) => id === sid),
      'the historical Host snapshot published an unverified live card')
    await advance(5100)
    expect(textOf(inst.tree) === '', 'an unverified historical queue returned after retries')
    unmount(inst)
    debug.__video2agentClearQueue(sid)
  }
}

// A transient failure can recover. Keep an unverified neighbour hidden while
// the independently confirmed background job stays visible.
{
  const sid = 'restored-verified-job'
  const current = { job_id: 'job_verified', title: '后台在跑', state: 'running' }
  const unknown = { job_id: 'job_not_verified', title: '未核实的旧视频', state: 'running' }
  storage.set('video2agent.queue.' + sid, JSON.stringify({ createdAt: clock.t - 3600000, jobs: [unknown, current] }))
  let verified = false
  fetchImpl = async (url) => {
    if (url.includes('/api/video2agent/job?')) {
      if (verified && url.includes('id=job_verified&')) return jobPayload(current.job_id, 'running')
      return { ok: false, status: 503 }
    }
    return { ok: true, status: 200, json: async () => ({ ok: true }) }
  }
  const inst = mount(table, { session: { id: sid, running: false } })
  await flush()
  expect(textOf(inst.tree) === '', 'the queue became visible before verification')
  verified = true
  await advance(2600)
  expect(textOf(inst.tree).includes('后台在跑'), 'a verified background job did not appear')
  expect(!textOf(inst.tree).includes('未核实的旧视频'), 'an unrelated, unverified row appeared')
  collectByAttr(inst.tree, 'data-vp-queue-collapse')[0].props.onClick()
  await flush()
  expect(collectByAttr(inst.tree, 'data-vp-queue-pill-job')[0].props['data-vp-queue-pill-job'] === current.job_id,
    'the collapsed table showed the unverified job')
  unmount(inst)
  debug.__video2agentClearQueue(sid)
}

// A narrower, newer client row must not hide the batch the Host started. This
// was the reported "only one card for five minutes" while ten videos ran.
{
  const sid = 'merge-host-batch'
  debug.__video2agentSetQueue(sid, {
    createdAt: Date.now(),
    collapsed: false,
    jobs: [{ job_id: 'job_direct', video_id: 'BV1direct', title: '直链视频', state: 'running' }],
    evidence: null,
  })
  fetchImpl = async (url) => {
    if (url.includes('/api/video2agent/queue')) {
      return {
        ok: true,
        status: 200,
        json: async () => ({
          ok: true,
          queue: {
            session_id: sid,
            started_at: Date.now() - 60000,
            jobs: [
              { job_id: 'job_batch1', video_id: 'BV1batch01', title: '批量一', state: 'running' },
              { job_id: 'job_batch2', video_id: 'BV1batch02', title: '批量二', state: 'queued' },
            ],
          },
        }),
      }
    }
    if (url.includes('/api/video2agent/job?')) return jobPayload('job_batch1', 'running')
    return { ok: true, status: 200, json: async () => ({ ok: true }) }
  }
  const inst = mount(table, { session: { id: sid, running: true } })
  await flush()
  const merged = debug.__video2agentQueueState(sid)
  const ids = ((merged && merged.jobs) || []).map((row) => row.job_id)
  expect(ids.includes('job_direct'), 'the newer direct row was dropped: ' + JSON.stringify(ids))
  expect(ids.includes('job_batch1') && ids.includes('job_batch2'),
    'the Host batch was hidden by a newer single row: ' + JSON.stringify(ids))
  expect(textOf(inst.tree).includes('批量一'), 'the merged batch row did not render')
  unmount(inst)
  debug.__video2agentClearQueue(sid)
}

// A finished batch must not come back over a later single row: that is the
// "批量完成后自动消除，然后又出现批量" report.
{
  const sid = 'no-resurrect-batch'
  debug.__video2agentSetQueue(sid, {
    createdAt: Date.now(),
    collapsed: false,
    jobs: [{ job_id: 'job_later_single', video_id: 'BV1later', title: '后面补的单条', state: 'running' }],
    evidence: null,
  })
  fetchImpl = async (url) => {
    if (url.includes('/api/video2agent/queue')) {
      return {
        ok: true,
        status: 200,
        json: async () => ({
          ok: true,
          queue: {
            session_id: sid,
            started_at: Date.now() - 600000,
            jobs: [
              { job_id: 'job_old_batch1', video_id: 'BV1old01', title: '旧批次一', state: 'ready' },
              { job_id: 'job_old_batch2', video_id: 'BV1old02', title: '旧批次二', state: 'ready' },
            ],
          },
        }),
      }
    }
    if (url.includes('/api/video2agent/job?')) return jobPayload('job_later_single', 'running')
    return { ok: true, status: 200, json: async () => ({ ok: true }) }
  }
  const inst = mount(table, { session: { id: sid, running: true } })
  await flush()
  const after = debug.__video2agentQueueState(sid)
  const ids = ((after && after.jobs) || []).map((row) => row.job_id)
  expect(ids.length === 1 && ids[0] === 'job_later_single',
    'a finished batch was resurrected over a later single row: ' + JSON.stringify(ids))
  expect(!textOf(inst.tree).includes('旧批次一'), 'the old batch row is on screen again')
  unmount(inst)
  debug.__video2agentClearQueue(sid)
}

// A failed row created from a profile URL must show the failure, not a raw
// sec_uid title or the old "未完成" label.
{
  const sid = 'failed-profile-row'
  const sec = 'MS4wLjABAAAAWGxxWTIOzTE_0LszlZpM-7wDQtO4WuQ_HWKzO5sXooMCc4_KomVvNrB6V1EOE5-N'
  debug.__video2agentSetQueue(sid, {
    createdAt: Date.now(),
    collapsed: false,
    jobs: [
      { job_id: 'job_bad_profile', video_id: sec, title: sec, source: 'https://www.douyin.com/user/' + sec, state: 'failed' },
      { job_id: 'job_keep_running', video_id: 'BV1keeprun', title: '正在跑', state: 'running' },
    ],
    evidence: null,
  })
  fetchImpl = async (url) => {
    if (url.includes('/api/video2agent/queue')) {
      return {
        ok: true,
        status: 200,
        json: async () => ({
          ok: true,
          queue: {
            session_id: sid,
            started_at: Date.now(),
            jobs: [
              { job_id: 'job_bad_profile', video_id: sec, title: sec, source: 'https://www.douyin.com/user/' + sec, state: 'failed' },
              { job_id: 'job_keep_running', video_id: 'BV1keeprun', title: '正在跑', state: 'running' },
            ],
          },
        }),
      }
    }
    if (url.includes('/api/video2agent/job?')) {
      const id = new URL(String(url), 'http://localhost').searchParams.get('id')
      if (id === 'job_bad_profile') {
        return { ok: true, status: 200, json: async () => ({ ok: true, job: { id, state: 'failed', error_message: '这是抖音用户主页，不是视频', video_id: null } }) }
      }
      return jobPayload(id, 'running')
    }
    return { ok: true, status: 200, json: async () => ({ ok: true }) }
  }
  const inst = mount(table, { session: { id: sid, running: true } })
  await flush()
  await advance(2600)
  const rowText = textOf(inst.tree)
  expect(rowText.includes('失败'), 'failed row should say 失败: ' + rowText)
  expect(rowText.includes('这是抖音用户主页'), 'failed row should show the error: ' + rowText)
  expect(!rowText.includes('未完成'), 'failed row still says 未完成: ' + rowText)
  expect(!rowText.includes(sec), 'failed row still exposes the raw sec_uid: ' + rowText)
  unmount(inst)
  debug.__video2agentClearQueue(sid)
}

// The progress ring must mark the row that is actually processing. It used to
// be the first non-terminal row, so a queued row above the running one took the
// ring while the table still said 正在处理 on another row (reported 2026-11-15).
{
  const sid = 'ring-on-running'
  debug.__video2agentSetQueue(sid, {
    createdAt: Date.now(),
    collapsed: false,
    jobs: [
      { job_id: 'job_ring_done', video_id: 'BV1ring01', title: '已完成视频', cover_url: 'https://i0.hdslb.com/bfs/archive/a.jpg', state: 'ready' },
      { job_id: 'job_ring_queued', video_id: 'BV1ring02', title: '排队视频', cover_url: 'https://i0.hdslb.com/bfs/archive/b.jpg', state: 'queued' },
      { job_id: 'job_ring_run', video_id: 'BV1ring03', title: '正在跑的视频', cover_url: 'https://i0.hdslb.com/bfs/archive/c.jpg', state: 'running' },
    ],
    evidence: null,
  })
  fetchImpl = async (url) => {
    if (url.includes('/api/video2agent/job?')) {
      const id = new URL(String(url), 'http://localhost').searchParams.get('id')
      return jobPayload(id, id === 'job_ring_run' ? 'running' : 'queued')
    }
    return { ok: true, status: 200, json: async () => ({ ok: true }) }
  }
  const inst = mount(table, { session: { id: sid, running: true } })
  await flush()
  const rows = collectByAttr(inst.tree, 'data-vp-queue-row')
  expect(rows.length === 3, 'expected three rows, got ' + rows.length)
  const rowFor = (needle) => rows.find((row) => textOf(row).includes(needle))
  const runningRow = rowFor('正在跑的视频')
  const queuedRow = rowFor('排队视频')
  expect(runningRow, 'the running row did not render')
  expect(queuedRow, 'the queued row did not render')
  expect(findByAttr(runningRow, 'data-vp-queue-ring-wrap'), 'the ring is not on the running row')
  expect(!findByAttr(queuedRow, 'data-vp-queue-ring-wrap'), 'the ring sits on the queued row')
  unmount(inst)
  debug.__video2agentClearQueue(sid)
}
// A collapsed pill must show the row that is still working, not the primary:
// after a dedupe the primary is already finished while the last row runs.
{
  const sid = 'pill-active-row'
  debug.__video2agentSetQueue(sid, {
    createdAt: Date.now(),
    collapsed: true,
    jobs: [
      { job_id: 'job_pill_primary', video_id: 'BV1pillp', title: '主视频', cover_url: 'https://i0.hdslb.com/bfs/archive/primary.jpg', state: 'ready', primary: true },
      { job_id: 'job_pill_active', video_id: 'BV1pilla', title: '还在跑的视频', cover_url: 'https://i0.hdslb.com/bfs/archive/active.jpg', state: 'running' },
    ],
    evidence: null,
  })
  fetchImpl = async (url) => {
    if (url.includes('/api/video2agent/queue')) {
      return {
        ok: true,
        status: 200,
        json: async () => ({
          ok: true,
          queue: {
            session_id: sid,
            started_at: Date.now() - 1000,
            jobs: [
              { job_id: 'job_pill_primary', video_id: 'BV1pillp', title: '主视频', cover_url: 'https://i0.hdslb.com/bfs/archive/primary.jpg', state: 'ready', primary: true },
              { job_id: 'job_pill_active', video_id: 'BV1pilla', title: '还在跑的视频', cover_url: 'https://i0.hdslb.com/bfs/archive/active.jpg', state: 'running' },
            ],
          },
        }),
      }
    }
    if (url.includes('/api/video2agent/job?')) {
      const id = decodeURIComponent((url.split('id=')[1] || '').split('&')[0])
      return jobPayload(id, id === 'job_pill_primary' ? 'ready' : 'running')
    }
    return { ok: true, status: 200, json: async () => ({ ok: true }) }
  }
  const inst = mount(table, { session: { id: sid, running: true } })
  await flush()
  const pill = findByAttr(inst.tree, 'data-vp-queue-pill-job')
  expect(pill, 'the collapsed pill does not say which row it shows')
  expect(String(pill.props['data-vp-queue-pill-job']) === 'job_pill_active',
    'the pill shows a finished row instead of the running one: ' + String(pill.props['data-vp-queue-pill-job']))
  unmount(inst)
  debug.__video2agentClearQueue(sid)
}

// A long batch must not grow past the window: the list is capped and scrolls,
// so the first rows stay reachable and the table never reaches the top.
expect(capturedCss.includes('[data-vp-queue-rows]'), 'the queue styles are missing (len=' + capturedCss.length + ')')
expect(/\[data-vp-queue-rows\]\([^)]*\)?[^{]*\{[^}]*max-height/.test(capturedCss) || /\[data-vp-queue-rows\]\{[^}]*max-height/.test(capturedCss),
  'the batch list has no height cap')
expect(/\[data-vp-queue-rows\]\{[^}]*overflow-y:auto/.test(capturedCss),
  'the batch list must scroll inside its cap')
// Below 620px the row grid shrinks to an 88px cover column: the active cover
// (96px) and its 108px ring used to overhang that column and clip the title.
const narrowMedia = capturedCss.split('@media (max-width:620px)')[1] || ''
expect(narrowMedia.includes('[data-vp-queue-cover],[data-vp-queue-cover][data-active="on"]{width:80px;height:45px;}'),
  'the narrow row still renders the 96px active cover')
expect(narrowMedia.includes('[data-vp-queue-ring-wrap],[data-vp-queue-ring]{width:88px;height:54px;}'),
  'the narrow row does not shrink the progress ring to its column')
// 1. Clearing a completed batch must not bring the completion back as a card.
{
  const inst = await runBatch('clear-a', 'job_a', 'ready')
  const before = textOf(inst.tree)
  expect(before.includes('已完成'), 'completed table missing 已完成: ' + before)
  const clearButton = findByAttr(inst.tree, 'data-vp-queue-clear')
  expect(clearButton, 'completed table has no 清除 button')
  clearButton.props.onClick()
  await flush()
  expect(debug.__video2agentQueueState('clear-a') === null, 'clear did not remove the queue')
  expect(textOf(inst.tree) === '', 'cleared table still renders: ' + textOf(inst.tree))
  const live = mount(strip, { session: { id: 'clear-a', running: false } })
  await flush()
  expect(textOf(live.tree) === '', 'clearing the completed table revived a live card: ' + textOf(live.tree))
  unmount(live)
  unmount(inst)
}

// 2. A canceled batch is not a completed one, in the header or the collapsed pill.
{
  const inst = await runBatch('clear-b', 'job_b', 'canceled')
  const header = textOf(inst.tree)
  expect(header.includes('已取消'), 'canceled batch header does not say 已取消: ' + header)
  expect(!header.includes('已完成'), 'canceled batch still claims 已完成: ' + header)
  const collapse = findByAttr(inst.tree, 'data-vp-queue-collapse')
  expect(collapse, 'table has no 收起 button')
  collapse.props.onClick()
  await flush()
  const pill = textOf(inst.tree)
  expect(pill.includes('已取消'), 'collapsed pill does not say 已取消: ' + pill)
  expect(!pill.includes('已完成'), 'collapsed pill still claims 已完成: ' + pill)
  unmount(inst)
}

// 3. The 8s auto-clear also leaves no live card behind.
{
  const inst = await runBatch('clear-c', 'job_c', 'ready')
  const live = mount(strip, { session: { id: 'clear-c', running: false } })
  await flush()
  await advance(8200)
  expect(debug.__video2agentQueueState('clear-c') === null, 'auto-clear did not remove the queue')
  expect(textOf(live.tree) === '', 'auto-clear revived a live card: ' + textOf(live.tree))
  unmount(live)
  unmount(inst)
}

// 3b. A new batch after a clear must appear again: clearBatch hides this batch's
// card, it must not latch the surface for the rest of the turn.
{
  const inst = await runBatch('clear-d', 'job_d', 'ready')
  const clearButton = findByAttr(inst.tree, 'data-vp-queue-clear')
  expect(clearButton, 'completed table has no 清除 button (second batch)')
  clearButton.props.onClick()
  await flush()
  await advance(1200)
  debug.__video2agentPublishBatch('clear-d', [{
    job_id: 'job_e', video_id: 'BV1xx411c7mD', title: '新批次视频', cover_url: '',
    uploader: 'up', duration_ms: 60000, state: 'running',
  }])
  fetchImpl = async (url) => {
    if (url.includes('/api/video2agent/job?')) return jobPayload('job_e', 'running')
    if (url.includes('/api/video2agent/resolve')) {
      return { ok: true, status: 200, json: async () => ({ ok: true, title: '新批次视频', cover_url: '', uploader: 'up', duration_ms: 60000 }) }
    }
    return { ok: true, status: 200, json: async () => ({ ok: true }) }
  }
  await flush()
  const tableText = textOf(inst.tree)
  expect(tableText.includes('新批次视频'), 'a new batch after clear did not render: ' + tableText)
  // The table owns the surface while a row exists; what matters is that the new
  // publish cleared the hidden latch, so a later single-job fallback can show.
  const entry = (debug.__video2agentLiveState().sessions.find(([id]) => id === 'clear-d') || [])[1]
  expect(entry, 'new batch did not publish a live entry')
  expect(entry.hidden !== true, 'the clear latch survived into the next batch')
  unmount(inst)
}

// A find-only turn must not leave the "正在筛选" card behind after the turn,
// and the same status must not resurrect in the next turn.
{
  let statusAt = clock.t
  let clears = 0
  fetchImpl = async (url) => {
    if (url.includes('/api/video2agent/discovery/clear')) {
      clears += 1
      return { ok: true, status: 200, json: async () => ({ ok: true, cleared: true }) }
    }
    if (url.includes('/api/video2agent/discovery/status')) {
      return {
        ok: true,
        status: 200,
        json: async () => ({
          ok: true,
          status: {
            phase: 'curating',
            query: '显卡',
            at: statusAt,
            candidates: [{ video_id: 'BV1search1', title: '候选一', uploader: 'up', duration_ms: 60000 }],
          },
        }),
      }
    }
    return { ok: true, status: 200, json: async () => ({ ok: true }) }
  }
  const inst = mount(searchStatus, { session: { id: 'search-a', running: true } })
  await flush()
  await advance(2600)
  expect(textOf(inst.tree).includes('正在筛选'), 'search card did not render: ' + textOf(inst.tree))
  inst.props = { session: { id: 'search-a', running: false } }
  inst.dirty = true
  await flush()
  await advance(100)
  expect(textOf(inst.tree) === '', 'find-only search card survived the turn end: ' + textOf(inst.tree))
  expect(clears === 1, 'turn end did not clear the Host status: ' + clears)
  // The next turn polls the same stale status; it must stay hidden.
  inst.props = { session: { id: 'search-a', running: true } }
  inst.dirty = true
  await flush()
  await advance(2600)
  expect(textOf(inst.tree) === '', 'hidden find-only status resurrected: ' + textOf(inst.tree))
  expect(clears === 1, 'a hidden status must be cleared only once: ' + clears)
  // A genuinely new find has a newer at and shows again.
  statusAt = clock.t + 10
  await advance(2600)
  expect(textOf(inst.tree).includes('正在筛选'), 'a new find did not show the card: ' + textOf(inst.tree))
  unmount(inst)
}

// A busy line older than its phase budget is stale even if the turn is still
// running (long model thinking after the search returned).
{
  let statusAt = clock.t - 20000
  let clears = 0
  fetchImpl = async (url) => {
    if (url.includes('/api/video2agent/discovery/clear')) {
      clears += 1
      return { ok: true, status: 200, json: async () => ({ ok: true, cleared: true }) }
    }
    if (url.includes('/api/video2agent/discovery/status')) {
      return { ok: true, status: 200, json: async () => ({ ok: true, status: { phase: 'curating', query: '显卡', at: statusAt } }) }
    }
    return { ok: true, status: 200, json: async () => ({ ok: true }) }
  }
  const inst = mount(searchStatus, { session: { id: 'search-stale', running: true } })
  await flush()
  await advance(100)
  expect(textOf(inst.tree) === '', 'stale curating card survived long thinking: ' + textOf(inst.tree))
  expect(clears === 1, 'stale busy status was not cleared: ' + clears)
  statusAt = clock.t + 10
  await advance(10200)
  expect(textOf(inst.tree).includes('正在筛选'), 'a fresh busy status did not render')
  unmount(inst)
}

// A no-result/error line is turn state too: show it during the turn, hide it
// at turn end, and never let the same status pop back in a later turn.
{
  let statusAt = clock.t
  let clears = 0
  fetchImpl = async (url) => {
    if (url.includes('/api/video2agent/discovery/clear')) {
      clears += 1
      return { ok: true, status: 200, json: async () => ({ ok: true, cleared: true }) }
    }
    if (url.includes('/api/video2agent/discovery/status')) {
      return {
        ok: true,
        status: 200,
        json: async () => ({ ok: true, status: { phase: 'empty', query: '不存在', found: 0, at: statusAt } }),
      }
    }
    return { ok: true, status: 200, json: async () => ({ ok: true }) }
  }
  const inst = mount(searchStatus, { session: { id: 'search-empty', running: true } })
  await flush()
  await advance(100)
  expect(textOf(inst.tree).includes('没有找到候选'), 'empty search card did not render during the turn')
  inst.props = { session: { id: 'search-empty', running: false } }
  inst.dirty = true
  await flush()
  await advance(100)
  expect(textOf(inst.tree) === '', 'empty search card survived the turn end: ' + textOf(inst.tree))
  expect(clears === 1, 'turn end did not clear the empty status: ' + clears)
  inst.props = { session: { id: 'search-empty', running: true } }
  inst.dirty = true
  await flush()
  await advance(100)
  expect(textOf(inst.tree) === '', 'old empty status resurrected in the next turn')
  statusAt = clock.t + 10
  await advance(2600)
  expect(textOf(inst.tree).includes('没有找到候选'), 'a newer empty status did not render')
  await advance(4000)
  expect(textOf(inst.tree) === '', 'a newer empty status outlived its 6s budget: ' + textOf(inst.tree))
  expect(clears === 2, 'the 6s budget did not clear the Host line exactly once: ' + clears)
  unmount(inst)
}

// A no-result line must expire from its own timer even when the next status
// fetch never answers: the budget is not a check performed by the poll that
// happens to arrive later.
{
  const statusAt = clock.t
  const clears = []
  let hang = false
  fetchImpl = async (url, opts) => {
    if (url.includes('/api/video2agent/discovery/clear')) {
      clears.push(JSON.parse(String((opts && opts.body) || '{}')))
      return { ok: true, status: 200, json: async () => ({ ok: true, cleared: true }) }
    }
    if (url.includes('/api/video2agent/discovery/status')) {
      if (hang) return new Promise(() => {})
      return {
        ok: true,
        status: 200,
        json: async () => ({ ok: true, status: { phase: 'empty', query: '无结果', found: 0, at: statusAt } }),
      }
    }
    return { ok: true, status: 200, json: async () => ({ ok: true }) }
  }
  const inst = mount(searchStatus, { session: { id: 'search-empty-hang', running: true } })
  await flush()
  expect(textOf(inst.tree).includes('没有找到候选'), 'the empty line did not render')
  hang = true
  await advance(6500)
  expect(textOf(inst.tree) === '', 'the empty line outlived its 6s budget while the next poll hung: ' + textOf(inst.tree))
  expect(clears.length === 1, 'the 6s budget did not clear the Host line: ' + clears.length)
  expect(clears[0].session === 'search-empty-hang', 'clear lost its session: ' + JSON.stringify(clears[0]))
  expect(clears[0].at === statusAt, 'clear did not carry the status at: ' + JSON.stringify(clears[0]))
  expect(clears[0].phase === 'empty', 'clear did not carry the status phase: ' + JSON.stringify(clears[0]))
  unmount(inst)
}

// A failed poll (500) must not cancel the already-armed budget.
{
  const statusAt = clock.t
  let clears = 0
  let broken = false
  fetchImpl = async (url) => {
    if (url.includes('/api/video2agent/discovery/clear')) {
      clears += 1
      return { ok: true, status: 200, json: async () => ({ ok: true, cleared: true }) }
    }
    if (url.includes('/api/video2agent/discovery/status')) {
      if (broken) return { ok: false, status: 500, json: async () => { throw new Error('boom') } }
      return {
        ok: true,
        status: 200,
        json: async () => ({ ok: true, status: { phase: 'error', query: 'q', at: statusAt, error: '搜索没有完成，请重试。' } }),
      }
    }
    return { ok: true, status: 200, json: async () => ({ ok: true }) }
  }
  const inst = mount(searchStatus, { session: { id: 'search-error-500', running: true } })
  await flush()
  expect(textOf(inst.tree).includes('搜索失败'), 'the error line did not render')
  broken = true
  await advance(6500)
  expect(textOf(inst.tree) === '', 'a failed poll cancelled the error line budget: ' + textOf(inst.tree))
  expect(clears === 1, 'the error line was not cleared once: ' + clears)
  unmount(inst)
}

// An empty body means the Host has no line. A no-result/error line is not
// waiting for a batch table, so it must not get a fresh 6s hold on top of its
// budget.
{
  const statusAt = clock.t
  let clears = 0
  let noLine = false
  fetchImpl = async (url) => {
    if (url.includes('/api/video2agent/discovery/clear')) {
      clears += 1
      return { ok: true, status: 200, json: async () => ({ ok: true, cleared: true }) }
    }
    if (url.includes('/api/video2agent/discovery/status')) {
      if (noLine) return { ok: true, status: 200, json: async () => ({ ok: true }) }
      return {
        ok: true,
        status: 200,
        json: async () => ({ ok: true, status: { phase: 'empty', query: '无', found: 0, at: statusAt } }),
      }
    }
    return { ok: true, status: 200, json: async () => ({ ok: true }) }
  }
  const inst = mount(searchStatus, { session: { id: 'search-empty-noline', running: true } })
  await flush()
  expect(textOf(inst.tree).includes('没有找到候选'), 'the empty line did not render before the line vanished')
  noLine = true
  await advance(2600)
  expect(textOf(inst.tree) === '', 'a no-result line was held after the Host line disappeared: ' + textOf(inst.tree))
  expect(clears === 0, 'a Host line that was already gone was cleared again: ' + clears)
  unmount(inst)
}

// A busy line may be held while the shortlist clears the status (the table is
// about to paint), but the hold is capped by that phase's remaining budget.
{
  const statusAt = clock.t - 8000
  let gone = false
  fetchImpl = async (url) => {
    if (url.includes('/api/video2agent/discovery/status')) {
      if (gone) return { ok: true, status: 200, json: async () => ({ ok: true }) }
      return {
        ok: true,
        status: 200,
        json: async () => ({ ok: true, status: { phase: 'curating', query: 'q', found: 2, at: statusAt } }),
      }
    }
    return { ok: true, status: 200, json: async () => ({ ok: true }) }
  }
  const inst = mount(searchStatus, { session: { id: 'search-hold-budget', running: true } })
  await flush()
  expect(textOf(inst.tree).includes('正在筛选'), 'the busy line did not render')
  gone = true
  await advance(2600)
  expect(textOf(inst.tree).includes('正在筛选'), 'the busy hold was dropped immediately')
  await advance(1600)
  expect(textOf(inst.tree) === '', 'the busy hold outlived the remaining phase budget: ' + textOf(inst.tree))
  unmount(inst)
}

// A short-lived null from the Host arms the 6s hold; a real new line arriving
// inside that window must cancel the old timer instead of being wiped by it.
{
  let statusAt = clock.t
  let phase = 'curating'
  let hasLine = true
  fetchImpl = async (url) => {
    if (url.includes('/api/video2agent/discovery/status')) {
      if (!hasLine) return { ok: true, status: 200, json: async () => ({ ok: true }) }
      return { ok: true, status: 200, json: async () => ({ ok: true, status: { phase, query: 'q', at: statusAt } }) }
    }
    return { ok: true, status: 200, json: async () => ({ ok: true }) }
  }
  const inst = mount(searchStatus, { session: { id: 'search-hold-then-new', running: true } })
  await flush()
  expect(textOf(inst.tree).includes('正在筛选'), 'the first busy line did not render')
  hasLine = false
  await advance(2600)
  expect(textOf(inst.tree).includes('正在筛选'), 'the null response dropped the busy line before its hold')
  hasLine = true
  phase = 'searching'
  statusAt = clock.t
  await advance(2600)
  expect(textOf(inst.tree).includes('正在找视频'), 'the new line did not replace the held one: ' + textOf(inst.tree))
  // Past the old hold's deadline (+2500+6000) and before the new line's expiry.
  await advance(3600)
  expect(textOf(inst.tree).includes('正在找视频'), 'the previous hold timer wiped the new line: ' + textOf(inst.tree))
  unmount(inst)
}

// A conversation switch must not show the previous chat's line, and the new
// chat's own line must win.
{
  const statusFor = {
    'switch-old': { phase: 'empty', query: '旧会话', found: 0, at: clock.t },
    'switch-new': { phase: 'curating', query: '新会话', found: 2, at: clock.t, candidates: [{ video_id: 'BV1switch', title: '新候选', duration_ms: 60000 }] },
  }
  fetchImpl = async (url) => {
    if (url.includes('/api/video2agent/discovery/status')) {
      const sid = new URL(String(url), 'http://localhost').searchParams.get('session')
      return { ok: true, status: 200, json: async () => ({ ok: true, status: statusFor[sid] || null }) }
    }
    return { ok: true, status: 200, json: async () => ({ ok: true }) }
  }
  const inst = mount(searchStatus, { session: { id: 'switch-old', running: true } })
  await flush()
  expect(textOf(inst.tree).includes('没有找到候选'), 'the old session empty line did not render')
  inst.props = { session: { id: 'switch-new', running: true } }
  inst.dirty = true
  await flush()
  const switched = textOf(inst.tree)
  expect(!switched.includes('没有找到候选'), 'the previous session card leaked into the new one: ' + switched)
  expect(switched.includes('正在筛选'), 'the new session line did not render: ' + switched)
  inst.props = { session: { id: 'switch-none', running: true } }
  inst.dirty = true
  await flush()
  expect(textOf(inst.tree) === '', 'a previous session card survived into an empty session: ' + textOf(inst.tree))
  unmount(inst)
}

// Turn end must drop the line without waiting for a status fetch that may be
// slow or throttled.
{
  const statusAt = clock.t
  let clears = 0
  let hang = false
  fetchImpl = async (url) => {
    if (url.includes('/api/video2agent/discovery/clear')) {
      clears += 1
      return { ok: true, status: 200, json: async () => ({ ok: true, cleared: true }) }
    }
    if (url.includes('/api/video2agent/discovery/status')) {
      if (hang) return new Promise(() => {})
      return {
        ok: true,
        status: 200,
        json: async () => ({ ok: true, status: { phase: 'empty', query: '无', found: 0, at: statusAt } }),
      }
    }
    return { ok: true, status: 200, json: async () => ({ ok: true }) }
  }
  const inst = mount(searchStatus, { session: { id: 'search-turnend-hang', running: true } })
  await flush()
  expect(textOf(inst.tree).includes('没有找到候选'), 'the empty line did not render before turn end')
  hang = true
  inst.props = { session: { id: 'search-turnend-hang', running: false } }
  inst.dirty = true
  await flush()
  expect(textOf(inst.tree) === '', 'turn end waited for a status fetch: ' + textOf(inst.tree))
  expect(clears === 1, 'turn end did not clear the Host line: ' + clears)
  unmount(inst)
}

// 4. A failed save keeps 保存失败 after the previous save's 1.2s timer.
{
  let settingsPosts = 0
  const saved = { enabled: true, cacheTtlMs: 86400000, cacheExpire: true, cacheDays: 7, cacheLimitEnabled: false, cacheLimitGb: 20, processLimit: 5, accentColor: '#0a84ff' }
  fetchImpl = async (url, opts) => {
    const method = String((opts && opts.method) || 'GET').toUpperCase()
    if (url.includes('/api/video2agent/settings')) {
      if (method === 'POST') {
        settingsPosts += 1
        if (settingsPosts === 1) return { ok: true, status: 200, json: async () => saved }
        return { ok: false, status: 500, json: async () => ({ error: 'nope' }) }
      }
      return { ok: true, status: 200, json: async () => saved }
    }
    if (url.includes('/api/video2agent/models')) {
      return { ok: true, status: 200, json: async () => ({ ok: true, asr: { selected: 'small', cached: true }, tiers: [], tier: 'mid' }) }
    }
    if (url.includes('/api/video2agent/cloud')) {
      return { ok: true, status: 200, json: async () => ({ ok: true, configured: false, presets: [] }) }
    }
    if (url.includes('/api/video2agent/bili-login/status')) {
      return { ok: true, status: 200, json: async () => ({ ok: true, logged_in: false }) }
    }
    return { ok: true, status: 200, json: async () => ({ ok: true }) }
  }
  const page = mount(settingsPage, {})
  await flush()
  // AGENTS: the cloud capsule is disabled without a key and says 先粘贴 API Key.
  const cloudAsr = findByChildText(page.tree, '云端 ASR')
  expect(cloudAsr, 'settings page has no cloud ASR capsule')
  expect(cloudAsr.props.disabled === true, 'cloud ASR is clickable without a saved key')
  const slider = findByAttr(page.tree, 'data-vp-process-limit')
  expect(slider, 'settings page has no processLimit slider')
  slider.props.onChange({ target: { value: '5' } })
  await advance(400)
  expect(settingsPosts === 1, 'first save did not POST (' + settingsPosts + ')')
  slider.props.onChange({ target: { value: '6' } })
  await advance(400)
  expect(settingsPosts === 2, 'second save did not POST (' + settingsPosts + ')')
  await advance(1300)
  const after = textOf(page.tree)
  expect(after.includes('保存失败'), 'failed save was cleared by the earlier save timer: ' + after.slice(0, 300))
  unmount(page)
}

// 4b. A failed patch must be retried by the next (unrelated) save: diffing
// against the optimistic SETTINGS silently dropped it.
{
  const posts = []
  let failNext = true
  const savedBase = { enabled: true, cacheTtlMs: 86400000, cacheExpire: true, cacheDays: 7, cacheLimitEnabled: false, cacheLimitGb: 20, processLimit: 5, accentColor: '#0a84ff' }
  fetchImpl = async (url, opts) => {
    const method = String((opts && opts.method) || 'GET').toUpperCase()
    if (url.includes('/api/video2agent/settings')) {
      if (method === 'POST') {
        const body = JSON.parse((opts && opts.body) || '{}')
        posts.push(body)
        if (failNext) { failNext = false; return { ok: false, status: 500, json: async () => ({ error: 'nope' }) } }
        return { ok: true, status: 200, json: async () => ({ ...savedBase, ...body }) }
      }
      return { ok: true, status: 200, json: async () => savedBase }
    }
    if (url.includes('/api/video2agent/models')) {
      return { ok: true, status: 200, json: async () => ({ ok: true, asr: { selected: 'small', cached: true }, tiers: [], tier: 'mid' }) }
    }
    if (url.includes('/api/video2agent/cloud')) {
      return { ok: true, status: 200, json: async () => ({ ok: true, configured: false, presets: [] }) }
    }
    if (url.includes('/api/video2agent/bili-login/status')) {
      return { ok: true, status: 200, json: async () => ({ ok: true, logged_in: false }) }
    }
    return { ok: true, status: 200, json: async () => ({ ok: true }) }
  }
  const page = mount(settingsPage, {})
  await flush()
  const failedSlider = findByAttr(page.tree, 'data-vp-process-limit')
  failedSlider.props.onChange({ target: { value: '6' } })
  await advance(400)
  expect(posts.length === 1 && posts[0].processLimit === 6, 'first save did not post processLimit: ' + JSON.stringify(posts))
  const accent = findByAttr(page.tree, 'data-vp-color')
  expect(accent, 'settings page has no accent control')
  // Use a colour distinct from test 5's: SETTINGS_ACKED is module state, so the
  // same value would be (correctly) diffed away as already saved.
  accent.props.onChange({ target: { value: '#7c5cff' } })
  await advance(400)
  expect(posts.length === 2, 'second save did not post (' + posts.length + ')')
  expect(posts[1].processLimit === 6, 'the failed processLimit was not retried: ' + JSON.stringify(posts))
  unmount(page)
}

// 5. Two controls inside the 300ms debounce post both keys, not only the last.
{
  const posts = []
  const saved = { enabled: true, cacheTtlMs: 86400000, cacheExpire: true, cacheDays: 7, cacheLimitEnabled: false, cacheLimitGb: 20, processLimit: 10, accentColor: '#0a84ff' }
  fetchImpl = async (url, opts) => {
    const method = String((opts && opts.method) || 'GET').toUpperCase()
    if (url.includes('/api/video2agent/settings')) {
      if (method === 'POST') {
        posts.push(JSON.parse(String(opts.body || '{}')))
        return { ok: true, status: 200, json: async () => saved }
      }
      return { ok: true, status: 200, json: async () => saved }
    }
    if (url.includes('/api/video2agent/models')) {
      return { ok: true, status: 200, json: async () => ({ ok: true, asr: { selected: 'small', cached: true }, tiers: [], tier: 'mid' }) }
    }
    if (url.includes('/api/video2agent/cloud')) {
      return { ok: true, status: 200, json: async () => ({ ok: true, configured: false, presets: [] }) }
    }
    if (url.includes('/api/video2agent/bili-login/status')) {
      return { ok: true, status: 200, json: async () => ({ ok: true, logged_in: false }) }
    }
    return { ok: true, status: 200, json: async () => ({ ok: true }) }
  }
  const page = mount(settingsPage, {})
  await flush()
  const color = findByAttr(page.tree, 'data-vp-color')
  const slider = findByAttr(page.tree, 'data-vp-process-limit')
  expect(color && slider, 'settings page is missing the colour or processLimit control')
  color.props.onChange({ target: { value: '#6b5cff' } })
  slider.props.onChange({ target: { value: '4' } })
  await advance(400)
  expect(posts.length === 1, 'debounced autosave did not post once (' + posts.length + ')')
  expect(posts[0].accentColor === '#6b5cff', 'accentColor was dropped by the debounce: ' + JSON.stringify(posts[0]))
  expect(posts[0].processLimit === 4, 'processLimit was dropped by the debounce: ' + JSON.stringify(posts[0]))
  unmount(page)
}

// 6. A late JobCard poll must not turn the turn-end wrap-up back into 正在处理.
// The card keeps polling until it unmounts; one more publish after closeLive
// used to reset the phase, cancel the 3s exit timer and leave the card up until
// the job itself finished.
{
  const sid = 'closing-a'
  const s = mount(strip, { session: { id: sid, running: true } })
  const base = { sessionId: sid, jobId: 'job_closing', title: '收尾视频', videoId: 'BV1xx411c7mD', phase: 'running', pct: 40, stage: 'ocr' }
  debug.__video2agentPublishLive(base)
  await flush()
  expect(textOf(s.tree).includes('正在处理'), 'running card missing before turn end')
  s.props = { session: { id: sid, running: false } }
  renderInstance(s)
  await flush()
  expect(textOf(s.tree).includes('本轮结束'), 'turn end did not wrap the card up: ' + textOf(s.tree))
  debug.__video2agentPublishLive(base)
  await flush()
  const revived = textOf(s.tree)
  expect(revived.includes('本轮结束') && !revived.includes('正在处理'),
    'a late poll revived the closing card: ' + revived)
  await advance(3200)
  expect(textOf(s.tree) === '', 'closing card did not auto-remove: ' + textOf(s.tree))
  debug.__video2agentPublishLive(base)
  await flush()
  expect(textOf(s.tree) === '', 'a poll after the close revived the card')
  // A genuinely new job (newer createdAt) may still take over the surface.
  debug.__video2agentPublishLive({
    ...base, jobId: 'job_after_close', title: '新任务',
    createdAt: new Date(clock.t).toISOString(),
  })
  await flush()
  expect(textOf(s.tree).includes('新任务'), 'a new job after the close did not render: ' + textOf(s.tree))
  unmount(s)
}

// 7. A turn end must not publish a closing card under a batch table: the table
// already owns the completion, and the card reappeared after the table cleared.
{
  const sid = 'closing-batch'
  const inst = await runBatch(sid, 'job_cb', 'ready')
  const s = mount(strip, { session: { id: sid, running: true } })
  await flush()
  s.props = { session: { id: sid, running: false } }
  renderInstance(s)
  await flush()
  const entry = (debug.__video2agentLiveState().sessions.find(([id]) => id === sid) || [])[1]
  expect(entry, 'batch did not publish a live entry')
  expect(entry.phase !== 'closing', 'turn end wrote a closing card under a batch table')
  expect(textOf(s.tree) === '', 'closing card rendered over the batch table: ' + textOf(s.tree))
  unmount(s)
  unmount(inst)
}

// 6b. Disabling the plugin while a search line is on screen must remove it:
// the poll stops, so nothing else would ever clear the frozen card.
{
  const statusAt = clock.t
  fetchImpl = async (url, opts) => {
    const method = String((opts && opts.method) || 'GET').toUpperCase()
    if (url.includes('/api/video2agent/discovery/clear')) {
      return { ok: true, status: 200, json: async () => ({ ok: true, cleared: true }) }
    }
    if (url.includes('/api/video2agent/discovery/status')) {
      return { ok: true, status: 200, json: async () => ({ ok: true, status: { phase: 'empty', query: '无', found: 0, at: statusAt } }) }
    }
    if (url.includes('/api/video2agent/settings')) {
      if (method === 'POST') {
        return { ok: true, status: 200, json: async () => ({ enabled: false, cacheTtlMs: 86400000, cacheExpire: true, cacheDays: 7, cacheLimitEnabled: false, cacheLimitGb: 20, processLimit: 5, accentColor: '#0a84ff' }) }
      }
      return { ok: true, status: 200, json: async () => ({ enabled: true, cacheTtlMs: 86400000, cacheExpire: true, cacheDays: 7, cacheLimitEnabled: false, cacheLimitGb: 20, processLimit: 5, accentColor: '#0a84ff' }) }
    }
    if (url.includes('/api/video2agent/models')) {
      return { ok: true, status: 200, json: async () => ({ ok: true, asr: { selected: 'small', cached: true }, tiers: [], tier: 'mid' }) }
    }
    if (url.includes('/api/video2agent/cloud')) {
      return { ok: true, status: 200, json: async () => ({ ok: true, configured: false, presets: [] }) }
    }
    if (url.includes('/api/video2agent/bili-login/status')) {
      return { ok: true, status: 200, json: async () => ({ ok: true, logged_in: false }) }
    }
    return { ok: true, status: 200, json: async () => ({ ok: true }) }
  }
  const inst = mount(searchStatus, { session: { id: 'search-disable', running: true } })
  await flush()
  expect(textOf(inst.tree).includes('没有找到候选'), 'the empty line did not render before disabling')
  const page = mount(settingsPage, {})
  await flush()
  const rows = collectByAttr(page.tree, 'data-vp-settings-row')
  const enabledRow = rows.find((row) => textOf(row).includes('显示处理卡片'))
  expect(enabledRow, 'settings page has no 显示处理卡片 row')
  const toggle = collectByAttr(enabledRow, 'type').find((node) => node.type === 'input' && node.props.type === 'checkbox')
  expect(toggle, '显示处理卡片 row has no checkbox')
  toggle.props.onChange({ target: { checked: false } })
  // The page's autosave debounce is 300ms; the optimistic settings update (and
  // the listener that drops the dock line) lands with it.
  await advance(400)
  expect(textOf(inst.tree) === '', 'disabling the plugin left the frozen search line: ' + textOf(inst.tree))
  unmount(page)
  unmount(inst)
}

// ---- environment card: plugin restart + engine update (Host fields) -----------
{
  const basePayload = (extraFields = {}) => ({
    ok: true,
    platform: 'win32',
    python: { ok: true, detail: 'Python 3.12.0' },
    cli: { ok: true, detail: 'video2agent 0.3.5', version: '0.3.5', latest: '0.3.6', update_available: true },
    ffmpeg: { ok: true, detail: 'ffmpeg version 7.0' },
    ocr: { ok: true, supported: true, version: '1.2' },
    browser: { ok: true, supported: true, version: '1.3' },
    canInstall: { cli: false, updateCli: true, ffmpeg: false, ocr: false, browser: false },
    hints: {},
    ...extraFields,
  })
  const saved = { enabled: true, cacheTtlMs: 86400000, cacheExpire: true, cacheDays: 7, cacheLimitEnabled: false, cacheLimitGb: 20, processLimit: 5, accentColor: '#0a84ff' }
  const serve = (setupHandler) => {
    fetchImpl = async (url, opts) => {
      const method = String((opts && opts.method) || 'GET').toUpperCase()
      if (url.includes('/api/video2agent/setup')) return setupHandler(method, opts)
      if (url.includes('/api/video2agent/settings')) return { ok: true, status: 200, json: async () => saved }
      if (url.includes('/api/video2agent/models')) return { ok: true, status: 200, json: async () => ({ ok: true, asr: { selected: 'small', cached: true }, tiers: [], tier: 'mid' }) }
      if (url.includes('/api/video2agent/cloud')) return { ok: true, status: 200, json: async () => ({ ok: true, configured: false, presets: [] }) }
      if (url.includes('/api/video2agent/bili-login/status')) return { ok: true, status: 200, json: async () => ({ ok: true, logged_in: false }) }
      return { ok: true, status: 200, json: async () => ({ ok: true }) }
    }
  }
  const payload = (data) => ({ ok: true, status: 200, json: async () => data })

  // A. Old Host: no plugin/engine_update fields -> the existing card is untouched.
  {
    let posts = 0
    serve((method) => {
      if (method !== 'GET') { posts += 1; return payload({ ok: true, status: basePayload() }) }
      return payload(basePayload())
    })
    const page = mount(settingsPage, {})
    await flush()
    const text = textOf(page.tree)
    expect(text.includes('视频引擎可更新：0.3.5 → 0.3.6'), 'old Host lost its update nudge: ' + text.slice(0, 300))
    expect(!text.includes('插件已更新') && !text.includes('正在更新视频引擎'), 'old Host rendered fields it never sent')
    expect(posts === 0, 'reading the card posted an install')
    unmount(page)
  }

  // B. Old Host first install still offers the missing dependency.
  {
    serve(() => payload(basePayload({
      cli: { ok: false, detail: '未安装', version: '', latest: '0.3.6', update_available: false },
      canInstall: { cli: true, updateCli: false, ffmpeg: false, ocr: false, browser: false },
    })))
    const page = mount(settingsPage, {})
    await flush()
    const install = collectByAttr(page.tree, 'data-vp-bili-btn').find((node) => textOf(node) === '安装 视频引擎')
    expect(install, 'first install button is gone: ' + textOf(page.tree).slice(0, 300))
    unmount(page)
  }

  // C. restart_required with an older engine: only the restart notice. No
  // manual update button and no engine-update nudge while the reload is pending.
  {
    let posts = 0
    serve((method) => {
      if (method === 'POST') { posts += 1; return payload({ ok: true }) }
      return payload(basePayload({ plugin: { loaded: '0.3.5', installed: '0.3.6', restart_required: true } }))
    })
    const page = mount(settingsPage, {})
    await flush()
    const text = textOf(page.tree)
    expect(text.includes('插件已更新，重开 DSH 后生效'), 'restart notice missing: ' + text.slice(0, 300))
    expect(!text.includes('视频引擎可更新'), 'a pending plugin reload still nudged an engine update')
    expect(!findByAttr(page.tree, 'data-vp-env-engine-manual'), 'an older engine still shows the manual update button during restart')
    expect(posts === 0, 'restart pending offered an engine update action')
    unmount(page)
  }

  // C2. Restart pending, engine already at the target: no manual update button
  // and no old update nudge (the restart notice is the only extra line).
  {
    serve(() => payload(basePayload({
      plugin: { loaded: '0.3.5', installed: '0.3.6', restart_required: true },
      cli: { ok: true, detail: 'video2agent 0.3.6', version: '0.3.6', latest: '0.3.6', update_available: true },
      canInstall: { cli: false, updateCli: true, ffmpeg: false, ocr: false, browser: false },
      engine_update: { state: 'ready', target: '0.3.6' },
    })))
    const page = mount(settingsPage, {})
    await flush()
    const text = textOf(page.tree)
    expect(text.includes('插件已更新，重开 DSH 后生效'), 'restart notice missing: ' + text.slice(0, 300))
    expect(!findByAttr(page.tree, 'data-vp-env-engine-manual'), 'a current engine still shows the manual update button')
    expect(!text.includes('视频引擎可更新'), 'a current engine still shows the update nudge: ' + text.slice(0, 300))
    unmount(page)
  }

  // C3. Restart pending, engine current, but the Host still carries a failed
  // marker: the stale failure, retry and manual update all stay hidden.
  {
    serve(() => payload(basePayload({
      plugin: { loaded: '0.3.5', installed: '0.3.6', restart_required: true },
      cli: { ok: true, detail: 'video2agent 0.3.6', version: '0.3.6', latest: '0.3.6', update_available: true },
      canInstall: { cli: false, updateCli: true, ffmpeg: false, ocr: false, browser: false },
      engine_update: { state: 'failed', target: '0.3.6' },
    })))
    const page = mount(settingsPage, {})
    await flush()
    const text = textOf(page.tree)
    expect(text.includes('插件已更新，重开 DSH 后生效'), 'restart notice missing: ' + text.slice(0, 300))
    expect(!text.includes('视频引擎更新失败'), 'a stale failure survived a current engine: ' + text.slice(0, 300))
    expect(!findByAttr(page.tree, 'data-vp-env-engine-retry'), 'a stale retry survived a current engine')
    expect(!findByAttr(page.tree, 'data-vp-env-engine-manual'), 'a current engine still shows the manual update button')
    unmount(page)
  }

  // C4. Restart pending with an older engine and a failed marker: no failure
  // copy or retry may push an engine update while the reload is pending.
  {
    serve(() => payload(basePayload({
      plugin: { loaded: '0.3.5', installed: '0.3.6', restart_required: true },
      engine_update: { state: 'failed', target: '0.3.6' },
    })))
    const page = mount(settingsPage, {})
    await flush()
    const text = textOf(page.tree)
    expect(!text.includes('视频引擎更新失败'), 'a failed marker leaked into the restart card: ' + text.slice(0, 300))
    expect(!findByAttr(page.tree, 'data-vp-env-engine-retry'), 'a retry is shown during restart')
    expect(!findByAttr(page.tree, 'data-vp-env-engine-manual'), 'a manual update is shown during restart')
    expect(!text.includes('视频引擎可更新'), 'the nudge is shown during restart: ' + text.slice(0, 300))
    unmount(page)
  }

  // D. A background update: show progress, poll briefly, then show the version
  // without asking the user to detect again; stop polling after it settles and
  // never POST from the poll.
  {
    let gets = 0
    let posts = 0
    let state = 'updating'
    serve((method) => {
      if (method !== 'GET') { posts += 1; return payload({ ok: true }) }
      gets += 1
      if (state === 'updating') return payload(basePayload({ engine_update: { state: 'updating', target: '0.3.6' } }))
      return payload(basePayload({
        cli: { ok: true, detail: 'video2agent 0.3.6', version: '0.3.6', latest: '0.3.6', update_available: false },
        canInstall: { cli: false, updateCli: false, ffmpeg: false, ocr: false, browser: false },
        engine_update: { state: 'ready', target: '0.3.6' },
      }))
    })
    const page = mount(settingsPage, {})
    await flush()
    let text = textOf(page.tree)
    expect(text.includes('正在更新视频引擎…'), 'updating state is not shown: ' + text.slice(0, 300))
    expect(!text.includes('视频引擎可更新'), 'an update in progress still nudged another update')
    state = 'ready'
    await advance(5100)
    text = textOf(page.tree)
    expect(text.includes('视频引擎已更新至 0.3.6'), 'ready state did not show the version: ' + text.slice(0, 300))
    expect(!text.includes('正在更新视频引擎…'), 'the updating line stayed after ready')
    expect(!text.includes('视频引擎可更新'), 'a finished update still nudged')
    const afterReady = gets
    await advance(5000)
    expect(gets === afterReady, 'polling continued after the engine settled: ' + afterReady + ' -> ' + gets)
    expect(posts === 0, 'the poll posted to the setup route')
    unmount(page)
  }

  // E. A failed background update: brief failure hint plus the existing retry
  // action; the retry POSTs update-cli and shows the new version.
  {
    const posts = []
    let state = 'updating'
    serve((method, opts) => {
      if (method === 'POST') {
        posts.push(JSON.parse(String((opts && opts.body) || '{}')))
        return payload({ ok: true, output: 'ok', status: basePayload({
          cli: { ok: true, detail: 'video2agent 0.3.6', version: '0.3.6', latest: '0.3.6', update_available: false },
          canInstall: { cli: false, updateCli: false, ffmpeg: false, ocr: false, browser: false },
          engine_update: { state: 'ready', target: '0.3.6' },
        }) })
      }
      if (state === 'updating') return payload(basePayload({ engine_update: { state: 'updating', target: '0.3.6' } }))
      return payload(basePayload({ engine_update: { state: 'failed', target: '0.3.6', message: '更新没有完成' } }))
    })
    const page = mount(settingsPage, {})
    await flush()
    state = 'failed'
    await advance(5100)
    let text = textOf(page.tree)
    expect(text.includes('视频引擎更新失败，可重试。'), 'failure hint missing: ' + text.slice(0, 300))
    expect(!text.includes('正在更新视频引擎…'), 'a failed update still says updating')
    const retry = findByAttr(page.tree, 'data-vp-env-engine-retry')
    expect(retry, 'a failed update has no retry action')
    retry.props.onClick()
    await flush()
    expect(posts.length === 1 && posts[0].action === 'update-cli', 'retry did not POST update-cli: ' + JSON.stringify(posts))
    text = textOf(page.tree)
    expect(text.includes('视频引擎已更新至 0.3.6'), 'a successful retry did not show the version: ' + text.slice(0, 300))
    expect(!text.includes('视频引擎更新失败'), 'the failure hint stayed after a successful retry')
    unmount(page)
  }

  // F. E_BUSY from a concurrent install is not a failed engine update: follow the
  // returned updating state and finish on the next poll.
  {
    const posts = []
    let state = 'idle'
    serve((method, opts) => {
      if (method === 'POST') {
        posts.push(JSON.parse(String((opts && opts.body) || '{}')))
        return payload({ ok: false, error: { code: 'E_BUSY', message: '有安装任务正在进行' },
          status: basePayload({ engine_update: { state: 'updating', target: '0.3.6' } }) })
      }
      if (state === 'idle') return payload(basePayload({ engine_update: { state: 'idle' } }))
      return payload(basePayload({
        cli: { ok: true, detail: 'video2agent 0.3.6', version: '0.3.6', latest: '0.3.6', update_available: false },
        canInstall: { cli: false, updateCli: false, ffmpeg: false, ocr: false, browser: false },
        engine_update: { state: 'ready', target: '0.3.6' },
      }))
    })
    const page = mount(settingsPage, {})
    await flush()
    const update = collectByAttr(page.tree, 'data-vp-bili-btn').find((node) => textOf(node) === '更新引擎')
    expect(update, 'no engine update button in the healthy card')
    update.props.onClick()
    await flush()
    let text = textOf(page.tree)
    expect(posts.length === 1 && posts[0].action === 'update-cli', 'update button did not POST update-cli')
    expect(!text.includes('视频引擎更新失败'), 'a busy install lock was reported as a failed update')
    expect(text.includes('正在更新视频引擎…'), 'the busy status did not show the running update: ' + text.slice(0, 300))
    state = 'ready'
    await advance(5100)
    expect(textOf(page.tree).includes('视频引擎已更新至 0.3.6'), 'the followed update did not finish: ' + textOf(page.tree).slice(0, 300))
    expect(!textOf(page.tree).includes('有安装任务正在进行'), 'the busy notice stayed under the success line: ' + textOf(page.tree).slice(0, 300))
    unmount(page)
  }

  // G. A broken Host must not be polled forever, and a closed card must not be
  // written back to; one manual refresh recovers.
  {
    let gets = 0
    let broken = false
    serve(() => {
      gets += 1
      if (broken) return { ok: false, status: 500, json: async () => { throw new Error('boom') } }
      return payload(basePayload({ engine_update: { state: 'updating', target: '0.3.6' } }))
    })
    const page = mount(settingsPage, {})
    await flush()
    expect(textOf(page.tree).includes('正在更新视频引擎…'), 'the updating line is missing before the Host breaks')
    broken = true
    await advance(70000)
    const settled = gets
    expect(settled <= 8, 'failure retries exceeded their budget: ' + settled)
    await advance(60000)
    expect(gets === settled, 'the card kept polling a broken Host: ' + settled + ' -> ' + gets)
    broken = false
    const refresh = findByAttr(page.tree, 'data-vp-env-refresh')
    expect(refresh, 'no 重新检测 button')
    refresh.props.onClick()
    await flush()
    expect(gets === settled + 1, 'a manual refresh did not recover: ' + (gets - settled))
    page.dirty = false
    unmount(page)
    await advance(30000)
    expect(page.dirty === false, 'an unmounted environment card was written back to')
  }

  // H. Two clicks on 重新检测 while one read is in flight must not stack requests.
  {
    let gets = 0
    let hang = false
    serve(() => {
      gets += 1
      if (hang) return new Promise(() => {})
      return payload(basePayload())
    })
    const page = mount(settingsPage, {})
    await flush()
    hang = true
    const refresh = findByAttr(page.tree, 'data-vp-env-refresh')
    refresh.props.onClick()
    refresh.props.onClick()
    await flush()
    expect(gets === 2, 'overlapping refreshes reached the Host: ' + gets)
    unmount(page)
  }

  // I. A hidden settings tab must not keep probing the environment; polling
  // resumes when the tab is visible again.
  {
    let gets = 0
    serve(() => {
      gets += 1
      return payload(basePayload({ engine_update: { state: 'updating', target: '0.3.6' } }))
    })
    const page = mount(settingsPage, {})
    await flush()
    const before = gets
    context.document.hidden = true
    try {
      await advance(16000)
      expect(gets === before, 'a hidden tab kept probing the environment: ' + (gets - before))
    } finally {
      context.document.hidden = false
    }
    await advance(5100)
    expect(gets === before + 1, 'polling did not resume when the tab became visible: ' + (gets - before))
    unmount(page)
  }

  // J. 重新检测 bypasses the Host's short status cache; the background poll uses
  // the plain cached read.
  {
    const urls = []
    serve(() => payload(basePayload({ engine_update: { state: 'updating', target: '0.3.6' } })))
    const cachedFetch = fetchImpl
    fetchImpl = async (url, opts) => {
      if (String(url).includes('/api/video2agent/setup')) urls.push(String(url))
      return cachedFetch(url, opts)
    }
    const page = mount(settingsPage, {})
    await flush()
    expect(urls.length === 1, 'the first page read count is wrong: ' + urls.length)
    expect(!urls[0].includes('refresh=1'), 'the first page read bypassed the cache: ' + urls[0])
    await advance(5100)
    expect(urls.length === 2, 'the background poll did not read: ' + urls.length)
    expect(!urls[1].includes('refresh=1'), 'the background poll bypassed the cache: ' + urls[1])
    const refresh = findByAttr(page.tree, 'data-vp-env-refresh')
    refresh.props.onClick()
    await flush()
    expect(urls.length === 3, 'the re-check did not read: ' + urls.length)
    expect(urls[2].includes('refresh=1'), '重新检测 did not bypass the status cache: ' + urls[2])
    unmount(page)
  }

  // K. A failed manual update, then a re-check that reports a running update:
  // the newer Host state owns the card. It used to show "正在更新视频引擎…"
  // and "视频引擎更新失败，可重试。" (plus a retry) at the same time.
  {
    let hostState = 'idle'
    serve((method) => {
      if (method === 'POST') {
        return payload({ ok: false, error: { message: '更新没有完成' }, status: basePayload({ engine_update: { state: 'failed', target: '0.3.6' } }) })
      }
      return payload(basePayload({ engine_update: { state: hostState, target: '0.3.6' } }))
    })
    const page = mount(settingsPage, {})
    await flush()
    const update = collectByAttr(page.tree, 'data-vp-bili-btn').find((node) => textOf(node) === '更新引擎')
    expect(update, 'no engine update button before the failed manual update')
    update.props.onClick()
    await flush()
    expect(textOf(page.tree).includes('视频引擎更新失败，可重试。'), 'the failed manual update was not reported')
    hostState = 'updating'
    const refresh = findByAttr(page.tree, 'data-vp-env-refresh')
    refresh.props.onClick()
    await flush()
    const text = textOf(page.tree)
    expect(text.includes('正在更新视频引擎…'), 'the newer running update is not shown: ' + text.slice(0, 300))
    expect(!text.includes('视频引擎更新失败'), 'a stale failure is still shown next to a running update')
    expect(!findByAttr(page.tree, 'data-vp-env-engine-retry'), 'a retry is offered while the Host is already updating')
    unmount(page)
  }

  // L. No restart, engine already current, but a failed manual result and stale
  // update flags remain: a re-check suppresses the stale failure, retry and offer.
  {
    let current = false
    serve((method) => {
      if (method === 'POST') {
        return payload({ ok: false, error: { message: '更新没有完成' }, status: basePayload({ engine_update: { state: 'failed', target: '0.3.6' } }) })
      }
      if (!current) return payload(basePayload({ engine_update: { state: 'idle' } }))
      return payload(basePayload({
        cli: { ok: true, detail: 'video2agent 0.3.6', version: '0.3.6', latest: '0.3.6', update_available: true },
        canInstall: { cli: false, updateCli: true, ffmpeg: false, ocr: false, browser: false },
        engine_update: { state: 'failed', target: '0.3.6' },
      }))
    })
    const page = mount(settingsPage, {})
    await flush()
    const update = collectByAttr(page.tree, 'data-vp-bili-btn').find((node) => textOf(node) === '更新引擎')
    expect(update, 'no engine update button before the failed manual update')
    update.props.onClick()
    await flush()
    expect(textOf(page.tree).includes('视频引擎更新失败，可重试。'), 'the failed manual update was not reported')
    current = true
    const refresh = findByAttr(page.tree, 'data-vp-env-refresh')
    refresh.props.onClick()
    await flush()
    const text = textOf(page.tree)
    expect(!text.includes('视频引擎更新失败'), 'a stale failure survived the current engine: ' + text.slice(0, 300))
    expect(!findByAttr(page.tree, 'data-vp-env-engine-retry'), 'a stale retry survived the current engine')
    expect(!text.includes('视频引擎可更新'), 'a stale update offer survived the current engine: ' + text.slice(0, 300))
    expect(!collectByAttr(page.tree, 'data-vp-bili-btn').some((node) => textOf(node) === '更新引擎'), 'a stale update button survived the current engine')
    unmount(page)
  }

  // M. Unknown versions and updateCli false must not hide a real failure: only
  // two comparable numeric versions can prove an update is stale.
  {
    serve(() => payload(basePayload({
      cli: { ok: true, detail: 'video2agent', version: '', latest: '', update_available: false },
      canInstall: { cli: false, updateCli: false, ffmpeg: false, ocr: false, browser: false },
      engine_update: { state: 'failed', target: '' },
    })))
    const page = mount(settingsPage, {})
    await flush()
    const text = textOf(page.tree)
    expect(text.includes('视频引擎更新失败，可重试。'), 'an unknown version hid a real failure: ' + text.slice(0, 300))
    expect(findByAttr(page.tree, 'data-vp-env-engine-retry'), 'an unknown version hid the retry action')
    unmount(page)
  }
}

console.log('dock state ok: clear removes card, canceled is not ready, auto-clear, late poll cannot revive the closing card, batch owns turn end, search line budget/hold/session/disable guards, environment card restart notice/current-engine suppression/updating poll/failed retry/bounded reads, stale failure/busy copy cleared by a newer update, slow first queue read not duplicated, failed save persists, debounce keeps both keys')

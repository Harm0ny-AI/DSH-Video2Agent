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
  await advance(10200)
  expect(textOf(inst.tree).includes('没有找到候选'), 'a newer empty status did not render')
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

console.log('dock state ok: clear removes card, canceled is not ready, auto-clear, late poll cannot revive the closing card, batch owns turn end, failed save persists, debounce keeps both keys')

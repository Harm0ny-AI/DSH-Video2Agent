import assert from 'node:assert/strict'
import { EventEmitter } from 'node:events'
import fs from 'node:fs'
import os from 'node:os'
import path from 'node:path'
import { createHash } from 'node:crypto'
import { fileURLToPath, pathToFileURL } from 'node:url'

const oldHome = process.env.VIDEO2AGENT_HOME
const oldBin = process.env.VIDEO2AGENT_BIN
const oldPython = process.env.VIDEO2AGENT_PYTHON
const home = fs.mkdtempSync(path.join(os.tmpdir(), 'vp-host-settings-'))
process.env.VIDEO2AGENT_HOME = home
process.env.VIDEO2AGENT_SHORTLIST_WAIT_MS = '50'
process.env.VIDEO2AGENT_BIN = 'definitely-missing-video2agent-binary-xyz'
// The setup card falls back to `python -m video2agent`; point that at a missing
// interpreter too so the missing-CLI assertions still test the failure path.
process.env.VIDEO2AGENT_PYTHON = path.join(home, 'missing-python')
const here = path.dirname(fileURLToPath(import.meta.url))
const pluginUrl = pathToFileURL(path.join(here, '..', 'packages', 'dsh-video2agent', 'index.js')).href
const { apply, __test } = await import(pluginUrl)
const routes = new Map()
const sections = []
let registeredTool = null
let connectionRejection = undefined
const admittedRequests = []
const ctx = {
  logger: { info() {} },
  commands: { register() {} },
  systemPrompt: { section: (options) => { sections.push(options); return () => {} } },
  get(name) {
    if (name === 'webServer') return { register(route) { routes.set(route.path, route.handler) }, getOrigin: () => 'https://qa.example' }
    if (name === 'tools') return { register(tool) { registeredTool = tool } }
    if (name === 'connection') {
      return { requestRejection(req) { admittedRequests.push(req.url || ''); return connectionRejection } }
    }
    return undefined
  },
}
apply(ctx)
assert.ok(routes.has('/api/video2agent/settings'), 'settings route missing')
assert.ok(routes.has('/api/video2agent/doctor'), 'doctor route missing')
assert.ok(routes.has('/api/video2agent/retry'), 'retry route missing')
assert.ok(routes.has('/api/video2agent/jobs/cancel'), 'cancel route missing')
assert.ok(routes.has('/api/video2agent/setup'), 'env-check/setup route missing')

function call(method, body, opts = {}) {
  return new Promise((resolve, reject) => {
    const req = new EventEmitter()
    req.method = method
    req.url = opts.url || '/api/video2agent/settings'
    // A same-origin browser POST carries Origin and Host; the guard now refuses a
    // write without Origin, so the default request looks like the real page.
    req.headers = {
      'content-type': 'application/json',
      host: '127.0.0.1:8640',
      origin: 'http://127.0.0.1:8640',
      ...(opts.headers || {}),
    }
    if (opts.noOrigin) delete req.headers.origin
    if (opts.contentType === null) delete req.headers['content-type']
    else if (opts.contentType !== undefined) req.headers['content-type'] = opts.contentType
    req.destroy = () => {}
    const chunks = []
    const res = new EventEmitter()
    res.statusCode = 0
    res.setHeader = () => {}
    res.write = (chunk) => { if (chunk) chunks.push(Buffer.from(chunk)); return true }
    res.end = (value) => {
      if (value) chunks.push(Buffer.from(value))
      resolve({ status: res.statusCode, body: Buffer.concat(chunks).toString('utf8') })
    }
    const route = opts.path || '/api/video2agent/settings'
    Promise.resolve(routes.get(route)(req, res)).catch(reject)
    setTimeout(() => {
      if (body !== undefined) req.emit('data', Buffer.from(body))
      req.emit('end')
    }, 0)
  })
}

const routingSection = sections.find((section) => section.name === 'video2agent:routing')
assert.ok(routingSection, 'routing prompt section missing')
assert.match(routingSection.text(), /check video before a web search/, 'routing rule missing')
assert.match(routingSection.text(), /with a concrete query/, 'single-query rule missing')
assert.match(routingSection.text(), /different search term/, 'search-again rule missing')
assert.match(routingSection.text(), /recording/, 'UI/recording path missing')
assert.deepEqual(__test.commandArgs({ command: 'find', query: '一' }),
  ['discover', '一', '--limit', '8', '--no-covers', '--json'],
  'Bilibili find must stay single-query')
assert.equal(__test.workerEligible({ command: 'admin', admin_action: 'ocr-index' }), false, 'admin ocr-index must not run in the read-only worker')
assert.equal(__test.workerEligible({ command: 'admin', admin_action: 'export' }), false)
assert.equal(__test.workerEligible({ command: 'admin', admin_action: 'account' }), false)
assert.equal(__test.workerEligible({ command: 'admin', admin_action: 'list' }), true)
assert.equal(__test.workerEligible({ command: 'find' }), true)
// Candidate offers and shortlist idempotency are per session.
assert.notEqual(__test.discoveryLastPath('session-a'), __test.discoveryLastPath('session-b'), 'discovery candidates must be per session')
assert.equal(__test.discoveryLastPath('session-a'), __test.discoveryLastPath('session-a'))
assert.deepEqual(__test.commandArgs({ command: 'find', query: '一' }),
  ['discover', '一', '--limit', '8', '--no-covers', '--json'],
  'a single-query find must stay unchanged')

const cancelMissing = await call('POST', JSON.stringify({ job_id: 'job_missing_xyz' }), { path: '/api/video2agent/jobs/cancel' })
assert.equal(cancelMissing.status, 404, 'cancel must not create a marker for a missing job')

// The environment card reads real state (python exists on the CI runner, the
// harness points VIDEO2AGENT_BIN at a missing binary) and never fakes "installed".
const setup = await call('GET', undefined, { path: '/api/video2agent/setup' })
assert.equal(setup.status, 200, 'setup status must be readable: ' + setup.body.slice(0, 200))
const setupData = JSON.parse(setup.body)
assert.equal(setupData.ok, true)
for (const key of ['python', 'cli', 'ffmpeg']) {
  assert.equal(typeof (setupData[key] || {}).ok, 'boolean', key + ' must be measured, not assumed')
}
// VIDEO2AGENT_BIN points at a missing binary, but this machine may still have a
// working python -m video2agent (the setup card's fallback). Both are truthful:
// assert the shape, and the only usable-CLI path is that fallback.
if (setupData.cli.ok) {
  assert.equal(setupData.cli.via, 'python', 'only the python-module fallback may make the CLI usable here')
}
// detectCli records that interpreter; the later routes still go through the
// explicit missing VIDEO2AGENT_BIN, but do not leave a record behind.
fs.rmSync(__test.managedToolsPath(), { force: true })
assert.equal(typeof setupData.hints.cli, 'string', 'the CLI hint must be copy-pasteable')
const badSetupAction = await call('POST', JSON.stringify({ action: 'not-a-real-action' }), { path: '/api/video2agent/setup' })
assert.equal(badSetupAction.status, 400, 'unknown setup actions must be refused')
const noJsonSetup = await call('POST', JSON.stringify({ action: 'refresh' }), { path: '/api/video2agent/setup', contentType: 'text/plain' })
assert.equal(noJsonSetup.status, 415, 'setup installs must require a JSON body')
assert.equal(__test.readManagedTools().ffmpeg, undefined, 'no managed ffmpeg is recorded in a fresh home')
assert.equal(__test.managedToolEnv({ PATH: process.env.PATH }).FFMPEG_BIN, undefined, 'no FFMPEG_BIN without a managed install')
// DSH Connection admission: a webServer route is otherwise callable by a page in
// the user's browser. A non-undefined rejection must be answered with that status.
connectionRejection = 403
const admittedRejected = await call('GET', undefined, { path: '/api/video2agent/setup' })
assert.equal(admittedRejected.status, 403, 'a Connection requestRejection must be answered, not ignored')
connectionRejection = undefined
// The evidence image is the one cross-site GET the desktop shell needs (opaque id
// + image destination); it must stay on guardRead and skip the Connection fence.
const admittedBefore = admittedRequests.length
const imageRead = await call('GET', undefined, {
  path: '/api/video2agent/frame',
  url: '/api/video2agent/frame?id=vid_missing/frame.jpg',
  headers: { 'sec-fetch-site': 'cross-site', 'sec-fetch-dest': 'image' },
})
assert.equal(admittedRequests.length, admittedBefore, 'the frame image read must not hit the Connection fence')
assert.notEqual(imageRead.status, 403, 'the frame image read must not be refused as cross-site')
assert.ok(admittedRequests.every((url) => !String(url).startsWith('/api/video2agent/frame?id=')), 'image routes never reach the fence')

const doctor = await call('GET', undefined, { path: '/api/video2agent/doctor' })
assert.equal(doctor.status, 502, 'doctor route must not fake success when the CLI is missing')
const missingCloud = await call('GET', undefined, { path: '/api/video2agent/cloud' })
assert.equal(missingCloud.status, 502, 'a missing CLI must not render as an empty cloud config')
const missingModels = await call('GET', undefined, { path: '/api/video2agent/models' })
assert.equal(missingModels.status, 502, 'a missing CLI must not render as default models')

const initial = await call('GET')
assert.equal(initial.status, 200)
// Reads have no Origin, so a DNS-rebinding page would otherwise read settings.
const foreignHost = await call('GET', undefined, { headers: { host: 'evil.example:8640' } })
assert.equal(foreignHost.status, 403, 'a foreign Host must not read settings')
const noHost = await call('GET', undefined, { headers: { host: '' } })
assert.equal(noHost.status, 403, 'a request without Host must not read settings')
assert.deepEqual(JSON.parse(initial.body), {
  enabled: true,
  cacheTtlMs: 86400000,
  cacheExpire: true,
  cacheDays: 7,
  cacheLimitEnabled: false,
  cacheLimitGb: 20,
  accentColor: '#0a84ff',
  cookiesPath: '',
  processLimit: 10,
})
// How much work an ingest does is the model's call, so no profile/OCR/hold keys are
// exposed as preferences any more — a stale file value must not resurrect them. The
// auto-pick countdown is gone too: the card starts the model-selected videos itself.
const retired = await call('POST', JSON.stringify({ defaultProfile: 'fast', ocrBudget: 240, autoHideMs: 8000, autoPickHoldMs: 4000, autoPick: true }))
assert.equal(retired.status, 200)
for (const key of ['defaultProfile', 'ocrBudget', 'autoHideMs', 'autoPickHoldMs', 'autoPick']) {
  assert.equal(key in JSON.parse(retired.body), false, 'retired setting came back: ' + key)
}
const saved = await call('POST', JSON.stringify({ enabled: false, cacheTtlMs: 3600000 }))
assert.equal(saved.status, 200)
assert.deepEqual(JSON.parse(saved.body), {
  enabled: false,
  cacheTtlMs: 3600000,
  cacheExpire: true,
  cacheDays: 7,
  cacheLimitEnabled: false,
  cacheLimitGb: 20,
  accentColor: '#0a84ff',
  cookiesPath: '',
  processLimit: 10,
})
const rawSaved = JSON.parse(fs.readFileSync(path.join(home, 'ui-settings.json'), 'utf8'))
assert.equal(rawSaved.cacheTtlMs, 3600000)
assert.equal(routingSection.text(), '', 'a disabled plugin (enabled:false) must publish no routing rule')
assert.equal('cookiesPath' in rawSaved, false, 'saving the UI must not freeze Config-only keys')
const fullSave = await call('POST', JSON.stringify({ enabled: true, cacheTtlMs: 86400000, cacheExpire: true, cacheDays: 7, cacheLimitEnabled: false, cacheLimitGb: 20, accentColor: '#0a84ff', processLimit: 10 }))
assert.equal(fullSave.status, 200, 'the exact full settings body must save')
const cachePolicy = await call('POST', JSON.stringify({ cacheExpire: false, cacheDays: 999, cacheLimitEnabled: true, cacheLimitGb: 99 }))
assert.equal(cachePolicy.status, 200)
const cacheSaved = JSON.parse(cachePolicy.body)
assert.equal(cacheSaved.cacheExpire, false)
assert.equal(cacheSaved.cacheDays, 365)
assert.equal(cacheSaved.cacheLimitEnabled, true)
assert.equal(cacheSaved.cacheLimitGb, 20)
const limited = await call('POST', JSON.stringify({ processLimit: 99 }))
assert.equal(JSON.parse(limited.body).processLimit, 10)
const floor = await call('POST', JSON.stringify({ processLimit: 0 }))
assert.equal(JSON.parse(floor.body).processLimit, 1)
await call('POST', JSON.stringify({ enabled: true, cacheTtlMs: 86400000, cacheExpire: true, cacheDays: 7, cacheLimitEnabled: false, cacheLimitGb: 20, processLimit: 10 }))

// Theme colour: a valid hex round-trips, and anything that is not #rrggbb falls
// back to the default so a corrupt file can never inject CSS.
const themed = await call('POST', JSON.stringify({ accentColor: '#6B5CFF' }))
assert.equal(themed.status, 200)
assert.equal(JSON.parse(themed.body).accentColor, '#6b5cff', 'accent colour should be lowercased and persisted')
assert.equal(JSON.parse(fs.readFileSync(path.join(home, 'ui-settings.json'), 'utf8')).accentColor, '#6b5cff')
const hostile = await call('POST', JSON.stringify({ accentColor: 'red;}body{display:none' }))
assert.equal(JSON.parse(hostile.body).accentColor, '#0a84ff', 'non-hex accent must fall back to the default')
const restored = await call('POST', JSON.stringify({ accentColor: '#0a84ff' }))
assert.equal(JSON.parse(restored.body).accentColor, '#0a84ff')

// Bilibili cookies: only the path is stored, and control characters are refused
// so the value can be passed as a single CLI argument.
const cookiePath = 'C:\\Users\\tester\\bilibili-cookies.txt'
const cookiesSaved = await call('POST', JSON.stringify({ cookiesPath: cookiePath }))
assert.equal(JSON.parse(cookiesSaved.body).cookiesPath, cookiePath)
const cookiesBad = await call('POST', JSON.stringify({ cookiesPath: 'bad\u0000path' }))
assert.equal(JSON.parse(cookiesBad.body).cookiesPath, '', 'control characters must be stripped')
const cookiesCleared = await call('POST', JSON.stringify({ cookiesPath: '' }))
assert.equal(JSON.parse(cookiesCleared.body).cookiesPath, '')
const after = await call('GET')
assert.equal('defaultProfile' in JSON.parse(after.body), false, 'the profile preference is retired')
assert.ok(registeredTool, 'video2agent tool should be registered')

// Token-budget regression: the fixed surface must stay small. Measured on
// 2026-11-10: schema description 1,224 chars, 52 params, SKILL.md 8,479 chars.
// A return of per-command prose fails here.
const skillText = fs.readFileSync(path.join(here, '..', 'skills', 'video2agent', 'SKILL.md'), 'utf8')
assert.ok(skillText.length < 8500, `SKILL.md grew to ${skillText.length} chars; keep the router lean`)
// A video-native question (new season tier list) is the product's reason to
// exist; trimming the skill must not remove the trigger again.
assert.ok(String(registeredTool.description).includes('fresh video'),
  'the tool description must name fresh-video questions')
assert.ok(skillText.includes('When video is the better source'),
  'SKILL.md must keep the video-native routing rule')
assert.ok(skillText.includes('新赛季枪械排行'), 'the Chinese video-native examples must stay')
for (const verb of ['find', 'ingest', 'outline', 'read', 'evidence', 'frames', 'perceive', 'admin']) {
  assert.ok(skillText.includes(verb), `SKILL.md must route the ${verb} verb`)
}
assert.ok(String(registeredTool.description).length < 1500, 'the tool description must stay a router, not a manual')
assert.ok(Object.keys(registeredTool.parameters.properties).length <= 56, 'schemas with 57+ params need a split, not another description')
assert.equal(registeredTool.parameters.properties.command.enum.length, 8, 'the model-facing command enum must stay at eight verbs')
// Image budget default: text first (docs/COST.md), 2 frames for layout.
const imagesSchema = registeredTool.parameters?.properties?.images
assert.ok(imagesSchema, 'images parameter missing')
assert.match(imagesSchema.description, /default 2/, 'evidence default should be 2 images, not 4')
assert.match(imagesSchema.description, /0 when transcript\/OCR text answers/, 'text-first guidance missing from the tool schema')
const failed = await registeredTool.execute({ command: 'overview', video_id: 'missing' })
assert.equal(failed.ok, false)
assert.equal(failed.error.code, 'E_SPAWN')
assert.match(failed.error.remedy, /VIDEO2AGENT_BIN|Install/)

// The chat card can only read the rendered text, so a failure must render as a
// JSON envelope that carries code + remedy. Bare prose would leave the card
// with no actionable error (the P1 "waiting for result forever" regression).
const renderFailed = registeredTool.output.render({ command: 'overview' }, failed)
assert.equal(renderFailed.length, 1)
const failureEnvelope = JSON.parse(renderFailed[0].text)
assert.equal(failureEnvelope.ok, false)
assert.equal(failureEnvelope.error.code, 'E_SPAWN')
assert.match(failureEnvelope.error.remedy, /VIDEO2AGENT_BIN|Install/)
assert.equal(typeof failureEnvelope.text, 'string')

// A successful call must keep the CLI payload raw so result cards parse it.
// `jobs` is used instead of `doctor` so the check does not depend on ffmpeg
// being installed on the runner.
process.env.VIDEO2AGENT_BIN = 'video2agent'
const okCall = await registeredTool.execute({ command: 'jobs' })
assert.equal(okCall.ok, true, 'jobs should succeed: ' + JSON.stringify(okCall).slice(0, 300))
assert.equal(okCall.error, undefined)
const renderedOk = registeredTool.output.render({ command: 'jobs' }, okCall)
assert.equal(renderedOk[0].text, okCall.text, 'success render must not wrap the payload')
assert.doesNotThrow(() => JSON.parse(renderedOk[0].text), 'tool output should stay parseable JSON')

// Cloud settings: the key is POSTed to a loopback-only route, passed to the CLI
// on stdin, and never returned by GET. This uses a disposable home.
const cloudInitial = await call('GET', undefined, { path: '/api/video2agent/cloud' })
assert.equal(cloudInitial.status, 200)
assert.equal(JSON.parse(cloudInitial.body).configured, false)
const fakeKey = 'sk-' + 'x'.repeat(30)
const cloudSaved = await call('POST', JSON.stringify({ action: 'save', key: fakeKey }), { path: '/api/video2agent/cloud' })
if (process.platform === 'win32') {
  assert.equal(cloudSaved.status, 200)
  assert.equal(JSON.parse(cloudSaved.body).configured, true)
  assert.equal(cloudSaved.body.includes(fakeKey), false, 'the key must never come back from the route')
  const cloudStatus = await call('GET', undefined, { path: '/api/video2agent/cloud' })
  assert.equal(JSON.parse(cloudStatus.body).configured, true)
  assert.equal(cloudStatus.body.includes(fakeKey), false, 'GET must expose only last4')
  const cloudCleared = await call('POST', JSON.stringify({ action: 'clear' }), { path: '/api/video2agent/cloud' })
  assert.equal(cloudCleared.status, 200)
  assert.equal(JSON.parse(cloudCleared.body).configured, false)
} else {
  // The key is DPAPI-encrypted; off Windows the CLI must refuse, not store it in
  // plaintext. The route passes that failure through as a structured 502.
  assert.equal(cloudSaved.status, 502, 'DPAPI is Windows-only; save must fail explicitly')
  const savedBody = JSON.parse(cloudSaved.body)
  assert.equal(savedBody.ok, false)
  assert.match(JSON.stringify(savedBody), /E_[A-Z_]+/, 'the failure must name a code')
  const cloudStatus = await call('GET', undefined, { path: '/api/video2agent/cloud' })
  assert.equal(JSON.parse(cloudStatus.body).configured, false, 'a refused save must not look configured')
}

// Flexible provider/model config: any OpenAI-compatible endpoint and model IDs.
const cloudConfigured = await call('POST', JSON.stringify({
  action: 'config',
  provider: 'custom',
  base_url: 'https://api.example.com/v1',
  asr_model: 'my-asr',
  ocr_model: 'my-ocr',
  asr_enabled: false,
}), { path: '/api/video2agent/cloud' })
assert.equal(cloudConfigured.status, 200)
const configuredBody = JSON.parse(cloudConfigured.body)
assert.equal(configuredBody.provider, 'custom')
assert.equal(configuredBody.asr_model, 'my-asr')
assert.equal(configuredBody.asr_enabled, false)
assert.equal(cloudConfigured.body.includes(fakeKey), false, 'config must not echo a key')
const modelSelected = await call('POST', JSON.stringify({ action: 'select', model: 'large-v3' }), { path: '/api/video2agent/models' })
assert.equal(modelSelected.status, 200)
assert.equal(JSON.parse(modelSelected.body).asr.selected, 'large-v3')

// Evidence/frames are pictures: the stored attachment refs must become image blocks
// so the model sees the frame (handwriting, charts, actions), not just OCR text.
const withImages = registeredTool.output.render({ command: 'evidence' }, {
  ok: true,
  text: '{"ok":true}',
  images: [
    { attachmentId: 'att_1', mediaType: 'image/jpeg', bytes: 10, width: 1280, height: 720 },
    { attachmentId: 'att_2', mediaType: 'image/png', bytes: 10, width: 800, height: 600 },
  ],
})
assert.equal(withImages.length, 3, 'text + two image blocks')
assert.equal(withImages[0].type, 'text')
assert.equal(withImages[1].type, 'image')
assert.equal(withImages[1].attachment.attachmentId, 'att_1')
assert.equal(withImages[2].attachment.attachmentId, 'att_2')
const textOnly = registeredTool.output.render({ command: 'evidence' }, { ok: true, text: '{"ok":true}' })
assert.equal(textOnly.length, 1, 'no images means text only, never a broken block')
// A failure never becomes an image block.
const failedBlocks = registeredTool.output.render({ command: 'evidence' }, { ok: false, text: 'boom', error: { code: 'E_X', message: 'boom' }, images: [{ attachmentId: 'att_9' }] })
assert.equal(failedBlocks.length, 1)
assert.equal(failedBlocks[0].type, 'text')

// A real CLI failure carries `{ok:false,error:{code,message,remedy}}` on stdout.
// The host used to wrap that JSON into an E_CLI message, so the card showed a
// JSON wall and lost the code/remedy (P0-4).
const notFound = await registeredTool.execute({ command: 'overview', video_id: 'vid_doesnotexist' })
assert.equal(notFound.ok, false)
assert.equal(notFound.error.code, 'E_NOT_FOUND', 'the CLI error code must survive the host wrapper')
assert.match(notFound.error.remedy, /video2agent list/i, 'the CLI remedy must survive too')
// The model-facing text must stay parseable JSON even on failure: in a run_code
// session a plain message made its JSON.parse throw and aborted a real turn
// (2026-11-14: the second find after a search error lost the rest of the plan).
const notFoundPayload = JSON.parse(notFound.text)
assert.equal(notFoundPayload.ok, false)
assert.equal(notFoundPayload.error.code, 'E_NOT_FOUND')
const renderedNotFound = registeredTool.output.render({ command: 'overview' }, notFound)
const notFoundEnvelope = JSON.parse(renderedNotFound[0].text)
assert.equal(notFoundEnvelope.error.code, 'E_NOT_FOUND')
assert.equal(notFoundEnvelope.text, '', 'the envelope must not re-print the error JSON')
// A model that says "timestamp" instead of "at" must not lose a call.
assert.ok(registeredTool.parameters.properties.timestamp, 'timestamp alias must be in the schema')
const aliasCall = await registeredTool.execute({ command: 'evidence', video_id: 'vid_missing_alias', timestamp: '5s' })
assert.equal(aliasCall.ok, false)
assert.ok(!/Missing required argument/.test(String(aliasCall.error && aliasCall.error.message)),
  'timestamp must satisfy the at requirement: ' + String(aliasCall.error && aliasCall.error.message))

// jobs can block instead of making the model poll.
assert.ok(registeredTool.parameters.properties.wait_ms, 'jobs wait_ms should be exposed to the model')

// Config export: present when the schema package is installed (the DSH case),
// absent in a bare checkout. Either way the plugin must load and the settings
// route must keep working — a missing schema package must not break activation.
const pluginModule = await import(pluginUrl)

// The /job route consumes the jobs CLI payload. A failed row comes wrapped in
// {ok:false, job, error}; taking the envelope itself would make the route answer
// 404 for a job that exists, and the first poll after a worker crash would never
// show the error or its remedy.
const failedJob = pluginModule.__test.jobFromCliPayload({
  ok: false,
  job: { id: 'job_crashed', state: 'failed', stage: null },
  error: { code: 'E_WORKER_LOST', message: 'worker 进程已退出，任务没有正常结束', remedy: '重新 ingest 或重试该任务。' },
})
assert.equal(failedJob.id, 'job_crashed')
assert.equal(failedJob.state, 'failed')
assert.equal(failedJob.error_code, 'E_WORKER_LOST')
assert.match(failedJob.error_message, /worker/)
assert.match(failedJob.remedy, /重试/)
assert.equal(pluginModule.__test.jobFromCliPayload({ ok: false, error: { code: 'E_JOB' } }), null,
  'an envelope without a job row cannot become a job')
assert.equal(pluginModule.__test.jobFromCliPayload({ id: 'job_plain', state: 'running' }).id, 'job_plain',
  'the unwrapped job shape must keep working')

if (pluginModule.Config === undefined) {
  // CI installs the optional peer and sets REQUIRE_SCHEMASTER=1, so a skip there
  // fails instead of printing 'Config schema' anyway.
  if (process.env.REQUIRE_SCHEMASTER === '1') {
    throw new Error('@deepseek-ai/schemastery is missing but REQUIRE_SCHEMASTER=1')
  }
  console.log('note: @deepseek-ai/schemastery is not installed here, so the Config schema is skipped')
} else {
  const defaults = pluginModule.Config({})
  assert.equal(defaults.accentColor, '#0a84ff')
  assert.equal(defaults.processLimit, 10)
  // Work-sized knobs and the old auto-pick countdown are gone from the Config too:
  // the model picks the profile per request and the card starts its own selection.
  for (const key of ['defaultProfile', 'ocrBudget', 'autoHideMs', 'autoPickHoldMs', 'autoPick']) {
    assert.equal(key in defaults, false, 'Config still exposes ' + key)
  }
  assert.throws(() => pluginModule.Config({ accentColor: 'red' }), /accentColor/)
}

// Writes must be JSON POSTs from the same origin; a foreign page can send a
// text/plain "simple" request that skips CORS preflight, and `/settings` persists
// a cookie path that later reaches yt-dlp.
const notJson = await call('POST', JSON.stringify({ accentColor: '#ff0000' }), { contentType: 'text/plain' })
assert.equal(notJson.status, 415, 'a non-JSON content type must be rejected')
const crossOrigin = await call('POST', JSON.stringify({ accentColor: '#ff0000' }), { headers: { origin: 'https://evil.example' } })
// Fail closed: with an Origin present and no getOrigin() to compare against, the
// write is refused. The real webServer implements getOrigin(), so the page's own
// requests still work.
assert.equal(crossOrigin.status, 403, 'a foreign origin must not be able to write')
const noOrigin = await call('POST', JSON.stringify({ accentColor: '#00ff00' }), { noOrigin: true })
assert.equal(noOrigin.status, 200, 'a loopback desktop write without Origin must save')
const foreignNoOrigin = await call('POST', JSON.stringify({ accentColor: '#00ff00' }), { noOrigin: true, headers: { host: 'evil.example:8640' } })
assert.equal(foreignNoOrigin.status, 403, 'a non-loopback write without Origin must be refused')
const nullOrigin = await call('POST', JSON.stringify({ cacheTtlMs: 86400000 }), { headers: { origin: 'null' } })
assert.equal(nullOrigin.status, 200, 'the desktop custom-scheme Origin: null must save on loopback')
// CSRF: a cross-site fetch must not read, but a cross-site POST must still reach
// guardWrite (the desktop shell's Origin:null writes depend on this order).
const crossRead = await call('GET', undefined, { headers: { 'sec-fetch-site': 'cross-site' } })
assert.equal(crossRead.status, 403, 'a cross-site read must be refused')
const crossPost = await call('POST', JSON.stringify({ accentColor: '#222222' }), { headers: { 'sec-fetch-site': 'cross-site' } })
assert.notEqual(crossPost.status, 500, 'a cross-site POST must not crash in guardRead')
// A read route accepts POST too (resolve/job/frame): cross-site must still be refused.
const crossResolve = await call('POST', JSON.stringify({ url: 'https://www.bilibili.com/video/BV1x' }), {
  path: '/api/video2agent/resolve',
  // The guard reads req.url; the harness dispatches by opts.path.
  url: '/api/video2agent/resolve?url=https%3A%2F%2Fwww.bilibili.com%2Fvideo%2FBV1x',
  headers: { 'sec-fetch-site': 'cross-site' },
})
assert.equal(crossResolve.status, 403, 'a cross-site POST to a read route must be refused')
// /setup is a write route (installs); it must be exempt from the cross-site read
// refusal for the same reason as /settings, or a legit desktop write gets 403.
const crossSetup = await call('POST', JSON.stringify({ action: 'refresh' }), { path: '/api/video2agent/setup', headers: { 'sec-fetch-site': 'cross-site' } })
assert.notEqual(crossSetup.status, 403, 'a cross-site POST to /setup must reach guardWrite, not guardRead')
assert.notEqual(crossSetup.status, 500, 'a cross-site POST to /setup must not crash')
// Body limit: answer 413 instead of destroying the socket (ECONNRESET).
const tooLarge = await call('POST', 'x'.repeat(20000))
assert.equal(tooLarge.status, 413, 'an oversized body must answer 413')
const appOrigin = await call('POST', JSON.stringify({ cacheTtlMs: 86400000 }), { headers: { origin: 'dsh-app://desktop' } })
assert.equal(appOrigin.status, 200, 'the desktop custom scheme must save on loopback')
// The advertised origin is the real webServer's own origin (used when the page
// is reached by a LAN name instead of 127.0.0.1). This fallback used to throw on
// an undefined `webServer`; the error was swallowed as a 403.
const advertised = await call('POST', JSON.stringify({ cacheTtlMs: 86400000 }), { headers: { origin: 'https://qa.example' } })
assert.equal(advertised.status, 200, 'the advertised origin must be allowed to write')
const stillIntact = JSON.parse((await call('GET')).body)
assert.notEqual(stillIntact.accentColor, '#ff0000', 'rejected writes must not change settings')

// `--images` and `--limit` are declared as bounded in the schema; the argv builder
// must clamp them, because the model can pass anything. Check the value next to
// the flag, not `.includes('0')` (which `--at 0` would satisfy by accident).
const { commandArgs, readMergedSettings } = pluginModule.__test
// A CLI installed by the setup card may live behind "python -m video2agent" (pip's
// Scripts dir is not on the app's PATH). The managed record must build that argv.
const managedTools = __test.managedToolsPath()
fs.mkdirSync(path.dirname(managedTools), { recursive: true })
fs.writeFileSync(managedTools, JSON.stringify({ cli: { python: process.execPath, prefix: [], at: new Date().toISOString() } }), 'utf8')
delete process.env.VIDEO2AGENT_BIN
const managedInvocation = __test.cliCommand()
assert.equal(managedInvocation.command, process.execPath)
assert.deepEqual(managedInvocation.prefix, ['-m', 'video2agent'])
process.env.VIDEO2AGENT_BIN = 'definitely-missing-video2agent-binary-xyz'
fs.rmSync(managedTools, { force: true })
const flagValue = (argv, flag) => argv[argv.indexOf(flag) + 1]
assert.equal(flagValue(commandArgs({ command: 'evidence', video_id: 'v', at: '00:10', images: 500 }), '--images'), '6')
assert.equal(flagValue(commandArgs({ command: 'evidence', video_id: 'v', at: '00:10', images: -3 }), '--images'), '0')
const batchEvidence = commandArgs({ command: 'evidence', video_id: 'v', at: '00:10,00:20', images: 2, max_images: 4 })
assert.equal(flagValue(batchEvidence, '--at'), '00:10,00:20')
assert.equal(flagValue(batchEvidence, '--max-images'), '4')
assert.equal(flagValue(commandArgs({ command: 'evidence', video_id: 'v', at: '00:10,00:20', max_images: 24 }), '--max-images'), '6')
const denseFrames = commandArgs({ command: 'frames', video_id: 'v', start: '00:00', end: '00:05', count: 3 })
assert.equal(flagValue(denseFrames, '--max'), '3')
assert.equal(flagValue(commandArgs({ command: 'discover', query: 'q', limit: 999 }), '--limit'), '50')
const digestArgv = commandArgs({ command: 'digest', video_id: 'v' })
assert.equal(digestArgv.includes('--max-chars'), true)
assert.equal(digestArgv.includes('--frames'), true)
assert.equal(digestArgv.includes('--compact'), true)
const cropArgv = commandArgs({ command: 'frames', video_id: 'v', at: '00:02', crop: '0,0,0.5,0.5', scale: 2 })
assert.equal(flagValue(cropArgv, '--crop'), '0,0,0.5,0.5')
assert.equal(flagValue(cropArgv, '--scale'), '2')
const denseArgv = commandArgs({ command: 'frames', video_id: 'v', start: '00:01', end: '00:03', fps: 5, max: 10, mode: 'change' })
assert.equal(flagValue(denseArgv, '--start'), '00:01')
assert.equal(flagValue(denseArgv, '--end'), '00:03')
assert.equal(flagValue(denseArgv, '--fps'), '5')
assert.equal(flagValue(denseArgv, '--max'), '10')
assert.equal(flagValue(denseArgv, '--mode'), 'change')
// A wait must fit inside the harness's per-program budget: a 200s wait made the
// whole program die with the wait half done (real turn 2026-11-15). The argv clamp
// is 90s, and a timed-out wait reports the worker mirror instead of a fake
// 'running' — a queued job used to look like it was making progress.
assert.equal(flagValue(commandArgs({ command: 'ingest', job_id: 'job_w', wait_ms: 200000 }), '--wait-timeout'), '90')
assert.equal(flagValue(commandArgs({ command: 'ingest', job_id: 'job_w', wait_ms: 5000 }), '--wait-timeout'), '5')
assert.equal(commandArgs({ command: 'ingest', job_id: 'job_w' }).includes('--wait'), false)
fs.mkdirSync(path.join(home, 'jobs'), { recursive: true })
fs.writeFileSync(path.join(home, 'jobs', 'job_queued.json'), JSON.stringify({
  ok: true, job: { id: 'job_queued', state: 'queued', stage: 'queued', progress: 0, message: '排队中：已有一个入库任务在运行' },
}))
const queuedWait = __test.timeoutPayload('job_queued', 45000)
assert.equal(queuedWait.state, 'queued', 'a queued wait must not report running')
assert.equal(queuedWait.stage, 'queued')
assert.match(queuedWait.note, /排队中/, 'the queued note must say the job has not started')
assert.equal(queuedWait.waited_ms, 45000)
fs.writeFileSync(path.join(home, 'jobs', 'job_running.json'), JSON.stringify({
  ok: true, job: { id: 'job_running', state: 'running', stage: 'ocr', progress: 0.4 },
}))
const runningWait = __test.timeoutPayload('job_running', 30000)
assert.equal(runningWait.state, 'running')
assert.equal(runningWait.stage, 'ocr')
assert.equal(runningWait.progress, 0.4)
assert.match(runningWait.note, /仍在处理/)
assert.equal(__test.timeoutPayload('job_missing', 30000).state, 'running', 'a missing mirror keeps the old default')
// An explicit ASR language is the only repair for a mis-detected transcript.
const langArgv = commandArgs({ command: 'ingest', source: 'https://www.bilibili.com/video/BV1xx411c7mD', language: 'zh' })
assert.equal(flagValue(langArgv, '--language'), 'zh')
assert.equal(commandArgs({ command: 'ingest', source: 'https://www.bilibili.com/video/BV1xx411c7mD' }).includes('--language'), false)
// Candidates: timecodes by default, one montage only when asked, and the id
// stays positional (splice would have made --images the video id).
const candidatesArgv = commandArgs({ command: 'candidates', video_id: 'v', query: 'fish', limit: 999 })
assert.equal(flagValue(candidatesArgv, '--limit'), '30')
assert.equal(flagValue(candidatesArgv, '--query'), 'fish')
assert.equal(candidatesArgv.includes('--images'), false)
const candidatesSheet = commandArgs({ command: 'candidates', video_id: 'v', include_images: true })
assert.equal(candidatesSheet.includes('--images'), true)
assert.equal(candidatesSheet[1], 'v', 'video_id must stay positional after --images')
// frames --sheet is one image for the window; --windows is a bounded range
// scan that must carry both edges (otherwise the CLI would guess a range).
const sheetFrames = commandArgs({ command: 'frames', video_id: 'v', start: '00:01', end: '00:04', sheet: true })
assert.equal(sheetFrames.includes('--sheet'), true)
// ocr-window needs both edges and passes the tiling switch only when asked.
const ocrWin = commandArgs({ command: 'ocr-window', video_id: 'v', start: '00:00:58', end: '00:01:02' })
assert.equal(flagValue(ocrWin, '--start'), '00:00:58')
assert.equal(flagValue(ocrWin, '--end'), '00:01:02')
assert.equal(ocrWin.includes('--tiles'), false)
const ocrWinTiles = commandArgs({ command: 'ocr-window', video_id: 'v', start: '00:00:58', end: '00:01:02', ocr_tiles: true })
assert.equal(ocrWinTiles.includes('--tiles'), true)
assert.equal(commandArgs({ command: 'ocr-window', video_id: 'v', start: '00:00:58' }), null)
// perceive: a number-only map (no --images), optional window, clamped fps, and
// it may run in the warm worker like the other read commands.
const perceiveArgv = commandArgs({ command: 'perceive', video_id: 'v', start: '00:01', end: '00:05', fps: 99 })
assert.equal(perceiveArgv[0], 'perceive')
assert.equal(perceiveArgv[1], 'v')
assert.equal(flagValue(perceiveArgv, '--start'), '00:01')
assert.equal(flagValue(perceiveArgv, '--end'), '00:05')
assert.equal(flagValue(perceiveArgv, '--fps'), '30')
assert.equal(perceiveArgv.includes('--images'), false, 'perceive must never return images')
assert.equal(commandArgs({ command: 'perceive' }), null, 'perceive needs a video_id')
assert.equal(pluginModule.__test.workerEligible({ command: 'perceive' }), true)

// Eight model-facing verbs: every one maps onto the same argv the old name
// produced, so the CLI surface stays the single implementation.
assert.equal(commandArgs({ command: 'find', query: 'q' })[0], 'discover')
assert.equal(commandArgs({ command: 'find', query: 'q', scope: 'library' })[0], 'search')
assert.equal(commandArgs({ command: 'find', url: 'https://b23.tv/abc' })[0], 'resolve')
assert.equal(commandArgs({ command: 'outline', video_id: 'v' })[0], 'digest')
assert.equal(commandArgs({ command: 'outline', video_id: 'v', detail: 'overview' })[0], 'overview')
assert.equal(commandArgs({ command: 'outline', video_id: 'v', detail: 'map' })[0], 'map')
assert.equal(commandArgs({ command: 'read', video_id: 'v' })[0], 'transcript')
assert.equal(commandArgs({ command: 'read', compare_video_ids: ['a', 'b'] })[0], 'compare')
assert.equal(commandArgs({ command: 'ingest', source: 'x' })[0], 'ingest')
assert.equal(commandArgs({ command: 'ingest', job_id: 'job_1', wait_ms: 4000 }).includes('--wait'), true)
assert.equal(commandArgs({ command: 'ingest' }), null, 'an ingest without a source is still an argument error')
assert.equal(commandArgs({ command: 'ingest', video_ids: ['a'] }), null, 'shortlist has no argv')
assert.equal(commandArgs({ command: 'ingest', campaign_id: 'campaign_abcdef12' }), null, 'campaign has no argv')
assert.equal(commandArgs({ command: 'frames', video_id: 'v', view: 'candidates' })[0], 'candidates')
assert.equal(commandArgs({ command: 'frames', video_id: 'v', view: 'ocr', start: '00:01', end: '00:02' })[0], 'ocr-window')
assert.equal(commandArgs({ command: 'frames', video_id: 'v', at: '00:03' })[0], 'frames')
assert.equal(commandArgs({ command: 'admin' })[0], 'list')
assert.equal(commandArgs({ command: 'admin', admin_action: 'doctor' })[0], 'doctor')
assert.equal(commandArgs({ command: 'admin', admin_action: 'export', video_id: 'v' })[0], 'export')
assert.equal(pluginModule.__test.workerEligible({ command: 'outline' }), true, 'read verbs must be worker-eligible')
// Behaviour parity: the verb must produce byte-identical argv to the internal
// command it replaces. The CLI is untouched, so identical argv means identical
// output, not merely similar output.
assert.deepEqual(commandArgs({ command: 'find', query: 'q', limit: 3 }), commandArgs({ command: 'discover', query: 'q', limit: 3 }))
assert.deepEqual(commandArgs({ command: 'find', query: 'q', scope: 'library' }), commandArgs({ command: 'search', query: 'q' }))
assert.deepEqual(commandArgs({ command: 'outline', video_id: 'v' }), commandArgs({ command: 'digest', video_id: 'v' }))
assert.deepEqual(commandArgs({ command: 'outline', video_id: 'v', detail: 'overview' }), commandArgs({ command: 'overview', video_id: 'v' }))
assert.deepEqual(commandArgs({ command: 'read', video_id: 'v', start: '00:01' }), commandArgs({ command: 'transcript', video_id: 'v', start: '00:01' }))
assert.deepEqual(commandArgs({ command: 'ingest', job_id: 'j1', wait_ms: 4000 }), commandArgs({ command: 'jobs', job_id: 'j1', wait_ms: 4000 }))
assert.deepEqual(commandArgs({ command: 'frames', video_id: 'v', view: 'ocr', start: '00:01', end: '00:02' }),
  commandArgs({ command: 'ocr-window', video_id: 'v', start: '00:01', end: '00:02' }))
assert.deepEqual(commandArgs({ command: 'admin', admin_action: 'export', video_id: 'v' }), commandArgs({ command: 'export', video_id: 'v' }))
assert.deepEqual(commandArgs({ command: 'admin', admin_action: 'doctor' }), commandArgs({ command: 'doctor' }))
assert.equal(pluginModule.__test.workerEligible({ command: 'ocr-window' }), true,
  'ocr-window should run in the warm worker')
const windowsFrames = commandArgs({ command: 'frames', video_id: 'v', start: '00:01', end: '00:04', windows: 6 })
assert.equal(flagValue(windowsFrames, '--windows'), '6')
assert.equal(flagValue(windowsFrames, '--start'), '00:01')
assert.equal(flagValue(windowsFrames, '--end'), '00:04')
assert.equal(commandArgs({ command: 'frames', video_id: 'v', windows: 6 }), null, 'windows needs start/end')
const fastDiscover = commandArgs({ command: 'discover', query: 'q' })
assert.equal(fastDiscover.includes('--no-covers'), true, 'discover must skip cover OCR by default')
const visualDiscover = commandArgs({ command: 'discover', query: 'q', covers: true })
assert.equal(visualDiscover.includes('--no-covers'), false, 'covers:true must opt into cover OCR')

// The five contract defects a model-facing review found. Each one used to fail
// silently: a crash, an empty image list, an extra image, a doctor run, or a gate
// with no way through.
assert.equal(commandArgs({ command: 'discover' }), null, 'a discover without a query must be an argument error, not a doctor run')
assert.equal(commandArgs({ command: 'ingest' }), null, 'an ingest without a source must be an argument error')
assert.equal(commandArgs({ command: 'overview' }), null, 'an overview without a video id must be an argument error')
const waited = commandArgs({ command: 'jobs', job_id: 'j1', wait_ms: 300000 })
assert.ok(Array.isArray(waited) && waited.includes('--wait'), 'jobs --wait_ms must build an argv (it used to throw ReferenceError)')
// 90s, not 300s: a single wait must fit inside the harness's per-program budget
// (~120s). A 300s wait died with the program and the wait was lost (2026-11-15).
assert.equal(flagValue(waited, '--wait-timeout'), '90')
// The model must not be able to certify a user's shortlist choice: confirmation is
// the card route's job. A `confirm` argument here would be a one-flag bypass.
assert.equal(commandArgs({ command: 'ingest', source: 'x', confirm: true }).includes('--confirm'), false,
  'the ingest tool must never forward a model-supplied confirmation')
// Account writes are CLI-only. The tool must never forward a model-supplied
// confirm:true; a hostile transcript could otherwise create folders/add videos.
const accountFolders = commandArgs({ command: 'account', account_action: 'folders' })
assert.deepEqual(accountFolders, ['account', 'folders', '--json'])
assert.equal(commandArgs({
  command: 'account', account_action: 'create-folder', title: '新夹', public: true, confirm: true,
}), null, 'account writes must not be callable through the tool')
assert.equal(commandArgs({
  command: 'account', account_action: 'classify-apply', plan: { folders: [{ title: 'x', videos: ['BV1'] }] },
}), null, 'classify-apply must not be callable through the tool')
assert.equal(commandArgs({ command: 'account', account_action: 'nope' }), null)
// A video id must never become an option. Without this, ["BV1", "--confirm"]
// reaches argparse's `--videos nargs='+'` and confirms a write even when the
// caller passed confirm:false.
assert.equal(commandArgs({
  command: 'account', account_action: 'add', folder_id: 1, videos: ['BV1', '--confirm'], confirm: false,
}), null, 'a leading-dash video id must be rejected')
assert.equal(commandArgs({
  command: 'account', account_action: 'add', folder_id: 1, videos: new Array(201).fill('BV1'), confirm: true,
}), null, 'more than 200 videos must be an argument error, not a silent slice')
const accountHistory = commandArgs({ command: 'account', account_action: 'analyze', account_source: 'history' })
assert.equal(flagValue(accountHistory, '--source'), 'history')
assert.equal(flagValue(commandArgs({ command: 'account', account_action: 'analyze', source: 'history' }), '--source'), 'history')
assert.equal(commandArgs({ command: 'account', account_action: 'analyze', source: 'C:\\tmp\\x' }), null)
assert.equal(flagValue(commandArgs({ command: 'account', account_action: 'favorites', folder_id: 1, limit: 500 }), '--limit'), '50',
  'account reads must stay under the 60k tool output cap')
assert.equal(commandArgs({ command: 'account', account_action: 'favorites', folder_id: 1 }).includes('--limit'), false)
const frameArgv = commandArgs({ command: 'frames', video_id: 'v', at: '00:03', count: 3 })
assert.equal(frameArgv.includes('--format'), false, 'frames must not take the export format flag')
assert.equal(flagValue(frameArgv, '--count'), '3')
const mapArgv = commandArgs({ command: 'map', video_id: 'v', limit: 200, start: '00:30:00', end: '00:40:00' })
assert.equal(flagValue(mapArgv, '--limit'), '200', 'map must forward --limit; otherwise a 1h record is capped at 50 rows')
assert.equal(flagValue(mapArgv, '--start'), '00:30:00', 'map must forward the continuation start')
assert.equal(flagValue(mapArgv, '--end'), '00:40:00', 'map must forward the range end')
assert.deepEqual(commandArgs({ command: 'evidence', video_id: 'v', start: '00:01', end: '00:02', images: 0 }),
  ['evidence', 'v', '--start', '00:01', '--end', '00:02', '--images', '0', '--json'])

// Ingest carries no "how much work" flags at all: the pipeline does captions-or-ASR
// and reads a frame's text when that frame is asked for. Neither a settings file, a
// plugin Config, nor a stray `profile` argument may reintroduce a knob.
const plain = commandArgs({ command: 'ingest', source: 'x' })
assert.equal(plain.includes('--profile'), false, 'ingest must not pass a profile')
assert.equal(plain.includes('--ocr-budget'), false, 'ingest must not pass an OCR budget')
assert.equal(commandArgs({ command: 'ingest', source: 'x', profile: 'deep' }).includes('--profile'), false, 'a profile argument must not come back')
fs.writeFileSync(path.join(home, 'ui-settings.json'), JSON.stringify({ defaultProfile: 'deep', ocrBudget: 30 }), 'utf8')
const afterFile = commandArgs({ command: 'ingest', source: 'x' })
assert.equal(afterFile.includes('--profile'), false, 'a stale file must not add a profile')
assert.equal(afterFile.includes('--ocr-budget'), false, 'a stale file must not add an OCR budget')

// The plugin Config cannot reintroduce them either.
fs.rmSync(path.join(home, 'ui-settings.json'), { force: true })
apply({ ...ctx, get(name) { return name === 'tools' ? { register() {} } : undefined } }, { defaultProfile: 'fast', ocrBudget: 120 })
const fromConfig = commandArgs({ command: 'ingest', source: 'x' })
assert.equal(fromConfig.includes('--profile'), false, 'a Config profile must not come back')
assert.equal(fromConfig.includes('--ocr-budget'), false, 'a Config OCR budget must not come back')
assert.equal(registeredTool.parameters.properties.profile, undefined, 'the tool must not expose a profile')

// The frame route is the riskiest surface: it streams files from the derived dir.
fs.mkdirSync(path.join(home, 'derived', 'vid_x', 'frames'), { recursive: true })
const goodFrame = path.join(home, 'derived', 'vid_x', 'frames', 'frame_00000.jpg')
fs.writeFileSync(goodFrame, Buffer.from([0xff, 0xd8, 0xff, 0xd9]))
const secret = path.join(home, 'secret.txt')
fs.writeFileSync(secret, 'not a frame')
const traversal = await call('GET', undefined, { path: '/api/video2agent/frame', url: `/api/video2agent/frame?path=${encodeURIComponent(secret)}` })
assert.equal(traversal.status, 403, 'a real file outside derived/ must be refused')
const outside = await call('GET', undefined, { path: '/api/video2agent/frame', url: '/api/video2agent/frame?path=' + encodeURIComponent('C:\\Windows\\win.ini') })
assert.ok([403, 404].includes(outside.status), 'absolute paths outside derived/ must be refused')
const okFrame = await call('GET', undefined, { path: '/api/video2agent/frame', url: `/api/video2agent/frame?path=${encodeURIComponent(goodFrame)}` })
assert.equal(okFrame.status, 200, 'a real frame inside derived/ must be served')
// New links use an opaque id so the URL never carries an absolute path.
const byId = await call('GET', undefined, { path: '/api/video2agent/frame', url: '/api/video2agent/frame?id=' + encodeURIComponent('vid_x/frame_00000.jpg') })
assert.equal(byId.status, 200, 'an opaque frame id must be served')
// The live desktop points .video2agent at .vidproof with a junction. The frame
// route must resolve the derived root before checking containment, or a real
// frame resolves to .vidproof/... and is rejected as outside .video2agent/....
const realDerived = fs.mkdtempSync(path.join(os.tmpdir(), 'vp-real-derived-'))
fs.mkdirSync(path.join(realDerived, 'vid_junction', 'frames'), { recursive: true })
fs.writeFileSync(path.join(realDerived, 'vid_junction', 'frames', 'frame.jpg'), Buffer.from([0xff, 0xd8, 0xff, 0xd9]))
const junctionHome = fs.mkdtempSync(path.join(os.tmpdir(), 'vp-junction-home-'))
fs.symlinkSync(realDerived, path.join(junctionHome, 'derived'), process.platform === 'win32' ? 'junction' : 'dir')
process.env.VIDEO2AGENT_HOME = junctionHome
try {
  const viaJunction = await call('GET', undefined, { path: '/api/video2agent/frame', url: '/api/video2agent/frame?id=' + encodeURIComponent('vid_junction/frame.jpg') })
  assert.equal(viaJunction.status, 200, 'a frame through a junctioned derived root must be served')
} finally {
  process.env.VIDEO2AGENT_HOME = home
}
const badId = await call('GET', undefined, { path: '/api/video2agent/frame', url: '/api/video2agent/frame?id=' + encodeURIComponent('vid_x/../secret.txt') })
assert.ok([400, 403, 404].includes(badId.status), 'a frame id that escapes the frames dir must be refused')
// A directory named *.jpg used to send 200 then crash the host with EISDIR.
fs.mkdirSync(path.join(home, 'derived', 'vid_x', 'frames', 'dir.jpg'), { recursive: true })
const dirFrame = await call('GET', undefined, { path: '/api/video2agent/frame', url: '/api/video2agent/frame?id=' + encodeURIComponent('vid_x/dir.jpg') })
assert.equal(dirFrame.status, 404, 'a directory must never be streamed as a frame')
// A UNC path must be refused before realpathSync could contact SMB.
const uncFrame = await call('GET', undefined, { path: '/api/video2agent/frame', url: '/api/video2agent/frame?path=' + encodeURIComponent('\\\\attacker\\share\\x.jpg') })
assert.equal(uncFrame.status, 403, 'a UNC path must be refused')
// The URL the model may copy carries only `<video_id>/<file>`, never a local path.
const { frameUrlFor, doctorFailure, redactTextPaths } = pluginModule.__test
const redacted = redactTextPaths({ source: { uri: 'C:\\Users\\me\\video.mp4' }, url: 'https://x/y', nested: ['/home/me/a.jpg'] })
assert.equal(redacted.source.uri, 'video.mp4', 'a local overview path must not reach the model')
assert.equal(redacted.url, 'https://x/y')
assert.equal(redacted.nested[0], 'a.jpg')
const embedded = redactTextPaths({ detail: '58.9 GB free at C:/Users/me/.vidproof', note: 'path /home/me/a.jpg here' })
assert.equal(embedded.detail, '58.9 GB free at .vidproof', 'an embedded drive path must be reduced to its basename')
assert.equal(embedded.note, 'path a.jpg here')
const doctorParsed = doctorFailure(JSON.stringify({ ok: false, required_ok: false, checks: [
  { name: 'python', ok: true, required: true },
  { name: 'ffmpeg', ok: false, required: true, detail: 'not found', remedy: 'install ffmpeg' },
] }))
assert.equal(doctorParsed.code, 'E_DOCTOR')
assert.match(doctorParsed.message, /ffmpeg/)
assert.equal(doctorParsed.remedy, 'install ffmpeg')
const frameUrl = frameUrlFor('vid_x', 'C:\\Users\\me\\derived\\vid_x\\frames\\frame_00000.jpg')
// The model's markdown renderer only accepts absolute http(s) images: a
// root-relative URL is treated as a local path and renders as 无法预览.
assert.match(frameUrl, /^https:\/\/qa\.example\/api\/video2agent\/frame\?id=/, 'a frame url must be absolute when the origin is known')
// A cross-site <img> (the desktop shell's dsh-app://app page) may read a frame;
// every other cross-site read stays refused.
const crossImg = await call('GET', undefined, {
  path: '/api/video2agent/frame',
  url: '/api/video2agent/frame?id=' + encodeURIComponent('vid_x/frame_00000.jpg'),
  headers: { 'sec-fetch-site': 'cross-site', 'sec-fetch-dest': 'image', 'sec-fetch-mode': 'no-cors' },
})
assert.equal(crossImg.status, 200, 'a cross-site image read of a frame must be served')
const crossNoDest = await call('GET', undefined, {
  path: '/api/video2agent/frame',
  url: '/api/video2agent/frame?id=' + encodeURIComponent('vid_x/frame_00000.jpg'),
  headers: { 'sec-fetch-site': 'cross-site', 'sec-fetch-dest': 'document' },
})
assert.equal(crossNoDest.status, 403, 'a cross-site non-image read must stay refused')
const crossFrameFetch = await call('GET', undefined, {
  path: '/api/video2agent/frame',
  url: '/api/video2agent/frame?path=' + encodeURIComponent('\\\\attacker\\share\\x.jpg'),
  headers: { 'sec-fetch-site': 'cross-site', 'sec-fetch-dest': 'image' },
})
assert.equal(crossFrameFetch.status, 403, 'the image allowance must not relax a UNC path')
assert.ok(frameUrl.includes('?id='), 'frame urls must use the opaque id')
assert.ok(!frameUrl.includes('Users'), 'a frame url must not carry an absolute path')
assert.equal(decodeURIComponent(frameUrl.split('id=')[1]), 'vid_x/frame_00000.jpg')


// The image allowance is only for /frame: every other read route must still
// refuse a cross-site GET that claims to be an image.
for (const pathname of ['/api/video2agent/job', '/api/video2agent/settings', '/api/video2agent/cover']) {
  const probe = await call('GET', undefined, {
    path: pathname,
    url: pathname + (pathname.endsWith('/cover') ? '?u=https%3A%2F%2Fi0.hdslb.com%2Fx.jpg' : '?id=job_x'),
    headers: { 'sec-fetch-site': 'cross-site', 'sec-fetch-dest': 'image' },
  })
  assert.equal(probe.status, 403, pathname + ' must stay closed to cross-site image reads')
}

// A corrupt settings file is an error, not defaults; a read failure (EACCES/EISDIR)
// must not be reported as "not valid JSON" with advice to delete the file.
{
  const settingsFile = path.join(home, 'ui-settings.json')
  const saved = fs.existsSync(settingsFile) ? fs.readFileSync(settingsFile, 'utf8') : null
  fs.writeFileSync(settingsFile, '{ not json', 'utf8')
  const corrupt = await call('GET', undefined, { path: '/api/video2agent/settings' })
  assert.equal(corrupt.status, 500)
  assert.equal(JSON.parse(corrupt.body).code, 'E_SETTINGS_CORRUPT')
  fs.rmSync(settingsFile, { force: true })
  fs.mkdirSync(settingsFile)
  try {
    const io = await call('GET', undefined, { path: '/api/video2agent/settings' })
    assert.equal(io.status, 500)
    const ioBody = JSON.parse(io.body)
    assert.equal(ioBody.code, 'E_SETTINGS_IO', 'a read failure must not be called corrupt: ' + io.body)
    assert.match(String(ioBody.remedy), /permission|lock/i)
  } finally {
    fs.rmSync(settingsFile, { recursive: true, force: true })
    if (saved !== null) fs.writeFileSync(settingsFile, saved, 'utf8')
  }
}
// The job card polls /job once a second. A fresh sidecar is served without a CLI
// start; a running mirror older than 15s must fall through to the CLI so a dead
// worker is reconciled instead of shown as "running" for two minutes. A queued
// job writes once, so it keeps the longer grace period.
fs.mkdirSync(path.join(home, 'jobs'), { recursive: true })
function writeSidecar(id, state, ageMs) {
  const file = path.join(home, 'jobs', id + '.json')
  fs.writeFileSync(file, JSON.stringify({ ok: true, job: { id, state, stage: state } }), 'utf8')
  const stamp = new Date(Date.now() - ageMs)
  fs.utimesSync(file, stamp, stamp)
}
async function pollJob(id) {
  return JSON.parse((await call('GET', undefined, { path: '/api/video2agent/job', url: '/api/video2agent/job?id=' + id })).body)
}
// A future mtime keeps "just written" deterministic: on a loaded machine the gap
// between the write and the poll could exceed the 15s staleness line and the test
// failed for scheduling, not for behaviour.
writeSidecar('job_fresh', 'running', -60000)
const fresh = await pollJob('job_fresh')
assert.equal(fresh.ok, true)
assert.equal(fresh.source, 'sidecar', 'a 1s-old sidecar should be served directly')
writeSidecar('job_queued', 'queued', 16000)
const queued = await pollJob('job_queued')
assert.equal(queued.source, 'sidecar', 'a queued job writes once and keeps the long grace period')
// The batch table polls with overview=0; it already has title/cover and must not
// spawn a Python overview process on every 2s tick.
fs.writeFileSync(path.join(home, 'jobs', 'job_noov.json'), JSON.stringify({
  ok: true, job: { id: 'job_noov', state: 'running', stage: 'ocr', video_id: 'vid_noov' },
}), 'utf8')
{
  const stamp = new Date(Date.now() + 60000)
  fs.utimesSync(path.join(home, 'jobs', 'job_noov.json'), stamp, stamp)
}
const noOverview = JSON.parse((await call('GET', undefined, {
  path: '/api/video2agent/job',
  url: '/api/video2agent/job?id=job_noov&overview=0',
})).body)
assert.equal(noOverview.source, 'sidecar')
assert.equal(noOverview.overview, null, 'overview=0 must skip the overview spawn')
writeSidecar('job_stale', 'running', 16000)
process.env.VIDEO2AGENT_BIN = 'definitely-missing-video2agent-binary-xyz'
const stale = await call('GET', undefined, { path: '/api/video2agent/job', url: '/api/video2agent/job?id=job_stale' })
assert.equal(stale.status, 404, 'a running sidecar older than 15s must fall back to the CLI')
process.env.VIDEO2AGENT_BIN = 'video2agent'

// shortlist validates the model's choice, then the Host starts the selected
// videos itself and returns their rows. The spawn contract is exercised with an
// injected runner; the tool path below uses a missing binary so no real job runs.
fs.mkdirSync(path.join(home, 'discovery'), { recursive: true })
const slCandidates = [
  { candidate_id: 'bili_A', video_id: 'BV1aaaaaaaa1', title: '甲视频', uploader: '阿甲', duration_ms: 100000, published_at: '2026-10-01', stats: { play: 1000 }, match: { score: 0.9 } },
  { candidate_id: 'bili_B', video_id: 'BV1bbbbbbbb1', title: '乙视频', uploader: '阿乙', duration_ms: 200000, published_at: '2026-10-02', stats: { play: 2000 }, match: { score: 0.8 } },
  { candidate_id: 'bili_C', video_id: 'BV1cccccccc1', title: '丙视频', uploader: '阿丙', duration_ms: 300000, published_at: '2026-10-03', stats: { play: 3000 }, match: { score: 0.7 } },
]
fs.writeFileSync(__test.discoveryLastPath(''), JSON.stringify({ at: Date.now(), query: '大模型评测', candidates: slCandidates }), 'utf8')
process.env.VIDEO2AGENT_BIN = 'definitely-missing-video2agent-binary-xyz'
const shortlist = await registeredTool.execute({ command: 'shortlist', video_ids: ['BV1aaaaaaaa1', 'BV1bbbbbbbb1'], default_selected: ['BV1aaaaaaaa1'], primary: 'BV1aaaaaaaa1', reasons: { BV1aaaaaaaa1: '最相关' } })
assert.equal(shortlist.ok, false, 'a missing CLI must fail the start, not fake success')
assert.equal(shortlist.error.code, 'E_START')
assert.match(shortlist.error.remedy, /video2agent CLI/)
const failedStatus = JSON.parse(fs.readFileSync(path.join(home, 'discovery', 'status.json'), 'utf8'))
assert.equal(failedStatus.phase, 'error', 'a failed start must leave a visible search error')

// The model-facing verb is `find`; the CLI command it maps to is `discover`.
// The Host must still persist the offered candidates, otherwise the follow-up
// ingest video_ids fails with E_NO_DISCOVERY and no batch — and no dock table —
// ever starts. A tiny fake CLI keeps this off the network.
{
  const fakeDir = fs.mkdtempSync(path.join(os.tmpdir(), 'vp-fake-cli-'))
  const discoverPayload = {
    ok: true,
    query: 'fake query',
    candidates: [{
      candidate_id: 'bili_BV1fake00001',
      platform: 'bilibili',
      video_id: 'BV1fake00001',
      url: 'https://www.bilibili.com/video/BV1fake00001',
      title: '假视频',
      uploader: '假 UP',
      duration_ms: 120000,
      published_at: '2026-11-01',
      cover_url: 'http://i0.hdslb.com/bfs/archive/fake.jpg',
      stats: { play: 42 },
    }, {
      candidate_id: 'bili_BV1fake00002',
      platform: 'bilibili',
      video_id: 'BV1fake00002',
      url: 'https://www.bilibili.com/video/BV1fake00002',
      title: '未选假视频',
      uploader: '假 UP 2',
      duration_ms: 60000,
      published_at: '2026-11-02',
      cover_url: 'http://i0.hdslb.com/bfs/archive/fake2.jpg',
      stats: { play: 7 },
    }],
  }
  fs.writeFileSync(path.join(fakeDir, 'discover'), 'process.stdout.write(' + JSON.stringify(JSON.stringify(discoverPayload)) + ')', 'utf8')
  fs.writeFileSync(path.join(fakeDir, 'ingest'), 'process.stdout.write(' + JSON.stringify(JSON.stringify({ ok: true, job_id: 'job_fake_find', state: 'running' })) + ')', 'utf8')
  const cwdBeforeFake = process.cwd()
  // A warm worker started by an earlier real-CLI case keeps its own binary, so
  // stop it before pointing the tool at the fake CLI.
  pluginModule.__test.stopWorker()
  process.chdir(fakeDir)
  try {
    process.env.VIDEO2AGENT_BIN = process.execPath
    const found = await registeredTool.execute({ command: 'find', query: 'fake query' }, { agent: { session: { id: 'sess-find' } } })
    assert.equal(found.ok, true, 'a find call must succeed: ' + String(found.text).slice(0, 300))
    const last = JSON.parse(fs.readFileSync(__test.discoveryLastPath('sess-find'), 'utf8'))
    assert.equal(last.candidates[0].video_id, 'BV1fake00001', 'find must persist its candidates for the shortlist')
    const curating = JSON.parse(fs.readFileSync(path.join(home, 'discovery', 'status.json'), 'utf8'))
    assert.equal(curating.phase, 'curating', 'find must publish the curating state')

    const started = await registeredTool.execute({
      command: 'ingest',
      video_ids: ['BV1fake00001', 'BV1fake00002'],
      default_selected: ['BV1fake00001'],
      primary: 'BV1fake00001',
    }, { agent: { session: { id: 'sess-find' } } })
    assert.equal(started.ok, true, 'ingest video_ids must start from the find result: ' + String(started.text).slice(0, 300))
    const startedPayload = JSON.parse(started.text)
    assert.equal(startedPayload.state, 'started')
    assert.equal(startedPayload.jobs[0].job_id, 'job_fake_find')
    // Only default_selected starts; the rest must be named, or the model thinks
    // it already started and later ingests it alone (the reported ghost row).
    assert.deepEqual(startedPayload.not_started, ['BV1fake00002'], 'unselected video_ids must be reported')
    // The model often copies candidate_id ("bili_BV...") into both fields; the
    // report must still be normalised to video_id, or every id looks unstarted.
    const byCandidate = await registeredTool.execute({
      command: 'ingest',
      video_ids: ['bili_BV1fake00001', 'bili_BV1fake00002'],
      default_selected: ['bili_BV1fake00001'],
      primary: 'bili_BV1fake00001',
    }, { agent: { session: { id: 'sess-find' } } })
    assert.equal(byCandidate.ok, true, String(byCandidate.text).slice(0, 200))
    const candidatePayload = JSON.parse(String(byCandidate.text))
    assert.deepEqual(candidatePayload.not_started, ['BV1fake00002'],
      'candidate_id input must be normalised before the not_started comparison')
    const queueKey = createHash('sha256').update('sess-find').digest('hex').slice(0, 32)
    const queue = JSON.parse(fs.readFileSync(path.join(home, 'ui-queue', queueKey + '.json'), 'utf8'))
    assert.equal(queue.jobs[0].video_id, 'BV1fake00001', 'the dock queue must receive the started row')
  } finally {
    process.chdir(cwdBeforeFake)
    process.env.VIDEO2AGENT_BIN = 'definitely-missing-video2agent-binary-xyz'
  }
}


// A wait that times out is a normal poll answer, not a tool failure. The CLI's
// E_TIMEOUT envelope used to be flattened to 'Job still running', so the model's
// JSON.parse threw and aborted the turn (reproduced through the tool).
{
  const dir = fs.mkdtempSync(path.join(os.tmpdir(), 'vp-wait-cli-'))
  const envelope = JSON.stringify({ ok: false, error: { code: 'E_TIMEOUT', message: 'Job still running after 5s', remedy: 'poll again' } })
  fs.writeFileSync(path.join(dir, 'jobs'), 'process.stdout.write(' + JSON.stringify(envelope) + '); process.exit(1)', 'utf8')
  const before = process.cwd()
  pluginModule.__test.stopWorker()
  process.chdir(dir)
  try {
    process.env.VIDEO2AGENT_BIN = process.execPath
    const stillRunning = await registeredTool.execute({
      command: 'ingest',
      job_id: 'job_wait',
      wait_ms: 5000,
    }, { agent: { session: { id: 'sess-wait' } } })
    assert.equal(stillRunning.ok, true, 'a timed-out wait must not be a failure: ' + String(stillRunning.text).slice(0, 200))
    const stillPayload = JSON.parse(String(stillRunning.text))
    assert.equal(stillPayload.still_running, true)
    assert.equal(stillPayload.job_id, 'job_wait')
    assert.equal(stillPayload.state, 'running')
  } finally {
    process.chdir(before)
    process.env.VIDEO2AGENT_BIN = 'definitely-missing-video2agent-binary-xyz'
  }
}
// PTC sessions call shortlist through run_code, so no Card mounts. The Host
// persists the started rows and the dock reads them through this route.
{
  const sid = 'session-queue-test'
  const queueKey = createHash('sha256').update(sid).digest('hex').slice(0, 32)
  fs.mkdirSync(path.join(home, 'ui-queue'), { recursive: true })
  fs.writeFileSync(path.join(home, 'ui-queue', queueKey + '.json'), JSON.stringify({
    session_id: sid,
    batch_id: 'batch_queue_test',
    started_at: Date.now(),
    jobs: [{ video_id: 'BV1queue', job_id: 'job_queue', title: '队列视频', cover_url: 'http://i0.hdslb.com/a.jpg', state: 'running' }],
  }), 'utf8')
  const own = await call('GET', undefined, { path: '/api/video2agent/queue', url: '/api/video2agent/queue?session=' + encodeURIComponent(sid) })
  assert.equal(own.status, 200)
  const ownQueue = JSON.parse(own.body).queue
  assert.equal(ownQueue.jobs.length, 1)
  // The snapshot is written once at start; a finished job must not keep reporting
  // "running" when the conversation is reopened (reported: the batch card stayed
  // on 正在处理 after the task had ended).
  fs.mkdirSync(path.join(home, 'jobs'), { recursive: true })
  fs.writeFileSync(path.join(home, 'jobs', 'job_queue.json'), JSON.stringify({
    ok: true,
    job: { id: 'job_queue', state: 'ready', stage: 'done', progress: 1, updated_at: new Date().toISOString() },
  }), 'utf8')
  const refreshed = await call('GET', undefined, { path: '/api/video2agent/queue', url: '/api/video2agent/queue?session=' + encodeURIComponent(sid) })
  const refreshedRow = JSON.parse(refreshed.body).queue.jobs[0]
  assert.equal(refreshedRow.state, 'ready', 'a finished job must not stay running in the dock snapshot')
  assert.equal(refreshedRow.title, '队列视频', 'the refresh must keep the row metadata')
  // An unreadable mirror leaves the row exactly as stored; a failed mirror wins.
  fs.writeFileSync(path.join(home, 'jobs', 'job_queue.json'), 'not json', 'utf8')
  const unreadable = JSON.parse((await call('GET', undefined, { path: '/api/video2agent/queue', url: '/api/video2agent/queue?session=' + encodeURIComponent(sid) })).body).queue.jobs[0]
  // The snapshot itself stored "running"; an unreadable mirror must leave it there.
  assert.equal(unreadable.state, 'running', 'an unreadable mirror must not change the row')
  fs.writeFileSync(path.join(home, 'jobs', 'job_queue.json'), JSON.stringify({
    ok: true, job: { id: 'job_queue', state: 'failed', stage: 'failed', error_code: 'E_DOWNLOAD' },
  }), 'utf8')
  const failedRow = JSON.parse((await call('GET', undefined, { path: '/api/video2agent/queue', url: '/api/video2agent/queue?session=' + encodeURIComponent(sid) })).body).queue.jobs[0]
  assert.equal(failedRow.state, 'failed', 'a failed mirror must reach the row')
  assert.equal(failedRow.error_code, 'E_DOWNLOAD')
  assert.equal(ownQueue.jobs[0].job_id, 'job_queue')
  assert.equal(ownQueue.batch_id, 'batch_queue_test')
  const other = await call('GET', undefined, { path: '/api/video2agent/queue', url: '/api/video2agent/queue?session=another-session' })
  assert.equal(JSON.parse(other.body).queue, null, 'a queue must not leak to another session')
}

// The Host-start contract: only default_selected rows start, every spawn carries
// the confirm token and detach, and a repeated batch reuses the jobs.
const { startShortlistJobs, resetShortlistStarts } = pluginModule.__test
resetShortlistStarts()
const calls = []
const fakeRun = async (args) => {
  calls.push(args)
  return { code: 0, out: JSON.stringify({ ok: true, job_id: 'job_' + calls.length, state: 'running' }), err: '' }
}
const selected = [
  { video_id: 'BV1aaaaaaaa1', checked: true, title: '甲视频', uploader: '阿甲', duration_ms: 100000, cover_url: 'https://example.com/a.jpg', primary: true, reason: '最相关' },
  { video_id: 'BV1bbbbbbbb1', checked: false, title: '乙视频' },
]
const started = await startShortlistJobs(selected, fakeRun)
assert.equal(started.jobs.length, 1, 'only default_selected should start')
assert.equal(calls.length, 1)
assert.equal(calls[0][0], 'ingest')
assert.ok(calls[0].includes('--confirm-token'), 'the Host must pass a confirm token')
assert.ok(calls[0].includes('--detach'), 'the Host must detach the worker')
assert.equal(started.jobs[0].title, '甲视频')
assert.equal(started.jobs[0].primary, true)
assert.equal(started.jobs[0].origin, 'shortlist')
assert.equal(started.jobs[0].reason, '最相关')
const reused = await startShortlistJobs(selected, fakeRun)
assert.equal(calls.length, 1, 'a retried shortlist must not spawn the batch twice')
assert.equal(reused.reused, true)
// A batch of two must issue two single-use tokens: the CLI deletes confirm.json
// on the first accepted ingest, so a shared token would fail the second video.
resetShortlistStarts()
const multiCalls = []
const multiRun = async (args) => {
  multiCalls.push(args)
  return { code: 0, out: JSON.stringify({ ok: true, job_id: 'job_m' + multiCalls.length, state: 'running' }), err: '' }
}
const multi = await startShortlistJobs([
  { video_id: 'BV1multiaa1', checked: true, title: '多一' },
  { video_id: 'BV1multibb1', checked: true, title: '多二' },
], multiRun)
assert.equal(multi.jobs.length, 2, 'both selected videos must start')
assert.equal(multiCalls.length, 2)
const tokens = multiCalls.map((args) => args[args.indexOf('--confirm-token') + 1])
assert.equal(new Set(tokens).size, 2, 'each video needs its own single-use confirm token')
const reordered = await startShortlistJobs([
  { video_id: 'BV1multibb1', checked: true, title: '多二' },
  { video_id: 'BV1multiaa1', checked: true, title: '多一' },
], multiRun)
assert.equal(multiCalls.length, 2, 'a reordered retry must reuse the batch')
assert.equal(reordered.reused, true)
// A partial batch must keep its failure in the idempotency cache; otherwise a
// retried shortlist reports only the started job and hides the missing video.
resetShortlistStarts()
let partialCalls = 0
const partialRun = async () => {
  partialCalls += 1
  return partialCalls === 1
    ? { code: 0, out: JSON.stringify({ ok: true, job_id: 'job_p1', state: 'running' }), err: '' }
    : { code: 1, out: '', err: 'second failed' }
}
const partialSelected = [
  { video_id: 'BV1partaa1', checked: true, title: '部分一' },
  { video_id: 'BV1partbb1', checked: true, title: '部分二' },
]
const partial = await startShortlistJobs(partialSelected, partialRun)
assert.equal(partial.jobs.length, 1)
assert.equal(partial.failed.length, 1, 'the failed video must be reported')
assert.match(partial.failed[0].error_message, /second failed/)
const partialRetry = await startShortlistJobs(partialSelected, partialRun)
assert.equal(partialCalls, 2, 'the retry must reuse the started job')
assert.equal(partialRetry.jobs.length, 1)
assert.equal(partialRetry.failed.length, 1, 'the partial failure must survive the idempotency cache')
resetShortlistStarts()
const failRun = async () => ({ code: 1, out: '', err: 'boom' })
const failedStart = await startShortlistJobs([{ video_id: 'BV1cccccccc1', checked: true, title: '丙' }], failRun)
assert.equal(failedStart.jobs.length, 0)
assert.equal(failedStart.failed[0].state, 'failed')
assert.match(failedStart.failed[0].error_message, /boom/)
// A real CLI prints its error envelope to stdout; the row must keep the code.
resetShortlistStarts()
const structuredFail = async () => ({ code: 1, out: JSON.stringify({ ok: false, error: { code: 'E_ASR_NOT_CONFIGURED', message: 'no asr model', remedy: 'download one' } }), err: '' })
const structuredFailed = await startShortlistJobs([{ video_id: 'BV1structured1', checked: true, title: 'structured' }], structuredFail)
assert.equal(structuredFailed.failed[0].error_code, 'E_ASR_NOT_CONFIGURED')
assert.match(structuredFailed.failed[0].error_message, /no asr model/)
assert.equal(structuredFailed.failed[0].remedy, 'download one')

// Search status route: one conversation claims the line; another sees nothing.
fs.writeFileSync(path.join(home, 'discovery', 'status.json'), JSON.stringify({ phase: 'curating', query: 'x', at: Date.now() }), 'utf8')
const statusA = JSON.parse((await call('GET', undefined, { path: '/api/video2agent/discovery/status', url: '/api/video2agent/discovery/status?session=alpha' })).body)
assert.equal(statusA.status.phase, 'curating')
assert.equal(statusA.status.session_id, 'alpha')
const statusB = JSON.parse((await call('GET', undefined, { path: '/api/video2agent/discovery/status', url: '/api/video2agent/discovery/status?session=beta' })).body)
assert.equal(statusB.status, null, 'another session must not see the search status')
const statusNoSession = JSON.parse((await call('GET', undefined, { path: '/api/video2agent/discovery/status', url: '/api/video2agent/discovery/status' })).body)
assert.equal(statusNoSession.status, null, 'a request without a session must not read a claimed search')
// A find-only client clears the Host status at turn end; another session cannot.
fs.writeFileSync(path.join(home, 'discovery', 'status.json'), JSON.stringify({ phase: 'curating', query: 'x', at: Date.now(), session_id: 'alpha' }), 'utf8')
const clearOther = await call('POST', JSON.stringify({ session: 'beta' }), { path: '/api/video2agent/discovery/clear' })
assert.equal(JSON.parse(clearOther.body).cleared, false, 'another session must not clear the search status')
const clearOwn = await call('POST', JSON.stringify({ session: 'alpha' }), { path: '/api/video2agent/discovery/clear' })
assert.equal(JSON.parse(clearOwn.body).cleared, true, 'the owning session must clear the search status')
const afterClear = JSON.parse((await call('GET', undefined, { path: '/api/video2agent/discovery/status', url: '/api/video2agent/discovery/status?session=alpha' })).body)
assert.equal(afterClear.status, null, 'a cleared search status must not come back')
assert.equal(routes.has('/api/video2agent/discovery/confirm'), false, 'the old confirm route must be gone')
assert.equal(routes.has('/api/video2agent/discovery/pending'), false, 'the old pending route must be gone')
assert.equal(routes.has('/api/video2agent/discovery/status'), true, 'the status route must exist')
// A start-failure retry names the video, not a job id; reject anything that is
// neither a valid job id nor a Bilibili BV id before spawning.
const badRetry = await call('POST', JSON.stringify({ video_id: 'not-a-bv' }), { path: '/api/video2agent/retry' })
assert.equal(badRetry.status, 400)

// Validation still happens before any spawn.
const defaultOutside = await registeredTool.execute({ command: 'shortlist', video_ids: ['BV1aaaaaaaa1'], default_selected: ['BV1bbbbbbbb1'], primary: 'BV1aaaaaaaa1' })
assert.equal(defaultOutside.error.code, 'E_SHORTLIST_DEFAULT')
const primaryOutsideDefault = await registeredTool.execute({ command: 'shortlist', video_ids: ['BV1aaaaaaaa1', 'BV1bbbbbbbb1'], default_selected: ['BV1bbbbbbbb1'], primary: 'BV1aaaaaaaa1' })
assert.equal(primaryOutsideDefault.error.code, 'E_SHORTLIST_DEFAULT')
await call('POST', JSON.stringify({ processLimit: 2 }))
const overLimit = await registeredTool.execute({ command: 'shortlist', video_ids: ['BV1aaaaaaaa1', 'BV1bbbbbbbb1', 'BV1cccccccc1'], default_selected: ['BV1aaaaaaaa1', 'BV1bbbbbbbb1', 'BV1cccccccc1'], primary: 'BV1aaaaaaaa1' })
assert.equal(overLimit.error.code, 'E_SHORTLIST_DEFAULT')
await call('POST', JSON.stringify({ processLimit: 10 }))
const emptyShortlist = await registeredTool.execute({ command: 'shortlist', video_ids: [], primary: '' })
assert.equal(emptyShortlist.error.code, 'E_SHORTLIST_COUNT')
const tooMany = await registeredTool.execute({ command: 'shortlist', video_ids: Array.from({ length: 11 }, (_, i) => 'BV1pad' + i), primary: 'BV1pad0' })
assert.equal(tooMany.error.code, 'E_SHORTLIST_COUNT')
const unknown = await registeredTool.execute({ command: 'shortlist', video_ids: ['BV1zzzzzzzz1'], primary: 'BV1zzzzzzzz1' })
assert.equal(unknown.error.code, 'E_SHORTLIST_UNKNOWN')
const wrongPrimary = await registeredTool.execute({ command: 'shortlist', video_ids: ['BV1aaaaaaaa1'], primary: 'BV1bbbbbbbb1' })
assert.equal(wrongPrimary.error.code, 'E_SHORTLIST_PRIMARY')

// A legacy Skill without default_selected must fail loudly instead of silently
// starting only the primary out of N videos.
const legacy = await registeredTool.execute({ command: 'shortlist', video_ids: ['BV1aaaaaaaa1'], primary: 'BV1aaaaaaaa1' })
assert.equal(legacy.error.code, 'E_SHORTLIST_DEFAULT')
assert.match(legacy.error.remedy, /default_selected/)
const legacyStatus = JSON.parse(fs.readFileSync(path.join(home, 'discovery', 'status.json'), 'utf8'))
assert.equal(legacyStatus.phase, 'error', 'a rejected shortlist must replace the curating spinner with an error')
// candidate_id is accepted too.
const byCandidate = await registeredTool.execute({ command: 'shortlist', video_ids: ['bili_A', 'bili_B'], default_selected: ['bili_A'], primary: 'bili_A' })
assert.equal(byCandidate.error.code, 'E_START')
// The deprecated auto flag is gone from the schema.
assert.equal(registeredTool.parameters.properties.auto, undefined, 'auto must not be in the tool schema')
process.env.VIDEO2AGENT_BIN = 'video2agent'
// Campaign route: an already-terminal campaign is readable without spawning.
const cid = 'campaign_' + 'a'.repeat(12)
fs.mkdirSync(path.join(home, 'campaigns'), { recursive: true })
fs.writeFileSync(path.join(home, 'campaigns', cid + '.json'), JSON.stringify({
  version: 1, id: cid, process_limit: 10, status: 'running',
  items: [{ video_id: 'BV1camp00001', title: 'campaign video', state: 'ready', job_id: 'job_c1', campaign_id: cid }],
}), 'utf8')
const campaignRead = await call('GET', undefined, { path: '/api/video2agent/campaign', url: '/api/video2agent/campaign?id=' + cid })
assert.equal(campaignRead.status, 200)
const campaignBody = JSON.parse(campaignRead.body)
assert.equal(campaignBody.total, 1)
assert.equal(campaignBody.ready, 1)
assert.equal(campaignBody.status, 'complete')
// A terminal sidecar older than 15s must still advance the campaign.
const staleId = 'campaign_' + 'b'.repeat(12)
fs.mkdirSync(path.join(home, 'jobs'), { recursive: true })
fs.writeFileSync(path.join(home, 'jobs', 'job_stale_campaign.json'), JSON.stringify({ ok: true, job: { id: 'job_stale_campaign', state: 'ready' } }), 'utf8')
const old = new Date(Date.now() - 60_000)
fs.utimesSync(path.join(home, 'jobs', 'job_stale_campaign.json'), old, old)
fs.writeFileSync(path.join(home, 'campaigns', staleId + '.json'), JSON.stringify({
  version: 1, id: staleId, process_limit: 10, status: 'running',
  items: [{ video_id: 'BV1stale0001', title: 'stale', state: 'running', job_id: 'job_stale_campaign', campaign_id: staleId }],
}), 'utf8')
const staleRead = await call('GET', undefined, { path: '/api/video2agent/campaign', url: '/api/video2agent/campaign?id=' + staleId })
assert.equal(staleRead.status, 200)
const staleBody = JSON.parse(staleRead.body)
assert.equal(staleBody.items[0].state, 'ready', 'a terminal sidecar must not be hidden by the 15s stale rule')
assert.equal(staleBody.status, 'complete')
const badCampaign = await call('GET', undefined, { path: '/api/video2agent/campaign', url: '/api/video2agent/campaign?id=nope' })
assert.equal(badCampaign.status, 400)
const invalidCampaign = await registeredTool.execute({ command: 'campaign', campaign_id: 'bad' })
assert.equal(invalidCampaign.ok, false)
assert.equal(JSON.parse(invalidCampaign.text).error.code, 'E_CAMPAIGN_ID')
const campaignTool = await registeredTool.execute({ command: 'campaign', campaign_id: cid })
assert.equal(campaignTool.ok, true, 'command campaign must be implemented, not a ReferenceError')
// More ids than one wave without campaign:true must fail before silently dropping the tail.
const many = Array.from({ length: 12 }, (_, i) => ({
  candidate_id: 'bili_pad' + i, video_id: 'BV1pad' + i, title: 'pad ' + i, stats: { play: i },
}))
fs.writeFileSync(__test.discoveryLastPath(''), JSON.stringify({ at: Date.now(), query: 'pad', candidates: many }), 'utf8')
const silentDrop = await registeredTool.execute({
  command: 'shortlist',
  video_ids: many.map((c) => c.video_id),
  default_selected: many.slice(0, 5).map((c) => c.video_id),
  primary: many[0].video_id,
})
assert.equal(silentDrop.error.code, 'E_SHORTLIST_DEFAULT', '12 ids with 5 defaults must not silently drop 7')
process.env.VIDEO2AGENT_BIN = 'definitely-missing-video2agent-binary-xyz'
const allFail = await registeredTool.execute({
  command: 'shortlist',
  campaign: true,
  video_ids: many.map((c) => c.video_id),
  primary: many[0].video_id,
})
assert.equal(allFail.error.code, 'E_START', 'a fully failed first wave must not be ok:true')
const failedCampaignFiles = fs.readdirSync(path.join(home, 'campaigns')).map((f) => JSON.parse(fs.readFileSync(path.join(home, 'campaigns', f), 'utf8')))
assert.equal(failedCampaignFiles.some((c) => c.status === 'failed'), true, 'an E_START campaign must not stay running forever')

console.log('host settings ok: GET, POST, retired knobs, structured spawn error, error envelope render, CLI error passthrough, wait_ms, Config schema, write guards, origin, arg clamping, settings precedence, frame route, host-start shortlist, status route')
fs.rmSync(home, { recursive: true, force: true })
if (oldHome === undefined) delete process.env.VIDEO2AGENT_HOME
else process.env.VIDEO2AGENT_HOME = oldHome
if (oldBin === undefined) delete process.env.VIDEO2AGENT_BIN
else process.env.VIDEO2AGENT_BIN = oldBin
if (oldPython === undefined) delete process.env.VIDEO2AGENT_PYTHON
else process.env.VIDEO2AGENT_PYTHON = oldPython

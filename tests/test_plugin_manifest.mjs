import fs from 'node:fs'
import path from 'node:path'
import assert from 'node:assert/strict'
import { fileURLToPath, pathToFileURL } from 'node:url'

const root = path.resolve(path.dirname(fileURLToPath(import.meta.url)), '..')
const pkgPath = path.join(root, 'packages/dsh-video2agent/package.json')
const pkg = JSON.parse(fs.readFileSync(pkgPath, 'utf8'))

if (pkg.name !== 'dsh-video2agent') throw new Error('unexpected package name')
if (!pkg.dsh?.bundle?.patch) throw new Error('missing dsh.bundle.patch')
if (!pkg.dsh?.client?.platform) throw new Error('missing dsh.client')
if (!pkg.files.includes('client.js') || !pkg.files.includes('index.js') || !pkg.files.includes('campaign.js')) throw new Error('missing files entries')
if (!pkg.peerDependencies?.['@deepseek-ai/dsh']) throw new Error('missing dsh peer')
if (pkg.dependencies?.['@deepseek-ai/dsh-tools']) throw new Error('plugin must not ship a second dsh-tools copy')

const patchPath = path.join(root, 'packages/dsh-video2agent', pkg.dsh.bundle.patch.replace('./', ''))
if (!fs.existsSync(patchPath)) throw new Error('bundle patch file missing')
const patch = fs.readFileSync(patchPath, 'utf8')
if (!patch.includes('dsh-video2agent')) throw new Error('patch does not name the plugin')

const shotsPath = path.join(root, 'packages/dsh-video2agent/screenshots.json')
if (!fs.existsSync(shotsPath)) throw new Error('screenshots.json missing')
const shotsRaw = JSON.parse(fs.readFileSync(shotsPath, 'utf8'))
const shots = Array.isArray(shotsRaw) ? shotsRaw : (Array.isArray(shotsRaw.screenshots) ? shotsRaw.screenshots : null)
if (!shots || shots.length < 1 || shots.length > 8) throw new Error('screenshots.json must contain 1-8 entries')
for (const shot of shots) {
  const rel = String(shot).replace(/^\.\//, '')
  if (!fs.existsSync(path.join(root, 'packages/dsh-video2agent', rel))) throw new Error('missing screenshot: ' + rel)
}

const index = fs.readFileSync(path.join(root, 'packages/dsh-video2agent/index.js'), 'utf8')
if (!index.includes('tools.register')) throw new Error('tool registration missing')
if (!index.includes('export function apply')) throw new Error('plugin apply export missing')
if (!index.includes('video2agent')) throw new Error('tool name missing')
if (!index.includes('/api/video2agent/resolve')) throw new Error('resolve route missing')
if (!index.includes('/api/video2agent/job')) throw new Error('live job route missing')
if (!index.includes('/api/video2agent/frame')) throw new Error('frame route missing')
if (!index.includes('/api/video2agent/settings')) throw new Error('settings route missing')
if (!index.includes('/api/video2agent/retry')) throw new Error('retry route missing')

const client = fs.readFileSync(path.join(root, 'packages/dsh-video2agent/client.js'), 'utf8')
if (!client.includes('tool.call.toolview')) throw new Error('tool card slot missing')
if (!client.includes("key: 'video2agent'")) throw new Error('tool card key missing')
if (!client.includes('conversation.input.dock')) throw new Error('composer preview slot missing')
if (!client.includes('/api/video2agent/resolve')) throw new Error('preview route missing')
if (client.includes('conversation.input.overlay')) throw new Error('floating overlay must not be registered')
if (!client.includes('/api/video2agent/job')) throw new Error('inline job card must poll the job route')
if (!client.includes('/api/video2agent/frame')) throw new Error('evidence card must load frames')
if (!client.includes("id: 'video2agent-status'")) throw new Error('processing window registration missing')
if (!client.includes('data-vp-live')) throw new Error('processing window markup missing')
if (!client.includes('RESOLVE_CACHE')) throw new Error('resolve cache missing')
if (!client.includes("'settings.section'")) throw new Error('settings section registration missing')
if (!client.includes("'plugins.bundle.config'")) throw new Error('plugin config registration missing')

// --- Activation without a web server (headless / TUI profiles) ---------------
// Regression for a real DSH 0.2 headless boot, which logged
//   dsh-video2agent: pending (waiting for service: webServer)
// and therefore never registered the tool or the /video command. webServer must
// stay an optional service: routes register when it appears, the tool does not
// depend on it.
const mod = await import(pathToFileURL(path.join(root, 'packages/dsh-video2agent/index.js')).href)
assert.deepEqual(mod.inject, ['commands', 'tools', 'systemPrompt'], 'webServer must not be a hard dependency; systemPrompt is core')

function fakeCtx({ withWebServer = false, provideWebServer = null } = {}) {
  const seen = { commands: [], tools: [], routes: [], injected: [] }
  const webServer = withWebServer ? provideWebServer || { register: (route) => seen.routes.push(route) } : null
  const ctx = {
    logger: { info() {} },
    commands: { register: (c) => seen.commands.push(c) },
    get(name) {
      if (name === 'tools') return { register: (t) => seen.tools.push(t) }
      if (name === 'webServer') return webServer || undefined
      return undefined
    },
    inject(deps, cb) {
      seen.injected.push(deps.join(','))
      // Simulate an app that never provides the service: the callback must not
      // be required for activation. When a service is provided, run it.
      if (provideWebServer) cb({ get: () => provideWebServer, webServer: provideWebServer })
    },
  }
  return { ctx, seen }
}

// No webServer, no inject() method at all: still activates.
{
  const { ctx, seen } = fakeCtx()
  delete ctx.inject
  mod.apply(ctx)
  assert.equal(seen.commands.length, 1, 'command must register without webServer')
  assert.equal(seen.tools.length, 1, 'tool must register without webServer')
  assert.equal(seen.routes.length, 0, 'no routes without a web server')
}

// webServer arrives later: activation first, routes on the deferred callback.
{
  const { ctx, seen } = fakeCtx()
  mod.apply(ctx)
  assert.equal(seen.tools.length, 1, 'tool registers before webServer exists')
  assert.ok(seen.injected.length >= 1, 'routes must defer on webServer')
  // connection is also deferred (optional admission fence for the HTTP routes);
  // neither may become a hard dependency of the plugin.
  assert.deepEqual([...new Set(seen.injected)].sort(), ['connection', 'webServer'], 'only webServer/connection are deferred')
  assert.equal(seen.routes.length, 0, 'no routes until the service appears')
}

// Deferred callback really registers every route.
{
  const ws = { register: () => {} }
  const routes = []
  const provided = { register: (route) => routes.push(route) }
  const { ctx } = fakeCtx({ provideWebServer: provided })
  provided.register = (route) => routes.push(route)
  void ws
  mod.apply(ctx)
  const paths = routes.map((r) => r.path).sort()
  assert.deepEqual(paths, [
    '/api/video2agent/activity',
    '/api/video2agent/bili-login/clear',
    '/api/video2agent/bili-login/poll',
    '/api/video2agent/bili-login/start',
    '/api/video2agent/bili-login/status',
    '/api/video2agent/campaign',
    '/api/video2agent/cloud',
    '/api/video2agent/cover',
    '/api/video2agent/discovery/clear',
    '/api/video2agent/discovery/status',
    '/api/video2agent/doctor',
    '/api/video2agent/douyin-login/clear',
    '/api/video2agent/douyin-login/start',
    '/api/video2agent/douyin-login/status',
    '/api/video2agent/frame',
    '/api/video2agent/job',
    '/api/video2agent/jobs/cancel',
    '/api/video2agent/models',
    '/api/video2agent/queue',
    '/api/video2agent/resolve',
    '/api/video2agent/retry',
    '/api/video2agent/settings',
    '/api/video2agent/setup',
  ])
}

console.log('plugin manifest ok: bundle, client, peers, files, slots, headless activation')

#!/usr/bin/env node
/**
 * Real old-version -> candidate upgrade smoke.
 *
 * This is a release gate, not part of the default harness set: it runs a real
 * pip install and therefore only executes when VIDEO2AGENT_UPGRADE_WHEEL names
 * a built candidate wheel. Without it the script prints SKIP and exits 0.
 *
 * What is real:
 *   - public PyPI video2agent 0.3.3 into an isolated venv (sha256 pinned below);
 *   - the actual plugin apply() startup path from packages/dsh-video2agent;
 *   - real pip through PIP_NO_INDEX/PIP_FIND_LINKS, installing by name so pip
 *     records no direct_url marker;
 *   - a real tool call whose child Python is recorded by a venv-local
 *     sitecustomize (instrumentation only; the installed package is untouched).
 *
 * Invocation (macOS/Linux shown; Windows uses the same command):
 *   python -m build --wheel --outdir dist
 *   VIDEO2AGENT_UPGRADE_WHEEL=dist/video2agent-0.3.6-py3-none-any.whl \
 *     node tests/test_plugin_upgrade_smoke.mjs
 *
 * Legacy (no provenance) record. Auto-update must do nothing; one explicit
 * manual update may then install the candidate and write provenance:
 *   VIDEO2AGENT_SMOKE_LEGACY=1 VIDEO2AGENT_UPGRADE_WHEEL=... \
 *     node tests/test_plugin_upgrade_smoke.mjs
 *
 * Optional:
 *   VIDEO2AGENT_TEST_PYTHON=/path/to/python3.11 (otherwise python3.11/3.12/3.13)
 *   VIDEO2AGENT_OLD_WHEEL=/path/video2agent-0.3.3-py3-none-any.whl (offline)
 *   VIDEO2AGENT_OLD_VERSION=0.3.3
 *   VIDEO2AGENT_PLUGIN_DIR=... (test-only override for the plugin checkout)
 *
 * Artifacts stay under .promo/upgrade-smoke-<pid>-<timestamp>.
 */
import assert from 'node:assert/strict'
import { spawnSync } from 'node:child_process'
import { createHash } from 'node:crypto'
import fs from 'node:fs'
import path from 'node:path'
import { fileURLToPath, pathToFileURL } from 'node:url'

const here = path.dirname(fileURLToPath(import.meta.url))
const repoRoot = path.resolve(here, '..')
const upgradeArg = String(process.env.VIDEO2AGENT_UPGRADE_WHEEL || '').trim()
if (!upgradeArg) {
  console.log('SKIP upgrade smoke: set VIDEO2AGENT_UPGRADE_WHEEL to a built candidate wheel')
  process.exit(0)
}

const resolveInside = (value) => path.isAbsolute(value) ? value : path.resolve(repoRoot, value)
const upgradeWheel = resolveInside(upgradeArg)
assert.ok(fs.existsSync(upgradeWheel), 'candidate wheel does not exist: ' + upgradeWheel)
assert.match(path.basename(upgradeWheel), /^video2agent-\d+\.\d+\.\d+-py3-none-any\.whl$/, 'unexpected candidate wheel name')

const pluginDir = resolveInside(process.env.VIDEO2AGENT_PLUGIN_DIR || path.join(repoRoot, 'packages', 'dsh-video2agent'))
const pluginManifest = JSON.parse(fs.readFileSync(path.join(pluginDir, 'package.json'), 'utf8'))
const pluginVersion = String(pluginManifest.version || '')
assert.match(pluginVersion, /^\d+\.\d+\.\d+$/, 'plugin version is missing')
assert.ok(path.basename(upgradeWheel).includes('-' + pluginVersion + '-'),
  'candidate wheel ' + path.basename(upgradeWheel) + ' does not match plugin version ' + pluginVersion)

const legacyMode = /^(1|true|yes)$/i.test(String(process.env.VIDEO2AGENT_SMOKE_LEGACY || ''))
const oldVersion = String(process.env.VIDEO2AGENT_OLD_VERSION || '0.3.3').trim()
const OLD_033_SHA256 = '96fd7e3043a07b048b85fe2c1e13085fbf8711373219aa1d090c1c68c6fffc69'
const smokeRoot = path.join(repoRoot, '.promo', 'upgrade-smoke-' + process.pid + '-' + Date.now())
const wheelhouse = path.join(smokeRoot, 'wheelhouse')
const home = path.join(smokeRoot, 'home')
const logs = path.join(smokeRoot, 'logs')
for (const dir of [wheelhouse, home, logs]) fs.mkdirSync(dir, { recursive: true })
const smokeLog = path.join(logs, 'python-starts.jsonl')
// Keep every pip/Python temporary file and the pip cache inside this run. A
// killed command must not leave build trackers in the repository root or write
// to the runner's shared temp/cache.
const tmpDir = path.join(smokeRoot, 'tmp')
const pipCache = path.join(smokeRoot, 'pip-cache')
for (const dir of [tmpDir, pipCache]) fs.mkdirSync(dir, { recursive: true })
process.env.TMP = tmpDir
process.env.TEMP = tmpDir
process.env.TMPDIR = tmpDir
process.env.PIP_CACHE_DIR = pipCache

function childEnv(extra = {}) {
  const env = { ...process.env, ...extra }
  env.PIP_DISABLE_PIP_VERSION_CHECK = '1'
  return env
}

function run(command, args, options = {}) {
  const started = Date.now()
  const r = spawnSync(command, args, {
    cwd: options.cwd || repoRoot,
    env: options.env || childEnv(),
    encoding: 'utf8',
    timeout: options.timeoutMs || 300000,
    windowsHide: true,
  })
  const record = { command, args, code: r.status, ms: Date.now() - started, stdout: r.stdout || '', stderr: r.stderr || '' }
  if (r.error) throw new Error('spawn failed: ' + command + ' ' + args.join(' ') + ': ' + r.error.message)
  if (r.status !== 0) {
    const error = new Error(options.label || 'command failed: ' + command + ' ' + args.join(' ') + ' (exit ' + r.status + ')\n' + record.stdout + '\n' + record.stderr)
    error.record = record
    throw error
  }
  return record
}

function sha256(file) {
  return createHash('sha256').update(fs.readFileSync(file)).digest('hex')
}

function findPython() {
  const explicit = String(process.env.VIDEO2AGENT_TEST_PYTHON || '').trim()
  const candidates = explicit
    ? [{ command: explicit, prefix: [] }]
    : process.platform === 'win32'
      ? [
        { command: 'py', prefix: ['-3.11'] },
        { command: 'py', prefix: ['-3.12'] },
        { command: 'py', prefix: ['-3.13'] },
        { command: 'python', prefix: [] },
      ]
      : [
        { command: 'python3.11', prefix: [] },
        { command: 'python3.12', prefix: [] },
        { command: 'python3.13', prefix: [] },
        { command: 'python3', prefix: [] },
      ]
  for (const candidate of candidates) {
    try {
      const probe = run(candidate.command, [...candidate.prefix, '-c',
        'import sys; print("%d.%d" % sys.version_info[:2]); print(sys.executable)'], { timeoutMs: 30000 })
      const [version, executable] = probe.stdout.trim().split(/\r?\n/)
      const [major, minor] = version.split('.').map(Number)
      if (major > 3 || (major === 3 && minor >= 11)) return { ...candidate, version, executable }
    } catch {}
  }
  throw new Error('no Python 3.11+ found; set VIDEO2AGENT_TEST_PYTHON')
}

const python = findPython()
const venvDir = path.join(smokeRoot, 'venv')
run(python.command, [...python.prefix, '-m', 'venv', venvDir], { label: 'venv creation failed' })
const venvPython = process.platform === 'win32'
  ? path.join(venvDir, 'Scripts', 'python.exe')
  : path.join(venvDir, 'bin', 'python')
assert.ok(fs.existsSync(venvPython), 'venv python missing at ' + venvPython)

// 1. Old release: download the public 0.3.3 wheel, verify it, then install it
// from the local wheelhouse by name (same shape as the upgrade below).
const oldWheelOverride = String(process.env.VIDEO2AGENT_OLD_WHEEL || '').trim()
if (oldWheelOverride) {
  const source = resolveInside(oldWheelOverride)
  assert.ok(fs.existsSync(source), 'VIDEO2AGENT_OLD_WHEEL missing: ' + source)
  fs.copyFileSync(source, path.join(wheelhouse, path.basename(source)))
} else {
  run(venvPython, ['-m', 'pip', 'download', '--disable-pip-version-check', '--no-deps',
    '--only-binary=:all:', '--timeout', '30', '--retries', '1', '--dest', wheelhouse,
    'video2agent==' + oldVersion],
  { label: 'public PyPI download of video2agent ' + oldVersion + ' failed', timeoutMs: 180000 })
}
const oldWheel = fs.readdirSync(wheelhouse).find((name) => name.startsWith('video2agent-' + oldVersion + '-') && name.endsWith('.whl'))
assert.ok(oldWheel, 'old wheel not found in ' + wheelhouse)
if (!oldWheelOverride && oldVersion === '0.3.3') {
  assert.equal(sha256(path.join(wheelhouse, oldWheel)), OLD_033_SHA256, 'public 0.3.3 wheel sha256 changed')
}
fs.copyFileSync(upgradeWheel, path.join(wheelhouse, path.basename(upgradeWheel)))
const pipOldEnv = childEnv()
delete pipOldEnv.PIP_NO_INDEX
delete pipOldEnv.PIP_FIND_LINKS
delete pipOldEnv.PIP_NO_DEPS
run(venvPython, ['-m', 'pip', 'install', '--no-index', '--find-links', wheelhouse, '--no-deps',
  'video2agent==' + oldVersion],
{ env: pipOldEnv, label: 'old version install failed' })
const oldVersionOut = run(venvPython, ['-m', 'video2agent', '--version']).stdout.trim()
assert.ok(oldVersionOut.includes(oldVersion), 'expected video2agent ' + oldVersion + ', got: ' + oldVersionOut)

// Instrument every child Python this venv starts. This records the interpreter
// and the installed distribution version without modifying the package.
const purelib = run(venvPython, ['-c', 'import sysconfig; print(sysconfig.get_paths()["purelib"])']).stdout.trim()
assert.ok(fs.existsSync(purelib), 'site-packages missing: ' + purelib)
fs.writeFileSync(path.join(purelib, 'sitecustomize.py'), [
  'import json, os, sys',
  'try:',
  '    import importlib.metadata as _m',
  '    _v = _m.version("video2agent")',
  'except Exception:',
  '    _v = ""',
  'try:',
  '    _log = os.environ.get("VIDEO2AGENT_SMOKE_LOG")',
  '    if _log:',
  '        with open(_log, "a", encoding="utf-8") as _f:',
  '            _f.write(json.dumps({"exe": sys.executable, "version": _v, "argv": sys.argv, "cwd": os.getcwd()}) + chr(10))',
  'except Exception:',
  '    pass',
  '',
].join('\n'), 'utf8')

const managedTools = path.join(home, 'tools', 'ffmpeg.json')
fs.mkdirSync(path.dirname(managedTools), { recursive: true })
const baseRecord = {
  python: venvPython,
  prefix: [],
  at: new Date().toISOString(),
  version: oldVersion,
  plugin_version: oldVersion,
}
if (legacyMode) {
  // Exactly what versions before provenance wrote: python/prefix/at only.
  fs.writeFileSync(managedTools, JSON.stringify({ cli: baseRecord }, null, 2), 'utf8')
} else {
  fs.writeFileSync(managedTools, JSON.stringify({
    cli: { ...baseRecord, source: 'plugin-install', auto_update: true },
  }, null, 2), 'utf8')
}

const managedRead = () => JSON.parse(fs.readFileSync(managedTools, 'utf8')).cli
const recordBefore = managedRead()
const logSizeBeforeApply = fs.existsSync(smokeLog) ? fs.statSync(smokeLog).size : 0

// 2. Run the real plugin apply() with only the isolated home, then wait for the
// startup gate. The plugin's pip spec is "video2agent==<plugin version>".
for (const key of ['VIDEO2AGENT_BIN', 'VIDEO2AGENT_PYTHON', 'VIDEO2AGENT_PLUGIN_MANIFEST']) delete process.env[key]
process.env.VIDEO2AGENT_HOME = home
process.env.VIDEO2AGENT_SMOKE_LOG = smokeLog
process.env.PIP_NO_INDEX = '1'
process.env.PIP_FIND_LINKS = wheelhouse
process.env.PIP_NO_DEPS = '1'
process.env.PIP_DISABLE_PIP_VERSION_CHECK = '1'
process.env.PIP_NO_INPUT = '1'

const routes = new Map()
let registeredTool = null
const ctx = {
  logger: { info() {} },
  commands: { register() {} },
  systemPrompt: { section() { return () => {} } },
  get(service) {
    if (service === 'tools') return { register(tool) { registeredTool = tool } }
    if (service === 'webServer') return { register(route) { routes.set(route.path, route.handler) }, getOrigin: () => 'http://127.0.0.1:8640' }
    if (service === 'connection') return { requestRejection() { return null } }
    return undefined
  },
}
const plugin = await import(pathToFileURL(path.join(pluginDir, 'index.js')).href)
plugin.apply(ctx)
await plugin.__test.waitForEngineReady()
assert.ok(registeredTool, 'the plugin did not register its tool')

const stateAfter = plugin.__test.engineUpdatePublic()
const recordAfter = managedRead()
if (legacyMode) {
  // No provenance = no automatic authorization. It must not even probe/pip.
  assert.equal(stateAfter.state, 'idle', 'a legacy record must not start an automatic update, got ' + JSON.stringify(stateAfter))
  assert.equal(recordAfter.version, oldVersion, 'the legacy record must stay on ' + oldVersion)
  assert.equal(recordAfter.source, undefined, 'an automatic pass must not invent provenance')
  const logSizeAfterAuto = fs.existsSync(smokeLog) ? fs.statSync(smokeLog).size : 0
  assert.equal(logSizeAfterAuto, logSizeBeforeApply,
    'the legacy automatic pass must not spawn a Python probe or pip')
  const installedAfterAuto = run(venvPython, ['-m', 'video2agent', '--version']).stdout.trim()
  assert.ok(installedAfterAuto.includes(oldVersion), 'automatic pass must not change the installed version')

  // Exactly one explicit manual click may update it, and that success records
  // provenance. This is the legacy path, not a default automatic upgrade.
  const manual = await plugin.__test.performEngineUpdate({ command: venvPython, prefix: [] },
    { manual: true, currentVersion: oldVersion })
  assert.equal(manual.ok, true, 'manual legacy update failed: ' + JSON.stringify(manual.error || {}))
  const recordManual = managedRead()
  assert.equal(recordManual.source, 'plugin-install', 'a successful manual legacy update must record provenance')
  assert.equal(recordManual.auto_update, true, 'a clean manual legacy update may authorize later upgrades')
} else {
  assert.equal(stateAfter.state, 'ready', 'managed auto-update did not finish ready: ' + JSON.stringify(stateAfter))
  assert.equal(stateAfter.target, pluginVersion)
  const applyLog = fs.readFileSync(smokeLog, 'utf8').slice(logSizeBeforeApply).trim().split(/\r?\n/).filter(Boolean).map((line) => JSON.parse(line))
  const pipRuns = applyLog.filter((entry) => {
    const argv = Array.isArray(entry.argv) ? entry.argv : []
    // Python rewrites sys.argv for -m entry points, so do not assume the
    // "pip" token survives; the requested spec is the stable evidence.
    return argv.includes('install') && argv.includes('video2agent==' + pluginVersion)
  })
  assert.ok(pipRuns.length > 0, 'the plugin did not run a real pip install of video2agent==' + pluginVersion)
}
const finalVersionOut = run(venvPython, ['-m', 'video2agent', '--version']).stdout.trim()
assert.ok(finalVersionOut.includes(pluginVersion), 'expected ' + pluginVersion + ' after upgrade, got: ' + finalVersionOut)
const finalRecord = managedRead()
assert.equal(finalRecord.python.toLowerCase(), venvPython.toLowerCase(), 'the managed record must point at the isolated venv')
assert.equal(finalRecord.version, pluginVersion, 'the record must carry the probed version')
assert.equal(finalRecord.source, 'plugin-install')
assert.equal(finalRecord.auto_update, true)

// The wheel came from a find-links index by name, not a wheel path: no direct
// URL marker may exist, otherwise the next release could not be auto-updated.
const distInfo = fs.readdirSync(purelib).find((name) => name.startsWith('video2agent-' + pluginVersion + '.dist-info'))
assert.ok(distInfo, 'installed dist-info not found for ' + pluginVersion)
assert.equal(fs.existsSync(path.join(purelib, distInfo, 'direct_url.json')), false,
  'indexed install must not create direct_url.json')

// 3. The actual model-facing tool must spawn this venv's 0.3.6. doctor is
// read-only and needs no network; its JSON success is not required, the child
// process record is.
const logSizeBefore = fs.existsSync(smokeLog) ? fs.statSync(smokeLog).size : 0
let toolResult = null
let toolError = null
try {
  toolResult = await registeredTool.execute(
    { command: 'admin', admin_action: 'doctor' },
    { agent: { session: { id: 'upgrade-smoke' } } },
  )
} catch (e) {
  toolError = e
}
plugin.__test.stopWorker()
if (toolError) throw toolError
assert.ok(toolResult && typeof toolResult === 'object', 'tool returned no object')
const logText = fs.readFileSync(smokeLog, 'utf8')
const newLines = logText.slice(logSizeBefore).trim().split(/\r?\n/).filter(Boolean).map((line) => JSON.parse(line))
const toolRuns = newLines.filter((entry) => {
  const argv = Array.isArray(entry.argv) ? entry.argv : []
  // admin doctor is worker-eligible, so the child is the warm worker that
  // executes doctor; a non-worker CLI would carry the command directly.
  // Python rewrites sys.argv for -m entry points, so match the subcommand.
  return argv.includes('__worker') || argv.includes('doctor')
})
assert.ok(toolRuns.length > 0, 'the tool call did not spawn python -m video2agent (worker or doctor)')
const toolRun = toolRuns[toolRuns.length - 1]
assert.equal(path.resolve(toolRun.exe).toLowerCase(), path.resolve(venvPython).toLowerCase(),
  'tool child used a different interpreter: ' + toolRun.exe)
assert.equal(toolRun.version, pluginVersion, 'tool child loaded ' + toolRun.version + ', expected ' + pluginVersion)

const summary = {
  mode: legacyMode ? 'legacy-manual' : 'managed-auto',
  okay: true,
  pluginVersion,
  oldVersion,
  oldWheel: path.basename(oldWheel),
  candidateWheel: path.basename(upgradeWheel),
  python: python.version,
  venvPython,
  engineUpdate: stateAfter,
  managedRecord: finalRecord,
  tool: { exit: toolResult.ok, textHead: String(toolResult.text || '').slice(0, 160), child: toolRun },
  artifacts: smokeRoot,
}
console.log(JSON.stringify(summary, null, 2))
process.exit(0)

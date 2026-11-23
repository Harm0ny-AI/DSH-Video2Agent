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
 * Modes:
 *   default: a managed plugin-install record (source/auto_update) is upgraded in
 *     place, in the isolated venv, exactly like the first release of this gate.
 *   VIDEO2AGENT_SMOKE_LEGACY=1: a real pre-provenance record (the isolated 0.3.3
 *     venv, no source/auto_update) must be adopted at Host startup into
 *     <home>/engines/<version>/venv-<attempt>. The old interpreter stays 0.3.3 and the
 *     registered tool must call the new private interpreter.
 *   VIDEO2AGENT_SMOKE_PATH=1: no record at all; the 0.3.3 venv is first on PATH.
 *     The Host must adopt that PATH install the same way, leaving it untouched.
 *   VIDEO2AGENT_SMOKE_LEGACY and VIDEO2AGENT_SMOKE_PATH are mutually exclusive.
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
const samePath = (a, b) => {
  const left = path.resolve(String(a || ''))
  const right = path.resolve(String(b || ''))
  return process.platform === 'win32' ? left.toLowerCase() === right.toLowerCase() : left === right
}
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
const pathMode = /^(1|true|yes)$/i.test(String(process.env.VIDEO2AGENT_SMOKE_PATH || ''))
assert.ok(!(legacyMode && pathMode), 'VIDEO2AGENT_SMOKE_LEGACY and VIDEO2AGENT_SMOKE_PATH are mutually exclusive')
const migrationMode = legacyMode || pathMode
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
const venvBin = process.platform === 'win32' ? path.join(venvDir, 'Scripts') : path.join(venvDir, 'bin')
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
// and the installed distribution version without modifying the package. A
// private engine venv created by the Host gets the same instrumentation after it
// is ready, so the model-facing tool call is observable without any Host hook.
const SITE_CUSTOMIZE = [
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
].join('\n')
function instrumentVenv(pythonPath) {
  const target = run(pythonPath, ['-c', 'import sysconfig; print(sysconfig.get_paths()["purelib"])']).stdout.trim()
  assert.ok(fs.existsSync(target), 'site-packages missing: ' + target)
  fs.writeFileSync(path.join(target, 'sitecustomize.py'), SITE_CUSTOMIZE, 'utf8')
  return target
}
const purelib = instrumentVenv(venvPython)

const managedTools = path.join(home, 'tools', 'ffmpeg.json')
const managedRead = () => {
  try {
    return JSON.parse(fs.readFileSync(managedTools, 'utf8')).cli
  } catch {
    return null
  }
}
const baseRecord = {
  python: venvPython,
  prefix: [],
  at: new Date().toISOString(),
  version: oldVersion,
  plugin_version: oldVersion,
}
if (legacyMode) {
  // Exactly what versions before provenance wrote: python/prefix/at plus the
  // detected version, and no source/auto_update authorization.
  fs.mkdirSync(path.dirname(managedTools), { recursive: true })
  fs.writeFileSync(managedTools, JSON.stringify({ cli: baseRecord }, null, 2), 'utf8')
} else if (!pathMode) {
  fs.mkdirSync(path.dirname(managedTools), { recursive: true })
  fs.writeFileSync(managedTools, JSON.stringify({
    cli: { ...baseRecord, source: 'plugin-install', auto_update: true },
  }, null, 2), 'utf8')
}
// PATH mode writes no record at all: the Host must discover the ordinary PyPI
// CLI exactly like a user whose old plugin never recorded an interpreter.
if (pathMode) {
  assert.equal(fs.existsSync(managedTools), false, 'PATH mode must start without a managed record')
  const oldCli = path.join(venvBin, process.platform === 'win32' ? 'video2agent.exe' : 'video2agent')
  assert.ok(fs.existsSync(oldCli), 'the isolated 0.3.3 venv has no video2agent console script: ' + oldCli)
  process.env.PATH = venvBin + path.delimiter + String(process.env.PATH || '')
}

const recordBefore = managedRead()
if (legacyMode) assert.equal(recordBefore && recordBefore.source, undefined, 'the legacy fixture must start without provenance')
if (!migrationMode) assert.equal(recordBefore && recordBefore.source, 'plugin-install')
if (pathMode) assert.equal(recordBefore, null, 'PATH mode must start with no record')
const logSizeBeforeApply = fs.existsSync(smokeLog) ? fs.statSync(smokeLog).size : 0

// 2. Run the real plugin apply() with only the isolated home, then wait for the
// startup gate. The plugin's pip spec is "video2agent==<plugin version>".
for (const key of ['VIDEO2AGENT_BIN', 'VIDEO2AGENT_PYTHON', 'VIDEO2AGENT_PLUGIN_MANIFEST']) delete process.env[key]
process.env.VIDEO2AGENT_HOME = home
process.env.VIDEO2AGENT_SMOKE_LOG = smokeLog
process.env.PIP_NO_INDEX = '1'
process.env.PIP_FIND_LINKS = wheelhouse
// pip reads every long option from PIP_*; this keeps the private venv install
// offline and identical in shape to the managed install above (no transitive
// wheels are needed for --version or admin doctor).
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
// Every mode must finish the startup gate in ready, including adoption. A
// legacy record or a bare PATH install is no longer a reason to stay idle.
assert.equal(stateAfter.state, 'ready', 'startup did not finish ready: ' + JSON.stringify(stateAfter))
assert.equal(stateAfter.target, pluginVersion, 'ready target is not the loaded plugin version: ' + JSON.stringify(stateAfter))

let enginePython = venvPython
let engineRoot = ''
let enginePurelib = purelib
if (migrationMode) {
  // The Host creates a fresh venv below <home>/engines/<version>/ and switches
  // the record to it. The attempt directory is unique, so locate it through the
  // record instead of assuming a fixed venv name.
  const versionRoot = plugin.__test.engineRootDir(pluginVersion)
  assert.ok(samePath(versionRoot, path.join(home, 'engines', pluginVersion)),
    'engineRootDir no longer matches the documented layout: ' + versionRoot)
  assert.ok(recordAfter && typeof recordAfter.python === 'string' && recordAfter.python,
    'adoption wrote no interpreter record')
  enginePython = path.resolve(recordAfter.python)
  assert.ok(recordAfter.engine_root, 'adoption must record engine_root')
  engineRoot = path.resolve(recordAfter.engine_root)
  assert.ok(fs.existsSync(enginePython), 'private engine interpreter missing at ' + enginePython + ' (state ' + JSON.stringify(stateAfter) + ')')
  assert.ok(samePath(plugin.__test.engineVenvPython(engineRoot), enginePython),
    'engineVenvPython no longer resolves the recorded engine root')
  const insideVersionRoot = process.platform === 'win32'
    ? engineRoot.toLowerCase().startsWith(versionRoot.toLowerCase() + path.sep)
    : engineRoot.startsWith(versionRoot + path.sep)
  assert.ok(insideVersionRoot, 'the private engine escaped its version root: ' + engineRoot)
  assert.ok(!samePath(enginePython, venvPython), 'the private engine must not be the old interpreter')

  assert.equal(recordAfter.source, 'plugin-install', 'adoption must record plugin-install provenance')
  assert.equal(recordAfter.auto_update, true, 'a clean adopted engine may be auto-updated later')
  assert.equal(recordAfter.version, pluginVersion)
  assert.equal(recordAfter.plugin_version, pluginVersion)
  assert.ok(Array.isArray(recordAfter.prefix) && recordAfter.prefix.length === 0, 'the adopted engine is invoked with -m, not a prefix')
  assert.ok(recordAfter.installed_at, 'adoption must stamp installed_at')
  assert.ok(samePath(recordAfter.python, enginePython),
    'the managed record must point at the private interpreter, got ' + recordAfter.python)

  // The old interpreter/environment is untouched: same 0.3.3 package, same
  // venv, no candidate dist-info written into it.
  const oldAfter = run(venvPython, ['-m', 'video2agent', '--version']).stdout.trim()
  assert.ok(oldAfter.includes(oldVersion), 'the old interpreter was modified: ' + oldAfter)
  const oldDistInfo = fs.readdirSync(purelib).find((name) => name.startsWith('video2agent-' + oldVersion + '.dist-info'))
  assert.ok(oldDistInfo, 'the old 0.3.3 dist-info disappeared from ' + purelib)
  assert.equal(fs.existsSync(path.join(purelib, 'video2agent-' + pluginVersion + '.dist-info')), false,
    'the candidate must not be installed into the old interpreter')
  if (pathMode) {
    // The ordinary console script on PATH is the user's own install: it must
    // still be 0.3.3 and still start after the Host switched its record.
    const pathCliAfter = run('video2agent', ['--version']).stdout.trim()
    assert.ok(pathCliAfter.includes(oldVersion), 'the PATH CLI was modified: ' + pathCliAfter)
  }

  // Diagnostic snapshot: a legacy record carries the exact old interpreter; a
  // PATH install carries the path/version the Host resolved.
  if (recordAfter.previous) {
    assert.equal(recordAfter.previous.version, oldVersion, 'previous snapshot lost the old version')
    if (legacyMode) {
      assert.ok(samePath(recordAfter.previous.python, venvPython),
        'previous snapshot lost the old interpreter, got ' + recordAfter.previous.python)
      assert.equal(recordAfter.previous.source, null)
    }
  } else if (legacyMode) {
    assert.fail('a legacy record adoption must keep a previous snapshot for diagnostics')
  }
  // The PATH probe resolves the console script's own interpreter; only trust an
  // absolute value (a bare launcher is legitimate but is not an interpreter).
  if (pathMode && recordAfter.previous && path.isAbsolute(String(recordAfter.previous.python || ''))) {
    assert.ok(samePath(recordAfter.previous.python, venvPython),
      'the PATH adoption did not identify the old interpreter, got ' + recordAfter.previous.python)
  }

  // The private venv starts without our instrumentation. Add it only after the
  // Host has finished, so the model-facing tool call is what we observe next.
  enginePurelib = instrumentVenv(enginePython)
} else {
  assert.ok(samePath(recordAfter.python, venvPython),
    'the managed record must still point at the isolated venv, got ' + recordAfter.python)
  const applyLog = fs.readFileSync(smokeLog, 'utf8').slice(logSizeBeforeApply).trim().split(/\r?\n/).filter(Boolean).map((line) => JSON.parse(line))
  const pipRuns = applyLog.filter((entry) => {
    const argv = Array.isArray(entry.argv) ? entry.argv : []
    // Python rewrites sys.argv for -m entry points, so do not assume the
    // "pip" token survives; the requested spec is the stable evidence.
    return argv.includes('install') && argv.includes('video2agent==' + pluginVersion)
  })
  assert.ok(pipRuns.length > 0, 'the plugin did not run a real pip install of video2agent==' + pluginVersion)
}

const finalVersionOut = run(enginePython, ['-m', 'video2agent', '--version']).stdout.trim()
assert.ok(finalVersionOut.includes(pluginVersion), 'expected ' + pluginVersion + ' on the managed engine, got: ' + finalVersionOut)
const finalRecord = managedRead()
assert.equal(finalRecord.source, 'plugin-install')
assert.equal(finalRecord.auto_update, true)
assert.equal(finalRecord.version, pluginVersion, 'the record must carry the probed version')
assert.ok(samePath(finalRecord.python, enginePython), 'the record must point at the engine the tool calls')

// The wheel came from a find-links index by name, not a wheel path: no direct
// URL marker may exist, otherwise the next release could not be auto-updated.
const distInfo = fs.readdirSync(enginePurelib).find((name) => name.startsWith('video2agent-' + pluginVersion + '.dist-info'))
assert.ok(distInfo, 'installed dist-info not found for ' + pluginVersion + ' under ' + enginePurelib)
assert.equal(fs.existsSync(path.join(enginePurelib, distInfo, 'direct_url.json')), false,
  'indexed install must not create direct_url.json')

// 3. The actual model-facing tool must spawn the engine the record names. doctor
// is read-only and needs no network; its JSON success is not required, the child
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
assert.ok(samePath(toolRun.exe, enginePython),
  'tool child used a different interpreter: ' + toolRun.exe + ' expected ' + enginePython)
assert.equal(toolRun.version, pluginVersion, 'tool child loaded ' + toolRun.version + ', expected ' + pluginVersion)

const summary = {
  mode: legacyMode ? 'legacy-record-auto-migrate' : pathMode ? 'path-only-auto-migrate' : 'managed-auto',
  okay: true,
  pluginVersion,
  oldVersion,
  oldWheel: path.basename(oldWheel),
  candidateWheel: path.basename(upgradeWheel),
  python: python.version,
  venvPython,
  engineUpdate: stateAfter,
  managedRecord: finalRecord,
  oldInterpreter: migrationMode ? { python: venvPython, version: oldVersion, unchanged: true } : null,
  privateEngine: migrationMode ? { root: engineRoot, python: enginePython } : null,
  tool: { exit: toolResult.ok, textHead: String(toolResult.text || '').slice(0, 160), child: toolRun },
  artifacts: smokeRoot,
}
console.log(JSON.stringify(summary, null, 2))
process.exit(0)
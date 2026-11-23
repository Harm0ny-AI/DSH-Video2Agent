import { spawn } from 'node:child_process'
import crypto from 'node:crypto'
import fs from 'node:fs'
import https from 'node:https'
import os from 'node:os'
import path from 'node:path'
import { createCampaignManager } from './campaign.js'

export const name = 'dsh-video2agent'
// webServer is deliberately NOT a hard dependency: the agent tool and the
// /video command must still load in headless/TUI profiles, where no web server
// exists. Routes are registered through whenWebServer() instead.
export const inject = ['commands', 'tools', 'systemPrompt']

// The schema package is an optional peer when DSH provides it; a bare checkout
// and the Node harnesses have no node_modules, so a missing package degrades to
// "no Config schema" instead of making the plugin fail to load.

let Schema = null
try {
  const mod = await import('@deepseek-ai/schemastery')
  Schema = mod.default ?? mod
} catch {
  Schema = null
}

// The web server that owns these routes. It is set when the optional service is
// available so guardWrite can compare the browser's Origin with the advertised
// one; without it the advertised-origin fallback used to be an undefined variable.
let ACTIVE_WEB_SERVER = null
// One optional Douyin QR-login child at a time. The CLI prints the QR screenshot
// first and blocks until the scan (or its timeout), so the Host keeps the child
// and serves the image instead of holding a three-minute HTTP request open.
let DOUYIN_LOGIN_STATE = null

// The npm package version. The environment card compares it with the installed
// Python CLI: the CLI carries the platform fixes (macOS Keychain key storage,
// OCR engine support), so an outdated CLI must be updatable from the page — a
// "CLI installed" chip alone would hide a CLI that cannot save the API key.
const PLUGIN_VERSION = (() => {
  try {
    return String(JSON.parse(fs.readFileSync(new URL('./package.json', import.meta.url), 'utf8')).version || '')
  } catch {
    return ''
  }
})()

function compareVersions(a, b) {
  const pa = String(a || '').split('.').map((x) => Number(x) || 0)
  const pb = String(b || '').split('.').map((x) => Number(x) || 0)
  for (let i = 0; i < Math.max(pa.length, pb.length); i += 1) {
    const da = pa[i] || 0
    const db = pb[i] || 0
    if (da !== db) return da < db ? -1 : 1
  }
  return 0
}

// CLI helper commands print pretty-printed JSON, so the last line is just "}".
// Parse the whole payload, and still tolerate a warning line before the object.
function parseJsonObjectText(text) {
  const trimmed = String(text || '').trim()
  if (!trimmed) return null
  const candidates = [trimmed]
  const first = trimmed.indexOf('{')
  const last = trimmed.lastIndexOf('}')
  if (first >= 0 && last > first) candidates.push(trimmed.slice(first, last + 1))
  for (const candidate of candidates) {
    try { return JSON.parse(candidate) } catch {}
  }
  return null
}

// The plugin row's Config, so DSH's own config editor validates and shows these
// values alongside every other plugin instead of hiding them in a private file.
// Runtime precedence: ui-settings.json (written by the settings form) over this
// row config over the built-in defaults.
export const Config = Schema
  ? Schema.object({
    enabled: Schema.boolean().default(true).description('Show the Video2Agent batch table above the composer.'),
douyinSearch: Schema.boolean().default(false).description('Enable Douyin keyword search by default. Off means find searches Bilibili only unless the user explicitly asks for Douyin.'),
    accentColor: Schema.string().pattern(/^#[0-9a-fA-F]{6}$/).default('#0a84ff').description('Accent colour for Video2Agent surfaces (#rrggbb).'),
    processLimit: Schema.natural().min(1).max(10).default(10).description('Maximum videos the card may process in one run (1-10).'),
    cacheTtlMs: Schema.natural().min(60000).default(86400000).description('How long a link preview is reused.'),
    cacheExpire: Schema.boolean().default(true).description('Free the media and frame files of old videos after the cache age; transcript and on-screen text stay searchable.'),
    cacheDays: Schema.natural().min(1).max(365).default(7).description('Cache age in days before a video\'s media is freed.'),
    cacheLimitEnabled: Schema.boolean().default(false).description('Evict the oldest cache entries when the cache exceeds a size cap.'),
    cacheLimitGb: Schema.natural().min(1).max(20).default(20).description('Cache size cap in GB (1-20); only used when the cap is enabled.'),
  })
  : undefined

// Resolve the CLI per call, not at import time: a long-lived Host process must
// pick up a changed VIDEO2AGENT_BIN (and tests can point it at a missing binary).
// A CLI installed by the setup card may not be on this process's PATH (pip's
// Scripts dir is often missing). The card records the interpreter that can run
// "python -m video2agent", and every spawn builds the argv from it.
function cliCommand() {
  if (process.env.VIDEO2AGENT_BIN) return { command: process.env.VIDEO2AGENT_BIN, prefix: [] }
  try {
    const cli = readManagedTools().cli
    if (cli && cli.python) {
      if (usableInterpreterPath(cli.python)) {
        return { command: cli.python, prefix: [...(cli.prefix || []), '-m', 'video2agent'] }
      }
      // detectCli verified this launcher by actually running the module. Use the
      // recorded invocation instead of guessing a possibly different
      // "video2agent" binary on PATH. A bare legacy record is not trusted here.
      if (cli.source === 'detected' && isBareCommandName(cli.python)) {
        return {
          command: String(cli.python),
          prefix: [...(Array.isArray(cli.prefix) ? cli.prefix.map(String) : []), '-m', 'video2agent'],
        }
      }
    }
  } catch {}
  return { command: 'video2agent', prefix: [] }
}

function cliInterpreter() {
  const invocation = cliCommand()
  if (invocation.prefix.length >= 2 &&
      invocation.prefix[invocation.prefix.length - 2] === '-m') {
    return { command: invocation.command, prefix: invocation.prefix.slice(0, -2) }
  }
  return null
}

function binPath() {
  const invocation = cliCommand()
  return invocation.prefix.length ? invocation.command + ' ' + invocation.prefix.join(' ') : invocation.command
}

// Windows app-execution aliases (the Store Python exposed through "py") can be
// spawned, but fs.existsSync follows the reparse point and reports false while
// lstat still sees the alias. Use lstat so a recorded interpreter that really
// runs is not mistaken for a missing one.
function usableInterpreterPath(candidate) {
  const text = String(candidate || '')
  if (!text) return false
  try {
    const stat = fs.lstatSync(text)
    return stat.isFile() || stat.isSymbolicLink()
  } catch {
    return false
  }
}

// Tools the plugin can provide to the Python CLI. FFmpeg may be installed after
// the app started (PATH is a snapshot), so the setup card records where winget/brew
// put it and every CLI spawn gets FFMPEG_BIN/FFPROBE_BIN.
function v2aHomePath() {
  return process.env.VIDEO2AGENT_HOME || path.join(os.homedir(), '.video2agent')
}

function managedToolsPath() {
  return path.join(v2aHomePath(), 'tools', 'ffmpeg.json')
}

function readManagedTools() {
  try {
    const parsed = JSON.parse(fs.readFileSync(managedToolsPath(), 'utf8'))
    return parsed && typeof parsed === 'object' ? parsed : {}
  } catch {
    return {}
  }
}

function managedToolEnv(baseEnv = process.env) {
  const env = { ...baseEnv }
  const tools = readManagedTools()
  if (tools.ffmpeg && fs.existsSync(tools.ffmpeg)) env.FFMPEG_BIN = tools.ffmpeg
  if (tools.ffprobe && fs.existsSync(tools.ffprobe)) env.FFPROBE_BIN = tools.ffprobe
  return env
}

// pip can install the console script into a Scripts dir this app does not have on
// PATH. Record the interpreter that runs "python -m video2agent" (a .cmd wrapper
// cannot be spawned without a shell, and shell quoting breaks Chinese paths).
// The optional provenance fields are what authorize an upgrade. A bare record is
// deliberately ambiguous: old versions wrote it after a mere detection, so it
// must not authorize anything.
function saveManagedCli(pythonCommand, pythonPrefix, extra = {}) {
  const target = managedToolsPath()
  const temporary = target + '.tmp-' + process.pid + '-' + Date.now()
  try {
    const tools = readManagedTools()
    const previous = tools.cli && typeof tools.cli === 'object' ? tools.cli : {}
    fs.mkdirSync(path.dirname(target), { recursive: true })
    const cli = {
      ...previous,
      python: pythonCommand,
      prefix: pythonPrefix || [],
      at: new Date().toISOString(),
      ...(extra && typeof extra === 'object' ? extra : {}),
    }
    // Atomic replace: a crash must never leave a half-written record that makes
    // cliCommand guess another interpreter. Same directory keeps the rename on
    // one filesystem.
    fs.writeFileSync(temporary, JSON.stringify({ ...tools, cli }, null, 2), 'utf8')
    fs.renameSync(temporary, target)
    return true
  } catch {
    try { fs.rmSync(temporary, { force: true }) } catch {}
    return false
  }
}

// Detection only proves that this interpreter can run the CLI; it does not prove
// who installed it. Never let a probe overwrite a provenance record.
function recordDetectedCli(pythonCommand, pythonPrefix) {
  const existing = readManagedTools().cli
  if (existing && typeof existing === 'object' && existing.source === 'plugin-install') return false
  return saveManagedCli(pythonCommand, pythonPrefix, { source: 'detected', auto_update: false })
}

// detectCli has already proven that this launcher can run "python -m
// video2agent". Store the actual interpreter so every later tool call can use
// the record; if that resolution fails, keep the verified launcher (cliCommand
// knows how to invoke a detected bare command). Detection never authorizes
// automatic updates.
async function recordVerifiedCli(pythonCommand, pythonPrefix) {
  const launcher = {
    command: String(pythonCommand || ''),
    prefix: Array.isArray(pythonPrefix) ? pythonPrefix.map(String) : [],
  }
  const absolute = launcher.command ? await probeEngineInterpreter(launcher) : ''
  return recordDetectedCli(absolute || launcher.command, absolute ? [] : launcher.prefix)
}

// The Python package that does the video work. The npm package and the CLI are
// released together (0.3.5 <-> 0.3.5), so a managed engine upgrade has exactly
// one target: this plugin's loaded version.
const CLI_PACKAGE = 'video2agent'
// Automatic pip must finish well inside a normal tool budget. A manual click may
// use the full setup budget.
const ENGINE_AUTO_PIP_TIMEOUT_MS = 90000
// A legacy migration also has to create a venv and carry the optional extras the
// old engine already had (browser/OCR wheels are much larger than the core
// package), so its single bounded pip gets a larger budget. The managed in-place
// path above keeps its short automatic budget.
const ENGINE_MIGRATE_PIP_TIMEOUT_MS = 180000
const ENGINE_WORKER_QUIESCE_MS = 15000
const ENGINE_UPDATE = { state: 'idle', target: '', message: '' }
// Test-only seams. The Node harness must never run a real pip against the
// machine; injected probes keep the eligibility/validation logic honest.
const ENGINE_TEST_HOOKS = {
  pipInstall: null,
  probeVersion: null,
  probeDistribution: null,
  probeInterpreter: null,
  probeEnvironment: null,
  onDiskVersion: null,
  // Legacy migration seams: the real harness never creates a venv on the test
  // machine, spawns the PATH CLI, or runs pip. The smoke can leave these unset
  // to exercise the real cross-platform path.
  probePathCli: null,
  probeCliDoctor: null,
  probeExtras: null,
  createVenv: null,
  browserRuntime: null,
  ocrRuntime: null,
  // Component installs (OCR/browser) run one injected pip; the harness never
  // touches a real environment.
  componentPip: null,
}
let ENGINE_READY_GATE = null
let ENGINE_READY_RESOLVE = null
let ENGINE_AUTO_STARTED = false
// A manual engine pip temporarily replaces the package files. New tool, GC and
// /video calls wait here instead of spawning the CLI that pip is rewriting. The
// updater's own probes never take this barrier, so it cannot deadlock itself.
let ENGINE_INSTALL_GATE = null
let ENGINE_INSTALL_RESOLVE = null
// The settings page polls /setup while an update is in flight. A full probe
// starts Python, the CLI, FFmpeg, OCR and browser checks; do not repeat that on
// every poll. Three seconds covers a page that mounts twice, while any engine
// state change invalidates the entry immediately.
const SETUP_STATUS_CACHE_TTL_MS = 3000
let SETUP_STATUS_CACHE = null
// A warm worker is never killed while a request is in flight. After an update
// the next idle moment stops it so the next call spawns the new CLI.
let WORKER_STALE = false

function onDiskPluginVersion() {
  if (ENGINE_TEST_HOOKS.onDiskVersion) return String(ENGINE_TEST_HOOKS.onDiskVersion)
  try {
    // The sibling package.json is the only disk evidence available by default.
    // When the module is loaded from a .pnpm path that is the loaded package, not
    // necessarily the active profile alias, so this is reported as observed and
    // is never turned into a guess about some other directory. A launch context
    // that knows the active profile can supply VIDEO2AGENT_PLUGIN_MANIFEST; then
    // that manifest is the authoritative on-disk version.
    const configured = String(process.env.VIDEO2AGENT_PLUGIN_MANIFEST || '').trim()
    const manifest = configured || new URL('./package.json', import.meta.url)
    return String(JSON.parse(fs.readFileSync(manifest, 'utf8')).version || '').trim()
  } catch {
    return ''
  }
}

function pluginRestartRequired() {
  const installed = onDiskPluginVersion()
  // Evidence only: an unreadable manifest is unknown, not "restart". A
  // same-version replacement cannot be detected this round; refreshing the page
  // is not reloading the plugin and must never be reported as such.
  return Boolean(installed && PLUGIN_VERSION && installed !== PLUGIN_VERSION)
}

function setEngineUpdate(state, target = '', message = '') {
  ENGINE_UPDATE.state = ['idle', 'updating', 'ready', 'failed'].includes(state) ? state : 'idle'
  ENGINE_UPDATE.target = ENGINE_UPDATE.state === 'idle' ? '' : String(target || '')
  ENGINE_UPDATE.message = String(message || '')
  // A polling client must see the state change immediately. Keep the probe
  // snapshot while updating so GET never re-runs a CLI probe against a package
  // pip is replacing; ready/failed clear it so the next read is fresh.
  if (state !== 'updating') SETUP_STATUS_CACHE = null
}

function engineUpdatePublic() {
  const out = { state: ENGINE_UPDATE.state }
  if (ENGINE_UPDATE.target) out.target = ENGINE_UPDATE.target
  if (ENGINE_UPDATE.message) out.message = ENGINE_UPDATE.message
  return out
}

function createEngineReadyGate() {
  // The gate is a startup barrier. Once it has settled, later applies reuse it
  // (and a manual update never re-blocks an already-running Host).
  if (ENGINE_READY_GATE && !ENGINE_READY_RESOLVE) return
  ENGINE_READY_GATE = new Promise((resolve) => { ENGINE_READY_RESOLVE = resolve })
}

function resolveEngineReadyGate() {
  const resolve = ENGINE_READY_RESOLVE
  ENGINE_READY_RESOLVE = null
  if (resolve) resolve()
}

function beginEngineInstall() {
  if (ENGINE_INSTALL_RESOLVE) return
  ENGINE_INSTALL_GATE = new Promise((resolve) => { ENGINE_INSTALL_RESOLVE = resolve })
}

function finishEngineInstall() {
  const resolve = ENGINE_INSTALL_RESOLVE
  ENGINE_INSTALL_RESOLVE = null
  ENGINE_INSTALL_GATE = null
  if (resolve) resolve()
}

async function waitForEngineReady() {
  const gate = ENGINE_READY_GATE
  if (gate) {
    try { await gate } catch {}
  }
  const install = ENGINE_INSTALL_GATE
  if (install) {
    try { await install } catch {}
  }
}

function engineUpdateMarkerPath() {
  return path.join(v2aHomePath(), 'engine-update.json')
}

function readEngineUpdateMarker() {
  try {
    const parsed = JSON.parse(fs.readFileSync(engineUpdateMarkerPath(), 'utf8'))
    return parsed && typeof parsed === 'object' ? parsed : null
  } catch {
    return null
  }
}

function writeEngineUpdateMarker(marker) {
  try {
    fs.mkdirSync(path.dirname(engineUpdateMarkerPath()), { recursive: true })
    fs.writeFileSync(engineUpdateMarkerPath(), JSON.stringify(marker, null, 2), 'utf8')
    return true
  } catch {
    return false
  }
}

function clearEngineUpdateMarker() {
  try { fs.rmSync(engineUpdateMarkerPath(), { force: true }) } catch {}
}

// A legacy adoption is heavier than an in-place update: it builds a new venv and
// installs the package there. A failed attempt must not repeat on every DSH
// start, so its failure is persisted with its own kind. The managed in-place
// updater keeps its own marker semantics and must never mistake this one for its
// own failed attempt.
const LEGACY_MIGRATION_MARKER_KIND = 'legacy-migrate'

function readLegacyMigrationFailure() {
  if (!PLUGIN_VERSION) return null
  const marker = readEngineUpdateMarker()
  if (!marker || marker.kind !== LEGACY_MIGRATION_MARKER_KIND || marker.state !== 'failed') return null
  if (marker.plugin_version !== PLUGIN_VERSION || marker.target !== PLUGIN_VERSION) return null
  return marker
}

// Written only after an install was actually attempted. A failure before that
// (for example a venv that cannot be created) is transient and may retry.
function writeLegacyMigrationFailure(message, oldVersion) {
  return writeEngineUpdateMarker({
    kind: LEGACY_MIGRATION_MARKER_KIND,
    plugin_version: PLUGIN_VERSION,
    target: PLUGIN_VERSION,
    state: 'failed',
    message: String(message || ''),
    old_version: String(oldVersion || ''),
    at: new Date().toISOString(),
  })
}

// Test-only reset, used after the first gate settles. It is deliberately
// separate from normal runtime state so a harness can exercise fail/retry paths.
function resetEngineUpdateForTest() {
  ENGINE_AUTO_STARTED = false
  ENGINE_READY_GATE = null
  ENGINE_READY_RESOLVE = null
  finishEngineInstall()
  WORKER_STALE = false
  setEngineUpdate('idle')
  clearEngineUpdateMarker()
  for (const key of Object.keys(ENGINE_TEST_HOOKS)) ENGINE_TEST_HOOKS[key] = null
}

// A managed CLI target is the interpreter that really runs "python -m
// video2agent". It is never inferred from a different Python probe: only the
// recorded interpreter counts, which is what makes an upgrade safe.
function managedCliTarget({ requireAuthorization = true } = {}) {
  const cli = readManagedTools().cli
  if (!cli || typeof cli !== 'object' || !cli.python) return { ok: false, reason: 'no-managed-cli' }
  if (!usableInterpreterPath(cli.python)) return { ok: false, reason: 'interpreter-missing' }
  if (requireAuthorization && (cli.source !== 'plugin-install' || cli.auto_update !== true)) {
    return { ok: false, reason: 'not-authorized' }
  }
  return {
    ok: true,
    command: String(cli.python),
    prefix: Array.isArray(cli.prefix) ? cli.prefix.map(String) : [],
    record: cli,
  }
}

function engineAutoTarget() {
  // An explicit path/Python pin is the user's choice. Never overwrite or update
  // it automatically, even when a managed record also exists.
  if (process.env.VIDEO2AGENT_BIN) return { ok: false, reason: 'explicit-bin' }
  if (process.env.VIDEO2AGENT_PYTHON) return { ok: false, reason: 'explicit-python' }
  return managedCliTarget({ requireAuthorization: true })
}

// A legacy record can name the launcher ("py", "python3") instead of an
// absolute interpreter. Only a manual action may resolve that name; automatic
// updates must never treat it as an authorized target.
function isBareCommandName(command) {
  const text = String(command || '').trim()
  return Boolean(text) && !path.isAbsolute(text) && !text.includes('/') && !text.includes('\\')
}

function engineOutputVersion(text) {
  const line = String(text || '').trim().split('\n').pop() || ''
  return (line.match(/(\d+\.\d+\.\d+)/) || [])[1] || ''
}

async function probeEngineVersion(target) {
  if (ENGINE_TEST_HOOKS.probeVersion) return await ENGINE_TEST_HOOKS.probeVersion(target)
  const r = await runCommand(target.command, [...(target.prefix || []), '-m', CLI_PACKAGE, '--version'], 30000)
  if (r.code !== 0) {
    return { ok: false, version: '', detail: String(r.err || r.out || 'version probe failed').slice(0, 300) }
  }
  const version = engineOutputVersion(r.out)
  return { ok: Boolean(version), version, detail: String(r.out || '').slice(0, 300) }
}

async function probeEngineDistribution(target) {
  if (ENGINE_TEST_HOOKS.probeDistribution) return await ENGINE_TEST_HOOKS.probeDistribution(target)
  const code = [
    'import importlib.metadata as m, json',
    'try:',
    '    d = m.distribution("video2agent")',
    '    try:',
    '        du = d.read_text("direct_url.json") or ""',
    '    except Exception:',
    '        du = ""',
    '    print(json.dumps({"ok": True, "version": d.version, "direct_url": du}))',
    'except Exception as e:',
    '    print(json.dumps({"ok": False, "error": str(e)}))',
  ].join('\n')
  const r = await runCommand(target.command, [...(target.prefix || []), '-c', code], 30000)
  const line = String(r.out || '').trim().split('\n').pop() || ''
  try {
    const data = JSON.parse(line)
    const directUrl = String(data.direct_url || '')
    return {
      ok: data.ok === true,
      version: String(data.version || ''),
      direct_url: directUrl,
      editable: /"editable"\s*:\s*true/.test(directUrl),
      detail: String(data.error || '').slice(0, 300),
    }
  } catch {
    return { ok: false, version: '', direct_url: '', editable: false, detail: line.slice(0, 300) }
  }
}

async function probeEngineEnvironment(target) {
  if (ENGINE_TEST_HOOKS.probeEnvironment) return await ENGINE_TEST_HOOKS.probeEnvironment(target)
  const code = [
    'import json, os, sys, sysconfig',
    'venv = sys.prefix != getattr(sys, "base_prefix", sys.prefix)',
    'stdlib = sysconfig.get_path("stdlib") or ""',
    'marker = os.path.join(stdlib, "EXTERNALLY-MANAGED") if stdlib else ""',
    'print(json.dumps({"ok": True, "venv": bool(venv), "externally_managed": bool(marker and os.path.exists(marker)), "marker": marker}))',
  ].join('\n')
  const r = await runCommand(target.command, [...(target.prefix || []), '-c', code], 30000)
  const line = String(r.out || '').trim().split('\n').pop() || ''
  try {
    const data = JSON.parse(line)
    return {
      ok: data.ok === true,
      venv: data.venv === true,
      externally_managed: data.externally_managed === true,
      marker: String(data.marker || ''),
      detail: String(data.error || '').slice(0, 300),
    }
  } catch {
    return { ok: false, venv: false, externally_managed: false, marker: '', detail: line.slice(0, 300) }
  }
}

async function probeEngineInterpreter(target) {
  if (ENGINE_TEST_HOOKS.probeInterpreter) return await ENGINE_TEST_HOOKS.probeInterpreter(target)
  const r = await runCommand(target.command, [...(target.prefix || []), '-c', 'import sys; print(sys.executable)'], 30000)
  const line = String(r.out || '').trim().split('\n').pop() || ''
  return r.code === 0 && line && usableInterpreterPath(line) ? line : ''
}

async function pipInstallEngine(target, { spec, timeoutMs, mirror = false }) {
  if (ENGINE_TEST_HOOKS.pipInstall) return await ENGINE_TEST_HOOKS.pipInstall(target, { spec, timeoutMs, mirror })
  const base = [...(target.prefix || []), '-m', 'pip', 'install', '--upgrade', '--no-input', spec]
  let r = await runCommand(target.command, base, timeoutMs)
  let note = ''
  if (r.code !== 0 && mirror) {
    note = '默认 PyPI 源安装失败，改用清华镜像重试…\n'
    r = await runCommand(target.command, [...base, '-i', 'https://pypi.tuna.tsinghua.edu.cn/simple'], timeoutMs)
  }
  return {
    code: r.code,
    output: (note + ((String(r.out || '') + '\n' + String(r.err || '')).trim())).slice(-8000),
    detail: String(r.err || r.out || '').slice(0, 300),
  }
}

function workerBusy() {
  return Boolean(WORKER && WORKER.pending)
}

async function waitForWorkerQuiescence(timeoutMs) {
  if (!workerBusy()) return true
  let timer = null
  const timeout = new Promise((resolve) => {
    timer = setTimeout(() => resolve(false), timeoutMs)
    timer.unref?.()
  })
  const settled = WORKER_QUEUE.then(() => true, () => true)
  const result = await Promise.race([settled, timeout])
  if (timer) clearTimeout(timer)
  return result === true
}

function markWorkerStale() {
  if (!WORKER) {
    WORKER_STALE = false
    return
  }
  if (WORKER.pending) {
    WORKER_STALE = true
    return
  }
  WORKER_STALE = false
  stopWorker()
}

// Spawn any helper command (python, pip, winget, ffmpeg) with the same capture and
// timeout rules as the CLI runner.
function runCommand(command, args, timeoutMs = 600000, env = managedToolEnv()) {
  return new Promise((resolve) => {
    let out = ''
    let err = ''
    let done = false
    const finish = (value) => {
      if (done) return
      done = true
      resolve(value)
    }
    let child
    try {
      child = spawn(command, args, { windowsHide: true, env })
    } catch (e) {
      finish({ code: -1, out: '', err: String((e && e.message) || e) })
      return
    }
    const timer = setTimeout(() => {
      killTree(child)
      finish({ code: -2, out: out.trim(), err: 'Timed out.' })
    }, timeoutMs)
    try { child.stdin.end() } catch {}
    child.stdout.setEncoding('utf8')
    child.stderr.setEncoding('utf8')
    child.stdout.on('data', (d) => { out = appendCapture(out, d) })
    child.stderr.on('data', (d) => { err = appendCapture(err, d) })
    child.on('error', (e) => {
      clearTimeout(timer)
      finish({ code: -1, out: out.trim(), err: String((e && e.message) || e) })
    })
    child.on('close', (code) => {
      clearTimeout(timer)
      finish({ code, out: out.trim(), err: err.trim() })
    })
  })
}

const MAX_CAPTURE = 2 * 1024 * 1024
const WORKER_IDLE_MS = 10 * 60 * 1000
const WORKER_COMMANDS = new Set(['search', 'overview', 'transcript', 'compare', 'digest', 'perceive', 'evidence', 'frames', 'map', 'candidates', 'ocr-window', 'list', 'find', 'outline', 'read', 'admin'])
// The worker is read-only; admin write actions must run in their own process and
// must never be re-run by the worker-failure fallback.
const ADMIN_WRITE_ACTIONS = new Set(['ocr-index', 'export', 'account', 'douyin'])

// Hard routing: public practical questions try one Bilibili/Douyin find before
// web search. It is registered only after the tool exists, owned by this plugin's
// context, and its text is empty while the plugin's surfaces are disabled, so
// disabling or removing the plugin leaves no routing rule behind.
const HARD_ROUTING_PROMPT = `## Video2Agent — check video before a web search

Before you run a web search (web_search, or answering from memory), first call video2agent find once with a concrete query. If the user named a specific site/source, follow that; if the user gave a Bilibili or Douyin link/video, process that video directly. find searches Bilibili by default. Douyin search is opt-in: use scope:"douyin" whenever the user explicitly asks for Douyin or a Douyin creator; a no-scope find includes Douyin only when the user has enabled the Douyin search setting. A saved Douyin login is required for Douyin results, and a Douyin URL still resolves directly.

If the question names a Douyin creator or asks for their videos, and find reports that Douyin login, verification or risk control is required, say so and stop for a login/check; do not silently replace it with a web search. Web search usually cannot see a small Douyin creator.

When the candidates come back, judge them on title, uploader, duration, view count and match with the question. Pick by quality, not by position; do not take the first N; if the candidates are weak, pick fewer or none instead of filling the batch with poor videos.

If the relevant candidates are not enough, call find again with a different search term and select from the new results too; stop when you have enough to answer the question. If the video side stays thin, stop the video search, fall back to web search or your own knowledge, and say the video side had nothing.

If a candidate looks like it can answer the question, analyze it: one video is enough when it covers the question; when the question needs comparison or several sources, select several at once (within the tool's limit) and process them together. Do not skip a candidate because it is long, slow, or costly — that cost is allowed here. Do not read the whole list, and do not stop after a single video if the question is not covered.

For a UI/interaction bug in the user's own app: ask for a recording that reproduces it, analyze it with outline/perceive/evidence, and do not search for private code or data.

When the user says not to use video, do not call video2agent.`


function killTree(child) {
  try {
    if (process.platform === 'win32' && child.pid) {
      const killer = spawn('taskkill', ['/PID', String(child.pid), '/T', '/F'], { windowsHide: true, stdio: 'ignore' })
      killer.on('error', () => {})
      killer.unref?.()
      return
    }
    child.kill('SIGKILL')
  } catch {}
}

function appendCapture(current, chunk) {
  if (current.length >= MAX_CAPTURE) return current
  return (current + chunk).slice(0, MAX_CAPTURE)
}

function runCli(args, timeoutMs = 600000, input = null) {
  return new Promise((resolve) => {
    let out = ''
    let err = ''
    let done = false
    const finish = (value) => {
      if (done) return
      done = true
      resolve(value)
    }
    let child
    const invocation = cliCommand()
    try {
      child = spawn(invocation.command, [...invocation.prefix, ...args], { windowsHide: true, env: managedToolEnv() })
    } catch (e) {
      finish({ code: -1, out: '', err: 'Cannot start video2agent: ' + (e?.message || e) })
      return
    }
    if (input !== null) {
      try { child.stdin.end(String(input)) } catch {}
    } else {
      try { child.stdin.end() } catch {}
    }
    const timer = setTimeout(() => {
      killTree(child)
      finish({ code: -2, out: out.trim(), err: 'Timed out. Try --detach and poll jobs.' })
    }, timeoutMs)
    // Pipe chunks can split a multi-byte UTF-8 character; setEncoding uses a
    // StringDecoder so Chinese/JSON never turns into U+FFFD (the worker path
    // already does this).
    child.stdout.setEncoding('utf8')
    child.stderr.setEncoding('utf8')
    child.stdout.on('data', (d) => { out = appendCapture(out, d) })
    child.stderr.on('data', (d) => { err = appendCapture(err, d) })
    child.on('error', (e) => {
      clearTimeout(timer)
      finish({ code: -1, out: out.trim(), err: String(e?.message || e) })
    })
    child.on('close', (code) => {
      clearTimeout(timer)
      finish({ code, out: out.trim(), err: err.trim() })
    })
  })
}

// A single warm JSON-lines worker per Host. It is started lazily, handles one
// read command at a time, and is stopped after an idle period. ASR/OCR are not
// preloaded: the worker imports them only when the selected command needs them.
let WORKER = null
let WORKER_SEQ = 0
let WORKER_QUEUE = Promise.resolve()

function workerEligible(args) {
  const command = String((args && args.command) || '')
  if (!WORKER_COMMANDS.has(command)) return false
  if (command === 'admin') return !ADMIN_WRITE_ACTIONS.has(String((args && (args.admin_action || args.action)) || ''))
  return true
}

function _workerFail(worker, message) {
  if (!worker) return
  if (WORKER === worker) WORKER = null
  clearTimeout(worker.idle)
  const pending = worker.pending
  worker.pending = null
  if (pending) {
    clearTimeout(pending.timer)
    pending.reject(new Error(message))
  }
  try { killTree(worker.child) } catch {}
}

function _workerIdle(worker) {
  clearTimeout(worker.idle)
  if (!worker.pending) {
    worker.idle = setTimeout(() => {
      if (WORKER === worker && !worker.pending) _workerFail(worker, 'worker idle timeout')
    }, WORKER_IDLE_MS)
    worker.idle.unref?.()
  }
}

function _workerStart() {
  const workerInvocation = cliCommand()
  const child = spawn(workerInvocation.command, [...workerInvocation.prefix, '__worker'], { windowsHide: true, env: managedToolEnv() })
  const worker = { child, pending: null, buffer: '', stderr: '', idle: null }
  WORKER = worker
  // The worker is an optimization, not a reason for the Host to stay alive.
  child.unref?.()
  child.stdin.unref?.()
  child.stdout.unref?.()
  child.stderr.unref?.()
  child.stdout.setEncoding('utf8')
  child.stderr.setEncoding('utf8')
  child.stdout.on('data', (chunk) => {
    worker.buffer += chunk
    let index
    while ((index = worker.buffer.indexOf('\n')) >= 0) {
      const line = worker.buffer.slice(0, index).trim()
      worker.buffer = worker.buffer.slice(index + 1)
      if (!line) continue
      let message
      try {
        message = JSON.parse(line)
      } catch {
        _workerFail(worker, 'invalid worker response')
        return
      }
      if (!worker.pending || message.id !== worker.pending.id) continue
      const pending = worker.pending
      worker.pending = null
      clearTimeout(pending.timer)
      pending.resolve({
        code: Number(message.code) || 0,
        out: String(message.out || '').slice(0, MAX_CAPTURE),
        err: String(message.err || '').slice(0, MAX_CAPTURE),
      })
      _workerIdle(worker)
      // The engine changed while this request was in flight. Do not kill it;
      // stop the old process only now that it is idle, so the next call starts
      // the new CLI.
      if (WORKER_STALE && WORKER === worker && !worker.pending) stopWorker()
    }
  })
  child.stderr.on('data', (chunk) => {
    worker.stderr = appendCapture(worker.stderr, chunk)
  })
  child.on('error', (error) => _workerFail(worker, String(error?.message || error)))
  child.on('close', () => _workerFail(worker, 'worker exited'))
  _workerIdle(worker)
  return worker
}

function _runWorker(args, timeoutMs) {
  return new Promise((resolve, reject) => {
    let worker
    try {
      worker = WORKER || _workerStart()
    } catch (error) {
      reject(error)
      return
    }
    if (!worker || !worker.child.stdin.writable) {
      _workerFail(worker, 'worker stdin is closed')
      reject(new Error('worker stdin is closed'))
      return
    }
    const id = ++WORKER_SEQ
    const timer = setTimeout(() => {
      _workerFail(worker, 'worker timeout')
    }, timeoutMs)
    worker.pending = { id, timer, resolve, reject }
    try {
      worker.child.stdin.write(JSON.stringify({ id, argv: args }) + '\n')
    } catch (error) {
      _workerFail(worker, String(error?.message || error))
    }
  })
}

function runWorker(args, timeoutMs = 600000) {
  const run = () => _runWorker(args, timeoutMs)
  const next = WORKER_QUEUE.then(run, run)
  WORKER_QUEUE = next.catch(() => {})
  return next
}

async function runToolCommand(args, argv, timeoutMs) {
  // Startup is gated on the one engine probe/update. The gate is resolved even
  // when no update is eligible, so this never blocks a normal host forever.
  await waitForEngineReady()
  if (workerEligible(args)) {
    try {
      return await runWorker(argv, timeoutMs)
    } catch {
      // A warm worker is an optimization, never the only path. Fall back to a
      // fresh CLI process for this read-only command.
    }
  }
  return runCli(argv, timeoutMs)
}

function stopWorker() {
  const worker = WORKER
  WORKER = null
  WORKER_STALE = false
  if (worker) _workerFail(worker, 'worker stopped')
}

function workerPid() {
  return WORKER?.child?.pid || null
}

process.once('exit', stopWorker)

function tokenize(input) {
  const out = []
  const re = /"([^"]*)"|'([^']*)'|(\S+)/g
  let m
  while ((m = re.exec(input || '')) !== null) out.push(m[1] ?? m[2] ?? m[3])
  return out
}

// Whitelist + coerce whatever the settings file or the plugin row carries. Only
// known keys survive, the accent must be #rrggbb (it ends up in a stylesheet) and
// control characters are stripped from the cookie path (it becomes one argv entry).
function sanitizeUiSettings(raw) {
  const source = raw && typeof raw === 'object' ? raw : {}
  const number = (value, fallback, min, max) => {
    const n = Number(value)
    if (!Number.isFinite(n)) return fallback
    return Math.max(min, Math.min(max, Math.round(n)))
  }
  return {
    enabled: source.enabled !== false,
    douyinSearch: source.douyinSearch === true,
    cacheTtlMs: number(source.cacheTtlMs, 24 * 60 * 60 * 1000, 60 * 1000, 30 * 24 * 60 * 60 * 1000),
    cacheExpire: source.cacheExpire !== false,
    cacheDays: number(source.cacheDays, 7, 1, 365),
    cacheLimitEnabled: source.cacheLimitEnabled === true,
    cacheLimitGb: number(source.cacheLimitGb, 20, 1, 20),
    // No profile / OCR-budget / hold-time / auto-pick keys: ingest is lazy
    // (captions, else ASR, and a frame is OCR'd the first time it is asked for),
    // the model starts the videos it selected, and no countdown exists to tune.
    processLimit: number(source.processLimit, 10, 1, 10),
    accentColor: /^#[0-9a-fA-F]{6}$/.test(String(source.accentColor || '')) ? String(source.accentColor).toLowerCase() : '#0a84ff',
    cookiesPath: (() => {
      const cookiePath = String(source.cookiesPath == null ? '' : source.cookiesPath).trim()
      if (!cookiePath || cookiePath.length > 512) return ''
      return /[\u0000-\u001f]/.test(cookiePath) ? '' : cookiePath
    })(),
  }
}

// The plugin-row Config, as validated by schemastery, is the default layer. The
// settings file (written by the settings form) wins over it. `apply()` sets this
// once; the tool helpers below need the same view as the settings route, otherwise
// a Config edit would be visible in the UI but ignored by an ingest.
let ROW_CONFIG = null

function settingsFile() {
  const home = String(process.env.VIDEO2AGENT_HOME || path.join(os.homedir(), '.video2agent'))
  return path.join(home, 'ui-settings.json')
}

// Precedence: settings file > plugin-row Config > built-in defaults.
function readMergedSettings() {
  let file = null
  try {
    file = JSON.parse(fs.readFileSync(settingsFile(), 'utf8'))
  } catch {
    file = null
  }
  return sanitizeUiSettings({
    ...(ROW_CONFIG || {}),
    ...(file && typeof file === 'object' && !Array.isArray(file) ? file : {}),
  })
}

// Bilibili only exposes CC/AI subtitles to a logged-in request, so the plugin has
// to hand the CLI a cookie file. Only the path is stored here (never the secret).
function persistedCookiesPath() {
  const raw = String(readMergedSettings().cookiesPath || '').trim()
  return raw && fs.existsSync(raw) ? raw : null
}

function cliError(r) {
  if (r.code === 0) return null
  // The CLI already prints `{ok:false, error:{code,message,remedy}}` on failure.
  // Passing its stdout through raw turned the ErrorCard into a JSON wall, so parse
  // it first and keep the original code/remedy.
  const structured = parseStructuredError(r.out)
  if (structured) return structured
  // `doctor` exits 1 with `{ok:false, checks:[...]}` and no `error` object. Without
  // this branch the tool reported E_CLI with 1000 chars of JSON and dropped the
  // failing check's remedy.
  const doctor = doctorFailure(r.out)
  if (doctor) return doctor
  const code = r.code === -2 ? 'E_TIMEOUT' : r.code === -1 ? 'E_SPAWN' : 'E_CLI'
  const message = String(r.err || r.out || 'video2agent failed').slice(0, 1000)
  const remedy = code === 'E_SPAWN'
    ? 'Install the video2agent CLI: `pip install video2agent` (needs Python 3.11+), then reopen the app; or set VIDEO2AGENT_BIN to its full path. FFmpeg is also required (`winget install Gyan.FFmpeg` on Windows, `brew install ffmpeg` on macOS, `apt install ffmpeg` on Linux) — `video2agent doctor` checks both.'
    : code === 'E_TIMEOUT'
      ? 'Reduce the batch/limit and check the account before retrying; video ingest can use --detach and poll jobs.'
      : 'Run video2agent doctor and inspect the CLI error.'
  return { code, message, remedy }
}

// Frames are addressed by an opaque `<video_id>/<file>` id, never by an absolute
// path: the model may copy this URL into an answer, and a local path there leaks
// the user's directory layout. `path=` remains only for old links/tests.
// The answer's markdown renderer only accepts absolute http(s) images; a
// root-relative URL is treated as a local file path, its query string is
// dropped, and the image renders as 无法预览. Prefix the web server's origin.
function webOrigin() {
  try {
    const origin = ACTIVE_WEB_SERVER && typeof ACTIVE_WEB_SERVER.getOrigin === 'function'
      ? String(ACTIVE_WEB_SERVER.getOrigin() || '').trim()
      : ''
    return /^https?:\/\/[^/]+$/i.test(origin) ? origin : ''
  } catch { return '' }
}

function frameUrlFor(videoId, framePath) {
  const base = webOrigin()
  const vid = String(videoId || '')
  if (!vid) return base + '/api/video2agent/frame?path=' + encodeURIComponent(String(framePath))
  // `path.basename` is host-specific: on Linux it does not split a Windows path,
  // so a test/old link with C:\\... became the whole id. Split both separators.
  const name = String(framePath || '').split(/[\\/]/).pop()
  return base + '/api/video2agent/frame?id=' + encodeURIComponent(vid + '/' + name)
}

function doctorFailure(stdout) {
  const text = String(stdout || '').trim()
  if (!text.startsWith('{')) return null
  try {
    const parsed = JSON.parse(text)
    if (!parsed || parsed.ok !== false || !Array.isArray(parsed.checks)) return null
    const failed = parsed.checks.find((c) => c && c.required && !c.ok) || parsed.checks.find((c) => c && !c.ok)
    if (!failed) return null
    const name = String(failed.name || 'check')
    const detail = String(failed.detail || 'failed').slice(0, 300)
    return {
      code: 'E_DOCTOR',
      message: name + ': ' + detail,
      remedy: String(failed.remedy || parsed.next_step || 'Run video2agent doctor and fix the failing check.').slice(0, 400),
    }
  } catch {
    return null
  }
}

// Tool text is model input. A local path in overview.source.uri or a job row
// would be copied into the answer, so replace any absolute path with its file name.
function redactTextPaths(value) {
  // Windows drive/UNC paths and Unix absolute paths, even when embedded in a
  // sentence (doctor's "58.9 GB free at C:/Users/..." leaked before). The
  // lookbehind keeps URL schemes and already-relative fragments intact.
  const absolute = /(?<![A-Za-z0-9])(?:[A-Za-z]:[\\/]|\\\\[^\\/\s]+[\\/])[^\s"'<>|]+|(?<![:\w/])\/(?:[^\s"'<>|/]+\/)+[^\s"'<>|/]+/g
  const walk = (item) => {
    if (typeof item === 'string') {
      return item.replace(absolute, (match) => {
        const parts = match.split(/[\\/]+/).filter(Boolean)
        return parts.length ? parts[parts.length - 1] : match
      })
    }
    if (Array.isArray(item)) return item.map(walk)
    if (item && typeof item === 'object') {
      const out = {}
      for (const [key, child] of Object.entries(item)) out[key] = walk(child)
      return out
    }
    return item
  }
  return walk(value)
}

// An all-failed Douyin profile batch still answers the question: the per-person
// errors say which creator failed and why. The normal error wrapper collapses a
// failed CLI payload to only code/message/remedy, which would hide those rows, so
// this shape is allowlisted. Fields follow the CLI contract; unknown fields are
// dropped and paths are redacted before anything reaches the model.
function failedBatchProfileText(payload, error) {
  if (!payload || typeof payload !== 'object' || !Array.isArray(payload.results)) return null
  const bounded = (value, max) => String(value == null ? '' : value).slice(0, max)
  const counts = (value) => {
    if (!value || typeof value !== 'object') return undefined
    const out = {}
    for (const key of ['follows', 'fans', 'likes', 'works']) {
      if (value[key] !== undefined) out[key] = value[key]
    }
    return Object.keys(out).length ? out : undefined
  }
  const results = payload.results
    .filter((row) => row && typeof row === 'object')
    .map((row) => {
      const entry = { input: bounded(row.input, DOUYIN_PROFILE_INPUT_MAX), sec_uid: bounded(row.sec_uid, 128), ok: row.ok === true }
      if (row.ok === true) {
        if (row.url !== undefined) entry.url = bounded(row.url, 2048)
        for (const key of ['nickname', 'douyin_id']) {
          if (row[key] !== undefined) entry[key] = bounded(row[key], 200)
        }
        for (const key of ['follows', 'fans', 'likes', 'works']) {
          if (row[key] !== undefined) entry[key] = row[key]
        }
        const exact = counts(row.counts_exact)
        if (exact) entry.counts_exact = exact
        const displayed = counts(row.displayed_counts)
        if (displayed) entry.displayed_counts = displayed
      } else if (row.error && typeof row.error === 'object') {
        entry.error = {
          code: bounded(row.error.code, 64),
          message: bounded(row.error.message, 1000),
          remedy: bounded(row.error.remedy, 600),
        }
      }
      return entry
    })
  if (!results.length) return null
  const numeric = (value) => (Number.isFinite(Number(value)) ? Number(value) : undefined)
  const out = {
    ok: false,
    platform: 'douyin',
    count: numeric(payload.count) ?? results.length,
    succeeded: numeric(payload.succeeded) ?? 0,
    failed: numeric(payload.failed) ?? results.length,
    results,
    error: {
      code: bounded(error && error.code, 64) || 'E_DOUYIN_PROFILES',
      message: bounded(error && error.message, 1000),
      remedy: bounded(error && error.remedy, 600),
    },
  }
  for (const key of ['requested', 'duplicates', 'duration_ms', 'entry_timeout_s']) {
    const value = numeric(payload[key])
    if (value !== undefined) out[key] = value
  }
  return JSON.stringify(redactTextPaths(out))
}

function parseStructuredError(stdout) {
  const text = String(stdout || '').trim()
  if (!text.startsWith('{')) return null
  try {
    const parsed = JSON.parse(text)
    const error = parsed && parsed.ok === false ? parsed.error : null
    if (!error || typeof error !== 'object') return null
    const code = String(error.code || 'E_CLI').slice(0, 64)
    const message = String(error.message || 'video2agent failed').slice(0, 1000)
    const remedy = String(error.remedy || '').slice(0, 600)
    return remedy ? { code, message, remedy } : { code, message, remedy: 'Run video2agent doctor.' }
  } catch {
    return null
  }
}

// The schema declares these bounds; enforce them here too, because the model can pass
// anything and `images: 500` would otherwise ask the pipeline for 500 frames.
function clampInt(value, fallback, min, max) {
  const n = Number(value)
  if (!Number.isFinite(n)) return fallback
  return Math.max(min, Math.min(max, Math.round(n)))
}

// A positional argv entry that starts with "-" is parsed as a flag by argparse.
// The tool already rejects unknown JSON keys, but `source: "--force"` used to
// silently become an option and drop the real source. Reject it as an argument
// error instead of handing it to the CLI.
function badPositional(value) {
  const text = String(value == null ? '' : value)
  return text.startsWith('-')
}

// Douyin account reads are browser-backed and read-only. Keep the mapping here
// so the tool can read a logged-in Douyin account from any session, not only the
// CLI. Login itself stays in the settings card / CLI.
// A batch profile read opens one browser/context for 1-10 identities, reusing a
// page per person. Each identity is validated by the CLI, so one bad URL must
// not abort the batch and the Host only enforces the array shape/bounds.
const DOUYIN_PROFILES_MAX = 10
const DOUYIN_PROFILE_INPUT_MAX = 1024
// Default per-entry bound is 12s; 10 entries plus browser startup stay around
// 130s, so 240s leaves headroom without letting a hung browser hold a call for
// the normal 10-minute tool budget.
const DOUYIN_PROFILES_TIMEOUT_MS = 240000

function douyinBatchUrls(value) {
  if (!Array.isArray(value) || value.length < 1 || value.length > DOUYIN_PROFILES_MAX) return null
  const urls = []
  for (const item of value) {
    // Scalar only: an object would serialize into the argv and reach the CLI as
    // an identity it cannot reason about.
    if (typeof item !== 'string') return null
    const text = item.trim()
    if (!text || text.length > DOUYIN_PROFILE_INPUT_MAX) return null
    // A control character would corrupt the one-argv JSON value in logs and
    // terminal echoes; identity validity is still the CLI's decision.
    if (/[\u0000-\u001f\u007f]/.test(text)) return null
    urls.push(text)
  }
  return urls
}

function douyinAccountArgs(args) {
  const action = String(args.douyin_action || 'me')
  if (!['me', 'profile', 'videos', 'status', 'profiles'].includes(action)) return null
  const out = ['douyin', action]
  if (action === 'profiles') {
    const urls = douyinBatchUrls(args.douyin_urls)
    if (!urls) return null
    // Exactly one argv entry: the CLI parses the JSON array itself.
    out.push('--urls', JSON.stringify(urls), '--json')
    return out
  }
  const url = args.douyin_url == null ? '' : String(args.douyin_url).trim()
  if (action === 'profile' && !url) return null
  if ((action === 'profile' || action === 'videos') && url) {
    if (badPositional(url)) return null
    out.push('--url', url)
  }
  if (action === 'videos') {
    const tab = String(args.douyin_tab || 'works')
    if (!['works', 'likes', 'favorites'].includes(tab)) return null
    out.push('--tab', tab)
    if (args.limit !== undefined && args.limit !== null && args.limit !== '') {
      out.push('--limit', String(clampInt(args.limit, 20, 1, 50)))
    }
  }
  out.push('--json')
  return out
}

function looksLikeDouyinProfile(value) {
  const raw = String(value || '').trim()
  if (!raw) return false
  if (/^MS4wLjAB[A-Za-z0-9_-]{20,}$/.test(raw)) return true
  try {
    const u = new URL(raw)
    return /(^|\.)douyin\.com$/i.test(u.hostname) && /^\/user\//.test(u.pathname)
  } catch { return false }
}

// Search results already carry the author's sec_uid from the data they returned;
// deriving the profile URL adds no request. Only a verified Douyin sec_uid is
// trusted, and only Douyin rows change, so Bilibili candidates (and a placeholder
// or missing sec_uid) stay byte-identical. This lets find -> profiles chain
// without the model rebuilding the URL from the skill text.
function withCandidateProfileUrl(candidate) {
  if (!candidate || typeof candidate !== 'object') return candidate
  if (String(candidate.platform || '') !== 'douyin') return candidate
  const secUid = String(candidate.uploader_sec_uid || '').trim()
  if (!/^MS4wLjAB[A-Za-z0-9_-]{20,}$/.test(secUid)) return candidate
  return { ...candidate, profile_url: 'https://www.douyin.com/user/' + secUid }
}

function commandArgs(args) {
  const command = String(args.command || '')
  // Eight model-facing verbs; the rest are internal CLI names. One implementation
  // and one set of argv tests serve both surfaces.
  if (command === 'find') {
    if (args.url && !args.query) return commandArgs({ ...args, command: 'resolve' })
    return commandArgs({ ...args, command: args.scope === 'library' ? 'search' : 'discover' })
  }
  if (command === 'outline') {
    const detail = String(args.detail || 'digest')
    const mapped = detail === 'overview' ? 'overview' : (detail === 'map' ? 'map' : 'digest')
    return commandArgs({ ...args, command: mapped })
  }
  if (command === 'read') {
    const compare = args.scope === 'compare' || Array.isArray(args.compare_video_ids)
    return commandArgs({ ...args, command: compare ? 'compare' : 'transcript' })
  }
  if (command === 'frames') {
    // frames is both a verb and an internal name: only reroute its views.
    if (args.view === 'candidates') return commandArgs({ ...args, command: 'candidates' })
    if (args.view === 'ocr') return commandArgs({ ...args, command: 'ocr-window' })
  }
  if (command === 'ingest') {
    if (args.job_id) return commandArgs({ ...args, command: 'jobs' })
    // shortlist/campaign run before commandArgs in execute(); they have no argv.
    if (Array.isArray(args.video_ids) || args.campaign_id) return null
  }
  if (command === 'admin') {
    // Accept `action` as an alias: real model calls used it, and with
    // additionalProperties:false that silently fell back to the local list.
    const action = String(args.admin_action || args.action || 'list')
    if (action === 'douyin') return douyinAccountArgs(args)
    const mapped = action === 'export' ? 'export'
      : (action === 'ocr-index' ? 'ocr-index' : (action === 'account' ? 'account' : (action === 'doctor' ? 'doctor' : 'list')))
    return commandArgs({ ...args, command: mapped })
  }
  if (command === 'doctor') return ['doctor', '--json']
  if (command === 'list') return ['list', '--json']
  if (command === 'discover') {
    if (!args.query || badPositional(args.query)) return null
    const discover = ['discover', String(args.query), '--limit', String(clampInt(args.limit, 8, 1, 50))]
    if (args.scope === 'douyin') discover.push('--platform', 'douyin')
    else if (args.scope === 'bilibili') discover.push('--platform', 'bilibili')
    else if (args.scope === 'all') discover.push('--platform', 'all')
    else discover.push('--platform', readMergedSettings().douyinSearch === true ? 'all' : 'bilibili')
    // Narrowing a broad search is how "this creator's last three videos" works;
    // the filters go before --json so the flag order stays conventional.
    if (args.uploader) discover.push('--uploader', String(args.uploader))
    if (args.after) discover.push('--after', String(args.after))
    if (args.before) discover.push('--before', String(args.before))
    // Cover OCR is a deliberate quality tool, not the default: on this machine
    // 8 covers took 13.8s versus 0.9s without them. The card gets cover images
    // through /api/video2agent/cover anyway, so the model can opt in when it
    // genuinely needs visual matching.
    if (args.covers !== true) discover.push('--no-covers')
    discover.push('--json')
    return discover
  }
  if (command === 'resolve') {
    const url = args.url || args.source
    if (!url || badPositional(url)) return null
    return ['resolve', String(url), '--json']
  }
  if (command === 'ingest') {
    if (!args.source || badPositional(args.source)) return null
    // No profile and no OCR budget: the pipeline does the cheap, always-correct thing
    // (captions, else ASR) and reads a frame's text the first time that frame is
    // asked for. "How much work" is not a knob anyone has to set.
    const ingest = ['ingest', String(args.source)]
    // A logged-in cookie file is what makes Bilibili hand over its CC/AI subtitles
    // instead of falling back to ASR.
    const cookies = persistedCookiesPath()
    if (cookies) ingest.push('--cookies', cookies)
    if (args.force) ingest.push('--force')
    // An explicit ASR language is the only repair for a mis-detected transcript.
    if (args.language && !badPositional(args.language)) ingest.push('--language', String(args.language))
    ingest.push('--detach', '--json')
    return ingest
  }
  if (command === 'jobs') {
    if (!args.job_id) return ['jobs', '--json']
    if (!args.wait_ms) return ['jobs', '--id', String(args.job_id), '--json']
    // A blocking wait beats asking the model to poll. `wait_ms` is honoured by
    // bounding the CLI's own wait to it (capped below the tool's process timeout),
    // so the call returns before the plugin kills the process.
    // A single wait must fit inside the harness's per-program budget (~120s in
    // run_code): a 200s wait made the whole program die with the wait half done
    // and nothing to show. 90s leaves room to parse and answer.
    const seconds = clampInt(Number(args.wait_ms) / 1000, 45, 5, 90)
    return ['jobs', '--id', String(args.job_id), '--wait', '--wait-timeout', String(seconds), '--json']
  }
  if (command === 'overview') {
    if (!args.video_id) return null
    return ['overview', String(args.video_id), '--json']
  }
  if (command === 'compare') {
    const ids = (Array.isArray(args.compare_video_ids) ? args.compare_video_ids : (Array.isArray(args.video_ids) ? args.video_ids : [])).map(String).filter(Boolean)
    if (ids.length < 2 || ids.length > 10) return null
    const out = ['compare', ...ids]
    if (args.aspects) out.push('--aspects', String(args.aspects))
    out.push('--per-video', String(clampInt(args.per_video, 2, 1, 5)))
    out.push('--max-chars', String(clampInt(args.max_chars, 12000, 2000, 30000)))
    if (args.max_total_chars !== undefined) out.push('--max-total-chars', String(clampInt(args.max_total_chars, 40000, 200, 120000)))
    out.push('--compact')
    out.push('--json')
    return out
  }
  if (command === 'ocr-index') {
    if (!args.video_id) return null
    return ['ocr-index', String(args.video_id), '--json']
  }
  if (command === 'perceive') {
    // Numbers first, no images: the perception map is what tells the model
    // where to look, and evidence/frames stay the only image path.
    if (!args.video_id) return null
    const out = ['perceive', String(args.video_id)]
    if (args.start) out.push('--start', String(args.start))
    if (args.end) out.push('--end', String(args.end))
    if (args.fps !== undefined && args.fps !== null) {
      out.push('--fps', String(clampInt(args.fps, 10, 1, 30)))
    }
    if (args.max_frames !== undefined && args.max_frames !== null) {
      out.push('--max-frames', String(clampInt(args.max_frames, 20000, 100, 40000)))
    }
    if (args.brief === true) out.push('--brief')
    out.push('--json')
    return out
  }
  if (command === 'transcript') {
    if (!args.video_id) return null
    // Compact output is the point: one "m:ss text" line per segment instead of a
    // JSON object per segment (measured 118k chars -> 11.8k on an 11-minute talk).
    const out = ['transcript', String(args.video_id || ''), '--compact']
    if (args.start) out.push('--start', String(args.start))
    if (args.end) out.push('--end', String(args.end))
    // The tool default is tighter than the CLI default: a long transcript is the
    // biggest avoidable context cost, and the reply carries next_start_ms so the
    // model can continue instead of asking for the whole file.
    out.push('--max-chars', String(args.max_chars || 6000))
    out.push('--json')
    return out
  }
  if (command === 'frames') {
    if (!args.video_id) return null
    const windowed = args.start !== undefined && args.start !== null && args.start !== ''
      || args.end !== undefined && args.end !== null && args.end !== ''
    // --windows is a range mode: it needs both edges and ignores --at.
    if (args.windows !== undefined && args.windows !== null) {
      if (!args.start || !args.end) return null
      const out = ['frames', String(args.video_id), '--start', String(args.start), '--end', String(args.end),
        '--windows', String(clampInt(args.windows, 6, 2, 9)), '--json']
      if (args.crop) out.push('--crop', String(args.crop))
      if (args.scale !== undefined) out.push('--scale', String(Math.max(1, Math.min(3, Number(args.scale) || 1))))
      return out
    }
    if (!windowed && (args.at === undefined || args.at === null || args.at === '')) return null
    const out = ['frames', String(args.video_id)]
    if (windowed) {
      if (args.start) out.push('--start', String(args.start))
      if (args.end) out.push('--end', String(args.end))
      const cap = Number(args.count) > 1 ? clampInt(args.count, 12, 1, 15) : clampInt(args.max, 12, 1, 15)
      out.push('--fps', String(clampInt(args.fps, 5, 1, 8)), '--max', String(cap),
        '--mode', args.mode === 'change' ? 'change' : 'uniform')
    } else {
      out.push('--at', String(args.at), '--count', String(clampInt(args.count, 1, 1, 8)))
    }
    if (args.sheet) out.push('--sheet')
    if (args.crop) out.push('--crop', String(args.crop))
    if (args.scale !== undefined) out.push('--scale', String(Math.max(1, Math.min(3, Number(args.scale) || 1))))
    out.push('--json')
    return out
  }
  if (command === 'candidates') {
    if (!args.video_id) return null
    const out = ['candidates', String(args.video_id), '--limit', String(clampInt(args.limit, 8, 1, 30)), '--json']
    if (args.query) out.push('--query', String(args.query))
    if (args.include_images) out.splice(2, 0, '--images')
    return out
  }
  if (command === 'map') {
    if (!args.video_id) return null
    const out = ['map', String(args.video_id), '--limit', String(clampInt(args.limit, 50, 1, 500)), '--json']
    if (args.start) out.push('--start', String(args.start))
    if (args.end) out.push('--end', String(args.end))
    return out
  }
  if (command === 'search') {
    const variants = Array.isArray(args.queries) ? args.queries.map(String).map((q) => q.trim()).filter(Boolean) : []
    const query = String(args.query || variants[0] || '')
    if (!query || badPositional(query)) return null
    if (args.video_id && badPositional(args.video_id)) return null
    // An empty --video made the CLI filter on an empty id; only pass it when real.
    const out = ['search', query, '--limit', String(clampInt(args.limit, 8, 1, 20)), '--json']
    if (args.video_id) out.splice(2, 0, '--video', String(args.video_id))
    if (variants.length) out.push('--queries', ...variants.slice(0, 7))
    return out
  }
  if (command === 'digest') {
    if (!args.video_id) return null
    return ['digest', String(args.video_id), '--max-chars', String(clampInt(args.max_chars, 2000, 500, 6000)),
      '--frames', String(clampInt(args.count, 6, 1, 6)), '--compact', '--json']
  }
  if (command === 'ocr-window') {
    if (!args.video_id || !args.start || !args.end) return null
    const out = ['ocr-window', String(args.video_id), '--start', String(args.start), '--end', String(args.end),
      '--fps', String(clampInt(args.fps, 2, 1, 4)), '--max', String(clampInt(args.max, 15, 1, 15))]
    if (args.ocr_tiles) out.push('--tiles')
    out.push('--json')
    return out
  }
  if (command === 'evidence') {
    if (!args.video_id) return null
    // `evidence` accepts either a single moment or a window; asking for neither would
    // silently answer 00:00.
    const out = ['evidence', String(args.video_id)]
    if (args.at !== undefined && args.at !== null && args.at !== '') out.push('--at', String(args.at))
    else if (args.start || args.end) {
      if (args.start) out.push('--start', String(args.start))
      if (args.end) out.push('--end', String(args.end))
    } else return null
    out.push('--images', String(clampInt(args.images, 2, 0, 6)))
    if (args.max_images !== undefined && args.max_images !== null) {
      out.push('--max-images', String(clampInt(args.max_images, 6, 1, 6)))
    }
    if (args.ocr_tiles) out.push('--ocr-tiles')
    out.push('--json')
    return out
  }
  if (command === 'export') {
    if (!args.video_id) return null
    return ['export', String(args.video_id), '--format', String(args.format || 'md'), '--json']
  }
  if (command === 'account') {
    const action = String(args.account_action || '')
    // The tool is read-only. Folder writes used to be available here with a
    // model-supplied confirm:true; a hostile transcript could talk the model into
    // creating folders or adding videos. Writes now stay in the CLI, where the
    // user runs them with --confirm. delete/remove were already CLI-only.
    const actions = new Set([
      'status', 'folders', 'favorites', 'history', 'analyze', 'classify-plan',
    ])
    if (!actions.has(action)) return null
    const out = ['account', action]
    if (args.folder_id !== undefined && args.folder_id !== null && args.folder_id !== '') {
      out.push('--folder', String(args.folder_id))
    }
    const videos = Array.isArray(args.videos) ? args.videos.map(String) : []
    // Never let a video id become an option. argparse's `--videos nargs='+'`
    // would otherwise turn ["BV1", "--confirm"] into a confirmed write even when
    // the caller set confirm:false.
    if (videos.length > 100 || videos.some((v) => !v.trim() || badPositional(v))) return null
    if (videos.reduce((n, v) => n + v.length + 1, 0) > 12000) return null
    if (videos.length) out.push('--videos', ...videos)
    if (args.title) {
      if (badPositional(args.title)) return null
      out.push('--title', String(args.title))
    }
    if (args.expected_title) {
      if (badPositional(args.expected_title)) return null
      out.push('--expected-title', String(args.expected_title))
    }
    if (args.intro) {
      if (badPositional(args.intro)) return null
      out.push('--intro', String(args.intro))
    }
    if (args.public === true) out.push('--public')
    if (args.days !== undefined) out.push('--days', String(args.days))
    if (args.limit !== undefined) out.push('--limit', String(clampInt(args.limit, 50, 1, 50)))
    const librarySource = args.account_source || args.source
    if (librarySource) {
      const source = String(librarySource)
      if (source !== 'favorites' && source !== 'history') return null
      out.push('--source', source)
    }
    if (args.plan !== undefined) {
      const encoded = JSON.stringify(args.plan)
      if (encoded.length > 30000) return null
      out.push('--plan-json', encoded)
    }
    if (args.confirm === true) out.push('--confirm')
    const cookies = persistedCookiesPath()
    if (cookies) out.push('--cookies', cookies)
    out.push('--json')
    return out
  }
  return null
}

// Register a web route when the host provides a web server, without making it a
// load-time dependency. In the web profile the service usually exists already
// (register immediately); in a headless/TUI profile it never appears, and the
// tool + /video command keep working.
// Reads do not carry an Origin, so a DNS-rebinding page could otherwise read
// settings/discovery/job metadata from loopback. Require a loopback Host or the
// exact advertised origin, for every GET the plugin serves.
// Doctor/model payloads are useful but they are not a place to publish the
// user's profile path or the plugin home. Redact known local roots; keep the
// basename so the check is still actionable.
function redactLocalPaths(value, depth = 0) {
  if (depth > 12) return value
  if (typeof value === 'string') {
    let text = value
    // Plain string replacement, not a generated RegExp: the roots contain
    // backslashes and Windows profile names that made the pattern fragile.
    const home = os.homedir()
    for (const root of [home, process.env.VIDEO2AGENT_HOME || path.join(home, '.video2agent')]) {
      if (root) text = text.split(String(root)).join('<local>')
    }
    return text
  }
  if (Array.isArray(value)) return value.map((item) => redactLocalPaths(item, depth + 1))
  if (value && typeof value === 'object') {
    const out = {}
    for (const [key, item] of Object.entries(value)) out[key] = redactLocalPaths(item, depth + 1)
    return out
  }
  return value
}

// Module-level: guardRead runs before apply()'s closure exists, so it cannot
// reach a sendJson defined inside apply.
function sendJson(res, code, obj) {
  res.statusCode = code
  res.setHeader('Content-Type', 'application/json; charset=utf-8')
  res.setHeader('Cache-Control', 'no-store')
  res.end(JSON.stringify(obj))
}

// DSH's own Host/Origin fence + authenticated Peer check. webServer.register
// routes do not get it automatically, so a page open in the user's browser could
// otherwise reach them (the plugin's own guardRead/guardWrite still apply too).
let ACTIVE_CONNECTION = null
function admitConnection(ctx, req, res) {
  try {
    let connection = ACTIVE_CONNECTION
    if (!connection) {
      try { connection = ctx?.get?.('connection') || ctx?.connection } catch { connection = null }
    }
    if (!connection || typeof connection.requestRejection !== 'function') return true
    const rejection = connection.requestRejection(req)
    if (rejection === undefined || rejection === null) return true
    sendJson(res, Number(rejection) || 403, { error: 'rejected', code: 'E_UNAUTHORIZED' })
    return false
  } catch {
    return true
  }
}

// The one cross-site read the desktop shell needs: evidence images with an opaque
// id and an image destination (the model's markdown uses absolute URLs).
function isFrameImageRead(req) {
  const pathOnly = String(req.url || '').split('?')[0]
  const query = String(req.url || '').split('?')[1] || ''
  return req.method === 'GET'
    && pathOnly === '/api/video2agent/frame'
    && /(^|&)id=/.test(query)
    && String((req.headers && req.headers['sec-fetch-dest']) || '').toLowerCase() === 'image'
}

function guardRead(req, res) {
  // GETs here can spawn the CLI, hit the network, or write campaign/queue files.
  // A browser marks a page-initiated cross-site request explicitly; refuse it
  // even though the Host header is loopback (img/fetch CSRF surface).
  const site = String((req.headers && req.headers['sec-fetch-site']) || '').toLowerCase()
  // Reads spawn the CLI / hit the network, and several read routes accept POST as
  // well (resolve/job/frame). A POST must still reach guardWrite for the desktop
  // shell's Origin:null writes, so only the *write* routes are exempt from the
  // cross-site refusal.
  const pathOnly = String(req.url || '').split('?')[0]
  const isWriteRoute = req.method === 'POST'
    && /^\/api\/video2agent\/(settings|cloud|models|bili-login\/|douyin-login\/|jobs\/cancel|retry|discovery\/clear|campaign|setup)/.test(pathOnly)
  // A frame <img> is a cross-site no-cors image read when the page is the
  // desktop shell (dsh-app://app): the model's markdown needs an absolute URL,
  // and an absolute URL is cross-site from there. Serve only image destinations
  // on the strict opaque-id frame route; every other read stays same-origin.
  // Only the opaque `id=` form: the legacy `?path=` form would turn the frame
  // route into a cross-site existence oracle for known local paths.
  const frameQuery = String(req.url || '').split('?')[1] || ''
  const imageRead = req.method === 'GET' && pathOnly === '/api/video2agent/frame'
    && /(^|&)id=/.test(frameQuery)
    && String((req.headers && req.headers['sec-fetch-dest']) || '').toLowerCase() === 'image'
  if (site === 'cross-site' && !isWriteRoute && !imageRead) {
    sendJson(res, 403, { error: 'cross-site read rejected' })
    return false
  }
  const host = String((req.headers && req.headers.host) || '').toLowerCase()
  let expected = ''
  try {
    const origin = ACTIVE_WEB_SERVER && typeof ACTIVE_WEB_SERVER.getOrigin === 'function'
      ? String(ACTIVE_WEB_SERVER.getOrigin())
      : ''
    if (origin) expected = new URL(origin).host.toLowerCase()
  } catch { expected = '' }
  const loopback = /^(127\.0\.0\.1|localhost|\[::1\])(:\d+)?$/.test(host)
  if (!host || (!loopback && host !== expected)) {
    res.statusCode = 403
    res.setHeader('Content-Type', 'application/json; charset=utf-8')
    res.end(JSON.stringify({ error: 'forbidden host' }))
    return false
  }
  return true
}

function captureConnection(ctx) {
  try {
    ctx.inject(['connection'], (inner) => {
      try { ACTIVE_CONNECTION = inner.get?.('connection') || inner.connection || null } catch { ACTIVE_CONNECTION = null }
    })
  } catch {
    ACTIVE_CONNECTION = null
  }
}

function whenWebServer(ctx, label, register) {
  const run = (webServer) => {
    try {
      if (!webServer || typeof webServer.register !== 'function') return
      ACTIVE_WEB_SERVER = webServer
      // Every route gets the Host check; writes still use guardWrite.
      const guarded = Object.create(webServer)
      guarded.register = (route) => {
        const handler = route && route.handler
        if (typeof handler !== 'function') return webServer.register(route)
        return webServer.register({
          ...route,
          handler: (req, res) => {
            // Limiting this to GET let a cross-site POST reach /resolve, /job or
            // /frame and spawn the CLI.
            if (!guardRead(req, res)) return
            // DSH's Connection fence first; the evidence-image read is the one
            // cross-site GET the desktop shell needs, so it stays on guardRead.
            if (!isFrameImageRead(req) && !admitConnection(ctx, req, res)) return
            return handler(req, res)
          },
        })
      }
      register(guarded)
    } catch (e) {
      ctx.logger?.info?.('[dsh-video2agent] ' + label + ' skipped: ' + (e?.message || e))
    }
  }
  let current = null
  try { current = ctx.get?.('webServer') || ctx.webServer } catch { current = null }
  if (current?.register) return run(current)
  try {
    ctx.inject(['webServer'], (inner) => {
      let svc = null
      try { svc = inner.get?.('webServer') || inner.webServer } catch { svc = null }
      run(svc)
    })
  } catch (e) {
    ctx.logger?.info?.('[dsh-video2agent] ' + label + ' not registered: ' + (e?.message || e))
  }
  return undefined
}

// The jobs command answers a failed row with `{ok:false, job, error}` and exits
// non-zero. The route needs the row, not the envelope, or the first poll after a
// crash looks like a missing job (404) and the card never shows the failure.
function jobFromCliPayload(parsed) {
  if (!parsed || typeof parsed !== 'object') return null
  const wrapped = parsed.job && typeof parsed.job === 'object' ? parsed.job : parsed
  if (!wrapped || !wrapped.id) return null
  if (wrapped !== parsed && parsed.error && typeof parsed.error === 'object') {
    wrapped.error_code = wrapped.error_code || parsed.error.code
    wrapped.error_message = wrapped.error_message || parsed.error.message
    wrapped.remedy = wrapped.remedy || parsed.error.remedy
  }
  return wrapped
}

// Cache policy is applied in the background: expiry/capacity is not allowed to
// block a settings save or a model call. Timers are unref'd so a test host exits.
// The Host hands the CLI the plugin-row Config layer (four cache keys only). The
// CLI reads ui-settings.json itself and lets it win, so a settings save that
// lands mid-tick cannot be half-applied from here, and a corrupt file still
// fails closed. Without this layer an unset file key fell back to the built-in
// 7-day default while the settings page showed the row Config's 关闭.
let CACHE_CLEANUP_TIMER = null
function cacheCleanupArgs() {
  const row = sanitizeUiSettings(ROW_CONFIG || {})
  return [
    'gc', '--auto', '--json',
    '--cache-defaults', JSON.stringify({
      cacheExpire: row.cacheExpire,
      cacheDays: row.cacheDays,
      cacheLimitEnabled: row.cacheLimitEnabled,
      cacheLimitGb: row.cacheLimitGb,
    }),
  ]
}

function runCacheCleanupSoon(delayMs = 30000) {
  if (CACHE_CLEANUP_TIMER) return
  const tick = () => {
    // Same startup barrier as a tool call: never sweep with a CLI that is being
    // replaced, and never run while an engine update is in flight. A skipped
    // tick is picked up by the interval; it is safe to miss one.
    waitForEngineReady().then(() => {
      if (ENGINE_UPDATE.state === 'updating') return
      runCli(cacheCleanupArgs(), 120000).catch(() => {})
    }).catch(() => {})
  }
  // The old code ran once and never again, so cacheExpire/cacheLimit silently
  // stopped applying in a long-lived desktop process. Re-check periodically.
  const first = setTimeout(() => {
    tick()
    CACHE_CLEANUP_TIMER = setInterval(tick, 15 * 60 * 1000)
    CACHE_CLEANUP_TIMER.unref?.()
  }, delayMs)
  first.unref?.()
  CACHE_CLEANUP_TIMER = first
}

export function apply(ctx, config) {
  // `config` is the validated plugin-row Config; it is the default layer under
  // the settings file, so a value chosen in the settings form is never reset by
  // a Config edit, while a fresh install still gets sane defaults.
  ROW_CONFIG = sanitizeUiSettings(config || {})
  // Routes served through webServer.register must apply DSH's own admission
  // fence themselves (captured here while services are being composed).
  captureConnection(ctx)
  try { runCacheCleanupSoon() } catch {}
  try {
    ctx.commands.register({
      definitionId: 'dsh-video2agent',
      name: 'video',
      description: 'Video2Agent: find a Bilibili video, index it, search moments, show evidence.',
      input: {
        hint: '<doctor|discover|resolve|ingest|jobs|overview|search|evidence|export> [args]',
      },
      handler: async (invocation) => {
        await waitForEngineReady()
        const args = tokenize(invocation?.rawInput || '')
        const r = await runCli(['help'].includes(args[0]) ? ['--help'] : args)
        return { kind: r.code === 0 ? 'success' : 'error', text: (r.out || r.err || 'no output').slice(0, 24000) }
      },
    })
  } catch (e) {
    ctx.logger?.info?.('[dsh-video2agent] command registration skipped: ' + (e?.message || e))
  }

  // Same-origin metadata endpoint for the composer preview. The browser
  // cannot call Bilibili directly (no CORS), so the host resolves it.
  const RESOLVE_RESULT_CACHE = new Map()
  whenWebServer(ctx, 'resolve route', (webServer) => {
    webServer.register({
        kind: 'exact',
        path: '/api/video2agent/resolve',
        handler: async (req, res) => {
          try {
            const url = new URL(req.url || '', 'http://localhost').searchParams.get('url') || ''
            if (!/^https?:\/\//i.test(url)) {
              res.statusCode = 400
              res.setHeader('Content-Type', 'application/json; charset=utf-8')
              res.end(JSON.stringify({ error: 'invalid url' }))
              return
            }
            const now = Date.now()
            // The composer persists cacheTtlMs and judges both its localStorage
            // entries and its in-memory copy against getSettings().cacheTtlMs on
            // every mount. The Host cache must use the same read-time value, not
            // a hard-coded day, or a preview keeps resolving server-side long
            // after the page would have refreshed it (or vice versa).
            const ttlMs = readMergedSettings().cacheTtlMs
            const cached = RESOLVE_RESULT_CACHE.get(url)
            if (cached && now - cached.at < ttlMs) {
              res.statusCode = 200
              res.setHeader('Content-Type', 'application/json; charset=utf-8')
              res.setHeader('Cache-Control', 'no-store')
              res.end(JSON.stringify(cached.data))
              return
            }
            const out = await runCli(['resolve', url, '--json'], 30000)
            const structured = out.code === 0 ? null : parseStructuredError(out.out)
            // An unsupported URL is bad input, not a backend outage. 502 made the
            // preview look like the service was down and counted as a server error.
            const badInput = structured && ['E_URL', 'E_METADATA', 'E_UNSUPPORTED', 'E_SOURCE'].includes(structured.code)
            res.statusCode = out.code === 0 ? 200 : (badInput ? 400 : 502)
            res.setHeader('Content-Type', 'application/json; charset=utf-8')
            res.setHeader('Cache-Control', 'no-store')
            if (out.code === 0) {
              try {
                RESOLVE_RESULT_CACHE.set(url, { at: now, data: JSON.parse(out.out) })
                if (RESOLVE_RESULT_CACHE.size > 32) RESOLVE_RESULT_CACHE.delete(RESOLVE_RESULT_CACHE.keys().next().value)
              } catch {}
            }
            res.end(out.code === 0
              ? out.out
              : JSON.stringify(structured ? { ok: false, error: structured } : { error: out.err || 'resolve failed' }))
          } catch (e) {
            res.statusCode = 500
            res.setHeader('Content-Type', 'application/json; charset=utf-8')
            res.end(JSON.stringify({ error: 'internal error', code: 'E_ROUTE' }))
          }
        },
    })
  })

  // ---- Environment check + one-click install --------------------------------
  // The plugin is a thin DSH layer; the video work runs in a Python CLI that
  // needs Python 3.11+ and FFmpeg. The settings page checks those and can install
  // what is missing. Only the page can start an install (loopback JSON POST,
  // guardWrite); the model-facing tool has no command that reaches it.
  const SETUP_INSTALL_TIMEOUT = 15 * 60 * 1000
  // One global install/update lock, not one per button. Auto-update, a manual
  // engine update, and install-all all mutate the same interpreter/site-packages,
  // so two of them must never run at once. A second caller gets E_BUSY.
  let SETUP_INFLIGHT = null

  function setupBusy() {
    return Boolean(SETUP_INFLIGHT)
  }

  async function withInstallLock(action, runner) {
    if (SETUP_INFLIGHT) {
      return {
        ok: false,
        error: { code: 'E_BUSY', message: '安装或更新已在进行中，请等它结束再试。' },
        // Reuse the last probe rather than starting another full one while the
        // owner of the lock is running pip. The state fields are refreshed from
        // memory, so the UI still sees updating/ready/failed immediately.
        status: await setupStatus({ cache: true }),
      }
    }
    const task = (async () => runner())()
    SETUP_INFLIGHT = { action, task }
    try {
      return await task
    } finally {
      if (SETUP_INFLIGHT && SETUP_INFLIGHT.task === task) SETUP_INFLIGHT = null
    }
  }

  function pythonCandidates() {
    // An explicit VIDEO2AGENT_PYTHON is a pin: never fall through to a different
    // interpreter, so "which python does the card use" is deterministic.
    if (process.env.VIDEO2AGENT_PYTHON) return [String(process.env.VIDEO2AGENT_PYTHON)]
    return process.platform === 'win32' ? ['py', 'python'] : ['python3', 'python']
  }

  async function detectPython() {
    for (const command of pythonCandidates()) {
      const prefix = command === 'py' ? ['-3'] : []
      const r = await runCommand(command, [...prefix, '-c', 'import sys; print(sys.version.split()[0])'], 30000)
      if (r.code !== 0) continue
      const version = String(r.out || '').trim().split('\n').pop() || ''
      const [major, minor] = version.split('.').map((x) => Number(x) || 0)
      const ok = major > 3 || (major === 3 && minor >= 11)
      return { ok, version, command, prefix, tooOld: major === 3 && minor < 11 }
    }
    return { ok: false, version: '', command: '', prefix: [], tooOld: false }
  }

  function findWingetFfmpeg() {
    if (process.platform !== 'win32') return null
    const root = path.join(process.env.LOCALAPPDATA || os.homedir(), 'Microsoft', 'WinGet', 'Packages')
    let packages = []
    try {
      packages = fs.readdirSync(root)
        .filter((name) => /ffmpeg/i.test(name))
        .sort()
        .reverse()
    } catch { return null }
    const walk = (dir, depth, out) => {
      if (depth > 7 || out.length) return
      let entries = []
      try { entries = fs.readdirSync(dir, { withFileTypes: true }) } catch { return }
      for (const entry of entries) {
        if (out.length) return
        const full = path.join(dir, entry.name)
        if (entry.isFile() && entry.name.toLowerCase() === 'ffmpeg.exe') out.push(full)
        else if (entry.isDirectory() && !/cache|temp/i.test(entry.name)) walk(full, depth + 1, out)
      }
    }
    for (const name of packages) {
      const found = []
      walk(path.join(root, name), 0, found)
      if (found.length) {
        const ffmpeg = found[0]
        const probe = path.join(path.dirname(ffmpeg), 'ffprobe.exe')
        return { ffmpeg, ffprobe: fs.existsSync(probe) ? probe : '' }
      }
    }
    return null
  }

  async function detectFfmpeg() {
    const managed = readManagedTools()
    const envFfmpeg = String(process.env.FFMPEG_BIN || '').trim()
    const envProbe = String(process.env.FFPROBE_BIN || '').trim()
    const managedFfmpeg = managed.ffmpeg && fs.existsSync(managed.ffmpeg) ? managed.ffmpeg : ''
    const managedProbe = managed.ffprobe && fs.existsSync(managed.ffprobe) ? managed.ffprobe : ''
    // FFMPEG_BIN/FFPROBE_BIN are the documented manual override; the card must use
    // the same precedence as the CLI instead of contradicting `doctor`.
    if (envFfmpeg && !fs.existsSync(envFfmpeg)) {
      return { ok: false, detail: 'FFMPEG_BIN 指向不存在的文件', managed: false }
    }
    if (envProbe && !fs.existsSync(envProbe)) {
      return { ok: false, detail: 'FFPROBE_BIN 指向不存在的文件', managed: false }
    }
    let ffmpegPath = envFfmpeg || managedFfmpeg || 'ffmpeg'
    let ffprobePath = envProbe || managedProbe || 'ffprobe'
    let source = envFfmpeg || envProbe ? 'env' : (managedFfmpeg ? 'managed' : 'path')
    let ffmpeg = await runCommand(ffmpegPath, ['-version'], 20000)
    if (ffmpeg.code !== 0) {
      // winget updates can leave a stale PATH entry (e.g. ffmpeg-8.1.1/bin)
      // while the actual package is under WinGet/Packages/Gyan.FFmpeg-*.
      const found = findWingetFfmpeg()
      if (found) {
        ffmpegPath = found.ffmpeg
        ffprobePath = found.ffprobe || path.join(path.dirname(found.ffmpeg), 'ffprobe.exe')
        source = 'winget'
        saveManagedFfmpeg(ffmpegPath, ffprobePath, source)
        ffmpeg = await runCommand(ffmpegPath, ['-version'], 20000)
      }
    }
    if (ffmpeg.code !== 0) return { ok: false, detail: '未安装', managed: false }
    let ffprobe = await runCommand(ffprobePath, ['-version'], 20000)
    if (ffprobe.code !== 0 && source !== 'env' && !managedProbe) {
      const found = findWingetFfmpeg()
      if (found && found.ffprobe) {
        ffprobePath = found.ffprobe
        saveManagedFfmpeg(ffmpegPath, ffprobePath, 'winget')
        ffprobe = await runCommand(ffprobePath, ['-version'], 20000)
      }
    }
    const first = String(ffmpeg.out || '').split('\n')[0] || ''
    const ffprobeOk = ffprobe.code === 0
    return {
      ok: ffprobeOk,
      // Say which one is missing: "ffmpeg found, ffprobe missing" is a different
      // fix (same package) from "nothing installed".
      detail: ffprobeOk
        ? (source === 'managed' || source === 'winget' ? '插件发现 · ' : (source === 'env' ? '环境变量 · ' : '')) + first.slice(0, 120)
        : 'ffmpeg 已找到，但 ffprobe 缺失',
      managed: source === 'managed' || source === 'winget',
      path: ffmpegPath,
    }
  }

  function versionLine(result) {
    return String((result && (result.out || result.err)) || '').trim().split('\n').pop()
  }

  // A pip install can put the console script in a Scripts dir the app's PATH does
  // not contain. Fall back to "python -m video2agent" and remember the interpreter
  // so the CLI is usable (and the card stops saying 缺失 after a successful install).
  async function detectCli() {
    const direct = await runCli(['--version'], 30000)
    if (direct.code === 0) return { ok: true, detail: versionLine(direct), via: 'path' }
    const python = await detectPython()
    if (python.ok) {
      const moduleRun = await runCommand(python.command, [...python.prefix, '-m', 'video2agent', '--version'], 30000)
      if (moduleRun.code === 0) {
        // A detection is not an install: remember how to reach the CLI, but do
        // not turn it into an auto-update authorization. Resolve a bare launcher
        // to the actual interpreter so the record also works for tool calls.
        await recordVerifiedCli(python.command, python.prefix)
        return { ok: true, detail: versionLine(moduleRun), via: 'python' }
      }
    }
    return { ok: false, detail: '未安装', via: '' }
  }

  async function detectOcr(python, cli) {
    // OCR runs inside the interpreter that runs the CLI. Probing `py -3` directly
    // said "未安装" on a machine where the CLI (a different Python) had rapidocr
    // installed, so ask the CLI first and only fall back to a Python import probe.
    const supported = !!(python.ok || (cli && cli.ok))
    if (cli && cli.ok) {
      const r = await runCli(['models', 'status', '--json'], 30000)
      try {
        const data = JSON.parse(String(r.out || '').trim() || '{}')
        const ocr = data && data.ocr
        if (r.code === 0 && ocr && typeof ocr.available === 'boolean') {
          const engine = String(ocr.engine_package || (ocr.available ? 'rapidocr' : ''))
          return {
            ok: !!ocr.available,
            supported: true,
            detail: ocr.available ? ('已安装' + (engine ? '（' + engine + '）' : '')) : '未安装',
            engine,
            version: String(ocr.version || ''),
          }
        }
      } catch {}
    }
    const detail = !python.ok ? '需要 CLI 或 Python' : '可选'
    if (!python.ok) return { ok: false, supported, detail, engine: '', version: '' }
    const probe = await runCommand(python.command, [
      ...python.prefix, '-c',
      "import importlib.util as u; print('rapidocr' if u.find_spec('rapidocr') else ('legacy' if u.find_spec('rapidocr_onnxruntime') else ''))",
    ], 30000)
    const engine = String(probe.out || '').trim().split('\n').pop() || ''
    return {
      ok: engine !== '',
      supported,
      detail: engine === 'rapidocr' ? '已安装（rapidocr 3.x）' : engine === 'legacy' ? '已安装（rapidocr-onnxruntime）' : '未安装',
      engine: engine === 'legacy' ? 'rapidocr-onnxruntime' : engine,
    }
  }

  async function detectPlaywrightBrowser(interpreter, { strict = false } = {}) {
    // A Python package alone is not usable. Prefer the user's Chrome/Edge, then
    // ask Playwright itself for the Chromium executable it expects. The directory
    // scan is a fallback for an old CLI that cannot answer the probe; it never
    // treats headless_shell as a visible-window runtime. Strict mode is for
    // migration: an arbitrary cached chromium-* directory can belong to a
    // different Playwright version, so only the executable this exact install
    // reports may count as compatible.
    const roots = [
      process.env.PLAYWRIGHT_BROWSERS_PATH,
      path.join(process.env.LOCALAPPDATA || '', 'ms-playwright'),
      path.join(os.homedir(), '.cache', 'ms-playwright'),
      path.join(os.homedir(), 'Library', 'Caches', 'ms-playwright'),
    ].filter((root) => root && fs.existsSync(root))
    if (interpreter) {
      const code = 'from playwright.sync_api import sync_playwright\np = sync_playwright().start()\ntry:\n    print(p.chromium.executable_path)\nfinally:\n    p.stop()'
      const probe = await runCommand(interpreter, ['-c', code], 20000)
      const executable = String(probe.out || '').trim().split('\n').pop() || ''
      if (probe.code === 0 && executable && fs.existsSync(executable)) return true
    }
    // Do not accept a directory scan for migration: it would let a downloaded
    // Chromium from an older Playwright look usable and lose the browser after
    // the switch.
    if (strict) return false
    const names = process.platform === 'win32'
      ? ['chrome-win/chrome.exe']
      : process.platform === 'darwin'
        ? ['chrome-mac/Chromium.app/Contents/MacOS/Chromium']
        : ['chrome-linux/chrome', 'chrome-linux64/chrome']
    for (const root of roots) {
      let entries = []
      try { entries = fs.readdirSync(root, { withFileTypes: true }) } catch { continue }
      for (const entry of entries) {
        if (!entry.isDirectory() || !/^chromium/i.test(entry.name)) continue
        for (const suffix of names) {
          try { if (fs.existsSync(path.join(root, entry.name, suffix))) return true } catch {}
        }
      }
    }
    return false
  }

  async function detectBrowser(python, cli) {
    // Ask the CLI itself first. The CLI may be a console script from another
    // interpreter (here: anaconda 3.12) while `py -3` on PATH is a Windows Store
    // Python 3.11 without Playwright. Probing "python" then reported a false
    // "未安装" even though the CLI's environment had the package.
    if (cli && cli.ok) {
      const doctor = await runCli(['doctor', '--json'], 30000)
      try {
        const data = JSON.parse(String(doctor.out || '').trim() || '{}')
        const check = (data.checks || []).find((item) => item && item.name === 'browser')
        if (check && typeof check.ok === 'boolean') {
          let runtime = check.ok
          const interpreter = data.python && data.python.executable ? String(data.python.executable) : (python && python.command ? String(python.command) : '')
          if (runtime) runtime = (await detectSystemBrowser()) || (await detectPlaywrightBrowser(interpreter))
          return {
            ok: check.ok && runtime,
            supported: true,
            detail: check.ok
              ? (runtime ? String(check.detail || '已安装') : 'Playwright 已装，但没有可启动的浏览器')
              : String(check.detail || '未安装'),
            version: (String(check.detail || '').match(/(\d+\.\d+\.\d+)/) || [])[1] || '',
            interpreter: data.python && data.python.executable ? String(data.python.executable) : '',
            python_version: data.python && data.python.version ? String(data.python.version) : '',
          }
        }
      } catch {}
    }
    // No usable CLI doctor (or an older CLI): probe the actual interpreter.
    const interpreter = cliInterpreter() || (python.ok ? python : null)
    if (!interpreter) {
      return { ok: false, supported: !!(python.ok || cli.ok), detail: '需要 CLI 或 Python', interpreter: '', version: '' }
    }
    const probe = await runCommand(interpreter.command, [
      ...(interpreter.prefix || []), '-c',
      "import importlib.util as u; print('yes' if u.find_spec('playwright') else 'no')",
    ], 30000)
    const ok = probe.code === 0 && String(probe.out || '').trim().split('\n').pop() === 'yes'
    return {
      ok,
      supported: true,
      detail: ok ? '已安装' : '未安装',
      version: '',
      interpreter: interpreter.command,
      python_version: python.version || '',
    }
  }

  async function setupStatus({ cache = false } = {}) {
    const installedPluginVersion = onDiskPluginVersion()
    const pluginStatus = {
      loaded: PLUGIN_VERSION,
      installed: installedPluginVersion,
      restart_required: Boolean(installedPluginVersion && PLUGIN_VERSION && installedPluginVersion !== PLUGIN_VERSION),
    }
    // GET is allowed to reuse a very short probe. During an update, reuse it
    // until the state changes (ready/failed) so polling does not spawn a new
    // Python/CLI/FFmpeg/browser probe every five seconds.
    if (cache && SETUP_STATUS_CACHE) {
      const age = Date.now() - SETUP_STATUS_CACHE.at
      if (age < SETUP_STATUS_CACHE_TTL_MS || ENGINE_UPDATE.state === 'updating') {
        return {
          ...SETUP_STATUS_CACHE.data,
          plugin: pluginStatus,
          engine_update: engineUpdatePublic(),
        }
      }
    }
    // If the snapshot could not be taken before pip (a probe threw), do not run
    // a CLI/doctor probe now: the package files are being replaced. Report the
    // safe transient shape and let the state change invalidate it.
    if (cache && ENGINE_UPDATE.state === 'updating' && !SETUP_STATUS_CACHE) {
      const record = managedCliTarget({ requireAuthorization: false })
      const version = record.ok ? String(record.record.version || '') : ''
      const transient = {
        ok: true,
        platform: process.platform,
        home: v2aHomePath(),
        plugin: pluginStatus,
        engine_update: engineUpdatePublic(),
        python: { ok: true, detail: '更新中…', tooOld: false },
        cli: {
          ok: true,
          detail: '更新中…',
          bin: binPath(),
          via: 'managed',
          version,
          latest: PLUGIN_VERSION,
          update_available: false,
        },
        ffmpeg: { ok: true, detail: '更新中…', managed: true, path: '' },
        hints: {
          python: '安装 Python 3.11+：https://www.python.org/downloads/',
          cli: 'pip install video2agent',
          ffmpeg: 'winget install Gyan.FFmpeg',
          browser: 'pip install "video2agent[browser]"',
        },
        ocr: { ok: false, supported: false, detail: '更新中…', engine: '', version: '' },
        browser: { ok: false, supported: false, detail: '更新中…', version: '', interpreter: '' },
        canInstall: { cli: false, updateCli: false, ffmpeg: false, ocr: false, browser: false },
      }
      SETUP_STATUS_CACHE = { at: Date.now(), data: transient }
      return transient
    }
    const python = await detectPython()
    const cli = await detectCli()
    const cliOk = cli.ok
    const cliVersion = (String(cli.detail || '').match(/(\d+\.\d+\.\d+)/) || [])[1] || ''
    const cliOutdated = Boolean(cliOk && PLUGIN_VERSION && cliVersion && compareVersions(cliVersion, PLUGIN_VERSION) < 0)
    const ffmpeg = await detectFfmpeg()
    const ocr = await detectOcr(python, cli)
    const browser = await detectBrowser(python, cli)
    // The CLI may run under a different interpreter than the first `python` on
    // PATH. Show the engine's real interpreter so the card is not self-contradictory.
    const runtimePython = browser.interpreter
      ? { ok: true, command: browser.interpreter, prefix: [], version: browser.python_version || python.version, tooOld: false }
      : python
    const ffmpegHint = process.platform === 'win32'
      ? 'winget install Gyan.FFmpeg'
      : process.platform === 'darwin' ? 'brew install ffmpeg' : 'sudo apt install ffmpeg'
    // GET is a probe. It never starts, retries, or waits for an engine update;
    // it only reports the loaded version, the on-disk version and the state the
    // background updater last published.
    const result = {
      ok: true,
      platform: process.platform,
      home: v2aHomePath(),
      plugin: pluginStatus,
      engine_update: engineUpdatePublic(),
      python: { ok: runtimePython.ok, detail: runtimePython.version ? 'Python ' + runtimePython.version : '未找到', tooOld: !!runtimePython.tooOld },
      cli: {
        ok: cliOk,
        detail: cliOk ? (cli.detail || '已安装') : '未安装',
        bin: binPath(),
        via: cli.via,
        version: cliVersion,
        latest: PLUGIN_VERSION,
        update_available: cliOutdated,
      },
      ffmpeg: { ok: ffmpeg.ok, detail: ffmpeg.detail, managed: ffmpeg.managed, path: ffmpeg.path || '' },
      hints: {
        python: '安装 Python 3.11+：https://www.python.org/downloads/（Windows 可 winget install Python.Python.3.12）',
        cli: 'pip install video2agent',
        ffmpeg: ffmpegHint,
        browser: 'pip install "video2agent[browser]"（Playwright，用于抖音登录/账号读取）',
      },
      ocr: { ok: ocr.ok, supported: ocr.supported, detail: ocr.detail, engine: ocr.engine, version: ocr.version || '' },
      browser: { ok: browser.ok, supported: browser.supported, detail: browser.detail, version: browser.version || '', interpreter: browser.interpreter || "" },
      // Linux installs FFmpeg with sudo, which the plugin cannot run; offer the
      // command instead of a button that always fails.
      canInstall: {
        cli: runtimePython.ok && !cliOk,
        updateCli: runtimePython.ok && cliOutdated,
        ffmpeg: process.platform !== 'linux' && !ffmpeg.ok,
        ocr: (python.ok || cliOk) && ocr.supported && !ocr.ok,
        browser: (runtimePython.ok || !!cliInterpreter()) && browser.supported && !browser.ok,
      },
    }
    SETUP_STATUS_CACHE = { at: Date.now(), data: result }
    return result
  }

  // ---- Managed engine update ------------------------------------------------
  // Only an interpreter this plugin installed into can be upgraded automatically.
  // A probe of some other Python is not authorization, and an explicit path/Python
  // pin, an editable checkout, or a direct-URL install is never touched.
  async function engineManualTarget({ preferred = '', allowDetect = false } = {}) {
    if (process.env.VIDEO2AGENT_BIN) return { ok: false, reason: 'explicit-bin' }
    // A legacy record (no provenance) is still the CLI this Host runs; a manual
    // click may update it once and that successful install records provenance.
    const managed = managedCliTarget({ requireAuthorization: false })
    if (managed.ok) return managed
    // Older records may store the launcher ("py", "python3") instead of the
    // interpreter. Resolve exactly that recorded command with its prefix, but
    // do not write the result back: the bare record stays unauthorized for
    // automatic updates until the explicit clean install below records it.
    if (managed.reason === 'interpreter-missing' && !process.env.VIDEO2AGENT_PYTHON) {
      const record = readManagedTools().cli
      if (record && isBareCommandName(record.python)) {
        const launcher = {
          command: String(record.python),
          prefix: Array.isArray(record.prefix) ? record.prefix.map(String) : [],
        }
        const absolute = await probeEngineInterpreter(launcher)
        if (absolute) return { ok: true, command: absolute, prefix: [], record }
      }
    }
    // setup/doctor reports the interpreter that actually ran the CLI (pipx and
    // other wrappers included). Prefer it over an unrelated Python on PATH.
    if (preferred && usableInterpreterPath(preferred)) return { ok: true, command: preferred, prefix: [] }
    if (process.env.VIDEO2AGENT_PYTHON) {
      const command = String(process.env.VIDEO2AGENT_PYTHON)
      if (usableInterpreterPath(command)) return { ok: true, command, prefix: command === 'py' ? ['-3'] : [] }
      return { ok: false, reason: 'python-pin-missing' }
    }
    if (allowDetect) {
      const python = await detectPython()
      if (python.ok) return { ok: true, command: python.command, prefix: python.prefix }
      return { ok: false, reason: 'no-python' }
    }
    // The CLI is running but no managed record or doctor interpreter exists.
    // Installing into a different Python would update a package this Host never
    // calls, so refuse instead of guessing.
    return { ok: false, reason: 'interpreter-unknown' }
  }

  async function saveInstalledEngine(target, version, dist, { authorize = true } = {}) {
    // Prefer the exact interpreter pip was told to use (a pipx/venv wrapper path)
    // over sys.executable, which can point at the base interpreter behind it.
    const absolute = path.isAbsolute(String(target.command || '')) && usableInterpreterPath(target.command)
      ? String(target.command)
      : await probeEngineInterpreter(target)
    if (!absolute) return false
    const clean = Boolean(dist && dist.ok && !dist.editable && !dist.direct_url)
    return saveManagedCli(absolute, [], {
      source: 'plugin-install',
      // Authorization is granted only after the whole install path succeeded and
      // the actual probed version meets this plugin's version.
      auto_update: authorize && clean && Boolean(version) && compareVersions(version, PLUGIN_VERSION) >= 0,
      version,
      plugin_version: PLUGIN_VERSION,
      installed_at: new Date().toISOString(),
    })
  }

  async function failEngineUpdate(message, { output = '', persist = true } = {}) {
    setEngineUpdate('failed', PLUGIN_VERSION, message)
    // Persist only the fact that this plugin version already tried and failed.
    // GET/refresh must not retry; a manual update clears this marker.
    if (persist && PLUGIN_VERSION) {
      writeEngineUpdateMarker({
        plugin_version: PLUGIN_VERSION,
        target: PLUGIN_VERSION,
        state: 'failed',
        message,
        at: new Date().toISOString(),
      })
    }
    return {
      ok: false,
      error: { code: 'E_ENGINE_UPDATE', message },
      output,
      status: await setupStatus(),
    }
  }

  // A manual click is the explicit one-time agreement for a legacy record, but
  // it still must not overwrite an environment the user owns another way.
  async function manualEngineGuard(target) {
    const dist = await probeEngineDistribution(target)
    if (dist.ok && (dist.editable || dist.direct_url)) {
      return {
        ok: false,
        code: 'E_ENGINE_EDITABLE',
        message: '视频引擎来自可编辑或本地路径安装，DSH 不会覆盖它。',
        remedy: '请在原来的项目/环境中更新这个安装，不要用 DSH 覆盖。',
      }
    }
    // PEP 668 marks a system Python that pip must not manage in place. A venv
    // has its own site-packages, so its updates stay ordinary.
    const env = await probeEngineEnvironment(target)
    if (env.ok && env.externally_managed && !env.venv) {
      return {
        ok: false,
        code: 'E_ENGINE_MANAGED',
        message: '视频引擎所在的 Python 由系统管理，DSH 不能直接更新。',
        remedy: '请在对应的系统 Python 环境中维护它，不要安装到用户目录（--user）。',
      }
    }
    return { ok: true }
  }

  // Runs under the global install lock. It does not take the lock itself, so
  // install-all can call it without deadlocking.
  async function performEngineUpdate(target, { manual = false, currentVersion = '' } = {}) {
    if (!PLUGIN_VERSION) {
      return { ok: false, error: { code: 'E_VERSION', message: '插件版本未知，无法更新视频引擎。' }, output: '', status: await setupStatus() }
    }
    if (currentVersion && compareVersions(currentVersion, PLUGIN_VERSION) >= 0) {
      clearEngineUpdateMarker()
      setEngineUpdate('ready', PLUGIN_VERSION)
      return { ok: true, already: true, output: '', status: await setupStatus() }
    }
    // The old warm worker must not keep running while pip replaces its package.
    // If a read is still in flight, wait briefly; a manual click can be retried,
    // and an automatic attempt is simply deferred instead of killing that work.
    const quiescent = await waitForWorkerQuiescence(ENGINE_WORKER_QUIESCE_MS)
    if (!quiescent) {
      if (manual) {
        setEngineUpdate('failed', PLUGIN_VERSION, '有视频正在处理，请稍后再更新。')
        return {
          ok: false,
          error: { code: 'E_BUSY', message: '有视频正在处理，请稍后再更新。' },
          output: '',
          status: await setupStatus(),
        }
      }
      setEngineUpdate('idle')
      return { ok: false, deferred: true, error: { code: 'E_ENGINE_DEFERRED', message: '视频引擎正在使用中，本次自动更新已跳过。' }, output: '' }
    }
    // New tool/GC/command calls wait from here until the package replacement and
    // its validation finish. Existing work has already drained above. The
    // updater's own probes stay outside this barrier, so it cannot self-deadlock.
    beginEngineInstall()
    try {
    if (manual) {
      const guard = await manualEngineGuard(target)
      if (!guard.ok) {
        // The explicit click is refused, not silently retried: keep that
        // environment under its owner. No failed marker is persisted, so other
        // eligible installs/versions are not blocked by this answer.
        setEngineUpdate('failed', PLUGIN_VERSION, guard.message)
        return {
          ok: false,
          error: { code: guard.code, message: guard.message, remedy: guard.remedy },
          output: '',
          status: await setupStatus(),
        }
      }
    }
    // Take one normal snapshot before pip starts. GET polls during the update
    // reuse this instead of probing the package pip is replacing.
    try { await setupStatus({ cache: true }) } catch {}
    if (!workerBusy()) stopWorker()
    setEngineUpdate('updating', PLUGIN_VERSION)
    try {
      // Automatic updates are one exact, bounded step to the loaded plugin
      // version: never "latest", never a downgrade, never a long mirror fallback.
      const spec = manual
        ? CLI_PACKAGE + '>=' + PLUGIN_VERSION
        : CLI_PACKAGE + '==' + PLUGIN_VERSION
      const timeoutMs = manual ? SETUP_INSTALL_TIMEOUT : ENGINE_AUTO_PIP_TIMEOUT_MS
      const pip = await pipInstallEngine(target, { spec, timeoutMs, mirror: manual })
      if (pip.code !== 0) {
        return await failEngineUpdate('视频引擎更新失败，请检查网络后重试。', { output: pip.output || '' })
      }
      // Strict validation: pip exiting 0 is not success. Re-probe the actual
      // interpreter and refuse to report success for an older version.
      const probe = await probeEngineVersion(target)
      if (!probe.ok) {
        return await failEngineUpdate('无法确认更新后的视频引擎版本，请手动更新。', { output: pip.output || '' })
      }
      if (compareVersions(probe.version, PLUGIN_VERSION) < 0) {
        return await failEngineUpdate('视频引擎版本仍低于插件要求，请手动更新。', { output: pip.output || '' })
      }
      const dist = await probeEngineDistribution(target)
      const saved = await saveInstalledEngine(target, probe.version, dist)
      if (!saved) {
        return await failEngineUpdate('无法记录视频引擎位置，请手动更新。', { output: pip.output || '' })
      }
      clearEngineUpdateMarker()
      // The worker was stopped before pip; mark stale as a second guard in case
      // a request slipped in. A pending request is never killed.
      markWorkerStale()
      setEngineUpdate('ready', PLUGIN_VERSION)
      return { ok: true, output: pip.output || '', status: await setupStatus() }
    } catch (e) {
      return await failEngineUpdate('视频引擎更新失败，请手动重试。', { output: String((e && e.message) || e).slice(0, 1000) })
    }
    } finally {
      // Covers the pip path, a guard refusal, and a probe failure before pip.
      finishEngineInstall()
    }
  }

  // ---- Legacy engine adoption ------------------------------------------------
  // Older plugin versions recorded only "this interpreter can run the CLI" and
  // never wrote provenance, so engineAutoTarget() correctly refuses to update
  // that record in place. That left an ordinary PyPI 0.3.x engine on the manual
  // path forever after the plugin was upgraded. Adoption never modifies the old
  // environment: it builds a version-specific private venv, validates it, and
  // only then atomically switches the record. Explicit pins and self-managed
  // (editable/direct-url) installs stay with their owner.
  function engineHomePath() {
    return path.join(v2aHomePath(), 'engines')
  }

  function engineRootDir(version) {
    return path.join(engineHomePath(), String(version))
  }

  // Each attempt gets a fresh unique venv directory below the version root. A
  // venv embeds absolute paths in its scripts, so it is created where it will
  // live and never moved. Existing venvs are never deleted or overwritten (no
  // recursive deletion here); a failed attempt is kept for diagnostics, and its
  // persisted failure marker is what stops the next start from building another.
  function newEngineVenvDir(version) {
    try {
      const root = engineRootDir(version)
      fs.mkdirSync(root, { recursive: true })
      return fs.mkdtempSync(path.join(root, 'venv-'))
    } catch {
      return ''
    }
  }

  function engineVenvPython(dir) {
    return process.platform === 'win32'
      ? path.join(dir, 'Scripts', 'python.exe')
      : path.join(dir, 'bin', 'python')
  }

  // The PATH console script is what a Host with no record actually runs. It is
  // tried first so a legacy install is only adopted when something real is there.
  async function probePathCli() {
    if (ENGINE_TEST_HOOKS.probePathCli) {
      const r = await ENGINE_TEST_HOOKS.probePathCli()
      return { ok: r && r.code === 0, version: engineOutputVersion(r && r.out), output: String((r && r.out) || '') }
    }
    const r = await runCommand('video2agent', ['--version'], 30000)
    return { ok: r.code === 0, version: engineOutputVersion(r.out), output: String(r.out || '') }
  }

  // A pipx/venv console script may live in a directory whose python is not the
  // first python on PATH. doctor reports the interpreter that really runs the
  // CLI, which is the only honest base for the private environment.
  async function probeCliDoctor() {
    if (ENGINE_TEST_HOOKS.probeCliDoctor) return await ENGINE_TEST_HOOKS.probeCliDoctor()
    const r = await runCli(['doctor', '--json'], 30000)
    const data = parseJsonObjectText(r.out)
    if (data) {
      const interpreter = String((data && data.python && data.python.executable) || '')
      return { ok: r.code === 0, interpreter, version: String((data && data.version) || '') }
    }
    return { ok: false, interpreter: '', version: '' }
  }

  // Optional components are carried over only when the old engine really has
  // them. Installing an extra (and failing) must never silently drop OCR or
  // browser support the user already had.
  async function probeEngineExtras(target) {
    if (ENGINE_TEST_HOOKS.probeExtras) return await ENGINE_TEST_HOOKS.probeExtras(target)
    const code = [
      'import importlib.util as u, json',
      'def has(name):',
      '    try:',
      '        return u.find_spec(name) is not None',
      '    except Exception:',
      '        return False',
      'browser = has("playwright")',
      'ocr = has("rapidocr") or has("rapidocr_onnxruntime")',
      'print(json.dumps({"ok": True, "browser": browser, "ocr": ocr}))',
    ].join('\n')
    const r = await runCommand(target.command, [...(target.prefix || []), '-c', code], 30000)
    const line = String(r.out || '').trim().split('\n').pop() || ''
    try {
      const data = JSON.parse(line)
      const extras = []
      if (data.browser === true) extras.push('browser')
      if (data.ocr === true) extras.push('ocr')
      return { ok: data.ok === true, extras, detail: '' }
    } catch {
      return { ok: false, extras: [], detail: line.slice(0, 300) }
    }
  }

  async function createEngineVenv(base, dir) {
    if (ENGINE_TEST_HOOKS.createVenv) return await ENGINE_TEST_HOOKS.createVenv(base, dir)
    try {
      fs.mkdirSync(path.dirname(dir), { recursive: true })
    } catch (e) {
      return { ok: false, output: String((e && e.message) || e).slice(0, 500) }
    }
    // POSIX and Windows both ship venv in the standard library; a distro that
    // splits it out reports a normal command error instead of a platform guess.
    const r = await runCommand(base.command, [...(base.prefix || []), '-m', 'venv', dir], 120000)
    const output = (String(r.out || '') + '\n' + String(r.err || '')).trim()
    return { ok: r.code === 0, output: output.slice(-4000) }
  }

  async function resolvePathCliInterpreter(version) {
    // doctor is the old CLI's own answer about the interpreter that runs it.
    // That is authoritative for pipx/venv wrappers, where the first python on
    // PATH can be a completely different environment.
    const doctor = await probeCliDoctor()
    if (doctor.ok && usableInterpreterPath(doctor.interpreter)) {
      return { command: doctor.interpreter, prefix: [] }
    }
    // Fallback: try every candidate, not just the first. On Windows "py" often
    // starts an unrelated Python while the old CLI's own "python" (or a
    // pipx/venv launcher earlier on PATH) is the one that can run it.
    for (const command of pythonCandidates()) {
      const prefix = command === 'py' ? ['-3'] : []
      const probe = await probeEngineVersion({ command, prefix })
      if (probe.ok && (!version || probe.version === version)) {
        return { command, prefix }
      }
    }
    return null
  }

  // What old engine (if any) may be adopted. Both a legacy record and a bare
  // PATH/module install are eligible; an authorized managed record is not (that
  // path keeps updating in place above), and pins are never touched.
  async function legacyEngineTarget() {
    if (process.env.VIDEO2AGENT_BIN) return { ok: false, reason: 'explicit-bin' }
    if (process.env.VIDEO2AGENT_PYTHON) return { ok: false, reason: 'explicit-python' }
    const record = readManagedTools().cli
    if (record && typeof record === 'object' && record.source === 'plugin-install') {
      return { ok: false, reason: 'managed' }
    }
    if (record && typeof record === 'object' && record.python) {
      const prefix = Array.isArray(record.prefix) ? record.prefix.map(String) : []
      let target = null
      if (usableInterpreterPath(record.python)) {
        target = { command: String(record.python), prefix }
      } else if (isBareCommandName(record.python)) {
        // Resolve the recorded launcher without writing it back: a failed
        // adoption must leave the record exactly as it was.
        const absolute = await probeEngineInterpreter({ command: String(record.python), prefix })
        if (absolute) target = { command: absolute, prefix: [] }
      }
      if (target) {
        const probe = await probeEngineVersion(target)
        if (probe.ok) return { ok: true, target, version: probe.version, source: 'record', record }
        return { ok: false, reason: 'version-unknown' }
      }
    }
    const pathCli = await probePathCli()
    if (pathCli.ok && pathCli.version) {
      const target = await resolvePathCliInterpreter(pathCli.version)
      if (!target) return { ok: false, reason: 'interpreter-unknown', version: pathCli.version }
      return { ok: true, target, version: pathCli.version, source: 'path', record: null }
    }
    // No PATH console script: the old engine may still be reachable as a module.
    // Probe every candidate for the same reason as above, rather than trusting
    // the first Python that happens to exist.
    for (const command of pythonCandidates()) {
      const prefix = command === 'py' ? ['-3'] : []
      const probe = await probeEngineVersion({ command, prefix })
      if (probe.ok) return { ok: true, target: { command, prefix }, version: probe.version, source: 'python', record: null }
    }
    return { ok: false, reason: 'no-engine' }
  }

  async function verifyPrivateEngine(python) {
    const probe = await probeEngineVersion({ command: python, prefix: [] })
    if (!probe.ok || compareVersions(probe.version, PLUGIN_VERSION) < 0) return { ok: false, version: probe.version || '' }
    const dist = await probeEngineDistribution({ command: python, prefix: [] })
    if (!dist.ok || dist.editable || dist.direct_url) return { ok: false, version: probe.version || '' }
    return { ok: true, version: probe.version, dist }
  }

  async function browserRuntimeAvailable(python) {
    if (ENGINE_TEST_HOOKS.browserRuntime) return await ENGINE_TEST_HOOKS.browserRuntime(python)
    // A Python package alone is not a usable browser. Reuse the user's installed
    // Chrome/Edge, or the browser this exact Playwright install can launch.
    // Never assume the newest Playwright matches an older downloaded Chromium.
    return (await detectSystemBrowser()) || (await detectPlaywrightBrowser(python, { strict: true }))
  }

  async function ocrRuntimeAvailable(python) {
    if (ENGINE_TEST_HOOKS.ocrRuntime) return await ENGINE_TEST_HOOKS.ocrRuntime(python)
    const r = await runCommand(python, ['-m', 'video2agent', 'models', 'status', '--json'], 30000)
    const data = parseJsonObjectText(r.out)
    return Boolean(data && data.ocr && data.ocr.available === true)
  }

  // The new venv is only trusted when the core engine AND every optional
  // component the old engine had are really usable there. Otherwise the record
  // is not switched and the working old engine remains in use.
  async function verifyMigratedExtras(python, wanted) {
    if (!wanted.length) return { ok: true }
    const installed = await probeEngineExtras({ command: python, prefix: [] })
    if (!installed.ok) return { ok: false, reason: 'extras-probe' }
    for (const extra of wanted) {
      if (!installed.extras.includes(extra)) return { ok: false, reason: 'missing-' + extra }
    }
    if (wanted.includes('browser') && !(await browserRuntimeAvailable(python))) {
      return { ok: false, reason: 'browser-runtime' }
    }
    if (wanted.includes('ocr') && !(await ocrRuntimeAvailable(python))) {
      return { ok: false, reason: 'ocr-runtime' }
    }
    return { ok: true }
  }

  // Runs under the global install lock (the caller takes it) and takes the
  // engine-install barrier itself, so no tool/GC/command path runs the old or
  // half-built CLI while pip writes the new environment.
  async function performLegacyEngineMigration(entry, { manual = false, currentVersion = '' } = {}) {
    if (!PLUGIN_VERSION) {
      return { ok: false, error: { code: 'E_VERSION', message: '插件版本未知，无法更新视频引擎。' }, output: '', status: await setupStatus() }
    }
    if (!entry || !entry.ok || !entry.target) {
      return { ok: false, error: { code: 'E_ENGINE_LEGACY', message: '无法确认旧版视频引擎的位置。' }, output: '', status: await setupStatus() }
    }
    const current = String(currentVersion || entry.version || '')
    if (current && compareVersions(current, PLUGIN_VERSION) >= 0) {
      clearEngineUpdateMarker()
      setEngineUpdate('idle')
      return { ok: true, already: true, output: '', status: await setupStatus() }
    }
    // A project checkout or a local wheel is owned elsewhere. Switching away
    // from it would silently override the user's setup, so leave it alone.
    const oldDist = await probeEngineDistribution(entry.target)
    if (!oldDist.ok || oldDist.editable || oldDist.direct_url) {
      setEngineUpdate('idle')
      return { ok: false, skipped: true, reason: 'owned-environment', output: '' }
    }
    const extras = await probeEngineExtras(entry.target)
    if (!extras.ok) {
      // Without an honest extras probe the migration could silently lose OCR or
      // browser support. Keep the working old engine instead of guessing.
      setEngineUpdate('idle')
      return { ok: false, skipped: true, reason: 'extras-unknown', output: '' }
    }
    const quiescent = await waitForWorkerQuiescence(ENGINE_WORKER_QUIESCE_MS)
    if (!quiescent) {
      if (manual) {
        setEngineUpdate('failed', PLUGIN_VERSION, '有视频正在处理，请稍后再更新。')
        return {
          ok: false,
          error: { code: 'E_BUSY', message: '有视频正在处理，请稍后再更新。' },
          output: '',
          status: await setupStatus(),
        }
      }
      setEngineUpdate('idle')
      return { ok: false, deferred: true, error: { code: 'E_ENGINE_DEFERRED', message: '视频引擎正在使用中，本次自动更新已跳过。' }, output: '' }
    }
    // Distinguishes a transient failure (no venv, nothing installed yet) from a
    // real attempt: only the latter persists a marker that stops the next start.
    let attemptedInstall = false
    const failMigration = async (message, output = '') => {
      if (attemptedInstall) writeLegacyMigrationFailure(message, entry.version)
      return await failEngineUpdate(message, { output, persist: false })
    }
    const venvDir = newEngineVenvDir(PLUGIN_VERSION)
    if (!venvDir) {
      return await failEngineUpdate('无法创建独立的视频引擎环境，请检查 Python 安装后重试。', { output: '', persist: false })
    }
    beginEngineInstall()
    try {
      // No pre-pip CLI probe here: a no-record module install would make
      // detectCli write a detection record before the migration has succeeded.
      // GET already serves a read-only transient while state is updating.
      if (!workerBusy()) stopWorker()
      setEngineUpdate('updating', PLUGIN_VERSION)
      try {
        // A unique attempt directory below the version root; it is created
        // where it will live (venv scripts embed absolute paths) and existing
        // venvs are never deleted or reused. The record write below is the
        // atomic switch: until then this directory is unreferenced and the old
        // engine keeps running.
        const venvPython = engineVenvPython(venvDir)
        const created = await createEngineVenv(entry.target, venvDir)
        if (!created.ok) {
          return await failEngineUpdate('无法创建独立的视频引擎环境，请检查 Python 安装后重试。', { output: created.output || '', persist: false })
        }
        if (!usableInterpreterPath(venvPython)) {
          return await failEngineUpdate('无法创建独立的视频引擎环境，请检查 Python 安装后重试。', { output: created.output || '', persist: false })
        }
        // Extras are only the ones the old engine actually had. The browser
        // extra installs Playwright; a system Chrome/Edge or an existing
        // Playwright browser cache is reused, never downloaded again.
        const spec = CLI_PACKAGE + (extras.extras.length ? '[' + extras.extras.join(',') + ']' : '') + '==' + PLUGIN_VERSION
        // From here on something was really installed: a failure leaves a venv
        // behind, so it must block the next automatic attempt.
        attemptedInstall = true
        const pip = await pipInstallEngine({ command: venvPython, prefix: [] }, {
          spec,
          timeoutMs: extras.extras.length ? ENGINE_MIGRATE_PIP_TIMEOUT_MS : ENGINE_AUTO_PIP_TIMEOUT_MS,
          mirror: false,
        })
        if (pip.code !== 0) {
          return await failMigration('视频引擎自动更新未完成，请稍后重试。', pip.output || '')
        }
        const verified = await verifyPrivateEngine(venvPython)
        if (!verified.ok) {
          return await failMigration('无法确认更新后的视频引擎版本，请稍后重试。', pip.output || '')
        }
        const extraCheck = await verifyMigratedExtras(venvPython, extras.extras)
        if (!extraCheck.ok) {
          return await failMigration('视频引擎的附加组件无法在新环境中继续使用，已保留当前版本。', extraCheck.reason || '')
        }
        const previous = entry.record
          ? {
            python: String(entry.record.python || ''),
            prefix: Array.isArray(entry.record.prefix) ? entry.record.prefix.map(String) : [],
            version: entry.version || '',
            source: entry.record.source || null,
          }
          : {
            python: entry.target.command,
            prefix: (entry.target.prefix || []).map(String),
            version: entry.version || '',
            source: null,
          }
        const saved = saveManagedCli(venvPython, [], {
          source: 'plugin-install',
          auto_update: true,
          version: verified.version,
          plugin_version: PLUGIN_VERSION,
          installed_at: new Date().toISOString(),
          engine_root: venvDir,
          previous,
        })
        if (!saved) {
          return await failMigration('无法记录视频引擎位置，请稍后重试。')
        }
        clearEngineUpdateMarker()
        markWorkerStale()
        setEngineUpdate('ready', PLUGIN_VERSION)
        return { ok: true, output: '已切换到独立版本视频引擎 ' + PLUGIN_VERSION, status: await setupStatus() }
      } catch (e) {
        return await failMigration('视频引擎自动更新未完成，请稍后重试。', String((e && e.message) || e).slice(0, 1000))
      }
    } finally {
      finishEngineInstall()
    }
  }

  async function runEngineAutoUpdate() {
    if (!PLUGIN_VERSION) { setEngineUpdate('idle'); return }
    // The code that is running may not match the package.json on disk. Until a
    // restart, do not guess which engine version belongs to which plugin.
    if (pluginRestartRequired()) { setEngineUpdate('idle'); return }
    const target = engineAutoTarget()
    if (!target.ok) {
      // A legacy install has no authorization record. Adopt it into a private
      // version environment instead of leaving the user on the manual path
      // forever. Explicit pins and managed records never reach this branch.
      if (['no-managed-cli', 'not-authorized', 'interpreter-missing'].includes(String(target.reason || ''))) {
        // A previous start already installed something and failed. Rebuilding a
        // private venv on every start is what this marker prevents; resuming is
        // the user's explicit update click (same migration, marker cleared).
        const failedMigration = readLegacyMigrationFailure()
        if (failedMigration) {
          setEngineUpdate('failed', PLUGIN_VERSION, String(failedMigration.message || '视频引擎更新失败，请手动重试。'))
          return
        }
        const legacy = await legacyEngineTarget()
        if (legacy.ok) {
          if (compareVersions(legacy.version, PLUGIN_VERSION) >= 0) {
            clearEngineUpdateMarker()
            setEngineUpdate('idle')
            return
          }
          const result = await withInstallLock('engine-legacy-migration', () => performLegacyEngineMigration(legacy, { manual: false, currentVersion: legacy.version }))
          if (result && result.error && result.error.code === 'E_BUSY') {
            if (ENGINE_UPDATE.state !== 'updating') setEngineUpdate('idle')
          }
          return
        }
      }
      setEngineUpdate('idle')
      return
    }
    const probe = await probeEngineVersion(target)
    if (!probe.ok) {
      await failEngineUpdate('无法确认视频引擎版本，请手动更新。')
      return
    }
    if (compareVersions(probe.version, PLUGIN_VERSION) >= 0) {
      // A stale failure marker must not outlive a manually fixed engine.
      clearEngineUpdateMarker()
      setEngineUpdate('idle')
      return
    }
    const marker = readEngineUpdateMarker()
    // A legacy-adoption marker is not an in-place update failure: this branch is
    // reached only with an authorized managed record, which the adoption did not
    // create, so it must not block the normal update.
    if (marker && marker.kind !== LEGACY_MIGRATION_MARKER_KIND
        && marker.plugin_version === PLUGIN_VERSION && marker.target === PLUGIN_VERSION && marker.state === 'failed') {
      setEngineUpdate('failed', PLUGIN_VERSION, String(marker.message || '视频引擎更新失败，请手动重试。'))
      return
    }
    const dist = await probeEngineDistribution(target)
    if (!dist.ok || dist.editable || dist.direct_url) {
      // The record says plugin-install, but the live environment is now editable
      // or a direct checkout. Do not overwrite it silently; the manual button
      // remains the explicit path.
      setEngineUpdate('idle')
      return
    }
    const result = await withInstallLock('engine-auto-update', () => performEngineUpdate(target, { manual: false, currentVersion: probe.version }))
    if (result && result.ok !== true && result.error && result.error.code === 'E_BUSY') {
      // A manual install/update owns the lock. Do not overwrite its state and do
      // not queue a second pip attempt.
      if (ENGINE_UPDATE.state !== 'updating') setEngineUpdate('idle')
    }
  }

  function scheduleEngineAutoUpdate() {
    // A repeated apply() must not skip the first update's startup barrier. Only
    // the run that armed the gate may settle it (in the finally below); settling
    // here would let tool/command/cache paths run the old CLI while pip is still
    // replacing it.
    if (ENGINE_AUTO_STARTED) return
    ENGINE_AUTO_STARTED = true
    createEngineReadyGate()
    ;(async () => {
      try {
        await runEngineAutoUpdate()
      } catch (e) {
        try {
          await failEngineUpdate('视频引擎更新失败，请手动重试。', { output: String((e && e.message) || e).slice(0, 1000) })
        } catch {}
      } finally {
        // The gate must settle on every path, including a thrown probe. A tool
        // waiting on it then proceeds with the old (still truthful) state.
        resolveEngineReadyGate()
      }
    })()
  }

  // An explicit update click is the only way out of a failed adoption: retry the
  // same private migration (it clears the marker on success) instead of leaving
  // the user on a message with no action. Everything else keeps the in-place
  // path below.
  async function retryLegacyMigration(before) {
    if (!readLegacyMigrationFailure()) return null
    const legacy = await legacyEngineTarget()
    if (!legacy.ok) return null
    const migrated = await performLegacyEngineMigration(legacy, {
      manual: true,
      currentVersion: (before && before.cli && before.cli.version) || legacy.version,
    })
    return migrated && !migrated.skipped ? migrated : null
  }

  async function installCli(force = false) {
    const before = await setupStatus()
    if (before.cli.ok && !force && !before.cli.update_available) return { ok: true, already: true, output: '', status: before }
    if (before.cli.ok) {
      // The explicit update button resumes a blocked adoption first.
      if (force) {
        const retried = await retryLegacyMigration(before)
        if (retried) return retried
      }
      // An installed CLI is updated in place, using the interpreter this Host
      // actually runs. Do not fall through to a different Python: that would
      // install a package the Host never calls and report a false success.
      const target = await engineManualTarget({
        preferred: (before.browser && before.browser.interpreter) || '',
        allowDetect: false,
      })
      if (!target.ok) {
        // No record at all (a PATH install this Host never adopted). The
        // explicit click may use the same private-venv adoption the automatic
        // path uses; it still never touches pins or a self-managed checkout.
        if (target.reason === 'interpreter-unknown') {
          const legacy = await legacyEngineTarget()
          if (legacy.ok) {
            const migrated = await performLegacyEngineMigration(legacy, {
              manual: true,
              currentVersion: before.cli.version || legacy.version,
            })
            if (!migrated.skipped) return migrated
          }
        }
        const message = target.reason === 'explicit-bin'
          ? '视频引擎由外部路径指定，请在对应环境手动更新。'
          : target.reason === 'python-pin-missing'
            ? 'VIDEO2AGENT_PYTHON 指向不存在的解释器。'
            : target.reason === 'interpreter-unknown'
              ? '无法确认视频引擎所在的 Python 环境（例如 pipx），请在对应环境中更新。'
              : '没有找到可更新的 Python 解释器。'
        return {
          ok: false,
          error: { code: 'E_MANUAL_UPDATE', message, remedy: '修正视频引擎路径/解释器设置后重试。' },
          status: before,
        }
      }
      return performEngineUpdate(target, { manual: true, currentVersion: before.cli.version })
    }
    const python = await detectPython()
    if (!python.ok) {
      return {
        ok: false,
        error: {
          code: 'E_PYTHON',
          message: python.tooOld ? 'Python 版本低于 3.11' : '没有找到 Python',
          remedy: '安装 Python 3.11+ 后重试：https://www.python.org/downloads/（Windows 可 winget install Python.Python.3.12）',
        },
        status: before,
      }
    }
    // PyPI can be slow/unreachable on some networks; a failed default-source
    // install is retried once through the Tsinghua mirror instead of dead-ending
    // the user on a machine that otherwise has a working Python.
    const pipInstall = (packages, extraArgs = []) => runCommand(
      python.command,
      [...python.prefix, '-m', 'pip', 'install', '--upgrade', ...extraArgs, ...packages],
      SETUP_INSTALL_TIMEOUT,
    )
    let r = await pipInstall(['video2agent'])
    let mirrorNote = ''
    if (r.code !== 0) {
      mirrorNote = '\n默认 PyPI 源安装失败，改用清华镜像重试…\n'
      // Mirror only: keep TLS certificate verification on. The old trusted-host
      // flag disabled it for the mirror, which turns a certificate problem into
      // a silent downgrade to unauthenticated package downloads.
      r = await pipInstall(['video2agent'], ['-i', 'https://pypi.tuna.tsinghua.edu.cn/simple'])
    }
    const coreOutput = (mirrorNote + ((String(r.out || '') + '\n' + String(r.err || '')).trim())).slice(-6000)
    const pythonLabel = [python.command, ...python.prefix].join(' ')
    if (r.code !== 0) {
      const failedText = String(r.out || '') + String(r.err || '')
      const versionHint = /No matching distribution/i.test(failedText)
        ? '（当前 Python 可能没有对应依赖的 wheel：核心安装支持 Python 3.11–3.13，本地 OCR 额外包要求 3.11/3.12）'
        : ''
      return {
        ok: false,
        error: {
          code: 'E_PIP',
          message: 'pip install video2agent 失败',
          remedy: '检查网络和 pip 后可手动运行：' + pythonLabel + ' -m pip install --upgrade video2agent' + versionHint
            + '。国内网络可加镜像 -i https://pypi.tuna.tsinghua.edu.cn/simple；'
            + '如果 Python 是系统托管环境（PEP 668），改用 pipx/venv 安装，或给 pip 加 --user。',
        },
        output: coreOutput,
        status: await setupStatus(),
      }
    }
    // Local OCR is an optional extra with its own button (and no rapidocr wheel
    // on Python 3.13); installing it here made the one-click CLI install slow and
    // look stuck, so keep the core install fast and report the extra separately.
    const [pMajor, pMinor] = String(python.version || '').split('.').map((part) => Number(part) || 0)
    const ocrSupported = pMajor < 3 || (pMajor === 3 && pMinor < 13)
    const extraOutput = ocrSupported
      ? '\n本地 OCR（可选，读画面上的字）可在环境检查里单独安装：pip install "video2agent[ocr]"'
      : '\nPython ' + (python.version || '') + ' 没有本地 OCR 的 wheel；核心转写/检索可用，本地 OCR 需要 Python 3.11/3.12。'
    const output = (coreOutput + '\n' + extraOutput).trim().slice(-8000)
    // Record provenance only after this plugin's own install succeeded. The
    // version/metadata re-probe also decides whether future releases may update
    // it automatically (never an editable or direct-URL install).
    const installedTarget = {
      command: python.command,
      prefix: python.prefix,
    }
    let managedEngineTarget = null
    let installedDist = null
    let probedVersion = ''
    const absolute = await probeEngineInterpreter(installedTarget)
    if (absolute) {
      const candidate = { command: absolute, prefix: [] }
      const probed = await probeEngineVersion(candidate)
      if (probed.ok) {
        managedEngineTarget = candidate
        probedVersion = probed.version
        installedDist = await probeEngineDistribution(candidate)
        // Record how to reach the new CLI so this probe and every later call use
        // it, but do not grant auto-update authorization yet. The full install
        // path below still has to confirm the CLI starts and the version matches.
        await saveInstalledEngine(candidate, probedVersion, installedDist, { authorize: false })
      }
    }
    const after = await setupStatus()
    if (!after.cli.ok) {
      return {
        ok: false,
        error: {
          code: 'E_CLI_NOT_ON_PATH',
          message: 'pip 装完了，但 video2agent 仍无法启动',
          remedy: '检查 ' + pythonLabel + ' -m video2agent --version；修好后重开 DSH 再试。',
        },
        output,
        status: after,
      }
    }
    // A version below the loaded plugin is not a usable install. Saying
    // "success" here would make the next tool call fail against an old engine.
    if (after.cli.version && compareVersions(after.cli.version, PLUGIN_VERSION) < 0) {
      return {
        ok: false,
        error: {
          code: 'E_CLI_VERSION',
          message: '安装的视频引擎版本低于插件要求',
          remedy: '确认 PyPI 上已有 video2agent ' + PLUGIN_VERSION + ' 后重试，或稍后再更新。',
        },
        output,
        status: after,
      }
    }
    // The install path succeeded and the version is not older than this plugin:
    // now the managed record may authorize future automatic updates.
    if (managedEngineTarget) {
      await saveInstalledEngine(managedEngineTarget, after.cli.version || probedVersion, installedDist, { authorize: true })
    }
    // A warm worker keeps the environment it started with; restart it so the new
    // CLI/env is what the next tool call uses.
    stopWorker()
    return { ok: true, output, status: after }
  }

  // Optional components live in the interpreter that actually runs the CLI. The
  // managed record is the exact invocation the Host uses; for a PATH/pipx install
  // the CLI's own doctor is the only honest owner report. A known engine with no
  // trustworthy interpreter is a refusal, not a reason to install into whichever
  // "python" happens to be first on PATH: that made the card say "installed"
  // while the CLI still reported OCR missing.
  async function componentInstallInterpreter(status) {
    const direct = cliInterpreter()
    if (direct && direct.command) {
      return { ok: true, command: direct.command, prefix: direct.prefix || [], via: 'record' }
    }
    if (status && status.cli && status.cli.ok) {
      const doctor = await probeCliDoctor()
      if (usableInterpreterPath(doctor.interpreter)) {
        return { ok: true, command: doctor.interpreter, prefix: [], via: 'doctor' }
      }
      return { ok: false, reason: 'interpreter-unknown' }
    }
    const python = await detectPython()
    if (python.ok) return { ok: true, command: python.command, prefix: python.prefix, via: 'detected' }
    return { ok: false, reason: python.tooOld ? 'python-too-old' : 'no-python' }
  }

  function componentInstallError(before, reason, extra) {
    const interpreterUnknown = reason === 'interpreter-unknown'
    return {
      ok: false,
      error: interpreterUnknown
        ? {
          code: 'E_PYTHON',
          message: '无法确认视频引擎所在的 Python 环境',
          remedy: '请回到安装视频引擎的那个环境重试，或手动运行 pip install "video2agent[' + extra + ']"。',
        }
        : {
          code: 'E_PYTHON',
          message: reason === 'python-too-old' ? 'Python 版本低于 3.11' : '没有找到可用的 Python',
          remedy: '安装 Python 3.11/3.12 后重试',
        },
      status: before,
    }
  }

  // A component install only adds the optional extra to the core engine that
  // interpreter already has. The exact installed version pins the requirement:
  // without a version pip may backtrack (or resolve a newer/older core) to
  // satisfy the extra's dependencies, and --upgrade would replace the managed
  // engine outside the version/authorization path. importlib.metadata is the
  // installed package's own answer (editable/dev builds included); the CLI's
  // reported version is only a fallback. The plugin version is never used here:
  // pinning that could downgrade a newer or user-owned engine.
  async function componentEngineVersion(interpreter, status) {
    const dist = await probeEngineDistribution(interpreter)
    if (dist.ok && dist.version) return String(dist.version)
    // The interpreter itself can still answer even when the card's CLI probe was
    // not usable. Only a real answer is used; no version is guessed.
    const probe = await probeEngineVersion(interpreter)
    if (probe.ok && probe.version) return String(probe.version)
    return status && status.cli && status.cli.version ? String(status.cli.version) : ''
  }

  function componentPipInstall(interpreter, extra, version, extraArgs = []) {
    const exact = String(version || '').trim()
    const pkg = CLI_PACKAGE + '[' + extra + ']' + (exact ? '==' + exact : '')
    const args = [
      ...(interpreter.prefix || []),
      '-m', 'pip', 'install',
      ...extraArgs,
      pkg,
    ]
    if (ENGINE_TEST_HOOKS.componentPip) {
      return ENGINE_TEST_HOOKS.componentPip(
        { command: interpreter.command, prefix: [...(interpreter.prefix || [])] },
        { args: [...args], extra, package: pkg, version: exact },
      )
    }
    return runCommand(interpreter.command, args, SETUP_INSTALL_TIMEOUT)
  }

  // Optional local OCR (rapidocr-onnxruntime). Separate from installCli: the
  // resolver for that package can be slow, and it has no Python 3.13 wheel.
  async function installOcr() {
    const before = await setupStatus()
    if (before.ocr && before.ocr.ok) return { ok: true, already: true, output: '', status: before }
    const python = await componentInstallInterpreter(before)
    if (!python.ok) return componentInstallError(before, python.reason, 'ocr')
    const coreVersion = await componentEngineVersion(python, before)
    const pipOcr = (extraArgs = []) => componentPipInstall(python, 'ocr', coreVersion, extraArgs)
    let r = await pipOcr()
    let note = ''
    if (r.code !== 0) {
      note = '默认 PyPI 源安装失败，改用清华镜像重试…\n'
      r = await pipOcr(['-i', 'https://pypi.tuna.tsinghua.edu.cn/simple'])
    }
    const output = (note + ((String(r.out || '') + '\n' + String(r.err || '')).trim())).slice(-6000)
    const status = await setupStatus()
    if (r.code !== 0 || !status.ocr || !status.ocr.ok) {
      return {
        ok: false,
        error: {
          code: 'E_PIP',
          message: '本地 OCR 安装失败',
          remedy: '检查网络后重试；也可改用云端 OCR，或手动运行 pip install "video2agent[ocr]"。',
        },
        output,
        status,
      }
    }
    stopWorker()
    return { ok: true, output, status }
  }

  async function detectSystemBrowser() {
    const candidates = []
    if (process.platform === 'win32') {
      const roots = [process.env.PROGRAMFILES, process.env['PROGRAMFILES(X86)'], process.env.LOCALAPPDATA].filter(Boolean)
      for (const root of roots) {
        candidates.push(path.join(root, 'Google', 'Chrome', 'Application', 'chrome.exe'))
        candidates.push(path.join(root, 'Microsoft', 'Edge', 'Application', 'msedge.exe'))
      }
    } else if (process.platform === 'darwin') {
      candidates.push('/Applications/Google Chrome.app/Contents/MacOS/Google Chrome')
      candidates.push('/Applications/Microsoft Edge.app/Contents/MacOS/Microsoft Edge')
    }
    for (const candidate of candidates) {
      try { if (fs.existsSync(candidate)) return true } catch {}
    }
    if (process.platform !== 'win32' && process.platform !== 'darwin') {
      for (const command of ['google-chrome', 'microsoft-edge']) {
        const probe = await runCommand(command, ['--version'], 15000)
        if (probe.code === 0) return true
      }
    }
    return false
  }

  async function installBrowser() {
    const before = await setupStatus()
    if (before.browser && before.browser.ok) return { ok: true, already: true, output: '', status: before }
    const interpreter = await componentInstallInterpreter(before)
    if (!interpreter.ok) return componentInstallError(before, interpreter.reason, 'browser')
    const coreVersion = await componentEngineVersion(interpreter, before)
    const pipInstall = (extraArgs = []) => componentPipInstall(interpreter, 'browser', coreVersion, extraArgs)
    let result = await pipInstall()
    let mirrorNote = ''
    if (result.code !== 0) {
      mirrorNote = '默认 PyPI 源安装失败，改用清华镜像重试…\n'
      result = await pipInstall(['-i', 'https://pypi.tuna.tsinghua.edu.cn/simple'])
    }
    let output = (mirrorNote + ((String(result.out || '') + '\n' + String(result.err || '')).trim())).slice(-6000)
    if (result.code !== 0) {
      return {
        ok: false,
        error: {
          code: 'E_PIP',
          message: '浏览器组件安装失败',
          remedy: '检查网络后重试；也可手动运行 pip install "video2agent[browser]"。',
        },
        output,
        status: await setupStatus(),
      }
    }
    // Prefer the user's Chrome/Edge. Only download Chromium when no system
    // browser exists; otherwise a one-click install would add hundreds of MB for
    // no reason on most desktops.
    if (!(await detectSystemBrowser())) {
      const browserInstall = await runCommand(
        interpreter.command,
        [...(interpreter.prefix || []), '-m', 'playwright', 'install', 'chromium'],
        SETUP_INSTALL_TIMEOUT,
      )
      output = (output + '\n' + ((String(browserInstall.out || '') + '\n' + String(browserInstall.err || '')).trim())).slice(-8000)
      if (browserInstall.code !== 0) {
        return {
          ok: false,
          error: {
            code: 'E_BROWSER_INSTALL',
            message: 'Playwright 已装好，但 Chromium 下载失败',
            remedy: '先安装 Chrome/Edge，或运行 python -m playwright install chromium 后重试。',
          },
          output,
          status: await setupStatus(),
        }
      }
    }
    stopWorker()
    return { ok: true, output, status: await setupStatus() }
  }

  async function installAll() {
    const before = await setupStatus()
    const outputs = []
    const failed = []
    const runStep = async (key, task) => {
      const result = await task()
      if (result && result.output) outputs.push('[' + key + ']\n' + result.output)
      if (!result || result.ok !== true) {
        failed.push({ key, error: (result && result.error) || { code: 'E_INSTALL', message: key + ' 安装失败' } })
      }
      return result
    }
    if (!before.cli.ok) await runStep('视频引擎', () => installCli(false))
    else if (before.cli.update_available) await runStep('视频引擎', () => installCli(true))
    if (!before.ffmpeg.ok && before.canInstall.ffmpeg) await runStep('FFmpeg', installFfmpeg)
    if (!before.browser.ok && before.canInstall.browser) await runStep('浏览器组件', installBrowser)
    if (before.ocr && before.ocr.supported && !before.ocr.ok && before.canInstall.ocr) {
      await runStep('OCR', installOcr)
    }
    const after = await setupStatus()
    const missing = []
    if (!after.python.ok) missing.push('Python')
    if (!after.cli.ok) missing.push('视频引擎')
    if (!after.ffmpeg.ok) missing.push('FFmpeg')
    if (after.browser && !after.browser.ok) missing.push('浏览器组件')
    if (after.ocr && after.ocr.supported && !after.ocr.ok) missing.push('OCR')
    if (failed.length) {
      const names = failed.map((item) => item.key + '：' + ((item.error && (item.error.message || item.error.code)) || '失败'))
      return {
        ok: false,
        error: { code: 'E_SETUP_PARTIAL', message: '部分依赖安装失败', remedy: names.join('；') },
        output: outputs.join('\n\n'),
        status: after,
      }
    }
    if (missing.length) {
      return {
        ok: false,
        error: {
          code: 'E_SETUP_MANUAL',
          message: '还有依赖需要手动安装：' + missing.join('、'),
          remedy: 'Python/FFmpeg 等系统依赖无法在页面内安装，请按环境检查里的提示处理。',
        },
        output: outputs.join('\n\n'),
        status: after,
      }
    }
    stopWorker()
    return { ok: true, output: outputs.join('\n\n'), status: after }
  }

  function findExecutable(root, name, depth = 0) {
    if (!root || depth > 4) return null
    let entries = []
    try {
      entries = fs.readdirSync(root, { withFileTypes: true })
    } catch {
      return null
    }
    for (const entry of entries) {
      if (entry.isFile() && entry.name.toLowerCase() === name) return path.join(root, entry.name)
    }
    for (const entry of entries) {
      if (!entry.isDirectory()) continue
      const hit = findExecutable(path.join(root, entry.name), name, depth + 1)
      if (hit) return hit
    }
    return null
  }

  function saveManagedFfmpeg(ffmpeg, ffprobe, source) {
    try {
      fs.mkdirSync(path.dirname(managedToolsPath()), { recursive: true })
      const tools = { ...readManagedTools(), ffmpeg, ffprobe: ffprobe || '', source, at: new Date().toISOString() }
      fs.writeFileSync(managedToolsPath(), JSON.stringify(tools, null, 2), 'utf8')
      return true
    } catch {
      return false
    }
  }

  function winGetPackageRoot() {
    const local = process.env.LOCALAPPDATA || path.join(os.homedir(), 'AppData', 'Local')
    return path.join(local, 'Microsoft', 'WinGet', 'Packages')
  }

  async function installFfmpeg() {
    const before = await setupStatus()
    if (before.ffmpeg.ok) return { ok: true, already: true, output: '', status: before }
    let r = null
    if (process.platform === 'win32') {
      // An FFmpeg can be installed but missing from this process's PATH (the app
      // started before the install). Adopt it instead of running an upgrade the
      // user did not ask for.
      const installedRoot = winGetPackageRoot()
      if (fs.existsSync(installedRoot)) {
        // Prefer the package the install button itself uses, then anything else;
        // require ffprobe and a working binary before recording anything.
        const candidates = fs.readdirSync(installedRoot)
          .filter((name) => /ffmpeg/i.test(name))
          .sort((a, b) => (/gyan/i.test(b) ? 1 : 0) - (/gyan/i.test(a) ? 1 : 0))
        for (const candidate of candidates) {
          const base = path.join(installedRoot, candidate)
          const existing = findExecutable(base, 'ffmpeg.exe')
          const probe = findExecutable(base, 'ffprobe.exe')
          if (!existing || !probe) continue
          const check = await runCommand(existing, ['-version'], 20000)
          if (check.code !== 0) continue
          saveManagedFfmpeg(existing, probe, 'found')
          const adopted = await setupStatus()
          if (adopted.ffmpeg.ok) {
            stopWorker()
            return { ok: true, already: true, adopted: true, output: '', status: adopted }
          }
        }
      }
      const where = await runCommand('where', ['winget'], 20000)
      if (where.code !== 0) {
        return {
          ok: false,
          error: { code: 'E_WINGET', message: '这台机器没有 winget', remedy: '手动安装 FFmpeg，或把 FFMPEG_BIN 指向 ffmpeg.exe 后重试' },
          status: before,
        }
      }
      r = await runCommand('winget', ['install', '--id', 'Gyan.FFmpeg', '-e', '--accept-source-agreements', '--accept-package-agreements', '--disable-interactivity'], SETUP_INSTALL_TIMEOUT)
      if (r.code === 0 || /already installed|已安装/i.test(String(r.out) + String(r.err))) {
        const root = winGetPackageRoot()
        let ffmpeg = ''
        let ffprobe = ''
        if (fs.existsSync(root)) {
          const packageDir = fs.readdirSync(root).find((name) => name.toLowerCase().includes('ffmpeg')) || ''
          const base = packageDir ? path.join(root, packageDir) : root
          ffmpeg = findExecutable(base, 'ffmpeg.exe') || ''
          ffprobe = findExecutable(base, 'ffprobe.exe') || ''
        }
        if (ffmpeg) saveManagedFfmpeg(ffmpeg, ffprobe, 'winget')
      }
    } else if (process.platform === 'darwin') {
      r = await runCommand('brew', ['install', 'ffmpeg'], SETUP_INSTALL_TIMEOUT)
      if (r.code === -1) {
        return {
          ok: false,
          error: { code: 'E_BREW', message: '这台机器没有 brew', remedy: '先安装 Homebrew，或手动安装 FFmpeg 后把 FFMPEG_BIN 指向它' },
          status: before,
        }
      }
      const which = await runCommand('which', ['ffmpeg'], 20000)
      if (which.code === 0) {
        const ffmpeg = String(which.out || '').trim()
        const probe = await runCommand('which', ['ffprobe'], 20000)
        saveManagedFfmpeg(ffmpeg, String(probe.out || '').trim(), 'brew')
      }
    } else {
      return {
        ok: false,
        error: { code: 'E_MANUAL_INSTALL', message: 'Linux 需要 sudo 安装 FFmpeg', remedy: 'sudo apt install ffmpeg' },
        status: before,
      }
    }
    const output = (String((r && r.out) || '') + '\n' + String((r && r.err) || '')).trim().slice(-6000)
    const after = await setupStatus()
    if (!after.ffmpeg.ok) {
      return {
        ok: false,
        error: {
          code: 'E_FFMPEG_INSTALL',
          message: 'FFmpeg 安装后仍未找到',
          remedy: '重开 DSH 再检测；或把 FFMPEG_BIN 指向 ffmpeg.exe 后重试',
        },
        output,
        status: after,
      }
    }
    stopWorker()
    return { ok: true, output, status: after }
  }

  // Environment check + installs. POST goes through the same loopback+JSON guard
  // as settings writes. GET usually only probes, but it can record the interpreter
  // for "python -m video2agent" once (a CLI that is installed but not on PATH), so
  // it is not strictly read-only — no user data is changed, only the tools record.
  whenWebServer(ctx, 'setup route', (webServer) => {
    webServer.register({
      kind: 'exact',
      path: '/api/video2agent/setup',
      handler: async (req, res) => {
        try {
          if (req.method === 'GET') {
            // The page's own polling uses the short cache. A manual "重新检测"
            // appends refresh=1 (or uses POST {action:'refresh'}) to force a
            // real probe even inside the cache window.
            let forceFresh = false
            try {
              const query = new URL(req.url || '', 'http://localhost').searchParams
              forceFresh = query.get('refresh') === '1' || query.get('fresh') === '1' || query.get('cache') === '0'
            } catch {}
            return sendJson(res, 200, await setupStatus({ cache: !forceFresh }))
          }
          if (!guardWrite(req, res)) return
          const body = await readBody(req, 8 * 1024)
          let incoming = null
          try { incoming = JSON.parse(body || '{}') } catch { incoming = null }
          if (!incoming || typeof incoming !== 'object') return sendJson(res, 400, { error: 'invalid request' })
          const action = String(incoming.action || '')
          if (action === 'refresh') return sendJson(res, 200, await setupStatus())
          if (action === 'install-cli') return sendJson(res, 200, await withInstallLock('install-cli', installCli))
          if (action === 'install-ffmpeg') return sendJson(res, 200, await withInstallLock('install-ffmpeg', installFfmpeg))
          if (action === 'install-ocr') return sendJson(res, 200, await withInstallLock('install-ocr', installOcr))
          if (action === 'install-browser') return sendJson(res, 200, await withInstallLock('install-browser', installBrowser))
          if (action === 'install-all') return sendJson(res, 200, await withInstallLock('install-all', installAll))
          if (action === 'update-cli') return sendJson(res, 200, await withInstallLock('update-cli', () => installCli(true)))
          return sendJson(res, 400, { error: 'unknown action' })
        } catch (e) {
          // readBody reports an oversized body as e.status (413); keep it.
          return sendJson(res, (e && e.status) || 500, { error: 'internal error', code: 'E_ROUTE', detail: String((e && e.message) || e).slice(0, 300) })
        }
      },
    })
  })

  // Persist the small UI preference surface on the Host so the Video2Agent
  // Configure page is not tied to one browser's localStorage. This is not the
  // DSH Config namespace yet, but it survives browser/profile restarts.
  whenWebServer(ctx, 'settings route', (webServer) => {
    webServer.register({
        kind: 'exact',
        path: '/api/video2agent/settings',
        handler: async (req, res) => {
          try {
            if (req.method === 'GET') {
              const problem = uiSettingsProblem()
              if (problem) return sendJson(res, 500, problem)
              return sendJson(res, 200, readUiSettings())
            }
            if (!guardWrite(req, res)) return
            const body = await readBody(req, 16 * 1024)
            let incoming = null
            try { incoming = JSON.parse(body || '{}') } catch { incoming = null }
            if (!incoming || typeof incoming !== 'object') return sendJson(res, 400, { error: 'invalid settings' })
            // Apply the body as a patch over what is stored: a client that sends
            // only one field (e.g. the theme colour) must not silently reset the
            // others to their defaults.
            // Patch the raw file, not the merged view. Writing merged Config
            // values into ui-settings.json would freeze keys the user never
            // saved and make later Config edits invisible.
            const raw = readRawUiSettings()
            const clean = sanitizeUiSettings({ ...raw, ...incoming })
            const next = { ...raw }
            for (const key of ['enabled', 'douyinSearch', 'cacheTtlMs', 'cacheExpire', 'cacheDays', 'cacheLimitEnabled', 'cacheLimitGb', 'processLimit', 'accentColor', 'cookiesPath']) {
              if (key in incoming || key in raw) next[key] = clean[key]
            }
            writeUiSettings(next)
            return sendJson(res, 200, readMergedSettings())
          } catch (e) {
            try {
              const dir = path.join(video2agentHome(), 'logs')
              fs.mkdirSync(dir, { recursive: true })
              fs.appendFileSync(path.join(dir, 'settings-error.log'),
                new Date().toISOString() + ' ' + (e && e.stack ? e.stack : String(e)) + '\n', 'utf8')
            } catch {}
            // An oversized body carries status 413; do not flatten every failure
            // into 500.
            return sendJson(res, (e && e.status) || 500, { error: 'internal error', code: 'E_ROUTE', detail: String((e && e.message) || e).slice(0, 300) })
          }
        },
    })
  })

  // Cloud provider settings. The API key is POSTed to this loopback-only route,
  // handed to the CLI on stdin (never argv), encrypted by the CLI, and never
  // returned by a GET. The settings page only sees configured/last4.
  whenWebServer(ctx, 'cloud route', (webServer) => {
    webServer.register({
        kind: 'exact',
        path: '/api/video2agent/cloud',
        handler: async (req, res) => {
          try {
            if (req.method === 'GET') {
              const r = await runCli(['cloud', 'status', '--json'], 30000)
              let data = null
              try { data = JSON.parse(r.out || '{}') } catch { data = null }
              // `{}` is not a configuration: a missing CLI returned an empty object
              // with exit -1 and the page rendered it as 'not configured'.
              if (r.code !== 0 || !data || data.ok === false) {
                return sendJson(res, 502, { error: 'cloud status failed' })
              }
              return sendJson(res, 200, data)
            }
            if (!guardWrite(req, res)) return
            const body = await readBody(req, 8 * 1024)
            let incoming = null
            try { incoming = JSON.parse(body || '{}') } catch { incoming = null }
            if (!incoming || typeof incoming !== 'object') return sendJson(res, 400, { error: 'invalid cloud settings' })
            const action = String(incoming.action || '')
            let argv = null
            let input = null
            if (action === 'config') {
              const payload = {
                provider: String(incoming.provider || ''),
                base_url: String(incoming.base_url || ''),
                asr_model: String(incoming.asr_model || ''),
                ocr_model: String(incoming.ocr_model || ''),
                asr_enabled: incoming.asr_enabled !== false,
              }
              argv = ['cloud', 'config', '--json']
              input = JSON.stringify(payload)
            } else if (action === 'save') {
              const key = String(incoming.key || '').trim()
              if (!key) return sendJson(res, 400, { error: 'missing key' })
              argv = ['cloud', 'save', '--json']
              input = key + '\n'
            } else if (action === 'test') {
              argv = ['cloud', 'test', '--json']
            } else if (action === 'clear') {
              argv = ['cloud', 'clear', '--json']
            } else if (action === 'ocr') {
              argv = ['cloud', incoming.enabled === true ? 'ocr-on' : 'ocr-off', '--json']
            } else {
              return sendJson(res, 400, { error: 'unknown action' })
            }
            const r = await runCli(argv, action === 'test' ? 60000 : 30000, input)
            let data = null
            try { data = JSON.parse(r.out || '{}') } catch { data = null }
            if (r.code === 0 && data) return sendJson(res, 200, data)
            const error = parseStructuredError(r.out) || {
              code: 'E_CLOUD',
              message: 'cloud request failed',
              remedy: '检查服务商控制台和 Key。',
            }
            return sendJson(res, 502, { ok: false, error })
          } catch (e) {
            return sendJson(res, 500, { ok: false, error: { code: 'E_ROUTE', message: 'internal error' } })
          }
        },
    })
  })

  // Local model management. Downloads are explicit button presses; the route
  // reports the cache state, never a fake ready flag.
  whenWebServer(ctx, 'models route', (webServer) => {
    webServer.register({
        kind: 'exact',
        path: '/api/video2agent/models',
        handler: async (req, res) => {
          try {
            if (req.method === 'GET') {
              const r = await runCli(['models', 'status', '--json'], 30000)
              let data = null
              try { data = JSON.parse(r.out || '{}') } catch { data = null }
              if (r.code !== 0 || !data || data.ok === false) {
                return sendJson(res, 502, { error: 'model status failed' })
              }
              return sendJson(res, 200, data)
            }
            if (!guardWrite(req, res)) return
            const body = await readBody(req, 8 * 1024)
            let incoming = null
            try { incoming = JSON.parse(body || '{}') } catch { incoming = null }
            const action = String((incoming && incoming.action) || '')
            if (!incoming || !['select', 'download', 'uninstall', 'select-ocr'].includes(action)) return sendJson(res, 400, { error: 'invalid model action' })
            let argv
            if (action === 'select-ocr') {
              const configPath = String(incoming.ocr_config || '').trim()
              if (configPath.length > 500 || /[\u0000-\u001f]/.test(configPath)) return sendJson(res, 400, { error: 'invalid ocr config' })
              argv = ['models', 'select-ocr', '--ocr-config', configPath, '--json']
            } else {
              const model = String(incoming.model || '').trim()
              if (!model || model.length > 300 || model.startsWith('-') || /[\u0000-\u001f]/.test(model)) {
                return sendJson(res, 400, { error: 'invalid model' })
              }
              argv = ['models', action, '--model', model, '--json']
            }
            const r = await runCli(argv, (action === 'download' || action === 'select-ocr') ? 600000 : 30000)
            let data = null
            try { data = JSON.parse(r.out || '{}') } catch { data = null }
            // Model config paths are the user's own settings (custom ASR dir,
            // generated OCR YAML). Redacting them here made the client write
            // "<local>/..." back, so the next "download and use" failed. The
            // GET returns the same unredacted paths; local UI, not model input.
            if (r.code === 0 && data) return sendJson(res, 200, data)
            return sendJson(res, 502, {
              ok: false,
              error: parseStructuredError(r.out) || { code: 'E_MODEL', message: 'model request failed', remedy: '检查模型 ID/路径和网络。' },
            })
          } catch (e) {
            return sendJson(res, 500, { ok: false, error: { code: 'E_ROUTE', message: 'internal error' } })
          }
        },
    })
  })

  // A user's first failure is usually an environment one (missing ffmpeg/ASR/OCR).
  // Expose the same doctor used by the CLI so the settings page can show it without
  // asking the model to run a shell command.
  whenWebServer(ctx, 'doctor route', (webServer) => {
    webServer.register({
      kind: 'exact',
      path: '/api/video2agent/doctor',
      handler: async (req, res) => {
        try {
          if (req.method !== 'GET') return sendJson(res, 405, { error: 'method not allowed' })
          const result = await runCli(['doctor', '--json'], 30000)
          let data = null
          try { data = JSON.parse(result.out || '{}') } catch { data = null }
          if (!data || !Array.isArray(data.checks)) {
            return sendJson(res, 502, {
              ok: false,
              error: '环境检查没有返回可用的 JSON 结果',
              stderr: (result.err || '').slice(0, 800),
            })
          }
          return sendJson(res, 200, { ok: data.required_ok !== false, doctor: redactLocalPaths(data) })
        } catch (e) {
          return sendJson(res, 500, { ok: false, error: 'internal error', code: 'E_DOCTOR' })
        }
      },
    })
  })

  // Bilibili hot-links its covers: a browser request from another origin gets 403,
  // which is why the cards looked text-only. Fetch with the platform referer, cache
  // on disk, and serve from here. Only the platform CDNs are allowed (no SSRF).
  whenWebServer(ctx, 'cover proxy route', (webServer) => {
    const ALLOWED = /(^|\.)(hdslb\.com|biliimg\.com|bilivideo\.com|douyinpic\.com|douyinstatic\.com|douyin\.com|iesdouyin\.com)$/i
    webServer.register({
      kind: 'exact',
      path: '/api/video2agent/cover',
      handler: async (req, res) => {
        try {
          if (req.method !== 'GET') return sendJson(res, 405, { error: 'method not allowed' })
          const query = new URL(String(req.url || ''), 'http://localhost')
          const target = query.searchParams.get('u') || ''
          let parsed
          try { parsed = new URL(target) } catch { return sendJson(res, 400, { error: 'bad url' }) }
          if (parsed.protocol !== 'https:') return sendJson(res, 400, { error: 'https only' })
          if (!ALLOWED.test(parsed.hostname)) return sendJson(res, 403, { error: 'host not allowed' })
          const hash = crypto.createHash('sha1').update(target).digest('hex')
          const dir = path.join(video2agentHome(), 'cache', 'covers')
          const file = path.join(dir, `${hash}.img`)
          let body = null
          let type = 'image/jpeg'
          try {
            body = fs.readFileSync(file)
            type = fs.readFileSync(`${file}.type`, 'utf8').trim() || type
            const cachedType = sniffImage(body)
            if (!cachedType) { body = null; type = 'image/jpeg' } else { type = cachedType }
          } catch {}
          if (!body) {
            const fetched = await new Promise((resolve) => {
              const request = https.get(parsed, {
                headers: {
                  'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64)',
                  // Douyin signed covers reject the Bilibili referer and vice
                  // versa; send the referer of the platform the host belongs to.
                  Referer: /(^|\.)douyin(pic|static)?\.com$|(^|\.)iesdouyin\.com$/i.test(parsed.hostname)
                    ? 'https://www.douyin.com/'
                    : 'https://www.bilibili.com/',
                  Accept: 'image/*',
                },
                timeout: 8000,
              }, (response) => {
                if (response.statusCode !== 200) { response.resume(); resolve(null); return }
                const chunks = []
                let size = 0
                response.on('data', (d) => {
                  size += d.length
                  if (size > 4 * 1024 * 1024) {
                    response.destroy()
                    resolve(null)
                    return
                  }
                  chunks.push(d)
                })
                response.on('end', () => resolve({ body: Buffer.concat(chunks), type: String(response.headers['content-type'] || 'image/jpeg') }))
              })
              request.on('error', () => resolve(null))
              request.on('timeout', () => { request.destroy(); resolve(null) })
            })
            if (!fetched) return sendJson(res, 404, { error: 'cover unavailable' })
            body = fetched.body
            type = String(fetched.type || 'image/jpeg').split(';')[0]
            try {
              fs.mkdirSync(dir, { recursive: true })
              fs.writeFileSync(file, body)
              fs.writeFileSync(`${file}.type`, type, 'utf8')
            } catch {}
          }
          // Never relay a non-image type from this origin, whatever the CDN says.
          const sniffed = sniffImage(body)
          const declared = String(type || '').toLowerCase()
          const safe = sniffed || (declared.startsWith('image/') ? declared : null)
          if (!safe) return sendJson(res, 415, { error: 'not an image' })
          res.setHeader('Content-Type', safe)
          res.setHeader('X-Content-Type-Options', 'nosniff')
          res.setHeader('Cache-Control', 'public, max-age=86400')
          res.end(body)
          return true
        } catch (e) {
          return sendJson(res, (e && e.status) || 500, { error: 'internal error', code: 'E_ROUTE' })
        }
      },
    })
  })

  // Search progress is the only discovery state the composer needs. The card
  // itself is gone: the model's shortlist starts the jobs, and the selected-video
  // table is driven by that tool result. A status-only route keeps the search
  // line ("正在找视频 / AI 正在筛选") without the pending/confirm round-trip.
  whenWebServer(ctx, 'discovery status route', (webServer) => {
    webServer.register({
      kind: 'exact',
      path: '/api/video2agent/discovery/status',
      handler: (req, res) => {
        try {
          if (req.method !== 'GET') return sendJson(res, 405, { error: 'method not allowed' })
          const sid = String(new URL(req.url || '', 'http://localhost').searchParams.get('session') || '').slice(0, 128)
          let status = readDiscoveryStatus()
          // A status claimed by a session is only visible to that session. The old
          // check let a request without `session` read another chat's query.
          if (status && status.session_id && status.session_id !== sid) status = null
          if (status && !status.session_id && sid) {
            // The tool call does not know its conversation; the first one that
            // polls claims the line so another chat cannot show it.
            status = { ...status, session_id: sid }
            writeDiscoveryStatus(status)
          }
          return sendJson(res, 200, { ok: true, status })
        } catch (e) {
          return sendJson(res, (e && e.status) || 500, { error: 'internal error', code: 'E_ROUTE' })
        }
      },
    })
  })

  // Read-only snapshot for nested (run_code/PTC) shortlist calls. The client
  // polls this because no tool Card is mounted to carry the rows.
  whenWebServer(ctx, 'session queue route', (webServer) => {
    webServer.register({
      kind: 'exact',
      path: '/api/video2agent/queue',
      handler: (req, res) => {
        try {
          if (req.method !== 'GET') return sendJson(res, 405, { error: 'method not allowed' })
          const sid = String(new URL(req.url || '', 'http://localhost').searchParams.get('session') || '').slice(0, 128)
          if (!sid) return sendJson(res, 400, { error: 'missing session' })
          return sendJson(res, 200, { ok: true, queue: readSessionQueue(sid) })
        } catch (e) {
          return sendJson(res, (e && e.status) || 500, { error: 'internal error', code: 'E_ROUTE' })
        }
      },
    })
  })

  // The client hides a find-only search card when the turn ends; this removes
  // the Host side too, so a reload or the next turn cannot read the stale
  // "curating" line. A different session cannot clear this one's status.
  whenWebServer(ctx, 'discovery clear route', (webServer) => {
    webServer.register({
      kind: 'exact',
      path: '/api/video2agent/discovery/clear',
      handler: async (req, res) => {
        try {
          if (req.method !== 'POST') return sendJson(res, 405, { error: 'method not allowed' })
          if (!guardWrite(req, res)) return
          const raw = await readBody(req, 8 * 1024)
          let parsed = {}
          try { parsed = JSON.parse(raw || '{}') } catch {}
          const sid = String(parsed && parsed.session || '').slice(0, 128)
          if (!sid) return sendJson(res, 400, { error: 'missing session' })
          // The client sends the exact `at` (and `phase`) of the line it is
          // hiding. A delayed clear that arrives after a newer search was
          // written must not delete that newer line, so only an exact match may
          // clear. A request without a selector is a no-op: it must not become
          // another unconditional clear path.
          const at = Number(parsed && parsed.at)
          const phase = String(parsed && parsed.phase || '')
          if (!Number.isFinite(at) || at <= 0) return sendJson(res, 200, { ok: true, cleared: false })
          const status = readDiscoveryStatus()
          if (!status) return sendJson(res, 200, { ok: true, cleared: false })
          if (status.session_id && status.session_id !== sid) {
            return sendJson(res, 200, { ok: true, cleared: false })
          }
          if (Number(status.at || 0) !== at) return sendJson(res, 200, { ok: true, cleared: false })
          if (phase && String(status.phase || '') !== phase) return sendJson(res, 200, { ok: true, cleared: false })
          clearDiscoveryStatus()
          return sendJson(res, 200, { ok: true, cleared: true })
        } catch (e) {
          return sendJson(res, (e && e.status) || 500, { error: 'internal error', code: 'E_ROUTE' })
        }
      },
    })
  })

  whenWebServer(ctx, 'campaign route', (webServer) => {
    webServer.register({
      kind: 'exact',
      path: '/api/video2agent/campaign',
      handler: async (req, res) => {
        try {
          const id = String(new URL(req.url || '', 'http://localhost').searchParams.get('id') || '').slice(0, 80)
          if (!/^campaign_[a-f0-9]{8,32}$/.test(id)) return sendJson(res, 400, { error: 'invalid campaign id' })
          if (req.method === 'GET') {
            // Read-only: a browser prefetch or tab refresh must never start the
            // next download wave.
            const campaign = await campaigns.refresh(id)
            if (!campaign) return sendJson(res, 404, { error: 'campaign not found' })
            return sendJson(res, 200, { ok: true, ...campaigns.snapshot(campaign) })
          }
          if (req.method !== 'POST') return sendJson(res, 405, { error: 'method not allowed' })
          if (!guardWrite(req, res)) return
          const campaign = await campaigns.tick(id)
          if (!campaign) return sendJson(res, 404, { error: 'campaign not found' })
          return sendJson(res, 200, { ok: true, ...campaigns.snapshot(campaign) })
        } catch (e) {
          return sendJson(res, (e && e.status) || 500, { error: 'internal error', code: 'E_ROUTE' })
        }
      },
    })
  })

  whenWebServer(ctx, 'activity route', (webServer) => {
    webServer.register({
      kind: 'exact',
      path: '/api/video2agent/activity',
      handler: (req, res) => {
        try {
          if (req.method !== 'GET') return sendJson(res, 405, { error: 'method not allowed' })
          const sid = String(new URL(req.url || '', 'http://localhost').searchParams.get('session') || '').slice(0, 128)
          let activity = readActivity()
          // The tool call does not know its conversation, so the first client
          // that polls claims the record for its session. Other conversations
          // must not see the card. A new activity has no session_id and can be
          // claimed again.
          if (activity && !activity.session_id && sid) {
            activity = { ...activity, session_id: sid }
            atomicJson(activityPath(), activity)
          }
          if (activity && activity.session_id && activity.session_id !== sid) activity = null
          return sendJson(res, 200, { ok: true, activity })
        } catch (e) {
          return sendJson(res, (e && e.status) || 500, { error: 'internal error', code: 'E_ROUTE' })
        }
      },
    })
  })

  // Bilibili QR login. The friendly path to a session, which is what unlocks
  // CC/AI subtitles. Cookies are written by the CLI into the local jar and never
  // travel through these routes.
  whenWebServer(ctx, 'bilibili login routes', (webServer) => {
    const runAuth = async (args) => {
      const out = await runCli(args, 30000)
      let data = null
      try { data = JSON.parse(out.out) } catch { data = null }
      return { data, out }
    }
    webServer.register({
      kind: 'exact',
      path: '/api/video2agent/bili-login/status',
      handler: async (req, res) => {
        try {
          if (req.method !== 'GET') return sendJson(res, 405, { error: 'method not allowed' })
          const { data, out } = await runAuth(['biliauth', '--status', '--json'])
          if (!data) return sendJson(res, 502, { error: (out.err || 'status failed').slice(0, 400) })
          return sendJson(res, 200, data)
        } catch (e) { return sendJson(res, (e && e.status) || 500, { error: 'internal error', code: 'E_ROUTE' }) }
      },
    })
    webServer.register({
      kind: 'exact',
      path: '/api/video2agent/bili-login/start',
      handler: async (req, res) => {
        try {
          if (!guardWrite(req, res)) return
          const { data, out } = await runAuth(['biliauth', '--start', '--json'])
          if (!data || !data.qr) return sendJson(res, 502, { error: (out.err || 'QR generation failed').slice(0, 400) })
          return sendJson(res, 200, data)
        } catch (e) { return sendJson(res, (e && e.status) || 500, { error: 'internal error', code: 'E_ROUTE' }) }
      },
    })
    webServer.register({
      kind: 'exact',
      path: '/api/video2agent/bili-login/poll',
      handler: async (req, res) => {
        try {
          if (req.method !== 'GET') return sendJson(res, 405, { error: 'method not allowed' })
          const key = new URL(req.url || '', 'http://localhost').searchParams.get('key') || ''
          if (!/^[A-Za-z0-9]{8,64}$/.test(key)) return sendJson(res, 400, { error: 'invalid key' })
          const { data, out } = await runAuth(['biliauth', '--poll', key, '--json'])
          if (!data) return sendJson(res, 502, { error: (out.err || 'poll failed').slice(0, 400) })
          return sendJson(res, 200, data)
        } catch (e) { return sendJson(res, (e && e.status) || 500, { error: 'internal error', code: 'E_ROUTE' }) }
      },
    })
    webServer.register({
      kind: 'exact',
      path: '/api/video2agent/bili-login/clear',
      handler: async (req, res) => {
        try {
          if (!guardWrite(req, res)) return
          const { data, out } = await runAuth(['biliauth', '--clear', '--json'])
          if (!data) return sendJson(res, 502, { error: (out.err || 'clear failed').slice(0, 400) })
          return sendJson(res, 200, data)
        } catch (e) { return sendJson(res, (e && e.status) || 500, { error: 'internal error', code: 'E_ROUTE' }) }
      },
    })
  })

  // Douyin QR login (optional browser extra). The CLI generates the QR and waits
  // for the scan; the Host only tracks that one child and serves the QR image, so
  // the settings page can show it without blocking a three-minute HTTP request.
  whenWebServer(ctx, 'douyin login routes', (webServer) => {
    const home = () => video2agentHome()
    const cookiePath = () => path.join(home(), 'cookies', 'douyin.txt')
    const accountPath = () => path.join(home(), 'cookies', 'douyin_account.json')
    const qrPath = () => path.join(home(), 'cookies', 'douyin_qr.png')
    const loginStagePath = () => path.join(home(), 'cookies', 'douyin_login.json')
    const readStage = () => {
      try {
        const raw = JSON.parse(fs.readFileSync(loginStagePath(), 'utf8'))
        return String((raw && raw.stage) || 'waiting')
      } catch { return 'waiting' }
    }
    const readAccount = () => {
      try { return JSON.parse(fs.readFileSync(accountPath(), 'utf8')) } catch { return null }
    }
    const loginCookiePresent = () => {
      try {
        const raw = fs.readFileSync(cookiePath(), 'utf8')
        const now = Math.floor(Date.now() / 1000)
        for (let line of raw.split(/\r?\n/)) {
          if (line.startsWith('#HttpOnly_')) line = line.slice('#HttpOnly_'.length)
          else if (!line || line.startsWith('#')) continue
          const parts = line.split('\t')
          if (parts.length < 7) continue
          const name = parts[5]
          const expires = Number(parts[4]) || 0
          if ((name === 'sessionid' || name === 'sessionid_ss') && (expires <= 0 || expires > now)) return true
        }
      } catch {}
      return false
    }
    const loggedIn = () => loginCookiePresent()
    const snapshot = () => {
      const current = DOUYIN_LOGIN_STATE
      if (current && current.state === 'waiting') {
        return { ok: true, state: 'waiting', stage: readStage(), logged_in: loggedIn(), started_at: current.startedAt }
      }
      if (current && current.state === 'ready') {
        return { ok: true, state: 'ready', logged_in: loggedIn(), account: current.account || readAccount() }
      }
      if (current && current.state === 'failed') {
        return { ok: true, state: 'failed', logged_in: loggedIn(), error: current.error || '登录失败' }
      }
      return { ok: true, state: 'idle', logged_in: loggedIn(), account: loggedIn() ? readAccount() : null }
    }
    const startLogin = () => {
      if (DOUYIN_LOGIN_STATE && DOUYIN_LOGIN_STATE.state === 'waiting') return
      const qr = qrPath()
      const cookie = cookiePath()
      const stageFile = loginStagePath()
      try {
        fs.mkdirSync(path.dirname(qr), { recursive: true })
        fs.rmSync(qr, { force: true })
        fs.rmSync(cookie, { force: true })
        fs.rmSync(stageFile, { force: true })
      } catch {}
      const invocation = cliCommand()
      // The CLI drives a real Chrome window placed off-screen: headless sessions
      // showed the QR but never received the login cookies after a real scan. A
      // visible window still opens only if Douyin asks for a slider verification.
      const args = [...invocation.prefix, 'douyin', 'login', '--timeout', '180',
        '--qr-out', qr, '--status-out', stageFile, '--json']
      let child
      try {
        child = spawn(invocation.command, args, { windowsHide: true, env: managedToolEnv() })
      } catch (e) {
        DOUYIN_LOGIN_STATE = { state: 'failed', error: String((e && e.message) || e), startedAt: Date.now() }
        return
      }
      const entry = { state: 'waiting', startedAt: Date.now(), child, out: '', err: '', account: null }
      DOUYIN_LOGIN_STATE = entry
      try { child.stdin.end() } catch {}
      child.stdout.setEncoding('utf8')
      child.stderr.setEncoding('utf8')
      child.stdout.on('data', (d) => { entry.out = appendCapture(entry.out, d) })
      child.stderr.on('data', (d) => { entry.err = appendCapture(entry.err, d) })
      const fail = (message) => {
        if (entry.state !== 'waiting') return
        entry.state = 'failed'
        entry.error = String(message || '登录失败').slice(0, 400)
      }
      child.on('error', (e) => fail((e && e.message) || '无法启动抖音登录'))
      child.on('close', (code) => {
        if (entry.state !== 'waiting') return
        let data = null
        try { data = JSON.parse((entry.out || '').trim() || '{}') } catch { data = null }
        if (data && data.ok === true) {
          entry.state = 'ready'
          entry.account = data.account || null
          try { if (entry.account) fs.writeFileSync(accountPath(), JSON.stringify(entry.account), 'utf8') } catch {}
        } else {
          const message = (data && data.error && (data.error.message || data.error.remedy)) || entry.err.trim() || ('exit code ' + code)
          fail(message)
        }
      })
      const timer = setTimeout(() => {
        try { killTree(child) } catch {}
        fail('登录超时，请重新扫码')
      }, 200000)
      child.on('close', () => clearTimeout(timer))
    }
    webServer.register({
      kind: 'exact',
      path: '/api/video2agent/douyin-login/status',
      handler: async (req, res) => {
        try {
          if (req.method !== 'GET') return sendJson(res, 405, { error: 'method not allowed' })
          return sendJson(res, 200, snapshot())
        } catch (e) { return sendJson(res, (e && e.status) || 500, { error: 'internal error', code: 'E_ROUTE' }) }
      },
    })
    webServer.register({
      kind: 'exact',
      path: '/api/video2agent/douyin-login/start',
      handler: async (req, res) => {
        try {
          if (!guardWrite(req, res)) return
          startLogin()
          return sendJson(res, 200, snapshot())
        } catch (e) { return sendJson(res, (e && e.status) || 500, { error: 'internal error', code: 'E_ROUTE' }) }
      },
    })
    webServer.register({
      kind: 'exact',
      path: '/api/video2agent/douyin-login/clear',
      handler: async (req, res) => {
        try {
          if (!guardWrite(req, res)) return
          const current = DOUYIN_LOGIN_STATE
          if (current && current.child) { try { killTree(current.child) } catch {} }
          DOUYIN_LOGIN_STATE = null
          try {
            fs.rmSync(cookiePath(), { force: true })
            fs.rmSync(accountPath(), { force: true })
            fs.rmSync(qrPath(), { force: true })
            fs.rmSync(loginStagePath(), { force: true })
          } catch {}
          return sendJson(res, 200, { ok: true, state: 'idle', logged_in: false })
        } catch (e) { return sendJson(res, (e && e.status) || 500, { error: 'internal error', code: 'E_ROUTE' }) }
      },
    })
  })

  // Cancel is a request to the worker, not a UI hide. The worker checks this
  // marker between stages and writes a terminal canceled state.
  whenWebServer(ctx, 'cancel route', (webServer) => {
    webServer.register({
        kind: 'exact',
        path: '/api/video2agent/jobs/cancel',
        handler: async (req, res) => {
          try {
            if (!guardWrite(req, res)) return
            const body = await readBody(req, 8 * 1024)
            let incoming = null
            try { incoming = JSON.parse(body || '{}') } catch { incoming = null }
            const jobId = incoming && String(incoming.job_id || '')
            if (!jobId || !/^[A-Za-z0-9_-]{3,64}$/.test(jobId)) return sendJson(res, 400, { error: 'invalid job_id' })
            // Do not let an arbitrary id create a marker in the live/cancel
            // directory. The sidecar is the Host's normal job view; when it is
            // missing or older than the 15s mirror window, ask the CLI before
            // saying 404 (a long download/ffmpeg stage writes no progress).
            let job = readJobSidecar(jobId)
            if (!job) {
              const out = await runCli(['jobs', '--id', jobId, '--json'], 20000)
              let parsed = null
              try { parsed = JSON.parse(out.out) } catch { parsed = null }
              job = jobFromCliPayload(parsed)
              if (!job) return sendJson(res, 404, { error: 'job not found' })
            }
            if (['ready', 'failed', 'canceled', 'cancelled'].includes(String(job.state || ''))) {
              return sendJson(res, 409, { error: 'job already finished', state: job.state })
            }
            const dir = path.join(video2agentHome(), 'jobs')
            fs.mkdirSync(dir, { recursive: true })
            fs.writeFileSync(path.join(dir, jobId + '.cancel'), String(Date.now()), 'utf8')
            return sendJson(res, 200, { ok: true, job_id: jobId, cancel_requested: true, state: job.state || 'unknown' })
          } catch (e) {
            return sendJson(res, (e && e.status) || 500, { error: 'internal error', code: 'E_ROUTE' })
          }
        },
    })
  })

  // Retry a failed ingest without asking the model to reconstruct the source
  // and options. The source comes from the stored job, never from the client.
  whenWebServer(ctx, 'retry route', (webServer) => {
    webServer.register({
        kind: 'exact',
        path: '/api/video2agent/retry',
        handler: async (req, res) => {
          try {
            if (!guardWrite(req, res)) return
            const body = await readBody(req, 8 * 1024)
            let incoming = null
            try { incoming = JSON.parse(body || '{}') } catch { incoming = null }
            const jobId = incoming && String(incoming.job_id || '')
            const videoId = incoming && String(incoming.video_id || '')
            const incomingSource = incoming && String(incoming.source || '')
            const validVideo = /^BV[0-9A-Za-z]{10}$/
            const validSource = /^https:\/\/www\.bilibili\.com\/video\/BV[0-9A-Za-z]{10}\/?$/
            // A failed Douyin start has no job id and no BV id; its row carries the
            // platform URL, which the CLI can ingest again. Any http(s) source is
            // therefore retryable — the CLI validates the platform itself.
            const validUrl = /^https?:\/\/[^\s]+$/i
            if (jobId && !/^[A-Za-z0-9_-]{3,64}$/.test(jobId)) return sendJson(res, 400, { error: 'invalid job_id' })
            if (!jobId && !validVideo.test(videoId) && !validSource.test(incomingSource)
                && !validUrl.test(incomingSource)) {
              return sendJson(res, 400, { error: 'invalid video_id or source' })
            }
            let job = null
            if (jobId) {
              const found = await runCli(['jobs', '--id', jobId, '--json'], 20000)
              try { job = JSON.parse(found.out).job || JSON.parse(found.out) } catch { job = null }
              if (!job || !job.source) return sendJson(res, 404, { error: 'job not found' })
              if (job.state !== 'failed') return sendJson(res, 409, { error: 'job is not failed' })
            }
            // A failed start has no job id; the row carries the video id/source it
            // was created from, so the user can restart just that video.
            const source = job
              ? String(job.source)
              : (validVideo.test(videoId) ? 'https://www.bilibili.com/video/' + videoId : incomingSource)
            // A retry is the user's explicit action on a failed job, so it may re-run
            // without asking again — still with a token, never a bare flag. The
            // issue+spawn section shares the shortlist lock because both write the
            // single confirm.json the CLI consumes.
            const out = await withConfirmTokenLock(async () => {
              const retryToken = issueConfirmToken([source])
              const args = ['ingest', source, '--confirm-token', retryToken]
              const retryCookies = persistedCookiesPath()
              if (retryCookies) args.push('--cookies', retryCookies)
              args.push('--detach', '--force', '--json')
              return runCli(args, 30000)
            })
            let created = null
            try { created = JSON.parse(out.out) } catch { created = null }
            if (!created || !created.job_id) return sendJson(res, 502, { error: (out.err || 'retry failed').slice(0, 1000) })
            return sendJson(res, 200, { ok: true, job_id: created.job_id, state: created.state || 'running' })
          } catch (e) {
            return sendJson(res, (e && e.status) || 500, { error: 'internal error', code: 'E_ROUTE' })
          }
        },
    })
  })

  // Live job progress for the in-chat card. Without this the card can only
  // show the snapshot returned by the tool call, and the old floating HUD had
  // to fake liveness in a fixed corner. One card, in place, updated by polling.
  const OVERVIEW_CACHE = new Map()

  function video2agentHome() {
    return String(process.env.VIDEO2AGENT_HOME || path.join(os.homedir(), '.video2agent'))
  }

  // A one-shot token is the only thing the CLI accepts as "the user picked this".
  // `--confirm` was a boolean, so any caller (including a shell command) could add
  // it and skip the card; this file is written only by the route handling the click.
  function issueConfirmToken(videoIds) {
    const dir = path.join(video2agentHome(), 'discovery')
    fs.mkdirSync(dir, { recursive: true })
    const token = crypto.randomBytes(12).toString('hex')
    fs.writeFileSync(
      path.join(dir, 'confirm.json'),
      JSON.stringify({
        token,
        video_ids: videoIds.map((v) => String(v)),
        expires_ms: Date.now() + 120000,
      }),
      'utf8',
    )
    return token
  }

  function settingsPath() {
    return path.join(video2agentHome(), 'ui-settings.json')
  }

  // The only discovery state left is the search line and the last candidate
  // union. The shortlist starts jobs directly, so there is no pending card,
  // per-session snapshot, interrupt marker, or started handshake to keep.
  function discoveryPaths() {
    const dir = path.join(video2agentHome(), 'discovery')
    return {
      dir,
      status: path.join(dir, 'status.json'),
      last: path.join(dir, 'last.json'),
    }
  }

  // Candidate offers are per conversation: one session's find must never make
  // its candidates shortlistable from another session.
  function discoveryLastPath(sessionId) {
    const key = crypto.createHash('sha256').update(String(sessionId || 'anon')).digest('hex').slice(0, 16)
    return path.join(video2agentHome(), 'discovery', 'last-' + key + '.json')
  }

  function atomicJson(file, payload) {
    let tmp = ''
    try {
      fs.mkdirSync(path.dirname(file), { recursive: true })
      tmp = file + '.tmp-' + process.pid + '-' + crypto.randomBytes(3).toString('hex')
      fs.writeFileSync(tmp, JSON.stringify(payload), 'utf8')
      fs.renameSync(tmp, file)
    } catch {
      // Windows overlay/AV can refuse the replace-rename while another handle is
      // open. Never lose the write silently: fall back to a direct write and
      // clean the temp file.
      try { fs.writeFileSync(file, JSON.stringify(payload), 'utf8') } catch {}
      if (tmp) { try { fs.rmSync(tmp, { force: true }) } catch {} }
    }
  }

  // The model is forced through run_code in PTC sessions, so its shortlist
  // result never mounts a Card. Persist the Host-started batch per conversation
  // and let the dock poll it; this is the bridge that makes nested calls visible.
  function sessionQueuePath(sessionId) {
    const key = crypto.createHash('sha256').update(String(sessionId)).digest('hex').slice(0, 32)
    return path.join(video2agentHome(), 'ui-queue', key + '.json')
  }

  function writeSessionQueue(sessionId, payload) {
    if (!sessionId || !payload) return
    const jobs = [
      ...(Array.isArray(payload.jobs) ? payload.jobs : []),
      ...(Array.isArray(payload.queued) ? payload.queued : []),
      ...(Array.isArray(payload.failed) ? payload.failed : []),
    ].filter((job) => job && (job.job_id || job.video_id)).map((job) => ({
      ...job,
      origin: 'shortlist',
      state: job.state || (job.job_id ? 'running' : 'queued'),
    }))
    if (!jobs.length) return
    atomicJson(sessionQueuePath(sessionId), {
      session_id: sessionId,
      batch_id: payload.batch_id,
      campaign_id: payload.campaign_id,
      started_at: Number(payload.started_at) || Date.now(),
      updated_at: Date.now(),
      jobs,
    })
  }

  function readSessionQueue(sessionId) {
    if (!sessionId) return null
    try {
      const parsed = JSON.parse(fs.readFileSync(sessionQueuePath(sessionId), 'utf8'))
      if (!parsed || parsed.session_id !== sessionId || !Array.isArray(parsed.jobs)) return null
      // The snapshot is written once, when the batch starts. Without a refresh a
      // finished batch still said "正在处理" when the conversation was reopened,
      // and a queued row never became ready. Each row is reconciled against its
      // own job mirror; an unreadable mirror leaves the row exactly as stored.
      try {
        parsed.jobs = parsed.jobs.map((row) => {
          if (!row || !row.job_id) return row
          const job = readJobSidecar(String(row.job_id))
          // `done` is a stage, not a state, but a legacy/external mirror can say
          // it; leaving it as-is made a finished row read as still working.
          const rawState = job && job.state ? String(job.state) : ''
          const state = rawState === 'done' ? 'ready' : rawState
          if (!state || state === row.state) return row
          return {
            ...row,
            state,
            stage: job.stage || row.stage,
            progress: job.progress == null ? row.progress : job.progress,
            error_code: job.error_code || row.error_code,
          }
        })
      } catch {}
      return parsed
    } catch {
      return null
    }
  }

  function writeDiscoveryStatus(payload, sessionId = '') {
    // `at` is the moment the search reached this phase, not the moment the line
    // was last persisted. Polling a status claims the line and used to re-stamp
    // `at`, which silently restarted the client's age budget for that line.
    const record = { ...payload, at: Number(payload && payload.at) || Date.now() }
    if (sessionId) record.session_id = sessionId
    atomicJson(discoveryPaths().status, record)
  }

  function readDiscoveryStatus() {
    try {
      const parsed = JSON.parse(fs.readFileSync(discoveryPaths().status, 'utf8'))
      if (!parsed || !parsed.phase) return null
      // Search status is turn-scoped. Never let a stale spinner or an old
      // no-result/error line outlive a restart or reappear in a later turn.
      if (Date.now() - Number(parsed.at || 0) > 2 * 60 * 1000) return null
      return parsed
    } catch {
      return null
    }
  }

  function clearDiscoveryStatus() {
    try { fs.rmSync(discoveryPaths().status, { force: true }) } catch {}
  }

  function writeDiscoveryLast(payload, sessionId = '') {
    // Keep the union of this turn's searches, not only the last query. The model
    // sometimes refines the query after seeing noise; a candidate from the first
    // search is still legitimately offered, and shortlisting it should not fail.
    let previous = []
    try {
      const old = JSON.parse(fs.readFileSync(discoveryLastPath(sessionId), 'utf8'))
      if (old && Date.now() - Number(old.at || 0) < 5 * 60 * 1000 && Array.isArray(old.candidates)) {
        previous = old.candidates
      }
    } catch {}
    const seen = new Set()
    const merged = []
    for (const candidate of [...(payload.candidates || []), ...previous]) {
      const videoId = String(candidate.video_id || '')
      if (!videoId || seen.has(videoId)) continue
      seen.add(videoId)
      merged.push(candidate)
      // Keep the full union the shortlist schema accepts; 40 silently hid the
      // tail of a 50-candidate discover and made valid ids E_SHORTLIST_UNKNOWN.
      if (merged.length >= 100) break
    }
    atomicJson(discoveryLastPath(sessionId), { ...payload, candidates: merged, at: Date.now(), session_id: sessionId || null })
  }

  function readDiscoveryLast(sessionId = '') {
    try {
      const parsed = JSON.parse(fs.readFileSync(discoveryLastPath(sessionId), 'utf8'))
      if (!parsed || !Array.isArray(parsed.candidates)) return null
      if (Date.now() - Number(parsed.at || 0) > 10 * 60 * 1000) return null
      return parsed
    } catch {
      return null
    }
  }

  // One generic activity record for the few long actions that are not
  // ingest jobs (OCR, export, account writes). The card only needs the
  // status; no counts, no error reason, no stage.
  function activityPath() {
    return path.join(video2agentHome(), 'activity', 'last.json')
  }

  function beginActivity(kind, title, sessionId = '') {
    const record = {
      id: 'act_' + Date.now().toString(36) + '_' + crypto.randomBytes(3).toString('hex'),
      kind,
      title: String(title || ''),
      state: 'running',
      at: Date.now(),
    }
    if (sessionId) record.session_id = sessionId
    atomicJson(activityPath(), record)
    return record
  }

  function finishActivity(record, state) {
    if (!record) return
    atomicJson(activityPath(), { ...record, state, finished_at: Date.now() })
  }

  function readActivity() {
    try {
      const parsed = JSON.parse(fs.readFileSync(activityPath(), 'utf8'))
      if (!parsed || !parsed.kind) return null
      const at = Number(parsed.finished_at || parsed.at || 0)
      if (Date.now() - at > 30 * 1000) return null
      return parsed
    } catch {
      return null
    }
  }

  // Read the job mirror the worker keeps up to date. Returns null when it is
  // absent or unreadable so the caller falls back to the CLI.
  function readJobSidecar(jobId) {
    try {
      const target = path.join(video2agentHome(), 'jobs', `${jobId}.json`)
      const stat = fs.statSync(target)
      const parsed = JSON.parse(fs.readFileSync(target, 'utf8'))
      const job = parsed && parsed.ok ? parsed.job : null
      if (!job || !job.id) return null
      // A live worker writes progress every stage (measured ~1 write/second), so a
      // mirror older than 15s means the worker died without a final write. Falling
      // back to the CLI reconciles the row (E_WORKER_LOST) and rewrites this mirror,
      // so the card stops showing "running" within seconds instead of two minutes.
      // A terminal mirror is durable despite age: treating an old `ready` as missing
      // stalled campaigns forever (wave 2 never started).
      const state = String(job.state || '')
      // Terminal mirrors are durable despite age. A queued job waits in the CLI's
      // global ingest queue (up to 1800s) without writing, so a 5-minute window
      // marked those rows "worker lost" while their worker was still waiting.
      const staleAfterMs = ['ready', 'failed', 'canceled', 'cancelled', 'done'].includes(state)
        ? Infinity
        // The CLI may hold a job queued for up to 1800s; give it slack but keep
        // a bound, or a worker killed while queued would be trusted forever.
        : state === 'queued' ? 40 * 60 * 1000 : 15_000
      if (Date.now() - stat.mtimeMs > staleAfterMs) return null
      return job
    } catch {
      return null
    }
  }

  // Shape of a timed-out wait. The CLI answers E_TIMEOUT without the row, so this
  // used to hardcode state:'running' — a job that was only queued behind the single
  // ingest slot looked like it was making progress (real turn 2026-11-15: three
  // polls before the download failure surfaced). The worker mirror knows better.
  function timeoutPayload(jobId, waitedMs) {
    const id = String(jobId || '')
    const mirror = readJobSidecar(id) || {}
    const state = String(mirror.state || 'running')
    const waited = Math.round(Number(waitedMs) || 0)
    const payload = {
      ok: true,
      job_id: id,
      state,
      still_running: true,
      waited_ms: waited,
    }
    if (mirror.stage) payload.stage = String(mirror.stage)
    if (mirror.message) payload.message = String(mirror.message)
    if (Number.isFinite(Number(mirror.progress))) payload.progress = Number(mirror.progress)
    payload.note = state === 'queued' || mirror.stage === 'queued'
      ? '排队中：一次只运行一个入库任务，这个任务还没开始。不要反复轮询；先处理主视频，需要它时再用一次 wait_ms。'
      : '仍在处理。不要循环等待：只有结论必须依赖这个任务时再等一次（≤90s），否则先读已经完成的视频。'
    return payload
  }

  function readRawUiSettings() {
    try {
      const parsed = JSON.parse(fs.readFileSync(settingsPath(), 'utf8'))
      return parsed && typeof parsed === 'object' && !Array.isArray(parsed) ? parsed : {}
    } catch {
      return {}
    }
  }

  function readUiSettings() {
    return readMergedSettings()
  }

  // A missing file is fine (defaults); an existing-but-unparseable one is not:
  // answering 200 with defaults made the page render them as saved values.
  // null = usable (or missing → defaults). Otherwise the exact reason, so a
  // permission error is not reported as "not valid JSON" with advice to delete it.
  function uiSettingsProblem() {
    let raw
    try {
      raw = fs.readFileSync(settingsPath(), 'utf8')
    } catch (e) {
      if (e && e.code === 'ENOENT') return null
      const code = String((e && e.code) || 'EIO')
      return {
        code: 'E_SETTINGS_IO',
        error: 'ui-settings.json could not be read (' + code + ')',
        remedy: 'Check permissions or lockers for ' + settingsPath() + '; defaults are hidden until it is readable.',
      }
    }
    try {
      const parsed = JSON.parse(raw)
      if (parsed && typeof parsed === 'object' && !Array.isArray(parsed)) return null
    } catch {
      return {
        code: 'E_SETTINGS_CORRUPT',
        error: 'ui-settings.json is not valid JSON',
        remedy: 'Fix or delete ' + settingsPath() + '; the page will otherwise show defaults as saved.',
      }
    }
    return {
      code: 'E_SETTINGS_CORRUPT',
      error: 'ui-settings.json is not a settings object',
      remedy: 'Fix or delete ' + settingsPath() + '; the page will otherwise show defaults as saved.',
    }
  }
  function uiSettingsCorrupt() { return uiSettingsProblem() !== null }

  function writeUiSettings(settings) {
    const target = settingsPath()
    const text = JSON.stringify(settings, null, 2) + '\n'
    fs.mkdirSync(path.dirname(target), { recursive: true })
    const tmp = target + '.tmp-' + process.pid
    try {
      fs.writeFileSync(tmp, text, 'utf8')
      fs.renameSync(tmp, target)
    } catch (e) {
      // Some Windows overlays/antivirus reject replace-rename over an existing
      // file. Falling back to a direct write keeps the settings page usable;
      // the temp file is only removed after the direct write succeeds.
      fs.writeFileSync(target, text, 'utf8')
      try { fs.unlinkSync(tmp) } catch {}
    }
  }

  // Writes must be a JSON POST from the same origin. A page on another origin can
  // send `text/plain` "simple" requests that skip CORS preflight; requiring JSON
  // (and a matching Origin when the browser sends one) closes that door without a
  // token, which the route layer does not provide.
  function sniffImage(buffer) {
  if (!buffer || buffer.length < 12) return null
  const b = buffer
  if (b[0] === 0xff && b[1] === 0xd8 && b[2] === 0xff) return 'image/jpeg'
  if (b[0] === 0x89 && b[1] === 0x50 && b[2] === 0x4e && b[3] === 0x47) return 'image/png'
  if (b.slice(0, 4).toString('ascii') === 'GIF8') return 'image/gif'
  if (b.slice(0, 4).toString('ascii') === 'RIFF' && b.slice(8, 12).toString('ascii') === 'WEBP') return 'image/webp'
  return null
}

function guardWrite(req, res) {
    if (req.method !== 'POST') {
      sendJson(res, 405, { error: 'method not allowed' })
      return false
    }
    const type = String((req.headers && req.headers['content-type']) || '').toLowerCase()
    if (!type.startsWith('application/json')) {
      sendJson(res, 415, { error: 'content-type must be application/json' })
      return false
    }
    const origin = req.headers && req.headers.origin
    const hostHeader = String((req.headers && req.headers.host) || '')
    const hostLoopbackForNoOrigin = /^(127\.0\.0\.1|localhost|\[::1\])(:\d+)?$/i.test(hostHeader)
    // The desktop shell can present a custom-scheme page whose fetch has a
    // null/missing Origin and a cross-site Sec-Fetch-Site. The request is still
    // a JSON write to a loopback Host; a web page cannot send this combination
    // without a CORS preflight, so allow it for this local app.
    const desktopOrigin = /^(dsh-app|file):\/\//i.test(String(origin || ''))
    if ((!origin || String(origin) === 'null' || desktopOrigin) && hostLoopbackForNoOrigin) {
      // The DSH desktop shell can load the page from a custom scheme; its
      // same-origin fetch then carries the literal Origin: null. A loopback
      // Host plus JSON Content-Type is still a local write; do not make every
      // settings save fail in that shell.
      return true
    } else if (!origin) {
      sendJson(res, 403, { error: 'missing origin' })
      return false
    }
    {
      // Same-origin writes carry Origin on a POST. Accept only a loopback host (a
      // DNS-rebinding page can make Origin === Host, so matching Host is not
      // enough), or an exact match against the advertised origin.
      let allowed = false
      try {
        const parsed = new URL(origin)
        const host = String((req.headers && req.headers.host) || '')
        const loopback = /^(127\.0\.0\.1|localhost|\[::1\])(:\d+)?$/i.test(parsed.host)
        // No Host header means there is nothing to compare with: refuse instead of
        // accepting any loopback origin. The DSH desktop shell can load the page
        // from `localhost` while the request Host is `127.0.0.1` (or vice versa),
        // so both must be loopback, but they need not be byte-identical.
        const hostLoopback = /^(127\.0\.0\.1|localhost|\[::1\])(:\d+)?$/i.test(host)
        allowed = Boolean(host) && loopback && hostLoopback
        if (!allowed) {
          const expected = ACTIVE_WEB_SERVER && typeof ACTIVE_WEB_SERVER.getOrigin === 'function'
            ? String(ACTIVE_WEB_SERVER.getOrigin())
            : ''
          allowed = Boolean(expected) && origin === expected
        }
      } catch {
        allowed = false
      }
      if (!allowed) {
        sendJson(res, 403, { error: 'cross-origin write rejected' })
        return false
      }
    }
    return true
  }

  function readBody(req, limit) {
    return new Promise((resolve, reject) => {
      let size = 0
      let settled = false
      const chunks = []
      const fail = (error) => {
        if (settled) return
        settled = true
        reject(error)
      }
      const done = (value) => {
        if (settled) return
        settled = true
        resolve(value)
      }
      req.on('data', (chunk) => {
        if (settled) return
        size += chunk.length
        if (size > limit) {
          const tooLarge = new Error('request too large')
          tooLarge.code = 'E_TOO_LARGE'
          tooLarge.status = 413
          // Let the route's catch answer 413 first; destroying the socket here
          // turned the response into ECONNRESET and the 413 never reached the
          // client. Drain the rest instead of aborting.
          fail(tooLarge)
          // Drain instead of destroying (the mock request in the harness has no
          // resume); destroying turned the 413 into ECONNRESET.
          if (typeof req.resume === 'function') req.resume()
          return
        }
        chunks.push(chunk)
      })
      req.on('end', () => done(Buffer.concat(chunks).toString('utf8')))
      req.on('error', fail)
      // A client abort mid-body used to leave this promise pending forever;
      // the route and socket stayed open and never returned 400/413.
      req.on('aborted', () => fail(new Error('request aborted')))
      req.on('close', () => {
        if (!settled && !req.complete) fail(new Error('request aborted'))
      })
    })
  }

  async function overviewFor(videoId, ttlMs) {
    const hit = OVERVIEW_CACHE.get(videoId)
    if (hit && Date.now() - hit.at < ttlMs) return hit.data
    const out = await runCli(['overview', String(videoId), '--json'], 20000)
    let data = null
    try { data = JSON.parse(out.out) } catch { data = null }
    if (data && data.ok) {
      if (OVERVIEW_CACHE.size > 40) OVERVIEW_CACHE.delete(OVERVIEW_CACHE.keys().next().value)
      OVERVIEW_CACHE.set(videoId, { at: Date.now(), data })
      return data
    }
    return hit ? hit.data : null
  }

  whenWebServer(ctx, 'job/frame routes', (webServer) => {
      webServer.register({
        kind: 'exact',
        path: '/api/video2agent/job',
        handler: async (req, res) => {
          try {
            const query = new URL(req.url || '', 'http://localhost').searchParams
            const id = query.get('id') || ''
            // The batch table already has title/cover/uploader/duration from the
            // shortlist rows; asking the CLI for an overview on every 2s poll was
            // ~1.7 Python processes/second for ten rows. The live card still asks.
            const wantOverview = query.get('overview') !== '0'
            if (!/^[A-Za-z0-9_-]{3,64}$/.test(id)) return sendJson(res, 400, { error: 'invalid job id' })
            // The worker mirrors every progress update into jobs/<id>.json. Reading
            // that file costs ~1ms; asking the CLI costs a 0.5s Python start per
            // poll, and the card polls once a second for the life of a job. The
            // database stays authoritative, so a missing mirror falls back to the
            // CLI rather than showing stale numbers.
            let job = readJobSidecar(id)
            const source = job ? 'sidecar' : 'cli'
            if (!job) {
              const out = await runCli(['jobs', '--id', id, '--json'], 20000)
              let parsed = null
              try { parsed = JSON.parse(out.out) } catch { parsed = null }
              job = jobFromCliPayload(parsed)
              if (!job) return sendJson(res, 404, { error: (out.err || 'job not found').slice(0, 400) })
            }
            let overview = null
            if (wantOverview && job.video_id) {
              overview = await overviewFor(job.video_id, job.state === 'running' ? 30000 : 60000)
            }
            sendJson(res, 200, { ok: true, job, overview, source })
          } catch (e) {
            sendJson(res, 500, { error: 'internal error', code: 'E_ROUTE' })
          }
        },
      })

      // Evidence frames are local files; the browser cannot read them directly.
      // Serve only JPEG/PNG/WebP files under $VIDEO2AGENT_HOME/derived.
      webServer.register({
        kind: 'exact',
        path: '/api/video2agent/frame',
        handler: (req, res) => {
          try {
            const params = new URL(req.url || '', 'http://localhost').searchParams
            // VIDEO2AGENT_HOME may itself be a junction (the live desktop points
            // .video2agent at .vidproof). Resolve the derived root before any
            // containment check; otherwise a real frame resolves to .vidproof/...
            // and is rejected as "outside" the unresolved .video2agent/... prefix.
            let derived = path.resolve(video2agentHome(), 'derived')
            try { derived = fs.realpathSync(derived) } catch {}
            // Preferred: an opaque `id=<video_id>/<file>`. The URL never carries an
            // absolute path, so a frame link cannot leak the user's disk layout.
            // `path=` stays for links created before this change.
            const frameId = params.get('id') || ''
            let candidate = ''
            if (frameId) {
              const match = /^([A-Za-z0-9_-]{1,64})\/([A-Za-z0-9_.-]{1,80})$/.exec(frameId)
              if (!match || match[2].includes('..')) return sendJson(res, 400, { error: 'invalid frame id' })
              candidate = path.join(derived, match[1], 'frames', match[2])
            } else {
              const raw = params.get('path') || ''
              if (!raw) return sendJson(res, 400, { error: 'missing frame id' })
              // A UNC/device path would make realpathSync contact SMB/NTLM BEFORE
              // the containment check. Refuse those shapes and validate the
              // resolved path against the derived dir first.
              if (/^[\\\\/]{2}/.test(raw) || /^[A-Za-z]:$/.test(raw)) {
                return sendJson(res, 403, { error: 'invalid path' })
              }
              // Do not compare the unresolved candidate with the resolved root:
              // path= links created before the opaque id also point through the
              // .video2agent junction. Resolve first, then check containment.
              candidate = path.resolve(raw)
            }
            let real = ''
            try { real = fs.realpathSync(candidate) } catch { return sendJson(res, 404, { error: 'not found' }) }
            const prefix = (derived + path.sep).toLowerCase()
            if (!real.toLowerCase().startsWith(prefix)) return sendJson(res, 403, { error: 'outside video2agent derived dir' })
            if (!/\.(jpe?g|png|webp)$/i.test(real)) return sendJson(res, 403, { error: 'unsupported file type' })
            const type = /\.png$/i.test(real) ? 'image/png' : /\.webp$/i.test(real) ? 'image/webp' : 'image/jpeg'
            const stat = fs.statSync(real)
            // A directory named x.jpg used to send 200 headers and then crash the
            // host with EISDIR; a vanished file must not take the process down.
            if (!stat.isFile()) return sendJson(res, 404, { error: 'not a file' })
            res.statusCode = 200
            res.setHeader('Content-Type', type)
            res.setHeader('Content-Length', String(stat.size))
            res.setHeader('Cache-Control', 'private, max-age=3600')
            const stream = fs.createReadStream(real)
            stream.on('error', () => { try { res.destroy() } catch {} })
            stream.pipe(res)
          } catch (e) {
            sendJson(res, 500, { error: 'internal error', code: 'E_ROUTE' })
          }
        },
      })
  })

  const tools = (() => { try { return ctx.get?.('tools') || ctx.tools } catch { return ctx.tools } })()
  if (!tools?.register) {
    ctx.logger?.info?.('[dsh-video2agent] tools service missing; tool not registered')
    return
  }

  // Store frame files as DSH attachments and return their refs. Without the optional
  // attachments service (headless/TUI compositions) this is a no-op and the tool
  // degrades to text + paths, which is exactly the old behaviour.
  // Return [{path, ref}] so a skipped frame and a stored attachment never get
  // misaligned; null means the attachments service is unavailable, and the
  // caller then keeps opaque frame URLs instead of dropping the images.
  async function storeImages(paths) {
    const attachments = typeof ctx.get === 'function' ? ctx.get('attachments') : undefined
    if (!attachments || typeof attachments.saveImages !== 'function') return null
    const inputs = []
    for (const file of paths) {
      try {
        const data = fs.readFileSync(file)
        const ext = path.extname(file).toLowerCase()
        const mediaType = ext === '.png' ? 'image/png' : ext === '.webp' ? 'image/webp' : ext === '.gif' ? 'image/gif' : 'image/jpeg'
        inputs.push({ path: file, data: new Uint8Array(data), mediaType, name: path.basename(file) })
      } catch {
        // a frame that vanished is skipped, not fatal
      }
    }
    if (!inputs.length) return null
    // Store one frame per call: saveImages answers positionally, so a short
    // list would pair frame 2's picture with frame 1's URL (and a batch that
    // partially fails would leave unattributed attachments behind).
    const stored = []
    for (const input of inputs) {
      try {
        const refs = await attachments.saveImages([{ data: input.data, mediaType: input.mediaType, name: input.name }])
        if (!Array.isArray(refs) || refs.length !== 1) continue
        stored.push({ path: input.path, ref: refs[0], index: input.path ? paths.indexOf(input.path) : -1 })
      } catch {
        // one unreadable frame must not drop the others
      }
    }
    if (!stored.length) return null
    return stored.filter((p) => p.path && p.index >= 0)
  }

  // A retried shortlist call must not start the same batch twice. The key is the
  // ordered video list; a 2-minute window covers a model retry after a timeout.
  const SHORTLIST_STARTS = new Map()
  // campaign start idempotency: a retried ingest campaign:true reuses the id.
  const CAMPAIGN_STARTS = new Map()
  const SHORTLIST_START_TTL_MS = 120_000
  const SHORTLIST_STARTS_MAX = 200
  function pruneShortlistStarts() {
    const now = Date.now()
    for (const [key, value] of SHORTLIST_STARTS) {
      if (!value || now - Number(value.at || 0) > SHORTLIST_START_TTL_MS) SHORTLIST_STARTS.delete(key)
    }
    // A long-lived host must not retain every batch's job rows forever.
    while (SHORTLIST_STARTS.size > SHORTLIST_STARTS_MAX) {
      SHORTLIST_STARTS.delete(SHORTLIST_STARTS.keys().next().value)
    }
  }
  // The CLI token file is a single path (discovery/confirm.json) and the CLI
  // deletes it when it accepts an ingest. Two conversations starting at once
  // would overwrite each other's token; serialize the issue+spawn section.
  // The same lock covers a retry, which also writes a token.
  let SHORTLIST_START_CHAIN = Promise.resolve()

  function withConfirmTokenLock(fn) {
    const task = SHORTLIST_START_CHAIN.then(fn, fn)
    SHORTLIST_START_CHAIN = task.catch(() => {})
    return task
  }

  function startShortlistJobs(selected, run = runCli, sessionId = '') {
    return withConfirmTokenLock(() => startShortlistJobsLocked(selected, run, sessionId))
  }

  // Start the model-selected videos in the Host. This used to live in the client's
  // confirm route; with no user picker there is nothing to wait for, and a closed
  // tab must not be able to prevent (or duplicate) the work. `run` is injectable
  // so the Node harness can exercise the spawn/limit/idempotency contract without
  // a real CLI.
  async function startShortlistJobsLocked(selected, run = runCli, sessionId = '') {
    const toStart = selected.filter((candidate) => candidate.checked && candidate.video_id)
    // Order-insensitive and session-scoped: a model retry in the same session
    // reuses the batch; another session selecting the same videos gets its own.
    const key = String(sessionId || 'anon') + '|' + toStart.map((candidate) => candidate.video_id).sort().join(',')
    pruneShortlistStarts()
    const cached = SHORTLIST_STARTS.get(key)
    if (cached && Date.now() - cached.at < SHORTLIST_START_TTL_MS) {
      // Preserve a partial failure: a retried shortlist must still show the
      // videos that did not start, not turn them into a clean success.
      return { jobs: cached.jobs, failed: cached.failed || [], reused: true }
    }
    const cookies = persistedCookiesPath()
    const jobs = []
    const failed = []
    for (const candidate of toStart) {
      const source = candidate.url || candidate.source
        || (candidate.platform === 'douyin'
          ? `https://www.douyin.com/video/${candidate.video_id}`
          : `https://www.bilibili.com/video/${candidate.video_id}`)
      // The CLI token is single-use (the first accepted ingest deletes
      // confirm.json), so each video needs its own token. One batch-wide token
      // started the first video and failed the second with E_CONFIRM_FIRST.
      const confirmToken = issueConfirmToken([candidate.video_id])
      const args = ['ingest', source]
      if (cookies) args.push('--cookies', cookies)
      // The token is issued by the Host for exactly this video; the CLI still
      // refuses an ingest that never came through a validated shortlist.
      args.push('--confirm-token', confirmToken, '--detach', '--json')
      const out = await run(args, 30000)
      let created = null
      try { created = JSON.parse(out.out) } catch { created = null }
      if (created && created.job_id) {
        jobs.push({
          video_id: candidate.video_id,
          job_id: String(created.job_id),
          title: candidate.title || '',
          cover_url: candidate.cover_url || '',
          uploader: candidate.uploader || '',
          views: Number(candidate.stats && candidate.stats.play) || 0,
          duration_ms: Number(candidate.duration_ms) || 0,
          source,
          reason: candidate.reason || '',
          primary: candidate.primary === true,
          origin: 'shortlist',
        })
      } else {
        failed.push({
          video_id: candidate.video_id,
          job_id: null,
          title: candidate.title || '',
          cover_url: candidate.cover_url || '',
          uploader: candidate.uploader || '',
          views: Number(candidate.stats && candidate.stats.play) || 0,
          duration_ms: Number(candidate.duration_ms) || 0,
          source,
          reason: candidate.reason || '',
          primary: candidate.primary === true,
          origin: 'shortlist',
          state: 'failed',
          // The CLI prints its failure envelope on stdout; reading stderr alone
          // turned every cause into the generic 'ingest failed'.
          ...(() => {
            const structured = parseStructuredError(out.out)
            return {
              error_code: structured ? structured.code : 'E_INGEST',
              error_message: String((structured && structured.message) || out.err || 'ingest failed').slice(0, 300),
              ...(structured && structured.remedy ? { remedy: String(structured.remedy).slice(0, 300) } : {}),
            }
          })(),
        })
      }
    }
    if (jobs.length) {
      pruneShortlistStarts()
      SHORTLIST_STARTS.set(key, { at: Date.now(), jobs, failed })
    }
    return { jobs, failed, reused: false }
  }
  // The Node harness exercises the start contract (limit, job rows, idempotency)
  // with an injected runner; a real CLI is only needed for the isolated E2E.
  __test.startShortlistJobs = startShortlistJobs
  __test.resetShortlistStarts = () => SHORTLIST_STARTS.clear()
  __test.discoveryLastPath = discoveryLastPath
  const campaigns = createCampaignManager({ home: video2agentHome, startShortlistJobs, readJobSidecar })
  __test.campaigns = campaigns
  __test.timeoutPayload = timeoutPayload
  __test.setupStatus = setupStatus
  __test.installCli = installCli
  __test.withInstallLock = withInstallLock
  __test.setupBusy = setupBusy
  __test.installBrowser = installBrowser
  __test.installOcr = installOcr
  __test.componentInstallInterpreter = componentInstallInterpreter
  __test.installAll = installAll
  __test.detectBrowser = detectBrowser
  __test.detectPlaywrightBrowser = detectPlaywrightBrowser
  __test.installFfmpeg = installFfmpeg
  __test.managedToolEnv = managedToolEnv
  __test.readManagedTools = readManagedTools
  __test.looksLikeDouyinProfile = looksLikeDouyinProfile
  __test.detectFfmpeg = detectFfmpeg
  __test.detectCli = detectCli
  __test.saveManagedCli = saveManagedCli
  __test.cliCommand = cliCommand
  __test.managedToolsPath = managedToolsPath
  __test.cacheCleanupArgs = cacheCleanupArgs
  __test.engineUpdatePublic = engineUpdatePublic
  __test.setEngineUpdate = setEngineUpdate
  __test.clearSetupStatusCache = () => { SETUP_STATUS_CACHE = null }
  __test.onDiskPluginVersion = onDiskPluginVersion
  __test.pluginRestartRequired = pluginRestartRequired
  __test.managedCliTarget = managedCliTarget
  __test.engineAutoTarget = engineAutoTarget
  __test.engineManualTarget = engineManualTarget
  __test.engineHomePath = engineHomePath
  __test.engineRootDir = engineRootDir
  __test.engineVenvPython = engineVenvPython
  __test.legacyEngineTarget = legacyEngineTarget
  __test.performLegacyEngineMigration = performLegacyEngineMigration
  __test.retryLegacyMigration = retryLegacyMigration
  __test.readLegacyMigrationFailure = readLegacyMigrationFailure
  __test.probeEngineVersion = probeEngineVersion
  __test.probeEngineDistribution = probeEngineDistribution
  __test.probeEngineEnvironment = probeEngineEnvironment
  __test.probeEngineInterpreter = probeEngineInterpreter
  __test.recordVerifiedCli = recordVerifiedCli
  __test.pipInstallEngine = pipInstallEngine
  __test.performEngineUpdate = performEngineUpdate
  __test.runEngineAutoUpdate = runEngineAutoUpdate
  __test.scheduleEngineAutoUpdate = scheduleEngineAutoUpdate
  __test.waitForEngineReady = waitForEngineReady
  __test.workerBusy = workerBusy
  __test.markWorkerStale = markWorkerStale
  __test.engineUpdateMarkerPath = engineUpdateMarkerPath
  __test.resetEngineUpdate = resetEngineUpdateForTest
  __test.setEngineTestHooks = (hooks) => { Object.assign(ENGINE_TEST_HOOKS, hooks || {}) }


  // Register a plain registry-ready definition instead of importing
  // @deepseek-ai/dsh-tools. A second copy of that package can disagree with
  // the host's scheduler symbol and break every run_code call.
  // The model filters the raw discover results and shortlists 1-10. The Host
  // validates every id, starts the selected videos inline, and returns their job
  // ids. There is no candidate card and no client confirm round-trip.
  async function executeShortlist(args, sessionId = '') {
    const rawIds = Array.isArray(args.video_ids) ? args.video_ids : []
    const last = readDiscoveryLast(sessionId)
    const fail = (code, message, remedy) => {
      // A rejected shortlist used to leave status.json at `curating`, so the
      // composer kept saying "AI 正在筛选" for two minutes after the turn failed.
      try {
        writeDiscoveryStatus({
          phase: 'error',
          kind: 'selection',
          query: String((last && last.query) || ''),
          error: String(message).slice(0, 240),
        }, sessionId)
      } catch {}
      return { ok: false, text: message, error: { code, message, remedy } }
    }
    if (!last) {
      return fail('E_NO_DISCOVERY', '还没有可展示的搜索结果', '先调用 discover 搜索一次，再从返回的 candidates 里选 1-10 个。')
    }
    // Models often copy candidate_id ("bili_BV...") into video_ids. Accept both
    // spellings and normalise to video_id; rejecting a valid id only caused retries
    // and made the turn longer (observed in the first real shortlist turn).
    const lookup = new Map()
    for (const candidate of last.candidates || []) {
      const videoId = String(candidate.video_id || '')
      const candidateId = String(candidate.candidate_id || '')
      if (videoId) lookup.set(videoId, candidate)
      if (candidateId) lookup.set(candidateId, candidate)
    }
    const ids = []
    const missing = []
    for (const raw of rawIds) {
      const key = String(raw || '').trim()
      if (!key) continue
      const candidate = lookup.get(key)
      if (!candidate) {
        missing.push(key)
        continue
      }
      const videoId = String(candidate.video_id || '')
      if (videoId && !ids.includes(videoId)) ids.push(videoId)
    }
    const requestedCount = rawIds.map((v) => String(v || '').trim()).filter(Boolean).length
    const processLimit = Number(readMergedSettings().processLimit) || 10
    if (requestedCount > 100) {
      return fail('E_SHORTLIST_COUNT', '单次最多 100 个候选；更多请拆成多个 campaign', '按相关性选，超过 100 个请分多个 campaign。')
    }
    if (requestedCount > processLimit && args.campaign !== true && !(Array.isArray(args.default_selected) && args.default_selected.length)) {
      return fail('E_SHORTLIST_COUNT', '单波最多 ' + processLimit + ' 个；更多视频请设置 campaign:true', '用 campaign:true 分析超过单波上限的视频；Host 会分波启动。')
    }
    if (missing.length) {
      return fail(
        'E_SHORTLIST_UNKNOWN',
        '这些视频不在刚才的搜索结果里：' + missing.slice(0, 4).join(', '),
        '只能从本轮 discover 返回的 candidates 里选；先重新搜索。',
      )
    }
    if (ids.length < 1) {
      return fail('E_SHORTLIST_COUNT', '至少选 1 个候选', '按相关性选，宁少勿多；1 个也合法。')
    }
    const byId = new Map()
    for (const candidate of last.candidates || []) {
      const videoId = String(candidate.video_id || '')
      if (videoId) byId.set(videoId, candidate)
    }
    const primaryCandidate = lookup.get(String(args.primary || ''))
    if (!primaryCandidate) {
      return fail('E_SHORTLIST_PRIMARY', 'primary 必须是候选中的一个视频', '把 primary 设成 video_ids 里的一个 video_id（也接受 candidate_id）。')
    }
    const primary = String(primaryCandidate.video_id || '')
    if (!ids.includes(primary)) {
      return fail('E_SHORTLIST_PRIMARY', 'primary 必须出现在 video_ids 里', '把 primary 设成 video_ids 里的一个 video_id（也接受 candidate_id）。')
    }
    const reasons = args.reasons && typeof args.reasons === 'object' ? args.reasons : {}
    // A campaign may hold more than one wave. All ids are the campaign; only
    // the first processLimit start now. A single-wave shortlist still requires
    // default_selected so the Host never silently starts everything.
    const campaignMode = args.campaign === true
    const rawDefault = Array.isArray(args.default_selected) ? args.default_selected : []
    // More ids than one wave MUST be an explicit campaign. Otherwise the
    // unchecked tail was silently dropped while the call looked successful.
    if (!campaignMode && requestedCount > processLimit) {
      return fail(
        rawDefault.length ? 'E_SHORTLIST_DEFAULT' : 'E_SHORTLIST_COUNT',
        '单波最多 ' + processLimit + ' 个，收到 ' + requestedCount + ' 个',
        '设置 campaign:true 分波处理全部视频；否则请减少 video_ids，Host 不会静默丢弃。',
      )
    }
    const defaultIds = []
    for (const raw of rawDefault) {
      const key = String(raw || '').trim()
      if (!key) continue
      const candidate = lookup.get(key)
      if (!candidate) return fail('E_SHORTLIST_DEFAULT', '默认选中里有不在候选中的视频', 'default_selected 只能从 video_ids 里选。')
      const videoId = String(candidate.video_id || '')
      if (videoId && !ids.includes(videoId)) return fail('E_SHORTLIST_DEFAULT', '默认选中必须包含在 video_ids 里', '先把该视频放进 video_ids。')
      if (videoId && !defaultIds.includes(videoId)) defaultIds.push(videoId)
    }
    if (campaignMode) {
      defaultIds.splice(0, defaultIds.length, ...ids)
    } else if (!defaultIds.length) {
      if (requestedCount > processLimit) {
        return fail('E_SHORTLIST_COUNT', '单波最多 ' + processLimit + ' 个；更多视频请设置 campaign:true', '用 campaign:true 分析超过单波上限的视频；Host 会分波启动。')
      }
      return fail('E_SHORTLIST_DEFAULT', '缺少 default_selected', '用 default_selected 指定要启动的 1 到 N 个视频（必须包含 primary）。')
    }
    if (!campaignMode && defaultIds.length > processLimit) {
      return fail('E_SHORTLIST_DEFAULT', '默认选中超过处理上限（当前 ' + processLimit + '）', '减少 default_selected，或设置 campaign:true 分波处理。')
    }
    if (!defaultIds.includes(primary)) {
      return fail('E_SHORTLIST_DEFAULT', '首选必须默认选中', '把 primary 放进 default_selected。')
    }
    const selected = ids.map((id) => {
      const candidate = byId.get(id)
      const reason = String(reasons[id] || reasons[String(candidate.candidate_id || '')] || '').trim().slice(0, 240)
      return {
        candidate_id: String(candidate.candidate_id || ''),
        video_id: String(candidate.video_id || ''),
        platform: String(candidate.platform || 'bilibili'),
        url: candidate.url ? String(candidate.url) : '',
        title: String(candidate.title || ''),
        uploader: String(candidate.uploader || ''),
        duration_ms: Number(candidate.duration_ms) || 0,
        published_at: String(candidate.published_at || ''),
        cover_url: candidate.cover_url ? String(candidate.cover_url) : '',
        stats: candidate.stats || {},
        checked: campaignMode ? true : defaultIds.includes(id),
        primary: id === primary,
        reason: reason || undefined,
      }
    })
    // Selected videos start immediately. The Host owns the start now: the old
    // client confirm route could wait 480s for a click that no longer exists, and
    // a closed tab could either block the batch or duplicate it.
    writeDiscoveryStatus({
      phase: 'starting',
      query: String(last.query || ''),
      found: selected.length,
      candidates: selected.slice(0, 4).map((c) => ({
        video_id: c.video_id || '',
        title: c.title || '',
        cover_url: c.cover_url || '',
        uploader: c.uploader || '',
        views: Number(c.stats && c.stats.play) || 0,
        duration_ms: c.duration_ms || 0,
      })),
      primary,
    }, sessionId)
    let started
    let campaign = null
    if (campaignMode) {
      // A retried ingest campaign:true must reuse the campaign instead of
      // starting a second one that re-ingests the same videos.
      const campaignKey = String(sessionId || 'anon') + '|'
        + selected.map((c) => c.video_id).sort().join(',')
      const cachedCampaign = CAMPAIGN_STARTS.get(campaignKey)
      // A wave runs for minutes, so an in-memory TTL alone missed the retry and
      // started a second campaign (re-ingesting the same videos). Fall back to
      // an unfinished campaign on disk with the same session and videos.
      let reuseId = cachedCampaign && Date.now() - cachedCampaign.at < 30 * 60 * 1000
        ? cachedCampaign.id
        : null
      if (!reuseId) {
        try { reuseId = campaigns.findActive(sessionId || '', selected.map((c) => c.video_id)) } catch { reuseId = null }
      }
      if (reuseId) {
        // A finished campaign must not be reused: its failed rows would be
        // impossible to retry until the TTL expired.
        const existing = await campaigns.get(reuseId)
        if (!existing || existing.status === 'complete' || existing.status === 'failed') {
          if (!((existing && existing.items) || []).some(
            (x) => x && x.state === 'failed' && x.error_code === 'E_WORKER_LOST')) reuseId = null
        }
      }
      if (reuseId) {
        // Reuse advances the campaign: the row that told the model to "ingest
        // again with campaign:true" only makes sense if that call ticks.
        campaign = await campaigns.tick(reuseId)
        if (campaign) {
          const snap = campaigns.snapshot(campaign)
          campaign = snap
          started = {
            jobs: snap.items.filter((x) => x.job_id && x.state !== 'failed'),
            failed: snap.items.filter((x) => x.state === 'failed'),
            queued: snap.items.filter((x) => x.state === 'queued'),
            reused: true,
          }
        }
      }
      if (!campaign) {
      campaign = await campaigns.start(selected, sessionId || null, processLimit)
      const snap = campaigns.snapshot(campaign)
      started = {
        jobs: snap.items.filter((x) => x.job_id && x.state !== 'failed'),
        failed: snap.items.filter((x) => x.state === 'failed'),
        queued: snap.items.filter((x) => x.state === 'queued'),
        reused: false,
      }
      // Cache only a campaign that actually started something: a fully failed
      // first wave must be retryable immediately.
      if (started.jobs.length && campaign && campaign.id) {
        CAMPAIGN_STARTS.set(campaignKey, { at: Date.now(), id: campaign.id })
        // Bound the cache: a long-lived Host otherwise grows it forever.
        if (CAMPAIGN_STARTS.size > 50) {
          const oldest = CAMPAIGN_STARTS.keys().next().value
          if (oldest && oldest !== campaignKey) CAMPAIGN_STARTS.delete(oldest)
        }
      }
      }
    } else {
      started = await startShortlistJobs(selected, undefined, sessionId)
    }
    if (!started.jobs.length) {
      const message = (started.failed[0] && started.failed[0].error_message) || '没有任务启动成功'
      writeDiscoveryStatus({
        phase: 'error',
        kind: 'start',
        query: String(last.query || ''),
        error: String(message).slice(0, 240),
      }, sessionId)
      if (campaign) campaigns.abort(campaign.id, message)
      return fail('E_START', '视频任务没有启动：' + message, '检查 video2agent CLI、FFmpeg 和网络；修复后重试 shortlist。')
    }
    clearDiscoveryStatus()
    const payload = {
      ok: true,
      state: 'started',
      batch_id: 'batch_' + crypto.randomBytes(6).toString('hex'),
      started_at: Date.now(),
      count: started.jobs.length,
      total: campaign ? campaign.items.length : started.jobs.length,
      campaign_id: campaign ? campaign.id : undefined,
      primary,
      jobs: started.jobs,
      failed: started.failed.length ? started.failed : undefined,
      queued: started.queued && started.queued.length ? started.queued : undefined,
      reused: started.reused === true ? true : undefined,
      candidates: selected.map((c) => ({
        video_id: c.video_id,
        title: c.title,
        primary: c.primary,
        reason: c.reason || '',
      })),
      // Only default_selected starts. Name the rest so the model does not think
      // a candidate it listed is already running (it then re-ingests it alone).
      // Only list the field when something really did not start: an empty array
      // next to 'the rest were NOT started' reads as if nothing started.
      not_started: (campaign || !ids.some((v) => !defaultIds.includes(String(v))))
        ? undefined
        : ids.filter((v) => !defaultIds.includes(String(v))).slice(0, 20),
      next_step: {
        action: 'started',
        rule: campaign
          ? 'This is a campaign: only the first wave started; queued rows are not running yet. Call ingest with campaign_id (or the same video_ids plus campaign:true) to advance/read it; there is no campaign tool command. Do not claim all rows are running. Use jobs --wait for started job ids, then overview/transcript/search/evidence.'
          : 'The videos in default_selected have started; other video_ids were NOT started (see not_started). Do not call ingest again and do not ask the user to repeat their question. If the original request was a content task, call video2agent jobs --id <job_id> --wait --json, then overview/transcript/search/evidence, and answer. If you truly need one of the not_started videos too, say so and start it separately; do not claim it is part of this batch.',
      },
    }
    // PTC sessions call this through run_code, so no Card mounts. The dock polls
    // this snapshot and creates the batch table itself. A reused batch must not
    // rewrite the queue with a fresh started_at: that overwrites the dock's live
    // state and revives a batch the user already cleared.
    if (started.reused !== true) writeSessionQueue(sessionId, payload)
    return { ok: true, text: JSON.stringify(payload) }
  }

  async function executeCampaign(args, sessionId = '') {
    const id = String(args.campaign_id || '')
    if (!/^campaign_[a-f0-9]{8,32}$/.test(id)) {
      return { ok: false, text: JSON.stringify({ ok: false, error: { code: 'E_CAMPAIGN_ID', message: 'Invalid campaign_id', remedy: 'Pass the campaign_id returned by shortlist campaign:true.' } }), error: { code: 'E_CAMPAIGN_ID', message: 'Invalid campaign_id', remedy: 'Pass the campaign_id returned by shortlist campaign:true.' } }
    }
    const campaign = await campaigns.tick(id)
    if (!campaign) {
      return { ok: false, text: JSON.stringify({ ok: false, error: { code: 'E_CAMPAIGN_NOT_FOUND', message: 'Campaign not found', remedy: 'The campaign may have been cleaned up; start a new shortlist.' } }), error: { code: 'E_CAMPAIGN_NOT_FOUND', message: 'Campaign not found', remedy: 'The campaign may have been cleaned up; start a new shortlist.' } }
    }
    const snapshot = campaigns.snapshot(campaign)
    return { ok: true, text: JSON.stringify({ ok: true, ...snapshot }) }
  }

  tools.register({
    name: 'video2agent',
    description:
      'Video and screen-recording perception + retrieval for agents. Use it for UI motion/QA, '
      + 'animations, tutorials, demos, and timestamp/frame questions, even when the user never says '
      + '"video". Also use it when a question is best answered by fresh video — game season/patch tier '
      + 'lists, loadouts, reviews, recipes, travel, breaking visual topics — and search Bilibili + Douyin with find. '
      + 'Not for a static screenshot, pure audio, or a live stream. Pick one command: '
      + 'find (Bilibili by default; scope:"douyin" for Douyin, or when the Douyin search setting is enabled; scope:library searches the library; a url resolves title/cover/duration), '
      + 'ingest (index a path/URL; video_ids starts a shortlist and returns job ids; job_id polls; campaign_id advances a campaign), '
      + 'outline (detail:digest is the one-call index with transcript/OCR/keyframes/cuts; overview; map), '
      + 'read (transcript with timestamps; compare packs 2-10 videos), '
      + 'evidence (a timestamp plus its on-screen text and an optional frame), '
      + 'frames (exact frames, windows, sheets; view:candidates for shots; view:ocr to read a window), '
      + 'perceive (number-only motion/cut/loop map for a window, never images), '
      + 'admin (list, export, ocr-index, account read-only for Bilibili, douyin reads (one or 1-10 profiles), doctor). Call it directly at the top '
      + 'level; in a harness that only exposes run_code, wrap it in run_code (the dock card may not render); never shell out to the CLI. On failure return the error; do not invent content.',
    parameters: {
      type: 'object',
      additionalProperties: false,
      required: ['command'],
      properties: {
        command: {
          type: 'string',
          enum: ['find', 'ingest', 'outline', 'read', 'evidence', 'frames', 'perceive', 'admin'],
          description: 'What to do. find: Bilibili search by default; Douyin only with scope:"douyin" or when the Douyin search setting is enabled; library search (scope library), or resolve a URL. ingest: index a path/URL, start a shortlist (video_ids), poll a job (job_id) or a campaign (campaign_id). outline: one-call index (detail digest), overview, or map. read: transcript or compare. evidence: a timestamp plus its text. frames: pixels. perceive: motion numbers. admin: list/export/ocr-index/account (Bilibili)/douyin (Douyin account)/doctor.',
        },
        scope: {
          type: 'string',
          enum: ['all', 'bilibili', 'douyin', 'library', 'transcript', 'compare'],
          description: 'find: omit for the configured default (Bilibili unless the Douyin search setting is on), bilibili, douyin (only when the user explicitly asks for Douyin), all (both), or library. read: transcript (default) or compare.',
        },
        detail: {
          type: 'string',
          enum: ['digest', 'overview', 'map'],
          description: 'outline: digest (default), overview, or map.',
        },
        view: {
          type: 'string',
          // Only these two change behaviour; at/window/sheet are inferred from
          // the at/start/end/sheet fields, so advertising them was a lie.
          enum: ['candidates', 'ocr'],
          description: 'frames: candidates (shot list) or ocr (text over a window); at/window/sheet follow at/start/end/sheet.',
        },
        admin_action: {
          type: 'string',
          enum: ['list', 'export', 'ocr-index', 'account', 'douyin', 'doctor'],
          description: 'admin: list (default), export, ocr-index, account (Bilibili), douyin (one or 1-10 profiles), or doctor. For a creator full-works timeline use admin_action:"douyin" + douyin_action:"videos" with the sec_uid. For 1-10 creators use douyin_action:"profiles" + douyin_urls. Use this exact field name (admin_action), not action.',
        },
        douyin_action: {
          type: 'string',
          enum: ['me', 'profile', 'videos', 'status', 'profiles'],
          description: 'admin douyin: me (own profile), profile (douyin_url), videos (douyin_url optional; douyin_tab works/likes/favorites), profiles (batch: 1-10 douyin_urls), or status.',
        },
        douyin_url: {
          type: 'string',
          description: 'admin douyin: profile URL or sec_uid (required for profile, optional for videos).',
        },
        douyin_urls: {
          type: 'array',
          items: { type: 'string' },
          minItems: 1,
          maxItems: 10,
          description: 'admin douyin profiles: 1-10 profile URLs or sec_uids. The CLI validates each identity, so one bad entry does not abort the batch.',
        },
        douyin_tab: {
          type: 'string',
          enum: ['works', 'likes', 'favorites'],
          description: 'admin douyin videos: works, likes or favorites (default works).',
        },
        account_action: {
          type: 'string',
          enum: ['status', 'folders', 'favorites', 'history', 'analyze', 'classify-plan'],
          description: 'account: status/folders/favorites/history/analyze/classify-plan (read-only).',
        },
        folder_id: { type: 'number', description: 'account favorites: folder id.' },
        days: { type: 'number', description: 'account history/analyze: window in days (default 30).' },
        account_source: { type: 'string', enum: ['favorites', 'history'], description: 'account analyze/classify-plan: favorites or history.' },
        query: { type: 'string', description: 'find: keyword. evidence/frames: unused.' },
        queries: {
          type: 'array',
          items: { type: 'string' },
          minItems: 1,
          maxItems: 8,
          description: 'find (scope library): up to 8 query variants.',
        },
        uploader: { type: 'string', description: 'find: uploader name or numeric UID.' },
        after: { type: 'string', description: 'find: published on/after (2026-10-01 or 7d).' },
        before: { type: 'string', description: 'find: published on/before (2026-10-26 or 30d).' },
        covers: { type: 'boolean', description: 'find: OCR covers for visual matching (default off, ~10s).' },
        source: { type: 'string', description: 'ingest: local path or URL.' },
        url: { type: 'string', description: 'find: URL to resolve title/cover/duration.' },
        video_id: { type: 'string', description: 'Target video: a vid_ id, or the BV id / URL of an indexed video (resolved automatically).' },
        compare_video_ids: {
          type: 'array',
          items: { type: 'string' },
          minItems: 2,
          maxItems: 10,
          description: 'read (compare): 2-10 video ids.',
        },
        aspects: { type: 'string', description: 'read (compare): comma-separated dimensions.' },
        per_video: { type: 'number', description: 'read (compare): hits per video per aspect (default 2).' },
        max_total_chars: { type: 'number', description: 'read (compare): total transcript budget (default 40000).' },
        video_ids: {
          type: 'array',
          items: { type: 'string' },
          minItems: 1,
          maxItems: 100,
          description: 'ingest: the 1-100 candidates you considered. Without campaign only default_selected starts; campaign:true runs them in later waves.',
        },
        default_selected: {
          type: 'array',
          items: { type: 'string' },
          minItems: 1,
          maxItems: 100,
          description: 'ingest: exactly the ids to start now (max process_limit). Nothing else starts.',
        },
        campaign: { type: 'boolean', description: 'ingest shortlist: queue more than one wave.' },
        campaign_id: { type: 'string', description: 'ingest: poll or advance a campaign.' },
        primary: { type: 'string', description: 'ingest shortlist: the main row; must be in default_selected.' },
        reasons: {
          type: 'object',
          additionalProperties: { type: 'string' },
          description: 'For shortlist: optional video_id -> one-sentence reason shown in the status table.',
        },
        job_id: { type: 'string', description: 'ingest: job id to poll.' },
        wait_ms: { type: 'number', description: 'ingest: wait for one job (ms, clamped to 5000-90000). One wait per job: never loop waits over several jobs in one program; read already-finished videos instead.' },
        language: { type: 'string', description: 'ingest: ASR language when the video has no captions (zh, en, ja, ...). Omit to auto-detect; pass it when the transcript came out in the wrong language.' },
        at: { type: 'string', description: 'evidence/frames: the moment (01:12:34, 548s, or 548000ms); comma list for evidence.' },
        timestamp: { type: 'string', description: 'Alias of at (evidence/frames); at wins when both are set.' },
        max_images: { type: 'number', description: 'evidence: image budget for a multi-moment call (1-6).' },
        crop: { type: 'string', description: 'frames: normalized x,y,w,h (0-1).' },
        scale: { type: 'number', description: 'frames: crop upscale 1-3.' },
        start: { type: 'string', description: 'Range start: seconds by default (548), or 548s / 00:09:08 / 548000ms.' },
        end: { type: 'string', description: 'Range end, same units as start (seconds by default).' },
        max_chars: { type: 'number', description: 'transcript: text budget (default 6000).' },
        count: { type: 'number', description: 'frames: 1-8 frames; outline: 1-6 keyframes.' },
        fps: { type: 'number', description: 'frames window 1-8; perceive 1-30.' },
        max_frames: { type: 'number', description: 'perceive: decode cap (100-40000).' },
        brief: { type: 'boolean', description: 'perceive: ~340-token survey (cuts + 4 moments).' },
        max: { type: 'number', description: 'frames window: frame cap (1-15).' },
        mode: { type: 'string', enum: ['uniform', 'change'], description: 'frames window: uniform or change.' },
        sheet: { type: 'boolean', description: 'frames: tile results into one labelled image (max 9).' },
        windows: { type: 'number', description: 'frames: split start/end into 2-9 windows.' },
        force: { type: 'boolean', description: 'ingest: re-index an existing video.' },
        format: { type: 'string', enum: ['md', 'html', 'json', 'knowledge'], description: 'export: md/html/json/knowledge.' },
        limit: { type: 'number', description: 'Result limit (default 8; map 50; account/douyin 50).' },
        images: { type: 'number', description: 'evidence: 0-6 images (default 2; use 0 when transcript/OCR text answers).' },
        include_images: { type: 'boolean', description: 'frames (candidates): one montage image.' },
        ocr_tiles: { type: 'boolean', description: 'evidence/ocr: tile small text.' },
      },
    },
    output: {
      schema: {
        type: 'object',
        additionalProperties: false,
        required: ['text'],
        properties: {
          ok: { type: 'boolean' },
          text: { type: 'string' },
          images: { type: 'array', items: { type: 'object' } },
          error: {
            type: 'object',
            additionalProperties: false,
            properties: {
              code: { type: 'string' },
              message: { type: 'string' },
              remedy: { type: 'string' },
            },
          },
        },
      },
      render: (_args, value) => {
        const text = String(value?.text || '').slice(0, 60000)
        // A failed call renders as a small JSON envelope, because that is the
        // only channel the tool card can read: without it the card could only
        // show bare CLI prose (or worse, "waiting for result" forever) and the
        // error code/remedy would never reach the user. Successful calls keep
        // the CLI payload untouched, since those cards parse it directly.
        if (value && value.ok === false) {
          const error = value.error || { code: 'E_RESULT', message: text.slice(0, 800) || 'Video2Agent failed' }
          // A partial write must keep its per-video receipt, and an all-failed
          // profile batch must keep its per-person errors, so the card can show
          // which creator failed. A generic error already carries message/remedy,
          // so its inner text stays empty instead of re-printing the JSON.
          const inner = error.code === 'E_DOUYIN_PROFILES'
            ? text.slice(0, 60000)
            : error.code === 'E_ACCOUNT_PARTIAL' && !text.trim().startsWith('{')
              ? text.slice(0, 60000) : ''
          return [{ type: 'text', text: JSON.stringify({ ok: false, error, text: inner }) }]
        }
        const blocks = [{ type: 'text', text }]
        // The frames the user is looking at are the same frames the model reads.
        if (Array.isArray(value?.images)) {
          for (const ref of value.images) {
            if (ref && ref.attachmentId) blocks.push({ type: 'image', attachment: ref })
          }
        }
        return blocks
      },
    },
    execute: async (args, exec) => {
      const sessionId = String(exec?.agent?.session?.id || '')
      // Every tool path (including shortlist/campaign starts) waits for the one
      // startup engine probe/update. While it runs, no old CLI is spawned.
      await waitForEngineReady()
      if (String(args.command || '') === 'campaign') return executeCampaign(args, sessionId)
      if (String(args.command || '') === 'shortlist') return executeShortlist(args, sessionId)
      if (String(args.command || '') === 'ingest' && args.campaign_id) return executeCampaign(args, sessionId)
      if (String(args.command || '') === 'ingest' && looksLikeDouyinProfile(args.source)) {
        const error = {
          code: 'E_DOUYIN_USER',
          message: '这是抖音用户主页，不是视频；请用 admin_action:"douyin" 读主页。',
          remedy: '资料/作品列表用 admin_action:"douyin", douyin_action:"profile" 或 "videos"；1-10 个主页用 "profiles" + douyin_urls；单条视频再 ingest。',
        }
        return { ok: false, text: JSON.stringify({ ok: false, error }), error }
      }
      if (String(args.command || '') === 'ingest' && Array.isArray(args.video_ids) && !args.source && !args.url) {
        return executeShortlist(args, sessionId)
      }
      // A model that remembers the concept ("timestamp") instead of the property
      // name used to burn a call on a schema rejection; accept both.
      if (args && args.timestamp !== undefined && args.timestamp !== null && args.timestamp !== ''
        && (args.at === undefined || args.at === null || args.at === '')) {
        args = { ...args, at: args.timestamp }
      }
      const argv = commandArgs(args)
      // The model-facing verbs (find/outline/read/admin) map onto different CLI
      // commands. Everything below this point — discovery handoff, the activity
      // line, image attachment and path redaction — is keyed on the command the
      // CLI actually ran, so derive it from argv instead of re-reading a verb.
      const cliCommand = String(argv && argv[0] || args.command || '')
      if (!argv) {
        const command = String(args.command || '')
        const error = {
          code: 'E_ARGS',
          message: `Missing required argument for "${command || 'unknown'}".`,
          remedy: 'discover/search need query; shortlist needs 1-10 video_ids, default_selected plus primary; ingest needs source; overview/transcript/frames/map/evidence/export need video_id; evidence needs at; resolve needs url; admin douyin needs douyin_action (profile also needs douyin_url, profiles needs 1-10 douyin_urls). Positional values must not start with "-".',
        }
        return { ok: false, text: JSON.stringify({ ok: false, error }), error }
      }
      if (cliCommand === 'discover') {
        // A new search replaces the previous status line; there is no pending
        // card or interrupt marker left to clear.
        writeDiscoveryStatus({
          phase: 'searching',
          query: String(args.query || ''),
          at: Date.now(),
        }, sessionId)
      }
      // A blocking `jobs --wait` must be allowed to outlive the default 10-minute
      // process timeout, otherwise the wait is killed before the CLI answers.
      const waiting = cliCommand === 'jobs' && args.wait_ms
      const timeout = waiting
        ? Math.min(105000, clampInt(Number(args.wait_ms), 45000, 5000, 90000) + 15000)
        : cliCommand === 'douyin' && String(args.douyin_action || '') === 'profiles'
          ? DOUYIN_PROFILES_TIMEOUT_MS
          : 600000
      const cmd = cliCommand
      const accountWrite = cmd === 'account' && ['create-folder', 'rename-folder', 'add', 'classify-apply'].includes(String(args.account_action || ''))
      const activityKind = cmd === 'ocr-index' ? 'ocr-index' : cmd === 'export' ? 'export' : accountWrite ? 'account-write' : ''
      const activityTitle = accountWrite ? String(args.title || args.folder_id || '') : ''
      const activity = activityKind ? beginActivity(activityKind, activityTitle, sessionId) : null
      let r
      try {
        r = await runToolCommand(args, argv, timeout)
        if (activity) finishActivity(activity, r.code === 0 ? 'ready' : 'failed')
      } catch (e) {
        if (activity) finishActivity(activity, 'failed')
        throw e
      }
      const error = cliError(r)
      const full = String(r.out || r.err || 'no output')
      const cut = full.length > 60000
      // A truncated JSON payload is not a partial success: the model cannot
      // parse it and silently loses the tail. Return a structured error so the
      // caller can reduce videos/aspects or the CLI can use compact output.
      if (cut && r.code === 0) {
        const tooLarge = {
          code: 'E_OUTPUT_TRUNCATED',
          message: '工具输出超过 60000 字符，已拒绝返回截断的 JSON。',
          remedy: '减少 compare 的视频/aspect 数，或降低 limit；compare 已使用 compact 输出。',
        }
        return { ok: false, text: JSON.stringify({ ok: false, error: tooLarge }), error: tooLarge }
      }
      const raw = cut ? full.slice(0, 60000) + '\n[output truncated at 60000 characters]' : full
      // On a structured failure keep the readable message as the card text; the
      // raw stdout would just re-print the JSON the CLI already parsed.
      const structured = error ? parseStructuredError(r.out) : null
      // A partial account write must keep the per-video results; replacing the
      // payload with only the error message hides which writes already landed and
      // invites a blind retry.
      const partial = structured && structured.code === 'E_ACCOUNT_PARTIAL'
      // An all-failed profile batch is still the answer: keep the allowlisted
      // per-entry errors instead of collapsing them to the top-level envelope.
      let batchFailure = null
      if (structured && structured.code === 'E_DOUYIN_PROFILES') {
        try { batchFailure = failedBatchProfileText(JSON.parse(r.out || ''), error) } catch {}
      }
      // A failed call must still hand the model JSON. In a run_code/PTC session the
      // nested result exposes this text verbatim, so a plain message made the
      // model's JSON.parse throw and abort the turn (real log 2026-11-14: the
      // second find after a search error; the model lost the rest of its plan).
      let text = error && !partial && !batchFailure ? JSON.stringify({ ok: false, error }) : raw
      if (batchFailure) text = batchFailure
      // jobs answers a failed row with {ok:false, job, error}; keep the row so the
      // model can name the video and tell canceled from failed. parseStructuredError
      // only returns code/message/remedy, so read the job from the raw payload.
      if (structured) {
        let rawPayload = null
        try { rawPayload = JSON.parse(r.out || '') } catch { rawPayload = null }
        const row = jobFromCliPayload(rawPayload)
        if (row) text = JSON.stringify({ ok: false, job: row, error })
      }
      // A wait that times out is not a failure: the job is still running. The
      // CLI reports E_TIMEOUT, and flattening that to the message text made the
      // model's JSON.parse throw and abort the turn. Answer with a normal payload.
      if (cliCommand === 'jobs' && structured && structured.code === 'E_TIMEOUT') {
        // commandArgs clamps the wait to 5-90s; report what actually elapsed.
        const waitedSeconds = Math.min(90, Math.max(5, Math.round((Number(args.wait_ms) || 0) / 1000)))
        return { ok: true, text: JSON.stringify(timeoutPayload(args.job_id, waitedSeconds * 1000)) }
      }
      // discover is search-only. It returns candidates to the model but does not
      // publish a card: the model filters them and calls shortlist. This is what
      // prevents ten searches from producing ten candidate cards.
      if (cliCommand === 'discover') {
        if (r.code === 0) {
          try {
            const parsed = JSON.parse(raw)
            if (Array.isArray(parsed.candidates) && parsed.candidates.length) {
              // Additive, verified profile URLs only (Douyin + a real sec_uid).
              // Bilibili rows and unverified placeholders stay byte-identical.
              parsed.candidates = parsed.candidates.map(withCandidateProfileUrl)
              writeDiscoveryLast({
                query: String(parsed.query || args.query || ''),
                candidates: parsed.candidates,
              }, sessionId)
              writeDiscoveryStatus({
                phase: 'curating',
                query: String(parsed.query || args.query || ''),
                found: parsed.candidates.length,
                candidates: parsed.candidates.slice(0, 4).map((c) => ({
                  video_id: c.video_id || '',
                  title: c.title || '',
                  cover_url: c.cover_url || '',
                  uploader: c.uploader || '',
                  views: Number(c.stats && c.stats.play) || 0,
                  duration_ms: c.duration_ms || 0,
                })),
                at: Date.now(),
              }, sessionId)
              const processLimit = Number(readMergedSettings().processLimit) || 10
              parsed.process_limit = processLimit
              parsed.next_step = {
                action: 'ingest',
                tool: 'video2agent',
                command: 'ingest',
                why: 'Raw discover results are not a card. Filter them first, then start only the ones you recommend.',
                rule: 'Pick the genuinely relevant candidates; pass them as video_ids with default_selected (at most ' + processLimit + ') and one primary to ingest. The Host starts only the selected videos. shortlist is not a tool command, so do not call it.',
              }
              parsed.next_step.ts = Date.now()
              text = JSON.stringify(parsed)
            } else {
              writeDiscoveryStatus({
                phase: 'empty',
                query: String(parsed.query || args.query || ''),
                found: 0,
                at: Date.now(),
              }, sessionId)
            }
          } catch {
            // Success with unparseable stdout is still a failure for the caller:
            // handing the model prose made its JSON.parse throw and aborted the
            // turn (2026-11-14). Return a structured error instead.
            const bad = {
              code: 'E_BAD_OUTPUT',
              message: '搜索返回的内容不是 JSON：' + String(raw).slice(0, 200),
              remedy: '重试一次；连续出现说明 CLI 输出被日志污染，运行 video2agent doctor。',
            }
            writeDiscoveryStatus({
              phase: 'error',
              query: String(args.query || ''),
              at: Date.now(),
              error: bad.message,
            }, sessionId)
            return { ok: false, text: JSON.stringify({ ok: false, error: bad }), error: bad }
          }
        } else {
          writeDiscoveryStatus({
            phase: 'error',
            query: String(args.query || ''),
            at: Date.now(),
            error: error && error.message ? String(error.message).slice(0, 240) : 'search failed',
          }, sessionId)
        }
      }
      // Evidence and frames are pictures. OCR is only a triage/index signal — it cannot
      // read a handwritten formula, a chart, an action or a menu the way the model can,
      // so the frames themselves go into the model's context as image blocks. That is
      // why the plugin needs the attachments service: an image block references a
      // stored attachment, not a path.
      const visual = []
      let attachedImagePaths = []
      if (r.code === 0 && (cliCommand === 'evidence' || cliCommand === 'frames' || cliCommand === 'digest' || cliCommand === 'candidates')) {
        try {
          const parsed = JSON.parse(raw)
          const command = cliCommand
          const windowedFrames = command === 'frames' && (args.start || args.end)
          const batchedAt = command === 'evidence' && (String(args.at || '').includes(',') || String(args.at || '').startsWith('['))
          const frameCap = Number(args.count) > 1 ? clampInt(args.count, 12, 1, 15) : clampInt(args.max, 12, 1, 15)
          const budget = command === 'frames'
            ? (parsed.sheet ? 1 : windowedFrames ? frameCap : clampInt(args.count, 1, 1, 8))
            : command === 'digest' || command === 'candidates' ? 1
              : batchedAt ? clampInt(args.max_images, 6, 0, 6) : clampInt(args.images, 2, 0, 6)
          const source = Array.isArray(parsed.images) ? parsed.images : []
          const paths = []
          for (const item of source) {
            if (typeof item === 'string') paths.push(item)
            else if (item && typeof item.path === 'string') paths.push(item.path)
          }
          const unique = [...new Set(paths)].slice(0, Math.max(0, budget))
          if (unique.length) {
            const pairs = await storeImages(unique)
            if (Array.isArray(pairs) && pairs.length) {
              attachedImagePaths = pairs.map((p) => p.path)
              visual.push(...pairs.map((p) => p.ref))
            }
          }
        } catch {
          // no images is never an error: the text answer still stands
        }
      }
      if (cliCommand === 'evidence' || cliCommand === 'frames' || cliCommand === 'digest' || cliCommand === 'candidates') {
        // The CLI's JSON contains absolute frame paths and an images list. If
        // either reaches the model it copies a path into the answer, and DSH
        // tries to preview it as a workspace file ("图片无法预览"). The frames
        // are already attachment blocks; keep only timestamps and counts in the
        // text payload, and redact paths even when the attachment service is
        // unavailable so a headless/TUI run never leaks a local path either.
        try {
          const parsed = JSON.parse(text)
          if (parsed && typeof parsed === 'object') {
            const imagePaths = (Array.isArray(parsed.images) ? parsed.images : [])
              .map((item) => (typeof item === 'string' ? item : item && item.path))
              .filter((item) => typeof item === 'string' && item)
            if (cliCommand === 'digest' && typeof parsed.contact_sheet === 'string' && parsed.contact_sheet && !imagePaths.includes(parsed.contact_sheet)) {
              imagePaths.unshift(parsed.contact_sheet)
            }
            if (cliCommand === 'candidates' && typeof parsed.sheet === 'string' && parsed.sheet && !imagePaths.includes(parsed.sheet)) {
              imagePaths.unshift(parsed.sheet)
            }
            if (cliCommand === 'frames' && typeof parsed.sheet === 'string' && parsed.sheet && !imagePaths.includes(parsed.sheet)) {
              imagePaths.unshift(parsed.sheet)
            }
            // For `frames`, the timestamps live only inside images[]. Deleting
            // images left the model with image_urls and no time for any of them.
            if (cliCommand === 'frames') {
              const rows = (Array.isArray(parsed.images) ? parsed.images : [])
                .filter((item) => item && typeof item === 'object')
                .map((item) => ({ t_ms: item.t_ms, timecode: item.timecode }))
              if (rows.length) parsed.frames = rows
            }
            if (Array.isArray(parsed.images)) parsed.image_count = parsed.images.length
            delete parsed.images
            if (cliCommand === 'digest') delete parsed.contact_sheet
            if (cliCommand === 'candidates') delete parsed.sheet
            if (cliCommand === 'frames') delete parsed.sheet
            if (imagePaths.length) {
              const frameVideo = String(parsed.video_id || '')
              // Opaque id, never the absolute path: the model may copy this URL
              // into an answer, and a path there leaks the user's directory layout.
              // When the attachments service is missing (headless/TUI) or a frame
              // could not be read, still expose opaque URLs for every requested
              // frame; only the attached subset becomes image blocks.
              // Always list every requested frame's URL. Only the attached
              // subset reaches the model as blocks; dropping the others made
              // image_urls and frames two different lists.
              const shown = imagePaths
              const attachedSet = new Set(attachedImagePaths.map((p) => String(p)))
              parsed.image_urls = shown.map((item) => frameUrlFor(frameVideo, item))
              // Which URLs actually became image blocks, so a partial attach
              // cannot pair frame 2's picture with frame 1's URL.
              parsed.image_attached = shown.map((item) => attachedSet.has(String(item)))
              parsed.image_markdown = parsed.image_urls.map((url, i) => `![frame ${i + 1}](${url})`)
              parsed.warnings = Array.isArray(parsed.warnings) ? parsed.warnings : []
              if (!attachedImagePaths.length) {
                parsed.images_attached = false
                parsed.warnings.push({ code: 'IMAGES_NOT_ATTACHED', message: '图片附件服务不可用，返回帧链接而不是图片', remedy: '文本与链接仍可用；需要看图请在带附件服务的环境重试。' })
              } else if (attachedImagePaths.length < imagePaths.length) {
                parsed.images_attached = false
                parsed.warnings.push({ code: 'IMAGES_PARTIAL', message: '部分帧未能附加', remedy: 'image_urls 列出全部帧；只有 image_attached 为 true 的位置是真正附上的图片。' })
              }
              // Lockstep only holds when one image maps to one frame. A sheet
              // is one image with N timecodes and must keep all of them.
              const lockstep = imagePaths.length === attachedImagePaths.length
                && Array.isArray(parsed.frames) && parsed.frames.length === imagePaths.length
              if (lockstep) {
                parsed.frames = parsed.frames.slice(0, attachedImagePaths.length)
                if (Array.isArray(parsed.image_frame_ms)) parsed.image_frame_ms = parsed.image_frame_ms.slice(0, attachedImagePaths.length)
              }
              parsed.image_count = shown.length
            }
            // Defensive: older/newer batch payloads may carry per-moment images.
            if (Array.isArray(parsed.moments)) {
              parsed.moments = parsed.moments.map((moment) => {
                if (!moment || typeof moment !== 'object') return moment
                const copy = { ...moment }
                delete copy.images
                return copy
              })
            }
            if (Array.isArray(parsed.frames)) {
              parsed.frames = parsed.frames.map((frame) => {
                if (!frame || typeof frame !== 'object') return frame
                const copy = { ...frame }
                delete copy.path
                delete copy.file
                delete copy.absolute_path
                return copy
              })
            }
            text = JSON.stringify(parsed)
          }
        } catch {
          // non-JSON text is left alone; attachments still render
        }
      }
      const visualCommand = ['evidence', 'frames', 'digest', 'candidates'].includes(cliCommand)
      if (r.code === 0 && !visualCommand) {
        try {
          const parsed = JSON.parse(text)
          if (parsed && typeof parsed === 'object') text = JSON.stringify(redactTextPaths(parsed))
        } catch {
          // non-JSON output is left alone
        }
      }
      const out = { ok: r.code === 0, text }
      if (error) out.error = error
      // `render` is synchronous, so the stored attachment refs travel inside the value
      // and are turned into image blocks there.
      if (visual.length) out.images = visual
      return out
    },
  })

  // Registered after the tool exists, on this plugin's context: Cordis removes
  // the section when the plugin unloads. The text function is empty once the
  // settings switch is off, so a disabled plugin cannot keep steering routing.
  if (ctx.systemPrompt && typeof ctx.systemPrompt.section === 'function') {
    try {
      ctx.systemPrompt.section({
        name: 'video2agent:routing',
        order: 1950,
        text: () => (readMergedSettings().enabled ? HARD_ROUTING_PROMPT : ''),
      })
    } catch (e) {
      ctx.logger?.info?.('[dsh-video2agent] routing prompt skipped: ' + (e?.message || e))
    }
  }

  // Probe once per Host load, in the background. It never runs from GET and
  // never repeats on refresh; a failed attempt needs an explicit manual retry.
  try { scheduleEngineAutoUpdate() } catch (e) {
    ctx.logger?.info?.('[dsh-video2agent] engine auto-update skipped: ' + (e?.message || e))
    resolveEngineReadyGate()
  }
}
// Test-only surface: the Node harness asserts the argv the tool would run and the
// merged settings precedence without spawning the CLI.
export const __test = { commandArgs, readMergedSettings, jobFromCliPayload, frameUrlFor, doctorFailure, redactTextPaths, workerEligible, runWorker, stopWorker, workerPid, parseJsonObjectText }

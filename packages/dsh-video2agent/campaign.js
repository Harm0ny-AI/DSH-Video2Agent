import crypto from 'node:crypto'
import fs from 'node:fs'
import path from 'node:path'

export function createCampaignManager({ home, startShortlistJobs, readJobSidecar }) {
  const inFlight = new Map()
  const dir = () => path.join(home(), 'campaigns')
  const file = (id) => path.join(dir(), String(id) + '.json')
  function read(id) {
    try { return JSON.parse(fs.readFileSync(file(id), 'utf8')) } catch { return null }
  }
  function write(campaign) {
    fs.mkdirSync(dir(), { recursive: true })
    const target = file(campaign.id)
    const tmp = target + '.tmp-' + process.pid
    fs.writeFileSync(tmp, JSON.stringify(campaign, null, 2), 'utf8')
    fs.renameSync(tmp, target)
  }
  function row(item) {
    const state = ['queued', 'running', 'ready', 'failed', 'canceled', 'cancelled'].includes(item.state) ? item.state : 'queued'
    return {
      video_id: item.video_id || '',
      job_id: item.job_id || null,
      title: item.title || '',
      cover_url: item.cover_url || '',
      uploader: item.uploader || '',
      views: Number(item.views) || 0,
      duration_ms: Number(item.duration_ms) || 0,
      source: item.source || '',
      reason: item.reason || '',
      primary: item.primary === true,
      origin: 'shortlist',
      state,
      error_message: item.error_message || undefined,
      error_code: item.error_code || undefined,
      revived: item.revived === true ? true : undefined,
      campaign_id: item.campaign_id || undefined,
    }
  }
  function snapshot(campaign) {
    return {
      id: campaign.id,
      session_id: campaign.session_id || null,
      status: campaign.status || 'running',
      process_limit: campaign.process_limit,
      total: campaign.items.length,
      started: campaign.items.filter((x) => x.job_id).length,
      ready: campaign.items.filter((x) => x.state === 'ready').length,
      failed: campaign.items.filter((x) => x.state === 'failed').length,
      queued: campaign.items.filter((x) => x.state === 'queued').length,
      items: campaign.items.map(row),
    }
  }
  function failPending(campaign, code, message) {
    for (const item of campaign.items.filter((item) => item.state === 'queued')) {
      item.state = 'failed'
      item.error_code = code
      item.error_message = message
    }
    campaign.status = 'failed'
    campaign.error_message = message
  }
  async function startWave(campaign) {
    const wave = campaign.items.filter((x) => x.state === 'queued').slice(0, Math.max(1, campaign.process_limit))
    if (!wave.length) {
      campaign.status = campaign.items.some((x) => x.state === 'running' || x.state === 'queued') ? 'running' : 'complete'
      campaign.updated_at = new Date().toISOString()
      write(campaign)
      return campaign
    }
    let started
    try {
      // Waves belong to the campaign's session: without it the anon idempotency
      // key made two conversations' campaigns reuse each other's jobs.
      started = await startShortlistJobs(wave.map((x) => ({ ...x, checked: true })), undefined, campaign.session_id || '')
    } catch (e) {
      failPending(campaign, 'E_INGEST', String(e && e.message || e).slice(0, 300))
      campaign.updated_at = new Date().toISOString()
      write(campaign)
      return campaign
    }
    const unavailable = started.failed[0]
    if (!started.jobs.length && started.failed.length === wave.length && unavailable
      && ['E_SPAWN', 'E_FFMPEG'].includes(unavailable.error_code)
      && started.failed.every((item) => item.error_code === unavailable.error_code)) {
      // A missing engine/dependency affects the entire campaign. A video-specific
      // failure leaves the next wave queued and eligible to advance.
      failPending(campaign, unavailable.error_code, unavailable.error_message || 'ingest failed')
      campaign.updated_at = new Date().toISOString()
      write(campaign)
      return campaign
    }
    const byVideo = new Map(started.jobs.map((j) => [String(j.video_id || ''), j]))
    const failedByVideo = new Map(started.failed.map((j) => [String(j.video_id || ''), j]))
    for (const item of wave) {
      const job = byVideo.get(String(item.video_id || ''))
      const failed = failedByVideo.get(String(item.video_id || ''))
      if (job) {
        item.job_id = job.job_id
        item.state = 'running'
      } else if (failed) {
        item.state = 'failed'
        item.job_id = null
        item.error_message = failed.error_message || 'ingest failed'
        item.error_code = failed.error_code || 'E_INGEST'
      } else {
        item.state = 'failed'
        item.error_message = 'wave did not return a job'
      }
    }
    campaign.status = campaign.items.some((x) => x.state === 'running' || x.state === 'queued') ? 'running' : 'complete'
    campaign.updated_at = new Date().toISOString()
    write(campaign)
    return campaign
  }
  async function tickInner(id, allowStart = true) {
    const campaign = read(id)
    if (!campaign) return campaign
    // A campaign we gave up on may still have a false E_WORKER_LOST row inside:
    // keep ticking it while such a row exists so a late ready sidecar can
    // correct it. An aborted (failed) campaign is otherwise terminal.
    const hasRevivable = campaign.aborted !== true && (campaign.items || []).some(
      (x) => x && x.state === 'failed' && x.error_code === 'E_WORKER_LOST' && x.revived !== true)
    if (!hasRevivable && (campaign.status === 'complete' || campaign.status === 'failed')) return campaign
    let changed = false
    for (const item of campaign.items) {
      // A row we already gave up on may still be alive: re-check it so a late
      // ready sidecar can correct a false E_WORKER_LOST.
      const revivable = item.state === 'failed' && item.error_code === 'E_WORKER_LOST'
        && item.revived !== true
      if (!item.job_id || !(revivable || ['running', 'queued'].includes(item.state))) continue
      const job = readJobSidecar(item.job_id)
      if (!job) {
        // A missing sidecar used to be retried forever: a crashed worker kept
        // the wave "running" and the next wave never started. A row we already
        // marked failed is not counted again (the count would grow unbounded).
        if (revivable) continue
        item.missing_ticks = (Number(item.missing_ticks) || 0) + 1
        // Persist the counter: without changed=true the tick never writes, so
        // the limit was only ever true inside one in-memory call.
        changed = true
        // ~10 minutes, not 100s: a long download or a cloud ASR pass (up to
        // 499s) legitimately leaves the sidecar untouched for minutes.
        if (item.missing_ticks >= 240) {
          item.state = 'failed'
          item.error_code = 'E_WORKER_LOST'
          item.error_message = '后台任务状态丢失（sidecar 不存在）'
          changed = true
        }
        continue
      }
      if (Number(item.missing_ticks) > 0) {
        item.missing_ticks = 0
        changed = true
      }
      const state = String(job.state || '')
      // 'done' is the CLI's success synonym; an unknown/legacy value must not be
      // read as "running" or the campaign would never complete.
      const terminal = ['ready', 'failed', 'canceled', 'cancelled']
      const normalized = state === 'done' ? 'ready' : state
      if (terminal.includes(normalized)) {
        if (item.state !== normalized || item.error_code) {
          item.state = normalized
          item.error_message = job.error_message || undefined
          item.error_code = job.error_code || undefined
          if (revivable) item.revived = true
          changed = true
        }
      } else if (revivable && normalized === 'running') {
        // One revival per row: otherwise a permanently dead sidecar would keep
        // the campaign "running" forever.
        item.state = 'running'
        item.error_message = undefined
        item.error_code = undefined
        item.revived = true
        campaign.status = 'running'
        changed = true
      }
    }
    if (allowStart && !campaign.items.some((x) => x.state === 'running') && campaign.items.some((x) => x.state === 'queued')) {
      return startWave(campaign)
    }
    if (!campaign.items.some((x) => ['running', 'queued'].includes(x.state))) {
      campaign.status = 'complete'
      changed = true
    }
    if (changed) {
      campaign.updated_at = new Date().toISOString()
      write(campaign)
    }
    return campaign
  }
  async function start(selected, sessionId, processLimit) {
    const id = 'campaign_' + crypto.randomBytes(6).toString('hex')
    const items = selected.map((candidate) => ({
      candidate_id: candidate.candidate_id || '',
      video_id: String(candidate.video_id || ''),
      platform: String(candidate.platform || 'bilibili'),
      url: candidate.url ? String(candidate.url) : '',
      title: String(candidate.title || ''),
      uploader: String(candidate.uploader || ''),
      views: Number(candidate.stats && candidate.stats.play) || 0,
      duration_ms: Number(candidate.duration_ms) || 0,
      cover_url: candidate.cover_url || '',
      source: candidate.url || (candidate.platform === 'douyin'
        ? 'https://www.douyin.com/video/' + candidate.video_id
        : 'https://www.bilibili.com/video/' + candidate.video_id),
      reason: candidate.reason || '',
      primary: candidate.primary === true,
      state: 'queued',
      job_id: null,
      campaign_id: id,
    }))
    const campaign = {
      version: 1,
      id,
      session_id: sessionId || null,
      created_at: new Date().toISOString(),
      updated_at: new Date().toISOString(),
      process_limit: Math.max(1, Number(processLimit) || 10),
      status: 'running',
      items,
    }
    write(campaign)
    const promise = startWave(campaign).finally(() => inFlight.delete(campaign.id))
    inFlight.set(campaign.id, { promise, advances: true })
    return promise
  }
  function tick(id) {
    // Two pollers (client route + model command) must not start the same wave
    // twice. Reuse the in-flight promise instead of duplicating jobs.
    const pending = inFlight.get(id)
    if (pending) return pending.advances ? pending.promise : pending.promise.then(() => tick(id))
    const promise = tickInner(id, true).finally(() => inFlight.delete(id))
    inFlight.set(id, { promise, advances: true })
    return promise
  }
  function refresh(id) {
    // Read-only poll: reconcile finished rows but never spawn a new wave. The
    // GET route uses this so prefetch/refresh cannot start downloads.
    const pending = inFlight.get(id)
    if (pending) return pending.promise
    const promise = tickInner(id, false).finally(() => inFlight.delete(id))
    inFlight.set(id, { promise, advances: false })
    return promise
  }
  function abort(id, message) {
    const campaign = read(id)
    if (!campaign) return null
    campaign.status = 'failed'
    // Marks a user stop: revival must not silently turn it back into "complete".
    campaign.aborted = true
    campaign.error_message = String(message || 'campaign stopped').slice(0, 300)
    campaign.updated_at = new Date().toISOString()
    write(campaign)
    return campaign
  }
  function get(id) { return read(id) }

  // A retried campaign:true must find the campaign it already started, not
  // start a second one. In-memory TTLs expire while a wave runs for minutes, so
  // look on disk for an unfinished campaign with the same session and videos.
  function findActive(sessionId, videoIds, maxAgeMs = 6 * 60 * 60 * 1000) {
    const wanted = [...new Set((videoIds || []).map(String))].sort().join(',')
    if (!wanted) return null
    let names = []
    try { names = fs.readdirSync(dir()) } catch { return null }
    let best = null
    for (const name of names) {
      if (!name.endsWith('.json')) continue
      const candidate = read(name.slice(0, -5))
      if (!candidate || !candidate.id) continue
      if (candidate.status === 'complete' || candidate.status === 'failed') continue
      if (String(candidate.session_id || '') !== String(sessionId || '')) continue
      const have = [...new Set((candidate.items || []).map((x) => String(x.video_id || '')))].sort().join(',')
      if (have !== wanted) continue
      // An unparseable timestamp must not win: it used to be treated as the
      // newest and could resurrect a stale campaign.
      const parsed = Date.parse(candidate.updated_at || candidate.created_at || '')
      // An unparseable timestamp cannot be aged, so it must not compete: skipping
      // the age check let an arbitrarily old campaign be reused.
      if (!Number.isFinite(parsed)) continue
      const at = parsed
      if (Date.now() - at > maxAgeMs) continue
      if (!best || at > best.at) best = { at, id: candidate.id }
    }
    return best ? best.id : null
  }
  return { start, tick, refresh, get, abort, snapshot, findActive }
}

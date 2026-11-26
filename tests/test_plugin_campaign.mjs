import assert from 'node:assert/strict'
import fs from 'node:fs'
import os from 'node:os'
import path from 'node:path'
import { createCampaignManager } from '../packages/dsh-video2agent/campaign.js'

const home = fs.mkdtempSync(path.join(os.tmpdir(), 'vp-campaign-'))
const started = []
const jobStates = new Map()
let seq = 0
let failFirst = false
const startShortlistJobs = async (selected) => {
  started.push(selected.map((c) => c.video_id))
  const failed = failFirst && selected.length ? [{ video_id: selected[0].video_id, job_id: null, state: 'failed', error_message: 'mock failure' }] : []
  failFirst = false
  return {
    jobs: selected.filter((c) => !failed.some((f) => f.video_id === c.video_id)).map((c) => ({ video_id: c.video_id, job_id: 'job_' + (++seq), state: 'running' })),
    failed,
    reused: false,
  }
}
const missingJobs = new Set()
const readJobSidecar = (id) => (missingJobs.has(id) ? null : ({ id, state: jobStates.get(id) || 'running' }))
const campaigns = createCampaignManager({ home: () => home, startShortlistJobs, readJobSidecar })
const candidates = Array.from({ length: 25 }, (_, i) => ({
  video_id: 'BV1camp' + String(i).padStart(3, '0'),
  title: 'video ' + i,
  uploader: 'up',
  stats: { play: 12345 + i },
  duration_ms: 1000 + i,
  cover_url: '',
  reason: '',
  primary: i === 0,
}))
const c = await campaigns.start(candidates, 'session-a', 10)
assert.equal(c.id.startsWith('campaign_'), true)
let snap = campaigns.snapshot(c)
assert.equal(snap.total, 25)
assert.equal(snap.started, 10)
assert.equal(snap.queued, 15)
assert.equal(snap.status, 'running')
assert.equal(started.length, 1)
assert.equal(started[0].length, 10)

// Finish wave 1; the next poll must start wave 2, not all 25 at once.
for (const item of c.items.filter((x) => x.state === 'running')) jobStates.set(item.job_id, 'ready')
await campaigns.tick(c.id)
let current = campaigns.get(c.id)
snap = campaigns.snapshot(current)
assert.equal(started.length, 2)
assert.equal(started[1].length, 10)
assert.equal(snap.queued, 5)
assert.equal(started.reduce((n, w) => Math.max(n, w.length), 0), 10, 'a wave must not exceed processLimit')

// Finish wave 2; wave 3 is the remaining five.
for (const item of current.items.filter((x) => x.state === 'running')) jobStates.set(item.job_id, 'ready')
await campaigns.tick(c.id)
current = campaigns.get(c.id)
snap = campaigns.snapshot(current)
assert.equal(started.length, 3)
assert.equal(started[2].length, 5)
assert.equal(snap.queued, 0)

// Finish the final wave; the campaign becomes complete with every row ready.
for (const item of current.items.filter((x) => x.state === 'running')) jobStates.set(item.job_id, 'ready')
await campaigns.tick(c.id)
snap = campaigns.snapshot(campaigns.get(c.id))
assert.equal(snap.status, 'complete')
assert.equal(snap.ready, 25)
assert.equal(snap.failed, 0)
assert.equal(snap.started, 25)
assert.equal(campaigns.get(c.id).items.length, 25)
// A failed row must not block later waves.
const failureCandidates = Array.from({ length: 12 }, (_, i) => ({
  video_id: 'BV1fail' + String(i).padStart(3, '0'),
  title: 'failure video ' + i,
  stats: { play: 1 },
}))
failFirst = true
const failedCampaign = await campaigns.start(failureCandidates, 'session-b', 10)
let failedSnap = campaigns.snapshot(failedCampaign)
assert.equal(failedSnap.failed, 1)
assert.equal(failedSnap.queued, 2)
for (const item of failedCampaign.items.filter((x) => x.state === 'running')) jobStates.set(item.job_id, 'ready')
await campaigns.tick(failedCampaign.id)
failedSnap = campaigns.snapshot(campaigns.get(failedCampaign.id))
assert.equal(failedSnap.queued, 0, 'the failed row must not block wave 2')
for (const item of campaigns.get(failedCampaign.id).items.filter((x) => x.state === 'running')) jobStates.set(item.job_id, 'ready')
await campaigns.tick(failedCampaign.id)
failedSnap = campaigns.snapshot(campaigns.get(failedCampaign.id))
assert.equal(failedSnap.status, 'complete')
assert.equal(failedSnap.failed, 1)
assert.equal(failedSnap.ready, 11)
assert.equal(failedSnap.total, 12)

// If every video in the first wave fails independently, a read-only refresh
// leaves later waves queued. Concurrent advancing requests start exactly one.
failFirst = true
const recovered = await campaigns.start(failureCandidates.slice(0, 3), 'session-recover', 1)
assert.equal(recovered.items[0].state, 'failed')
assert.equal(recovered.status, 'running')
const beforeAdvance = started.length
const refresh = campaigns.refresh(recovered.id)
const advance = campaigns.tick(recovered.id)
const duplicateAdvance = campaigns.tick(recovered.id)
assert.equal((await refresh).items[1].state, 'queued')
const [afterAdvance] = await Promise.all([advance, duplicateAdvance])
assert.equal(afterAdvance.items[1].state, 'running')
assert.equal(afterAdvance.items[2].state, 'queued')
assert.equal(started.length, beforeAdvance + 1, 'concurrent advance must start only one wave')

// Infrastructure failures affect all selections. Do not start each later wave
// only to repeat the same failure.
let systemAttempts = 0
const unavailable = createCampaignManager({
  home: () => home, readJobSidecar,
  startShortlistJobs: async (selected) => {
    systemAttempts++
    return { jobs: [], failed: selected.map((item) => ({
      video_id: item.video_id, error_code: 'E_SPAWN', error_message: 'engine unavailable',
    })) }
  },
})
const blocked = await unavailable.start(failureCandidates.slice(0, 3), 'session-blocked', 1)
assert.equal(blocked.status, 'failed')
assert.ok(blocked.items.every((item) => item.state === 'failed' && item.error_code === 'E_SPAWN' && !item.job_id))
await unavailable.tick(blocked.id)
assert.equal(systemAttempts, 1, 'an unavailable engine must not start later waves')

// A vanished sidecar must fail the row after 240 ticks instead of keeping the
// campaign "running" forever (a crashed worker).
const missingCampaign = await campaigns.start([{
  video_id: 'BV1missing001', title: 'missing', stats: { play: 1 },
}], 'session-m', 10)
for (const item of campaigns.get(missingCampaign.id).items) {
  if (item.job_id) missingJobs.add(item.job_id)
}
for (let i = 0; i < 250; i++) await campaigns.tick(missingCampaign.id)
const missingSnap = campaigns.snapshot(campaigns.get(missingCampaign.id))
assert.equal(missingSnap.items[0].state, 'failed', 'a missing sidecar must eventually fail')
assert.equal(campaigns.get(missingCampaign.id).items[0].error_code, 'E_WORKER_LOST')
assert.equal(missingSnap.status, 'complete')

// A late sidecar must be able to correct a false E_WORKER_LOST, even though the
// campaign already reported complete.
const revivedJobId = campaigns.get(missingCampaign.id).items[0].job_id
missingJobs.delete(revivedJobId)
jobStates.set(revivedJobId, 'done')
await campaigns.tick(missingCampaign.id)
const revivedSnap = campaigns.snapshot(campaigns.get(missingCampaign.id))
assert.equal(revivedSnap.items[0].state, 'ready', 'a late done sidecar did not correct the row')
assert.equal(revivedSnap.items[0].error_code, undefined)
assert.equal(revivedSnap.status, 'complete')
// 'done' must not be read as running (that left the campaign running forever).
assert.equal(campaigns.get(missingCampaign.id).items[0].revived, true)



// A user/start-failure abort is terminal: a late ready sidecar must not revive it.
{
  const aborted = await campaigns.start([{
    video_id: 'BV1abort0001', title: 'abort', stats: { play: 1 },
  }], 'session-abort', 10)
  const abortedJobId = campaigns.get(aborted.id).items[0].job_id
  missingJobs.add(abortedJobId)
  for (let i = 0; i < 250; i++) await campaigns.tick(aborted.id)
  assert.equal(campaigns.get(aborted.id).items[0].error_code, 'E_WORKER_LOST')
  campaigns.abort(aborted.id, 'stopped by the user')
  assert.equal(campaigns.get(aborted.id).aborted, true)
  // The worker was only slow: its sidecar turns ready after the abort.
  missingJobs.delete(abortedJobId)
  jobStates.set(abortedJobId, 'ready')
  await campaigns.tick(aborted.id)
  const abortedSnap = campaigns.snapshot(campaigns.get(aborted.id))
  assert.equal(abortedSnap.status, 'failed', 'an aborted campaign came back to life')
  assert.equal(abortedSnap.items[0].state, 'failed', 'an aborted row was revived')
}
// An unparseable timestamp cannot be aged, so it must not be reused.
{
  const c3 = await campaigns.start([{
    video_id: 'BV1finder001', title: 'finder', stats: { play: 1 },
  }], 'session-find', 10)
  const file = path.join(home, 'campaigns', c3.id + '.json')
  const raw = JSON.parse(fs.readFileSync(file, 'utf8'))
  raw.updated_at = 'not-a-date'
  raw.created_at = 'not-a-date'
  fs.writeFileSync(file, JSON.stringify(raw, null, 2), 'utf8')
  assert.equal(campaigns.findActive('session-find', ['BV1finder001']), null,
    'a campaign with an unparseable timestamp must not be reused')
}
console.log('campaign ok: 25 videos -> 3 waves, max 10, all ready; a failed row does not block wave 2; a missing sidecar fails after 240 ticks; a late sidecar revives once; an aborted campaign never revives; an unparseable campaign is not reused')

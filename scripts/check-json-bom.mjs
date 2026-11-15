#!/usr/bin/env node
import fs from 'node:fs'

const paths = process.argv.slice(2)
if (!paths.length) {
  console.error('usage: node scripts/check-json-bom.mjs <file> [...file]')
  process.exit(2)
}

let failed = false
for (const p of paths) {
  try {
    const bytes = fs.readFileSync(p)
    if (bytes.length >= 3 && bytes[0] === 0xef && bytes[1] === 0xbb && bytes[2] === 0xbf) {
      console.error('BOM: ' + p)
      failed = true
      continue
    }
    JSON.parse(bytes.toString('utf8'))
    console.log('ok: ' + p)
  } catch (e) {
    console.error('FAIL: ' + p + ' — ' + (e?.message || e))
    failed = true
  }
}
process.exit(failed ? 1 : 0)

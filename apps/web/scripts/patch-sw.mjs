// bumps the service worker cache name per build: every deploy gets a
// fresh shell cache, so users never see stale assets after a release
// (three stale-cache incidents: nemo's qa round, muse's audit race,
// the missing digest ui - all the same root cause)
import { readFileSync, writeFileSync } from 'node:fs'

const index = readFileSync('dist/index.html', 'utf8')
const m = index.match(/index-([A-Za-z0-9_-]+)\.js/)
if (!m) throw new Error('no asset hash found in dist/index.html')
const sw = readFileSync('dist/sw.js', 'utf8')
const patched = sw.replace(/vozonda-shell-v[^'"]*/, `vozonda-shell-${m[1]}`)
writeFileSync('dist/sw.js', patched)
console.log('sw cache name ->', `vozonda-shell-${m[1]}`)

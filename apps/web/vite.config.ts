import { defineConfig } from 'vite'
import { svelte } from '@sveltejs/vite-plugin-svelte'

// VOZONDA_API_PROXY points the dev server and preview at another API (e2e checks); default the local one
const API = process.env.VOZONDA_API_PROXY || 'http://127.0.0.1:8787'

// Top-level API paths, shared by the dev server and the preview. Until
// 2026-09-28 two hand-kept copies lacked /llm, /music, /shows and /storage:
// the preview answered those with index.html, so the settings page showed
// the LLM as offline and the music and show lists stayed empty.
// Check against the API: every top-level path of vozonda_api.main.app.routes
// (apps/api/tests/test_vite_proxy_paths.py enforces it; 2026-10-02 /distribution was missing).
const API_PATHS = [
  '/audio', '/auth', '/clips', '/doctor', '/e', '/health', '/img', '/jobs', '/llm', '/llms.txt',
  '/meta', '/music', '/plugins', '/providers', '/settings', '/share', '/shows', '/source', '/sources', '/srt',
  '/storage', '/tts', '/vtt', '/watchlist', '/feed.xml', '/docs', '/redoc', '/openapi.json',
  '/distribution', '/billing', '/feed', '/styles', '/og-default.png', '/update-check'
]
// changeOrigin rewrites the Host header to the API's, so the API cannot tell from it that a request came
// from another machine (preview runs with --host). Pass the client address on when it is not loopback;
// the API then treats the request as remote and asks for the token (GHSA-crq5-73gf-fv2h).
const LOOPBACK = /^(127\.|::1$|::ffff:127\.)/
const proxyOptions = {
  target: API,
  changeOrigin: true,
  configure: (proxy: { on: (ev: string, fn: (proxyReq: any, req: any) => void) => void }) => {
    proxy.on('proxyReq', (proxyReq, req) => {
      const ip: string = req.socket?.remoteAddress || ''
      if (ip && !LOOPBACK.test(ip) && !req.headers['x-forwarded-for']) proxyReq.setHeader('X-Forwarded-For', ip)
    })
  }
}
const proxy: Record<string, typeof proxyOptions> = Object.fromEntries(API_PATHS.map((p) => [p, proxyOptions]))
// per-show feeds are /{show}/{name}/feed.xml (podcast apps fetch them through the preview too)
proxy['^/[^/]+/[^/]+/feed\\.xml(\\?.*)?$'] = proxyOptions  // Vite matches the url with its query

// Vite answers only host names it knows; the address other devices use (VOZONDA_PUBLIC_URL in .env,
// e.g. the machine's Tailscale name) is one of them. VOZONDA_ALLOWED_HOSTS adds more, comma-separated.
const allowedHosts = [process.env.VOZONDA_PUBLIC_URL, ...(process.env.VOZONDA_ALLOWED_HOSTS || '').split(',')]
  .map((v) => (v || '').trim())
  .filter(Boolean)
  .map((v) => { try { return new URL(v.includes('://') ? v : `http://${v}`).hostname } catch { return '' } })
  .filter(Boolean)

export default defineConfig({
  plugins: [svelte()],
  server: { proxy, allowedHosts },
  preview: { proxy, allowedHosts }
})

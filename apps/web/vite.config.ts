import { defineConfig } from 'vite'
import { svelte } from '@sveltejs/vite-plugin-svelte'

const API = 'http://127.0.0.1:8787'

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
  '/distribution', '/billing', '/feed', '/styles', '/og-default.png'
]
const proxy = Object.fromEntries(API_PATHS.map((p) => [p, API]))

export default defineConfig({
  plugins: [svelte()],
  server: { proxy },
  preview: { proxy }
})

import { mount } from 'svelte'
import '@fontsource-variable/source-serif-4'
import '@fontsource-variable/jetbrains-mono'
import './lib/styles/tokens.css'
import App from './App.svelte'

// A tab opened before a deploy still runs the old bundle; its lazy screens
// (faq, about, agents, ...) point at chunks the new build deleted, so they
// failed with "failed to load" and retry could never succeed. Reload once to
// pick up the new build; the timestamp guard stops a loop if a chunk is
// really broken.
window.addEventListener('vite:preloadError', (event) => {
  const key = 'vozonda.chunkReloadAt'
  let last = 0
  try { last = Number(sessionStorage.getItem(key)) || 0 } catch {}
  if (Date.now() - last < 10_000) return
  try { sessionStorage.setItem(key, String(Date.now())) } catch {}
  event.preventDefault()
  location.reload()
})

const app = mount(App, {
  target: document.getElementById('app') as HTMLElement
})

if ('serviceWorker' in navigator) {
  window.addEventListener('load', () => {
    navigator.serviceWorker.register('/sw.js').catch(() => {})
  })
}

export default app

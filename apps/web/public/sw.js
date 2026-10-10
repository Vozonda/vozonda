/* vozonda service worker v3 - shell and offline audio caching */
const SHELL_CACHE = 'vozonda-shell-v3'
const AUDIO_CACHE = 'vozonda-audio-v2'
const OFFLINE_URL = '/offline.html'
const SHELL_URLS = [OFFLINE_URL, '/']

self.addEventListener('install', (event) => {
  self.skipWaiting()
  event.waitUntil(
    caches.open(SHELL_CACHE).then((cache) => cache.addAll(SHELL_URLS)).catch(() => {})
  )
})

self.addEventListener('activate', (event) => {
  event.waitUntil(
    (async () => {
      const keys = await caches.keys()
      const allowed = new Set([SHELL_CACHE, AUDIO_CACHE])
      await Promise.all(keys.filter((k) => !allowed.has(k)).map((k) => caches.delete(k)))
      await self.clients.claim()
    })()
  )
})

self.addEventListener('message', (event) => {
  if (event.data === 'SKIP_WAITING') self.skipWaiting()
})

// Every API path is network-first: served from the asset cache, /auth/session kept answering
// "not signed in" after a sign-in (GHSA-crq5-73gf-fv2h), and other JSON could go stale the same way.
const API_PREFIXES = ['/jobs', '/providers', '/meta', '/settings', '/watchlist', '/feed.xml', '/doctor',
  '/health', '/e/', '/auth', '/shows', '/sources', '/source/', '/styles', '/plugins', '/storage', '/clips',
  '/vtt/', '/srt/', '/llm', '/distribution', '/billing', '/tts']

function isApiRequest(url) {
  return API_PREFIXES.some((p) => url.pathname.startsWith(p)) || url.pathname.endsWith('/feed.xml')
}

function isAudioRequest(url) {
  return url.pathname.startsWith('/audio/')
}

self.addEventListener('fetch', (event) => {
  const req = event.request
  const url = new URL(req.url)

  // only handle GET, same-origin
  if (req.method !== 'GET' || url.origin !== self.location.origin) return

  // audio: cache-first with network fallback and background cache storage
  if (isAudioRequest(url)) {
    event.respondWith(
      (async () => {
        const audioCache = await caches.open(AUDIO_CACHE)
        const cached = await audioCache.match(req.url)
        if (cached) return cached
        try {
          const resp = await fetch(req)
          if (resp && (resp.status === 200 || resp.status === 206)) {
            // Cache audio stream
            try {
              await audioCache.put(req.url, resp.clone())
            } catch {}
          }
          return resp
        } catch {
          return new Response('', { status: 504, statusText: 'offline' })
        }
      })()
    )
    return
  }

  // api: network first, no cache
  if (isApiRequest(url)) {
    event.respondWith(
      fetch(req)
        .then((res) => res)
        .catch(() => caches.match(req).then((cached) => cached || Promise.reject('offline')))
    )
    return
  }

  // navigations: network first with offline fallback, cache html
  const isNavigation = req.mode === 'navigate' || req.headers.get('accept')?.includes('text/html')
  if (isNavigation) {
    event.respondWith(
      (async () => {
        try {
          const network = await fetch(req)
          const cache = await caches.open(SHELL_CACHE)
          cache.put(req, network.clone())
          return network
        } catch {
          const cached = await caches.match(req)
          if (cached) return cached
          const offline = await caches.match(OFFLINE_URL)
          if (offline) return offline
          return new Response('offline', { status: 503, headers: { 'content-type': 'text/plain' } })
        }
      })()
    )
    return
  }

  // assets (js, css, fonts, images): stale-while-revalidate
  event.respondWith(
    (async () => {
      const cache = await caches.open(SHELL_CACHE)
      const cached = await cache.match(req)
      const networkFetch = fetch(req)
        .then((res) => {
          if (res && res.status === 200) cache.put(req, res.clone())
          return res
        })
        .catch(() => undefined)
      if (cached) {
        // update in background
        event.waitUntil(networkFetch)
        return cached
      }
      const network = await networkFetch
      if (network) return network
      return new Response('', { status: 504 })
    })()
  )
})

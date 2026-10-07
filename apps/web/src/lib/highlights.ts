/** NIP-84 Highlights (kind 9802) helpers for vozonda frontend.
 * Mirrors the python module: event construction, validation, relay query.
 * Also provides publish + fetch helpers that do not block audio.
 */

import { signWithExtension, hasNip07Extension, type NostrEventTemplate, type NostrSignedEvent } from './nostr'

export const HIGHLIGHT_KIND = 9802
export const MAX_HIGHLIGHT_LENGTH = 2000
export const MAX_CONTEXT_LENGTH = 5000
export const DEFAULT_ALT = 'highlight'
export const DEFAULT_RELAYS = ['wss://relay.damus.io', 'wss://nos.lol']

const TRACKER_PARAMS = new Set(['utm_source', 'utm_medium', 'utm_campaign', 'utm_term', 'utm_content', 'fbclid', 'gclid', 'msclkid', 'igshid'])

/** Best effort clean: strip utm_* and tracker params + fragment. */
export function cleanHighlightUrl(url: string): string {
  const trimmed = url.trim()
  if (!trimmed) throw new Error('url must be non-empty')
  let parsed: URL
  try {
    parsed = new URL(trimmed)
  } catch {
    throw new Error(`invalid url: ${trimmed}`)
  }
  if (parsed.protocol !== 'http:' && parsed.protocol !== 'https:') throw new Error('url must be http(s)')
  // remove tracker params
  const toDelete: string[] = []
  parsed.searchParams.forEach((_v, k) => {
    if (TRACKER_PARAMS.has(k) || k.startsWith('utm_')) toDelete.push(k)
  })
  for (const k of toDelete) parsed.searchParams.delete(k)
  parsed.hash = ''
  return parsed.toString()
}

export interface HighlightTemplate extends NostrEventTemplate {
  kind: typeof HIGHLIGHT_KIND
}

export interface HighlightParsed {
  id?: string
  pubkey?: string
  content: string
  sourceUrl: string
  alt: string
  context?: string
  authorPubkeys: string[]
  pTags: string[][]
  createdAt: number
  tags: string[][]
}

export function buildHighlightEvent(opts: {
  content: string
  sourceUrl: string
  context?: string | null
  authorPubkey?: string | null
  authorRelay?: string | null
  authorRole?: string | null
  alt?: string | null
}): HighlightTemplate {
  const { content, sourceUrl, context, authorPubkey, authorRelay, authorRole, alt } = opts
  if (!content || !content.trim()) throw new Error('content must be non-empty highlighted text')
  const trimmed = content.trim()
  if (trimmed.length > MAX_HIGHLIGHT_LENGTH) throw new Error(`content too long (max ${MAX_HIGHLIGHT_LENGTH})`)
  if (!sourceUrl || !sourceUrl.trim()) throw new Error('sourceUrl must be non-empty')
  const cleaned = cleanHighlightUrl(sourceUrl)
  const tags: string[][] = [
    ['r', cleaned],
    ['alt', (alt?.trim() || DEFAULT_ALT).slice(0, 200)]
  ]
  if (context && context.trim()) {
    const ctx = context.trim()
    if (ctx.length > MAX_CONTEXT_LENGTH) throw new Error(`context too long (max ${MAX_CONTEXT_LENGTH})`)
    tags.push(['context', ctx])
  }
  if (authorPubkey) {
    const hex = authorPubkey.trim().toLowerCase()
    if (!/^[0-9a-f]{64}$/.test(hex)) throw new Error('authorPubkey must be 64 hex')
    const pTag: string[] = ['p', hex]
    if (authorRelay?.trim()) {
      pTag.push(authorRelay.trim())
      if (authorRole) pTag.push(authorRole)
    } else if (authorRole) {
      pTag.push('')
      pTag.push(authorRole)
    }
    tags.push(pTag)
  }

  return {
    kind: HIGHLIGHT_KIND,
    created_at: Math.floor(Date.now() / 1000),
    tags,
    content: trimmed
  }
}

export function isValidHighlight(event: Record<string, unknown>): { ok: boolean; reason: string } {
  if (!event || typeof event !== 'object') return { ok: false, reason: 'event must be object' }
  if ((event as Record<string, unknown>).kind !== HIGHLIGHT_KIND) return { ok: false, reason: `kind must be ${HIGHLIGHT_KIND}` }
  const content = (event as Record<string, unknown>).content
  if (typeof content !== 'string') return { ok: false, reason: 'content must be string' }
  if (!content.trim()) return { ok: false, reason: 'content must be non-empty' }
  if (content.length > MAX_HIGHLIGHT_LENGTH) return { ok: false, reason: `content too long (max ${MAX_HIGHLIGHT_LENGTH})` }
  const tags = (event as Record<string, unknown>).tags
  if (!Array.isArray(tags)) return { ok: false, reason: 'tags must be array' }
  const rTags = (tags as unknown[]).filter((t) => Array.isArray(t) && (t as string[])[0] === 'r')
  if (rTags.length === 0) return { ok: false, reason: 'missing r tag' }
  for (const t of rTags as string[][]) {
    if (t.length < 2) return { ok: false, reason: 'invalid r tag' }
    try { cleanHighlightUrl(t[1]!) } catch (e) { return { ok: false, reason: `invalid r tag url: ${(e as Error).message}` } }
  }
  const altTags = (tags as unknown[]).filter((t) => Array.isArray(t) && (t as string[])[0] === 'alt')
  if (altTags.length === 0) return { ok: false, reason: 'missing alt tag' }
  for (const t of tags as string[][]) {
    if (Array.isArray(t) && t[0] === 'p') {
      if (t.length < 2 || !/^[0-9a-f]{64}$/i.test(t[1]!)) return { ok: false, reason: 'invalid p tag pubkey' }
    }
    if (Array.isArray(t) && t[0] === 'context') {
      if (t.length < 2 || typeof t[1] !== 'string') return { ok: false, reason: 'invalid context tag' }
      if ((t[1] as string).length > MAX_CONTEXT_LENGTH) return { ok: false, reason: 'context too long' }
    }
  }
  return { ok: true, reason: 'ok' }
}

export function parseHighlight(event: Record<string, unknown>): HighlightParsed | null {
  const { ok } = isValidHighlight(event)
  if (!ok) return null
  const tags = (event as Record<string, unknown>).tags as string[][]
  const rVals = tags.filter((t) => t[0] === 'r').map((t) => t[1]!)
  const altVals = tags.filter((t) => t[0] === 'alt').map((t) => t[1]!)
  const contexts = tags.filter((t) => t[0] === 'context').map((t) => t[1]!)
  const pTags = tags.filter((t) => t[0] === 'p')
  return {
    id: (event as Record<string, unknown>).id as string | undefined,
    pubkey: (event as Record<string, unknown>).pubkey as string | undefined,
    content: (event as Record<string, unknown>).content as string,
    sourceUrl: rVals[0] ?? '',
    alt: altVals[0] ?? DEFAULT_ALT,
    context: contexts[0],
    authorPubkeys: pTags.map((t) => t[1]!.toLowerCase()),
    pTags,
    createdAt: (event as Record<string, unknown>).created_at as number,
    tags
  }
}

export function buildHighlightFilter(sourceUrl: string, limit = 100): Record<string, unknown> {
  if (!sourceUrl || !sourceUrl.trim()) throw new Error('sourceUrl required')
  const cleaned = cleanHighlightUrl(sourceUrl)
  if (limit <= 0 || limit > 500) throw new Error('limit must be 1..500')
  return {
    kinds: [HIGHLIGHT_KIND],
    '#r': [cleaned],
    limit
  }
}

/** Sign via NIP-07 extension if available, otherwise throw (never holds nsec). */
export async function signHighlight(template: NostrEventTemplate): Promise<NostrSignedEvent> {
  if (!hasNip07Extension()) throw new Error('no NIP-07 signer found (install Alby / Amber / nos2x)')
  return await signWithExtension(template)
}

/** Publish a signed highlight to a list of relays (fire-and-forget, best effort). Returns count of acks. */
export async function publishHighlight(
  signed: NostrSignedEvent,
  relays: string[] = DEFAULT_RELAYS,
  timeoutMs = 4000
): Promise<{ ok: number; fail: number }> {
  let ok = 0
  let fail = 0
  const payload = JSON.stringify(['EVENT', signed])
  const promises = relays.map(
    (url) =>
      new Promise<void>((resolve) => {
        let done = false
        let timer: ReturnType<typeof setTimeout> | undefined
        let ws: WebSocket | undefined
        try {
          ws = new WebSocket(url)
        } catch {
          fail++
          resolve()
          return
        }
        timer = setTimeout(() => {
          if (!done) {
            done = true
            try { ws?.close() } catch {}
            fail++
            resolve()
          }
        }, timeoutMs)
        ws.onopen = () => {
          try { ws!.send(payload) } catch {}
        }
        ws.onmessage = (ev) => {
          try {
            const msg = JSON.parse(ev.data as string)
            if (Array.isArray(msg) && msg[0] === 'OK') {
              const success = msg[2] === true
              if (!done) {
                done = true
                clearTimeout(timer)
                if (success) ok++
                else fail++
                try { ws?.close() } catch {}
                resolve()
              }
            }
          } catch {}
        }
        ws.onerror = () => {
          if (!done) {
            done = true
            clearTimeout(timer)
            fail++
            try { ws?.close() } catch {}
            resolve()
          }
        }
        ws.onclose = () => {
          if (!done) {
            done = true
            clearTimeout(timer)
            // if we sent but got no OK, count as fail
            fail++
            resolve()
          }
        }
      })
  )
  await Promise.all(promises)
  return { ok, fail }
}

export type HighlightCategory = 'user' | 'friend' | 'global'

export function categorizeHighlight(
  h: HighlightParsed,
  userPubkey: string | null,
  friendPubkeys: Set<string>
): HighlightCategory {
  const pk = (h.pubkey ?? '').toLowerCase()
  if (userPubkey && pk === userPubkey.toLowerCase()) return 'user'
  if (pk && friendPubkeys.has(pk)) return 'friend'
  return 'global'
}

/** Fetch highlights for a url from relays. Non-blocking: caller should invoke after audio play / idle. */
export function fetchHighlights(
  relays: string[],
  sourceUrl: string,
  onHighlight: (h: HighlightParsed) => void,
  onDone?: () => void,
  timeoutMs = 5000
): () => void {
  const filter = buildHighlightFilter(sourceUrl)
  const subId = `vozonda-hl-${Math.random().toString(36).slice(2, 7)}`
  const req = JSON.stringify(['REQ', subId, filter])
  const close = JSON.stringify(['CLOSE', subId])
  const sockets: WebSocket[] = []
  let finished = false
  let eoseCount = 0
  let timer: ReturnType<typeof setTimeout> | undefined

  const finish = () => {
    if (finished) return
    finished = true
    if (timer) clearTimeout(timer)
    for (const ws of sockets) {
      try { ws.send(close); ws.close() } catch { try { ws.close() } catch {} }
    }
    onDone?.()
  }

  timer = setTimeout(finish, timeoutMs)

  for (const relay of relays) {
    try {
      const ws = new WebSocket(relay)
      sockets.push(ws)
      ws.onopen = () => {
        try { ws.send(req) } catch {}
      }
      ws.onmessage = (ev) => {
        try {
          const msg = JSON.parse(ev.data as string)
          if (Array.isArray(msg) && msg[0] === 'EVENT' && msg[1] === subId) {
            const parsed = parseHighlight(msg[2] as Record<string, unknown>)
            if (parsed) onHighlight(parsed)
          } else if (Array.isArray(msg) && msg[0] === 'EOSE' && msg[1] === subId) {
            eoseCount++
            if (eoseCount >= sockets.length) finish()
          }
        } catch {}
      }
      ws.onerror = () => {}
    } catch {}
  }

  return finish
}

export function getEpisodeHighlightCount(episodeId: string): number {
  if (typeof localStorage === 'undefined' || !episodeId) return 0
  try {
    const raw = localStorage.getItem(`vozonda_hl_count_${episodeId}`)
    return raw ? parseInt(raw, 10) || 0 : 0
  } catch {
    return 0
  }
}

export function incrementEpisodeHighlightCount(episodeId: string): void {
  if (typeof localStorage === 'undefined' || !episodeId) return
  try {
    const current = getEpisodeHighlightCount(episodeId)
    localStorage.setItem(`vozonda_hl_count_${episodeId}`, String(current + 1))
  } catch {}
}

export function setEpisodeHighlightCount(episodeId: string, count: number): void {
  if (typeof localStorage === 'undefined' || !episodeId) return
  try {
    localStorage.setItem(`vozonda_hl_count_${episodeId}`, String(Math.max(0, count)))
  } catch {}
}

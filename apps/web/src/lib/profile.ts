/** Nostr profile (kind 0) fetching and resolution helpers for vozonda. */

import { isValidHexPubkey, isValidNpub, normalizePubkey, hexToNpub, npubToHex } from './nostr'
import { isNip05, verifyNip05 } from './nip05'

export const PROFILE_KIND = 0
export const DEFAULT_RELAYS = ['wss://relay.damus.io', 'wss://nos.lol']
export const PROFILE_TIMEOUT_MS = 5000

export interface NostrProfile {
  pubkey: string
  npub: string
  name?: string
  display_name?: string
  displayName?: string
  picture?: string
  banner?: string
  about?: string
  nip05?: string
  nip05Valid?: boolean
  lud16?: string
  lud06?: string
  website?: string
  raw: Record<string, unknown>
  created_at?: number
  relays: string[]
}

export interface ProfileFetchResult {
  profile: NostrProfile | null
  fromRelay: string | null
  error: string | null
}

export type PubkeyInputKind = 'hex' | 'npub' | 'nip05' | 'invalid'

export function classifyInput(input: string): PubkeyInputKind {
  const t = input.trim()
  if (!t) return 'invalid'
  if (isValidHexPubkey(t)) return 'hex'
  if (isValidNpub(t)) return 'npub'
  if (isNip05(t)) return 'nip05'
  // also support namepart without domain? no
  return 'invalid'
}

export async function resolveInputToPubkey(input: string): Promise<{ hex: string; npub: string; kind: PubkeyInputKind }> {
  const t = input.trim()
  const kind = classifyInput(t)
  if (kind === 'hex') {
    const hex = t.toLowerCase()
    return { hex, npub: hexToNpub(hex), kind }
  }
  if (kind === 'npub') {
    const hex = npubToHex(t)
    return { hex, npub: t.toLowerCase(), kind }
  }
  if (kind === 'nip05') {
    const res = await verifyNip05(t)
    if (!res.valid || !res.pubkey) throw new Error(`nip05 not verified: ${res.reason}`)
    return { hex: res.pubkey, npub: hexToNpub(res.pubkey), kind }
  }
  // try generic normalize (handles hex/npub via nostr.ts)
  try {
    const hex = normalizePubkey(t)
    return { hex, npub: hexToNpub(hex), kind: isValidNpub(t) ? 'npub' : 'hex' }
  } catch {
    throw new Error('invalid identifier (expected npub, hex 64, or nip05 like alice@example.com)')
  }
}

function parseKind0Content(content: string): Record<string, unknown> {
  try {
    const j = JSON.parse(content) as Record<string, unknown>
    if (j && typeof j === 'object') return j
    return {}
  } catch {
    return {}
  }
}

export function buildProfileFromEvent(event: Record<string, unknown>, fallbackHex?: string): NostrProfile | null {
  if (!event || typeof event !== 'object') return null
  if ((event as { kind?: number }).kind !== PROFILE_KIND) return null
  const pubkey = String((event as { pubkey?: string }).pubkey ?? fallbackHex ?? '').toLowerCase()
  if (!/^[0-9a-f]{64}$/.test(pubkey)) return null
  const content = String((event as { content?: string }).content ?? '')
  const meta = parseKind0Content(content)
  const getStr = (k: string): string | undefined => {
    const v = meta[k]
    return typeof v === 'string' && v.trim() ? v.trim() : undefined
  }
  const raw: Record<string, unknown> = meta
  const profile: NostrProfile = {
    pubkey,
    npub: hexToNpub(pubkey),
    name: getStr('name'),
    display_name: getStr('display_name'),
    displayName: getStr('display_name') ?? getStr('displayName'),
    picture: getStr('picture'),
    banner: getStr('banner'),
    about: getStr('about'),
    nip05: getStr('nip05'),
    lud16: getStr('lud16'),
    lud06: getStr('lud06'),
    website: getStr('website'),
    raw,
    created_at: typeof (event as { created_at?: number }).created_at === 'number' ? (event as { created_at: number }).created_at : undefined,
    relays: []
  }
  return profile
}

export function displayNameFor(p: NostrProfile | null): string {
  if (!p) return ''
  return p.display_name ?? p.displayName ?? p.name ?? p.nip05 ?? p.npub.slice(0, 12)
}

export function fetchProfileFromRelays(
  pubkeyHex: string,
  relays: string[] = DEFAULT_RELAYS,
  timeoutMs = PROFILE_TIMEOUT_MS
): Promise<ProfileFetchResult> {
  const hex = pubkeyHex.toLowerCase()
  return new Promise((resolve) => {
    const sockets: WebSocket[] = []
    let done = false
    let best: { event: Record<string, unknown>; relay: string } | null = null
    const subId = `vozonda-p-${Math.random().toString(36).slice(2, 7)}`
    const filter = { kinds: [PROFILE_KIND], authors: [hex], limit: 1 }
    const req = JSON.stringify(['REQ', subId, filter])
    const close = JSON.stringify(['CLOSE', subId])
    let timer: ReturnType<typeof setTimeout> | undefined
    let eoseCount = 0

    const finish = (error: string | null = null) => {
      if (done) return
      done = true
      if (timer) clearTimeout(timer)
      for (const ws of sockets) {
        try { ws.send(close); ws.close() } catch { try { ws.close() } catch {} }
      }
      if (best) {
        const prof = buildProfileFromEvent(best.event, hex)
        if (prof) {
          prof.relays = relays
          resolve({ profile: prof, fromRelay: best.relay, error: null })
          return
        }
      }
      if (error) resolve({ profile: null, fromRelay: null, error })
      else resolve({ profile: null, fromRelay: null, error: best ? 'parse failed' : 'no profile found' })
    }

    timer = setTimeout(() => finish('timeout'), timeoutMs)

    for (const relay of relays) {
      try {
        const ws = new WebSocket(relay)
        sockets.push(ws)
        ws.onopen = () => { try { ws.send(req) } catch {} }
        ws.onmessage = (ev) => {
          try {
            const msg = JSON.parse(ev.data as string)
            if (Array.isArray(msg) && msg[0] === 'EVENT' && msg[1] === subId) {
              const ev2 = msg[2] as Record<string, unknown>
              const ca = typeof ev2.created_at === 'number' ? ev2.created_at : 0
              const bestCa = best && typeof best.event.created_at === 'number' ? (best.event.created_at as number) : -1
              if (!best || ca > bestCa) best = { event: ev2, relay }
            } else if (Array.isArray(msg) && msg[0] === 'EOSE' && msg[1] === subId) {
              eoseCount++
              if (eoseCount >= sockets.length) finish(null)
            }
          } catch {}
        }
        ws.onerror = () => {}
        ws.onclose = () => {}
      } catch {}
    }
    if (sockets.length === 0) finish('no relay connection')
  })
}

export async function verifyProfileNip05(profile: NostrProfile): Promise<NostrProfile> {
  if (!profile.nip05) return profile
  try {
    const res = await verifyNip05(profile.nip05, profile.pubkey)
    return { ...profile, nip05Valid: res.valid }
  } catch {
    return { ...profile, nip05Valid: false }
  }
}

// Zap history: fetch kind 9735 receipts where p = pubkey
export interface ZapHistoryItem {
  id: string
  pubkey: string
  content: string
  bolt11?: string
  amountMsats?: number
  zapRequest?: Record<string, unknown>
  created_at: number
  tags: string[][]
}

function parseZapReceipt(raw: unknown): ZapHistoryItem | null {
  if (!raw || typeof raw !== 'object') return null
  const ev = raw as Record<string, unknown>
  if (ev.kind !== 9735) return null
  const tags = ev.tags
  if (!Array.isArray(tags)) return null
  const t = tags as string[][]
  const bolt11 = t.find((x) => x[0] === 'bolt11')?.[1]
  const amt = t.find((x) => x[0] === 'amount')?.[1]
  let amountMsats: number | undefined
  if (amt) { const n = Number(amt); if (!Number.isNaN(n)) amountMsats = n }
  const desc = t.find((x) => x[0] === 'description')?.[1]
  let zapRequest: Record<string, unknown> | undefined
  if (desc) try { zapRequest = JSON.parse(desc) as Record<string, unknown> } catch {}
  return {
    id: String(ev.id ?? ''),
    pubkey: String(ev.pubkey ?? ''),
    content: String(ev.content ?? ''),
    tags: t,
    bolt11,
    amountMsats,
    zapRequest,
    created_at: typeof ev.created_at === 'number' ? ev.created_at : 0
  }
}

export function fetchZapHistory(
  relays: string[],
  pubkeyHex: string,
  onItem: (z: ZapHistoryItem) => void,
  onDone?: () => void,
  limit = 30,
  timeoutMs = 5000
): () => void {
  const hex = pubkeyHex.toLowerCase()
  const subId = `vozonda-zap-h-${Math.random().toString(36).slice(2, 7)}`
  const filter: Record<string, unknown> = { kinds: [9735], '#p': [hex], limit }
  const req = JSON.stringify(['REQ', subId, filter])
  const close = JSON.stringify(['CLOSE', subId])
  const sockets: WebSocket[] = []
  let finished = false
  let eose = 0
  let timer: ReturnType<typeof setTimeout> | undefined
  const finish = () => {
    if (finished) return
    finished = true
    if (timer) clearTimeout(timer)
    for (const ws of sockets) { try { ws.send(close); ws.close() } catch { try { ws.close() } catch {} } }
    onDone?.()
  }
  timer = setTimeout(finish, timeoutMs)
  for (const relay of relays) {
    try {
      const ws = new WebSocket(relay)
      sockets.push(ws)
      ws.onopen = () => { try { ws.send(req) } catch {} }
      ws.onmessage = (ev) => {
        try {
          const msg = JSON.parse(ev.data as string)
          if (Array.isArray(msg) && msg[0] === 'EVENT' && msg[1] === subId) {
            const z = parseZapReceipt(msg[2])
            if (z) onItem(z)
          } else if (Array.isArray(msg) && msg[0] === 'EOSE' && msg[1] === subId) {
            eose++; if (eose >= sockets.length) finish()
          }
        } catch {}
      }
      ws.onerror = () => {}
    } catch {}
  }
  return finish
}

// Highlights by author: kind 9802 where pubkey == author
export interface AuthorHighlight {
  id: string
  pubkey: string
  content: string
  rTag?: string
  alt?: string
  created_at: number
  tags: string[][]
}

function parseAuthorHighlight(raw: unknown): AuthorHighlight | null {
  if (!raw || typeof raw !== 'object') return null
  const ev = raw as Record<string, unknown>
  if (ev.kind !== 9802) return null
  const tags = ev.tags as string[][] | undefined
  if (!Array.isArray(tags)) return null
  return {
    id: String(ev.id ?? ''),
    pubkey: String(ev.pubkey ?? ''),
    content: String(ev.content ?? ''),
    rTag: tags.find((t) => t[0] === 'r')?.[1],
    alt: tags.find((t) => t[0] === 'alt')?.[1],
    created_at: typeof ev.created_at === 'number' ? ev.created_at : 0,
    tags
  }
}

export function fetchHighlightsByAuthor(
  relays: string[],
  pubkeyHex: string,
  onItem: (h: AuthorHighlight) => void,
  onDone?: () => void,
  limit = 30,
  timeoutMs = 5000
): () => void {
  const hex = pubkeyHex.toLowerCase()
  const subId = `vozonda-hl-a-${Math.random().toString(36).slice(2, 7)}`
  const filter: Record<string, unknown> = { kinds: [9802], authors: [hex], limit }
  const req = JSON.stringify(['REQ', subId, filter])
  const close = JSON.stringify(['CLOSE', subId])
  const sockets: WebSocket[] = []
  let finished = false
  let eose = 0
  let timer: ReturnType<typeof setTimeout> | undefined
  const finish = () => {
    if (finished) return
    finished = true
    if (timer) clearTimeout(timer)
    for (const ws of sockets) { try { ws.send(close); ws.close() } catch { try { ws.close() } catch {} } }
    onDone?.()
  }
  timer = setTimeout(finish, timeoutMs)
  for (const relay of relays) {
    try {
      const ws = new WebSocket(relay)
      sockets.push(ws)
      ws.onopen = () => { try { ws.send(req) } catch {} }
      ws.onmessage = (ev) => {
        try {
          const msg = JSON.parse(ev.data as string)
          if (Array.isArray(msg) && msg[0] === 'EVENT' && msg[1] === subId) {
            const h = parseAuthorHighlight(msg[2])
            if (h) onItem(h)
          } else if (Array.isArray(msg) && msg[0] === 'EOSE' && msg[1] === subId) {
            eose++; if (eose >= sockets.length) finish()
          }
        } catch {}
      }
      ws.onerror = () => {}
    } catch {}
  }
  return finish
}

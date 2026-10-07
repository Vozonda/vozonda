/** Nostr helpers for vozonda: NIP-19 bech32, NIP-07, NIP-46 Amber, npub validation. */

const CHARSET = 'qpzry9x8gf2tvdw0s3jn54khce6mua7l'
const GEN = [0x3b6a57b2, 0x26508e6d, 0x1ea119fa, 0x3d4233dd, 0x2a1462b3]

function polymod(values: number[]): number {
  let chk = 1
  for (const v of values) {
    const top = chk >> 25
    chk = ((chk & 0x1ffffff) << 5) ^ v
    for (let i = 0; i < 5; i++) chk ^= (top >> i) & 1 ? GEN[i]! : 0
  }
  return chk
}
function hrpExpand(hrp: string): number[] {
  return [...hrp].map((c) => c.charCodeAt(0) >> 5).concat([0], [...hrp].map((c) => c.charCodeAt(0) & 31))
}
function verifyChecksum(hrp: string, data: number[]): boolean {
  return polymod(hrpExpand(hrp).concat(data)) === 1
}
function createChecksum(hrp: string, data: number[]): number[] {
  const values = hrpExpand(hrp).concat(data).concat([0, 0, 0, 0, 0, 0])
  const mod = polymod(values) ^ 1
  return Array.from({ length: 6 }, (_, i) => (mod >> (5 * (5 - i))) & 31)
}
function convertBits(data: number[], fromBits: number, toBits: number, pad: boolean): number[] | null {
  let acc = 0
  let bits = 0
  const ret: number[] = []
  const maxv = (1 << toBits) - 1
  const maxAcc = (1 << (fromBits + toBits - 1)) - 1
  for (const value of data) {
    if (value < 0 || value >> fromBits) return null
    acc = ((acc << fromBits) | value) & maxAcc
    bits += fromBits
    while (bits >= toBits) {
      bits -= toBits
      ret.push((acc >> bits) & maxv)
    }
  }
  if (pad) { if (bits) ret.push((acc << (toBits - bits)) & maxv) }
  else if (bits >= fromBits || ((acc << (toBits - bits)) & maxv)) return null
  return ret
}
function bech32Encode(hrp: string, data: number[]): string {
  const combined = data.concat(createChecksum(hrp, data))
  return hrp + '1' + combined.map((d) => CHARSET[d]!).join('')
}
function bech32Decode(bech: string): { hrp: string; data: number[] } | null {
  if ([...bech].some((c) => c.charCodeAt(0) < 33 || c.charCodeAt(0) > 126)) return null
  if (bech.toLowerCase() !== bech && bech.toUpperCase() !== bech) return null
  bech = bech.toLowerCase()
  const pos = bech.lastIndexOf('1')
  if (pos < 1 || pos + 7 > bech.length || bech.length > 90) return null
  if ([...bech.slice(pos + 1)].some((c) => !CHARSET.includes(c))) return null
  const hrp = bech.slice(0, pos)
  const data = [...bech.slice(pos + 1)].map((c) => CHARSET.indexOf(c))
  if (!verifyChecksum(hrp, data)) return null
  return { hrp, data: data.slice(0, -6) }
}

// --- NIP-19 ---
const HEX_RE = /^[0-9a-fA-F]{64}$/
export function isValidHexPubkey(s: string): boolean { return HEX_RE.test(s.trim()) }
export function isValidNpub(s: string): boolean {
  const d = bech32Decode(s.trim())
  if (!d || d.hrp !== 'npub') return false
  const c = convertBits(d.data, 5, 8, false)
  return !!c && c.length === 32
}
export function isValidNsec(s: string): boolean {
  const d = bech32Decode(s.trim())
  if (!d || d.hrp !== 'nsec') return false
  const c = convertBits(d.data, 5, 8, false)
  return !!c && c.length === 32
}
export function npubToHex(npub: string): string {
  const d = bech32Decode(npub.trim())
  if (!d || d.hrp !== 'npub') throw new Error(`invalid npub: ${npub}`)
  const c = convertBits(d.data, 5, 8, false)
  if (!c || c.length !== 32) throw new Error(`invalid npub payload: ${npub}`)
  return c.map((b) => b.toString(16).padStart(2, '0')).join('')
}
export function hexToNpub(hex: string): string {
  hex = hex.trim().toLowerCase()
  if (!isValidHexPubkey(hex)) throw new Error(`invalid hex pubkey: ${hex}`)
  const bytes = hex.match(/.{2}/g)!.map((h) => parseInt(h, 16))
  const conv = convertBits(bytes, 8, 5, true)
  if (!conv) throw new Error('convert failed')
  return bech32Encode('npub', conv)
}
export function normalizePubkey(input: string): string {
  input = input.trim()
  if (isValidHexPubkey(input)) return input.toLowerCase()
  if (isValidNpub(input)) return npubToHex(input)
  throw new Error(`invalid pubkey (expected hex 64 or npub): ${input}`)
}
export function shortNpub(npub: string): string {
  if (npub.length <= 16) return npub
  return npub.slice(0, 12) + '...' + npub.slice(-6)
}

// --- NIP-07 ---
export interface WindowNostr {
  getPublicKey(): Promise<string>
  signEvent(event: NostrEventTemplate): Promise<NostrSignedEvent>
  getRelays?(): Promise<Record<string, { read: boolean; write: boolean }>>
  nip04?: { encrypt(pubkey: string, plaintext: string): Promise<string>; decrypt(pubkey: string, ciphertext: string): Promise<string> }
}
declare global { interface Window { nostr?: WindowNostr } }

export function hasNip07Extension(): boolean {
  return typeof window !== 'undefined' && !!window.nostr && typeof window.nostr.getPublicKey === 'function'
}
export async function getExtensionPubkey(): Promise<string> {
  if (!window.nostr) throw new Error('no NIP-07 extension found')
  const pk = await window.nostr.getPublicKey()
  if (!isValidHexPubkey(pk)) throw new Error(`extension returned invalid pubkey: ${pk}`)
  return pk.toLowerCase()
}
export type NostrEventTemplate = { kind: number; created_at: number; tags: string[][]; content: string }
export type NostrSignedEvent = NostrEventTemplate & { id: string; pubkey: string; sig: string }

export async function signWithExtension(template: NostrEventTemplate): Promise<NostrSignedEvent> {
  if (!window.nostr?.signEvent) throw new Error('extension does not support signEvent')
  return (await window.nostr.signEvent(template)) as NostrSignedEvent
}

// --- NIP-46 Amber / bunker ---
export interface BunkerInfo { pubkey: string; relays: string[]; secret?: string }
export function parseBunkerUrl(url: string): BunkerInfo | null {
  url = url.trim()
  // bunker://<pubkey>?relay=wss://...&relay=wss://...&secret=...
  try {
    if (url.startsWith('bunker://')) {
      const u = new URL(url.replace('bunker://', 'https://'))
      const pubkey = u.hostname || u.pathname.replace(/^\/+/, '')
      if (!isValidHexPubkey(pubkey)) return null
      const relays = u.searchParams.getAll('relay')
      const secret = u.searchParams.get('secret') ?? undefined
      return { pubkey: pubkey.toLowerCase(), relays, secret }
    }
    if (url.startsWith('nostrconnect://')) {
      const u = new URL(url.replace('nostrconnect://', 'https://'))
      const pubkey = u.hostname || u.pathname.replace(/^\/+/, '')
      if (!isValidHexPubkey(pubkey)) return null
      const relays = u.searchParams.getAll('relay')
      return { pubkey: pubkey.toLowerCase(), relays }
    }
  } catch { return null }
  return null
}

export function buildNostrConnectUri(clientPubkey: string, relays: string[], name = 'vozonda'): string {
  const base = `nostrconnect://${clientPubkey}`
  const p = new URLSearchParams()
  for (const r of relays) p.append('relay', r)
  p.set('metadata', JSON.stringify({ name }))
  return `${base}?${p.toString()}`
}

// Minimal NIP-46 client: opens ws to relay, sends NIP-46 request, waits for response.
// For MVP we expose status callbacks; real crypto (nip44 encrypt) is handled by Amber.
// This implementation does NOT hold nsec, it only speaks to the remote signer.
export type AmberStatus = 'idle' | 'connecting' | 'waiting' | 'connected' | 'error'
export class NostrConnectClient {
  private ws: WebSocket | null = null
  private pending = new Map<string, { resolve: (v: string) => void; reject: (e: Error) => void }>()
  status: AmberStatus = 'idle'
  error = ''

  constructor(
    private relay: string,
    private remotePubkey: string,
    private clientSecret: string // hex 64, ephemeral, never persisted beyond session
  ) {}

  connect(): Promise<void> {
    return new Promise((resolve, reject) => {
      this.status = 'connecting'
      try {
        this.ws = new WebSocket(this.relay)
      } catch (e) { this.status='error'; this.error=String(e); reject(e); return }
      this.ws.onopen = () => { this.status='waiting'; resolve() }
      this.ws.onerror = () => { this.status='error'; this.error='relay connection failed'; reject(new Error(this.error)) }
      this.ws.onclose = () => { if (this.status !== 'connected') this.status='idle' }
      this.ws.onmessage = (ev) => {
        try {
          const msg = JSON.parse(ev.data as string)
          // NIP-46 response: ["EVENT", subId, event] with decrypted content
          // For MVP we just surface raw; full decrypt requires nip44 which Amber handles.
          void msg
        } catch { void ev }
      }
    })
  }
  disconnect() { this.ws?.close(); this.ws=null; this.status='idle' }
}

// --- Identity storage (multi-signer) ---
export type SignerKind = 'extension' | 'amber' | 'bunker' | 'readonly' | 'unknown'
export interface NostrIdentity {
  pubkey: string
  npub: string
  signer: SignerKind
  name?: string
  displayName?: string
  picture?: string
  nip05?: string
  relays?: string[]
  createdAt?: number
}

export function identityDisplayName(id: NostrIdentity | null): string {
  if (!id) return ''
  return id.name || id.displayName || shortNpub(id.npub)
}

const ACTIVE_KEY = 'vozonda.nostr.active'
const LIST_KEY = 'vozonda.nostr.identities'

export function getActiveIdentity(): NostrIdentity | null {
  try { const raw = localStorage.getItem(ACTIVE_KEY); return raw ? JSON.parse(raw) as NostrIdentity : null } catch { return null }
}
export function setActiveIdentity(id: NostrIdentity): void {
  localStorage.setItem(ACTIVE_KEY, JSON.stringify(id))
  const list = getStoredIdentities()
  const idx = list.findIndex((x) => x.pubkey === id.pubkey)
  if (idx >= 0) list[idx] = id; else list.unshift(id)
  localStorage.setItem(LIST_KEY, JSON.stringify(list.slice(0, 8)))
}
export function clearActiveIdentity(): void { localStorage.removeItem(ACTIVE_KEY) }
export function getStoredIdentities(): NostrIdentity[] {
  try { const raw = localStorage.getItem(LIST_KEY); return raw ? JSON.parse(raw) as NostrIdentity[] : [] } catch { return [] }
}
export function removeStoredIdentity(pubkey: string): void {
  const list = getStoredIdentities().filter((x) => x.pubkey !== pubkey.toLowerCase())
  localStorage.setItem(LIST_KEY, JSON.stringify(list))
  const active = getActiveIdentity()
  if (active?.pubkey === pubkey.toLowerCase()) clearActiveIdentity()
}

// --- API helpers ---
const API_BASE = (import.meta as unknown as { env: Record<string,string> }).env?.VITE_API_BASE ?? ''

async function parseJsonOrThrow(r: Response, context: string): Promise<unknown> {
  const ct = r.headers.get('content-type') ?? ''
  if (!ct.includes('application/json')) {
    const text = await r.text()
    throw new Error(`${context}: expected JSON, got ${ct || 'no content-type'} (first 120 chars: ${text.slice(0, 120)})`)
  }
  return r.json()
}

export async function fetchChallenge(): Promise<{ challenge: string; expires_at: number }> {
  const r = await fetch(`${API_BASE}/auth/nostr/challenge`)
  if (!r.ok) throw new Error(`challenge failed: HTTP ${r.status}`)
  return (await parseJsonOrThrow(r, 'fetchChallenge')) as { challenge: string; expires_at: number }
}
export async function verifyLogin(event: NostrSignedEvent, challenge: string, signer: SignerKind): Promise<NostrIdentity> {
  try {
    const r = await fetch(`${API_BASE}/auth/nostr/verify`, { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ event, challenge, signer }) })
    if (!r.ok) {
      const j = await parseJsonOrThrow(r, 'verifyLogin').catch(() => ({ detail: `HTTP ${r.status}` })) as { detail?: string }
      throw new Error(j.detail ?? `HTTP ${r.status}`)
    }
    const j = await parseJsonOrThrow(r, 'verifyLogin') as { pubkey: string; npub: string; signer: string }
    const id: NostrIdentity = { pubkey: j.pubkey, npub: j.npub, signer: (j.signer as SignerKind) ?? signer }
    setActiveIdentity(id)
    return id
  } catch (error) {
    // Log the error for debugging
    console.error('verifyLogin failed:', error)
    throw error
  }
}
export async function validateNpubInput(input: string): Promise<{ hex: string; npub: string }> {
  try {
    const r = await fetch(`${API_BASE}/auth/npub/validate`, { method: 'POST', headers: { 'Content-Type':'application/json' }, body: JSON.stringify({ input }) })
    if (!r.ok) {
      const j = await parseJsonOrThrow(r, 'validateNpubInput').catch(() => ({ detail: `HTTP ${r.status}` })) as { detail?: string }
      throw new Error(j.detail ?? `HTTP ${r.status}`)
    }
    const j = await parseJsonOrThrow(r, 'validateNpubInput') as { hex: string; npub: string }
    return { hex: j.hex, npub: j.npub }
  } catch (error) {
    // Log the error for debugging
    console.error('validateNpubInput failed:', error)
    throw error
  }
}
export function makeReadOnlyIdentity(input: string, hex: string, npub: string): NostrIdentity {
  void input
  return { pubkey: hex, npub, signer: 'readonly', createdAt: Date.now() }
}

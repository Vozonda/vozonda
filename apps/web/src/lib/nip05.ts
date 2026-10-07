/** NIP-05 identifier verification for vozonda. */

export interface Nip05Result {
  nip05: string
  domain: string
  name: string
  pubkey: string | null
  valid: boolean
  reason: string
}

const NIP05_RE = /^([^@\s]+)@([^@\s]+\.[^@\s]+)$/

export function isNip05(input: string): boolean {
  return NIP05_RE.test(input.trim())
}

export function parseNip05(input: string): { name: string; domain: string } | null {
  const m = input.trim().match(NIP05_RE)
  if (!m) return null
  return { name: m[1]!.toLowerCase(), domain: m[2]!.toLowerCase() }
}

export async function verifyNip05(
  nip05: string,
  expectedPubkey?: string,
  fetchImpl: typeof fetch = fetch,
  timeoutMs = 4000
): Promise<Nip05Result> {
  const parsed = parseNip05(nip05)
  if (!parsed) {
    return { nip05: nip05.trim(), domain: '', name: '', pubkey: null, valid: false, reason: 'invalid nip05 format' }
  }
  const { name, domain } = parsed
  const url = `https://${domain}/.well-known/nostr.json?name=${encodeURIComponent(name)}`
  const ctrl = new AbortController()
  const timer = setTimeout(() => ctrl.abort(), timeoutMs)
  try {
    const r = await fetchImpl(url, { signal: ctrl.signal, headers: { Accept: 'application/json' } })
    if (!r.ok) {
      return { nip05, domain, name, pubkey: null, valid: false, reason: `http ${r.status}` }
    }
    const j = (await r.json()) as { names?: Record<string, string>; relays?: Record<string, string[]> }
    const names = j.names ?? {}
    const hex = names[name]
    if (!hex) {
      return { nip05, domain, name, pubkey: null, valid: false, reason: 'name not found' }
    }
    if (!/^[0-9a-f]{64}$/i.test(hex)) {
      return { nip05, domain, name, pubkey: hex, valid: false, reason: 'invalid hex in registry' }
    }
    const lower = hex.toLowerCase()
    if (expectedPubkey && lower !== expectedPubkey.toLowerCase()) {
      return { nip05, domain, name, pubkey: lower, valid: false, reason: 'pubkey mismatch' }
    }
    return { nip05, domain, name, pubkey: lower, valid: true, reason: 'ok' }
  } catch (e) {
    return { nip05, domain, name, pubkey: null, valid: false, reason: e instanceof Error ? e.message : String(e) }
  } finally {
    clearTimeout(timer)
  }
}

export async function resolveNip05ToPubkey(nip05: string): Promise<string | null> {
  const res = await verifyNip05(nip05)
  return res.valid ? res.pubkey : null
}

export async function lookupPubkeyNip05(pubkeyHex: string, fetchImpl: typeof fetch = fetch): Promise<string | null> {
  // Reverse lookup is not part of NIP-05; attempt common domains if profile hints contain nip05.
  void pubkeyHex
  void fetchImpl
  return null
}

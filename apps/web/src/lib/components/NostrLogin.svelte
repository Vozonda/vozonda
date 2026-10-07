<script lang="ts">
  import Icon from './Icon.svelte'
  import {
    hasNip07Extension,
    getExtensionPubkey,
    signWithExtension,
    parseBunkerUrl,
    isValidNpub,
    isValidHexPubkey,
    hexToNpub,
    npubToHex,
    normalizePubkey,
    shortNpub,
    fetchChallenge,
    verifyLogin,
    validateNpubInput,
    makeReadOnlyIdentity,
    getActiveIdentity,
    getStoredIdentities,
    setActiveIdentity,
    clearActiveIdentity,
    removeStoredIdentity,
    type NostrIdentity,
    type SignerKind
  } from '../nostr'

  let { open = false, onClose, onLogin }: { open: boolean; onClose: () => void; onLogin?: (id: NostrIdentity) => void } = $props()

  type Tab = 'extension' | 'amber' | 'npub'
  let tab = $state<Tab>('extension')
  let busy = $state(false)
  let error = $state('')
  let active = $state<NostrIdentity | null>(null)
  let stored = $state<NostrIdentity[]>([])

  // npub tab
  let npubInput = $state('')
  let npubValid = $state<boolean | null>(null)
  let npubHex = $state('')
  let npubNorm = $state('')
  let npubChecking = $state(false)

  // amber tab
  let bunkerInput = $state('')
  let amberRelays = $state('wss://relay.damus.io')
  let amberStatus = $state('')
  let amberPubkey = $state('')

  function refreshStore() {
    active = getActiveIdentity()
    stored = getStoredIdentities()
  }

  $effect(() => {
    if (open) {
      refreshStore()
      // auto-detect best tab: if extension available default to it, else npub
      if (!hasNip07Extension() && tab === 'extension') tab = 'npub'
      error = ''
    }
  })

  async function loginWithExtension() {
    busy = true; error = ''
    try {
      if (!hasNip07Extension()) throw new Error('no NIP-07 extension detected. Install Alby, nos2x, or Flaming.')
      const { challenge } = await fetchChallenge()
      const pubkey = await getExtensionPubkey()
      const template = { kind: 27235, created_at: Math.floor(Date.now()/1000), tags: [['challenge', challenge]], content: challenge }
      const signed = await signWithExtension(template)
      const id = await verifyLogin(signed, challenge, 'extension')
      active = id; refreshStore(); onLogin?.(id)
    } catch (e) { error = e instanceof Error ? e.message : String(e) } finally { busy = false }
  }

  async function loginWithAmber() {
    busy = true; error = ''; amberStatus=''
    try {
      let pubkey = ''
      let signer: SignerKind = 'amber'
      let relays: string[] = []
      const info = parseBunkerUrl(bunkerInput.trim())
      if (info) {
        pubkey = info.pubkey
        relays = info.relays.length ? info.relays : [amberRelays.trim()].filter(Boolean)
        signer = 'bunker'
      } else if (bunkerInput.trim()) {
        // raw hex or npub fallback
        try { pubkey = normalizePubkey(bunkerInput.trim()) } catch { throw new Error('invalid bunker URL, hex or npub') }
        relays = [amberRelays.trim()].filter(Boolean)
      } else if (amberPubkey.trim()) {
        pubkey = normalizePubkey(amberPubkey.trim())
        relays = [amberRelays.trim()].filter(Boolean)
      } else {
        throw new Error('paste a bunker:// URL or a npub/hex pubkey')
      }
      // For Amber we still do challenge flow if window.nostr exists remotely via relay
      // MVP: if we have a remote signer pubkey, do read-only challenge-less binding via validate,
      // then attempt signed challenge if Amber bridge is present
      const { challenge } = await fetchChallenge()
      // Try to sign via extension if available (Amber exposes as nos2x after pairing)
      if (hasNip07Extension()) {
        const extPk = await getExtensionPubkey().catch(()=> '')
        if (extPk.toLowerCase() === pubkey.toLowerCase()) {
          const template = { kind: 27235, created_at: Math.floor(Date.now()/1000), tags: [['challenge', challenge]], content: challenge }
          const signed = await signWithExtension(template)
          const id = await verifyLogin(signed, challenge, signer)
          amberStatus = 'signed via Amber bridge'
          active = id; refreshStore(); onLogin?.(id); return
        }
      }
      // fallback: read-only verified via backend validate (no signature)
      const v = await validateNpubInput(pubkey)
      const id: NostrIdentity = { pubkey: v.hex, npub: v.npub, signer, relays, createdAt: Date.now() }
      setActiveIdentity(id)
      amberStatus = 'linked in read-only mode (pair Amber to enable signing)'
      active = id; refreshStore(); onLogin?.(id)
    } catch (e) { error = e instanceof Error ? e.message : String(e) } finally { busy = false }
  }

  let npubDebounce: ReturnType<typeof setTimeout> | undefined
  function onNpubInput(val: string) {
    npubInput = val
    npubValid = null; npubHex=''; npubNorm=''
    clearTimeout(npubDebounce)
    if (!val.trim()) return
    if (val.trim().startsWith('nsec1')) { npubValid=false; error='nsec not allowed. Use npub or hex only.'; return }
    npubChecking = true
    npubDebounce = setTimeout(async () => {
      try {
        const v = await validateNpubInput(val.trim())
        npubValid = true; npubHex = v.hex; npubNorm = v.npub; error=''
      } catch (e) {
        npubValid = false; error = e instanceof Error ? e.message : String(e)
      } finally { npubChecking=false }
    }, 320)
  }

  async function loginReadOnly() {
    busy = true; error=''
    try {
      if (!npubValid || !npubHex) throw new Error('enter a valid npub or hex pubkey')
      const id = makeReadOnlyIdentity(npubInput.trim(), npubHex, npubNorm)
      setActiveIdentity(id)
      // also validate on server for consistency (no challenge needed for read-only)
      try { await validateNpubInput(npubInput.trim()) } catch { void 0 }
      active = id; refreshStore(); onLogin?.(id)
    } catch (e) { error = e instanceof Error ? e.message : String(e) } finally { busy=false }
  }

  function handleLogout() { clearActiveIdentity(); active=null; refreshStore() }
  function selectStored(id: NostrIdentity) { setActiveIdentity(id); active=id; refreshStore(); onLogin?.(id) }

  function closeIfBackdrop(e: MouseEvent) { if (e.target === e.currentTarget) onClose() }
</script>

{#if open}
  <div class="overlay" role="presentation" onclick={closeIfBackdrop}>
    <div class="modal" role="dialog" aria-modal="true" aria-labelledby="nostr-login-title">
      <div class="modal-head">
        <h2 id="nostr-login-title" class="mono"><Icon name="info" size={16} /> nostr login</h2>
        <button class="close mono" onclick={onClose} aria-label="Close">close</button>
      </div>

      {#if active}
        <div class="active-card">
          <span class="mono badge">active identity</span>
          <p class="mono npub">{shortNpub(active.npub)}</p>
          <p class="mono sub">{active.pubkey.slice(0,16)}... · {active.signer}</p>
          <div class="row">
            <button class="quiet mono" onclick={handleLogout}>sign out</button>
            <button class="quiet mono" onclick={onClose}>continue</button>
          </div>
        </div>
        {#if stored.length > 1}
          <div class="stored">
            <p class="mono label">switch identity</p>
            <div class="chips">
              {#each stored as s (s.pubkey)}
                <button class="chip mono" class:sel={s.pubkey===active.pubkey} onclick={()=>selectStored(s)} title={s.npub}>
                  {shortNpub(s.npub)} · {s.signer}
                </button>
              {/each}
            </div>
          </div>
        {/if}
        <hr class="sep" />
      {/if}

      <div class="tabs mono" role="tablist" aria-label="Signer">
        <button role="tab" aria-selected={tab==='extension'} class:sel={tab==='extension'} onclick={()=>tab='extension'}>extension</button>
        <button role="tab" aria-selected={tab==='amber'} class:sel={tab==='amber'} onclick={()=>tab='amber'}>amber</button>
        <button role="tab" aria-selected={tab==='npub'} class:sel={tab==='npub'} onclick={()=>tab='npub'}>npub</button>
      </div>

      {#if tab==='extension'}
        <section class="pane">
          <p class="mono help">NIP-07 browser extension (Alby, nos2x, Flaming). No nsec ever leaves the extension.</p>
          {#if !hasNip07Extension()}
            <p class="mono warn">no extension detected. Install Alby and reload.</p>
          {/if}
          <button class="primary mono" disabled={busy} onclick={()=>void loginWithExtension()}>{busy ? 'waiting...' : 'login with extension'}</button>
          <p class="mono hint">signs a one-time challenge (kind 27235). Private key stays in the extension.</p>
        </section>
      {:else if tab==='amber'}
        <section class="pane">
          <p class="mono help">NIP-46 Amber / bunker signer. Paste your bunker:// URL from Amber or enter the remote pubkey.</p>
          <label class="mono lab" for="bunker">bunker url or pubkey</label>
          <input id="bunker" class="mono text-in" placeholder="bunker://pubkey?relay=wss://relay.damus.io&secret=..." bind:value={bunkerInput} />
          <div class="grid2">
            <div>
              <label class="mono lab" for="amber-relay">relay</label>
              <input id="amber-relay" class="mono text-in" placeholder="wss://relay.damus.io" bind:value={amberRelays} />
            </div>
            <div>
              <label class="mono lab" for="amber-pk">or pubkey (npub/hex)</label>
              <input id="amber-pk" class="mono text-in" placeholder="npub1... or hex" bind:value={amberPubkey} />
            </div>
          </div>
          <button class="primary mono" disabled={busy} onclick={()=>void loginWithAmber()}>{busy ? 'connecting...' : 'connect Amber'}</button>
          {#if amberStatus}<p class="mono ok">{amberStatus}</p>{/if}
          <p class="mono hint">Amber signs on your phone. Vozonda only stores the npub. Relay handling is NIP-46 bunker.</p>
        </section>
      {:else}
        <section class="pane">
          <p class="mono help">npub identification. Paste your npub or hex pubkey for read-only login.</p>
          <label class="mono lab" for="npub-in">npub or hex</label>
          <input id="npub-in" class="mono text-in" placeholder="npub1... or 64-char hex" value={npubInput} oninput={(e)=>onNpubInput(e.currentTarget.value)} autocomplete="off" spellcheck="false" />
          {#if npubChecking}<p class="mono sub">validating...</p>{/if}
          {#if npubValid===true}
            <div class="valid-card mono">
              <span class="ok">valid</span>
              <span class="npub">{shortNpub(npubNorm)}</span>
              <span class="sub">{npubHex.slice(0,16)}...</span>
            </div>
          {:else if npubValid===false}
            <p class="mono warn">invalid npub or hex</p>
          {/if}
          <button class="primary mono" disabled={busy || !npubValid} onclick={()=>void loginReadOnly()}>{busy ? '...' : 'use this identity'}</button>
          <p class="mono hint">read-only mode: you can browse and link content, signing requires extension or Amber.</p>
        </section>
      {/if}

      {#if error}<p class="mono err" role="alert">{error}</p>{/if}

      {#if stored.length > 0 && !active}
        <div class="stored">
          <p class="mono label">recent identities</p>
          <div class="chips">
            {#each stored as s (s.pubkey)}
              <button class="chip mono" onclick={()=>selectStored(s)} title={s.npub}>
                {shortNpub(s.npub)} · {s.signer}
              </button>
            {/each}
          </div>
        </div>
      {/if}

      <p class="mono foot-note">vozonda never stores nsec. Only npub/hex is kept for linking and recovery.</p>
    </div>
  </div>
{/if}

<style>
  .overlay { position: fixed; inset:0; background: color-mix(in srgb, var(--ink) 42%, transparent); backdrop-filter: blur(2px); display:grid; place-items:center; z-index:60; padding: var(--space-3); }
  .modal { width: min(560px, 100%); max-height: 90vh; overflow:auto; background: var(--paper); border: 1px solid var(--line); border-radius: var(--radius); padding: var(--space-4); display:grid; gap: var(--space-3); box-shadow: 0 12px 32px rgba(0,0,0,.18); }
  .modal-head { display:flex; justify-content:space-between; align-items:center; }
  .modal-head h2 { margin:0; font-size: var(--ui-size); font-weight:600; text-transform: lowercase; display:flex; align-items:center; gap: var(--space-2); }
  .close { background:transparent; border:1px solid var(--line); border-radius: var(--radius); padding: var(--space-1) var(--space-2); cursor:pointer; min-height:32px; color: var(--ink-soft); }
  .close:hover { border-color: var(--ink); color: var(--ink); }
  .tabs { display:flex; gap: var(--space-2); border-bottom:1px solid var(--line); padding-bottom: var(--space-2); }
  .tabs button { background: color-mix(in srgb, var(--ink) 4%, var(--paper)); border:1px solid var(--line); border-radius: var(--radius); padding: var(--space-1) var(--space-3); cursor:pointer; min-height: 36px; color: var(--ink); transition: background var(--dur-fast) ease-out, border-color var(--dur-fast) ease-out; }
  .tabs button:hover:not(.sel):not([aria-selected="true"]) { border-color: var(--ink); background: color-mix(in srgb, var(--ink) 8%, var(--paper)); color: var(--ink); }
  .tabs button.sel { background: color-mix(in srgb, var(--green) 12%, var(--paper)); color: var(--ink); border-color: var(--green); font-weight:600; }
  .tabs button.sel:hover { background: color-mix(in srgb, var(--green) 20%, var(--paper)); border-color: var(--green); color: var(--ink); }
  .pane { display:grid; gap: var(--space-3); }
  .help { color: var(--ink-soft); font-size: calc(var(--ui-size)*.9); margin:0; line-height:1.45; }
  .hint { color: var(--ink-soft); font-size: calc(var(--ui-size)*.85); }
  .warn { color: var(--danger); }
  .err { color: var(--danger); white-space: pre-wrap; }
  .ok { color: var(--green); }
  .lab { color: var(--ink-soft); font-size: calc(var(--ui-size)*.9); }
  .text-in { width:100%; min-height:42px; font-family: var(--font-mono); font-size: var(--ui-size); background: color-mix(in srgb, var(--ink) 4%, var(--paper)); border:1px solid color-mix(in srgb, var(--ink) 18%, var(--line)); border-radius: var(--radius); padding: var(--space-2) var(--space-3); color: var(--ink); }
  .text-in:focus-visible { outline:2px solid var(--green); outline-offset: 2px; border-color: var(--green); }
  .grid2 { display:grid; grid-template-columns: 1fr 1fr; gap: var(--space-3); }
  @media (max-width:520px){ .grid2{ grid-template-columns:1fr; } }
  .primary { background: var(--green); color: var(--paper); border:1px solid var(--green); border-radius: var(--radius); padding: var(--space-2) var(--space-4); font-family: var(--font-mono); font-size: var(--ui-size); cursor:pointer; min-height:42px; font-weight:600; }
  .primary:disabled{ opacity:.5; cursor:not-allowed; }
  .primary:hover:not(:disabled){ background: color-mix(in srgb, var(--green) 85%, var(--ink)); border-color: var(--green); color: var(--paper); }
  .active-card { border:1px solid color-mix(in srgb, var(--green) 28%, var(--line)); background: color-mix(in srgb, var(--green) 6%, var(--paper)); border-radius: var(--radius); padding: var(--space-3); display:grid; gap: var(--space-1); }
  .badge{ font-size: calc(var(--ui-size)*.75); letter-spacing:.05em; color: var(--green); }
  .npub{ color: var(--ink); font-weight:600; }
  .sub{ color: var(--ink-soft); font-size: calc(var(--ui-size)*.85); }
  .row{ display:flex; gap: var(--space-2); }
  .quiet{ background: transparent; border:1px solid var(--line); border-radius: var(--radius); padding: var(--space-1) var(--space-2); cursor:pointer; min-height:32px; color: var(--ink-soft); }
  .quiet:hover{ border-color: var(--ink); color: var(--ink); }
  .stored{ display:grid; gap: var(--space-2); }
  .label{ color: var(--ink-soft); font-size: calc(var(--ui-size)*.85); margin:0; }
  .chips{ display:flex; flex-wrap:wrap; gap: var(--space-2); }
  .chip{ background: color-mix(in srgb, var(--ink) 4%, var(--paper)); border:1px solid var(--line); border-radius: var(--radius); padding: var(--space-1) var(--space-2); cursor:pointer; min-height:32px; max-width: 100%; overflow:hidden; text-overflow:ellipsis; color: var(--ink); }
  .chip:hover:not(.sel){ border-color: var(--green); color: var(--ink); background: color-mix(in srgb, var(--green) 8%, var(--paper)); }
  .chip.sel{ background: color-mix(in srgb, var(--green) 12%, var(--paper)); border-color: var(--green); color: var(--ink); font-weight:600; }
  .chip.sel:hover{ background: color-mix(in srgb, var(--green) 20%, var(--paper)); border-color: var(--green); color: var(--ink); }
  .valid-card{ border:1px solid var(--line); border-radius: var(--radius); padding: var(--space-2) var(--space-3); display:flex; gap: var(--space-2); align-items:center; flex-wrap:wrap; }
  .sep{ border:none; border-top:1px solid var(--line); margin:0; }
  .foot-note{ color: var(--ink-soft); font-size: calc(var(--ui-size)*.8); margin:0; }
</style>

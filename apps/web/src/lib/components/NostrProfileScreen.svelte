<script lang="ts">
  import Icon from './Icon.svelte'
  import { getActiveIdentity, setActiveIdentity, hasNip07Extension, clearActiveIdentity, getStoredIdentities, shortNpub as nostrShort } from '../nostr'
  import { isValidHexPubkey, isValidNpub, shortNpub, hexToNpub } from '../nostr'
  import { fetchProfileFromRelays, verifyProfileNip05, fetchZapHistory, fetchHighlightsByAuthor, resolveInputToPubkey, classifyInput, displayNameFor, type NostrProfile, type ZapHistoryItem, type AuthorHighlight, DEFAULT_RELAYS } from '../profile'
  import { fetchShows, getSettings, type ShowItem } from '../api'
  import { isNip05 } from '../nip05'

  let {
    initial = '',
    onback
  }: {
    initial?: string
    onback: () => void
  } = $props()

  // svelte-ignore state_referenced_locally
  let query = $state(initial.trim())
  let resolving = $state(false)
  let loading = $state(false)
  let error = $state('')
  let profile = $state<NostrProfile | null>(null)
  let nip05Checked = $state(false)
  let relays = $state<string[]>(DEFAULT_RELAYS)
  let zaps = $state<ZapHistoryItem[]>([])
  let highlights = $state<AuthorHighlight[]>([])
  let shows = $state<ShowItem[]>([])
  let settingsDict = $state<Record<string, string>>({})
  let copiedFeed = $state<string | null>(null)
  let zapLoading = $state(false)
  let hlLoading = $state(false)
  let activeTab = $state<'highlights' | 'zaps' | 'feeds'>('highlights')
  let copiedNpub = $state(false)
  let copiedHex = $state(false)
  let hexPubkey = $state('')

  const isOwn = $derived.by(() => {
    try {
      const id = getActiveIdentity()
      return !!id && !!hexPubkey && id.pubkey.toLowerCase() === hexPubkey.toLowerCase()
    } catch { return false }
  })

  const hasSigner = $derived(hasNip07Extension())
  const short = $derived(profile ? shortNpub(profile.npub) : hexPubkey ? shortNpub(hexToNpub(hexPubkey)) : '')
  const displayName = $derived(profile ? displayNameFor(profile) : hexPubkey ? short : '')
  const totalSats = $derived(zaps.reduce((sum, z) => sum + Math.round((z.amountMsats ?? 0) / 1000), 0))
  const activeIdentity = $derived.by(() => { try { return getActiveIdentity() } catch { return null } })
  const signerLabel = $derived.by(() => {
    const id = activeIdentity
    if (!id) return hasSigner ? 'NIP-07 available (Alby, nos2x, Amber)' : 'no signer detected'
    const map: Record<string, string> = { extension: 'NIP-07 extension (Alby, nos2x)', amber: 'Amber (NIP-46)', bunker: 'Bunker (NIP-46)', readonly: 'read-only (no signer)', unknown: 'unknown signer' }
    return map[id.signer] ?? id.signer
  })

  async function resolveAndLoad(input: string) {
    const t = input.trim()
    if (!t) { error = 'enter npub, hex or nip05 (alice@example.com)'; return }
    resolving = true; loading = true; error=''; profile=null; nip05Checked=false; zaps=[]; highlights=[]; hexPubkey=''
    try {
      const resolved = await resolveInputToPubkey(t)
      hexPubkey = resolved.hex
      // push hash for deep-link
      try { history.replaceState(null,'',`#profile=${encodeURIComponent(t)}`) } catch {}
      await loadProfile(resolved.hex)
    } catch (e) {
      error = e instanceof Error ? e.message : String(e)
    } finally {
      resolving=false; loading=false
    }
  }

  async function loadProfile(hex: string) {
    loading=true; error=''
    try {
      const res = await fetchProfileFromRelays(hex, relays, 5000)
      if (res.profile) {
        let p = res.profile
        // verify nip05 if present
        if (p.nip05) {
          p = await verifyProfileNip05(p)
          nip05Checked = true
        }
        profile = p
        if (activeIdentity && activeIdentity.pubkey.toLowerCase() === hex.toLowerCase()) {
          const name = p.name || p.display_name || p.displayName
          if (name && (activeIdentity.name !== name || activeIdentity.picture !== p.picture)) {
            const updated = {
              ...activeIdentity,
              name,
              displayName: p.display_name || p.displayName || p.name,
              picture: p.picture,
              nip05: p.nip05
            }
            setActiveIdentity(updated)
          }
        }
      } else {
        // no kind0 found, synthesize minimal profile so avatar/name fallback still shows activity
        profile = {
          pubkey: hex.toLowerCase(),
          npub: hexToNpub(hex.toLowerCase()),
          raw: {},
          relays,
          nip05Valid: undefined
        } as NostrProfile
        if (res.error && res.error !== 'no profile found') error = `profile not found on relays (${res.error}) - showing activity only`
      }
      // kick off activity fetches
      void fetchActivity(hex)
    } catch (e) {
      error = e instanceof Error ? e.message : String(e)
    } finally { loading=false }
  }

  async function fetchActivity(hex: string) {
    zapLoading=true; hlLoading=true
    const cleanHex = hex.toLowerCase()
    // clear
    zaps=[]; highlights=[]
    const stopZap = fetchZapHistory(relays, cleanHex, (z) => {
      // de-dupe by id
      if (!zaps.find((x)=>x.id===z.id)) zaps = [...zaps, z].sort((a,b)=>b.created_at-a.created_at).slice(0,30)
    }, ()=>{ zapLoading=false }, 30, 6000)
    const stopHl = fetchHighlightsByAuthor(relays, cleanHex, (h) => {
      if (!highlights.find((x)=>x.id===h.id)) highlights = [...highlights, h].sort((a,b)=>b.created_at-a.created_at).slice(0,30)
    }, ()=>{ hlLoading=false }, 30, 6000)
    // auto-stop after timeout is handled inside helpers; keep refs for cleanup
    void stopZap; void stopHl
    // fallback timeout to clear loading
    setTimeout(()=>{ zapLoading=false; hlLoading=false }, 7000)
  }

  function onSubmit(e: SubmitEvent) {
    e.preventDefault()
    void resolveAndLoad(query)
  }

  async function copyNpub() {
    const v = profile?.npub ?? (hexPubkey ? hexToNpub(hexPubkey) : '')
    if (!v) return
    try { await navigator.clipboard.writeText(v); copiedNpub=true; setTimeout(()=>copiedNpub=false, 1600) } catch {}
  }
  async function copyHex() {
    const v = hexPubkey || profile?.pubkey || ''
    if (!v) return
    try { await navigator.clipboard.writeText(v); copiedHex=true; setTimeout(()=>copiedHex=false, 1600) } catch {}
  }

  async function refreshProfile() {
    if (!hexPubkey) return
    loading = true; error = ''
    try {
      const res = await fetchProfileFromRelays(hexPubkey, relays, 5000)
      if (res.profile) {
        let p = res.profile
        if (p.nip05) { p = await verifyProfileNip05(p); nip05Checked = true }
        profile = p
      }
      void fetchActivity(hexPubkey)
    } catch (e) { error = e instanceof Error ? e.message : String(e) }
    finally { loading = false }
  }

  function handleLogout() {
    try { clearActiveIdentity() } catch {}
    // dispatch storage event for App.svelte header to pick up on next tick
    try { window.dispatchEvent(new Event('storage')) } catch {}
  }

  function switchToStored(pubkey: string) {
    const list = getStoredIdentities()
    const found = list.find((x) => x.pubkey.toLowerCase() === pubkey.toLowerCase())
    if (found) void resolveAndLoad(found.npub)
  }

  function fmtDate(ts: number): string {
    if (!ts) return ''
    return new Date(ts*1000).toLocaleDateString(undefined, { month:'short', day:'numeric', year:'numeric'})
  }
  function satsLabel(msats?: number): string {
    if (msats==null) return ''
    return `${Math.round(msats/1000).toLocaleString()} sats`
  }

  const origin = typeof window !== 'undefined' ? window.location.origin : 'http://127.0.0.1:8787'
  const creatorSlug = $derived((profile?.name || activeIdentity?.name || 'vozonda').toLowerCase().replace(/[^a-z0-9_-]/g, ''))
  const masterFeedUrl = $derived(`${origin}/feed.xml`)

  const masterTitle = $derived(settingsDict['show.name'] || settingsDict['show.title'] || settingsDict['feed.title'] || 'All Episodes')
  const masterDesc = $derived(settingsDict['show.description'] || settingsDict['feed.description'] || 'Aggregates all standalone episodes and all series in chronological order.')
  const masterCategory = $derived(settingsDict['show.category'] || settingsDict['feed.category'] || 'general')
  const masterAuthor = $derived(settingsDict['show.author'] || settingsDict['feed.creator.address'] || profile?.name || activeIdentity?.name || 'vozonda')

  async function copyFeedUrl(url: string, key: string) {
    try {
      await navigator.clipboard.writeText(url)
      copiedFeed = key
      setTimeout(() => {
        if (copiedFeed === key) copiedFeed = null
      }, 2000)
    } catch {}
  }

  // load user-defined series / shows and settings for feeds tab
  $effect(() => {
    if (isOwn) {
      fetchShows()
        .then((s) => (shows = s))
        .catch(() => {})
      getSettings()
        .then((res) => {
          if (res?.settings) settingsDict = res.settings
        })
        .catch(() => {})
    }
  })

  // auto-load target (initial query or active logged-in identity)
  $effect(() => {
    const target = initial.trim() || activeIdentity?.npub || activeIdentity?.pubkey || ''
    if (target && !profile && !loading && !resolving) {
      query = target
      void resolveAndLoad(target)
    }
  })
</script>

<main class="profile-screen" aria-labelledby="profile-heading">
  <div class="back-row">
    <button type="button" class="back mono" onclick={onback} aria-label="Back to previous screen">
      <Icon name="back" size={14} /> back
    </button>
    <span class="mono crumb">{isOwn ? 'my account' : 'nostr profile'}</span>
  </div>

  {#if loading && !profile}
    <div class="ess loading mono" role="status" aria-live="polite">
      <Icon name="pulse" size={14} /> fetching kind 0 from relays...
    </div>
  {/if}

  {#if profile || hexPubkey}
    <section class="ess hero" aria-labelledby="profile-heading">
      <div class="hero-top">
        <div class="avatar-wrap">
          {#if profile?.picture}
            <img class="avatar" src={profile.picture} alt="{displayName} avatar" loading="lazy" onerror={(e)=>{(e.currentTarget as HTMLImageElement).style.display='none'}} />
          {:else}
            <div class="avatar fallback" aria-hidden="true">
              <span class="fallback-initial">{ (displayName || 'N').slice(0,1).toUpperCase()}</span>
            </div>
          {/if}
        </div>
        <div class="hero-meta">
          <h2 id="profile-heading" class="name">{displayName || short || 'unknown'}</h2>
          {#if profile?.name && profile?.display_name && profile.name !== profile.display_name}
            <p class="mono sub">@{profile.name}</p>
          {:else if profile?.name}
            <p class="mono sub">@{profile.name}</p>
          {/if}
          {#if profile?.nip05}
            <p class="mono nip05" class:valid={profile.nip05Valid===true} class:invalid={profile.nip05Valid===false}>
              <Icon name={profile.nip05Valid===true ? 'check' : profile.nip05Valid===false ? 'cross' : 'info'} size={12} />
              {profile.nip05}
              {#if profile.nip05Valid===true} <span class="badge ok">verified</span>
              {:else if profile.nip05Valid===false} <span class="badge bad">not verified</span>
              {:else if nip05Checked} <span class="badge">checked</span>
              {/if}
            </p>
          {/if}
          {#if profile?.about}
            <p class="about">{profile.about}</p>
          {/if}
          <div class="meta-row mono">
            {#if profile?.website}
              <a class="link" href={profile.website.startsWith('http') ? profile.website : `https://${profile.website}`} target="_blank" rel="noopener noreferrer">{profile.website}</a>
            {/if}
            {#if profile?.lud16}
              <span class="chip-lud"><Icon name="zap" size={12} /> {profile.lud16}</span>
            {/if}
            {#if isOwn}
              <span class="chip-own"><Icon name="check" size={12} /> you · {hasSigner ? 'NIP-07 ready' : 'read-only'}</span>
            {:else if hasSigner}
              <span class="chip-signer">NIP-07 available</span>
            {/if}
          </div>
        </div>
      </div>

      <div class="npub-row mono">
        <div class="npub-box">
          <span class="label">npub</span>
          <code class="code" title={profile?.npub ?? (hexPubkey ? hexToNpub(hexPubkey) : '')}>{short}</code>
          <button type="button" class="mini mono" onclick={copyNpub} aria-label="Copy npub">{copiedNpub ? 'copied' : 'copy'}</button>
        </div>
        <div class="npub-box">
          <span class="label">hex</span>
          <code class="code" title={hexPubkey}>{hexPubkey ? `${hexPubkey.slice(0,16)}...${hexPubkey.slice(-8)}` : ''}</code>
          <button type="button" class="mini mono" onclick={copyHex} aria-label="Copy hex">{copiedHex ? 'copied' : 'copy'}</button>
        </div>
      </div>

      <div class="stats mono" role="status" aria-live="polite">
        <span class="stat"><Icon name="zap" size={12} /> {zaps.length} zaps ({totalSats.toLocaleString()} sats){zapLoading ? ' loading...' : ''}</span>
        <span class="dot" aria-hidden="true">·</span>
        <span class="stat"><Icon name="highlighter" size={12} /> {highlights.length} highlights {hlLoading ? '(loading...)' : ''}</span>
        <span class="dot" aria-hidden="true">·</span>
        <span class="stat">{relays.length} relays</span>
      </div>

      <div class="profile-actions mono">
        <button type="button" class="mini mono" onclick={refreshProfile} disabled={loading} aria-label="Refresh profile metadata">
          <Icon name="rss" size={12} /> refresh
        </button>
        {#if isOwn && activeIdentity}
          <button type="button" class="mini mono danger" onclick={handleLogout} aria-label="Disconnect nostr identity">
            <Icon name="cross" size={12} /> disconnect / logout
          </button>
        {/if}
      </div>

      <div class="signer-box mono" role="status" aria-live="polite">
        <span class="label">signer</span>
        <span class="signer-text">{signerLabel}</span>
        {#if activeIdentity}
          <span class="signer-id">{nostrShort(activeIdentity.npub)} ({activeIdentity.signer})</span>
        {/if}
      </div>
    </section>

    <div class="tabs mono" role="tablist" aria-label="Activity and feeds">
      <button role="tab" aria-selected={activeTab==='highlights'} class:sel={activeTab==='highlights'} onclick={()=>activeTab='highlights'}>
        <Icon name="highlighter" size={12} /> highlights {highlights.length ? `(${highlights.length})` : ''}
      </button>
      <button role="tab" aria-selected={activeTab==='zaps'} class:sel={activeTab==='zaps'} onclick={()=>activeTab='zaps'}>
        <Icon name="zap" size={12} /> zaps {zaps.length ? `(${zaps.length})` : ''}
      </button>
      {#if isOwn}
        <button role="tab" aria-selected={activeTab==='feeds'} class:sel={activeTab==='feeds'} onclick={()=>activeTab='feeds'}>
          <Icon name="rss" size={12} /> podcast feeds {shows.length ? `(${shows.length + 1})` : ''}
        </button>
      {/if}
    </div>

    {#if activeTab==='highlights'}
      <section class="ess activity" aria-labelledby="hl-h">
        <h2 id="hl-h" class="mono ess-h"><Icon name="highlighter" size={18} /> public highlights</h2>
        <p class="mono help">kind 9802 events authored by this pubkey, fetched live from relays. NIP-84 quotes travel with the user, tap a quote to jump to episode if the source is a vozonda episode.</p>
        {#if hlLoading && highlights.length===0}
          <p class="mono sub">loading highlights from relays...</p>
        {:else if highlights.length===0}
          <p class="mono sub">no public highlights found on {relays[0]}. Try again or check another relay.</p>
        {:else}
          <ul class="hl-list">
            {#each highlights as h (h.id)}
              <li class="hl-item">
                <blockquote class="quote">"{h.content}"</blockquote>
                <div class="mono hl-meta">
                  {#if h.rTag}
                    {#if h.rTag.includes('#e=') || h.rTag.includes('/audio/') || h.rTag.includes('vozonda')}
                      <a class="link" href={h.rTag.includes('#e=') ? h.rTag.slice(h.rTag.indexOf('#e=')) : h.rTag} >{h.rTag.slice(0,48)}{h.rTag.length>48 ? '...' : ''} (open episode)</a>
                    {:else}
                      <a class="link" href={h.rTag} target="_blank" rel="noopener noreferrer">{h.rTag.slice(0,48)}{h.rTag.length>48 ? '...' : ''}</a>
                    {/if}
                  {/if}
                  <span class="date">{fmtDate(h.created_at)}</span>
                  {#if h.alt}<span class="alt">{h.alt}</span>{/if}
                </div>
              </li>
            {/each}
          </ul>
        {/if}
      </section>
    {:else if activeTab==='zaps'}
      <section class="ess activity" aria-labelledby="zap-h">
        <h2 id="zap-h" class="mono ess-h"><Icon name="zap" size={18} /> zap history</h2>
        <p class="mono help">kind 9735 receipts where this user is recipient (p tag). Live from relays, NIP-57.</p>
        {#if zapLoading && zaps.length===0}
          <p class="mono sub">listening for zap receipts...</p>
        {:else if zaps.length===0}
          <p class="mono sub">no zaps found yet. Zaps appear after someone sends sats via NIP-57 to this npub.</p>
        {:else}
          <ul class="zap-list">
            {#each zaps as z (z.id)}
              <li class="zap-item">
                <div class="zap-amount mono">{satsLabel(z.amountMsats)} {#if z.bolt11}<span class="bolt">bolt11</span>{/if}</div>
                {#if z.content}<p class="zap-content">"{z.content}"</p>{/if}
                <div class="mono zap-meta">
                  <span class="date">{fmtDate(z.created_at)}</span>
                  {#if z.zapRequest && typeof (z.zapRequest as any).pubkey === 'string'} <!-- ts-any-ok: Nostr relay data is untyped JSON -->
                    <span class="from" title={(z.zapRequest as any).pubkey as string}>from {shortNpub(hexToNpub(String((z.zapRequest as any).pubkey)))} </span> <!-- ts-any-ok -->
                  {/if}
                  {#if z.bolt11}<code class="bolt-code" title={z.bolt11}>{z.bolt11.slice(0,28)}...</code>{/if}
                </div>
              </li>
            {/each}
          </ul>
        {/if}
      </section>
    {:else if activeTab==='feeds' && isOwn}
      <section class="ess activity" aria-labelledby="feeds-h">
        <h2 id="feeds-h" class="mono ess-h"><Icon name="rss" size={18} /> your podcast output feeds</h2>
        <p class="mono help">Private, self-hosted RSS feeds generated by your sovereign instance. Subscribe in any podcast app with 1-click.</p>

        <div class="feed-cards">
          <!-- Master Feed -->
          <div class="feed-card">
            <div class="feed-card-header">
              <div>
                <span class="mono feed-tag">master feed · {masterCategory}</span>
                <h3 class="feed-card-title">{masterTitle}</h3>
              </div>
              <button type="button" class="mini mono copy-feed-btn" onclick={() => copyFeedUrl(masterFeedUrl, 'master')} aria-label="Copy master feed RSS link">
                <Icon name={copiedFeed === 'master' ? 'check' : 'rss'} size={12} />
                {copiedFeed === 'master' ? 'copied!' : 'copy rss'}
              </button>
            </div>
            <p class="mono feed-desc">{masterDesc}</p>
            {#if masterAuthor}
              <p class="mono feed-desc" style="font-size: calc(var(--ui-size) * .78); color: var(--ink-soft);">Host / author: {masterAuthor}</p>
            {/if}
            <code class="mono feed-url">{masterFeedUrl}</code>
          </div>

          <!-- Series Sub-Feeds -->
          {#if shows.length > 0}
            {#each shows as s (s.slug)}
              {@const showUrl = `${origin}/${creatorSlug}/${s.slug}/feed.xml`}
              <div class="feed-card">
                <div class="feed-card-header">
                  <div>
                    <span class="mono feed-tag">series sub-feed · {s.category || 'general'}</span>
                    <h3 class="feed-card-title">{s.name}</h3>
                  </div>
                  <button type="button" class="mini mono copy-feed-btn" onclick={() => copyFeedUrl(showUrl, s.slug)} aria-label={`Copy ${s.name} feed RSS link`}>
                    <Icon name={copiedFeed === s.slug ? 'check' : 'rss'} size={12} />
                    {copiedFeed === s.slug ? 'copied!' : 'copy rss'}
                  </button>
                </div>
                {#if s.author}
                  <p class="mono feed-desc">Host / author: {s.author}</p>
                {/if}
                <code class="mono feed-url">{showUrl}</code>
              </div>
            {/each}
          {:else}
            <div class="feed-empty mono">
              <p class="help">No dedicated series configured yet. When you define a series or playlist name in episode options, its isolated sub-feed appears here automatically.</p>
            </div>
          {/if}
        </div>
      </section>
    {/if}

    <section class="ess relays-ctrl" aria-labelledby="relays-h">
      <h2 id="relays-h" class="mono ess-h"><Icon name="rss" size={18} /> relays</h2>
      <p class="mono help">profile and activity are fetched directly from nostr relays (no vozonda backend). Add or remove relays to improve coverage.</p>
      <div class="relay-chips mono">
        {#each relays as r,i (r)}
          <span class="chip-relay">{r} <button type="button" class="x" onclick={()=>{ relays=relays.filter((_,ix)=>ix!==i) }} aria-label={`Remove ${r}`}>×</button></span>
        {/each}
      </div>
      <form class="relay-add" onsubmit={(e)=>{ e.preventDefault(); const f=(e.currentTarget as HTMLFormElement); const inp=(f.elements.namedItem('relay') as HTMLInputElement); const v=inp.value.trim(); if(v && v.startsWith('wss://') && !relays.includes(v)){ relays=[...relays,v]; inp.value=''}}}>
        <input name="relay" class="mono text-in" placeholder="wss://relay.example.com" aria-label="Add relay" />
        <button type="submit" class="mini mono">add</button>
      </form>
      <div class="mono help" style="margin-top: 8px;">
        active signer: {signerLabel}
        {#if activeIdentity}
          · {nostrShort(activeIdentity.npub)} via {activeIdentity.signer}
        {/if}
      </div>
      {#if getStoredIdentities().length > 1}
        <div class="mono sub" style="margin-top: 8px;">fast switch:</div>
        <div class="relay-chips mono">
          {#each getStoredIdentities() as sid (sid.pubkey)}
            <button type="button" class="chip-relay" style="cursor:pointer" onclick={()=>switchToStored(sid.pubkey)} aria-label={`Switch to ${nostrShort(sid.npub)}`}>
              {nostrShort(sid.npub)} ({sid.signer})
            </button>
          {/each}
        </div>
      {/if}
    </section>

    <!-- Collapsible drawer to look up any other profile -->
    <details class="lookup-drawer mono">
      <summary class="lookup-sum">
        <Icon name="search" size={13} />
        <span>look up another nostr profile</span>
      </summary>
      <div class="lookup-body">
        <p class="help">paste npub, hex 64, or nip05 (name@domain) to explore another creator's highlights and zaps.</p>
        <form class="resolve-form" onsubmit={onSubmit}>
          <input
            class="mono text-in"
            type="text"
            placeholder="npub1... or 64 hex or alice@example.com"
            aria-label="Nostr identifier"
            bind:value={query}
            spellcheck="false"
            autocomplete="off"
          />
          <button type="submit" class="go mono" disabled={resolving || loading}>{resolving ? 'resolving...' : loading ? 'loading...' : 'view'}</button>
        </form>
        {#if error}
          <p class="mono err" role="alert">// {error}</p>
        {/if}
      </div>
    </details>
  {:else}
    <!-- No profile loaded and not logged in: prominent search box -->
    <section class="ess resolver" aria-labelledby="resolve-h">
      <h2 id="resolve-h" class="mono ess-h"><Icon name="search" size={18} /> find profile</h2>
      <p class="mono help">paste npub, hex 64, or nip05 (name@domain) to view avatar, highlights, and zaps live from relays.</p>
      <form class="resolve-form" onsubmit={onSubmit}>
        <input
          class="mono text-in"
          type="text"
          placeholder="npub1... or 64 hex or alice@example.com"
          aria-label="Nostr identifier"
          bind:value={query}
          spellcheck="false"
          autocomplete="off"
        />
        <button type="submit" class="go mono" disabled={resolving || loading}>{resolving ? 'resolving...' : loading ? 'loading...' : 'view'}</button>
      </form>
      {#if error}
        <p class="mono err" role="alert">// {error}</p>
      {/if}
      {#if query.trim() && classifyInput(query)==='invalid' && query.trim().length>6}
        <p class="mono hint">tip: nip05 looks like name@domain, npub starts with npub1, hex is 64 chars</p>
      {/if}
    </section>
  {/if}
</main>

<style>
  .profile-screen { max-width: var(--content-max-width); margin: 0 auto; padding: var(--space-6) var(--space-4); display: grid; gap: var(--space-4); }
  .back-row { display:flex; align-items:center; gap: var(--space-3); }
  .back { display:inline-flex; align-items:center; gap:6px; background:transparent; border:1px solid var(--line); border-radius:var(--radius); padding:6px 10px; cursor:pointer; color:var(--ink-soft); }
  .back:hover { border-color:var(--ink); color:var(--ink); }
  .crumb { color:var(--ink-soft); font-size:calc(var(--ui-size)*.85); }
  .ess { border:1px solid var(--line); border-radius:var(--radius); padding:var(--space-5); display:grid; gap:var(--space-3); background: color-mix(in srgb, var(--paper) 4%, transparent); }
  .ess-h { display:flex; align-items:center; gap:var(--space-2); font-size:var(--ui-size); color:var(--ink); text-transform:lowercase; letter-spacing:.04em; margin:0; }
  .lookup-drawer { border:1px solid var(--line); border-radius:var(--radius); padding:var(--space-3) var(--space-4); background: color-mix(in srgb, var(--paper) 2%, transparent); }
  .lookup-sum { display:flex; align-items:center; gap:8px; cursor:pointer; color:var(--ink-soft); font-size:calc(var(--ui-size)*.88); user-select:none; }
  .lookup-sum:hover { color:var(--ink); }
  .lookup-body { margin-top:var(--space-3); display:grid; gap:var(--space-2); }
  .help { color:var(--ink-soft); font-size:calc(var(--ui-size)*.85); margin:0; line-height:1.45; }
  .sub { color:var(--ink-soft); font-size:calc(var(--ui-size)*.85); margin:0; }
  .err { color: var(--danger); margin:0; white-space:pre-wrap; }
  .hint { color:var(--ink-soft); font-size:calc(var(--ui-size)*.8); margin:0; }
  .text-in { width:100%; min-height:42px; font-family:var(--font-mono); font-size:var(--ui-size); background: color-mix(in srgb, var(--ink) 4%, var(--paper)); border:1px solid color-mix(in srgb, var(--ink) 18%, var(--line)); border-radius:var(--radius); padding:var(--space-2) var(--space-3); color:var(--ink); }
  .text-in:focus-visible { outline:2px solid var(--green); outline-offset: 2px; border-color:var(--green); }
  .resolve-form { display:flex; gap:var(--space-2); align-items:center; flex-wrap:wrap; }
  .resolve-form .text-in { flex:1 1 260px; }
  .go { background:var(--ink); color:var(--paper); border:1px solid var(--ink); border-radius:var(--radius); padding:var(--space-2) var(--space-4); font-family:var(--font-mono); font-size:var(--ui-size); cursor:pointer; min-height:42px; font-weight:600; }
  .go:hover { background:var(--green); border-color:var(--green); }
  .go:disabled { opacity:.5; cursor:not-allowed; }
  .hero-top { display:flex; gap:var(--space-4); align-items:flex-start; flex-wrap:wrap; }
  .avatar-wrap { flex:none; }
  .avatar { width:88px; height:88px; border-radius:50%; object-fit:cover; border:2px solid var(--line); display:block; background:var(--paper); }
  .avatar.fallback { width:88px; height:88px; border-radius:50%; border:2px solid var(--line); display:grid; place-items:center; background: color-mix(in srgb, var(--line) 35%, transparent); color:var(--ink-soft); }
  .fallback-initial { font-family:var(--font-serif); font-size:1.8rem; font-weight:600; color:var(--ink); }
  .hero-meta { flex:1 1 260px; min-width:0; display:grid; gap:6px; }
  .name { font-family:var(--font-serif); font-size: clamp(1.4rem, 3vw, 1.9rem); font-weight:600; line-height:1.15; margin:0; color:var(--ink); overflow-wrap:anywhere; }
  .about { margin:0; color:var(--ink-soft); font-size:0.98rem; line-height:1.5; max-width:52ch; white-space:pre-wrap; }
  .nip05 { display:inline-flex; align-items:center; gap:6px; margin:0; font-size:calc(var(--ui-size)*.88); }
  .nip05.valid { color:var(--green); }
  .nip05.invalid { color:var(--danger); }
  .badge { display:inline-block; border:1px solid var(--line); border-radius:var(--radius); padding:1px 6px; font-size:calc(var(--ui-size)*.72); letter-spacing:.04em; }
  .badge.ok { border-color: color-mix(in srgb, var(--green) 40%, var(--line)); color:var(--green); background: color-mix(in srgb, var(--green) 8%, transparent); }
  .badge.bad { border-color: color-mix(in srgb, var(--danger) 40%, var(--line)); color:var(--danger); background: color-mix(in srgb, var(--danger) 8%, transparent); }
  .meta-row { display:flex; flex-wrap:wrap; gap:var(--space-2); align-items:center; }
  .chip-lud, .chip-own, .chip-signer { display:inline-flex; align-items:center; gap:6px; border:1px solid var(--line); border-radius:var(--radius); padding:3px 8px; font-size:calc(var(--ui-size)*.82); }
  .chip-lud { color:var(--green); border-color: color-mix(in srgb, var(--green) 30%, var(--line)); background: color-mix(in srgb, var(--green) 6%, transparent); }
  .chip-own { color:var(--ink); border-color:var(--green); background: color-mix(in srgb, var(--green) 6%, transparent); }
  .chip-signer { color:var(--ink-soft); }
  .npub-row { display:flex; flex-wrap:wrap; gap:var(--space-3); }
  .npub-box { display:inline-flex; align-items:center; gap:8px; background: color-mix(in srgb, var(--ink) 4%, var(--paper)); border:1px solid var(--line); border-radius:var(--radius); padding:6px 8px; }
  .label { color:var(--ink-soft); font-size:calc(var(--ui-size)*.8); text-transform:lowercase; }
  .code { color:var(--ink); font-size:calc(var(--ui-size)*.85); }
  .mini { background:transparent; border:1px solid var(--line); border-radius:var(--radius); padding:4px 8px; cursor:pointer; min-height:28px; }
  .mini:hover { border-color:var(--green); color:var(--green); }
  .stats { display:flex; flex-wrap:wrap; gap:var(--space-2); align-items:center; color:var(--ink-soft); font-size:calc(var(--ui-size)*.85); border-top:1px solid var(--line); padding-top:var(--space-2); }
  .dot { color:var(--line); }
  .tabs { display:flex; gap:var(--space-2); border-bottom:1px solid var(--line); padding-bottom:var(--space-2); }
  .tabs button { background: color-mix(in srgb, var(--ink) 4%, var(--paper)); border:1px solid var(--line); border-radius:var(--radius); padding:6px 12px; cursor:pointer; min-height:36px; display:inline-flex; align-items:center; gap:6px; }
  .tabs button.sel { background:var(--ink); color:var(--paper); border-color:var(--ink); font-weight:600; }
  .hl-list, .zap-list { list-style:none; margin:0; padding:0; display:grid; gap:var(--space-3); }
  .hl-item, .zap-item { border:1px solid var(--line); border-radius:var(--radius); padding:var(--space-3); display:grid; gap:var(--space-2); background: transparent; }
  .hl-item:hover, .zap-item:hover { border-color: color-mix(in srgb, var(--ink) 20%, var(--line)); }
  .quote { margin:0; font-family:var(--font-serif); font-size:1.02rem; line-height:1.5; color:var(--ink); font-style:italic; }
  .hl-meta, .zap-meta { display:flex; flex-wrap:wrap; gap:var(--space-2); align-items:center; color:var(--ink-soft); font-size:calc(var(--ui-size)*.82); }
  .date { color:var(--ink-soft); }
  .zap-amount { font-weight:600; color:var(--green); }
  .bolt { color:var(--ink-soft); font-weight:400; border:1px solid var(--line); border-radius:var(--radius); padding:1px 6px; font-size:calc(var(--ui-size)*.72); }
  .zap-content { margin:0; color:var(--ink); line-height:1.5; }
  .bolt-code { font-size:calc(var(--ui-size)*.78); background: color-mix(in srgb, var(--ink) 4%, var(--paper)); padding:2px 6px; border-radius:var(--radius); overflow-wrap:anywhere; }
  .link { color:var(--green); text-decoration:underline; text-underline-offset:2px; overflow-wrap:anywhere; }
  .link:hover { color:var(--ink); }
  .relay-chips { display:flex; flex-wrap:wrap; gap:var(--space-2); }
  .chip-relay { display:inline-flex; align-items:center; gap:6px; background: color-mix(in srgb, var(--ink) 4%, var(--paper)); border:1px solid var(--line); border-radius:var(--radius); padding:4px 8px; font-size:calc(var(--ui-size)*.82); }
  .chip-relay .x { background:transparent; border:none; cursor:pointer; color:var(--ink-soft); padding:0 2px; font-size:1rem; line-height:1; }
  .chip-relay .x:hover { color:var(--danger); }
  .relay-add { display:flex; gap:var(--space-2); align-items:center; flex-wrap:wrap; }
  .relay-add .text-in { flex:1 1 260px; }
  .profile-actions { display:flex; flex-wrap:wrap; gap:var(--space-2); align-items:center; }
  .mini.danger { color: var(--danger); border-color: color-mix(in srgb, var(--danger) 30%, var(--line)); }
  .mini.danger:hover { color: var(--paper); background: var(--danger); border-color: var(--danger); }
  .signer-box { display:flex; flex-wrap:wrap; gap:var(--space-2); align-items:center; border-top:1px solid var(--line); padding-top:var(--space-2); color:var(--ink-soft); font-size:calc(var(--ui-size)*.82); }
  .signer-box .signer-text { color: var(--ink); }
  .signer-box .signer-id { color: var(--ink-soft); border:1px solid var(--line); border-radius:var(--radius); padding:2px 8px; }
  .loading { color:var(--ink-soft); display:flex; align-items:center; gap:8px; }
  .feed-cards { display: grid; gap: var(--space-3); }
  .feed-card { border: 1px solid var(--line); border-radius: var(--radius); padding: var(--space-4); display: grid; gap: var(--space-2); background: color-mix(in srgb, var(--ink) 2%, var(--paper)); }
  .feed-card-header { display: flex; justify-content: space-between; align-items: flex-start; gap: var(--space-2); flex-wrap: wrap; }
  .feed-tag { font-size: calc(var(--ui-size) * .76); color: var(--green); text-transform: lowercase; }
  .feed-card-title { font-family: var(--font-serif); font-size: 1.15rem; margin: 2px 0 0 0; color: var(--ink); }
  .feed-desc { font-size: calc(var(--ui-size) * .84); color: var(--ink-soft); margin: 0; }
  .feed-url { font-size: calc(var(--ui-size) * .8); color: var(--ink); background: color-mix(in srgb, var(--ink) 5%, var(--paper)); padding: 4px 8px; border-radius: var(--radius); border: 1px solid var(--line); overflow-wrap: anywhere; }
  .copy-feed-btn { display: inline-flex; align-items: center; gap: 6px; }
  .feed-empty { border: 1px dashed var(--line); border-radius: var(--radius); padding: var(--space-4); }
  @media (max-width: 600px) {
    .profile-screen { padding: var(--space-4) var(--space-3); }
    .avatar, .avatar.fallback { width:72px; height:72px; }
    .hero-top { gap:var(--space-3); }
    .resolve-form { flex-direction:column; align-items:stretch; }
  }
</style>

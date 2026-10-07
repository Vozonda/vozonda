<script lang="ts">
  import type { JobSummary, Meta, ShowItem, VoiceProfile, WatchlistEntry } from '../api'
  import { fetchShows, getSettings } from '../api'
  import EssentialsSection from './EssentialsSection.svelte'
  import TemplateTiles from './TemplateTiles.svelte'
  import Icon from './Icon.svelte'

  interface TemplateVoices {
    a?: string
    b?: string
    c?: string
    solo?: string
    a_emotion?: string
    b_emotion?: string
    c_emotion?: string
    solo_emotion?: string
  }

  interface TemplateValues {
    style: string
    format: 'dialog' | 'narration'
    hosts: number
    explicit: boolean
    voices?: TemplateVoices
  }

  const FEED_TEMPLATES: { label: string; context: string; values: TemplateValues }[] = [
    { label: 'morning dispatch', context: '2 hosts (m/f · serious + calm) · serious', values: { style: 'serious', format: 'dialog', hosts: 2, explicit: false, voices: { a: 'dylan', b: 'sohee', a_emotion: 'serious', b_emotion: 'calm' } } },
    { label: 'feature story', context: '2 hosts (m/f · neutral + warm) · balanced', values: { style: 'balanced', format: 'dialog', hosts: 2, explicit: false, voices: { a: 'dylan', b: 'sohee', a_emotion: 'neutral', b_emotion: 'warm' } } },
    { label: 'trio roundtable', context: '3 hosts (2m/1f · energetic + dramatic + serious) · clash', values: { style: 'clash', format: 'dialog', hosts: 3, explicit: false, voices: { a: 'dylan', b: 'sohee', c: 'uncle_fu', a_emotion: 'energetic', b_emotion: 'dramatic', c_emotion: 'serious' } } },
    { label: 'tech roast', context: '2 hosts (m/f · cheerful + energetic) · tech roast', values: { style: 'tech_roast', format: 'dialog', hosts: 2, explicit: false, voices: { a: 'dylan', b: 'sohee', a_emotion: 'cheerful', b_emotion: 'energetic' } } },
    { label: 'true crime dossier', context: '2 hosts (m/f · dramatic + serious) · true crime', values: { style: 'true_crime', format: 'dialog', hosts: 2, explicit: false, voices: { a: 'dylan', b: 'sohee', a_emotion: 'dramatic', b_emotion: 'serious' } } },
    { label: 'explainer lab', context: '2 hosts (m/f · cheerful + warm) · eli5', values: { style: 'eli5', format: 'dialog', hosts: 2, explicit: false, voices: { a: 'dylan', b: 'sohee', a_emotion: 'cheerful', b_emotion: 'warm' } } },
    { label: 'socratic dialogue', context: '2 hosts (m/f · serious + calm) · socrates', values: { style: 'socrates', format: 'dialog', hosts: 2, explicit: false, voices: { a: 'dylan', b: 'sohee', a_emotion: 'serious', b_emotion: 'calm' } } },
    { label: 'solo audio essay', context: '1 host (f · calm) · balanced', values: { style: 'balanced', format: 'narration', hosts: 1, explicit: false, voices: { solo: 'sohee', solo_emotion: 'calm' } } },
    { label: 'zen meditation', context: '1 host (f · calm) · meditation', values: { style: 'meditation', format: 'narration', hosts: 1, explicit: false, voices: { solo: 'sohee', solo_emotion: 'calm' } } }
  ]

  let {
    watchlists,
    episodes,
    meta,
    onback,
    onSettings,
    onLibrary,
    onAdd,
    onRemove,
    onToggle,
    onCheck,
    onDigestToggle,
    onDigestNow,
    onResume,
    onSaveVoice,
    onUpdateSettings
  }: {
    watchlists: WatchlistEntry[]
    episodes: JobSummary[]
    meta: Meta | null
    onback: () => void
    onSettings: () => void
    onLibrary?: () => void
    onAdd: (entry: { feed_url: string; style: string; format: 'dialog' | 'narration'; language: string; hosts: number; explicit: boolean }) => Promise<void>
    onRemove: (id: string) => Promise<void>
    onToggle: (id: string, enabled: boolean) => Promise<void>
    onCheck: (id: string) => Promise<void>
    onDigestToggle: (id: string, digestMode: boolean, digestCount: number) => Promise<void>
    onDigestNow: (id: string) => Promise<{ digest_job: string; sources: string[] }>
    onResume: (e: JobSummary) => void
    onSaveVoice: (id: string, voice: VoiceProfile) => Promise<void>
    onUpdateSettings: (
      id: string,
      patch: Partial<{ style: string; format: 'dialog' | 'narration'; language: string; hosts: number; explicit: boolean; show_slug: string }>
    ) => Promise<void>
  } = $props()

  let feedUrl = $state('')
  // DUE-078: per-feed voice drafts, keyed by feed id; seeded lazily from the
  // stored profile so the editor starts from what the feed actually uses
  let voiceDrafts = $state<Record<string, VoiceProfile>>({})
  let savingVoice = $state('')
  let settingsDrafts = $state<Record<string, { style: string; format: string; language: string; hosts: number; explicit: boolean; show_slug?: string; template?: string }>>({})
  let savingSettings = $state('')

  let activeTuneFeed = $state<WatchlistEntry | null>(null)
  let shows = $state<ShowItem[]>([])
  let activeTuneValues = $state<{
    style: string
    format: 'dialog' | 'narration'
    language: string
    hosts: number
    explicit: boolean
    digest_mode: boolean
    digest_count: number
    show_slug: string
    template?: string
  }>({
    style: 'balanced',
    format: 'dialog',
    language: 'auto',
    hosts: 2,
    explicit: false,
    digest_mode: false,
    digest_count: 3,
    show_slug: ''
  })
  let activeTuneVoice = $state<VoiceProfile>({})
  let activeSaveMsg = $state('')

  function openTuneModal(w: WatchlistEntry) {
    activeTuneFeed = w
    void fetchShows().then((s) => (shows = s)).catch(() => {})
    activeTuneValues = {
      style: settingsDrafts[w.id]?.style ?? w.style,
      format: (settingsDrafts[w.id]?.format ?? w.format) as 'dialog' | 'narration',
      language: settingsDrafts[w.id]?.language ?? w.language,
      hosts: settingsDrafts[w.id]?.hosts ?? w.hosts,
      explicit: settingsDrafts[w.id]?.explicit ?? !!w.explicit,
      digest_mode: !!(w.digest_mode),
      digest_count: w.digest_count ?? 3,
      show_slug: settingsDrafts[w.id]?.show_slug ?? (w.show_slug === 'default' ? 'default' : (w.show_slug?.replace(/^s/, '') ?? '')),
      template: settingsDrafts[w.id]?.template
    }
    activeTuneVoice = { ...(voiceDrafts[w.id] ?? w.voice_profile ?? {}) }
    activeSaveMsg = ''
  }

  function closeTuneModal() {
    activeTuneFeed = null
    activeSaveMsg = ''
  }

  async function saveActiveTune() {
    if (!activeTuneFeed) return
    const w = activeTuneFeed
    savingSettings = w.id
    try {
      await onUpdateSettings(w.id, {
        style: activeTuneValues.style,
        format: activeTuneValues.format,
        language: activeTuneValues.language,
        hosts: activeTuneValues.hosts,
        explicit: activeTuneValues.explicit,
        show_slug: activeTuneValues.show_slug
      })
      await onDigestToggle(w.id, activeTuneValues.digest_mode, activeTuneValues.digest_count)
      await onSaveVoice(w.id, activeTuneVoice)
      settingsDrafts[w.id] = { ...activeTuneValues }
      voiceDrafts[w.id] = { ...activeTuneVoice }
      activeSaveMsg = 'settings saved!'
      setTimeout(() => {
        if (activeSaveMsg === 'settings saved!') activeSaveMsg = ''
      }, 2500)
    } finally {
      savingSettings = ''
    }
  }

  function onKeydown(e: KeyboardEvent) {
    if (e.key === 'Escape' && activeTuneFeed) {
      closeTuneModal()
    }
  }

  const timbreKey = (v: string) => `${v}.timbre` as 'a.timbre' | 'b.timbre' | 'c.timbre'
  const nameKey = (v: string) => `${v}.name` as 'a.name' | 'b.name' | 'c.name'

  // drafts are created in an effect, never inside template expressions:
  // svelte 5 forbids state mutation during render (state_unsafe_mutation
  // killed the whole watchlist render - cards stayed invisible)
  $effect(() => {
    for (const w of watchlists) {
      if (!voiceDrafts[w.id]) voiceDrafts[w.id] = { ...(w.voice_profile ?? {}) }
    }
  })

  function draftFor(w: WatchlistEntry): VoiceProfile {
    return voiceDrafts[w.id] ?? {}
  }

  async function saveVoice(w: WatchlistEntry) {
    savingVoice = w.id
    try {
      await onSaveVoice(w.id, voiceDrafts[w.id] ?? {})
      voiceDrafts[w.id] = { ...(voiceDrafts[w.id] ?? {}) }
    } finally {
      savingVoice = ''
    }
  }

  function settingsDraftFor(w: WatchlistEntry) {
    return settingsDrafts[w.id] ?? { style: w.style, format: w.format as 'dialog' | 'narration', language: w.language, hosts: w.hosts, explicit: !!w.explicit }
  }

  async function saveAllFeedSettings(w: WatchlistEntry) {
    savingSettings = w.id
    try {
      const d = settingsDraftFor(w)
      await onUpdateSettings(w.id, {
        style: d.style,
        format: d.format as 'dialog' | 'narration',
        language: d.language,
        hosts: d.hosts,
        explicit: d.explicit
      })
      await onSaveVoice(w.id, voiceDrafts[w.id] ?? {})
      settingsDrafts[w.id] = { ...d }
    } finally {
      savingSettings = ''
    }
  }

  function goToAdd() {
    const input = document.querySelector<HTMLInputElement>('.add-form input[type="url"]')
    input?.focus()
    input?.scrollIntoView({ behavior: 'smooth', block: 'center' })
  }
  let feedVals = $state<{ style: string; format: 'dialog' | 'narration'; language: string; hosts: number; explicit: boolean }>({
    style: 'balanced',
    format: 'dialog',
    language: 'auto',
    hosts: 2,
    explicit: false
  })
  let busy = $state(false)
  let error = $state('')
  let addedMsg = $state('')
  let checking = $state<string | null>(null)

  const feedXmlUrl = new URL(`${import.meta.env.VITE_API_BASE ?? ''}/feed.xml`, window.location.origin).href
  let copiedFeed = $state(false)
  let copiedWatchlistFeed = $state<string | null>(null)
  async function copyFeed() {
    try {
      await navigator.clipboard.writeText(feedXmlUrl)
      copiedFeed = true
      setTimeout(() => (copiedFeed = false), 2000)
    } catch {
      copiedFeed = false
    }
  }
  let creatorSlug = $state('vozonda')
  $effect(() => {
    void getSettings().then((s) => {
      const raw = (s.settings['show.name'] || s.settings['show.author'] || 'vozonda').trim()
      if (raw) creatorSlug = slugify(raw)
    }).catch(() => {})
  })
  function slugify(s: string): string {
    return s.toLowerCase().replace(/[^a-z0-9]+/g, '-').replace(/^-|-$/g, '').slice(0, 32) || 'show'
  }
  function watchlistShowFeedUrl(w: WatchlistEntry): string {
    // hierarchical: /{creator}/{watchlist_slug}/feed.xml
    const watchlistSlug = slugify(w.id)
    const base = import.meta.env.VITE_API_BASE ?? ''
    return new URL(`${base}/${creatorSlug}/${watchlistSlug}/feed.xml`, window.location.origin).href
  }
  async function copyWatchlistFeed(w: WatchlistEntry) {
    try {
      await navigator.clipboard.writeText(watchlistShowFeedUrl(w))
      copiedWatchlistFeed = w.id
      setTimeout(() => {
        if (copiedWatchlistFeed === w.id) copiedWatchlistFeed = null
      }, 2000)
    } catch {
      copiedWatchlistFeed = null
    }
  }

  function dateLabel(ts?: number | null): string {
    if (!ts) return 'never'
    const d = new Date(ts * 1000)
    return d.toLocaleDateString('en-US', { month: 'short', day: 'numeric' }) + ', ' + d.toLocaleTimeString('en-US', { hour: '2-digit', minute: '2-digit', hour12: false })
  }

  async function submit(e: SubmitEvent) {
    e.preventDefault()
    let url = feedUrl.trim()
    if (!url || busy) return
    // scheme-less pastes are valid feeds behind https; native url
    // validation would block them silently (same fix as compose)
    if (!/^https?:\/\//i.test(url)) {
      url = `https://${url}`
      feedUrl = url
    }
    busy = true
    error = ''
    addedMsg = ''
    try {
      await onAdd({ feed_url: url, style: feedVals.style, format: feedVals.format, language: feedVals.language, hosts: feedVals.hosts, explicit: feedVals.explicit })
      feedUrl = ''
      addedMsg = 'feed added. first episodes render on the next check (within 10 min).'
    } catch (err) {
      error = err instanceof Error ? err.message : 'failed'
    } finally {
      busy = false
    }
  }

  async function del(id: string) {
    error = ''
    try {
      await onRemove(id)
    } catch (err) {
      error = err instanceof Error ? err.message : 'delete failed'
    }
  }

  let toggling = $state<string | null>(null)

  async function toggle(id: string, enabled: boolean) {
    toggling = id
    error = ''
    try {
      await onToggle(id, enabled)
    } catch (err) {
      error = err instanceof Error ? err.message : 'toggle failed'
    } finally {
      toggling = null
    }
  }

  async function check(id: string) {
    checking = id
    error = ''
    try {
      await onCheck(id)
    } catch (err) {
      error = err instanceof Error ? err.message : 'check failed'
    } finally {
      checking = null
    }
  }

  let digestBusy = $state<string | null>(null)
  let digestMsg = $state<Record<string, string>>({})

  async function digestToggle(id: string, mode: boolean, count: number) {
    digestBusy = id
    error = ''
    try {
      await onDigestToggle(id, mode, count)
    } catch (err) {
      error = err instanceof Error ? err.message : 'digest toggle failed'
    } finally {
      digestBusy = null
    }
  }

  async function renderDigest(id: string) {
    digestBusy = id
    error = ''
    try {
      const r = await onDigestNow(id)
      digestMsg[id] = `digest rendering: ${r.sources.length} stories · find it in recent when done`
    } catch (err) {
      digestMsg[id] = ''
      error = err instanceof Error ? err.message : 'digest render failed'
    } finally {
      digestBusy = null
    }
  }

  const autoEpisodes = $derived(episodes.filter((e) => e.watchlist_id))
  const recentAutoEpisodes = $derived(autoEpisodes.slice(0, 5))

  const lastDigestByWatchlist = $derived.by(() => {
    const m = new Map<string, JobSummary>()
    for (const e of episodes) {
      if (!e.digest || !e.watchlist_id) continue
      if (e.state !== 'done') continue
      const prev = m.get(e.watchlist_id)
      if (!prev || (e.created_at ?? 0) > (prev.created_at ?? 0)) m.set(e.watchlist_id, e)
    }
    return m
  })

  function lastDigestLabel(e: JobSummary): string {
    const stories = e.digest_sources?.length
    const n = stories ?? '?'
    const min = e.duration_ms ? `${Math.round(e.duration_ms / 60000)} min` : '?'
    return `last digest: ${n} stories · ${min}`
  }

  const episodeCountByWatchlist = $derived.by(() => {
    const m = new Map<string, number>()
    for (const e of episodes) {
      if (!e.watchlist_id) continue
      m.set(e.watchlist_id, (m.get(e.watchlist_id) ?? 0) + 1)
    }
    return m
  })

  function domainOf(url: string): string {
    try {
      return new URL(url).hostname.replace(/^www\./, '')
    } catch {
      return url
    }
  }

  function pathOf(url: string): string {
    try {
      const p = new URL(url).pathname
      return p === '/' ? '' : p
    } catch {
      return ''
    }
  }

  function freshnessState(w: WatchlistEntry): 'fresh' | 'soon' | 'error' {
    if (w.last_error) return 'error'
    if (!w.last_checked) return 'soon'
    const age = Date.now() / 1000 - w.last_checked
    return age < 30 * 60 ? 'fresh' : 'soon'
  }
  function freshnessLabel(s: 'fresh' | 'soon' | 'error'): string {
    if (s === 'fresh') return 'up to date'
    if (s === 'error') return 'error'
    return 'next check soon'
  }
</script>

<svelte:window onkeydown={onKeydown} />

<main>
  <section class="ess add-section" aria-labelledby="wf-add-h">
    <h2 id="wf-add-h" class="mono ess-h"><Icon name="plus" size={18} /> watch a feed</h2>
    <p class="mono sec-help">new articles turn into episodes automatically. fine-tune voices, style and digest mode anytime.</p>
    <form class="add-form" onsubmit={submit} novalidate>
      <div class="add-row">
        <label class="mono field" style="flex:1;">
          <span>feed link</span>
          <input
            type="url"
            bind:value={feedUrl}
            placeholder="https://example.com/feed.xml"
            aria-label="Feed URL"
            required
          />
        </label>
        <button type="submit" disabled={busy} class="mono submit">{busy ? '···' : 'add feed'}</button>
      </div>
      {#if addedMsg}
        <p class="mono added" role="status" aria-live="polite">✓ {addedMsg}</p>
      {/if}
      {#if error}
        <p class="mono err" role="alert" aria-live="assertive">// {error}</p>
      {/if}
    </form>
  </section>

  <section class="ess" aria-labelledby="wf-list-h">
    <h2 id="wf-list-h" class="mono ess-h"><Icon name="rss" size={18} /> watched feeds ({watchlists.length})</h2>
    <p class="mono sec-help">every finished episode lands in your podcast feed. point any podcast app at the url.</p>
    <div class="feed-out">
      <span class="mono fo-lab"><Icon name="rss" size={14} /> podcast feed</span>
      <span class="mono fo-url" title={feedXmlUrl}>{feedXmlUrl}</span>
      <button class="link mono copy-btn" onclick={() => void copyFeed()}>{copiedFeed ? 'copied!' : 'copy'}</button>
    </div>
    {#if watchlists.length === 0}
      <p class="mono note" role="status" aria-live="polite">
        // nothing yet. <button class="link mono" onclick={goToAdd}>add a feed above</button>
      </p>
    {:else}
      <ul class="shelf">
        {#each watchlists as w (w.id)}
          <li class="card">
            <!-- Header: Domain, Path, Status Pill & Polling Status Badge -->
            <div class="card-head">
              <div class="card-title-group">
                <span class="mono card-domain" title={w.feed_url}>{domainOf(w.feed_url)}</span>
                {#if pathOf(w.feed_url)}
                  <span class="mono card-path" title={w.feed_url}>{pathOf(w.feed_url)}</span>
                {/if}
              </div>
              <div class="card-status-group">
                <span class="mono freshness-pill" class:fresh={freshnessState(w) === 'fresh'} class:soon={freshnessState(w) === 'soon'} class:error={freshnessState(w) === 'error'} title={freshnessLabel(freshnessState(w))}>
                  <span class="freshness-dot"></span>
                  {freshnessLabel(freshnessState(w))}
                </span>
                <span class="mono badge">{w.enabled ? 'polling on' : 'polling paused'}</span>
              </div>
            </div>

            <!-- Clean Tags & Time Summary -->
            <div class="card-meta-line mono">
              <div class="card-tags">
                <span class="tag-pill">{w.style}</span>
                <span class="tag-pill">{w.format === 'dialog' ? `${w.hosts} hosts` : 'narrator'}</span>
                <span class="tag-pill">lang: {w.language}</span>
                <span class="tag-pill">{w.digest_mode ? `digest: ${w.digest_count ?? 3} stories` : 'per story'}</span>
                <span class="tag-pill">{episodeCountByWatchlist.get(w.id) ?? 0} eps</span>
              </div>
              <span class="time-readout" role="status" aria-live="polite">
                checked {dateLabel(w.last_checked)} · added {dateLabel(w.created_at)}
              </span>
            </div>

            <div class="feed-out mono" style="margin-top: var(--space-2);">
              <span class="fo-lab"><Icon name="rss" size={12} /> show rss</span>
              <span class="fo-url" title={watchlistShowFeedUrl(w)}>{watchlistShowFeedUrl(w)}</span>
              <button class="link mono copy-btn" onclick={() => void copyWatchlistFeed(w)}>{copiedWatchlistFeed === w.id ? 'copied!' : 'copy'}</button>
            </div>

            {#if w.last_error}
              <p class="mono err" role="alert">// {w.last_error}</p>
            {/if}

            <!-- Latest Digest Bar (if available) -->
            {#if w.digest_mode && lastDigestByWatchlist.get(w.id)}
              {@const d = lastDigestByWatchlist.get(w.id)!}
              <div class="dh-latest-bar">
                <span class="mono dh-latest-label">latest digest:</span>
                <button
                  type="button"
                  class="link mono dh-latest-play"
                  onclick={() => onResume(d)}
                  aria-label={`Play latest digest: ${d.title || 'Digest'}`}
                >
                  <Icon name="playtri" size={11} />
                  <span class="dh-latest-title">{d.title || 'latest digest'}</span>
                  {#if d.duration_ms}
                    <span class="dh-dur-badge mono">{Math.round(d.duration_ms / 60000)}m</span>
                  {/if}
                </button>
                <span class="mono dh-latest-time">{dateLabel(d.created_at)}</span>
              </div>
            {/if}

            <!-- Card Actions Bar (Uniform Calm Grid Buttons with Icons) -->
            <div class="card-actions">
              <button type="button" class="action-btn mono" onclick={() => openTuneModal(w)}>
                <Icon name="sliders" size={13} />
                <span>tune feed</span>
              </button>
              {#if w.digest_mode}
                <button
                  type="button"
                  class="action-btn mono"
                  disabled={digestBusy === w.id}
                  onclick={() => void renderDigest(w.id)}
                >
                  <Icon name="layers" size={13} />
                  <span>{digestBusy === w.id ? 'bundling…' : `generate digest (${w.digest_count ?? 3})`}</span>
                </button>
              {/if}
              <button
                type="button"
                class="action-btn mono"
                onclick={() => void check(w.id)}
                disabled={checking === w.id}
              >
                <Icon name="refresh" size={13} />
                <span>{checking === w.id ? 'syncing…' : 'sync feed'}</span>
              </button>
              <button
                type="button"
                class="action-btn mono"
                role="switch"
                aria-checked={w.enabled}
                disabled={toggling === w.id}
                onclick={() => void toggle(w.id, !w.enabled)}
              >
                <Icon name={w.enabled ? 'pausebars' : 'playtri'} size={12} />
                <span>{w.enabled ? 'pause polling' : 'resume polling'}</span>
              </button>
              <button
                type="button"
                class="action-btn mono danger"
                onclick={() => void del(w.id)}
              >
                <Icon name="trash" size={13} />
                <span>unwatch</span>
              </button>
            </div>
            {#if digestMsg[w.id]}
              <p class="mono dmsg" role="status" aria-live="polite">{digestMsg[w.id]}</p>
            {/if}
          </li>
        {/each}
      </ul>
    {/if}
  </section>

  <section class="ess" aria-labelledby="wf-auto-h">
    <div class="sec-head-row">
      <h2 id="wf-auto-h" class="mono ess-h"><Icon name="playtri" size={18} /> auto episodes ({autoEpisodes.length})</h2>
      {#if onLibrary && autoEpisodes.length > 5}
        <button type="button" class="link mono sec-head-link" onclick={onLibrary}>
          view all in library ({autoEpisodes.length}) →
        </button>
      {/if}
    </div>
    <p class="mono sec-help">rendered from your feeds automatically. showing the 5 most recent.</p>
    {#if autoEpisodes.length === 0}
      <p class="mono note">// no auto-rendered episodes yet. add a feed or sync above.</p>
    {:else}
      <ul class="shelf">
        {#each recentAutoEpisodes as e (e.id)}
          <li>
            <button
              class="entry"
              onclick={() => onResume(e)}
              aria-label={`Play auto episode: ${e.title || 'Untitled'}`}
            >
              <div class="etitle">{e.title || 'untitled episode'}</div>
              {#if e.description}
                <div class="edesc">{e.description}</div>
              {/if}
              <div class="mono emeta">
                {e.style} · {e.format} · {dateLabel(e.created_at)}
                {#if e.duration_ms}
                  · {Math.round(e.duration_ms / 60000)}m
                {/if}
                {#if e.url}
                  · {domainOf(e.url)}
                {/if}
              </div>
            </button>
          </li>
        {/each}
      </ul>
      {#if autoEpisodes.length > 5 && onLibrary}
        <div class="more-row">
          <button type="button" class="action-btn mono" onclick={onLibrary}>
            <Icon name="history" size={13} />
            <span>view all {autoEpisodes.length} episodes in library →</span>
          </button>
        </div>
      {/if}
    {/if}
  </section>
</main>

{#if activeTuneFeed}
  <div class="tune-overlay" onclick={(e) => { if (e.target === e.currentTarget) closeTuneModal() }} role="presentation">
    <div
      class="tune-dialog"
      role="dialog"
      aria-modal="true"
      aria-labelledby="tune-modal-h"
      tabindex="-1"
    >
      <div class="tune-dialog-head">
        <div class="td-title-group">
          <h2 id="tune-modal-h" class="mono td-title">
            <Icon name="sliders" size={18} />
            tune feed · {domainOf(activeTuneFeed.feed_url)}
          </h2>
          <span class="mono td-url" title={activeTuneFeed.feed_url}>{activeTuneFeed.feed_url}</span>
        </div>
        <button type="button" class="link mono td-close" onclick={closeTuneModal} aria-label="Close settings">
          ✕ close
        </button>
      </div>

      <div class="tune-dialog-body">
        <!-- 1. Quick Actions Bar -->
        <div class="tune-dialog-actions">
          <button
            type="button"
            class="action-btn mono"
            onclick={() => void check(activeTuneFeed!.id)}
            disabled={checking === activeTuneFeed.id}
          >
            <Icon name="refresh" size={13} />
            <span>{checking === activeTuneFeed.id ? 'syncing…' : 'sync feed'}</span>
          </button>
          <button
            type="button"
            class="action-btn mono"
            role="switch"
            aria-checked={activeTuneFeed.enabled}
            disabled={toggling === activeTuneFeed.id}
            onclick={() => void toggle(activeTuneFeed!.id, !activeTuneFeed!.enabled)}
          >
            <Icon name={activeTuneFeed.enabled ? 'pausebars' : 'playtri'} size={12} />
            <span>{activeTuneFeed.enabled ? 'pause polling' : 'resume polling'}</span>
          </button>
          <button
            type="button"
            class="action-btn mono danger"
            onclick={() => { const id = activeTuneFeed!.id; closeTuneModal(); void del(id); }}
          >
            <Icon name="trash" size={13} />
            <span>unwatch feed</span>
          </button>
        </div>

        <!-- 2. Templates Section -->
        <section class="ess td-section" aria-labelledby="td-tpl-h">
          <h3 id="td-tpl-h" class="mono ess-h"><Icon name="template" size={16} /> template</h3>
          <p class="mono td-help">a template prefills style, format and voices for this feed; engine and pacing follow your global settings.</p>
          <TemplateTiles
            activeEngine={meta?.runtime?.tts_engine ?? 'qwen_tts'}
            onPick={(v) => {
              activeTuneValues.style = v.style
              activeTuneValues.format = v.format
              activeTuneValues.hosts = v.hosts
              activeTuneValues.explicit = v.explicit
              activeTuneValues.template = v.style
              if (v.voices) {
                activeTuneVoice = {
                  ...activeTuneVoice,
                  ...(v.voices.a ? { 'a.timbre': v.voices.a } : {}),
                  ...(v.voices.b ? { 'b.timbre': v.voices.b } : {}),
                  ...(v.voices.c ? { 'c.timbre': v.voices.c } : {}),
                  ...(v.voices.solo ? { 'solo.timbre': v.voices.solo } : {}),
                  ...(v.voices.a_emotion ? { 'a.emotion': v.voices.a_emotion } : {}),
                  ...(v.voices.b_emotion ? { 'b.emotion': v.voices.b_emotion } : {}),
                  ...(v.voices.c_emotion ? { 'c.emotion': v.voices.c_emotion } : {}),
                  ...(v.voices.solo_emotion ? { 'solo.emotion': v.voices.solo_emotion } : {})
                }
              }
            }}
          />
        </section>

        <!-- 3. Essentials Section (Style, Voices, Format, Language, Rating) -->
        <EssentialsSection
          {meta}
          values={activeTuneValues}
          voiceProfile={activeTuneVoice}
          onStyleChange={(style) => (activeTuneValues.style = style)}
          onFormatChange={(format) => (activeTuneValues.format = format)}
          onLanguageChange={(language) => (activeTuneValues.language = language)}
          onHostsChange={(hosts) => (activeTuneValues.hosts = hosts)}
          onExplicitChange={(explicit) => (activeTuneValues.explicit = explicit)}
          onVoiceTimbreChange={(key, timbre) => (activeTuneVoice[key as keyof VoiceProfile] = timbre)}
          onVoiceEmotionChange={(key, emotion) => (activeTuneVoice[key as keyof VoiceProfile] = emotion)}
          onVoiceNameChange={(key, name) => (activeTuneVoice[key as keyof VoiceProfile] = name)}
          onProbePlay={() => {}}
          probeKey=""
          showStyle={true}
          showVoices={true}
          showFormat={true}
          showLanguage={true}
          showRating={true}
        />

        <!-- 4. Render Mode Section: Instant (1:1) vs Digest Bundle -->
        <section class="ess td-section" aria-labelledby="td-mode-h">
          <h3 id="td-mode-h" class="mono ess-h"><Icon name="brain" size={16} /> render mode</h3>
          <div class="seg" role="radiogroup" aria-label="Render mode">
            <button
              type="button"
              role="radio"
              aria-checked={!activeTuneValues.digest_mode}
              class:sel={!activeTuneValues.digest_mode}
              onclick={() => (activeTuneValues.digest_mode = false)}
            >per story</button>
            <button
              type="button"
              role="radio"
              aria-checked={activeTuneValues.digest_mode}
              class:sel={activeTuneValues.digest_mode}
              onclick={() => (activeTuneValues.digest_mode = true)}
            >digest bundle</button>
          </div>
          {#if activeTuneValues.digest_mode}
            <div class="mode-bundle-box">
              <span class="mono mode-count-title">stories per digest:</span>
              <div class="seg" role="radiogroup" aria-label="Stories per digest">
                {#each [2, 3, 4, 5] as n (n)}
                  <button
                    type="button"
                    role="radio"
                    aria-checked={activeTuneValues.digest_count === n}
                    class:sel={activeTuneValues.digest_count === n}
                    onclick={() => (activeTuneValues.digest_count = n)}
                  >{n} stories</button>
                {/each}
              </div>
            </div>
            <p class="mono td-help">bundles up to {activeTuneValues.digest_count} new articles into a single multi-story overview episode.</p>
          {:else}
            <p class="mono td-help">renders each new article individually as its own separate podcast episode.</p>
          {/if}
        </section>

        <!-- 5. Show reach: episodes inherit the show's reach -->
        <section class="ess td-section" aria-labelledby="td-show-h">
          <h3 id="td-show-h" class="mono ess-h"><Icon name="rss" size={16} /> show</h3>
          <label class="mono field">
            <span>show</span>
            <select
              bind:value={activeTuneValues.show_slug}
              aria-label="Show"
            >
              <option value="">none</option>
              {#each shows as s (s.slug)}
                <option value={s.slug === 'default' ? 'default' : s.slug.replace(/^s/, '')}>{s.name}</option>
              {/each}
            </select>
          </label>
          <p class="mono td-help">episodes inherit the show's reach (rss, nostr) from settings · shows</p>
        </section>

        <!-- 5. Save Feed Settings Action Bar -->
        <div class="tune-dialog-footer">
          <button
            type="button"
            class="td-save-btn mono"
            disabled={savingSettings === activeTuneFeed.id}
            onclick={() => void saveActiveTune()}
          >
            {savingSettings === activeTuneFeed.id ? 'saving…' : 'save feed settings'}
          </button>
          {#if activeSaveMsg}
            <span class="mono td-save-msg" role="status" aria-live="polite">{activeSaveMsg}</span>
          {/if}
          <button type="button" class="link mono" onclick={closeTuneModal}>done</button>
        </div>

        <!-- 5. Link to Advanced Settings -->
        <div class="settings-cta-row">
          <button type="button" class="settings-cta mono" onclick={() => { closeTuneModal(); onSettings(); }} aria-expanded="false">
            <Icon name="sliders" size={18} /> advanced settings
          </button>
          <span class="mono cta-hint">sources · script · voice · shows · player · system</span>
        </div>
      </div>
    </div>
  </div>
{/if}

<style>
  /* this main nests inside App.svelte's main, which already applies
     max-width and padding - adding our own made the whole page narrower
     than compose (double constraint). stay unconstrained here. */
  main {
    max-width: none;
    margin: 0;
    padding: 0;
  }
  /* same card chrome as compose essentials: icon header, explainer, content */
  .ess {
    border: 1px solid var(--line);
    border-radius: var(--radius);
    padding: var(--space-5);
    display: grid;
    gap: var(--space-4);
    min-width: 0;
    max-width: 100%;
    overflow: hidden;
    box-sizing: border-box;
    margin-bottom: var(--space-5);
    background: color-mix(in srgb, var(--paper) 4%, transparent);
  }
  .ess-h {
    display: flex;
    align-items: center;
    gap: var(--space-2);
    font-size: var(--ui-size);
    color: var(--ink);
    text-transform: lowercase;
    letter-spacing: 0.04em;
    margin: 0;
  }
  .sec-help {
    color: var(--ink-soft);
    font-size: calc(var(--ui-size) * 0.85);
    margin: 0;
  }
  .added {
    color: var(--green);
  }
  .add-row {
    display: flex;
    gap: var(--space-3);
    align-items: flex-end;
  }
  .add-row .field {
    flex: 1;
  }
  .field {
    display: grid;
    gap: var(--space-1);
    font-size: var(--ui-size);
    color: var(--ink-soft);
  }
  .field input {
    background: transparent;
    border: none;
    border-bottom: 1px solid var(--line);
    color: var(--ink);
    font-family: var(--font-mono);
    font-size: var(--ui-size);
    padding: var(--space-2) 0;
  }
  .field input:focus-visible {
    outline: 2px solid var(--green);
    outline-offset: 2px;
    border-bottom-color: var(--green);
  }
  .submit {
    justify-self: start;
    padding: var(--space-2) var(--space-4);
    background: var(--green);
    color: var(--paper);
    border: 1px solid var(--green);
    border-radius: var(--radius);
    font-size: var(--ui-size);
    cursor: pointer;
    transition: background var(--dur-fast) ease-out, border-color var(--dur-fast) ease-out;
  }
  .submit:hover { background: color-mix(in srgb, var(--green) 85%, var(--ink)); border-color: var(--green); color: var(--paper); }
  .submit:disabled { opacity: 0.6; }
  .err { color: var(--voice-b); margin-top: var(--space-2); }

  /* same sales-pitch row as compose: centered, prominent look */
  .settings-cta-row {
    display: flex;
    flex-direction: column;
    align-items: center;
    gap: var(--space-2);
    text-align: center;
    border-top: 1px solid var(--line);
    padding-top: var(--space-4);
    margin-top: var(--space-4);
  }

  .settings-cta {
    display: inline-flex;
    align-items: center;
    gap: var(--space-2);
    background: transparent;
    border: 1px solid var(--line);
    border-radius: var(--radius);
    color: var(--ink);
    font-size: var(--ui-size);
    padding: var(--space-2) var(--space-4);
    cursor: pointer;
  }
  .settings-cta:hover { border-color: var(--green); }

  .cta-hint {
    color: var(--ink);
    font-size: var(--ui-size);
  }
  .sec-head-row {
    display: flex;
    justify-content: space-between;
    align-items: baseline;
    gap: var(--space-2);
    flex-wrap: wrap;
  }
  .sec-head-link {
    font-size: calc(var(--ui-size) * 0.85);
    text-decoration: underline;
  }
  .more-row {
    display: flex;
    justify-content: center;
    padding-top: var(--space-2);
  }
  .note { color: var(--ink-soft); }
  .feed-out {
    display: flex;
    align-items: center;
    gap: var(--space-3);
    border: 1px solid var(--line);
    border-radius: var(--radius);
    padding: var(--space-2) var(--space-3);
    margin-bottom: var(--space-3);
    min-width: 0;
    max-width: 100%;
    overflow: hidden;
  }
  .fo-lab {
    flex: none;
    display: inline-flex;
    align-items: center;
    gap: var(--space-1);
    color: var(--ink-soft);
  }
  .fo-url {
    flex: 1 1 0;
    min-width: 0;
    max-width: 100%;
    overflow: hidden;
    text-overflow: ellipsis;
    white-space: nowrap;
    overflow-wrap: anywhere;
    word-break: break-all;
    color: var(--ink);
  }
  .shelf {
    list-style: none;
    margin: 0;
    padding: 0;
    display: grid;
    gap: var(--space-3);
  }
  .card {
    border: 1px solid var(--line);
    border-radius: var(--radius);
    padding: var(--space-3);
    display: grid;
    gap: var(--space-1);
    min-width: 0;
    max-width: 100%;
    overflow: hidden;
  }
  .card-head {
    display: flex;
    justify-content: space-between;
    align-items: flex-start;
    gap: var(--space-2);
    min-width: 0;
    max-width: 100%;
    overflow: hidden;
  }
  .card-title-group {
    display: grid;
    gap: 2px;
    min-width: 0;
    flex: 1 1 auto;
  }
  .card-domain {
    font-size: 1.05rem;
    font-weight: 600;
    color: var(--ink);
    text-decoration: none;
    overflow: hidden;
    text-overflow: ellipsis;
    white-space: nowrap;
  }
  .card-path {
    font-size: calc(var(--ui-size) * 0.8);
    color: var(--ink-soft);
    overflow: hidden;
    text-overflow: ellipsis;
    white-space: nowrap;
  }
  .card-status-group {
    display: flex;
    align-items: center;
    gap: var(--space-2);
    flex-shrink: 0;
  }
  .freshness-pill {
    display: inline-flex;
    align-items: center;
    gap: 6px;
    font-size: calc(var(--ui-size) * 0.8);
    color: var(--ink-soft);
    background: transparent;
    border: 1px solid var(--line);
    padding: 2px 8px;
    border-radius: var(--radius);
  }
  .freshness-pill.fresh {
    border-color: var(--green);
    color: var(--ink);
  }
  .freshness-pill.error {
    border-color: var(--danger);
    color: var(--danger);
  }
  .badge {
    flex: none;
    background: var(--line);
    color: var(--ink-soft);
    padding: 2px 7px;
    border-radius: var(--radius);
    font-size: calc(var(--ui-size) * 0.75);
    letter-spacing: 0.06em;
  }
  .card-meta-line {
    display: flex;
    justify-content: space-between;
    align-items: center;
    gap: var(--space-2);
    flex-wrap: wrap;
    margin-top: 2px;
  }
  .card-tags {
    display: flex;
    gap: var(--space-1);
    flex-wrap: wrap;
  }
  .tag-pill {
    font-size: calc(var(--ui-size) * 0.78);
    color: var(--ink-soft);
    background: var(--line);
    padding: 1px 6px;
    border-radius: var(--radius);
  }
  .time-readout {
    font-size: calc(var(--ui-size) * 0.78);
    color: var(--ink-soft);
  }

  .freshness-dot {
    width: 7px;
    height: 7px;
    border-radius: 50%;
    flex: none;
    background: var(--line);
  }
  .freshness-pill.fresh .freshness-dot { background: var(--green); }
  .freshness-pill.soon .freshness-dot { background: var(--line); }
  .freshness-pill.error .freshness-dot { background: var(--danger); }

  .mode-bundle-box {
    display: flex;
    align-items: center;
    gap: var(--space-2);
    flex-wrap: wrap;
    margin-top: var(--space-1);
  }
  .mode-count-title {
    color: var(--ink-soft);
    font-size: calc(var(--ui-size) * 0.85);
  }

  .action-btn {
    display: inline-flex;
    align-items: center;
    gap: 6px;
    padding: 3px 8px;
    background: transparent;
    color: var(--ink);
    border: 1px solid var(--line);
    border-radius: var(--radius);
    font-family: var(--font-mono);
    font-size: calc(var(--ui-size) * 0.85);
    cursor: pointer;
    white-space: nowrap;
    transition: border-color var(--dur-fast) ease-out, color var(--dur-fast) ease-out, background var(--dur-fast) ease-out;
  }
  .action-btn:hover:not(:disabled) {
    border-color: var(--green);
    color: var(--ink);
    background: color-mix(in srgb, var(--green) 8%, var(--paper));
  }
  .action-btn.danger:hover:not(:disabled) {
    border-color: var(--danger);
    color: var(--danger);
    background: color-mix(in srgb, var(--danger) 4%, transparent);
  }
  .action-btn:disabled {
    opacity: 0.5;
    cursor: not-allowed;
  }
  .dh-latest-bar {
    display: flex;
    align-items: center;
    gap: var(--space-2);
    font-size: calc(var(--ui-size) * 0.85);
    padding-top: var(--space-2);
    border-top: 1px dashed var(--line);
    flex-wrap: wrap;
  }
  .dh-latest-label {
    color: var(--ink-soft);
  }
  .dh-latest-play {
    display: inline-flex;
    align-items: center;
    gap: 6px;
    color: var(--ink);
    text-decoration: none;
  }
  .dh-latest-play:hover {
    color: var(--green);
  }
  .dh-latest-title {
    font-weight: 500;
  }
  .dh-dur-badge {
    background: var(--line);
    color: var(--ink-soft);
    padding: 1px 5px;
    border-radius: var(--radius);
    font-size: calc(var(--ui-size) * 0.75);
  }
  .dh-latest-time {
    color: var(--ink-soft);
    margin-left: auto;
  }

  .seg {
    display: flex;
    gap: var(--space-1);
    flex-wrap: wrap;
  }

  .seg button {
    background: transparent;
    border: 1px solid var(--line);
    border-radius: var(--radius);
    color: var(--ink-soft);
    font-family: var(--font-mono);
    font-size: var(--ui-size);
    padding: var(--space-1) var(--space-2);
    cursor: pointer;
    transition: background var(--dur-fast) ease-out, color var(--dur-fast) ease-out, border-color var(--dur-fast) ease-out;
  }

  .seg button:hover:not(.sel):not([aria-checked="true"]) {
    color: var(--ink);
    border-color: var(--ink);
    background: color-mix(in srgb, var(--ink) 6%, transparent);
  }

  .seg button.sel,
  .seg button[aria-checked="true"] {
    background: var(--green);
    color: var(--paper);
    border-color: var(--green);
    font-weight: 600;
  }

  .seg button.sel:hover,
  .seg button[aria-checked="true"]:hover {
    background: color-mix(in srgb, var(--green) 90%, var(--ink));
    border-color: var(--green);
    color: var(--paper);
  }

  .card-actions {
    display: flex;
    align-items: center;
    gap: var(--space-2);
    flex-wrap: wrap;
    padding-top: var(--space-2);
  }

  .dmsg {
    color: var(--ink-soft);
    margin: 0;
  }

  .entry {
    width: 100%;
    text-align: left;
    background: transparent;
    border: 1px solid var(--line);
    border-radius: var(--radius);
    padding: var(--space-3);
    cursor: pointer;
    display: grid;
    gap: var(--space-1);
  }
  .entry:hover { border-color: var(--green); }
  .etitle {
    font-family: var(--font-serif);
    font-size: 1.05rem;
    line-height: 1.35;
  }
  .edesc {
    color: var(--ink-soft);
    font-size: 0.95rem;
    line-height: 1.45;
    max-width: 58ch;
  }
  .emeta { color: var(--ink-soft); }
  .link {
    background: transparent;
    border: none;
    padding: var(--space-1) var(--space-1);
    cursor: pointer;
    min-height: 28px;
    color: var(--ink-soft);
    font-family: var(--font-mono);
    font-size: var(--ui-size);
    text-decoration: underline;
    text-decoration-color: var(--line);
  }
  .link:hover { color: var(--green); }
  .link:disabled { opacity: 0.5; }

  /* Shared Tune Modal / Overlay */
  .tune-overlay {
    position: fixed;
    inset: 0;
    background: rgba(0, 0, 0, 0.72);
    backdrop-filter: blur(2px);
    z-index: 100;
    display: flex;
    justify-content: center;
    align-items: flex-start;
    overflow-y: auto;
    padding: var(--space-4) var(--space-2);
  }
  .tune-dialog {
    background: var(--paper);
    border: 1px solid var(--line);
    border-radius: var(--radius);
    width: 100%;
    max-width: 720px;
    padding: var(--space-5);
    display: grid;
    gap: var(--space-4);
    margin: auto;
    max-height: calc(100vh - 2 * var(--space-4));
    overflow-y: auto;
    box-sizing: border-box;
  }
  .tune-dialog-head {
    display: flex;
    justify-content: space-between;
    align-items: flex-start;
    gap: var(--space-2);
    border-bottom: 1px solid var(--line);
    padding-bottom: var(--space-3);
  }
  .td-title-group {
    display: grid;
    gap: 4px;
    min-width: 0;
  }
  .td-title {
    font-size: 1.15rem;
    color: var(--ink);
    display: inline-flex;
    align-items: center;
    gap: var(--space-2);
    margin: 0;
  }
  .td-url {
    font-size: calc(var(--ui-size) * 0.82);
    color: var(--ink-soft);
    overflow: hidden;
    text-overflow: ellipsis;
    white-space: nowrap;
  }
  .td-close {
    flex-shrink: 0;
  }
  .tune-dialog-actions {
    display: flex;
    gap: var(--space-3);
    flex-wrap: wrap;
    padding-bottom: var(--space-3);
    border-bottom: 1px dashed var(--line);
  }
  .td-section {
    border: 1px solid var(--line);
    border-radius: var(--radius);
    padding: var(--space-4);
    margin-bottom: 0;
    background: color-mix(in srgb, var(--paper) 4%, transparent);
  }
  .td-help {
    color: var(--ink-soft);
    font-size: calc(var(--ui-size) * 0.85);
    margin: 0;
  }
  .tune-dialog-footer {
    display: flex;
    align-items: center;
    gap: var(--space-3);
    padding-top: var(--space-3);
    border-top: 1px solid var(--line);
    flex-wrap: wrap;
  }
  .td-save-btn {
    background: var(--green);
    color: var(--paper);
    border: 1px solid var(--green);
    border-radius: var(--radius);
    padding: 8px 16px;
    font-family: var(--font-mono);
    font-size: var(--ui-size);
    font-weight: 600;
    cursor: pointer;
    transition: background var(--dur-fast) ease-out, opacity var(--dur-fast) ease-out;
  }
  .td-save-btn:hover:not(:disabled) {
    background: color-mix(in srgb, var(--green) 85%, var(--ink));
    border-color: var(--green);
    color: var(--paper);
  }
  .td-save-btn:disabled {
    opacity: 0.5;
    cursor: not-allowed;
  }
  .td-save-msg {
    color: var(--green);
    font-size: calc(var(--ui-size) * 0.9);
  }
</style>

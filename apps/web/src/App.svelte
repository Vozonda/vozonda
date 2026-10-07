<script lang="ts">
  import Icon from './lib/components/Icon.svelte'
  import SourceTray from './lib/components/SourceTray.svelte'
  import EssentialsSection from './lib/components/EssentialsSection.svelte'
  import ShowPicker from './lib/components/ShowPicker.svelte'
  import { SHOWS, showVoicePatch, type Show } from './lib/shows'
  import { getActiveIdentity, setActiveIdentity, identityDisplayName, shortNpub as nostrShort, type NostrIdentity } from './lib/nostr'
  import { fetchProfileFromRelays } from './lib/profile'
  import { buildStyleGroups, buildStyleDocs } from './lib/styles'
  import { untrack } from 'svelte'

  // Lazy component loaders (VOZONDA-LAUNCH-3: bundle budget < 60 KB gzip)
  const loadSettingsScreen = () => import('./lib/components/SettingsScreen.svelte').then((m) => m.default)
  let settingsPromise: ReturnType<typeof loadSettingsScreen> | null = null
  const getSettingsScreen = () => (settingsPromise ??= loadSettingsScreen())

  const loadWatchlistScreen = () => import('./lib/components/WatchlistScreen.svelte').then((m) => m.default)
  let watchlistPromise: ReturnType<typeof loadWatchlistScreen> | null = null
  const getWatchlistScreen = () => (watchlistPromise ??= loadWatchlistScreen())

  const loadLibraryScreen = () => import('./lib/components/LibraryScreen.svelte').then((m) => m.default)
  let libraryPromise: ReturnType<typeof loadLibraryScreen> | null = null
  const getLibraryScreen = () => (libraryPromise ??= loadLibraryScreen())

  const loadFaqScreen = () => import('./lib/components/FaqScreen.svelte').then((m) => m.default)
  let faqPromise: ReturnType<typeof loadFaqScreen> | null = null
  const getFaqScreen = () => (faqPromise ??= loadFaqScreen())

  const loadAboutScreen = () => import('./lib/components/AboutScreen.svelte').then((m) => m.default)
  let aboutPromise: ReturnType<typeof loadAboutScreen> | null = null
  const getAboutScreen = () => (aboutPromise ??= loadAboutScreen())

  const loadAgentsScreen = () => import('./lib/components/AgentsScreen.svelte').then((m) => m.default)
  let agentsPromise: ReturnType<typeof loadAgentsScreen> | null = null
  const getAgentsScreen = () => (agentsPromise ??= loadAgentsScreen())

  const loadProfileScreen = () => import('./lib/components/NostrProfileScreen.svelte').then((m) => m.default)
  let profilePromise: ReturnType<typeof loadProfileScreen> | null = null
  const getProfileScreen = () => (profilePromise ??= loadProfileScreen())

  const loadListenScreen = () => import('./lib/components/ListenScreen.svelte').then((m) => m.default)
  let listenPromise: ReturnType<typeof loadListenScreen> | null = null
  const getListenScreen = () => (listenPromise ??= loadListenScreen())

  const loadNostrLogin = () => import('./lib/components/NostrLogin.svelte').then((m) => m.default)
  let nostrLoginPromise: ReturnType<typeof loadNostrLogin> | null = null
  const getNostrLogin = () => (nostrLoginPromise ??= loadNostrLogin())

  const loadScriptReview = () => import('./lib/components/ScriptReview.svelte').then((m) => m.default)
  let scriptReviewPromise: ReturnType<typeof loadScriptReview> | null = null
  const getScriptReview = () => (scriptReviewPromise ??= loadScriptReview())

  const loadQueueIndicator = () => import('./lib/components/QueueIndicator.svelte').then((m) => m.default)
  const loadPipelineChecklist = () => import('./lib/components/PipelineChecklist.svelte').then((m) => m.default)
  let queuePromise: ReturnType<typeof loadQueueIndicator> | null = null
  let pipelinePromise: ReturnType<typeof loadPipelineChecklist> | null = null
  const getQueueComponent = () => (queuePromise ??= loadQueueIndicator())
  const getPipelineComponent = () => (pipelinePromise ??= loadPipelineChecklist())
  import {
    createJob,
    createJobFromText,
    createJobWithSources,
    createDigestJob,
    cancelJob,
    fetchProviders,
    fetchMeta,
    getSettings,
    jobEvents,
    getJob,
    listJobs,
    readLocalRecent,
    pushLocalRecent,
    listWatchlists,
    addWatchlist,
    removeWatchlist,
    checkWatchlist,
    setWatchlistEnabled,
    setWatchlistDigest,
    renderWatchlistDigest,
    updateWatchlist,
    saveSetting,
    createJobWithTray,
    cloneJobSources,
    type SourceItem,
    type SourceRole,
    type Job,
    type JobSummary,
    type Meta,
    type ProviderStatus,
    type VoiceProfile,
    LANG_NAMES,
    type WatchlistEntry,
    type ClipListItem,
    approveScript
  } from './lib/api'

  type Screen = 'compose' | 'progress' | 'listen' | 'faq' | 'library' | 'watchlist' | 'about' | 'settings' | 'profile' | 'agents'

  let screen = $state<Screen>('compose')
  let url = $state('')
  let text = $state('')
  let sourceKind = $state<'url' | 'text'>('url')
  let traySources = $state<SourceItem[]>([])
  let allowCloudForUploads = $state(false)
  let error = $state('')
  let busy = $state(false)
  let providers = $state<ProviderStatus>({ providers: [], active: [] })
  let job = $state<Job | null>(null)
  let recent = $state<JobSummary[]>([])
  let stopEvents: (() => void) | null = null
  let streamError = $state<string | null>(null)
  let meta = $state<Meta | null>(null)
  let style = $state('balanced')
  let library = $state<JobSummary[]>([])
  let watchlists = $state<WatchlistEntry[]>([])
  let nostrOpen = $state(false)
  let nostrIdentity = $state<NostrIdentity | null>(null)
  let profileQuery = $state('')

  // Clip route (#184 / DUE-020)
  let clipTurnStart = $state<number | null>(null)
  let clipTurnEnd = $state<number | null>(null)

  async function leaveHash() {
    stopEvents?.()
    if (location.hash) history.pushState(null, '', location.pathname)
    screen = 'compose'
    window.scrollTo(0, 0)
    clipTurnStart = null
    clipTurnEnd = null
    void loadRecent()
    try {
      meta = await fetchMeta()
      providers = await fetchProviders()
      const validTimbres = (meta?.timbres ?? []).map((t) => t.id)
      if (validTimbres.length > 0) {
        if (!validTimbres.includes(jobVoice['a.timbre'] ?? '')) {
          jobVoice['a.timbre'] = validTimbres[0]
        }
        if (!validTimbres.includes(jobVoice['b.timbre'] ?? '')) {
          jobVoice['b.timbre'] = validTimbres[1] ?? validTimbres[0]
        }
        if (!validTimbres.includes(jobVoice['solo.timbre'] ?? '')) {
          jobVoice['solo.timbre'] = validTimbres[0]
        }
      }
    } catch {}
  }

  function goFaq() {
    void getFaqScreen()
    history.pushState(null, '', '#faq')
    screen = 'faq'
    window.scrollTo(0, 0)
  }

  function goAbout() {
    void getAboutScreen()
    history.pushState(null, '', '#about')
    screen = 'about'
    window.scrollTo(0, 0)
  }

  function goAgents() {
    void getAgentsScreen()
    history.pushState(null, '', '#agents')
    screen = 'agents'
    window.scrollTo(0, 0)
  }


  function goProfile(query?: string) {
    void getProfileScreen()
    const q = query ?? nostrIdentity?.npub ?? nostrIdentity?.pubkey ?? ''
    if (q) {
      profileQuery = q
      history.pushState(null, '', `#profile=${encodeURIComponent(q)}`)
    } else {
      profileQuery = ''
      history.pushState(null, '', '#profile')
    }
    screen = 'profile'
    window.scrollTo(0, 0)
  }

  function openProfileFromHash(hash: string) {
    void getProfileScreen()
    const raw = hash.startsWith('#') ? hash.slice(1) : hash
    // #profile, #profile=..., #profile/<...>, #p=..., #p/<...>
    let q = ''
    if (raw.startsWith('profile=')) q = decodeURIComponent(raw.slice('profile='.length))
    else if (raw.startsWith('profile/')) q = decodeURIComponent(raw.slice('profile/'.length))
    else if (raw === 'profile') q = ''
    else if (raw.startsWith('p=')) q = decodeURIComponent(raw.slice(2))
    else if (raw.startsWith('p/')) q = decodeURIComponent(raw.slice(2))
    profileQuery = q
    screen = 'profile'
    window.scrollTo(0, 0)
  }

  async function openLibrary() {
    void getLibraryScreen()
    if (location.hash !== '#library') history.pushState(null, '', '#library')
    screen = 'library'
    window.scrollTo(0, 0)
    try {
      library = await listJobs(200)
    } catch {
      library = []
    }
  }

  async function openWatchlist() {
    void getWatchlistScreen()
    if (location.hash !== '#watchlist') history.pushState(null, '', '#watchlist')
    screen = 'watchlist'
    window.scrollTo(0, 0)
    try {
      const [w, jobs] = await Promise.all([listWatchlists(), listJobs(200)])
      watchlists = w
      library = jobs
    } catch {
      watchlists = []
    }
  }

  async function handleAddWatchlist(entry: { feed_url: string; style: string; format: 'dialog' | 'narration'; language: string; hosts: number }) {
    const w = await addWatchlist(entry)
    watchlists = [...watchlists, w]
  }

  async function handleRemoveWatchlist(id: string) {
    await removeWatchlist(id)
    watchlists = watchlists.filter((w) => w.id !== id)
  }

  async function handleToggleWatchlist(id: string, enabled: boolean) {
    const w = await setWatchlistEnabled(id, enabled)
    watchlists = watchlists.map((x) => (x.id === w.id ? w : x))
  }

  async function handleDigestToggle(id: string, digestMode: boolean, digestCount: number) {
    const w = await setWatchlistDigest(id, digestMode, digestCount)
    watchlists = watchlists.map((x) => (x.id === w.id ? w : x))
  }

  async function handleDigestNow(id: string): Promise<{ digest_job: string; sources: string[] }> {
    const r = await renderWatchlistDigest(id)
    try {
      library = await listJobs(200)
    } catch {
      void library
    }
    return r
  }

  async function handleSaveWatchlistVoice(id: string, voice: VoiceProfile) {
    const current = watchlists.find((w) => w.id === id)
    const w = await setWatchlistEnabled(id, current?.enabled ?? true, cleanVoice(voice))
    watchlists = watchlists.map((x) => (x.id === w.id ? w : x))
  }

  async function handleUpdateWatchlistSettings(
    id: string,
    patch: Partial<{ style: string; format: 'dialog' | 'narration'; language: string; hosts: number; explicit: boolean; show_slug: string }>
  ) {
    const w = await updateWatchlist(id, patch)
    watchlists = watchlists.map((x) => (x.id === w.id ? w : x))
  }

  async function handleCheckWatchlist(id: string) {
    const res = await checkWatchlist(id)
    // refresh library to show new auto episodes
    try {
      library = await listJobs(200)
      watchlists = await listWatchlists()
    } catch {
      void res
    }
  }

  // Style groups, icons and docs come from GET /meta style_meta
  // (lib/styles.ts), with an offline fallback when /meta is unreachable.
  const groupedStyles = $derived.by(() => {
    if (!meta) return buildStyleGroups(null)
    return buildStyleGroups(meta)
  })
  const styleDocs = $derived(buildStyleDocs(meta))
  let format = $state<'dialog' | 'narration'>('dialog')
  let language = $state('auto')
  let v4v = $state<{
    address: string
    split: number
    appAddress: string
    creatorAddress: string
    creatorSplit: number
    sourceAddress: string
    sourceSplit: number
    appSplit: number
  } | null>(null)
  let explicit = $state(false)
  let panelVals = $state<{ style: string; format: 'dialog' | 'narration'; language: string; hosts: number; explicit: boolean; showId: string; showName: string }>({ style: 'balanced', format: 'dialog', language: 'auto', hosts: 2, explicit: false, showId: '', showName: '' })
  let goFlash = $state(false)
  let goFlashTimer: ReturnType<typeof setTimeout> | undefined
  let voiceTouched = $state(false)
  let settingsVoiceKeys = $state<ReadonlySet<string>>(new Set())
  let jobVoice = $state<VoiceProfile>({})
  let urlInput = $state<HTMLTextAreaElement | null>(null)
  
  // Defaults for the customize panel (this episode only)
  let defaultStyle = $state('balanced')
  let defaultFormat = $state<'dialog' | 'narration'>('dialog')
  let defaultHosts = $state(2)
  let defaultReviewScript = $state(false)
  const changedStyle = $derived(panelVals.style !== defaultStyle)
  const changedFormat = $derived(panelVals.format !== defaultFormat)
  const changedHosts = $derived(panelVals.hosts !== defaultHosts)

  // VOZONDA-UX-1: compose as 3 steps (source, format, fine-tune).
  // Step 1 collects up to 10 sources (url field + chips); 2+ go as digest.
  let extraSources = $state<string[]>([])
  let newSource = $state('')
  let textNotes = $state<string[]>([])
  let newTextNote = $state('')
  // UX masterplan 2026-09-23: one "show" choice, then a flat "customize"
  // for this episode only (settings = defaults for every episode).
  let selectedShowId = $state('deep_dive')
  let customizeOpen = $state(false)
  let customizeEl = $state<HTMLElement | null>(null)
  try {
    customizeOpen = localStorage.getItem('vozonda.customizeOpen') === '1'
  } catch {
    customizeOpen = false
  }

  // VOZONDA-LEN-1 presets (minutes mirror apps/api length.py LENGTH_PRESETS)
  const LENGTH_PRESETS: { id: 'short' | 'default' | 'long'; label: string; minutes: number }[] = [
    { id: 'short', label: 'short', minutes: 3 },
    { id: 'default', label: 'default', minutes: 8 },
    { id: 'long', label: 'long', minutes: 15 }
  ]
  let lengthPreset = $state<'short' | 'default' | 'long'>('default')
  let focus = $state('')
  // UX phase 2: pause after the script to review it (single source only)
  let reviewScript = $state(false)
  const changedReviewScript = $derived(reviewScript !== defaultReviewScript)
  let reviewTouched = $state(false)
  let reviewBusy = $state(false)
  let lengthMinutes = $state<number | null>(null)
  const episodeMinutes = $derived(lengthMinutes ?? LENGTH_PRESETS.find((p) => p.id === lengthPreset)?.minutes ?? 8)

  function setLengthMinutes(raw: string) {
    const n = Math.round(Number(raw))
    lengthMinutes = raw.trim() === '' || !Number.isFinite(n) ? null : Math.min(60, Math.max(1, n))
  }

  function lengthOpts(): { target_minutes?: number; length?: 'short' | 'default' | 'long' } {
    return lengthMinutes ? { target_minutes: lengthMinutes } : { length: lengthPreset }
  }

  function addSource() {
    const raw = newSource.trim()
    if (!raw) return
    const norm = /^https?:\/\//i.test(raw) ? raw : `https://${raw}`
    if (url.trim() === norm || extraSources.includes(norm)) {
      newSource = ''
      return
    }
    if (extraSources.length >= 9) return
    extraSources = [...extraSources, norm]
    newSource = ''
  }

  function removeSource(s: string) {
    extraSources = extraSources.filter((x) => x !== s)
  }

  function addTextNote() {
    const raw = newTextNote.trim()
    if (!raw) return
    if (textNotes.includes(raw)) {
      newTextNote = ''
      return
    }
    if (textNotes.length >= 9 - extraSources.length) return
    textNotes = [...textNotes, raw]
    newTextNote = ''
  }

  function removeTextNote(n: string) {
    textNotes = textNotes.filter((x) => x !== n)
  }

  function buildSources(): string[] {
    const list: string[] = []
    const primary = (sourceKind === 'url' ? url : text).trim()
    if (primary) {
      list.push(sourceKind === 'url' ? primary : `text:${primary}`)
    }
    for (const s of extraSources) {
      const trimmed = s.trim()
      if (trimmed) list.push(trimmed)
    }
    for (const n of textNotes) {
      const trimmed = n.trim()
      if (trimmed) list.push(`text:${trimmed}`)
    }
    return list
  }

  function buildCombinedText(): string {
    const parts: string[] = []
    const primary = text.trim()
    if (primary) parts.push(primary)
    for (const n of textNotes) {
      if (n.trim()) parts.push(n.trim())
    }
    return parts.join('\n\n---\n\n')
  }

  function getSourceCount(): number {
    const primary = (sourceKind === 'url' ? url : text).trim() ? 1 : 0
    return primary + extraSources.length + textNotes.length
  }

  function shortenText(s: string): string {
    return s.length > 60 ? s.slice(0, 60) + '...' : s
  }

  function persistCustomize() {
    try {
      localStorage.setItem('vozonda.customizeOpen', customizeOpen ? '1' : '0')
    } catch {
      void 0
    }
  }

  function openCustomize() {
    customizeOpen = true
    persistCustomize()
    requestAnimationFrame(() => {
      customizeEl?.scrollIntoView({ behavior: 'smooth', block: 'start' })
      customizeEl?.focus({ preventScroll: true })
    })
  }

  function closeCustomize() {
    customizeOpen = false
    persistCustomize()
  }

  // A show sets this episode only: style, hosts, format and, for the active
  // engine, voices plus pacing. It never switches the engine or writes settings
  // (the old template tiles silently did both, e.g. tts.engine=voxtral).
  function selectShow(show: Show) {
    selectedShowId = show.id
    panelVals.style = show.style
    panelVals.format = show.format
    panelVals.hosts = show.hosts
    panelVals.explicit = show.explicit
    const next: VoiceProfile = { ...jobVoice }
    for (const k of ['speed', 'gap_ms', 'a.emotion', 'b.emotion', 'c.emotion', 'solo.emotion']) delete next[k]
    const patch = showVoicePatch(show, meta?.runtime?.tts_engine ?? 'qwen_tts')
    if (Object.keys(patch).some((k) => k.endsWith('.timbre'))) voiceTouched = true
    jobVoice = { ...next, ...patch }
    goFlash = false
    clearTimeout(goFlashTimer)
    requestAnimationFrame(() => (goFlash = true))
    goFlashTimer = setTimeout(() => (goFlash = false), 600)
  }

  function resetToDefault(field: 'style' | 'format' | 'hosts' | 'reviewScript') {
    switch (field) {
      case 'style':
        panelVals.style = defaultStyle
        break
      case 'format':
        panelVals.format = defaultFormat
        break
      case 'hosts':
        panelVals.hosts = defaultHosts
        break
      case 'reviewScript':
        reviewScript = defaultReviewScript
        break
    }
  }

  // Names in the summary sentence: the chosen host name, else the voice label
  const hostNames = $derived.by(() => {
    const engine = meta?.runtime?.tts_engine ?? 'qwen_tts'
    const table: { id: string; label: string }[] = meta?.speaker_tables?.[engine] ?? meta?.timbres ?? []
    const label = (id: unknown) => {
      if (typeof id !== 'string' || !id) return ''
      const t = table.find((x) => x.id === id)
      return ((t?.label ?? id).split(/[·(,]/)[0] ?? id).trim()
    }
    const keys = panelVals.format === 'narration' ? ['solo'] : ['a', 'b', 'c'].slice(0, Math.max(1, panelVals.hosts))
    return keys.map((k) => String(jobVoice[`${k}.name`] ?? '') || label(jobVoice[`${k}.timbre`]) || k.toUpperCase())
  })

  // DUE-041-Rest: per-language default timbres (meta.default_timbre_for,
  // rating-5 cast from docs/archive/internal/voice-accent-probe.md). Applies on load and on
  // every language change until the user explicitly picks a voice - their
  // choice then always wins. Explicit global settings also win.
  $effect(() => {
    const df = meta?.default_timbre_for
    if (!df || voiceTouched) return
    const entry = df[panelVals.language] ?? df['auto']
    if (!entry) return
    for (const key of ['a.timbre', 'b.timbre', 'c.timbre', 'solo.timbre'] as const) {
      if (!settingsVoiceKeys.has(`voice.${key}`)) jobVoice[key] = entry[key.split('.')[0] as 'a' | 'b' | 'c' | 'solo']
    }
  })

  // (style groups, icons and docs: see lib/styles.ts, built from /meta)

  function detectGibberish(str: string): string | null {
    const trimmed = str.trim()
    if (trimmed.length < 50) return null
    const words = trimmed.split(/\s+/)
    if (words.some((w) => w.length > 45)) {
      return 'unbroken letter sequence (gibberish detected)'
    }
    const letters = trimmed.replace(/[^a-zA-Z\u00c0-\u024f]/g, '')
    if (letters.length > 50) {
      const vowels = letters.match(/[aeiouy\u00c0-\u024f]/gi)
      const ratio = (vowels ? vowels.length : 0) / letters.length
      if (ratio < 0.12) {
        return 'unreadable letter salad (too few vowels)'
      }
    }
    if (/(.)\1{7,}/.test(trimmed)) {
      return 'repetitive character pattern detected'
    }
    if (/(.{2,6})\1{4,}/.test(trimmed)) {
      return 'repetitive text pattern detected'
    }
    if (words.length >= 10) {
      const unique = new Set(words.map((w) => w.toLowerCase()))
      if (unique.size <= 2) {
        return 'repeated identical words'
      }
    }
    return null
  }

  function detectUnreadableUrl(rawUrl: string): string | null {
    const trimmed = rawUrl.trim()
    if (!trimmed) return null
    const badExtensions = /\.(zip|tar|gz|exe|dmg|iso|bin|apk|mp3|wav|flac|m4a|aac|ogg)$/i
    const cleanPath = (trimmed.split('?')[0] ?? '').split('#')[0] ?? ''
    if (badExtensions.test(cleanPath)) {
      return 'targets a binary/audio archive instead of an article or document'
    }
    if (/^(https?:\/\/)?(localhost|127\.0\.0\.1|10\.|192\.168\.|172\.(1[6-9]|2[0-9]|3[0-1]))/i.test(trimmed)) {
      return 'local network addresses cannot be converted to podcasts'
    }
    return null
  }

  let textWarn = $derived(detectGibberish(text))
  let urlWarn = $derived(detectUnreadableUrl(url))

  let probeAudio: HTMLAudioElement | null = null
  let probeKey = $state('')

  function toggleProbe(src: string, key: string) {
    if (probeAudio && probeKey === key) {
      probeAudio.pause()
      probeKey = ''
    } else {
      if (probeAudio) {
        probeAudio.pause()
        probeAudio.currentTime = 0
      }
      probeAudio = new Audio(src)
      probeKey = key
      probeAudio.onplay = () => (probeKey = key)
      probeAudio.onpause = () => (probeKey = '')
      probeAudio.onended = () => (probeKey = '')
      probeAudio.play()
    }
  }

  function openSettings() {
    stopEvents?.()
    void getSettingsScreen()
    history.pushState(null, '', '#settings')
    screen = 'settings'
    window.scrollTo(0, 0)
  }

  const timbreKey = (v: string) => `${v}.timbre` as 'a.timbre' | 'b.timbre' | 'c.timbre'
  const nameKey = (v: string) => `${v}.name` as 'a.name' | 'b.name' | 'c.name'
  const emotionKey = (v: string) => `${v}.emotion` as 'a.emotion' | 'b.emotion' | 'c.emotion'

  const NAME_PLACEHOLDER = 'custom name'

  function cleanVoice(v: VoiceProfile): VoiceProfile {
    const out: VoiceProfile = {}
    for (const [k, val] of Object.entries(v)) {
      if (typeof val === 'string' ? val.trim() : val !== undefined && val !== null) out[k as keyof VoiceProfile] = val
    }
    return out
  }

  $effect(() => {
    if (urlInput && screen === 'compose') {
      const active = document.activeElement
      if (active && (active === document.body || active instanceof HTMLButtonElement && active.type === 'submit')) urlInput.focus()
    }
  })

  // the source field is the anchor of compose ("/ focuses input"): after a
  // settings level toggle, typing readiness is the default state again
  function refocusSource() {
    // preventScroll: typing readiness without yanking the viewport to the top
    urlInput?.focus({ preventScroll: true })
  }

  async function handleRemix(sourceOrJobId: string, isUrl: boolean) {
    if (job) {
      if (job.style) panelVals.style = job.style
      if (job.format) panelVals.format = job.format as 'dialog' | 'narration'
      if (job.language) panelVals.language = job.language
      if (job.show_name) panelVals.showName = job.show_name
      if (job.watchlist_id) panelVals.showId = job.watchlist_id
      if (job.voice_profile) {
        jobVoice = { ...job.voice_profile }
      }

      const scriptStage = job.stages?.find((s) => s.name === 'script')
      const voiceMap = scriptStage?.meta?.voice_map as Record<string, string> | undefined
      if (voiceMap) {
        if (voiceMap['A']) jobVoice['a.name'] = voiceMap['A']
        if (voiceMap['B']) jobVoice['b.name'] = voiceMap['B']
        if (voiceMap['C']) jobVoice['c.name'] = voiceMap['C']
      }

      if (job.script?.length) {
        const spks = new Set(job.script.map((l) => l.speaker))
        panelVals.hosts = Math.max(1, Math.min(3, spks.size))
      }
    }

    const transcriptFallback = job?.script?.length
      ? job.script.map((l) => `${l.speaker}: ${l.text}`).join('\n\n')
      : ''

    const targetId = job?.id || sourceOrJobId
    let clonedLoaded = false
    if (targetId) {
      try {
        const cloned = await cloneJobSources(targetId)
        if (cloned && cloned.length > 0) {
          traySources = cloned
          clonedLoaded = true
        }
      } catch {
        // ignore clone failure, use fallback
      }
    }

    if (!clonedLoaded) {
      if (isUrl && sourceOrJobId) {
        sourceKind = 'url'
        url = sourceOrJobId
        text = transcriptFallback
      } else {
        sourceKind = 'text'
        url = ''
        let loadedText = ''
        if (targetId) {
          try {
            const resp = await fetch(`/source/${targetId}`)
            if (resp.ok) {
              loadedText = await resp.text()
            }
          } catch {
            // ignore
          }
        }
        text = loadedText || transcriptFallback
      }
    }

    history.replaceState(null, '', location.pathname)
    screen = 'compose'
    window.scrollTo({ top: 0, behavior: 'smooth' })
    setTimeout(() => refocusSource(), 60)
  }

  async function loadRecent() {
    try {
      const fetched = await listJobs(12)
      // server now dedupes done jobs by url (recent dedupe moved to GET /jobs)
      recent = fetched.filter((r) => r.state === 'done')
    } catch {
      recent = readLocalRecent()
    }
  }

  // only reacts to explicit hashes; never resets the screen on its own
  async function openFromHash(h: string) {
    const raw = h.startsWith('#') ? h.slice(1) : h
    // Check for clip route: #e={id}/clip/{turn_start}-{turn_end}[-{slug}] (slug ignored, regex extracts indices)
    const clipMatch = raw.match(/^e=(.+?)\/clip\/(\d+)-(\d+)(?:-.+)?$/)
    if (clipMatch) {
      const id = clipMatch[1] ?? ''
      const startStr = clipMatch[2] ?? ''
      const endStr = clipMatch[3] ?? ''
      if (!id || !startStr || !endStr) return
      clipTurnStart = parseInt(startStr, 10)
      clipTurnEnd = parseInt(endStr, 10)
      if (job?.id !== id || screen !== 'listen') {
        try {
          void getListenScreen()
          job = await getJob(id)
          screen = 'listen'
        } catch {
          error = 'gone'
        }
      }
      return
    }
    const id = (raw.split('&')[0] || '').replace(/^e=/, '')
    if (!id) return
    if (job?.id === id && screen === 'listen') return
    try {
      job = await getJob(id)
      // an unfinished job (queued, running, or paused for its script review)
      // belongs on the progress screen, not in the player
      if (job.state === 'queued' || job.state === 'running' || job.state === 'awaiting_review') {
        void getQueueComponent()
        void getPipelineComponent()
        screen = 'progress'
        if (job.state !== 'awaiting_review') watch(id)
      } else {
        void getListenScreen()
        screen = 'listen'
      }
    } catch {
      error = 'gone'
    }
  }

  function applyHash() {
    // router handler: must never be tracked by effects. the mount
    // effect calls this; without untrack it would re-run on every
    // screen change and reset compose -> progress (regression from
    // e729e24, broke the go button for a day)
    untrack(() => {
      const h = location.hash
      const prevScreen = screen
      if (h === '#faq' || h.startsWith('#faq#') || h.startsWith('#faq?')) {
        screen = 'faq'
        if (h.includes('#') && h.indexOf('#', 1) !== -1) {
          const targetId = h.slice(h.indexOf('#', 1) + 1)
          setTimeout(() => {
            const el = document.getElementById(targetId)
            if (el) el.scrollIntoView({ behavior: 'smooth', block: 'start' })
          }, 60)
        }
      } else if (h === '#library') {
        screen = 'library'
        void openLibrary()
      } else if (h === '#settings') {
        stopEvents?.()
        void getSettingsScreen()
        screen = 'settings'
      } else if (h === '#watchlist') {
        screen = 'watchlist'
        void openWatchlist()
      } else if (h === '#about' || h.startsWith('#about#') || h.startsWith('#about?')) {
        screen = 'about'
        if (h.includes('#') && h.indexOf('#', 1) !== -1) {
          const targetId = h.slice(h.indexOf('#', 1) + 1)
          setTimeout(() => {
            const el = document.getElementById(targetId)
            if (el) el.scrollIntoView({ behavior: 'smooth', block: 'start' })
          }, 60)
        }
      } else if (h === '#agents' || h.startsWith('#agents#') || h.startsWith('#agents?')) {
        void getAgentsScreen()
        screen = 'agents'
        if (h.includes('#') && h.indexOf('#', 1) !== -1) {
          const targetId = h.slice(h.indexOf('#', 1) + 1)
          setTimeout(() => {
            const el = document.getElementById(targetId)
            if (el) el.scrollIntoView({ behavior: 'smooth', block: 'start' })
          }, 60)
        }

      } else if (h === '#profile' || h.startsWith('#profile=') || h.startsWith('#profile/') || h === '#p' || h.startsWith('#p=') || h.startsWith('#p/')) {
        openProfileFromHash(h)
      } else if (h.startsWith('#e=')) {
        void getListenScreen()
        void openFromHash(h)
      } else screen = 'compose'
      if (screen !== prevScreen && !h.includes('#', 1)) window.scrollTo(0, 0)
    })
  }

  function showEpisode(j: Job) {
    void getListenScreen()
    history.pushState(null, '', `#e=${j.id}`)
    screen = 'listen'
    window.scrollTo(0, 0)
  }

  $effect(() => {
    try {
      const active = getActiveIdentity()
      nostrIdentity = active
      if (active && active.pubkey && !active.name && !active.displayName) {
        fetchProfileFromRelays(active.pubkey)
          .then((res) => {
            if (res.profile) {
              const name = res.profile.name || res.profile.display_name || res.profile.displayName
              if (name) {
                const updated: NostrIdentity = {
                  ...active,
                  name,
                  displayName: res.profile.display_name || res.profile.displayName || res.profile.name,
                  picture: res.profile.picture,
                  nip05: res.profile.nip05
                }
                setActiveIdentity(updated)
                nostrIdentity = updated
              }
            }
          })
          .catch(() => {})
      }
    } catch {
      nostrIdentity = null
    }
    window.addEventListener('hashchange', applyHash)
    applyHash()
    fetchProviders()
      .then((p) => (providers = p))
      .catch(() => (providers = { providers: [], active: [] }))
    fetchMeta()
      .then((m) => (meta = m))
      .catch(() => (meta = null))
    getSettings()
      .then((s) => {
        if (!reviewTouched) {
          reviewScript = s.settings['script.review_default'] === '1'
        }
        const lang = s.settings['language.default']
        if (lang && lang !== 'auto') language = lang
        const creatorAddress = (s.settings['feed.creator.address'] ?? '').trim()
        const sourceAddress = (s.settings['feed.source.address'] ?? '').trim()
        const appAddress = (s.settings['feed.app.address'] ?? '').trim()
        const creatorSplit = Number(s.settings['feed.creator.split'] ?? 70)
        const sourceSplit = Number(s.settings['feed.source.split'] ?? 20)
        const appSplit = Number(s.settings['feed.app.split'] ?? 10)
        if (creatorAddress || sourceAddress || appAddress) {
          v4v = {
            address: creatorAddress,
            split: creatorSplit,
            creatorAddress,
            creatorSplit,
            sourceAddress,
            sourceSplit,
            appAddress,
            appSplit
          }
        } else {
          v4v = null
        }
        // DUE-041-Rest: keys with an explicit global setting win over the
        // per-language defaults applied by the effect above
        settingsVoiceKeys = new Set(
          (['voice.a.timbre', 'voice.b.timbre', 'voice.c.timbre', 'voice.solo.timbre'] as const).filter(
            (k) => s.settings[k] !== undefined && s.settings[k] !== null && s.settings[k] !== ''
          )
        )
        // DUE-078: panel defaults prefill the per-job voice profile
        const count = Number(s.settings['voice.dialog.count'] ?? 2)
        // Unset voices take the active engine's default cast; hardcoded qwen
        // ids here used to overwrite that cast whenever settings loaded last,
        // so kokoro/dia2 jobs got qwen voice names.
        const df = meta?.default_timbre_for
        const cast = df?.[panelVals.language] ?? df?.['auto']
        jobVoice = {
          'a.timbre': s.settings['voice.a.timbre'] ?? cast?.a,
          'b.timbre': s.settings['voice.b.timbre'] ?? cast?.b,
          'c.timbre': s.settings['voice.c.timbre'] ?? cast?.c,
          'solo.timbre': s.settings['voice.solo.timbre'] ?? cast?.solo,
          'a.emotion': 'neutral',
          'b.emotion': 'neutral',
          'c.emotion': 'neutral',
          'solo.emotion': 'neutral',
          count: isNaN(count) ? 2 : count
        }
        const defShow = s.settings['show.name'] ?? ''
        if (defShow) panelVals.showName = defShow
        
        // Set effective defaults for the customize panel
        defaultStyle = s.settings['style.default'] ?? 'balanced'
        defaultFormat = (s.settings['format.default'] as 'dialog' | 'narration') ?? 'dialog'
        defaultHosts = Number(s.settings['hosts.default'] ?? 2)
        defaultReviewScript = s.settings['script.review_default'] === '1'
      })
      .catch(() => {})
    void loadRecent()
    void listWatchlists().then((w) => (watchlists = w)).catch(() => {})
    return () => {
      window.removeEventListener('hashchange', applyHash)
      stopEvents?.()
    }
  })

  function handleSlash(e: KeyboardEvent) {
    if (e.key !== '/' || screen !== 'compose') return
    const t = e.target as HTMLElement
    if (t && (t.tagName === 'INPUT' || t.tagName === 'TEXTAREA' || t.tagName === 'SELECT' || t.isContentEditable)) return
    e.preventDefault()
    urlInput?.focus()
  }

  let sourceCardEl = $state<HTMLElement | null>(null)
  let showStickyBar = $state(false)

  function handleWindowScroll() {
    if (screen !== 'compose' || !sourceCardEl) {
      if (showStickyBar) showStickyBar = false
      return
    }
    const rect = sourceCardEl.getBoundingClientRect()
    // Show quick launch bar once main source card header scrolls out of view
    showStickyBar = rect.bottom < 50
  }

  async function handleTraySubmit(sourceRefs: { id: string; role: SourceRole }[]) {
    if (sourceRefs.length === 0) return
    busy = true
    error = ''
    try {
      const opts = {
        style: panelVals.style,
        format: panelVals.format,
        language: panelVals.language,
        hosts: panelVals.hosts,
        explicit: panelVals.explicit,
        voice: cleanVoice(jobVoice),
        show_name: (panelVals.showName ?? '').trim() || undefined,
        focus: focus.trim() || undefined,
        review_script: reviewScript || undefined,
        ...lengthOpts()
      }
      job = await createJobWithTray(sourceRefs, { ...opts, allow_cloud_for_uploads: allowCloudForUploads })
      const primaryTitle = traySources.find((s) => s.id === sourceRefs[0]?.id)?.title || 'podcast'
      pushLocalRecent({
        id: job.id,
        title: job.title || primaryTitle,
        url: traySources.find((s) => s.id === sourceRefs[0]?.id)?.origin_url || '',
        state: job.state
      })
      void getQueueComponent()
      void getPipelineComponent()
      screen = 'progress'
      watch(job.id)
    } catch (err) {
      error = err instanceof Error ? err.message : 'unreachable'
    } finally {
      busy = false
    }
  }

  async function submit(e?: Event) {
    e?.preventDefault()
    if (traySources.length > 0) {
      const validRefs = traySources
        .filter((s) => s.status !== 'failed')
        .map((s) => ({ id: s.id, role: s.role || 'main' }))
      if (validRefs.length > 0) {
        await handleTraySubmit(validRefs)
        return
      }
    }
    let source = sourceKind === 'url' ? url.trim() : text.trim()
    if (!source && textNotes.length === 0 && extraSources.length === 0) return
    if (sourceKind === 'text' && textNotes.length === 0 && extraSources.length === 0) {
      if (source.length < 150) {
        error = 'pasted text too short (min 150 chars for a meaningful dialogue)'
        return
      }
      if (textWarn) {
        error = `cannot generate dialogue: ${textWarn}`
        return
      }
    } else {
      if (sourceKind === 'url' && urlWarn) {
        error = `invalid URL: ${urlWarn}`
        return
      }
    }
    // pastes often lose the scheme; native url validation would block
    // the submit silently, so we normalize instead (issue: go button
    // did nothing on scheme-less urls)
    if (sourceKind === 'url' && source && !/^https?:\/\//i.test(source)) {
      source = `https://${source}`
      url = source
    }
    busy = true
    error = ''
    try {
      const opts = {
        style: panelVals.style,
        format: panelVals.format,
        language: panelVals.language,
        hosts: panelVals.hosts,
        explicit: panelVals.explicit,
        voice: cleanVoice(jobVoice),
        show_name: (panelVals.showName ?? '').trim() || undefined,
        focus: focus.trim() || undefined,
        review_script: reviewScript || undefined,
        ...lengthOpts()
      }
      const allSources = buildSources()
      const combinedText = buildCombinedText()
      const combine = selectedShowId !== 'digest'
      if (allSources.length >= 2) {
        // multiple sources (urls, text notes, or both): combined multi-source episode
        job = await createJobWithSources(allSources, combinedText, {
          ...opts,
          combine,
          review_script: combine ? opts.review_script : undefined
        })
      } else if (sourceKind === 'url') {
        job = await createJob(source, opts)
      } else {
        job = await createJobFromText(source, opts)
      }
      pushLocalRecent({ id: job.id, title: job.title || (sourceKind === 'url' ? url : 'pasted text'), url: sourceKind === 'url' ? url : '', state: job.state })
      void getQueueComponent()
      void getPipelineComponent()
      screen = 'progress'
      watch(job.id)
    } catch (err) {
      error = err instanceof Error ? err.message : 'unreachable'
    } finally {
      busy = false
    }
  }

  async function retryJob() {
    if (!job || busy) return
    busy = true
    error = ''
    try {
      const srcUrl = job.url ?? ''
      job = await createJob(srcUrl, {
        style: panelVals.style,
        format: panelVals.format,
        language: panelVals.language,
        hosts: panelVals.hosts,
        explicit: panelVals.explicit,
        voice: cleanVoice(jobVoice),
        show_name: (panelVals.showName ?? '').trim() || undefined,
        focus: focus.trim() || undefined,
        ...lengthOpts()
      })
      pushLocalRecent({ id: job.id, title: job.title, url: srcUrl, state: job.state })
      screen = 'progress'
      watch(job.id)
    } catch (err) {
      error = err instanceof Error ? err.message : 'unreachable'
    } finally {
      busy = false
    }
  }

  function watch(id: string) {
    stopEvents?.()
    streamError = null
    const poll = setInterval(async () => {
      try {
        const j = await getJob(id)
        job = j
        // clear stale stream error once polling succeeds
        if (streamError) streamError = null
        if (j.state === 'done') {
          finish(j)
          clearInterval(poll)
        } else if (j.state === 'failed' || j.state === 'cancelled' || j.state === 'awaiting_review') {
          clearInterval(poll)
        }
      } catch {
        void id
      }
    }, 4000)
    stopEvents = jobEvents(
      id,
      (j) => {
        job = j
        streamError = null
        if (j.state === 'done') {
          finish(j)
          stopEvents?.()
          clearInterval(poll)
        } else if (j.state === 'failed' || j.state === 'cancelled' || j.state === 'awaiting_review') {
          stopEvents?.()
          clearInterval(poll)
        }
      },
      (reason) => {
        if (reason === 'invalid data') {
          // keep stream open, polling already covers gaps
          return
        }
        streamError = reason
      }
    )
  }

  async function approveReview(lines: { speaker: string; text: string }[] | undefined, title?: string) {
    if (!job || reviewBusy) return
    reviewBusy = true
    error = ''
    try {
      job = await approveScript(job.id, lines, title)
      watch(job.id)
    } catch (err) {
      error = err instanceof Error ? err.message : 'could not start voicing'
    } finally {
      reviewBusy = false
    }
  }

  async function cancel() {
    if (!job || job.state === 'done' || job.state === 'failed') return
    try {
      job = await cancelJob(job.id)
    } catch {
      error = 'cancel failed'
    }
  }

  function finish(j: Job) {
    job = j
    showEpisode(j)
  }

  function reset() {
    stopEvents?.()
    streamError = null
    const failedUrl = job?.state === 'failed' ? (job.url ?? '') : ''
    job = null
    url = failedUrl
    extraSources = []
    newSource = ''
    textNotes = []
    newTextNote = ''
    error = ''
    screen = 'compose'
    history.replaceState(null, '', location.pathname)
    void loadRecent()
  }



  async function resume(r: JobSummary) {
    if (r.state !== 'done') {
      try {
        void getQueueComponent()
        void getPipelineComponent()
        job = await getJob(r.id)
        screen = 'progress'
        watch(job.id)
      } catch {
        error = 'gone'
      }
      return
    }
    try {
      job = await getJob(r.id)
      showEpisode(job)
    } catch {
      error = 'gone'
    }
  }

  function goNext() {
    if (!job) return
    const idx = recent.findIndex((r) => r.id === job!.id)
    if (idx >= 0 && idx < recent.length - 1) void resume(recent[idx + 1]!)
    else if (idx === -1 && recent.length > 0) void resume(recent[0]!)
  }

  function goPrev() {
    if (!job) return
    const idx = recent.findIndex((r) => r.id === job!.id)
    if (idx > 0) void resume(recent[idx - 1]!)
  }
</script>

<svelte:window onkeydown={handleSlash} onscroll={handleWindowScroll} />

<a href="#main-content" class="skip-link mono">Skip to content</a>
<main id="main-content" tabindex="-1">
  <header class:compose-header={screen === 'compose'}>
    <div class="header-bar">
      <a href="/" class="mono kicker">
        <picture class="brand-mark-picture">
          <source srcset="/vozonda-mark-dark.svg" media="(prefers-color-scheme: dark)" />
          <img src="/vozonda-mark.svg" class="brand-mark" alt="" width="56" height="56" />
        </picture>
        <span class="brand-title">vozonda</span>
      </a>
      <div class="header-actions">
        {#if nostrIdentity}
          <button
            type="button"
            class="header-action mono"
            onclick={() => goProfile(profileQuery || nostrIdentity?.npub || '')}
            title={`Signed in as ${nostrIdentity.name ? `${nostrIdentity.name} (${nostrIdentity.npub})` : nostrIdentity.npub} · click to view profile`}
            aria-label={`View Nostr profile for ${identityDisplayName(nostrIdentity)}`}
          >
            <span class="nostr-dot" aria-hidden="true"></span> {identityDisplayName(nostrIdentity)}
          </button>
        {:else}
          <button
            type="button"
            class="header-action mono"
            onclick={() => (nostrOpen = true)}
            title="Sign in with Nostr"
            aria-label="Sign in with Nostr"
          >
            <Icon name="key" size={13} /> sign in
          </button>
        {/if}
        {#if screen === 'compose'}
          <button type="button" class="header-action mono" onclick={openSettings} title="Open advanced settings">
            <Icon name="sliders" size={13} /> settings
          </button>
        {/if}
      </div>
    </div>
    {#if nostrOpen}
      {#await getNostrLogin()}
        <div class="mono loading-screen" style="padding: var(--space-6); text-align: center;">// loading sign-in...</div>
      {:then NostrLogin}
        <NostrLogin
          open={true}
          onClose={() => { nostrOpen = false; try { nostrIdentity = getActiveIdentity() } catch { void 0 } }}
          onLogin={(id) => { nostrIdentity = id; nostrOpen = false }}
        />
      {:catch err}
        <p class="mono err" role="alert">// failed to load sign-in &middot; <button onclick={() => { nostrLoginPromise = null }}>retry</button></p>
      {/await}
    {/if}
    {#if screen === 'compose'}
      <h1 class="hero">Turn sources into your podcast</h1>
      <p class="lede hero">Vozonda reads them, voices make waves, you listen.</p>
    {:else if screen === 'about'}
      <h1>Yours to keep.<br>Truly sovereign audio.</h1>
    {:else if screen === 'agents'}
      <h1>connect your assistant.<br />let agents produce.</h1>
      <p class="lede">mcp server and http api for autonomous podcast episodes.</p>
{:else if screen === 'settings'}
      <h1>Advanced settings.</h1>
      <p class="lede">Where the show gets its edge.</p>
{:else if screen === 'watchlist'}
      <h1>Set a feed.<br>Wake up to episodes.</h1>
    {:else if screen === 'library'}
      <h1>Everything<br />you've made so far.</h1>
    {:else if screen === 'faq'}
      <h1>How it works,<br />straight up.</h1>
    {:else if screen === 'listen' && job}
      <h1>{job.title}</h1>
    {/if}
  </header>
{#if screen === 'watchlist'}
  {#await getWatchlistScreen()}
    <div class="watchlist-screen mono loading-screen" style="padding: var(--space-6); text-align: center;">// loading watchlist...</div>
  {:then WatchlistScreen}
    <WatchlistScreen
      watchlists={watchlists}
      episodes={library}
      meta={meta}
      onback={leaveHash}
      onSettings={openSettings}
      onLibrary={openLibrary}
      onAdd={handleAddWatchlist}
      onRemove={handleRemoveWatchlist}
      onToggle={handleToggleWatchlist}
      onCheck={handleCheckWatchlist}
      onDigestToggle={handleDigestToggle}
      onDigestNow={handleDigestNow}
      onResume={(e) => resume(e)}
      onSaveVoice={handleSaveWatchlistVoice}
      onUpdateSettings={handleUpdateWatchlistSettings}
    />
  {:catch err}
    <p class="mono err" role="alert">// failed to load watchlist &middot; <button onclick={() => { watchlistPromise = null }}>retry</button></p>
  {/await}
{:else if screen === 'library'}
  {#await getLibraryScreen()}
    <div class="library-screen mono loading-screen" style="padding: var(--space-6); text-align: center;">// loading library...</div>
  {:then LibraryScreen}
    <LibraryScreen
      episodes={library}
      onResume={(e) => resume(e)}
      onback={leaveHash}
    />
  {:catch err}
    <p class="mono err" role="alert">// failed to load library &middot; <button onclick={() => { libraryPromise = null }}>retry</button></p>
  {/await}
{:else if screen === 'faq'}
  {#await getFaqScreen()}
    <div class="faq-screen mono loading-screen" style="padding: var(--space-6); text-align: center;">// loading faq...</div>
  {:then FaqScreen}
    <FaqScreen meta={meta} onback={() => (screen = 'compose')} />
  {:catch err}
    <p class="mono err" role="alert">// failed to load faq &middot; <button onclick={() => { faqPromise = null }}>retry</button></p>
  {/await}
{:else if screen === 'about'}
  {#await getAboutScreen()}
    <div class="about-screen mono loading-screen" style="padding: var(--space-6); text-align: center;">// loading about...</div>
  {:then AboutScreen}
    <AboutScreen onback={leaveHash} />
  {:catch err}
    <p class="mono err" role="alert">// failed to load about &middot; <button onclick={() => { aboutPromise = null }}>retry</button></p>
  {/await}
{:else if screen === 'agents'}
  {#await getAgentsScreen()}
    <div class="agents-screen mono loading-screen" style="padding: var(--space-6); text-align: center;">// loading agents...</div>
  {:then AgentsScreen}
    <AgentsScreen onback={leaveHash} />
  {:catch err}
    <p class="mono err" role="alert">// failed to load agents &middot; <button onclick={() => { agentsPromise = null }}>retry</button></p>
  {/await}

{:else if screen === 'settings'}
  {#await getSettingsScreen()}
    <div class="settings-screen mono loading-screen" style="padding: var(--space-6); text-align: center;">// loading...</div>
  {:then SettingsScreen}
    <SettingsScreen meta={meta} {providers} onback={leaveHash} />
  {:catch err}
    <p class="mono err" role="alert">// failed to load settings &middot; <button onclick={() => { settingsPromise = null }}>retry</button></p>
  {/await}
{:else if screen === 'profile'}
  {#await getProfileScreen()}
    <div class="profile-screen mono loading-screen" style="padding: var(--space-6); text-align: center;">// loading profile...</div>
  {:then NostrProfileScreen}
    {#key profileQuery}
      <NostrProfileScreen initial={profileQuery} onback={leaveHash} />
    {/key}
  {:catch err}
    <p class="mono err" role="alert">// failed to load profile &middot; <button onclick={() => { profilePromise = null }}>retry</button></p>
  {/await}
{:else if screen === 'listen' && job}
  {#await getListenScreen()}
    <div class="listen-screen mono loading-screen" style="padding: var(--space-6); text-align: center;">// loading player...</div>
  {:then ListenScreen}
    <ListenScreen
      title={job.title}
      src={`/audio/${job.id}.mp3`}
      lines={job.script ?? []}
      jobId={job.id}
      sourceUrl={job.url}
      createdAt={job.created_at}
      jobStyle={job.style}
      jobFormat={job.format}
      jobLanguage={job.language}
      jobDurationMs={job.duration_ms}
      jobAudio={job.stages?.find((s) => s.name === 'master')?.meta?.audio ?? null}
      jobVoices={job.stages?.find((s) => s.name === 'script')?.meta?.voices ?? []}
      jobVoiceMap={job.stages?.find((s) => s.name === 'script')?.meta?.voice_map ?? null}
      jobTuning={job.stages?.find((s) => s.name === 'master')?.meta?.tuning ?? null}
      jobStages={job.stages ?? null}
      jobProvider={job.provider ?? null}
      jobTone={job.tone ?? null}
      jobExplicit={!!job.explicit}
      metaStyleDocs={meta?.style_docs ?? null}
      metaStyleMeta={meta?.style_meta ?? null}
      sourceLang={job.stages?.find((s) => s.name === 'extract')?.meta?.source_lang ?? ''}
      watchlistId={job.watchlist_id ?? null}
      showName={job.show_name ?? null}
      showAuthor={job.show_author ?? null}
      chapters={job.chapters ?? null}
      isDigest={!!job.digest}
      ogImage={job.og_image}
      valueTip={v4v}
      executiveSummary={job.executive_summary ?? null}
      executiveQuote={job.executive_quote ?? null}
      keyTakeaways={job.key_takeaways ?? null}
      factualityScore={job.factuality_score ?? null}
      onback={() => reset()}
      onPrev={goPrev}
      onNext={goNext}
      onremix={handleRemix}
      clipTurnStart={clipTurnStart}
      clipTurnEnd={clipTurnEnd}
    />
  {:catch err}
    <p class="mono err" role="alert">// failed to load player &middot; <button onclick={() => { listenPromise = null }}>retry</button></p>
  {/await}

    {:else}
    {#if screen === 'progress' && job}
      {#await getQueueComponent()}
        <div class="mono loading-screen" style="padding: var(--space-6); text-align: center;">// loading queue...</div>
      {:then QueueIndicator}
        <QueueIndicator
          queuePosition={job.queue_position}
          queueLength={job.queue_length}
          estimatedWaitMs={job.estimated_wait_ms}
          jobState={job.state}
          streamError={streamError}
          aheadTitle={job.ahead_title}
          aheadCount={job.ahead_count}
          billingEnabled={meta?.billing_enabled}
          jobTitle={job.title}
          voiceStageStarted={job.stages?.some((s) => s.name === 'voice' && (s.status === 'running' || s.status === 'done')) ?? false}
          onCancel={async (id: string) => { await cancelJob(id); job = await getJob(id); }}
          jobId={job.id}
        />
      {:catch err}
        <p class="mono err" role="alert">// failed to load queue &middot; <button onclick={() => { queuePromise = null }}>retry</button></p>
      {/await}
      {#await getPipelineComponent()}
        <div class="mono loading-screen" style="padding: var(--space-6); text-align: center;">// loading pipeline...</div>
      {:then PipelineChecklist}
        <PipelineChecklist stages={job.stages} title={job.title} queuePosition={job.queue_position} estimatedWaitMs={job.estimated_wait_ms} state={job.state} />
      {:catch err}
        <p class="mono err" role="alert">// failed to load pipeline &middot; <button onclick={() => { pipelinePromise = null }}>retry</button></p>
      {/await}
      {#if job.state === 'awaiting_review' && job.script}
        {#key job.id}
          {#await getScriptReview()}
            <div class="mono loading-screen" style="padding: var(--space-6); text-align: center;">// loading script review...</div>
          {:then ScriptReview}
            <ScriptReview script={job.script} title={job.title} names={Object.fromEntries(hostNames.map((n, i) => [panelVals.format === 'narration' ? 'Narrator' : 'ABC'[i] ?? '', n]))} busy={reviewBusy} onApprove={(lines, title) => void approveReview(lines, title)} />
          {:catch err}
            <p class="mono err" role="alert">// failed to load script review &middot; <button onclick={() => { scriptReviewPromise = null }}>retry</button></p>
          {/await}
        {/key}
      {/if}
      {#if job.error}
        <p class="mono err" role="alert" aria-live="assertive">// {job.error}</p>
      {/if}
      {#if error && job.state === 'awaiting_review'}
        <p class="mono err" role="alert" aria-live="assertive">// {error}</p>
      {/if}
      <div class="progress-actions">
        {#if job.state === 'queued' || job.state === 'running'}
          <button class="quiet mono danger" onclick={() => void cancel()}>cancel</button>
        {:else if job.state === 'failed'}
          <button class="quiet mono" onclick={() => void retryJob()}>try again</button>
        {/if}
        <button class="quiet mono" onclick={reset}>← start over</button>
      </div>
{:else if screen === 'compose'}
      {#if showStickyBar}
        <div class="sticky-action-bar" role="toolbar" aria-label="Quick launch bar">
          <button
            type="button"
            class="sab-source-preview"
            onclick={() => {
              window.scrollTo({ top: 0, behavior: 'smooth' })
              refocusSource()
            }}
            title="Click to edit source link or text"
          >
            <Icon name={traySources.length > 0 ? 'brain' : (sourceKind === 'url' ? 'link' : 'brain')} size={15} />
            {#if traySources.length > 0}
              <span class="sab-text">
                {traySources.length} source{traySources.length === 1 ? '' : 's'} · {traySources[0]?.title || 'draft'}
              </span>
            {:else if sourceKind === 'url'}
              <span class="sab-text" class:sab-placeholder={!url.trim()}>
                {url.trim() ? url.trim() : 'paste link or url...'}
              </span>
            {:else}
              <span class="sab-text" class:sab-placeholder={!text.trim()}>
                {text.trim() ? `${text.trim().length} chars · draft` : 'paste notes / draft...'}
              </span>
            {/if}
          </button>

          <div class="sab-right">
            <span class="sab-badge" title="Selected show">
              {SHOWS.find((sh) => sh.id === selectedShowId)?.label ?? panelVals.style}
            </span>
            <button
              type="button"
              class="sab-go-btn"
              class:flash={goFlash}
              disabled={busy || (traySources.length === 0 && !url.trim() && !text.trim())}
              onclick={(e) => void submit(e)}
              title="Launch episode generation"
              aria-label="Generate podcast"
            >
              <Icon name="playtri" size={14} />
              <span>{busy ? 'starting…' : 'make it talk'}</span>
            </button>
          </div>
        </div>
      {/if}

      <section bind:this={sourceCardEl} class="ess source-card" class:launching={busy} aria-labelledby="source-h">
        <h2 id="source-h" class="mono ess-h"><Icon name="brain" size={18} /> source</h2>

        <SourceTray
          bind:sources={traySources}
          maxSources={meta?.limits?.max_sources ?? meta?.max_sources ?? 10}
          maxSourceChars={meta?.limits?.max_source_chars ?? meta?.max_source_chars ?? 120000}
          scriptEngineLocal={meta?.script_engine_local ?? true}
          scriptEngineProvider={meta?.runtime?.llm_engine || meta?.runtime?.llm || 'cloud'}
          bind:allowCloudForUploads
          busy={busy}
          goFlash={goFlash}
          onSubmit={handleTraySubmit}
          bind:inputEl={urlInput}
        />

        <div class="opts-row">
          <input id="c-focus" class="focus-input mono" type="text" maxlength="300" bind:value={focus}
            placeholder="focus: e.g. the privacy angle, skip the history"
            aria-label="Focus: what should the hosts dig into?" />
          <select id="c-lang-top" class="lang-select mono" aria-label="Episode language" bind:value={panelVals.language}>
            <option value="auto">language: auto</option>
            {#each Object.entries(meta?.languages ?? {}) as [code, name] (code)}
              <option value={code}>language: {name}</option>
            {/each}
          </select>
        </div>

        {#if busy}
          <div class="launch-status mono" role="status" aria-live="assertive">
            <Icon name="pulse" size={14} />
            <span>studio engaged · composing dialogue script...</span>
          </div>
        {/if}
      </section>

      <ShowPicker
        selectedId={selectedShowId}
        engine={meta?.runtime?.tts_engine ?? 'qwen_tts'}
        names={hostNames}
        speed={typeof jobVoice.speed === 'number' ? jobVoice.speed : undefined}
        minutes={episodeMinutes}
        sourceCount={traySources.length > 0 ? traySources.length : (sourceKind === 'url' ? 1 + extraSources.length : 1)}
        review={reviewScript}
        onSelect={selectShow}
        onCustomize={openCustomize}
      />

      {#if customizeOpen}
        <div class="customize-head" bind:this={customizeEl} tabindex="-1" aria-labelledby="customize-h">
          <h2 id="customize-h" class="mono ess-h"><Icon name="sliders" size={18} /> customize <span class="cz-scope">this episode only</span></h2>
          <button type="button" class="link mono" onclick={closeCustomize}>done</button>
        </div>

        <section class="ess length-card" aria-labelledby="length-h">
          <h2 id="length-h" class="mono ess-h"><Icon name="pacing" size={18} /> length</h2>
          <div class="length-row">
            <div class="seg" role="radiogroup" aria-label="Episode length">
              {#each LENGTH_PRESETS as p (p.id)}
                <button type="button" role="radio" aria-checked={!lengthMinutes && lengthPreset === p.id} class:sel={!lengthMinutes && lengthPreset === p.id}
                  onclick={() => { lengthPreset = p.id; lengthMinutes = null }}>{p.label}</button>
              {/each}
            </div>
            <label class="len-min mono" for="len-min">or
              <input id="len-min" type="number" min="1" max="60" step="1" inputmode="numeric" placeholder={String(episodeMinutes)}
                value={lengthMinutes ?? ''} oninput={(e) => setLengthMinutes(e.currentTarget.value)} />
              min</label>
          </div>
          <p class="mono source-help">about {episodeMinutes} minutes. a thin source is kept shorter, never padded with invented material.</p>
        </section>

        <EssentialsSection
          {meta}
          values={panelVals}
          voiceProfile={jobVoice}
          showStyle={true}
          showLanguage={false}
          onStyleChange={(style: string) => {
            panelVals.style = style
          }}
          onFormatChange={(format: 'dialog' | 'narration') => {
            panelVals.format = format
          }}
          onLanguageChange={(language: string) => (panelVals.language = language)}
          onHostsChange={(hosts: number) => {
            panelVals.hosts = hosts
          }}
          onExplicitChange={(explicit: boolean) => (panelVals.explicit = explicit)}
          onVoiceTimbreChange={(key: string, timbre: string) => { voiceTouched = true; jobVoice[key as keyof VoiceProfile] = timbre }}
          onVoiceEmotionChange={(key: string, emotion: string) => (jobVoice[key as keyof VoiceProfile] = emotion)}
          onVoiceNameChange={(key: string, name: string) => (jobVoice[key as keyof VoiceProfile] = name)}
          onProbePlay={toggleProbe}
          {probeKey}
          watchlists={watchlists}
          selectedShow={panelVals.showId}
          onShowChange={(showId: string) => (panelVals.showId = showId)}
          showName={panelVals.showName}
          onShowNameChange={(showName: string) => (panelVals.showName = showName)}
          onResetStyle={() => resetToDefault('style')}
          onResetFormat={() => resetToDefault('format')}
          onResetHosts={() => resetToDefault('hosts')}
          defaultStyle={defaultStyle}
          defaultFormat={defaultFormat}
          defaultHosts={defaultHosts}
          changedStyle={changedStyle}
          changedFormat={changedFormat}
          changedHosts={changedHosts}
        />

        <section class="ess script-card" aria-labelledby="script-h">
          <h2 id="script-h" class="mono ess-h"><Icon name="prompts" size={18} /> script</h2>
          <div class="script-ctrl-row">
            <div class="seg" role="radiogroup" aria-label="Script">
              <button
                type="button"
                role="radio"
                aria-checked={!reviewScript}
                class:sel={!reviewScript}
                onclick={() => { reviewTouched = true; reviewScript = false }}
              >straight to audio</button>
              <button
                type="button"
                role="radio"
                aria-checked={reviewScript}
                class:sel={reviewScript}
                onclick={() => { reviewTouched = true; reviewScript = true }}
              >script to me first</button>
            </div>
            <div class="script-defaults">
              {#if changedReviewScript}
                <span class="changed-marker">changed</span>
                <button type="button" class="link mono back-to-default" onclick={() => resetToDefault('reviewScript')}>back to default</button>
              {:else}
                <span class="default-marker">(default)</span>
              {/if}
            </div>
          </div>
          <p class="mono source-help">
            {#if reviewScript}
              script to me first: the script and title are generated first for your review and editing; audio is voiced only after you approve.
            {:else}
              straight to audio: script, title and audio are all voiced automatically in one continuous run.
            {/if}
          </p>
        </section>
      {/if}

      <div class="settings-cta-row">
        <button type="button" class="settings-cta mono" onclick={openSettings}>
          <Icon name="sliders" size={18} /> defaults for every episode
        </button>
        <span class="mono cta-hint">engines, feed, value for value, prompts</span>
      </div>

      {#if error}
        <p class="mono err" role="alert" aria-live="assertive">// {error}</p>
      {/if}

      <section class="ess recent-card" aria-labelledby="recent-h">
        <h2 id="recent-h" class="mono ess-h"><Icon name="history" size={18} /> recent episodes</h2>
        <p class="mono sec-help">
          pick up where you left off. everything lives in
          <button class="link mono" onclick={openLibrary}>the library</button>.
        </p>
        {#if recent.length > 0}
          <div class="rlinks">
            {#each recent.slice(0, 4) as r (r.id)}
              <button
                class="rcard"
                onclick={() => resume(r)}
                title={r.url}
              >
                <span class="rtitle">{r.title}</span>
                <span class="mono rmeta">
                  {r.created_at ? new Date(r.created_at * 1000).toLocaleDateString(undefined, { month: 'short', day: 'numeric' }) : ''}
                  {r.style ? ` · ${r.style}` : ''}
                  {r.format ? ` · ${r.format === 'narration' ? 'read aloud' : 'conversation'}` : ''}
                  {r.audio_seconds ? ` · ${Math.round(r.audio_seconds / 60)} min` : ''}
                </span>
              </button>
            {/each}
            {#if recent.length > 4}
              <button class="link mono" onclick={openLibrary}>all {recent.length} →</button>
            {/if}
          </div>
        {:else}
          <p class="mono styledoc">// nothing yet. paste something worth hearing.</p>
        {/if}
      </section>
    {/if}

    {/if}
    <footer class="foot">
      <nav class="foot-nav" aria-label="Places">
        <button class="foot-link mono" onclick={goAbout}>about</button>
        <button class="foot-link mono" onclick={goFaq}>faq</button>
        <button class="foot-link mono" onclick={goAgents}>agents</button>
        <button class="foot-link mono" onclick={openLibrary}>library</button>
        <button class="foot-link mono" onclick={openWatchlist}>watchlist</button>
      </nav>
      <div class="foot-meta mono tagline">
        {#if meta}<span class="nobrk"><a href="https://vozonda.com/changelog/" target="_blank" rel="noopener" class="dev-link">v{meta.version}</a> ·</span> {/if}<span class="nobrk">sovereign audio overview</span> · <span class="nobrk">nostr-native</span> · <span class="nobrk">multi-engine</span> · <span class="nobrk">open source</span>
      </div>
    </footer>
  </main>

<style>
  main {
    max-width: var(--content-max-width);
    margin: 0 auto;
    padding: var(--space-4) var(--space-4) var(--space-6);
    flex: 1;
    display: flex;
    flex-direction: column;
  }

  header {
    margin-bottom: var(--space-4);
  }

  header.compose-header {
    margin-bottom: clamp(24px, 4.5vh, 44px);
  }

  header.compose-header .header-bar {
    margin-bottom: clamp(32px, 6vh, 64px);
  }

  .source-card {
    margin-bottom: clamp(16px, 3vh, 32px);
  }

  .header-bar {
    display: flex;
    align-items: center;
    justify-content: space-between;
    gap: var(--space-2);
    margin-bottom: var(--space-4);
    flex-wrap: nowrap;
  }

  .header-actions {
    display: flex;
    align-items: center;
    gap: var(--space-2);
    flex-wrap: nowrap;
  }

  .header-action {
    display: inline-flex;
    align-items: center;
    gap: 5px;
    background: transparent;
    border: 1px solid var(--line);
    border-radius: var(--radius);
    padding: 3px 8px;
    color: var(--ink-soft);
    font-family: var(--font-mono);
    font-size: var(--ui-size);
    letter-spacing: 0.03em;
    cursor: pointer;
    line-height: 1.2;
    white-space: nowrap;
    transition: color var(--dur-fast, 120ms) ease-out, border-color var(--dur-fast, 120ms) ease-out, background var(--dur-fast, 120ms) ease-out;
  }

  .header-action:hover {
    color: var(--green);
    border-color: var(--green);
    background: color-mix(in srgb, var(--green) 4%, transparent);
  }

  .header-action:focus-visible {
    outline: 2px solid var(--green);
    outline-offset: 2px;
  }

  .kicker {
    display: inline-flex;
    align-items: center;
    gap: 12px;
    color: var(--ink-soft);
    font-family: var(--font-mono);
    text-decoration: none;
    min-height: 56px;
    padding: 0;
  }

  .brand-mark-picture {
    display: inline-flex;
    align-items: center;
  }

  .brand-mark {
    width: 56px;
    height: 56px;
    display: block;
    flex-shrink: 0;
  }

  .brand-title {
    font-size: 2.1rem;
    font-weight: 700;
    letter-spacing: -0.02em;
    line-height: 1;
    color: var(--ink);
  }

  .kicker:hover {
    text-decoration: underline;
  }

  h1 {
    font-size: var(--h1-size);
    font-weight: var(--h1-weight, 600);
    line-height: var(--h1-line-height, 1.08);
    letter-spacing: var(--h1-letter-spacing, -0.02em);
    margin: var(--h1-margin, var(--space-3) 0);
    text-wrap: var(--h1-text-wrap, balance);
  }

  h2 {
    font-size: var(--h2-size);
    font-weight: var(--h2-weight, 600);
    line-height: var(--h2-line-height, 1.18);
    margin: var(--h2-margin, var(--space-2) 0);
    text-wrap: var(--h2-text-wrap, balance);
  }

  .hero {
    text-align: center;
    margin-left: auto;
    margin-right: auto;
  }

  h1.hero {
    margin-top: 0;
    margin-bottom: var(--space-2);
  }

  .lede {
    color: var(--lede-color, var(--ink-soft));
    font-size: var(--lede-size, clamp(0.85rem, 2.2vw, 1.08rem));
    margin-bottom: 0;
    max-width: 52ch;
    text-wrap: balance;
  }

  .lede.hero {
    margin-top: 0;
  }


  @media (max-width: 480px) {
    main {
      padding: var(--space-2) var(--space-3) var(--space-4);
    }
    .brand-mark {
      width: 44px;
      height: 44px;
    }
    .brand-title {
      font-size: 1.6rem;
    }
    .kicker {
      min-height: 44px;
      gap: 8px;
    }
    header {
      margin-bottom: var(--space-4);
    }
    header.compose-header {
      margin-bottom: var(--space-3);
    }
    header.compose-header .header-bar {
      margin-bottom: var(--space-3);
    }
    .source-card {
      margin-bottom: 0;
    }
    .header-bar {
      gap: 4px;
    }
    .header-actions {
      gap: 3px;
    }
    .header-action {
      padding: 2px 5px;
      font-size: calc(var(--ui-size) * 0.75);
      letter-spacing: 0;
      min-height: 26px;
      gap: 2px;
    }
    .kicker {
      font-size: calc(var(--ui-size) * 0.85);
      white-space: nowrap;
    }
    h1 {
      margin: var(--space-2) 0;
    }
    .ess {
      padding: var(--space-3);
      gap: var(--space-3);
      max-width: 100%;
      box-sizing: border-box;
    }
    .seg {
      width: 100%;
      max-width: 100%;
      display: grid;
      grid-template-columns: 1fr 1fr;
      box-sizing: border-box;
    }
    .seg button {
      min-height: 32px;
      padding: 3px var(--space-2);
      font-size: calc(var(--ui-size) * 0.82);
    }
    input:not([type=checkbox]):not([type=radio]) {
      min-height: 38px;
      padding: 6px 10px;
      font-size: calc(var(--ui-size) * 0.88);
    }
  }

  @media (max-height: 640px) {
    header.compose-header {
      margin-bottom: var(--space-2);
    }
    header.compose-header .header-bar {
      margin-bottom: var(--space-2);
    }
    .source-card {
      margin-bottom: var(--space-2);
    }
  }

  input:not([type=checkbox]):not([type=radio]) {
    flex: 1;
    min-width: 0;
    max-width: 100%;
    width: 100%;
    box-sizing: border-box;
    padding: 8px 12px;
    font-family: var(--font-mono);
    font-size: var(--ui-size);
    background: color-mix(in srgb, var(--ink) 3%, var(--paper));
    border: 1px solid color-mix(in srgb, var(--ink) 16%, var(--line));
    border-radius: var(--radius);
    color: var(--ink);
    min-height: 40px;
    transition: border-color var(--dur-slow) ease-out, background var(--dur-fast) ease-out;
  }

  input:not([type=checkbox]):not([type=radio])::placeholder {
    color: var(--ink-soft);
    opacity: 0.7;
  }

  input:not([type=checkbox]):not([type=radio]):focus-visible {
    outline: 2px solid var(--green);
    outline-offset: 2px;
    border-color: var(--green);
    background: color-mix(in srgb, var(--green) 3%, var(--paper));
  }

  .seg {
    display: inline-flex;
    gap: 2px;
    align-items: center;
    background: color-mix(in srgb, var(--ink) 4%, var(--paper));
    border: 1px solid color-mix(in srgb, var(--ink) 14%, var(--line));
    border-radius: var(--radius);
    padding: 2px;
  }

  .seg button {
    background: transparent;
    border: 1px solid transparent;
    border-radius: calc(var(--radius) - 1px);
    color: var(--ink-soft);
    font-family: var(--font-mono);
    font-size: calc(var(--ui-size) * 0.88);
    font-weight: 500;
    min-height: 34px;
    padding: 3px var(--space-3);
    cursor: pointer;
    text-transform: lowercase;
    display: inline-flex;
    align-items: center;
    justify-content: center;
    transition: color var(--dur-fast) ease-out, background var(--dur-fast) ease-out, border-color var(--dur-fast) ease-out;
  }

  .seg button:hover:not(:disabled):not(.sel):not([aria-checked="true"]) {
    color: var(--ink);
    background: color-mix(in srgb, var(--ink) 8%, var(--paper));
  }

  .seg button.sel,
  .seg button[aria-checked="true"] {
    background: var(--green);
    color: var(--paper);
    border: 1px solid var(--green);
    font-weight: 600;
  }

  .seg button:disabled {
    opacity: 0.45;
    cursor: not-allowed;
  }


  .err {
    color: var(--voice-b);
    margin-top: var(--space-3);
  }

  /* recent episodes as a proper card: drastic separation from the
     settings CTA line above, consistent with the card system */
  .recent-card {
    margin-top: var(--space-6);
  }

  .sec-help {
    color: var(--ink-soft);
    font-size: calc(var(--ui-size) * 0.85);
    margin: 0;
  }

  .rlinks {
    display: grid;
    gap: var(--space-2);
  }

  /* mini cards: library recognition without stealing the create focus */
  .rcard {
    display: grid;
    gap: var(--space-1);
    width: 100%;
    text-align: left;
    background: transparent;
    border: 1px solid var(--line);
    border-radius: var(--radius);
    padding: var(--space-2) var(--space-3);
    cursor: pointer;
  }

  .rcard:hover {
    border-color: var(--ink-soft);
  }

  .rtitle {
    font-family: var(--font-serif);
    font-size: calc(var(--ui-size) * 1.05);
    color: var(--ink);
    white-space: nowrap;
    overflow: hidden;
    text-overflow: ellipsis;
  }

  .rmeta {
    font-size: calc(var(--ui-size) * 0.8);
    color: var(--ink-soft);
  }

  .link {
    background: none;
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

  .link:hover {
    color: var(--green);
  }

  .quiet {
    margin-top: var(--space-4);
    background: none;
    border: none;
    cursor: pointer;
  }

  .progress-actions {
    display: flex;
    gap: var(--space-3);
    margin-top: var(--space-4);
  }

  .progress-actions .quiet {
    margin-top: 0;
    padding: var(--space-1) var(--space-1);
    min-height: 28px;
  }

  .quiet.danger:hover {
    color: var(--voice-b);
  }

  footer.foot {
    margin-top: var(--space-6);
    padding-top: var(--space-5);
    padding-bottom: var(--space-6);
    border-top: 1px solid var(--line);
    display: flex;
    flex-direction: column;
    align-items: center;
    justify-content: center;
    text-align: center;
    gap: var(--space-3);
  }

  .foot-nav {
    display: flex;
    align-items: center;
    justify-content: center;
    gap: var(--space-5);
    flex-wrap: wrap;
  }

  .foot-link {
    display: inline-flex;
    align-items: center;
    background: transparent;
    border: none;
    color: var(--ink);
    font-size: var(--ui-size);
    cursor: pointer;
    min-height: 44px;
    padding: 0 var(--space-2);
    letter-spacing: 0.02em;
    transition: color var(--dur-fast, 120ms) ease-out;
  }
  .foot-link:hover {
    color: var(--green);
  }
  .foot-link:focus-visible {
    outline: 2px solid var(--green);
    outline-offset: 2px;
    color: var(--ink);
  }

  .foot-meta {
    text-align: center;
    color: var(--ink-soft);
    font-size: calc(var(--ui-size) * 0.92);
    line-height: 1.5;
  }

  .nobrk {
    white-space: nowrap;
  }
  @media (max-width: 480px) {
    .nobrk {
      white-space: normal;
    }
  }
  .tagline :global(a),
  .foot-meta :global(a),
  .dev-link {
    color: var(--ink-soft);
    text-decoration: underline;
    text-underline-offset: 2px;
    /* tap target: audit requires >= 24px hit height */
    display: inline-block;
    padding: 3px 2px;
    min-height: 24px;
    line-height: 18px;
  }
  .tagline :global(a:hover),
  .foot-meta :global(a:hover),
  .dev-link:hover {
    color: var(--green);
  }

  @media (max-width: 640px) {
    footer.foot {
      margin-top: var(--space-5);
      padding-top: var(--space-4);
      padding-bottom: var(--space-5);
      gap: var(--space-2);
    }
    .foot-nav {
      gap: var(--space-3);
    }
    .foot-meta {
      font-size: calc(var(--ui-size) * 0.88);
    }
  }

  .skip-link {
    position: absolute;
    top: -100%;
    left: 8px;
    z-index: 100;
    background: var(--ink);
    color: var(--paper);
    padding: var(--space-2) var(--space-3);
    border-radius: var(--radius);
    text-decoration: none;
    font-family: var(--font-mono);
    font-size: var(--ui-size);
  }

  .skip-link:focus,
  .skip-link:focus-visible {
    top: 8px;
    outline: 2px solid var(--green);
    outline-offset: 2px;
  }

  #main-content:focus {
    outline: none;
  }

  #main-content:focus-visible {
    outline: 2px solid var(--green);
    outline-offset: 2px;
  }

  .ess {
    border: 1px solid var(--line);
    border-radius: var(--radius);
    padding: var(--space-5);
    display: grid;
    gap: var(--space-4);
    min-width: 0;
    background: color-mix(in srgb, var(--paper) 4%, transparent);
  }

  .source-help {
    color: var(--ink-soft);
    font-size: calc(var(--ui-size) * 0.85);
    margin: 0;
  }

  .sab-go-btn.flash {
    animation: go-pulse var(--dur-slow) ease-out 2;
  }

  @keyframes go-pulse {
    from {
      box-shadow: 0 0 0 0 color-mix(in srgb, var(--green) 50%, transparent);
    }
    to {
      box-shadow: 0 0 0 10px transparent;
    }
  }

  /* status label: subtle separator from compose output */
  .launch-status {
    margin-top: var(--space-3);
    padding-top: var(--space-2);
    border-top: 1px solid var(--line);
    color: var(--ink-soft);
    font-size: calc(var(--ui-size) * 0.85);
    display: flex;
    align-items: center;
    gap: var(--space-2);
    animation: editorialFade var(--dur-slow) ease-out;
  }

  @keyframes editorialFade {
    from {
      opacity: 0;
      transform: translateY(2px);
    }
    to {
      opacity: 1;
      transform: translateY(0);
    }
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

  /* sales-pitch row: position stays at the bottom, look is centered and
     prominent (grill decision 2026-08-24) */
  .settings-cta-row {
    display: flex;
    flex-direction: column;
    align-items: center;
    gap: var(--space-2);
    text-align: center;
    border-top: 1px solid var(--line);
    padding-top: var(--space-4);
    margin-top: var(--space-4);
    scroll-margin-top: 90px;
  }

  /* flexibility is the USP: the settings door stays visible, not subtle */
  .settings-cta {
    display: inline-flex;
    align-items: center;
    gap: var(--space-2);
    background: transparent;
    border: 1px solid var(--ink-soft);
    border-radius: var(--radius);
    color: var(--ink);
    font-family: var(--font-mono);
    font-size: var(--ui-size);
    padding: var(--space-2) var(--space-4);
    cursor: pointer;
    letter-spacing: 0.02em;
    scroll-margin-top: 90px;
  }

  .settings-cta:hover {
    background: var(--ink);
    color: var(--paper);
    border-color: var(--ink);
  }

  .cta-hint {
    color: var(--ink);
    font-size: var(--ui-size);
  }

  /* Quick launch sticky top bar on compose screen */
  .sticky-action-bar {
    position: sticky;
    top: 0;
    z-index: 30;
    margin: 0 0 var(--space-4) 0;
    padding: var(--space-2) var(--space-3);
    background: color-mix(in srgb, var(--paper) 90%, transparent);
    backdrop-filter: blur(12px);
    -webkit-backdrop-filter: blur(12px);
    border: 1px solid color-mix(in srgb, var(--ink) 16%, var(--line));
    border-radius: var(--radius);
    display: flex;
    align-items: center;
    justify-content: space-between;
    gap: var(--space-3);
    box-shadow: 0 4px 14px rgba(0, 0, 0, 0.08);
    animation: stickySlideDown 180ms ease-out;
  }

  @keyframes stickySlideDown {
    from {
      transform: translateY(-8px);
      opacity: 0;
    }
    to {
      transform: translateY(0);
      opacity: 1;
    }
  }

  .sab-source-preview {
    display: flex;
    align-items: center;
    gap: var(--space-2);
    flex: 1 1 auto;
    min-width: 0;
    cursor: pointer;
    background: color-mix(in srgb, var(--ink) 4%, var(--paper));
    border: 1px solid color-mix(in srgb, var(--ink) 14%, var(--line));
    border-radius: var(--radius);
    padding: var(--space-1) var(--space-3);
    min-height: 42px;
    text-align: left;
    transition: border-color var(--dur-fast) ease-out, background var(--dur-fast) ease-out;
  }

  .sab-source-preview:hover {
    border-color: var(--ink);
    background: color-mix(in srgb, var(--ink) 8%, var(--paper));
  }

  .sab-text {
    font-family: var(--font-mono);
    font-size: var(--ui-size);
    color: var(--ink);
    white-space: nowrap;
    overflow: hidden;
    text-overflow: ellipsis;
  }

  .sab-text.sab-placeholder {
    color: var(--ink-soft);
  }

  .sab-right {
    display: flex;
    align-items: center;
    gap: var(--space-2);
    flex-shrink: 0;
  }

  .sab-badge {
    font-family: var(--font-mono);
    font-size: calc(var(--ui-size) * 0.85);
    font-weight: 500;
    color: var(--ink);
    background: color-mix(in srgb, var(--ink) 5%, transparent);
    padding: 3px 8px;
    border-radius: var(--radius);
    border: 1px solid color-mix(in srgb, var(--ink) 15%, var(--line));
    white-space: nowrap;
  }

  @media (max-width: 500px) {
    .sab-badge {
      display: none;
    }
  }

  .sab-go-btn {
    flex-shrink: 0;
    min-height: 42px;
    min-width: 72px;
    font-family: var(--font-mono);
    font-size: var(--ui-size);
    font-weight: 600;
    background: var(--ink);
    color: var(--paper);
    border: none;
    border-radius: var(--radius);
    padding: var(--space-1) var(--space-4);
    cursor: pointer;
    display: inline-flex;
    align-items: center;
    gap: var(--space-2);
    white-space: nowrap;
    transition: background var(--dur-fast) ease-out, opacity var(--dur-fast) ease-out;
  }

  .sab-go-btn:hover:not(:disabled) {
    background: var(--green);
  }

  .sab-go-btn:disabled {
    opacity: 0.45;
    cursor: not-allowed;
  }

  /* VOZONDA-UX-1: step 1 multi-source chips */

  /* UX masterplan 2026-09-23: language on the source card, flat customize */
  .opts-row {
    display: flex;
    flex-wrap: wrap;
    gap: var(--space-2);
  }

  /* phones: focus and language stack; side by side the focus field shrank to a stub */
  @media (max-width: 600px) {
    .opts-row {
      flex-direction: column;
    }
    .opts-row .focus-input,
    .opts-row .lang-select {
      flex: 0 0 auto;
      max-width: none;
    }
  }

  .focus-input {
    flex: 3 1 260px;
    min-width: 0;
    min-height: 44px;
    padding: 0 var(--space-3);
    background: var(--paper);
    color: var(--ink);
    border: 1px solid var(--line);
    border-radius: var(--radius);
    font-size: calc(var(--ui-size) * 0.9);
  }

  .focus-input::placeholder {
    color: color-mix(in srgb, var(--ink-soft) 80%, transparent);
    font-style: italic;
  }

  .focus-input:focus-visible {
    outline: 2px solid var(--green);
    outline-offset: 2px;
  }

  .lang-select {
    /* a select is as wide as its longest option unless allowed to shrink;
       that pushed the whole source card past the phone edge */
    flex: 1 1 160px;
    min-width: 0;
    width: 100%;
    max-width: 16rem;
    text-overflow: ellipsis;
    min-height: 44px;
    padding: 0 var(--space-3);
    background: var(--paper);
    color: var(--ink);
    border: 1px solid var(--line);
    border-radius: var(--radius);
    font-size: calc(var(--ui-size) * 0.9);
  }

  .lang-select:focus-visible {
    outline: 2px solid var(--green);
    outline-offset: 2px;
  }

  /* phones: the link field is the page's main input, so it gets the full
     width; its button and the add-source row stack below it */
  .customize-head {
    display: flex;
    align-items: center;
    justify-content: space-between;
    gap: var(--space-3);
    margin-top: var(--space-5);
    padding: var(--space-3) 0;
    border-top: 1px dashed var(--line);
    /* clear the sticky quick-launch bar when scrolled to */
    scroll-margin-top: calc(var(--space-6) + var(--space-5));
  }

  /* focused only by script (tabindex=-1) so screen readers land here; no ring */
  .customize-head:focus {
    outline: none;
  }

  .cz-scope {
    color: var(--ink-soft);
    font-size: calc(var(--ui-size) * 0.85);
    letter-spacing: 0;
    margin-left: var(--space-1);
  }

  .length-card {
    margin-bottom: var(--space-5);
  }

  .length-row {
    display: flex;
    flex-wrap: wrap;
    align-items: center;
    gap: var(--space-3);
  }

  .length-row .seg button,
  .script-card .seg button {
    min-height: 44px;
  }

  .script-card {
    margin-top: var(--space-5);
  }

  .script-ctrl-row {
    display: flex;
    flex-wrap: wrap;
    align-items: center;
    gap: var(--space-3);
  }

  .script-defaults {
    display: inline-flex;
    align-items: center;
    gap: var(--space-2);
  }

  .changed-marker {
    font-size: calc(var(--ui-size) * 0.8);
    color: var(--voice-b);
    font-weight: 500;
  }

  .default-marker {
    font-size: calc(var(--ui-size) * 0.8);
    color: var(--ink-soft);
    font-style: italic;
  }

  .back-to-default {
    font-size: calc(var(--ui-size) * 0.8);
    padding: 0;
    min-height: 24px;
  }



  .len-min {
    display: inline-flex;
    align-items: center;
    gap: var(--space-2);
    color: var(--ink-soft);
    font-size: calc(var(--ui-size) * 0.9);
  }

  .len-min input {
    width: 5.5em;
    min-height: 44px;
    padding: 0 var(--space-2);
    background: var(--paper);
    color: var(--ink);
    border: 1px solid var(--line);
    border-radius: var(--radius);
    font-family: var(--font-mono);
    font-size: var(--ui-size);
  }


  .header-actions { display:flex; align-items:center; gap: var(--space-2); }
  .nostr-dot { width:8px; height:8px; border-radius:50%; background: var(--green); display:inline-block; box-shadow: 0 0 6px color-mix(in srgb, var(--green) 55%, transparent); }

</style>

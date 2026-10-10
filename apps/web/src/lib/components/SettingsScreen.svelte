<script lang="ts">
  import { tick } from 'svelte'
  import Icon from './Icon.svelte'
  import ProviderStrip from './ProviderStrip.svelte'
  import PluginsDrawer from './PluginsDrawer.svelte'
  import CustomStyleEditor from './CustomStyleEditor.svelte'
  import AddressCard from './AddressCard.svelte'
  import {
    getSettings,
    getStorageStats,
    purgeStorage,
    saveSetting,
    probeLlm,
    fetchLlmModels,
    getMusicStatus,
    importMusicUrl,
    resetMusic,
    getDistribution,
    setShowRss,
    getNostrShowStatus,
    setNostrPublish,
    exportNostrNsec,
    updateShow,
    createShow,
    deleteShow,
    listCustomStyles,
    deleteCustomStyle,
    type CustomStyle,
    type DistributionMeta,
    type NostrShowStatus,
    type Meta,
    type ProviderStatus,
    type StorageStats,
    type LlmProbeResult,
    type MusicStatus
  } from '../api'
  import { buildStyleGroups, buildStyleIcons, buildStyleDocs, categoryOf } from '../styles'

  let {
    meta,
    providers,
    onback
  }: {
    meta: Meta | null
    providers: ProviderStatus
    onback: () => void
  } = $props()

  let values = $state<Record<string, string>>({})
  let defaults = $state<Record<string, string>>({})
  let loaded = $state(false)
  let promptMode = $state('script.balanced')
  let selectedStyle = $state('balanced')
  let storageStats = $state<StorageStats | null>(null)
  let purging = $state(false)
  let purgeMsg = $state('')
  let llmApiKey = $state('')
  let llmCustomBase = $state('')
  let llmCustomModel = $state('')
  let llmStatus = $state<'checking' | 'ok' | 'offline' | 'unknown'>('checking')
  let llmProbe = $state<LlmProbeResult | null>(null)
  // model ids the cloud writers offer right now (asked live; no built-in list)
  let llmModels = $state<Record<string, string[]>>({})

  async function loadLlmModels(engine: string) {
    if ((engine !== 'opencode' && engine !== 'kimi_nim') || llmModels[engine]) return
    try {
      llmModels = { ...llmModels, [engine]: await fetchLlmModels(engine) }
    } catch {
      llmModels = { ...llmModels, [engine]: [] }
    }
  }

  function addOpencodeModel(id: string) {
    const list = (values['llm.opencode_models'] ?? '').split(/[,\s]+/).filter(Boolean)
    if (!list.includes(id)) set('llm.opencode_models', [...list, id].join(', '))
  }
  let pluginsOpen = $state(false)
  let musicStatus = $state<MusicStatus | null>(null)
  let musicImportUrl = $state('')
  let musicImportKind = $state<'intro' | 'outro'>('intro')
  let musicImportBusy = $state(false)
  let musicImportMsg = $state('')
  let musicImportError = $state('')
  let playingMusic = $state<'intro' | 'outro' | null>(null)
  let musicAudioEl: HTMLAudioElement | null = null

  function togglePlayMusic(kind: 'intro' | 'outro') {
    if (playingMusic === kind) {
      musicAudioEl?.pause()
      playingMusic = null
      return
    }
    if (musicAudioEl) {
      musicAudioEl.pause()
    }
    musicAudioEl = new Audio(`/music/${kind}.mp3?t=${Date.now()}`)
    musicAudioEl.onended = () => { playingMusic = null }
    musicAudioEl.onerror = () => { playingMusic = null }
    musicAudioEl.play().catch(() => { playingMusic = null })
    playingMusic = kind
  }

  async function doImportMusic() {
    if (!musicImportUrl.trim()) return
    musicImportBusy = true
    musicImportMsg = ''
    musicImportError = ''
    try {
      const res = await importMusicUrl(musicImportUrl.trim(), musicImportKind)
      musicImportMsg = `imported ${res.kind}.mp3 (${res.duration}s, 44.1kHz)`
      musicImportUrl = ''
      musicStatus = await getMusicStatus()
    } catch (err: unknown) {
      musicImportError = err instanceof Error ? err.message : 'import failed'
    } finally {
      musicImportBusy = false
    }
  }

  async function doResetMusic(kind: 'intro' | 'outro' | 'all' = 'all') {
    try {
      const res = await resetMusic(kind)
      musicStatus = res.status
      musicImportMsg = 'reset to built-in harmonic jazz'
      musicImportError = ''
      if (playingMusic) {
        musicAudioEl?.pause()
        playingMusic = null
      }
    } catch {
      musicImportError = 'reset failed'
    }
  }

  // Style groups, icons and docs come from GET /meta style_meta
  // (lib/styles.ts), with an offline fallback when /meta is unreachable.
  // Custom styles saved under /styles/custom merge in as group 'custom'.
  let customStyles = $state<CustomStyle[]>([])
  let customError = $state('')
  let showEditor = $state(false)
  let editingStyle = $state<CustomStyle | null>(null)
  let confirmDeleteId = $state<string | null>(null)
  let deleteBusy = $state(false)
  let confirmDeleteBtn = $state<HTMLButtonElement | null>(null)

  const mergedMeta = $derived(
    meta
      ? {
          ...meta,
          style_meta: [
            ...(meta.style_meta ?? []),
            ...customStyles
              .filter((s) => !(meta.style_meta ?? []).some((m) => m.id === s.id))
              .map((s) => ({ id: s.id, doc: s.doc || s.name, group: 'custom', icon: 'balanced', hosts: 'AB' }))
          ]
        }
      : meta
  )
  const styleGroups = $derived(buildStyleGroups(mergedMeta))
  const styleIcons = $derived(buildStyleIcons(mergedMeta))

  function categoryOfStyle(style: string): string {
    return categoryOf(style, mergedMeta)
  }

  const styleDocs = $derived(buildStyleDocs(mergedMeta))

  async function loadCustomStyles() {
    try {
      customStyles = await listCustomStyles()
      customError = ''
    } catch (err) {
      customError = err instanceof Error ? err.message.toLowerCase() : 'could not load your styles'
    }
  }

  function askDeleteStyle(id: string) {
    confirmDeleteId = id
    void tick().then(() => confirmDeleteBtn?.focus())
  }

  async function confirmDeleteStyle() {
    if (!confirmDeleteId || deleteBusy) return
    const id = confirmDeleteId
    confirmDeleteId = null
    deleteBusy = true
    try {
      await deleteCustomStyle(id)
      await loadCustomStyles()
    } catch (err) {
      customError = err instanceof Error ? err.message.toLowerCase() : 'could not delete the style'
    } finally {
      deleteBusy = false
    }
  }

  const feedXmlUrl = new URL(`${import.meta.env.VITE_API_BASE ?? ''}/feed.xml`, window.location.origin).href
  let copiedFeed = $state(false)
  async function copyFeed() {
    try {
      await navigator.clipboard.writeText(feedXmlUrl)
      copiedFeed = true
      setTimeout(() => (copiedFeed = false), 2000)
    } catch {
      copiedFeed = false
    }
  }

  function formatBytes(bytes: number): string {
    if (bytes === 0) return '0 B'
    const k = 1024
    const sizes = ['B', 'KB', 'MB', 'GB']
    const i = Math.floor(Math.log(bytes) / Math.log(k))
    return parseFloat((bytes / Math.pow(k, i)).toFixed(1)) + ' ' + sizes[i]
  }

  async function handlePurge() {
    if (purging) return
    purging = true
    purgeMsg = ''
    try {
      const res = await purgeStorage(360)
      storageStats = await getStorageStats()
      if (res.purged_count > 0) {
        purgeMsg = `freed ${formatBytes(res.freed_bytes)} across ${res.purged_count} files`
      } else {
        purgeMsg = 'all audio files are within the 360-day window'
      }
    } catch {
      purgeMsg = 'cleanup failed'
    } finally {
      purging = false
    }
  }

  // key for legacy reasons: balanced/narration live flat, every other
  // style under script.style.* (see settings_store)
  function promptKey(mode: string): string {
    if (mode === 'script.balanced' || mode === 'script.narration') return mode
    return `script.style.${mode}`
  }

  function scrollToSection(id: string) {
    activeSection = id
    const el = document.getElementById(id)
    if (el) {
      const nav = document.querySelector('.settings-nav') as HTMLElement | null
      const navHeight = nav ? nav.offsetHeight : 54
      const top = el.getBoundingClientRect().top + window.scrollY - navHeight - 16
      const reduce = matchMedia('(prefers-reduced-motion: reduce)').matches
      window.scrollTo({ top: Math.max(0, top), behavior: reduce ? 'auto' : 'smooth' })
    }
  }

  let nodeV4vLocked = $state(false)

  $effect(() => {
    void getStorageStats().then((s) => (storageStats = s)).catch(() => {})
    void getMusicStatus().then((m) => (musicStatus = m)).catch(() => {})
    void loadDistribution()
    void loadCustomStyles()
    getSettings()
      .then((s) => {
        values = {
          ...s.settings,
          'voice.speed': s.settings['voice.speed'] ?? '1.0',
          'voice.gap_ms': s.settings['voice.gap_ms'] ?? '380',
          'music.enabled': s.settings['music.enabled'] ?? '1',
          'music.intro': s.settings['music.intro'] ?? '1',
          'music.outro': s.settings['music.outro'] ?? '1',
          'music.duck_db': s.settings['music.duck_db'] ?? '-12.0',
          'feed.creator.address': s.settings['feed.creator.address'] || 'cipherfox@rizful.com',
          'feed.creator.split': s.settings['feed.creator.split'] ?? '70',
          'feed.source.address': s.settings['feed.source.address'] ?? '',
          'feed.source.split': s.settings['feed.source.split'] ?? '20',
          'feed.app.address': s.settings['feed.app.address'] ?? '',
          'feed.app.split': s.settings['feed.app.split'] ?? '10',
          'watchlist.render_mode': s.settings['watchlist.render_mode'] ?? 'newest',
          'source.research_depth': s.settings['source.research_depth'] ?? 'direct',
          'source.max_sources': s.settings['source.max_sources'] ?? '10',
          'source.max_chars': s.settings['source.max_chars'] ?? 'auto',
          'tts.engine': s.settings['tts.engine'] ?? 'qwen_tts',
          'llm.engine': s.settings['llm.engine'] ?? 'local',
          'llm.api_key': s.settings['llm.api_key'] ?? '',
          'llm.nim_api_key': s.settings['llm.nim_api_key'] ?? '',
          'llm.custom_base': s.settings['llm.custom_base'] ?? '',
          'llm.custom_model': s.settings['llm.custom_model'] ?? '',
          'show.name': s.settings['show.name'] ?? '',
          'show.author': s.settings['show.author'] ?? '',
          'show.description': s.settings['show.description'] ?? '',
          'show.category': s.settings['show.category'] ?? 'Technology',
          'player.default_speed': s.settings['player.default_speed'] ?? (typeof localStorage !== 'undefined' ? localStorage.getItem('vozonda_player_speed') : null) ?? '1.0',
          'player.default_text_size': s.settings['player.default_text_size'] ?? (typeof localStorage !== 'undefined' ? (localStorage.getItem('vozonda_pref_transcript_size') ?? localStorage.getItem('vozonda_text_size')) : null) ?? 'normal',
          'player.karaoke': s.settings['player.karaoke'] ?? (typeof localStorage !== 'undefined' ? (localStorage.getItem('vozonda_pref_karaoke') === 'false' ? '0' : '1') : null) ?? '1',
          'player.chapters': s.settings['player.chapters'] ?? (typeof localStorage !== 'undefined' ? (localStorage.getItem('vozonda_pref_transcript_chapters') === 'true' ? '1' : '0') : null) ?? '0',
          'player.autoscroll': s.settings['player.autoscroll'] ?? (typeof localStorage !== 'undefined' ? (localStorage.getItem('vozonda_pref_transcript_autoscroll') === 'false' ? 'free' : 'follow') : null) ?? 'follow',
          'player.boost_placement': s.settings['player.boost_placement'] ?? (typeof localStorage !== 'undefined' ? localStorage.getItem('vozonda_boost_variant') : null) ?? 'meta',
          'disclosure.ai_label': s.settings['disclosure.ai_label'] ?? '1',
          'script.review_default': s.settings['script.review_default'] ?? '0',
        }
        defaults = s.defaults ?? {}
        nodeV4vLocked = Boolean(s.node_v4v_locked)
        loaded = true
        llmApiKey = values['llm.api_key'] ?? ''
        llmCustomBase = values['llm.custom_base'] ?? ''
        llmCustomModel = values['llm.custom_model'] ?? ''
        void checkLlmStatus()
      })
      .catch(() => (loaded = true))
  })

  let savedFlash = $state(false)
  // a value the server refused (validation): shown instead of "saved"
  let saveError = $state('')
  let savedTimer: ReturnType<typeof setTimeout> | undefined

  const API_BASE = import.meta.env.VITE_API_BASE ?? ''

  async function checkLlmStatus() {
    const engine = values['llm.engine'] ?? 'local'
    llmStatus = 'checking'
    void loadLlmModels(engine)
    void loadLlmModels(values['llm.backup_engine'] ?? '')
    try {
      const res = await probeLlm({
        engine,
        custom_base: values['llm.custom_base'] || llmCustomBase,
        custom_model: values['llm.custom_model'] || llmCustomModel,
        api_key: values['llm.api_key'] || llmApiKey,
      })
      llmProbe = res
      llmStatus = res.status === 'ok' ? 'ok' : res.status === 'none' ? 'unknown' : 'offline'
    } catch {
      llmStatus = 'offline'
      llmProbe = null
    }
  }

  function set(key: string, value: string) {
    values = { ...values, [key]: value }
    if (key === 'llm.api_key') llmApiKey = value
    if (key === 'llm.custom_base') llmCustomBase = value
    if (key === 'llm.custom_model') llmCustomModel = value
    if (key === 'llm.engine') void checkLlmStatus()
    if (key === 'player.default_speed') {
      try { localStorage.setItem('vozonda_player_speed', value) } catch {}
    } else if (key === 'player.default_text_size') {
      try {
        localStorage.setItem('vozonda_text_size', value)
        localStorage.setItem('vozonda_pref_transcript_size', value)
      } catch {}
    } else if (key === 'player.karaoke') {
      try {
        localStorage.setItem('vozonda_karaoke', value)
        localStorage.setItem('vozonda_pref_karaoke', value === '1' ? 'true' : 'false')
      } catch {}
    } else if (key === 'player.chapters') {
      try {
        localStorage.setItem('vozonda_chapters', value)
        localStorage.setItem('vozonda_pref_transcript_chapters', value === '1' ? 'true' : 'false')
      } catch {}
    } else if (key === 'player.autoscroll') {
      try {
        localStorage.setItem('vozonda_autoscroll', value)
        localStorage.setItem('vozonda_pref_transcript_autoscroll', value === 'follow' ? 'true' : 'false')
      } catch {}
    } else if (key === 'player.boost_placement') {
      try { localStorage.setItem('vozonda_boost_variant', value) } catch {}
    }
    void saveSetting(key, value).then(() => {
      if (['llm.nim_api_key', 'llm.nim_model', 'llm.opencode_models', 'llm.backup_engine'].includes(key)) void checkLlmStatus()
      saveError = ''
      savedFlash = true
      clearTimeout(savedTimer)
      savedTimer = setTimeout(() => (savedFlash = false), 2000)
    }).catch((err: unknown) => {
      savedFlash = false
      saveError = err instanceof Error ? err.message : 'could not save'
    })
  }

  // restore the shipped defaults for one section; keys without a known
  // default are skipped so we never write blind values
  // ---- distribution (section 04) ----
  type Reach = 'private' | 'apps' | 'nostr' | 'both'
  type DistShow = DistributionMeta['shows'][number]
  const REACHES: { id: Reach; label: string; help: string }[] = [
    { id: 'private', label: 'private', help: 'no public feed and nothing published: episodes stay in your library.' },
    { id: 'apps', label: 'podcast apps', help: 'an rss feed for apple podcasts, spotify, pocket casts, antennapod and others. it needs your vozonda at a public address.' },
    { id: 'nostr', label: 'nostr only', help: 'audio on free blossom servers, episodes on nostr relays, signed with the show\'s own key. no server of your own, and no rss feed.' },
    { id: 'both', label: 'both', help: 'an rss feed for podcast apps and nostr: the widest reach.' }
  ]
  let dist = $state<DistributionMeta | null>(null)
  let distError = $state('')
  // the default show only chooses between private and podcast apps (no nostr key of its own)
  const MASTER_REACHES = REACHES.filter((r) => r.id === 'private' || r.id === 'apps').map((r) =>
    r.id === 'private'
      ? { ...r, help: 'no public feed: /feed.xml returns 404, so podcast apps that subscribed to it lose the show.' }
      : r
  )
  let reachBusy = $state<string | null>(null)
  let nostrStatus = $state<Record<string, NostrShowStatus>>({})
  let confirmNostr = $state<{ show: DistShow; reach: Reach } | null>(null)
  let confirmBtn = $state<HTMLButtonElement | null>(null)
  let nsecAsk = $state<string | null>(null)
  let nsecShown = $state<Record<string, string>>({})
  let copiedKey = $state('')

  const distShows = $derived((dist?.shows ?? []) as DistShow[])
  const anyFeed = $derived(distShows.some((s) => s.rss === '1'))

  function reachOf(s: DistShow): Reach {
    const rss = s.rss === '1'
    const nostr = s.nostr === '1'
    return rss && nostr ? 'both' : rss ? 'apps' : nostr ? 'nostr' : 'private'
  }

  async function loadDistribution() {
    try {
      dist = await getDistribution()
      distError = ''
      for (const s of distShows) {
        if (!s.fixed && s.nostr === '1') {
          nostrStatus = { ...nostrStatus, [s.slug]: await getNostrShowStatus(s.slug) }
        }
      }
    } catch (err) {
      distError = err instanceof Error ? err.message.toLowerCase() : 'could not load the distribution settings'
    }
  }

  async function applyReach(s: DistShow, reach: Reach, confirmPublic = false) {
    const wantRss = reach === 'apps' || reach === 'both'
    const wantNostr = reach === 'nostr' || reach === 'both'
    reachBusy = s.slug
    try {
      if ((s.rss === '1') !== wantRss) await setShowRss(s.slug, wantRss)
      if ((s.nostr === '1') !== wantNostr) await setNostrPublish(s.slug, wantNostr, confirmPublic)
      await loadDistribution()
    } catch (err) {
      distError = err instanceof Error ? err.message.toLowerCase() : 'could not change the reach'
    } finally {
      reachBusy = null
    }
  }

  function chooseReach(s: DistShow, reach: Reach) {
    const turnsNostrOn = (reach === 'nostr' || reach === 'both') && s.nostr !== '1'
    if (turnsNostrOn) {
      // publishing to nostr is public and hard to take back: confirm first, inline
      confirmNostr = { show: s, reach }
      void tick().then(() => confirmBtn?.focus())
      return
    }
    confirmNostr = null
    void applyReach(s, reach)
  }

  async function confirmPublish() {
    if (!confirmNostr) return
    const { show, reach } = confirmNostr
    confirmNostr = null
    await applyReach(show, reach, true)
  }

  async function saveShow(s: DistShow, patch: { name?: string; author?: string; category?: string }) {
    const name = (patch.name ?? s.name).trim()
    if (!name) {
      distError = 'a show needs a name'
      return
    }
    try {
      await updateShow(s.slug, { name, author: patch.author ?? s.author ?? '', category: patch.category ?? s.category ?? '' })
      await loadDistribution()
    } catch (err) {
      distError = err instanceof Error ? err.message.toLowerCase() : 'could not save the show'
    }
  }

  let creatingShow = $state(false)
  let newShowName = $state('')
  let newShowAuthor = $state('')
  let newShowCategory = $state('')
  let newShowBusy = $state(false)
  let newShowError = $state('')

  async function doCreateShow() {
    const name = newShowName.trim()
    if (!name) {
      newShowError = 'a show needs a name'
      return
    }
    newShowBusy = true
    newShowError = ''
    try {
      await createShow({
        name,
        author: newShowAuthor.trim(),
        category: newShowCategory.trim()
      })
      newShowName = ''
      newShowAuthor = ''
      newShowCategory = ''
      creatingShow = false
      await loadDistribution()
    } catch (err) {
      newShowError = err instanceof Error ? err.message.toLowerCase() : 'could not create the show'
    } finally {
      newShowBusy = false
    }
  }

  let deleteShowAsk = $state<DistShow | null>(null)
  let deleteShowBusy = $state(false)

  async function confirmDeleteShow() {
    if (!deleteShowAsk) return
    const s = deleteShowAsk
    deleteShowBusy = true
    distError = ''
    try {
      await deleteShow(s.slug)
      deleteShowAsk = null
      await loadDistribution()
    } catch (err) {
      distError = err instanceof Error ? err.message.toLowerCase() : 'could not delete the show'
    } finally {
      deleteShowBusy = false
    }
  }

  async function revealNsec(slug: string) {
    nsecAsk = null
    try {
      const res = await exportNostrNsec(slug)
      nsecShown = { ...nsecShown, [slug]: res.nsec }
    } catch (err) {
      distError = err instanceof Error ? err.message.toLowerCase() : 'could not export the key'
    }
  }

  async function copyText(key: string, text: string) {
    try {
      await navigator.clipboard.writeText(text)
      copiedKey = key
      setTimeout(() => { if (copiedKey === key) copiedKey = '' }, 1600)
    } catch {}
  }

  // relay and server lists: stored comma separated, edited one per line
  function asLines(v: string | undefined): string {
    return (v ?? '').split(/[,\n]+/).map((u) => u.trim()).filter(Boolean).join('\n')
  }
  function listError(v: string, prefix: string): string {
    const bad = v.split(/[,\n]+/).map((u) => u.trim()).filter(Boolean).find((u) => !u.startsWith(prefix))
    return bad ? `"${bad}" must start with ${prefix}` : ''
  }
  let relayError = $state('')
  let blossomError = $state('')
  function setList(key: string, text: string, prefix: string) {
    const err = listError(text, prefix)
    if (key === 'nostr.relays') relayError = err
    else blossomError = err
    if (!err) set(key, text.split(/[,\n]+/).map((u) => u.trim()).filter(Boolean).join(', '))
  }

  function resetSection(keys: string[]) {
    for (const k of keys) {
      const d = defaults[k]
      if (d !== undefined && d !== values[k]) set(k, d)
    }
  }

  const creatorSplit = $derived(Number(values['feed.creator.split'] ?? 70))
  const sourceSplit = $derived(Number(values['feed.source.split'] ?? 20))
  const appSplit = $derived(Number(values['feed.app.split'] ?? 10))

  const llmEngine = $derived(values['llm.engine'] ?? 'local')
  const showLlmConfig = $derived(llmEngine === 'claude' || llmEngine === 'custom')

  const ttsOptions = $derived.by(() => {
    const list = providers?.providers ?? []
    const filtered = list.filter((p) => p.id !== 'local' && p.id !== 'qwen_vllm')
    if (filtered.length === 0) {
      return [
        { id: 'qwen_tts', label: 'qwen3_tts (local GPU, studio quality)', installed: true, fix: '', ui_badge: 'local GPU', license: 'Apache-2.0', commercial_use: true, ui_fix_hint: '' },
        { id: 'voxtral', label: 'voxtral (Mistral EU, 30+ European voices & emotion tags)', installed: true, fix: '', ui_badge: 'EU cloud', license: 'Mistral API terms', commercial_use: true, ui_fix_hint: '', location: 'cloud' as const },
        { id: 'kokoro', label: 'kokoro-82m (local ONNX, 82M expressive, 15-25x realtime)', installed: true, fix: '', ui_badge: 'local CPU / ONNX', license: 'Apache-2.0', commercial_use: true, ui_fix_hint: '' },
        { id: 'piper', label: 'piper (CPU, multi-lingual open source)', installed: true, fix: '', ui_badge: 'local CPU', license: 'MIT', commercial_use: true, ui_fix_hint: '' },
      ]
    }
    return filtered
  })
  // native options cannot wrap: the list shows the short name, the full
  // description and licence of the chosen engine sit under the select
  function engineName(label: string): string {
    const i = label.indexOf(' (')
    return i > 0 ? label.slice(0, i) : label
  }
  const TTS_GROUPS = [
    { location: 'local', label: 'local · runs on this machine' },
    { location: 'cloud', label: 'cloud · script text leaves this machine' },
  ] as const
  const selectedEngineId = $derived(values['tts.engine'] ?? 'qwen_tts')
  const selectedEngine = $derived(ttsOptions.find((e) => e.id === selectedEngineId) ?? ttsOptions.find((e) => e.id === 'qwen_tts') ?? ttsOptions[0] ?? null)

  function applySplitPreset(creator: number, source: number, app: number) {
    set('feed.creator.split', String(creator))
    set('feed.source.split', String(source))
    set('feed.app.split', String(app))
  }

  function updateSplit(target: 'creator' | 'source' | 'app', valStr: string) {
    const val = Math.max(0, Math.min(100, Math.round(Number(valStr) || 0)))
    let c = creatorSplit
    let s = sourceSplit
    let a = appSplit

    if (target === 'source') {
      s = val
      if (s + a > 100) a = 100 - s
      c = Math.max(0, 100 - s - a)
    } else if (target === 'app') {
      a = val
      if (a + s > 100) s = 100 - a
      c = Math.max(0, 100 - s - a)
    } else if (target === 'creator') {
      c = val
      const remaining = 100 - c
      if (remaining <= 0) {
        s = 0
        a = 0
        c = 100
      } else {
        const totalOther = s + a
        if (totalOther > 0) {
          s = Math.round((s / totalOther) * remaining)
          a = remaining - s
        } else {
          a = remaining
        }
      }
    }

    set('feed.creator.split', String(c))
    set('feed.source.split', String(s))
    set('feed.app.split', String(a))
  }

  const speed = $derived(Number(values['voice.speed'] ?? 1))
  const duckDb = $derived(Number(values['music.duck_db'] ?? -12))
  // source tray (VOZONDA-TRAY-SETTINGS): the budget readout comes from /meta,
  // the override lives in source.max_chars ('auto' or a char count)
  const trayCharsRaw = $derived(((values['source.max_chars'] ?? 'auto').trim() || 'auto').toLowerCase())
  const trayCharsAuto = $derived(trayCharsRaw === 'auto')
  const trayBudgetChars = $derived(meta?.limits?.max_source_chars ?? meta?.max_source_chars ?? 180000)
  const trayMaxSources = $derived(meta?.limits?.max_sources ?? meta?.max_sources ?? 10)
  function formatKChars(n: number): string {
    return n >= 1000 ? `${Math.round(n / 1000)}k` : `${n}`
  }
  function chooseTrayCharsCustom() {
    if (trayCharsAuto) set('source.max_chars', String(trayBudgetChars))
  }
  // an empty stored prompt means 'use the built-in' (the pipeline falls back the same way);
  // '??' kept an emptied box empty and hid the default (script.balanced was saved as '')
  const promptValue = $derived(values[promptKey(promptMode)] || defaults[promptKey(promptMode)] || '')

  let activeSection = $state('sec-sources')

  $effect(() => {
    if (!loaded) return
    const sections = ['sec-sources', 'sec-script', 'sec-voice', 'sec-shows', 'sec-player', 'sec-system']
    let ticking = false

    const updateActiveSection = () => {
      const nav = document.querySelector('.settings-nav') as HTMLElement | null
      const navOffset = (nav ? nav.offsetHeight : 54) + 30
      const scrollPos = window.scrollY + navOffset

      const last = sections[sections.length - 1]
      if (last && window.innerHeight + window.scrollY >= document.documentElement.scrollHeight - 60) {
        activeSection = last
        return
      }

      let current = sections[0] ?? 'sec-sources'
      for (const id of sections) {
        const el = document.getElementById(id)
        if (el) {
          const top = el.getBoundingClientRect().top + window.scrollY
          if (scrollPos >= top) {
            current = id
          }
        }
      }
      activeSection = current
    }

    const onScroll = () => {
      if (!ticking) {
        requestAnimationFrame(() => {
          updateActiveSection()
          ticking = false
        })
        ticking = true
      }
    }

    window.addEventListener('scroll', onScroll, { passive: true })
    updateActiveSection()

    return () => {
      window.removeEventListener('scroll', onScroll)
    }
  })
</script>

<div class="settings-screen">
  <div class="settings-head">
    <button class="back mono" onclick={onback} aria-label="Back to compose">
      <Icon name="back" size={13} /> back
    </button>
    <p class="mono save-note" class:ok={savedFlash} class:err={!!saveError} role="status" aria-live="polite">
      {saveError ? `not saved: ${saveError}` : savedFlash ? 'saved' : 'changes save instantly'}
    </p>
  </div>

  {#if !loaded}
    <p class="mono note">// loading</p>
  {:else}
    <!-- Top Anchor Navigation Bar -->
    <nav class="settings-nav mono" aria-label="Settings navigation">
      <button
        type="button"
        class="nav-pill"
        class:active={activeSection === 'sec-sources'}
        onclick={() => scrollToSection('sec-sources')}
      >
        <Icon name="source" size={16} /> sources
      </button>
      <button
        type="button"
        class="nav-pill"
        class:active={activeSection === 'sec-script'}
        onclick={() => scrollToSection('sec-script')}
      >
        <Icon name="prompts" size={16} /> script
      </button>
      <button
        type="button"
        class="nav-pill"
        class:active={activeSection === 'sec-voice'}
        onclick={() => scrollToSection('sec-voice')}
      >
        <Icon name="voices" size={16} /> voice
      </button>
      <button
        type="button"
        class="nav-pill"
        class:active={activeSection === 'sec-shows'}
        onclick={() => scrollToSection('sec-shows')}
      >
        <Icon name="share" size={16} /> shows
      </button>
      <button
        type="button"
        class="nav-pill"
        class:active={activeSection === 'sec-player'}
        onclick={() => scrollToSection('sec-player')}
      >
        <Icon name="playtri" size={16} /> player
      </button>
      <button
        type="button"
        class="nav-pill"
        class:active={activeSection === 'sec-system'}
        onclick={() => scrollToSection('sec-system')}
      >
        <Icon name="storage" size={16} /> system
      </button>
    </nav>
    <!-- SECTION 1: SOURCES (how articles are gathered and watched) -->
    <div id="sec-sources" class="settings-group">
      <div class="group-title mono">
        <span class="group-kicker">// 01</span>
        <h2>sources</h2>
      </div>
      <p class="help group-help">how vozonda reads a source and what it does with the feeds you watch.</p>

      <section aria-labelledby="research-h">
        <div class="sec-head">
          <h3 id="research-h" class="mono"><Icon name="brain" size={18} /> research depth</h3>
          <button class="link mono" onclick={() => resetSection(['source.research_depth'])}>reset</button>
        </div>
        <div class="opt">
          <label class="lab mono" for="s-depth">source depth</label>
          <select
            id="s-depth"
            class="mono"
            value={values['source.research_depth'] ?? 'direct'}
            onchange={(e) => set('source.research_depth', e.currentTarget.value)}
          >
            <option value="direct">direct (target article text only)</option>
            <option value="deep-page">deep-page (+ internal chapters & subpages)</option>
            <option value="fact-check">fact-check (+ cited primary sources & studies)</option>
            <option value="contrast">contrast (+ synthesized counter-perspectives)</option>
          </select>
        </div>
        <div class="engine-detail mono" role="region" aria-live="polite">
          {#if (values['source.research_depth'] ?? 'direct') === 'direct'}
            <div class="detail-badge"><span class="badge-tag">Single Pass</span> · Fastest latency</div>
            <p class="detail-body">
              Extracts and digests only the direct article text from the submitted URL. Ideal for concise news, isolated blog posts, and fast audio delivery.
            </p>
          {:else if values['source.research_depth'] === 'deep-page'}
            <div class="detail-badge"><span class="badge-tag">Hierarchical Crawl</span> · Internal subpages</div>
            <p class="detail-body">
              Crawls up to 2 linked internal chapters, sub-articles, or documentation pages on the same domain to build deeper context.
            </p>
          {:else if values['source.research_depth'] === 'fact-check'}
            <div class="detail-badge"><span class="badge-tag">Grounding Expansion</span> · Primary citations</div>
            <p class="detail-body">
              Follows external references, studies, and source links cited in the body to corroborate claims and provide rich factual background.
            </p>
          {:else}
            <div class="detail-badge"><span class="badge-tag">Dialectical Debate</span> · Opposing views</div>
            <p class="detail-body">
              Synthesizes counter-arguments, critical questions, and alternative perspectives so the podcast hosts can debate nuances.
            </p>
          {/if}
        </div>
      </section>

      <section aria-labelledby="tray-h">
        <div class="sec-head">
          <h3 id="tray-h" class="mono"><Icon name="source" size={18} /> source tray</h3>
          <button class="link mono" onclick={() => resetSection(['source.max_sources', 'source.max_chars'])}>reset</button>
        </div>
        <div class="opt">
          <label class="lab mono" for="s-tray-max">max sources per episode</label>
          <input
            id="s-tray-max"
            class="mono text-in"
            type="number"
            min="2"
            max="50"
            step="1"
            value={values['source.max_sources'] ?? '10'}
            onchange={(e) => set('source.max_sources', e.currentTarget.value)}
          />
          <p class="help">at most this many sources in one episode (2 to 50, {trayMaxSources} effective right now).</p>
        </div>
        <div class="opt">
          <div class="ctl-row">
            <label class="lab mono" for="s-tray-chars">max source length</label>
            <span class="mono readout">{trayCharsAuto ? `auto · ${formatKChars(trayBudgetChars)} chars` : 'custom'}</span>
          </div>
          <div id="s-tray-chars" class="seg" role="radiogroup" aria-label="Max source length">
            <button
              type="button"
              role="radio"
              aria-label="Auto"
              aria-checked={trayCharsAuto}
              class:sel={trayCharsAuto}
              onclick={() => set('source.max_chars', 'auto')}
            >
              auto
            </button>
            <button
              type="button"
              role="radio"
              aria-label="Custom"
              aria-checked={!trayCharsAuto}
              class:sel={!trayCharsAuto}
              onclick={() => chooseTrayCharsCustom()}
            >
              custom
            </button>
          </div>
          {#if trayCharsAuto}
            <p class="help">auto · {formatKChars(trayBudgetChars)} chars from the script model. longer sources are condensed, not cut.</p>
          {:else}
            <label class="lab mono" for="s-tray-chars-custom">custom length (characters)</label>
            <input
              id="s-tray-chars-custom"
              class="mono text-in"
              type="number"
              min="10000"
              max="2000000"
              step="1000"
              value={values['source.max_chars'] ?? String(trayBudgetChars)}
              onchange={(e) => set('source.max_chars', e.currentTarget.value)}
            />
            <p class="help">10000 to 2000000 characters per source. longer sources are condensed, not cut.</p>
          {/if}
        </div>
      </section>

      <section aria-labelledby="watchlist-h">
        <div class="sec-head">
          <h3 id="watchlist-h" class="mono"><Icon name="rss" size={18} /> watchlist automation</h3>
          <button class="link mono" onclick={() => resetSection(['watchlist.render_mode'])}>reset</button>
        </div>
        <div class="opt">
          <label class="lab mono" for="s-wl-mode">rendering policy</label>
          <select
            id="s-wl-mode"
            class="mono"
            value={values['watchlist.render_mode'] ?? 'newest'}
            onchange={(e) => set('watchlist.render_mode', e.currentTarget.value)}
          >
            <option value="newest">newest only (1 per check)</option>
            <option value="catchup">catch up (up to 3 per check)</option>
          </select>
        </div>
        <p class="help">
          newest only prevents feed backlog from overwhelming your machine. older entries can be rendered on demand via check now.
        </p>
      </section>
    </div>

    <!-- SECTION 2: SCRIPT (the writing model first, then how it writes) -->
    <div id="sec-script" class="settings-group">
      <div class="group-title mono">
        <span class="group-kicker">// 02</span>
        <h2>script</h2>
      </div>

      <section aria-labelledby="llm-h">
        <div class="sec-head">
          <h3 id="llm-h" class="mono"><Icon name="brain" size={18} /> llm engine</h3>
          <button class="link mono" onclick={() => resetSection(['llm.engine', 'llm.backup_engine'])}>reset</button>
        </div>
        <div class="opt">
          <label class="lab mono" for="s-llm-engine">inference engine</label>
          <select
            id="s-llm-engine"
            class="mono"
            value={values['llm.engine'] ?? 'local'}
            onchange={(e) => set('llm.engine', e.currentTarget.value)}
          >
            <optgroup label="local · runs on this machine">
              <option value="local">Local model (your endpoint, VOZONDA_LLM_BASE)</option>
            </optgroup>
            <optgroup label="cloud · source text leaves this machine">
              <option value="kimi_nim">NVIDIA NIM (model below)</option>
              <option value="opencode">OpenCode (models below, via opencode CLI)</option>
              <option value="claude">Claude (Anthropic API)</option>
              <option value="custom">Custom OpenAI-compatible endpoint</option>
            </optgroup>
            <option value="none">none (no llm available)</option>
          </select>
          {#if llmEngine === 'kimi_nim' || llmEngine === 'opencode' || llmEngine === 'claude' || llmEngine === 'custom'}
            <p class="help" role="note">cloud: the source text of every episode is sent to this provider</p>
          {/if}
        </div>
        <div class="opt">
          <label class="lab mono" for="s-llm-backup">backup writer</label>
          <select
            id="s-llm-backup"
            class="mono"
            value={values['llm.backup_engine'] || 'none'}
            onchange={(e) => set('llm.backup_engine', e.currentTarget.value)}
          >
            <option value="none">none</option>
            <optgroup label="local · runs on this machine">
              <option value="local">Local model (your endpoint)</option>
            </optgroup>
            <optgroup label="cloud · source text leaves this machine">
              <option value="kimi_nim">NVIDIA NIM</option>
              <option value="opencode">OpenCode</option>
              <option value="claude">Claude (Anthropic API)</option>
              <option value="custom">Custom OpenAI-compatible endpoint</option>
            </optgroup>
          </select>
          <p class="help">takes over when the writer above fails (a cloud queue down, the local server stopped). a cloud backup sends the source text out only when it is used.</p>
        </div>
        {#if showLlmConfig}
          <div class="opt">
            <label class="lab mono" for="s-llm-api-key">api key</label>
            <input
              id="s-llm-api-key"
              class="mono text-in"
              type="password"
              placeholder="sk-ant-... (or set ANTHROPIC_API_KEY in .env)"
              value={llmApiKey}
              oninput={(e) => set('llm.api_key', e.currentTarget.value)}
            />
            <p class="help">API keys can also be stored securely in .env (ANTHROPIC_API_KEY)</p>
          </div>
          <div class="opt">
            <label class="lab mono" for="s-llm-model">model</label>
            <input
              id="s-llm-model"
              class="mono text-in"
              type="text"
              placeholder={llmEngine === 'claude' ? 'claude-model-id' : 'model-name'}
              value={llmCustomModel}
              oninput={(e) => set('llm.custom_model', e.currentTarget.value)}
            />
            <p class="help">custom model id for {llmEngine === 'claude' ? 'Claude API' : 'OpenAI-compatible endpoint'}</p>
          </div>
        {/if}
        {#if llmEngine === 'kimi_nim'}
          <div class="opt">
            <label class="lab mono" for="s-llm-nim-key">nvidia nim api key</label>
            <input
              id="s-llm-nim-key"
              class="mono text-in"
              type="password"
              placeholder="nvapi-... (or VOZONDA_NIM_API_KEY / secrets/nvidia_nim_api.key)"
              value={values['llm.nim_api_key'] ?? ''}
              onchange={(e) => set('llm.nim_api_key', e.currentTarget.value)}
            />
            <p class="help">key from build.nvidia.com (the key file or env var works too). The free developer key is for testing and prototyping only; production use needs an NVIDIA AI Enterprise licence.</p>
          </div>
        {/if}
        {#if llmEngine === 'kimi_nim' || values['llm.backup_engine'] === 'kimi_nim'}
          <div class="opt">
            <label class="lab mono" for="s-llm-nim-model">nvidia nim model</label>
            <input
              id="s-llm-nim-model"
              class="mono text-in"
              type="text"
              list="nim-models"
              placeholder="vendor/model, e.g. vendor/model-name"
              value={values['llm.nim_model'] ?? ''}
              onchange={(e) => set('llm.nim_model', e.currentTarget.value)}
            />
            <datalist id="nim-models">
              {#each llmModels['kimi_nim'] ?? [] as m (m)}<option value={m}></option>{/each}
            </datalist>
            <p class="help">{(llmModels['kimi_nim'] ?? []).length ? `${(llmModels['kimi_nim'] ?? []).length} models offered by NIM right now` : 'the list of offered models loads once a NIM key is set'}</p>
          </div>
        {/if}
        {#if llmEngine === 'opencode' || values['llm.backup_engine'] === 'opencode'}
          <div class="opt">
            <label class="lab mono" for="s-llm-opencode-models">opencode models</label>
            <input
              id="s-llm-opencode-models"
              class="mono text-in"
              type="text"
              placeholder="opencode/model-a, opencode/model-b"
              value={values['llm.opencode_models'] ?? ''}
              onchange={(e) => set('llm.opencode_models', e.currentTarget.value)}
            />
            <p class="help">tried in this order; the next one takes over when one fails. add from what opencode offers right now:</p>
            {#if (llmModels['opencode'] ?? []).length}
              <div class="model-chips">
                {#each llmModels['opencode'] as m (m)}
                  <button type="button" class="mono model-chip" onclick={() => addOpencodeModel(m)}>+ {m.replace(/^opencode\//, '')}</button>
                {/each}
              </div>
            {:else}
              <p class="help">no list yet: is the opencode CLI installed?</p>
            {/if}
          </div>
        {/if}
        {#if llmEngine === 'custom'}
          <div class="opt">
            <label class="lab mono" for="s-llm-custom-base">custom base url</label>
            <input
              id="s-llm-custom-base"
              class="mono text-in"
              type="text"
              placeholder="https://api.openai.com/v1"
              value={llmCustomBase}
              oninput={(e) => set('llm.custom_base', e.currentTarget.value)}
            />
          </div>
        {/if}
        <div class="engine-detail mono" role="region" aria-live="polite">
          {#if llmProbe && llmProbe.status === 'ok'}
            {#if llmProbe.location === 'cloud'}
              <div class="detail-badge"><span class="badge-tag">Cloud</span> · {llmProbe.badge ?? llmProbe.label}</div>
            {:else}
              <div class="detail-badge"><span class="badge-tag">Local GPU</span> · {llmProbe.badge ? llmProbe.badge.replace(/^Local GPU · /, '') : 'vLLM'}</div>
            {/if}
            <p class="detail-body">
              {llmProbe.summary || `${llmProbe.root || llmProbe.model_id} via your endpoint.`}
            </p>
            {#if llmProbe.best_for}
              <p class="detail-body note">
                Best for: {llmProbe.best_for}
              </p>
            {/if}
          {:else if llmEngine === 'local'}
            <div class="detail-badge"><span class="badge-tag">Local</span> · your endpoint</div>
            <p class="detail-body">
              Your own OpenAI-compatible endpoint from VOZONDA_LLM_BASE (Ollama, vLLM, LM Studio, llama.cpp).
            </p>
            <p class="detail-body note">
              Best for: private script writing on your own setup. No hardware, quantization or speed claims here: check your endpoint.
            </p>
          {:else if llmEngine === 'kimi_nim'}
            <div class="detail-badge"><span class="badge-tag">Cloud</span> · {llmProbe?.badge ?? 'NVIDIA NIM'}</div>
            <p class="detail-body">{llmProbe?.summary ?? 'A chat model on the NVIDIA NIM API.'}</p>
            <p class="detail-body note">{llmProbe?.note ?? 'Add an NVIDIA NIM key and a model below.'}</p>
          {:else if llmEngine === 'opencode'}
            <div class="detail-badge"><span class="badge-tag">Cloud</span> · {llmProbe?.badge ?? 'OpenCode'}</div>
            <p class="detail-body">{llmProbe?.summary ?? 'Models offered by OpenCode, through your opencode CLI.'}</p>
            <p class="detail-body note">{llmProbe?.note ?? 'Install the opencode CLI and pick models below.'}</p>
          {:else if llmEngine === 'claude'}
            <div class="detail-badge"><span class="badge-tag">Anthropic API</span> · Claude 3.7 Sonnet</div>
            <p class="detail-body">
              Frontier cloud model via Anthropic API. High fidelity script generation with extended thinking. Requires an active API key.
            </p>
            <p class="detail-body note">
              Best for: Maximum script quality when local models are insufficient. Pay-per-use pricing.
            </p>
          {:else if llmEngine === 'custom'}
            <div class="detail-badge"><span class="badge-tag">Custom Endpoint</span> · OpenAI-compatible</div>
            <p class="detail-body">
              Connect to any OpenAI-compatible inference endpoint. Configure the base URL and model ID below.
            </p>
            <p class="detail-body note">
              Best for: Connecting to third-party LLM providers or self-hosted endpoints with OpenAI API compatibility.
            </p>
          {:else}
            <div class="detail-badge"><span class="badge-tag">Disabled</span> · No LLM</div>
            <p class="detail-body">
              No local LLM engine is configured. Features that require LLM inference (research depth, script generation) will be unavailable.
            </p>
            <p class="detail-body note">
              Enable local to restore LLM capabilities.
            </p>
          {/if}
          <div class="llm-status" class:checking={llmStatus === 'checking'} class:ok={llmStatus === 'ok'} class:offline={llmStatus === 'offline'} class:unknown={llmStatus === 'unknown'}>
            <span class="status-dot"></span>
            <span class="status-text">
              {#if llmStatus === 'checking'}checking...
              {:else if llmStatus === 'ok'}reachable ({llmProbe?.root || llmProbe?.model_id || 'your endpoint'})
              {:else if llmStatus === 'offline'}offline
              {:else}status unknown
              {/if}
            </span>
          </div>
        </div>
      </section>

      <section class="style-section {selectedStyle ? 'g-' + categoryOfStyle(selectedStyle) : ''}" aria-labelledby="styles-h">
        <div class="sec-head">
          <h3 id="styles-h" class="mono"><Icon name="prompts" size={18} /> style personas & prompts</h3>
          <button class="link mono" onclick={() => resetSection([promptKey(promptMode)])}>reset</button>
        </div>
        <p class="help">
          redactional tonality, vocabulary and dialogue rules. select any persona to inspect its rules and edit its prompt directly.
        </p>
        {#each styleGroups as group (group.key)}
          <div class="style-group g-{group.key}">
            <span class="group-label mono" title="category">{group.label}</span>
            <div class="seg seg-wrap" role="radiogroup" aria-label="Style: {group.label}">
              {#each group.styles as s (s)}
                <button
                  type="button"
                  role="radio"
                  aria-checked={selectedStyle === s}
                  class:sel={selectedStyle === s}
                  onclick={() => {
                    selectedStyle = s
                    promptMode = s === 'balanced' ? 'script.balanced' : s
                  }}
                >{s.replace(/_/g, ' ')}</button>
              {/each}
            </div>
          </div>
        {/each}
        <div class="style-group g-solo">
          <span class="group-label mono">solo</span>
          <div class="seg" role="radiogroup" aria-label="Solo narration">
            <button
              type="button"
              role="radio"
              aria-checked={selectedStyle === 'narration'}
              class:sel={selectedStyle === 'narration'}
              onclick={() => {
                selectedStyle = 'narration'
                promptMode = 'script.narration'
              }}
            >narration · one narrator</button>
          </div>
        </div>

        {#if selectedStyle && selectedStyle !== 'narration'}
          {#key selectedStyle}
            <div class="styledoc-box" role="note">
              <Icon name={styleIcons[selectedStyle] ?? 'balanced'} size={27} />
              <p class="styledoc-text">
                {styleDocs[selectedStyle] ?? ''}
              </p>
            </div>
          {/key}
        {/if}

        <div class="opt" style="margin-top: var(--space-3);">
          <div class="ctl-row">
            <label class="lab mono" for="p-key">custom prompt</label>
            <span class="mono readout key-readout">{promptKey(promptMode)}</span>
          </div>
          <textarea
            id="p-key"
            class="mono prompt-box"
            rows="12"
            spellcheck="false"
            aria-label={`Custom prompt for ${promptMode}`}
            value={promptValue}
            oninput={(e) => set(promptKey(promptMode), e.currentTarget.value)}
          ></textarea>
        </div>
      </section>

      <section aria-labelledby="custom-styles-h">
        <div class="sec-head">
          <h3 id="custom-styles-h" class="mono"><Icon name="prompts" size={18} /> your styles</h3>
          {#if !showEditor}
            <button type="button" class="link mono" onclick={() => { editingStyle = null; showEditor = true }}>new style</button>
          {/if}
        </div>
        <p class="help">
          your own personas: pick a rhythm type and name the two roles. they appear in the style picker under custom.
        </p>
        {#if customError}
          <p class="mono help err" role="alert">{customError}</p>
        {/if}
        {#if customStyles.length === 0 && !showEditor}
          <p class="help">no custom style yet. create one with new style above.</p>
        {/if}
        {#each customStyles as s (s.id)}
          <div class="opt custom-row">
            <div class="ctl-row">
              <span class="lab mono custom-name">{s.name}</span>
              <span class="mono readout">{s.rhythm_type.replace(/_/g, ' ')}</span>
            </div>
            {#if s.doc}
              <p class="help">{s.doc}</p>
            {/if}
            <div class="custom-actions">
              <button
                type="button"
                class="link mono"
                onclick={() => { editingStyle = s; showEditor = true; confirmDeleteId = null }}
                aria-label={`edit style ${s.name}`}
              >edit</button>
              <button
                type="button"
                class="link mono"
                onclick={() => askDeleteStyle(s.id)}
                aria-label={`delete style ${s.name}`}
              >delete</button>
            </div>
            {#if confirmDeleteId === s.id}
              <div
                class="confirm-box"
                role="dialog"
                aria-modal="false"
                aria-labelledby={`confirm-del-${s.id}`}
                tabindex="-1"
                onkeydown={(e) => { if (e.key === 'Escape') confirmDeleteId = null }}
              >
                <p id={`confirm-del-${s.id}`} class="mono confirm-title">delete {s.name}?</p>
                <p class="help">episodes already made with it keep their audio; new episodes fall back to balanced.</p>
                <div class="confirm-actions">
                  <button type="button" class="probe-btn mono active" bind:this={confirmDeleteBtn} disabled={deleteBusy} onclick={() => void confirmDeleteStyle()}>delete style</button>
                  <button type="button" class="link mono" onclick={() => (confirmDeleteId = null)}>cancel</button>
                </div>
              </div>
            {/if}
          </div>
        {/each}
        {#if showEditor}
          <CustomStyleEditor
            editing={editingStyle}
            onclose={() => { showEditor = false; editingStyle = null }}
            onsaved={() => { showEditor = false; editingStyle = null; void loadCustomStyles() }}
          />
        {/if}
      </section>

      <section aria-labelledby="dialog-tuning-h">
        <div class="sec-head">
          <h3 id="dialog-tuning-h" class="mono"><Icon name="prompts" size={18} /> script & dialogue directives</h3>
          <button class="link mono" onclick={() => resetSection(['script.use_names', 'script.intro_hook', 'script.takeaways', 'script.review_default'])}>reset</button>
        </div>
        <div class="opt">
          <div class="ctl-row">
            <label class="lab mono" for="s-names">mention host names</label>
            <span class="mono readout">{values['script.use_names'] === '1' ? 'always' : values['script.use_names'] === '0' ? 'never' : 'natural'}</span>
          </div>
          <div id="s-names" class="seg" role="radiogroup" aria-label="Host names policy">
            <button
              type="button"
              role="radio"
              aria-checked={!values['script.use_names'] || values['script.use_names'] === 'auto'}
              class:sel={!values['script.use_names'] || values['script.use_names'] === 'auto'}
              onclick={() => set('script.use_names', 'auto')}
            >
              natural
            </button>
            <button
              type="button"
              role="radio"
              aria-checked={values['script.use_names'] === '1'}
              class:sel={values['script.use_names'] === '1'}
              onclick={() => set('script.use_names', '1')}
            >
              always
            </button>
            <button
              type="button"
              role="radio"
              aria-checked={values['script.use_names'] === '0'}
              class:sel={values['script.use_names'] === '0'}
              onclick={() => set('script.use_names', '0')}
            >
              never
            </button>
          </div>
          <p class="help">controls whether hosts address each other by name (e.g. "Good point, Alex") or converse directly without calling names.</p>
        </div>
        <div class="opt">
          <div class="ctl-row">
            <label class="lab mono" for="s-hook">cold open hook</label>
            <span class="mono readout">{values['script.intro_hook'] === '1' ? 'enabled' : 'disabled'}</span>
          </div>
          <div id="s-hook" class="seg" role="radiogroup" aria-label="Cold open hook">
            <button
              type="button"
              role="radio"
              aria-checked={values['script.intro_hook'] === '1'}
              class:sel={values['script.intro_hook'] === '1'}
              onclick={() => set('script.intro_hook', '1')}
            >
              on
            </button>
            <button
              type="button"
              role="radio"
              aria-checked={values['script.intro_hook'] !== '1'}
              class:sel={values['script.intro_hook'] !== '1'}
              onclick={() => set('script.intro_hook', '0')}
            >
              off
            </button>
          </div>
          <p class="help">starts Turn 1 immediately with the most surprising fact or punchy question without generic podcast greetings.</p>
        </div>
        <div class="opt">
          <div class="ctl-row">
            <label class="lab mono" for="s-takeaways">actionable wrap-up takeaways</label>
            <span class="mono readout">{values['script.takeaways'] === '1' ? 'enabled' : 'disabled'}</span>
          </div>
          <div id="s-takeaways" class="seg" role="radiogroup" aria-label="Actionable wrap-up takeaways">
            <button
              type="button"
              role="radio"
              aria-checked={values['script.takeaways'] === '1'}
              class:sel={values['script.takeaways'] === '1'}
              onclick={() => set('script.takeaways', '1')}
            >
              on
            </button>
            <button
              type="button"
              role="radio"
              aria-checked={values['script.takeaways'] !== '1'}
              class:sel={values['script.takeaways'] !== '1'}
              onclick={() => set('script.takeaways', '0')}
            >
              off
            </button>
          </div>
          <p class="help">ensures the final dialogue turns summarize concrete conclusions and takeaways from the story.</p>
        </div>
        <div class="opt">
          <div class="ctl-row">
            <label class="lab mono" for="s-review">default script review policy</label>
            <span class="mono readout">{values['script.review_default'] === '1' ? 'script to me first' : 'straight to audio'}</span>
          </div>
          <div id="s-review" class="seg" role="radiogroup" aria-label="Default script review policy">
            <button
              type="button"
              role="radio"
              aria-checked={values['script.review_default'] !== '1'}
              class:sel={values['script.review_default'] !== '1'}
              onclick={() => set('script.review_default', '0')}
            >
              straight to audio
            </button>
            <button
              type="button"
              role="radio"
              aria-checked={values['script.review_default'] === '1'}
              class:sel={values['script.review_default'] === '1'}
              onclick={() => set('script.review_default', '1')}
            >
              script to me first
            </button>
          </div>
          <p class="help">default preset for new episodes in the composer. straight to audio: script and audio are generated automatically in one continuous run. script to me first: the script and title are generated first for your review and editing; audio is voiced only after you approve.</p>
        </div>
      </section>
    </div>

    <!-- SECTION 3: VOICE (engine, pacing, music) -->
    <div id="sec-voice" class="settings-group">
      <div class="group-title mono">
        <span class="group-kicker">// 03</span>
        <h2>voice</h2>
      </div>

      <section aria-labelledby="engine-h">
        <div class="sec-head">
          <h3 id="engine-h" class="mono"><Icon name="voices" size={18} /> voice engine</h3>
          <button class="link mono" onclick={() => resetSection(['tts.engine'])}>reset</button>
        </div>
        <div class="opt">
          <label class="lab mono" for="s-engine">synthesis engine</label>
          <select
            id="s-engine"
            class="mono"
            value={values['tts.engine'] ?? 'qwen_tts'}
            onchange={(e) => set('tts.engine', e.currentTarget.value)}
          >
            {#each TTS_GROUPS as grp (grp.location)}
              {#if ttsOptions.some((e) => (e.location ?? 'local') === grp.location)}
                <optgroup label={grp.label}>
                  {#each ttsOptions.filter((e) => (e.location ?? 'local') === grp.location) as eng (eng.id)}
                    <option
                      value={eng.id}
                      disabled={!eng.installed}
                      title={!eng.installed ? (eng.ui_fix_hint ?? eng.fix) : (eng.commercial_use === false ? `${eng.license ?? ''} · non-commercial` : (eng.license ?? ''))}
                    >
                      {engineName(eng.label)}{eng.ui_badge ? ` · ${eng.ui_badge}` : ''}{eng.commercial_use === false ? ' · non-commercial' : ''}{!eng.installed ? ' · not installed' : ''}
                    </option>
                  {/each}
                </optgroup>
              {/if}
            {/each}
          </select>
          {#if selectedEngine}
            <p class="help">{selectedEngine.label}{selectedEngine.license ? ` · ${selectedEngine.license}` : ''}</p>
          {/if}
          {#if selectedEngine && !selectedEngine.installed}
            <p class="help" role="note">{selectedEngine.ui_fix_hint ?? selectedEngine.fix}</p>
          {/if}
          {#if selectedEngine && selectedEngine.commercial_use === false}
            <p class="help" role="note">{selectedEngine.license} · non-commercial</p>
          {/if}
        </div>
        <div class="engine-detail mono" role="region" aria-live="polite">
          {#if (values['tts.engine'] ?? 'qwen_tts') === 'voxtral'}
            <div class="detail-badge"><span class="badge-tag">EU Cloud API</span> · 0 MB VRAM · Emotional Realism</div>
            <p class="detail-body">
              Mistral Voxtral Neural Audio · 30+ European native accents (German, French, Spanish, Italian, Portuguese, English). Full expressive emotion steering: human breathing, dynamic laughter, natural pauses, and conversational tone.
            </p>
            <p class="detail-body note">
              Best for: NotebookLM-level dialogue acting, emotional laughter, and multi-European accents with zero local GPU load.
            </p>
          {:else if (values['tts.engine'] ?? 'qwen_tts') === 'qwen_tts'}
            <div class="detail-badge"><span class="badge-tag">Local GPU</span> · GB10 Neural Audio · Studio Clarity</div>
            <p class="detail-body">
              Qwen3-TTS 1.7B Custom Voice · 100% private, sovereign on-device inference. High fidelity 24 kHz studio speech synthesis.
            </p>
            <p class="detail-body note">
              Best for: 100% sovereign offline privacy, GB10 GPU acceleration, and broadcast 24 kHz studio clarity.
            </p>
          {:else if (values['tts.engine'] ?? 'qwen_tts') === 'kokoro'}
            <div class="detail-badge"><span class="badge-tag">Local ONNX</span> · 82M Expressive · 15-25x Realtime</div>
            <p class="detail-body">
              Kokoro-82M Neural Audio · Ultra-compact 82M params, 350 MB. Highly expressive American and British English voices: Bella, Sarah, Nicole, Sky, Adam, Michael, Eric, Emma, Isabella, George, Lewis.
            </p>
            <p class="detail-body note">
              Best for: Fast expressive dialogue, low VRAM synthesis, and American and British voice variety without cloud.
            </p>
          {:else if selectedEngine}
            <div class="detail-badge"><span class="badge-tag">{selectedEngine.ui_badge || 'engine'}</span> · {selectedEngine.license || 'unknown license'}{selectedEngine.commercial_use === false ? ' · non-commercial' : ''} · {selectedEngine.installed ? 'ready' : 'not installed'}</div>
            <p class="detail-body">
              {selectedEngine.label} · {selectedEngine.license ?? ''}{selectedEngine.commercial_use === false ? ' (non-commercial)' : ''}. {selectedEngine.installed ? '' : (selectedEngine.ui_fix_hint ?? selectedEngine.fix)}
            </p>
            {#if selectedEngine.commercial_use === false}
              <p class="detail-body note">
                non-commercial license · billing gated when enabled.
              </p>
            {:else}
              <p class="detail-body note">
                Best for: general synthesis via {selectedEngine.ui_badge || 'engine'}.
              </p>
            {/if}
          {:else}
            <div class="detail-badge"><span class="badge-tag">Local CPU</span> · Open Source ONNX · Lightweight</div>
            <p class="detail-body">
              Piper Neural Engine · Ultra-fast lightweight CPU synthesis. Multi-lingual open-source voice catalog (German, English, French, Spanish, Italian). Zero GPU load.
            </p>
            <p class="detail-body note">
              Best for: Silent, ultra-fast background rendering on CPU without competing for GPU VRAM.
            </p>
          {/if}
        </div>
      </section>

      <section aria-labelledby="delivery-h">
        <div class="sec-head">
          <h3 id="delivery-h" class="mono"><Icon name="pacing" size={18} /> pacing & timing</h3>
          <button class="link mono" onclick={() => resetSection(['voice.speed', 'voice.gap_ms'])}>reset</button>
        </div>
        <div class="opt">
          <div class="ctl-row">
            <label class="lab mono" for="s-speed">playback speed</label>
            <span class="mono readout">{speed.toFixed(2)}x</span>
          </div>
          <input
            id="s-speed"
            type="range"
            min="0.7"
            max="1.4"
            step="0.05"
            value={values['voice.speed']}
            oninput={(e) => set('voice.speed', e.currentTarget.value)}
          />
          <p class="help">master-stage tempo · 1.0 is natural pace</p>
        </div>
        <div class="opt">
          <div class="ctl-row">
            <label class="lab mono" for="s-gap">turn gap</label>
            <span class="mono readout">{values['voice.gap_ms']} ms</span>
          </div>
          <input
            id="s-gap"
            type="range"
            min="50"
            max="1200"
            step="10"
            value={values['voice.gap_ms']}
            oninput={(e) => set('voice.gap_ms', e.currentTarget.value)}
          />
          <p class="help">silence inserted between dialogue turns</p>
        </div>
      </section>

      <section aria-labelledby="music-h">
        <div class="sec-head">
          <h3 id="music-h" class="mono"><Icon name="music" size={18} /> music beds & jingles</h3>
          <button class="link mono" onclick={() => resetSection(['music.enabled', 'music.intro', 'music.outro', 'music.duck_db', 'music.style'])}>reset</button>
        </div>
        <div class="opt">
          <div class="ctl-row">
            <label class="lab mono" for="s-music-enable">music beds</label>
            <span class="mono readout">{values['music.enabled'] === '1' ? 'enabled' : 'disabled'}</span>
          </div>
          <div id="s-music-enable" class="seg" role="radiogroup" aria-label="Music beds master switch">
            <button
              type="button"
              role="radio"
              aria-checked={values['music.enabled'] === '1'}
              class:sel={values['music.enabled'] === '1'}
              onclick={() => set('music.enabled', '1')}
            >
              on
            </button>
            <button
              type="button"
              role="radio"
              aria-checked={values['music.enabled'] === '0'}
              class:sel={values['music.enabled'] === '0'}
              onclick={() => set('music.enabled', '0')}
            >
              off
            </button>
          </div>
          <p class="help">master switch for intro and outro musical jingle beds during audio mastering.</p>
        </div>
        {#if values['music.enabled'] === '1'}
          <div class="opt">
            <label class="lab mono" for="s-jingle-style">jingle harmonic palette</label>
            <select
              id="s-jingle-style"
              class="mono"
              value={values['music.style'] ?? 'auto'}
              onchange={(e) => set('music.style', e.currentTarget.value)}
            >
              <option value="auto">auto (matches episode style / template mood)</option>
              <option value="jazz_calm">jazz calm (warm electric piano & pads · classic, solo)</option>
              <option value="tech_pulse">tech pulse (rhythmic synth pulse · news briefing, tech)</option>
              <option value="dramatic_swell">dramatic swell (cinematic strings & deep chords · duel, drama)</option>
              <option value="lofi_chill">lofi chill (soft vinyl chords · asmr, meditation, night)</option>
              <option value="energetic_brass">energetic brass (bright energetic fanfare · sports, dude, hype)</option>
            </select>
            <p class="help">harmonic chord progression synthesized for intro/outro beds</p>
          </div>
          <div class="opt">
            <div class="ctl-row">
              <span class="lab mono">jingle selection</span>
            </div>
            <div class="jingle-toggles mono">
              <label class="toggle-label">
                <input
                  type="checkbox"
                  checked={values['music.intro'] !== '0'}
                  onchange={(e) => set('music.intro', e.currentTarget.checked ? '1' : '0')}
                />
                <span>intro jingle (starts full, ducks smoothly under dialogue)</span>
              </label>
              <label class="toggle-label">
                <input
                  type="checkbox"
                  checked={values['music.outro'] !== '0'}
                  onchange={(e) => set('music.outro', e.currentTarget.checked ? '1' : '0')}
                />
                <span>outro jingle (fades in under sign-off, swells at end)</span>
              </label>
            </div>
          </div>
          <div class="opt">
            <div class="ctl-row">
              <label class="lab mono" for="s-duck-db">dialogue ducking level</label>
              <span class="mono readout">{duckDb.toFixed(1)} dB</span>
            </div>
            <input
              id="s-duck-db"
              type="range"
              min="-30.0"
              max="-3.0"
              step="1.0"
              value={values['music.duck_db']}
              oninput={(e) => set('music.duck_db', e.currentTarget.value)}
            />
            <p class="help">broadcast standard is -12 dB. raised-cosine S-curve eliminates pumping.</p>
          </div>
          <div class="engine-detail mono" role="region" aria-live="polite">
            <div class="detail-badge"><span class="badge-tag">Audio Asset Discovery</span> · Procedural / Stems</div>
            <p class="detail-body">
              Plays built-in harmonic chord progressions (Cmaj9 / Fmaj7), or automatically uses custom audio files placed in <span class="mono">media/music/</span> (<span class="mono">intro.mp3</span>, <span class="mono">outro.mp3</span>).
            </p>
          </div>

          <div class="opt custom-music-opt">
            <div class="ctl-row">
              <label class="lab mono" for="s-custom-music">signature audio assets</label>
              {#if musicStatus?.intro?.active || musicStatus?.outro?.active}
                <button type="button" class="link mono" onclick={() => doResetMusic('all')}>reset to built-in</button>
              {/if}
            </div>

            <!-- Current tracks status & probe buttons -->
            <div class="music-status-rows mono">
              <div class="music-track-row">
                <span class="track-tag">intro:</span>
                <span class="track-desc">{musicStatus?.intro?.label ?? 'built-in harmonic jazz'} {musicStatus?.intro?.duration ? `(${musicStatus.intro.duration}s)` : ''}</span>
                <button
                  type="button"
                  class="probe-btn mono"
                  class:active={playingMusic === 'intro'}
                  onclick={() => togglePlayMusic('intro')}
                  aria-label="Probe intro music"
                >
                  <Icon name={playingMusic === 'intro' ? 'pausebars' : 'playtri'} size={13} />
                  <span>{playingMusic === 'intro' ? 'stop' : 'audition'}</span>
                </button>
              </div>

              <div class="music-track-row">
                <span class="track-tag">outro:</span>
                <span class="track-desc">{musicStatus?.outro?.label ?? 'built-in harmonic jazz'} {musicStatus?.outro?.duration ? `(${musicStatus.outro.duration}s)` : ''}</span>
                <button
                  type="button"
                  class="probe-btn mono"
                  class:active={playingMusic === 'outro'}
                  onclick={() => togglePlayMusic('outro')}
                  aria-label="Probe outro music"
                >
                  <Icon name={playingMusic === 'outro' ? 'pausebars' : 'playtri'} size={13} />
                  <span>{playingMusic === 'outro' ? 'stop' : 'audition'}</span>
                </button>
              </div>
            </div>

            <!-- Safe URL Import Box -->
            <div class="music-import-box">
              <div class="import-kind-row">
                <span class="lab mono">import as:</span>
                <div class="seg" role="radiogroup" aria-label="Import track destination">
                  <button
                    type="button"
                    role="radio"
                    aria-checked={musicImportKind === 'intro'}
                    class:sel={musicImportKind === 'intro'}
                    onclick={() => (musicImportKind = 'intro')}
                  >
                    intro
                  </button>
                  <button
                    type="button"
                    role="radio"
                    aria-checked={musicImportKind === 'outro'}
                    class:sel={musicImportKind === 'outro'}
                    onclick={() => (musicImportKind = 'outro')}
                  >
                    outro
                  </button>
                </div>
              </div>

              <div class="import-input-row">
                <input
                  id="s-custom-music"
                  type="url"
                  class="mono music-url-input"
                  placeholder="https://example.com/signature-jingle.mp3"
                  bind:value={musicImportUrl}
                  disabled={musicImportBusy}
                />
                <button
                  type="button"
                  class="import-btn mono"
                  disabled={musicImportBusy || !musicImportUrl.trim()}
                  onclick={doImportMusic}
                >
                  {musicImportBusy ? 'fetching...' : 'import URL'}
                </button>
              </div>

              {#if musicImportMsg}
                <p class="mono import-msg ok" role="status">// {musicImportMsg}</p>
              {/if}
              {#if musicImportError}
                <p class="mono import-msg err" role="alert">// error: {musicImportError}</p>
              {/if}
              <p class="help">
                safely imports MP3, WAV, or OGG via SSRF-hardened fetcher. Automatically normalized by ffmpeg to 44.1kHz stereo (max 120s).
              </p>
            </div>
          </div>
        {/if}
      </section>
    </div>

    <!-- SECTION 4: SHOWS & DISTRIBUTION (each show with its identity and reach; operator 2026-10-02) -->
    <div id="sec-shows" class="settings-group">
      <div class="group-title mono">
        <span class="group-kicker">// 04</span>
        <h2>shows & distribution</h2>
      </div>
      <p class="help group-help">each show with what it is and where it goes: a feed for podcast apps, nostr, both, or nothing public.</p>

      <section aria-labelledby="reach-h">
        <div class="sec-head">
          <h3 id="reach-h" class="mono"><Icon name="share" size={18} /> your shows</h3>
          <button type="button" class="link mono new-show-trigger" onclick={() => { creatingShow = !creatingShow; newShowError = '' }}>
            <Icon name={creatingShow ? 'close' : 'plus'} size={14} /> {creatingShow ? 'cancel' : 'new show'}
          </button>
        </div>
        {#if distError}
          <p class="mono help err" role="alert">{distError}</p>
        {/if}
        {#if creatingShow}
          <div class="opt show-reach new-show-card">
            <div class="ctl-row">
              <span class="lab mono show-name">// create new show</span>
            </div>
            <div class="show-fields">
              <label class="lab mono" for="new-show-name">name *</label>
              <input id="new-show-name" class="mono text-in" type="text" maxlength="80" placeholder="e.g. Weekly Tech Radar"
                bind:value={newShowName} disabled={newShowBusy} />
              <label class="lab mono" for="new-show-author">author</label>
              <input id="new-show-author" class="mono text-in" type="text" maxlength="80" placeholder="creator name"
                bind:value={newShowAuthor} disabled={newShowBusy} />
              <label class="lab mono" for="new-show-category">category</label>
              <input id="new-show-category" class="mono text-in" type="text" maxlength="60" placeholder="Technology"
                bind:value={newShowCategory} disabled={newShowBusy} />
            </div>
            {#if newShowError}
              <p class="mono help err" role="alert">// {newShowError}</p>
            {/if}
            <div class="new-show-actions">
              <button type="button" class="probe-btn mono active" disabled={newShowBusy || !newShowName.trim()} onclick={() => void doCreateShow()}>
                {newShowBusy ? 'creating...' : 'create show'}
              </button>
              <button type="button" class="link mono" disabled={newShowBusy} onclick={() => { creatingShow = false; newShowError = '' }}>
                cancel
              </button>
            </div>
          </div>
        {/if}
        {#if !dist && !distError}
          <p class="help">loading…</p>
        {:else if dist && distShows.length === 0}
          <p class="help">no show yet. click "new show" above or name one in the composer.</p>
        {/if}
        {#each distShows as show (show.slug)}
          {@const reach = reachOf(show)}
          {@const isPendingNostr = Boolean(confirmNostr && confirmNostr.show.slug === show.slug)}
          {@const activeReach = isPendingNostr && confirmNostr ? confirmNostr.reach : reach}
          <div class="opt show-reach">
            <div class="ctl-row">
              <span class="lab mono show-name">{show.name}</span>
              <div class="show-ctl-actions">
                <span class="mono readout">{REACHES.find((r) => r.id === activeReach)?.label}{isPendingNostr ? ' (pending)' : ''}</span>
                {#if !show.fixed}
                  <button type="button" class="link mono delete-show-trigger" onclick={() => (deleteShowAsk = show)} aria-label={`Delete ${show.name}`}>
                    <Icon name="trash" size={13} /> delete
                  </button>
                {/if}
              </div>
            </div>
            {#if show.fixed}
              <p class="help">the default show: every episode without a named show, in the master feed. name a show in the composer to give it its own reach and nostr key.</p>
              <div class="show-fields">
                <label class="lab mono" for="s-show-name">name</label>
                <input id="s-show-name" class="mono text-in" type="text" maxlength="80" placeholder="your show title"
                  value={values['show.name']} onchange={(e) => { set('show.name', e.currentTarget.value); void loadDistribution() }} />
                <label class="lab mono" for="s-show-author">author</label>
                <input id="s-show-author" class="mono text-in" type="text" maxlength="80" placeholder="creator name"
                  value={values['show.author']} onchange={(e) => set('show.author', e.currentTarget.value)} />
                <label class="lab mono" for="s-show-category">category</label>
                <input id="s-show-category" class="mono text-in" type="text" maxlength="60" placeholder="Technology"
                  value={values['show.category']} onchange={(e) => set('show.category', e.currentTarget.value)} />
                <label class="lab mono" for="s-show-desc">description</label>
                <textarea id="s-show-desc" class="mono text-in desc-ta" rows="3" maxlength="4000" spellcheck="false"
                  placeholder="what your show is about" value={values['show.description']}
                  onchange={(e) => set('show.description', e.currentTarget.value)}></textarea>
                <span class="lab mono">distribution</span>
                <div class="master-reach-row">
                  <div class="seg reach-seg" role="radiogroup" aria-label="Distribution of the default show">
                    {#each MASTER_REACHES as r (r.id)}
                      <button
                        type="button"
                        role="radio"
                        aria-checked={reach === r.id}
                        class:sel={reach === r.id}
                        disabled={reachBusy === show.slug}
                        onclick={() => void applyReach(show, r.id)}
                      >{r.label}</button>
                    {/each}
                  </div>
                </div>
                <p class="help reach-note">no nostr here: the default show has no nostr key of its own. name a show in the composer to publish it as nostr only or both.</p>
              </div>
              <p class="help">{MASTER_REACHES.find((r) => r.id === reach)?.help}</p>
              <p class="help">name and author also go into every mp3, the player and the share page; category and description are for podcast apps.</p>
            {:else}
              <div class="show-fields">
                <label class="lab mono" for={`s-${show.slug}-name`}>name</label>
                <input id={`s-${show.slug}-name`} class="mono text-in" type="text" maxlength="80" value={show.name}
                  onchange={(e) => saveShow(show, { name: e.currentTarget.value })} />
                <label class="lab mono" for={`s-${show.slug}-author`}>author</label>
                <input id={`s-${show.slug}-author`} class="mono text-in" type="text" maxlength="80" value={show.author ?? ''}
                  onchange={(e) => saveShow(show, { author: e.currentTarget.value })} />
                {#if show.rss === '1'}
                  <label class="lab mono" for={`s-${show.slug}-category`}>category</label>
                  <input id={`s-${show.slug}-category`} class="mono text-in" type="text" maxlength="60" placeholder="Technology"
                    value={show.category ?? ''} onchange={(e) => saveShow(show, { category: e.currentTarget.value })} />
                {/if}
                <span class="lab mono">distribution</span>
                <div class="seg reach-seg" role="radiogroup" aria-label={`Distribution of ${show.name}`}>
                  {#each REACHES as r (r.id)}
                    <button
                      type="button"
                      role="radio"
                      aria-checked={activeReach === r.id}
                      class:sel={activeReach === r.id && !isPendingNostr}
                      class:pending={isPendingNostr && confirmNostr?.reach === r.id}
                      disabled={reachBusy === show.slug}
                      onclick={() => chooseReach(show, r.id)}
                    >{r.label}</button>
                  {/each}
                </div>
              </div>
              <p class="help">{REACHES.find((r) => r.id === activeReach)?.help}</p>
            {/if}

            {#if deleteShowAsk?.slug === show.slug}
              <div
                class="confirm-box delete-confirm-box"
                role="dialog"
                aria-modal="false"
                aria-labelledby={`confirm-del-show-${show.slug}`}
                tabindex="-1"
                onkeydown={(e) => { if (e.key === 'Escape') deleteShowAsk = null }}
              >
                <p id={`confirm-del-show-${show.slug}`} class="mono confirm-title">delete {show.name}?</p>
                <p class="help">this removes the show definition and its feed from settings. past episodes keep their audio.</p>
                <div class="confirm-actions">
                  <button type="button" class="probe-btn mono active danger" disabled={deleteShowBusy} onclick={() => void confirmDeleteShow()}>
                    {deleteShowBusy ? 'deleting...' : 'delete permanently'}
                  </button>
                  <button type="button" class="link mono" disabled={deleteShowBusy} onclick={() => (deleteShowAsk = null)}>cancel</button>
                </div>
              </div>
            {/if}

            {#if confirmNostr?.show.slug === show.slug}
              <div
                class="confirm-box"
                role="dialog"
                aria-modal="false"
                aria-labelledby={`confirm-h-${show.slug}`}
                tabindex="-1"
                onkeydown={(e) => { if (e.key === 'Escape') confirmNostr = null }}
              >
                <p id={`confirm-h-${show.slug}`} class="mono confirm-title">publish {show.name} on nostr?</p>
                <p class="help">every new episode becomes public on nostr relays and blossom servers. removing it later is best effort: other servers may keep copies. publish only what you may share.</p>
                <div class="confirm-actions">
                  <button type="button" class="probe-btn mono active" bind:this={confirmBtn} onclick={confirmPublish}>publish publicly</button>
                  <button type="button" class="link mono" onclick={() => (confirmNostr = null)}>cancel</button>
                </div>
              </div>
            {/if}

            {#if show.feed_url}
              <div class="kv mono">
                <span class="kv-key">rss feed</span>
                <code class="kv-val">{show.feed_url}</code>
                <button type="button" class="link mono" onclick={() => copyText(`feed-${show.slug}`, show.feed_url ?? '')} aria-label={`Copy the feed URL of ${show.name}`}>
                  <Icon name={copiedKey === `feed-${show.slug}` ? 'check' : 'copy'} size={13} /> {copiedKey === `feed-${show.slug}` ? 'copied' : 'copy'}
                </button>
              </div>
              {#if dist?.feed_private}
                <p class="help">private feed: the link carries its key, so anyone who has the link can listen. keep it on your own devices.</p>
              {/if}
            {/if}

            {#if !show.fixed && show.nostr === '1'}
              {@const ns = nostrStatus[show.slug]}
              <div class="kv mono">
                <span class="kv-key">nostr</span>
                {#if ns?.npub}
                  <code class="kv-val">{ns.npub}</code>
                  <button type="button" class="link mono" onclick={() => copyText(`npub-${show.slug}`, ns.npub ?? '')} aria-label={`Copy the npub of ${show.name}`}>
                    <Icon name={copiedKey === `npub-${show.slug}` ? 'check' : 'copy'} size={13} /> {copiedKey === `npub-${show.slug}` ? 'copied' : 'copy'}
                  </button>
                {:else}
                  <span class="kv-val help">the show's key is created with its first published episode.</span>
                {/if}
              </div>
              {#if ns?.npub}
                {#if nsecShown[show.slug]}
                  <div class="confirm-box">
                    <p class="mono confirm-title">secret key of {show.name}</p>
                    <code class="kv-val secret">{nsecShown[show.slug]}</code>
                    <p class="help">store it in your password manager now. it is shown this once; whoever has it can publish as this show.</p>
                    <div class="confirm-actions">
                      <button type="button" class="link mono" onclick={() => copyText(`nsec-${show.slug}`, nsecShown[show.slug] ?? '')}>
                        <Icon name={copiedKey === `nsec-${show.slug}` ? 'check' : 'copy'} size={13} /> {copiedKey === `nsec-${show.slug}` ? 'copied' : 'copy'}
                      </button>
                      <button type="button" class="link mono" onclick={() => { const n = { ...nsecShown }; delete n[show.slug]; nsecShown = n }}>done, hide it</button>
                    </div>
                  </div>
                {:else if nsecAsk === show.slug}
                  <div class="confirm-box" role="dialog" aria-modal="false" aria-label="Show the secret key" tabindex="-1"
                    onkeydown={(e) => { if (e.key === 'Escape') nsecAsk = null }}>
                    <p class="help">the secret key (nsec) controls this show on nostr. show it once to back it up?</p>
                    <div class="confirm-actions">
                      <button type="button" class="probe-btn mono" onclick={() => revealNsec(show.slug)}>show it once</button>
                      <button type="button" class="link mono" onclick={() => (nsecAsk = null)}>cancel</button>
                    </div>
                  </div>
                {:else}
                  <button type="button" class="link mono key-link" onclick={() => (nsecAsk = show.slug)}>
                    <Icon name="key" size={13} /> back up the key
                  </button>
                {/if}
              {/if}
            {/if}
          </div>
        {/each}
      </section>

      <section aria-labelledby="v4v-h">
        <div class="sec-head">
          <h3 id="v4v-h" class="mono"><Icon name="v4v" size={18} /> value for value (v4v)</h3>
          <button class="link mono" onclick={() => resetSection(['feed.creator.address', 'feed.creator.split', 'feed.source.address', 'feed.source.split', 'feed.app.address', 'feed.app.split'])}>reset</button>
        </div>

        <!-- Single unified multi-recipient breakdown bar -->
        <div class="opt v4v-breakdown-card">
          <div class="ctl-row">
            <label class="lab mono" for="v4v-breakdown">podcasting 2.0 value breakdown</label>
            <span class="mono readout">{creatorSplit}% creator · {sourceSplit}% source · {appSplit}% app</span>
          </div>
          <div id="v4v-breakdown" class="split-bar-wrap" aria-label="Value split breakdown bar">
            <div class="split-bar-creator" style="width: {creatorSplit}%" title="Creator {creatorSplit}%"></div>
            <div class="split-bar-source" style="width: {sourceSplit}%" title="Source {sourceSplit}%"></div>
            <div class="split-bar-app" style="width: {appSplit}%" title="App {appSplit}%"></div>
          </div>
          <div class="split-presets mono">
            <button type="button" class="preset-btn" class:active={creatorSplit === 70 && sourceSplit === 20 && appSplit === 10} onclick={() => applySplitPreset(70, 20, 10)}>70/20/10 (trio split)</button>
            <button type="button" class="preset-btn" class:active={creatorSplit === 50 && sourceSplit === 0 && appSplit === 50} onclick={() => applySplitPreset(50, 0, 50)}>50/50 (creator+app)</button>
            <button type="button" class="preset-btn" class:active={creatorSplit === 34 && sourceSplit === 33 && appSplit === 33} onclick={() => applySplitPreset(34, 33, 33)}>34/33/33 (equal)</button>
          </div>
          <p class="help">multi-recipient value split · Podcasting 2.0 standard</p>
        </div>

        <!-- Recipient 1: Creator -->
        <div class="v4v-recipient-card">
          <div class="v4v-card-head">
            <label class="v4v-card-title mono" for="s-creator">1. your lightning address (creator)</label>
            <div class="split-pct-box mono">
              <input
                id="s-creator-split"
                class="pct-in mono"
                type="number"
                min="0"
                max="100"
                value={creatorSplit}
                oninput={(e) => updateSplit('creator', e.currentTarget.value)}
                aria-label="Creator split percentage"
              />
              <span class="pct-unit">%</span>
            </div>
          </div>
          <input
            id="s-creator"
            class="mono text-in v4v-input"
            type="text"
            placeholder="cipherfox@rizful.com"
            value={values['feed.creator.address']}
            onchange={(e) => set('feed.creator.address', e.currentTarget.value)}
          />
          <p class="help v4v-help">primary producer receiving value splits in podcast:value and making-of</p>
        </div>

        <!-- Recipient 2: Source Author -->
        <div class="v4v-recipient-card">
          <div class="v4v-card-head">
            <label class="v4v-card-title mono" for="s-source">2. original source lightning address (author)</label>
            <div class="split-pct-box mono">
              <input
                id="s-source-split"
                class="pct-in mono"
                type="number"
                min="0"
                max="100"
                value={sourceSplit}
                oninput={(e) => updateSplit('source', e.currentTarget.value)}
                aria-label="Source author split percentage"
              />
              <span class="pct-unit">%</span>
            </div>
          </div>
          <input
            id="s-source"
            class="mono text-in v4v-input"
            type="text"
            placeholder="author@nostr.net (or auto-resolved from Nostr/RSS)"
            value={values['feed.source.address']}
            onchange={(e) => set('feed.source.address', e.currentTarget.value)}
          />
          <p class="help v4v-help">honors original content creators · empty = share rolls into creator</p>
        </div>

        <!-- Recipient 3: App / Node -->
        <div class="v4v-recipient-card locked">
          <div class="v4v-card-head">
            <div class="v4v-title-wrap">
              <label class="v4v-card-title mono" for="s-app">3. app / node lightning address (vozonda)</label>
              <span class="v4v-badge-locked mono"><Icon name="lock" size={12} /> fixed host node</span>
            </div>
            <div class="split-pct-box mono">
              <input
                id="s-app-split"
                class="pct-in mono"
                type="number"
                min="0"
                max="100"
                value={appSplit}
                oninput={(e) => updateSplit('app', e.currentTarget.value)}
                aria-label="App split percentage"
              />
              <span class="pct-unit">%</span>
            </div>
          </div>
          <input
            id="s-app"
            class="mono text-in v4v-input readonly-input"
            type="text"
            value={values['feed.app.address'] || 'vozonda@rizful.com'}
            disabled
            readonly
            aria-readonly="true"
          />
          <p class="help v4v-help">
            goes to the open-source project that builds this app · set its split to 0 to opt out
          </p>
        </div>

        <!-- Feed URL Card -->
        <div class="v4v-recipient-card">
          <div class="ctl-row">
            <span class="v4v-card-title mono" id="feed-url-lab">master podcast feed</span>
            <button class="link mono" onclick={() => void copyFeed()} aria-describedby="feed-url-lab">{copiedFeed ? 'copied!' : 'copy'}</button>
          </div>
          <span class="mono feed-url" title={feedXmlUrl}>{feedXmlUrl}</span>
          <p class="help v4v-help">contains all manual episodes and automated watchlists · point Apple Podcasts, Pocket Casts, or Fountain at this URL</p>
        </div>
      </section>

      <section aria-labelledby="disclosure-h">
        <div class="sec-head">
          <h3 id="disclosure-h" class="mono"><Icon name="rss" size={18} /> ai disclosure</h3>
          <button class="link mono" onclick={() => resetSection(['disclosure.ai_label'])}>reset</button>
        </div>
        <div class="opt">
          <div class="ctl-row">
            <label class="lab mono" for="s-disclosure">ai-generated label in feed, page and ID3</label>
            <span class="mono readout">{values['disclosure.ai_label'] === '1' ? 'enabled' : 'disabled'}</span>
          </div>
          <div id="s-disclosure" class="seg" role="radiogroup" aria-label="AI-generated disclosure">
            <button
              type="button"
              role="radio"
              aria-checked={values['disclosure.ai_label'] === '1'}
              class:sel={values['disclosure.ai_label'] === '1'}
              onclick={() => set('disclosure.ai_label', '1')}
            >
              on
            </button>
            <button
              type="button"
              role="radio"
              aria-checked={values['disclosure.ai_label'] === '0'}
              class:sel={values['disclosure.ai_label'] === '0'}
              onclick={() => set('disclosure.ai_label', '0')}
            >
              off
            </button>
          </div>
          <p class="help">appends an "AI-generated: script by X, voices by Y." line to the rss feed, episode page and mp3 ID3 tags.</p>
        </div>
      </section>

      <section aria-labelledby="address-h">
        <div class="sec-head">
          <h3 id="address-h" class="mono"><Icon name="link" size={18} /> address for other devices</h3>
        </div>
        {#if dist}
          <AddressCard address={dist.address} onchange={loadDistribution} />
        {/if}
        {#if anyFeed && dist}
          <div class="opt">
            <span class="lab mono">list your feed in podcast apps</span>
            <p class="help">copy a feed url from above and add it once in each directory:</p>
            <ul class="dir-links mono">
              <li><a href={dist.directory_help.apple_podcasts_connect} target="_blank" rel="noreferrer">apple podcasts connect</a></li>
              <li><a href={dist.directory_help.spotify_for_creators} target="_blank" rel="noreferrer">spotify for creators</a></li>
              <li><a href={dist.directory_help.podcast_index} target="_blank" rel="noreferrer">podcast index</a> <span class="help">(feeds apps like fountain, podverse, antennapod search)</span></li>
            </ul>
          </div>
        {/if}
      </section>

      <section aria-labelledby="dist-defaults-h">
        <div class="sec-head">
          <h3 id="dist-defaults-h" class="mono"><Icon name="sliders" size={18} /> defaults for new shows</h3>
          <button class="link mono" onclick={() => resetSection(['distribution.rss_default', 'nostr.publish_default'])}>reset</button>
        </div>
        <p class="help">a new show starts with these; existing shows keep their own reach.</p>
        {#each [{ key: 'distribution.rss_default', label: 'rss feed for podcast apps' }, { key: 'nostr.publish_default', label: 'publish on nostr' }] as d (d.key)}
          {@const on = (values[d.key] ?? defaults[d.key]) === '1'}
          <div class="opt">
            <div class="ctl-row">
              <label class="lab mono" for={`s-dist-${d.key.replace(/\./g, '-')}`}>{d.label}</label>
              <span class="mono readout">{on ? 'on' : 'off'}</span>
            </div>
            <div id={`s-dist-${d.key.replace(/\./g, '-')}`} class="seg" role="radiogroup" aria-label={`${d.label} for new shows`}>
              <button type="button" role="radio" aria-checked={on} class:sel={on} onclick={() => set(d.key, '1')}>on</button>
              <button type="button" role="radio" aria-checked={!on} class:sel={!on} onclick={() => set(d.key, '0')}>off</button>
            </div>
          </div>
        {/each}
      </section>

      <section aria-labelledby="servers-h">
        <div class="sec-head">
          <h3 id="servers-h" class="mono"><Icon name="radio" size={18} /> nostr relays & blossom servers</h3>
          <button class="link mono" onclick={() => { resetSection(['nostr.relays', 'nostr.blossom_servers']); relayError = ''; blossomError = '' }}>reset</button>
        </div>
        <div class="opt">
          <label class="lab mono" for="s-relays">relays (episodes and show info)</label>
          <textarea id="s-relays" class="mono text-in list-ta" rows="3" spellcheck="false"
            value={asLines(values['nostr.relays'] ?? defaults['nostr.relays'])}
            oninput={(e) => setList('nostr.relays', e.currentTarget.value, 'wss://')}></textarea>
          {#if relayError}<p class="mono help err" role="alert">{relayError}</p>{/if}
          <p class="help">one per line, each starting with wss://.</p>
        </div>
        <div class="opt">
          <label class="lab mono" for="s-blossom">blossom servers (audio, transcript, chapters)</label>
          <textarea id="s-blossom" class="mono text-in list-ta" rows="3" spellcheck="false"
            value={asLines(values['nostr.blossom_servers'] ?? defaults['nostr.blossom_servers'])}
            oninput={(e) => setList('nostr.blossom_servers', e.currentTarget.value, 'https://')}></textarea>
          {#if blossomError}<p class="mono help err" role="alert">{blossomError}</p>{/if}
          <p class="help">one per line, each starting with https://. the first that accepts the file keeps it, the others mirror it. free servers keep files without a guarantee; the defaults all take episodes of an hour.</p>
        </div>
      </section>
    </div>

    <!-- SECTION 5: PLAYER (how episodes play and read) -->
    <div id="sec-player" class="settings-group">
      <div class="group-title mono">
        <span class="group-kicker">// 05</span>
        <h2>player</h2>
      </div>

      <section aria-labelledby="player-defaults-h">
        <div class="sec-head">
          <h3 id="player-defaults-h" class="mono"><Icon name="playtri" size={18} /> player & reader defaults</h3>
          <button class="link mono" onclick={() => resetSection(['player.default_speed', 'player.default_text_size', 'player.karaoke', 'player.chapters', 'player.autoscroll', 'player.boost_placement'])}>reset</button>
        </div>

        <div class="opt">
          <div class="ctl-row">
            <label class="lab mono" for="s-player-speed">default player speed</label>
            <span class="mono readout">{values['player.default_speed'] ?? '1.0'}x</span>
          </div>
          <div id="s-player-speed" class="seg" role="radiogroup" aria-label="Default player speed">
            {#each ['0.8', '1.0', '1.25', '1.5', '2.0'] as spd}
              <button
                type="button"
                role="radio"
                aria-checked={(values['player.default_speed'] ?? '1.0') === spd}
                class:sel={(values['player.default_speed'] ?? '1.0') === spd}
                onclick={() => set('player.default_speed', spd)}
              >
                {spd}x
              </button>
            {/each}
          </div>
          <p class="help">web player playback speed, independent of tts synthesis rate.</p>
        </div>

        <div class="opt">
          <div class="ctl-row">
            <label class="lab mono" for="s-text-size">default text size</label>
            <span class="mono readout">{values['player.default_text_size'] ?? 'normal'}</span>
          </div>
          <div id="s-text-size" class="seg" role="radiogroup" aria-label="Default transcript text size">
            {#each ['compact', 'normal', 'large'] as sz}
              <button
                type="button"
                role="radio"
                aria-checked={(values['player.default_text_size'] ?? 'normal') === sz}
                class:sel={(values['player.default_text_size'] ?? 'normal') === sz}
                onclick={() => set('player.default_text_size', sz)}
              >
                {sz}
              </button>
            {/each}
          </div>
          <p class="help">transcript dialogue font size and vertical reading rhythm.</p>
        </div>

        <div class="opt">
          <div class="ctl-row">
            <label class="lab mono" for="s-karaoke">karaoke highlighting</label>
            <span class="mono readout">{(values['player.karaoke'] ?? '1') === '1' ? 'on' : 'off'}</span>
          </div>
          <div id="s-karaoke" class="seg" role="radiogroup" aria-label="Karaoke word highlighting default">
            <button
              type="button"
              role="radio"
              aria-checked={(values['player.karaoke'] ?? '1') === '1'}
              class:sel={(values['player.karaoke'] ?? '1') === '1'}
              onclick={() => set('player.karaoke', '1')}
            >
              on
            </button>
            <button
              type="button"
              role="radio"
              aria-checked={(values['player.karaoke'] ?? '1') === '0'}
              class:sel={(values['player.karaoke'] ?? '1') === '0'}
              onclick={() => set('player.karaoke', '0')}
            >
              off
            </button>
          </div>
          <p class="help">word-by-word synchronized highlighting during audio playback.</p>
        </div>

        <div class="opt">
          <div class="ctl-row">
            <label class="lab mono" for="s-autoscroll">transcript autoscroll</label>
            <span class="mono readout">{values['player.autoscroll'] ?? 'follow'}</span>
          </div>
          <div id="s-autoscroll" class="seg" role="radiogroup" aria-label="Transcript autoscroll mode">
            <button
              type="button"
              role="radio"
              aria-checked={(values['player.autoscroll'] ?? 'follow') === 'follow'}
              class:sel={(values['player.autoscroll'] ?? 'follow') === 'follow'}
              onclick={() => set('player.autoscroll', 'follow')}
            >
              follow
            </button>
            <button
              type="button"
              role="radio"
              aria-checked={(values['player.autoscroll'] ?? 'follow') === 'free'}
              class:sel={(values['player.autoscroll'] ?? 'follow') === 'free'}
              onclick={() => set('player.autoscroll', 'free')}
            >
              free
            </button>
          </div>
          <p class="help">keep active spoken turn smoothly centered in viewport.</p>
        </div>

        <div class="opt">
          <div class="ctl-row">
            <label class="lab mono" for="s-chapters">chapter section breaks</label>
            <span class="mono readout">{(values['player.chapters'] ?? '0') === '1' ? 'on' : 'off'}</span>
          </div>
          <div id="s-chapters" class="seg" role="radiogroup" aria-label="Chapter section breaks in transcript">
            <button
              type="button"
              role="radio"
              aria-checked={(values['player.chapters'] ?? '0') === '1'}
              class:sel={(values['player.chapters'] ?? '0') === '1'}
              onclick={() => set('player.chapters', '1')}
            >
              on
            </button>
            <button
              type="button"
              role="radio"
              aria-checked={(values['player.chapters'] ?? '0') === '0'}
              class:sel={(values['player.chapters'] ?? '0') === '0'}
              onclick={() => set('player.chapters', '0')}
            >
              off
            </button>
          </div>
          <p class="help">render chapter headlines and thematic boundaries inline in dialogue.</p>
        </div>

        <div class="opt">
          <div class="ctl-row">
            <label class="lab mono" for="s-boost-placement">boost button placement</label>
            <span class="mono readout">{(values['player.boost_placement'] ?? 'meta') === 'meta' ? 'date header (+100 sats)' : 'bottom strip'}</span>
          </div>
          <div id="s-boost-placement" class="seg" role="radiogroup" aria-label="Boost button placement A/B variant">
            <button
              type="button"
              role="radio"
              aria-checked={(values['player.boost_placement'] ?? 'meta') === 'meta'}
              class:sel={(values['player.boost_placement'] ?? 'meta') === 'meta'}
              onclick={() => set('player.boost_placement', 'meta')}
            >
              date header (+100 sats)
            </button>
            <button
              type="button"
              role="radio"
              aria-checked={(values['player.boost_placement'] ?? 'meta') === 'strip'}
              class:sel={(values['player.boost_placement'] ?? 'meta') === 'strip'}
              onclick={() => set('player.boost_placement', 'strip')}
            >
              bottom strip
            </button>
          </div>
          <p class="help">choose eye-level placement in episode meta row or classical strip below player.</p>
        </div>
      </section>
    </div>

    <!-- SECTION 6: SYSTEM & STORAGE -->
    <div id="sec-system" class="settings-group">
      <div class="group-title mono">
        <span class="group-kicker">// 06</span>
        <h2>system & storage</h2>
      </div>

      <section aria-labelledby="storage-h">
        <div class="sec-head">
          <h3 id="storage-h" class="mono"><Icon name="storage" size={18} /> audio storage</h3>
          {#if storageStats}
            <span class="mono readout">{formatBytes(storageStats.total_bytes)}</span>
          {/if}
        </div>
        <p class="help">
          all generated audio stays on this device. episodes older than 360 days are auto-pruned to keep storage lean. transcripts, scripts and metadata are never deleted.
        </p>
        {#if storageStats}
          <p class="mono readout engine-line">
            {storageStats.audio_files} audio files · {formatBytes(storageStats.total_bytes)} total · {storageStats.prunable_files} older than 360 days
          </p>
        {/if}
        <div class="opt">
          <button
            type="button"
            class="link mono"
            disabled={purging}
            onclick={() => void handlePurge()}
          >
            {purging ? 'cleaning up…' : 'clean up audio > 360 days'}
          </button>
          {#if purgeMsg}
            <p class="mono save-note ok" role="status" aria-live="polite">
              {purgeMsg}
            </p>
          {/if}
        </div>
      </section>

      <section aria-labelledby="telemetry-h">
        <h3 id="telemetry-h" class="mono"><Icon name="engine" size={18} /> runtime & providers</h3>
        <p class="help">
          active pipeline configuration and installed speech/language backends.
        </p>
        {#if meta?.runtime}
          <p class="mono readout engine-line" title="runtime engines">active: {meta.runtime.tts_engine} · llm: {meta.runtime.llm}{meta.version ? ` · v${meta.version}` : ''}</p>
        {/if}
        {#if meta}
          <p class="mono readout engine-line">
            {meta.timbres.length} voices · {meta.styles.length} styles · {meta.languages ? Object.keys(meta.languages).length : 10} languages
          </p>
        {/if}
        <ProviderStrip {providers} />
      </section>

      <section aria-labelledby="plugins-h">
        <div class="sec-head">
          <h3 id="plugins-h" class="mono"><Icon name="layers" size={18} /> plugins</h3>
          <button type="button" class="mono plugin-drawer-btn" onclick={() => (pluginsOpen = true)} aria-haspopup="dialog" aria-expanded={pluginsOpen}>
            <Icon name="sliders" size={13} /> manage plugins
          </button>
        </div>
        <p class="help">runtime-toggle pipeline modules. audio filters, ingestors, and syndication stay modular.</p>
      </section>
    </div>
  {/if}
  <PluginsDrawer open={pluginsOpen} onClose={() => (pluginsOpen = false)} />
</div>

<style>
  .settings-screen {
    /* page width comes from main (--content-max-width), like every page */
    display: grid;
    gap: var(--space-4);
  }

  .settings-head {
    display: flex;
    align-items: baseline;
    gap: var(--space-3);
    flex-wrap: wrap;
  }

  .settings-nav {
    display: flex;
    align-items: center;
    gap: var(--space-2);
    flex-wrap: wrap;
    padding: var(--space-2) 0;
    border-bottom: 1px solid var(--line);
    margin-bottom: var(--space-3);
    position: sticky;
    top: 0;
    background: var(--paper);
    z-index: 10;
  }

  .nav-pill {
    display: inline-flex;
    align-items: center;
    gap: var(--space-2);
    background: color-mix(in srgb, var(--ink) 4%, var(--paper));
    border: 1px solid color-mix(in srgb, var(--ink) 16%, var(--line));
    border-radius: var(--radius);
    color: var(--ink);
    padding: var(--space-2) var(--space-3);
    min-height: 42px;
    font-size: var(--ui-size);
    font-family: var(--font-mono);
    font-weight: 500;
    cursor: pointer;
    text-transform: lowercase;
    box-shadow: 0 1px 2px rgba(0, 0, 0, 0.04);
    transition: all var(--dur-fast) ease-out;
  }

  .nav-pill:hover:not(.active) {
    color: var(--ink);
    border-color: var(--ink);
    background: color-mix(in srgb, var(--ink) 8%, var(--paper));
    box-shadow: 0 1px 3px rgba(0, 0, 0, 0.08);
  }

  .nav-pill.active {
    color: var(--ink);
    border-color: var(--green);
    background: color-mix(in srgb, var(--green) 12%, var(--paper));
    font-weight: 600;
    box-shadow: 0 2px 4px rgba(0, 0, 0, 0.09);
  }

  .nav-pill.active:hover {
    color: var(--ink);
    border-color: var(--green);
    background: color-mix(in srgb, var(--green) 20%, var(--paper));
  }

  .nav-pill:focus-visible {
    outline: 2px solid var(--green);
    outline-offset: 2px;
  }

  .settings-group {
    display: grid;
    gap: var(--space-4);
    margin-bottom: var(--space-6);
    scroll-margin-top: 76px;
  }

  .group-title {
    display: flex;
    align-items: baseline;
    gap: var(--space-2);
    border-bottom: 1.5px solid color-mix(in srgb, var(--green) 35%, var(--line));
    padding-bottom: var(--space-3);
    margin-top: var(--space-5);
    margin-bottom: var(--space-3);
  }

  .group-kicker {
    color: var(--green);
    font-size: var(--ui-size);
    font-weight: 700;
    letter-spacing: 0.05em;
  }

  .group-title h2 {
    font-size: var(--ui-size);
    font-weight: 700;
    text-transform: uppercase;
    letter-spacing: 0.06em;
    margin: 0;
    color: var(--ink);
  }

  .sec-head {
    display: flex;
    align-items: center;
    justify-content: space-between;
    gap: var(--space-3);
  }

  .sec-head .link {
    flex: none;
  }

  .seg {
    display: inline-flex;
    border: 1px solid var(--line);
    border-radius: var(--radius);
    overflow: hidden;
    width: fit-content;
  }

  .seg button {
    background: color-mix(in srgb, var(--ink) 4%, var(--paper));
    border: none;
    border-right: 1px solid var(--line);
    padding: var(--space-2) var(--space-3);
    min-height: 44px;
    font-family: var(--font-mono);
    font-size: var(--ui-size);
    font-weight: 500;
    color: var(--ink-soft);
    cursor: pointer;
    transition: background var(--dur-fast) ease-out, color var(--dur-fast) ease-out, border-color var(--dur-fast) ease-out;
  }
  .seg button:last-child {
    border-right: none;
  }
  .seg button:hover:not(.sel):not([aria-checked="true"]) {
    color: var(--ink);
    background: color-mix(in srgb, var(--ink) 8%, var(--paper));
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
    color: var(--paper);
  }

  .jingle-toggles {
    display: grid;
    gap: var(--space-2);
    margin-top: var(--space-1);
  }

  .toggle-label {
    display: flex;
    align-items: center;
    gap: var(--space-2);
    font-size: var(--ui-size);
    color: var(--ink);
    cursor: pointer;
  }

  .toggle-label input[type='checkbox'] {
    accent-color: var(--green);
    width: 16px;
    height: 16px;
    cursor: pointer;
  }

  .back {
    display: inline-flex;
    align-items: center;
    gap: var(--space-1);
    background: transparent;
    border: 1px solid var(--line);
    border-radius: var(--radius);
    color: var(--ink-soft);
    padding: var(--space-1) var(--space-2);
    cursor: pointer;
    font-size: var(--ui-size);
  }

  .back:hover {
    color: var(--ink);
    border-color: var(--ink-soft);
  }

  .save-note {
    color: var(--ink-soft);
    font-size: var(--ui-size);
    margin: var(--space-2) 0 0;
  }
  .save-note.ok {
    color: var(--green);
  }
  .save-note.err {
    color: var(--danger);
  }

  section {
    border: 1px solid var(--line);
    border-radius: var(--radius);
    padding: var(--space-5);
    display: grid;
    gap: var(--space-4);
    background: color-mix(in srgb, var(--paper) 4%, transparent);
  }

  h3 {
    display: flex;
    align-items: center;
    gap: var(--space-2);
    font-size: var(--ui-size);
    color: var(--ink);
    text-transform: lowercase;
    margin: 0;
  }

  .opt {
    display: grid;
    gap: var(--space-2);
    padding: var(--space-1) 0;
  }

  .opt + .opt {
    border-top: 1px solid color-mix(in srgb, var(--line) 40%, transparent);
    padding-top: var(--space-3);
  }

  .ctl-row {
    display: flex;
    justify-content: space-between;
    align-items: baseline;
    gap: var(--space-2);
  }

  .lab {
    color: var(--ink-soft);
  }

  .readout {
    color: var(--ink);
  }

  .feed-url {
    display: block;
    font-size: var(--ui-size);
    color: var(--ink);
    overflow: hidden;
    text-overflow: ellipsis;
    white-space: nowrap;
  }

  .link {
    background: transparent;
    border: none;
    padding: 0;
    cursor: pointer;
    min-height: 28px;
    color: var(--ink-soft);
    font-family: var(--font-mono);
    font-size: var(--ui-size);
    text-decoration: underline;
    text-decoration-color: var(--line);
  }
  .link:hover { color: var(--green); }

  .key-readout {
    font-size: var(--ui-size);
    color: var(--ink-soft);
    display: block;
    margin: var(--space-2) 0;
  }

  .help {
    color: var(--ink-soft);
    font-size: var(--ui-size);
    line-height: 1.45;
    margin: 0;
  }

  select,
  .text-in {
    font-family: var(--font-mono);
    font-size: var(--ui-size);
    background-color: color-mix(in srgb, var(--ink) 4%, transparent);
    color: var(--ink);
    border: 1px solid var(--line);
    border-radius: var(--radius);
    padding: var(--space-1) var(--space-2);
    max-width: 100%;
    width: 100%;
    box-sizing: border-box;
    transition: border-color var(--dur-fast) ease-out, background-color var(--dur-fast) ease-out;
  }

  select {
    padding-right: 28px;
    cursor: pointer;
  }

  select:hover,
  .text-in:hover {
    border-color: var(--ink-soft);
    background-color: color-mix(in srgb, var(--ink) 7%, transparent);
  }

  .text-in::placeholder {
    color: var(--ink-soft);
  }

  .prompt-box {
    font-family: var(--font-mono);
    font-size: var(--ui-size);
    line-height: 1.5;
    background: transparent;
    color: var(--ink);
    border: 1px solid var(--line);
    border-radius: var(--radius);
    padding: var(--space-2);
    resize: vertical;
    width: 100%;
  }

  select:focus-visible,
  .text-in:focus-visible,
  .prompt-box:focus-visible {
    outline: 2px solid var(--green);
    outline-offset: 2px;
  }

  input[type='range']:focus-visible {
    outline: 2px solid var(--green);
    outline-offset: 2px;
  }

  .back:focus-visible,
  .link:focus-visible {
    outline: 2px solid var(--green);
    outline-offset: 2px;
  }

  .engine-line {
    color: var(--ink-soft);
  }

  .engine-detail {
    margin-top: var(--space-2);
    padding: var(--space-2) var(--space-3);
    border-left: 2px solid var(--line);
    display: grid;
    gap: var(--space-1);
    animation: fadein 180ms ease-out;
  }

  .detail-badge {
    font-size: var(--ui-size);
    color: var(--ink-soft);
    display: flex;
    align-items: center;
    gap: var(--space-1);
  }

  .badge-tag {
    color: var(--ink);
    border: 1px solid var(--line);
    padding: 1px 6px;
    border-radius: var(--radius);
  }

  .detail-body {
    font-size: var(--ui-size);
    color: var(--ink-soft);
    line-height: 1.45;
    margin: 0;
  }

  .detail-body.note {
    font-style: italic;
    color: var(--ink-soft);
  }

  .llm-status {
    display: inline-flex;
    align-items: center;
    gap: var(--space-2);
    margin-top: var(--space-1);
    font-size: var(--ui-size);
    color: var(--ink-soft);
  }

  .status-dot {
    width: 8px;
    height: 8px;
    border-radius: 50%;
    border: 1px solid var(--line);
    background: transparent;
    flex: none;
    transition: background var(--dur-fast) ease-out, border-color var(--dur-fast) ease-out;
  }

  .llm-status.checking .status-dot {
    background: var(--ink-soft);
    border-color: var(--ink-soft);
    animation: pulse 1.2s ease-in-out infinite;
  }

  .llm-status.ok .status-dot {
    background: var(--green);
    border-color: var(--green);
  }

  .llm-status.offline .status-dot {
    background: var(--danger);
    border-color: var(--danger);
  }

  .llm-status.unknown .status-dot {
    background: var(--ink-soft);
    border-color: var(--ink-soft);
  }

  .status-text {
    font-size: var(--ui-size);
  }

  @keyframes pulse {
    0%, 100% { opacity: 1; }
    50% { opacity: 0.4; }
  }

  @keyframes fadein {
    from {
      opacity: 0;
      transform: translateY(-2px);
    }
    to {
      opacity: 1;
      transform: translateY(0);
    }
  }

  .v4v-breakdown-card {
    background: color-mix(in srgb, var(--ink) 2%, var(--paper));
    border: 1px solid color-mix(in srgb, var(--ink) 12%, var(--line));
    border-radius: var(--radius);
    padding: var(--space-3);
    margin-bottom: var(--space-3);
    display: grid;
    gap: var(--space-2);
  }

  .v4v-recipient-card {
    background: color-mix(in srgb, var(--ink) 2%, var(--paper));
    border: 1.5px solid color-mix(in srgb, var(--ink) 14%, var(--line));
    border-radius: var(--radius);
    padding: var(--space-3);
    display: grid;
    gap: var(--space-2);
    margin-bottom: var(--space-3);
    box-shadow: 0 1px 2px rgba(0, 0, 0, 0.03);
  }

  .v4v-card-head {
    display: flex;
    align-items: center;
    justify-content: space-between;
    gap: var(--space-2);
  }

  .v4v-title-wrap {
    display: flex;
    align-items: center;
    gap: var(--space-2);
    flex-wrap: wrap;
  }

  .v4v-badge-locked {
    font-size: calc(var(--ui-size) * 0.78);
    font-weight: 500;
    color: var(--green);
    border: 1px solid color-mix(in srgb, var(--green) 35%, var(--line));
    background: color-mix(in srgb, var(--green) 8%, transparent);
    padding: 1px 6px;
    border-radius: var(--radius);
    display: inline-flex;
    align-items: center;
    gap: 4px;
    letter-spacing: 0.02em;
  }

  .readonly-input {
    opacity: 0.85;
    background: color-mix(in srgb, var(--ink) 2%, var(--paper)) !important;
    border-style: dashed !important;
    cursor: not-allowed;
  }

  .v4v-card-title {
    font-size: var(--ui-size);
    font-weight: 600;
    color: var(--ink);
    letter-spacing: 0.01em;
  }

  .v4v-input {
    width: 100%;
    min-height: 44px;
    background: color-mix(in srgb, var(--ink) 4%, var(--paper));
    border: 1px solid color-mix(in srgb, var(--ink) 18%, var(--line));
    border-radius: var(--radius);
    padding: var(--space-2) var(--space-3);
    font-size: var(--ui-size);
    color: var(--ink);
    box-shadow: inset 0 1px 2px rgba(0, 0, 0, 0.05);
  }

  .v4v-input:focus-visible {
    outline: 2px solid var(--green);
    outline-offset: 2px;
    border-color: var(--green);
  }

  .v4v-help {
    color: color-mix(in srgb, var(--ink) 75%, transparent);
    font-size: calc(var(--ui-size) * 0.85);
    line-height: 1.4;
    margin: 0;
  }

  .pct-unit {
    color: var(--ink-soft);
    font-size: calc(var(--ui-size) * 0.9);
    font-weight: 500;
  }

  .split-bar-wrap {
    display: flex;
    width: 100%;
    height: 8px;
    border-radius: var(--radius);
    overflow: hidden;
    background: var(--line);
    margin: var(--space-1) 0;
  }

  .split-bar-creator {
    background: var(--green);
    transition: width var(--dur-fast) ease-out;
  }

  .split-bar-source {
    background: var(--paper-warm, #d97706);
    opacity: 0.85;
    transition: width var(--dur-fast) ease-out;
  }

  .split-bar-app {
    background: var(--ink-soft);
    opacity: 0.6;
    transition: width var(--dur-fast) ease-out;
  }

  .split-pct-box {
    display: inline-flex;
    align-items: center;
    gap: 6px;
    background: color-mix(in srgb, var(--ink) 4%, var(--paper));
    border: 1px solid color-mix(in srgb, var(--ink) 18%, var(--line));
    border-radius: var(--radius);
    padding: var(--space-1) var(--space-2);
    min-height: 38px;
  }

  .pct-in {
    width: 58px;
    min-width: 58px;
    text-align: right;
    background: transparent;
    border: none;
    color: var(--ink);
    font-weight: 600;
    font-size: var(--ui-size);
    padding: 2px 4px;
  }

  .pct-in:focus-visible {
    outline: 2px solid var(--green);
    outline-offset: 2px;
  }

  .split-presets {
    display: flex;
    gap: var(--space-2);
    flex-wrap: wrap;
    margin-top: var(--space-1);
  }

  .preset-btn {
    font-size: calc(var(--ui-size) * 0.9);
    background: color-mix(in srgb, var(--ink) 4%, var(--paper));
    color: var(--ink);
    border: 1px solid color-mix(in srgb, var(--ink) 16%, var(--line));
    border-radius: var(--radius);
    padding: var(--space-1) var(--space-2);
    min-height: 36px;
    cursor: pointer;
    font-weight: 500;
    transition: all var(--dur-fast) ease-out;
  }

  .preset-btn:hover:not(.active) {
    border-color: var(--ink);
    background: color-mix(in srgb, var(--ink) 8%, var(--paper));
  }

  .preset-btn.active {
    color: var(--ink);
    border-color: var(--green);
    background: color-mix(in srgb, var(--green) 12%, var(--paper));
    font-weight: 600;
  }

  .preset-btn.active:hover {
    color: var(--ink);
    border-color: var(--green);
    background: color-mix(in srgb, var(--green) 20%, var(--paper));
  }

  .style-section {
    display: grid;
    gap: var(--space-3);
  }

  .style-group {
    display: flex;
    align-items: center;
    gap: var(--space-2);
    margin-bottom: var(--space-2);
  }

  .group-label {
    font-size: calc(var(--ui-size) * 0.8);
    color: var(--ink-soft);
    min-width: 3.5rem;
  }

  .seg-wrap {
    display: grid;
    grid-template-columns: repeat(auto-fill, minmax(7.5em, 1fr));
    gap: var(--space-2);
    flex: 1;
  }

  .seg-wrap button {
    text-align: center;
  }

  .g-learn .seg button.sel { color: var(--paper); border-color: var(--style-learn); background: var(--style-learn); }
  .g-mood .seg button.sel { color: var(--paper); border-color: var(--style-mood); background: var(--style-mood); }
  .g-drama .seg button.sel { color: var(--paper); border-color: var(--style-drama); background: var(--style-drama); }
  .g-play .seg button.sel { color: var(--paper); border-color: var(--style-play); background: var(--style-play); }
  .g-solo .seg button.sel { color: var(--paper); border-color: var(--ink); background: var(--ink); }
  .g-custom .seg button.sel { color: var(--paper); border-color: var(--green); background: var(--green); }
  .style-section.g-custom .styledoc-box { border-color: var(--green); }

  .custom-row .custom-name {
    color: var(--ink);
    font-weight: 600;
  }
  .custom-actions {
    display: flex;
    flex-wrap: wrap;
    align-items: center;
    gap: var(--space-3);
  }

  .styledoc-box {
    display: grid;
    justify-items: center;
    gap: var(--space-2);
    border: 1px solid var(--line);
    border-radius: var(--radius);
    padding: var(--space-4);
    margin-top: var(--space-3);
    animation: styledocFade var(--dur-slow) ease-out;
    background: color-mix(in srgb, var(--paper) 4%, transparent);
  }

  .styledoc-text {
    margin: 0;
    font-family: var(--font-serif);
    font-style: italic;
    font-size: calc(var(--ui-size) * 1.08);
    color: var(--ink);
    text-align: center;
    max-width: 34em;
    line-height: 1.45;
  }

  @keyframes styledocFade {
    from { opacity: 0; transform: translateY(2px); }
    to { opacity: 1; transform: translateY(0); }
  }

  .style-section.g-learn .styledoc-box { border-color: var(--style-learn); }
  .style-section.g-mood .styledoc-box { border-color: var(--style-mood); }
  .style-section.g-drama .styledoc-box { border-color: var(--style-drama); }
  .style-section.g-play .styledoc-box { border-color: var(--style-play); }

  .note {
    color: var(--ink-soft);
  }

  .model-chips {
    display: flex;
    flex-wrap: wrap;
    gap: 6px;
  }
  .model-chip {
    font-size: 12px;
    padding: 3px 8px;
    border: 1px solid var(--line);
    background: transparent;
    color: inherit;
    cursor: pointer;
  }
  .plugin-drawer-btn {
    display: inline-flex;
    align-items: center;
    gap: 6px;
    background: transparent;
    border: 1px solid var(--line);
    border-radius: var(--radius);
    color: var(--ink-soft);
    padding: 6px 12px;
    cursor: pointer;
    min-height: 36px;
    font-size: var(--ui-size);
  }

  .plugin-drawer-btn:hover {
    border-color: var(--ink);
    color: var(--ink);
  }

  .plugin-drawer-btn:focus-visible {
    outline: 2px solid var(--green);
    outline-offset: 2px;
  }

  .music-status-rows {
    display: grid;
    gap: var(--space-2);
    margin-top: var(--space-1);
  }

  .music-track-row {
    display: flex;
    align-items: center;
    justify-content: space-between;
    gap: var(--space-2);
    padding: var(--space-2) var(--space-3);
    background: color-mix(in srgb, var(--ink) 4%, var(--paper));
    border: 1px solid color-mix(in srgb, var(--ink) 12%, var(--line));
    border-radius: var(--radius);
  }

  .track-tag {
    color: var(--ink-soft);
    font-size: var(--ui-size);
    font-weight: 600;
    min-width: 3.5rem;
  }

  .track-desc {
    color: var(--ink);
    font-size: var(--ui-size);
    flex: 1;
    overflow: hidden;
    text-overflow: ellipsis;
    white-space: nowrap;
  }

  .probe-btn {
    display: inline-flex;
    align-items: center;
    gap: var(--space-1);
    background: color-mix(in srgb, var(--ink) 6%, var(--paper));
    border: 1px solid var(--line);
    border-radius: var(--radius);
    color: var(--ink);
    padding: var(--space-1) var(--space-2);
    font-size: calc(var(--ui-size) * 0.85);
    font-family: var(--font-mono);
    cursor: pointer;
    transition: all var(--dur-fast) ease-out;
  }

  .probe-btn:hover:not(.active) {
    color: var(--ink);
    border-color: var(--green);
    background: color-mix(in srgb, var(--green) 8%, var(--paper));
  }

  .probe-btn.active {
    color: var(--ink);
    border-color: var(--green);
    background: color-mix(in srgb, var(--green) 12%, var(--paper));
    font-weight: 600;
  }

  .probe-btn.active:hover {
    color: var(--ink);
    border-color: var(--green);
    background: color-mix(in srgb, var(--green) 20%, var(--paper));
  }

  .music-import-box {
    display: grid;
    gap: var(--space-2);
    margin-top: var(--space-2);
    padding: var(--space-3);
    border: 1px dashed color-mix(in srgb, var(--ink) 20%, var(--line));
    border-radius: var(--radius);
    background: color-mix(in srgb, var(--paper) 2%, transparent);
  }

  .import-kind-row {
    display: flex;
    align-items: center;
    gap: var(--space-3);
  }

  .import-input-row {
    display: flex;
    gap: var(--space-2);
    align-items: center;
    flex-wrap: wrap;
  }

  .music-url-input {
    flex: 1;
    min-width: 14rem;
    min-height: 38px;
    padding: var(--space-1) var(--space-3);
    border: 1px solid var(--line);
    border-radius: var(--radius);
    background: var(--paper);
    color: var(--ink);
    font-size: var(--ui-size);
  }

  .music-url-input:focus {
    outline: 2px solid var(--green);
    border-color: var(--green);
  }

  .import-btn {
    background: var(--green);
    color: var(--paper);
    border: 1px solid var(--green);
    border-radius: var(--radius);
    padding: var(--space-1) var(--space-3);
    min-height: 38px;
    cursor: pointer;
    font-size: var(--ui-size);
    font-family: var(--font-mono);
    font-weight: 500;
    transition: all var(--dur-fast) ease-out;
  }

  .import-btn:hover:not(:disabled) {
    background: color-mix(in srgb, var(--green) 85%, var(--ink));
    border-color: var(--green);
    color: var(--paper);
  }

  .import-btn:disabled {
    opacity: 0.5;
    cursor: not-allowed;
  }

  .import-msg {
    font-size: var(--ui-size);
    margin: var(--space-1) 0 0;
  }

  .import-msg.ok {
    color: var(--green);
  }

  .import-msg.err {
    color: var(--danger);
  }

  @media (max-width: 600px) {
    .settings-screen {
      min-width: 0;
      max-width: 100%;
      width: 100%;
    }
    .settings-screen * {
      min-width: 0;
    }
    .ctl-row {
      flex-direction: column;
      align-items: flex-start;
      gap: var(--space-2);
    }
    .seg {
      flex-wrap: wrap;
      max-width: 100%;
    }
    .seg button {
      flex: 1 1 auto;
      border-bottom: 1px solid var(--line);
    }
    .music-track-row {
      flex-wrap: wrap;
      gap: var(--space-2);
    }
    .import-input-row {
      flex-direction: column;
      align-items: stretch;
      gap: var(--space-2);
    }
    .music-url-input {
      min-width: 0;
      width: 100%;
    }
    .import-btn {
      width: 100%;
      text-align: center;
      justify-content: center;
    }
  }

  /* ---- distribution (section 04) ---- */
  .group-help {
    margin: calc(var(--space-2) * -1) 0 0;
  }
  .new-show-trigger {
    display: inline-flex;
    align-items: center;
    gap: var(--space-1);
    font-size: calc(var(--ui-size) * 0.88);
  }
  .new-show-card {
    border-left: 3px solid var(--green);
    margin-bottom: var(--space-3);
  }
  .new-show-actions {
    display: flex;
    align-items: center;
    gap: var(--space-3);
    margin-top: var(--space-2);
  }
  .show-ctl-actions {
    display: inline-flex;
    align-items: center;
    gap: var(--space-3);
  }
  .delete-show-trigger {
    color: var(--danger);
    font-size: calc(var(--ui-size) * 0.85);
    display: inline-flex;
    align-items: center;
    gap: 3px;
  }
  .delete-show-trigger:hover {
    color: var(--danger-fill);
    text-decoration: underline;
  }
  .confirm-box.delete-confirm-box {
    border-left: 3px solid var(--danger);
  }
  .probe-btn.danger {
    background: var(--danger);
    border-color: var(--danger);
    color: #ffffff;
  }
  .probe-btn.danger:hover:not(:disabled) {
    background: var(--danger-fill);
    border-color: var(--danger-fill);
    color: #ffffff;
  }
  .show-reach .show-name {
    color: var(--ink);
    font-weight: 600;
  }
  .reach-seg {
    flex-wrap: wrap;
  }
  .reach-seg button.pending {
    border: 1px dashed var(--green);
    color: var(--green);
    background: color-mix(in srgb, var(--green) 18%, transparent);
    font-weight: 600;
  }
  .master-reach-row {
    display: flex;
    align-items: center;
    gap: var(--space-3);
    flex-wrap: wrap;
  }
  .master-reach-row .help-inline {
    font-size: calc(var(--ui-size) * 0.88);
    color: var(--ink-soft);
  }
  .confirm-box {
    display: grid;
    gap: var(--space-2);
    padding: var(--space-3);
    border: 1px solid var(--line);
    border-left: 3px solid var(--green);
    border-radius: var(--radius);
    background: color-mix(in srgb, var(--ink) 3%, var(--paper));
  }
  .confirm-box:focus-visible {
    outline: 2px solid var(--green);
    outline-offset: 2px;
  }
  .confirm-title {
    margin: 0;
    color: var(--ink);
    font-weight: 600;
  }
  .confirm-actions {
    display: flex;
    flex-wrap: wrap;
    align-items: center;
    gap: var(--space-3);
  }
  .kv {
    display: grid;
    grid-template-columns: 5.5rem minmax(0, 1fr) auto;
    align-items: baseline;
    gap: var(--space-2);
    font-size: calc(var(--ui-size) * 0.9);
  }
  .kv-key {
    color: var(--ink-soft);
  }
  .kv-val {
    color: var(--ink);
    overflow-wrap: anywhere;
    font-family: var(--font-mono);
  }
  .kv-val.secret {
    padding: var(--space-2);
    border: 1px dashed var(--line);
    border-radius: var(--radius);
  }
  .key-link {
    justify-self: start;
  }
  .readout.ok {
    color: var(--green);
  }
  .readout.bad {
    color: var(--danger);
  }
  .dir-links {
    margin: 0;
    padding-left: var(--space-4);
    display: grid;
    gap: var(--space-1);
  }
  .dir-links a {
    color: var(--ink);
    display: inline-flex;
    align-items: center;
    min-height: 24px;
    padding: 2px 0;
  }
  .dir-links a:hover {
    color: var(--green);
  }
  .list-ta {
    resize: vertical;
    line-height: 1.5;
  }
  .err {
    color: var(--danger);
  }
  @media (max-width: 520px) {
    .kv {
      grid-template-columns: minmax(0, 1fr) auto;
    }
    .kv-key {
      grid-column: 1 / -1;
    }
  }

  .show-fields {
    display: grid;
    grid-template-columns: 7rem minmax(0, 1fr);
    align-items: center;
    gap: var(--space-2) var(--space-3);
  }
  /* the note sits under the distribution buttons, in the field column */
  .show-fields .reach-note {
    grid-column: 2;
    margin: 0;
  }
  .show-fields .desc-ta {
    resize: vertical;
    line-height: 1.5;
  }
  @media (max-width: 520px) {
    .show-fields {
      grid-template-columns: minmax(0, 1fr);
    }
    .show-fields .reach-note {
      grid-column: 1;
    }
  }
</style>


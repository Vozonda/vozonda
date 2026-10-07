<script lang="ts">
  import { onMount, tick } from 'svelte'
  import Waveform from './Waveform.svelte'
  import Icon from './Icon.svelte'
  import ZapModal from './ZapModal.svelte'
  import HighlightModal from './HighlightModal.svelte'
  import TranscriptHighlighter from './TranscriptHighlighter.svelte'
  import { LANG_NAMES, type AudioFacts, type DialogueLine, type ClipListItem, coverUrl, createClip, listClips, deleteClip, renameJob } from '../api'
  import { styleDocFor } from '../styles'
  import {
    getEpisodePlayCount,
    incrementEpisodePlayCount,
    getEpisodeZappedSats,
    getEpisodeZapCount,
    quickZap,
    hasAnyWallet,
    hasWebLN,
    hasNWC,
    recordEpisodeBoost,
    getStreamSatsPerMin,
    setStreamSatsPerMin,
    getNWCUri,
    isValidNWCUri
  } from '../zaps'
  import { setEpisodeHighlightCount, categorizeHighlight, type HighlightParsed } from '../highlights'
  import { shortNpub, getActiveIdentity } from '../nostr'
  import type { WaveformPin } from './Waveform.svelte'

  interface Props {
    title?: string
    src: string
    lines: DialogueLine[]
    jobId?: string
    sourceUrl?: string
    createdAt?: number
    jobStyle?: string
    jobFormat?: string
    jobLanguage?: string
    jobDurationMs?: number | null
    jobAudio?: AudioFacts | null
    jobVoices?: string[]
    jobVoiceMap?: Record<string, string> | null
    jobTuning?: { speed?: number; emotion?: string; gap_ms?: number; music_bed?: boolean } | null
    jobStages?: Array<{
      name: string
      status: string
      ms?: number
      meta?: Record<string, unknown>
      detail?: string
    }> | null
    jobProvider?: string | null
    jobTone?: string | null
    jobExplicit?: boolean
    metaStyleDocs?: Record<string, string> | null
    metaStyleMeta?: import('../styles').StyleMeta[] | null
    sourceLang?: string
    watchlistId?: string | null
    showName?: string | null
    showAuthor?: string | null
    chapters?: { index: number; title: string; url?: string; word_offset?: number }[] | null
    isDigest?: boolean
    ogImage?: string | null
    valueTip?: {
      address: string
      split: number
      appAddress?: string
      creatorAddress?: string
      creatorSplit?: number
      sourceAddress?: string
      sourceSplit?: number
      appSplit?: number
    } | null
    onback?: () => void
    onPrev?: () => void
    onNext?: () => void
    onremix?: (source: string, isUrl: boolean) => void
    clipTurnStart?: number | null
    clipTurnEnd?: number | null
    executiveSummary?: string | null
    executiveQuote?: string | null
    keyTakeaways?: import('../api').KeyTakeaway[] | null
    factualityScore?: number | null
    nostrShowEnabled?: boolean
    nostrStatus?: 'published' | 'failed' | null
    nostrRelayCount?: number
    nostrSuccessCount?: number
  }

  let {
    title,
    src,
    lines,
    jobId,
    sourceUrl,
    createdAt,
    jobStyle,
    jobFormat,
    jobLanguage,
    jobDurationMs,
    jobAudio,
    jobVoices,
    jobVoiceMap,
    jobTuning,
    jobStages = null,
    jobProvider = null,
    jobTone = null,
    jobExplicit = false,
    metaStyleDocs = null,
    metaStyleMeta = null,
    sourceLang,
    watchlistId,
    showName = null,
    showAuthor = null,
    chapters,
    isDigest = false,
    ogImage = null,
    valueTip = null,
    onback,
    onPrev,
    onNext,
    onremix,
    clipTurnStart = null,
    clipTurnEnd = null,
    executiveSummary = null,
    executiveQuote = null,
    keyTakeaways = null,
    factualityScore = null,
    nostrShowEnabled = false,
    nostrStatus = null,
    nostrRelayCount = 0,
    nostrSuccessCount = 0
  }: Props = $props()

  let imageFailed = $state(false)
  let zapOpen = $state(false)
  let highlightOpen = $state(false)
  let hasTrackedPlay = $state(false)
  let nostrPublishStatus = $state<'published' | 'failed' | null>(null)
  let nostrPublishBusy = $state(false)
  let nostrPublishError = $state('')

  // Episode rename affordance (VOZONDA-RENAME)
  let currentTitle = $state(title || '')
  let isRenaming = $state(false)
  let renameDraft = $state('')
  let renameBusy = $state(false)
  let renameError = $state('')
  let renameInputEl = $state<HTMLInputElement | null>(null)
  let headerH1El = $state<HTMLElement | null>(null)
  let headerH1Found = $state(false)

  $effect(() => {
    if (title && !isRenaming) {
      currentTitle = title
    }
  })

  function updateLocalRecentTitle(id: string, newTitle: string) {
    if (typeof localStorage === 'undefined') return
    try {
      const raw = localStorage.getItem('vozonda.recent')
      if (raw) {
        const list = JSON.parse(raw) as unknown
        if (Array.isArray(list)) {
          for (const item of list) {
            if (item && typeof item === 'object' && 'id' in item && item.id === id) {
              item.title = newTitle
            }
          }
          localStorage.setItem('vozonda.recent', JSON.stringify(list))
        }
      }
    } catch {}
  }

  function startRename() {
    renameDraft = currentTitle
    renameError = ''
    isRenaming = true
    void tick().then(() => {
      renameInputEl?.focus()
      renameInputEl?.select()
    })
  }

  function cancelRename() {
    isRenaming = false
    renameError = ''
  }

  async function saveRename() {
    const trimmed = renameDraft.replace(/\s+/g, ' ').trim()
    if (!trimmed || trimmed.length > 120) {
      renameError = 'title must be 1 to 120 characters'
      return
    }
    if (!jobId) {
      currentTitle = trimmed
      isRenaming = false
      if (headerH1El) headerH1El.textContent = trimmed
      return
    }
    renameBusy = true
    renameError = ''
    try {
      const updated = await renameJob(jobId, trimmed)
      currentTitle = updated.title || trimmed
      if (headerH1El) headerH1El.textContent = currentTitle
      if (typeof navigator !== 'undefined' && 'mediaSession' in navigator && navigator.mediaSession?.metadata) {
        navigator.mediaSession.metadata.title = currentTitle
      }
      updateLocalRecentTitle(jobId, currentTitle)
      isRenaming = false
    } catch (err) {
      renameError = err instanceof Error ? err.message.toLowerCase() : 'failed to rename'
    } finally {
      renameBusy = false
    }
  }

  function handleRenameKeydown(e: KeyboardEvent) {
    if (e.key === 'Enter') {
      e.preventDefault()
      e.stopPropagation()
      void saveRename()
    } else if (e.key === 'Escape') {
      e.preventDefault()
      e.stopPropagation()
      cancelRename()
    }
  }

  let playCount = $state(0)
  let zappedSats = $state(0)
  let zapCount = $state(0)
  let highlightCount = $state(0)
  let highlightsList = $state<HighlightParsed[]>([])
  let hlFilter = $state<'all' | 'user' | 'friend' | 'global'>('all')
  let hlCopiedIdx = $state<number | null>(null)
  let hlCopyTimer: ReturnType<typeof setTimeout> | undefined

  const userPubkey = $derived.by(() => {
    try {
      const id = getActiveIdentity()
      return id?.pubkey?.toLowerCase() ?? null
    } catch {
      return null
    }
  })

  const hlCounts = $derived.by(() => {
    let user = 0
    let friend = 0
    let global = 0
    for (const h of highlightsList) {
      const cat = categorizeHighlight(h, userPubkey, new Set())
      if (cat === 'user') user++
      else if (cat === 'friend') friend++
      else global++
    }
    return { all: highlightsList.length, user, friend, global }
  })

  const filteredHighlights = $derived.by(() => {
    if (hlFilter === 'all') return highlightsList
    return highlightsList.filter((h) => categorizeHighlight(h, userPubkey, new Set()) === hlFilter)
  })

  async function copyHighlightText(e: MouseEvent, text: string, idx: number) {
    e.stopPropagation()
    if (navigator.clipboard) {
      try {
        await navigator.clipboard.writeText(text)
        hlCopiedIdx = idx
        if (hlCopyTimer) clearTimeout(hlCopyTimer)
        hlCopyTimer = setTimeout(() => (hlCopiedIdx = null), 2000)
      } catch {}
    }
  }

  // Clips section (DUE-020 / #184) - selection-driven, no manual numeric inputs
  let clipsOpen = $state(false)
  let clips = $state<ClipListItem[]>([])
  let clipBusy = $state(false)
  let clipError = $state('')
  let clipCopiedIdx = $state<number | null>(null)
  let clipCopyTimers: ReturnType<typeof setTimeout>[] = []
  let sliceDraft = $state<{ turnStart: number; turnEnd: number; textSnippet: string } | null>(null)
  let slicePreviewPlaying = $state(false)
  let slicePreviewTimer: ReturnType<typeof setTimeout> | undefined

  let clipPlayingMap = $state<Record<number, boolean>>({})
  let clipTimeMap = $state<Record<number, number>>({})
  let clipDurMap = $state<Record<number, number>>({})

  // Unified Episode Navigation (transcript, chapters, takeaways, highlights, clips, facts)
  type ListenTab = 'transcript' | 'chapters' | 'takeaways' | 'highlights' | 'clips' | 'facts'
  let activeTab = $state<ListenTab>('transcript')
  let mode = $derived<'podcast' | 'takeaways'>(activeTab === 'takeaways' ? 'takeaways' : 'podcast')
  let streamingSats = $state(false)
  let streamingInterval: ReturnType<typeof setInterval> | null = null
  let streamingTotalSats = $state(0)
  let zapInitialSats = $state<number | undefined>(undefined)
  let zapInitialComment = $state<string>('')
  let zapTimestamp = $state<number | undefined>(undefined)
  let copiedSummary = $state(false)

  // V4V 1-click boost state (DUE-074)
  let boostNote = $state('')
  let boostBusy = $state(false)
  let boostFeedback = $state('')
  let boostError = $state('')
  let streamingRate = $state(getStreamSatsPerMin())
  let showStreamRate = $state(false)
  let walletConnected = $state(false)
  $effect(() => {
    try { walletConnected = hasAnyWallet() } catch { walletConnected = false }
  })

  // DUE-088 A/B Test Variant for Boost Placement:
  // 'meta': Compact date row with right-aligned +100 sats boost button (Variant A)
  // 'strip': Classical bottom strip below player (Variant B)
  const getInitialBoostVariant = (): 'meta' | 'strip' => {
    try {
      if (typeof window !== 'undefined') {
        const urlParam = new URLSearchParams(window.location.search).get('boost_variant')
        if (urlParam === 'strip' || urlParam === 'meta') return urlParam
        const stored = localStorage.getItem('vozonda_boost_variant')
        if (stored === 'strip' || stored === 'meta') return stored
      }
    } catch {}
    return 'meta'
  }
  let boostVariant = $state<'meta' | 'strip'>(getInitialBoostVariant())

  // Hallucination-Guard Source-Quote Inspector (DUE-077 / #262)
  let expandedQuotes = $state<Set<number>>(new Set())
  let showExecQuote = $state(false)

  // Waveform timestamp pins for Boostagrams and NIP-84 Highlights (DUE-075 / #260)
  const waveformPins = $derived.by((): WaveformPin[] => {
    const pins: WaveformPin[] = []
    // NIP-84 highlights mapped to transcript t0 via content substring match
    for (const h of highlightsList) {
      const needle = h.content.trim().toLowerCase().slice(0, 60)
      if (!needle) continue
      let at: number | undefined
      for (let i = 0; i < lines.length; i++) {
        const txt = (lines[i]?.text ?? '').toLowerCase()
        const shortNeedle = needle.slice(0, 40)
        const shortTxt = txt.slice(0, 40)
        if (txt.includes(shortNeedle) || needle.includes(shortTxt)) {
          const t0 = lines[i]?.t0
          if (typeof t0 === 'number' && Number.isFinite(t0)) {
            at = t0
            break
          }
        }
      }
      if (at === undefined) continue
      const id = `hl-${h.id ?? h.content.slice(0, 10).replace(/\s+/g, '-')}`
      const label = h.content.slice(0, 48) + (h.content.length > 48 ? '...' : '')
      pins.push({ id, at, kind: 'highlight', label, detail: h.content })
    }
    // Boostagrams (NIP-57 streaming sats) persisted as timestamped boosts
    if (jobId && typeof localStorage !== 'undefined') {
      try {
        const raw = localStorage.getItem(`vozonda_boosts_${jobId}`)
        if (raw) {
          const arr = JSON.parse(raw) as Array<{ at: number; sats: number; message?: string }>
          if (Array.isArray(arr)) {
            for (let i = 0; i < arr.length; i++) {
              const b = arr[i] as { at: number; sats: number; message?: string }
              if (typeof b.at !== 'number' || !Number.isFinite(b.at)) continue
              const sats = typeof b.sats === 'number' && Number.isFinite(b.sats) ? Math.round(b.sats) : 100
              const msg = typeof b.message === 'string' ? b.message : ''
              pins.push({
                id: `boost-${i}-${b.at}`,
                at: b.at,
                kind: 'boost',
                label: msg ? msg.slice(0, 48) : `${sats} sats boost`,
                detail: msg || `${sats} sats`,
                sats
              })
            }
          }
        }
      } catch {}
    }
    pins.sort((a, b) => a.at - b.at)
    return pins
  })

  // Sync clip route props to slice draft for deep-linking (#184)
  $effect(() => {
    if (clipTurnStart !== null && clipTurnEnd !== null) {
      const textSnippet = lines.slice(clipTurnStart, clipTurnEnd + 1).map((l) => l.text).join(' ').slice(0, 120)
      sliceDraft = { turnStart: clipTurnStart, turnEnd: clipTurnEnd, textSnippet }
      clipsOpen = true
      activeTab = 'clips'
    }
  })

  function fmtTime(s: number): string {
    if (!s || isNaN(s)) return '0:00'
    const m = Math.floor(s / 60)
    const r = Math.floor(s % 60)
    return `${m}:${r.toString().padStart(2, '0')}`
  }

  function clipShareUrl(clip: ClipListItem): string {
    // Prefer server-provided SEO URL (includes slug), fallback to local construction
    if (clip.share_url) return clip.share_url
    if (jobId) {
      try { return `${window.location.origin}/e/${jobId}/clip/${clip.turn_start}-${clip.turn_end}` } catch { return '' }
    }
    return ''
  }

  function clipLabel(clip: ClipListItem): string {
    if (clip.label) return clip.label
    if (clip.speaker && clip.quote_snippet) return `${clip.speaker} · "${clip.quote_snippet}" (${Math.round(clip.duration_seconds)}s)`
    return `clip ${clip.turn_start}-${clip.turn_end}`
  }

  function sliceSpeakers(draft: { turnStart: number; turnEnd: number }): string {
    const seen: string[] = []
    for (let i = draft.turnStart; i <= draft.turnEnd; i++) {
      const line = lines[i]
      if (!line) continue
      const lab = labelFor(line)
      if (!seen.includes(lab)) seen.push(lab)
    }
    return seen.join(' · ') || '2 voices'
  }

  function sliceEstimatedDuration(draft: { turnStart: number; turnEnd: number }): number {
    const startLine = lines[draft.turnStart]
    const startT0 = startLine?.t0
    if (typeof startT0 === 'number') {
      const nextIdx = draft.turnEnd + 1
      const nextT0 = lines[nextIdx]?.t0
      if (typeof nextT0 === 'number') return Math.max(0.5, nextT0 - startT0)
      if (dur > 0) return Math.max(0.5, dur - startT0)
    }
    if (dur > 0 && lines.length > 0) {
      const totalChars = lines.reduce((n, l) => n + (l.text?.length ?? 0), 0) || 1
      const charsBefore = lines.slice(0, draft.turnStart).reduce((n, l) => n + (l.text?.length ?? 0), 0)
      const charsSel = lines.slice(draft.turnStart, draft.turnEnd + 1).reduce((n, l) => n + (l.text?.length ?? 0), 0)
      const start = (dur * charsBefore) / totalChars
      const end = (dur * (charsBefore + charsSel)) / totalChars
      return Math.max(0.5, end - start)
    }
    const charsSel = lines.slice(draft.turnStart, draft.turnEnd + 1).reduce((n, l) => n + (l.text?.length ?? 0), 0)
    return Math.max(1, charsSel / 14)
  }

  const slicePreviewMeta = $derived.by(() => {
    if (!sliceDraft) return null
    return {
      speakers: sliceSpeakers(sliceDraft),
      duration: sliceEstimatedDuration(sliceDraft)
    }
  })

  function handleSliceFromHighlight(detail: { turnStart: number; turnEnd: number; text: string }) {
    const start = Math.max(0, Math.min(detail.turnStart, detail.turnEnd))
    const end = Math.max(start, Math.min(Math.max(detail.turnStart, detail.turnEnd), Math.max(0, lines.length - 1)))
    sliceDraft = { turnStart: start, turnEnd: end, textSnippet: detail.text.slice(0, 180) }
    clipError = ''
    clipsOpen = true
  }

  function handleTurnSliceClick(idx: number) {
    // Tap/hover handle: single turn slice, or shift-extend if draft exists
    if (sliceDraft && idx >= sliceDraft.turnStart && idx <= sliceDraft.turnEnd) {
      // tapping inside existing selection clears it
      sliceDraft = null
      return
    }
    if (sliceDraft) {
      const start = Math.min(sliceDraft.turnStart, idx)
      const end = Math.max(sliceDraft.turnEnd, idx)
      sliceDraft = { turnStart: start, turnEnd: end, textSnippet: lines.slice(start, end + 1).map((l) => l.text).join(' ').slice(0, 180) }
    } else {
      sliceDraft = { turnStart: idx, turnEnd: idx, textSnippet: (lines[idx]?.text ?? '').slice(0, 180) }
    }
    clipsOpen = true
    clipError = ''
  }

  function handlePreviewSlice() {
    if (!sliceDraft || !audio) return
    const draft = sliceDraft
    const startT0 = lines[draft.turnStart]?.t0
    const durEst = sliceEstimatedDuration(draft)
    const seekToTime = typeof startT0 === 'number' ? startT0 : 0
    try {
      audio.currentTime = Math.max(0, Math.min(seekToTime, dur || seekToTime))
      void audio.play()
      slicePreviewPlaying = true
      if (slicePreviewTimer) clearTimeout(slicePreviewTimer)
      slicePreviewTimer = setTimeout(() => {
        try { audio.pause() } catch {}
        slicePreviewPlaying = false
      }, Math.max(600, Math.min(durEst * 1000 + 400, 45000)))
    } catch {}
  }

  async function handleCreateSlice() {
    if (!jobId || !sliceDraft || clipBusy) return
    clipBusy = true
    clipError = ''
    try {
      await createClip({ job_id: jobId, turn_start: sliceDraft.turnStart, turn_end: sliceDraft.turnEnd })
      await refreshClips()
    } catch (e) {
      clipError = (e as Error).message ?? 'create failed'
      setTimeout(() => { clipError = '' }, 5000)
    } finally {
      clipBusy = false
    }
  }

  async function refreshClips() {
    if (!jobId) return
    try {
      clips = await listClips(jobId)
    } catch {
      clips = []
    }
  }

  async function handleDeleteClip(filename: string) {
    if (!jobId || !filename) return
    try {
      await deleteClip(jobId, filename)
      await refreshClips()
    } catch (e) {
      clipError = (e as Error).message ?? 'delete failed'
      setTimeout(() => { clipError = '' }, 5000)
    }
  }

  function fmtCount(n: number, singular: string, plural: string): string {
    if (n === 1) return `1 ${singular}`
    if (n >= 1000) return `${(n / 1000).toFixed(1)}k ${plural}`
    return `${n} ${plural}`
  }

  $effect(() => {
    void jobId
    imageFailed = false
    hasTrackedPlay = false
    if (jobId) {
      playCount = getEpisodePlayCount(jobId)
      zappedSats = getEpisodeZappedSats(jobId)
      zapCount = getEpisodeZapCount(jobId)
    } else {
      playCount = 0
      zappedSats = 0
      zapCount = 0
    }
  })

  const coverSrc = $derived.by(() => {
    if (imageFailed) return null
    if (ogImage) {
      return coverUrl(ogImage)
    }
    if (jobId) {
      return `/img/${jobId}-cover.png`
    }
    return null
  })

  // chapter start times derived from word offsets: walk the transcript,
  // a chapter begins at the first line whose cumulative word count
  // reaches its word_offset (first chapter always starts at 0)
  const chapterMarks = $derived.by(() => {
    if (!chapters || chapters.length < 2) return []
    const out: { index: number; title: string; t: number | undefined }[] = []
    let cum = 0
    let ci = 0
    for (const line of lines) {
      const ch = chapters[ci]
      if (!ch) break
      while (ci < chapters.length && (chapters[ci]?.word_offset ?? 0) <= cum) {
        const cur = chapters[ci]
        if (!cur) break
        out.push({ index: cur.index, title: cur.title, t: out.length === 0 ? 0 : line.t0 })
        ci++
      }
      cum += (line.text || '').split(/\s+/).filter(Boolean).length
    }
    while (ci < chapters.length) {
      const cur = chapters[ci]
      if (!cur) break
      out.push({ index: cur.index, title: cur.title, t: undefined })
      ci++
    }
    return out
  })

  function domainOf(u?: string): string {
    if (!u) return ''
    try {
      const h = new URL(u).hostname.replace(/^www\./, '')
      return h
    } catch {
      return u.replace(/^https?:\/\//i, '').split('/')[0] ?? ''
    }
  }

  const isDigestEpisode = $derived(!!isDigest && !!chapters && chapters.length > 0)

  type GroupedSection = { header: string; lines: typeof lines; startIdx: number; domain: string; globalIdxs: number[] }
  const groupedTranscript = $derived.by((): GroupedSection[] | null => {
    if (!isDigestEpisode || !chapters || chapters.length === 0) return null
    const groups: GroupedSection[] = chapters.map((c) => ({
      header: `${c.index + 1} · ${c.title}${c.url ? ` (${domainOf(c.url)})` : ''}`,
      lines: [],
      startIdx: 0,
      domain: c.url ? domainOf(c.url) : '',
      globalIdxs: []
    }))
    let cum = 0
    let ci = 0
    let lineIdx = 0
    for (const line of lines) {
      while (ci + 1 < chapters.length && (chapters[ci + 1]?.word_offset ?? 0) <= cum) ci++
      const g = groups[ci]!
      if (g.lines.length === 0) g.startIdx = lineIdx
      g.lines.push(line)
      g.globalIdxs.push(lineIdx)
      cum += (line.text || '').split(/\s+/).filter(Boolean).length
      lineIdx++
    }
    const empty = groups.filter((g) => g.lines.length === 0).length
    if (empty === groups.length - 1 && groups[0]!.lines.length === lines.length) {
      const per = Math.ceil(lines.length / groups.length)
      const fallback: GroupedSection[] = []
      for (let i = 0; i < groups.length; i++) {
        const slice = lines.slice(i * per, (i + 1) * per)
        if (slice.length) {
          const idxs = slice.map((_, k) => i * per + k)
          fallback.push({ ...groups[i]!, lines: slice, startIdx: i * per, globalIdxs: idxs })
        }
      }
      return fallback.length ? fallback : groups.filter((g) => g.lines.length > 0)
    }
    return groups.filter((g) => g.lines.length > 0)
  })

  let audio: HTMLAudioElement
  let lineEls: HTMLElement[] = []
  let playing = $state(false)
  let time = $state(0)
  let dur = $state(0)
  let maxHeard = $state(0)
  const reducedMotion =
    typeof window !== 'undefined' &&
    window.matchMedia('(prefers-reduced-motion: reduce)').matches

  $effect(() => {
    if (time > maxHeard) maxHeard = time
  })

  const KARAOKE_STORAGE_KEY = 'vozonda_pref_karaoke'
  const CHAPTERS_IN_TRANSCRIPT_KEY = 'vozonda_pref_transcript_chapters'

  function readKaraokePref(): boolean {
    if (typeof localStorage === 'undefined') return true
    try {
      const v = localStorage.getItem(KARAOKE_STORAGE_KEY) ?? localStorage.getItem('vozonda_karaoke')
      if (v === '0' || v === 'false') return false
      return true
    } catch {
      return true
    }
  }

  function readChapterBreaksPref(): boolean {
    if (typeof localStorage === 'undefined') return false
    try {
      const v = localStorage.getItem(CHAPTERS_IN_TRANSCRIPT_KEY) ?? localStorage.getItem('vozonda_chapters')
      if (v === '1' || v === 'true') return true
      return false
    } catch {
      return false
    }
  }

  let karaokeEnabled = $state(readKaraokePref())
  let chapterBreaksEnabled = $state(readChapterBreaksPref())

  function setKaraoke(val: boolean) {
    karaokeEnabled = val
    try {
      localStorage.setItem(KARAOKE_STORAGE_KEY, String(val))
      localStorage.setItem('vozonda_karaoke', val ? '1' : '0')
    } catch {}
  }

  function setChapterBreaks(val: boolean) {
    chapterBreaksEnabled = val
    try {
      localStorage.setItem(CHAPTERS_IN_TRANSCRIPT_KEY, String(val))
      localStorage.setItem('vozonda_chapters', val ? '1' : '0')
    } catch {}
  }

  const AUTOSCROLL_STORAGE_KEY = 'vozonda_pref_transcript_autoscroll'
  function readAutoscrollPref(): boolean {
    if (typeof localStorage === 'undefined') return true
    try {
      const v = localStorage.getItem(AUTOSCROLL_STORAGE_KEY) ?? localStorage.getItem('vozonda_autoscroll')
      if (v === 'free' || v === 'false') return false
      return true
    } catch {
      return true
    }
  }

  let autoscrollEnabled = $state(readAutoscrollPref())
  function setAutoscroll(val: boolean) {
    autoscrollEnabled = val
    try {
      localStorage.setItem(AUTOSCROLL_STORAGE_KEY, String(val))
      localStorage.setItem('vozonda_autoscroll', val ? 'follow' : 'free')
    } catch {}
  }

  type TextSize = 'normal' | 'large' | 'compact'
  const TEXT_SIZE_STORAGE_KEY = 'vozonda_pref_transcript_size'
  function readTextSizePref(): TextSize {
    if (typeof localStorage === 'undefined') return 'normal'
    try {
      const v = localStorage.getItem(TEXT_SIZE_STORAGE_KEY) ?? localStorage.getItem('vozonda_text_size')
      return v === 'large' || v === 'compact' ? v : 'normal'
    } catch {
      return 'normal'
    }
  }

  let textSize = $state<TextSize>(readTextSizePref())
  function setTextSize(val: TextSize) {
    textSize = val
    try {
      localStorage.setItem(TEXT_SIZE_STORAGE_KEY, val)
      localStorage.setItem('vozonda_text_size', val)
    } catch {}
  }


  const voiceCount = $derived(new Set(lines.map((l) => l.speaker)).size)

  const sourceLabel = $derived.by(() => {
    const u = (sourceUrl ?? '').trim()
    if (!u) return ''
    if (/^https?:\/\//i.test(u)) {
      return u.replace(/^https?:\/\//i, '').replace(/\/$/, '')
    }
    return `pasted text · ${u.split(/\s+/).filter(Boolean).length} words`
  })

  const dateLabel = $derived.by(() => {
    if (!createdAt) return ''
    const d = new Date(createdAt * 1000)
    const now = new Date()
    const isSameYear = d.getFullYear() === now.getFullYear()
    const day = d.getDate()
    const month = d.toLocaleDateString('en-US', { month: 'short' })
    const time = d.toLocaleTimeString('en-US', { hour: '2-digit', minute: '2-digit', hour12: false })
    const datePart = isSameYear ? `${day} ${month}` : `${day} ${month} ${d.getFullYear()}`
    return `${datePart} · ${time}`
  })

  const wordCount = $derived(
    lines.reduce((n, l) => n + l.text.split(/\s+/).filter(Boolean).length, 0)
  )

  const tuningLabel = $derived.by(() => {
    if (!jobTuning) return ''
    const parts: string[] = []
    if (jobTuning.speed !== undefined && Math.abs(jobTuning.speed - 1) > 0.01) parts.push(`${jobTuning.speed}x speed`)
    if (jobTuning.emotion && jobTuning.emotion !== 'neutral') parts.push(`${jobTuning.emotion}`)
    if (jobTuning.gap_ms) parts.push(`${jobTuning.gap_ms}ms gaps`)
    return parts.join(' · ')
  })

  const voicesLabel = $derived(
    jobVoices?.length
      ? jobVoices.join(' + ')
      : `${voiceCount} ${voiceCount === 1 ? 'narrator' : 'hosts'}`
  )

  // DUE-078: burned-in display names, shown only when they exist so the
  // facts never duplicate the technical timbre line above
  const castLabel = $derived.by(() => {
    const names: string[] = []
    for (const l of lines) {
      if (l.name && !names.includes(l.name)) names.push(l.name)
    }
    return names.length > 0 ? names.join(' · ') : ''
  })

  const hostByLabel = $derived.by(() => {
    if (castLabel) return `by: ${castLabel.replace(/ · /g, ' & ').toLowerCase()}`
    if (jobVoices?.length) return `by: ${jobVoices.join(' & ')}`
    return `by: ${voiceCount === 1 ? 'narrator' : `${voiceCount} hosts`}`
  })

  const languageFact = $derived.by(() => {
    const jobLangName = jobLanguage && jobLanguage !== 'auto' ? LANG_NAMES[jobLanguage] ?? jobLanguage : null
    const srcLangName = sourceLang && sourceLang !== 'auto' ? LANG_NAMES[sourceLang] ?? sourceLang : null

    if (jobLangName && srcLangName && jobLanguage !== sourceLang) {
      return `${jobLangName} (translated from ${srcLangName} source)`
    }
    if (jobLangName) {
      return `${jobLangName} (source language)`
    }
    if (srcLangName) {
      return `${srcLangName} (source language)`
    }
    return 'original source language'
  })

  const audioLabel = $derived.by(() => {
    if (!jobAudio?.bytes) {
      return jobTuning?.music_bed ? 'MP3 audio · intro song' : 'MP3 audio'
    }
    const mb = (jobAudio.bytes / (1024 * 1024)).toFixed(1)
    const parts = [`${mb} MB`, `${jobAudio.kbps} kbps`]
    if (jobAudio.sample_rate) parts.push(`${(jobAudio.sample_rate / 1000).toFixed(1)} kHz`)
    if (jobTuning?.music_bed) parts.push('intro song')
    return parts.join(' · ')
  })

  const llmFact = $derived.by(() => {
    const scriptMeta = jobStages?.find((s) => s.name === 'script')?.meta as Record<string, unknown> | undefined
    if (scriptMeta?.llm_model) {
      return `${String(scriptMeta.llm_model)} (${String(scriptMeta.llm_provider || 'local')})`
    }
    const prov = (jobProvider || '').toLowerCase()
    if (prov === 'mistral') return 'mistral-small-4 (sglang :30000)'
    if (prov === 'claude') return 'claude-3.7-sonnet'
    if (prov) return `${prov} (local)`
    return 'local model (your endpoint)'
  })

  const ttsFact = $derived.by(() => {
    const voiceStage = jobStages?.find((s) => s.name === 'voice')
    const voiceMeta = voiceStage?.meta as Record<string, unknown> | undefined
    if (voiceMeta?.engine) {
      return `${String(voiceMeta.engine).replace('_', '-')} (local)`
    }
    if (voiceStage?.detail) {
      const match = voiceStage.detail.match(/via\s+([a-zA-Z0-9_-]+)/i)
      if (match?.[1]) return `${match[1].replace('_', '-')} (local)`
    }
    return 'qwen-tts (local torch)'
  })

  const musicBedFact = $derived.by(() => {
    if (jobTuning?.music_bed === true) return 'intro & outro song (music bed active)'
    if (jobTuning?.music_bed === false) return 'off (speech only, no music bed)'
    return 'off (speech only)'
  })

  const mp3QualityFact = $derived.by(() => {
    const kbps = jobAudio?.kbps || 128
    const sr = jobAudio?.sample_rate ? `${(jobAudio.sample_rate / 1000).toFixed(1)} kHz` : '48.0 kHz'
    const mb = jobAudio?.bytes ? `${(jobAudio.bytes / (1024 * 1024)).toFixed(1)} MB` : ''
    const parts = [`${kbps} kbps MP3`, sr]
    if (mb) parts.push(mb)
    parts.push('stereo loudnorm')
    return parts.join(' · ')
  })

  const stageTimingsFact = $derived.by(() => {
    if (!jobStages?.length) return ''
    const parts: string[] = []
    for (const name of ['script', 'voice', 'master'] as const) {
      const st = jobStages.find((s) => s.name === name)
      if (st?.ms && st.ms > 0) {
        parts.push(`${name} ${(st.ms / 1000).toFixed(0)}s`)
      }
    }
    return parts.length > 0 ? parts.join(' · ') : ''
  })

  const pacingFact = $derived.by(() => {
    const parts: string[] = []
    if (jobTuning?.speed !== undefined) parts.push(`${jobTuning.speed}x speed`)
    if (jobTuning?.gap_ms !== undefined) parts.push(`${jobTuning.gap_ms}ms turn gap`)
    if (jobTuning?.emotion && jobTuning.emotion !== 'neutral') parts.push(`emotion: ${jobTuning.emotion}`)
    if (jobTone && jobTone !== 'neutral') parts.push(`tone: ${jobTone}`)
    if (jobExplicit) parts.push('explicit: on')
    return parts.join(' · ')
  })

  const styleDocFact = $derived.by(() => {
    const s = jobStyle || 'balanced'
    return styleDocFor(s, { style_meta: metaStyleMeta ?? undefined, style_docs: metaStyleDocs ?? undefined }) ?? ''
  })

  const episodeUrlForHighlights = $derived.by(() => {
    const u = (sourceUrl ?? '').trim()
    if (/^https?:\/\//i.test(u)) return u
    if (jobId) {
      return `${window.location.origin}/e/${jobId}`
    }
    return u || `${window.location.origin}/`
  })

  const transcriptPlainText = $derived(lines.map((l) => l.text).join('\n').slice(0, 8000))

  const activeIdx = $derived.by(() => {
    if (!lines[0] || lines[0].t0 === undefined) return -1
    let idx = -1
    for (let i = 0; i < lines.length; i++) {
      const t0 = lines[i]?.t0 ?? Infinity
      if (t0 <= time) idx = i
      else break
    }
    return idx
  })

  $effect(() => {
    const el = lineEls[activeIdx]
    if (el && playing && autoscrollEnabled) {
      el.scrollIntoView({
        block: 'nearest',
        behavior: reducedMotion ? 'auto' : 'smooth'
      })
    }
  })

  function lineLabel(spk: string): string {
    if (spk === 'A' || spk === 'B') {
      const name = jobVoiceMap?.[spk]
      return name ? `${spk} · ${name}` : spk === 'A' ? 'A' : 'B'
    }
    if (/narrat/i.test(spk)) return 'narrator'
    return jobVoiceMap?.[spk] ?? spk
  }

  function labelFor(line: DialogueLine): string {
    // custom host name (#76) replaces the letter label when present
    return line.name || lineLabel(line.speaker)
  }

  function fmt(s: number): string {
    const m = Math.floor(s / 60)
    const r = Math.floor(s % 60)
    return `${m}:${r.toString().padStart(2, '0')}`
  }

  const SPEEDS = [1, 1.25, 1.5, 2, 0.8]
  const SPEED_STORAGE_KEY = 'vozonda_player_speed'
  function readDefaultSpeedIdx(): number {
    if (typeof localStorage === 'undefined') return 0
    try {
      const v = localStorage.getItem(SPEED_STORAGE_KEY)
      if (v) {
        const num = Number(v)
        const idx = SPEEDS.indexOf(num)
        if (idx !== -1) return idx
      }
    } catch {}
    return 0
  }
  let speedIdx = $state(readDefaultSpeedIdx())
  const currentSpeed = $derived(SPEEDS[speedIdx] ?? 1)
  let showPlayerMenu = $state(false)

  function setSpeed(spd: number) {
    const idx = SPEEDS.indexOf(spd)
    if (idx !== -1) speedIdx = idx
    if (audio) {
      audio.playbackRate = spd
    }
    try {
      localStorage.setItem(SPEED_STORAGE_KEY, String(spd))
    } catch {}
  }

  function cycleSpeed() {
    speedIdx = (speedIdx + 1) % SPEEDS.length
    const spd = SPEEDS[speedIdx] ?? 1
    if (audio) {
      audio.playbackRate = spd
    }
    try {
      localStorage.setItem(SPEED_STORAGE_KEY, String(spd))
    } catch {}
  }

  function jump(deltaSecs: number) {
    if (audio) {
      audio.currentTime = Math.max(0, Math.min(dur || Infinity, audio.currentTime + deltaSecs))
    }
  }

  // --- V4V split helper (Host, Source Author, Sovereign Node) ---
  type SplitRecipient = { address: string; sats: number; name: string; split: number }
  function buildV4VRecipients(totalSats: number): SplitRecipient[] {
    if (!valueTip) return []
    const creatorAddr = (valueTip.creatorAddress ?? valueTip.address ?? '').trim()
    const sourceAddr = (valueTip.sourceAddress ?? '').trim()
    const appAddr = (valueTip.appAddress ?? '').trim()
    const creatorSplit = Number(valueTip.creatorSplit ?? valueTip.split ?? 70)
    const sourceSplit = Number(valueTip.sourceSplit ?? 20)
    const appSplit = Number(valueTip.appSplit ?? 10)
    const raw: Array<{ name: string; address: string; split: number }> = [
      { name: 'creator', address: creatorAddr, split: creatorSplit },
      { name: 'source', address: sourceAddr, split: sourceSplit },
      { name: 'app', address: appAddr, split: appSplit }
    ].filter((r) => !!r.address && r.split > 0)
    if (raw.length === 0 && creatorAddr) raw.push({ name: 'creator', address: creatorAddr, split: 100 })
    if (raw.length === 0) return []
    // Normalize to 100 if sum !=100 (auto-balance like feed.xml does via presets)
    let totalSplit = raw.reduce((a, r) => a + r.split, 0)
    if (!totalSplit) totalSplit = 100
    let satsAlloc: number[] = raw.map((r) => Math.floor((totalSats * r.split) / totalSplit))
    let allocated = satsAlloc.reduce((a, b) => a + b, 0)
    let remainder = totalSats - allocated
    // distribute remainder to largest split recipients first
    const order = raw.map((_, i) => i).sort((a, b) => (raw[b]?.split ?? 0) - (raw[a]?.split ?? 0))
    for (let i = 0; i < remainder; i++) {
      const idx = order[i % order.length]
      if (idx !== undefined) satsAlloc[idx] = (satsAlloc[idx] ?? 0) + 1
    }
    return raw.map((r, i) => ({ address: r.address, sats: satsAlloc[i] ?? 0, name: r.name, split: r.split }))
  }

  async function payV4VSplits(totalSats: number, comment: string): Promise<void> {
    const recipients = buildV4VRecipients(totalSats)
    if (recipients.length === 0) throw new Error('no lightning address configured (set Creator/App address in settings)')
    if (!hasAnyWallet()) throw new Error('no wallet connected (enable WebLN/Alby or set NWC)')
    for (const r of recipients) {
      if (r.sats <= 0) continue
      const note = recipients.length > 1 ? `${comment} [${r.name} ${r.split}%]` : comment
      await quickZap(r.address, r.sats, note, ['wss://relay.damus.io', 'wss://nos.lol'], undefined, jobId ?? undefined)
    }
  }

  async function handleBoost(amount: number) {
    if (boostBusy) return
    const sats = Math.max(1, Math.round(amount))
    const rawNote = boostNote.trim()
    const note = rawNote || `Boost ${sats} sats at ${fmt(time)}`
    // If no wallet or no recipients, fall back to full ZapModal (supports copy invoice)
    const recipients = buildV4VRecipients(sats)
    const canPayDirect = recipients.length > 0 && hasAnyWallet()
    if (!canPayDirect) {
      zapInitialSats = sats
      zapInitialComment = note
      zapTimestamp = Math.round(time)
      zapOpen = true
      return
    }
    boostBusy = true
    boostError = ''
    boostFeedback = ''
    try {
      await payV4VSplits(sats, note)
      streamingTotalSats += 0 // keep type
      if (jobId) {
        recordEpisodeBoost({
          id: `boost-${Date.now()}`,
          episodeId: jobId,
          sats,
          comment: note,
          timestampSeconds: Math.round(time),
          createdAt: Date.now()
        })
        // refresh local counters
        zappedSats = getEpisodeZappedSats(jobId)
        zapCount = getEpisodeZapCount(jobId)
      }
      boostFeedback = `boosted ${sats} sats`
      setTimeout(() => (boostFeedback = ''), 3000)
    } catch (e) {
      boostError = e instanceof Error ? e.message : String(e)
      // On pay failure, offer modal as fallback so user can still copy invoice
      // Keep error visible for 4s
      setTimeout(() => (boostError = ''), 4000)
    } finally {
      boostBusy = false
    }
  }

  function triggerQuickZap(amount: number) {
    void handleBoost(amount)
  }

  function toggleStreamingSats() {
    streamingSats = !streamingSats
    if (streamingSats) {
      startStreaming()
    } else {
      stopStreaming()
    }
  }

  function startStreaming() {
    if (streamingInterval) clearInterval(streamingInterval)
    if (!valueTip || (!valueTip.address && !valueTip.creatorAddress && !valueTip.appAddress && !valueTip.sourceAddress)) {
      boostError = 'set lightning addresses in settings to enable streaming'
      streamingSats = false
      setTimeout(() => (boostError = ''), 4000)
      return
    }
    if (!hasAnyWallet()) {
      boostError = 'connect WebLN (Alby) or NWC to stream sats'
      streamingSats = false
      setTimeout(() => (boostError = ''), 4000)
      return
    }
    const satsPerMin = Math.max(1, Math.min(100, Math.round(streamingRate || getStreamSatsPerMin())))
    streamingTotalSats = 0
    async function sendOne() {
      try {
        await payV4VSplits(satsPerMin, `Stream ${satsPerMin} sats/min at ${fmt(time)}`)
        streamingTotalSats += satsPerMin
        if (jobId)
          recordEpisodeBoost({
            id: `boost-stream-${Date.now()}`,
            episodeId: jobId,
            sats: satsPerMin,
            comment: `streaming ${satsPerMin} sats/min`,
            timestampSeconds: Math.round(time),
            createdAt: Date.now()
          })
        if (jobId) {
          zappedSats = getEpisodeZappedSats(jobId)
          zapCount = getEpisodeZapCount(jobId)
        }
      } catch {
        // silent fail - stream continues; surface one-time error if needed
      }
    }
    // Pay immediately on toggle, then every 60s while playing
    void sendOne()
    streamingInterval = setInterval(() => {
      if (!streamingSats || !playing) return
      void sendOne()
    }, 60000)
  }

  function stopStreaming() {
    if (streamingInterval) {
      clearInterval(streamingInterval)
      streamingInterval = null
    }
  }

  function handleStreamingRateInput(val: string) {
    const n = Math.max(1, Math.min(100, Math.round(Number(val) || 10)))
    streamingRate = n
    setStreamSatsPerMin(n)
  }

  async function retryNostrPublish() {
    if (!jobId || nostrPublishBusy) return
    nostrPublishBusy = true
    nostrPublishError = ''
    try {
      const res = await fetch(`/jobs/${jobId}/nostr/publish`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' }
      })
      if (!res.ok) throw new Error(`HTTP ${res.status}`)
      nostrPublishStatus = 'published'
    } catch (err) {
      nostrPublishStatus = 'failed'
      nostrPublishError = err instanceof Error ? err.message : 'publish failed'
    } finally {
      nostrPublishBusy = false
    }
  }

  function seekTakeaway(tk: import('../api').KeyTakeaway, idx: number) {
    let targetTime = 0
    let targetIdx = -1

    if (typeof tk.timestamp_ms === 'number' && tk.timestamp_ms >= 0) {
      targetTime = tk.timestamp_ms / 1000
    } else if (typeof tk.section_idx === 'number' && lines[tk.section_idx]?.t0 !== undefined) {
      targetTime = lines[tk.section_idx]?.t0 ?? 0
      targetIdx = tk.section_idx
    } else if (lines.length > 0) {
      const lineIdx = Math.min(lines.length - 1, Math.floor(idx * (lines.length / Math.max(1, keyTakeaways?.length ?? 1))))
      targetTime = lines[lineIdx]?.t0 ?? 0
      targetIdx = lineIdx
    }

    seekTo(targetTime)
    activeTab = 'transcript'

    setTimeout(() => {
      let finalIdx = targetIdx
      if (finalIdx < 0) {
        finalIdx = lines.findIndex((l) => (l.t0 ?? 0) >= targetTime)
      }
      const resolvedIdx = finalIdx >= 0 ? finalIdx : 0
      const el = lineEls[resolvedIdx]
      if (el) {
        el.scrollIntoView({
          block: 'center',
          behavior: reducedMotion ? 'auto' : 'smooth'
        })
      }
    }, 60)
  }

  async function copySummaryMarkdown() {
    const parts: string[] = []
    if (title) parts.push(`# ${title}\n`)
    if (executiveSummary) parts.push(`> ${executiveSummary}\n`)
    if (keyTakeaways && keyTakeaways.length > 0) {
      parts.push('## Key Takeaways\n')
      for (const tk of keyTakeaways) {
        parts.push(`- **${tk.title}** (${tk.time_formatted || ''}): ${tk.text}`)
      }
    }
    const md = parts.join('\n')
    try {
      await navigator.clipboard.writeText(md)
      copiedSummary = true
      setTimeout(() => (copiedSummary = false), 2000)
    } catch {}
  }

  function shareNostrDraft() {
    const parts: string[] = []
    if (title) parts.push(title)
    if (executiveSummary) parts.push(`TL;DR: ${executiveSummary}`)
    if (keyTakeaways && keyTakeaways.length > 0) {
      parts.push('')
      for (const tk of keyTakeaways.slice(0, 5)) {
        parts.push(`• ${tk.title}: ${tk.text.slice(0, 90)}${tk.text.length > 90 ? '...' : ''} [${tk.time_formatted || '00:00'}]`)
      }
    }
    parts.push('')
    try { parts.push(window.location.href) } catch {}
    parts.push('\n#vozonda #podcast #keytakeaways')
    const text = parts.join('\n')
    try {
      navigator.clipboard.writeText(text)
      copiedSummary = true
      setTimeout(() => (copiedSummary = false), 2000)
    } catch {}
  }

  function handleClipAndBoost() {
    if (sliceDraft) {
      zapInitialSats = 100
      zapInitialComment = `Clipped snippet: "${sliceDraft.textSnippet.slice(0, 50)}..."`
      const t0 = lines[sliceDraft.turnStart]?.t0
      zapTimestamp = typeof t0 === 'number' ? Math.round(t0) : Math.round(time)
      zapOpen = true
    }
  }

  function getWordState(lineText: string, t0: number | undefined, nextT0: number | undefined, currentTime: number) {
    const rawWords = lineText.split(/\s+/).filter(Boolean)
    if (t0 === undefined || currentTime < t0) {
      return { words: rawWords, activeIdx: -1 }
    }
    const tEnd = nextT0 ?? (t0 + Math.max(1.5, rawWords.length * 0.35))
    const lineDur = Math.max(0.2, tEnd - t0)
    const elapsed = Math.max(0, currentTime - t0)
    const progress = Math.min(1, elapsed / lineDur)

    let totalChars = 0
    const charBounds: number[] = []
    for (const w of rawWords) {
      totalChars += Math.max(1, w.length)
      charBounds.push(totalChars)
    }
    const targetChar = progress * totalChars
    let activeIdx = 0
    for (let w = 0; w < charBounds.length; w++) {
      if (targetChar <= charBounds[w]!) {
        activeIdx = w
        break
      }
    }
    return { words: rawWords, activeIdx }
  }

  let copiedTranscript = $state(false)
  let copyTimeout: ReturnType<typeof setTimeout> | null = null

  function copyTranscript() {
    const text = lines.map((l) => `${labelFor(l)}: ${l.text}`).join('\n\n')
    if (navigator.clipboard) {
      void navigator.clipboard.writeText(text).then(() => {
        copiedTranscript = true
        if (copyTimeout) clearTimeout(copyTimeout)
        copyTimeout = setTimeout(() => {
          copiedTranscript = false
        }, 2000)
      })
    }
  }

  let resumedHint = $state('')
  let resumeTimer: ReturnType<typeof setTimeout> | undefined

  type SleepMode = 'off' | '15' | '30' | '45' | 'end'
  let sleepMode = $state<SleepMode>('off')
  let sleepRemaining = $state(0)
  let sleepInterval: ReturnType<typeof setInterval> | undefined

  let copiedTurnIdx = $state<number | null>(null)
  let copyTurnTimer: ReturnType<typeof setTimeout> | undefined

  function fmtSleep(s: number): string {
    const m = Math.floor(s / 60)
    const r = Math.floor(s % 60)
    return `${m}:${r.toString().padStart(2, '0')}`
  }

  function setSleepTimer(mode: SleepMode) {
    sleepMode = mode
    if (sleepInterval) clearInterval(sleepInterval)
    if (mode === 'off') {
      sleepRemaining = 0
      if (audio) audio.volume = 1.0
      return
    }
    if (mode === 'end') {
      sleepRemaining = dur > 0 ? Math.max(1, Math.round(dur - time)) : 600
    } else {
      sleepRemaining = parseInt(mode, 10) * 60
    }

    sleepInterval = setInterval(() => {
      if (!playing) return
      sleepRemaining--
      if (sleepRemaining <= 3 && sleepRemaining > 0 && audio) {
        audio.volume = Math.max(0, sleepRemaining / 3)
      }
      if (sleepRemaining <= 0) {
        if (sleepInterval) clearInterval(sleepInterval)
        if (audio) {
          audio.pause()
          audio.volume = 1.0
        }
        sleepMode = 'off'
        sleepRemaining = 0
      }
    }, 1000)
  }

  function copyTurnLink(e: MouseEvent, line: DialogueLine, idx: number) {
    e.stopPropagation()
    const tSec = Math.round(line.t0 ?? 0)
    const base = window.location.origin + window.location.pathname
    const link = `${base}#e=${jobId}&t=${tSec}`
    if (navigator.clipboard) {
      void navigator.clipboard.writeText(link).then(() => {
        copiedTurnIdx = idx
        if (copyTurnTimer) clearTimeout(copyTurnTimer)
        copyTurnTimer = setTimeout(() => (copiedTurnIdx = null), 2000)
      })
    }
  }

  async function copyClipUrl(e: MouseEvent, idx: number) {
    e.stopPropagation()
    const clip = clips[idx]
    if (!clip) return
    const url = clipShareUrl(clip)
    if (!url) return
    if (typeof navigator !== 'undefined' && typeof navigator.share === 'function') {
      try {
        await navigator.share({
          title: clipLabel(clip),
          text: `Clip from ${title || 'Vozonda'}`,
          url
        })
        return
      } catch {
        // user cancelled or share failed; proceed to clipboard copy
      }
    }
    if (navigator.clipboard) {
      void navigator.clipboard.writeText(url).then(() => {
        clipCopiedIdx = idx
        const t = setTimeout(() => { clipCopiedIdx = null }, 2000)
        clipCopyTimers.push(t)
      })
    }
  }

  onMount(() => {
    // 1. Resume playback position from localStorage (#162)
    if (jobId) {
      try {
        const saved = localStorage.getItem(`vozonda_pos_${jobId}`)
        if (saved) {
          const parsed = parseFloat(saved)
          if (parsed > 3) {
            time = parsed
            if (audio) audio.currentTime = parsed
            resumedHint = `resumed at ${fmt(parsed)}`
            resumeTimer = setTimeout(() => (resumedHint = ''), 3500)
          }
        }
      } catch {}
    }

    // 2. Check for URL timestamp #e=...&t=45 (#164)
    if (typeof window !== 'undefined') {
      const match = location.hash.match(/[&#]t=(\d+(?:\.\d+)?)/)
      if (match && match[1]) {
        const seekTime = parseFloat(match[1])
        if (seekTime >= 0) {
          seekTo(seekTime)
        }
      }
    }

    // 3. Load clips for this job (#184 / DUE-020)
    if (jobId) {
      void refreshClips()
    }

    // 4. The header h1 (App.svelte) shows the title; rename lives in the facts tab
    // (operator 2026-10-02: not below the title) and updates the h1 after a save
    const h1 = document.querySelector('header h1') as HTMLElement | null
    if (h1) {
      headerH1El = h1
      headerH1Found = true
    }

    return () => {
      if (sleepInterval) clearInterval(sleepInterval)
      if (resumeTimer) clearTimeout(resumeTimer)
      if (copyTurnTimer) clearTimeout(copyTurnTimer)
      for (const t of clipCopyTimers) clearTimeout(t)
      if (slicePreviewTimer) clearTimeout(slicePreviewTimer)
      if (hlCopyTimer) clearTimeout(hlCopyTimer)
      stopStreaming()
    }
  })

  // Throttled position saving to localStorage (#162)
  let lastSave = 0
  $effect(() => {
    if (!jobId || time <= 0) return
    const now = Date.now()
    if (now - lastSave > 2000) {
      lastSave = now
      try {
        if (dur > 0 && time >= dur - 2) {
          localStorage.removeItem(`vozonda_pos_${jobId}`)
        } else {
          localStorage.setItem(`vozonda_pos_${jobId}`, time.toFixed(1))
        }
      } catch {}
    }
  })

  // MediaSession API (#161)
  $effect(() => {
    if (typeof navigator !== 'undefined' && 'mediaSession' in navigator) {
      navigator.mediaSession.metadata = new MediaMetadata({
        title: title || 'vozonda episode',
        artist: voicesLabel || 'vozonda voices',
        album: 'vozonda · self-hosted audio',
        artwork: [
          { src: '/icon-192.png', sizes: '192x192', type: 'image/png' },
          { src: '/icon-512.png', sizes: '512x512', type: 'image/png' }
        ]
      })

      navigator.mediaSession.setActionHandler('play', () => {
        if (audio && audio.paused) void audio.play()
      })
      navigator.mediaSession.setActionHandler('pause', () => {
        if (audio && !audio.paused) audio.pause()
      })
      navigator.mediaSession.setActionHandler('seekbackward', (details) => {
        const offset = details.seekOffset || 10
        if (audio) audio.currentTime = Math.max(0, audio.currentTime - offset)
      })
      navigator.mediaSession.setActionHandler('seekforward', (details) => {
        const offset = details.seekOffset || 10
        if (audio) audio.currentTime = Math.min(dur || Infinity, audio.currentTime + offset)
      })
      navigator.mediaSession.setActionHandler('seekto', (details) => {
        if (audio && details.seekTime !== undefined) {
          audio.currentTime = details.seekTime
        }
      })
      navigator.mediaSession.setActionHandler('previoustrack', () => {
        const prevIdx = activeIdx > 0 ? activeIdx - 1 : 0
        const prevLine = lines[prevIdx]
        if (prevLine && prevLine.t0 !== undefined) seekTo(prevLine.t0)
        else if (onPrev) onPrev()
      })
      navigator.mediaSession.setActionHandler('nexttrack', () => {
        const nextIdx = activeIdx + 1 < lines.length ? activeIdx + 1 : activeIdx
        const nextLine = lines[nextIdx]
        if (nextLine && nextLine.t0 !== undefined) seekTo(nextLine.t0)
        else if (onNext) onNext()
      })
    }
  })

  // Sync position state with MediaSession (#161)
  $effect(() => {
    if (typeof navigator !== 'undefined' && 'mediaSession' in navigator && dur > 0) {
      try {
        navigator.mediaSession.setPositionState({
          duration: dur,
          playbackRate: currentSpeed,
          position: Math.min(dur, Math.max(0, time))
        })
      } catch {}
    }
  })

  function toggle() {
    if (!audio) return
    if (audio.paused) void audio.play()
    else audio.pause()
  }

  function seekFraction(f: number) {
    if (audio && dur > 0) audio.currentTime = f * dur
  }

  function seekTo(t?: number) {
    if (audio && t !== undefined) {
      audio.currentTime = Math.min(t, dur)
      void audio.play()
    }
  }

  function handleChapterClick(c: { index: number; title: string; t?: number }) {
    if (c.t !== undefined) {
      seekTo(c.t)
      activeTab = 'transcript'
      setTimeout(() => {
        const targetIdx = lines.findIndex((l) => (l.t0 ?? 0) >= (c.t ?? 0))
        const idx = targetIdx >= 0 ? targetIdx : 0
        const el = lineEls[idx]
        if (el) {
          el.scrollIntoView({
            block: 'center',
            behavior: reducedMotion ? 'auto' : 'smooth'
          })
        }
      }, 60)
    }
  }

  function handleKey(e: KeyboardEvent) {
    const t = e.target as HTMLElement | null
    if (t && (t.tagName === 'INPUT' || t.tagName === 'TEXTAREA' || t.tagName === 'SELECT' || t.isContentEditable)) return
    if (e.key === ' ' || e.code === 'Space') {
      // space toggles play/pause without scrolling
      e.preventDefault()
      toggle()
    } else if (e.key === 'ArrowLeft') {
      if (audio && dur > 0) {
        e.preventDefault()
        audio.currentTime = Math.max(0, audio.currentTime - 5)
      }
    } else if (e.key === 'ArrowRight') {
      if (audio && dur > 0) {
        e.preventDefault()
        audio.currentTime = Math.min(dur, audio.currentTime + 5)
      }
    } else if (e.key === 'ArrowUp') {
      e.preventDefault()
      const prevIdx = activeIdx > 0 ? activeIdx - 1 : 0
      const prevLine = lines[prevIdx]
      if (prevLine && prevLine.t0 !== undefined) {
        seekTo(prevLine.t0)
      }
    } else if (e.key === 'ArrowDown') {
      e.preventDefault()
      const nextIdx = activeIdx + 1 < lines.length ? activeIdx + 1 : activeIdx
      const nextLine = lines[nextIdx]
      if (nextLine && nextLine.t0 !== undefined) {
        seekTo(nextLine.t0)
      }
    } else if (e.key === 's' || e.key === 'S') {
      e.preventDefault()
      cycleSpeed()
    } else if (e.key === 'j') {
      if (onNext) {
        e.preventDefault()
        onNext()
      }
    } else if (e.key === 'k') {
      if (onPrev) {
        e.preventDefault()
        onPrev()
      }
    }
  }
</script>

<svelte:window onkeydown={handleKey} />

<article class="listen">
  <div class="episode-title-area" class:attached={headerH1Found}>
    {#if !headerH1Found}
      <div class="standalone-title">{currentTitle}</div>
    {/if}
  </div>

  <div class="mono meta">
    <div class="meta-left">
      {#if watchlistId}
        <span class="mono badge-watchlist" title="Generated automatically from watchlist feed">
          <Icon name="rss" size={11} /> watchlist
        </span>
      {/if}
      <span class="meta-date">{dateLabel}</span>
    </div>

    {#if boostVariant === 'meta'}
      <div class="meta-boost">
        <button
          type="button"
          class="meta-boost-pill meta-boost-primary"
          onclick={() => triggerQuickZap(100)}
          disabled={boostBusy}
          aria-label="Boost 100 sats"
          title="1-click boost 100 sats via WebLN/NWC with splits"
        >
          <Icon name="zap" size={11} /> +100 sats
        </button>
        <button
          type="button"
          class="meta-boost-pill meta-boost-more"
          onclick={() => (zapOpen = true)}
          title="Open boost modal with custom amount, recipient splits and NIP-57 receipt"
          aria-label="Custom boost"
        >
          boost...
        </button>
        {#if boostBusy}
          <span class="meta-boost-status" role="status" aria-live="polite">paying...</span>
        {:else if boostFeedback}
          <span class="meta-boost-status ok" role="status" aria-live="polite">{boostFeedback}</span>
        {:else if boostError}
          <span class="meta-boost-status err" role="alert">{boostError}</span>
        {/if}
      </div>
    {/if}
  </div>

  <div class="player-wrap" class:has-cover={!!coverSrc}>
    {#if coverSrc}
      <div class="ambient-backdrop" aria-hidden="true">
        <img
          src={coverSrc}
          alt=""
          class="ambient-img"
          onerror={() => (imageFailed = true)}
        />
        <div class="ambient-overlay"></div>
      </div>
    {/if}
    <div class="player-inner">
      <div class="player-main">
        <div class="player-top-row">
          <button class="play" onclick={toggle} aria-label={playing ? 'Pause' : 'Play'}>
            <Icon name={playing ? 'pausebars' : 'playtri'} size={20} />
          </button>
          <div class="player-meta-block mono">
            <span class="player-voices">{hostByLabel}</span>
            {#if resumedHint}
              <span class="resume-hint" role="status" aria-live="polite">{resumedHint}</span>
            {/if}
          </div>
        </div>

        <div class="player-waveform-row">
          <Waveform
            {src}
            currentTime={time}
            {playing}
            onseek={seekFraction}
            pins={waveformPins}
          />
        </div>

        <div class="player-controls mono">
          <span class="time">{fmt(time)} / {fmt(Math.round(dur))}</span>
          <div class="player-controls-right">
            {#if sleepMode !== 'off' && sleepRemaining > 0}
              <button
                type="button"
                class="sleep-indicator"
                onclick={() => (showPlayerMenu = true)}
                title="Sleep timer active. Click to adjust."
              >
                <Icon name="moon" size={11} /> {fmtSleep(sleepRemaining)}
              </button>
            {/if}
            <button
              type="button"
              class="speed-btn"
              onclick={cycleSpeed}
              title="Playback speed (click to cycle, shortcut: s)"
              aria-label={`Playback speed ${currentSpeed}x`}
            >
              {currentSpeed}x
            </button>
            <button
              type="button"
              class="opt-btn"
              class:open={showPlayerMenu}
              onclick={() => (showPlayerMenu = !showPlayerMenu)}
              title="Player and transcript options"
              aria-label="Player and transcript options"
              aria-expanded={showPlayerMenu}
            >
              <Icon name="sliders" size={13} /> <span>options</span>
            </button>
          </div>
        </div>
      </div>

      {#if coverSrc}
        <div class="player-cover">
          <img
            src={coverSrc}
            alt="Episode cover"
            class="cover-art"
            onerror={() => (imageFailed = true)}
          />
        </div>
      {/if}
    </div>

    {#if showPlayerMenu}
      <div class="player-menu mono" role="region" aria-label="Player and transcript options">
        <div class="menu-sec-title">// playback</div>
        <div class="menu-row">
          <span class="menu-lab">speed</span>
          <div class="menu-chips">
            {#each SPEEDS as spd}
              <button
                type="button"
                class="menu-chip"
                class:active={currentSpeed === spd}
                onclick={() => setSpeed(spd)}
              >
                {spd}x
              </button>
            {/each}
          </div>
        </div>
        <div class="menu-row">
          <span class="menu-lab">jump</span>
          <div class="menu-chips">
            <button type="button" class="menu-chip" onclick={() => jump(-15)}>
              <Icon name="rewind" size={12} /> -15s
            </button>
            <button type="button" class="menu-chip" onclick={() => jump(15)}>
              <Icon name="forward" size={12} /> +15s
            </button>
          </div>
        </div>
        <div class="menu-row">
          <span class="menu-lab">sleep</span>
          <div class="menu-chips">
            {#each ['off', '15', '30', '45', 'end'] as const as sm}
              <button
                type="button"
                class="menu-chip"
                class:active={sleepMode === sm}
                onclick={() => setSleepTimer(sm)}
              >
                {sm === 'off' ? 'off' : sm === 'end' ? 'end' : `${sm}m`}
              </button>
            {/each}
            {#if sleepMode !== 'off' && sleepRemaining > 0}
              <span class="sleep-countdown">{fmtSleep(sleepRemaining)}</span>
            {/if}
          </div>
        </div>

        <div class="menu-sec-title">// transcript</div>
        <div class="menu-row">
          <span class="menu-lab">karaoke</span>
          <div class="menu-chips">
            <button
              type="button"
              class="menu-chip"
              class:active={karaokeEnabled}
              onclick={() => setKaraoke(true)}
              aria-pressed={karaokeEnabled}
            >
              on
            </button>
            <button
              type="button"
              class="menu-chip"
              class:active={!karaokeEnabled}
              onclick={() => setKaraoke(false)}
              aria-pressed={!karaokeEnabled}
            >
              off
            </button>
            <span class="menu-hint">real-time word follow</span>
          </div>
        </div>

        {#if isDigestEpisode || (chapters && chapters.length > 1)}
          <div class="menu-row">
            <span class="menu-lab">chapters</span>
            <div class="menu-chips">
              <button
                type="button"
                class="menu-chip"
                class:active={chapterBreaksEnabled}
                onclick={() => setChapterBreaks(true)}
                aria-pressed={chapterBreaksEnabled}
              >
                on
              </button>
              <button
                type="button"
                class="menu-chip"
                class:active={!chapterBreaksEnabled}
                onclick={() => setChapterBreaks(false)}
                aria-pressed={!chapterBreaksEnabled}
              >
                off
              </button>
              <span class="menu-hint">section headers in text</span>
            </div>
          </div>
        {/if}

        <div class="menu-row">
          <span class="menu-lab">autoscroll</span>
          <div class="menu-chips">
            <button
              type="button"
              class="menu-chip"
              class:active={autoscrollEnabled}
              onclick={() => setAutoscroll(true)}
              aria-pressed={autoscrollEnabled}
            >
              follow
            </button>
            <button
              type="button"
              class="menu-chip"
              class:active={!autoscrollEnabled}
              onclick={() => setAutoscroll(false)}
              aria-pressed={!autoscrollEnabled}
            >
              free
            </button>
            <span class="menu-hint">keep current turn in view</span>
          </div>
        </div>

        <div class="menu-row">
          <span class="menu-lab">text size</span>
          <div class="menu-chips">
            {#each ['normal', 'large', 'compact'] as const as sz}
              <button
                type="button"
                class="menu-chip"
                class:active={textSize === sz}
                onclick={() => setTextSize(sz)}
              >
                {sz}
              </button>
            {/each}
          </div>
        </div>

        <div class="menu-sec-title">// more</div>
        <div class="menu-row">
          <span class="menu-lab">specs</span>
          <div class="menu-chips">
            <button
              type="button"
              class="menu-chip"
              onclick={() => { showPlayerMenu = false; activeTab = 'facts' }}
              title="Jump to episode facts, downloads, models, and provenance"
            >
              <Icon name="info" size={12} /> view episode facts
            </button>
            <span class="menu-hint">downloads, models, timing & remix</span>
          </div>
        </div>

        <div class="menu-row shortcuts">
          <span class="menu-lab">shortcuts</span>
          <span class="menu-hint">
            <kbd>Space</kbd> play · <kbd>s</kbd> speed · <kbd>←</kbd><kbd>→</kbd> 5s seek · <kbd>↑</kbd><kbd>↓</kbd> turn · <kbd>j</kbd><kbd>k</kbd> episode
          </span>
        </div>
      </div>
    {/if}
  </div>

  <div
    role="progressbar"
    aria-valuenow={dur > 0 ? Math.round((time / dur) * 100) : 0}
    aria-valuemin={0}
    aria-valuemax={100}
    aria-label="Playback position"
    aria-valuetext={`${fmt(time)} of ${fmt(Math.round(dur))}`}
    class="sr-only"
  >
    {fmt(time)} of {fmt(Math.round(dur))}
  </div>

  <div class="v4v-quick-strip mono" aria-label="Value for Value Boosts">
    {#if boostVariant === 'strip'}
      <div class="v4v-boost-actions">
        <span class="v4v-lab"><Icon name="zap" size={12} /> boost:</span>
        <button type="button" class="v4v-pill v4v-pill-primary" onclick={() => triggerQuickZap(100)} disabled={boostBusy} aria-label="Boost 100 sats" title="1-click boost 100 sats via WebLN/NWC with splits">
          <Icon name="zap" size={11} /> +100 sats
        </button>
        <button type="button" class="v4v-pill" onclick={() => triggerQuickZap(500)} disabled={boostBusy} aria-label="Boost 500 sats" title="1-click boost 500 sats via WebLN/NWC with splits">
          +500
        </button>
        <button type="button" class="v4v-pill v4v-custom-btn" onclick={() => (zapOpen = true)} title="Open boost modal with custom amount, recipient splits and NIP-57 receipt">
          <Icon name="zap" size={11} /> <span>boost...</span>
        </button>
        {#if boostBusy}
          <span class="v4v-feedback mono" role="status" aria-live="polite">paying...</span>
        {:else if boostFeedback}
          <span class="v4v-feedback mono ok" role="status" aria-live="polite">{boostFeedback}</span>
        {:else if boostError}
          <span class="v4v-feedback mono err" role="alert">{boostError}</span>
        {/if}
      </div>
    {/if}

    <div class="v4v-stream-group">
      <button
        type="button"
        class="v4v-stream-toggle"
        class:active={streamingSats}
        onclick={toggleStreamingSats}
        title="Stream sats per minute while listening via WebLN/NWC across splits"
        aria-pressed={streamingSats}
      >
        <span>stream:</span>
        {#if streamingSats}
          <Icon name="zap" size={11} /> <span>on ({streamingTotalSats > 0 ? `${streamingTotalSats} sats` : `${streamingRate} sats/m`})</span>
        {:else}
          <span>off</span>
        {/if}
      </button>

      {#if showStreamRate || streamingSats}
        <div class="v4v-rate-popover" role="region" aria-label="Stream rate configuration">
          <label class="v4v-rate-label mono" for="stream-rate">rate</label>
          <input
            id="stream-rate"
            type="number"
            class="v4v-rate-input mono"
            min="1"
            max="100"
            value={streamingRate}
            oninput={(e) => handleStreamingRateInput(e.currentTarget.value)}
            aria-label="Streaming sats per minute"
            title="Sats per minute for streaming while playing"
          />
          <span class="v4v-rate-suffix mono">sats/m</span>
          <button
            type="button"
            class="v4v-rate-close"
            onclick={() => (showStreamRate = false)}
            aria-label="Close rate setting"
            title="Close rate setting"
          >
            ✕
          </button>
        </div>
      {:else}
        <button
          type="button"
          class="v4v-rate-btn"
          onclick={() => (showStreamRate = true)}
          title="Configure streaming sats per minute rate"
          aria-label="Configure stream rate"
        >
          <span>{streamingRate}/m</span>
        </button>
      {/if}
    </div>
  </div>

  <div class="mode-switch-strip mono">
    <div class="seg" role="tablist" aria-label="Episode navigation">
      <button
        type="button"
        role="tab"
        id="tab-transcript"
        aria-controls="panel-transcript"
        aria-selected={activeTab === 'transcript'}
        class:sel={activeTab === 'transcript'}
        onclick={() => (activeTab = 'transcript')}
        onkeydown={(e) => {
          if (e.key === 'ArrowRight') {
            e.preventDefault()
            const next = e.currentTarget.nextElementSibling as HTMLElement | null
            if (next) { next.focus(); next.click() }
          }
        }}
        title="Waveform and synchronized transcript"
      >
        <Icon name="file-text" size={13} /> <span>transcript</span>
      </button>

      <button
        type="button"
        role="tab"
        id="tab-chapters"
        aria-controls="panel-chapters"
        aria-selected={activeTab === 'chapters'}
        class:sel={activeTab === 'chapters'}
        onclick={() => (activeTab = 'chapters')}
        onkeydown={(e) => {
          if (e.key === 'ArrowRight') {
            e.preventDefault()
            const next = e.currentTarget.nextElementSibling as HTMLElement | null
            if (next) { next.focus(); next.click() }
          } else if (e.key === 'ArrowLeft') {
            e.preventDefault()
            const prev = e.currentTarget.previousElementSibling as HTMLElement | null
            if (prev) { prev.focus(); prev.click() }
          }
        }}
        title="Episode chapters and timestamps"
      >
        <Icon name="layers" size={13} /> <span>chapters</span>
        {#if chapterMarks.length > 0}
          <span class="mode-count">{chapterMarks.length}</span>
        {/if}
      </button>

      <button
        type="button"
        role="tab"
        id="tab-takeaways"
        aria-controls="panel-takeaways"
        aria-selected={activeTab === 'takeaways'}
        class:sel={activeTab === 'takeaways'}
        onclick={() => (activeTab = 'takeaways')}
        onkeydown={(e) => {
          if (e.key === 'ArrowRight') {
            e.preventDefault()
            const next = e.currentTarget.nextElementSibling as HTMLElement | null
            if (next) { next.focus(); next.click() }
          } else if (e.key === 'ArrowLeft') {
            e.preventDefault()
            const prev = e.currentTarget.previousElementSibling as HTMLElement | null
            if (prev) { prev.focus(); prev.click() }
          }
        }}
        title="Executive summary and key insights (60s reader)"
      >
        <Icon name="book" size={13} /> <span>takeaways</span>
        {#if keyTakeaways && keyTakeaways.length > 0}
          <span class="mode-count">{keyTakeaways.length}</span>
        {/if}
      </button>

      <button
        type="button"
        role="tab"
        id="tab-highlights"
        aria-controls="panel-highlights"
        aria-selected={activeTab === 'highlights'}
        class:sel={activeTab === 'highlights'}
        onclick={() => (activeTab = 'highlights')}
        onkeydown={(e) => {
          if (e.key === 'ArrowRight') {
            e.preventDefault()
            const next = e.currentTarget.nextElementSibling as HTMLElement | null
            if (next) { next.focus(); next.click() }
          } else if (e.key === 'ArrowLeft') {
            e.preventDefault()
            const prev = e.currentTarget.previousElementSibling as HTMLElement | null
            if (prev) { prev.focus(); prev.click() }
          }
        }}
        title="Community highlights on Nostr (NIP-84)"
      >
        <Icon name="highlighter" size={13} /> <span>highlights</span>
        {#if highlightCount > 0}
          <span class="mode-count">{highlightCount}</span>
        {/if}
      </button>

      {#if jobId}
        <button
          type="button"
          role="tab"
          id="tab-clips"
          aria-controls="panel-clips"
          aria-selected={activeTab === 'clips'}
          class:sel={activeTab === 'clips'}
          onclick={() => (activeTab = 'clips')}
          onkeydown={(e) => {
            if (e.key === 'ArrowRight') {
              e.preventDefault()
              const next = e.currentTarget.nextElementSibling as HTMLElement | null
              if (next) { next.focus(); next.click() }
            } else if (e.key === 'ArrowLeft') {
              e.preventDefault()
              const prev = e.currentTarget.previousElementSibling as HTMLElement | null
              if (prev) { prev.focus(); prev.click() }
            }
          }}
          title="Audio snippet clips"
        >
          <Icon name="slice" size={13} /> <span>clips</span>
          {#if clips.length > 0}
            <span class="mode-count">{clips.length}</span>
          {/if}
        </button>
      {/if}

      <button
        type="button"
        role="tab"
        id="tab-facts"
        aria-controls="panel-facts"
        aria-selected={activeTab === 'facts'}
        class="makingof"
        class:sel={activeTab === 'facts'}
        onclick={() => (activeTab = 'facts')}
        onkeydown={(e) => {
          if (e.key === 'ArrowLeft') {
            e.preventDefault()
            const prev = e.currentTarget.previousElementSibling as HTMLElement | null
            if (prev) { prev.focus(); prev.click() }
          }
        }}
        title="Episode provenance, voice cast, and technical facts"
      >
        <Icon name="info" size={13} /> <span>facts</span>
      </button>
    </div>
  </div>

  <div
    role="tabpanel"
    id="panel-transcript"
    aria-labelledby="tab-transcript"
    class="tab-panel tab-panel-transcript"
    hidden={activeTab !== 'transcript'}
  >
    {#if sliceDraft && slicePreviewMeta}
      <div class="slice-banner mono">
        <span class="slice-banner-info">
          <Icon name="slice" size={12} /> turns {sliceDraft.turnStart + 1}-{sliceDraft.turnEnd + 1} ({sliceDraft.turnEnd - sliceDraft.turnStart + 1} turns · ~{Math.round(slicePreviewMeta.duration)}s)
        </span>
        <div class="slice-banner-actions">
          <button type="button" class="chip slice-preview-play" onclick={handlePreviewSlice} title="Play preview in main audio">
            <Icon name={slicePreviewPlaying ? 'pausebars' : 'playtri'} size={11} /> {slicePreviewPlaying ? 'playing…' : 'preview'}
          </button>
          <button type="button" class="chip slice-create-action" onclick={handleCreateSlice} disabled={clipBusy}>
            <Icon name="slice" size={11} /> create clip
          </button>
          <button type="button" class="chip" onclick={() => (activeTab = 'clips')}>
            view in clips tab
          </button>
          <button type="button" class="chip" onclick={() => { sliceDraft = null; clipError = ''; if (slicePreviewTimer) clearTimeout(slicePreviewTimer); slicePreviewPlaying = false }}>
            cancel
          </button>
        </div>
      </div>
    {/if}

    <TranscriptHighlighter
      episodeUrl={episodeUrlForHighlights}
      transcriptText={transcriptPlainText}
      onHighlightCountChange={(count) => {
        highlightCount = count
        if (jobId) setEpisodeHighlightCount(jobId, count)
      }}
      onHighlightsChange={(hl) => (highlightsList = hl)}
      onSlice={handleSliceFromHighlight}
    >

    {#if chapterBreaksEnabled && groupedTranscript}
      <ol class="transcript" class:text-large={textSize === 'large'} class:text-compact={textSize === 'compact'} aria-label="Episode transcript">
        {#each groupedTranscript as sec (sec.header)}
          <li class="section-head mono" aria-label={`Section ${sec.header}`}>
            {sec.header}
          </li>
          {#each sec.lines as line, localIdx (sec.globalIdxs[localIdx])}
            {@const globalIdx = sec.globalIdxs[localIdx] ?? sec.startIdx + localIdx}
            {@const inSlice = sliceDraft !== null && globalIdx >= sliceDraft.turnStart && globalIdx <= sliceDraft.turnEnd}
            <li
              data-turn={globalIdx}
              class:active={globalIdx === activeIdx}
              class:heard={line.t0 !== undefined && line.t0 <= maxHeard}
              class:a={line.speaker === 'A'}
              class:b={line.speaker === 'B'}
              class:slice-selected={inSlice}
              bind:this={lineEls[globalIdx]}
            >
              <div class="line-row">
                <div class="line-body">
                  <button
                    type="button"
                    class="speaker-btn speaker mono"
                    onclick={() => seekTo(line.t0)}
                    disabled={line.t0 === undefined}
                    title={`Jump to ${fmt(line.t0 ?? 0)}`}
                    aria-label={`Seek to ${fmt(line.t0 ?? 0)}: ${labelFor(line)}`}
                  >
                    {labelFor(line)}
                  </button>
                  <span class="text selectable">
                    {#if karaokeEnabled && globalIdx === activeIdx}
                      {@const nextLine = lines[globalIdx + 1]}
                      {@const wState = getWordState(line.text, line.t0, nextLine?.t0, time)}
                      {#each wState.words as w, wIdx (wIdx)}
                        <span
                          class="word"
                          class:w-current={wIdx === wState.activeIdx}
                          class:w-past={wIdx < wState.activeIdx}
                          class:w-future={wIdx > wState.activeIdx}
                        >{w}{' '}</span>
                      {/each}
                    {:else}
                      {line.text}
                    {/if}
                  </span>
                </div>
                <button
                  type="button"
                  class="quote-btn"
                  class:copied={copiedTurnIdx === globalIdx}
                  onclick={(e) => copyTurnLink(e, line, globalIdx)}
                  title="Copy shareable link to this quote"
                  aria-label={`Copy quote link for ${labelFor(line)}`}
                >
                  <Icon name="link" size={12} />
                  {#if copiedTurnIdx === globalIdx}
                    <span class="copied-tag mono">copied!</span>
                  {/if}
                </button>
                <button
                  type="button"
                  class="slice-handle"
                  class:active={inSlice}
                  onclick={() => handleTurnSliceClick(globalIdx)}
                  title={inSlice ? 'Remove from clip selection' : `Slice from turn ${globalIdx}`}
                  aria-label={inSlice ? `Remove turn ${globalIdx} from clip` : `Select turn ${globalIdx} for clip`}
                  aria-pressed={inSlice}
                >
                  <Icon name="slice" size={12} />
                </button>
              </div>
            </li>
          {/each}
        {/each}
      </ol>
    {:else}
      <ol class="transcript" class:text-large={textSize === 'large'} class:text-compact={textSize === 'compact'} aria-label="Episode transcript">
        {#each lines as line, i (i)}
          {@const inSliceElse = sliceDraft !== null && i >= sliceDraft.turnStart && i <= sliceDraft.turnEnd}
          <li
            data-turn={i}
            class:active={i === activeIdx}
            class:heard={line.t0 !== undefined && time >= line.t0}
            class:a={line.speaker === 'A'}
            class:b={line.speaker === 'B'}
            class:slice-selected={inSliceElse}
            bind:this={lineEls[i]}
          >
            <div class="line-row">
              <div class="line-body">
                <button
                  type="button"
                  class="speaker-btn speaker mono"
                  onclick={() => seekTo(line.t0)}
                  disabled={line.t0 === undefined}
                  title={`Jump to ${fmt(line.t0 ?? 0)}`}
                  aria-label={`Seek to ${fmt(line.t0 ?? 0)}: ${labelFor(line)}`}
                >
                  {labelFor(line)}
                </button>
                <span class="text selectable">
                  {#if karaokeEnabled && i === activeIdx}
                    {@const nextLine = lines[i + 1]}
                    {@const wState = getWordState(line.text, line.t0, nextLine?.t0, time)}
                    {#each wState.words as w, wIdx (wIdx)}
                      <span
                        class="word"
                        class:w-current={wIdx === wState.activeIdx}
                        class:w-past={wIdx < wState.activeIdx}
                        class:w-future={wIdx > wState.activeIdx}
                      >{w}{' '}</span>
                    {/each}
                  {:else}
                    {line.text}
                  {/if}
                </span>
              </div>
              <button
                type="button"
                class="quote-btn"
                class:copied={copiedTurnIdx === i}
                onclick={(e) => copyTurnLink(e, line, i)}
                title="Copy shareable link to this quote"
                aria-label={`Copy quote link for ${labelFor(line)}`}
              >
                <Icon name="link" size={12} />
                {#if copiedTurnIdx === i}
                  <span class="copied-tag mono">copied!</span>
                {/if}
              </button>
              <button
                type="button"
                class="slice-handle"
                class:active={inSliceElse}
                onclick={() => handleTurnSliceClick(i)}
                title={inSliceElse ? 'Remove from clip selection' : `Slice from turn ${i}`}
                aria-label={inSliceElse ? `Remove turn ${i} from clip` : `Select turn ${i} for clip`}
                aria-pressed={inSliceElse}
              >
                <Icon name="slice" size={12} />
              </button>
            </div>
          </li>
        {/each}
      </ol>
    {/if}
    </TranscriptHighlighter>
  </div>

  <div
    role="tabpanel"
    id="panel-chapters"
    aria-labelledby="tab-chapters"
    class="tab-panel tab-panel-chapters mono"
    hidden={activeTab !== 'chapters'}
  >
    {#if chapterMarks.length > 0}
      <nav class="chapters" aria-label="Episode chapters">
        <ol class="ch-list">
          {#each chapterMarks as c, idx (c.index)}
            {@const nextC = chapterMarks[idx + 1]}
            {@const isCur = c.t !== undefined && time >= c.t && (nextC?.t === undefined || time < nextC.t)}
            <li class="ch-item" class:active={isCur}>
              <button
                type="button"
                class="ch-btn"
                onclick={() => handleChapterClick(c)}
                disabled={c.t === undefined}
                aria-current={isCur ? 'true' : undefined}
              >
                <span class="ch-num">{c.index + 1}</span>
                <span class="ch-label">{c.title}</span>
                {#if c.t !== undefined}
                  <span class="ch-time">{fmt(c.t)}</span>
                {/if}
              </button>
            </li>
          {/each}
        </ol>
      </nav>
    {:else}
      <div class="tab-empty-state mono">
        <div class="empty-icon"><Icon name="layers" size={22} /></div>
        <p class="empty-title">no chapters recorded for this episode</p>
        <p class="empty-sub">Chapters are automatically generated when podcast:chapters metadata or structured topics are present.</p>
      </div>
    {/if}
  </div>

  <div
    role="tabpanel"
    id="panel-takeaways"
    aria-labelledby="tab-takeaways"
    class="tab-panel tab-panel-takeaways"
    hidden={activeTab !== 'takeaways'}
  >
    <section class="takeaways-view" aria-label="Executive Summary and Key Takeaways">
      {#if executiveSummary}
        <div class="exec-summary-card">
          <div class="exec-head mono">
            <span class="exec-tag"><Icon name="sparkles" size={13} /> Executive Summary (TL;DR)</span>
            <div class="exec-actions">
              <button type="button" class="exec-btn" onclick={copySummaryMarkdown} title="Copy executive summary as Markdown" aria-label="Copy executive summary as Markdown">
                <Icon name="copy" size={12} /> {copiedSummary ? 'Copied!' : 'Copy Markdown'}
              </button>
              <button type="button" class="exec-btn" onclick={shareNostrDraft} title="Draft a Nostr note with takeaways" aria-label="Share takeaways to Nostr (copy note draft)">
                <Icon name="share" size={12} /> Share to Nostr
              </button>
            </div>
          </div>
          <p class="exec-text">{executiveSummary}</p>
          {#if executiveQuote}
            <div class="exec-quote-row mono">
              <button
                type="button"
                class="quote-toggle"
                onclick={() => (showExecQuote = !showExecQuote)}
                aria-expanded={showExecQuote}
                aria-label="Show or hide source quote for executive summary"
              >
                <span class="arrow">{showExecQuote ? '▾' : '▸'}</span> source
              </button>
              {#if showExecQuote}
                <blockquote class="source-quote">"{executiveQuote}"</blockquote>
              {/if}
            </div>
          {/if}
          {#if factualityScore !== null && factualityScore !== undefined}
            <div class="factuality-badge mono" title="Factuality score: verified source quotes / total">
              <span class="fact-label">grounded</span>
              <span class="fact-score" class:fact-low={factualityScore < 0.85}>{Math.round(factualityScore * 100)}% verified</span>
            </div>
          {/if}
        </div>
      {/if}

      {#if keyTakeaways && keyTakeaways.length > 0}
        <div class="takeaways-list" role="list">
          {#each keyTakeaways as tk, idx (tk.id ?? idx)}
            {@const isExpanded = expandedQuotes.has(idx)}
            <div class="takeaway-card" role="listitem">
              <div class="tk-header">
                <button
                  type="button"
                  class="tk-jump-btn mono"
                  onclick={() => seekTakeaway(tk, idx)}
                  title={`Jump to ${tk.time_formatted || '00:00'} where co-hosts debate this takeaway`}
                  aria-label={`Seek to ${tk.time_formatted || '00:00'}: ${tk.title}`}
                >
                  <span aria-hidden="true">[ ▶ {tk.time_formatted || '00:00'} ]</span><span class="sr-only"> {tk.time_formatted || '00:00'}</span>
                </button>
                <h3 class="tk-title">{tk.title}</h3>
              </div>
              <p class="tk-body">{tk.text}</p>
              {#if tk.source_quote}
                <div class="tk-quote-row mono">
                  <button
                    type="button"
                    class="quote-toggle"
                    onclick={() => {
                      const next = new Set(expandedQuotes)
                      if (next.has(idx)) next.delete(idx)
                      else next.add(idx)
                      expandedQuotes = next
                    }}
                    aria-expanded={isExpanded}
                    aria-label={`Show or hide source quote for ${tk.title}`}
                  >
                    <span class="arrow">{isExpanded ? '▾' : '▸'}</span> source
                  </button>
                  {#if isExpanded}
                    <blockquote class="source-quote">"{tk.source_quote}"</blockquote>
                  {/if}
                </div>
              {/if}
            </div>
          {/each}
        </div>
      {:else if !executiveSummary}
        <div class="tab-empty-state mono">
          <div class="empty-icon"><Icon name="book" size={22} /></div>
          <p class="empty-title">no key takeaways extracted yet</p>
          <p class="empty-sub">Key takeaways and executive insights are generated during audio overview synthesis.</p>
        </div>
      {/if}
    </section>
  </div>

  <div
    role="tabpanel"
    id="panel-highlights"
    aria-labelledby="tab-highlights"
    class="tab-panel tab-panel-highlights mono"
    hidden={activeTab !== 'highlights'}
  >
    <div class="tab-kicker-banner">
      <span class="kicker-lead">
        <Icon name="highlighter" size={13} />
        <span>highlight tip: select any phrase in the <strong>transcript</strong> tab to create and sign a Nostr (NIP-84) quote</span>
      </span>
      {#if highlightsList.length > 0}
        <button
          type="button"
          class="kicker-action-btn mono"
          onclick={() => (highlightOpen = true)}
          title="Open full highlights modal with social filter"
        >
          <Icon name="sliders" size={11} /> <span>modal view</span>
        </button>
      {/if}
    </div>

    {#if highlightsList.length > 0}
      <div class="hl-filter-bar mono" role="group" aria-label="Highlight categories">
        <button
          type="button"
          class="hl-filter-chip"
          class:active={hlFilter === 'all'}
          onclick={() => (hlFilter = 'all')}
        >
          all ({hlCounts.all})
        </button>
        {#if hlCounts.user > 0}
          <button
            type="button"
            class="hl-filter-chip"
            class:active={hlFilter === 'user'}
            onclick={() => (hlFilter = 'user')}
          >
            <span class="hl-dot hl-dot-user"></span> you ({hlCounts.user})
          </button>
        {/if}
        {#if hlCounts.friend > 0}
          <button
            type="button"
            class="hl-filter-chip"
            class:active={hlFilter === 'friend'}
            onclick={() => (hlFilter = 'friend')}
          >
            <span class="hl-dot hl-dot-friend"></span> friends ({hlCounts.friend})
          </button>
        {/if}
        <button
          type="button"
          class="hl-filter-chip"
          class:active={hlFilter === 'global'}
          onclick={() => (hlFilter = 'global')}
        >
          <span class="hl-dot hl-dot-global"></span> global ({hlCounts.global})
        </button>
      </div>

      <div class="hl-list" role="feed" aria-label="Episode highlights list">
        {#each filteredHighlights as h, idx (h.id || idx)}
          {@const cat = categorizeHighlight(h, userPubkey, new Set())}
          <article class="hl-item hl-item-{cat}">
            <div class="hl-item-top">
              <div class="hl-author-group">
                <span class="hl-badge hl-badge-{cat}">{cat}</span>
                {#if h.pubkey}
                  <span class="hl-author" title={h.pubkey}>by {shortNpub(h.pubkey)}</span>
                {/if}
              </div>
              <div class="hl-actions">
                <button
                  type="button"
                  class="secondary hl-action-btn mono"
                  onclick={() => {
                    const targetIdx = lines.findIndex((l) => l.text.includes(h.content) || h.content.includes(l.text))
                    const target = targetIdx >= 0 ? lines[targetIdx] : undefined
                    if (target?.t0 !== undefined) {
                      seekTo(target.t0)
                      activeTab = 'transcript'
                      setTimeout(() => {
                        const el = lineEls[targetIdx]
                        if (el) {
                          el.scrollIntoView({
                            block: 'center',
                            behavior: reducedMotion ? 'auto' : 'smooth'
                          })
                        }
                      }, 60)
                    }
                  }}
                  title="Jump to quote in playback"
                >
                  <Icon name="playtri" size={10} /> <span>jump to quote</span>
                </button>
                <button
                  type="button"
                  class="secondary hl-action-btn mono"
                  onclick={(e) => copyHighlightText(e, h.content.trim(), idx)}
                  title="Copy quote text"
                >
                  <Icon name="copy" size={10} /> <span>{hlCopiedIdx === idx ? 'copied!' : 'copy'}</span>
                </button>
              </div>
            </div>
            <blockquote class="hl-quote">
              "{h.content.trim()}"
            </blockquote>
          </article>
        {/each}
      </div>
    {:else}
      <div class="tab-empty-state mono">
        <div class="empty-icon"><Icon name="highlighter" size={22} /></div>
        <p class="empty-title">no highlights recorded yet</p>
        <p class="empty-sub">Select any sentence in the transcript tab to highlight and sign a NIP-84 quote to Nostr relays.</p>
        <button type="button" class="empty-action" onclick={() => (activeTab = 'transcript')}>
          <Icon name="file-text" size={12} /> <span>go to transcript</span>
        </button>
      </div>
    {/if}
  </div>

  {#if jobId}
    <div
      role="tabpanel"
      id="panel-clips"
      aria-labelledby="tab-clips"
      class="tab-panel tab-panel-clips mono"
      hidden={activeTab !== 'clips'}
    >
      <div class="clips-content">
        <div class="tab-kicker-banner">
          <span class="kicker-lead">
            <Icon name="slice" size={13} />
            <span>clip tip: tap the <strong>slice icon</strong> on dialogue turns or select text to create a shareable audio snippet</span>
          </span>
          <button
            type="button"
            class="kicker-action-btn mono"
            onclick={() => (activeTab = 'transcript')}
            title="Open transcript to slice a new clip"
          >
            <Icon name="file-text" size={11} /> <span>go to transcript</span>
          </button>
        </div>

        {#if sliceDraft && slicePreviewMeta}
          <div class="slice-preview" role="region" aria-label="Clip preview">
            <div class="slice-preview-head">
              <span class="slice-range mono">turns {sliceDraft.turnStart + 1}-{sliceDraft.turnEnd + 1} · {sliceDraft.turnEnd - sliceDraft.turnStart + 1} turns</span>
              <span class="slice-speakers mono">{slicePreviewMeta.speakers}</span>
              <span class="slice-dur mono">~{Math.round(slicePreviewMeta.duration)}s</span>
            </div>
            {#if sliceDraft.textSnippet}
              <p class="slice-snippet mono">"{sliceDraft.textSnippet.slice(0, 140)}{sliceDraft.textSnippet.length > 140 ? '…' : ''}"</p>
            {/if}
            <div class="slice-preview-actions">
              <button type="button" class="chip slice-preview-play" onclick={handlePreviewSlice} aria-label="Preview clip in main player" title="Play preview in main audio">
                <Icon name={slicePreviewPlaying ? 'pausebars' : 'playtri'} size={12} /> {slicePreviewPlaying ? 'playing preview…' : 'preview'}
              </button>
              <button type="button" class="chip slice-create-action" onclick={handleCreateSlice} disabled={clipBusy} aria-label="Create audio clip">
                {#if clipBusy}
                  creating…
                {:else}
                  <Icon name="slice" size={12} /> create clip
                {/if}
              </button>
              <button type="button" class="chip slice-boost-action" onclick={handleClipAndBoost} title="Tip and attach zap to this clip snippet">
                <Icon name="zap" size={12} /> Clip & Boost
              </button>
              <button type="button" class="chip" onclick={() => { sliceDraft = null; clipError = ''; if (slicePreviewTimer) clearTimeout(slicePreviewTimer); slicePreviewPlaying = false }} aria-label="Cancel clip preview">cancel</button>
            </div>
            {#if clipError}
              <p class="mono clip-err" role="alert">{clipError}</p>
            {/if}
          </div>
        {:else if clips.length === 0}
          <div class="tab-empty-state mono">
            <div class="empty-icon"><Icon name="slice" size={22} /></div>
            <p class="empty-title">no audio clips saved yet</p>
            <p class="empty-sub">Select text in the transcript or tap the slice icon next to dialogue turns to craft an audio snippet.</p>
            <button type="button" class="empty-action" onclick={() => (activeTab = 'transcript')}>
              <Icon name="file-text" size={12} /> <span>open transcript to clip</span>
            </button>
          </div>
        {/if}

        {#if clips.length > 0}
          <div class="clips-list">
            {#each clips as clip, idx (idx)}
              <div class="clip-card">
                <div class="clip-info">
                  <span class="clip-label mono" title={clipLabel(clip)}>{clipLabel(clip)}</span>
                  <span class="clip-dur mono">{fmtTime(clip.duration_seconds)}</span>
                </div>
                <div class="clip-actions">
                  <audio
                    src={clip.url}
                    preload="metadata"
                    style="display:none;"
                    onplay={() => (clipPlayingMap = { ...clipPlayingMap, [idx]: true })}
                    onpause={() => (clipPlayingMap = { ...clipPlayingMap, [idx]: false })}
                    onended={() => (clipPlayingMap = { ...clipPlayingMap, [idx]: false })}
                    ontimeupdate={(e) => (clipTimeMap = { ...clipTimeMap, [idx]: (e.currentTarget as HTMLAudioElement).currentTime })}
                    onloadedmetadata={(e) => (clipDurMap = { ...clipDurMap, [idx]: (e.currentTarget as HTMLAudioElement).duration })}
                  ></audio>
                  <button type="button" class="chip clip-play-btn" onclick={(e) => {
                    const card = (e.currentTarget as HTMLElement).closest('.clip-card')
                    const el = card?.querySelector('audio') as HTMLAudioElement | null
                    document.querySelectorAll('.clips-list audio').forEach((a) => {
                      if (a !== el) (a as HTMLAudioElement).pause()
                    })
                    if (el) { if (el.paused) el.play(); else el.pause() }
                  }} aria-label={clipPlayingMap[idx] ? 'Pause clip' : 'Play clip'}>
                    {#if clipPlayingMap[idx]}
                      <Icon name="pausebars" size={12} /> pause
                    {:else}
                      <Icon name="playtri" size={12} /> play
                    {/if}
                  </button>
                  <span class="clip-time mono">{fmtTime(clipTimeMap[idx] ?? 0)} / {fmtTime(clipDurMap[idx] ?? clip.duration_seconds)}</span>
                  <button type="button" class="chip clip-share-btn" onclick={(e) => copyClipUrl(e, idx)} aria-label="Copy share link">
                    <Icon name="link" size={12} /> {clipCopiedIdx === idx ? 'copied!' : 'share'}
                  </button>
                  <a class="chip clip-download-btn" href={clip.url} download aria-label="Download clip MP3">
                    <Icon name="download" size={12} /> mp3
                  </a>
                  <button type="button" class="chip clip-delete-btn" onclick={() => handleDeleteClip(clip.filename)} aria-label="Delete clip" title="Delete clip">
                    <Icon name="trash" size={12} />
                  </button>
                </div>
                <div class="clip-share-row mono">
                  <span class="clip-url mono" title={clipShareUrl(clip)}>{clipShareUrl(clip)}</span>
                  <button type="button" class="chip clip-copy-url" onclick={(e) => copyClipUrl(e, idx)} aria-label="Copy clip share URL">
                    <Icon name="copy" size={11} /> {clipCopiedIdx === idx ? 'copied!' : 'copy link'}
                  </button>
                </div>
              </div>
            {/each}
          </div>
        {/if}
        {#if clipError && !sliceDraft}
          <p class="mono clip-err" role="alert">{clipError}</p>
        {/if}
      </div>
    </div>
  {/if}

  <div
    role="tabpanel"
    id="panel-facts"
    aria-labelledby="tab-facts"
    class="tab-panel tab-panel-facts mono"
    hidden={activeTab !== 'facts'}
  >
    <div class="facts-actions-bar">
      <a href={src} download class="facts-action-pill primary" aria-label="Download episode MP3" title="Download audio file as MP3">
        <Icon name="download" size={13} />
        <span class="action-text">download mp3</span>
        {#if jobAudio?.bytes}
          <span class="action-badge">{(jobAudio.bytes / (1024 * 1024)).toFixed(1)} MB</span>
        {/if}
      </a>

      <button type="button" class="facts-action-pill" onclick={copyTranscript} aria-label="Copy transcript" title="Copy episode script to clipboard">
        <Icon name={copiedTranscript ? 'check' : 'copy'} size={13} />
        <span class="action-text">{copiedTranscript ? 'copied!' : 'copy transcript'}</span>
        <span class="action-badge">{lines.length} turns</span>
      </button>

      {#if onremix}
        <button
          type="button"
          class="facts-action-pill"
          onclick={() => onremix?.(sourceUrl || jobId || '', /^https?:\/\//i.test(sourceUrl ?? ''))}
          title="Load episode and settings into composer to create a new variant"
        >
          <Icon name="sliders" size={13} />
          <span class="action-text">create variant</span>
        </button>
      {/if}

      {#if /^https?:\/\//i.test(sourceUrl ?? '')}
        <a href={sourceUrl} target="_blank" rel="noopener noreferrer" class="facts-action-pill" title="Open source URL in new tab">
          <Icon name="link" size={13} />
          <span class="action-text">open source</span>
        </a>
      {/if}
    </div>

    <dl class="mono facts">
      <div class="facts-section-label">// episode & dialogue</div>
      <div class="fact-row fact-title"><dt>title</dt><dd>
        {#if !isRenaming}
          <span class="fact-title-text">{currentTitle}</span>
          <button type="button" class="rename-link mono" onclick={startRename} aria-label="rename episode">rename</button>
        {:else}
          <div class="rename-inline">
            <input
              bind:this={renameInputEl}
              type="text"
              class="rename-input mono"
              maxlength="120"
              bind:value={renameDraft}
              onkeydown={handleRenameKeydown}
              aria-label="episode title"
            />
            <button type="button" class="rename-btn rename-save mono" onclick={saveRename} disabled={renameBusy} aria-label="save title">
              {renameBusy ? 'saving...' : 'save'}
            </button>
            <button type="button" class="rename-btn rename-cancel mono" onclick={cancelRename} disabled={renameBusy} aria-label="cancel rename">
              cancel
            </button>
            {#if renameError}
              <span class="rename-error mono" role="alert">{renameError}</span>
            {/if}
          </div>
        {/if}
      </dd></div>
      <div class="fact-row"><dt>source</dt><dd>
        {#if /^https?:\/\//i.test(sourceUrl ?? '')}
          <a href={sourceUrl} target="_blank" rel="noopener noreferrer" class="fact-link" title={sourceUrl}>
            <Icon name="link" size={11} /> <span>{sourceLabel.slice(0, 72)}{sourceLabel.length > 72 ? '…' : ''}</span>
          </a>
        {:else if sourceLabel && jobId}
          <a href={`/source/${jobId}`} class="fact-link" title="View captured source text">
            <Icon name="file-text" size={11} /> <span>{sourceLabel}</span>
          </a>
        {:else if sourceLabel}
          <span>{sourceLabel}</span>
        {:else}
          <span class="fact-dim">none recorded</span>
        {/if}
      </dd></div>
      {#if showName}<div class="fact-row"><dt>series</dt><dd>{showName}</dd></div>{/if}
      <div class="fact-row"><dt>format</dt><dd>{jobFormat === 'narration' ? 'read aloud' : `${voiceCount} hosts`}</dd></div>
      <div class="fact-row"><dt>style</dt><dd><span class="fact-tag">{jobStyle || 'balanced'}</span></dd></div>
      <div class="fact-row"><dt>language</dt><dd>{languageFact}</dd></div>
      <div class="fact-row"><dt>voices</dt><dd>{voicesLabel}</dd></div>
      {#if castLabel}<div class="fact-row"><dt>cast</dt><dd>{castLabel}</dd></div>{/if}
      <div class="fact-row"><dt>script</dt><dd>{wordCount} words · {lines.length} turns</dd></div>

      <div class="facts-section-label">// audio & models</div>
      <div class="fact-row"><dt>audio</dt><dd>{audioLabel || 'MP3 audio'}</dd></div>
      <div class="fact-row"><dt>llm writer</dt><dd>{llmFact}</dd></div>
      <div class="fact-row"><dt>tts engine</dt><dd>{ttsFact}</dd></div>
      <div class="fact-row"><dt>music bed</dt><dd>{musicBedFact}</dd></div>
      {#if mp3QualityFact}<div class="fact-row"><dt>mp3 specs</dt><dd>{mp3QualityFact}</dd></div>{/if}
      {#if tuningLabel}<div class="fact-row"><dt>tuning</dt><dd>{tuningLabel}</dd></div>{/if}
      {#if jobDurationMs}<div class="fact-row"><dt>render</dt><dd>{Math.round(jobDurationMs / 1000)}s to render{#if stageTimingsFact} ({stageTimingsFact}){/if}</dd></div>{/if}

      <div class="facts-section-label">// community & value</div>
      <div class="fact-row"><dt>stats</dt><dd>{playCount} {playCount === 1 ? 'play' : 'plays'} · {zapCount} {zapCount === 1 ? 'zap' : 'zaps'} (total {zappedSats.toLocaleString()} sats) · {highlightCount} {highlightCount === 1 ? 'highlight' : 'highlights'}</dd></div>
      {#if valueTip}
        <div class="fact-row"><dt>value</dt><dd>
          <a href={`lightning:${valueTip.address}`} rel="payment" class="fact-link">
            <Icon name="zap" size={11} /> <span>zap {valueTip.split}% to the maker</span>
          </a>
          {#if valueTip.appAddress && valueTip.split < 100}<span class="fact-dim"> · {100 - valueTip.split}% vozonda</span>{/if}
        </dd></div>
      {/if}
      {#if styleDocFact}
        <div class="fact-row"><dt>directive</dt><dd class="fact-directive-text">{styleDocFact}</dd></div>
      {/if}
    </dl>

    <!-- Nostr publish status line -->
    {#if nostrShowEnabled && (jobId)}
      <div class="nostr-status-bar">
        <span class="mono nostr-status-text" role="status" aria-live="polite">
          {#if nostrPublishStatus === 'published'}
            // nostr: published to {nostrSuccessCount}/{nostrRelayCount} relays
          {:else if nostrPublishStatus === 'failed' || nostrStatus === 'failed'}
            // nostr: failed ·
            <button class="nostr-retry-btn mono" onclick={retryNostrPublish} aria-label="Retry nostr publishing" disabled={nostrPublishBusy}>retry</button>
          {:else}
            // nostr: ready to publish
          {/if}
        </span>
      </div>
    {/if}
  </div>

  <div class="listen-cta-row">
    <a href="/?new" class="listen-cta mono" aria-label="Compose a new episode from your next sources">
      <Icon name="plus" size={16} /> <span>turn your next sources into a podcast</span>
    </a>
  </div>
</article>

<ZapModal
  open={zapOpen}
  onClose={() => {
    zapOpen = false
    if (jobId) {
      zappedSats = getEpisodeZappedSats(jobId)
      zapCount = getEpisodeZapCount(jobId)
    }
  }}
  lightningAddress={valueTip?.address ?? ''}
  recipientPubkey={''}
  jobId={jobId ?? ''}
  relays={['wss://relay.damus.io', 'wss://nos.lol']}
  initialSats={zapInitialSats}
  initialComment={zapInitialComment}
  timestampSeconds={zapTimestamp}
/>

<HighlightModal
  open={highlightOpen}
  onClose={() => (highlightOpen = false)}
  highlights={highlightsList}
  onSeekTurn={(txt) => {
    const target = lines.find((l) => l.text.includes(txt) || txt.includes(l.text))
    if (target?.t0 !== undefined) seekTo(target.t0)
  }}
/>

<audio
  bind:this={audio}
  bind:currentTime={time}
  bind:duration={dur}
  onloadedmetadata={() => {
    if (audio && currentSpeed !== 1) audio.playbackRate = currentSpeed
  }}
  onplay={() => {
    playing = true
    if (audio && currentSpeed !== 1) audio.playbackRate = currentSpeed
    if (jobId && !hasTrackedPlay) {
      hasTrackedPlay = true
      incrementEpisodePlayCount(jobId)
      playCount = getEpisodePlayCount(jobId)
    }
  }}
  onpause={() => (playing = false)}
  onended={() => {
    playing = false
    stopStreaming()
    if (sleepMode === 'end') {
      sleepMode = 'off'
      sleepRemaining = 0
    }
  }}
  {src}
></audio>

<style>
  .episode-title-area {
    display: flex;
    align-items: baseline;
    gap: var(--space-2);
    margin-bottom: var(--space-2);
    flex-wrap: wrap;
  }

  .episode-title-area.attached {
    display: contents;
  }

  .standalone-title {
    font-size: var(--h1-size, 1.8rem);
    font-weight: var(--h1-weight, 600);
    letter-spacing: -0.02em;
    margin: 0;
    color: var(--ink);
  }

  .fact-title dd {
    display: flex;
    flex-wrap: wrap;
    align-items: baseline;
    gap: var(--space-2);
  }

  /* the title editor takes the row's full width (the inline field cut long titles) */
  .fact-title .rename-inline {
    display: flex;
    flex: 1 1 100%;
  }

  .fact-title .rename-input {
    flex: 1 1 16rem;
    min-width: 0;
  }

  .rename-link {
    background: transparent;
    border: none;
    padding: 0;
    color: var(--ink-soft);
    font-family: var(--font-mono);
    font-size: calc(var(--ui-size) * 0.85);
    text-decoration: underline;
    text-underline-offset: 3px;
    cursor: pointer;
    line-height: 1.2;
    transition: color var(--dur-fast, 120ms) ease-out;
  }

  .rename-link:hover {
    color: var(--green);
  }

  .rename-link:focus-visible {
    outline: 2px solid var(--green);
    outline-offset: 2px;
  }

  .rename-inline {
    display: inline-flex;
    align-items: center;
    gap: var(--space-2);
    flex-wrap: wrap;
  }

  .rename-input {
    background: var(--paper);
    color: var(--ink);
    border: 1px solid var(--line);
    border-radius: var(--radius);
    padding: 3px 8px;
    font-family: var(--font-mono);
    font-size: var(--ui-size);
    min-width: 240px;
    max-width: 480px;
    box-sizing: border-box;
    transition: border-color var(--dur-fast, 120ms) ease-out;
  }

  .rename-input:focus-visible {
    border-color: var(--green);
    outline: 1px solid var(--green);
  }

  .rename-btn {
    display: inline-flex;
    align-items: center;
    justify-content: center;
    padding: 3px 9px;
    border-radius: var(--radius);
    font-family: var(--font-mono);
    font-size: calc(var(--ui-size) * 0.85);
    line-height: 1.2;
    cursor: pointer;
    text-transform: lowercase;
    transition: background var(--dur-fast, 120ms) ease-out, color var(--dur-fast, 120ms) ease-out, border-color var(--dur-fast, 120ms) ease-out;
  }

  .rename-btn:disabled {
    opacity: 0.5;
    cursor: not-allowed;
  }

  .rename-save {
    background: color-mix(in srgb, var(--green) 12%, var(--paper));
    border: 1px solid var(--green);
    color: var(--ink);
  }

  .rename-save:hover:not(:disabled) {
    background: color-mix(in srgb, var(--green) 20%, var(--paper));
    color: var(--ink);
  }

  .rename-save:focus-visible {
    outline: 2px solid var(--green);
    outline-offset: 2px;
  }

  .rename-cancel {
    background: transparent;
    border: 1px solid var(--line);
    color: var(--ink-soft);
  }

  .rename-cancel:hover:not(:disabled) {
    color: var(--ink);
    border-color: var(--ink-soft);
  }

  .rename-cancel:focus-visible {
    outline: 2px solid var(--green);
    outline-offset: 2px;
  }

  .rename-error {
    color: var(--error, #e5534b);
    font-family: var(--font-mono);
    font-size: calc(var(--ui-size) * 0.82);
  }

  .listen {
    width: 100%;
    max-width: var(--content-max-width, 880px);
    margin: 0 auto;
    padding: 0;
    box-sizing: border-box;
  }

  .meta {
    display: flex;
    align-items: center;
    justify-content: space-between;
    gap: var(--space-2);
    margin-bottom: var(--space-2);
    flex-wrap: wrap;
    min-height: 28px;
  }

  .meta-left {
    display: inline-flex;
    align-items: center;
    gap: 6px;
  }

  .meta-date {
    color: var(--ink-soft);
    font-size: calc(var(--ui-size) * 0.88);
  }

  .meta-boost {
    display: inline-flex;
    align-items: center;
    gap: 6px;
    margin-left: auto;
  }

  .meta-boost-pill {
    display: inline-flex;
    align-items: center;
    gap: 4px;
    background: transparent;
    border: 1px solid var(--line);
    border-radius: var(--radius);
    padding: 2px 9px;
    min-height: 26px;
    color: var(--ink);
    cursor: pointer;
    font-family: var(--font-mono);
    font-size: calc(var(--ui-size) * 0.82);
    line-height: 1.2;
    transition: color var(--dur-fast, 120ms) ease-out, background var(--dur-fast, 120ms) ease-out, border-color var(--dur-fast, 120ms) ease-out;
  }

  .meta-boost-pill:hover:not(:disabled) {
    background: color-mix(in srgb, var(--green) 12%, var(--paper));
    color: var(--ink);
    border-color: var(--green);
  }

  .meta-boost-pill:disabled {
    opacity: 0.5;
    cursor: not-allowed;
  }

  .meta-boost-primary {
    color: var(--green);
    border-color: color-mix(in srgb, var(--green) 45%, var(--line));
    font-weight: 500;
  }

  .meta-boost-more {
    color: var(--ink-soft);
  }

  .meta-boost-status {
    font-size: calc(var(--ui-size) * 0.8);
    color: var(--ink-soft);
  }

  .meta-boost-status.ok {
    color: var(--green);
  }

  .meta-boost-status.err {
    color: var(--error, #e5534b);
  }

  .badge-watchlist {
    display: inline-flex;
    align-items: center;
    gap: 4px;
    background: transparent;
    border: 1px solid var(--line);
    color: var(--ink-soft);
    padding: 1px 7px;
    border-radius: var(--radius);
    font-size: calc(var(--ui-size) * 0.78);
    letter-spacing: 0.04em;
    vertical-align: middle;
    margin-right: 6px;
  }

  .chip {
    display: inline-flex;
    align-items: center;
    gap: 6px;
    background: transparent;
    border: 1px solid var(--line);
    border-radius: var(--radius);
    padding: 3px 8px;
    color: var(--ink-soft);
    font-family: var(--font-mono);
    font-size: var(--ui-size);
    letter-spacing: 0.03em;
    text-decoration: none;
    cursor: pointer;
    line-height: 1.2;
    transition: color var(--dur-fast, 120ms) ease-out, border-color var(--dur-fast, 120ms) ease-out, background var(--dur-fast, 120ms) ease-out;
  }

  .chip:hover {
    color: var(--ink);
    border-color: var(--green);
    background: color-mix(in srgb, var(--green) 8%, var(--paper));
  }

  .chip:focus-visible {
    outline: 2px solid var(--green);
    outline-offset: 2px;
  }

  .arrow {
    font-size: calc(var(--ui-size) * 0.78);
    color: var(--green);
  }

  .tab-panel-facts {
    padding: var(--space-3) 0 var(--space-6);
    min-height: 280px;
    animation: modeFade 200ms ease-out;
  }

  .facts-actions-bar {
    display: flex;
    flex-wrap: wrap;
    align-items: center;
    gap: var(--space-2);
    margin-bottom: var(--space-4);
    padding-bottom: var(--space-4);
    border-bottom: 1px solid var(--line);
  }

  .facts-action-pill {
    display: inline-flex;
    align-items: center;
    gap: 6px;
    background: color-mix(in srgb, var(--ink) 4%, var(--paper));
    border: 1px solid var(--line);
    border-radius: var(--radius);
    padding: 5px 12px;
    min-height: 32px;
    color: var(--ink);
    cursor: pointer;
    font-family: var(--font-mono);
    font-size: calc(var(--ui-size) * 0.85);
    text-decoration: none;
    text-transform: lowercase;
    transition: color var(--dur-fast) ease-out, border-color var(--dur-fast) ease-out, background var(--dur-fast) ease-out;
  }

  .facts-action-pill:hover {
    color: var(--ink);
    border-color: var(--green);
    background: color-mix(in srgb, var(--green) 8%, var(--paper));
  }

  .facts-action-pill.primary {
    border-color: color-mix(in srgb, var(--green) 35%, var(--line));
    background: color-mix(in srgb, var(--green) 6%, var(--paper));
  }

  .facts-action-pill.primary:hover {
    color: var(--ink);
    border-color: var(--green);
    background: color-mix(in srgb, var(--green) 14%, var(--paper));
  }

  .facts-action-pill .action-badge {
    font-size: calc(var(--ui-size) * 0.76);
    color: var(--ink-soft);
    background: color-mix(in srgb, var(--ink) 8%, var(--paper));
    padding: 1px 6px;
    border-radius: var(--radius);
  }

  .facts {
    margin: 0;
    display: flex;
    flex-direction: column;
    gap: 0;
  }

  .fact-row {
    display: flex;
    align-items: baseline;
    gap: var(--space-4);
    padding: 9px 0;
    border-bottom: 1px solid color-mix(in srgb, var(--line) 40%, transparent);
  }

  .fact-row:last-child {
    border-bottom: none;
  }

  .facts dt {
    flex: 0 0 110px;
    width: 110px;
    color: var(--ink-soft);
    font-size: calc(var(--ui-size) * 0.85);
    text-transform: lowercase;
    letter-spacing: 0.02em;
  }

  .facts dd {
    flex: 1 1 auto;
    margin: 0;
    color: var(--ink);
    font-size: calc(var(--ui-size) * 0.9);
    line-height: 1.5;
    word-break: break-word;
  }

  .fact-tag {
    display: inline-block;
    padding: 1px 7px;
    background: color-mix(in srgb, var(--ink) 5%, var(--paper));
    border: 1px solid var(--line);
    border-radius: var(--radius);
    font-size: calc(var(--ui-size) * 0.84);
  }

  .fact-link {
    color: var(--ink-soft);
    text-decoration: underline;
    text-underline-offset: 3px;
    display: inline-flex;
    align-items: center;
    gap: 5px;
    transition: color var(--dur-fast) ease-out;
  }

  .fact-link:hover,
  .facts dd a:hover {
    color: var(--green);
  }

  .facts dd a {
    color: var(--ink-soft);
    text-decoration: underline;
    text-underline-offset: 3px;
  }

  .fact-dim {
    color: var(--ink-soft);
    opacity: 0.75;
  }

  .facts-section-label {
    color: var(--ink-soft);
    font-size: calc(var(--ui-size) * 0.78);
    letter-spacing: 0.05em;
    padding-top: var(--space-4);
    padding-bottom: var(--space-1);
    margin-top: var(--space-2);
    border-top: 1px dashed var(--line);
    text-transform: lowercase;
  }

  .facts-section-label:first-child {
    padding-top: 0;
    margin-top: 0;
    border-top: none;
  }

  .fact-directive-text {
    color: var(--ink-soft);
    font-size: calc(var(--ui-size) * 0.88);
    line-height: 1.4;
  }

  .nostr-status-bar {
    margin-top: var(--space-3);
    padding: var(--space-2) var(--space-3);
    border: 1px solid var(--line);
    border-radius: var(--radius);
    background: color-mix(in srgb, var(--ink) 2%, var(--paper));
  }

  .nostr-status-text {
    font-size: var(--ui-size);
    color: var(--ink);
    display: block;
    line-height: 1.45;
  }

  .nostr-retry-btn {
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

  .nostr-retry-btn:hover { color: var(--green); }
  .nostr-retry-btn:focus-visible {
    outline: 2px solid var(--green);
    outline-offset: 2px;
  }

  .nostr-retry-btn:disabled {
    opacity: 0.5;
    cursor: not-allowed;
  }

  .player-wrap {
    position: relative;
    margin-bottom: var(--space-5);
  }

  .player-wrap.has-cover {
    border: 1px solid var(--line);
    border-radius: var(--radius);
    overflow: hidden;
    background: var(--paper);
  }

  .player-wrap.has-cover .player-inner {
    overflow: hidden;
  }

  .ambient-backdrop {
    position: absolute;
    inset: -30px;
    z-index: 0;
    overflow: hidden;
    pointer-events: none;
  }

  .ambient-img {
    width: 100%;
    height: 100%;
    object-fit: cover;
    filter: blur(52px) saturate(140%) brightness(0.35);
    opacity: 0.55;
    transform: scale(1.35);
  }

  .ambient-overlay {
    position: absolute;
    inset: 0;
    background: color-mix(in srgb, var(--paper) 65%, transparent);
  }

  .player-inner {
    position: relative;
    z-index: 1;
    display: flex;
    align-items: stretch;
    gap: var(--space-4);
    padding: var(--space-4);
    border: 1px solid var(--line);
    border-radius: var(--radius);
    background: var(--paper);
  }

  .player-wrap.has-cover .player-inner {
    background: color-mix(in srgb, var(--paper) 85%, transparent);
    backdrop-filter: blur(16px);
  }

  .player-cover {
    flex: none;
    width: 112px;
    height: 112px;
    border-radius: var(--radius);
    overflow: hidden;
    border: 1px solid color-mix(in srgb, var(--line) 80%, transparent);
    box-shadow: 0 6px 20px rgba(0, 0, 0, 0.28);
    background: var(--paper);
    align-self: center;
  }

  .cover-art {
    width: 100%;
    height: 100%;
    object-fit: cover;
    display: block;
  }

  .player-main {
    flex: 1 1 0;
    min-width: 0;
    display: flex;
    flex-direction: column;
    justify-content: space-between;
    gap: var(--space-3);
  }

  .player-top-row {
    display: flex;
    align-items: center;
    gap: var(--space-3);
  }

  .player-meta-block {
    display: flex;
    align-items: center;
    gap: var(--space-2);
    flex-wrap: wrap;
    font-size: var(--ui-size);
  }

  .player-voices {
    font-weight: 600;
    color: var(--ink);
  }

  .player-waveform-row {
    width: 100%;
    min-width: 0;
  }

  @media (max-width: 580px) {
    .player-inner {
      flex-direction: column-reverse;
      gap: var(--space-3);
      padding: var(--space-3);
    }
    .player-cover {
      width: 80px;
      height: 80px;
      align-self: flex-start;
    }
  }

  .play {
    flex-shrink: 0;
    width: 44px;
    height: 44px;
    border-radius: 50%;
    border: none;
    background: var(--green);
    color: var(--paper);
    font-size: 0.85rem;
    cursor: pointer;
    display: flex;
    align-items: center;
    justify-content: center;
    transition: background var(--dur-fast) ease-out, color var(--dur-fast) ease-out;
  }

  .play:hover {
    background: color-mix(in srgb, var(--green) 85%, var(--ink));
    color: var(--paper);
  }

  .player-controls {
    display: flex;
    align-items: center;
    justify-content: space-between;
    gap: var(--space-2);
    width: 100%;
    font-size: var(--ui-size);
  }

  .player-controls-right {
    display: flex;
    align-items: center;
    gap: var(--space-2);
  }

  .time {
    min-width: 9ch;
    text-align: left;
    line-height: 1;
    color: var(--ink-soft);
  }

  .speed-btn {
    font-family: var(--font-mono);
    font-size: var(--ui-size);
    color: var(--ink);
    padding: 2px 7px;
    border-radius: var(--radius);
    border: 1px solid var(--line);
    background: transparent;
    cursor: pointer;
    line-height: 1.2;
    transition: color var(--dur-fast, 120ms) ease-out, border-color var(--dur-fast, 120ms) ease-out, background var(--dur-fast, 120ms) ease-out;
  }

  .speed-btn:hover {
    color: var(--ink);
    border-color: var(--green);
    background: color-mix(in srgb, var(--green) 8%, var(--paper));
  }

  .speed-btn:focus-visible,
  .opt-btn:focus-visible {
    outline: 2px solid var(--green);
    outline-offset: 2px;
  }

  .opt-btn {
    display: inline-flex;
    align-items: center;
    gap: 5px;
    background: transparent;
    border: 1px solid var(--line);
    border-radius: var(--radius);
    padding: 2px 8px;
    color: var(--ink);
    font-family: var(--font-mono);
    font-size: var(--ui-size);
    letter-spacing: 0.02em;
    cursor: pointer;
    line-height: 1.2;
    transition: color var(--dur-fast, 120ms) ease-out, border-color var(--dur-fast, 120ms) ease-out, background var(--dur-fast, 120ms) ease-out;
  }

  .opt-btn:hover:not(.open) {
    color: var(--ink);
    border-color: var(--green);
    background: color-mix(in srgb, var(--green) 8%, var(--paper));
  }

  .opt-btn.open {
    color: var(--ink);
    border-color: var(--green);
    background: color-mix(in srgb, var(--green) 12%, var(--paper));
  }

  .opt-btn.open:hover {
    color: var(--ink);
    border-color: var(--green);
    background: color-mix(in srgb, var(--green) 16%, var(--paper));
  }

  .player-menu {
    position: relative;
    z-index: 2;
    margin-top: var(--space-2);
    padding: var(--space-3);
    border: 1px solid var(--line);
    border-radius: var(--radius);
    background: var(--paper);
    color: var(--ink);
    display: grid;
    gap: var(--space-2);
    font-size: var(--ui-size);
  }

  .menu-row {
    display: flex;
    align-items: center;
    gap: var(--space-3);
  }

  .menu-lab {
    flex: none;
    width: 7.5em;
    color: var(--ink-soft);
  }

  .menu-chips {
    display: flex;
    align-items: center;
    gap: 6px;
    flex-wrap: wrap;
  }

  .menu-chip {
    display: inline-flex;
    align-items: center;
    gap: 4px;
    background: transparent;
    border: 1px solid var(--line);
    border-radius: var(--radius);
    padding: 2px 7px;
    color: var(--ink);
    font-family: var(--font-mono);
    font-size: var(--ui-size);
    cursor: pointer;
    line-height: 1.2;
    transition: color var(--dur-fast, 120ms) ease-out, border-color var(--dur-fast, 120ms) ease-out, background var(--dur-fast, 120ms) ease-out;
  }

  .menu-chip:hover:not(.active) {
    color: var(--ink);
    border-color: var(--green);
    background: color-mix(in srgb, var(--green) 8%, var(--paper));
  }

  .menu-chip.active {
    color: var(--ink);
    border-color: var(--green);
    background: color-mix(in srgb, var(--green) 12%, var(--paper));
    font-weight: 500;
  }

  .menu-chip.active:hover {
    color: var(--ink);
    border-color: var(--green);
    background: color-mix(in srgb, var(--green) 16%, var(--paper));
  }

  .menu-hint {
    color: var(--ink-soft);
    font-size: calc(var(--ui-size) * 0.9);
  }

  .menu-hint kbd {
    background: var(--line);
    color: var(--ink);
    padding: 1px 4px;
    border-radius: 2px;
    font-family: var(--font-mono);
    font-size: calc(var(--ui-size) * 0.72);
    border: 1px solid color-mix(in srgb, var(--ink) 12%, transparent);
  }

  .chapters {
    margin: var(--space-4) 0 0;
    padding: var(--space-3);
    border: 1px solid var(--line);
    border-radius: var(--radius);
    background: transparent;
  }

  .ch-list {
    list-style: none;
    margin: 0;
    padding: 0;
    display: grid;
    gap: 3px;
  }

  .ch-item {
    border: none;
    margin: 0;
    padding: 0;
    list-style: none;
  }

  .ch-btn {
    width: 100%;
    text-align: left;
    display: flex;
    align-items: baseline;
    gap: var(--space-2);
    padding: 6px var(--space-2);
    background: transparent;
    border: 1px solid transparent;
    border-radius: var(--radius);
    color: var(--ink-soft);
    font-family: var(--font-mono);
    font-size: var(--ui-size);
    cursor: pointer;
    line-height: 1.35;
    transition: background var(--dur-fast) ease-out, color var(--dur-fast) ease-out, border-color var(--dur-fast) ease-out;
  }

  .ch-btn:hover:not(:disabled) {
    background: color-mix(in srgb, var(--green) 8%, var(--paper));
    color: var(--ink);
    border-color: color-mix(in srgb, var(--green) 35%, var(--line));
  }

  .ch-item.active .ch-btn {
    background: color-mix(in srgb, var(--green) 12%, var(--paper));
    color: var(--ink);
    border-color: var(--green);
    font-weight: 500;
  }

  .ch-item.active .ch-btn:hover:not(:disabled) {
    background: color-mix(in srgb, var(--green) 16%, var(--paper));
    color: var(--ink);
  }

  .ch-num {
    flex: none;
    width: 1.5em;
    color: var(--ink-soft);
    font-size: calc(var(--ui-size) * 0.85);
  }

  .ch-item.active .ch-num {
    color: var(--ink);
    font-weight: 600;
  }

  .ch-label {
    flex: 1 1 auto;
    overflow-wrap: anywhere;
  }

  .ch-time {
    flex: none;
    font-size: calc(var(--ui-size) * 0.85);
    color: var(--ink-soft);
    margin-left: auto;
  }

  .ch-item.active .ch-time {
    color: var(--ink-soft);
  }

  .menu-sec-title {
    color: var(--ink-soft);
    font-size: calc(var(--ui-size) * 0.78);
    letter-spacing: 0.05em;
    padding-top: var(--space-2);
    margin-top: var(--space-1);
    border-top: 1px dashed var(--line);
    text-transform: lowercase;
  }

  .menu-sec-title:first-child {
    padding-top: 0;
    margin-top: 0;
    border-top: none;
  }

  .transcript {
    list-style: none;
    padding: 0;
    margin: 0;
    max-height: 50vh;
    overflow-y: auto;
    animation: modeFade 200ms ease-out;
  }
  .transcript.text-large {
    font-size: calc(var(--ui-size) * 1.15);
    line-height: 1.6;
  }
  .transcript.text-compact {
    font-size: calc(var(--ui-size) * 0.9);
    line-height: 1.35;
  }
  @media (prefers-reduced-motion: reduce) {
    .transcript { animation: none; }
  }

  .section-head {
    color: var(--ink-soft);
    font-size: calc(var(--ui-size) * 0.85);
    letter-spacing: 0.04em;
    text-transform: lowercase;
    padding: var(--space-3) var(--space-3) var(--space-2);
    margin-top: var(--space-4);
    border-left: 2px solid var(--line);
    background: color-mix(in srgb, var(--line) 6%, transparent);
    overflow-wrap: anywhere;
  }

  .section-head:first-child {
    margin-top: var(--space-2);
  }

  li {
    display: block;
    border-left: 2px solid transparent;
    color: var(--ink-soft);
    transition:
      background var(--dur-fast) ease-out,
      border-color var(--dur-slow) ease-out,
      color var(--dur-slow) ease-out,
      font-size var(--dur-slow) ease-out,
      padding var(--dur-slow) ease-out;
  }

  .line-body {
    display: flex;
    align-items: baseline;
    gap: var(--space-2);
    flex: 1 1 auto;
    padding: var(--space-2) var(--space-3);
    min-width: 0;
  }

  .speaker-btn {
    flex: none;
    background: none;
    border: none;
    padding: 0;
    font: inherit;
    cursor: pointer;
    text-align: left;
  }

  .speaker-btn:disabled {
    cursor: default;
  }

  .speaker-btn:focus-visible {
    outline: 2px solid var(--green);
    outline-offset: 2px;
  }

  .selectable {
    user-select: text;
    -webkit-user-select: text;
    cursor: text;
  }

  .play:focus-visible {
    outline: 2px solid var(--green);
    outline-offset: 2px;
  }

  li.heard {
    color: var(--ink);
  }

  li.a .speaker {
    color: var(--voice-a);
  }

  li:not(.a) .speaker {
    color: var(--voice-b);
  }

  li.active {
    background: color-mix(in srgb, var(--green) 8%, transparent);
    border-left-color: var(--green);
    color: var(--ink);
    font-size: 1.05em;
  }

  li.active .line-body {
    padding-top: var(--space-3);
    padding-bottom: var(--space-3);
  }

  .speaker {
    display: inline-block;
    min-width: 5ch;
    margin-right: var(--space-2);
  }

  .text {
    max-width: 65ch;
  }

  .word {
    display: inline;
    transition: color var(--dur-fast, 120ms) ease-out;
  }

  .word.w-past {
    color: var(--ink);
    opacity: 0.95;
  }

  .word.w-current {
    color: var(--green);
    font-weight: 600;
    text-underline-offset: 3px;
    text-decoration: underline;
    text-decoration-color: color-mix(in srgb, var(--green) 35%, transparent);
  }

  .word.w-future {
    color: var(--ink-soft);
    opacity: 0.75;
  }

  .listen-cta-row {
    display: flex;
    align-items: center;
    justify-content: center;
    text-align: center;
    padding: var(--space-6) 0 var(--space-2);
    margin-top: var(--space-4);
  }

  .listen-cta {
    display: inline-flex;
    align-items: center;
    justify-content: center;
    gap: var(--space-2);
    background: transparent;
    border: 1px solid var(--line);
    border-radius: var(--radius);
    color: var(--ink);
    font-family: var(--font-mono);
    font-size: var(--ui-size);
    padding: var(--space-2) var(--space-4);
    min-height: 40px;
    max-width: 100%;
    text-align: center;
    cursor: pointer;
    letter-spacing: 0.02em;
    text-decoration: none;
    line-height: 1.3;
    transition: background var(--dur-fast, 120ms) ease-out, color var(--dur-fast, 120ms) ease-out, border-color var(--dur-fast, 120ms) ease-out;
  }

  .listen-cta:hover {
    background: color-mix(in srgb, var(--green) 12%, var(--paper));
    color: var(--ink);
    border-color: var(--green);
  }

  .listen-cta:focus-visible {
    outline: 2px solid var(--green);
    outline-offset: 2px;
  }

  .resume-hint {
    color: var(--green);
    font-size: calc(var(--ui-size) * 0.85);
    margin-right: var(--space-2);
    animation: fadeout 3.5s forwards;
  }

  .sleep-indicator {
    display: inline-flex;
    align-items: center;
    gap: 4px;
    background: transparent;
    border: 1px solid var(--line);
    border-radius: var(--radius);
    padding: 1px 6px;
    color: var(--ink-soft);
    font-family: var(--font-mono);
    font-size: calc(var(--ui-size) * 0.78);
    cursor: pointer;
    margin-right: var(--space-1);
    transition: color var(--dur-fast, 120ms) ease-out, border-color var(--dur-fast, 120ms) ease-out;
  }

  .sleep-indicator:hover {
    color: var(--green);
    border-color: var(--green);
  }

  .sleep-countdown {
    color: var(--green);
    font-size: var(--ui-size);
    margin-left: 4px;
  }

  .line-row {
    display: flex;
    align-items: baseline;
    width: 100%;
    gap: var(--space-2);
  }

  .quote-btn {
    opacity: 0;
    display: inline-flex;
    align-items: center;
    gap: 4px;
    background: transparent;
    border: none;
    color: var(--ink-soft);
    padding: 0 4px;
    cursor: pointer;
    vertical-align: middle;
    flex-shrink: 0;
    transition: opacity var(--dur-fast, 120ms) ease-out, color var(--dur-fast, 120ms) ease-out;
  }

  li:hover .quote-btn,
  .quote-btn:focus-visible,
  .quote-btn.copied {
    opacity: 1;
  }

  .quote-btn:hover,
  .quote-btn.copied {
    color: var(--green);
  }

  .copied-tag {
    font-size: calc(var(--ui-size) * 0.72);
    color: var(--green);
  }

  /* Clips tab content */
  .clips-content {
    display: grid;
    gap: var(--space-3);
  }

  .clips-list {
    display: grid;
    gap: var(--space-2);
    min-width: 0;
    max-width: 100%;
  }

  .clip-card {
    border: 1px solid var(--line);
    border-radius: var(--radius);
    padding: var(--space-3);
    display: grid;
    gap: var(--space-2);
    background: color-mix(in srgb, var(--paper) 60%, transparent);
    min-width: 0;
    max-width: 100%;
    box-sizing: border-box;
    overflow: hidden;
  }

  .clip-info {
    display: flex;
    align-items: center;
    justify-content: space-between;
    gap: var(--space-2);
    min-width: 0;
  }

  .clip-label {
    color: var(--ink);
    font-weight: 600;
    font-size: var(--ui-size);
    overflow: hidden;
    text-overflow: ellipsis;
    white-space: nowrap;
    min-width: 0;
  }

  .clip-dur {
    color: var(--ink-soft);
    font-size: calc(var(--ui-size) * 0.85);
    flex-shrink: 0;
  }

  .clip-actions {
    display: flex;
    align-items: center;
    gap: var(--space-2);
    flex-wrap: wrap;
    min-width: 0;
    max-width: 100%;
  }

  .clip-play-btn {
    display: inline-flex;
    align-items: center;
    gap: 4px;
    background: var(--green);
    color: var(--paper);
    border: 1px solid var(--green);
    border-radius: var(--radius);
    padding: 4px 10px;
    font-family: var(--font-mono);
    font-size: var(--ui-size);
    cursor: pointer;
    line-height: 1.2;
    transition: background var(--dur-fast) ease-out, color var(--dur-fast) ease-out;
  }

  .clip-play-btn:hover {
    background: color-mix(in srgb, var(--green) 85%, var(--ink));
    border-color: var(--green);
    color: var(--paper);
  }

  .clip-play-btn:focus-visible {
    outline: 2px solid var(--green);
    outline-offset: 2px;
  }

  .clip-time {
    font-size: calc(var(--ui-size) * 0.82);
    color: var(--ink-soft);
    min-width: 8ch;
    text-align: right;
  }

  .clip-share-btn {
    display: inline-flex;
    align-items: center;
    gap: 4px;
    background: transparent;
    border: 1px solid var(--line);
    border-radius: var(--radius);
    padding: 4px 10px;
    color: var(--ink-soft);
    font-family: var(--font-mono);
    font-size: var(--ui-size);
    cursor: pointer;
    line-height: 1.2;
    transition: color var(--dur-fast) ease-out, border-color var(--dur-fast) ease-out;
  }

  .clip-share-btn:hover {
    color: var(--ink);
    border-color: var(--green);
    background: color-mix(in srgb, var(--green) 8%, var(--paper));
  }

  .clip-share-btn:focus-visible {
    outline: 2px solid var(--green);
    outline-offset: 2px;
  }

  .clip-err {
    color: var(--voice-b);
    font-size: calc(var(--ui-size) * 0.88);
    margin: 0;
  }

  /* Slice selection state */
  li.slice-selected {
    background: color-mix(in srgb, var(--green) 10%, transparent);
    border-left-color: var(--green);
  }
  .slice-handle {
    opacity: 0;
    display: inline-flex;
    align-items: center;
    justify-content: center;
    min-width: 28px;
    min-height: 28px;
    padding: 2px 6px;
    background: transparent;
    border: 1px solid transparent;
    border-radius: var(--radius);
    cursor: pointer;
    color: var(--ink-soft);
    font-size: 0.9rem;
    transition: opacity var(--dur-fast) ease-out, background var(--dur-fast) ease-out, border-color var(--dur-fast) ease-out, color var(--dur-fast) ease-out;
  }
  li:hover .slice-handle,
  .slice-handle:focus-visible,
  .slice-handle.active {
    opacity: 1;
  }
  .slice-handle:hover:not(.active) {
    background: color-mix(in srgb, var(--green) 10%, var(--paper));
    border-color: var(--green);
    color: var(--ink);
  }
  .slice-handle.active {
    background: color-mix(in srgb, var(--green) 12%, var(--paper));
    border-color: var(--green);
    color: var(--ink);
  }
  .slice-handle.active:hover {
    background: color-mix(in srgb, var(--green) 20%, var(--paper));
    border-color: var(--green);
    color: var(--ink);
  }
  .slice-handle:focus-visible {
    outline: 2px solid var(--green);
    outline-offset: 2px;
  }
  @media (max-width: 640px) {
    .slice-handle {
      opacity: 0.65;
    }
  }

  /* Inline slice preview card */
  .slice-preview {
    border: 1px solid var(--green);
    border-radius: var(--radius);
    background: color-mix(in srgb, var(--green) 6%, var(--paper));
    padding: var(--space-3);
    display: grid;
    gap: var(--space-2);
  }
  .slice-preview-head {
    display: flex;
    flex-wrap: wrap;
    gap: var(--space-2) var(--space-3);
    align-items: center;
  }
  .slice-range {
    font-weight: 600;
    color: var(--ink);
    font-size: var(--ui-size);
  }
  .slice-speakers {
    color: var(--green);
    font-weight: 500;
    font-size: calc(var(--ui-size) * 0.88);
  }
  .slice-dur {
    color: var(--ink-soft);
    font-size: calc(var(--ui-size) * 0.85);
    margin-left: auto;
  }
  .slice-snippet {
    margin: 0;
    color: var(--ink-soft);
    font-size: calc(var(--ui-size) * 0.88);
    line-height: 1.5;
    border-left: 2px solid var(--line);
    padding-left: var(--space-2);
    overflow-wrap: anywhere;
  }
  .slice-preview-actions {
    display: flex;
    gap: var(--space-2);
    flex-wrap: wrap;
    align-items: center;
  }
  .slice-preview-play {
    background: var(--green);
    color: var(--paper);
    border-color: var(--green);
  }
  .slice-preview-play:hover {
    background: color-mix(in srgb, var(--green) 85%, var(--ink));
    border-color: var(--green);
    color: var(--paper);
  }
  .clip-download-btn,
  .clip-copy-url {
    text-decoration: none;
  }
  .clip-share-row {
    display: flex;
    gap: var(--space-2);
    align-items: center;
    margin-top: var(--space-1);
    min-width: 0;
    max-width: 100%;
  }
  .clip-url {
    flex: 1 1 auto;
    min-width: 0;
    overflow: hidden;
    text-overflow: ellipsis;
    white-space: nowrap;
    color: var(--ink-soft);
    font-size: calc(var(--ui-size) * 0.78);
  }
  .clip-card audio {
    width: 100%;
    height: 28px;
  }
  @media (max-width: 600px) {
    .clip-share-row {
      flex-wrap: wrap;
    }
    .clip-url {
      word-break: break-all;
    }
  }

  /* V4V Quick Strip & Mode Switch Tabs (DUE-072 / DUE-074) */
  /* V4V Quick Strip & Mode Switch Tabs (DUE-072 / DUE-074) */
  .v4v-quick-strip {
    display: flex;
    align-items: center;
    justify-content: space-between;
    gap: var(--space-3);
    margin: var(--space-3) 0 var(--space-3);
    font-size: calc(var(--ui-size) * 0.85);
    flex-wrap: wrap;
  }
  .v4v-boost-actions {
    display: flex;
    align-items: center;
    gap: var(--space-2);
    flex-wrap: wrap;
  }
  .v4v-lab {
    color: var(--ink-soft);
    display: inline-flex;
    align-items: center;
    gap: 4px;
    font-family: var(--font-mono);
    text-transform: lowercase;
  }
  .v4v-pill {
    background: transparent;
    border: 1px solid var(--line);
    border-radius: var(--radius);
    padding: 3px 10px;
    min-height: 28px;
    color: var(--ink);
    cursor: pointer;
    font-family: var(--font-mono);
    font-size: calc(var(--ui-size) * 0.82);
    transition: color var(--dur-fast) ease-out, background var(--dur-fast) ease-out, border-color var(--dur-fast) ease-out;
  }
  .v4v-pill:hover:not(:disabled) {
    background: color-mix(in srgb, var(--green) 12%, var(--paper));
    color: var(--ink);
    border-color: var(--green);
  }
  .v4v-pill:disabled {
    opacity: 0.5;
    cursor: not-allowed;
  }
  .v4v-custom-btn {
    display: inline-flex;
    align-items: center;
    gap: 4px;
    text-decoration: none;
  }
  .v4v-stream-group {
    display: inline-flex;
    align-items: center;
    gap: var(--space-2);
    margin-left: auto;
    flex-wrap: wrap;
  }
  .v4v-sep {
    color: var(--line);
    user-select: none;
  }
  .v4v-stream-toggle {
    background: transparent;
    border: 1px dashed var(--line);
    border-radius: var(--radius);
    padding: 3px 10px;
    min-height: 28px;
    color: var(--ink-soft);
    cursor: pointer;
    font-family: var(--font-mono);
    font-size: calc(var(--ui-size) * 0.82);
    display: inline-flex;
    align-items: center;
    gap: 4px;
    transition: all var(--dur-fast) ease-out;
  }
  .v4v-stream-toggle:hover:not(.active) {
    color: var(--ink);
    border-color: var(--ink-soft);
  }
  .v4v-stream-toggle.active {
    border-style: solid;
    border-color: var(--green);
    color: var(--ink);
    background: color-mix(in srgb, var(--green) 12%, var(--paper));
    font-weight: 600;
  }
  .v4v-stream-toggle.active:hover {
    background: color-mix(in srgb, var(--green) 18%, var(--paper));
    color: var(--ink);
  }
  .v4v-feedback {
    font-size: calc(var(--ui-size) * 0.8);
    color: var(--ink-soft);
  }
  .v4v-feedback.ok {
    color: var(--green);
    font-weight: 600;
  }
  .v4v-feedback.err {
    color: #c53030;
  }
  .v4v-rate-btn {
    background: transparent;
    border: 1px solid var(--line);
    border-radius: var(--radius);
    padding: 3px 10px;
    min-height: 28px;
    color: var(--ink-soft);
    cursor: pointer;
    font-family: var(--font-mono);
    font-size: calc(var(--ui-size) * 0.82);
    display: inline-flex;
    align-items: center;
    transition: all var(--dur-fast) ease-out;
  }
  .v4v-rate-btn:hover {
    color: var(--ink);
    border-color: var(--green);
    background: color-mix(in srgb, var(--green) 8%, var(--paper));
  }
  .v4v-rate-popover {
    display: inline-flex;
    align-items: center;
    gap: 5px;
    background: color-mix(in srgb, var(--ink) 4%, var(--paper));
    border: 1px solid var(--line);
    border-radius: var(--radius);
    padding: 2px 6px;
  }
  .v4v-rate-label {
    font-size: calc(var(--ui-size) * 0.75);
    color: var(--ink-soft);
  }
  .v4v-rate-input {
    width: 52px;
    min-height: 24px;
    border: 1px solid var(--line);
    border-radius: var(--radius);
    padding: 1px 4px;
    background: color-mix(in srgb, var(--paper) 85%, transparent);
    color: var(--ink);
    font-size: calc(var(--ui-size) * 0.78);
    text-align: center;
  }
  .v4v-rate-input:focus-visible {
    outline: 2px solid var(--green);
    outline-offset: 2px;
  }
  .v4v-rate-suffix {
    font-size: calc(var(--ui-size) * 0.75);
    color: var(--ink-soft);
  }
  .v4v-rate-close {
    background: transparent;
    border: none;
    color: var(--ink-soft);
    cursor: pointer;
    font-family: var(--font-mono);
    font-size: calc(var(--ui-size) * 0.8);
    padding: 0 3px;
    line-height: 1;
  }
  .v4v-rate-close:hover {
    color: var(--ink);
  }

  .mode-switch-strip {
    display: flex;
    width: 100%;
    margin: var(--space-2) 0 var(--space-4);
    position: relative;
  }
  .mode-switch-strip .seg {
    display: flex;
    width: 100%;
    gap: 3px;
    align-items: stretch;
    background: color-mix(in srgb, var(--ink) 4%, var(--paper));
    border: 1px solid color-mix(in srgb, var(--ink) 14%, var(--line));
    border-radius: var(--radius);
    padding: 3px;
    overflow-x: auto;
    scrollbar-width: none;
    -ms-overflow-style: none;
    -webkit-overflow-scrolling: touch;
    touch-action: pan-x;
  }
  .mode-switch-strip .seg::-webkit-scrollbar {
    display: none;
  }
  .mode-switch-strip .seg button {
    flex: 1 1 0;
    min-width: 0;
    background: transparent;
    border: none;
    border-radius: calc(var(--radius) - 1px);
    color: var(--ink-soft);
    font-family: var(--font-mono);
    font-size: calc(var(--ui-size) * 0.85);
    font-weight: 500;
    min-height: 34px;
    padding: 4px 6px;
    cursor: pointer;
    text-transform: lowercase;
    display: inline-flex;
    align-items: center;
    justify-content: center;
    gap: 6px;
    white-space: nowrap;
    transition: color var(--dur-fast) ease-out, background var(--dur-fast) ease-out;
  }
  .mode-switch-strip .seg button:hover:not(.sel) {
    color: var(--ink);
  }
  .mode-switch-strip .seg button:focus-visible {
    outline: 2px solid var(--green);
    outline-offset: 2px;
  }
  .mode-switch-strip .seg button.sel {
    background: var(--green);
    color: var(--paper);
    border: 1px solid var(--green);
    font-weight: 600;
  }
  .mode-switch-strip .seg button.sel:hover {
    background: color-mix(in srgb, var(--green) 90%, var(--ink));
    color: var(--paper);
  }
  .mode-count {
    background: color-mix(in srgb, var(--voice-b, #8a4200) 16%, var(--paper));
    color: var(--voice-b, #8a4200);
    border: 1px solid color-mix(in srgb, var(--voice-b, #8a4200) 30%, var(--line));
    font-size: calc(var(--ui-size) * 0.72);
    padding: 0 5px;
    border-radius: var(--radius);
    font-weight: 600;
    line-height: 1.3;
  }
  .mode-switch-strip .seg button.sel .mode-count {
    background: color-mix(in srgb, var(--paper) 20%, transparent);
    color: var(--paper);
    border-color: color-mix(in srgb, var(--paper) 40%, transparent);
  }
  @media (max-width: 780px) {
    .v4v-quick-strip {
      flex-direction: column;
      align-items: flex-start;
      gap: var(--space-2);
    }
    .v4v-stream-group {
      margin-left: 0;
    }
  }
  @media (max-width: 640px) {
    .mode-switch-strip {
      -webkit-mask-image: linear-gradient(to right, black calc(100% - 24px), transparent 100%);
      mask-image: linear-gradient(to right, black calc(100% - 24px), transparent 100%);
    }
    .mode-switch-strip .seg {
      display: inline-flex;
      width: 100%;
    }
    .mode-switch-strip .seg button {
      flex: 0 0 auto;
      padding: 6px 12px;
    }
    .facts-action-pill {
      flex: 1 1 calc(50% - var(--space-2));
      justify-content: center;
    }
    .fact-row {
      flex-direction: column;
      gap: 2px;
      padding: 8px 0;
    }
    .facts dt {
      width: auto;
      flex: none;
      font-size: calc(var(--ui-size) * 0.78);
      text-transform: uppercase;
      opacity: 0.85;
    }
  }

  /* Key Takeaways View (DUE-071 / DUE-072) */
  .takeaways-view {
    display: flex;
    flex-direction: column;
    gap: var(--space-4);
    margin-bottom: var(--space-6);
    animation: modeFade 200ms ease-out;
  }
  @keyframes modeFade {
    from { opacity: 0; transform: translateY(4px); }
    to { opacity: 1; transform: translateY(0); }
  }
  @media (prefers-reduced-motion: reduce) {
    .takeaways-view { animation: none; }
  }
  .exec-summary-card {
    background: var(--paper-warm, var(--paper));
    border: 1px solid var(--line);
    border-left: 4px solid var(--voice-b, #8a4200);
    border-radius: var(--radius);
    padding: var(--space-4);
  }
  .exec-head {
    display: flex;
    justify-content: space-between;
    align-items: center;
    margin-bottom: var(--space-2);
  }
  .exec-tag {
    color: var(--voice-b, #8a4200);
    font-weight: 700;
    font-size: calc(var(--ui-size) * 0.9);
    display: inline-flex;
    align-items: center;
    gap: var(--space-2);
  }
  .exec-actions {
    display: flex;
    gap: var(--space-2);
  }
  .exec-btn {
    background: transparent;
    border: 1px solid var(--line);
    border-radius: var(--radius);
    padding: 2px 8px;
    color: var(--ink-soft);
    font-size: calc(var(--ui-size) * 0.8);
    cursor: pointer;
    display: inline-flex;
    align-items: center;
    gap: 4px;
  }
  .exec-btn:hover {
    color: var(--ink);
    border-color: var(--ink);
  }
  .exec-text {
    margin: 0;
    font-size: calc(var(--ui-size) * 1.05);
    line-height: 1.6;
    color: var(--ink);
  }

  .takeaways-list {
    display: flex;
    flex-direction: column;
    gap: var(--space-3);
  }
  .takeaway-card {
    background: var(--paper);
    border: 1px solid var(--line);
    border-radius: var(--radius);
    padding: var(--space-3) var(--space-4);
    transition: border-color 0.15s ease;
  }
  .takeaway-card:hover {
    border-color: var(--ink-soft);
  }
  .tk-header {
    display: flex;
    align-items: baseline;
    gap: var(--space-3);
    margin-bottom: var(--space-2);
  }
  .tk-jump-btn {
    background: var(--line);
    border: none;
    border-radius: var(--radius);
    padding: 2px 8px;
    font-size: calc(var(--ui-size) * 0.8);
    color: var(--ink);
    cursor: pointer;
    display: inline-flex;
    align-items: center;
    gap: 4px;
    white-space: nowrap;
    transition: all 0.15s ease;
  }
  .tk-jump-btn:hover {
    background: var(--green);
    color: var(--paper);
  }
  .tk-title {
    margin: 0;
    font-size: calc(var(--ui-size) * 1.05);
    font-weight: 600;
    color: var(--ink);
  }
  .tk-body {
    margin: 0;
    font-size: calc(var(--ui-size) * 0.95);
    line-height: 1.55;
    color: var(--ink-soft);
  }
  .takeaways-empty {
    padding: var(--space-6);
    text-align: center;
    color: var(--ink-soft);
    border: 1px dashed var(--line);
    border-radius: var(--radius);
  }
  /* Source-Quote Inspector (DUE-077 / #262) */
  .exec-quote-row,
  .tk-quote-row {
    margin-top: var(--space-2);
    display: grid;
    gap: var(--space-1);
  }
  .quote-toggle {
    display: inline-flex;
    align-items: center;
    gap: 4px;
    background: transparent;
    border: 1px solid transparent;
    border-radius: var(--radius);
    padding: 1px 6px;
    color: var(--ink-soft);
    font-family: var(--font-mono);
    font-size: calc(var(--ui-size) * 0.78);
    cursor: pointer;
    letter-spacing: 0.02em;
  }
  .quote-toggle:hover {
    color: var(--green);
    border-color: var(--line);
    background: color-mix(in srgb, var(--green) 4%, transparent);
  }
  .quote-toggle:focus-visible {
    outline: 2px solid var(--green);
    outline-offset: 2px;
  }
  .quote-toggle .arrow {
    font-size: calc(var(--ui-size) * 0.72);
    color: var(--green);
  }
  .source-quote {
    margin: 0;
    padding: var(--space-2) var(--space-3);
    border-left: 2px solid var(--voice-b, #8a4200);
    background: color-mix(in srgb, var(--voice-b, #8a4200) 6%, transparent);
    font-family: var(--font-serif, Georgia, serif);
    font-style: italic;
    font-size: calc(var(--ui-size) * 0.88);
    line-height: 1.5;
    color: var(--ink-soft);
    overflow-wrap: anywhere;
  }
  .factuality-badge {
    margin-top: var(--space-2);
    display: inline-flex;
    align-items: center;
    gap: var(--space-2);
    font-size: calc(var(--ui-size) * 0.78);
  }
  .fact-label {
    color: var(--ink-soft);
    text-transform: lowercase;
    letter-spacing: 0.03em;
  }
  .fact-score {
    padding: 1px 6px;
    border-radius: var(--radius);
    background: color-mix(in srgb, var(--green) 12%, transparent);
    border: 1px solid color-mix(in srgb, var(--green) 25%, transparent);
    color: var(--green);
    font-weight: 600;
  }
  .fact-score.fact-low {
    background: color-mix(in srgb, var(--voice-b, #8A4200) 10%, transparent);
    border-color: color-mix(in srgb, var(--voice-b, #8A4200) 25%, transparent);
    color: var(--voice-b, #8A4200);
  }
  .slice-boost-action {
    background: transparent;
    border-color: var(--voice-b, #8a4200);
    color: var(--voice-b, #8a4200);
  }
  .slice-boost-action:hover {
    background: color-mix(in srgb, var(--voice-b, #8a4200) 12%, var(--paper));
    border-color: var(--voice-b, #8a4200);
    color: var(--ink);
  }

  /* Unified Tab Panels and Empty States */
  .tab-panel {
    animation: modeFade 140ms ease-out;
    padding-top: var(--space-2);
  }
  .tab-panel[hidden] {
    display: none !important;
  }
  @media (prefers-reduced-motion: reduce) {
    .tab-panel { animation: none; }
  }

  .tab-kicker-banner {
    display: flex;
    align-items: center;
    justify-content: space-between;
    gap: var(--space-3);
    padding: var(--space-2) var(--space-3);
    margin-bottom: var(--space-3);
    background: color-mix(in srgb, var(--green) 7%, var(--paper));
    border: 1px solid color-mix(in srgb, var(--green) 25%, var(--line));
    border-radius: var(--radius);
    color: var(--ink);
    font-size: calc(var(--ui-size) * 0.85);
    line-height: 1.4;
    flex-wrap: wrap;
  }
  .kicker-lead {
    display: inline-flex;
    align-items: center;
    gap: 6px;
    color: var(--ink);
  }
  .kicker-lead strong {
    color: var(--green);
  }
  .kicker-action-btn {
    display: inline-flex;
    align-items: center;
    gap: 4px;
    background: transparent;
    border: 1px solid var(--line);
    border-radius: var(--radius);
    padding: 1px 7px;
    color: var(--ink-soft);
    font-size: calc(var(--ui-size) * 0.78);
    cursor: pointer;
    text-transform: lowercase;
    transition: all var(--dur-fast) ease-out;
  }
  .kicker-action-btn:hover {
    color: var(--ink);
    border-color: var(--green);
    background: color-mix(in srgb, var(--green) 8%, var(--paper));
  }

  .tab-empty-state {
    display: flex;
    flex-direction: column;
    align-items: center;
    justify-content: center;
    padding: var(--space-6) var(--space-4);
    border: 1px dashed var(--line);
    border-radius: var(--radius);
    background: color-mix(in srgb, var(--ink) 2%, var(--paper));
    text-align: center;
    gap: var(--space-2);
    margin: var(--space-2) 0 var(--space-4);
  }
  .empty-icon {
    color: var(--ink-soft);
    opacity: 0.7;
    margin-bottom: var(--space-1);
  }
  .empty-title {
    margin: 0;
    color: var(--ink);
    font-weight: 600;
    font-size: calc(var(--ui-size) * 0.95);
    text-transform: lowercase;
  }
  .empty-sub {
    margin: 0;
    color: var(--ink-soft);
    font-size: calc(var(--ui-size) * 0.82);
    max-width: 48ch;
    line-height: 1.5;
  }
  .empty-action {
    margin-top: var(--space-2);
    display: inline-flex;
    align-items: center;
    gap: 6px;
    background: transparent;
    border: 1px solid var(--line);
    border-radius: var(--radius);
    padding: 3px 10px;
    color: var(--ink-soft);
    font-family: var(--font-mono);
    font-size: calc(var(--ui-size) * 0.82);
    cursor: pointer;
    text-transform: lowercase;
    transition: all var(--dur-fast) ease-out;
  }
  .empty-action:hover {
    color: var(--ink);
    border-color: var(--green);
    background: color-mix(in srgb, var(--green) 8%, var(--paper));
  }

  /* Inline Slice Banner in Transcript View */
  .slice-banner {
    display: flex;
    align-items: center;
    justify-content: space-between;
    gap: var(--space-2);
    padding: var(--space-2) var(--space-3);
    margin-bottom: var(--space-3);
    background: color-mix(in srgb, var(--green) 8%, var(--paper));
    border: 1px solid color-mix(in srgb, var(--green) 30%, var(--line));
    border-radius: var(--radius);
    flex-wrap: wrap;
  }
  .slice-banner-info {
    display: inline-flex;
    align-items: center;
    gap: 6px;
    font-size: calc(var(--ui-size) * 0.85);
    color: var(--green);
    font-weight: 600;
  }
  .slice-banner-actions {
    display: inline-flex;
    align-items: center;
    gap: var(--space-1);
    flex-wrap: wrap;
  }

  /* Inline Highlights Tab View */
  .hl-filter-bar {
    display: flex;
    align-items: center;
    gap: 6px;
    margin-bottom: var(--space-3);
    flex-wrap: wrap;
  }
  .hl-filter-chip {
    background: transparent;
    border: 1px solid var(--line);
    border-radius: var(--radius);
    padding: 2px 8px;
    color: var(--ink-soft);
    font-family: var(--font-mono);
    font-size: calc(var(--ui-size) * 0.78);
    cursor: pointer;
    display: inline-flex;
    align-items: center;
    gap: 5px;
    transition: all var(--dur-fast) ease-out;
  }
  .hl-filter-chip:hover:not(.active) {
    color: var(--ink);
    border-color: var(--ink-soft);
  }
  .hl-filter-chip.active {
    background: color-mix(in srgb, var(--green) 12%, var(--paper));
    color: var(--ink);
    border-color: var(--green);
    font-weight: 600;
  }
  .hl-filter-chip.active:hover {
    background: color-mix(in srgb, var(--green) 20%, var(--paper));
    border-color: var(--green);
    color: var(--ink);
  }
  .hl-dot {
    width: 6px;
    height: 6px;
    border-radius: 50%;
    display: inline-block;
  }
  .hl-dot-user { background: var(--voice-a, #84b832); }
  .hl-dot-friend { background: #8fb8c4; }
  .hl-dot-global { background: var(--ink-soft); }

  .hl-list {
    display: flex;
    flex-direction: column;
    gap: var(--space-2);
  }
  .hl-item {
    padding: var(--space-3) var(--space-4);
    border-radius: var(--radius);
    border: 1px solid var(--line);
    background: color-mix(in srgb, var(--ink) 3%, var(--paper));
    border-left: 3px solid var(--green);
  }
  .hl-item-top {
    display: flex;
    align-items: center;
    justify-content: space-between;
    gap: var(--space-2);
    font-size: calc(var(--ui-size) * 0.8);
    color: var(--ink-soft);
    margin-bottom: 6px;
    flex-wrap: wrap;
  }
  .hl-author-group {
    display: inline-flex;
    align-items: center;
    gap: 6px;
  }
  .hl-badge {
    font-size: calc(var(--ui-size) * 0.7);
    padding: 0 5px;
    border-radius: var(--radius);
    font-weight: 600;
    text-transform: uppercase;
    letter-spacing: 0.04em;
    display: inline-block;
    border: 1px solid var(--line);
  }
  .hl-badge-user {
    background: color-mix(in srgb, var(--green) 18%, var(--paper));
    color: var(--ink);
    border-color: var(--green);
  }
  .hl-badge-friend {
    background: color-mix(in srgb, #8fb8c4 18%, var(--paper));
    color: #8fb8c4;
    border-color: #8fb8c4;
  }
  .hl-badge-global {
    background: color-mix(in srgb, var(--ink) 6%, var(--paper));
    color: var(--ink-soft);
  }
  .hl-author {
    color: var(--ink-soft);
  }
  .hl-actions {
    display: inline-flex;
    align-items: center;
    gap: 6px;
  }
  .hl-action-btn {
    display: inline-flex;
    align-items: center;
    gap: 4px;
    background: transparent;
    border: 1px solid var(--line);
    border-radius: var(--radius);
    color: var(--ink-soft);
    font-size: calc(var(--ui-size) * 0.78);
    padding: 2px 7px;
    cursor: pointer;
    font-family: var(--font-mono);
    text-transform: lowercase;
    transition: color var(--dur-fast) ease-out, border-color var(--dur-fast) ease-out, background var(--dur-fast) ease-out;
  }
  .hl-action-btn:hover {
    color: var(--ink);
    border-color: var(--green);
    background: color-mix(in srgb, var(--green) 8%, var(--paper));
  }
  .hl-quote {
    margin: 0;
    padding: 0;
    color: var(--ink);
    font-style: italic;
    font-size: calc(var(--ui-size) * 0.95);
    line-height: 1.45;
  }
</style>

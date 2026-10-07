import type { StyleMeta } from './styles'

export type StageName =
  | 'fetch'
  | 'extract'
  | 'script'
  | 'voice'
  | 'master'

export type JobState =
  | 'queued'
  | 'running'
  | 'done'
  | 'failed'
  | 'cancelled'
  // UX phase 2: paused after the script until the listener approves it
  | 'awaiting_review'

export interface AudioFacts {
  bytes: number
  kbps: number
  sample_rate?: number
}

export interface StageStatus {
  name: StageName
  status: 'pending' | 'running' | 'done' | 'failed'
  ms?: number
  detail?: string
  meta?: {
    lint?: unknown
    audio?: AudioFacts
    tuning?: { speed?: number; emotion?: string; gap_ms?: number; music_bed?: boolean }
    voices?: string[]
    voice_map?: Record<string, string>
    source_lang?: string
    engine?: string
    llm_provider?: string
    llm_model?: string
  }
  queue_position?: number
  estimated_wait_ms?: number
}

export interface DialogueLine {
  speaker: string
  text: string
  t0?: number
  name?: string
  src?: number[]
}

export interface KeyTakeaway {
  id?: string
  title: string
  text: string
  source_quote?: string
  section_idx?: number
  timestamp_ms?: number
  time_formatted?: string
}

export interface Job {
  id: string
  title: string
  url?: string
  created_at?: number
  duration_ms?: number | null
  /** length of the finished audio; duration_ms is the render time */
  audio_seconds?: number | null
  style?: string
  format?: string
  language?: string
  provider?: string | null
  tone?: string | null
  explicit?: boolean
  state: JobState
  current_stage?: StageName
  stages: StageStatus[]
  script?: DialogueLine[]
  description?: string
  error?: string
  watchlist_id?: string | null
  voice_profile?: VoiceProfile | null
  digest?: boolean
  digest_sources?: string[] | null
  chapters?: { index: number; title: string; url?: string; word_offset?: number }[] | null
  og_image?: string | null
  queue_position?: number | null
  queue_length?: number
  estimated_wait_ms?: number | null
  estimated_wait_seconds?: number | null
  ahead_title?: string | null
  ahead_count?: number
  show_name?: string | null
  show_author?: string | null
  show_category?: string | null
  executive_summary?: string | null
  executive_quote?: string | null
  key_takeaways?: KeyTakeaway[] | null
  factuality_score?: number | null
}

const API_BASE = import.meta.env.VITE_API_BASE ?? ''

async function get<T>(path: string, timeoutMs = 4000): Promise<T> {
  const ctrl = new AbortController()
  const timer = setTimeout(() => ctrl.abort(), timeoutMs)
  try {
    const res = await fetch(`${API_BASE}${path}`, { signal: ctrl.signal })
    if (!res.ok) throw new Error(`HTTP ${res.status}`)
    return (await res.json()) as T
  } finally {
    clearTimeout(timer)
  }
}

export interface ProviderInfo {
  id: string
  label: string
  installed: boolean
  fix: string
  ui_fix_hint?: string
  ui_badge?: string
  license?: string
  commercial_use?: boolean
  renderer?: string
  location?: 'local' | 'cloud'
}

export interface ProviderStatus {
  providers: ProviderInfo[]
  active: string[]
  default?: string
}

export async function fetchProviders(): Promise<ProviderStatus> {
  return await get<ProviderStatus>('/providers')
}

export interface LlmProbeResult {
  status: 'ok' | 'offline' | 'unconfigured' | 'none'
  engine: string
  installed: boolean
  badge?: string
  label?: string
  model_id?: string
  root?: string
  max_context?: number
  base?: string
  hardware?: string
  quant?: string
  speed?: string
  summary?: string
  best_for?: string
  note?: string
  error?: string
  location?: 'local' | 'cloud'
}

export async function probeLlm(params?: {
  engine?: string
  custom_base?: string
  custom_model?: string
  api_key?: string
}): Promise<LlmProbeResult> {
  const query = new URLSearchParams()
  if (params?.engine) query.set('engine', params.engine)
  if (params?.custom_base) query.set('custom_base', params.custom_base)
  if (params?.custom_model) query.set('custom_model', params.custom_model)
  if (params?.api_key) query.set('api_key', params.api_key)
  const qs = query.toString() ? `?${query.toString()}` : ''
  return await get<LlmProbeResult>(`/llm/probe${qs}`, 5000)
}

/** Model ids a cloud writer offers right now (asked live, never a built-in list). */
export async function fetchLlmModels(engine: 'opencode' | 'kimi_nim'): Promise<string[]> {
  const res = await get<{ models: string[] }>(`/llm/models?engine=${engine}`, 35000)
  return res.models ?? []
}

export interface VoiceProfile {
  'a.timbre'?: string
  'b.timbre'?: string
  'c.timbre'?: string
  'solo.timbre'?: string
  'solo.name'?: string
  'a.name'?: string
  'b.name'?: string
  'c.name'?: string
  'a.emotion'?: string
  'b.emotion'?: string
  'c.emotion'?: string
  'solo.emotion'?: string
  count?: number
  emotion?: string
  speed?: number
  gap_ms?: number
  [key: string]: string | number | undefined
}

export interface JobOptions {
  style?: string
  format?: 'dialog' | 'narration'
  tone?: string
  language?: string
  hosts?: number
  explicit?: boolean
  voice?: VoiceProfile
  show_name?: string
  show_author?: string
  show_category?: string
  // VOZONDA-LEN-1: exact minutes win over a preset name
  target_minutes?: number
  length?: 'short' | 'default' | 'long'
  // UX phase 2: what the hosts should dig into (steers emphasis, adds no facts)
  focus?: string
  // UX phase 2: pause after the script so it can be reviewed (single source only)
  review_script?: boolean
  // 2+ sources: one conversation across them (default) instead of a digest
  combine?: boolean
}

export async function createJob(url: string, opts: JobOptions = {}): Promise<Job> {
  const res = await fetch(`${API_BASE}/jobs`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ url, ...opts })
  })
  if (!res.ok) {
    let detail = `HTTP ${res.status}`
    try { const b = await res.json(); if (b?.detail) detail = b.detail } catch { void detail }
    throw new Error(detail)
  }
  return (await res.json()) as Job
}

export async function createDigestJob(sources: string[], opts: JobOptions = {}): Promise<Job> {
  const res = await fetch(`${API_BASE}/jobs`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ digest: true, digest_sources: sources, ...opts })
  })
  if (!res.ok) {
    let detail = `HTTP ${res.status}`
    try { const b = await res.json(); if (b?.detail) detail = b.detail } catch { void detail }
    throw new Error(detail)
  }
  return (await res.json()) as Job
}

export async function createJobFromText(text: string, opts: JobOptions = {}): Promise<Job> {
  const res = await fetch(`${API_BASE}/jobs`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ text, ...opts })
  })
  if (!res.ok) {
    let detail = `HTTP ${res.status}`
    try { const b = await res.json(); if (b?.detail) detail = b.detail } catch { void detail }
    throw new Error(detail)
  }
  return (await res.json()) as Job
}

export async function createJobWithSources(sources: string[], textBody: string, opts: JobOptions = {}): Promise<Job> {
  const res = await fetch(`${API_BASE}/jobs`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ digest: true, digest_sources: sources, text: textBody, ...opts })
  })
  if (!res.ok) {
    let detail = `HTTP ${res.status}`
    try { const b = await res.json(); if (b?.detail) detail = b.detail } catch { void detail }
    throw new Error(detail)
  }
  return (await res.json()) as Job
}

export type SourceKind = 'article' | 'pdf' | 'image' | 'youtube' | 'note' | 'file-text'
export type SourceStatus = 'reading' | 'ready' | 'failed'
export type SourceRole = 'main' | 'context'

export interface SourceError {
  code: string
  hint: string
  retryable: boolean
}

export interface SourceItem {
  id: string
  kind: SourceKind
  origin_url?: string | null
  title: string
  words: number
  chars: number
  language?: string | null
  status: SourceStatus
  preview?: string
  error?: SourceError | null
  role?: SourceRole
  created_at: number
  updated_at: number
}

export interface CreateJobSourceRef {
  id: string
  role?: SourceRole
}

export async function addSource(payload: { url?: string; text?: string }): Promise<SourceItem> {
  const res = await fetch(`${API_BASE}/sources`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(payload)
  })
  if (!res.ok) {
    let detail = `HTTP ${res.status}`
    try {
      const b = await res.json()
      if (b?.detail) {
        detail = typeof b.detail === 'object' && b.detail?.hint ? b.detail.hint : (typeof b.detail === 'string' ? b.detail : JSON.stringify(b.detail))
      }
    } catch { void detail }
    throw new Error(detail)
  }
  return (await res.json()) as SourceItem
}

export async function uploadSource(data: Blob | ArrayBuffer, contentType?: string): Promise<SourceItem> {
  const headers: Record<string, string> = {}
  if (contentType) headers['Content-Type'] = contentType
  const res = await fetch(`${API_BASE}/sources/upload`, {
    method: 'POST',
    headers,
    body: data
  })
  if (!res.ok) {
    let detail = `HTTP ${res.status}`
    try {
      const b = await res.json()
      if (b?.detail) {
        detail = typeof b.detail === 'object' && b.detail?.hint ? b.detail.hint : (typeof b.detail === 'string' ? b.detail : JSON.stringify(b.detail))
      }
    } catch { void detail }
    throw new Error(detail)
  }
  return (await res.json()) as SourceItem
}

export async function getSource(sourceId: string): Promise<SourceItem> {
  return await get<SourceItem>(`/sources/${sourceId}`)
}

export async function updateSourceTitle(sourceId: string, title: string): Promise<SourceItem> {
  const res = await fetch(`${API_BASE}/sources/${sourceId}`, {
    method: 'PATCH',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ title })
  })
  if (!res.ok) throw new Error(`HTTP ${res.status}`)
  return (await res.json()) as SourceItem
}

export async function retrySource(sourceId: string): Promise<SourceItem> {
  const res = await fetch(`${API_BASE}/sources/${sourceId}/retry`, {
    method: 'POST'
  })
  if (!res.ok) throw new Error(`HTTP ${res.status}`)
  return (await res.json()) as SourceItem
}

export async function deleteSource(sourceId: string): Promise<{ deleted: string }> {
  const res = await fetch(`${API_BASE}/sources/${sourceId}`, {
    method: 'DELETE'
  })
  if (!res.ok) throw new Error(`HTTP ${res.status}`)
  return (await res.json()) as { deleted: string }
}

export async function listJobSources(jobId: string): Promise<SourceItem[]> {
  return await get<SourceItem[]>(`/jobs/${jobId}/sources`)
}

export async function cloneJobSources(jobId: string): Promise<SourceItem[]> {
  const res = await fetch(`${API_BASE}/jobs/${jobId}/sources/clone`, {
    method: 'POST'
  })
  if (!res.ok) throw new Error(`HTTP ${res.status}`)
  return (await res.json()) as SourceItem[]
}

export async function createJobWithTray(
  sources: CreateJobSourceRef[],
  opts: JobOptions & { allow_cloud_for_uploads?: boolean } = {}
): Promise<Job> {
  const res = await fetch(`${API_BASE}/jobs`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ sources, ...opts })
  })
  if (!res.ok) {
    let detail = `HTTP ${res.status}`
    try {
      const b = await res.json()
      if (b?.detail) detail = typeof b.detail === 'string' ? b.detail : JSON.stringify(b.detail)
    } catch { void detail }
    throw new Error(detail)
  }
  return (await res.json()) as Job
}

export interface Meta {
  styles: string[]
  style_docs?: Record<string, string>
  style_meta?: StyleMeta[]
  timbres: { id: string; label: string; native?: string; sample_url?: string | null }[]
  speaker_tables?: Record<string, { id: string; label: string; native?: string; sample_url?: string | null }[]>
  default_timbre_for?: Record<string, { a: string; b: string; c: string; solo: string }>
  emotions: { id: string; help: string }[]
  languages: Record<string, string>
  tones: string[]
  version?: string
  git_rev?: string
  max_source_chars?: number
  max_sources?: number
  limits?: { max_source_chars: number; max_sources: number; max_parallel_jobs: number; setting_ranges: Record<string, number[]> }
  runtime?: { tts_engine: string; llm: string; llm_engine?: string }
  billing_enabled?: boolean
  write_auth?: boolean
  v4v?: { node_address: string; node_locked: boolean }
  source_budget_chars?: number
  script_engine_local?: boolean
}

export async function fetchMeta(): Promise<Meta> {
  return get<Meta>('/meta')
}

export async function getSettings(): Promise<{
  settings: Record<string, string>
  defaults: Record<string, string>
  node_v4v_locked?: boolean
  node_v4v_address?: string
}> {
  return get('/settings')
}

export async function saveSetting(key: string, value: string): Promise<void> {
  await fetch(`${API_BASE}/settings/${key}`, {
    method: 'PUT',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ value })
  })
}

export interface JobSummary {
  id: string
  title: string
  url: string
  state: JobState
  created_at?: number
  duration_ms?: number | null
  /** length of the finished audio; duration_ms is the render time */
  audio_seconds?: number | null
  style?: string
  format?: string
  language?: string
  description?: string
  watchlist_id?: string | null
  digest?: boolean
  digest_sources?: string[] | null
  error?: string
  voice_profile?: VoiceProfile | null
  og_image?: string | null
  show_name?: string | null
  show_author?: string | null
  show_category?: string | null
}

export async function listJobs(limit = 5): Promise<JobSummary[]> {
  const data = await get<{ jobs: JobSummary[] }>(`/jobs?limit=${limit}`)
  return data.jobs
}

const RECENT_KEY = 'vozonda.recent'

export function readLocalRecent(): JobSummary[] {
  try {
    return JSON.parse(localStorage.getItem(RECENT_KEY) ?? '') as JobSummary[]
  } catch {
    return []
  }
}

export function pushLocalRecent(entry: JobSummary): void {
  const list = [entry, ...readLocalRecent().filter((r) => r.url !== entry.url)].slice(0, 5)
  localStorage.setItem(RECENT_KEY, JSON.stringify(list))
}

export async function getJob(id: string): Promise<Job> {
  return get<Job>(`/jobs/${id}`)
}

/** Approve a script paused for review; pass lines to replace it with an edit. */
export async function approveScript(id: string, lines?: { speaker: string; text: string }[], title?: string): Promise<Job> {
  const body: { lines?: { speaker: string; text: string }[]; title?: string } = {}
  if (lines) body.lines = lines
  if (title) body.title = title
  const res = await fetch(`${API_BASE}/jobs/${id}/script`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(body)
  })
  if (!res.ok) {
    let detail = `HTTP ${res.status}`
    try { const b = await res.json(); if (b?.detail) detail = b.detail } catch { void detail }
    throw new Error(detail)
  }
  return (await res.json()) as Job
}

export async function renameJob(id: string, title: string): Promise<Job> {
  const res = await fetch(`${API_BASE}/jobs/${id}`, {
    method: 'PATCH',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ title })
  })
  if (!res.ok) {
    let detail = `HTTP ${res.status}`
    try {
      const b = (await res.json()) as { detail?: string }
      if (b?.detail) detail = b.detail
    } catch {
      void detail
    }
    throw new Error(detail)
  }
  return (await res.json()) as Job
}

export async function cancelJob(id: string): Promise<Job> {
  const res = await fetch(`${API_BASE}/jobs/${id}`, { method: 'DELETE' })
  if (!res.ok) throw new Error(`HTTP ${res.status}`)
  return (await res.json()) as Job
}

export async function deleteJob(id: string): Promise<void> {
  const res = await fetch(`${API_BASE}/jobs/${id}`, { method: 'DELETE' })
  if (!res.ok && res.status !== 404) throw new Error(`HTTP ${res.status}`)
}

export function jobEvents(
  id: string,
  onJob: (job: Job) => void,
  onError?: (reason: string) => void
): () => void {
  const es = new EventSource(`${API_BASE}/jobs/${id}/events`)
  es.onmessage = (ev) => {
    if (!ev.data || typeof ev.data !== 'string') return
    try {
      const parsedRaw = JSON.parse(ev.data) as unknown
      if (!parsedRaw || typeof parsedRaw !== 'object') {
        onError?.('invalid data')
        return
      }
      // Normalize common payload shapes from the SSE stream.
      const parsed = { ...(parsedRaw as Record<string, unknown>) } as Record<string, unknown>

      // Coerce estimated_wait_seconds → estimated_wait_ms when present.
      if (parsed['estimated_wait_ms'] == null && parsed['estimated_wait_seconds'] != null) {
        const s = Number(parsed['estimated_wait_seconds'])
        if (!Number.isNaN(s)) parsed['estimated_wait_ms'] = Math.round(s * 1000)
      }

      // Validate queue_position if present; allow null but ensure numeric type.
      if (parsed['queue_position'] != null && Number.isNaN(Number(parsed['queue_position']))) {
        // malformed position, surface an error but keep stream open
        onError?.('invalid queue position')
      }

      // Ensure the minimal Job shape is present (state is required)
      if (!('state' in parsed)) {
        onError?.('invalid data')
        return
      }

      onJob(parsed as unknown as Job)
    } catch (err) {
      // provide more detail when parse fails
      onError?.('invalid data')
    }
  }
  es.onerror = () => {
    // EventSource auto-reconnects; notify UI so it can show retry state
    // Do not close here - let browser retry, but surface the condition
    if (es.readyState === EventSource.CLOSED) {
      onError?.('connection closed')
    } else {
      onError?.('connection lost')
    }
    // Log the error for debugging
    console.error('SSE connection error')
  }
  return () => es.close()
}

export function formatWaitMs(ms: number | null | undefined): string {
  if (ms == null || ms <= 0) return 'moments'
  const s = Math.round(ms / 1000)
  if (s < 45) return `${s}s`
  const m = Math.round(s / 60)
  if (m < 60) return `${m} min`
  const h = Math.floor(m / 60)
  const rem = m % 60
  return rem ? `${h}h ${rem}min` : `${h}h`
}


export interface WatchlistEntry {
  id: string
  feed_url: string
  style: string
  format: string
  language: string
  hosts: number
  created_at: number
  last_checked?: number | null
  last_error?: string | null
  enabled: boolean
  explicit?: boolean | number | null
  voice_profile?: VoiceProfile | null
  digest_mode?: number
  digest_count?: number
  show_slug?: string | null
}

export async function listWatchlists(): Promise<WatchlistEntry[]> {
  const data = await get<{ watchlist: WatchlistEntry[] }>('/watchlist')
  return data.watchlist
}

export async function addWatchlist(entry: {
  feed_url: string
  style?: string
  format?: 'dialog' | 'narration'
  language?: string
  hosts?: number
  explicit?: boolean
  show_slug?: string
}): Promise<WatchlistEntry> {
  const res = await fetch(`${API_BASE}/watchlist`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(entry)
  })
  if (!res.ok) {
    let detail = `HTTP ${res.status}`
    try {
      const body = await res.json()
      if (body?.detail) detail = body.detail
    } catch {
      try { detail = await res.text() } catch { void detail }
    }
    throw new Error(detail)
  }
  return (await res.json()) as WatchlistEntry
}

export async function setWatchlistEnabled(id: string, enabled: boolean, voice?: VoiceProfile): Promise<WatchlistEntry> {
  const res = await fetch(`${API_BASE}/watchlist/${id}`, {
    method: 'PUT',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ enabled, ...(voice !== undefined ? { voice } : {}) })
  })
  if (!res.ok) {
    let detail = `HTTP ${res.status}`
    try {
      const body = await res.json()
      if (body?.detail) detail = body.detail
    } catch {
      try { detail = await res.text() } catch { void detail }
    }
    throw new Error(detail)
  }
  return (await res.json()) as WatchlistEntry
}

export async function setWatchlistDigest(id: string, digestMode: boolean, digestCount: number): Promise<WatchlistEntry> {
  const res = await fetch(`${API_BASE}/watchlist/${id}`, {
    method: 'PUT',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ enabled: true, digest_mode: digestMode ? 1 : 0, digest_count: digestCount })
  })
  if (!res.ok) {
    let detail = `HTTP ${res.status}`
    try {
      const body = await res.json()
      if (body?.detail) detail = body.detail
    } catch {
      try { detail = await res.text() } catch { void detail }
    }
    throw new Error(detail)
  }
  return (await res.json()) as WatchlistEntry
}

export async function updateWatchlist(
  id: string,
  patch: Partial<{ style: string; format: 'dialog' | 'narration'; language: string; hosts: number; explicit: boolean; show_slug: string }>
): Promise<WatchlistEntry> {
  const res = await fetch(`${API_BASE}/watchlist/${id}`, {
    method: 'PUT',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(patch)
  })
  if (!res.ok) {
    let detail = `HTTP ${res.status}`
    try {
      const body = await res.json()
      if (body?.detail) detail = body.detail
    } catch {
      try { detail = await res.text() } catch { void detail }
    }
    throw new Error(detail)
  }
  return (await res.json()) as WatchlistEntry
}

export async function renderWatchlistDigest(id: string): Promise<{ digest_job: string; sources: string[] }> {
  const res = await fetch(`${API_BASE}/watchlist/${id}/digest`, { method: 'POST' })
  if (!res.ok) {
    let detail = `HTTP ${res.status}`
    try {
      const body = await res.json()
      if (body?.detail) detail = body.detail
    } catch {
      try { detail = await res.text() } catch { void detail }
    }
    throw new Error(detail)
  }
  return (await res.json()) as { digest_job: string; sources: string[] }
}

export async function removeWatchlist(id: string): Promise<void> {
  const res = await fetch(`${API_BASE}/watchlist/${id}`, { method: 'DELETE' })
  if (!res.ok) throw new Error(`HTTP ${res.status}`)
}

export async function checkWatchlist(id: string): Promise<{ created: string[] }> {
  const res = await fetch(`${API_BASE}/watchlist/${id}/check`, { method: 'POST' })
  if (!res.ok) throw new Error(`HTTP ${res.status}`)
  return (await res.json()) as { created: string[] }
}

export interface DoctorCheck {
  id: string
  ok: boolean
  hint: string
  optional?: boolean
}

export interface DoctorResult {
  ok: boolean
  checks: DoctorCheck[]
}

export async function fetchDoctor(): Promise<DoctorResult> {
  return get<DoctorResult>('/doctor')
}

export interface StorageStats {
  total_bytes: number
  file_count: number
  audio_files: number
  retention_days: number
  prunable_files: number
  prunable_bytes: number
}

export interface PurgeResult {
  purged_count: number
  freed_bytes: number
  days: number
  remaining_bytes: number
}

export async function getStorageStats(): Promise<StorageStats> {
  return get<StorageStats>('/storage')
}

export async function purgeStorage(days: number = 360): Promise<PurgeResult> {
  const res = await fetch(`${API_BASE}/storage/purge`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ days })
  })
  if (!res.ok) throw new Error(`HTTP ${res.status}`)
  return (await res.json()) as PurgeResult
}

export interface ClipCreateRequest {
  job_id: string
  turn_start: number
  turn_end: number
}

export interface ClipMetadata {
  job_id: string
  turn_start: number
  turn_end: number
  filename: string
  url: string
  start_seconds: number
  end_seconds: number
  duration_seconds: number
  slug?: string
  quote_snippet?: string
  speaker?: string
  label?: string
  title?: string
  description?: string
  share_url?: string
}

export interface ClipListItem {
  filename: string
  turn_start: number
  turn_end: number
  duration_seconds: number
  url: string
  share_url: string
  slug?: string
  quote_snippet?: string
  speaker?: string
  label?: string
  title?: string
  description?: string
}

export async function createClip(body: ClipCreateRequest): Promise<ClipMetadata> {
  const res = await fetch(`${API_BASE}/clips`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(body)
  })
  if (!res.ok) {
    let detail = `HTTP ${res.status}`
    try { const b = await res.json(); if (b?.detail) detail = b.detail } catch { void detail }
    throw new Error(detail)
  }
  return (await res.json()) as ClipMetadata
}

export async function listClips(jobId: string): Promise<ClipListItem[]> {
  const res = await fetch(`${API_BASE}/jobs/${jobId}/clips`)
  if (!res.ok) {
    if (res.status === 404) return []
    throw new Error(`HTTP ${res.status}`)
  }
  return (await res.json()) as ClipListItem[]
}

export async function deleteClip(jobId: string, filename: string): Promise<void> {
  const res = await fetch(`${API_BASE}/jobs/${jobId}/clips/${encodeURIComponent(filename)}`, {
    method: 'DELETE',
  })
  if (!res.ok) {
    let detail = `HTTP ${res.status}`
    try { const b = await res.json(); if (b?.detail) detail = b.detail } catch { void detail }
    throw new Error(detail)
  }
}

export const LANG_NAMES: Record<string, string> = {
  en: 'english',
  de: 'german',
  es: 'spanish',
  fr: 'french',
  it: 'italian',
  pt: 'portuguese',
  ru: 'russian',
  zh: 'chinese',
  ja: 'japanese',
  ko: 'korean',
  auto: ''
}

export interface ShowItem {
  slug: string
  name: string
  author?: string
  category?: string
}

export async function fetchShows(): Promise<ShowItem[]> {
  try {
    const data = await get<{ shows: ShowItem[] }>('/shows')
    return data.shows || []
  } catch {
    return []
  }
}

export interface PluginItem {
  id: string
  kind: string
  label: string
  version: string
  enabled: boolean
  healthy: boolean
  ui_badge: string
  ui_fix_hint: string
  permissions: string[]
  supports_instructions: boolean
  supports_emotion_instructions: boolean
  supports_paralinguistic_tags: boolean
}

export async function fetchPlugins(): Promise<PluginItem[]> {
  const data = await get<{ plugins: PluginItem[] }>('/plugins')
  return data.plugins ?? []
}

export async function togglePlugin(id: string): Promise<{ id: string; enabled: boolean }> {
  const res = await fetch(`${API_BASE}/plugins/${encodeURIComponent(id)}/toggle`, { method: 'POST' })
  if (!res.ok) {
    let detail = `HTTP ${res.status}`
    try { const b = await res.json() as { detail?: string }; if (b?.detail) detail = b.detail } catch { void detail }
    throw new Error(detail)
  }
  return (await res.json()) as { id: string; enabled: boolean }
}

export interface MusicTrackInfo {
  active: boolean
  mode: 'procedural' | 'custom'
  label: string
  filename?: string
  duration?: number
  size_bytes?: number
  url?: string
}

export interface MusicStatus {
  intro: MusicTrackInfo
  outro: MusicTrackInfo
  procedural_palette: string
}

export async function getMusicStatus(): Promise<MusicStatus> {
  return get<MusicStatus>('/music/status')
}

export async function importMusicUrl(url: string, kind: 'intro' | 'outro' = 'intro'): Promise<{ ok: boolean; kind: string; duration: number; url: string }> {
  const res = await fetch(`${API_BASE}/music/import-url`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ url, kind })
  })
  if (!res.ok) {
    let detail = `HTTP ${res.status}`
    try { const b = await res.json() as { detail?: string }; if (b?.detail) detail = b.detail } catch { void detail }
    throw new Error(detail)
  }
  return (await res.json()) as { ok: boolean; kind: string; duration: number; url: string }
}

export async function resetMusic(kind: 'intro' | 'outro' | 'all' = 'all'): Promise<{ ok: boolean; removed: string[]; status: MusicStatus }> {
  const res = await fetch(`${API_BASE}/music/reset`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ kind })
  })
  if (!res.ok) {
    let detail = `HTTP ${res.status}`
    try { const b = await res.json() as { detail?: string }; if (b?.detail) detail = b.detail } catch { void detail }
    throw new Error(detail)
  }
  return (await res.json()) as { ok: boolean; removed: string[]; status: MusicStatus }
}

/** URL of an episode cover: the API stores a file name served under /img/ (or a full URL). */
export function coverUrl(ogImage: string | null | undefined): string | null {
  if (!ogImage) return null
  return /^https?:\/\//i.test(ogImage) || ogImage.startsWith('/') ? ogImage : `/img/${ogImage}`
}

// ---------------------------------------------------------------------------
// Distribution endpoints (VOZONDA-DISTRIBUTION)
// ---------------------------------------------------------------------------

export interface DistributionMeta {
  defaults: { rss_default: string; nostr_publish_default: string }
  public_url: string | null
  reachable: boolean | null
  shows: { slug: string; name: string; author?: string; category?: string; rss: string; nostr: string; feed_url: string | null; fixed?: boolean }[]
  directory_help: { apple_podcasts_connect: string; spotify_for_creators: string; podcast_index: string }
}

export async function getDistribution(): Promise<DistributionMeta> {
  return await get<DistributionMeta>('/distribution')
}

export interface ShowRssResult {
  slug: string
  rss: string
  feed_url: string | null
}

export async function setShowRss(slug: string, enabled: boolean): Promise<ShowRssResult> {
  const res = await fetch(`${API_BASE}/shows/${encodeURIComponent(slug)}/rss`, {
    method: 'PUT',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ enabled })
  })
  if (!res.ok) {
    const b = await res.json().catch(() => ({})) as { detail?: string }
    throw new Error(b.detail ?? `HTTP ${res.status}`)
  }
  return (await res.json()) as ShowRssResult
}

export async function updateShow(slug: string, show: { name: string; author: string; category: string }): Promise<ShowItem> {
  const res = await fetch(`${API_BASE}/shows/${encodeURIComponent(slug)}`, {
    method: 'PUT',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(show)
  })
  if (!res.ok) {
    const b = await res.json().catch(() => ({})) as { detail?: string }
    throw new Error(b.detail ?? `HTTP ${res.status}`)
  }
  return (await res.json()) as ShowItem
}

export async function createShow(show: { name: string; author?: string; category?: string }): Promise<ShowItem> {
  const res = await fetch(`${API_BASE}/shows`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(show)
  })
  if (!res.ok) {
    const b = await res.json().catch(() => ({})) as { detail?: string }
    throw new Error(b.detail ?? `HTTP ${res.status}`)
  }
  return (await res.json()) as ShowItem
}

export async function deleteShow(slug: string): Promise<void> {
  const res = await fetch(`${API_BASE}/shows/${encodeURIComponent(slug)}`, {
    method: 'DELETE'
  })
  if (!res.ok) {
    const b = await res.json().catch(() => ({})) as { detail?: string }
    throw new Error(b.detail ?? `HTTP ${res.status}`)
  }
}

// ---------------------------------------------------------------------------
// Nostr publishing per-show (VOZONDA-NOSTR-3)
// ---------------------------------------------------------------------------

export interface NostrShowStatus {
  enabled: boolean
  npub: string | null
  last_event_id: string | null
}

export async function getNostrShowStatus(slug: string): Promise<NostrShowStatus> {
  return await get<NostrShowStatus>(`/shows/${encodeURIComponent(slug)}/nostr`)
}

export async function setNostrPublish(slug: string, enabled: boolean, confirm_public?: boolean): Promise<{ enabled: boolean; slug: string }> {
  const res = await fetch(`${API_BASE}/shows/${encodeURIComponent(slug)}/nostr`, {
    method: 'PUT',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ enabled, confirm_public: confirm_public ?? false })
  })
  if (!res.ok) {
    const b = await res.json().catch(() => ({})) as { detail?: string }
    throw new Error(b.detail ?? `HTTP ${res.status}`)
  }
  return (await res.json()) as { enabled: boolean; slug: string }
}

export async function exportNostrNsec(slug: string): Promise<{ slug: string; nsec: string }> {
  const res = await fetch(`${API_BASE}/shows/${encodeURIComponent(slug)}/nostr/export-nsec`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' }
  })
  if (!res.ok) {
    const b = await res.json().catch(() => ({})) as { detail?: string }
    throw new Error(b.detail ?? `HTTP ${res.status}`)
  }
  return (await res.json()) as { slug: string; nsec: string }
}

export interface NostrJobStatus {
  events: Array<{ kind: number; event_id: string; relays_ok: number; relays_total: number }>
}

// ---------------------------------------------------------------------------
// Custom user styles (VOZONDA-CUSTOM-STYLES-UI)
// ---------------------------------------------------------------------------

export interface CustomStyle {
  id: string
  name: string
  doc: string
  role_a: string
  role_b: string
  tone: string
  rhythm_type: string
  created_at?: number
}

export interface CustomStylePayload {
  id?: string
  name: string
  doc: string
  role_a: string
  role_b: string
  tone: string
  rhythm_type: string
}

function throwApiError(res: Response, fallback: string): Promise<never> {
  return res.json().then(
    (b) => {
      const raw = (b as { detail?: unknown })?.detail
      const detail = typeof raw === 'string' ? raw : Array.isArray(raw) ? raw.map((d) => typeof d === 'string' ? d : (d as { msg?: string })?.msg ?? '').filter(Boolean).join('; ') : ''
      throw new Error(detail || fallback)
    },
    () => { throw new Error(fallback) }
  )
}

export async function listCustomStyles(): Promise<CustomStyle[]> {
  const data = await get<{ styles: CustomStyle[] }>('/styles/custom')
  return data.styles ?? []
}

export async function createCustomStyle(payload: CustomStylePayload): Promise<CustomStyle> {
  const res = await fetch(`${API_BASE}/styles/custom`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(payload)
  })
  if (!res.ok) await throwApiError(res, `HTTP ${res.status}`)
  return (await res.json()) as CustomStyle
}

export async function updateCustomStyle(styleId: string, payload: Partial<CustomStylePayload>): Promise<CustomStyle> {
  const res = await fetch(`${API_BASE}/styles/custom/${encodeURIComponent(styleId)}`, {
    method: 'PUT',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(payload)
  })
  if (!res.ok) await throwApiError(res, `HTTP ${res.status}`)
  return (await res.json()) as CustomStyle
}

export async function deleteCustomStyle(styleId: string): Promise<void> {
  const res = await fetch(`${API_BASE}/styles/custom/${encodeURIComponent(styleId)}`, {
    method: 'DELETE'
  })
  if (!res.ok) await throwApiError(res, `HTTP ${res.status}`)
}

export async function getNostrJobStatus(jobId: string): Promise<NostrJobStatus> {
  return await get<NostrJobStatus>(`/jobs/${encodeURIComponent(jobId)}/nostr`)
}

export async function retryNostrPublish(jobId: string): Promise<{ job_id: string; retried: boolean }> {
  const res = await fetch(`${API_BASE}/jobs/${encodeURIComponent(jobId)}/nostr/publish`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' }
  })
  if (!res.ok) {
    const b = await res.json().catch(() => ({})) as { detail?: string }
    throw new Error(b.detail ?? `HTTP ${res.status}`)
  }
  return (await res.json()) as { job_id: string; retried: boolean }
}

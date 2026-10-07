<script lang="ts">
  import Icon from './Icon.svelte'
  import SourceInput from './SourceInput.svelte'
  import {
    addSource,
    uploadSource,
    getSource,
    updateSourceTitle,
    retrySource,
    deleteSource,
    type SourceItem,
    type SourceRole
  } from '../api'

  let {
    sources = $bindable([]),
    maxSources = 10,
    maxSourceChars = 60000,
    scriptEngineLocal = true,
    scriptEngineProvider = '',
    allowCloudForUploads = $bindable(false),
    busy = false,
    goFlash = false,
    onSubmit,
    inputEl = $bindable(null)
  }: {
    sources?: SourceItem[]
    maxSources?: number
    maxSourceChars?: number
    scriptEngineLocal?: boolean
    scriptEngineProvider?: string
    allowCloudForUploads?: boolean
    busy?: boolean
    goFlash?: boolean
    onSubmit: (refs: { id: string; role: SourceRole }[]) => Promise<void>
    inputEl?: HTMLTextAreaElement | null
  } = $props()

  const STORAGE_KEY = 'vozonda_tray_sources'

  let editingId = $state<string | null>(null)
  let editTitleDraft = $state('')
  let confirmBypassFailures = $state(false)
  let sourceInputComp = $state<SourceInput | null>(null)

  // Load persisted tray on mount
  $effect(() => {
    try {
      const stored = localStorage.getItem(STORAGE_KEY)
      if (stored && sources.length === 0) {
        const parsed = JSON.parse(stored) as { id: string; role?: SourceRole }[]
        if (Array.isArray(parsed) && parsed.length > 0) {
          void restoreSavedTray(parsed)
        }
      }
    } catch {
      // ignore JSON error
    }
  })

  async function restoreSavedTray(saved: { id: string; role?: SourceRole }[]) {
    const loaded: SourceItem[] = []
    for (const ref of saved) {
      try {
        const s = await getSource(ref.id)
        if (s) {
          loaded.push({ ...s, role: ref.role || 'main' })
        }
      } catch {
        // Source expired (24h) or not found, silently drop
      }
    }
    if (loaded.length > 0) {
      sources = loaded
      syncStorage()
    }
  }

  function syncStorage() {
    try {
      const data = sources.map((s) => ({ id: s.id, role: s.role || 'main' }))
      localStorage.setItem(STORAGE_KEY, JSON.stringify(data))
    } catch {
      // quota or local storage disabled
    }
  }

  // Active polling for sources in 'reading' status
  $effect(() => {
    const reading = sources.filter((s) => s.status === 'reading')
    if (reading.length === 0) return

    const interval = setInterval(async () => {
      let changed = false
      const updated = await Promise.all(
        sources.map(async (s) => {
          if (s.status === 'reading') {
            try {
              const fresh = await getSource(s.id)
              if (fresh.status !== 'reading') {
                changed = true
                return { ...fresh, role: s.role || 'main' }
              }
            } catch {
              // ignore poll errors
            }
          }
          return s
        })
      )
      if (changed) {
        sources = updated
        syncStorage()
      }
    }, 1000)

    return () => clearInterval(interval)
  })

  // Derived state
  const totalChars = $derived(sources.reduce((sum, s) => sum + (s.chars || 0), 0))
  const failedSources = $derived(sources.filter((s) => s.status === 'failed'))
  const readingSources = $derived(sources.filter((s) => s.status === 'reading'))
  const readySources = $derived(sources.filter((s) => s.status === 'ready'))
  const readyMainSources = $derived(readySources.filter((s) => s.role !== 'context'))

  // A job can start if there's at least one ready main source and no reading sources.
  // Per decision 9: starting is allowed with failed sources (first press prompts inline confirmation).
  const canSubmit = $derived(readingSources.length === 0 && readyMainSources.length > 0)

  const hasUploads = $derived(
    sources.some((s) => (s.kind === 'file-text' || s.kind === 'pdf' || s.kind === 'image') && !s.origin_url)
  )

  const showPrivacyNotice = $derived(hasUploads && !scriptEngineLocal)

  function formatNumber(num: number): string {
    if (num >= 1_000_000) return `${(num / 1_000_000).toFixed(1)}M`
    if (num >= 1000) return `${Math.round(num / 1000)}k`
    return `${num}`
  }

  // Source Add handlers
  async function handleAddUrl(url: string) {
    if (sources.length >= maxSources) return
    const src = await addSource({ url })
    sources = [...sources, { ...src, role: 'main' }]
    confirmBypassFailures = false
    syncStorage()
  }

  async function handleAddNote(text: string) {
    if (sources.length >= maxSources) return
    const src = await addSource({ text })
    sources = [...sources, { ...src, role: 'main' }]
    confirmBypassFailures = false
    syncStorage()
  }

  async function handleUploadFile(file: File) {
    if (sources.length >= maxSources) return
    const buf = await file.arrayBuffer()
    const src = await uploadSource(buf, file.type || undefined)
    sources = [...sources, { ...src, role: 'main' }]
    confirmBypassFailures = false
    syncStorage()
  }

  async function handleRemove(id: string) {
    sources = sources.filter((s) => s.id !== id)
    syncStorage()
    void deleteSource(id).catch(() => {})
    confirmBypassFailures = false
  }

  function handleToggleRole(source: SourceItem, newRole: SourceRole) {
    sources = sources.map((s) => (s.id === source.id ? { ...s, role: newRole } : s))
    syncStorage()
  }

  function startEditing(source: SourceItem) {
    editingId = source.id
    editTitleDraft = source.title
  }

  async function saveEditing(source: SourceItem) {
    if (editingId !== source.id) return
    const next = editTitleDraft.trim()
    editingId = null
    if (next && next !== source.title) {
      try {
        const updated = await updateSourceTitle(source.id, next)
        sources = sources.map((s) => (s.id === source.id ? { ...updated, role: s.role || 'main' } : s))
        syncStorage()
      } catch {
        // keep old title on error
      }
    }
  }

  async function handleRetry(source: SourceItem) {
    try {
      const retrying = await retrySource(source.id)
      sources = sources.map((s) => (s.id === source.id ? { ...retrying, role: s.role || 'main' } : s))
      syncStorage()
    } catch {
      // ignore
    }
  }

  async function triggerSubmit() {
    if (busy) return
    // Flush any remaining text in the input first
    if (sourceInputComp) {
      await sourceInputComp.flushRemaining()
    }
    // a link pasted and started at once is still being read: wait for it (max 2 min)
    for (let i = 0; i < 240 && sources.some((s) => s.status === 'reading'); i++) {
      await new Promise((r) => setTimeout(r, 500))
    }

    if (failedSources.length > 0 && !confirmBypassFailures) {
      // First click with failures: show inline confirmation
      confirmBypassFailures = true
      return
    }

    // Filter to ready sources only (dropping failures on confirmed launch)
    const targets = sources.filter((s) => s.status === 'ready')
    if (targets.length === 0 || !targets.some((s) => s.role !== 'context')) return

    await onSubmit(targets.map((s) => ({ id: s.id, role: s.role || 'main' })))
  }

  // Kind icon helper
  function kindIcon(kind: string): string {
    switch (kind) {
      case 'article':
        return 'link'
      case 'youtube':
        return 'play'
      case 'pdf':
      case 'note':
      case 'file-text':
        return 'file-text'
      case 'image':
        return 'highlighter'
      default:
        return 'source'
    }
  }
</script>

<div class="source-tray-wrap">
  <SourceInput
    bind:this={sourceInputComp}
    onAddUrl={handleAddUrl}
    onAddNote={handleAddNote}
    onUploadFile={handleUploadFile}
    onSubmitReady={() => void triggerSubmit()}
    canSubmit={canSubmit}
    {busy}
    flash={goFlash}
    disabled={busy || sources.length >= maxSources}
    bind:inputEl
  />

  {#if sources.length > 0}
    <ul class="source-tray-list" aria-label="sources">
      {#each sources as s (s.id)}
        <li
          class="source-card"
          class:card-failed={s.status === 'failed'}
          class:card-reading={s.status === 'reading'}
          class:card-context={s.role === 'context'}
        >
          <div class="card-header">
            <span class="kind-badge mono">
              <Icon name={kindIcon(s.kind)} size={12} />
              {s.kind}
            </span>

            <div class="card-tools">
              <!-- Role toggle (main / context) -->
              <div class="seg role-seg" role="radiogroup" aria-label="Source role">
                <button
                  type="button"
                  role="radio"
                  aria-checked={s.role !== 'context'}
                  class:sel={s.role !== 'context'}
                  disabled={s.status === 'failed' || busy}
                  onclick={() => handleToggleRole(s, 'main')}
                >
                  main
                </button>
                <button
                  type="button"
                  role="radio"
                  aria-checked={s.role === 'context'}
                  class:sel={s.role === 'context'}
                  disabled={s.status === 'failed' || busy}
                  onclick={() => handleToggleRole(s, 'context')}
                >
                  context
                </button>
              </div>

              <button
                type="button"
                class="remove-btn mono"
                onclick={() => void handleRemove(s.id)}
                aria-label={`remove source ${s.title || s.kind}`}
                disabled={busy}
              >
                ×
              </button>
            </div>
          </div>

          <div class="card-body">
            {#if editingId === s.id}
              <input
                type="text"
                class="mono title-edit-input"
                bind:value={editTitleDraft}
                onblur={() => void saveEditing(s)}
                onkeydown={(e) => {
                  if (e.key === 'Enter') void saveEditing(s)
                  if (e.key === 'Escape') editingId = null
                }}
                maxlength={200}
                aria-label="Edit source title"
              />
            {:else}
              <div class="title-row">
                <span
                  class="source-title mono"
                  title={s.title || s.origin_url || 'untitled source'}
                >
                  {s.title || s.origin_url || 'untitled source'}
                </span>
                {#if !s.origin_url && s.status === 'ready'}
                  <button
                    type="button"
                    class="edit-title-btn"
                    onclick={() => startEditing(s)}
                    aria-label="Rename source"
                    title="Rename source"
                  >
                    <Icon name="slice" size={10} />
                  </button>
                {/if}
              </div>
            {/if}

            {#if s.origin_url}
              <a
                href={s.origin_url}
                target="_blank"
                rel="noreferrer"
                class="mono origin-link"
                title={s.origin_url}
              >
                {s.origin_url}
              </a>
            {/if}

            {#if s.status === 'reading'}
              <div class="status-reading mono">
                <Icon name="pulse" size={12} />
                <span>reading source…</span>
              </div>
            {:else if s.status === 'failed'}
              <div class="status-failed mono">
                <span class="fail-hint">
                  <Icon name="warn" size={12} />
                  {s.error?.hint || 'could not read this source.'}
                </span>
                {#if s.error?.retryable && s.origin_url}
                  <button
                    type="button"
                    class="retry-btn mono"
                    onclick={() => void handleRetry(s)}
                    disabled={busy}
                    aria-label="Retry reading source"
                  >
                    <Icon name="refresh" size={12} />
                    <span>retry</span>
                  </button>
                {/if}
              </div>
            {:else}
              <div class="card-meta mono">
                {#if s.words}
                  <span>{formatNumber(s.words)} words</span>
                {/if}
                {#if s.chars}
                  <span class="sep">·</span>
                  <span>{formatNumber(s.chars)} chars</span>
                {/if}
                {#if s.language}
                  <span class="sep">·</span>
                  <span class="lang-tag">{s.language}</span>
                {/if}
              </div>
            {/if}
          </div>
        </li>
      {/each}
    </ul>
  {/if}

  <!-- Tray Footer & Launch Bar -->
  <div class="tray-footer">
    {#if sources.length > 0}
      <div class="tray-stats mono">
        <span>{sources.length} / {maxSources} sources</span>
        <span class="sep">·</span>
        <span>{formatNumber(totalChars)} of {formatNumber(maxSourceChars)} chars</span>
      </div>
    {/if}

    {#if showPrivacyNotice}
      <div class="privacy-notice mono">
        <Icon name="lock" size={12} />
        <span>uploaded files will be sent to {scriptEngineProvider || 'cloud'}</span>
        <label class="privacy-opt">
          <input
            type="checkbox"
            checked={!allowCloudForUploads}
            onchange={(e) => (allowCloudForUploads = !e.currentTarget.checked)}
          />
          <span>use local model for this episode</span>
        </label>
      </div>
    {/if}

    <!-- Inline confirmation bar when unreadable sources are in tray -->
    {#if failedSources.length > 0 && confirmBypassFailures}
      <div class="fail-confirm-bar mono" role="alert">
        <span class="fail-msg">
          <Icon name="warn" size={12} />
          {failedSources.length === 1 ? "1 source can't be read" : `${failedSources.length} sources can't be read`}
        </span>
        <div class="fail-actions">
          <button
            type="button"
            class="bypass-btn mono"
            onclick={() => void triggerSubmit()}
            disabled={busy || readyMainSources.length === 0}
          >
            make it talk without it
          </button>
          <button
            type="button"
            class="cancel-bypass-btn mono"
            onclick={() => (confirmBypassFailures = false)}
          >
            fix first
          </button>
        </div>
      </div>
    {/if}

  </div>
</div>

<style>
  .source-tray-wrap {
    min-width: 0;
    max-width: 100%;
    display: flex;
    flex-direction: column;
    gap: 12px;
  }

  .source-tray-list {
    list-style: none;
    margin: 0;
    padding: 0;
    display: flex;
    flex-direction: column;
    gap: 8px;
  }

  .source-card {
    min-width: 0;
    background: var(--paper);
    border: 1px solid var(--line);
    border-radius: var(--radius);
    padding: 8px 10px;
    display: flex;
    flex-direction: column;
    gap: 6px;
    transition: border-color 0.15s ease, background 0.15s ease;
  }

  .source-card.card-context {
    opacity: 0.85;
    background: color-mix(in srgb, color-mix(in srgb, var(--ink) 5%, var(--paper)) 40%, var(--paper));
  }

  .source-card.card-failed {
    border-color: color-mix(in srgb, var(--danger) 40%, var(--line));
    background: color-mix(in srgb, var(--danger) 5%, var(--paper));
  }

  .source-card.card-reading {
    border-color: color-mix(in srgb, var(--green, #22c55e) 40%, var(--line));
  }

  .card-header {
    display: flex;
    align-items: center;
    justify-content: space-between;
    gap: 8px;
  }

  .kind-badge {
    font-size: calc(var(--ui-size) * 0.85);
    color: var(--ink-soft);
    display: inline-flex;
    align-items: center;
    gap: 4px;
    text-transform: lowercase;
  }

  .card-tools {
    display: flex;
    align-items: center;
    gap: 8px;
  }

  .role-seg {
    display: inline-flex;
    border: 1px solid var(--line);
    border-radius: var(--radius);
    overflow: hidden;
  }

  .role-seg button {
    padding: 3px 10px;
    min-height: 24px;
    font-size: calc(var(--ui-size) * 0.78);
    font-family: var(--font-mono);
    background: var(--paper);
    color: var(--ink-soft);
    border: none;
    cursor: pointer;
    line-height: 1.3;
  }

  .role-seg button.sel {
    background: color-mix(in srgb, var(--green, #22c55e) 15%, var(--paper));
    color: var(--ink);
    font-weight: 500;
  }

  .role-seg button:not(.sel):hover:not(:disabled) {
    background: color-mix(in srgb, var(--ink) 5%, var(--paper));
  }

  .remove-btn {
    background: transparent;
    border: none;
    color: var(--ink-soft);
    font-size: 16px;
    line-height: 1;
    cursor: pointer;
    padding: 2px 4px;
    border-radius: var(--radius);
  }

  .remove-btn:hover:not(:disabled) {
    color: var(--ink);
    background: color-mix(in srgb, var(--ink) 5%, var(--paper));
  }

  .card-body {
    min-width: 0;
    display: flex;
    flex-direction: column;
    gap: 3px;
  }

  .title-row {
    min-width: 0;
    display: flex;
    align-items: center;
    gap: 6px;
  }

  .source-title {
    min-width: 0;
    font-size: var(--ui-size, 13px);
    color: var(--ink);
    font-weight: 500;
    overflow: hidden;
    text-overflow: ellipsis;
    white-space: nowrap;
  }


  .title-edit-input {
    font-size: var(--ui-size, 13px);
    padding: 3px 6px;
    background: var(--paper);
    color: var(--ink);
    border: 1px solid var(--ink-soft);
    border-radius: var(--radius);
    outline: none;
    width: 100%;
    box-sizing: border-box;
  }

  .edit-title-btn {
    background: transparent;
    border: none;
    color: var(--ink-soft);
    cursor: pointer;
    padding: 2px;
    opacity: 0.6;
    display: inline-flex;
    align-items: center;
  }

  .edit-title-btn:hover {
    opacity: 1;
    color: var(--ink);
  }

  .origin-link {
    font-size: calc(var(--ui-size) * 0.85);
    color: var(--ink-soft);
    text-decoration: none;
    overflow: hidden;
    text-overflow: ellipsis;
    white-space: nowrap;
    opacity: 0.85;
  }

  .origin-link:hover {
    text-decoration: underline;
    color: var(--ink);
  }

  .status-reading {
    font-size: calc(var(--ui-size) * 0.9);
    color: var(--green, #22c55e);
    display: inline-flex;
    align-items: center;
    gap: 5px;
    padding-top: 2px;
  }

  .status-failed {
    font-size: calc(var(--ui-size) * 0.9);
    color: var(--danger);
    display: flex;
    align-items: center;
    justify-content: space-between;
    gap: 8px;
    padding-top: 2px;
  }

  .fail-hint {
    display: inline-flex;
    align-items: center;
    gap: 5px;
  }

  .retry-btn {
    font-size: calc(var(--ui-size) * 0.85);
    background: var(--paper);
    border: 1px solid color-mix(in srgb, var(--danger) 40%, var(--line));
    color: var(--ink);
    border-radius: var(--radius);
    padding: 2px 8px;
    display: inline-flex;
    align-items: center;
    gap: 4px;
    cursor: pointer;
  }

  .retry-btn:hover:not(:disabled) {
    background: color-mix(in srgb, var(--danger) 10%, var(--paper));
  }

  .card-meta {
    font-size: calc(var(--ui-size) * 0.85);
    color: var(--ink-soft);
    display: flex;
    align-items: center;
    gap: 4px;
    padding-top: 2px;
  }

  .sep {
    opacity: 0.4;
  }

  .lang-tag {
    text-transform: uppercase;
  }

  .tray-footer {
    display: flex;
    flex-direction: column;
    gap: 8px;
    padding-top: 4px;
  }

  .tray-stats span {
    white-space: nowrap;
  }

  .tray-stats {
    font-size: calc(var(--ui-size) * 0.85);
    color: var(--ink-soft);
    display: flex;
    align-items: center;
    gap: 5px;
    flex-wrap: wrap;
  }

  .privacy-notice {
    font-size: calc(var(--ui-size) * 0.85);
    padding: 6px 10px;
    background: color-mix(in srgb, var(--yellow, #eab308) 8%, var(--paper));
    border: 1px solid color-mix(in srgb, var(--yellow, #eab308) 25%, var(--line));
    border-radius: var(--radius);
    color: var(--ink);
    display: flex;
    flex-direction: column;
    gap: 4px;
  }

  .privacy-opt {
    display: inline-flex;
    align-items: center;
    gap: 6px;
    cursor: pointer;
  }

  .fail-confirm-bar {
    display: flex;
    align-items: center;
    justify-content: space-between;
    gap: 8px;
    padding: 6px 10px;
    background: color-mix(in srgb, var(--danger) 10%, var(--paper));
    border: 1px solid color-mix(in srgb, var(--danger) 30%, var(--line));
    border-radius: var(--radius);
    font-size: calc(var(--ui-size) * 0.9);
  }

  .fail-msg {
    color: var(--danger);
    display: inline-flex;
    align-items: center;
    gap: 5px;
  }

  .fail-actions {
    display: flex;
    align-items: center;
    gap: 6px;
  }

  .bypass-btn {
    background: color-mix(in srgb, var(--danger) 15%, var(--paper));
    border: 1px solid color-mix(in srgb, var(--danger) 40%, var(--line));
    color: var(--ink);
    padding: 3px 8px;
    border-radius: var(--radius);
    cursor: pointer;
    font-size: calc(var(--ui-size) * 0.85);
  }

  .bypass-btn:hover:not(:disabled) {
    background: color-mix(in srgb, var(--danger) 25%, var(--paper));
  }

  .cancel-bypass-btn {
    background: var(--paper);
    border: 1px solid var(--line);
    color: var(--ink-soft);
    padding: 3px 8px;
    border-radius: var(--radius);
    cursor: pointer;
    font-size: calc(var(--ui-size) * 0.85);
  }

  .cancel-bypass-btn:hover {
    color: var(--ink);
  }

</style>

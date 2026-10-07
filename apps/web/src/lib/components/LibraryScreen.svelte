<script lang="ts">
  import Icon from './Icon.svelte'
  import { getEpisodePlayCount, getEpisodeZappedSats } from '../zaps'
  import { getEpisodeHighlightCount } from '../highlights'
  import { coverUrl, deleteJob, type JobSummary } from '../api'

  let { episodes, onback, onResume }: { episodes: JobSummary[]; onback: () => void; onResume: (e: JobSummary) => void } =
    $props()

  function cleanTitle(raw?: string): string {
    if (!raw) return ''
    return raw
      .replace(/&#x27;/g, "'")
      .replace(/&#39;/g, "'")
      .replace(/&quot;/g, '"')
      .replace(/&amp;/g, '&')
      .replace(/&lt;/g, '<')
      .replace(/&gt;/g, '>')
  }

  function dateLabel(ts?: number, compact = false): string {
    if (!ts) return ''
    const d = new Date(ts * 1000)
    if (compact) {
      return d.toLocaleDateString('en-US', { month: 'short', day: 'numeric' })
    }
    return (
      d.toLocaleDateString('en-US', { month: 'short', day: 'numeric' }) +
      ', ' +
      d.toLocaleTimeString('en-US', { hour: '2-digit', minute: '2-digit', hour12: false })
    )
  }

  function durLabel(ms?: number | null): string {
    if (!ms) return ''
    // whole seconds, rounded like the player's total: the browser measures the MP3 a few
    // ms shorter than ffprobe (231.999 vs 232.032 s), so flooring gave 3:51 against 3:52
    const s = Math.round(ms / 1000)
    return `${Math.floor(s / 60)}:${(s % 60).toString().padStart(2, '0')} min`
  }

  let sortBy = $state<'newest' | 'longest' | 'shortest' | 'most_played' | 'most_highlighted' | 'most_zapped'>('newest')
  let typeFilter = $state<'all' | 'single' | 'digest' | 'feed'>('all')
  let langFilter = $state('all')
  let styleFilter = $state('all')
  let search = $state('')
  let debounced = $state('')

  let manageMode = $state(false)
  let selectedIds = $state(new Set<string>())
  let confirmAction = $state<'selected' | 'all' | null>(null)
  let deleting = $state(false)
  let deletedIds = $state(new Set<string>())

  let viewDensity = $state<'detailed' | 'compact'>(
    typeof localStorage !== 'undefined' && localStorage.getItem('vozonda_library_view') === 'compact'
      ? 'compact'
      : 'detailed'
  )

  function toggleViewDensity() {
    viewDensity = viewDensity === 'detailed' ? 'compact' : 'detailed'
    try {
      localStorage.setItem('vozonda_library_view', viewDensity)
    } catch {}
  }

  $effect(() => {
    const v = search
    const t = setTimeout(() => (debounced = v.trim().toLowerCase()), 200)
    return () => clearTimeout(t)
  })

  const done = $derived(episodes.filter((e) => e.state === 'done' && !deletedIds.has(e.id)))
  let clearing = $state(false)
  const failed = $derived(episodes.filter((e) => e.state !== 'done' && !deletedIds.has(e.id)))

  async function clearFailed() {
    if (clearing || failed.length === 0) return
    clearing = true
    for (const e of failed) {
      try {
        await fetch(`/jobs/${e.id}`, { method: 'DELETE' })
        deletedIds.add(e.id)
        deletedIds = new Set(deletedIds)
      } catch {
        void e
      }
    }
    clearing = false
  }

  function toggleSelect(id: string, e?: Event) {
    if (e) e.stopPropagation()
    const next = new Set(selectedIds)
    if (next.has(id)) next.delete(id)
    else next.add(id)
    selectedIds = next
  }

  function toggleSelectAll() {
    if (selectedIds.size === shown.length) {
      selectedIds = new Set()
    } else {
      selectedIds = new Set(shown.map((e) => e.id))
    }
  }

  async function deleteSelected() {
    if (deleting || selectedIds.size === 0) return
    deleting = true
    const targets = [...selectedIds]
    for (const id of targets) {
      try {
        await deleteJob(id)
        deletedIds.add(id)
      } catch {
        void id
      }
    }
    deletedIds = new Set(deletedIds)
    selectedIds = new Set()
    confirmAction = null
    deleting = false
  }

  async function deleteAll() {
    if (deleting || done.length === 0) return
    deleting = true
    const targets = done.map((e) => e.id)
    for (const id of targets) {
      try {
        await deleteJob(id)
        deletedIds.add(id)
      } catch {
        void id
      }
    }
    deletedIds = new Set(deletedIds)
    selectedIds = new Set()
    confirmAction = null
    deleting = false
    manageMode = false
  }

  async function deleteSingle(id: string, evt: Event) {
    evt.stopPropagation()
    try {
      await deleteJob(id)
      deletedIds.add(id)
      deletedIds = new Set(deletedIds)
      const next = new Set(selectedIds)
      next.delete(id)
      selectedIds = next
    } catch {
      void id
    }
  }

  const langs = $derived([...new Set(done.map((e) => e.language).filter(Boolean))])
  const styles = $derived([...new Set(done.map((e) => e.style).filter(Boolean))])

  // episode length = audio_seconds; duration_ms is how long the render took
  function durSec(e: JobSummary): number {
    const d = Number(e.audio_seconds)
    return isNaN(d) || d <= 0 ? 0 : d
  }

  function fmtCount(n: number, singular: string, plural: string): string {
    if (n === 1) return `1 ${singular}`
    if (n >= 1000) return `${(n / 1000).toFixed(1)}k ${plural}`
    return `${n} ${plural}`
  }

  const shown = $derived.by(() => {
    let list = [...done]
    if (typeFilter === 'digest') list = list.filter((e) => !!e.digest)
    else if (typeFilter === 'feed') list = list.filter((e) => !!e.watchlist_id)
    else if (typeFilter === 'single') list = list.filter((e) => !e.digest && !e.watchlist_id)

    if (langFilter !== 'all') list = list.filter((e) => e.language === langFilter)
    if (styleFilter !== 'all') list = list.filter((e) => e.style === styleFilter)
    if (debounced) {
      list = list.filter((e) => {
        const hay = `${e.title ?? ''} ${e.description ?? ''}`.toLowerCase()
        return hay.includes(debounced)
      })
    }
    if (sortBy === 'longest') {
      list.sort((a, b) => {
        const da = durSec(a) > 0 ? durSec(a) : -1
        const db = durSec(b) > 0 ? durSec(b) : -1
        if (db !== da) return db - da
        return (b.created_at ?? 0) - (a.created_at ?? 0)
      })
    } else if (sortBy === 'shortest') {
      list.sort((a, b) => {
        const da = durSec(a) > 0 ? durSec(a) : Number.MAX_SAFE_INTEGER
        const db = durSec(b) > 0 ? durSec(b) : Number.MAX_SAFE_INTEGER
        if (da !== db) return da - db
        return (b.created_at ?? 0) - (a.created_at ?? 0)
      })
    } else if (sortBy === 'most_played') {
      list.sort((a, b) => {
        const diff = getEpisodePlayCount(b.id) - getEpisodePlayCount(a.id)
        if (diff !== 0) return diff
        return (b.created_at ?? 0) - (a.created_at ?? 0)
      })
    } else if (sortBy === 'most_highlighted') {
      list.sort((a, b) => {
        const diff = getEpisodeHighlightCount(b.id) - getEpisodeHighlightCount(a.id)
        if (diff !== 0) return diff
        return (b.created_at ?? 0) - (a.created_at ?? 0)
      })
    } else if (sortBy === 'most_zapped') {
      list.sort((a, b) => {
        const diff = getEpisodeZappedSats(b.id) - getEpisodeZappedSats(a.id)
        if (diff !== 0) return diff
        return (b.created_at ?? 0) - (a.created_at ?? 0)
      })
    } else {
      list.sort((a, b) => (b.created_at ?? 0) - (a.created_at ?? 0))
    }
    return list
  })

  const totalPlays = $derived(
    done.reduce((acc, e) => acc + getEpisodePlayCount(e.id), 0)
  )
  const totalHighlights = $derived(
    done.reduce((acc, e) => acc + getEpisodeHighlightCount(e.id), 0)
  )
  const totalZaps = $derived(
    done.reduce((acc, e) => acc + getEpisodeZappedSats(e.id), 0)
  )
  const showNames = $derived([...new Set(done.map((e) => e.show_name).filter(Boolean))])
  const hasMultipleShows = $derived(showNames.length > 1)
</script>

<main>
  {#if done.length === 0}
    <p class="mono note" role="status" aria-live="polite">// nothing here yet. go make something.</p>
  {:else}
    <div class="library-summary mono" role="status">
      // library · {done.length} {done.length === 1 ? 'episode' : 'episodes'} · {fmtCount(totalPlays, 'play', 'plays')} · {fmtCount(totalHighlights, 'highlight', 'highlights')} · {totalZaps.toLocaleString()} sats zapped
    </div>

    <div class="library-toolbar mono" role="search" aria-label="Library search and filters">
      <div class="toolbar-row searchbar">
        <div class="search-wrap">
          <Icon name="search" size={14} />
          <input
            type="search"
            class="mono search-input"
            placeholder="search by title or topic..."
            aria-label="Search episodes"
            bind:value={search}
          />
          {#if search}
            <button type="button" class="clear-search-btn mono" onclick={() => (search = '')} aria-label="Clear search">×</button>
          {/if}
        </div>
        <div class="sort-wrap">
          <label class="sort-label">
            <span class="sort-caption">sort</span>
            <select bind:value={sortBy} aria-label="Sort episodes">
              <option value="newest">newest first</option>
              <option value="most_played">most played</option>
              <option value="most_highlighted">most highlighted</option>
              <option value="most_zapped">most zapped</option>
              <option value="longest">longest first</option>
              <option value="shortest">shortest first</option>
            </select>
          </label>
        </div>
      </div>

      <div class="toolbar-row filterbar" aria-label="Filter options">
        <div class="filter-group">
          <label>style
            <select bind:value={styleFilter} aria-label="Filter by style">
              <option value="all">all</option>
              {#each styles as s (s)}<option value={s}>{s}</option>{/each}
            </select>
          </label>
          <label>type
            <select bind:value={typeFilter} aria-label="Filter by type">
              <option value="all">all</option>
              <option value="single">single stories</option>
              <option value="digest">digest bundles</option>
              <option value="feed">auto from feeds</option>
            </select>
          </label>
          <label>language
            <select bind:value={langFilter} aria-label="Filter by language">
              <option value="all">all</option>
              {#each langs as l (l)}<option value={l}>{l}</option>{/each}
            </select>
          </label>
        </div>

        <div class="filter-meta">
          <span class="count">{shown.length} of {done.length}</span>
          <button
            type="button"
            class="chip view-chip"
            onclick={toggleViewDensity}
            title={`Switch to ${viewDensity === 'detailed' ? 'compact' : 'detailed'} view`}
            aria-label={`Toggle view density: currently ${viewDensity}`}
          >
            <Icon name={viewDensity === 'detailed' ? 'layers' : 'template'} size={12} />
            <span>{viewDensity}</span>
          </button>
          <button
            type="button"
            class="chip manage-chip"
            class:active={manageMode}
            onclick={() => { manageMode = !manageMode; selectedIds = new Set(); confirmAction = null }}
            aria-expanded={manageMode}
          >
            <Icon name={manageMode ? 'check' : 'sliders'} size={12} />
            <span>{manageMode ? 'done' : 'manage'}</span>
          </button>
        </div>
      </div>
    </div>

    {#if manageMode}
      <div class="manage-bar mono" role="toolbar" aria-label="Bulk actions">
        <div class="manage-left">
          <label class="select-all-label">
            <input
              type="checkbox"
              checked={shown.length > 0 && selectedIds.size === shown.length}
              onchange={toggleSelectAll}
              disabled={shown.length === 0 || deleting}
            />
            <span>select all ({shown.length})</span>
          </label>
          <span class="selected-count">{selectedIds.size} selected</span>
        </div>

        <div class="manage-actions">
          {#if confirmAction === 'selected'}
            <div class="confirm-prompt">
              <span>permanently delete {selectedIds.size} episodes?</span>
              <button class="confirm-btn danger" onclick={deleteSelected} disabled={deleting}>
                {deleting ? 'deleting...' : 'confirm'}
              </button>
              <button class="confirm-btn cancel" onclick={() => (confirmAction = null)} disabled={deleting}>
                cancel
              </button>
            </div>
          {:else if confirmAction === 'all'}
            <div class="confirm-prompt">
              <span>permanently delete all {done.length} episodes?</span>
              <button class="confirm-btn danger" onclick={deleteAll} disabled={deleting}>
                {deleting ? 'deleting...' : 'confirm delete all'}
              </button>
              <button class="confirm-btn cancel" onclick={() => (confirmAction = null)} disabled={deleting}>
                cancel
              </button>
            </div>
          {:else}
            <button
              type="button"
              class="action-btn"
              onclick={toggleViewDensity}
              title={`Switch to ${viewDensity === 'detailed' ? 'compact' : 'detailed'} view`}
            >
              <Icon name={viewDensity === 'detailed' ? 'layers' : 'template'} size={12} />
              <span>view: {viewDensity}</span>
            </button>
            <button
              type="button"
              class="action-btn"
              disabled={selectedIds.size === 0 || deleting}
              onclick={() => (confirmAction = 'selected')}
              title="Delete selected episodes"
            >
              <Icon name="trash" size={12} /> <span>delete selected ({selectedIds.size})</span>
            </button>
            <button
              type="button"
              class="action-btn danger"
              disabled={done.length === 0 || deleting}
              onclick={() => (confirmAction = 'all')}
              title="Delete all finished episodes"
            >
              <span>delete all</span>
            </button>
          {/if}
        </div>
      </div>
    {/if}

    {#if shown.length === 0}
      <p class="mono note" role="status" aria-live="polite">// no episode matches. try clearing a filter.</p>
    {:else}
      <ul class="shelf" class:compact={viewDensity === 'compact'} class:managing={manageMode}>
        {#each shown as e (e.id)}
          {@const isSelected = selectedIds.has(e.id)}
          <li class="shelf-item" class:selected={isSelected}>
            {#if manageMode}
              <div class="row-checkbox">
                <input
                  type="checkbox"
                  checked={isSelected}
                  onchange={() => toggleSelect(e.id)}
                  onclick={(evt) => evt.stopPropagation()}
                  aria-label={`Select ${e.title}`}
                />
              </div>
            {/if}
            <div class="ep-thumb" aria-hidden="true" onclick={() => (manageMode ? toggleSelect(e.id) : onResume(e))}>
              {#if e.og_image}
                <img src={coverUrl(e.og_image)} alt="" class="thumb-img" loading="lazy" />
              {:else}
                <div class="thumb-fallback">
                  <Icon name="mic" size={viewDensity === 'compact' ? 14 : 18} />
                </div>
              {/if}
            </div>
            <button
              type="button"
              class="entry"
              onclick={() => (manageMode ? toggleSelect(e.id) : onResume(e))}
            >
              {#if e.show_name && (hasMultipleShows || e.show_name)}
                <span class="show-badge mono" title="Series: {e.show_name}">{e.show_name}</span>
              {/if}
              <span class="etitle">{cleanTitle(e.title)}</span>
              {#if e.description && viewDensity === 'detailed'}<span class="edesc">{e.description}</span>{/if}
              <span class="emeta mono">
                {#if viewDensity === 'compact'}
                  <span class="meta-compact-date">{dateLabel(e.created_at, true)}</span>
                  {#if durLabel(durSec(e) * 1000)}· {durLabel(durSec(e) * 1000)}{/if}
                  · <span class="stat-tag plays-tag" class:highlighted={sortBy === 'most_played'}>
                      <Icon name="playtri" size={10} /> {fmtCount(getEpisodePlayCount(e.id), 'play', 'plays')}
                    </span>
                  · <span class="stat-tag hl-tag" class:highlighted={sortBy === 'most_highlighted'} class:has-hl={getEpisodeHighlightCount(e.id) > 0}>
                      <Icon name="highlighter" size={10} /> {getEpisodeHighlightCount(e.id)} hl
                    </span>
                  · <span class="stat-tag zaps-tag" class:highlighted={sortBy === 'most_zapped'} class:has-sats={getEpisodeZappedSats(e.id) > 0}>
                      <Icon name="zap" size={10} /> {getEpisodeZappedSats(e.id).toLocaleString()} sats
                    </span>
                  {#if e.show_name && hasMultipleShows}· <span class="badge show-mini">{e.show_name}</span>{/if}
                  {#if e.watchlist_id}· <span class="badge">auto</span>{/if}
                  {#if e.digest}· <span class="badge">digest</span>{/if}
                {:else}
                  {dateLabel(e.created_at)}
                  {#if e.style}· {e.style}{/if}
                  · {e.format === 'narration' ? 'read aloud' : 'conversation'}
                  {#if e.language && e.language !== 'auto'}· {e.language}{/if}
                  {#if durLabel(durSec(e) * 1000)}· {durLabel(durSec(e) * 1000)}{/if}
                  · <span class="stat-tag plays-tag" class:highlighted={sortBy === 'most_played'}>
                      <Icon name="playtri" size={11} /> {fmtCount(getEpisodePlayCount(e.id), 'play', 'plays')}
                    </span>
                  · <span class="stat-tag hl-tag" class:highlighted={sortBy === 'most_highlighted'} class:has-hl={getEpisodeHighlightCount(e.id) > 0}>
                      <Icon name="highlighter" size={11} /> {fmtCount(getEpisodeHighlightCount(e.id), 'highlight', 'highlights')}
                    </span>
                  · <span class="stat-tag zaps-tag" class:highlighted={sortBy === 'most_zapped'} class:has-sats={getEpisodeZappedSats(e.id) > 0}>
                      <Icon name="zap" size={11} /> {getEpisodeZappedSats(e.id).toLocaleString()} sats
                    </span>
                  {#if e.show_name}· <span class="badge show-mini">{e.show_name}</span>{/if}
                  {#if e.watchlist_id}· <span class="badge">auto</span>{/if}
                  {#if e.digest}· <span class="badge">digest</span>{/if}
                {/if}
              </span>
            </button>
            {#if !manageMode}
              <button
                type="button"
                class="row-delete-btn"
                onclick={(evt) => deleteSingle(e.id, evt)}
                title="Delete episode"
                aria-label={`Delete ${e.title}`}
              >
                <Icon name="trash" size={13} />
              </button>
            {/if}
          </li>
        {/each}
      </ul>
    {/if}
  {/if}

  {#if failed.length > 0}
    <details class="graveyard">
      <summary class="mono graveyard-summary">didn't make it ({failed.length})</summary>
      <button class="mono clear-failed" onclick={clearFailed} disabled={clearing} aria-label="Clear failed jobs">{clearing ? 'clearing...' : 'clear failed'}</button>
      <ul class="mono ghosts">
        {#each failed as e (e.id)}
          <li>
            {e.title || e.url}
            {#if e.error}
              <span class="ghost-error" title={e.error}>{e.error.length > 160 ? `${e.error.slice(0, 160)}…` : e.error}</span>
            {/if}
          </li>
        {/each}
      </ul>
    </details>
  {/if}


  <footer class="foot">
    <p class="mono tagline">private by design · no tracking · no accounts</p>
  </footer>
</main>

<style>
  main {
    max-width: var(--content-max-width);
    margin: 0 auto;
    padding: var(--space-6) var(--space-4);
  }

  @media (max-width: 768px) {
    main {
      padding: var(--space-4) var(--space-3);
    }
  }

  .note {
    color: var(--ink-soft);
  }

  .library-toolbar {
    display: flex;
    flex-direction: column;
    gap: var(--space-3);
    margin-bottom: var(--space-4);
    background: color-mix(in srgb, var(--ink) 2%, var(--paper));
    border: 1px solid var(--line);
    border-radius: var(--radius);
    padding: var(--space-3);
  }

  .toolbar-row {
    display: flex;
    align-items: center;
    justify-content: space-between;
    gap: var(--space-3);
    flex-wrap: wrap;
  }

  .searchbar {
    width: 100%;
  }

  .search-wrap {
    flex: 1 1 240px;
    display: flex;
    align-items: center;
    gap: var(--space-2);
    background: color-mix(in srgb, var(--ink) 4%, var(--paper));
    border: 1px solid var(--line);
    border-radius: var(--radius);
    padding: 0 var(--space-2);
    min-height: 38px;
    color: var(--ink-soft);
    transition: border-color var(--dur-fast) ease-out, background var(--dur-fast) ease-out;
  }

  .search-wrap:focus-within {
    border-color: var(--green);
    background: color-mix(in srgb, var(--green) 3%, var(--paper));
    color: var(--green);
  }

  .search-input {
    flex: 1 1 auto;
    border: none;
    background: transparent;
    font-family: var(--font-mono);
    font-size: var(--ui-size);
    color: var(--ink);
    padding: 6px 0;
    outline: none;
  }

  .search-input:focus-visible {
    outline: 2px solid var(--green);
    outline-offset: 2px;
    border-radius: var(--radius);
  }

  .search-input::placeholder {
    color: var(--ink-soft);
    opacity: 0.7;
  }

  .clear-search-btn {
    background: transparent;
    border: none;
    color: var(--ink-soft);
    cursor: pointer;
    font-size: 16px;
    padding: 0 4px;
    line-height: 1;
  }

  .clear-search-btn:hover {
    color: var(--ink);
  }

  .sort-wrap {
    flex: 0 0 auto;
  }

  .sort-label {
    display: inline-flex;
    align-items: center;
    gap: var(--space-2);
    font-size: var(--ui-size);
    color: var(--ink-soft);
  }

  .sort-caption {
    font-size: calc(var(--ui-size) * 0.9);
    color: var(--ink-soft);
    letter-spacing: 0.04em;
  }

  .sort-label select,
  .filter-group select {
    background: color-mix(in srgb, var(--ink) 4%, var(--paper));
    border: 1px solid var(--line);
    border-radius: var(--radius);
    color: var(--ink);
    font-family: var(--font-mono);
    font-size: var(--ui-size);
    padding: 5px 8px;
    cursor: pointer;
    outline: none;
    transition: border-color var(--dur-fast) ease-out;
  }

  .sort-label select:focus-visible,
  .filter-group select:focus-visible {
    outline: 2px solid var(--green);
    outline-offset: 2px;
    border-color: var(--green);
  }

  .filterbar {
    width: 100%;
    color: var(--ink-soft);
  }

  .filter-group {
    display: flex;
    align-items: center;
    gap: var(--space-3);
    flex-wrap: wrap;
  }

  .filter-group label {
    display: inline-flex;
    align-items: center;
    gap: var(--space-2);
    font-size: var(--ui-size);
    letter-spacing: 0.04em;
    color: var(--ink-soft);
  }

  .filter-meta {
    margin-left: auto;
    display: flex;
    align-items: center;
    gap: var(--space-3);
    flex-wrap: wrap;
  }

  .count {
    font-size: var(--ui-size);
    color: var(--ink-soft);
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

  .chip:hover,
  .chip.active {
    color: var(--green);
    border-color: var(--green);
    background: color-mix(in srgb, var(--green) 4%, transparent);
  }

  .manage-bar {
    display: flex;
    align-items: center;
    justify-content: space-between;
    gap: var(--space-3);
    padding: var(--space-2) var(--space-3);
    margin-bottom: var(--space-4);
    background: color-mix(in srgb, var(--line) 30%, transparent);
    border: 1px solid var(--line);
    border-radius: var(--radius);
    flex-wrap: wrap;
    font-size: var(--ui-size);
  }

  .manage-left {
    display: flex;
    align-items: center;
    gap: var(--space-3);
  }

  .select-all-label {
    display: inline-flex;
    align-items: center;
    gap: 6px;
    cursor: pointer;
    color: var(--ink);
  }

  .selected-count {
    color: var(--ink-soft);
  }

  .manage-actions {
    display: flex;
    align-items: center;
    gap: var(--space-2);
    margin-left: auto;
  }

  .action-btn {
    display: inline-flex;
    align-items: center;
    gap: 6px;
    background: transparent;
    border: 1px solid var(--line);
    border-radius: var(--radius);
    padding: 4px 10px;
    color: var(--ink);
    font-family: var(--font-mono);
    font-size: var(--ui-size);
    cursor: pointer;
    transition: color var(--dur-fast) ease-out, border-color var(--dur-fast) ease-out, background var(--dur-fast) ease-out;
  }

  .action-btn:hover:not(:disabled) {
    border-color: var(--green);
    color: var(--green);
    background: color-mix(in srgb, var(--green) 4%, transparent);
  }

  .action-btn.danger:hover:not(:disabled) {
    border-color: #e74c3c;
    color: #e74c3c;
    background: color-mix(in srgb, #e74c3c 6%, transparent);
  }

  .action-btn:disabled {
    opacity: 0.4;
    cursor: default;
  }

  .confirm-prompt {
    display: flex;
    align-items: center;
    gap: var(--space-2);
    color: var(--ink);
  }

  .confirm-btn {
    background: transparent;
    border: 1px solid var(--line);
    border-radius: var(--radius);
    padding: 3px 8px;
    font-family: var(--font-mono);
    font-size: var(--ui-size);
    cursor: pointer;
  }

  .confirm-btn.danger {
    border-color: #e74c3c;
    color: #e74c3c;
    background: color-mix(in srgb, #e74c3c 10%, transparent);
  }

  .confirm-btn.cancel {
    color: var(--ink-soft);
  }

  .confirm-btn:hover {
    filter: brightness(1.2);
  }

  .edesc {
    color: var(--ink-soft);
    font-size: 0.95rem;
    line-height: 1.45;
    max-width: 58ch;
  }

  .library-summary {
    font-size: var(--ui-size);
    color: var(--ink-soft);
    margin-bottom: var(--space-3);
    padding: var(--space-2) var(--space-3);
    background: color-mix(in srgb, var(--line) 25%, transparent);
    border-radius: var(--radius);
    border: 1px solid color-mix(in srgb, var(--line) 40%, transparent);
    letter-spacing: 0.02em;
  }

  .shelf {
    list-style: none;
    margin: 0;
    padding: 0;
    display: grid;
    gap: var(--space-3);
  }

  .shelf-item {
    position: relative;
    display: flex;
    align-items: stretch;
    gap: var(--space-3);
    list-style: none;
    border: 1px solid var(--line);
    border-radius: var(--radius);
    padding: var(--space-2);
    transition: border-color var(--dur-fast) ease-out, background var(--dur-fast) ease-out;
  }

  .shelf-item:hover {
    border-color: color-mix(in srgb, var(--green) 50%, var(--line));
  }

  .shelf-item.selected {
    border-color: var(--green);
    background: color-mix(in srgb, var(--green) 3%, transparent);
  }

  .ep-thumb {
    width: 64px;
    height: 64px;
    flex: none;
    border-radius: calc(var(--radius) - 2px);
    overflow: hidden;
    background: color-mix(in srgb, var(--line) 30%, transparent);
    border: 1px solid color-mix(in srgb, var(--line) 50%, transparent);
    display: flex;
    align-items: center;
    justify-content: center;
    cursor: pointer;
  }

  .thumb-img {
    width: 100%;
    height: 100%;
    object-fit: cover;
    display: block;
  }

  .thumb-fallback {
    width: 100%;
    height: 100%;
    display: flex;
    align-items: center;
    justify-content: center;
    color: var(--ink-soft);
    background: linear-gradient(135deg, color-mix(in srgb, var(--voice-a) 15%, transparent), color-mix(in srgb, var(--voice-b) 15%, transparent));
  }

  .shelf-item .entry {
    flex: 1 1 auto;
    min-width: 0;
    border: none;
    padding: 0;
    background: transparent;
  }

  .shelf.compact {
    gap: 3px;
  }

  .shelf.compact .shelf-item {
    padding: 3px var(--space-2);
    gap: var(--space-2);
    align-items: center;
    min-width: 0;
    max-width: 100%;
    overflow: hidden;
    border-color: color-mix(in srgb, var(--line) 40%, transparent);
  }

  .shelf.compact .ep-thumb {
    width: 28px;
    height: 28px;
    border-radius: var(--radius);
    flex: 0 0 28px;
  }

  .shelf.compact .etitle {
    font-size: 0.90rem;
    white-space: nowrap;
    overflow: hidden;
    text-overflow: ellipsis;
    flex: 1 1 auto;
    min-width: 0;
  }

  .shelf.compact .edesc {
    display: none;
  }

  .shelf.compact .emeta {
    font-size: calc(var(--ui-size) * 0.76);
    white-space: nowrap;
    flex: 0 0 auto;
    color: var(--ink-soft);
    display: inline-flex;
    align-items: center;
    gap: 4px;
  }

  .shelf.compact .entry {
    display: flex;
    flex-direction: row;
    align-items: center;
    justify-content: space-between;
    gap: var(--space-3);
    flex: 1 1 auto;
    min-width: 0;
    max-width: 100%;
    overflow: hidden;
    text-align: left;
  }

  .shelf.compact .row-delete-btn {
    position: static;
    transform: none;
    padding: 2px;
    flex: 0 0 auto;
    opacity: 0.6;
  }

  .shelf.compact .shelf-item:hover .row-delete-btn {
    opacity: 1;
  }

  .view-chip {
    text-transform: lowercase;
  }

  .stat-tag {
    display: inline-flex;
    align-items: center;
    gap: 3px;
    color: var(--ink-soft);
    vertical-align: middle;
  }

  .stat-tag.highlighted {
    color: var(--ink);
    font-weight: 500;
  }

  .stat-tag.zaps-tag.has-sats {
    color: var(--green);
  }

  .stat-tag.zaps-tag.highlighted {
    color: var(--green);
  }

  .stat-tag.hl-tag.has-hl {
    color: color-mix(in srgb, var(--green) 85%, var(--ink));
  }

  .stat-tag.hl-tag.highlighted {
    color: var(--green);
    font-weight: 500;
  }

  .row-checkbox {
    flex: none;
    display: flex;
    align-items: center;
    justify-content: center;
    cursor: pointer;
    padding: var(--space-1);
  }

  .row-checkbox input[type="checkbox"],
  .select-all-label input[type="checkbox"] {
    accent-color: var(--green);
    width: 16px;
    height: 16px;
    cursor: pointer;
  }

  .row-delete-btn {
    opacity: 0;
    position: absolute;
    right: var(--space-3);
    top: var(--space-3);
    background: transparent;
    border: 1px solid transparent;
    border-radius: var(--radius);
    padding: 4px;
    color: var(--ink-soft);
    cursor: pointer;
    transition: opacity var(--dur-fast) ease-out, color var(--dur-fast) ease-out, border-color var(--dur-fast) ease-out;
  }

  .shelf-item:hover .row-delete-btn,
  .row-delete-btn:focus-visible {
    opacity: 1;
  }

  .row-delete-btn:hover {
    color: #e74c3c;
    border-color: color-mix(in srgb, #e74c3c 40%, transparent);
    background: color-mix(in srgb, #e74c3c 8%, transparent);
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
    transition: border-color var(--dur-fast) ease-out;
  }

  @media (max-width: 768px) {
    .entry {
      padding: var(--space-3);
    }
    .row-delete-btn {
      opacity: 0.7;
      top: var(--space-2);
      right: var(--space-2);
    }
  }

  .entry:hover {
    border-color: var(--green);
  }

  .etitle {
    font-family: var(--font-serif);
    font-size: 1.05rem;
    line-height: 1.35;
  }

  .emeta {
    color: var(--ink-soft);
  }

  .badge {
    display: inline-block;
    background: var(--line);
    color: var(--ink-soft);
    padding: 1px 6px;
    border-radius: var(--radius);
    font-size: calc(var(--ui-size) * 0.72);
    letter-spacing: 0.06em;
    vertical-align: middle;
  }

  .show-badge {
    display: inline-block;
    background: color-mix(in srgb, var(--green) 12%, var(--paper));
    color: var(--green);
    border: 1px solid color-mix(in srgb, var(--green) 30%, transparent);
    padding: 1px 6px;
    border-radius: var(--radius);
    font-size: calc(var(--ui-size) * 0.72);
    letter-spacing: 0.06em;
    vertical-align: middle;
    margin-bottom: 2px;
  }

  .show-mini {
    background: color-mix(in srgb, var(--green) 10%, transparent);
    color: var(--green);
    border: 1px solid color-mix(in srgb, var(--green) 25%, transparent);
  }

  .graveyard {
    margin-top: var(--space-4);
  }

  .graveyard-summary {
    font-size: var(--ui-size);
    color: var(--ink-soft);
    cursor: pointer;
    display: inline;
    text-transform: lowercase;
    letter-spacing: 0.02em;
  }

  .graveyard-summary:hover {
    color: var(--ink);
  }

  .graveyard[open] .graveyard-summary {
    margin-bottom: var(--space-2);
  }

  .ghost-error {
    display: block;
    font-size: calc(var(--ui-size) * 0.85);
    color: var(--ink-soft);
    opacity: 0.8;
    overflow-wrap: anywhere;
    word-break: break-word;
    max-width: 100%;
  }

  .ghosts {
    list-style: none;
    padding: 0;
    margin: var(--space-2) 0 0;
    display: grid;
    gap: var(--space-1);
    color: var(--ink-soft);
  }

  .clear-failed {
    background: transparent;
    border: 1px solid var(--line);
    border-radius: var(--radius);
    color: var(--ink-soft);
    font-family: var(--font-mono);
    font-size: calc(var(--ui-size) * 0.85);
    padding: var(--space-1) var(--space-2);
    cursor: pointer;
    margin-top: var(--space-2);
  }

  .clear-failed:hover {
    border-color: var(--ink-soft);
    color: var(--ink);
  }

  .clear-failed:disabled {
    opacity: 0.6;
    cursor: default;
  }

  footer {
    margin-top: var(--space-6);
    border-top: 1px solid var(--line);
    padding-top: var(--space-3);
  }

  .tagline {
    color: var(--ink-soft);
    font-size: var(--ui-size);
  }
</style>

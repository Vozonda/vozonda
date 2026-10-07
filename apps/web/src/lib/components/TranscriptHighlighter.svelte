<script lang="ts">
  import { onMount } from 'svelte'
  import {
    DEFAULT_RELAYS,
    buildHighlightEvent,
    signHighlight,
    publishHighlight,
    fetchHighlights,
    categorizeHighlight,
    type HighlightParsed
  } from '../highlights'
  import { getActiveIdentity } from '../nostr'

  import Icon from './Icon.svelte'
  import type { Snippet } from 'svelte'

  interface SliceDetail {
    turnStart: number
    turnEnd: number
    text: string
  }

  interface Props {
    episodeUrl: string
    authorPubkey?: string | null
    transcriptText?: string
    relays?: string[]
    friendPubkeys?: string[]
    children?: Snippet
    onHighlightCountChange?: (count: number) => void
    onHighlightsChange?: (highlights: HighlightParsed[]) => void
    onSlice?: (detail: SliceDetail) => void
  }

  let {
    episodeUrl,
    authorPubkey = null,
    transcriptText = '',
    relays = DEFAULT_RELAYS,
    friendPubkeys = [],
    children,
    onHighlightCountChange,
    onHighlightsChange,
    onSlice
  }: Props = $props()

  let wrapper: HTMLDivElement | undefined = $state(undefined)
  let selectionText = $state('')
  let selectionContext = $state<string | null>(null)
  let popupPos = $state<{ x: number; y: number; placeBelow: boolean } | null>(null)
  let popupOpen = $state(false)
  let busy = $state(false)
  let copiedQuote = $state(false)
  let error = $state('')
  let doneMsg = $state('')
  let highlights = $state<HighlightParsed[]>([])
  let fetched = $state(false)
  let selectionTimeout: ReturnType<typeof setTimeout> | undefined
  let sliceRange = $state<{ turnStart: number; turnEnd: number } | null>(null)

  $effect(() => {
    onHighlightCountChange?.(highlights.length)
    onHighlightsChange?.(highlights)
  })

  const friendSet = $derived(new Set((friendPubkeys ?? []).map((k) => k.toLowerCase())))
  const userPubkey = $derived.by(() => {
    try {
      const id = getActiveIdentity()
      return id?.pubkey ?? null
    } catch { return null }
  })

  // group counts for legend
  const counts = $derived.by(() => {
    let user = 0, friend = 0, global = 0
    for (const h of highlights) {
      const cat = categorizeHighlight(h, userPubkey, friendSet)
      if (cat === 'user') user++
      else if (cat === 'friend') friend++
      else global++
    }
    return { user, friend, global }
  })

  function categoryFor(h: HighlightParsed): 'user' | 'friend' | 'global' {
    return categorizeHighlight(h, userPubkey, friendSet)
  }

  // Defer relay fetch until after audio is interactive: requestIdleCallback or timeout
  onMount(() => {
    const onDocSelectionChange = () => onSelectionChangeDebounced()
    const onWinScroll = () => {
      if (popupOpen) updateSelection()
    }
    const onWinResize = () => {
      if (popupOpen) updateSelection()
    }

    document.addEventListener('selectionchange', onDocSelectionChange)
    window.addEventListener('scroll', onWinScroll, { passive: true })
    window.addEventListener('resize', onWinResize)

    let stopFn: (() => void) | undefined
    if (episodeUrl) {
      const startFetch = () => {
        try {
          const stop = fetchHighlights(
            relays,
            episodeUrl,
            (h) => {
              highlights = [...highlights, h]
            },
            () => { fetched = true },
            6000
          )
          return stop
        } catch {
          fetched = true
          return () => {}
        }
      }
      // Ensure audio playback is not blocked: schedule fetch idle
      const w = window as unknown as Record<string, unknown>
      if (typeof (w['requestIdleCallback'] as unknown) === 'function') {
        const ric = w['requestIdleCallback'] as (cb: () => void, opts?: { timeout: number }) => number
        ric(() => { stopFn = startFetch() }, { timeout: 2500 })
      } else {
        const t = setTimeout(() => { stopFn = startFetch() }, 900)
        void t
      }
    }

    return () => {
      document.removeEventListener('selectionchange', onDocSelectionChange)
      window.removeEventListener('scroll', onWinScroll)
      window.removeEventListener('resize', onWinResize)
      clearTimeout(selectionTimeout)
      try { stopFn?.() } catch {}
    }
  })

  function computeSliceRange(sel: Selection): { turnStart: number; turnEnd: number } | null {
    if (!wrapper) return null
    try {
      const range = sel.getRangeAt(0)
      const fragment = range.cloneContents()
      // Collect data-turn values from wrapper lis that intersect selection
      const allLis = wrapper.querySelectorAll('li[data-turn]')
      if (allLis.length === 0) return null
      const selected: number[] = []
      for (const li of allLis) {
        const idxAttr = (li as HTMLElement).getAttribute('data-turn')
        if (idxAttr === null) continue
        const idx = parseInt(idxAttr, 10)
        if (Number.isNaN(idx)) continue
        if (sel.containsNode(li as Node, true)) {
          selected.push(idx)
        } else {
          // Fallback: check range intersects li via Range comparison
          try {
            const liRange = document.createRange()
            liRange.selectNodeContents(li as Node)
            const intersects = !(range.compareBoundaryPoints(Range.END_TO_START, liRange) >= 0 || range.compareBoundaryPoints(Range.START_TO_END, liRange) <= 0)
            if (intersects) selected.push(idx)
            liRange.detach?.()
          } catch {}
        }
      }
      // If cloneContents heuristic found turns, use it; otherwise try anchor/focus proximity
      if (selected.length > 0) {
        return { turnStart: Math.min(...selected), turnEnd: Math.max(...selected) }
      }
      // Fallback: find closest li for anchor/focus
      const anchorEl = sel.anchorNode ? (sel.anchorNode.nodeType === 1 ? sel.anchorNode as HTMLElement : (sel.anchorNode.parentElement as HTMLElement | null)) : null
      const focusEl = sel.focusNode ? (sel.focusNode.nodeType === 1 ? sel.focusNode as HTMLElement : (sel.focusNode.parentElement as HTMLElement | null)) : null
      const aLi = anchorEl?.closest?.('li[data-turn]') as HTMLElement | null
      const fLi = focusEl?.closest?.('li[data-turn]') as HTMLElement | null
      const aIdx = aLi ? parseInt(aLi.getAttribute('data-turn') ?? '', 10) : NaN
      const fIdx = fLi ? parseInt(fLi.getAttribute('data-turn') ?? '', 10) : NaN
      if (!Number.isNaN(aIdx) && !Number.isNaN(fIdx)) {
        return { turnStart: Math.min(aIdx, fIdx), turnEnd: Math.max(aIdx, fIdx) }
      }
      if (!Number.isNaN(aIdx)) return { turnStart: aIdx, turnEnd: aIdx }
      if (!Number.isNaN(fIdx)) return { turnStart: fIdx, turnEnd: fIdx }
      void fragment
      return null
    } catch {
      return null
    }
  }

  function updateSelection() {
    const sel = window.getSelection()
    if (!sel || sel.isCollapsed || sel.rangeCount === 0) {
      if (popupOpen && !busy) {
        popupOpen = false
        popupPos = null
        sliceRange = null
      }
      return
    }
    const text = sel.toString().trim()
    if (!text || text.length < 2 || text.length > 2000) {
      if (popupOpen && !busy) {
        popupOpen = false
        popupPos = null
        sliceRange = null
      }
      return
    }
    if (!wrapper) return
    const anchor = sel.anchorNode
    const focus = sel.focusNode
    const inside = (n: Node | null) => n && wrapper!.contains(n)
    if (!inside(anchor) && !inside(focus)) return

    let range: Range
    try {
      range = sel.getRangeAt(0)
    } catch {
      return
    }
    if (!wrapper.contains(range.commonAncestorContainer)) return

    const rect = range.getBoundingClientRect()
    if (rect.width === 0 && rect.height === 0) return

    // Position fixed relative to viewport
    const rawX = rect.left + rect.width / 2
    const margin = 230
    const clampedX = Math.min(window.innerWidth - margin, Math.max(margin, rawX))

    let y = rect.top - 12
    let placeBelow = false
    if (rect.top < 70) {
      y = rect.bottom + 12
      placeBelow = true
    }

    popupPos = { x: clampedX, y, placeBelow }
    selectionText = text
    sliceRange = computeSliceRange(sel)

    try {
      const container = range.commonAncestorContainer as HTMLElement
      const el = container.nodeType === 1 ? container : (container.parentElement as HTMLElement | null)
      const lineEl = el?.closest?.('li')
      selectionContext = lineEl?.textContent?.slice(0, 5000) ?? transcriptText?.slice(0, 600) ?? null
      if (selectionContext && selectionContext.length > 5000) selectionContext = selectionContext.slice(0, 5000)
    } catch {
      selectionContext = transcriptText?.slice(0, 600) ?? null
    }

    popupOpen = true
    copiedQuote = false
    error = ''
    doneMsg = ''
  }

  function onSelectionChangeDebounced() {
    clearTimeout(selectionTimeout)
    selectionTimeout = setTimeout(updateSelection, 60)
  }

  function clearSelection() {
    selectionText = ''
    selectionContext = null
    popupOpen = false
    popupPos = null
    sliceRange = null
    copiedQuote = false
    error = ''
    doneMsg = ''
    const sel = window.getSelection()
    try { sel?.removeAllRanges() } catch {}
  }

  function handleSlice() {
    if (!selectionText || !onSlice) return
    const range = sliceRange
    if (!range) {
      error = 'select inside transcript to slice'
      return
    }
    try {
      onSlice({ turnStart: range.turnStart, turnEnd: range.turnEnd, text: selectionText })
      setTimeout(clearSelection, 280)
    } catch (e) {
      error = (e as Error).message ?? String(e)
    }
  }

  async function handleCopyQuote() {
    if (!selectionText) return
    let textToCopy = `"${selectionText}"`
    if (selectionContext) {
      const cleanContext = selectionContext.replace(/\s+/g, ' ').trim()
      textToCopy = `"${selectionText}"\n- ${cleanContext}`
    }
    try {
      if (navigator.clipboard) {
        await navigator.clipboard.writeText(textToCopy)
      }
      copiedQuote = true
      setTimeout(() => {
        copiedQuote = false
        clearSelection()
      }, 1000)
    } catch {
      copiedQuote = true
      setTimeout(() => { copiedQuote = false }, 1000)
    }
  }

  async function handleShare() {
    if (!selectionText || busy) return
    busy = true
    error = ''
    doneMsg = ''
    try {
      const tmpl = buildHighlightEvent({
        content: selectionText,
        sourceUrl: episodeUrl,
        context: selectionContext,
        authorPubkey: authorPubkey?.trim() || null
      })
      let signed
      try {
        signed = await signHighlight(tmpl as unknown as import('../nostr').NostrEventTemplate)
      } catch (e) {
        throw new Error(`signing failed: ${(e as Error).message}`)
      }
      try {
        const plan = await publishHighlight(signed, relays, 4000)
        doneMsg = plan.ok > 0 ? `shared to ${plan.ok} relay${plan.ok === 1 ? '' : 's'}` : 'highlight signed'
      } catch {
        doneMsg = 'published locally'
      }
      // optimistic add to local list as user highlight
      const now: HighlightParsed = {
        id: signed.id,
        pubkey: signed.pubkey,
        content: signed.content,
        createdAt: signed.created_at,
        sourceUrl: episodeUrl,
        alt: 'highlight',
        context: selectionContext ?? undefined,
        authorPubkeys: authorPubkey ? [authorPubkey.toLowerCase()] : [],
        pTags: authorPubkey ? [['p', authorPubkey.toLowerCase()]] : [],
        tags: signed.tags as string[][]
      }
      highlights = [...highlights, now]
      setTimeout(clearSelection, 1400)
    } catch (e) {
      error = (e as Error).message ?? String(e)
    } finally {
      busy = false
    }
  }

  function handleKey(e: KeyboardEvent) {
    if (e.key === 'Escape') clearSelection()
  }
</script>

<!-- swarm ticks: tiny inline markers for each highlight positioned under transcript via CSS -->
{#if highlights.length > 0}
  <div class="hl-swarm" aria-hidden="true">
    {#each highlights as h, idx (idx)}
      {@const cat = categoryFor(h)}
      <span
        class="hl-mark hl-{cat}"
        title={`${h.content.slice(0, 80)}${h.content.length > 80 ? '...' : ''} : ${cat}`}
        aria-hidden="true"
      ></span>
    {/each}
  </div>
{/if}

<!-- svelte-ignore a11y_no_noninteractive_element_interactions -->
<div
  bind:this={wrapper}
  class="transcript-highlighter"
  role="region"
  aria-label="Transcript with highlights"
  onmouseup={updateSelection}
  ontouchend={onSelectionChangeDebounced}
  onkeyup={updateSelection}
>
  {#if children}
    {@render children()}
  {/if}
</div>

{#if popupOpen && selectionText}
  <div
    class="hl-popup"
    class:below={popupPos?.placeBelow}
    role="toolbar"
    aria-label="Selection actions"
    tabindex="-1"
    style={popupPos ? `--desk-x: ${popupPos.x}px; --desk-y: ${popupPos.y}px;` : ''}
    onpointerdown={(e) => e.stopPropagation()}
    onmousedown={(e) => e.preventDefault()}
  >
    <div class="hl-popup-card">
      <div class="hl-quote-preview mono" title={selectionText}>
        <span class="hl-quote-icon">"</span>
        <span class="hl-quote-text">{selectionText.length > 55 ? selectionText.slice(0, 55) + '...' : selectionText}</span>
        <span class="hl-quote-icon">"</span>
      </div>
      <div class="hl-actions-row">
        <button
          type="button"
          class="hl-btn hl-btn-highlight"
          onclick={handleShare}
          disabled={busy}
          aria-label="Highlight on Nostr (NIP-84)"
        >
          <Icon name="zap" size={13} />
          <span>{busy ? 'sharing...' : doneMsg ? 'shared!' : 'highlight (NIP-84)'}</span>
        </button>
        <button
          type="button"
          class="hl-btn hl-btn-copy"
          onclick={handleCopyQuote}
          aria-label="Copy quote"
        >
          <Icon name="copy" size={13} />
          <span>{copiedQuote ? 'copied!' : 'copy quote'}</span>
        </button>
        {#if onSlice}
          <button
            type="button"
            class="hl-btn hl-btn-slice"
            onclick={handleSlice}
            disabled={!sliceRange}
            aria-label="Slice audio clip from selection"
            title={sliceRange ? `Slice turns ${sliceRange.turnStart} to ${sliceRange.turnEnd}` : 'Select inside transcript to slice'}
          >
            <Icon name="slice" size={13} />
            <span>slice</span>
          </button>
        {/if}
        <button type="button" class="hl-btn-close" onclick={clearSelection} aria-label="Dismiss selection">
          <Icon name="close" size={13} />
        </button>
      </div>
      {#if error}
        <p class="hl-err mono" role="alert">{error}</p>
      {:else if doneMsg}
        <p class="hl-success mono" role="status">{doneMsg}</p>
      {/if}
    </div>
  </div>
{/if}

<style>
  .transcript-highlighter {
    position: relative;
  }
  .hl-swarm {
    display: flex;
    flex-wrap: wrap;
    gap: 4px;
    margin: 0 0 8px;
    min-height: 6px;
  }
  .hl-mark {
    display: inline-block;
    width: 18px;
    height: 6px;
    border-radius: var(--radius);
    border: 1px solid transparent;
  }
  .hl-mark.hl-user {
    background: #1a5c1a;
  }
  .hl-mark.hl-friend {
    background: #7ec87e;
  }
  .hl-mark.hl-global {
    background: #d9a441;
  }
  :global(.transcript-highlighter :is(li, p, span).hl-hit) {
    box-decoration-break: clone;
  }
  /* highlight hits inside transcript: category colors */
  :global(.hl-hit-user) {
    background: color-mix(in srgb, #1a5c1a 18%, transparent);
    border-bottom: 2px solid #1a5c1a;
  }
  :global(.hl-hit-friend) {
    background: color-mix(in srgb, #7ec87e 22%, transparent);
    border-bottom: 2px solid #7ec87e;
  }
  :global(.hl-hit-global) {
    background: color-mix(in srgb, #d9a441 22%, transparent);
    border-bottom: 2px solid #d9a441;
  }

  .hl-tag {
    color: var(--ink-soft);
    letter-spacing: 0.04em;
    margin-right: 4px;
  }

  /* Desktop floating popup */
  .hl-popup {
    position: fixed;
    z-index: 100;
    left: var(--desk-x, 50%);
    top: var(--desk-y, 50%);
    transform: translate(-50%, -100%);
    filter: drop-shadow(0 8px 24px rgba(0, 0, 0, 0.22));
    pointer-events: auto;
    width: max-content;
    max-width: min(94vw, 460px);
  }
  .hl-popup.below {
    transform: translate(-50%, 0);
  }
  .hl-popup-card {
    background: var(--paper);
    border: 1px solid color-mix(in srgb, var(--ink) 18%, var(--line));
    border-radius: var(--radius);
    padding: 8px 10px;
    display: flex;
    flex-direction: column;
    gap: 6px;
    box-shadow: 0 4px 20px rgba(0, 0, 0, 0.16);
    width: max-content;
    max-width: min(94vw, 460px);
    box-sizing: border-box;
  }
  .hl-quote-preview {
    font-size: calc(var(--ui-size) * 0.78);
    color: var(--ink-soft);
    display: flex;
    align-items: center;
    gap: 2px;
    overflow: hidden;
    white-space: nowrap;
    text-overflow: ellipsis;
    padding-bottom: 4px;
    border-bottom: 1px solid color-mix(in srgb, var(--ink) 8%, var(--line));
  }
  .hl-quote-text {
    overflow: hidden;
    white-space: nowrap;
    text-overflow: ellipsis;
  }
  .hl-actions-row {
    display: flex;
    align-items: center;
    gap: 5px;
    flex-wrap: nowrap;
    width: 100%;
    box-sizing: border-box;
  }
  .hl-btn {
    display: inline-flex;
    align-items: center;
    gap: 4px;
    font-family: var(--font-mono);
    font-size: calc(var(--ui-size) * 0.8);
    padding: 4px 8px;
    border-radius: var(--radius);
    cursor: pointer;
    white-space: nowrap;
    touch-action: manipulation;
    transition: background var(--dur-fast) ease-out, color var(--dur-fast) ease-out, border-color var(--dur-fast) ease-out;
  }
  .hl-btn-highlight {
    background: color-mix(in srgb, var(--green) 12%, var(--paper));
    color: var(--ink);
    border: 1px solid var(--green);
    font-weight: 600;
  }
  .hl-btn-highlight:hover:not(:disabled) {
    background: color-mix(in srgb, var(--green) 22%, var(--paper));
    border-color: var(--green);
    color: var(--ink);
  }
  .hl-btn-highlight:disabled {
    opacity: 0.5;
    cursor: not-allowed;
  }
  .hl-btn-copy {
    background: transparent;
    color: var(--ink);
    border: 1px solid var(--line);
  }
  .hl-btn-copy:hover {
    color: var(--ink);
    border-color: var(--green);
    background: color-mix(in srgb, var(--green) 8%, var(--paper));
  }
  .hl-btn-close {
    background: transparent;
    border: 1px solid transparent;
    color: var(--ink-soft);
    border-radius: var(--radius);
    padding: 4px 6px;
    cursor: pointer;
    display: inline-flex;
    align-items: center;
    justify-content: center;
    margin-left: auto;
    touch-action: manipulation;
  }
  .hl-btn-close:hover {
    color: var(--ink);
    background: color-mix(in srgb, var(--ink) 6%, transparent);
  }
  .hl-btn-slice {
    background: var(--green);
    color: var(--paper);
    border: 1px solid var(--green);
    font-weight: 600;
  }
  .hl-btn-slice:hover:not(:disabled) {
    background: color-mix(in srgb, var(--green) 85%, var(--ink));
    border-color: var(--green);
    color: var(--paper);
  }
  .hl-btn-slice:disabled {
    opacity: 0.45;
    cursor: not-allowed;
  }
  .hl-err {
    margin: 4px 0 0;
    color: #a83232;
    font-size: calc(var(--ui-size) * 0.78);
    text-align: center;
  }
  .hl-success {
    margin: 4px 0 0;
    color: var(--green);
    font-size: calc(var(--ui-size) * 0.78);
    text-align: center;
  }

  /* Mobile bottom action dock: completely avoids native selection collision */
  @media (max-width: 640px) {
    .hl-popup {
      position: fixed;
      top: auto !important;
      bottom: calc(16px + env(safe-area-inset-bottom, 0px)) !important;
      left: 12px !important;
      right: 12px !important;
      transform: none !important;
      width: auto !important;
      max-width: 480px;
      margin: 0 auto;
      z-index: 120;
      animation: dockSlideUp 180ms ease-out;
    }
    @keyframes dockSlideUp {
      from {
        transform: translateY(20px);
        opacity: 0;
      }
      to {
        transform: translateY(0);
        opacity: 1;
      }
    }
    .hl-popup-card {
      background: color-mix(in srgb, var(--paper) 96%, transparent);
      backdrop-filter: blur(16px);
      -webkit-backdrop-filter: blur(16px);
      border: 1px solid color-mix(in srgb, var(--ink) 24%, var(--line));
      border-radius: calc(var(--radius) + 4px);
      padding: 10px 14px;
      gap: 8px;
      box-shadow: 0 8px 32px rgba(0, 0, 0, 0.28);
      max-width: 100%;
    }
    .hl-actions-row {
      gap: 8px;
      justify-content: space-between;
    }
    .hl-btn {
      flex: 1 1 auto;
      justify-content: center;
      min-height: 40px;
      padding: 6px 12px;
      font-size: calc(var(--ui-size) * 0.85);
    }
    .hl-btn-close {
      flex: 0 0 40px;
      min-height: 40px;
      min-width: 40px;
      margin-left: 0;
    }
  }

  @media (prefers-color-scheme: dark) {
    .hl-dot-user { background: #1e7a1e; border-color: #1e7a1e; }
    .hl-mark.hl-user { background: #1e7a1e; }
    :global(.hl-hit-user) { border-bottom-color: #2a8a2a; }
  }
</style>

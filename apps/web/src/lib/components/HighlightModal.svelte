<script lang="ts">
  import Icon from './Icon.svelte'
  import { getActiveIdentity, shortNpub } from '../nostr'
  import { categorizeHighlight, type HighlightParsed } from '../highlights'

  let {
    open = false,
    onClose,
    highlights = [],
    friendPubkeys = [],
    onSeekTurn
  }: {
    open: boolean
    onClose: () => void
    highlights?: HighlightParsed[]
    friendPubkeys?: string[]
    onSeekTurn?: (text: string) => void
  } = $props()

  const friendSet = $derived(new Set((friendPubkeys ?? []).map((k) => k.toLowerCase())))
  const userPubkey = $derived.by(() => {
    try {
      const id = getActiveIdentity()
      return id?.pubkey ?? null
    } catch {
      return null
    }
  })

  const counts = $derived.by(() => {
    let user = 0,
      friend = 0,
      global = 0
    for (const h of highlights) {
      const cat = categorizeHighlight(h, userPubkey, friendSet)
      if (cat === 'user') user++
      else if (cat === 'friend') friend++
      else global++
    }
    return { user, friend, global }
  })

  function closeIfBackdrop(e: MouseEvent) {
    if (e.target === e.currentTarget) onClose()
  }

  function handleKeydown(e: KeyboardEvent) {
    if (e.key === 'Escape' && open) {
      e.stopPropagation()
      onClose()
    }
  }
</script>

<svelte:window onkeydown={handleKeydown} />

{#if open}
  <div
    class="overlay"
    onclick={closeIfBackdrop}
    role="presentation"
  >
    <div
      class="modal mono"
      role="dialog"
      aria-modal="true"
      aria-labelledby="hl-modal-title"
    >
      <div class="modal-head">
        <h2 id="hl-modal-title">
          <Icon name="highlighter" size={14} /> highlights · nostr NIP-84
        </h2>
        <button
          type="button"
          class="close mono"
          onclick={onClose}
          aria-label="Close modal"
        >
          close
        </button>
      </div>

      <p class="help">
        Quotes and key passages highlighted by listeners in this episode and published to decentralized Nostr relays.
      </p>

      <div class="hl-stats">
        <span class="hl-total">{highlights.length} {highlights.length === 1 ? 'highlight' : 'highlights'}</span>
        <span class="hl-dot hl-dot-user"></span> you ({counts.user})
        <span class="hl-dot hl-dot-friend"></span> friends ({counts.friend})
        <span class="hl-dot hl-dot-global"></span> global ({counts.global})
      </div>

      {#if highlights.length > 0}
        <div class="hl-list" role="feed" aria-label="Episode highlights list">
          {#each highlights as h, idx (h.id || idx)}
            {@const cat = categorizeHighlight(h, userPubkey, friendSet)}
            <article class="hl-item hl-item-{cat}">
              <div class="hl-item-top">
                <span class="hl-badge hl-badge-{cat}">{cat}</span>
                {#if h.pubkey}
                  <span class="hl-author" title={h.pubkey}>by {shortNpub(h.pubkey)}</span>
                {/if}
                {#if onSeekTurn}
                  <button
                    type="button"
                    class="secondary hl-seek-btn"
                    onclick={() => {
                      onSeekTurn?.(h.content)
                      onClose()
                    }}
                    title="Jump to this quote in audio"
                  >
                    <Icon name="playtri" size={10} /> <span>jump to quote</span>
                  </button>
                {/if}
              </div>
              <blockquote class="hl-quote">
                "{h.content.trim()}"
              </blockquote>
            </article>
          {/each}
        </div>
      {:else}
        <div class="empty-state">
          No highlights shared on Nostr relays for this episode yet.
        </div>
      {/if}

      <div class="guide-card">
        <p class="guide-title"><Icon name="help" size={12} /> how to create your own highlights:</p>
        <ol class="guide-steps">
          <li>Select any phrase or sentence in the transcript below.</li>
          <li>Click <strong>highlight (NIP-84)</strong> in the popup menu.</li>
          <li>Sign the quote with your Nostr extension (Alby / Amber / nos2x).</li>
        </ol>
      </div>

      <div class="actions">
        <button type="button" class="primary mono" onclick={onClose}>done</button>
      </div>
    </div>
  </div>
{/if}

<style>
  .overlay {
    position: fixed;
    inset: 0;
    background: color-mix(in srgb, var(--ink) 42%, transparent);
    backdrop-filter: blur(2px);
    display: grid;
    place-items: center;
    z-index: 70;
    padding: var(--space-3);
  }

  .modal {
    width: min(560px, 100%);
    max-height: 90vh;
    overflow: auto;
    background: var(--paper);
    border: 1px solid var(--line);
    border-radius: var(--radius);
    padding: var(--space-4);
    display: grid;
    gap: var(--space-3);
    box-shadow: 0 12px 32px rgba(0, 0, 0, 0.18);
  }

  .modal-head {
    display: flex;
    justify-content: space-between;
    align-items: center;
  }

  .modal-head h2 {
    margin: 0;
    font-size: var(--ui-size);
    font-weight: 600;
    text-transform: lowercase;
    display: flex;
    align-items: center;
    gap: var(--space-2);
  }

  .close {
    background: transparent;
    border: 1px solid var(--line);
    border-radius: var(--radius);
    padding: var(--space-1) var(--space-2);
    cursor: pointer;
    min-height: 32px;
    font-family: var(--font-mono);
    font-size: var(--ui-size);
    color: var(--ink-soft);
  }

  .close:hover {
    border-color: var(--ink);
    color: var(--ink);
  }

  .help {
    color: var(--ink-soft);
    font-size: calc(var(--ui-size) * 0.9);
    margin: 0;
    line-height: 1.45;
  }

  .hl-stats {
    display: flex;
    align-items: center;
    gap: 6px;
    font-size: calc(var(--ui-size) * 0.85);
    color: var(--ink-soft);
    padding: var(--space-2) var(--space-3);
    background: color-mix(in srgb, var(--ink) 4%, var(--paper));
    border-radius: var(--radius);
    border: 1px solid var(--line);
    flex-wrap: wrap;
  }

  .hl-total {
    font-weight: 600;
    color: var(--ink);
    margin-right: 4px;
  }

  .hl-dot {
    width: 7px;
    height: 7px;
    border-radius: 50%;
    display: inline-block;
  }

  .hl-dot-user {
    background: var(--green);
  }

  .hl-dot-friend {
    background: #b197fc;
  }

  .hl-dot-global {
    background: #ffd43b;
  }

  .hl-list {
    display: flex;
    flex-direction: column;
    gap: var(--space-2);
    max-height: 240px;
    overflow-y: auto;
    padding-right: 4px;
  }

  .hl-item {
    padding: var(--space-2) var(--space-3);
    border-radius: var(--radius);
    border: 1px solid var(--line);
    background: color-mix(in srgb, var(--ink) 3%, var(--paper));
  }

  .hl-item-user {
    border-left: 3px solid var(--green);
  }

  .hl-item-friend {
    border-left: 3px solid #b197fc;
  }

  .hl-item-global {
    border-left: 3px solid #ffd43b;
  }

  .hl-item-top {
    display: flex;
    align-items: center;
    gap: 8px;
    font-size: calc(var(--ui-size) * 0.8);
    color: var(--ink-soft);
    margin-bottom: 4px;
  }

  .hl-badge {
    text-transform: uppercase;
    font-size: calc(var(--ui-size) * 0.7);
    padding: 1px 4px;
    border-radius: 2px;
    letter-spacing: 0.04em;
  }

  .hl-badge-user {
    background: color-mix(in srgb, var(--green) 15%, var(--paper));
    color: var(--ink);
  }

  .hl-badge-friend {
    background: rgba(177, 151, 252, 0.15);
    color: #b197fc;
  }

  .hl-badge-global {
    background: rgba(255, 212, 59, 0.15);
    color: #ffd43b;
  }

  .hl-author {
    flex: 1;
    overflow: hidden;
    text-overflow: ellipsis;
    white-space: nowrap;
  }

  .hl-seek-btn {
    padding: 2px 6px;
    min-height: 24px;
    font-size: calc(var(--ui-size) * 0.78);
    display: inline-flex;
    align-items: center;
    gap: 4px;
  }

  .secondary {
    background: transparent;
    border: 1px solid var(--line);
    border-radius: var(--radius);
    padding: 4px 8px;
    cursor: pointer;
    font-family: var(--font-mono);
    color: var(--ink-soft);
  }

  .secondary:hover {
    border-color: var(--green);
    color: var(--ink);
    background: color-mix(in srgb, var(--green) 8%, var(--paper));
  }

  .hl-quote {
    margin: 0;
    font-size: calc(var(--ui-size) * 0.9);
    color: var(--ink);
    line-height: 1.45;
  }

  .empty-state {
    padding: var(--space-3);
    text-align: center;
    color: var(--ink-soft);
    font-size: calc(var(--ui-size) * 0.88);
    border: 1px dashed var(--line);
    border-radius: var(--radius);
  }

  .guide-card {
    border: 1px solid color-mix(in srgb, var(--green) 22%, var(--line));
    background: color-mix(in srgb, var(--green) 6%, var(--paper));
    border-radius: var(--radius);
    padding: var(--space-3);
    display: grid;
    gap: var(--space-2);
  }

  .guide-title {
    margin: 0;
    font-size: calc(var(--ui-size) * 0.82);
    color: var(--green);
    font-weight: 600;
    display: flex;
    align-items: center;
    gap: 6px;
  }

  .guide-steps {
    margin: 0;
    padding-left: 1.4em;
    font-size: calc(var(--ui-size) * 0.8);
    color: var(--ink-soft);
    line-height: 1.5;
  }

  .guide-steps strong {
    color: var(--ink);
  }

  .actions {
    display: flex;
    justify-content: flex-end;
    gap: var(--space-2);
  }

  .primary {
    background: var(--green);
    color: var(--paper);
    border: 1px solid var(--green);
    border-radius: var(--radius);
    padding: var(--space-2) var(--space-4);
    font-family: var(--font-mono);
    font-size: var(--ui-size);
    cursor: pointer;
    min-height: 38px;
    font-weight: 600;
  }

  .primary:hover {
    background: color-mix(in srgb, var(--green) 85%, var(--ink));
    border-color: var(--green);
    color: var(--paper);
  }
</style>

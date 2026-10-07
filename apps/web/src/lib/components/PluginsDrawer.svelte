<script lang="ts">
  import { onMount } from 'svelte'
  import Icon from './Icon.svelte'

  type PluginKind = 'ingestor' | 'script_engine' | 'tts_engine' | 'audio_filter' | 'distribution'

  interface PluginItem {
    id: string
    kind: PluginKind
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

  let {
    open = false,
    onClose = () => {}
  }: {
    open: boolean
    onClose?: () => void
  } = $props()

  let plugins = $state<PluginItem[]>([])
  let loading = $state(false)
  let error = $state('')
  let toggling = $state<string | null>(null)

  const API_BASE = import.meta.env.VITE_API_BASE ?? ''

  async function load() {
    loading = true
    error = ''
    try {
      const res = await fetch(`${API_BASE}/plugins`)
      if (!res.ok) throw new Error(`HTTP ${res.status}`)
      const data = await res.json() as { plugins: PluginItem[] }
      plugins = data.plugins ?? []
    } catch (e) {
      error = e instanceof Error ? e.message : 'unreachable'
    } finally {
      loading = false
    }
  }

  async function toggle(id: string) {
    if (toggling) return
    toggling = id
    try {
      const res = await fetch(`${API_BASE}/plugins/${encodeURIComponent(id)}/toggle`, { method: 'POST' })
      if (!res.ok) {
        const b = await res.json().catch(() => null) as { detail?: string } | null
        throw new Error(b?.detail ?? `HTTP ${res.status}`)
      }
      const data = await res.json() as { enabled: boolean }
      plugins = plugins.map((p) => p.id === id ? { ...p, enabled: data.enabled } : p)
    } catch (e) {
      error = e instanceof Error ? e.message : 'toggle failed'
    } finally {
      toggling = null
    }
  }

  function kindLabel(k: string): string {
    if (k === 'tts_engine') return 'voice'
    if (k === 'script_engine') return 'script'
    if (k === 'audio_filter') return 'audio'
    return k.replace('_', ' ')
  }

  function kindOrder(a: PluginItem, b: PluginItem): number {
    const order: Record<string, number> = {
      tts_engine: 0,
      script_engine: 1,
      ingestor: 2,
      audio_filter: 3,
      distribution: 4
    }
    return (order[a.kind] ?? 99) - (order[b.kind] ?? 99)
  }

  const grouped = $derived.by(() => {
    const sorted = [...plugins].sort(kindOrder)
    const map = new Map<string, PluginItem[]>()
    for (const p of sorted) {
      const key = p.kind
      const arr = map.get(key)
      if (arr) arr.push(p)
      else map.set(key, [p])
    }
    return Array.from(map.entries())
  })

  let panelEl = $state<HTMLElement | null>(null)
  let closeBtnEl = $state<HTMLButtonElement | null>(null)

  $effect(() => {
    if (open) {
      void load()
      queueMicrotask(() => closeBtnEl?.focus())
      document.body.style.overflow = 'hidden'
    } else {
      document.body.style.overflow = ''
    }
  })

  onMount(() => {
    return () => { document.body.style.overflow = '' }
  })

  function handleBackdrop(e: MouseEvent) {
    if (e.target === e.currentTarget) onClose()
  }

  function handleKeydown(e: KeyboardEvent) {
    if (!open) return
    if (e.key === 'Escape') {
      e.preventDefault()
      onClose()
    }
    if (e.key === 'Tab' && panelEl) {
      const focusable = panelEl.querySelectorAll<HTMLElement>(
        'button, [href], input, select, textarea, [tabindex]:not([tabindex="-1"])'
      )
      if (focusable.length === 0) return
      const first = focusable[0]!
      const last = focusable[focusable.length - 1]!
      if (e.shiftKey && document.activeElement === first) {
        e.preventDefault()
        last.focus()
      } else if (!e.shiftKey && document.activeElement === last) {
        e.preventDefault()
        first.focus()
      }
    }
  }
</script>

{#if open}
  <!-- svelte-ignore a11y_click_events_have_key_events -->
  <!-- svelte-ignore a11y_no_static_element_interactions -->
  <div
    class="drawer-overlay"
    onclick={handleBackdrop}
    onkeydown={handleKeydown}
    role="presentation"
  >
    <div
      class="drawer-backdrop"
      aria-hidden="true"
    ></div>
    <div
      bind:this={panelEl}
      class="drawer-panel"
      role="dialog"
      aria-modal="true"
      aria-label="Plugin settings"
      aria-describedby="drawer-desc"
    >
      <header class="drawer-head">
        <div class="drawer-title-wrap">
          <h2 id="drawer-title" class="mono drawer-title"><Icon name="sliders" size={16} /> plugins</h2>
          <p id="drawer-desc" class="mono drawer-desc">runtime toggle for pipeline modules. changes save instantly.</p>
        </div>
        <button
          bind:this={closeBtnEl}
          type="button"
          class="mono drawer-close"
          onclick={onClose}
          aria-label="Close plugin settings"
        >
          <Icon name="close" size={14} /> close
        </button>
      </header>

      {#if loading}
        <p class="mono drawer-note" role="status" aria-live="polite">// loading plugins</p>
      {:else if error}
        <p class="mono drawer-error" role="alert">// {error}</p>
        <button type="button" class="mono drawer-retry" onclick={load}>retry</button>
      {:else if plugins.length === 0}
        <p class="mono drawer-note">// no plugins discovered</p>
      {:else}
        <div class="drawer-body">
          {#each grouped as [kind, items] (kind)}
            <section class="drawer-group" aria-labelledby={`group-${kind}`}>
              <h3 id={`group-${kind}`} class="mono group-h">
                <span class="group-kind">{kindLabel(kind)}</span>
                <span class="group-count">{items.length}</span>
              </h3>
              <ul class="plugin-list" role="list">
                {#each items as p (p.id)}
                  <li class="plugin-row">
                    <div class="plugin-main">
                      <div class="plugin-head">
                        <span class="mono plugin-id">{p.id}</span>
                        {#if p.ui_badge}
                          <span class="mono plugin-badge">{p.ui_badge}</span>
                        {/if}
                        <span class="probe-dot" class:ok={p.healthy} class:off={!p.healthy} title={p.healthy ? 'healthy' : p.ui_fix_hint || 'unhealthy'} aria-label={p.healthy ? 'healthy' : 'unhealthy'}></span>
                        <span class="mono probe-label">{p.healthy ? 'healthy' : 'offline'}</span>
                      </div>
                      <span class="mono plugin-label">{p.label}</span>
                      <span class="mono plugin-meta">{p.kind} · v{p.version} · {p.permissions.join(', ') || 'no permissions'}</span>
                      {#if !p.healthy && p.ui_fix_hint}
                        <span class="mono plugin-hint">{p.ui_fix_hint}</span>
                      {/if}
                    </div>
                    <button
                      type="button"
                      role="switch"
                      aria-checked={p.enabled}
                      aria-label={`Toggle ${p.id} ${p.enabled ? 'enabled' : 'disabled'}`}
                      class="plugin-switch"
                      class:enabled={p.enabled}
                      class:busy={toggling === p.id}
                      disabled={toggling === p.id}
                      onclick={() => void toggle(p.id)}
                    >
                      <span class="switch-thumb"></span>
                    </button>
                  </li>
                {/each}
              </ul>
            </section>
          {/each}
        </div>
        <footer class="drawer-foot mono">
          <span>{plugins.filter((p) => p.enabled).length} of {plugins.length} enabled</span>
          <span class="foot-hint">toggle updates data/config.json</span>
        </footer>
      {/if}
    </div>
  </div>
{/if}

<style>
  .drawer-overlay {
    position: fixed;
    inset: 0;
    z-index: 40;
    display: flex;
    justify-content: flex-end;
  }

  .drawer-backdrop {
    position: absolute;
    inset: 0;
    background: rgba(26, 24, 21, 0.32);
    backdrop-filter: blur(2px);
  }

  .drawer-panel {
    position: relative;
    width: min(420px, 100vw);
    max-width: 100%;
    height: 100%;
    background: var(--paper);
    border-left: 1px solid var(--line);
    box-shadow: -8px 0 24px rgba(0, 0, 0, 0.12);
    display: flex;
    flex-direction: column;
    overflow: hidden;
    animation: drawerIn 200ms ease-out;
  }

  @keyframes drawerIn {
    from { transform: translateX(100%); }
    to { transform: translateX(0); }
  }

  @media (prefers-reduced-motion: reduce) {
    .drawer-panel { animation: none; }
  }

  .drawer-head {
    display: flex;
    align-items: flex-start;
    justify-content: space-between;
    gap: var(--space-3);
    padding: var(--space-4);
    border-bottom: 1px solid var(--line);
    flex-shrink: 0;
  }

  .drawer-title-wrap {
    display: flex;
    flex-direction: column;
    gap: 4px;
    min-width: 0;
  }

  .drawer-title {
    margin: 0;
    font-size: var(--ui-size);
    color: var(--ink);
    display: inline-flex;
    align-items: center;
    gap: var(--space-2);
    text-transform: lowercase;
    letter-spacing: 0.04em;
  }

  .drawer-desc {
    margin: 0;
    font-size: calc(var(--ui-size) * 0.85);
    color: var(--ink-soft);
    line-height: 1.4;
  }

  .drawer-close {
    flex-shrink: 0;
    display: inline-flex;
    align-items: center;
    gap: 6px;
    background: transparent;
    border: 1px solid var(--line);
    border-radius: var(--radius);
    color: var(--ink-soft);
    padding: 6px 10px;
    cursor: pointer;
    min-height: 36px;
  }

  .drawer-close:hover {
    border-color: var(--ink);
    color: var(--ink);
  }

  .drawer-close:focus-visible {
    outline: 2px solid var(--green);
    outline-offset: 2px;
  }

  .drawer-body {
    flex: 1;
    overflow-y: auto;
    padding: var(--space-4);
    display: flex;
    flex-direction: column;
    gap: var(--space-5);
  }

  .drawer-note {
    padding: var(--space-4);
    color: var(--ink-soft);
  }

  .drawer-error {
    padding: var(--space-3) var(--space-4);
    color: var(--danger);
  }

  .drawer-retry {
    margin: 0 var(--space-4);
    align-self: flex-start;
    background: transparent;
    border: 1px solid var(--line);
    border-radius: var(--radius);
    color: var(--ink-soft);
    padding: 6px 12px;
    cursor: pointer;
  }

  .drawer-retry:hover {
    border-color: var(--ink);
    color: var(--ink);
  }

  .drawer-group {
    display: flex;
    flex-direction: column;
    gap: var(--space-3);
  }

  .group-h {
    margin: 0;
    display: flex;
    align-items: center;
    gap: var(--space-2);
    font-size: calc(var(--ui-size) * 0.85);
    color: var(--ink-soft);
    text-transform: uppercase;
    letter-spacing: 0.08em;
    border-bottom: 1px solid var(--line);
    padding-bottom: var(--space-2);
  }

  .group-kind { color: var(--ink); }
  .group-count {
    margin-left: auto;
    font-size: calc(var(--ui-size) * 0.8);
    color: var(--ink-soft);
    background: color-mix(in srgb, var(--ink) 6%, var(--paper));
    border: 1px solid var(--line);
    border-radius: var(--radius);
    padding: 1px 7px;
  }

  .plugin-list {
    list-style: none;
    margin: 0;
    padding: 0;
    display: flex;
    flex-direction: column;
    gap: var(--space-2);
  }

  .plugin-row {
    display: flex;
    align-items: center;
    gap: var(--space-3);
    padding: var(--space-3);
    border: 1px solid var(--line);
    border-radius: var(--radius);
    background: color-mix(in srgb, var(--paper) 96%, var(--ink));
  }

  .plugin-main {
    flex: 1;
    min-width: 0;
    display: flex;
    flex-direction: column;
    gap: 2px;
  }

  .plugin-head {
    display: flex;
    align-items: center;
    gap: 6px;
    flex-wrap: wrap;
  }

  .plugin-id {
    color: var(--ink);
    font-size: calc(var(--ui-size) * 0.92);
    font-weight: 600;
  }

  .plugin-badge {
    font-size: calc(var(--ui-size) * 0.72);
    color: var(--green);
    background: color-mix(in srgb, var(--green) 10%, var(--paper));
    border: 1px solid color-mix(in srgb, var(--green) 25%, var(--line));
    border-radius: var(--radius);
    padding: 1px 6px;
    letter-spacing: 0.02em;
  }

  .probe-dot {
    width: 8px;
    height: 8px;
    border-radius: 50%;
    flex-shrink: 0;
    border: 1px solid var(--line);
  }
  .probe-dot.ok { background: var(--green); border-color: var(--green); }
  .probe-dot.off { background: var(--ink-soft); opacity: 0.5; }

  .probe-label {
    font-size: calc(var(--ui-size) * 0.75);
    color: var(--ink-soft);
  }

  .plugin-label {
    color: var(--ink-soft);
    font-size: calc(var(--ui-size) * 0.88);
    line-height: 1.35;
  }

  .plugin-meta {
    color: var(--ink-soft);
    font-size: calc(var(--ui-size) * 0.75);
    opacity: 0.85;
  }

  .plugin-hint {
    color: var(--ink-soft);
    font-size: calc(var(--ui-size) * 0.75);
    background: color-mix(in srgb, var(--ink) 4%, var(--paper));
    border-left: 2px solid var(--line);
    padding: 2px 6px;
    margin-top: 2px;
  }

  .plugin-switch {
    flex-shrink: 0;
    width: 42px;
    height: 24px;
    border-radius: var(--radius);
    border: 1.5px solid var(--line);
    background: color-mix(in srgb, var(--ink) 8%, var(--paper));
    cursor: pointer;
    position: relative;
    transition: background 120ms ease-out, border-color 120ms ease-out;
    padding: 0;
  }

  .plugin-switch:hover {
    border-color: var(--ink-soft);
  }

  .plugin-switch:focus-visible {
    outline: 2px solid var(--green);
    outline-offset: 2px;
  }

  .plugin-switch.enabled {
    background: var(--green);
    border-color: var(--green);
  }

  .plugin-switch.busy { opacity: 0.6; cursor: wait; }

  .switch-thumb {
    position: absolute;
    top: 2px;
    left: 2px;
    width: 16px;
    height: 16px;
    border-radius: 50%;
    background: var(--paper);
    box-shadow: 0 1px 3px rgba(0, 0, 0, 0.2);
    transition: transform 120ms ease-out;
  }

  .plugin-switch.enabled .switch-thumb {
    transform: translateX(18px);
  }

  .drawer-foot {
    flex-shrink: 0;
    display: flex;
    justify-content: space-between;
    align-items: center;
    gap: var(--space-2);
    padding: var(--space-3) var(--space-4);
    border-top: 1px solid var(--line);
    font-size: calc(var(--ui-size) * 0.8);
    color: var(--ink-soft);
    background: color-mix(in srgb, var(--ink) 3%, var(--paper));
  }

  .foot-hint {
    opacity: 0.8;
    font-size: calc(var(--ui-size) * 0.75);
  }

  @media (max-width: 480px) {
    .drawer-panel { width: 100vw; }
  }
</style>

<script lang="ts">
  // Shows when a newer Vozonda release exists (GET /update-check, which asks GitHub at most every six hours).
  // Updating is a command the operator runs; a button that updates the install itself would need control
  // over Docker, which means root on the host. Hidden per version once dismissed; "stop checking" sets
  // the setting update.check to "0".
  import { onMount } from 'svelte'
  import { saveSetting } from '../api'

  interface UpdateInfo {
    current: string
    available: boolean
    latest?: string
    security?: boolean
    url?: string
    command?: string
  }

  const DISMISS_KEY = 'vozonda.updateDismissed'
  let info = $state<UpdateInfo | null>(null)
  let copied = $state(false)
  let codeEl: HTMLElement | undefined = $state()

  onMount(async () => {
    try {
      const res = await fetch('/update-check', { cache: 'no-store' })
      if (!res.ok) return
      const data: UpdateInfo = await res.json()
      let dismissed = ''
      try { dismissed = localStorage.getItem(DISMISS_KEY) || '' } catch {}
      if (data.available && data.latest !== dismissed) info = data
    } catch {
      /* offline or API down: no banner */
    }
  })

  function dismiss() {
    try { if (info?.latest) localStorage.setItem(DISMISS_KEY, info.latest) } catch {}
    info = null
  }

  async function stopChecking() {
    try {
      await saveSetting('update.check', '0')
      info = null
    } catch {
      dismiss() // not saved (e.g. signed out): at least hide it until the next version
    }
  }

  async function copy() {
    if (!info?.command) return
    try {
      await navigator.clipboard.writeText(info.command)
      copied = true
      setTimeout(() => (copied = false), 2000)
    } catch {
      // no clipboard on plain http from another machine: select the text instead
      if (codeEl) {
        const range = document.createRange()
        range.selectNodeContents(codeEl)
        const sel = window.getSelection()
        sel?.removeAllRanges()
        sel?.addRange(range)
      }
    }
  }
</script>

{#if info}
  <aside class="update" class:security={info.security} aria-live="polite">
    <p class="head">
      <strong>Update available: v{info.latest}{info.security ? ' (security)' : ''}</strong>
      <span class="cur">you run v{info.current}</span>
    </p>
    <p class="how">In the folder you installed Vozonda in, run:</p>
    <div class="cmd">
      <code bind:this={codeEl}>{info.command}</code>
      <button type="button" onclick={copy}>{copied ? 'copied' : 'copy'}</button>
    </div>
    <p class="links">
      {#if info.url}<a href={info.url} target="_blank" rel="noopener noreferrer">what changed</a> · {/if}
      <button type="button" class="link" onclick={dismiss}>hide until the next version</button> ·
      <button type="button" class="link" onclick={stopChecking}>stop checking</button>
    </p>
  </aside>
{/if}

<style>
  .update {
    position: fixed; left: 50%; bottom: var(--space-4); transform: translateX(-50%); z-index: 900;
    width: min(560px, calc(100% - 2 * var(--space-4))); padding: var(--space-3) var(--space-4);
    display: grid; gap: var(--space-2); color: var(--ink); background: var(--paper);
    border: 1px solid var(--line); border-left: 4px solid var(--green); border-radius: var(--radius);
    box-shadow: 0 6px 24px rgb(0 0 0 / 0.12);
  }
  .update.security { border-left-color: var(--red, #b42318); }
  p { margin: 0; }
  .head { display: flex; flex-wrap: wrap; gap: var(--space-2); align-items: baseline; }
  .cur, .how, .links { color: var(--ink-soft); font-size: 0.9em; }
  .cmd { display: flex; gap: var(--space-2); align-items: stretch; min-width: 0; }
  code {
    flex: 1; min-width: 0; overflow-wrap: anywhere; user-select: all; padding: var(--space-2) var(--space-3);
    font: var(--ui-size) var(--font-mono); background: color-mix(in srgb, var(--ink) 6%, var(--paper));
    border: 1px solid var(--line); border-radius: var(--radius);
  }
  .cmd button {
    font: 600 var(--ui-size) var(--font-mono); padding: 0 var(--space-3); color: var(--paper);
    background: var(--ink); border: 0; border-radius: var(--radius); cursor: pointer;
  }
  .link {
    font: inherit; color: inherit; background: none; border: 0; padding: 0; text-decoration: underline;
    cursor: pointer;
  }
  a { color: inherit; }
</style>

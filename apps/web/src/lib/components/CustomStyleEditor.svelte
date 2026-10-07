<script lang="ts">
  import { tick } from 'svelte'
  import {
    createCustomStyle,
    updateCustomStyle,
    type CustomStyle
  } from '../api'

  let {
    editing = null,
    onclose,
    onsaved
  }: {
    editing: CustomStyle | null
    onclose: () => void
    onsaved: () => void
  } = $props()

  const RHYTHM_TYPES: { id: string; label: string; desc: string }[] = [
    { id: 'peer', label: 'peer', desc: 'equal conversation, both hosts argue and answer each other.' },
    { id: 'host_expert', label: 'host expert', desc: 'curious host asks, expert guest explains.' },
    { id: 'narrator_listener', label: 'narrator listener', desc: 'one host narrates the story, the other reacts and guesses.' },
    { id: 'interrogator', label: 'interrogator', desc: 'one host asks only questions, the other answers shrink over time.' },
    { id: 'calm', label: 'calm', desc: 'slow guided turns, no turn longer than twenty-five words.' }
  ]

  let name = $state('')
  let doc = $state('')
  let roleA = $state('')
  let roleB = $state('')
  let tone = $state('')
  let rhythm = $state('peer')
  let formError = $state('')
  let busy = $state(false)
  let nameEl: HTMLInputElement | null = $state(null)

  $effect(() => {
    name = editing?.name ?? ''
    doc = editing?.doc ?? ''
    roleA = editing?.role_a ?? ''
    roleB = editing?.role_b ?? ''
    tone = editing?.tone ?? ''
    rhythm = editing?.rhythm_type ?? 'peer'
  })

  $effect(() => {
    void tick().then(() => nameEl?.focus())
  })

  function handleRhythmKeydown(e: KeyboardEvent) {
    const ids = RHYTHM_TYPES.map((r) => r.id)
    const idx = ids.indexOf(rhythm)
    let next: number
    switch (e.key) {
      case 'ArrowRight':
      case 'ArrowDown':
        next = (idx + 1) % ids.length
        break
      case 'ArrowLeft':
      case 'ArrowUp':
        next = (idx - 1 + ids.length) % ids.length
        break
      case 'Home':
        next = 0
        break
      case 'End':
        next = ids.length - 1
        break
      default:
        return
    }
    const target = ids[next]
    if (target) {
      e.preventDefault()
      rhythm = target
    }
  }

  function slugify(v: string): string {
    const slug = v.toLowerCase().replace(/[^a-z0-9]+/g, '_').replace(/^_+|_+$/g, '').slice(0, 30)
    return slug.length >= 2 ? slug : 'style'
  }

  async function save() {
    formError = ''
    if (!name.trim()) {
      formError = 'name is required'
      return
    }
    if (!roleA.trim()) {
      formError = 'host A role is required'
      return
    }
    if (!roleB.trim()) {
      formError = 'host B role is required'
      return
    }
    if (!RHYTHM_TYPES.some((r) => r.id === rhythm)) {
      formError = 'pick a rhythm type'
      return
    }
    busy = true
    try {
      if (editing) {
        await updateCustomStyle(editing.id, {
          name: name.trim(),
          doc: doc.trim(),
          role_a: roleA.trim(),
          role_b: roleB.trim(),
          tone: tone.trim(),
          rhythm_type: rhythm
        })
      } else {
        await createCustomStyle({
          id: `custom_${slugify(name)}`,
          name: name.trim(),
          doc: doc.trim(),
          role_a: roleA.trim(),
          role_b: roleB.trim(),
          tone: tone.trim(),
          rhythm_type: rhythm
        })
      }
      onsaved()
    } catch (err) {
      formError = err instanceof Error ? err.message.toLowerCase() : 'could not save the style'
    } finally {
      busy = false
    }
  }
</script>

<div
  class="editor"
  role="dialog"
  aria-modal="false"
  aria-label={editing ? `edit style ${editing.name}` : 'new custom style'}
  tabindex="-1"
  onkeydown={(e) => { if (e.key === 'Escape') onclose() }}
>
  <div class="opt">
    <label class="lab mono" for="cs-name">name</label>
    <input
      id="cs-name"
      class="mono text-in"
      type="text"
      maxlength="40"
      placeholder="my evening debate"
      bind:this={nameEl}
      bind:value={name}
      disabled={busy}
      aria-label="style name"
    />
    <p class="help">max 40 characters. the id becomes custom_slug from this name.</p>
  </div>
  <div class="opt">
    <label class="lab mono" for="cs-doc">one-line description</label>
    <input
      id="cs-doc"
      class="mono text-in"
      type="text"
      maxlength="120"
      placeholder="two friends argue gently about the news"
      bind:value={doc}
      disabled={busy}
      aria-label="one-line description"
    />
    <p class="help">max 120 characters. shown under the style in the picker.</p>
  </div>
  <div class="opt">
    <label class="lab mono" for="cs-role-a">host A role</label>
    <textarea
      id="cs-role-a"
      class="mono text-in role-ta"
      rows="3"
      maxlength="400"
      spellcheck="false"
      placeholder="a curious host who asks short questions"
      bind:value={roleA}
      disabled={busy}
      aria-label="host A role"
    ></textarea>
    <p class="help">max 400 characters. who host A is and how they talk.</p>
  </div>
  <div class="opt">
    <label class="lab mono" for="cs-role-b">host B role</label>
    <textarea
      id="cs-role-b"
      class="mono text-in role-ta"
      rows="3"
      maxlength="400"
      spellcheck="false"
      placeholder="an expert guest who explains with examples"
      bind:value={roleB}
      disabled={busy}
      aria-label="host B role"
    ></textarea>
    <p class="help">max 400 characters. who host B is and how they answer.</p>
  </div>
  <div class="opt">
    <label class="lab mono" for="cs-tone">tone</label>
    <input
      id="cs-tone"
      class="mono text-in"
      type="text"
      maxlength="300"
      placeholder="warm, a little witty, never snarky"
      bind:value={tone}
      disabled={busy}
      aria-label="tone"
    />
    <p class="help">max 300 characters. optional overall tone.</p>
  </div>
  <div class="opt">
    <span class="lab mono" id="cs-rhythm-lab">rhythm type</span>
    <div class="seg seg-wrap" role="radiogroup" aria-labelledby="cs-rhythm-lab" tabindex="0" onkeydown={handleRhythmKeydown}>
      {#each RHYTHM_TYPES as r (r.id)}
        <button
          type="button"
          role="radio"
          aria-checked={rhythm === r.id}
          class:sel={rhythm === r.id}
          disabled={busy}
          onclick={() => (rhythm = r.id)}
          aria-label={`rhythm ${r.id}`}
        >{r.label}</button>
      {/each}
    </div>
    <p class="help">{RHYTHM_TYPES.find((r) => r.id === rhythm)?.desc ?? ''}</p>
    <ul class="rhythm-list mono" aria-label="rhythm types">
      {#each RHYTHM_TYPES as r (r.id)}
        <li class:sel={rhythm === r.id}><span class="rhythm-id">{r.id}</span><span class="rhythm-desc">{r.desc}</span></li>
      {/each}
    </ul>
  </div>
  {#if formError}
    <p class="mono help err" role="alert">{formError}</p>
  {/if}
  <div class="editor-actions">
    <button type="button" class="save-btn mono" disabled={busy} onclick={() => void save()}>
      {busy ? 'saving...' : editing ? 'save changes' : 'create style'}
    </button>
    <button type="button" class="link mono" disabled={busy} onclick={onclose}>cancel</button>
  </div>
</div>

<style>
  .editor {
    display: grid;
    gap: var(--space-3);
    padding: var(--space-3);
    border: 1px solid var(--line);
    border-radius: var(--radius);
    background: color-mix(in srgb, var(--ink) 3%, var(--paper));
  }
  .editor:focus-visible {
    outline: 2px solid var(--green);
    outline-offset: 2px;
  }
  .opt {
    display: grid;
    gap: var(--space-2);
    padding: var(--space-1) 0;
  }
  .lab {
    font-size: var(--ui-size);
    color: var(--ink);
    font-weight: 600;
  }
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
  }
  .text-in:hover {
    border-color: var(--ink-soft);
  }
  .text-in:focus-visible {
    outline: 2px solid var(--green);
    outline-offset: 2px;
  }
  .role-ta {
    resize: vertical;
    line-height: 1.5;
  }
  .help {
    color: var(--ink-soft);
    font-size: var(--ui-size);
    line-height: 1.45;
    margin: 0;
  }
  .err {
    color: var(--danger);
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
    transition: background var(--dur-fast) ease-out, color var(--dur-fast) ease-out;
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
    font-weight: 600;
  }
  .seg button.sel:hover,
  .seg button[aria-checked="true"]:hover {
    background: color-mix(in srgb, var(--green) 90%, var(--ink));
    color: var(--paper);
  }
  .seg-wrap {
    display: grid;
    grid-template-columns: repeat(auto-fill, minmax(7.5em, 1fr));
    gap: var(--space-2);
    border: none;
    overflow: visible;
    width: 100%;
  }
  .seg-wrap button {
    border: 1px solid var(--line);
    border-radius: var(--radius);
    text-align: center;
  }
  .rhythm-list {
    list-style: none;
    margin: 0;
    padding: 0;
    display: grid;
    gap: var(--space-1);
  }
  .rhythm-list li {
    display: flex;
    gap: var(--space-2);
    font-size: var(--ui-size);
    color: var(--ink-soft);
  }
  .rhythm-list li.sel {
    color: var(--ink);
  }
  .rhythm-id {
    min-width: 9rem;
    font-weight: 600;
  }
  .rhythm-desc {
    flex: 1;
  }
  .editor-actions {
    display: flex;
    flex-wrap: wrap;
    align-items: center;
    gap: var(--space-3);
  }
  .save-btn {
    background: color-mix(in srgb, var(--green) 12%, var(--paper));
    border: 1px solid var(--green);
    border-radius: var(--radius);
    color: var(--ink);
    padding: var(--space-2) var(--space-3);
    min-height: 44px;
    font-size: var(--ui-size);
    font-weight: 600;
    cursor: pointer;
  }
  .save-btn:hover:not(:disabled) {
    background: color-mix(in srgb, var(--green) 20%, var(--paper));
  }
  .save-btn:disabled {
    opacity: 0.5;
    cursor: not-allowed;
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
  .link:hover {
    color: var(--green);
  }
  .link:focus-visible,
  .save-btn:focus-visible,
  .seg button:focus-visible {
    outline: 2px solid var(--green);
    outline-offset: 2px;
  }
</style>

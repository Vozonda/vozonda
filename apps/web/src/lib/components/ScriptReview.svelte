<script lang="ts">
  // UX phase 2: a script paused for review. Every turn is editable; clearing a
  // turn drops it; nothing is voiced until "voice it". Only an edited script is
  // sent back, an unchanged one is approved as is.
  import Icon from './Icon.svelte'
  import type { DialogueLine } from '../api'

  let {
    script,
    names = {},
    busy = false,
    title = '',
    onApprove
  }: {
    script: DialogueLine[]
    // speaker letter -> voice name shown in the compose summary ('A' -> 'Ryan')
    names?: Record<string, string>
    busy?: boolean
    title?: string
    onApprove: (lines: { speaker: string; text: string }[] | undefined, title?: string) => void
  } = $props()

  // plain snapshot of the stored script: the editable draft starts from it
  const original = script.map((l) => ({ speaker: l.speaker, text: l.text, name: l.name, src: l.src }))
  let draft = $state(original.map((l) => ({ ...l })))

  const kept = $derived(draft.filter((l) => l.text.trim()))
  const words = $derived(kept.reduce((n, l) => n + l.text.trim().split(/\s+/).length, 0))
  const minutes = $derived(Math.max(1, Math.round(words / 150)))
  const edited = $derived(
    kept.length !== original.length || kept.some((l, i) => l.text.trim() !== original[i]?.text.trim())
  )

  let titleDraft = $state(title.trim())
  const titleEdited = $derived(titleDraft !== title.trim())

  function who(l: { speaker: string; name?: string }): string {
    if (l.name) return l.name
    if (names[l.speaker]) return names[l.speaker]!
    return l.speaker === 'Narrator' ? 'narrator' : `host ${l.speaker.toLowerCase()}`
  }

  function approve() {
    onApprove(
      edited ? kept.map((l) => ({ speaker: l.speaker, text: l.text.trim(), src: l.src })) : undefined,
      titleEdited ? titleDraft : undefined
    )
  }
</script>

<section class="ess review" aria-labelledby="review-h">
  <h2 id="review-h" class="mono ess-h"><Icon name="prompts" size={18} /> script ready</h2>
  <p class="mono help">read it, change anything, then voice it. nothing is voiced before that. clear a line to drop it.</p>

  <label class="title-label mono" for="rv-title">title</label>
  <input id="rv-title" class="title" type="text" maxlength="120" bind:value={titleDraft} disabled={busy} aria-label="Episode title" />

  <ol class="lines">
    {#each draft as line, i (i)}
      <li class="line spk-{line.speaker.toLowerCase()}">
        <div class="speaker-col">
          <label class="who mono" for="rv-{i}">{who(line)}</label>
          {#if line.src && line.src.length > 0}
            <span class="src-citations mono" title="Sources: {line.src.map((s) => `[${s}]`).join(' ')}">
              {#each line.src as s}
                <span class="src-badge">[{s}]</span>
              {/each}
            </span>
          {/if}
        </div>
        <textarea id="rv-{i}" class="text" rows={Math.max(2, Math.ceil(line.text.length / 90))}
          bind:value={line.text} disabled={busy}></textarea>
      </li>
    {/each}
  </ol>

  <div class="footer">
    <span class="mono meta">{kept.length} turns · {words} words · about {minutes} min{edited ? ' · edited' : ''}{titleEdited ? ' · title edited' : ''}</span>
    <button type="button" class="go mono" onclick={approve} disabled={busy || kept.length === 0}>
      <Icon name="playtri" size={14} /> {busy ? 'starting…' : 'voice it'}
    </button>
  </div>
</section>

<style>
  .ess {
    border: 1px solid var(--line);
    border-radius: var(--radius);
    padding: var(--space-5);
    display: grid;
    gap: var(--space-4);
    min-width: 0;
    margin-top: var(--space-4);
    background: color-mix(in srgb, var(--paper) 4%, transparent);
  }

  .ess-h {
    display: flex;
    align-items: center;
    gap: var(--space-2);
    font-size: var(--ui-size);
    color: var(--ink);
    text-transform: lowercase;
    letter-spacing: 0.04em;
    margin: 0;
  }

  .help {
    color: var(--ink-soft);
    font-size: calc(var(--ui-size) * 0.85);
    margin: 0;
  }

  .lines {
    list-style: none;
    margin: 0;
    padding: 0;
    display: grid;
    gap: var(--space-3);
  }

  .line {
    display: grid;
    grid-template-columns: 7rem minmax(0, 1fr);
    gap: var(--space-3);
    align-items: start;
  }

  .speaker-col {
    display: flex;
    flex-direction: column;
    gap: 4px;
    padding-top: var(--space-2);
  }

  .src-citations {
    display: inline-flex;
    flex-wrap: wrap;
    gap: 3px;
  }

  .src-badge {
    font-size: 0.72rem;
    padding: 1px 4px;
    border: 1px solid var(--line);
    border-radius: var(--radius);
    color: var(--green);
    background: color-mix(in srgb, var(--green) 8%, var(--paper));
    font-weight: 500;
    line-height: 1.2;
  }

  .who {
    font-size: calc(var(--ui-size) * 0.85);
    font-weight: 600;
    color: var(--ink-soft);
    overflow-wrap: anywhere;
  }

  .spk-a .who { color: var(--voice-a); }
  .spk-b .who { color: var(--voice-b); }
  .spk-c .who { color: var(--style-learn); }

  .text {
    width: 100%;
    min-width: 0;
    resize: vertical;
    field-sizing: content;
    padding: var(--space-2) var(--space-3);
    background: var(--paper);
    color: var(--ink);
    border: 1px solid var(--line);
    border-radius: var(--radius);
    font-family: var(--font-serif);
    font-size: 1rem;
    line-height: 1.5;
  }

  .text:focus-visible {
    outline: 2px solid var(--green);
    outline-offset: 2px;
  }

  .footer {
    display: flex;
    flex-wrap: wrap;
    align-items: center;
    justify-content: space-between;
    gap: var(--space-3);
    border-top: 1px dashed var(--line);
    padding-top: var(--space-4);
  }

  .meta {
    color: var(--ink-soft);
    font-size: calc(var(--ui-size) * 0.85);
  }

  .title-label {
    font-size: calc(var(--ui-size) * 0.85);
    font-weight: 600;
    color: var(--ink-soft);
    text-transform: lowercase;
    letter-spacing: 0.04em;
  }

  .title {
    width: 100%;
    min-width: 0;
    padding: var(--space-2) var(--space-3);
    background: var(--paper);
    color: var(--ink);
    border: 1px solid var(--line);
    border-radius: var(--radius);
    font-family: var(--font-serif);
    font-size: 1rem;
    line-height: 1.5;
  }

  .title:focus-visible {
    outline: 2px solid var(--green);
    outline-offset: 2px;
  }

  .title:disabled {
    opacity: 0.5;
    cursor: default;
  }

  .go {
    display: inline-flex;
    align-items: center;
    gap: var(--space-2);
    min-height: 44px;
    padding: 0 var(--space-4);
    background: var(--green);
    color: var(--paper);
    border: none;
    border-radius: var(--radius);
    font-weight: 600;
    cursor: pointer;
  }

  .go:disabled {
    opacity: 0.5;
    cursor: default;
  }

  .go:focus-visible {
    outline: 2px solid var(--green);
    outline-offset: 2px;
  }

  @media (max-width: 620px) {
    .ess {
      padding: var(--space-4);
    }

    .line {
      grid-template-columns: 1fr;
      gap: var(--space-1);
    }

    .who {
      padding-top: 0;
    }

    .go {
      flex: 1 1 100%;
      justify-content: center;
    }
  }
</style>

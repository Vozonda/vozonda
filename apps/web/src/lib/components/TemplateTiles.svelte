<script lang="ts">
  import Icon from './Icon.svelte'

  import { TEMPLATES, type TemplateItem, type TemplateValues } from '../shows'

  let { onPick, activeEngine = 'qwen_tts' }: { onPick: (values: TemplateValues) => void; activeEngine?: string } = $props()

  // summary = intuitive at-a-glance overview on tile
  // details = precise technical specs in active footnote

  let picked = $state('')
  let activeTemplate = $state<TemplateItem | null>(null)
  let playingTeaser = $state<string | null>(null)
  let audioEl: HTMLAudioElement | null = null

  function stopTeaser() {
    if (audioEl) {
      audioEl.pause()
      audioEl.currentTime = 0
      audioEl = null
    }
    playingTeaser = null
  }

  function toggleTeaser(e: MouseEvent, t: TemplateItem) {
    e.stopPropagation()
    if (playingTeaser === t.id) {
      stopTeaser()
      return
    }
    stopTeaser()
    playingTeaser = t.id
    audioEl = new Audio(`/media/samples/templates/${t.id}.mp3`)
    audioEl.onended = () => {
      playingTeaser = null
      audioEl = null
    }
    audioEl.onerror = () => {
      playingTeaser = null
      audioEl = null
    }
    audioEl.play().catch(() => {
      playingTeaser = null
      audioEl = null
    })
  }

  $effect(() => {
    return () => {
      stopTeaser()
    }
  })

  function pick(t: TemplateItem) {
    stopTeaser()
    const normEngine = (activeEngine === 'voxtral' ? 'voxtral' : activeEngine === 'piper' ? 'piper' : activeEngine === 'kokoro' ? 'kokoro' : 'qwen_tts') as 'qwen_tts' | 'voxtral' | 'piper' | 'kokoro'
    const resolvedVoices = t.engineVoices ? t.engineVoices[normEngine] : t.values.voices
    onPick({ ...t.values, voices: resolvedVoices })
    picked = t.label
    activeTemplate = t
    setTimeout(() => (picked = ''), 600)
  }
</script>

<div class="template-tiles" role="group" aria-label="Templates">
  {#each TEMPLATES as t (t.label)}
    <div
      class="template-tile mono"
      class:picked={picked === t.label}>
      <button
        type="button"
        class="tt-pick-btn mono"
        onclick={() => pick(t)}
        aria-label="template {t.label}: {t.summary}">
        <div class="tt-header">
          <span class="tt-icon"><Icon name={t.icon} size={21} /></span>
          <span class="tt-name">{t.label}</span>
        </div>
        <span class="tt-context">{t.summary}</span>
      </button>
      <div class="tt-footer">
        <button
          type="button"
          class="teaser-btn mono"
          class:active={playingTeaser === t.id}
          onclick={(e) => toggleTeaser(e, t)}
          aria-label="play teaser for {t.label}">
          <Icon name={playingTeaser === t.id ? 'pausebars' : 'playtri'} size={12} />
          <span>{playingTeaser === t.id ? 'stop' : t.teaserTitle}</span>
        </button>
      </div>
    </div>
  {/each}
</div>



{#if activeTemplate}
  {#key activeTemplate.label}
    <div class="template-footnote mono" role="status" aria-live="polite">
      <span class="tf-icon"><Icon name={activeTemplate.icon} size={21} /></span>
      <span class="tf-label">{activeTemplate.label}</span>
      <span
        class="tf-badge badge-{activeTemplate.engineName}"
        title="Optimized for {activeTemplate.engineName}, fully compatible with all installed engines">
        <Icon name="engine" size={15} />
        <span>{activeTemplate.engineName === 'kokoro' ? 'kokoro' : `best on ${activeTemplate.engineName}`}</span>
      </span>
      <span class="tf-compat">(runs on any engine)</span>
      <span class="tf-sep">·</span>
      <span class="tf-context">{activeTemplate.details}</span>
      <span class="tf-ready">· ready</span>
    </div>
  {/key}
{/if}

<style>
  .template-tiles {
    display: grid;
    grid-template-columns: repeat(auto-fill, minmax(11.5em, 1fr));
    gap: var(--space-3);
  }
  @media (max-width: 600px) {
    .template-tiles {
      grid-template-columns: 1fr;
      gap: var(--space-2);
    }
  }
  .template-tile {
    display: flex;
    flex-direction: column;
    gap: var(--space-2);
    text-align: left;
    background: color-mix(in srgb, var(--ink) 3%, var(--paper));
    border: 1.5px solid color-mix(in srgb, var(--ink) 14%, var(--line));
    border-radius: var(--radius);
    padding: var(--space-3);
    cursor: pointer;
    user-select: none;
    min-height: 54px;
    box-shadow: 0 1px 2px rgba(0, 0, 0, 0.04);
    transition: border-color var(--dur-fast) ease-out, background var(--dur-fast) ease-out, box-shadow var(--dur-fast) ease-out, transform var(--dur-fast) ease-out;
  }
  .template-tile:hover {
    border-color: var(--ink);
    background: color-mix(in srgb, var(--ink) 6%, var(--paper));
    box-shadow: 0 2px 5px rgba(0, 0, 0, 0.08);
  }
  .template-tile.picked {
    border-color: var(--green);
    border-width: 2px;
    background: color-mix(in srgb, var(--green) 8%, var(--paper));
    box-shadow: 0 2px 6px rgba(0, 0, 0, 0.09);
  }
  .tt-pick-btn {
    background: none;
    border: none;
    padding: 0;
    margin: 0;
    font: inherit;
    color: inherit;
    text-align: left;
    cursor: pointer;
    display: flex;
    flex-direction: column;
    gap: var(--space-2);
    width: 100%;
  }
  .tt-pick-btn:focus-visible {
    outline: 2px solid var(--green);
    outline-offset: 2px;
    border-radius: var(--radius);
  }
  .tt-header {

    display: flex;
    align-items: center;
    gap: var(--space-2);
  }
  .tt-name {
    color: var(--ink);
    font-size: var(--ui-size);
    font-weight: 600;
    letter-spacing: 0.01em;
  }
  .tt-icon {
    width: 24px;
    height: 24px;
    display: inline-flex;
    align-items: center;
    justify-content: center;
    flex-shrink: 0;
    color: color-mix(in srgb, var(--ink) 75%, transparent);
    transition: color var(--dur-fast) ease-out;
  }
  .template-tile:hover .tt-icon,
  .template-tile.picked .tt-icon {
    color: var(--green);
  }
  .tt-context {
    color: color-mix(in srgb, var(--ink) 80%, transparent);
    font-size: calc(var(--ui-size) * 0.92);
    line-height: 1.45;
  }

  .tt-footer {
    display: flex;
    align-items: center;
    justify-content: flex-start;
    margin-top: auto;
    padding-top: var(--space-2);
  }

  .teaser-btn {
    display: inline-flex;
    align-items: center;
    gap: 5px;
    white-space: nowrap;
    background: color-mix(in srgb, var(--ink) 6%, var(--paper));
    border: 1px solid color-mix(in srgb, var(--ink) 16%, var(--line));
    border-radius: var(--radius);
    color: var(--ink);
    padding: 3px 8px;
    font-size: calc(var(--ui-size) * 0.80);
    font-family: var(--font-mono);
    line-height: 1.25;
    cursor: pointer;
    transition: all var(--dur-fast) ease-out;
    max-width: 100%;
  }

  .teaser-btn:hover {
    color: var(--green);
    border-color: var(--green);
    background: color-mix(in srgb, var(--green) 10%, var(--paper));
  }

  .teaser-btn.active {
    color: var(--green);
    border-color: var(--green);
    background: color-mix(in srgb, var(--green) 16%, var(--paper));
    font-weight: 600;
  }


  .template-footnote {
    margin-top: var(--space-3);
    padding: var(--space-2) var(--space-3);
    background: color-mix(in srgb, var(--ink) 3%, var(--paper));
    border: 1px solid color-mix(in srgb, var(--ink) 14%, var(--line));
    border-radius: var(--radius);
    color: var(--ink);
    font-size: calc(var(--ui-size) * 0.92);
    line-height: 1.5;
    display: flex;
    align-items: center;
    gap: var(--space-2);
    flex-wrap: wrap;
    animation: editorialFade var(--dur-slow) ease-out;
  }

  .tf-icon {
    width: 24px;
    height: 24px;
    display: inline-flex;
    align-items: center;
    justify-content: center;
    flex-shrink: 0;
    color: var(--green);
  }

  .tf-label {
    color: var(--ink);
    font-weight: 600;
  }

  .tf-badge {
    font-size: calc(var(--ui-size) * 0.85);
    font-weight: 600;
    padding: 3px 8px;
    border-radius: var(--radius);
    border: 1px solid var(--line);
    color: var(--ink);
    background: color-mix(in srgb, var(--ink) 6%, transparent);
    letter-spacing: 0.02em;
    display: inline-flex;
    align-items: center;
    gap: 5px;
    white-space: nowrap;
    line-height: 1.2;
  }
  .tf-badge.badge-voxtral {
    color: var(--voice-b);
    border-color: color-mix(in srgb, var(--voice-b) 35%, var(--line));
    background: color-mix(in srgb, var(--voice-b) 10%, transparent);
  }
  .tf-badge.badge-qwen {
    color: var(--green);
    border-color: color-mix(in srgb, var(--green) 40%, var(--line));
    background: color-mix(in srgb, var(--green) 10%, transparent);
  }
  .tf-badge.badge-piper {
    color: var(--style-learn);
    border-color: color-mix(in srgb, var(--style-learn) 40%, var(--line));
    background: color-mix(in srgb, var(--style-learn) 10%, transparent);
  }
  .tf-badge.badge-kokoro {
    color: var(--voice-a);
    border-color: color-mix(in srgb, var(--voice-a) 40%, var(--line));
    background: color-mix(in srgb, var(--voice-a) 10%, transparent);
  }

  .kokoro-badge {
    font-size: calc(var(--ui-size) * 0.72);
    font-weight: 700;
    letter-spacing: 0.06em;
    text-transform: lowercase;
    padding: 2px 6px;
    border-radius: var(--radius);
    border: 1px solid color-mix(in srgb, var(--voice-a) 30%, var(--line));
    color: var(--voice-a);
    background: color-mix(in srgb, var(--voice-a) 8%, var(--paper));
    margin-left: auto;
    line-height: 1.1;
  }

  .tf-compat {
    font-size: calc(var(--ui-size) * 0.85);
    color: color-mix(in srgb, var(--ink) 75%, transparent);
  }

  .tf-sep {
    color: color-mix(in srgb, var(--ink) 30%, var(--line));
  }

  .tf-context {
    color: var(--ink);
    font-weight: 450;
  }

  .tf-ready {
    color: var(--green);
    font-weight: 600;
    letter-spacing: 0.02em;
  }

  @keyframes editorialFade {
    from { opacity: 0; transform: translateY(2px); }
    to { opacity: 1; transform: translateY(0); }
  }
</style>



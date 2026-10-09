<script lang="ts">
  // Compose step "show" (UX masterplan 2026-09-23): one list for the NotebookLM
  // classics and the curated shows, then one sentence saying what you get and
  // one row of actions. Cards keep the .format-card look unchanged.
  import Icon from './Icon.svelte'
  import { SHOWS, SHOWS_VISIBLE, paceWord, type Show } from '../shows'

  let {
    selectedId,
    engine,
    names,
    speed,
    minutes,
    sourceCount = 1,
    review = false,
    reviewScript = false,
    onSelect,
    onCustomize
  }: {
    selectedId: string
    engine: string
    names: string[]
    speed: number | undefined
    minutes: number
    sourceCount?: number
    review?: boolean
    reviewScript?: boolean
    onSelect: (show: Show) => void
    onCustomize: () => void
  } = $props()

  let showAll = $state(false)
  try {
    showAll = localStorage.getItem('vozonda.showAllShows') === '1'
  } catch {
    showAll = false
  }

  const selected = $derived(SHOWS.find((s) => s.id === selectedId) ?? null)
  // a selected show from the hidden part keeps the list open, so it stays visible
  const visible = $derived(
    showAll || SHOWS.findIndex((s) => s.id === selectedId) >= SHOWS_VISIBLE ? SHOWS : SHOWS.slice(0, SHOWS_VISIBLE)
  )

  function toggleAll() {
    showAll = !showAll
    try {
      localStorage.setItem('vozonda.showAllShows', showAll ? '1' : '0')
    } catch {
      void 0
    }
  }

  const who = $derived.by(() => {
    const n = names.filter(Boolean)
    const many = sourceCount >= 2
    const what = sourceCount === 2 ? 'both sources' : `all ${sourceCount} sources`
    if (n.length <= 1) {
      return { lead: n[0] ?? 'one voice', verb: many ? `reads ${what} to you` : 'reads it to you', rest: [] as string[] }
    }
    const verb = !many ? 'talk it through' : selectedId === 'digest' ? 'take one story per source' : `talk through ${what}`
    return { lead: n[0], verb, rest: n.slice(1) }
  })

  const minutesText = $derived(`about ${Math.round(minutes)} ${Math.round(minutes) === 1 ? 'minute' : 'minutes'}`)

  // sample: honest about voices that differ from what this engine will produce
  const sampleOtherVoices = $derived(!!selected?.sample && selected.sample.engine !== engine)

  let playing = $state(false)
  let audioEl: HTMLAudioElement | null = null

  function stopSample() {
    if (audioEl) {
      audioEl.pause()
      audioEl = null
    }
    playing = false
  }

  function toggleSample() {
    if (playing) {
      stopSample()
      return
    }
    const url = selected?.sample?.url
    if (!url) return
    audioEl = new Audio(url)
    audioEl.onended = stopSample
    audioEl.onerror = stopSample
    playing = true
    audioEl.play().catch(stopSample)
  }

  function pick(s: Show) {
    stopSample()
    onSelect(s)
  }

  $effect(() => () => stopSample())
</script>

<section class="ess show-section" aria-labelledby="show-h">
  <h2 id="show-h" class="mono ess-h"><Icon name="style" size={18} /> show</h2>
  <p class="mono help">pick how it should sound.</p>

  <div class="format-cards" role="radiogroup" aria-label="Show">
    {#each visible as s (s.id)}
      <button
        type="button"
        role="radio"
        aria-checked={selectedId === s.id}
        class="format-card {s.category ? 'cat-' + s.category : ''}"
        class:sel={selectedId === s.id}
        onclick={() => pick(s)}
      >
        <span class="fc-icon"><Icon name={s.icon} size={21} /></span>
        <span class="fc-label">{s.label}</span>
        <span class="fc-desc">{s.desc}</span>
      </button>
    {/each}
  </div>

  <button type="button" class="link mono all-toggle" aria-expanded={showAll} onclick={toggleAll}>
    {showAll ? 'show fewer' : `show all ${SHOWS.length}`}
  </button>

  <div class="summary" aria-live="polite">
    <p class="sum-line">
      <span class="sum-ic"><Icon name="voices" size={16} /></span>
      <span>
        <b class="va">{who.lead}</b>{#each who.rest as n, i (i)}{i === who.rest.length - 1 ? ' and ' : ', '}<b class={i === 0 ? 'vb' : 'vc'}>{n}</b>{/each}
        {who.verb}
        <span class="dot">·</span> {paceWord(speed)}
        <span class="dot">·</span> {minutesText}
        {#if review || reviewScript}
          <span class="dot">·</span> script comes to you first
        {/if}
      </span>
    </p>
    <div class="actions">
      {#if selected?.sample}
        <button type="button" class="sample-btn mono" class:playing onclick={toggleSample}
          aria-label={playing ? `stop the ${selected.label} sample` : `hear a ${selected.label} sample`}>
          <Icon name={playing ? 'pausebars' : 'playtri'} size={14} />
          <span>{playing ? 'stop' : 'hear a'} <b>{selected.label}</b> sample{#if sampleOtherVoices}<span class="other">, other voices</span>{/if}</span>
        </button>
      {/if}
      <button type="button" class="link mono customize-link" onclick={onCustomize}>
        <Icon name="sliders" size={14} /> this episode: length, style, voices, script
      </button>
    </div>
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
    margin-top: var(--space-5);
    background: color-mix(in srgb, var(--paper) 4%, transparent);
    container-type: inline-size;
    container-name: show;
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

  /* moved unchanged from App.svelte (VOZONDA-UX-1 format cards); only the
     column count is fixed so 8 cards always fill the grid: 4x2, 2x4 on phones */
  .format-cards {
    display: grid;
    grid-template-columns: repeat(4, minmax(0, 1fr));
    gap: var(--space-3);
  }

.format-card {
    display: grid;
    justify-items: start;
    align-content: start;
    gap: var(--space-1);
    text-align: left;
    background: color-mix(in srgb, var(--ink) 3%, var(--paper));
    border: 1.5px solid color-mix(in srgb, var(--ink) 14%, var(--line));
    border-radius: var(--radius);
    padding: var(--space-3);
    cursor: pointer;
    min-height: 54px;
    font-family: var(--font-mono);
    transition: border-color var(--dur-fast) ease-out, background var(--dur-fast) ease-out;
    min-width: 0;
  }

  .format-card:hover {
    border-color: var(--ink);
    background: color-mix(in srgb, var(--ink) 6%, var(--paper));
  }

  .format-card.sel {
    border-color: var(--green);
    background: color-mix(in srgb, var(--green) 12%, var(--paper));
  }

  .format-card:focus-visible {
    outline: 2px solid var(--green);
    outline-offset: 2px;
  }

  .fc-icon {
    color: color-mix(in srgb, var(--ink) 75%, transparent);
  }

  /* curated shows carry their style-category color, as the template tiles did */
  .cat-learn .fc-icon { color: var(--style-learn); }
  .cat-mood .fc-icon { color: var(--style-mood); }
  .cat-drama .fc-icon { color: var(--style-drama); }
  .cat-play .fc-icon { color: var(--style-play); }

  .format-card.sel .fc-icon {
    color: var(--green);
  }

.fc-label {
    color: var(--ink);
    font-size: var(--ui-size);
    font-weight: 600;
    overflow-wrap: anywhere;
  }

.fc-desc {
    color: var(--ink-soft);
    font-size: calc(var(--ui-size) * 0.85);
    line-height: 1.4;
    overflow-wrap: anywhere;
  }

  .link {
    background: none;
    border: none;
    padding: var(--space-1) var(--space-1);
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

  .all-toggle {
    justify-self: start;
    font-size: calc(var(--ui-size) * 0.85);
  }

  /* one closed block, left edge: a sentence that says what you get, then actions */
  .summary {
    display: grid;
    gap: var(--space-3);
    border-top: 1px dashed var(--line);
    padding-top: var(--space-4);
  }

  .sum-line {
    display: flex;
    gap: var(--space-2);
    align-items: baseline;
    margin: 0;
    font-family: var(--font-serif);
    font-size: 1.02rem;
    color: var(--ink);
  }

  .sum-ic {
    color: var(--ink-soft);
    align-self: center;
    display: inline-flex;
  }

  .sum-line b {
    font-weight: 600;
  }

  .va { color: var(--voice-a); }
  .vb { color: var(--voice-b); }
  .vc { color: var(--style-learn); }

  .dot {
    color: var(--ink-soft);
    padding-inline: 2px;
  }

  .actions {
    display: flex;
    flex-wrap: wrap;
    align-items: center;
    gap: var(--space-3) var(--space-4);
  }

  .sample-btn {
    display: inline-flex;
    align-items: center;
    gap: var(--space-2);
    min-height: 44px;
    padding: 0 var(--space-3);
    background: none;
    border: 1.5px solid var(--green);
    border-radius: var(--radius);
    color: var(--green);
    font-family: var(--font-mono);
    font-size: calc(var(--ui-size) * 0.9);
    cursor: pointer;
  }

  .sample-btn:hover,
  .sample-btn.playing {
    background: color-mix(in srgb, var(--green) 12%, var(--paper));
  }

  .sample-btn:focus-visible {
    outline: 2px solid var(--green);
    outline-offset: 2px;
  }

  .sample-btn b {
    font-weight: 600;
  }

  .other {
    color: var(--ink-soft);
  }

  .customize-link {
    justify-self: start;
    text-align: left;
    display: inline-flex;
    align-items: center;
    gap: var(--space-2);
    min-height: 44px;
    font-size: calc(var(--ui-size) * 0.9);
  }

  @container show (max-width: 680px) {
    .format-cards {
      grid-template-columns: repeat(2, minmax(0, 1fr));
      gap: var(--space-2);
    }
  }

  @media (max-width: 620px) {
    .ess {
      padding: var(--space-4);
    }

    .actions {
      display: grid;
    }

    .sample-btn {
      justify-content: center;
    }
  }

  @media (prefers-reduced-motion: reduce) {
    .format-card {
      transition: none;
    }
  }
</style>

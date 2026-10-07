<script lang="ts">
  import type { StageStatus } from '../api'

  interface Props {
    stages: StageStatus[]
    title?: string
    queuePosition?: number | null
    estimatedWaitMs?: number | null
    state?: string
  }

  let {
    stages,
    title = '',
    queuePosition = null,
    estimatedWaitMs = null,
    state = ''
  }: Props = $props()

  const mark: Record<StageStatus['status'], string> = {
    done: '✓',
    running: '',
    pending: '○',
    failed: '✗'
  }

  const doneCount = $derived(stages.filter((s) => s.status === 'done').length)
</script>

<div class="checklist" aria-live="polite" aria-atomic="true">
  {#if title}
    <p class="mono title">// working on: {title}</p>
  {/if}
  <div
    class="progress"
    role="progressbar"
    aria-valuenow={doneCount}
    aria-valuemin={0}
    aria-valuemax={stages.length}
    aria-label="Pipeline progress: {doneCount} of {stages.length} stages done"
  >
    <div class="progress-fill" style="width: {(doneCount / Math.max(1, stages.length)) * 100}%"></div>
  </div>
  <ul>
    {#each stages as s (s.name)}
      <li class={s.status}>
        <span class="glyph" aria-hidden="true">{mark[s.status]}{#if s.status === 'running'}<span class="spinner" aria-hidden="true"></span>{/if}</span>
        <span class="name mono">{s.name}</span>
        {#if s.status === 'running' && s.detail}
          <span class="detail mono">{s.detail}</span>
        {:else if s.ms !== undefined}
          <span class="detail mono">{(s.ms / 1000).toFixed(1)}s</span>
        {/if}
      </li>
    {/each}
  </ul>
</div>

<style>
  .title {
    color: var(--ink-soft);
    margin-bottom: var(--space-3);
  }

  ul {
    list-style: none;
    margin: 0;
    padding: 0;
  }

  li {
    display: flex;
    align-items: baseline;
    gap: var(--space-3);
    padding: var(--space-2) 0;
  }

  .glyph {
    width: 1.2em;
    text-align: center;
    color: var(--green);
  }

  li.pending .glyph,
  li.failed .glyph {
    color: var(--ink-soft);
  }

  .name {
    min-width: 6ch;
  }

  li.running .name {
    font-weight: 600;
    color: var(--green);
  }

  li.running {
    border-left: 2px solid var(--green);
    padding-left: var(--space-2);
  }

  li.failed .name {
    color: var(--voice-b);
  }

  li.pending .name {
    color: color-mix(in srgb, var(--ink-soft) 70%, transparent);
  }

  .detail {
    margin-left: auto;
  }

  .progress {
    height: 4px;
    background: var(--line);
    border-radius: 2px;
    overflow: hidden;
    margin-bottom: var(--space-3);
  }

  .progress-fill {
    height: 100%;
    background: var(--green);
    transition: width var(--dur-slow) ease-out;
  }

  .spinner {
    display: inline-block;
    font-family: inherit;
    font-size: 1em;
    line-height: 1;
    width: 1.2ch;
    text-align: center;
    animation: braille-spin 1s steps(10) infinite;
  }

  .spinner::before {
    content: "⠋⠙⠹⠸⠼⠴⠦⠧⠇⠏";
  }

  @keyframes braille-spin {
    from { text-indent: 0; }
    to { text-indent: -12ch; }
  }

  @media (prefers-reduced-motion: reduce) {
    .spinner {
      animation: none;
    }
    .spinner::before {
      content: "▸";
    }
  }
</style>

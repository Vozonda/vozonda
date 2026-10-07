<script lang="ts">
  import { formatWaitMs } from '../api'

  interface Props {
    queuePosition?: number | null
    queueLength?: number
    estimatedWaitMs?: number | null
    jobState: string
    streamError?: string | null
    aheadTitle?: string | null
    aheadCount?: number
    billingEnabled?: boolean
    jobTitle?: string
    voiceStageStarted?: boolean
    onCancel?: (jobId: string) => Promise<void>
    jobId?: string
  }

  let {
    queuePosition = null,
    queueLength = 0,
    estimatedWaitMs = null,
    jobState,
    streamError = null,
    aheadTitle = null,
    aheadCount = 0,
    billingEnabled = false,
    jobTitle = '',
    voiceStageStarted = false,
    onCancel,
    jobId = ''
  }: Props = $props()

  const isQueued = $derived(jobState === 'queued')
  const isRunning = $derived(jobState === 'running')
  const showQueue = $derived(isQueued && queuePosition != null && queuePosition > 0)
  const showWaiting = $derived(isQueued && (queuePosition == null || queuePosition === 0))
  const waitLabel = $derived(formatWaitMs(estimatedWaitMs))

  let cancelConfirm = $state(false)
  let cancelPending = $state(false)

  // Truncate title to ~48 chars with ellipsis
  const displayAheadTitle = $derived(
    aheadTitle && aheadTitle.length > 48 ? `${aheadTitle.slice(0, 45)}...` : aheadTitle
  )

  // Determine what to show for the ahead title
  // In billing mode with different user, aheadTitle is null from API
  const effectiveAheadTitle = $derived(billingEnabled && aheadTitle === null ? 'another episode' : displayAheadTitle)

  // Build the queue message
  const queueMessage = $derived(() => {
    if (!showQueue) return ''

    const waitPart = `approx. ${waitLabel} wait`

    if (effectiveAheadTitle) {
      if (aheadCount > 0) {
        return `waiting for "${effectiveAheadTitle}" and ${aheadCount} more &middot; ${waitPart}`
      } else {
        return `waiting for "${effectiveAheadTitle}" to finish &middot; then yours &middot; ${waitPart}`
      }
    } else {
      // No running job ahead, just queued jobs
      if (aheadCount > 0) {
        return `waiting for ${aheadCount} episode${aheadCount > 1 ? 's' : ''} ahead &middot; ${waitPart}`
      } else {
        return `// in queue &middot; position #${queuePosition} &middot; ${waitPart}`
      }
    }
  })

  // ticking countdown: decrease displayed wait every second while queued
  // we keep a local copy that ticks down without needing new SSE data
  let tickMs = $state<number | null>(null)
  let tickTimer: ReturnType<typeof setInterval> | null = null

  $effect(() => {
    // reset tick when upstream value changes
    if (estimatedWaitMs != null && estimatedWaitMs > 0 && isQueued) {
      tickMs = estimatedWaitMs
    } else {
      tickMs = null
    }
  })

  $effect(() => {
    if (tickMs == null || !isQueued) {
      if (tickTimer) clearInterval(tickTimer)
      tickTimer = null
      return
    }
    tickTimer = setInterval(() => {
      if (tickMs != null && tickMs > 1000) tickMs = tickMs - 1000
      else if (tickMs != null && tickMs <= 1000) tickMs = 0
    }, 1000)
    return () => {
      if (tickTimer) clearInterval(tickTimer)
    }
  })

  const displayWait = $derived(tickMs != null ? formatWaitMs(tickMs) : waitLabel)

  async function handleCancel() {
    if (!onCancel || !jobId || cancelPending) return
    cancelPending = true
    try {
      await onCancel(jobId)
    } finally {
      cancelPending = false
      cancelConfirm = false
    }
  }

  function requestCancel() {
    if (isQueued || !voiceStageStarted) {
      // No confirmation for queued jobs or running jobs before voice stage
      cancelConfirm = false
      handleCancel()
    } else {
      // Inline confirm for running jobs with voice stage started
      cancelConfirm = true
    }
  }
</script>

{#if isQueued}
  <div
    class="queue-indicator mono"
    role="status"
    aria-live="polite"
    aria-atomic="true"
    data-testid="queue-indicator"
  >
    {#if streamError}
      <span class="qi-error" role="alert">
        connection lost, retrying
      </span>
      <span class="qi-sep" aria-hidden="true">&middot;</span>
    {/if}

    {#if showQueue}
      <span class="qi-pos">{@html queueMessage}</span>
    {:else if showWaiting}
      <span class="qi-pos">// in queue &middot; waiting for slot</span>
      {#if estimatedWaitMs != null}
        <span class="qi-sep" aria-hidden="true">&middot;</span>
        <span class="qi-wait">approx. {displayWait} wait</span>
      {/if}
    {:else}
      <span class="qi-pos">// in queue</span>
    {/if}

    <span class="qi-dot" aria-hidden="true"></span>
    {#if onCancel && jobId}
      <button
        type="button"
        class="qi-cancel mono"
        onclick={requestCancel}
        disabled={cancelPending}
        aria-label={`Cancel "${jobTitle}"`}
      >
        cancel
      </button>
    {/if}
  </div>
{:else if isRunning}
  <!-- running jobs need no queue badge, but keep live region for a11y transition -->
  <div class="queue-indicator mono is-running" role="status" aria-live="polite" data-testid="queue-indicator-running">
    <span class="qi-pos">// rendering now</span>
    <span class="qi-dot live" aria-hidden="true"></span>
    {#if onCancel && jobId}
      {#if cancelConfirm && voiceStageStarted}
        <span class="qi-cancel-confirm mono">
          cancel render? &nbsp;
          <button type="button" class="qi-cancel-btn mono" onclick={handleCancel} disabled={cancelPending} aria-label={`Confirm cancel "${jobTitle}"`}>yes</button>
          <span class="qi-sep" aria-hidden="true">&middot;</span>
          <button type="button" class="qi-cancel-btn mono" onclick={() => (cancelConfirm = false)} aria-label={`Keep rendering "${jobTitle}"`}>no</button>
        </span>
      {:else}
        <button
          type="button"
          class="qi-cancel mono"
          onclick={requestCancel}
          disabled={cancelPending}
          aria-label={`Cancel "${jobTitle}"`}
        >
          cancel
        </button>
      {/if}
    {/if}
  </div>
{:else if streamError}
  <div class="queue-indicator mono has-error" role="alert" aria-live="assertive" data-testid="queue-indicator-error">
    <span class="qi-error">connection lost, retrying</span>
  </div>
{/if}

<style>
  .queue-indicator {
    display: inline-flex;
    align-items: center;
    gap: 8px;
    flex-wrap: wrap;
    padding: 8px 12px;
    border: 1px solid var(--line);
    border-radius: var(--radius);
    background: color-mix(in srgb, var(--paper) 96%, var(--ink) 4%);
    font-size: calc(var(--ui-size) * 0.9);
    line-height: 1.4;
  }

  .qi-pos {
    color: var(--ink);
    font-weight: 500;
  }

  .qi-sep {
    color: var(--ink-soft);
  }

  .qi-wait {
    color: var(--ink-soft);
  }

  .qi-error {
    color: var(--danger);
    font-weight: 600;
  }

  .qi-dot {
    width: 8px;
    height: 8px;
    border-radius: 50%;
    background: var(--ink-soft);
    opacity: 0.6;
    flex-shrink: 0;
  }

  .qi-dot.live {
    background: var(--green);
    opacity: 1;
    box-shadow: 0 0 6px color-mix(in srgb, var(--green) 45%, transparent);
    animation: qi-pulse 1.4s ease-in-out infinite;
  }

  @keyframes qi-pulse {
    0%, 100% { opacity: 1; transform: scale(1); }
    50% { opacity: 0.7; transform: scale(0.9); }
  }

  .is-running {
    border-color: color-mix(in srgb, var(--green) 30%, var(--line));
    background: color-mix(in srgb, var(--green) 6%, var(--paper));
  }

  .has-error {
    border-color: color-mix(in srgb, var(--danger) 30%, var(--line));
  }

  @media (prefers-reduced-motion: reduce) {
    .qi-dot.live { animation: none; }
  }

  /* Wrap cleanly at 375px */
  @media (max-width: 375px) {
    .queue-indicator {
      flex-wrap: wrap;
      gap: 6px;
    }
    .qi-pos {
      white-space: normal;
      word-break: break-word;
    }
  }

  .qi-cancel {
    margin-left: auto;
    padding: 2px 8px;
    border: 1px solid var(--line);
    border-radius: var(--radius);
    background: transparent;
    color: var(--ink-soft);
    font-size: calc(var(--ui-size) * 0.85);
    cursor: pointer;
    transition: color 120ms ease-out, border-color 120ms ease-out, background 120ms ease-out;
  }

  .qi-cancel:hover:not(:disabled) {
    color: var(--danger);
    border-color: var(--danger);
    background: color-mix(in srgb, var(--danger) 8%, var(--paper));
  }

  .qi-cancel:disabled {
    opacity: 0.5;
    cursor: not-allowed;
  }

  .qi-cancel-confirm {
    margin-left: auto;
    display: inline-flex;
    align-items: center;
    gap: 4px;
    color: var(--ink-soft);
    font-size: calc(var(--ui-size) * 0.85);
  }

  .qi-cancel-btn {
    padding: 2px 6px;
    border: 1px solid var(--line);
    border-radius: var(--radius);
    background: transparent;
    color: var(--ink);
    font-size: inherit;
    cursor: pointer;
    transition: color 120ms ease-out, border-color 120ms ease-out, background 120ms ease-out;
  }

  .qi-cancel-btn:hover:not(:disabled) {
    color: var(--danger);
    border-color: var(--danger);
    background: color-mix(in srgb, var(--danger) 8%, var(--paper));
  }

  .qi-cancel-btn:disabled {
    opacity: 0.5;
    cursor: not-allowed;
  }
</style>
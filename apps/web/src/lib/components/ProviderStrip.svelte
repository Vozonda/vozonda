<script lang="ts">
  import type { ProviderStatus, DoctorCheck } from '../api'
  import Icon from './Icon.svelte'
  import { onMount } from 'svelte'
  import { fetchDoctor } from '../api'

  interface Props {
    providers: ProviderStatus
  }

  let { providers }: Props = $props()

  let doctorChecks = $state<DoctorCheck[]>([])
  let doctorLoading = $state(true)

  async function loadDoctor() {
    try {
      const res = await fetchDoctor()
      doctorChecks = res.checks
    } catch {
      doctorChecks = []
    } finally {
      doctorLoading = false
    }
  }

  onMount(loadDoctor)

  const allGood = $derived(
    providers.providers.length > 0 &&
      providers.providers.every((p) => p.installed) &&
      providers.active.length > 0
  )
</script>

<section class="ess" aria-labelledby="prov-h">
  <h2 id="prov-h" class="mono ess-h"><Icon name="pulse" size={18} /> system status</h2>
  <p class="mono sec-help">
    which engine renders your episodes. green = active, grey = installed
    but idle, hollow = not installed.
  </p>
  <div class="cells">
    {#each providers.providers as p (p.id)}
      {@const isActive = providers.active.includes(p.id)}
      <span
        class="cell"
        title={p.installed
          ? isActive
            ? `${p.label} - active engine`
            : `${p.label} - installed, not active`
          : `${p.label} - not installed. fix: ${p.fix}`}
      >
        <span class="dot" class:ok={isActive} class:dim={p.installed && !isActive}></span>
        <span class="pid">{p.id}</span>
        <span class="pstate">{!p.installed ? 'not installed' : isActive ? 'active' : 'installed'}</span>
      </span>
    {/each}
    {#if providers.providers.length === 0}
      <span class="pstate">// no engines reported by the api</span>
    {/if}
  </div>

  {#if doctorLoading}
    <p class="mono warn">// loading diagnostics…</p>
  {:else if doctorChecks.length > 0}
    <details class="doctor-details">
      <summary class="mono doctor-summary">diagnostics ({doctorChecks.filter(c => c.ok).length}/{doctorChecks.length} ok)</summary>
      <div class="doctor-grid">
        {#each doctorChecks as c (c.id)}
          {@const isOptionalIdle = c.optional === true || (c.id.startsWith('engine_') && !c.ok && c.hint.includes('not installed'))}
          {@const showFail = !c.ok && !isOptionalIdle}
          <div class="doctor-row" class:fail={showFail} class:idle={isOptionalIdle}>
            <span class="doctor-id">{c.id}</span>
            <span class="doctor-status" class:ok={c.ok} class:fail={showFail} class:idle={isOptionalIdle}>
              {c.ok ? 'ok' : isOptionalIdle ? 'not installed' : 'fail'}
            </span>
            {#if c.hint}
              <span class="doctor-hint">{c.hint}</span>
            {/if}
          </div>
        {/each}
      </div>
    </details>
  {/if}

  {#if !allGood && doctorChecks.length === 0}
    <p class="mono warn" role="status">
      // partial setup. episodes still render with the active engine.
      install hints: hover an engine.
    </p>
  {/if}
</section>

<style>
  /* card chrome mirrors compose essentials; scoped copy, this component
     renders inside the app footer */
  .ess {
    border: 1px solid var(--line);
    border-radius: var(--radius);
    padding: var(--space-4);
    display: grid;
    gap: var(--space-2);
    min-width: 0;
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
  .sec-help {
    color: var(--ink-soft);
    font-size: calc(var(--ui-size) * 0.85);
    margin: 0;
  }
  .cells {
    display: flex;
    align-items: center;
    gap: var(--space-4);
    flex-wrap: wrap;
  }
  .cell {
    display: inline-flex;
    align-items: center;
    gap: var(--space-2);
  }
  .dot {
    width: 8px;
    height: 8px;
    border-radius: 50%;
    border: 1px solid var(--line);
    background: transparent;
    flex: none;
  }
  .dot.ok {
    background: var(--green);
    border-color: var(--green);
  }
  .dot.dim {
    background: var(--ink-soft);
    border-color: var(--ink-soft);
  }
  .pid {
    color: var(--ink);
  }
  .pstate {
    color: var(--ink-soft);
    font-size: calc(var(--ui-size) * 0.85);
  }
  .warn {
    color: var(--ink-soft);
    font-size: calc(var(--ui-size) * 0.85);
    margin: 0;
  }

  .doctor-details {
    margin-top: var(--space-2);
    border-top: 1px solid var(--line);
    padding-top: var(--space-2);
  }
  .doctor-summary {
    color: var(--ink-soft);
    font-size: calc(var(--ui-size) * 0.85);
    cursor: pointer;
    user-select: none;
  }
  .doctor-summary:hover {
    color: var(--ink);
  }
  .doctor-grid {
    display: grid;
    gap: var(--space-2);
    margin-top: var(--space-2);
  }
  .doctor-row {
    display: grid;
    grid-template-columns: auto auto 1fr;
    gap: var(--space-2);
    align-items: start;
    font-size: calc(var(--ui-size) * 0.85);
  }
  .doctor-row.fail {
    color: var(--danger);
  }
  .doctor-row.idle {
    color: var(--ink-soft);
  }
  .doctor-id {
    color: var(--ink);
    font-family: var(--font-mono);
  }
  .doctor-status {
    color: var(--ink-soft);
    font-family: var(--font-mono);
    font-size: calc(var(--ui-size) * 0.78);
  }
  .doctor-status.ok {
    color: var(--green);
  }
  .doctor-status.fail {
    color: var(--danger);
  }
  .doctor-status.idle {
    color: var(--ink-soft);
  }
  .doctor-hint {
    color: var(--ink-soft);
    line-height: 1.4;
  }
</style>

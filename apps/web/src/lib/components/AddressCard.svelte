<script lang="ts">
  // The address other devices use for feed, share and webhook links (setting address.public, #56).
  // The scope comes from the address itself (reliable); whether a phone or Apple reaches it cannot be
  // tested from the server, so the texts say who *can* reach it.
  import { saveSetting } from '../api'
  import type { DistributionMeta } from '../api'
  import Icon from './Icon.svelte'

  let {
    address,
    onchange
  }: {
    address: DistributionMeta['address']
    onchange?: () => void
  } = $props()

  // empty when nothing is set: the request's own address is only a fallback, not a choice
  const shown = (a: DistributionMeta['address']) => (a.source === 'none' ? '' : a.url)
  let value = $state('')  // set from the address by the effect below
  let err = $state('')
  let saving = $state(false)

  $effect(() => {
    value = shown(address)
    err = ''
  })

  async function save(next: string) {
    saving = true
    err = ''
    try {
      await saveSetting('address.public', next.trim())
      onchange?.()
    } catch (e: unknown) {
      err = e instanceof Error ? e.message : 'could not save'
    } finally {
      saving = false
    }
  }

  function useCurrent() {
    value = location.origin
    void save(value)
  }

  function onKeydown(e: KeyboardEvent) {
    if (e.key === 'Enter') {
      e.preventDefault()
      void save(value)
    }
  }

  const scopeInfo = $derived.by(() => {
    switch (address.scope) {
      case 'this-computer':
        return {
          badge: 'local only',
          icon: 'lock',
          text: 'only this computer reaches it: your phone and apps cannot',
          type: 'warn'
        }
      case 'private-network':
        return {
          badge: 'private network / vpn',
          icon: 'lock',
          text: 'only your own devices on your network or vpn reach it (tailscale, lan): fine for your phone, not for apple or spotify',
          type: 'ok'
        }
      case 'internet':
        return {
          badge: 'public internet',
          icon: 'radio',
          text: 'anyone on the internet can reach it',
          type: 'ok'
        }
      default:
        return { badge: '', icon: 'info', text: '', type: 'neutral' }
    }
  })

  const answersText = $derived.by(() => {
    if (address.answers === true) return 'answers'
    if (address.answers === false) return 'does not answer from this server'
    return ''
  })
</script>

<div class="opt address-card">
  <label class="lab mono" for="addr-input">the address your phone and apps use</label>
  <div class="addr-row">
    <input
      id="addr-input"
      class="mono addr-input"
      type="url"
      inputmode="url"
      autocomplete="off"
      spellcheck="false"
      placeholder="https://pods.example.org"
      bind:value
      oninput={() => (err = '')}
      onkeydown={onKeydown}
    />
    <button type="button" class="mono btn-save" onclick={() => save(value)} disabled={saving}>save</button>
  </div>
  {#if err}
    <p class="mono help err" role="alert">{err}</p>
  {/if}

  <div class="links">
    <button type="button" class="mono btn-link" onclick={useCurrent} disabled={saving}>use the address you are on now</button>
    {#if address.source === 'setting'}
      <button type="button" class="mono btn-link" onclick={() => save('')} disabled={saving}>clear</button>
    {/if}
  </div>

  {#if scopeInfo.text}
    <div class="scope-status mono" class:warn={scopeInfo.type === 'warn'}>
      <div class="scope-meta">
        <span class="scope-badge" class:ok={scopeInfo.type === 'ok'} class:warn={scopeInfo.type === 'warn'}>
          <Icon name={scopeInfo.icon} size={12} />
          <span>{scopeInfo.badge}</span>
        </span>
        {#if answersText}
          <span class="scope-answers" class:ok={address.answers === true} class:warn={address.answers === false}>
            <span class="status-dot"></span>
            <span>{answersText}</span>
          </span>
        {/if}
      </div>
      <p class="scope-text">{scopeInfo.text}</p>
    </div>
  {/if}
  {#if address.source === 'env'}
    <p class="mono help">set in .env as VOZONDA_PUBLIC_URL; an address saved here wins</p>
  {/if}
</div>

<style>
  .address-card {
    display: grid;
    gap: var(--space-2);
  }
  .lab {
    color: var(--ink-soft);
    font-size: var(--ui-size);
  }
  .addr-row {
    display: flex;
    gap: var(--space-2);
    min-width: 0;
  }
  .addr-input {
    flex: 1;
    min-width: 0;
    font: var(--ui-size) var(--font-mono);
    padding: var(--space-2) var(--space-3);
    color: var(--ink);
    background: var(--paper);
    border: 1px solid var(--line);
    border-radius: var(--radius);
  }
  .addr-input:focus-visible {
    outline: 2px solid var(--green);
    outline-offset: 1px;
  }
  .btn-save {
    font: 600 var(--ui-size) var(--font-mono);
    padding: 0 var(--space-3);
    color: var(--paper);
    background: var(--ink);
    border: 0;
    border-radius: var(--radius);
    cursor: pointer;
    min-height: 38px;
    transition: opacity var(--dur-fast) ease-out;
  }
  .btn-save:hover:not(:disabled) {
    opacity: 0.85;
  }
  .btn-save:disabled, .btn-link:disabled {
    opacity: 0.5;
    cursor: default;
  }
  .links {
    display: flex;
    flex-wrap: wrap;
    gap: var(--space-3);
  }
  .btn-link {
    font: var(--ui-size) var(--font-mono);
    color: var(--ink-soft);
    background: none;
    border: 0;
    padding: 0;
    text-decoration: underline;
    text-decoration-color: var(--line);
    text-underline-offset: 3px;
    cursor: pointer;
    transition: color var(--dur-fast) ease-out, text-decoration-color var(--dur-fast) ease-out;
  }
  .btn-link:hover:not(:disabled) {
    color: var(--ink);
    text-decoration-color: var(--ink);
  }
  .scope-status {
    display: flex;
    flex-direction: column;
    gap: var(--space-2);
    padding: var(--space-3);
    border: 1px solid var(--line);
    border-radius: var(--radius);
    background: color-mix(in srgb, var(--paper) 4%, transparent);
    margin-top: var(--space-1);
  }
  .scope-status.warn {
    border-color: color-mix(in srgb, var(--danger) 30%, var(--line));
    background: color-mix(in srgb, var(--danger) 4%, var(--paper));
  }
  .scope-meta {
    display: flex;
    align-items: center;
    gap: var(--space-3);
    flex-wrap: wrap;
  }
  .scope-badge {
    display: inline-flex;
    align-items: center;
    gap: 5px;
    padding: 2px 7px;
    border-radius: var(--radius);
    border: 1px solid var(--line);
    font-size: calc(var(--ui-size) * 0.85);
    background: var(--paper);
    color: var(--ink);
    font-weight: 500;
  }
  .scope-badge.ok {
    border-color: color-mix(in srgb, var(--green) 35%, var(--line));
    color: var(--green);
    background: color-mix(in srgb, var(--green) 8%, var(--paper));
  }
  .scope-badge.warn {
    border-color: color-mix(in srgb, var(--danger) 35%, var(--line));
    color: var(--danger);
    background: color-mix(in srgb, var(--danger) 8%, var(--paper));
  }
  .scope-answers {
    display: inline-flex;
    align-items: center;
    gap: 6px;
    font-size: calc(var(--ui-size) * 0.85);
    color: var(--ink-soft);
  }
  .scope-answers .status-dot {
    width: 6px;
    height: 6px;
    border-radius: 50%;
    background: var(--ink-soft);
    display: inline-block;
  }
  .scope-answers.ok {
    color: var(--green);
  }
  .scope-answers.ok .status-dot {
    background: var(--green);
  }
  .scope-answers.warn {
    color: var(--danger);
  }
  .scope-answers.warn .status-dot {
    background: var(--danger);
  }
  .scope-text {
    margin: 0;
    font-size: var(--ui-size);
    color: var(--ink-soft);
    line-height: 1.45;
  }
  .help {
    margin: 0;
    font-size: var(--ui-size);
    color: var(--ink-soft);
    line-height: 1.45;
  }
  .err {
    color: var(--danger);
  }
</style>

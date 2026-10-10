<script lang="ts">
  import { saveSetting } from '../api'
  import type { DistributionMeta } from '../api'

  let {
    address,
    onchange
  }: {
    address: DistributionMeta['address']
    onchange?: () => void
  } = $props()

  let value = $state(address.url)
  let err = $state('')
  let saving = $state(false)

  $effect(() => {
    value = address.url
    err = ''
  })

  async function doSave() {
    saving = true
    err = ''
    try {
      await saveSetting('address.public', value)
      onchange?.()
    } catch (e: unknown) {
      err = e instanceof Error ? e.message : 'save failed'
    } finally {
      saving = false
    }
  }

  function useCurrent() {
    value = location.origin
    doSave()
  }

  function onKeydown(e: KeyboardEvent) {
    if (e.key === 'Enter') {
      e.preventDefault()
      void doSave()
    }
  }

  async function clear() {
    saving = true
    err = ''
    try {
      await saveSetting('address.public', '')
      value = ''
      onchange?.()
    } catch (e: unknown) {
      err = e instanceof Error ? e.message : 'clear failed'
    } finally {
      saving = false
    }
  }

  const scopeText = $derived.by(() => {
    switch (address.scope) {
      case 'this-computer':
        return 'only this computer reaches it: your phone and apps cannot'
      case 'private-network':
        return 'only your own devices on your network or vpn reach it (tailscale, lan): fine for your phone, not for apple or spotify'
      case 'internet':
        return 'anyone on the internet can reach it'
      default:
        return ''
    }
  })

  const answersText = $derived.by(() => {
    if (address.answers === true) return 'answers'
    if (address.answers === false) return 'does not answer from this server'
    return ''
  })
</script>

<div class="address-card">
  <h4 class="mono card-title">your address for other devices</h4>

  <div class="opt">
    <label class="lab mono" for="addr-input">address</label>
    <input
      id="addr-input"
      class="mono text-in addr-input"
      type="text"
      placeholder={address.source === 'none' ? 'no address set' : ''}
      value={value}
      oninput={(e) => { value = e.currentTarget.value; err = '' }}
      onkeydown={onKeydown}
    />
    <button class="mono btn-save" onclick={doSave} disabled={saving}>save</button>
    {#if err}
      <p class="mono help err" role="alert">{err}</p>
    {/if}
  </div>

  <div class="ctl-row">
    <button class="mono btn-link" onclick={useCurrent}>use the address you are on now</button>
    {#if address.source === 'setting'}
      <button class="mono btn-link" onclick={clear}>clear</button>
    {/if}
  </div>

  {#if scopeText}
    <p class="mono scope">{scopeText}</p>
  {/if}

  {#if answersText}
    <p class="mono answers">{answersText}</p>
  {/if}

  {#if address.source === 'env'}
    <p class="mono note">set in .env as VOZONDA_PUBLIC_URL</p>
  {/if}
</div>

<style>
  .address-card {
    border: 1px solid var(--line);
    border-radius: var(--radius);
    padding: var(--space-3);
    background: color-mix(in srgb, var(--ink) 3%, var(--paper));
  }

  .card-title {
    font-family: var(--mono);
    font-size: var(--ui-size);
    color: var(--ink);
    margin: 0 0 var(--space-2) 0;
    font-weight: 600;
  }

  .opt {
    display: flex;
    flex-direction: column;
    gap: var(--space-1);
  }

  .addr-input {
    width: 100%;
    min-width: 0;
  }

  .btn-save {
    align-self: flex-start;
    background: var(--ink);
    color: var(--paper);
    border: none;
    border-radius: var(--radius);
    padding: 2px var(--space-2);
    font-family: var(--mono);
    font-size: var(--ui-size);
    cursor: pointer;
  }

  .btn-save:disabled {
    opacity: 0.5;
    cursor: default;
  }

  .btn-link {
    background: none;
    border: none;
    color: var(--ink);
    text-decoration: underline;
    font-family: var(--mono);
    font-size: var(--ui-size);
    cursor: pointer;
    padding: 0;
  }

  .btn-link:hover {
    color: color-mix(in srgb, var(--ink) 70%, var(--paper));
  }

  .scope {
    font-family: var(--mono);
    font-size: var(--ui-size);
    color: color-mix(in srgb, var(--ink) 75%, var(--paper));
    margin: var(--space-2) 0 0 0;
  }

  .answers {
    font-family: var(--mono);
    font-size: var(--ui-size);
    color: color-mix(in srgb, var(--ink) 60%, var(--paper));
    margin: var(--space-1) 0 0 0;
  }

  .note {
    font-family: var(--mono);
    font-size: calc(var(--ui-size) - 1px);
    color: color-mix(in srgb, var(--ink) 50%, var(--paper));
    margin: var(--space-2) 0 0 0;
  }
</style>
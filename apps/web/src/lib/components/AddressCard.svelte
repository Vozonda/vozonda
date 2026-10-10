<script lang="ts">
  // The address other devices use for feed, share and webhook links (setting address.public, #56).
  // The scope comes from the address itself (reliable); whether a phone or Apple reaches it cannot be
  // tested from the server, so the texts say who *can* reach it.
  import { saveSetting } from '../api'
  import type { DistributionMeta } from '../api'

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

  {#if scopeText}
    <p class="mono scope">{address.source === 'none' ? 'without an address, links use ' + address.url + ': ' : ''}{scopeText}</p>
  {/if}
  {#if answersText}
    <p class="mono help">{answersText}</p>
  {/if}
  {#if address.source === 'env'}
    <p class="mono help">set in .env as VOZONDA_PUBLIC_URL; an address saved here wins</p>
  {/if}
</div>

<style>
  .address-card { display: grid; gap: var(--space-2); }
  .addr-row { display: flex; gap: var(--space-2); min-width: 0; }
  .addr-input {
    flex: 1; min-width: 0; font: var(--ui-size) var(--font-mono); padding: var(--space-2) var(--space-3);
    color: var(--ink); background: var(--paper); border: 1px solid var(--line); border-radius: var(--radius);
  }
  .btn-save {
    font: 600 var(--ui-size) var(--font-mono); padding: 0 var(--space-3); color: var(--paper);
    background: var(--ink); border: 0; border-radius: var(--radius); cursor: pointer;
  }
  .btn-save:disabled, .btn-link:disabled { opacity: 0.5; cursor: default; }
  .links { display: flex; flex-wrap: wrap; gap: var(--space-3); }
  .btn-link {
    font: var(--ui-size) var(--font-mono); color: var(--ink); background: none; border: 0; padding: 0;
    text-decoration: underline; cursor: pointer;
  }
  .scope { margin: 0; color: var(--ink); font-size: var(--ui-size); }
  .err { color: var(--danger); }
</style>

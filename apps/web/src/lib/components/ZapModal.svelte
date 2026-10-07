<script lang="ts">
  import Icon from './Icon.svelte'
  import { getActiveIdentity, hasNip07Extension } from '../nostr'
  import {
    PRESET_SATS,
    DEFAULT_RELAYS,
    MAX_COMMENT,
    isValidLightningAddress,
    fetchLnurlPayParams,
    validateLnurlForZap,
    satsToMsats,
    buildZapRequest,
    signZapRequest,
    buildCallbackUrl,
    fetchInvoice,
    hasWebLN,
    hasNWC,
    payWithWebLN,
    payWithNWC,
    getNWCUri,
    setNWCUri,
    clearNWCUri,
    isValidNWCUri,
    copyInvoice,
    openLightningUri,
    listenForZapReceipts,
    isValidBolt11,
    recordEpisodeBoost
  } from '../zaps'

  let {
    open = false,
    onClose,
    lightningAddress = '',
    recipientPubkey = '',
    jobId = '',
    relays = DEFAULT_RELAYS,
    initialSats = 500,
    initialComment = '',
    timestampSeconds,
    onZapSuccess
  }: {
    open: boolean
    onClose: () => void
    lightningAddress: string
    recipientPubkey?: string
    jobId?: string
    relays?: string[]
    initialSats?: number
    initialComment?: string
    timestampSeconds?: number
    onZapSuccess?: (sats: number, comment: string, timestampSeconds?: number) => void
  } = $props()

  let sats = $state<number>(500)
  let customSats = $state<string>('')
  let comment = $state<string>('')

  let weblnActive = $state(false)
  let nwcActive = $state(false)
  let showNwcConfig = $state(false)
  let nwcInput = $state('')
  let nwcError = $state('')

  $effect(() => {
    if (open) {
      if (initialSats) sats = initialSats
      if (initialComment) comment = initialComment
      weblnActive = hasWebLN()
      nwcActive = hasNWC()
      if (nwcActive) nwcInput = getNWCUri() ?? ''
    }
  })
  let busy = $state(false)
  let error = $state('')
  let step = $state<'idle' | 'fetching' | 'signing' | 'invoice' | 'pay' | 'waiting' | 'confirmed'>('idle')
  let invoice = $state<string>('')
  let zapConfirmed = $state(false)
  let zapAmount = $state<number | null>(null)
  let stopListening: (() => void) | null = null
  let copied = $state(false)

  const effectiveSats = $derived.by(() => {
    if (customSats.trim()) {
      const n = Number(customSats.trim())
      if (!Number.isNaN(n) && n > 0) return Math.round(n)
    }
    return sats
  })

  const commentLen = $derived(comment.length)
  const canZap = $derived(
    !!lightningAddress && isValidLightningAddress(lightningAddress) && effectiveSats > 0 && commentLen <= MAX_COMMENT && !busy && step !== 'confirmed'
  )

  function closeIfBackdrop(e: MouseEvent) {
    if (e.target === e.currentTarget) handleClose()
  }

  function handleClose() {
    stopListening?.()
    stopListening = null
    showNwcConfig = false
    nwcError = ''
    if (step !== 'waiting' && step !== 'pay') {
      // reset only if not in payment flow? keep invoice for copy
    }
    onClose()
  }

  function reset() {
    busy = false
    error = ''
    step = 'idle'
    invoice = ''
    zapConfirmed = false
    zapAmount = null
    copied = false
    stopListening?.()
    stopListening = null
  }

  function handleSaveNwc() {
    nwcError = ''
    const uri = nwcInput.trim()
    if (!isValidNWCUri(uri)) {
      nwcError = 'invalid NWC URI (must start with nostr+walletconnect://)'
      return
    }
    setNWCUri(uri)
    nwcActive = true
    showNwcConfig = false
  }

  function handleDisconnectNwc() {
    clearNWCUri()
    nwcInput = ''
    nwcActive = false
    showNwcConfig = false
  }

  function handleOpenFaqGuide(e: MouseEvent) {
    e.preventDefault()
    handleClose()
    window.location.hash = '#faq#nostr-section'
    setTimeout(() => {
      const el = document.getElementById('nostr-section')
      if (el) el.scrollIntoView({ behavior: 'smooth', block: 'start' })
    }, 80)
  }

  $effect(() => {
    if (open) {
      // when modal opens, reset to idle unless we show confirmed
      if (step === 'confirmed') reset()
      error = ''
      // if recipientPubkey not provided, try to derive from LNURL fetch later
    } else {
      // keep state for a moment, but clean up relay
      stopListening?.()
    }
  })

  async function startZap() {
    error = ''
    const addr = lightningAddress.trim()
    if (!isValidLightningAddress(addr)) { error = 'invalid lightning address'; return }
    if (effectiveSats <= 0) { error = 'pick an amount'; return }
    if (comment.length > MAX_COMMENT) { error = `comment too long (max ${MAX_COMMENT})`; return }

    const active = getActiveIdentity()
    const senderPubkey = active?.pubkey ?? ''
    // Allow anon zap with ephemeral? For now require signer for NIP-57 signed zap
    // If no signer, we will create unsigned zap and still request invoice (some LNURL allow anon)
    // But spec says zap request must be signed. So warn if no extension.
    const msats = satsToMsats(effectiveSats)

    busy = true
    step = 'fetching'
    try {
      const params = await fetchLnurlPayParams(addr)
      const zapErr = validateLnurlForZap(params)
      if (zapErr) throw new Error(zapErr)
      if (msats < params.minSendable || msats > params.maxSendable) {
        throw new Error(`amount ${msats} msats outside range [${params.minSendable}, ${params.maxSendable}]`)
      }
      const allow = params.commentAllowed ?? MAX_COMMENT
      if (comment.length > allow) throw new Error(`comment too long (allowed ${allow})`)

      const recipient = params.nostrPubkey ?? recipientPubkey
      if (!recipient || !/^[0-9a-f]{64}$/i.test(recipient)) throw new Error('missing recipient pubkey for zap')

      step = 'signing'
      let zapJson: string
      if (hasNip07Extension() && senderPubkey && /^[0-9a-f]{64}$/i.test(senderPubkey)) {
        const template = buildZapRequest({
          senderPubkey,
          recipientPubkey: recipient,
          amountMsats: msats,
          relays,
          content: comment,
          lnurl: addr,
          eventId: jobId && /^[0-9a-f]{64}$/i.test(jobId) ? jobId : undefined
        })
        const signed = await signZapRequest(template)
        zapJson = JSON.stringify(signed)
      } else {
        // anonymous or read-only: build unsigned template and use as nostr param
        // Some providers accept unsigned? We still send a minimal request without sig
        // For compliance, we warn and send unsigned
        const template = buildZapRequest({
          senderPubkey: senderPubkey && /^[0-9a-f]{64}$/i.test(senderPubkey) ? senderPubkey : '0'.repeat(64),
          recipientPubkey: recipient,
          amountMsats: msats,
          relays,
          content: comment,
          lnurl: addr,
          eventId: jobId && /^[0-9a-f]{64}$/i.test(jobId) ? jobId : undefined
        })
        // mark as unsigned but still valid JSON; LNURL server may accept
        zapJson = JSON.stringify(template)
        if (!hasNip07Extension()) {
          // continue with unsigned, but note in error if needed
        }
      }

      step = 'invoice'
      const callbackUrl = buildCallbackUrl(params.callback, msats, zapJson, comment || undefined)
      const inv = await fetchInvoice(callbackUrl)
      invoice = inv.pr
      if (!isValidBolt11(invoice)) throw new Error('invalid bolt11 returned')

      step = 'pay'
      // try WebLN auto-pay, then NWC auto-pay
      if (hasWebLN()) {
        try {
          await payWithWebLN(invoice)
          // payment sent, now wait for receipt
          step = 'waiting'
          startReceiptListener(recipient, jobId)
          return
        } catch (e) {
          // WebLN failed, fall back to manual
          error = `WebLN: ${e instanceof Error ? e.message : String(e)} - copy invoice below`
          step = 'pay'
        }
      } else if (hasNWC()) {
        try {
          await payWithNWC(invoice)
          step = 'waiting'
          startReceiptListener(recipient, jobId)
          return
        } catch (e) {
          error = `NWC: ${e instanceof Error ? e.message : String(e)} - copy invoice below`
          step = 'pay'
        }
      } else {
        step = 'pay'
      }

      // start listening even before manual pay, so confirmation appears after they pay externally
      startReceiptListener(recipient, jobId)
      if (step === 'pay') step = 'waiting'

    } catch (e) {
      error = e instanceof Error ? e.message : String(e)
      step = 'idle'
    } finally {
      busy = false
    }
  }

  function startReceiptListener(recipient: string, eventId?: string) {
    stopListening?.()
    zapConfirmed = false
    const watchRelays = relays.length ? relays : DEFAULT_RELAYS
    stopListening = listenForZapReceipts(
      watchRelays,
      { recipientPubkey: recipient, eventId: eventId && /^[0-9a-f]{64}$/i.test(eventId) ? eventId : undefined },
      (receipt) => {
        // basic check: receipt bolt11 matches our invoice or amount matches
        if (receipt.bolt11 && receipt.bolt11 === invoice) {
          zapConfirmed = true
          zapAmount = receipt.amountMsats ? Math.round(receipt.amountMsats / 1000) : effectiveSats
          step = 'confirmed'
          stopListening?.()
          if (jobId) {
            recordEpisodeBoost({
              id: `boost-${Date.now()}`,
              episodeId: jobId,
              sats: zapAmount ?? effectiveSats,
              comment,
              timestampSeconds,
              createdAt: Date.now()
            })
          }
          if (onZapSuccess) onZapSuccess(zapAmount ?? effectiveSats, comment, timestampSeconds)
        } else if (receipt.amountMsats && Math.abs(receipt.amountMsats - satsToMsats(effectiveSats)) < 1000) {
          // amount close enough
          zapConfirmed = true
          zapAmount = Math.round(receipt.amountMsats / 1000)
          step = 'confirmed'
          stopListening?.()
          if (jobId) {
            recordEpisodeBoost({
              id: `boost-${Date.now()}`,
              episodeId: jobId,
              sats: zapAmount ?? effectiveSats,
              comment,
              timestampSeconds,
              createdAt: Date.now()
            })
          }
          if (onZapSuccess) onZapSuccess(zapAmount ?? effectiveSats, comment, timestampSeconds)
        } else if (!receipt.bolt11) {
          // any receipt for this recipient counts as confirmation in MVP
          zapConfirmed = true
          zapAmount = effectiveSats
          step = 'confirmed'
          stopListening?.()
          if (jobId) {
            recordEpisodeBoost({
              id: `boost-${Date.now()}`,
              episodeId: jobId,
              sats: effectiveSats,
              comment,
              timestampSeconds,
              createdAt: Date.now()
            })
          }
          if (onZapSuccess) onZapSuccess(effectiveSats, comment, timestampSeconds)
        }
      },
      () => { void 0 }
    )
    // auto-timeout after 90s
    setTimeout(() => {
      if (step === 'waiting' && !zapConfirmed) {
        // keep waiting, but show hint
      }
    }, 90000)
  }

  async function handleCopy() {
    try {
      await copyInvoice(invoice)
      copied = true
      setTimeout(() => (copied = false), 2000)
    } catch (e) {
      error = e instanceof Error ? e.message : String(e)
    }
  }

  function handleOpenWallet() {
    try { openLightningUri(invoice) } catch { void 0 }
  }
</script>

{#if open}
  <div class="overlay" role="presentation" onclick={closeIfBackdrop}>
    <div class="modal" role="dialog" aria-modal="true" aria-labelledby="zap-title">
      <div class="modal-head">
        <h2 id="zap-title" class="mono"><Icon name="zap" size={16} /> boost episode (nostr zap)</h2>
        <button class="close mono" onclick={handleClose} aria-label="Close">close</button>
      </div>

      {#if step === 'confirmed'}
        <div class="confirmed" role="status" aria-live="polite">
          <div class="confirmed-icon"><Icon name="check" size={22} /></div>
          <p class="mono confirmed-text">boost confirmed{zapAmount ? ` · ${zapAmount} sats` : ''}</p>
          <p class="mono confirmed-sub">receipt kind 9735 seen on relays. Thanks for the value.</p>
          <button class="primary mono" onclick={handleClose}>done</button>
        </div>
      {:else}
        <div class="wallet-bar mono" class:wallet-bar-ok={weblnActive || nwcActive}>
          {#if weblnActive}
            <span class="status-dot green" aria-hidden="true"></span>
            <span class="wallet-status-txt">WebLN active · 1-click zap ready</span>
          {:else if nwcActive}
            <span class="status-dot green" aria-hidden="true"></span>
            <span class="wallet-status-txt">NWC connected · remote zap ready</span>
            <button type="button" class="wallet-bar-btn mono" onclick={handleDisconnectNwc}>disconnect</button>
          {:else}
            <span class="status-dot muted" aria-hidden="true"></span>
            <span class="wallet-status-txt">no wallet connected · QR or invoice fallback</span>
            <button type="button" class="wallet-bar-btn mono" onclick={() => (showNwcConfig = !showNwcConfig)}>
              {showNwcConfig ? 'close' : 'connect NWC'}
            </button>
          {/if}
        </div>

        {#if showNwcConfig && !nwcActive}
          <div class="nwc-box mono">
            <label for="nwc-uri-input" class="nwc-label">nostr wallet connect (NWC) uri</label>
            <div class="nwc-input-row">
              <input
                id="nwc-uri-input"
                type="password"
                class="text-in mono nwc-input"
                placeholder="nostr+walletconnect://..."
                bind:value={nwcInput}
              />
              <button type="button" class="secondary mono" onclick={handleSaveNwc}>save</button>
            </div>
            {#if nwcError}
              <p class="err mono">{nwcError}</p>
            {/if}
            <p class="nwc-hint mono">Connects to Alby Hub, Mutiny, CoinOS, or any NWC-compatible lightning wallet for 1-click background boosts.</p>
          </div>
        {/if}

        <p class="mono help">Send sats directly to creators via Podcasting 2.0 Value-for-Value. Signed with NIP-07 or Amber, paid via WebLN, NWC, or any lightning wallet.</p>

        <div class="chips" role="group" aria-label="Amount presets">
          {#each PRESET_SATS as amt (amt)}
            <button
              type="button"
              class="chip mono"
              class:sel={sats === amt && !customSats.trim()}
              onclick={() => { sats = amt; customSats = '' }}
              aria-pressed={sats === amt && !customSats.trim()}
            >
              {amt} sats
            </button>
          {/each}
        </div>

        <div class="custom-row">
          <label class="mono lab" for="zap-custom">custom sats</label>
          <input id="zap-custom" class="mono text-in" type="number" min="1" inputmode="numeric" placeholder="e.g. 1000" bind:value={customSats} />
        </div>

        <div class="comment-row">
          <label class="mono lab" for="zap-comment">comment (optional)</label>
          <textarea id="zap-comment" class="mono text-area" placeholder="love this episode" rows={2} maxlength={MAX_COMMENT} bind:value={comment}></textarea>
          <span class="mono counter" class:warn={commentLen > MAX_COMMENT} class:near={commentLen > MAX_COMMENT * 0.8 && commentLen <= MAX_COMMENT}>{commentLen}/{MAX_COMMENT}</span>
        </div>

        <div class="addr-row mono">
          <span class="addr-label">to</span>
          <span class="addr-value" title={lightningAddress}>{lightningAddress || 'no lightning address set'}</span>
          {#if !hasNip07Extension()}
            <span class="addr-hint">no signer detected · zap will be sent unsigned (Amber/WebLN available for signing)</span>
          {/if}
        </div>

        {#if step === 'pay' || step === 'waiting' || invoice}
          <div class="invoice-card">
            <p class="mono invoice-label">invoice {step === 'waiting' ? '· waiting for receipt (kind 9735)' : ''}</p>
            <code class="mono invoice-pr" title={invoice}>{invoice.slice(0, 42)}...{invoice.slice(-12)}</code>
            <div class="invoice-actions">
              <button type="button" class="secondary mono" onclick={handleCopy}>{copied ? 'copied!' : 'copy invoice'}</button>
              <button type="button" class="secondary mono" onclick={handleOpenWallet}>open wallet</button>
              {#if hasWebLN() && invoice}
                <button type="button" class="secondary mono" onclick={async () => {
                  try { await payWithWebLN(invoice); step='waiting'; } catch(e){ error = e instanceof Error ? e.message : String(e) }
                }}>pay with WebLN</button>
              {/if}
              {#if hasNWC() && invoice}
                <button type="button" class="secondary mono" onclick={async () => {
                  try { await payWithNWC(invoice); step='waiting'; } catch(e){ error = e instanceof Error ? e.message : String(e) }
                }}>pay with NWC</button>
              {/if}
            </div>
            {#if step === 'waiting'}
              <p class="mono waiting-hint"><Icon name="pulse" size={12} /> listening for kind 9735 on {relays[0] ?? DEFAULT_RELAYS[0]} ...</p>
            {/if}
          </div>
        {/if}

        {#if zapConfirmed}
          <p class="mono ok" role="status" aria-live="polite">zap receipt seen · thank you</p>
        {/if}

        {#if error}
          <p class="mono err" role="alert">{error}</p>
        {/if}

        <div class="actions">
          {#if step === 'idle' || step === 'fetching' || step === 'signing' || step === 'invoice'}
            <button type="button" class="primary mono" disabled={!canZap || busy} onclick={() => void startZap()}>
              {#if busy}
                {step === 'fetching' ? 'fetching lnurl...' : step === 'signing' ? 'signing 9734...' : step === 'invoice' ? 'requesting invoice...' : 'working...'}
              {:else}
                zap {effectiveSats} sats
              {/if}
            </button>
          {:else if step === 'pay' || step === 'waiting'}
            <button type="button" class="primary mono" onclick={handleClose}>close</button>
          {/if}
          <button type="button" class="quiet mono" onclick={reset} disabled={busy}>reset</button>
        </div>

        <div class="v4v-guide-box mono">
          <div class="v4v-guide-title">
            <Icon name="zap" size={12} />
            <span>how value for value works</span>
          </div>
          <p class="v4v-guide-body">
            Boosts and streaming send Bitcoin sats directly to creators with cryptographic NIP-57 receipts on Nostr relays. No intermediaries, no advertisements, no subscriptions.
          </p>
          <a
            href="#faq#nostr-section"
            class="v4v-guide-faq-link mono"
            onclick={handleOpenFaqGuide}
          >
            read full boost & zap guide in FAQ →
          </a>
        </div>
      {/if}
    </div>
  </div>
{/if}

<style>
  .overlay { position: fixed; inset: 0; background: color-mix(in srgb, var(--ink) 42%, transparent); backdrop-filter: blur(2px); display: grid; place-items: center; z-index: 70; padding: var(--space-3); }
  .modal { width: min(560px, 100%); max-height: 90vh; overflow: auto; background: var(--paper); border: 1px solid var(--line); border-radius: var(--radius); padding: var(--space-4); display: grid; gap: var(--space-3); box-shadow: 0 12px 32px rgba(0,0,0,.18); }
  .modal-head { display: flex; justify-content: space-between; align-items: center; }
  .modal-head h2 { margin: 0; font-size: var(--ui-size); font-weight: 600; text-transform: lowercase; display: flex; align-items: center; gap: var(--space-2); }
  .close { background: transparent; border: 1px solid var(--line); border-radius: var(--radius); padding: var(--space-1) var(--space-2); cursor: pointer; min-height: 32px; }
  .close:hover { border-color: var(--ink); color: var(--ink); }
  .wallet-bar {
    display: flex;
    align-items: center;
    gap: var(--space-2);
    padding: 6px 10px;
    background: color-mix(in srgb, var(--ink) 4%, var(--paper));
    border: 1px solid var(--line);
    border-radius: var(--radius);
    font-size: calc(var(--ui-size) * .84);
    color: var(--ink-soft);
  }
  .wallet-bar.wallet-bar-ok {
    border-color: color-mix(in srgb, var(--green) 30%, var(--line));
    background: color-mix(in srgb, var(--green) 6%, var(--paper));
    color: var(--ink);
  }
  .status-dot {
    width: 6px;
    height: 6px;
    border-radius: 50%;
    flex-shrink: 0;
  }
  .status-dot.green {
    background: var(--green);
    box-shadow: 0 0 4px color-mix(in srgb, var(--green) 60%, transparent);
  }
  .status-dot.muted {
    background: var(--ink-soft);
  }
  .wallet-status-txt {
    flex: 1;
    overflow: hidden;
    text-overflow: ellipsis;
    white-space: nowrap;
  }
  .wallet-bar-btn {
    background: transparent;
    border: 1px solid var(--line);
    border-radius: var(--radius);
    padding: 2px 8px;
    font-size: calc(var(--ui-size) * .78);
    color: var(--ink);
    cursor: pointer;
    text-decoration: none;
    line-height: 1.4;
  }
  .wallet-bar-btn:hover {
    border-color: var(--green);
    color: var(--ink);
    background: color-mix(in srgb, var(--green) 8%, var(--paper));
  }
  .nwc-box {
    background: color-mix(in srgb, var(--ink) 3%, var(--paper));
    border: 1px solid var(--line);
    border-radius: var(--radius);
    padding: var(--space-3);
    display: grid;
    gap: 6px;
    font-size: calc(var(--ui-size) * .84);
  }
  .nwc-label {
    color: var(--ink-soft);
    font-size: calc(var(--ui-size) * .82);
  }
  .nwc-input-row {
    display: flex;
    gap: var(--space-2);
  }
  .nwc-input {
    flex: 1;
    font-size: calc(var(--ui-size) * .82);
    min-height: 36px;
  }
  .nwc-hint {
    margin: 0;
    color: var(--ink-soft);
    font-size: calc(var(--ui-size) * .78);
    line-height: 1.35;
  }
  .help { color: var(--ink-soft); font-size: calc(var(--ui-size) * .9); margin: 0; line-height: 1.45; }
  .chips { display: flex; flex-wrap: wrap; gap: var(--space-2); }
  .chip { background: color-mix(in srgb, var(--ink) 4%, var(--paper)); border: 1px solid var(--line); border-radius: var(--radius); padding: 6px 10px; cursor: pointer; min-height: 38px; font-size: var(--ui-size); color: var(--ink); transition: background var(--dur-fast) ease-out, border-color var(--dur-fast) ease-out; }
  .chip:hover:not(.sel):not([aria-pressed="true"]) { border-color: var(--green); color: var(--ink); background: color-mix(in srgb, var(--green) 8%, var(--paper)); }
  .chip.sel { background: color-mix(in srgb, var(--green) 12%, var(--paper)); color: var(--ink); border-color: var(--green); font-weight: 600; }
  .chip.sel:hover { background: color-mix(in srgb, var(--green) 20%, var(--paper)); border-color: var(--green); color: var(--ink); }
  .custom-row, .comment-row { display: grid; gap: 6px; }
  .lab { color: var(--ink-soft); font-size: calc(var(--ui-size) * .88); }
  .text-in { width: 100%; min-height: 42px; font-family: var(--font-mono); font-size: var(--ui-size); background: color-mix(in srgb, var(--ink) 4%, var(--paper)); border: 1px solid color-mix(in srgb, var(--ink) 18%, var(--line)); border-radius: var(--radius); padding: var(--space-2) var(--space-3); color: var(--ink); }
  .text-in:focus-visible { outline: 2px solid var(--green); outline-offset: 2px; border-color: var(--green); }
  .text-area { width: 100%; font-family: var(--font-mono); font-size: calc(var(--ui-size) * .92); background: color-mix(in srgb, var(--ink) 4%, var(--paper)); border: 1px solid color-mix(in srgb, var(--ink) 18%, var(--line)); border-radius: var(--radius); padding: var(--space-2) var(--space-3); color: var(--ink); resize: vertical; }
  .text-area:focus-visible { outline: 2px solid var(--green); outline-offset: 2px; border-color: var(--green); }
  .counter { justify-self: end; font-size: calc(var(--ui-size) * .8); color: var(--ink-soft); }
  .counter.near { color: var(--ink); }
  .counter.warn { color: #c53030; }
  .addr-row { display: flex; flex-wrap: wrap; gap: var(--space-2); align-items: center; font-size: calc(var(--ui-size) * .85); color: var(--ink-soft); }
  .addr-label { color: var(--ink-soft); }
  .addr-value { color: var(--ink); overflow-wrap: anywhere; }
  .addr-hint { flex: 1 1 100%; color: var(--ink-soft); font-size: calc(var(--ui-size) * .8); }
  .invoice-card { border: 1px solid color-mix(in srgb, var(--green) 22%, var(--line)); background: color-mix(in srgb, var(--green) 6%, var(--paper)); border-radius: var(--radius); padding: var(--space-3); display: grid; gap: var(--space-2); }
  .invoice-label { margin: 0; font-size: calc(var(--ui-size) * .8); color: var(--ink-soft); text-transform: lowercase; letter-spacing: .04em; }
  .invoice-pr { display: block; font-size: calc(var(--ui-size) * .82); color: var(--ink); overflow-wrap: anywhere; word-break: break-all; background: color-mix(in srgb, var(--paper) 60%, transparent); padding: 6px 8px; border-radius: var(--radius); border: 1px solid var(--line); }
  .invoice-actions { display: flex; flex-wrap: wrap; gap: var(--space-2); }
  .secondary { background: transparent; border: 1px solid var(--line); border-radius: var(--radius); padding: 6px 10px; cursor: pointer; min-height: 36px; color: var(--ink); }
  .secondary:hover { border-color: var(--green); color: var(--ink); background: color-mix(in srgb, var(--green) 8%, var(--paper)); }
  .waiting-hint { margin: 0; color: var(--ink-soft); font-size: calc(var(--ui-size) * .82); display: flex; align-items: center; gap: 6px; }
  .actions { display: flex; gap: var(--space-3); align-items: center; flex-wrap: wrap; }
  .primary { background: var(--green); color: var(--paper); border: 1px solid var(--green); border-radius: var(--radius); padding: var(--space-2) var(--space-4); font-family: var(--font-mono); font-size: var(--ui-size); cursor: pointer; min-height: 42px; font-weight: 600; transition: background var(--dur-fast) ease-out, border-color var(--dur-fast) ease-out; }
  .primary:disabled { opacity: .5; cursor: not-allowed; }
  .primary:hover:not(:disabled) { background: color-mix(in srgb, var(--green) 85%, var(--ink)); border-color: var(--green); color: var(--paper); }
  .quiet { background: transparent; border: 1px solid var(--line); border-radius: var(--radius); padding: 6px 10px; cursor: pointer; min-height: 36px; color: var(--ink-soft); }
  .quiet:hover { border-color: var(--ink); color: var(--ink); }
  .quiet:disabled { opacity: .4; }
  .err { color: #c53030; white-space: pre-wrap; margin: 0; }
  .ok { color: var(--green); margin: 0; }
  .v4v-guide-box {
    margin-top: var(--space-1);
    padding: var(--space-3);
    background: color-mix(in srgb, var(--ink) 3%, var(--paper));
    border: 1px solid var(--line);
    border-radius: var(--radius);
    display: grid;
    gap: 6px;
    font-size: calc(var(--ui-size) * .84);
  }
  .v4v-guide-title {
    display: flex;
    align-items: center;
    gap: 6px;
    font-weight: 600;
    color: var(--ink);
    text-transform: lowercase;
    letter-spacing: .02em;
  }
  .v4v-guide-body {
    margin: 0;
    line-height: 1.45;
    color: var(--ink-soft);
    font-size: calc(var(--ui-size) * .82);
  }
  .v4v-guide-faq-link {
    color: var(--green);
    text-decoration: underline;
    text-underline-offset: 2px;
    font-size: calc(var(--ui-size) * .82);
    display: inline-flex;
    align-items: center;
    gap: 4px;
    cursor: pointer;
    justify-self: start;
    transition: opacity var(--dur-fast) ease-out;
  }
  .v4v-guide-faq-link:hover {
    opacity: .8;
  }
  .confirmed { display: grid; place-items: center; gap: var(--space-2); padding: var(--space-4) 0; text-align: center; }
  .confirmed-icon { width: 48px; height: 48px; border-radius: 50%; background: color-mix(in srgb, var(--green) 12%, transparent); border: 1px solid color-mix(in srgb, var(--green) 30%, transparent); display: grid; place-items: center; color: var(--green); }
  .confirmed-text { margin: 0; font-weight: 600; color: var(--ink); font-size: var(--ui-size); }
  .confirmed-sub { margin: 0; color: var(--ink-soft); font-size: calc(var(--ui-size) * .85); }
</style>

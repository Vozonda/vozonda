<script lang="ts" module>
  /** What a show should be: the three switches behind "who can listen?" (#56). */
  export interface ReachTarget {
    rss: boolean
    public: boolean
    nostr: boolean
  }
</script>

<script lang="ts">
  // "Who can listen?" for one show (#56). Presentational: it derives the level from the show's switches
  // and asks the settings screen for a target; the screen sets the switches (and confirms Nostr).
  //   only in vozonda : no feed, no nostr
  //   my podcast app  : a private feed (its link carries the feed key)
  //   public          : rss and/or nostr, at least one; rss needs an internet address, nostr no server
  import { tick } from 'svelte'
  import type { DistributionMeta } from '../api'

  type Level = 'vozonda' | 'podcast' | 'public'

  let {
    show,
    address,
    busy = false,
    onchoose
  }: {
    show: DistributionMeta['shows'][number]
    address: DistributionMeta['address']
    busy?: boolean
    onchoose: (target: ReachTarget) => void
  } = $props()

  const rssOn = $derived(show.rss === '1')
  const nostrOn = $derived(show.nostr === '1')
  const publicOn = $derived(show.public === '1')
  // a nostr-only show (rss off) is public too: its episodes are on relays and blossom
  const level = $derived<Level>(nostrOn || (rssOn && publicOn) ? 'public' : rssOn ? 'podcast' : 'vozonda')
  const noNostr = $derived(!!show.fixed) // the default show has no nostr key of its own

  // switching to public asks once; the channels can be picked while asking
  let asking = $state(false)
  let draftRss = $state(true)
  let draftNostr = $state(false)
  let confirmBtn = $state<HTMLButtonElement | null>(null)

  function choose(next: Level) {
    if (busy || next === level) return
    if (next === 'public') {
      draftRss = true
      draftNostr = false
      asking = true
      void tick().then(() => confirmBtn?.focus())
      return
    }
    asking = false
    onchoose(next === 'podcast' ? { rss: true, public: false, nostr: false } : { rss: false, public: false, nostr: false })
  }

  function confirmPublic() {
    if (!draftRss && !draftNostr) return
    asking = false
    onchoose({ rss: draftRss, public: true, nostr: draftNostr && !noNostr })
  }

  // a public show's channels change right away; at least one stays on
  function setChannel(which: 'rss' | 'nostr', on: boolean) {
    const rss = which === 'rss' ? on : rssOn
    const nostr = which === 'nostr' ? on : nostrOn
    if (!rss && !nostr) return
    onchoose({ rss, public: true, nostr })
  }

  const host = $derived.by(() => {
    try { return new URL(address.url).host } catch { return address.url || 'this address' }
  })
  const ownDevicesOnly = $derived(address.scope === 'this-computer' || address.scope === 'private-network')

  // one plain line: who can listen, and a warning when the choice cannot work from this address
  const status = $derived.by((): { text: string; warn: boolean } => {
    if (level === 'vozonda') return { text: 'episodes stay in the web ui; no feed, nothing published.', warn: false }
    if (level === 'podcast') {
      if (address.scope === 'this-computer')
        return { text: "your phone cannot reach this address; set it under 'address for other devices'.", warn: true }
      if (address.scope === 'private-network')
        return { text: `your own devices reach the feed at ${host}; anyone with the link (it carries a key) can listen.`, warn: false }
      return { text: 'anyone with the link can listen: it carries the key, so keep it on your own devices.', warn: false }
    }
    if (rssOn && ownDevicesOnly)
      return { text: `apple and spotify cannot reach ${host}: only your own devices do.`, warn: true }
    if (rssOn) return { text: 'anyone can listen: the feed is open and can be listed in podcast directories.', warn: false }
    return { text: 'public on nostr: the episodes are on relays and blossom servers; podcast apps do not see them.', warn: false }
  })
</script>

<div class="reach-card">
  <p class="lab mono reach-q" id={`reach-q-${show.slug}`}>who can listen to {show.name}?</p>
  <div class="seg reach-seg" role="radiogroup" aria-labelledby={`reach-q-${show.slug}`}>
    <button type="button" role="radio" aria-checked={level === 'vozonda'} class:sel={level === 'vozonda'}
      disabled={busy} onclick={() => choose('vozonda')}>only in vozonda</button>
    <button type="button" role="radio" aria-checked={level === 'podcast'} class:sel={level === 'podcast'}
      disabled={busy} onclick={() => choose('podcast')}>my podcast app</button>
    <button type="button" role="radio" aria-checked={level === 'public' || asking} class:sel={level === 'public'}
      class:pending={asking} disabled={busy} onclick={() => choose('public')}>public</button>
  </div>
  {#if level === 'podcast'}
    <p class="help">private feed: the link carries a key.</p>
  {/if}

  {#if asking}
    <div class="confirm-box" role="dialog" aria-modal="false" aria-labelledby={`pub-h-${show.slug}`} tabindex="-1"
      onkeydown={(e) => { if (e.key === 'Escape') asking = false }}>
      <p id={`pub-h-${show.slug}`} class="mono confirm-title">make {show.name} public?</p>
      <p class="help">anyone can listen; directories and apps may keep copies.</p>
      <label class="reach-check"><input type="checkbox" bind:checked={draftRss} />
        <span>rss feed: apple, spotify, every app; needs an internet address</span></label>
      <label class="reach-check"><input type="checkbox" bind:checked={draftNostr} disabled={noNostr} />
        <span>nostr: no server of your own; audio on blossom, public; mainstream podcast apps do not read it</span></label>
      {#if noNostr}<p class="help">no nostr here: the default show has no nostr key of its own.</p>{/if}
      <div class="confirm-actions">
        <button type="button" class="probe-btn mono active" bind:this={confirmBtn} disabled={!draftRss && !draftNostr}
          onclick={confirmPublic}>make it public</button>
        <button type="button" class="link mono" onclick={() => (asking = false)}>cancel</button>
      </div>
    </div>
  {:else if level === 'public'}
    <div class="reach-channels">
      <label class="reach-check"><input type="checkbox" checked={rssOn} disabled={busy || (rssOn && !nostrOn)}
        onchange={(e) => setChannel('rss', e.currentTarget.checked)} />
        <span>rss feed: apple, spotify, every app; needs an internet address</span></label>
      <label class="reach-check"><input type="checkbox" checked={nostrOn} disabled={busy || noNostr || (nostrOn && !rssOn)}
        onchange={(e) => setChannel('nostr', e.currentTarget.checked)} />
        <span>nostr: no server of your own; audio on blossom, public; mainstream podcast apps do not read it</span></label>
      {#if noNostr}<p class="help">no nostr here: the default show has no nostr key of its own.</p>{/if}
    </div>
  {/if}

  <p class="mono reach-status" class:warn={status.warn}>{status.text}</p>

  {#if level === 'public' && rssOn && !asking}
    <ul class="reach-checklist mono" aria-label="Ready for apple podcasts and spotify?">
      <li class:ok={address.scope === 'internet'}>{address.scope === 'internet' ? '✓' : '✗'} an internet address</li>
      <li class:ok={address.answers === true}>{address.answers === true ? '✓' : address.answers === false ? '✗' : '·'} it answers</li>
      <li>· square cover, owner e-mail, explicit flag:
        <a href="https://github.com/Vozonda/vozonda/issues/58" target="_blank" rel="noopener noreferrer">not yet supported</a></li>
    </ul>
  {/if}
</div>

<style>
  /* the settings' own look, repeated here: Svelte scopes styles per component */
  .seg { display: inline-flex; flex-wrap: wrap; max-width: 100%; border: 1px solid var(--line); border-radius: var(--radius); overflow: hidden; width: fit-content; }
  .seg button {
    flex: 1 1 auto; min-height: 44px; padding: var(--space-2) var(--space-3); border: none;
    border-right: 1px solid var(--line); border-bottom: 1px solid var(--line);
    background: color-mix(in srgb, var(--ink) 4%, var(--paper)); color: var(--ink-soft);
    font-family: var(--font-mono); font-size: var(--ui-size); font-weight: 500; cursor: pointer;
    transition: background var(--dur-fast) ease-out, color var(--dur-fast) ease-out;
  }
  .seg button.sel { background: var(--green); color: var(--paper); font-weight: 600; }
  .seg button.pending { outline: 2px dashed var(--green); outline-offset: -4px; }
  .seg button:disabled { cursor: default; opacity: 0.6; }
  .confirm-box {
    display: grid; gap: var(--space-2); padding: var(--space-3); border: 1px solid var(--line);
    border-left: 3px solid var(--green); border-radius: var(--radius); background: color-mix(in srgb, var(--ink) 3%, var(--paper));
  }
  .confirm-title { margin: 0; color: var(--ink); font-weight: 600; }
  .confirm-actions { display: flex; flex-wrap: wrap; align-items: center; gap: var(--space-3); }
  .probe-btn {
    display: inline-flex; align-items: center; padding: var(--space-1) var(--space-2); border: 1px solid var(--green);
    border-radius: var(--radius); background: color-mix(in srgb, var(--green) 12%, var(--paper)); color: var(--ink);
    font-family: var(--font-mono); font-size: calc(var(--ui-size) * 0.85); font-weight: 600; cursor: pointer;
  }
  .probe-btn:disabled { opacity: 0.5; cursor: default; }
  .help { margin: 0; color: var(--ink-soft); font-size: var(--ui-size); line-height: 1.45; }
  .lab { color: var(--ink-soft); }
  .link {
    background: transparent; border: none; padding: 0; min-height: 28px; cursor: pointer; color: var(--ink-soft);
    font-family: var(--font-mono); font-size: var(--ui-size); text-decoration: underline; text-decoration-color: var(--line);
  }
  .reach-card { display: grid; gap: var(--space-2); margin-top: var(--space-2); }
  .reach-q { margin: 0; }
  .reach-channels { display: grid; gap: var(--space-1); }
  .reach-check { display: flex; gap: var(--space-2); align-items: baseline; font-size: var(--ui-size); }
  .reach-status { margin: 0; font-size: var(--ui-size); color: var(--ink-soft); }
  .reach-status.warn { color: var(--danger); }
  .reach-checklist { list-style: none; margin: 0; padding: 0; display: grid; gap: 2px; font-size: var(--ui-size); color: var(--ink-soft); }
  .reach-checklist li.ok { color: var(--green); }
</style>

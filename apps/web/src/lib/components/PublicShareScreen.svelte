<script lang="ts">
  import Icon from './Icon.svelte'
  import Waveform from './Waveform.svelte'
  import ZapModal from './ZapModal.svelte'
  import type { DialogueLine } from '../api'

  interface Props {
    title: string
    src: string
    lines: DialogueLine[]
    jobId: string
    lightningAddress?: string
    recipientPubkey?: string
    createdAt?: number
    onBack?: () => void
  }

  let { title, src, lines, jobId, lightningAddress = '', recipientPubkey = '', createdAt, onBack }: Props = $props()

  let zapOpen = $state(false)
  let audio: HTMLAudioElement
  let playing = $state(false)
  let time = $state(0)
  let dur = $state(0)

  function fmt(s: number): string {
    const m = Math.floor(s / 60)
    const r = Math.floor(s % 60)
    return `${m}:${r.toString().padStart(2, '0')}`
  }

  const dateLabel = $derived.by(() => {
    if (!createdAt) return ''
    const d = new Date(createdAt * 1000)
    return d.toLocaleDateString('en-US', { month: 'short', day: 'numeric', year: 'numeric' })
  })

  function toggle() {
    if (!audio) return
    if (audio.paused) void audio.play()
    else audio.pause()
  }

  function seekFraction(f: number) {
    if (audio && dur > 0) audio.currentTime = f * dur
  }
</script>

<article class="pub">
  {#if onBack}
    <button class="mono back" onclick={onBack}><Icon name="back" size={13} /> back</button>
  {/if}
  <p class="mono kicker">// vozonda · shared episode</p>
  <h1>{title}</h1>
  <p class="mono meta">{dateLabel} · {lines.length} turns</p>

  <div class="player">
    <button class="play" onclick={toggle} aria-label={playing ? 'Pause' : 'Play'}>
      <Icon name={playing ? 'pausebars' : 'playtri'} size={18} />
    </button>
    <Waveform {src} currentTime={time} {playing} onseek={seekFraction} />
    <span class="mono time">{fmt(time)} / {fmt(dur)}</span>
  </div>

  <div class="actions mono">
    <button type="button" class="chip zap-chip" onclick={() => (zapOpen = true)} aria-label="Zap this episode">
      <Icon name="zap" size={13} /> zap the maker
    </button>
    <a href={src} download class="chip">download mp3</a>
    <span class="hint">NIP-57 zap via LNURL, signed with NIP-07 or Amber, paid via WebLN</span>
  </div>

  <ol class="transcript" aria-label="Episode transcript">
    {#each lines as line, i (i)}
      <li>
        <span class="speaker mono">{line.name ?? line.speaker}</span>
        <span class="text">{line.text}</span>
      </li>
    {/each}
  </ol>

  <footer class="mono foot">Created with vozonda · Sovereign AI · <a href="/">make your own</a></footer>
</article>

<ZapModal
  open={zapOpen}
  onClose={() => (zapOpen = false)}
  lightningAddress={lightningAddress}
  recipientPubkey={recipientPubkey}
  jobId={jobId}
  relays={['wss://relay.damus.io', 'wss://nos.lol']}
/>

<audio bind:this={audio} bind:currentTime={time} bind:duration={dur} onplay={() => (playing = true)} onpause={() => (playing = false)} {src}></audio>

<style>
  .pub { max-width: var(--content-max-width); margin: 0 auto; padding: var(--space-6) var(--space-4); display: grid; gap: var(--space-4); }
  .back { background: transparent; border: 1px solid var(--line); border-radius: var(--radius); padding: 4px 8px; cursor: pointer; color: var(--ink-soft); }
  .back:hover { border-color: var(--ink); color: var(--ink); }
  .kicker { color: var(--ink-soft); font-size: calc(var(--ui-size) * .82); }
  h1 { margin: var(--space-2) 0 0; font-size: var(--h1-size); line-height: var(--h1-line-height); }
  .meta { color: var(--ink-soft); margin: 0; }
  .player { display: flex; align-items: center; gap: var(--space-3); padding: var(--space-3); border: 1px solid var(--line); border-radius: var(--radius); }
  .play { width: 48px; height: 48px; border-radius: 50%; border: none; background: var(--green); color: var(--paper); display: grid; place-items: center; cursor: pointer; transition: background var(--dur-fast) ease-out; }
  .play:hover { background: color-mix(in srgb, var(--green) 85%, var(--ink)); color: var(--paper); }
  .time { min-width: 8ch; text-align: right; }
  .actions { display: flex; align-items: center; gap: var(--space-3); flex-wrap: wrap; }
  .chip { display: inline-flex; align-items: center; gap: 6px; background: transparent; border: 1px solid var(--line); border-radius: var(--radius); padding: 6px 10px; color: var(--ink-soft); font-family: var(--font-mono); font-size: var(--ui-size); cursor: pointer; text-decoration: none; min-height: 38px; }
  .chip:hover { border-color: var(--green); color: var(--ink); background: color-mix(in srgb, var(--green) 8%, var(--paper)); }
  .zap-chip { border-color: color-mix(in srgb, var(--green) 40%, var(--line)); color: var(--ink); }
  .zap-chip:hover { border-color: var(--green); color: var(--ink); background: color-mix(in srgb, var(--green) 12%, var(--paper)); }
  .hint { color: var(--ink-soft); font-size: calc(var(--ui-size) * .82); }
  .transcript { list-style: none; padding: 0; margin: 0; display: grid; gap: var(--space-2); }
  .transcript li { display: grid; gap: var(--space-1); padding: var(--space-2) var(--space-3); border-left: 2px solid transparent; }
  .speaker { color: var(--ink-soft); }
  .text { color: var(--ink); max-width: 65ch; }
  .foot { margin-top: var(--space-4); border-top: 1px solid var(--line); padding-top: var(--space-3); color: var(--ink-soft); font-size: var(--ui-size); }
  .foot a { color: var(--ink-soft); text-decoration: underline; }
  .foot a:hover { color: var(--green); }
</style>

<script lang="ts">
  export type WaveformPin = {
    id: string
    at: number
    kind: 'boost' | 'highlight'
    label: string
    detail?: string
    sats?: number
  }

  interface Props {
    src: string
    currentTime?: number
    playing?: boolean
    onseek?: (fraction: number) => void
    pins?: WaveformPin[]
  }

  let { src, currentTime = 0, playing = false, onseek, pins = [] }: Props = $props()

  let canvas: HTMLCanvasElement
  let duration = $state(0)
  let peaks = $state<number[]>([])
  let phase = $state(0)
  let activePinId = $state<string | null>(null)

  const BARS = 160

  $effect(() => {
    let cancelled = false
    let ctx: AudioContext | null = null
    const rawSrc = src ?? ''
    if (!rawSrc) return
    const peaksUrl = (rawSrc.split('?')[0] ?? rawSrc).replace(/\.mp3$/, '.peaks.json')
    const shouldCache = peaksUrl.startsWith('/audio/') && peaksUrl.endsWith('.peaks.json')

    async function load() {
      // 1) try cached peaks file next to the mp3: {id}.peaks.json
      try {
        const r = await fetch(peaksUrl)
        if (!cancelled && r.ok) {
          const cached = await r.json()
          const arr: unknown = Array.isArray(cached) ? cached : (cached as { peaks?: unknown }).peaks
          if (Array.isArray(arr) && arr.length === BARS) {
            const numeric = (arr as unknown[]).map((v) => Number(v))
            if (numeric.every((v) => Number.isFinite(v))) {
              peaks = numeric
              const dur = (cached as { duration?: unknown }).duration
              if (typeof dur === 'number' && Number.isFinite(dur) && dur > 0) {
                duration = dur
              }
              return
            }
          }
        }
      } catch {
        // cache miss -> fall through to decode
      }

      // 2) fallback: full decode, then cache as {id}.peaks.json on first decode
      ctx = new AudioContext()
      try {
        const r = await fetch(rawSrc)
        if (!r.ok) throw new Error(`fetch ${r.status}`)
        const buf = await r.arrayBuffer()
        const audio = await ctx.decodeAudioData(buf)
        if (cancelled) return
        duration = audio.duration
        const data = audio.getChannelData(0)
        const block = Math.floor(data.length / BARS)
        const next: number[] = []
        for (let i = 0; i < BARS; i++) {
          let sum = 0
          for (let j = 0; j < block; j += 32) {
            sum += Math.abs(data[i * block + j] ?? 0)
          }
          next.push(Math.min(1, (sum / (block / 32)) * 6))
        }
        peaks = next
        // store cache next to mp3 for next mount (fire-and-forget)
        if (shouldCache) {
          fetch(peaksUrl, {
            method: 'PUT',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ peaks: next, duration, bars: BARS })
          }).catch(() => {})
        }
      } catch {
        if (!cancelled) peaks = Array.from({ length: BARS }, () => 0.3)
      } finally {
        if (ctx) void ctx.close()
      }
    }

    void load()
    return () => {
      cancelled = true
      if (ctx) void ctx.close()
    }
  })

  $effect(() => {
    if (!playing) return
    const reduced = window.matchMedia('(prefers-reduced-motion: reduce)').matches
    if (reduced) return
    let raf = 0
    const tick = () => {
      phase = (phase + 0.08) % (Math.PI * 2)
      raf = requestAnimationFrame(tick)
    }
    raf = requestAnimationFrame(tick)
    return () => cancelAnimationFrame(raf)
  })

  $effect(() => {
    draw(currentTime, peaks, playing ? phase : -1)
  })

  let cachedColors = { played: '#76b900', idle: '#e4dccb' }

  $effect(() => {
    if (canvas) {
      const css = getComputedStyle(canvas)
      cachedColors = {
        played: css.getPropertyValue('--green-text').trim() || '#76b900',
        idle: css.getPropertyValue('--ink-soft').trim() || '#6b655b'
      }
    }
  })

  function draw(t: number, pks: number[], breath: number) {
    if (!canvas) return
    const dpr = window.devicePixelRatio || 1
    const w = canvas.clientWidth
    const h = canvas.clientHeight
    canvas.width = w * dpr
    canvas.height = h * dpr
    const g = canvas.getContext('2d')
    if (!g) return
    g.scale(dpr, dpr)
    g.clearRect(0, 0, w, h)

    const progress = duration > 0 ? t / duration : 0
    const barW = w / BARS
    for (let i = 0; i < BARS; i++) {
      const amp = pks[i] ?? 0.15
      const breathe = breath >= 0 ? 1 + Math.sin(breath + i * 0.12) * 0.08 : 1
      const bh = Math.max(3, amp * h * 0.9 * breathe)
      const x = i * barW + barW * 0.25
      const y = (h - bh) / 2
      g.fillStyle = i / BARS <= progress ? cachedColors.played : cachedColors.idle
      g.fillRect(x, y, Math.max(2, barW * 0.6), bh)
    }
  }

  function seek(e: MouseEvent) {
    if (!canvas || !onseek || duration <= 0) return
    const rect = canvas.getBoundingClientRect()
    onseek(Math.min(1, Math.max(0, (e.clientX - rect.left) / rect.width)))
  }

  function onKey(e: KeyboardEvent) {
    if (!onseek) return
    const d = duration > 0 ? duration : 90
    let f: number | null = null
    if (e.key === 'ArrowLeft') {
      e.preventDefault()
      f = Math.max(0, (currentTime - 5) / d)
    } else if (e.key === 'ArrowRight') {
      e.preventDefault()
      f = Math.min(1, (currentTime + 5) / d)
    } else if (e.key === 'Home') {
      e.preventDefault()
      f = 0
    } else if (e.key === 'End') {
      e.preventDefault()
      f = 1
    }
    if (f !== null) onseek(f)
  }

  // Pins: normalized offset plotting
  type PinView = WaveformPin & { pct: number }

  const visiblePins = $derived.by((): PinView[] => {
    if (!pins || pins.length === 0 || duration <= 0) return []
    const out: PinView[] = []
    for (const p of pins) {
      if (typeof p.at !== 'number' || !Number.isFinite(p.at)) continue
      if (p.at < 0 || p.at > duration) continue
      const pct = (p.at / duration) * 100
      if (!Number.isFinite(pct)) continue
      out.push({ ...p, pct: Math.max(0, Math.min(100, pct)) })
    }
    out.sort((a, b) => a.pct - b.pct)
    return out
  })

  function fmtTime(s: number): string {
    if (!Number.isFinite(s) || s < 0) return '0:00'
    const m = Math.floor(s / 60)
    const r = Math.floor(s % 60)
    return `${m}:${r.toString().padStart(2, '0')}`
  }

  function pinAriaLabel(p: WaveformPin): string {
    const t = fmtTime(p.at)
    if (p.kind === 'boost') {
      const sats = p.sats ? `${p.sats} sats` : 'boost'
      return `${sats} at ${t}: ${p.label}`
    }
    return `Highlight at ${t}: ${p.label}`
  }

  function handlePinKey(e: KeyboardEvent, idx: number) {
    if (e.key === 'Enter' || e.key === ' ') {
      e.preventDefault()
      const p = visiblePins[idx]
      if (p && onseek && duration > 0) onseek(p.at / duration)
      return
    }
    if (e.key === 'ArrowLeft' || e.key === 'ArrowRight') {
      e.preventDefault()
      const dir = e.key === 'ArrowLeft' ? -1 : 1
      const nextIdx = (idx + dir + visiblePins.length) % visiblePins.length
      const el = document.querySelector(`[data-pin-idx="${nextIdx}"]`) as HTMLElement | null
      el?.focus()
    }
    if (e.key === 'Escape') {
      activePinId = null
      ;(e.currentTarget as HTMLElement).blur()
    }
  }

  function handlePinSeek(p: PinView) {
    if (!onseek || duration <= 0) return
    onseek(p.at / duration)
  }
</script>

<div class="waveform-wrap">
  <canvas
    bind:this={canvas}
    class="wave"
    onclick={seek}
    onkeydown={onKey}
    role="slider"
    aria-label="Seek"
    aria-valuemin="0"
    aria-valuemax={duration}
    aria-valuenow={currentTime}
    tabindex="0"
  ></canvas>
  {#if visiblePins.length > 0}
    <div class="pins-layer" aria-label="Timeline markers">
      {#each visiblePins as pin, idx (pin.id)}
        <button
          type="button"
          class="pin pin--{pin.kind}"
          class:active={activePinId === pin.id}
          style="left: {pin.pct}%"
          data-pin-idx={idx}
          aria-label={pinAriaLabel(pin)}
          onmouseenter={() => (activePinId = pin.id)}
          onmouseleave={() => (activePinId = null)}
          onfocus={() => (activePinId = pin.id)}
          onblur={() => (activePinId = null)}
          onclick={() => handlePinSeek(pin)}
          onkeydown={(e) => handlePinKey(e, idx)}
        >
          <span class="pin-dot" aria-hidden="true"></span>
          <span class="pin-stem" aria-hidden="true"></span>
        </button>
      {/each}
      {#each visiblePins as pin (pin.id + '-tip')}
        {#if activePinId === pin.id}
          <div
            class="pin-tip"
            class:pin-tip--boost={pin.kind === 'boost'}
            class:pin-tip--highlight={pin.kind === 'highlight'}
            style="left: {pin.pct}%"
            role="tooltip"
          >
            <span class="pin-tip-time mono">{fmtTime(pin.at)}</span>
            {#if pin.kind === 'boost' && pin.sats}
              <span class="pin-tip-badge mono">{pin.sats} sats</span>
            {:else if pin.kind === 'highlight'}
              <span class="pin-tip-badge mono hl-badge">highlight</span>
            {:else}
              <span class="pin-tip-badge mono">{pin.kind}</span>
            {/if}
            <span class="pin-tip-label">{pin.label}</span>
            {#if pin.detail && pin.detail !== pin.label}
              <span class="pin-tip-detail">{pin.detail.slice(0, 120)}{pin.detail.length > 120 ? '...' : ''}</span>
            {/if}
            <span class="pin-tip-hint mono">click to jump</span>
          </div>
        {/if}
      {/each}
    </div>
  {/if}
</div>

<style>
  .waveform-wrap {
    position: relative;
    display: block;
    width: 100%;
  }
  .wave {
    display: block;
    width: 100%;
    height: 64px;
    cursor: pointer;
  }
  .pins-layer {
    position: absolute;
    inset: 0;
    pointer-events: none;
  }
  .pin {
    position: absolute;
    top: 0;
    bottom: 0;
    width: 28px;
    height: 100%;
    transform: translateX(-50%);
    background: transparent;
    border: none;
    padding: 0;
    cursor: pointer;
    pointer-events: auto;
    display: flex;
    flex-direction: column;
    align-items: center;
    justify-content: flex-start;
    touch-action: manipulation;
  }
  .pin-dot {
    width: 10px;
    height: 10px;
    border-radius: 50%;
    border: 2px solid var(--paper);
    box-shadow: 0 1px 4px rgba(0, 0, 0, 0.28);
    margin-top: 2px;
    flex-shrink: 0;
    transition: transform 120ms ease-out, box-shadow 120ms ease-out;
  }
  .pin-stem {
    width: 2px;
    flex: 1;
    min-height: 8px;
    opacity: 0.9;
    margin-top: 1px;
  }
  .pin--boost .pin-dot {
    background: #d9a441;
  }
  .pin--boost .pin-stem {
    background: color-mix(in srgb, #d9a441 88%, var(--line));
  }
  .pin--highlight .pin-dot {
    background: var(--green);
  }
  .pin--highlight .pin-stem {
    background: color-mix(in srgb, var(--green) 80%, transparent);
  }
  .pin:hover .pin-dot,
  .pin:focus-visible .pin-dot,
  .pin.active .pin-dot {
    transform: scale(1.25);
    box-shadow: 0 2px 8px rgba(0, 0, 0, 0.32);
  }
  .pin:focus-visible {
    outline: 2px solid var(--green);
    outline-offset: 2px;
    border-radius: 6px;
  }
  .pin-tip {
    position: absolute;
    bottom: calc(100% + 10px);
    transform: translateX(-50%);
    background: var(--paper);
    border: 1px solid color-mix(in srgb, var(--ink) 18%, var(--line));
    border-radius: 6px;
    padding: 8px 10px;
    min-width: 160px;
    max-width: 240px;
    display: flex;
    flex-direction: column;
    gap: 3px;
    box-shadow: 0 8px 24px rgba(0, 0, 0, 0.2);
    pointer-events: none;
    z-index: 5;
  }
  .pin-tip::after {
    content: '';
    position: absolute;
    top: 100%;
    left: 50%;
    transform: translateX(-50%);
    border: 6px solid transparent;
    border-top-color: var(--paper);
    filter: drop-shadow(0 1px 1px rgba(0, 0, 0, 0.12));
  }
  .pin-tip-time {
    font-size: calc(var(--ui-size) * 0.72);
    color: var(--ink-soft);
  }
  .pin-tip-badge {
    display: inline-flex;
    align-self: flex-start;
    font-size: calc(var(--ui-size) * 0.68);
    padding: 1px 6px;
    border-radius: 999px;
    background: color-mix(in srgb, var(--ink) 7%, var(--paper));
    border: 1px solid var(--line);
    color: var(--ink-soft);
  }
  .pin-tip--boost .pin-tip-badge {
    background: color-mix(in srgb, #d9a441 22%, var(--paper));
    border-color: color-mix(in srgb, #d9a441 45%, var(--line));
    color: #7a4e00;
  }
  .pin-tip--highlight .pin-tip-badge.hl-badge {
    background: color-mix(in srgb, var(--green) 16%, var(--paper));
    border-color: color-mix(in srgb, var(--green) 40%, var(--line));
    color: var(--green);
  }
  .pin-tip-label {
    font-family: var(--font-serif);
    font-size: 0.82rem;
    line-height: 1.35;
    color: var(--ink);
    display: -webkit-box;
    -webkit-line-clamp: 2;
    -webkit-box-orient: vertical;
    overflow: hidden;
  }
  .pin-tip-detail {
    font-family: var(--font-mono);
    font-size: calc(var(--ui-size) * 0.72);
    color: var(--ink-soft);
    line-height: 1.4;
    display: -webkit-box;
    -webkit-line-clamp: 2;
    -webkit-box-orient: vertical;
    overflow: hidden;
  }
  .pin-tip-hint {
    font-size: calc(var(--ui-size) * 0.68);
    color: var(--ink-soft);
    opacity: 0.85;
  }
  @media (max-width: 640px) {
    .pin {
      width: 36px;
    }
    .pin-dot {
      width: 12px;
      height: 12px;
    }
    .pin-tip {
      min-width: 148px;
      max-width: 200px;
      padding: 7px 9px;
    }
  }
  @media (prefers-color-scheme: dark) {
    .pin--boost .pin-dot {
      background: #e0b45c;
    }
    .pin--boost .pin-stem {
      background: color-mix(in srgb, #e0b45c 85%, var(--line));
    }
    .pin-tip--boost .pin-tip-badge {
      color: #e0b45c;
      background: color-mix(in srgb, #e0b45c 18%, var(--paper));
    }
  }
  @media (prefers-reduced-motion: reduce) {
    .pin-dot {
      transition: none;
    }
  }
</style>

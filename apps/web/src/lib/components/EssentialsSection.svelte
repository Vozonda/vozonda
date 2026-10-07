<script lang="ts">
  import type { Meta, VoiceProfile, ProviderStatus } from '../api'
  import { fetchProviders } from '../api'
  import { buildStyleGroups, buildStyleIcons, buildStyleDocs, categoryOf } from '../styles'
  import { timbreLabel } from '../timbreHelp'
  import Icon from './Icon.svelte'

  interface EssentialsProps {
    meta: Meta | null
    providers?: ProviderStatus | null
    values: {
      style: string
      format: 'dialog' | 'narration'
      language: string
      hosts: number
      explicit: boolean
      showId?: string
      showName?: string
    }
    voiceProfile: VoiceProfile
    onStyleChange: (style: string) => void
    onFormatChange: (format: 'dialog' | 'narration') => void
    onLanguageChange: (language: string) => void
    onHostsChange: (hosts: number) => void
    onExplicitChange: (explicit: boolean) => void
    onVoiceTimbreChange: (key: string, timbre: string) => void
    onVoiceEmotionChange: (key: string, emotion: string) => void
    onVoiceNameChange: (key: string, name: string) => void
    onProbePlay: (src: string, key: string) => void
    probeKey: string
    showVoices?: boolean
    showStyle?: boolean
    showFormat?: boolean
    showLanguage?: boolean
    showRating?: boolean
    watchlists?: { id: string; feed_url: string; style: string }[]
    selectedShow?: string
    onShowChange?: (showId: string) => void
    showName?: string
    onShowNameChange?: (showName: string) => void
    onResetStyle?: () => void
    onResetFormat?: () => void
    onResetHosts?: () => void
    defaultStyle?: string
    defaultFormat?: string
    defaultHosts?: number
    changedStyle?: boolean
    changedFormat?: boolean
    changedHosts?: boolean
  }

  let { meta, providers: providersProp = null, values, voiceProfile, onStyleChange, onFormatChange, onLanguageChange, onHostsChange, onExplicitChange, onVoiceTimbreChange, onVoiceEmotionChange, onVoiceNameChange, onProbePlay, probeKey, showVoices = true, showStyle = true, showFormat = true, showLanguage = true, showRating = true, watchlists = [], selectedShow = '', onShowChange, showName = '', onShowNameChange, onResetStyle, onResetFormat, onResetHosts, defaultStyle = 'balanced', defaultFormat = 'dialog', defaultHosts = 2, changedStyle = false, changedFormat = false, changedHosts = false }: EssentialsProps = $props()

  let providersLocal = $state<ProviderStatus | null>(providersProp)
  $effect(() => {
    if (providersProp) {
      providersLocal = providersProp
      return
    }
    void fetchProviders().then((p) => (providersLocal = p)).catch(() => {})
  })

  let advancedOpen = $state(false)
  // Helper to cast timbre entry to include sample_url (API may carry it)
  function sampleFor(t: { sample_url?: string | null }): string | null {
    return t.sample_url ?? null
  }

  // the test button plays the selected voice's recorded sample when the engine has one,
  // else the generated probe (one button per voice instead of a strip of every voice)
  function testUrl(timbreId: string | undefined): string {
    const t = timbres.find((x) => x.id === timbreId) as { sample_url?: string | null } | undefined
    return (t && sampleFor(t)) || `/audio/probe-${timbreId ?? 'aiden'}.mp3`
  }

  // Style groups, icons and docs come from GET /meta style_meta
  // (lib/styles.ts), with an offline fallback when /meta is unreachable.
  const styleGroups = $derived(buildStyleGroups(meta))
  const styleIcons = $derived(buildStyleIcons(meta))

  function categoryOfStyle(style: string): string {
    return categoryOf(style, meta)
  }

  const styleDocs = $derived(buildStyleDocs(meta))

  const timbreKey = (v: string) => `${v}.timbre` as 'a.timbre' | 'b.timbre' | 'c.timbre'
  const nameKey = (v: string) => `${v}.name` as 'a.name' | 'b.name' | 'c.name'
  const emotionKey = (v: string) => `${v}.emotion` as 'a.emotion' | 'b.emotion' | 'c.emotion' | 'solo.emotion'
  // neutral is the default: name it as such so the dropdown reads as an emotion control
  const emotionLabel = (em: { id: string; help: string }): string =>
    em.id === 'neutral' ? 'default emotion · neutral' : `${em.id}${em.help ? ` · ${em.help}` : ''}`

  const emotions = $derived(meta?.emotions ?? [{ id: 'neutral', help: '' }])
  const currentEngine = $derived(meta?.runtime?.tts_engine ?? 'qwen_tts')
  const timbres = $derived(
    (meta?.speaker_tables && meta.speaker_tables[currentEngine]) || meta?.timbres || []
  )
  const kokoroGroups = $derived.by(() => {
    if (currentEngine !== 'kokoro') return null
    const groups: {
      'American Female': typeof timbres
      'American Male': typeof timbres
      'British Female': typeof timbres
      'British Male': typeof timbres
    } = {
      'American Female': [],
      'American Male': [],
      'British Female': [],
      'British Male': []
    }
    for (const t of timbres) {
      if (t.id.startsWith('af_')) groups['American Female'].push(t)
      else if (t.id.startsWith('am_')) groups['American Male'].push(t)
      else if (t.id.startsWith('bf_')) groups['British Female'].push(t)
      else if (t.id.startsWith('bm_')) groups['British Male'].push(t)
      else groups['American Female'].push(t)
    }
    return groups
  })
  const ttsEngines = $derived((providersLocal?.providers ?? []).filter((p) => p.id !== 'qwen_vllm'))
  const currentEngineInfo = $derived(ttsEngines.find((e) => e.id === currentEngine) ?? null)

  const languages = $derived(meta?.languages ?? {})

  const showOptions = $derived(watchlists.length > 0 ? watchlists : [])

  function domainOf(url: string): string {
    try {
      return new URL(url).hostname.replace(/^www\./, '')
    } catch {
      return url
    }
  }

  function detectGender(tId: string, label: string): 'female' | 'male' | 'user' {
    const l = (label || '').toLowerCase()
    const id = (tId || '').toLowerCase()
    if (l.includes('(f)') || l.includes('female') || id.startsWith('af_') || id.startsWith('bf_') || id.includes('female')) return 'female'
    if (l.includes('(m)') || l.includes('male') || id.startsWith('am_') || id.startsWith('bm_') || id.includes('male')) return 'male'
    return 'user'
  }

  const activeLineup = $derived.by(() => {
    if (values.format === 'narration') {
      const tId = voiceProfile['solo.timbre'] ?? 'aiden'
      const tObj = timbres.find((t) => t.id === tId)
      const tLabel = tObj?.label ?? tId
      const custom = (voiceProfile['solo.name'] || '').trim()
      const em = voiceProfile['solo.emotion'] ?? 'neutral'
      const gender = detectGender(tId, tLabel)
      return [{
        key: 'solo',
        displayName: custom || 'Narrator',
        timbreId: tId,
        timbreName: tObj?.label ? (tObj.label.split('·')[0] ?? tId).trim() : tId,
        gender,
        emotion: em,
      }]
    }
    const hostKeys = (['a', 'b', 'c'] as const).slice(0, values.hosts)
    return hostKeys.map((k) => {
      const tId = voiceProfile[timbreKey(k)] ?? (k === 'a' ? 'aiden' : (k === 'b' ? 'ryan' : 'sarah'))
      const tObj = timbres.find((t) => t.id === tId)
      const tLabel = tObj?.label ?? tId
      const custom = (voiceProfile[nameKey(k)] || '').trim()
      const em = voiceProfile[emotionKey(k)] ?? 'neutral'
      const gender = detectGender(tId, tLabel)
      return {
        key: k,
        displayName: custom || `Host ${k.toUpperCase()}`,
        timbreId: tId,
        timbreName: tObj?.label ? (tObj.label.split('·')[0] ?? tId).trim() : tId,
        gender,
        emotion: em,
      }
    })
  })

  $effect(() => {
    const list = timbres
    if (list && list.length > 0 && list[0]) {
      const firstId = list[0].id
      if (values.format === 'narration') {
        const cur = voiceProfile['solo.timbre']
        if (!cur || !list.some((t) => t.id === cur)) {
          onVoiceTimbreChange('solo.timbre', firstId)
        }
      } else {
        const keys = ['a.timbre', 'b.timbre', 'c.timbre']
        keys.slice(0, values.hosts).forEach((k, idx) => {
          const cur = voiceProfile[k as keyof VoiceProfile]
          if (!cur || !list.some((t) => t.id === cur)) {
            const fallback = list[Math.min(idx, list.length - 1)]?.id ?? firstId
            onVoiceTimbreChange(k, fallback)
          }
        })
      }
    }
  })
</script>

<div class="essentials">
  {#if showStyle}
  <section class="ess {values.style ? 'g-' + categoryOfStyle(values.style) : ''}" aria-labelledby="ess-style-h">
    <h2 id="ess-style-h" class="mono ess-h"><Icon name="style" size={18} /> style</h2>
    <p class="mono style-help">how the script is written (persona, turn length, vocabulary)</p>
    {#each styleGroups as group (group.key)}
      <div class="style-group g-{group.key}">
        <span class="group-label mono" title="category">{group.label}</span>
        <div class="seg seg-wrap" role="radiogroup" aria-label="Style: {group.label}">
          {#each group.styles as s (s)}
            <button type="button" role="radio" aria-checked={values.style === s} class:sel={values.style === s}
              onclick={() => onStyleChange(s)}>{s.replace(/_/g, ' ')}</button>
          {/each}
        </div>
      </div>
    {/each}
    {#if values.style}
      {#key values.style}
        <div class="styledoc-box" role="note">
          <Icon name={styleIcons[values.style] ?? 'balanced'} size={27} />
          <p class="styledoc-text">
            {styleDocs[values.style] ?? `no description yet for ${values.style}`}
          </p>
          {#if onResetStyle}
            <div class="style-defaults">
              {#if changedStyle}
                <span class="changed-marker">changed</span>
                <button type="button" class="link mono back-to-default" onclick={onResetStyle}>back to default</button>
              {:else}
                <span class="default-marker">(default)</span>
              {/if}
            </div>
          {/if}
        </div>
      {/key}
    {/if}
  </section>
  {/if}

  {#if showVoices}
  <section class="ess" aria-labelledby="ess-voices-h">
    <h2 id="ess-voices-h" class="mono ess-h"><Icon name="voices" size={18} /> voices</h2>
    <p class="mono help" style="font-size: calc(var(--ui-size) * 0.85); color: var(--ink-soft); margin-bottom: var(--space-2);">
      customize host voices, speaking tone, and names. tap test to listen.
    </p>
    {#if currentEngineInfo}
      <p class="mono help" style="font-size: calc(var(--ui-size) * 0.78); color: var(--ink-soft);">
        engine: {currentEngineInfo.label}{currentEngineInfo.ui_badge ? ` · ${currentEngineInfo.ui_badge}` : ''}{currentEngineInfo.license ? ` · ${currentEngineInfo.license}` : ''}{currentEngineInfo.commercial_use === false ? ' · non-commercial' : ''}{!currentEngineInfo.installed ? ` · ${currentEngineInfo.ui_fix_hint ?? currentEngineInfo.fix}` : ''}
      </p>
    {/if}
    {#if showFormat}
    <div class="seg" role="radiogroup" aria-label="Episode format">
      <button type="button" role="radio" aria-checked={values.format === 'dialog'} class:sel={values.format === 'dialog'}
        onclick={() => onFormatChange('dialog')}>conversation</button>
      <button type="button" role="radio" aria-checked={values.format === 'narration'} class:sel={values.format === 'narration'}
        onclick={() => onFormatChange('narration')}>read aloud</button>
    </div>
    {#if onResetFormat}
      <div class="format-defaults">
        {#if changedFormat}
          <span class="changed-marker">changed</span>
          <button type="button" class="link mono back-to-default" onclick={onResetFormat}>back to default</button>
        {:else}
          <span class="default-marker">(default)</span>
        {/if}
      </div>
    {/if}
    {/if}

    {#if values.format === 'narration'}
      <div class="voice-head mono" aria-hidden="true">
        <span class="vh-play">test</span>
        <span class="vh-voice">timbre</span>
        <span class="vh-name">name</span>
      </div>
      <div class="voice-row mono">
        <button type="button" class="mono play-btn" class:playing={probeKey === 'solo'}
          title={probeKey === 'solo' ? 'Pause narrator' : 'Play narrator'}
          aria-label={probeKey === 'solo' ? 'Pause narrator probe' : 'Play narrator probe'}
          onclick={() => onProbePlay(testUrl(voiceProfile['solo.timbre']), 'solo')}>
          <Icon name={probeKey === 'solo' ? 'pausebars' : 'playtri'} size={16} />
        </button>
        <div class="voice-select-wrap">
          <select class="voice-select" aria-label="Narrator voice" bind:value={voiceProfile['solo.timbre']} onchange={(e) => onVoiceTimbreChange('solo.timbre', e.currentTarget.value)}>
            {#if kokoroGroups}
              {#each Object.entries(kokoroGroups) as [group, list] (group)}
                {#if list.length > 0}
                  <optgroup label={group}>
                    {#each list as t (t.id)}
                      <option value={t.id}>{timbreLabel(t.id, timbres)}</option>
                    {/each}
                  </optgroup>
                {/if}
              {/each}
            {:else}
              {#each timbres as t (t.id)}
                <option value={t.id}>{timbreLabel(t.id, timbres)}</option>
              {/each}
            {/if}
          </select>
        </div>
      </div>
      <div class="voice-sub mono">
        <select class="voice-select" aria-label="Narrator emotion" bind:value={voiceProfile[emotionKey('solo')]} onchange={(e) => onVoiceEmotionChange(emotionKey('solo'), e.currentTarget.value)}>
          {#each emotions as em (em.id)}
            <option value={em.id}>{emotionLabel(em)}</option>
          {/each}
        </select>
        <input
          class="mono name-input"
          type="text"
          maxlength="24"
          placeholder="custom name"
          aria-label="Custom name for narrator"
          bind:value={voiceProfile['solo.name']}
          oninput={(e) => onVoiceNameChange('solo.name', e.currentTarget.value)}
        />
      </div>
    {:else}
      <div class="seg" role="radiogroup" aria-label="How many hosts">
        {#each [1, 2, 3] as n (n)}
          <button type="button" role="radio" aria-checked={values.hosts === n} class:sel={values.hosts === n}
            onclick={() => onHostsChange(n)}>{n}</button>
        {/each}
      </div>
      {#if onResetHosts}
        <div class="hosts-defaults">
          {#if changedHosts}
            <span class="changed-marker">changed</span>
            <button type="button" class="link mono back-to-default" onclick={onResetHosts}>back to default</button>
          {:else}
            <span class="default-marker">(default)</span>
          {/if}
        </div>
      {/if}
      <div class="voice-head mono" aria-hidden="true">
        <span class="vh-play">test</span>
        <span class="vh-voice">timbre</span>
        <span class="vh-name">name</span>
      </div>
      {#each ['a', 'b', 'c'].slice(0, values.hosts) as v (v)}
        <div class="voice-row mono">
          <button type="button" class="mono play-btn" class:playing={probeKey === v}
            title={probeKey === v ? `Pause host ${v.toUpperCase()}` : `Play host ${v.toUpperCase()}`}
            aria-label={probeKey === v ? `Pause host ${v.toUpperCase()} probe` : `Play host ${v.toUpperCase()} probe`}
            onclick={() => onProbePlay(testUrl(voiceProfile[timbreKey(v)]), v)}>
            <Icon name={probeKey === v ? 'pausebars' : 'playtri'} size={16} />
          </button>
          <div class="voice-select-wrap">
            <select class="voice-select" aria-label={`Host ${v.toUpperCase()} voice`} bind:value={voiceProfile[timbreKey(v)]} onchange={(e) => onVoiceTimbreChange(timbreKey(v), e.currentTarget.value)}>
              {#if kokoroGroups}
                {#each Object.entries(kokoroGroups) as [group, list] (group)}
                  {#if list.length > 0}
                    <optgroup label={group}>
                      {#each list as t (t.id)}
                        <option value={t.id}>{timbreLabel(t.id, timbres)}</option>
                      {/each}
                    </optgroup>
                  {/if}
                {/each}
              {:else}
                {#each timbres as t (t.id)}
                  <option value={t.id}>{timbreLabel(t.id, timbres)}</option>
                {/each}
              {/if}
            </select>
          </div>
        </div>
        <div class="voice-sub mono">
          <select class="voice-select" aria-label={`Host ${v.toUpperCase()} emotion`} bind:value={voiceProfile[emotionKey(v)]} onchange={(e) => onVoiceEmotionChange(emotionKey(v), e.currentTarget.value)}>
            {#each emotions as em (em.id)}
              <option value={em.id}>{emotionLabel(em)}</option>
            {/each}
          </select>
          <input
            class="mono name-input"
            type="text"
            maxlength="24"
            placeholder="custom name"
            aria-label={`Custom name for host ${v.toUpperCase()}`}
            bind:value={voiceProfile[nameKey(v)]}
            oninput={(e) => onVoiceNameChange(nameKey(v), e.currentTarget.value)}
          />
        </div>
      {/each}
    {/if}

    <div class="lineup-card mono" role="region" aria-label="Your hosts lineup">
      <div class="lineup-head">
        <span class="lineup-kicker">// host lineup</span>
        <span class="lineup-count">{values.format === 'narration' ? '1 narrator' : `${values.hosts} ${values.hosts === 1 ? 'host' : 'hosts'}`}</span>
      </div>
      <div class="lineup-pills">
        {#each activeLineup as host (host.key)}
          <div class="lineup-pill">
            <span class="pill-avatar" aria-hidden="true">
              <Icon name={host.gender === 'female' ? 'female' : (host.gender === 'male' ? 'male' : 'user')} size={13} />
            </span>
            <div class="pill-body">
              <span class="pill-name">{host.displayName}</span>
              <span class="pill-meta">
                <span class="pill-timbre">{host.timbreName}</span>
                {#if host.emotion && host.emotion !== 'neutral'}
                  <span class="pill-dot">·</span>
                  <span class="pill-emotion">{host.emotion}</span>
                {/if}
              </span>
            </div>
          </div>
        {/each}
      </div>
    </div>
  </section>
  {/if}

  <details class="advanced-details mono" bind:open={advancedOpen}>
    <summary class="advanced-summary">
      <span class="advanced-summary-left">
        <Icon name={advancedOpen ? 'sliders' : 'plus'} size={14} />
        <span>episode options: {showLanguage ? 'series, feed, language' : 'series, feed'}</span>
      </span>
      <span class="advanced-summary-badge">
        {#if values.language && values.language !== 'auto'}
          <span class="adv-badge">{values.language}</span>
        {/if}
        {#if showName || values.showName}
          <span class="adv-badge" title={showName || values.showName}>{showName || values.showName}</span>
        {/if}
      </span>
    </summary>
    <div class="advanced-body">
      <div class="opt">
        <label class="lab mono" for="c-show-name">series / playlist (optional)</label>
        <input
          id="c-show-name"
          class="mono text-in show-name-input"
          type="text"
          maxlength="80"
          placeholder="e.g. Paper Reviews, Deep Dive..."
          value={showName ?? values.showName ?? ''}
          oninput={(e) => onShowNameChange?.(e.currentTarget.value)}
          aria-label="Series or playlist name"
        />
        <p class="help">leave empty to publish to your default podcast. sets an episode category tag and generates a separate series RSS feed.</p>
      </div>

      {#if showOptions.length > 0}
        <div class="opt">
          <label class="lab mono" for="c-show">linked show (watchlist)</label>
          <select id="c-show" class="voice-select" value={selectedShow} onchange={(e) => onShowChange?.(e.currentTarget.value)}>
            <option value="">none (standalone episode)</option>
            {#each showOptions as w (w.id)}
              <option value={w.id}>{domainOf(w.feed_url)}</option>
            {/each}
          </select>
          <p class="help">link to a watched feed to group under that show rss</p>
        </div>
      {/if}

      {#if showLanguage}
        <div class="opt">
          <label class="lab mono" for="c-lang">translate to</label>
          <select id="c-lang" class="voice-select" bind:value={values.language} onchange={(e) => onLanguageChange(e.currentTarget.value)}>
            <option value="auto">auto (source language)</option>
            {#each Object.entries(languages) as [code, name] (code)}
              <option value={code}>{name}</option>
            {/each}
          </select>
          <p class="help">output language of the episode</p>
        </div>
      {/if}

      {#if showRating}
        <div class="opt">
          <label class="lab mono" for="c-rating">content rating</label>
          <div id="c-rating" class="seg" role="radiogroup" aria-label="Content rating">
            <button type="button" role="radio" aria-checked={!values.explicit} class:sel={!values.explicit}
              onclick={() => onExplicitChange(false)}>clean</button>
            <button type="button" role="radio" aria-checked={values.explicit} class:sel={values.explicit} class:risk={values.explicit}
              onclick={() => onExplicitChange(true)}>18+ unfiltered</button>
          </div>
          <p class="help">unfiltered: swearing allowed, no sugarcoating. episodes get tagged 18+.</p>
        </div>
      {/if}

    </div>
  </details>
</div>


<style>
  .essentials {
    max-width: 100%;
    overflow-x: hidden;
  }

  .seg-wrap {
    display: grid;
    grid-template-columns: repeat(auto-fill, minmax(7.5em, 1fr));
    gap: var(--space-2);
  }



  .seg-wrap button {
    text-align: center;
  }

  .seg button {
    background: color-mix(in srgb, var(--ink) 4%, var(--paper));
    border: 1px solid color-mix(in srgb, var(--ink) 18%, var(--line));
    border-radius: var(--radius);
    color: var(--ink-soft);
    font-family: var(--font-mono);
    font-size: var(--ui-size);
    font-weight: 500;
    padding: var(--space-2) var(--space-3);
    cursor: pointer;
    min-height: 44px;
    box-shadow: 0 1px 2px rgba(0, 0, 0, 0.04);
    transition: color var(--dur-fast) ease-out, border-color var(--dur-fast) ease-out, background var(--dur-fast) ease-out, box-shadow var(--dur-fast) ease-out;
  }

  .seg button:hover:not(.sel):not([aria-checked="true"]) {
    color: var(--ink);
    border-color: var(--ink);
    background: color-mix(in srgb, var(--ink) 8%, var(--paper));
    box-shadow: 0 1px 3px rgba(0, 0, 0, 0.08);
  }

  .g-learn .seg button.sel { color: var(--paper); border-color: var(--style-learn); background: var(--style-learn); }
  .g-mood .seg button.sel { color: var(--paper); border-color: var(--style-mood); background: var(--style-mood); }
  .g-drama .seg button.sel { color: var(--paper); border-color: var(--style-drama); background: var(--style-drama); }
  .g-play .seg button.sel { color: var(--paper); border-color: var(--style-play); background: var(--style-play); }

  .seg:not(.style-group .seg) > button.sel,
  .seg:not(.style-group .seg) > button[aria-checked="true"] {
    background: var(--green);
    color: var(--paper);
    border-color: var(--green);
    font-weight: 600;
    box-shadow: 0 2px 4px rgba(0, 0, 0, 0.12);
  }

  .seg:not(.style-group .seg) > button.sel:hover,
  .seg:not(.style-group .seg) > button[aria-checked="true"]:hover {
    background: color-mix(in srgb, var(--green) 90%, var(--ink));
    border-color: var(--green);
    color: var(--paper);
  }

  .seg button.risk {
    color: var(--danger);
    border-color: color-mix(in srgb, var(--danger) 40%, var(--line));
    background: color-mix(in srgb, var(--danger) 6%, var(--paper));
  }

  .seg button.risk:hover {
    border-color: var(--danger);
    background: color-mix(in srgb, var(--danger) 12%, var(--paper));
  }

  .seg button.risk.sel {
    background: var(--danger-fill);
    border-color: var(--danger-fill);
    color: #ffffff;
    font-weight: 600;
    box-shadow: 0 2px 4px rgba(0, 0, 0, 0.2);
  }

  /* style category grid: 6.5em label column left of the chips.
     agreed layout 2026-08-24, restored after dead-code sweep.
     contract: docs/design.md "compose style system" - do not remove. */
  .style-group {
    display: grid;
    grid-template-columns: 6.5em 1fr;
    gap: var(--space-3);
    align-items: start;
    min-width: 0;
  }

  @media (max-width: 480px) {
    .seg-wrap {
      grid-template-columns: repeat(auto-fill, minmax(6em, 1fr));
    }
    /* label stacks above chips when the 6.5em column would squeeze them */
    .style-group {
      grid-template-columns: 1fr;
      gap: var(--space-2);
    }
  }

  @media (max-width: 380px) {
    .seg-wrap {
      grid-template-columns: 1fr 1fr;
    }
  }

  /* uppercase category label, inherits the category color from .g-* below */
  .group-label {
    display: inline-flex;
    align-items: center;
    gap: var(--space-1);
    font-size: calc(var(--ui-size) * 0.78);
    text-transform: uppercase;
    letter-spacing: 0.12em;
    cursor: default;
    user-select: none;
    padding-top: var(--space-1);
  }

  /* category color coding: colors the label, the selected chip and the
     styledoc icon (inherit). used by .g-* rules below. keep in sync with
     tokens.css --style-* and docs/design.md. */
  .g-learn { color: var(--style-learn); }
  .g-mood { color: var(--style-mood); }
  .g-drama { color: var(--style-drama); }
  .g-play { color: var(--style-play); }


  .seg button.risk {
    color: var(--danger);
    border-color: var(--danger);
  }

  .seg button.risk.sel {
    background: var(--danger-fill);
    border-color: var(--danger-fill);
    color: #0a0a0a;
  }

  .voice-sub {
    display: grid;
    grid-template-columns: minmax(0, 1fr) minmax(0, 1fr);
    gap: var(--space-3);
    margin-left: calc(48px + var(--space-3));
    margin-top: var(--space-2);
    min-width: 0;
  }

  @media (max-width: 380px) {
    .voice-sub {
      grid-template-columns: 1fr;
      margin-left: 0;
    }
    /* stacked rows make column headers useless */
    .voice-head {
      display: none;
    }
  }

  .show-name-input {
    width: 100%;
    min-width: 0;
  }

  .name-input {
    width: 100%;
    min-width: 0;
  }

  .help {
    font-family: var(--font-mono);
    font-size: calc(var(--ui-size) * 0.85);
    color: var(--ink-soft);
    margin: 0;
  }

  .lang-row {
    display: flex;
    align-items: center;
    gap: var(--space-2);
    flex-wrap: wrap;
  }

  .lab {
    color: var(--ink-soft);
    font-size: calc(var(--ui-size) * 0.9);
  }

  .voice-select {
    font-family: var(--font-mono);
    font-size: var(--ui-size);
    /* long timbre labels must not stretch the card on narrow screens */
    width: 100%;
    min-width: 0;
  }

  .voice-row .voice-select {
    flex: 1 1 0;
  }

  .voice-select-wrap {
    flex: 1 1 0;
    display: flex;
    gap: var(--space-2);
    align-items: center;
    min-width: 0;
  }

  .voice-row {
    display: flex;
    gap: var(--space-2);
    align-items: center;
    min-width: 0;
  }

  .play-btn {
    flex-shrink: 0;
    width: 48px;
    height: 48px;
    border-radius: 50%;
    border: none;
    background: var(--green);
    color: var(--paper);
    font-size: 0.85rem;
    cursor: pointer;
    display: inline-flex;
    align-items: center;
    justify-content: center;
    transition: background var(--dur-fast) ease-out, color var(--dur-fast) ease-out;
  }

  .play-btn:hover {
    background: color-mix(in srgb, var(--green) 85%, var(--ink));
    color: var(--paper);
  }

  .play-btn.playing {
    background: color-mix(in srgb, var(--green) 85%, var(--ink));
    color: var(--paper);
  }

  .play-btn :global(svg) {
    margin-left: 2px;
  }

  .voice-head {
    display: grid;
    grid-template-columns: 48px 1fr 1fr;
    gap: var(--space-3);
    align-items: center;
    min-width: 0;
    font-size: calc(var(--ui-size) * 0.78);
    color: var(--ink-soft);
    letter-spacing: 0.06em;
  }

  .vh-play {
    text-align: center;
  }

  .optional-note {
    color: var(--ink-soft);
    font-size: calc(var(--ui-size) * 0.85);
    margin: 0;
  }

  /* --- style system (shared with App.svelte compose) ---
     single source of truth lives above with the guard comments;
     do not re-add copies of these rules further down the file. */

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

  .ess {
    border: 1px solid var(--line);
    border-radius: var(--radius);
    padding: var(--space-5);
    display: grid;
    gap: var(--space-4);
    min-width: 0;
    margin-bottom: var(--space-5);
    background: color-mix(in srgb, var(--paper) 4%, transparent);
  }

  .ess:last-of-type {
    margin-bottom: 0;
  }

  /* style explanation box: centered, serif italic, 27px icon inherits the
     category color from the .g-* class on the box. agreed look 2026-08-24,
     restored after dead-code sweep. contract: docs/design.md - do not flatten
     to a flex row or drop the centering. */
  .styledoc-box {
    display: grid;
    justify-items: center;
    gap: var(--space-2);
    border: 1px solid var(--line);
    border-radius: var(--radius);
    padding: var(--space-4);
    margin-top: var(--space-3);
    animation: styledocFade var(--dur-slow) ease-out;
  }

  .styledoc-text {
    margin: 0;
    font-family: var(--font-serif);
    font-style: italic;
    font-size: calc(var(--ui-size) * 1.08);
    color: var(--ink);
    text-align: center;
    max-width: 34em;
    line-height: 1.45;
  }

  @keyframes styledocFade {
    from { opacity: 0; transform: translateY(2px); }
    to { opacity: 1; transform: translateY(0); }
  }

  .ess.g-learn .styledoc-box { border-color: var(--style-learn); }
  .ess.g-mood .styledoc-box { border-color: var(--style-mood); }
  .ess.g-drama .styledoc-box { border-color: var(--style-drama); }
  .ess.g-play .styledoc-box { border-color: var(--style-play); }

  .settings-cta-row {
    margin-top: var(--space-4);
    padding-top: var(--space-3);
    border-top: 1px solid var(--line);
    display: flex;
    align-items: center;
    gap: var(--space-2);
  }

  .settings-cta {
    background: transparent;
    border: 1px solid var(--line);
    border-radius: var(--radius);
    color: var(--ink-soft);
    font-family: var(--font-mono);
    font-size: var(--ui-size);
    padding: var(--space-2) var(--space-3);
    cursor: pointer;
    display: inline-flex;
    align-items: center;
    gap: var(--space-2);
    min-height: 44px;
  }

  .settings-cta:hover {
    border-color: var(--ink-soft);
    color: var(--ink);
  }

  .cta-hint {
    color: var(--ink-soft);
    font-size: calc(var(--ui-size) * 0.85);
  }

  .lineup-card {
    margin-top: var(--space-4);
    padding: var(--space-3) var(--space-4);
    background: color-mix(in srgb, var(--green) 5%, var(--paper));
    border: 1px solid color-mix(in srgb, var(--green) 25%, var(--line));
    border-radius: var(--radius);
    display: flex;
    flex-direction: column;
    gap: var(--space-2);
  }

  .lineup-head {
    display: flex;
    justify-content: space-between;
    align-items: center;
    font-size: calc(var(--ui-size) * 0.85);
  }

  .lineup-kicker {
    color: var(--green);
    letter-spacing: 0.04em;
    font-weight: 500;
  }

  .lineup-count {
    color: var(--ink-soft);
  }

  .lineup-pills {
    display: flex;
    flex-wrap: wrap;
    gap: var(--space-2);
  }

  .lineup-pill {
    display: inline-flex;
    align-items: center;
    gap: var(--space-2);
    padding: 6px 12px;
    background: color-mix(in srgb, var(--ink) 4%, var(--paper));
    border: 1px solid color-mix(in srgb, var(--ink) 12%, var(--line));
    border-radius: var(--radius);
    font-size: var(--ui-size);
  }

  .pill-avatar {
    color: var(--green);
    display: flex;
    align-items: center;
  }

  .pill-body {
    display: flex;
    align-items: baseline;
    gap: 6px;
    flex-wrap: wrap;
  }

  .pill-name {
    color: var(--ink);
    font-weight: 600;
  }

  .pill-meta {
    font-size: calc(var(--ui-size) * 0.88);
    color: var(--ink-soft);
    display: flex;
    align-items: baseline;
    gap: 4px;
  }

  .pill-dot {
    opacity: 0.5;
  }

  .pill-emotion {
    color: color-mix(in srgb, var(--green) 75%, var(--ink));
  }

  .advanced-details {
    margin-top: var(--space-4);
    border: 1px dashed var(--line);
    border-radius: var(--radius);
    background: color-mix(in srgb, var(--ink) 2%, var(--paper));
    transition: background-color var(--dur-fast) ease-out, border-color var(--dur-fast) ease-out;
  }

  .advanced-details[open] {
    border-style: solid;
    border-color: color-mix(in srgb, var(--ink) 20%, var(--line));
    background: color-mix(in srgb, var(--ink) 3%, var(--paper));
  }

  .advanced-summary {
    padding: var(--space-3) var(--space-4);
    cursor: pointer;
    display: flex;
    justify-content: space-between;
    align-items: center;
    font-size: var(--ui-size);
    color: var(--ink-soft);
    user-select: none;
    list-style: none;
  }

  .advanced-summary::-webkit-details-marker {
    display: none;
  }

  .advanced-summary:hover {
    color: var(--ink);
  }

  .advanced-summary-left {
    display: flex;
    align-items: center;
    gap: var(--space-2);
  }

  .advanced-summary-badge {
    display: flex;
    align-items: center;
    gap: var(--space-1);
    min-width: 0;
    flex: 0 1 auto;
  }

  .adv-badge {
    font-size: calc(var(--ui-size) * 0.8);
    background: color-mix(in srgb, var(--green) 12%, var(--paper));
    color: var(--ink);
    border: 1px solid color-mix(in srgb, var(--green) 30%, var(--line));
    padding: 2px 6px;
    border-radius: var(--radius);
    /* a long series name must not turn into a wrapped box (owner screenshot 2026-09-25) */
    max-width: 22ch;
    overflow: hidden;
    text-overflow: ellipsis;
    white-space: nowrap;
  }

  .advanced-body {
    padding: 0 var(--space-4) var(--space-4) var(--space-4);
    display: flex;
    flex-direction: column;
    gap: var(--space-4);
    border-top: 1px solid color-mix(in srgb, var(--ink) 8%, var(--line));
    margin-top: var(--space-2);
    padding-top: var(--space-3);
  }

  .style-defaults, .format-defaults, .hosts-defaults {
    display: flex;
    align-items: center;
    gap: var(--space-2);
    margin-top: var(--space-2);
  }

  .changed-marker {
    font-size: calc(var(--ui-size) * 0.8);
    color: var(--voice-b);
    font-weight: 500;
  }

  .default-marker {
    font-size: calc(var(--ui-size) * 0.8);
    color: var(--ink-soft);
    font-style: italic;
  }

  .back-to-default {
    font-size: calc(var(--ui-size) * 0.8);
    padding: 0;
    min-height: 24px;
  }
</style>

<script lang="ts">
  import { onMount } from 'svelte'
  import { fetchMeta, type Meta } from '../api'

  let { meta, onback }: { meta: Meta | null; onback: () => void } = $props()

  let retried = $state<Meta | null>(null)
  let activeSection = $state('steps')

  $effect(() => {
    if (!meta && !retried) {
      fetchMeta()
        .then((m) => (retried = m))
        .catch(() => {})
    }
  })
  const info = $derived(meta ?? retried)

  const FAQ_NAV = [
    { id: 'steps', label: 'Steps' },
    { id: 'templates-vs-styles', label: 'Templates' },
    { id: 'audio-clips', label: 'Audio Clips' },
    { id: 'watchlist-section', label: 'Watchlist' },
    { id: 'podcast-channels', label: 'Shows' },
    { id: 'voices-hosts', label: 'Voices' },
    { id: 'voice-engines', label: 'Engines' },
    { id: 'agents-mcp', label: 'Agents & MCP' },
    { id: 'nostr-section', label: 'Nostr & npub' },
    { id: 'v4v-fairness', label: 'V4V Fair' },
    { id: 'bitcoin-vs-crypto', label: 'Bitcoin' },
    { id: 'numbers', label: 'Numbers' }
  ]

  const RANGE_LABELS: Record<string, string> = {
    'voice.dialog.count': 'hosts per episode',
    'voice.speed': 'voice speed',
    'voice.gap_ms': 'pause between turns (ms)',
  }

  function fmtRange(r: number[]): string {
    return `${r[0]} to ${r[1]}`
  }

  onMount(() => {
    let ticking = false

    const updateActiveSection = () => {
      const allSections = Array.from(document.querySelectorAll('main > section[id]')) as HTMLElement[]
      if (allSections.length === 0) return

      const nav = document.querySelector('.sticky-nav') as HTMLElement | null
      const navOffset = (nav ? nav.offsetHeight : 56) + 30
      const scrollPos = window.scrollY + navOffset

      const last = allSections[allSections.length - 1]
      if (last && window.innerHeight + window.scrollY >= document.documentElement.scrollHeight - 60) {
        activeSection = last.id
        return
      }

      const first = allSections[0]
      let current = first ? first.id : 'steps'
      for (const el of allSections) {
        const top = el.getBoundingClientRect().top + window.scrollY
        if (scrollPos >= top) {
          current = el.id
        }
      }
      activeSection = current
    }

    const onScroll = () => {
      if (!ticking) {
        requestAnimationFrame(() => {
          updateActiveSection()
          ticking = false
        })
        ticking = true
      }
    }

    window.addEventListener('scroll', onScroll, { passive: true })
    updateActiveSection()

    return () => {
      window.removeEventListener('scroll', onScroll)
    }
  })

  $effect(() => {
    if (activeSection) {
      const activeBtn = document.querySelector('.jump-pill.active') as HTMLElement | null
      if (activeBtn) {
        activeBtn.scrollIntoView({ behavior: 'smooth', block: 'nearest', inline: 'center' })
      }
    }
  })

  // in-page anchors must not hit the hash router: unknown hashes eject
  // the faq screen (App.svelte applyHash falls through to compose)
  function goToSection(e: MouseEvent, id: string) {
    e.preventDefault()
    activeSection = id
    const el = document.getElementById(id)
    if (!el) return
    const nav = document.querySelector('.sticky-nav') as HTMLElement | null
    const navHeight = nav ? nav.offsetHeight : 56
    const top = el.getBoundingClientRect().top + window.scrollY - navHeight - 16
    const reduce = matchMedia('(prefers-reduced-motion: reduce)').matches
    window.scrollTo({ top: Math.max(0, top), behavior: reduce ? 'auto' : 'smooth' })
    el.setAttribute('tabindex', '-1')
    el.focus({ preventScroll: true })
  }

  function scrollToTop() {
    window.scrollTo({ top: 0, behavior: 'smooth' })
  }

  const ranges = $derived(info?.limits?.setting_ranges ?? {})
  const rangeRows = $derived(Object.entries(ranges).filter(([k]) => k in RANGE_LABELS))
</script>

<div class="faq-page">
  <!-- Sticky Quick-Jump & Breadcrumb Bar -->
  <nav class="sticky-nav" aria-label="Quick jump">
    <div class="sticky-nav-inner">
      <div class="sticky-breadcrumb mono">
        <span class="sticky-app">vozonda</span>
        <span class="sticky-sep">/</span>
        <span class="sticky-cur">faq</span>
        <span class="sticky-sep">/</span>
        <span class="sticky-sec">{activeSection}</span>
      </div>
      <div class="sticky-pills mono">
        {#each FAQ_NAV as item}
          <button
            type="button"
            class="jump-pill"
            class:active={activeSection === item.id}
            onclick={(e) => goToSection(e, item.id)}
          >
            {item.label}
          </button>
        {/each}
      </div>
      <button type="button" class="jump-top-btn mono" onclick={scrollToTop} title="Jump to top" aria-label="Jump to top">
        ↑ top
      </button>
    </div>
  </nav>

  <main>
    <section id="steps">
      <h2>Six steps, start to finish</h2>
    <ol class="mono steps">
      <li><span>fetch</span> pulls your URL, or takes pasted text as-is</li>
      <li><span>extract</span> strips layout, keeps the readable body and title</li>
      <li><span>translate</span> only runs if you picked an output language</li>
      <li><span>script</span> a local LLM writes the dialogue in the style you picked</li>
      <li><span>voice</span> each turn gets performed by its assigned voice</li>
      <li><span>master</span> all turns stitched into one MP3, transcript included</li>
    </ol>
  </section>

  <nav class="toc" aria-label="FAQ sections">
    <h2 class="mono toc-title">In this page</h2>
    <ol class="mono toc-list">
      <li><a href="#templates-vs-styles" onclick={(e) => goToSection(e, 'templates-vs-styles')}>Templates vs styles</a></li>
      <li><a href="#current-templates" onclick={(e) => goToSection(e, 'current-templates')}>Current templates (reviewed)</a></li>
      <li><a href="#new-templates" onclick={(e) => goToSection(e, 'new-templates')}>New templates: Qwen TTS secret sauce</a></li>
      <li><a href="#natural-dialogue" onclick={(e) => goToSection(e, 'natural-dialogue')}>Natural dialogue: roles, rhythm, repairs</a></li>
      <li><a href="#custom-prompts" onclick={(e) => goToSection(e, 'custom-prompts')}>Custom prompts: the biggest flexibility</a></li>
      <li><a href="#episode-vs-defaults" onclick={(e) => goToSection(e, 'episode-vs-defaults')}>This episode vs defaults</a></li>
      <li><a href="#audio-clips" onclick={(e) => goToSection(e, 'audio-clips')}>Audio clips & social slicing</a></li>
      <li><a href="#watchlist-section" onclick={(e) => goToSection(e, 'watchlist-section')}>Watchlist: auto-episodes from RSS</a></li>
      <li><a href="#podcast-channels" onclick={(e) => goToSection(e, 'podcast-channels')}>Podcast shows & custom RSS feeds</a></li>
      <li><a href="#listen-screen" onclick={(e) => goToSection(e, 'listen-screen')}>Listen screen: what you see</a></li>
      <li><a href="#keyboard" onclick={(e) => goToSection(e, 'keyboard')}>Keyboard shortcuts</a></li>
      <li><a href="#content-language" onclick={(e) => goToSection(e, 'content-language')}>Content & language</a></li>
      <li><a href="#voices-hosts" onclick={(e) => goToSection(e, 'voices-hosts')}>Voices & hosts</a></li>
      <li><a href="#jargon" onclick={(e) => goToSection(e, 'jargon')}>TTS jargon, translated</a></li>
      <li><a href="#voice-engines" onclick={(e) => goToSection(e, 'voice-engines')}>Voice engines & decision guide</a></li>
      <li><a href="#agents-mcp" onclick={(e) => goToSection(e, 'agents-mcp')}>Agents, MCP & the API</a></li>
      <li><a href="#nostr-section" onclick={(e) => goToSection(e, 'nostr-section')}>Nostr & npubs</a></li>
      <li><a href="#v4v-fairness" onclick={(e) => goToSection(e, 'v4v-fairness')}>Value for Value (V4V)</a></li>
      <li><a href="#bitcoin-vs-crypto" onclick={(e) => goToSection(e, 'bitcoin-vs-crypto')}>Bitcoin vs "crypto"</a></li>
      <li><a href="#hybrid-engines" onclick={(e) => goToSection(e, 'hybrid-engines')}>Local vs Cloud engines</a></li>
      <li><a href="#numbers" onclick={(e) => goToSection(e, 'numbers')}>The numbers (from /meta)</a></li>
      <li><a href="#whats-running" onclick={(e) => goToSection(e, 'whats-running')}>What's running it</a></li>
      <li><a href="#version-data" onclick={(e) => goToSection(e, 'version-data')}>Version & data</a></li>
    </ol>
  </nav>

  <section id="templates-vs-styles">
    <h2>Templates vs styles: the difference</h2>
    <dl class="mono facts">
      <div><dt>style</dt><dd>the script's DNA. it decides how the hosts talk, how long they hold the mic, what words they reach for, and whether they argue or agree. 20 of them, from a whisper (asmr) to a stadium shout (futbol). you pick the personality, the writing brain follows it.</dd></div>
      <div><dt>template</dt><dd>a shortcut, not a new style. it just pushes the right buttons at once: style plus conversation or read aloud plus number of hosts plus clean or 18+. no invention, just a saved combo for a real job.</dd></div>
      <div><dt>why templates exist</dt><dd>you should not have to remember that solo calm means meditation plus read aloud plus one host. you have a goal, the template knows the recipe. classic is the everyday default, duel is pro versus contra from the same source, news briefing is facts first with no jokes.</dd></div>
      <div><dt>can you override</dt><dd>always. pick a template, then change anything in the essentials below. templates are a starting point, not a cage. think preset on a synth, you can still turn every knob after.</dd></div>
    </dl>
  </section>

  <section id="current-templates">
    <h2>Current templates, reviewed and fixed</h2>
    <dl class="mono facts">
      <div><dt>classic</dt><dd>balanced plus conversation plus 2 hosts. the daily driver. throw anything at it and it just works, no thinking required.</dd></div>
      <div><dt>duel</dt><dd>debate plus conversation plus 2 hosts. same source, two sides, sharp but fair. built for opinion pieces, policy fights, any tech bet where you want both edges.</dd></div>
      <div><dt>solo · calm</dt><dd>meditation plus read aloud plus 1 host. a guided walk down numbered floors through your article. best for essays you want to absorb, not skim, the kind you read with a slow breath.</dd></div>
      <div><dt>news briefing</dt><dd>serious plus conversation plus 2 hosts. evidence first, jokes off, stakes clear. built for breaking news, security notes, anything where getting it right beats sounding clever.</dd></div>
      <div><dt>explained simply</dt><dd>eli5 plus conversation plus 2 hosts. A plays the kid who almost gets it, B fixes the picture with an image you can see. built for papers, whitepapers, anything that normally needs a dictionary and a second coffee.</dd></div>
    </dl>
  </section>

  <section id="new-templates">
    <h2>Show templates: power combinations</h2>
    <dl class="mono facts">
      <div><dt>why templates matter</dt><dd>curated show formats with preconfigured voice cast, emotion, and pacing. Adaptive badges show which TTS engine brings out its best character, but every template works on all engines.</dd></div>
      <div><dt>character trio</dt><dd>dude plus conversation plus 3 hosts. A drifts, B erupts on principle, C wanders in late and slightly off. Three distinct timbres you can tell apart blind. Best with Qwen.</dd></div>
      <div><dt>true crime</dt><dd>true_crime plus conversation plus 2 hosts. Atmospheric tension, slow suspenseful pacing, and haunting evidence dissection. Best with Voxtral.</dd></div>
      <div><dt>tech roast</dt><dd>tech_roast plus conversation plus 2 hosts. Sharp sarcastic banter, witty deadpan one-liners, and pragmatic counter-arguments. Best with Voxtral.</dd></div>
      <div><dt>zen meditation</dt><dd>meditation_zen plus read aloud plus 1 host. Gentle soothing ASMR narration, calm breath pacing. Best with Piper.</dd></div>
      <div><dt>emotional arc</dt><dd>storyteller plus conversation plus 2 hosts. Emotion curves dynamically across the story from curiosity to revelation. Best with Qwen.</dd></div>
      <div><dt>whisper & witness</dt><dd>asmr plus conversation plus 2 hosts, soft close mic female voices. Late night intimate texture. Best with Piper.</dd></div>
    </dl>
  </section>

  <section id="natural-dialogue">
    <h2>Natural dialogue: roles, rhythm, repairs</h2>
    <dl class="mono facts">
      <div><dt>roles in numbers</dt><dd>every style knows its cast. in balanced the curious host holds about a third of the words and the expert carries the long explanations; in storyteller A narrates and B reacts; in socrates A only asks while B's answers shrink. these numbers open every script prompt, so the writing model knows what "done" looks like.</dd></div>
      <div><dt>checked after writing</dt><dd>when the script comes back, code measures it: who talks how much, how long the turns run, how many quick reactions there are. nothing is taken on trust.</dd></div>
      <div><dt>repaired where it slips</dt><dd>if one host ends up talking too much, vozonda does not throw the script away. it picks the few longest explanations of that host and asks the model to hand the second half to the other host, in their own words, without losing or adding a fact. a repair that drops content is rejected.</dd></div>
      <div><dt>rhythm by code</dt><dd>monologues far over a host's usual length are split at a sentence end, and when quick reactions are too few the other host chimes in mid-explanation ("Huh.", "Wait, really?", "Echt?"). never the same one twice in a row, never one the hosts already use, never a bare "Mhm.".</dd></div>
      <div><dt>your interjections stay</dt><dd>anything the hosts say on their own, "mhm, krass" or "wie geil ist das denn", is never removed. those are what make it sound human.</dd></div>
      <div><dt>where it holds back</dt><dd>calm styles (asmr, meditation) keep their slow pace untouched. inserted reactions exist for English and German; other languages get the checks and repairs, but no inserted words.</dd></div>
    </dl>
  </section>

  <section id="custom-prompts">
    <h2>Custom prompts: the biggest flexibility</h2>
    <dl class="mono facts">
      <div><dt>what it is</dt><dd>every style has a built-in prompt. in advanced settings you can replace any of them completely. leave it blank and the built in runs. type something and your words replace it. the model listens to you, not to a hidden default.</dd></div>
      <div><dt>why it beats the one-prompt crowd</dt><dd>ElevenLabs GenFM, NotebookLM, Wondercraft and friends have no local LLM before the voice. they hand your text straight to a fixed voice prompt, you get their one idea of how it should sound. vozonda puts a local LLM of your choice before the TTS. that brain rewrites, structures, adds host dynamics, keeps facts tied to the source, translates if you asked, then the TTS performs it. two models, not one. the script is written, not just read.</dd></div>
      <div><dt>how we keep it honest</dt><dd>the built-in prompts carry the boring but important bits: stay inside the source, no invented facts, plain prose for the ear, no emoji, no markdown, no parentheses, no dash tricks, plus each style's own rules for reactions, questions and conflict. the JSON contract (speaker plus text) means no surprise formatting. your custom prompt replaces the built-in one, so keep the rules you copied with it. two things are always added around it: the style's success criteria up front (roles and rhythm in numbers) and a short form check at the end, and the checks and repairs above run on every script.</dd></div>
      <div><dt>power move</dt><dd>copy the default you see when the box is empty, then add your rule: always end B with a question, never say delve, host A talks like a noir detective who has seen too much. if it is in the prompt, the LLM does it. it is not a wish, it is an instruction you wrote.</dd></div>
      <div><dt>per-style</dt><dd>each key like script.style.conspiracy has its own slot. change one without touching the others. experiment cheap, keep what works, leave the rest alone.</dd></div>
    </dl>
  </section>

  <section id="episode-vs-defaults">
    <h2>This episode vs defaults for every episode</h2>
    <dl class="mono facts">
      <div><dt>two places, one rule</dt><dd>"this episode: length, style, voices, script" on the compose page changes only the episode you are about to make. "defaults for every episode" opens advanced settings, and what you set there is used whenever an episode does not say otherwise.</dd></div>
      <div><dt>how to tell them apart</dt><dd>in the per-episode panel every field shows "(default)" while it follows your settings, and "changed" once you override it. "back to default" drops the override for that field only.</dd></div>
      <div><dt>what wins</dt><dd>the episode's own choice, then your defaults, then the built-in value. changing a default never rewrites episodes you already made.</dd></div>
    </dl>
  </section>

  <section id="audio-clips">
    <h2>Audio clips & social slicing</h2>
    <dl class="mono facts">
      <div><dt>for listeners (easy)</dt><dd>found a killer 30-second explanation or hilarious quote? Select the text in the transcript or tap a speaker turn, hit "slice", and get an instant shareable audio clip with its own player to send to friends or social media.</dd></div>
      <div><dt>how to slice</dt><dd>desktop: highlight text with mouse. mobile: tap directly on any transcript turn row to select the passage without fighting touch cursor handles. The bottom action dock pops up with preview and duration.</dd></div>
      <div><dt>under the hood (pro)</dt><dd>deterministic streamcopy slicing via POST /clips. Millisecond-accurate start/end timestamps from the speech renderer. Standalone preview pages at <code>/e/:id/clip/:start-:end</code> with rich open graph audio tags.</dd></div>
      <div><dt>sharing & nostr</dt><dd>1-click copy creates a Nostr Kind 1 quote note referencing the exact audio timestamp, plus direct MP3 download for podcast clips.</dd></div>
    </dl>
  </section>

  <section id="watchlist-section">
    <h2>Watchlist: auto-episodes from RSS</h2>
    <dl class="mono facts">
      <div><dt>how it works</dt><dd>add an rss feed url, pick style/format/language/hosts. The poller checks every 10 minutes. New articles render immediately, then on schedule.</dd></div>
      <div><dt>schedule</dt><dd>optional digest schedule per watchlist: daily@HH:MM or weekly@&lt;day&gt;@HH:MM with timezone. One digest per slot, a missed slot is caught up once, and check now forces a digest.</dd></div>
      <div><dt>dedupe</dt><dd>cross-feed dedupe: tracking params are stripped, near-duplicate titles across all feeds within 72 h are skipped, and titles that differ in a number count as different stories.</dd></div>
      <div><dt>digest vs per story</dt><dd>choose between rendering single episodes per story or bundling N stories into one structured digest with chapter marks.</dd></div>
      <div><dt>per-feed voices</dt><dd>each feed can have its own voice profile (timbre, emotion, custom names). Saved with the feed.</dd></div>
      <div><dt>explicit per feed</dt><dd>enable 18+ mode per feed. The feed carries the tag in the rss.</dd></div>
      <div><dt>podcast feed url</dt><dd>every watchlist has a feed url with its own episodes. Copy from the watchlist page.</dd></div>
    </dl>
  </section>


  <section id="podcast-channels">
    <h2>Podcast feeds, series & automation</h2>
    <dl class="mono facts">
      <div><dt>master feed vs series feeds</dt><dd>your master feed at <code>/feed.xml</code> is your central podcast inbox containing all manual episodes and automated watchlists. If you assign an optional series tag (e.g. "Paper Reviews", "Tech Roast") to an episode, it also gets its own dedicated, shareable sub-feed at <code>/:creator/:show/feed.xml</code>.</dd></div>
      <div><dt>standalone episodes</dt><dd>when you leave the series field empty, the episode publishes directly to your master podcast feed. No extra setup required.</dd></div>
      <div><dt>watchlists (input feeds)</dt><dd>add any number of external RSS/Atom feeds in the Watchlist room. Vozonda checks them every 10 minutes, automatically turns fresh articles into dialogue episodes, and puts them into your podcast feed.</dd></div>
      <div><dt>how to subscribe</dt><dd>copy your master feed URL from Advanced Settings or Watchlists, and paste it into Apple Podcasts, Fountain, Pocket Casts, Overcast, or AntennaPod. Your app syncs new audio episodes as soon as they finish rendering.</dd></div>
      <div><dt>under the hood (pro)</dt><dd>standard-compliant Podcasting 2.0 RSS 2.0 XML feeds with iTunes categories, artwork, chapter markers, transcript enclosures, and Value4Value Lightning splits.</dd></div>
    </dl>
  </section>

  <section id="listen-screen">
    <h2>Listen screen: what you see</h2>
    <dl class="mono facts">
      <div><dt>ambient player</dt><dd>cover artwork with an organic ambient blur aura in the background, matching the article's color palette.</dd></div>
      <div><dt>chapters</dt><dd>for digest episodes, clickable chapter list with active marker and time offsets to jump between source stories.</dd></div>
      <div><dt>transcript</dt><dd>full dialogue with speaker labels. Click any line to seek. Active line highlights while playing.</dd></div>
      <div><dt>while it renders</dt><dd>a terminal-style progress line shows which stage is running, and cancel stops the episode, including a voice renderer that is already working.</dd></div>
      <div><dt>making-of</dt><dd>expand to see style, format, voices, language, render time, source link, tuning, value-for-value address.</dd></div>
      <div><dt>source link</dt><dd>the original article is linked. Open it side-by-side to verify.</dd></div>
    </dl>
  </section>

  <section id="keyboard">
    <h2>Keyboard shortcuts</h2>
    <dl class="mono facts">
      <div><dt>space</dt><dd>play / pause (listen screen)</dd></div>
      <div><dt>left / right arrow</dt><dd>seek 5s back / forward (listen)</dd></div>
      <div><dt>up / down arrow</dt><dd>jump to previous / next dialogue turn (listen)</dd></div>
      <div><dt>s</dt><dd>cycle playback speed (listen)</dd></div>
      <div><dt>j / k</dt><dd>next / previous episode (library & listen)</dd></div>
      <div><dt>/</dt><dd>jump to the URL field (compose)</dd></div>
      <div><dt>escape</dt><dd>close settings / making-of</dd></div>
    </dl>
  </section>

  <section id="content-language">
    <h2>Content & language</h2>
    <dl class="mono facts">
      <div><dt>slang style</dt><dd>voices talk like friends after hours. Swearing included. Episodes that go there get an 18+ tag.</dd></div>
      <div><dt>emotion</dt><dd>set per voice. Style is how the script is written, emotion is how each line is spoken. They add up, neither overrides the other.</dd></div>
      <div><dt>explicit mode</dt><dd>global 18+ toggle in advanced settings. When on, slang and any style use adult register. Per-job explicit flag in rss.</dd></div>
    </dl>
  </section>

  <section id="voices-hosts">
    <h2>Voices & hosts</h2>
    <dl class="mono facts">
      <div><dt>hosts per episode</dt><dd>1 (read aloud), 2 (conversation), or 3 (conversation + late entrant). Each host gets its own timbre, emotion, and optional custom name.</dd></div>
      <div><dt>probe play</dt><dd>press the play button next to any timbre to hear a sample before rendering.</dd></div>
      <div><dt>custom names</dt><dd>override the default speaker label (A/B/C or Narrator) with any name. Shows in transcript and making-of.</dd></div>
      <div><dt>engine</dt><dd>one engine chosen in advanced settings: Kokoro-82M (any CPU, the default of the docker quickstart), Qwen3-TTS (NVIDIA GPU, 9 voices) or Piper (any CPU, 13 voices in German, English, French, Spanish and Italian). Voxtral runs in the Mistral cloud with your own API key. Pick kokoro and it renders English and 7 more languages itself, handing German and the other languages it lacks to piper automatically.</dd></div>
    </dl>
  </section>

  <section id="jargon">
    <h2>TTS jargon, translated</h2>
    <p class="mono note">// the key concepts behind vozonda's engine and value splits.</p>
    <dl class="mono facts">
      <div><dt>timbre vs voice vs speaker</dt><dd>same thing in three costumes. the <em>voice</em> is the character you hear ("the deep guy who sounds done with meetings"). under the hood it's a <em>timbre</em>, an id like "eric" that tells the engine which throat to borrow. and when the transcript says A or B, that's the <em>speaker</em> label. one timbre, many name tags.</dd></div>
      <div><dt>what's a model?</dt><dd>a neural network that froze after cramming. piper crammed audiobooks: fast, clean, a little flat, like a GPS with feelings. kokoro learned to be expressive on tiny hardware. qwen3-tts (the default on a GPU box) studied mountains of real speech across languages and can actually act: whisper, cheer, drop its voice for dramatic effect. bigger head, better acting.</dd></div>
      <div><dt>ssml</dt><dd>the industry's answer to "how do we control a voice": angle brackets, prosody tags, pause lengths in milliseconds. powerful, and about as fun to write as a tax return. vozonda hides all of it. you steer with plain words (pick a style, set an emotion) and the LLM writes performance directions the engine understands. curation over mass: ten good dials beat fifty cryptic ones.</dd></div>
      <div><dt>doctor checks</dt><dd>the system status card in <a href="#settings">advanced settings</a> is the machine's pulse. three vitals: llm reachable (can we ping the writing brain?), voices renderable (can the TTS actually speak?), ffmpeg present (can we stitch it into one mp3?). green means episodes will flow. a red row comes with a hint, not with a panic.</dd></div>
      <div><dt>v4v, lightning, auto-balance</dt><dd>value for value: podcasting's tip jar without middleman fees. lightning is bitcoin's instant-rail network. every feed carries a multi-recipient split tag (creator, original author, and host node). the UI auto-balances splits to exactly 100% against your creator anchor, while the server node address is protected in .env.</dd></div>
      <div><dt>why one engine at a time</dt><dd>the GPU has one lap. the LLM and the TTS both want to sit on it. run two big models at once and they elbow each other until something runs out of memory mid-sentence. so vozonda runs one engine at a time and queues everything else. patience beats crashes.</dd></div>
    </dl>
  </section>

  <section id="sources">
    <h2>Sources: what you can throw at it</h2>
    <dl class="mono facts">
      <div><dt>web article</dt><dd>any article or blog post. Layout stripped, readable body kept. Hard paywalls and JS-only pages may come out empty. You get a clear error if so.</dd></div>
      <div><dt>nostr notes & articles</dt><dd>supports NIP-19 identifiers (nostr:nevent1..., nostr:naddr1...) and gateways (njump.me, habla.news, coracle). Automatically extracts author npub, title, and body.</dd></div>
      <div><dt>youtube link</dt><dd>pulls the video's transcript, not the audio. No subtitles on the video? It fails with a clear message.</dd></div>
      <div><dt>rss feed</dt><dd>watched automatically via watchlist. New articles become episodes on their own, poller checks every 10 minutes.</dd></div>
      <div><dt>pasted text</dt><dd>taken as-is, nothing fetched. Good for notes, drafts, or anything behind a login.</dd></div>
      <div><dt>how long</dt><dd>up to {info?.limits?.max_sources ?? info?.max_sources ?? 10} sources per episode, each up to about {(info?.limits?.max_source_chars ?? info?.max_source_chars ?? 180000).toLocaleString('en-US')} characters. Longer sources are condensed, not cut. You pick the episode length: short (3 min), default (8 min), long (15 min) or any value from 1 to 60 minutes. The script is written to a word budget for that length, so the audio lands close to it.</dd></div>
    </dl>
  </section>

  <section id="voice-engines">
    <h2>Voice engines: Kokoro vs Qwen3-TTS vs Voxtral vs Piper</h2>
    <dl class="mono facts">
      <div><dt>kokoro</dt><dd>82M parameter ONNX engine that runs on any CPU, no GPU needed. Apache-2.0, speaks English and 7 more languages (en, es, fr, it, pt, hi, ja, zh); German and the other languages it lacks render with piper automatically. Model files download on first use and are cached. The default of the docker quickstart.</dd></div>
      <div><dt>qwen3_tts</dt><dd>1.7B parameter autoregressive codec transformer on your own NVIDIA GPU. 24 kHz audio, the most expressive local option. Private and offline once the weights are downloaded.</dd></div>
      <div><dt>voxtral</dt><dd>Mistral AI EU Cloud API. Delivers NotebookLM-level emotional realism: laughter [laughs], sighs [sighs], natural breathing, conversational pauses, and 30+ native European accents (DE, FR, ES, IT, PT, EN). Consumes 0 MB VRAM on Sparki.</dd></div>
      <div><dt>piper</dt><dd>open source VITS engine that runs on any CPU, no GPU needed. 13 community voices (for example Thorsten, Kerstin, Ryan, Amy, Siwis, Paola); each episode is cast with voices native to its language. Every voice model (up to about 60 MB) is downloaded from Hugging Face on first use and cached. Clear and fast, but flatter than qwen3_tts.</dd></div>
      <div><dt>which to pick</dt><dd>Choose kokoro when you have no GPU: it is the default of the docker quickstart. Choose piper for German and the other languages kokoro lacks. Choose qwen3_tts for 100% local GPU privacy and studio sound. Choose voxtral for lively conversational podcast acting with human emotions and European accents.</dd></div>
    </dl>
  </section>

  <section id="music-ducking">
    <h2>Master stage: music beds & studio ducking</h2>
    <dl class="mono facts">
      <div><dt>smooth ducking</dt><dd>Vozonda uses mathematical raised-cosine S-curves to attenuate music by -12 dB when speech begins. This eliminates unnatural compressor pumping and harsh volume cuts.</dd></div>
      <div><dt>timing adaptation</dt><dd>Intro music ducks for 3-5 seconds across opening dialogue turns. Outro music starts under the final sign-off line and swells to full volume the exact moment speech ends.</dd></div>
      <div><dt>procedural vs stems</dt><dd>Plays harmonic jazz/broadcast progressions (Cmaj9 / Fmaj7) with analog saturation by default, or auto-discovers custom studio audio files in media/music/ (intro.mp3, outro.mp3).</dd></div>
    </dl>
  </section>

  <section id="agents-mcp">
    <h2>Agents, MCP & the API</h2>
    <dl class="mono facts">
      <div><dt>mcp server</dt><dd>vozonda ships an MCP server (python -m vozonda_api.mcp_server) with eleven tools. episodes: create_episode, get_episode, list_episodes, list_styles, get_feed_url. watchlists: list_watchlists, create_watchlist, set_watchlist_schedule, check_watchlist, render_digest, delete_watchlist, so an agent can set up a feed that turns into a podcast on its own. connect it to Claude Code, Claude Desktop or any MCP client, then ask your agent in plain words.</dd></div>
      <div><dt>rest api</dt><dd>everything the web app does goes through the same HTTP API. /llms.txt describes it for agents. Pass a callback_url with a job and vozonda posts to it when the episode is done or has failed, so nothing has to poll.</dd></div>
      <div><dt>where to start</dt><dd>the <a href="#agents" class="link">agents page</a> has copy-paste setup for each client, example prompts and the tool reference.</dd></div>
    </dl>
  </section>

  <section id="nostr-section">
    <h2>Nostr: sovereign social identity & npubs</h2>
    <p class="mono note">// open communication protocol without corporate servers, emails, or platform lock-in.</p>
    <dl class="mono facts">
      <div>
        <dt>what is nostr</dt>
        <dd>
          Notes and Other Stuff Transmitted by Relays. An open, censorship-resistant protocol for decentralized identity, social networking, and value transfer. Instead of an account on a corporation's server, you own a cryptographic keypair (secp256k1). Nobody can ban your identity, take your followers, or delete your content.
        </dd>
      </div>
      <div>
        <dt>npub vs nsec</dt>
        <dd>
          Your <strong>npub</strong> is your public key (like an open handle or account address). You share it everywhere so friends, podcast feeds, and relays find you. Your <strong>nsec</strong> is your private key that signs your notes and proves ownership. Never enter your nsec on untrusted websites and never share it with anyone.
        </dd>
      </div>
      <div>
        <dt>how to get an npub</dt>
        <dd>
          Install a browser extension or mobile client. It generates your cryptographic keypair in seconds with zero personal information required:
          <br />
          • Starter Guide: <a href="https://nostr.how" target="_blank" rel="noreferrer" class="link">nostr.how</a>
          <br />
          • Browser Signers: <a href="https://getalby.com" target="_blank" rel="noreferrer" class="link">Alby</a> or <a href="https://github.com/nostr-protocol/nos2x" target="_blank" rel="noreferrer" class="link">nos2x</a>
          <br />
          • Web Clients: <a href="https://primal.net" target="_blank" rel="noreferrer" class="link">Primal</a> and <a href="https://coracle.social" target="_blank" rel="noreferrer" class="link">Coracle</a>
          <br />
          • Mobile Apps: <a href="https://damus.io" target="_blank" rel="noreferrer" class="link">Damus (iOS)</a> and <a href="https://amethyst.social" target="_blank" rel="noreferrer" class="link">Amethyst (Android)</a>
        </dd>
      </div>
      <div>
        <dt>in vozonda</dt>
        <dd>
          Connect via NIP-07 browser signer (Alby/nos2x) or Amber. Vozonda signs transcript quotes (NIP-84 highlights), and splits sats directly to your npub.
        </dd>
      </div>
      <div>
        <dt>zaps & boosts</dt>
        <dd>
          Value4Value lightning tips (NIP-57). Send sats directly to episode creators or split support with Vozonda using WebLN, Amber, or QR invoice. Turn on streaming to send sats per minute continuously while listening.
        </dd>
      </div>
    </dl>
  </section>

  <section id="v4v-fairness">
    <h2>Value for Value (V4V): why it is fair</h2>
    <p class="mono note">// streaming satoshis directly from listener to creator, replacing surveillance capitalism.</p>
    <dl class="mono facts">
      <div>
        <dt>ads vs value for value</dt>
        <dd>
          The traditional web is subsidized by surveillance capitalism: invasive tracking scripts, clickbait paywalls, and tech monopolies skimming 30% to 50% cuts. V4V (pioneered by Adam Curry and the Podcasting 2.0 initiative) establishes an honest direct exchange: you listen freely without tracking, and if you receive value, you stream back whatever value that content was worth to you.
        </dd>
      </div>
      <div>
        <dt>direct sat streaming</dt>
        <dd>
          Using Bitcoin's Lightning Network, modern podcast players (Fountain, Podverse, CurioCaster) stream micro-payments (satoshis per minute) while you listen. You can also send 1-click boosts with a message when a particular dialogue turn or insight lands.
        </dd>
      </div>
      <div>
        <dt>transparent splits</dt>
        <dd>
          Every Vozonda episode and RSS feed carries a cryptographic <code>&lt;podcast:value&gt;</code> split specification. For example: 70% goes directly to the podcast creator, 20% to the original source author, and 10% to the sovereign host node. Sats settle instantly into recipients' wallets without middleman fees or custodial risk.
        </dd>
      </div>
      <div>
        <dt>learn more</dt>
        <dd>
          Read the movement manifesto and explore supporting players at <a href="https://value4value.info" target="_blank" rel="noreferrer" class="link">value4value.info</a> and the Podcasting 2.0 standards at <a href="https://podcasting20.com" target="_blank" rel="noreferrer" class="link">podcasting20.com</a>.
        </dd>
      </div>
    </dl>
  </section>

  <section id="bitcoin-vs-crypto">
    <h2>Bitcoin vs "crypto": mathematical sound money</h2>
    <p class="mono note">// why vozonda operates exclusively on bitcoin lightning and rejects speculative altcoins.</p>
    <dl class="mono facts">
      <div>
        <dt>mathematical scarcity</dt>
        <dd>
          Bitcoin has an absolute fixed supply limit of 21,000,000 coins, mathematically enforced by a global decentralized node consensus. There is no central bank, company foundation, or creator board that can vote to print more or dilute your savings.
        </dd>
      </div>
      <div>
        <dt>proof-of-work & physics</dt>
        <dd>
          Bitcoin is anchored in the physical world through thermodynamics. Minting blocks requires real computational work and electricity. This makes transactions irreversible and unforgeable without trusting human institutions.
        </dd>
      </div>
      <div>
        <dt>why not "crypto"?</dt>
        <dd>
          The broader "crypto" industry is largely composed of centralized tokens, venture capital pre-mines, and speculative assets with foundation leaders who can alter code, roll back ledgers, or censor transactions. Bitcoin has no CEO, no pre-mine, no foundation, and no single point of failure. Bitcoin is digital property; "crypto" is venture speculation.
        </dd>
      </div>
      <div>
        <dt>lightning micropayments</dt>
        <dd>
          The Lightning Network is Bitcoin's layer-2 settlement rail. Payments settle in seconds with fees down to single satoshis. This makes streaming fractions of a cent per minute economically viable for independent audio.
        </dd>
      </div>
      <div>
        <dt>foundational reading</dt>
        <dd>
          Study Satoshi Nakamoto's original paper at <a href="https://bitcoin.org" target="_blank" rel="noreferrer" class="link">bitcoin.org</a>, read Der Gigi's essential essay collection at <a href="https://dergigi.com/21-lessons/" target="_blank" rel="noreferrer" class="link">dergigi.com/21-lessons</a>, and explore the Austrian economics archives at <a href="https://nakamotoinstitute.org" target="_blank" rel="noreferrer" class="link">nakamotoinstitute.org</a>.
        </dd>
      </div>
    </dl>
  </section>

  <section id="hybrid-engines">
    <h2>Voice engines & privacy: local vs cloud</h2>
    <dl class="mono facts">
      <div><dt>sovereign local</dt><dd>runs with local neural models (Qwen, Piper, Kokoro) on your own hardware. No telemetry, no per-token subscription markups. What leaves the box: fetching the sources you give it, and downloading model weights once on first use.</dd></div>
      <div><dt>private cloud</dt><dd>optional cloud engines with your own API key: Voxtral for voices, and for the script a model on NVIDIA NIM, OpenCode (through its CLI) or Claude. Which model runs is a setting, and the settings page lists what each provider offers right now; any writer can back up another. NVIDIA's free developer key is for testing and prototyping only; production use needs their paid licence. In our script benchmark Kimi K3 on NIM wrote livelier dialogue than the local model, and of the free OpenCode models big-pickle came closest. Both dropdowns in advanced settings group engines into local and cloud; with a cloud engine the text of the episode leaves your machine.</dd></div>
    </dl>
  </section>

  {#if info}
    <section id="numbers">
      <h2>The numbers</h2>
      <dl class="mono facts">
        <div><dt>source text</dt><dd>first {(info.limits?.max_source_chars ?? info.max_source_chars ?? 180000).toLocaleString('en-US')} characters per source, up to {info.limits?.max_sources ?? info.max_sources ?? 10} sources. Longer sources are condensed, not cut.</dd></div>
        <div><dt>jobs at once</dt><dd>{info.limits?.max_parallel_jobs}. One GPU, one job. The rest queue.</dd></div>
        <div><dt>script length</dt><dd>planned from the episode length you pick (8 minutes by default, 1 to 60), not from a fixed number of turns.</dd></div>
        <div><dt>words per turn</dt><dd>90 max. Nobody needs to lecture.</dd></div>
        {#each rangeRows as [key, r] (key)}
          <div><dt>{RANGE_LABELS[key]}</dt><dd>{fmtRange(r)}</dd></div>
        {/each}
        <div><dt>styles</dt><dd>{info.styles.length} modes, from whisper to stadium</dd></div>
        <div><dt>voices</dt><dd>{info.timbres.length} speakers on the active engine</dd></div>
        <div><dt>languages</dt><dd>{Object.keys(info.languages).length - 1} output languages plus auto</dd></div>
      </dl>
        <p class="mono note">// most of these are tunable in settings</p>
    </section>

    <section id="whats-running">
      <h2>What's running it</h2>
      <dl class="mono facts">
        <div><dt>LLM</dt><dd>{info.runtime?.llm}</dd></div>
        <div><dt>TTS engine</dt><dd>{info.runtime?.tts_engine}</dd></div>
        <div><dt>swappable?</dt><dd>Yes. Drop in a different engine, its voices show up. Nothing else changes.</dd></div>
      </dl>
    </section>

    <section id="version-data">
      <h2>Version & data</h2>
      <dl class="mono facts">
        <div><dt>vozonda</dt><dd><a href="https://vozonda.com/changelog/" target="_blank" rel="noopener" class="dev-link">v{info.version}</a> · git {info.git_rev}</dd></div>
        <div><dt>data</dt><dd>jobs, settings and audio live on your own disk (in docker: named volumes). Nothing is shared with 3rd-party ad networks or telemetry platforms.</dd></div>
      </dl>
    </section>
  {:else}
    <p class="mono note">// api unreachable. numbers show up once it responds</p>
  {/if}

  <p class="mono backline">
    <button class="link mono" onclick={onback}>← back</button>
    <a class="link mono" href="#about">why this exists →</a>
  </p>
</main>
</div>

<style>
  .faq-page {
    width: 100%;
    min-height: 100vh;
  }

  .sticky-nav {
    position: sticky;
    top: 0;
    z-index: 50;
    background: color-mix(in srgb, var(--paper) 92%, transparent);
    backdrop-filter: blur(12px);
    -webkit-backdrop-filter: blur(12px);
    border-bottom: 1px solid var(--line);
    padding: var(--space-2) var(--space-4);
  }

  .sticky-nav-inner {
    max-width: var(--content-max-width);
    margin: 0 auto;
    display: flex;
    align-items: center;
    justify-content: space-between;
    gap: var(--space-3);
  }

  .sticky-breadcrumb {
    font-size: calc(var(--ui-size) * 0.85);
    color: var(--ink-soft);
    display: flex;
    align-items: center;
    gap: var(--space-1);
    white-space: nowrap;
  }

  .sticky-app {
    color: var(--ink);
    font-weight: 500;
  }

  .sticky-sep {
    color: var(--line);
  }

  .sticky-sec {
    color: var(--green);
    font-weight: 500;
  }

  .sticky-pills {
    display: flex;
    align-items: center;
    gap: var(--space-1);
    overflow-x: auto;
    scrollbar-width: none;
    -webkit-overflow-scrolling: touch;
    scroll-behavior: smooth;
    padding: 2px 0;
  }

  .sticky-pills::-webkit-scrollbar {
    display: none;
  }

  .jump-pill {
    background: transparent;
    border: 1px solid transparent;
    color: var(--ink-soft);
    font-size: calc(var(--ui-size) * 0.78);
    padding: 3px 8px;
    border-radius: var(--radius);
    cursor: pointer;
    white-space: nowrap;
    transition: all 120ms ease;
  }

  .jump-pill:hover {
    color: var(--ink);
    background: color-mix(in srgb, var(--ink) 6%, transparent);
    border-color: var(--line);
  }

  .jump-pill.active {
    color: var(--green);
    background: color-mix(in srgb, var(--green) 12%, transparent);
    border-color: color-mix(in srgb, var(--green) 30%, transparent);
    font-weight: 600;
  }

  .jump-top-btn {
    background: color-mix(in srgb, var(--ink) 6%, transparent);
    border: 1px solid var(--line);
    color: var(--ink);
    font-size: calc(var(--ui-size) * 0.78);
    padding: 4px 10px;
    border-radius: var(--radius);
    cursor: pointer;
    white-space: nowrap;
    flex: none;
  }

  .jump-top-btn:hover {
    color: var(--green);
    border-color: var(--green);
    background: color-mix(in srgb, var(--green) 10%, transparent);
  }

  main {
    max-width: var(--content-max-width);
    margin: 0 auto;
    padding: var(--space-6) var(--space-4);
    width: 100%;
    box-sizing: border-box;
  }

  section {
    scroll-margin-top: 76px;
    margin-top: var(--space-5);
  }

  @media (max-width: 640px) {
    .sticky-breadcrumb {
      display: none;
    }
    .sticky-nav-inner {
      gap: var(--space-2);
    }
  }

  @media (max-width: 480px) {
    main {
      padding: var(--space-4) var(--space-3);
    }
    .facts div {
      flex-direction: column;
      gap: var(--space-1);
      align-items: flex-start;
    }
    .facts dt {
      width: auto;
    }
    .toc {
      padding: var(--space-3);
    }
  }

  .toc {
    margin-top: var(--space-5);
    padding: var(--space-4);
    border: 1px solid var(--line);
    border-radius: var(--radius);
    background: color-mix(in srgb, var(--paper) 4%, transparent);
  }
  .toc-title {
    margin: 0 0 var(--space-3);
    font-size: var(--ui-size);
    color: var(--ink);
  }
  .toc-list {
    margin: 0;
    padding-left: var(--space-4);
    display: grid;
    gap: var(--space-1);
    font-size: calc(var(--ui-size) * 0.9);
  }
  .toc-list a {
    color: var(--ink-soft);
    text-decoration: underline;
    text-decoration-color: var(--line);
  }
  .toc-list a:hover {
    color: var(--green);
    text-decoration-color: var(--green);
  }

  /* scroll targets receive programmatic focus (tabindex set at runtime);
     the jump itself is the indicator, a full-width outline ring is noise */
  section:focus {
    outline: none;
  }

  h2 {
    font-size: var(--h2-size);
    margin: var(--h2-margin);
    font-weight: var(--h2-weight);
    line-height: var(--h2-line-height);
    text-wrap: var(--h2-text-wrap);
  }

  .steps {
    list-style: none;
    margin: 0;
    padding: 0;
    display: grid;
    gap: var(--space-2);
  }

  .steps span {
    color: var(--ink-soft);
    display: inline-block;
    width: 6.5em;
  }

  .facts {
    margin: 0;
    display: grid;
    gap: var(--space-2);
  }

  .facts div {
    display: flex;
    gap: var(--space-3);
    align-items: baseline;
  }

  .facts dt {
    flex: none;
    width: 11em;
    color: var(--ink-soft);
  }

  .facts dd {
    margin: 0;
  }

  .facts dd a {
    color: var(--ink-soft);
    text-decoration: underline;
    text-decoration-color: var(--line);
  }

  .facts dd a:hover {
    color: var(--green);
    text-decoration-color: var(--green);
  }

  .note {
    color: var(--ink-soft);
    margin-top: var(--space-3);
  }

  .backline {
    margin-top: var(--space-5);
    display: flex;
    gap: var(--space-4);
  }

  .link {
    background: none;
    border: none;
    padding: 0;
    cursor: pointer;
    color: var(--ink-soft);
    text-decoration: underline;
    text-decoration-color: var(--line);
  }

  .link:hover {
    color: var(--green);
  }

</style>

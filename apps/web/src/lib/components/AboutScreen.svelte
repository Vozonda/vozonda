<script lang="ts">
  import { onMount } from 'svelte'
  import { fetchMeta, type Meta } from '../api'

  interface Props {
    onback: () => void
  }

  let { onback }: Props = $props()

  let meta: Meta | null = $state(null)
  let activeSection = $state('story')

  const SECTIONS = [
    { id: 'story', label: 'Story' },
    { id: 'rooms', label: 'Rooms' },
    { id: 'clips', label: 'Social Clips' },
    { id: 'bookmarks', label: 'Bookmarks' },
    { id: 'shows', label: 'Podcast Shows' },
    { id: 'identity', label: 'Nostr & Zaps' },
    { id: 'engines', label: 'Engines' },
    { id: 'manifesto', label: 'Manifesto' }
  ]

  onMount(() => {
    fetchMeta().then((m) => (meta = m)).catch(() => {})

    const observer = new IntersectionObserver(
      (entries) => {
        for (const entry of entries) {
          if (entry.isIntersecting) {
            activeSection = entry.target.id
          }
        }
      },
      { rootMargin: '-80px 0px -60% 0px', threshold: 0.1 }
    )

    for (const sec of SECTIONS) {
      const el = document.getElementById(sec.id)
      if (el) observer.observe(el)
    }

    return () => observer.disconnect()
  })

  function scrollToSection(e: MouseEvent, id: string) {
    e.preventDefault()
    const el = document.getElementById(id)
    if (!el) return
    const reduce = matchMedia('(prefers-reduced-motion: reduce)').matches
    el.scrollIntoView({ behavior: reduce ? 'auto' : 'smooth', block: 'start' })
  }

  function scrollToTop() {
    window.scrollTo({ top: 0, behavior: 'smooth' })
  }
</script>

<div class="about-page">
  <!-- Sticky Quick-Jump & Breadcrumb Bar -->
  <nav class="sticky-nav" aria-label="Quick jump">
    <div class="sticky-nav-inner">
      <div class="sticky-breadcrumb mono">
        <span class="sticky-app">vozonda</span>
        <span class="sticky-sep">/</span>
        <span class="sticky-cur">about</span>
        <span class="sticky-sep">/</span>
        <span class="sticky-sec">{activeSection}</span>
      </div>
      <div class="sticky-pills mono">
        {#each SECTIONS as sec}
          <button
            type="button"
            class="jump-pill"
            class:active={activeSection === sec.id}
            onclick={(e) => scrollToSection(e, sec.id)}
          >
            {sec.label}
          </button>
        {/each}
      </div>
      <button type="button" class="jump-top-btn mono" onclick={scrollToTop} title="Jump to top" aria-label="Jump to top">
        ↑ top
      </button>
    </div>
  </nav>

  <div class="about-content">
    <section id="story" class="about-sec">
      <p class="hook">Turn any web article, research paper, or newsletter into an engaging podcast episode or solo narration with 1, 2, or 3 hosts, at the length you pick. Runs on your own hardware, no Big Tech lock-in, no mandatory accounts.</p>

      <p>Drop links, PDFs, images or your own notes, pick your dialogue style, and press make it talk. While you do literally anything else, local AI models extract the story, write the conversation, and voice it with a synchronized transcript. You get an instant MP3 ready for playback, sharing, or your morning commute.</p>

      <p>Hand it your favorite RSS feeds or Nostr bookmarks, and Vozonda works automatically in the background: new articles become polished audio episodes on their own. Everything lands straight in your personal podcast feed, with Podcasting 2.0 chapters and Value4Value Lightning tips wired in.</p>
    </section>

    <section id="rooms" class="about-sec">
      <h2>Five rooms, one engine</h2>

      <p><a class="nav-link" href="/">the compose page</a> is where episodes
      are born: drop your sources, pick a template, make it talk.</p>

      <p><a class="nav-link" href="#watchlist">the watchlist</a> is the
      automation: hand it rss feeds, wake up to new episodes, and hand the
      podcast feed that comes out the other end to any player.</p>

      <p><a class="nav-link" href="#library">the library</a> keeps every
      episode you ever made, each one with its making-of and full transcript.</p>

      <p><a class="nav-link" href="#settings">advanced settings</a> is the
      control room: the defaults for every episode, value for value splits,
      custom prompts, engine details. changes save instantly. to change one
      episode only, use "this episode" on the compose page instead.</p>
      <p><a class="nav-link" href="#agents">the agents page</a> connects
      your AI agent: an MCP server and an HTTP API, so an agent can make
      and fetch episodes for you, or set up a watchlist that keeps
      turning a feed into a podcast.</p>
    </section>

    <section id="dialogue" class="about-sec feature-box">
      <h2>Conversations that sound like people</h2>
      <p>Twenty styles, each with its own cast: a curious host and an expert, a
      narrator and a listener, a questioner who takes an answer apart. Every
      script is measured after it is written, who talks how much, how long the
      turns run, how often someone just says "huh". Where a host talks too much,
      only those few turns are rewritten; where the rhythm goes flat, the other
      host chimes in. The interjections the hosts come up with on their own stay.</p>
      <p class="deep-link-row mono">
        <a class="faq-link" href="#faq#natural-dialogue">→ Roles, rhythm and repairs in FAQ</a>
      </p>
    </section>

    <section id="clips" class="about-sec feature-box">
      <h2>Shareable audio clips and social highlights</h2>
      <p>Found a golden 30-second explanation or a funny debate turn? Highlight any
      text in the transcript or tap a speaker turn to slice a millisecond-accurate
      audio clip. You get an instant shareable web link, direct MP3 download, and a
      1-click Nostr quote note referencing the exact audio timestamp.</p>
      <p class="deep-link-row mono">
        <a class="faq-link" href="#faq#audio-clips">→ How audio clipping works in FAQ</a>
      </p>
    </section>

    <section id="bookmarks" class="about-sec feature-box">
      <h2>Nostr bookmarks to podcast pipeline</h2>
      <p>Save long-reads in your favorite Nostr app (Primal, Damus, Coracle, Amethyst)
      as bookmarks. Vozonda automatically detects your public reading queue and
      converts saved articles into your morning audio podcast episodes.</p>
      <p class="deep-link-row mono">
        <a class="faq-link" href="#faq#nostr-bookmarks">→ NIP-51 bookmark ingestion guide in FAQ</a>
      </p>
    </section>

    <section id="shows" class="about-sec feature-box">
      <h2>Personal podcast shows and private RSS feeds</h2>
      <p>Organize your favorite digests and episodes into custom show channels with
      dedicated cover art and Podcasting 2.0 RSS feeds. Subscribe from Apple Podcasts,
      Pocket Casts, or AntennaPod to listen on the go.</p>
      <p class="deep-link-row mono">
        <a class="faq-link" href="#faq#podcast-channels">→ Custom podcast RSS specification in FAQ</a>
      </p>
    </section>

    <section id="identity" class="about-sec">
      <h2>Sovereign identity and Value4Value</h2>
      <p>Vozonda is Nostr-native. Log in with your NIP-07 browser extension (like Alby
      or nos2x) or NIP-46 remote signer (Amber) to publish highlights (NIP-84),
      sync your bookmarks into episodes (NIP-51), and zap creators (NIP-57) directly
      over Lightning. No email, no password, no central database tracking you.</p>
      <p class="deep-link-row mono">
        <a class="faq-link" href="#faq#nostr-section">→ Nostr keys & zap setup in FAQ</a>
      </p>
    </section>

    <section id="engines" class="about-sec feature-box">
      <h2>Sovereign compute with private engine choice</h2>
      <p>No GPU? Kokoro-82M voices run on any CPU and are the default of the docker
      quickstart: English and 7 more languages. Piper renders German and the other
      languages Kokoro lacks. With an NVIDIA GPU, Qwen3-TTS acts far more expressively. Or plug in
      Voxtral with your own API key when you want laughter and breathing. You hold
      the keys. You choose the seam.</p>
      <p class="deep-link-row mono">
        <a class="faq-link" href="#faq#voice-engines">→ Voice engines & decision guide in FAQ</a>
      </p>
    </section>

    <section id="manifesto" class="about-sec">
      <h2>Why sovereign over proprietary platforms?</h2>
      <p>Because then it's truly yours. The dialogue runs on sovereign models without
      corporate surveillance or ad trackers. Nothing phones home because there is no
      telemetry; model weights are downloaded once, then it runs offline. No paywalls. No subscription lock-in.</p>

      <h2>It all fits on one box</h2>
      <p>A small workstation. Maybe a tiny VPS for the front door. That's it.
      No data centers. No growth team. No quarterly call about your listening
      habits. If it ever vanishes, you still have the code and the weights. Try
      getting that from a subscription.</p>

      <h2>Yes, it's free at the margin</h2>
      <p>Local inference costs nothing at the margin. Make one episode or ten
      thousand. Same price: zero. If an episode earned its keep, zap what felt
      fair. If nobody zaps, nothing changes. No pricing page. On purpose.</p>

      <h2>Full transparency</h2>
      <p>The voices argue about your text in the style you picked. A making-of
      section lays bare exactly how it was built: source, settings, render time.
      The transcript sits next to the audio so you can read along. You see the machine's
      work, not just its result.</p>
    </section>

    <p class="mono backline">
      <button class="link mono" onclick={onback}>← back</button>
      <a class="link mono" href="#faq">open technical FAQ manual →</a>
    </p>
  </div>
</div>

<style>
  .about-page {
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

  .about-content {
    max-width: var(--content-max-width);
    margin: 0 auto;
    padding: var(--space-6) var(--space-4);
  }

  .about-sec {
    scroll-margin-top: 60px;
    margin-bottom: var(--space-6);
  }

  .feature-box {
    border-left: 2px solid var(--green);
    padding-left: var(--space-4);
    margin: var(--space-5) 0;
  }

  .deep-link-row {
    margin-top: var(--space-2);
  }

  .faq-link {
    color: var(--green);
    font-size: calc(var(--ui-size) * 0.88);
    text-decoration: underline;
    text-decoration-color: color-mix(in srgb, var(--green) 40%, transparent);
    text-underline-offset: 3px;
  }

  .faq-link:hover {
    text-decoration-color: var(--green);
  }

  .hook {
    color: var(--lede-color, var(--ink-soft));
    font-size: var(--lede-size, clamp(0.8rem, 2.2vw, 1.12rem));
    margin: 0 0 1.6rem;
  }

  .nav-link {
    color: var(--ink);
    text-decoration: underline;
    text-decoration-color: var(--ink-soft);
    text-underline-offset: 3px;
  }

  .nav-link:hover {
    color: var(--green);
    text-decoration-color: var(--green);
  }

  h2 {
    font-size: var(--h2-size);
    margin: var(--h2-margin);
    font-weight: var(--h2-weight);
    line-height: var(--h2-line-height);
    text-wrap: var(--h2-text-wrap);
  }

  .backline {
    margin-top: var(--space-6);
    display: flex;
    justify-content: space-between;
    align-items: center;
    padding-top: var(--space-4);
    border-top: 1px solid var(--line);
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


  @media (max-width: 640px) {
    .sticky-breadcrumb {
      display: none;
    }
    .sticky-nav-inner {
      gap: var(--space-2);
    }
  }
</style>